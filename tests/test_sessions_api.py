# test_sessions_api.py -- GET /api/sessions, the endpoint the dashboard reads.
#
# The test that matters here is the cross-organisation one. `capture` carries no
# organisation of its own; the only thing between one tenant and another's
# container numbers is a WHERE clause on a joined table, and a WHERE clause is
# exactly the kind of thing a later refactor drops without any test noticing.
# So two organisations are built, both filled, and each one's token is asked for
# the other's rows in three different ways: plainly, through a cursor that points
# at a foreign row, and by searching the raw response body for the foreign
# identifier as a string.
#
# Deterministic and offline. No network, no clock dependence -- every capture is
# written with an explicit created_at -- and no signup: users are inserted
# directly and tokens are minted with auth.issue_token, so PBKDF2 is never paid
# for and the signup rate limiter is never touched.
#
# Runs under pytest or as a script.
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from server import auth
from server.config import Settings, get_settings
from server.db import create_all, get_db, make_engine
from server.main import CAPTURES_LIMIT_DEFAULT, CAPTURES_LIMIT_MAX, app
from server.models import FORBIDDEN_NAME, Capture, Organisation, Session, User

# The shape this endpoint ships. web/src/lib/api.ts declares exactly these keys;
# asserting the set rather than a few members means adding a field to the server
# without adding it to the client fails here instead of in a browser.
ROW_KEYS = {
    "id", "session_id", "format", "value", "heard", "final", "state", "status",
    "silent", "repaired", "repaired_position", "questions", "ms_to_settle",
    "source", "created_at",
}

# THREE KEYS WERE ADDED, AND THIS TEST IS WHY THEY WERE ADDED CORRECTLY.
#
# The endpoint shipped without them and the dashboard printed "no identifiers
# captured yet" over thirteen real rows: DashboardParts.readCapture requires
# `session_id` and returned null without it, so every row was dropped before it
# reached the screen. Dashboard.tsx's own comment calls printing that string
# unknowingly "the same failure as a fabricated row wearing a politer face".
#
#   session_id  the record view groups by session and cannot invent the link.
#               Not a secret: /api/session/start already returns one and it sits
#               in a URL, and reading rows back is still organisation-scoped.
#   heard/final `value` collapses the two, with `state` saying which it is. That
#               is enough to print an identifier and not enough to draw one: a
#               repaired slot shows the superseded character ABOVE the one that
#               replaced it, and that difference is the product.

# A verifier-shaped string that verifies nothing. No test in this file signs in
# with a password, and a real hash would cost 600,000 iterations per user.
PLACEHOLDER_HASH = "pbkdf2_sha256$1$00$00"

T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


def _settings() -> Settings:
    return Settings(replay_mode=True, session_secret="test-secret-sessions-1")


class _Fixture:
    """A client wired to a fresh database and a known token secret."""

    def __init__(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_sessions_")
        os.close(fd)
        self.engine = make_engine(f"sqlite:///{self.path}", echo=False,
                                  settings=_settings())
        create_all(self.engine)
        self.Factory = sessionmaker(bind=self.engine, expire_on_commit=False)

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
        self.engine.dispose()

    # -- building a tenant ---------------------------------------------------
    def organisation(self, name: str, email: str) -> tuple[uuid.UUID, str]:
        """An organisation, its owner, and a bearer token for that owner."""
        with self.Factory() as db:
            org = Organisation(name=name)
            user = User(organisation=org, email=email, name=name.split()[0],
                        password_hash=PLACEHOLDER_HASH, role="owner")
            db.add(org)
            db.add(user)
            db.commit()
            token = auth.issue_token(user, _settings())
            return org.id, token

    def session_row(self, org_id: uuid.UUID, *, source: str = "replay") -> uuid.UUID:
        with self.Factory() as db:
            row = Session(organisation_id=org_id, consent_version="2026-08-01",
                          consent_at=T0, disclosure_played=True, source=source,
                          started_at=T0)
            db.add(row)
            db.commit()
            return row.id

    def capture(self, session_id: uuid.UUID, value: str, *, at: datetime,
                status: str = "committed", silent: bool = True,
                corrected: bool = False, position: int | None = None,
                questions: int = 0, handed_over: bool = False,
                latency_ms: int | None = 800, rung: int = 0,
                fmt: str = "ISO6346", capture_id: uuid.UUID | None = None) -> uuid.UUID:
        """One capture, written straight to the table.

        The CHECK constraints in models.py police the combinations -- committed
        needs two signals and a final value, silent needs rung 0 and no
        questions -- so a row that gets written here is a row the pipeline could
        have written.
        """
        with self.Factory() as db:
            row = Capture(
                id=capture_id or uuid.uuid4(),
                session_id=session_id,
                created_at=at,
                format_type=fmt,
                heard_value=value,
                final_value=value if status == "committed" or corrected else None,
                validated_by="check_digit" if status == "committed" else "none",
                second_signal="carrier" if status == "committed" else "none",
                status=status,
                corrected=corrected,
                position_corrected=position,
                rung=rung,
                questions_asked=questions,
                silent=silent,
                handed_over=handed_over,
                latency_ms=latency_ms,
            )
            db.add(row)
            db.commit()
            return row.id

    def get(self, token: str | None, **params) -> object:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.get("/api/sessions", params=params, headers=headers)


def _two_organisations(fx: _Fixture) -> dict[str, object]:
    """Docks Ltd and Rival Freight, three captures each, interleaved in time so
    a bug that ignores the tenant and takes the newest rows returns a mixture
    rather than something that could pass by luck."""
    docks_org, docks_token = fx.organisation("Docks Ltd", "ada@docks.example")
    rival_org, rival_token = fx.organisation("Rival Freight", "eve@rival.example")
    docks_session = fx.session_row(docks_org)
    rival_session = fx.session_row(rival_org)

    docks_values = ["MSKU4158005", "TGHU7654321", "CSQU3054383"]
    rival_values = ["HLXU1234567", "OOLU9876543", "TEMU2222222"]
    docks_ids, rival_ids = [], []
    for i in range(3):
        docks_ids.append(fx.capture(docks_session, docks_values[i],
                                    at=T0 + timedelta(seconds=2 * i)))
        rival_ids.append(fx.capture(rival_session, rival_values[i],
                                    at=T0 + timedelta(seconds=2 * i + 1)))
    return {
        "docks_token": docks_token, "rival_token": rival_token,
        "docks_ids": docks_ids, "rival_ids": rival_ids,
        "docks_values": docks_values, "rival_values": rival_values,
    }


# ------------------------------------------------------- the one that matters --
def test_captures_are_scoped_to_the_signed_in_organisation() -> None:
    """Two tenants, and neither can see the other's identifiers by any route.

    Checked three ways because they fail differently: the plain list is the
    WHERE clause, the foreign cursor is the pagination path (a keyset built from
    another tenant's row must not become a way into their pages), and the
    substring search over the raw body catches a leak through some field nobody
    thought to assert.
    """
    fx = _Fixture()
    try:
        w = _two_organisations(fx)

        docks = fx.get(w["docks_token"])
        assert docks.status_code == 200, docks.text
        rows = docks.json()
        assert isinstance(rows, list) and len(rows) == 3, rows
        assert {r["id"] for r in rows} == {str(i) for i in w["docks_ids"]}
        assert {r["value"] for r in rows} == set(w["docks_values"])

        rival = fx.get(w["rival_token"])
        assert rival.status_code == 200, rival.text
        assert {r["id"] for r in rival.json()} == {str(i) for i in w["rival_ids"]}

        # Not one character of the other tenant's data anywhere in the body.
        for value in w["rival_values"]:
            assert value not in docks.text, f"{value} leaked into the other org"
        for row_id in w["rival_ids"]:
            assert str(row_id) not in docks.text

        # A cursor pointing at a foreign row is still answered inside the
        # caller's own tenancy: it filters, it does not authorise.
        leaked = fx.get(w["docks_token"],
                        before=(T0 + timedelta(seconds=99)).isoformat(),
                        before_id=str(w["rival_ids"][0]))
        assert leaked.status_code == 200, leaked.text
        assert {r["id"] for r in leaked.json()} == {str(i) for i in w["docks_ids"]}
        for value in w["rival_values"]:
            assert value not in leaked.text
    finally:
        fx.close()


def test_a_token_is_required_and_the_401_is_flat() -> None:
    """No token, a forged one and one signed with somebody else's secret all get
    the same 401 with `error` and `message` at the TOP level -- the client reads
    them there and a wrapped {"detail": ...} shows a generic failure."""
    fx = _Fixture()
    try:
        _two_organisations(fx)

        anonymous = fx.get(None)
        assert anonymous.status_code == 401, anonymous.text
        body = anonymous.json()
        assert body.get("error") == "unauthorized", body
        assert isinstance(body.get("message"), str) and body["message"]
        assert "detail" not in body, "the error body must not be wrapped"

        assert fx.get("rb1.not.a-token").status_code == 401

        foreign = Settings(replay_mode=True, session_secret="a-different-secret")
        with fx.Factory() as db:
            user = db.query(User).first()
            assert user is not None
            assert fx.get(auth.issue_token(user, foreign)).status_code == 401
    finally:
        fx.close()


# --------------------------------------------------------------------- shape --
def test_row_shape_is_exactly_the_client_contract() -> None:
    fx = _Fixture()
    try:
        org, token = fx.organisation("Docks Ltd", "ada@docks.example")
        session_id = fx.session_row(org, source="replay")
        fx.capture(session_id, "MSKU4158005", at=T0, corrected=True, position=3,
                   latency_ms=1234)

        r = fx.get(token)
        assert r.status_code == 200, r.text
        row = r.json()[0]
        assert set(row) == ROW_KEYS, sorted(set(row) ^ ROW_KEYS)
        assert row["format"] == "ISO6346"
        assert row["value"] == "MSKU4158005"
        assert row["silent"] is True
        assert row["repaired"] is True
        assert row["repaired_position"] == 3
        assert row["questions"] == 0
        assert row["status"] == "committed"
        assert row["ms_to_settle"] == 1234
        assert row["source"] == "replay"
        assert row["session_id"] == str(session_id)
        # A repaired row must carry both halves, or the rack cannot show what
        # changed -- which is the one thing this product exists to show.
        assert row["final"] == "MSKU4158005"
        assert row["heard"] is not None
        # Parseable by Date(), and carrying its zone: a naive timestamp would be
        # read as local time by the browser and drift the whole rack.
        assert datetime.fromisoformat(row["created_at"]).tzinfo is not None
    finally:
        fx.close()


def test_no_field_could_hold_the_conversation() -> None:
    """The same vocabulary models.py refuses at the schema, applied to the wire.

    A column named `transcript` fails at import; a *response key* named
    `transcript` would not, and this endpoint is where somebody assembling a
    nicer dashboard would add one. There is also no confidence number: this
    system says it is unsure by asking, not by printing a percentage.
    """
    fx = _Fixture()
    try:
        org, token = fx.organisation("Docks Ltd", "ada@docks.example")
        session_id = fx.session_row(org)
        fx.capture(session_id, "MSKU4158005", at=T0)

        row = fx.get(token).json()[0]
        for key in row:
            assert not FORBIDDEN_NAME.search(key), f"{key} names a stored conversation"
            assert "confid" not in key.lower(), f"{key} puts a confidence on screen"
            assert "candidate" not in key.lower(), f"{key} exposes the reasoning"
    finally:
        fx.close()


def test_state_vocabulary_is_derived_from_the_row() -> None:
    """Five display states off three database statuses, and the narrow one is
    the point: --green means QUIETLY repaired, so a repair that had to ask is
    `settled` with `repaired` still true, not `repaired`."""
    fx = _Fixture()
    try:
        org, token = fx.organisation("Docks Ltd", "ada@docks.example")
        session_id = fx.session_row(org)
        cases = [
            ("settled", dict(status="committed")),
            ("repaired", dict(status="committed", corrected=True, position=2)),
            # Repaired, but it asked. Not quiet, so not green.
            ("settled", dict(status="committed", corrected=True, position=2,
                             silent=False, questions=1, rung=3)),
            ("flagged", dict(status="flagged", silent=False, questions=1, rung=3)),
            ("asking", dict(status="unverified", silent=False, handed_over=True,
                            questions=1, rung=3)),
            ("heard", dict(status="unverified", silent=False)),
        ]
        wanted = {}
        for i, (state, kw) in enumerate(cases):
            row_id = fx.capture(session_id, f"MSKU415800{i}",
                                at=T0 + timedelta(seconds=i), **kw)
            wanted[str(row_id)] = state

        rows = fx.get(token).json()
        assert len(rows) == len(cases)
        got = {r["id"]: r["state"] for r in rows}
        assert got == wanted, got

        by_state = {r["state"]: r for r in rows}
        assert by_state["repaired"]["silent"] is True
        assert by_state["settled"]["state"] != "repaired"
    finally:
        fx.close()


# ---------------------------------------------------------------- pagination --
def test_newest_first_and_the_page_is_bounded() -> None:
    fx = _Fixture()
    try:
        org, token = fx.organisation("Docks Ltd", "ada@docks.example")
        session_id = fx.session_row(org)
        for i in range(7):
            fx.capture(session_id, f"MSKU415800{i}", at=T0 + timedelta(seconds=i))

        rows = fx.get(token).json()
        stamps = [r["created_at"] for r in rows]
        assert stamps == sorted(stamps, reverse=True), stamps

        assert len(fx.get(token, limit=3).json()) == 3
        assert len(fx.get(token, limit=100).json()) == 7
        assert CAPTURES_LIMIT_DEFAULT == 50 and CAPTURES_LIMIT_MAX == 200
    finally:
        fx.close()


def test_fifty_thousand_captures_cannot_be_asked_for_at_once() -> None:
    """The requirement, stated as a test. There is no limit value and no absent
    limit that returns everything: the default is bounded and anything above the
    ceiling is refused rather than quietly clamped."""
    fx = _Fixture()
    try:
        org, token = fx.organisation("Docks Ltd", "ada@docks.example")
        session_id = fx.session_row(org)
        # 220 rows: more than the ceiling, so "bounded" is measured rather than
        # asserted against a table too small to prove it.
        for i in range(220):
            fx.capture(session_id, f"MSKU{i:07d}", at=T0 + timedelta(seconds=i))

        assert len(fx.get(token).json()) == CAPTURES_LIMIT_DEFAULT
        assert len(fx.get(token, limit=CAPTURES_LIMIT_MAX).json()) == CAPTURES_LIMIT_MAX

        for bad in ("50000", "201", "0", "-1", "abc", "1.5"):
            r = fx.get(token, limit=bad)
            assert r.status_code == 400, f"limit={bad} -> {r.status_code}"
            body = r.json()
            assert body.get("error") == "invalid_limit", body
            assert isinstance(body.get("message"), str) and body["message"]
            assert "detail" not in body, "the error body must not be wrapped"
    finally:
        fx.close()


def test_the_cursor_walks_every_row_once_including_a_tie() -> None:
    """Keyset paging, checked against the case that breaks OFFSET and breaks a
    timestamp-only cursor: two captures written inside the same instant."""
    fx = _Fixture()
    try:
        org, token = fx.organisation("Docks Ltd", "ada@docks.example")
        session_id = fx.session_row(org)
        expected = set()
        for i in range(5):
            expected.add(str(fx.capture(session_id, f"MSKU415800{i}",
                                        at=T0 + timedelta(seconds=i))))
        # Two rows sharing one created_at, exactly.
        tie = T0 + timedelta(seconds=9)
        for value in ("TGHU7654321", "CSQU3054383"):
            expected.add(str(fx.capture(session_id, value, at=tie)))

        seen: list[str] = []
        cursor: dict[str, str] = {}
        for _ in range(20):
            page = fx.get(token, limit=1, **cursor).json()
            if not page:
                break
            seen.append(page[-1]["id"])
            cursor = {"before": page[-1]["created_at"], "before_id": page[-1]["id"]}

        assert len(seen) == len(set(seen)), "a row was served twice"
        assert set(seen) == expected, "paging did not cover every row"
    finally:
        fx.close()


def test_a_half_cursor_and_a_malformed_one_are_flat_400s() -> None:
    fx = _Fixture()
    try:
        org, token = fx.organisation("Docks Ltd", "ada@docks.example")
        fx.capture(fx.session_row(org), "MSKU4158005", at=T0)

        for params in ({"before": T0.isoformat()},
                       {"before_id": str(uuid.uuid4())},
                       {"before": "yesterday", "before_id": str(uuid.uuid4())},
                       {"before": T0.isoformat(), "before_id": "not-a-uuid"}):
            r = fx.get(token, **params)
            assert r.status_code == 400, f"{params} -> {r.status_code} {r.text}"
            body = r.json()
            assert body.get("error") == "invalid_cursor", body
            assert isinstance(body.get("message"), str) and body["message"]
            assert "detail" not in body

        # The JavaScript spelling of an instant. Date#toISOString ends in Z and
        # fromisoformat only learned to read it in 3.11.
        ok = fx.get(token, before="2026-09-01T12:00:00.000Z",
                    before_id=str(uuid.uuid4()))
        assert ok.status_code == 200, ok.text
    finally:
        fx.close()


TESTS = [
    test_captures_are_scoped_to_the_signed_in_organisation,
    test_a_token_is_required_and_the_401_is_flat,
    test_row_shape_is_exactly_the_client_contract,
    test_no_field_could_hold_the_conversation,
    test_state_vocabulary_is_derived_from_the_row,
    test_newest_first_and_the_page_is_bounded,
    test_fifty_thousand_captures_cannot_be_asked_for_at_once,
    test_the_cursor_walks_every_row_once_including_a_tie,
    test_a_half_cursor_and_a_malformed_one_are_flat_400s,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001 -- a script runner reports, not raises
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
