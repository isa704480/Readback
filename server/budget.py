"""ARCH 3.11: the daily ceiling on socket-seconds, and how much of it is spent.

One deployment-wide number -- the kill switch that stops a surprise invoice --
read by two callers: session admission refuses when it cannot afford one more
session, and /api/usage shows it beside the organisation's own spend.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as SASession

from server.config import Settings
from server.models import Session


def spent_socket_seconds(db: SASession, since: datetime) -> int:
    """Socket-seconds billed today. The product is computed, never stored --
    models.py keeps `billed_seconds` and `sockets` apart so that a reconciliation
    has one place to be wrong instead of two."""
    total = db.scalar(
        select(func.coalesce(func.sum(Session.billed_seconds * Session.sockets), 0))
        .where(Session.started_at >= since)
    )
    return int(total or 0)



def today(db: SASession, settings: Settings) -> tuple[int, bool, bool]:
    """(remaining socket-seconds, alarm, exhausted)."""
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                  microsecond=0)
    spent = spent_socket_seconds(db, midnight)
    remaining = settings.daily_budget_seconds - spent
    return (max(0, remaining),
            spent >= settings.budget_alarm_seconds,
            remaining < settings.session_socket_seconds)
