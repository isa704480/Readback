"""The platform admin panel's API: /api/admin/*. See docs/ADMIN.md.

Who: a signed-in user with a `platform_admin` row, granted only by
`python -m server.admin_cli`. Anyone else -- including every organisation's own
owner -- gets 404, so the panel's existence is not advertised to a tenant.

What, grouped the way an operator reaches for it:

  overview      one screen: tenants, sessions, spend against budget, quality
  quality       how right the agent is -- traffic metrics, and a benchmark
                against recorded truth (server/quality.py)
  organisations list, drill down, suspend / reinstate, per-tenant daily budget
  users         list, disable / enable
  live          sessions running now, and force-stop
  audit         the append-only log, filterable
  controls      runtime switches: pause live capture, pause sign-ups
  system        configuration and health, never a secret

Every write is audited with actor "admin:<user id>". Reads are not: the audit
log records what changed, and an operator reading a list changes nothing.
"""

from __future__ import annotations

import asyncio
import platform as py_platform
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Final

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session as SASession

from server import audit, auth, budget, platform_state, quality
from server.config import Settings, get_settings
from server.db import get_db
from server.models import (
    AuditEvent,
    Capture,
    Organisation,
    PlatformAdmin,
    Session,
    User,
)
from server.stream.replay import fixture_dir

router = APIRouter(prefix="/api/admin")

PROCESS_STARTED: Final = time.time()
LIST_LIMIT_MAX: Final = 200
BUDGET_MAX_SECONDS: Final = 10_000_000


def _not_found() -> HTTPException:
    return HTTPException(404, {"error": "not_found", "message": "Not found."})


def platform_admin(user: User = Depends(auth.current_user),
                   db: SASession = Depends(get_db)) -> User:
    """404, not 403, for everyone who is not an operator: a tenant probing
    /api/admin learns nothing about whether it exists."""
    if not platform_state.is_admin(db, user):
        raise _not_found()
    return user


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _limit(raw: int | None, default: int = 50) -> int:
    if raw is None:
        return default
    if not 1 <= raw <= LIST_LIMIT_MAX:
        raise HTTPException(400, {"error": "invalid_limit",
                                  "message": f"limit must be between 1 and {LIST_LIMIT_MAX}."})
    return raw


def _days(raw: int) -> int:
    if not 1 <= raw <= 90:
        raise HTTPException(400, {"error": "invalid_days",
                                  "message": "days must be between 1 and 90."})
    return raw


def _live_registry():
    """The in-memory session registry lives in main.py with the lifecycle that
    owns it. Imported late: main.py includes this router, so a module-level
    import would be a cycle."""
    from server import main

    return main


# ------------------------------------------------------------------- me ----

@router.get("/me")
def me(admin: User = Depends(platform_admin)) -> dict[str, Any]:
    """200 means "show the admin link". Anything else means do not."""
    return {"email": admin.email, "name": admin.name}


# ------------------------------------------------------------- overview ----

@router.get("/overview")
def overview(admin: User = Depends(platform_admin), db: SASession = Depends(get_db),
             settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    del admin
    now = datetime.now(timezone.utc)
    remaining, alarm, exhausted = budget.today(db, settings)
    main = _live_registry()
    q = quality.metrics(db, _since(7))
    orgs_total = db.scalar(select(func.count()).select_from(Organisation)) or 0
    orgs_suspended = db.scalar(select(func.count()).select_from(Organisation)
                               .where(Organisation.active.is_(False))) or 0
    return {
        "organisations": {"total": orgs_total, "suspended": orgs_suspended},
        "users": {
            "total": db.scalar(select(func.count()).select_from(User)) or 0,
            "disabled": db.scalar(select(func.count()).select_from(User)
                                  .where(User.active.is_(False))) or 0,
            "admins": db.scalar(select(func.count()).select_from(PlatformAdmin)) or 0,
            "signed_in_7d": db.scalar(select(func.count()).select_from(User)
                                      .where(User.last_login_at >= now - timedelta(days=7))) or 0,
        },
        "sessions": {
            "last_24h": db.scalar(select(func.count()).select_from(Session)
                                  .where(Session.started_at >= now - timedelta(days=1))) or 0,
            "last_7d": db.scalar(select(func.count()).select_from(Session)
                                 .where(Session.started_at >= now - timedelta(days=7))) or 0,
            "running_now": main._running_sessions(settings),
            "capacity": settings.max_concurrent_sessions,
        },
        "budget": {
            "daily_seconds": settings.daily_budget_seconds,
            "spent_today_seconds": budget.spent_socket_seconds(db, platform_state.midnight_utc()),
            "remaining_seconds": remaining,
            "alarm": alarm,
            "exhausted": exhausted,
        },
        "quality_7d": {
            "captures": q["captures"]["total"],
            "silent_commit_rate": q["rates"]["silent_commit_rate"],
            "asked_rate": q["rates"]["asked_rate"],
            "handover_rate": q["rates"]["handover_rate"],
            "needed_rate": q["questions"]["needed_rate"],
            "latency_p50_ms": q["latency_ms"]["p50"],
        },
        "benchmark": _last_benchmark_summary(),
        "controls": platform_state.controls(db),
        "live_capture": settings.live_capture,
    }


# -------------------------------------------------------------- quality ----

@router.get("/quality")
def quality_report(days: int = 7, org: uuid.UUID | None = None, source: str | None = None,
                   admin: User = Depends(platform_admin),
                   db: SASession = Depends(get_db)) -> dict[str, Any]:
    del admin
    if source not in (None, "live", "replay"):
        raise HTTPException(400, {"error": "invalid_source",
                                  "message": "source must be live or replay."})
    return quality.metrics(db, _since(_days(days)), org_id=org, source=source)


_BENCHMARK: dict[str, Any] = {"result": None, "ran_at": None}
_BENCHMARK_LOCK = asyncio.Lock()


def _last_benchmark_summary() -> dict[str, Any] | None:
    r = _BENCHMARK["result"]
    if r is None:
        return None
    return {"ran_at": _BENCHMARK["ran_at"], "fixtures": r["fixtures"],
            "correct": r["correct"], "accuracy": r["accuracy"],
            "silent_wrong": r["silent_wrong"]}


@router.get("/quality/benchmark")
def benchmark_last(admin: User = Depends(platform_admin)) -> dict[str, Any]:
    del admin
    return {"ran_at": _BENCHMARK["ran_at"], "result": _BENCHMARK["result"]}


@router.post("/quality/benchmark")
async def benchmark_run(admin: User = Depends(platform_admin),
                        db: SASession = Depends(get_db)) -> dict[str, Any]:
    """Replay every fixture against its recorded truth. Instant clock, no
    socket, no database writes from the pipeline -- it costs nothing but CPU,
    and one run at a time."""
    if _BENCHMARK_LOCK.locked():
        raise HTTPException(409, {"error": "benchmark_running",
                                  "message": "A benchmark is already running."})
    async with _BENCHMARK_LOCK:
        result = await quality.run_benchmark()
    _BENCHMARK.update(result=result, ran_at=datetime.now(timezone.utc).isoformat())
    audit.record(db, audit.ADMIN_BENCHMARK_RUN, organisation_id=None,
                 actor=platform_state.admin_actor(admin),
                 detail={"fixtures": result["fixtures"], "correct": result["correct"],
                         "silent_wrong": result["silent_wrong"]})
    db.commit()
    return {"ran_at": _BENCHMARK["ran_at"], "result": result}


# -------------------------------------------------------- organisations ----

def _org_rows(db: SASession, org_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """Per-organisation counts in four grouped queries, not four per row."""
    if not org_ids:
        return {}
    week = _since(7)
    midnight = platform_state.midnight_utc()
    users = dict(db.execute(select(User.organisation_id, func.count())
                            .where(User.organisation_id.in_(org_ids))
                            .group_by(User.organisation_id)).all())
    sessions = dict(db.execute(select(Session.organisation_id, func.count())
                               .where(Session.organisation_id.in_(org_ids),
                                      Session.started_at >= week)
                               .group_by(Session.organisation_id)).all())
    last = dict(db.execute(select(Session.organisation_id, func.max(Session.started_at))
                           .where(Session.organisation_id.in_(org_ids))
                           .group_by(Session.organisation_id)).all())
    spend = dict(db.execute(
        select(Session.organisation_id,
               func.coalesce(func.sum(Session.billed_seconds * Session.sockets), 0))
        .where(Session.organisation_id.in_(org_ids), Session.started_at >= midnight)
        .group_by(Session.organisation_id)).all())
    captures = dict(db.execute(
        select(Session.organisation_id, func.count(Capture.id))
        .join(Capture, Capture.session_id == Session.id)
        .where(Session.organisation_id.in_(org_ids), Session.started_at >= week)
        .group_by(Session.organisation_id)).all())
    return {oid: {"users": int(users.get(oid, 0)), "sessions_7d": int(sessions.get(oid, 0)),
                  "captures_7d": int(captures.get(oid, 0)),
                  "spent_today_seconds": int(spend.get(oid, 0)),
                  "last_session_at": last[oid].isoformat() if last.get(oid) else None}
            for oid in org_ids}


@router.get("/organisations")
def organisations(q: str | None = None, limit: int | None = None,
                  admin: User = Depends(platform_admin),
                  db: SASession = Depends(get_db)) -> dict[str, Any]:
    del admin
    stmt = select(Organisation).order_by(Organisation.created_at.desc())
    if q:
        stmt = stmt.where(Organisation.name.ilike(f"%{q.strip()}%"))
    orgs = list(db.scalars(stmt.limit(_limit(limit))))
    counts = _org_rows(db, [o.id for o in orgs])
    return {"organisations": [{**platform_state.summary_of(o), **counts[o.id]} for o in orgs]}


def _org_or_404(db: SASession, org_id: uuid.UUID) -> Organisation:
    org = db.get(Organisation, org_id)
    if org is None:
        raise HTTPException(404, {"error": "not_found", "message": "No such organisation."})
    return org


@router.get("/organisations/{org_id}")
def organisation_detail(org_id: uuid.UUID, admin: User = Depends(platform_admin),
                        db: SASession = Depends(get_db)) -> dict[str, Any]:
    del admin
    org = _org_or_404(db, org_id)
    members = list(db.scalars(select(User).where(User.organisation_id == org.id)
                              .order_by(User.created_at)))
    recent = list(db.scalars(select(Session).where(Session.organisation_id == org.id)
                             .order_by(Session.started_at.desc()).limit(20)))
    return {
        **platform_state.summary_of(org),
        **_org_rows(db, [org.id])[org.id],
        "spent_today_seconds": platform_state.org_spent_today(db, org.id),
        "members": [_user_row(db, u, org) for u in members],
        "recent_sessions": [{
            "id": str(s.id), "started_at": s.started_at.isoformat(),
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "source": s.source, "end_reason": s.end_reason,
            "billed_seconds": s.billed_seconds, "regime": s.confidence_regime,
        } for s in recent],
        "quality_30d": quality.metrics(db, _since(30), org_id=org.id),
    }


class SuspendBody(BaseModel):
    reason: str = Field(default="", max_length=200)


@router.post("/organisations/{org_id}/suspend")
async def suspend(org_id: uuid.UUID, body: SuspendBody | None = None,
                  admin: User = Depends(platform_admin),
                  db: SASession = Depends(get_db)) -> dict[str, Any]:
    """New sessions and demo replays are refused (main.py), and anything the
    organisation has running is stopped now -- a suspension that let a live
    socket keep billing would not be one."""
    body = body or SuspendBody()
    org = _org_or_404(db, org_id)
    main = _live_registry()
    stopped = 0
    for sid, live in list(main._SESSIONS.items()):
        row = db.get(Session, sid)
        if live.running and row is not None and row.organisation_id == org.id:
            if await main.terminate_live(sid):
                stopped += 1
                if row.ended_at is None:
                    row.ended_at = datetime.now(timezone.utc)
                    row.end_reason = "user"
    org.active = False
    audit.record(db, audit.ADMIN_ORG_SUSPENDED, organisation_id=org.id,
                 actor=platform_state.admin_actor(admin),
                 detail={"reason": body.reason[:200], "sessions_stopped": stopped})
    db.commit()
    return {**platform_state.summary_of(org), "sessions_stopped": stopped}


@router.post("/organisations/{org_id}/reinstate")
def reinstate(org_id: uuid.UUID, admin: User = Depends(platform_admin),
              db: SASession = Depends(get_db)) -> dict[str, Any]:
    org = _org_or_404(db, org_id)
    org.active = True
    audit.record(db, audit.ADMIN_ORG_REINSTATED, organisation_id=org.id,
                 actor=platform_state.admin_actor(admin), detail={})
    db.commit()
    return platform_state.summary_of(org)


class BudgetBody(BaseModel):
    # None clears the organisation's own ceiling; the deployment's still applies.
    daily_budget_seconds: int | None = Field(default=None, ge=0, le=BUDGET_MAX_SECONDS)


@router.put("/organisations/{org_id}/budget")
def set_budget(org_id: uuid.UUID, body: BudgetBody, admin: User = Depends(platform_admin),
               db: SASession = Depends(get_db)) -> dict[str, Any]:
    org = _org_or_404(db, org_id)
    before = org.daily_budget_seconds
    org.daily_budget_seconds = body.daily_budget_seconds
    audit.record(db, audit.ADMIN_ORG_BUDGET_SET, organisation_id=org.id,
                 actor=platform_state.admin_actor(admin),
                 detail={"before": before, "after": body.daily_budget_seconds})
    db.commit()
    return platform_state.summary_of(org)


# ---------------------------------------------------------------- users ----

def _user_row(db: SASession, u: User, org: Organisation | None = None) -> dict[str, Any]:
    org = org or u.organisation
    return {"id": str(u.id), "email": u.email, "name": u.name, "role": u.role,
            "active": u.active, "created_at": u.created_at.isoformat(),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "organisation": {"id": str(org.id), "name": org.name, "active": org.active},
            "is_admin": db.get(PlatformAdmin, u.id) is not None}


@router.get("/users")
def users(q: str | None = None, limit: int | None = None,
          admin: User = Depends(platform_admin),
          db: SASession = Depends(get_db)) -> dict[str, Any]:
    del admin
    stmt = select(User).order_by(User.created_at.desc())
    if q:
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(User.email.ilike(needle), User.name.ilike(needle)))
    return {"users": [_user_row(db, u) for u in db.scalars(stmt.limit(_limit(limit)))]}


def _set_user_active(user_id: uuid.UUID, active: bool, admin: User, db: SASession) -> dict[str, Any]:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, {"error": "not_found", "message": "No such user."})
    if target.id == admin.id:
        raise HTTPException(400, {"error": "cannot_disable_self",
                                  "message": "You cannot disable your own account."})
    if not active and db.get(PlatformAdmin, target.id) is not None:
        # An operator is removed with the CLI, which is audited as a revoke;
        # disabling one from the panel would leave a grant nobody can see used.
        raise HTTPException(400, {"error": "target_is_admin",
                                  "message": "Revoke admin with server.admin_cli first."})
    target.active = active
    audit.record(db, audit.ADMIN_USER_ENABLED if active else audit.ADMIN_USER_DISABLED,
                 organisation_id=target.organisation_id,
                 actor=platform_state.admin_actor(admin), detail={"user_id": str(target.id)})
    db.commit()
    return _user_row(db, target)


@router.post("/users/{user_id}/disable")
def disable_user(user_id: uuid.UUID, admin: User = Depends(platform_admin),
                 db: SASession = Depends(get_db)) -> dict[str, Any]:
    """Takes effect on the user's next request: every token is re-checked
    against `User.active` (auth.resolve_user)."""
    return _set_user_active(user_id, False, admin, db)


@router.post("/users/{user_id}/enable")
def enable_user(user_id: uuid.UUID, admin: User = Depends(platform_admin),
                db: SASession = Depends(get_db)) -> dict[str, Any]:
    return _set_user_active(user_id, True, admin, db)


# ----------------------------------------------------------------- live ----

@router.get("/sessions/live")
def live_sessions(admin: User = Depends(platform_admin), db: SASession = Depends(get_db)
                  ) -> dict[str, Any]:
    del admin
    main = _live_registry()
    out = []
    for sid, live in list(main._SESSIONS.items()):
        if not live.running:
            continue
        row = db.get(Session, sid)
        org = db.get(Organisation, row.organisation_id) if row else None
        out.append({
            "id": str(sid),
            "organisation": {"id": str(org.id), "name": org.name} if org else None,
            "source": row.source if row else None,
            "started_at": row.started_at.isoformat() if row else None,
            "running_seconds": int(time.monotonic() - live.opened_at),
            "audio_connected": live.producer is not None,
        })
    return {"sessions": out}


@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: uuid.UUID, admin: User = Depends(platform_admin),
                       db: SASession = Depends(get_db)) -> dict[str, Any]:
    """Force-stop any organisation's session. Ends it with reason "user" --
    the schema has no operator reason and a CHECK constraint guards the list --
    and the audit row says who actually stopped it."""
    main = _live_registry()
    row = db.get(Session, session_id)
    if row is None:
        raise HTTPException(404, {"error": "not_found", "message": "No such session."})
    stopped = await main.terminate_live(session_id)
    if row.ended_at is None:
        row.ended_at = datetime.now(timezone.utc)
        row.end_reason = "user"
    audit.record(db, audit.ADMIN_SESSION_STOPPED, organisation_id=row.organisation_id,
                 session_id=row.id, actor=platform_state.admin_actor(admin),
                 detail={"was_running": stopped})
    db.commit()
    return {"ok": True, "was_running": stopped}


# ---------------------------------------------------------------- audit ----

@router.get("/audit")
def audit_log(action: str | None = None, org: uuid.UUID | None = None,
              before_seq: int | None = None, limit: int | None = None,
              admin: User = Depends(platform_admin),
              db: SASession = Depends(get_db)) -> dict[str, Any]:
    """Newest first, paged by `seq` (the log's own monotonic key). `action` may
    be an exact action or a prefix ending in "." -- "admin." is every operator
    action."""
    del admin
    stmt = select(AuditEvent).order_by(AuditEvent.seq.desc())
    if action:
        stmt = stmt.where(AuditEvent.action.startswith(action) if action.endswith(".")
                          else AuditEvent.action == action)
    if org is not None:
        stmt = stmt.where(AuditEvent.organisation_id == org)
    if before_seq is not None:
        stmt = stmt.where(AuditEvent.seq < before_seq)
    n = _limit(limit, 100)
    rows = list(db.scalars(stmt.limit(n)))
    return {
        "events": [{"seq": e.seq, "at": e.at.isoformat(), "action": e.action, "actor": e.actor,
                    "organisation_id": str(e.organisation_id) if e.organisation_id else None,
                    "session_id": str(e.session_id) if e.session_id else None,
                    "detail": e.detail} for e in rows],
        "next_before_seq": rows[-1].seq if len(rows) == n else None,
        "actions": sorted(audit.ACTIONS),
    }


# ------------------------------------------------------------- controls ----

@router.get("/controls")
def get_controls(admin: User = Depends(platform_admin),
                 db: SASession = Depends(get_db)) -> dict[str, bool]:
    del admin
    return platform_state.controls(db)


@router.put("/controls")
def put_controls(body: dict[str, bool], admin: User = Depends(platform_admin),
                 db: SASession = Depends(get_db)) -> dict[str, bool]:
    unknown = sorted(set(body) - set(platform_state.CONTROL_DEFAULTS))
    if unknown or not body:
        raise HTTPException(400, {"error": "unknown_control",
                                  "message": "Controls are: "
                                  + ", ".join(sorted(platform_state.CONTROL_DEFAULTS)) + "."})
    before = platform_state.controls(db)
    actor = platform_state.admin_actor(admin)
    for key, value in body.items():
        platform_state.set_control(db, key, bool(value), actor)
        if before[key] != bool(value):
            audit.record(db, audit.ADMIN_CONTROL_SET, organisation_id=None, actor=actor,
                         detail={"key": key, "value": bool(value)})
    db.commit()
    return platform_state.controls(db)


# --------------------------------------------------------------- system ----

@router.get("/system")
def system(admin: User = Depends(platform_admin), db: SASession = Depends(get_db),
           settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """What this deployment is configured to do. Presence of secrets, never
    their values."""
    del admin
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001 -- the answer is "not ok", whatever the cause
        db_ok = False
    main = _live_registry()
    return {
        "environment": settings.environment,
        "python": py_platform.python_version(),
        "uptime_seconds": int(time.time() - PROCESS_STARTED),
        "database": {"dialect": db.get_bind().dialect.name, "ok": db_ok},
        "assemblyai_key_present": settings.live_capture_possible,
        "live_capture": settings.live_capture,
        "replay_mode": settings.replay_mode,
        "consent_required": settings.consent_required,
        "consent_version": settings.consent_version,
        "session_cap_seconds": settings.session_cap_seconds,
        "max_concurrent_sessions": settings.max_concurrent_sessions,
        "sessions_running": main._running_sessions(settings),
        "sessions_in_memory": len(main._SESSIONS),
        "daily_budget_seconds": settings.daily_budget_seconds,
        "trusted_proxy_hops": settings.trusted_proxy_hops,
        "api_docs": settings.api_docs,
        "cors_origins": settings.cors_origin_list,
        "fixtures": len(list(fixture_dir().glob("*.json"))),
    }
