# test_persistence.py -- the persistence layer against a real SQLite file.
#
# A temp FILE and not :memory:, because three of the things under test are
# properties of the file-backed engine and vanish on an in-memory one: the
# foreign-key pragma, the WAL journal, and the audit triggers surviving a
# reconnect. Runs under pytest or as a script.
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from server import audit, models
from server.audit import AppendOnlyViolation, AuditPayloadRefused
from server.config import Settings
from server.db import create_all, make_engine, normalise_database_url, session_scope
from server.models import (
    AuditEvent,
    Capture,
    CataloguePart,
    ConfusionObservation,
    Organisation,
    OwnerCode,
    QuestionEvent,
    Session,
    utcnow,
)
from sqlalchemy.orm import sessionmaker


def _fresh_db() -> tuple[sa.Engine, sessionmaker]:
    fd, path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_test_")
    os.close(fd)
    engine = make_engine(f"sqlite:///{path}", echo=False,
                         settings=Settings(replay_mode=True))
    create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


# ------------------------------------------------------------------ config --
def test_url_normalisation() -> None:
    assert normalise_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalise_database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    # An explicit driver is a decision, not a mistake.
    assert normalise_database_url("postgresql+asyncpg://h/db") == "postgresql+asyncpg://h/db"
    assert normalise_database_url("sqlite:///./readback.db") == "sqlite:///./readback.db"


def test_settings_defaults_and_seam() -> None:
    st = Settings(assemblyai_api_key="")
    assert st.live_capture is False           # no key today
    assert st.consent_required is True
    assert st.session_cap_seconds == 150
    assert st.daily_budget_seconds == 120_000
    assert st.session_socket_seconds == 300
    assert st.budget_alarm_seconds == 72_000

    live = Settings(assemblyai_api_key="k-arrives-this-evening")
    assert live.live_capture is True          # the whole change, tonight
    # The key must not be reachable by printing the settings object.
    assert "k-arrives-this-evening" not in repr(live)
    assert "**********" in repr(live.assemblyai_api_key)
    assert Settings(assemblyai_api_key="k", replay_mode=True).live_capture is False

    for bad in (dict(consent_required=False),
                dict(daily_budget_seconds=10)):
        try:
            Settings(**bad)
        except Exception as exc:
            assert "consent" in str(exc) or "budget" in str(exc)
        else:
            raise AssertionError(f"Settings({bad}) should have been refused")


# ------------------------------------------------------------ the schema ----
def test_no_binary_and_no_tape_columns() -> None:
    models.assert_no_audio_or_tape_columns()

    md = sa.MetaData()
    sa.Table("bad_audio", md, sa.Column("pcm", sa.LargeBinary))
    try:
        models.assert_no_audio_or_tape_columns(md)
    except RuntimeError as exc:
        assert "binary" in str(exc)
    else:
        raise AssertionError("a LargeBinary column must fail the invariant")

    md2 = sa.MetaData()
    sa.Table("bad_tape", md2, sa.Column("transcript", sa.Text))
    try:
        models.assert_no_audio_or_tape_columns(md2)
    except RuntimeError as exc:
        assert "never-stored" in str(exc)
    else:
        raise AssertionError("a transcript column must fail the invariant")


def test_insert_one_of_each() -> None:
    engine, Factory = _fresh_db()
    with session_scope(Factory) as db:
        org = Organisation(name="Blue Star Line", daily_budget_seconds=None)
        db.add(org)
        db.flush()

        now = utcnow()
        sess = Session(
            organisation_id=org.id, consent_version="2026-09-01", consent_at=now,
            disclosure_played=True, channel="dual", source="replay", sockets=2,
            billed_seconds=94, confidence_regime="per_char", demo_mode=True,
            ip_hash="a" * 64, ip_hash_purge_after=now + timedelta(hours=24),
        )
        db.add(sess)
        db.flush()
        assert sess.charged_seconds == 188

        cap = Capture(
            session_id=sess.id, format_type="iso6346",
            heard_value="MSKU4198005", final_value="MSKU4158005",
            validated_by="check_digit", second_signal="prefix", status="committed",
            confidence_at_write=0.91, corrected=True, position_corrected=6,
            candidates_considered=[["MSKU4158005", 0.94], ["MSKU4198055", 0.04]],
            rung=0, questions_asked=0, silent=True, latency_ms=612,
        )
        db.add(cap)
        db.flush()

        q = QuestionEvent(
            session_id=sess.id, capture_id=cap.id, rung=3, spoken=True,
            position=3, form="alternative",
            question_text="Quick one -- right after Mike, Sierra, Kilo, was that Uniform or Juliett?",
            offered=["U", "J"], answered=True, answer_in_grammar=True,
            answer_char="U", resolution_ms=1480,
        )
        db.add(q)

        db.add(OwnerCode(code="MSK", owner="Maersk A/S", weight=0.081))
        db.add(CataloguePart(sku="BX-4471-A", description="Bearing housing",
                             rhyme_signature="EI-FFAI-A"))
        db.add(ConfusionObservation(heard="9", truth="5", n=3))

        audit.record(db, audit.CONSENT_GRANTED, organisation_id=org.id,
                     session_id=sess.id, actor="judge",
                     detail={"version": "2026-09-01", "checkbox": True})
        ev = audit.record(db, audit.CAPTURE_COMMITTED, organisation_id=org.id,
                          session_id=sess.id, capture_id=cap.id,
                          detail={"rung": 0, "silent": True, "edits": 1})
        assert ev.seq == 2

    with Factory() as db:
        counts = {
            m.__tablename__: db.scalar(sa.select(sa.func.count()).select_from(m.__table__))
            for m in (Organisation, Session, Capture, QuestionEvent,
                      OwnerCode, CataloguePart, ConfusionObservation, AuditEvent)
        }
        assert counts == {"organisation": 1, "session": 1, "capture": 1,
                          "question_event": 1, "owner_code": 1, "catalogue_part": 1,
                          "confusion_observation": 1, "audit_event": 2}, counts
        assert audit.gaps(db) == []
    engine.dispose()


def test_timestamps_come_back_utc_aware() -> None:
    """SQLite drops tzinfo. UtcDateTime is what stops dev diverging from prod."""
    engine, Factory = _fresh_db()
    with session_scope(Factory) as db:
        org = Organisation(name="t")
        db.add(org)
        db.flush()
        oid = org.id
    with Factory() as db:
        got = db.get(Organisation, oid)
        assert got is not None and got.created_at.tzinfo is not None
        assert got.created_at.utcoffset() == timedelta(0)
        assert (utcnow() - got.created_at) < timedelta(minutes=1)  # would raise if naive
    engine.dispose()


def test_schema_compiles_for_postgres() -> None:
    """The dev database is SQLite and production is Postgres, so render the DDL
    for the dialect that is never exercised locally until deploy day."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    pg = postgresql.dialect()
    ddl = "\n".join(str(CreateTable(t).compile(dialect=pg)) for t in models.Base.metadata.tables.values())
    assert "TIMESTAMP WITH TIME ZONE" in ddl
    assert "JSONB" in ddl
    assert "ck_capture_commit_needs_two_signals" in ddl
    idx = str(CreateIndex(
        next(i for i in Capture.__table__.indexes if i.name == "uq_capture_flag_once")
    ).compile(dialect=pg))
    assert "WHERE status = 'flagged'" in idx


def test_commit_needs_two_signals() -> None:
    """ARCH 3.10: no path from probably-right to a clean row -- in the database."""
    engine, Factory = _fresh_db()
    with session_scope(Factory) as db:
        org = Organisation(name="t")
        db.add(org)
        db.flush()
        sess = Session(organisation_id=org.id, consent_version="v",
                       consent_at=utcnow())
        db.add(sess)
        db.flush()
        sid = sess.id

    for kwargs, why in [
        (dict(validated_by="none", second_signal="prefix"), "no validation"),
        (dict(validated_by="check_digit", second_signal="none"), "no second signal"),
    ]:
        try:
            with session_scope(Factory) as db:
                db.add(Capture(session_id=sid, format_type="iso6346",
                               heard_value="CSQU3054383", final_value="CSQU3054383",
                               status="committed", **kwargs))
        except IntegrityError as exc:
            assert "ck_capture_commit_needs_two_signals" in str(exc)
        else:
            raise AssertionError(f"committed capture with {why} must be refused")

    # silent must mean rung 0 and zero questions.
    try:
        with session_scope(Factory) as db:
            db.add(Capture(session_id=sid, format_type="iso6346",
                           heard_value="CSQU3054383", final_value="CSQU3054383",
                           validated_by="check_digit", second_signal="prefix",
                           status="committed", silent=True, rung=3, questions_asked=1))
    except IntegrityError as exc:
        assert "ck_capture_silent_means_rung0" in str(exc)
    else:
        raise AssertionError("silent=True at rung 3 must be refused")
    engine.dispose()


def test_flag_at_most_once_per_string() -> None:
    """ARCH 3.10: 'At most once per distinct string per session. Twice is the
    deadlock.' Enforced by a partial unique index, not by the endpoint."""
    engine, Factory = _fresh_db()
    with session_scope(Factory) as db:
        org = Organisation(name="t")
        db.add(org)
        db.flush()
        sess = Session(organisation_id=org.id, consent_version="v", consent_at=utcnow())
        db.add(sess)
        db.flush()
        sid = sess.id

    def flag() -> None:
        with session_scope(Factory) as db:
            db.add(Capture(session_id=sid, format_type="iso6346",
                           heard_value="MSKU4198006", status="flagged",
                           flag_reason="checksum_invalid"))

    flag()
    try:
        flag()
    except IntegrityError as exc:
        # SQLite names the columns, Postgres names the index; both are the index.
        assert "UNIQUE" in str(exc).upper()
    else:
        raise AssertionError("the same string may not be flagged twice in a session")

    # ...and the index is genuinely partial: once the human resolves it, the same
    # string may still be captured cleanly. A plain unique constraint would have
    # blocked the resolution as well as the second flag.
    with session_scope(Factory) as db:
        db.add(Capture(session_id=sid, format_type="iso6346",
                       heard_value="MSKU4198006", final_value="MSKU4198005",
                       validated_by="check_digit", second_signal="prefix",
                       status="committed", rung=3, questions_asked=1, corrected=True))
    with Factory() as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(Capture.__table__)) == 2
    engine.dispose()


def test_candidates_capped_at_five() -> None:
    try:
        Capture(session_id=uuid.uuid4(), format_type="iso6346", heard_value="X",
                candidates_considered=[["a", 1]] * 6)
    except ValueError as exc:
        assert "top 5" in str(exc)
    else:
        raise AssertionError("candidates_considered must refuse more than five")


# --------------------------------------------------------- the audit log ----
def test_audit_rejects_mutation() -> None:
    engine, Factory = _fresh_db()
    with session_scope(Factory) as db:
        ev = audit.record(db, audit.SESSION_STARTED, actor="server",
                          detail={"sockets": 2})
        seq = ev.seq

    # 1. ORM update
    with Factory() as db:
        ev = db.get(AuditEvent, seq)
        ev.action = audit.SESSION_ENDED
        try:
            db.flush()
        except AppendOnlyViolation as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("ORM update on audit_event must be refused")
        db.rollback()

    # 2. ORM delete
    with Factory() as db:
        db.delete(db.get(AuditEvent, seq))
        try:
            db.flush()
        except AppendOnlyViolation:
            pass
        else:
            raise AssertionError("ORM delete on audit_event must be refused")
        db.rollback()

    # 3. raw SQL, which is the case the ORM guard cannot see
    for stmt in ("UPDATE audit_event SET action = 'session.ended'",
                 "DELETE FROM audit_event"):
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(stmt)
        except sa.exc.DatabaseError as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError(f"raw {stmt.split()[0]} on audit_event must be refused")

    # 4. still there, unchanged
    with Factory() as db:
        ev = db.get(AuditEvent, seq)
        assert ev is not None and ev.action == audit.SESSION_STARTED
        assert audit.count(db, audit.SESSION_STARTED) == 1
    engine.dispose()


def test_audit_refuses_unknown_actions_and_tape_payloads() -> None:
    engine, Factory = _fresh_db()
    with Factory() as db:
        for bad in ("session.strated", "capture.commited"):
            try:
                audit.record(db, bad)
            except ValueError as exc:
                assert "unknown audit action" in str(exc)
            else:
                raise AssertionError(f"{bad} must be refused")

        try:
            audit.record(db, audit.CAPTURE_COMMITTED,
                         detail={"transcript": "the container is mike sierra kilo uniform"})
        except AuditPayloadRefused as exc:
            assert "never stores" in str(exc)
        else:
            raise AssertionError("a transcript key must be refused, not scrubbed")

        try:
            audit.record(db, audit.CAPTURE_COMMITTED, detail={"notes": "x" * 5000})
        except AuditPayloadRefused as exc:
            assert "limit" in str(exc)
        else:
            raise AssertionError("an oversized detail must be refused")
        db.rollback()
    engine.dispose()


def test_audit_scrubs_card_numbers() -> None:
    # 4539578763621486 is the Luhn-valid vector from FINDINGS 1.
    dirty = {"note": "caller read 4539578763621486 aloud",
             "spaced": "4539 5787 6362 1486",
             "keep": "container CSQU3054383 and NHS 9434765919"}
    clean = audit.scrub(dirty)
    assert "4539578763621486" not in clean["note"]
    assert "[REDACTED:PAN]" in clean["note"]
    assert "[REDACTED:PAN]" in clean["spaced"]
    # NHS is 10 digits and a container number is not all-digits: both survive.
    assert clean["keep"] == dirty["keep"]

    engine, Factory = _fresh_db()
    with session_scope(Factory) as db:
        ev = audit.record(db, audit.CAPTURE_FLAGGED,
                          detail={"value": "4539578763621486", "reason": "checksum_invalid"})
        assert ev.detail is not None and ev.detail["value"] == "[REDACTED:PAN]"
    engine.dispose()


def test_delete_session_cascades_but_audit_survives() -> None:
    """ARCH 3.12's stop-and-delete visibly deletes; the record of it does not."""
    engine, Factory = _fresh_db()
    with session_scope(Factory) as db:
        org = Organisation(name="t")
        db.add(org)
        db.flush()
        sess = Session(organisation_id=org.id, consent_version="v", consent_at=utcnow())
        db.add(sess)
        db.flush()
        cap = Capture(session_id=sess.id, format_type="nhs", heard_value="9434765919",
                      final_value="9434765919", validated_by="check_digit",
                      second_signal="carrier", status="committed")
        db.add(cap)
        db.flush()
        db.add(QuestionEvent(session_id=sess.id, capture_id=cap.id, position=2,
                             form="confirm", question_text="after nine four three, four?"))
        audit.record(db, audit.SESSION_DELETED, session_id=sess.id, actor="judge")
        sid = sess.id

    with session_scope(Factory) as db:
        db.delete(db.get(Session, sid))

    with Factory() as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(Capture.__table__)) == 0
        assert db.scalar(sa.select(sa.func.count()).select_from(QuestionEvent.__table__)) == 0
        rows = audit.events(db, session_id=sid)
        assert len(rows) == 1 and rows[0].action == audit.SESSION_DELETED
    engine.dispose()


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    failed = 0
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 -- this is the harness
            failed += 1
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok   {fn.__name__}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
