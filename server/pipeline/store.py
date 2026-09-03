"""Where a decision goes when it is finished being a decision.

The runner is written against `CaptureStore`, never against SQLAlchemy, for the
same reason it is written against `TranscriptSource` rather than a socket: the
end-to-end test has to be able to drive all five fixtures through the real loop
without a database, and the demo endpoint has to write real rows through the same
loop. One protocol, two implementations, no branch inside the loop.

`NullStore` is not a stub for the tests to make assertions against -- the event
stream is what the tests assert on, because the event stream is what the product
shows. It exists so that "no database configured" is a first-class mode rather
than an exception path nobody runs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Final, Protocol, runtime_checkable

from sqlalchemy.orm import Session as SASession

from server import audit
from server.models import Capture, QuestionEvent, Session, utcnow
from server.readback.validators import luhn_ok

# ARCH 3.9, never-stored, last line: "anything matching a 13-19 digit Luhn-valid
# pattern, at every stage including logs and stack traces." `audit.scrub` already
# enforces that for the one column taking a caller-shaped payload. The capture
# table needed it more and did not have it: `card number` is a carrier phrase in
# the detector and `luhn16` is a live format, so the ordinary success path of this
# system writes a PAN. Measured before the fix -- a session reading the published
# Luhn vector 4539578763621486 persisted it verbatim in `heard_value`,
# `final_value` and `candidates_considered`.
#
# Masked rather than refused, because the capture still has to be findable by the
# operator who just read it out. Last four is the convention every payment
# interface uses and is the most that can be kept without keeping a card number.
# The event stream is deliberately untouched: showing the operator the digits
# they are currently speaking is the product, and 3.9 is a rule about storage.
PAN_KEEP_TAIL: Final = 4


def mask_pan(value: str | None) -> str | None:
    """Mask a value on its way to a column, if and only if it is a card number.

    Deliberately the same predicate as `audit.scrub` -- Luhn-valid, 13-19 digits
    -- so the two layers cannot come to disagree about what a PAN is. Container
    numbers, VINs and NHS numbers all fall outside that window or fail the check,
    so this is a no-op on every other format the system captures.
    """
    if not value:
        return value
    digits = value.replace(" ", "").replace("-", "")
    if 13 <= len(digits) <= 19 and digits.isdigit() and luhn_ok(digits):
        return "*" * (len(digits) - PAN_KEEP_TAIL) + digits[-PAN_KEEP_TAIL:]
    return value


@dataclass(frozen=True, slots=True)
class CaptureRecord:
    """One finished identifier, as the database wants it.

    Deliberately not the solver's result dict: the solver returns eight
    candidates, per-position posteriors and a marginal, and models.py caps
    `candidates_considered` at five precisely because the temptation to persist
    the whole reasoning is how a column becomes a record of the conversation
    (ARCH 3.9). This type is the projection, and it is where the projection is
    decided rather than at the call site.
    """

    capture_id: uuid.UUID
    format_type: str
    heard_value: str
    final_value: str | None
    validated_by: str
    second_signal: str
    status: str
    rung: int
    silent: bool
    corrected: bool
    position_corrected: int | None
    questions_asked: int
    spans: int
    handed_over: bool
    handover_reason: str | None
    flag_reason: str | None
    confidence_at_write: float | None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class QuestionRecord:
    """One question and, if it came back, three facts about the answer.

    Three facts and never the text. The answer is the one moment in the session
    where a human speaks directly to the agent, which makes it the most tempting
    thing in the system to keep, which is exactly why models.py has no column for
    it (ARCH 3.9).
    """

    question_id: uuid.UUID
    capture_id: uuid.UUID
    rung: int
    spoken: bool
    position: int
    form: str
    question_text: str
    offered: list[str]
    answered: bool = False
    answer_in_grammar: bool | None = None
    answer_char: str | None = None
    resolution_ms: int | None = None


@runtime_checkable
class CaptureStore(Protocol):
    """What the runner is allowed to know about persistence."""

    def open_capture(self, capture_id: uuid.UUID, format_type: str,
                     heard_value: str) -> None: ...

    def abandon_capture(self, capture_id: uuid.UUID) -> None: ...

    def write_capture(self, record: CaptureRecord) -> None: ...

    def write_question(self, record: QuestionRecord) -> None: ...

    def observe_confusion(self, heard: str, truth: str) -> None: ...

    def finish(self, *, billed_seconds: int, end_reason: str,
               confidence_regime: str | None) -> None: ...


class NullStore:
    """Keeps the records in memory. The default, and what the fixtures run on."""

    def __init__(self) -> None:
        self.opened: list[tuple[uuid.UUID, str, str]] = []
        self.abandoned: list[uuid.UUID] = []
        self.captures: list[CaptureRecord] = []
        self.questions: list[QuestionRecord] = []
        self.confusions: list[tuple[str, str]] = []
        self.ended: dict[str, Any] | None = None

    def open_capture(self, capture_id: uuid.UUID, format_type: str,
                     heard_value: str) -> None:
        self.opened.append((capture_id, format_type, heard_value))

    def abandon_capture(self, capture_id: uuid.UUID) -> None:
        self.abandoned.append(capture_id)

    def write_capture(self, record: CaptureRecord) -> None:
        self.captures.append(record)

    def write_question(self, record: QuestionRecord) -> None:
        self.questions.append(record)

    def observe_confusion(self, heard: str, truth: str) -> None:
        self.confusions.append((heard, truth))

    def finish(self, *, billed_seconds: int, end_reason: str,
               confidence_regime: str | None) -> None:
        self.ended = {
            "billed_seconds": billed_seconds,
            "end_reason": end_reason,
            "confidence_regime": confidence_regime,
        }


class SqlCaptureStore:
    """Rows, plus the audit events that make them accountable.

    Commits per record rather than per session. A session is minutes long and a
    browser that vanishes mid-call must not take the captures with it -- the
    identifiers are the only thing worth keeping, and they are already written
    down by the time anything else can fail.
    """

    def __init__(self, db: SASession, session_id: uuid.UUID,
                 organisation_id: uuid.UUID | None = None) -> None:
        self.db = db
        self.session_id = session_id
        self.organisation_id = organisation_id

    def open_capture(self, capture_id: uuid.UUID, format_type: str,
                     heard_value: str) -> None:
        """Create the row the moment a candidate exists, as `unverified`.

        Not premature: `question_event.capture_id` is a foreign key, and the
        agent asks its question *before* the capture reaches a terminal state,
        so a row that appears only at commit time cannot be referenced by the
        question that produced the commit. It is also the truth -- an identifier
        under consideration is exactly an unverified capture, which is what the
        rack is already showing -- and it means a session that dies mid-question
        leaves evidence that it was working on something rather than nothing.
        """
        if self.db.get(Capture, capture_id) is not None:
            return
        self.db.add(Capture(id=capture_id, session_id=self.session_id,
                            format_type=format_type,
                            heard_value=mask_pan(heard_value),
                            status="unverified"))
        self.db.commit()

    def abandon_capture(self, capture_id: uuid.UUID) -> None:
        """The recogniser revised the window before this candidate was decided.

        Not a capture. The row exists because `open_capture` has to create it
        early enough for a question to reference it, and if no question ever did
        and no decision was ever made, what is left is a hypothesis the pipeline
        withdrew -- which the team-leader view would otherwise render as an
        identifier somebody read out. Measured: a card number passing through ten
        digits on its way to sixteen left a phantom `nhs` capture of the first
        ten, permanently `unverified`.

        Refuses to delete a row a question points at, both because the foreign
        key forbids it and because a question asked out loud is a thing that
        happened; a capture with a question on it is decided by definition.
        """
        row = self.db.get(Capture, capture_id)
        if row is None or row.status != "unverified" or row.questions_asked:
            return
        if self.db.query(QuestionEvent).filter(
                QuestionEvent.capture_id == capture_id).first() is not None:
            return
        self.db.delete(row)
        self.db.commit()

    def write_capture(self, record: CaptureRecord) -> None:
        row = self.db.get(Capture, record.capture_id)
        if row is None:
            row = Capture(id=record.capture_id, session_id=self.session_id)
            self.db.add(row)
        row.format_type = record.format_type
        row.heard_value = mask_pan(record.heard_value)
        row.final_value = mask_pan(record.final_value)
        row.validated_by = record.validated_by
        row.second_signal = record.second_signal
        row.status = record.status
        row.flag_reason = record.flag_reason
        row.confidence_at_write = record.confidence_at_write
        row.corrected = record.corrected
        row.position_corrected = record.position_corrected
        # The candidate list is the one place a masked value could be undone: the
        # top five near-misses of a PAN differ from it in one digit each, so five
        # of them plus the last four is the whole card.
        row.candidates_considered = [
            {**c, "value": mask_pan(str(c["value"]))} if "value" in c else c
            for c in record.candidates[:5]
        ]
        row.rung = record.rung
        row.questions_asked = record.questions_asked
        row.silent = record.silent
        row.handed_over = record.handed_over
        row.handover_reason = record.handover_reason
        row.latency_ms = record.latency_ms
        action = {
            "committed": audit.CAPTURE_COMMITTED,
            "flagged": audit.CAPTURE_FLAGGED,
        }.get(record.status, audit.CAPTURE_HANDOVER)
        audit.record(
            self.db, action,
            session_id=self.session_id,
            organisation_id=self.organisation_id,
            capture_id=record.capture_id,
            actor="pipeline",
            # Facts about the decision. No heard or written value: ARCH 3.9's
            # never-stored list covers logs, and a capture row already holds the
            # value under its own retention window. The audit row is the count.
            detail={
                "format": record.format_type,
                "validated_by": record.validated_by,
                "second_signal": record.second_signal,
                "rung": record.rung,
                "silent": record.silent,
                "corrected": record.corrected,
                "position_corrected": record.position_corrected,
                "questions": record.questions_asked,
                "spans": record.spans,
                "handover_reason": record.handover_reason,
                "latency_ms": record.latency_ms,
            },
        )
        if record.corrected and record.status == "committed":
            audit.record(
                self.db, audit.CAPTURE_CORRECTED,
                session_id=self.session_id,
                organisation_id=self.organisation_id,
                capture_id=record.capture_id,
                actor="pipeline",
                detail={"position": record.position_corrected},
            )
        self.db.commit()

    def write_question(self, record: QuestionRecord) -> None:
        row = QuestionEvent(
            id=record.question_id,
            session_id=self.session_id,
            capture_id=record.capture_id,
            rung=record.rung,
            spoken=record.spoken,
            position=record.position,
            form=record.form,
            question_text=record.question_text,
            offered=record.offered,
            answered=record.answered,
            answer_in_grammar=record.answer_in_grammar,
            answer_char=record.answer_char,
            resolution_ms=record.resolution_ms,
        )
        self.db.add(row)
        audit.record(
            self.db, audit.QUESTION_ASKED,
            session_id=self.session_id,
            organisation_id=self.organisation_id,
            capture_id=record.capture_id,
            actor="pipeline",
            detail={"position": record.position, "form": record.form,
                    "rung": record.rung, "spoken": record.spoken},
        )
        if record.answered:
            audit.record(
                self.db, audit.QUESTION_ANSWERED,
                session_id=self.session_id,
                organisation_id=self.organisation_id,
                capture_id=record.capture_id,
                actor="human",
                detail={"position": record.position,
                        "in_grammar": record.answer_in_grammar,
                        "resolution_ms": record.resolution_ms},
            )
        self.db.commit()

    def observe_confusion(self, heard: str, truth: str) -> None:
        """ARCH 4.6's online pseudo-count, written down rather than applied.

        4.6 says one dict write fixes a systematic accent after a single
        question, and it is right about the value: an out-of-table confusion pair
        costs 21 -> 0.8% silence. What it does not say is where the dict lives.
        `solver.W` is a module global shared by every session in the process, so
        mutating it from inside a request handler makes one caller's answer
        change another caller's posterior mid-call, and makes test order
        significant. The count is durable here instead; `apply_observations()`
        folds the table into `solver.W` at process start, which is the same
        arithmetic with a boundary around it.
        """
        from sqlalchemy import select

        from server.models import ConfusionObservation

        row = self.db.scalar(
            select(ConfusionObservation).where(
                ConfusionObservation.heard == heard,
                ConfusionObservation.truth == truth,
            )
        )
        if row is None:
            self.db.add(ConfusionObservation(heard=heard, truth=truth, n=1,
                                             last_seen=utcnow()))
        else:
            row.n += 1
            row.last_seen = utcnow()
        self.db.commit()

    def finish(self, *, billed_seconds: int, end_reason: str,
               confidence_regime: str | None) -> None:
        row = self.db.get(Session, self.session_id)
        if row is not None:
            row.billed_seconds = billed_seconds
            row.end_reason = end_reason
            row.ended_at = utcnow()
            if confidence_regime is not None:
                row.confidence_regime = confidence_regime
            if row.ip_hash is not None and row.ip_hash_purge_after is None:
                row.ip_hash_purge_after = utcnow() + timedelta(
                    hours=Session.IP_HASH_RETENTION.total_seconds() // 3600
                )
        audit.record(
            self.db, audit.SESSION_ENDED,
            session_id=self.session_id,
            organisation_id=self.organisation_id,
            actor="pipeline",
            detail={"billed_seconds": billed_seconds, "end_reason": end_reason,
                    "confidence_regime": confidence_regime},
        )
        self.db.commit()


def apply_observations(db: SASession, *, min_n: int = 1,
                       weight_per_count: float = 0.15, cap: float = 0.60) -> int:
    """Fold `confusion_observation` into `solver.W`. Call at process start.

    `weight_per_count` is 0.15 because that is `CFG["MIN_EDGE"]` -- the weight
    at which the solver is willing to make a substitution silently. One observed
    answer therefore promotes a pair from "the floor, 0.004" to "the lightest
    substitution the agent will act on without asking", which is the behaviour
    4.6 describes and not a guess. The cap is below the heaviest real pairs
    (O/0 at 0.95, M/N at 0.72) so that observation can never outrank measurement.
    """
    from sqlalchemy import select

    from server.models import ConfusionObservation
    from server.readback import solver

    n = 0
    for row in db.scalars(select(ConfusionObservation)):
        if row.n < min_n:
            continue
        w = min(cap, weight_per_count * row.n)
        key = (row.truth, row.heard)
        if w > solver.W.get(key, 0.0):
            solver.W[key] = w
            n += 1
    return n


__all__ = [
    "CaptureRecord",
    "CaptureStore",
    "NullStore",
    "QuestionRecord",
    "SqlCaptureStore",
    "apply_observations",
]
