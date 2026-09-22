"""Platform-level state the admin panel owns, and the gates that read it.

Three things, each read by the code paths it constrains rather than only by the
panel that sets it:

  who is an admin      platform_admin rows, granted out of band (admin_cli.py)
  runtime switches     platform_setting rows -- `live_paused`, `signups_paused`
  per-tenant limits    Organisation.active and Organisation.daily_budget_seconds,
                       both of which existed in the schema and were enforced
                       nowhere until this module

Nothing here imports main.py; main.py and routes/admin.py both import this.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session as SASession

from server.models import Organisation, PlatformAdmin, PlatformSetting, Session, User, utcnow

# Every switch the panel can flip, with its value when no row exists. A key not
# in this table cannot be set: the admin route validates against it.
CONTROL_DEFAULTS: Final[dict[str, bool]] = {
    # New sessions run the recorded fixtures instead of opening an AssemblyAI
    # socket. The same fallback the daily budget uses, so nothing downstream
    # needs a third behaviour. Takes effect at the next admission.
    "live_paused": False,
    # POST /api/auth/signup answers 403. For an abuse wave: existing accounts
    # keep working, nobody new gets in.
    "signups_paused": False,
}


def is_admin(db: SASession, user: User | None) -> bool:
    if user is None or not user.active:
        return False
    return db.get(PlatformAdmin, user.id) is not None


def controls(db: SASession) -> dict[str, bool]:
    """The switches as they stand, defaults filled in for keys never set."""
    out = dict(CONTROL_DEFAULTS)
    for row in db.scalars(select(PlatformSetting)
                          .where(PlatformSetting.key.in_(tuple(CONTROL_DEFAULTS)))):
        out[row.key] = bool(row.value)
    return out


def set_control(db: SASession, key: str, value: bool, actor: str) -> None:
    if key not in CONTROL_DEFAULTS:
        raise KeyError(key)
    row = db.get(PlatformSetting, key)
    if row is None:
        db.add(PlatformSetting(key=key, value=bool(value), updated_by=actor))
    else:
        row.value = bool(value)
        row.updated_at = utcnow()
        row.updated_by = actor


def midnight_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def org_spent_today(db: SASession, org_id: uuid.UUID) -> int:
    """Socket-seconds this organisation billed since UTC midnight -- the same
    product (billed_seconds x sockets) the deployment budget counts."""
    total = db.scalar(
        select(func.coalesce(func.sum(Session.billed_seconds * Session.sockets), 0))
        .where(Session.organisation_id == org_id, Session.started_at >= midnight_utc()))
    return int(total or 0)


def org_budget_exhausted(db: SASession, org: Organisation | None) -> bool:
    """True when the organisation has its own ceiling and has reached it.

    NULL means "no ceiling of its own" -- the deployment budget still applies.
    The column's comment in models.py has always said why this exists: one
    tenant burning the day's seconds must not drop every other tenant into
    replay mode. It was never read until now.
    """
    if org is None or org.daily_budget_seconds is None:
        return False
    return org_spent_today(db, org.id) >= org.daily_budget_seconds


def admin_actor(user: User) -> str:
    """Audit actor for an operator action. The id, not the email: the email is
    personal data and the audit log outlives the account."""
    return f"admin:{user.id}"


def summary_of(org: Organisation) -> dict[str, Any]:
    return {"id": str(org.id), "name": org.name, "active": org.active,
            "daily_budget_seconds": org.daily_budget_seconds,
            "created_at": org.created_at.isoformat()}
