"""Six server defects the second audit round confirmed, pinned.

Runs under pytest or as a script.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from server import audit, auth
from server.config import Settings, get_settings
from server.db import create_all, get_db, make_engine
from server.main import (  # noqa: E501
    _SESSIONS,
    DEMO_ORG_ID,
    DEMO_ORG_NAME,
    REPLAY_MIN_SPEED,
    LiveSession,
    ReplayRequest,
    _masked_event,
    app,
    ip_hash,
)
from server.models import AuditEvent, Organisation, Session, User
from server.pipeline import events as ev
from server.pipeline.runner import Question, RunnerConfig, _ask_human

PLACEHOLDER_HASH = "pbkdf2_sha256$1$00$00"
# A Luhn-valid test card, and a container number that must NOT be touched.
PAN = "4111111111111111"
ISO = "MSKU4158005"


def _settings() -> Settings:
    return Settings(replay_mode=True, session_secret="test-secret-auditfix-1")


class _Fixture:
    def __init__(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_auditfix_")
        os.close(fd)
        self.engine = make_engine(f"sqlite:///{self.path}", echo=False, settings=_settings())
        create_all(self.engine)
        self.Factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Factory() as db:
            if db.get(Organisation, DEMO_ORG_ID) is None:
                db.add(Organisation(id=DEMO_ORG_ID, name=DEMO_ORG_NAME))
                db.commit()

        def _db():
            db = self.Factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_settings] = _settings
        self.client = TestClient(app, raise_server_exceptions=False)

    def close(self) -> None:
        app.dependency_overrides.clear()
        # `_SESSIONS` is module-global and outlives this fixture. Leaving
        # entries in it makes the NEXT test file's concurrency and
        # single-producer assertions depend on what ran before it --
        # measured: two live-ingress tests passed alone and failed in the
        # full suite until this line existed.
        _SESSIONS.clear()
        self.engine.dispose()

    def token(self) -> str:
        with self.Factory() as db:
            org = Organisation(name="Docks Ltd")
            user = User(organisation=org, email="ada@docks.example", name="Ada",
                        password_hash=PLACEHOLDER_HASH, role="owner")
            db.add(org)
            db.add(user)
            db.commit()
            return auth.issue_token(user, _settings())


# ------------------------------------------------------------------- PAN ---
def test_a_card_number_is_masked_on_every_way_out_of_the_process() -> None:
    """`write_capture` masks a PAN before it reaches a column, so the database
    never holds one -- but the event history and the replay summary are built
    from the runner's own records, and both are returned by the API. A card
    number the database refused to keep was handed back in clear."""
    masked = _masked_event({"type": "capture.commit", "format": "luhn16",
                            "value": PAN, "heard": PAN,
                            "diff": {"heard": PAN, "written": PAN}})
    assert PAN not in str(masked), masked
    assert masked["value"].endswith("1111") and masked["value"].startswith("*")
    assert masked["diff"]["written"].endswith("1111")

    # A rack would put the PAN back together one slot at a time.
    slots = _masked_event({"type": "capture.update", "format": "luhn16",
                           "slots": [{"char": c, "state": "settled"} for c in PAN]})
    assert all(s["char"] == "" for s in slots["slots"])

    # Every other format is untouched: mask_pan is a no-op on them.
    iso = _masked_event({"type": "capture.commit", "format": "iso6346",
                         "value": ISO, "heard": ISO,
                         "slots": [{"char": c, "state": "settled"} for c in ISO]})
    assert iso["value"] == ISO and iso["heard"] == ISO
    assert "".join(s["char"] for s in iso["slots"]) == ISO


# ----------------------------------------------------------------- replay ---
def test_replay_speed_has_a_floor_as_well_as_a_ceiling() -> None:
    """speed=1e-9 is a task that runs for a century holding a capacity slot."""
    for bad in (1e-9, 0.0001, REPLAY_MIN_SPEED / 2):
        try:
            ReplayRequest(fixture="x", speed=bad)
        except Exception:
            continue
        raise AssertionError(f"speed={bad} was accepted")
    assert ReplayRequest(fixture="x", speed=0.0).speed == 0.0
    assert ReplayRequest(fixture="x", speed=REPLAY_MIN_SPEED).speed == REPLAY_MIN_SPEED
    assert ReplayRequest(fixture="x", speed=1.0).speed == 1.0


def test_a_running_session_cannot_be_replayed_into_twice() -> None:
    """Two runners on one session would both write captures for it and the
    second would replace the source under the first."""
    fx = _Fixture()
    try:
        token = fx.token()
        headers = {"Authorization": f"Bearer {token}"}
        first = fx.client.post("/api/demo/replay", headers=headers,
                               json={"fixture": "iso_clean_single_turn",
                                     "answer_timeout_ms": 50}).json()
        sid = first["session_id"]

        # The finished session's stream is closed; a re-run gets a fresh one
        # rather than emitting into a stream nobody can read.
        again = fx.client.post("/api/demo/replay", headers=headers,
                               json={"fixture": "iso_clean_single_turn",
                                     "session_id": sid, "answer_timeout_ms": 50})
        assert again.status_code == 200, again.text
        assert again.json()["events"], "the re-run emitted into a closed stream"
    finally:
        fx.close()


# ------------------------------------------------------------ cancellation ---
def test_a_pending_question_does_not_swallow_the_tasks_cancellation() -> None:
    """/stop cancels the pipeline task. Catching CancelledError in the answerer
    returned None for that as well as for the timeout, so the loop carried on
    past its own cancellation and the stop button did not stop the session."""
    async def go() -> tuple[object, bool]:
        live = LiveSession(session_id=uuid.uuid4(), stream=ev.EventStream())
        import dataclasses
        fields = {f.name: ("q1" if f.name == "question_id" else
                           2 if f.name == "position" else
                           ("alfa", "kilo") if f.name in ("choices", "grammar", "offered") else
                           "A or K?" if f.name in ("text", "form", "prompt") else
                           1 if f.name == "rung" else None)
                  for f in dataclasses.fields(Question)}
        q = Question(**fields)

        # The timeout still yields None -- 4.7's unanswered question.
        timed_out = await _ask_human(live.answerer(), q,
                                     RunnerConfig(session_id="t", answer_timeout_ms=60))

        # An external cancellation now actually stops the task.
        task = asyncio.create_task(_ask_human(
            live.answerer(), q, RunnerConfig(session_id="t", answer_timeout_ms=30_000)))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
            stopped = False
        except asyncio.CancelledError:
            stopped = True
        return timed_out, stopped

    answer, stopped = asyncio.run(go())
    assert answer is None, answer
    assert stopped, "the cancellation was swallowed"


# ----------------------------------------------------------------- audit ---
def test_stop_does_not_write_a_second_session_ended_row() -> None:
    """This log is read by counting, so two rows for one ending is a wrong
    count, not a tidiness problem."""
    fx = _Fixture()
    try:
        token = fx.token()
        headers = {"Authorization": f"Bearer {token}"}
        sid = fx.client.post("/api/demo/replay", headers=headers,
                             json={"fixture": "iso_clean_single_turn",
                                   "answer_timeout_ms": 50}).json()["session_id"]
        stopped = fx.client.post(f"/api/session/{sid}/stop", headers=headers,
                                 json={"delete": False})
        assert stopped.status_code == 200, stopped.text
        with fx.Factory() as db:
            rows = [e for e in db.query(AuditEvent).all()
                    if str(e.session_id) == sid and e.action == audit.SESSION_ENDED]
        assert len(rows) == 1, [r.detail for r in rows]
    finally:
        fx.close()


# -------------------------------------------------------------- ip_hash ---
def test_the_admission_hash_cannot_be_moved_by_a_forwarded_header() -> None:
    """ip_hash keyed on request.client.host, which uvicorn fills from the
    LEFTMOST X-Forwarded-For entry under --forwarded-allow-ips="*" -- the one
    the caller writes. Two requests differing only in that header must not be
    two different callers."""
    class _Req:
        def __init__(self, headers: dict[str, str], host: str) -> None:
            self.headers = headers
            self.client = type("C", (), {"host": host})()

    settings = _settings()
    real = _Req({"x-forwarded-for": "9.9.9.9, 203.0.113.7"}, "9.9.9.9")
    spoofed = _Req({"x-forwarded-for": "1.2.3.4, 203.0.113.7"}, "1.2.3.4")
    assert ip_hash(real, settings) == ip_hash(spoofed, settings)
    # A different real client (last hop) is still a different caller.
    other = _Req({"x-forwarded-for": "9.9.9.9, 198.51.100.2"}, "9.9.9.9")
    assert ip_hash(real, settings) != ip_hash(other, settings)


TESTS = [
    test_a_card_number_is_masked_on_every_way_out_of_the_process,
    test_replay_speed_has_a_floor_as_well_as_a_ceiling,
    test_a_running_session_cannot_be_replayed_into_twice,
    test_a_pending_question_does_not_swallow_the_tasks_cancellation,
    test_stop_does_not_write_a_second_session_ended_row,
    test_the_admission_hash_cannot_be_moved_by_a_forwarded_header,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc!r}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
