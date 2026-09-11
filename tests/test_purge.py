"""ARCH 3.12's auto-purge, which nothing implemented until the audit said so.

config.py claimed "states a 24-hour auto-purge and implements it" and carried
four windows; models.py carried the same numbers again as RETENTION attributes.
Neither deleted a row.

Runs under pytest or as a script.
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from server import audit
from server.config import Settings
from server.db import create_all, make_engine
from server.models import AuditEvent, Capture, Organisation, QuestionEvent, Session
from server.purge import purge

NOW = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)


def _settings() -> Settings:
    return Settings(replay_mode=True, session_secret="test-secret-purge-1")


class _Fixture:
    def __init__(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_purge_")
        os.close(fd)
        self.engine = make_engine(f"sqlite:///{self.path}", echo=False, settings=_settings())
        create_all(self.engine)
        self.Factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Factory() as db:
            org = Organisation(name="Docks Ltd")
            db.add(org)
            db.commit()
            self.org_id = org.id

    def close(self) -> None:
        self.engine.dispose()

    def session(self, *, age_days: float, demo: bool = False,
                ip: str | None = "cafebabe") -> uuid.UUID:
        started = NOW - timedelta(days=age_days)
        with self.Factory() as db:
            # models.py enforces the pairing: a hash without a deadline is an
            # address kept forever by accident, so the row carries its own.
            row = Session(organisation_id=self.org_id, consent_version="2026-08-01",
                          consent_at=NOW, disclosure_played=True, source="replay",
                          started_at=started, demo_mode=demo, ip_hash=ip,
                          ip_hash_purge_after=(started + timedelta(hours=24)) if ip else None)
            db.add(row)
            db.commit()
            return row.id

    def capture(self, session_id: uuid.UUID, *, age_days: float) -> uuid.UUID:
        with self.Factory() as db:
            row = Capture(session_id=session_id, created_at=NOW - timedelta(days=age_days),
                          format_type="ISO6346", heard_value="MSKU4158005",
                          final_value="MSKU4158005", validated_by="check_digit",
                          second_signal="carrier", status="committed", silent=True,
                          rung=0, questions_asked=0)
            db.add(row)
            db.commit()
            return row.id

    def question(self, session_id: uuid.UUID, capture_id: uuid.UUID,
                 *, age_days: float) -> None:
        with self.Factory() as db:
            db.add(QuestionEvent(session_id=session_id, capture_id=capture_id,
                                 asked_at=NOW - timedelta(days=age_days),
                                 # Spoken means rung 3 -- the agent interrupted.
                                 position=2, form="alternative", rung=3, spoken=True,
                                 question_text="Was that Alfa or Kilo?",
                                 # An unanswered question produced no character,
                                 # and models.py refuses a row that says it did.
                                 answered=False, answer_in_grammar=None))
            db.commit()

    def counts(self) -> dict[str, int]:
        with self.Factory() as db:
            return {
                "sessions": len(list(db.scalars(select(Session.id)))),
                "captures": len(list(db.scalars(select(Capture.id)))),
                "questions": len(list(db.scalars(select(QuestionEvent.id)))),
                "with_ip": len([x for x in db.scalars(select(Session.ip_hash)) if x]),
            }


def test_each_window_removes_what_is_past_it_and_nothing_else() -> None:
    fx = _Fixture()
    try:
        # Inside every window.
        fresh = fx.session(age_days=0.1)
        fresh_cap = fx.capture(fresh, age_days=0.1)
        fx.question(fresh, fresh_cap, age_days=0.1)
        # Past its own window, one per rule.
        old_ip = fx.session(age_days=2)                      # ip_hash: 24 h
        old_cap_session = fx.session(age_days=0.1)
        old_cap = fx.capture(old_cap_session, age_days=40)    # capture: 30 d
        old_q_cap = fx.capture(old_cap_session, age_days=0.1)
        fx.question(old_cap_session, old_q_cap, age_days=10)  # question: 7 d
        stale_demo = fx.session(age_days=3, demo=True)        # demo: 24 h
        fx.capture(stale_demo, age_days=0.1)

        before = fx.counts()
        assert before == {"sessions": 4, "captures": 4, "questions": 2, "with_ip": 4}

        with fx.Factory() as db:
            counts = purge(db, _settings(), now=NOW)

        after = fx.counts()
        # The stale demo session took its own capture with it.
        assert after["sessions"] == 3, after
        assert after["captures"] == 2, after       # 40-day one and the demo's
        assert after["questions"] == 1, after      # the 10-day one
        # Two sessions kept their hash: the two started within 24 h.
        assert after["with_ip"] == 2, after

        assert counts.captures == 1 and counts.questions == 1
        assert counts.demo_sessions == 1 and counts.ip_hashes == 2

        # The fresh rows are all still there.
        with fx.Factory() as db:
            assert db.get(Capture, fresh_cap) is not None
            assert db.get(Session, fresh) is not None
    finally:
        fx.close()


def test_a_sweep_that_removed_something_leaves_exactly_one_audit_row() -> None:
    fx = _Fixture()
    try:
        sid = fx.session(age_days=0.1)
        fx.capture(sid, age_days=40)
        with fx.Factory() as db:
            purge(db, _settings(), now=NOW)
        with fx.Factory() as db:
            rows = [e for e in db.scalars(select(AuditEvent))
                    if e.action == audit.DATA_PURGED]
        assert len(rows) == 1, rows
        assert rows[0].detail["captures"] == 1
        assert rows[0].actor == "system"
    finally:
        fx.close()


def test_a_sweep_with_nothing_to_do_writes_nothing() -> None:
    """A log read by counting must not fill with rows saying "I did nothing"."""
    fx = _Fixture()
    try:
        sid = fx.session(age_days=0.1)
        fx.capture(sid, age_days=0.1)
        with fx.Factory() as db:
            counts = purge(db, _settings(), now=NOW)
        assert counts.total == 0
        with fx.Factory() as db:
            assert [e for e in db.scalars(select(AuditEvent))
                    if e.action == audit.DATA_PURGED] == []
    finally:
        fx.close()


TESTS = [
    test_each_window_removes_what_is_past_it_and_nothing_else,
    test_a_sweep_that_removed_something_leaves_exactly_one_audit_row,
    test_a_sweep_with_nothing_to_do_writes_nothing,
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
