"""ARCH 3.12's auto-purge. Nothing implemented it until now.

`config.py` said "ARCH 3.12 states a 24-hour auto-purge and implements it" and
carried four windows; `models.py` carried the same numbers again as RETENTION
attributes so a table and its window could not drift apart. Neither of them
deleted a row. A retention policy nothing enforces is not a policy, and the
2026-09-11 audit found the claim standing on its own.

Four windows, each with a reason rather than a round number:

  ip_hash            24 h  the salt rotates daily, so an older hash cannot be
                           re-identified anyway -- keeping it buys nothing and
                           is one more column to explain.
  question_event      7 d  a question holds the position the agent doubted and
                           the character a human said back. Counts survive it;
                           the rows do not.
  capture            30 d  the captured identifier is the product's output and
                           the customer's record, so this is the longest of
                           them -- but it is not forever.
  demo sessions      24 h  fictional by construction, and the demo tenant is
                           shared: yesterday's fixtures are nobody's record.

Every pass writes ONE audit row with the counts. That row is the evidence the
purge ran, and it is deliberately the only thing the purge leaves behind.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session as SASession

from server import audit
from server.config import Settings
from server.models import Capture, QuestionEvent, Session

log = logging.getLogger("readback.purge")


@dataclass(frozen=True, slots=True)
class PurgeCounts:
    ip_hashes: int = 0
    questions: int = 0
    captures: int = 0
    demo_sessions: int = 0

    @property
    def total(self) -> int:
        return self.ip_hashes + self.questions + self.captures + self.demo_sessions


def purge(db: SASession, settings: Settings, *, now: datetime | None = None) -> PurgeCounts:
    """Delete what is past its window. Commits once, at the end.

    Order matters: questions and captures are removed before the sessions that
    own them, so a cascade never removes a row this function has not counted.
    """
    now = now or datetime.now(timezone.utc)

    q_cut = now - timedelta(days=settings.question_retention_days)
    c_cut = now - timedelta(days=settings.capture_retention_days)
    demo_cut = now - timedelta(hours=settings.demo_purge_hours)

    # Cleared rather than deleted: the session row is the record of the call,
    # and only this one column is past its window. The deadline is read off the
    # row (`ip_hash_purge_after`, written when the hash was) rather than
    # recomputed from `started_at` and today's setting -- models.py enforces the
    # pairing with a CHECK for exactly this reason, so the row is the authority
    # on when its own hash expires. Both columns are cleared together or the
    # constraint refuses the write.
    ip_hashes = db.execute(
        update(Session)
        .where(Session.ip_hash.is_not(None), Session.ip_hash_purge_after < now)
        .values(ip_hash=None, ip_hash_purge_after=None)
    ).rowcount or 0

    questions = db.execute(
        delete(QuestionEvent).where(QuestionEvent.asked_at < q_cut)
    ).rowcount or 0

    captures = db.execute(
        delete(Capture).where(Capture.created_at < c_cut)
    ).rowcount or 0

    # A demo session goes whole: its captures are fixtures, not a customer's
    # record, and the audit rows describing it survive by construction
    # (audit_event has no foreign keys).
    stale_demo = list(db.scalars(
        select(Session.id).where(Session.demo_mode.is_(True),
                                 Session.started_at < demo_cut)))
    demo_sessions = 0
    if stale_demo:
        db.execute(delete(Capture).where(Capture.session_id.in_(stale_demo)))
        db.execute(delete(QuestionEvent).where(QuestionEvent.session_id.in_(stale_demo)))
        demo_sessions = db.execute(
            delete(Session).where(Session.id.in_(stale_demo))).rowcount or 0

    counts = PurgeCounts(ip_hashes=ip_hashes, questions=questions,
                         captures=captures, demo_sessions=demo_sessions)
    if counts.total:
        # Organisation-less on purpose: a purge is a property of the
        # deployment, and naming one tenant on a sweep across all of them
        # would be a wrong fact in a log that is read by counting.
        audit.record(db, audit.DATA_PURGED, actor="system", detail=asdict(counts))
    db.commit()
    if counts.total:
        log.info("purge removed %s", asdict(counts))
    return counts
