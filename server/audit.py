# audit.py -- the append-only event log. Small, boring, correct.
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session as SASession

from server.models import AuditEvent, FORBIDDEN_NAME

# validators.py calls random.seed(7) at import -- an artefact of its bench
# harness. Harmless here: nothing in this layer draws from the `random` module,
# and uuid4 reads os.urandom. Importing luhn_ok rather than re-implementing it
# keeps one definition of the check in the repo.
from server.readback.validators import luhn_ok


class AppendOnlyViolation(RuntimeError):
    """Raised when something tries to update or delete an audit row."""


class AuditPayloadRefused(ValueError):
    """Raised when a detail payload is too large or names forbidden material."""


# ---------------------------------------------------------------- actions ---
# A closed vocabulary. record() refuses anything outside it, because this log is
# read by counting -- "how many sessions ran without disclosure", "how often did
# the budget gate fire" -- and a typo'd action name is not a broken query, it is
# a silently wrong count that nobody notices.
CONSENT_GRANTED: Final = "consent.granted"
CONSENT_WITHDRAWN: Final = "consent.withdrawn"
DISCLOSURE_PLAYED: Final = "disclosure.played"
SESSION_STARTED: Final = "session.started"
SESSION_ENDED: Final = "session.ended"
SESSION_DELETED: Final = "session.deleted"
SESSION_REFUSED: Final = "session.refused"
SOCKET_OPENED: Final = "socket.opened"
SOCKET_CLOSED: Final = "socket.closed"
REGIME_DETECTED: Final = "regime.detected"
BUDGET_ALARM: Final = "budget.alarm"
BUDGET_EXHAUSTED: Final = "budget.exhausted"
REPLAY_ENTERED: Final = "replay.entered"
CAPTURE_COMMITTED: Final = "capture.committed"
CAPTURE_FLAGGED: Final = "capture.flagged"
CAPTURE_CORRECTED: Final = "capture.corrected"
CAPTURE_HANDOVER: Final = "capture.handover"
QUESTION_ASKED: Final = "question.asked"
QUESTION_ANSWERED: Final = "question.answered"
DATA_PURGED: Final = "data.purged"

ACTIONS: Final[frozenset[str]] = frozenset({
    CONSENT_GRANTED, CONSENT_WITHDRAWN, DISCLOSURE_PLAYED,
    SESSION_STARTED, SESSION_ENDED, SESSION_DELETED, SESSION_REFUSED,
    SOCKET_OPENED, SOCKET_CLOSED, REGIME_DETECTED,
    BUDGET_ALARM, BUDGET_EXHAUSTED, REPLAY_ENTERED,
    CAPTURE_COMMITTED, CAPTURE_FLAGGED, CAPTURE_CORRECTED, CAPTURE_HANDOVER,
    QUESTION_ASKED, QUESTION_ANSWERED, DATA_PURGED,
})


# ------------------------------------------------------------ minimisation --
# 13-19 digits, optionally spaced or hyphenated, not touching another digit.
_PAN_RUN: Final = re.compile(r"(?<!\d)(\d(?:[ -]?\d){12,18})(?!\d)")
_REDACTED: Final = "[REDACTED:PAN]"

# ARCH 3.9's never-stored list applies "at every stage including logs and stack
# traces", and detail is the one column in this layer that accepts a shape the
# caller chose. 4 KB is generous for the facts an audit row is for -- a rung, a
# position, a reason, a count -- and small enough that anything wanting more
# room is a transcript wearing a JSON hat.
MAX_DETAIL_BYTES: Final = 4096


def scrub(value: Any) -> Any:
    """Redact Luhn-valid card-shaped runs anywhere in a JSON-able payload.

    Luhn-checking before redacting rather than blanking every long digit run:
    a random 16-digit string passes Luhn 1 time in 10, so the check removes 90%
    of the false positives, and the identifiers this system exists to write --
    container numbers, NHS numbers, VINs -- are all outside the 13-19 digit
    all-digit window or fail the check. A card number that reaches this function
    is a bug upstream; the redaction is here so the bug does not become a
    retained PAN.
    """
    if isinstance(value, str):
        return _PAN_RUN.sub(_sub_if_luhn, value)
    if isinstance(value, Mapping):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


def _sub_if_luhn(m: re.Match[str]) -> str:
    digits = re.sub(r"[ -]", "", m.group(1))
    return _REDACTED if 13 <= len(digits) <= 19 and luhn_ok(digits) else m.group(1)


def _check_detail(detail: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if detail is None:
        return None
    for key in detail:
        # A key called `transcript` is not an accident to be scrubbed, it is a
        # decision to be reversed, so this refuses rather than redacts.
        if FORBIDDEN_NAME.search(str(key)):
            raise AuditPayloadRefused(
                f"audit detail key {key!r} names material the system never "
                f"stores (ARCH 3.9). Record the decision, not the tape."
            )
    clean = scrub(dict(detail))
    encoded = json.dumps(clean, default=str, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_DETAIL_BYTES:
        raise AuditPayloadRefused(
            f"audit detail is {len(encoded)} bytes, limit {MAX_DETAIL_BYTES}"
        )
    return json.loads(encoded)


# --------------------------------------------------------------- appending --
def record(
    db: SASession,
    action: str,
    *,
    organisation_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    capture_id: uuid.UUID | None = None,
    actor: str = "system",
    detail: Mapping[str, Any] | None = None,
    at: datetime | None = None,
) -> AuditEvent:
    """Append one event. Flushes, never commits.

    The caller owns the transaction boundary on purpose: an audit row that
    committed independently of the fact it describes would be a lie in one
    direction (a recorded capture that rolled back) or the other (a capture with
    no record). Flushing rather than deferring is what assigns `seq`, which the
    caller usually wants and the gap detector always does.
    """
    if action not in ACTIONS:
        raise ValueError(f"unknown audit action {action!r}; add it to ACTIONS first")
    if not actor:
        raise ValueError("audit events need an actor")
    ev = AuditEvent(
        action=action,
        actor=actor,
        organisation_id=organisation_id,
        session_id=session_id,
        capture_id=capture_id,
        detail=_check_detail(detail),
    )
    if at is not None:
        ev.at = at
    db.add(ev)
    db.flush()
    return ev


def events(
    db: SASession,
    *,
    session_id: uuid.UUID | None = None,
    organisation_id: uuid.UUID | None = None,
    action: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.seq)
    if session_id is not None:
        stmt = stmt.where(AuditEvent.session_id == session_id)
    if organisation_id is not None:
        stmt = stmt.where(AuditEvent.organisation_id == organisation_id)
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    if since is not None:
        stmt = stmt.where(AuditEvent.at >= since)
    return list(db.scalars(stmt.limit(limit)))


def count(db: SASession, action: str, *, since: datetime | None = None) -> int:
    stmt = select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)
    if since is not None:
        stmt = stmt.where(AuditEvent.at >= since)
    return int(db.scalar(stmt) or 0)


def gaps(db: SASession) -> list[tuple[int, int]]:
    """Missing `seq` ranges: evidence that rows were removed around the guards.

    Not a hash chain. A chain would need every writer serialised behind a
    read-modify-write on the previous row's digest, and the honest version of
    that is a single-threaded sequencer, not a lock held inside every request
    handler. Gap detection catches deletion, which is the threat the triggers
    already refuse and this exists to notice if they are ever dropped.
    """
    seqs = list(db.scalars(select(AuditEvent.seq).order_by(AuditEvent.seq)))
    out: list[tuple[int, int]] = []
    for a, b in zip(seqs, seqs[1:]):
        if b != a + 1:
            out.append((a + 1, b - 1))
    return out


# ----------------------------------------------------------- the ORM guard --
@event.listens_for(SASession, "before_flush")
def _refuse_audit_mutation(session: SASession, flush_context: Any, instances: Any) -> None:
    """Refuse UPDATE and DELETE on audit rows before the flush emits SQL.

    Registered on the Session class rather than on one factory, so a session
    built anywhere -- a script, a test, a migration -- inherits it. The database
    triggers in models.py catch raw SQL; this catches the ORM, and it catches it
    early enough to name the object rather than surfacing a driver error.
    """
    for obj in session.dirty:
        if isinstance(obj, AuditEvent) and session.is_modified(obj, include_collections=False):
            raise AppendOnlyViolation(
                f"audit_event seq={obj.seq} was modified; the log is append-only"
            )
    for obj in session.deleted:
        if isinstance(obj, AuditEvent):
            raise AppendOnlyViolation(
                f"audit_event seq={obj.seq} was deleted; the log is append-only"
            )
