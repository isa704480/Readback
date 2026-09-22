# models.py -- the persistence schema. ARCH 3.9, plus the parts of ARCH 3.12
# that this file is required to make structurally impossible rather than merely
# undone. Two invariants are enforced by code at the bottom of this module and
# will fail at import, not at review:
#
#   1. no column in this schema can hold raw audio
#   2. no column in this schema can hold the conversation around an identifier
#
# Both are checked over the metadata, so they also police tables added later by
# someone who never read this comment. That is the point of doing it this way.
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Final

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DDL,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates
from sqlalchemy.types import TypeDecorator

# JSON everywhere, JSONB where it exists. ARCH 3.9 writes JSONB; SQLite in dev
# has no such type and the variant keeps one model definition serving both.
JSONVariant = JSON().with_variant(JSONB, "postgresql")

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator[datetime]):
    """UTC-aware going in and coming out, on every dialect.

    Postgres TIMESTAMPTZ round-trips tzinfo. SQLite stores a naive string and
    hands back a naive datetime, so `session.started_at < utcnow()` works in
    production and raises "can't compare offset-naive and offset-aware
    datetimes" in dev -- found at the worst moment, in the purge job or the
    nightly reconciliation. Normalising both ends here costs one function call
    and removes the whole class of difference.

    A naive value on the way in is assumed UTC rather than rejected. It is a bug
    at the call site either way, but this type sits under the billing ledger and
    the consent record, and losing one of those rows over a missing tzinfo is a
    worse failure than recording it against the assumption that matches
    utcnow(), which is where every timestamp in this system comes from.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# Python-side defaults rather than func.now(): SQLite's CURRENT_TIMESTAMP is a
# naive UTC string and Postgres's now() is transaction-start time, so the two
# dialects disagree about both the type and the instant, and a reconciliation
# comparing them would be comparing two different clocks.
TS = UtcDateTime()


class Base(DeclarativeBase):
    pass


# ------------------------------------------------------------------ tenant --
class Organisation(Base):
    """The payer. Budget is metered here because ARCH 3.11's ceiling is a spend
    ceiling and spend belongs to whoever is being charged."""

    __tablename__ = "organisation"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # NULL means "use Settings.daily_budget_seconds". The override exists because
    # the kill switch has to be per-payer: one tenant burning the day's seconds
    # must not drop every other tenant into replay mode.
    daily_budget_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )
    users: Mapped[list["User"]] = relationship(
        back_populates="organisation", cascade="all, delete-orphan"
    )


# -------------------------------------------------------------------- user --
# "One account per company. Everyone else joins by invitation." -- the signup
# screen's own promise, and the reason a user hangs off an organisation rather
# than the other way round. The first person to sign up for a company creates
# it and owns it; everyone after arrives by invitation and is a member.
ROLES: Final = ("owner", "member")


class User(Base):
    """A person who can sign in and look at what their company captured.

    NOT ON THIS TABLE, AND WHY. No password, ever -- `password_hash` holds a
    PBKDF2-HMAC-SHA256 verifier in the printable `algo$iterations$salt$hash`
    form, which is a string and not bytes on purpose: the binary guard at the
    foot of this module would reject a bytes column, and it is right to, because
    a column that can hold bytes is a column somebody will eventually put
    something else in.

    No security questions, no password hints, no "previous passwords" list. A
    hint is a plaintext clue to a credential and a history table is a set of
    old credentials to steal; neither earns its place in a system whose recovery
    story is "the owner re-invites you".

    Email is stored lowercased and uniquely indexed. Case-folding at write time
    rather than at read time means the uniqueness constraint is the one doing
    the work, so `A@x.com` cannot become a second account for `a@x.com` on a
    database that happens to collate case-sensitively.
    """

    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint(f"role IN {ROLES}", name="ck_user_role"),
        CheckConstraint("email = lower(email)", name="ck_user_email_lower"),
        Index("ix_user_org", "organisation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False
    )
    # 320 is the RFC 5321 maximum. Unique across the whole system, not per
    # organisation: an address identifies one person, and letting the same
    # address exist twice would make "which company am I signing in to?" a
    # question the login form cannot answer.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="owner")
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)
    # Nullable because "never signed in" is a real state and 1970 is not it.
    last_login_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    organisation: Mapped["Organisation"] = relationship(back_populates="users")

    @validates("email")
    def _fold_email(self, _key: str, value: str) -> str:
        """The one place an address is normalised, so the unique index cannot be
        sidestepped by capitalisation."""
        return (value or "").strip().lower()


# ----------------------------------------------------------------- session --
CHANNELS: Final = ("clean", "phone", "dual")
SOURCES: Final = ("live", "replay")
REGIMES: Final = ("per_char", "flat", "block")
# "complete" was added when the runner landed: a session whose transcript source
# reached its end -- a recording that finished, a socket the far side closed --
# is a real outcome and none of the others describes it. Folding it into
# "inactivity" would make "how many sessions timed out" wrong by exactly the
# number of demo replays, which is most of them.
END_REASONS: Final = ("cap", "inactivity", "user", "budget", "error", "open",
                      "complete")


class Session(Base):
    """One listening session: consent, the billed clock, the money.

    NOT ON THIS TABLE, AND WHY. The rolling tape (ARCH 3.4) exists in memory for
    the life of the session and is destroyed with it. There is deliberately no
    transcript, turn, utterance or context column here, and none may be added:
    a session row and its captures say which identifiers were written and what
    they cost, and say nothing whatever about the conversation they came out of.
    Reconstructing the call from this schema is not disallowed by policy, it is
    unsupported by the columns.

    The row is created by the consent gate, not by the socket. That is why
    consent_version, consent_at and disclosure_played are NOT NULL: a session
    that exists is a session that consented, and there is no ordering in which
    audio is captured against a session row that does not yet record consent.
    """

    __tablename__ = "session"
    RETENTION: Final = timedelta(days=30)          # counters only; see purge notes
    IP_HASH_RETENTION: Final = timedelta(hours=24)  # ARCH 3.9

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )

    started_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    end_reason: Mapped[str] = mapped_column(String(16), nullable=False, default="open")

    # Termination.session_duration_seconds, times the socket count. Stored as
    # the two measured facts and never as their product: the product is what a
    # reconciliation recomputes, and a stored product is a second place to be
    # wrong about the bill.
    billed_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sockets: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    channel: Mapped[str] = mapped_column(String(8), nullable=False, default="clean")
    # 'replay' today, 'live' from the evening the key lands. A column rather than
    # an inference, because the honesty of every measurement taken off this
    # database depends on knowing which rows came from a real microphone.
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="replay")

    # NULL until the first ~40 words settle it (ARCH 3.7). Not defaulted to
    # per_char: per_char is the regime that permits silent acceptance at letter
    # positions, and a default that grants the most permissive behaviour before
    # any evidence arrives is the wrong way round.
    confidence_regime: Mapped[str | None] = mapped_column(String(16), nullable=True)

    consent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    consent_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    disclosure_played: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_withdrawn_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)

    operator_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # Salted hash only, purged on the schedule in the column beside it. The
    # address itself never reaches this process's memory beyond the rate limiter.
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ip_hash_purge_after: Mapped[datetime | None] = mapped_column(TS, nullable=True)

    demo_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    organisation: Mapped[Organisation] = relationship(back_populates="sessions")
    captures: Mapped[list["Capture"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    questions: Mapped[list["QuestionEvent"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("billed_seconds >= 0", name="ck_session_billed_nonneg"),
        CheckConstraint("sockets >= 1", name="ck_session_sockets_min"),
        CheckConstraint(f"channel IN {CHANNELS}", name="ck_session_channel"),
        CheckConstraint(f"source IN {SOURCES}", name="ck_session_source"),
        CheckConstraint(f"end_reason IN {END_REASONS}", name="ck_session_end_reason"),
        CheckConstraint(
            f"confidence_regime IS NULL OR confidence_regime IN {REGIMES}",
            name="ck_session_regime",
        ),
        # An ip_hash without a purge date is an address kept forever by
        # accident. The pairing is enforced rather than remembered.
        CheckConstraint(
            "(ip_hash IS NULL) = (ip_hash_purge_after IS NULL)",
            name="ck_session_ip_hash_has_expiry",
        ),
        Index("ix_session_org_started", "organisation_id", "started_at"),
    )

    @property
    def charged_seconds(self) -> int:
        """What the ledger owes AssemblyAI for this session."""
        return self.billed_seconds * self.sockets

    # Deliberately no CHECK bounding billed_seconds by the per-session cap. The
    # cap is enforced at the socket; if it is ever breached the database must
    # still be able to record what actually happened, because a ledger that
    # cannot represent an overrun cannot be reconciled against the invoice.


# ----------------------------------------------------------------- capture --
VALIDATED_BY: Final = ("check_digit", "registry", "catalogue", "both", "none")
SECOND_SIGNAL: Final = ("carrier", "prefix", "llm", "none")
CAPTURE_STATUS: Final = ("committed", "flagged", "unverified")
HANDOVER_REASONS: Final = (
    "no_candidate", "budget_exhausted", "too_late", "implausible_repair", "regime_flat",
    # The call ended -- or the recording ran out -- with an identifier still under
    # consideration. Distinct from `too_late`, which is 4.8 gate 7 firing on an
    # identifier the conversation moved on from while the session kept running.
    # Collapsing the two hides a mute agent behind a reason that sounds deliberate.
    "stream_ended",
)


class Capture(Base):
    """One identifier, heard to written.

    NOT ON THIS TABLE, AND WHY. `heard_value` and `final_value` are the
    identifier and nothing around it: no carrier phrase, no leading tokens, no
    following words. The sentence surrounding an identifier is precisely what
    would let someone rebuild the call, and ARCH 3.9 lists it among the things
    never stored in any environment, so there is no column for it here or
    anywhere else. Per-word confidences and timings die with the tape when the
    capture commits; `confidence_at_write` is one scalar because the meter and
    the regime detector need a number, and one scalar localises nothing.
    """

    __tablename__ = "capture"
    RETENTION: Final = timedelta(days=30)  # ARCH 3.9

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("session.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)

    # No CHECK on the vocabulary: validators.py already carries 14 formats and
    # the list grows with the catalogue. A constraint here would turn adding a
    # format into a migration.
    format_type: Mapped[str] = mapped_column(String(24), nullable=False)
    heard_value: Mapped[str] = mapped_column(String(64), nullable=False)
    final_value: Mapped[str | None] = mapped_column(String(64), nullable=True)

    validated_by: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    second_signal: Mapped[str] = mapped_column(String(8), nullable=False, default="none")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="unverified")
    flag_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)

    confidence_at_write: Mapped[float | None] = mapped_column(Float, nullable=True)
    corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position_corrected: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Top 5 only, per ARCH 3.9. Candidate strings and their posterior mass --
    # each candidate is a rendering of the identifier itself, so the list adds
    # no information about the conversation. The cap is enforced in the
    # validator below rather than trusted to the caller.
    candidates_considered: Mapped[list[Any] | None] = mapped_column(JSONVariant, nullable=True)

    rung: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    questions_asked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Silence is the product (README, FINDINGS 6), so it gets a column instead of
    # being recomputed by whoever draws the chart. The CHECK below stops that
    # column and the two facts it summarises from drifting apart.
    silent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    handed_over: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    handover_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)

    # Wall clock from the identifier's last word to the row being written. The
    # number ARCH 4.8 gate 7 is about: past 10 s the agent must not speak at all.
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    session: Mapped[Session] = relationship(back_populates="captures")
    questions: Mapped[list["QuestionEvent"]] = relationship(
        back_populates="capture", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(f"validated_by IN {VALIDATED_BY}", name="ck_capture_validated_by"),
        CheckConstraint(f"second_signal IN {SECOND_SIGNAL}", name="ck_capture_second_signal"),
        CheckConstraint(f"status IN {CAPTURE_STATUS}", name="ck_capture_status"),
        CheckConstraint("rung BETWEEN 0 AND 3", name="ck_capture_rung"),
        CheckConstraint("questions_asked >= 0", name="ck_capture_questions_nonneg"),
        CheckConstraint(
            f"handover_reason IS NULL OR handover_reason IN {HANDOVER_REASONS}",
            name="ck_capture_handover_reason",
        ),
        # ARCH 3.10: capture.commit refuses with 422 unless validated_by and
        # second_signal are both present. Stated there as endpoint behaviour;
        # written here as well, because "there is no path from probably-right to
        # a clean row" is a claim about the database and only the database can
        # keep it. A second endpoint, a backfill script or a psql session all
        # hit this.
        CheckConstraint(
            "status <> 'committed' OR "
            "(validated_by <> 'none' AND second_signal <> 'none')",
            name="ck_capture_commit_needs_two_signals",
        ),
        CheckConstraint(
            "status <> 'committed' OR final_value IS NOT NULL",
            name="ck_capture_commit_has_value",
        ),
        # silent means the agent wrote it without asking anybody anything:
        # rung 0 and no questions. Rung 1 (amber) did not speak either, but it
        # put doubt on the screen, and counting that as silence would inflate the
        # one number the pitch rests on.
        CheckConstraint(
            "NOT silent OR (rung = 0 AND questions_asked = 0)",
            name="ck_capture_silent_means_rung0",
        ),
        CheckConstraint(
            "NOT corrected OR final_value IS NOT NULL",
            name="ck_capture_corrected_has_value",
        ),
        # ARCH 3.10: capture.flag at most once per distinct string per session,
        # "twice is the deadlock". Partial unique index, so the constraint binds
        # only the flagged rows and a string may still be captured cleanly after
        # the human resolves it.
        Index(
            "uq_capture_flag_once",
            "session_id",
            "heard_value",
            unique=True,
            sqlite_where=text("status = 'flagged'"),
            postgresql_where=text("status = 'flagged'"),
        ),
    )

    @validates("candidates_considered")
    def _cap_candidates(self, key: str, value: list[Any] | None) -> list[Any] | None:
        # ARCH 3.9 says top 5. Enforced rather than documented because the
        # solver returns cands[:8] and the temptation to persist all eight for
        # debugging is exactly how a column grows into a record of the reasoning.
        if value is not None and len(value) > 5:
            raise ValueError("candidates_considered holds the top 5 only (ARCH 3.9)")
        return value


# ---------------------------------------------------------------- question --
QUESTION_FORMS: Final = ("confirm", "alternative", "respell", "span")


class QuestionEvent(Base):
    """One question the agent asked about one character, and what came back.

    ARCH 3.9 calls this table `interrupt`. Renamed because rungs 1 and 2 land
    here too, and an amber slot or an earcon interrupts nobody; the old name
    would talk every reader of a count into thinking each row cost a caller
    their turn. `spoken` is the column that separates the two.

    NOT ON THIS TABLE, AND WHY. `question_text` is ours -- question.py generated
    it from characters of an identifier this schema already holds, so it
    discloses nothing new. What came back is recorded as three facts: whether
    they answered, whether the answer fell inside the grammar we offered, and
    which character it resolved to. Not as text. The answer is the one moment in
    a session where a human speaks directly to the agent, which makes its
    transcript both the most tempting thing to keep and the most obviously
    forbidden one.
    """

    __tablename__ = "question_event"
    RETENTION: Final = timedelta(days=7)  # ARCH 3.9: 7d, then counts

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("session.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("capture.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asked_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)

    rung: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    spoken: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    form: Mapped[str] = mapped_column(String(12), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    # The characters offered, in posterior order. Single characters only -- this
    # is the grammar, not the utterance.
    offered: Mapped[list[str] | None] = mapped_column(JSONVariant, nullable=True)

    answered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    answer_in_grammar: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    answer_char: Mapped[str | None] = mapped_column(String(1), nullable=True)
    resolution_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    session: Mapped[Session] = relationship(back_populates="questions")
    capture: Mapped[Capture] = relationship(back_populates="questions")

    __table_args__ = (
        CheckConstraint(f"form IN {QUESTION_FORMS}", name="ck_question_form"),
        CheckConstraint("rung BETWEEN 0 AND 3", name="ck_question_rung"),
        CheckConstraint("position >= 0", name="ck_question_position"),
        CheckConstraint(
            "answer_char IS NULL OR length(answer_char) = 1",
            name="ck_question_answer_is_one_char",
        ),
        # An unanswered question cannot have produced a character. Without this
        # a timeout and a resolution look the same in the counts, and the counts
        # are what survives the 7-day window.
        CheckConstraint(
            "answered OR (answer_char IS NULL AND answer_in_grammar IS NULL)",
            name="ck_question_unanswered_is_empty",
        ),
        CheckConstraint("NOT spoken OR rung = 3", name="ck_question_spoken_is_rung3"),
        Index("ix_question_session_asked", "session_id", "asked_at"),
    )


# ------------------------------------------------------------------- audit --
class AuditEvent(Base):
    """Append-only. Inserts only, forever.

    Enforced twice on purpose. audit.py installs an ORM before_flush guard that
    refuses UPDATE and DELETE on this class, which catches the 99% of mutations
    that arrive through the application; the triggers created below catch raw
    SQL, which is the 1% that matters.

    No foreign keys, despite three columns holding other tables' ids. The audit
    outlives what it describes: ARCH 3.12 requires a stop-and-delete button that
    visibly deletes a session, and with a foreign key that deletion would either
    be blocked by the log or would cascade into it. A record of a deletion that
    is destroyed by the deletion is not a record. The ids are kept bare and are
    expected to dangle.
    """

    __tablename__ = "audit_event"

    # Autoincrement integer as the primary key, next to a UUID that identifies
    # the row externally. The integer is the total order and the gap detector:
    # triggers can be dropped by anyone with DDL rights, and a missing seq is
    # what makes that visible afterwards.
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow, index=True)

    organisation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    capture_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    # Facts about a decision, scrubbed and size-capped by audit.record(). Never
    # a payload the caller assembled from the tape.
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)

    __table_args__ = (
        CheckConstraint("length(actor) > 0", name="ck_audit_actor_present"),
        CheckConstraint("length(action) > 0", name="ck_audit_action_present"),
        Index("ix_audit_action_at", "action", "at"),
    )


# SQLite and Postgres spell "refuse this write" differently and neither has a
# portable append-only table, so the DDL is dialect-dispatched and attached to
# the table rather than run by hand. create_all() installs it; a developer who
# builds the schema without reading this file still gets the guard.
event.listen(
    AuditEvent.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER IF NOT EXISTS audit_event_no_update "
        "BEFORE UPDATE ON audit_event "
        "BEGIN SELECT RAISE(ABORT, 'audit_event is append-only'); END"
    ).execute_if(dialect="sqlite"),
)
event.listen(
    AuditEvent.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER IF NOT EXISTS audit_event_no_delete "
        "BEFORE DELETE ON audit_event "
        "BEGIN SELECT RAISE(ABORT, 'audit_event is append-only'); END"
    ).execute_if(dialect="sqlite"),
)
event.listen(
    AuditEvent.__table__,
    "after_create",
    DDL(
        "CREATE OR REPLACE FUNCTION readback_audit_append_only() RETURNS trigger AS $$ "
        "BEGIN RAISE EXCEPTION 'audit_event is append-only'; END; $$ LANGUAGE plpgsql"
    ).execute_if(dialect="postgresql"),
)
event.listen(
    AuditEvent.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER audit_event_append_only "
        "BEFORE UPDATE OR DELETE ON audit_event "
        "FOR EACH ROW EXECUTE FUNCTION readback_audit_append_only()"
    ).execute_if(dialect="postgresql"),
)


# ------------------------------------------------------- reference tables ---
class OwnerCode(Base):
    """ISO 6346 owner prefixes -- the letter constraint the check digit is not.

    The first three characters of a container number carry no checksum weight
    the solver can use on their own, so a registered prefix is the second signal
    ARCH 3.8 requires before a format may be asserted. Frequency-weighted
    because a prefix seen daily is better evidence than one seen once.
    """

    __tablename__ = "owner_code"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    owner: Mapped[str] = mapped_column(String(160), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint("length(code) = 3", name="ck_owner_code_len"),
        CheckConstraint("weight >= 0", name="ck_owner_code_weight"),
    )


class CataloguePart(Base):
    """Part numbers with no checksum at all. The catalogue is the constraint:
    a hypothesis is valid iff a row exists within edit distance 2. The rhyme
    signature is the multi-probe index key -- solver.RHYME collapses acoustically
    confusable characters to one class, so a lookup on it retrieves the whole
    confusable neighbourhood in one indexed read instead of a scan.

    One catalogue per ORGANISATION. It used to be one per deployment, read and
    replaced by any signed-in account while sign-up was open -- so a stranger
    could read another company's part list or plant their own, and the catalogue
    is what vouches for a `catalogue` capture silently (22 September audit).
    A table created before that is renamed aside on boot by
    db.create_all, never read: its rows have no owner to give them to."""

    __tablename__ = "catalogue_part"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisation.id", ondelete="CASCADE"), primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    rhyme_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)

    __table_args__ = (Index("ix_catalogue_rhyme", "organisation_id", "rhyme_signature"),)


class ConfusionObservation(Base):
    """Online pseudo-counts from answered questions: the human told us the truth
    for a character we misheard, which is one observation of w(truth -> heard).

    Two characters, never a context. This is the only table that learns from
    what people say, and it is designed so that everything it learns is a
    26x26 tally -- there is no session id, no capture id and no timestamp beyond
    last_seen, so no row can be traced back to the call that produced it.
    """

    __tablename__ = "confusion_observation"

    heard: Mapped[str] = mapped_column(String(1), primary_key=True)
    truth: Mapped[str] = mapped_column(String(1), primary_key=True)
    n: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint("length(heard) = 1 AND length(truth) = 1", name="ck_confusion_chars"),
        CheckConstraint("n >= 0", name="ck_confusion_n"),
    )


# ------------------------------------------- the two structural invariants ---
# ARCH 3.12 forbids raw audio retention and transcript retention in every
# environment "including dev". A rule that lives only in a document survives
# exactly until the first person who needs a debugging column at 2am. These two
# checks run at import, so that person's branch does not start.

_BYTES_TYPES: Final = (bytes, bytearray, memoryview)

# Matched against column names, case-insensitively, as substrings. The list is
# the ARCH 3.9 never-stored list turned into vocabulary: the words someone would
# reach for if they were about to persist audio, the tape, or the sentence
# around an identifier. "transcript" rather than "script", because
# "description" contains "script" and CataloguePart legitimately has one.
FORBIDDEN_NAME: Final = re.compile(
    r"audio|pcm|waveform|voiceprint|embedding|speaker_label|speaker_id"
    r"|transcript|tape|utterance|sentence|surrounding|dialogue|conversation"
    r"|turn_text|raw_text|full_text|word_conf|word_time",
    re.IGNORECASE,
)


def assert_no_audio_or_tape_columns(metadata: Any = None) -> None:
    """Fail the import if the schema grows somewhere to put a call.

    The bytes check is on `python_type` rather than on LargeBinary, so it also
    catches BINARY, VARBINARY, BYTEA and any custom type that round-trips bytes.
    There is no legitimate binary column in this system: identifiers are text,
    candidates are JSON, and audio never reaches the database layer at all.
    """
    md = metadata if metadata is not None else Base.metadata
    for table in md.tables.values():
        for col in table.columns:
            try:
                py = col.type.python_type
            except (NotImplementedError, AttributeError):
                py = None
            if py in _BYTES_TYPES:
                raise RuntimeError(
                    f"{table.name}.{col.name} is a binary column. Raw audio is "
                    f"never stored (ARCH 3.12); the schema must not be able to "
                    f"hold PCM even by accident."
                )
            if FORBIDDEN_NAME.search(col.name):
                raise RuntimeError(
                    f"{table.name}.{col.name} names something from the ARCH 3.9 "
                    f"never-stored list. Captures are persisted, the tape is not; "
                    f"if a column would let someone reconstruct the conversation "
                    f"around an identifier, it does not go in."
                )


assert_no_audio_or_tape_columns()


class VocabularyTerm(Base):
    """ARCH 3.9: an organisation's own words for the recogniser -- owner
    prefixes, part numbers, the names its callers actually say. Pushed as
    keyterms after the state's own terms on every session the organisation
    runs (detector.keyterms `extra`). One row per term and the pair is the key,
    so a term cannot be stored twice; `position` keeps the order the operator
    chose, which is the order the 100-term budget is spent in."""

    __tablename__ = "vocabulary_term"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisation.id", ondelete="CASCADE"), primary_key=True)
    term: Mapped[str] = mapped_column(String(50), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)
