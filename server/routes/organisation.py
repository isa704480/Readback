"""What an organisation configures and reads about itself: its usage against
the deployment's budget, the vocabulary pack pushed to the recogniser, and the
part catalogue that vouches for checksum-less part numbers.

Every read and write is scoped by the verified token's organisation. The two
readers the session builders need -- `vocabulary_for` and `catalogue_index` --
are public for that reason and take the organisation explicitly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Final

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as SASession

from server import audit, auth, budget
from server.config import Settings, get_settings
from server.db import get_db
from server.http_guards import bad_request
from server.models import CataloguePart, Capture, Session, User, VocabularyTerm
from server.models import Organisation as OrganisationRow
from server.readback.catalogue import CatalogueIndex
from server.readback.catalogue import normalise as catalogue_normalise
from server.readback.catalogue import signature as catalogue_signature

router = APIRouter()


# ------------------------------------------------------------------- usage ---
@router.get("/api/usage")
def usage(user: User = Depends(auth.current_user),
          db: SASession = Depends(get_db),
          settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """What the account screen's usage panel could only estimate until now.

    Two blocks, because ARCH 3.11's budget is a property of the DEPLOYMENT --
    one daily ceiling on socket-seconds across every tenant, the kill switch
    that stops a surprise invoice -- while what a team leader wants to see is
    their own organisation's spend and count. Reporting the deployment figure
    alone would let one tenant infer another's activity from the remainder;
    reporting only the organisation's would hide the ceiling that will refuse
    their next call. So both are here, and the organisation block is scoped
    by the verified token like every other read.

    Seconds are socket-seconds (billed_seconds x sockets), computed the same
    way the admission gate computes them, never stored twice.
    """
    org_id = user.organisation_id
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                  microsecond=0)
    remaining, alarm, exhausted = budget.today(db, settings)
    spent_today = budget.spent_socket_seconds(db, midnight)

    socket_seconds = func.coalesce(func.sum(Session.billed_seconds * Session.sockets), 0)
    org_today = int(db.scalar(
        select(socket_seconds).where(Session.organisation_id == org_id,
                                     Session.started_at >= midnight)) or 0)
    org_total = int(db.scalar(
        select(socket_seconds).where(Session.organisation_id == org_id)) or 0)
    sessions_today = int(db.scalar(
        select(func.count()).select_from(Session)
        .where(Session.organisation_id == org_id, Session.started_at >= midnight)) or 0)
    sessions_total = int(db.scalar(
        select(func.count()).select_from(Session)
        .where(Session.organisation_id == org_id)) or 0)
    captures_total = int(db.scalar(
        select(func.count()).select_from(Capture)
        .join(Session, Capture.session_id == Session.id)
        .where(Session.organisation_id == org_id)) or 0)
    org_row = db.get(OrganisationRow, org_id)

    return {
        "day_started_at": midnight.isoformat(),
        "deployment": {
            "daily_budget_seconds": settings.daily_budget_seconds,
            "spent_today_seconds": spent_today,
            "remaining_seconds": remaining,
            "alarm": alarm,
            "exhausted": exhausted,
            "session_socket_seconds": settings.session_socket_seconds,
            "cap_seconds": settings.session_cap_seconds,
            "live_capture": settings.live_capture,
            "replay_mode": settings.replay_mode,
        },
        "organisation": {
            "daily_budget_seconds": org_row.daily_budget_seconds if org_row else None,
            "seconds_today": org_today,
            "seconds_total": org_total,
            "sessions_today": sessions_today,
            "sessions_total": sessions_total,
            "captures_total": captures_total,
        },
    }


# -------------------------------------------------------------- vocabulary ---
# The recogniser's documented caps on keyterms_prompt (stream/source.py), which
# the account screen mirrors. Enforced here so an over-long pack is a flat 400
# at save time rather than a socket close mid-call.
VOCAB_MAX_TERMS: Final = 100
VOCAB_MAX_CHARS: Final = 50


class VocabularyRequest(BaseModel):
    terms: list[str]


def _clean_terms(raw: list[str]) -> list[str]:
    """Trim, collapse inner whitespace, drop empties, dedupe case-insensitively
    keeping the first spelling and the operator's order."""
    out: list[str] = []
    seen: set[str] = set()
    for term in raw:
        cleaned = " ".join(str(term).split())
        if not cleaned:
            continue
        if len(cleaned) > VOCAB_MAX_CHARS:
            raise bad_request(
                "term_too_long",
                f"a term is {len(cleaned)} characters; the cap is {VOCAB_MAX_CHARS}.",
            )
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    if len(out) > VOCAB_MAX_TERMS:
        raise bad_request(
            "too_many_terms",
            f"{len(out)} terms; the cap is {VOCAB_MAX_TERMS}.",
        )
    return out


def vocabulary_for(db: SASession, org_id: uuid.UUID) -> list[str]:
    """The organisation's pack, in the order it was saved. Read by the session
    manager on every start and by the account screen."""
    return list(db.scalars(
        select(VocabularyTerm.term)
        .where(VocabularyTerm.organisation_id == org_id)
        .order_by(VocabularyTerm.position, VocabularyTerm.term)))


def _vocabulary_payload(terms: list[str]) -> dict[str, Any]:
    return {"terms": terms, "max_terms": VOCAB_MAX_TERMS, "max_chars": VOCAB_MAX_CHARS}


@router.get("/api/vocabulary")
def get_vocabulary(user: User = Depends(auth.current_user),
                   db: SASession = Depends(get_db)) -> dict[str, Any]:
    """ARCH 3.9: the organisation's own words for the recogniser."""
    return _vocabulary_payload(vocabulary_for(db, user.organisation_id))


@router.put("/api/vocabulary")
def put_vocabulary(body: VocabularyRequest,
                   user: User = Depends(auth.current_user),
                   db: SASession = Depends(get_db)) -> dict[str, Any]:
    """Replace the pack. Whole-list PUT rather than per-term POST/DELETE
    because the pack is small, ordered, and the order is what the keyterm
    budget spends first -- a list is the honest unit. Takes effect on the
    organisation's NEXT session: a running socket keeps the pack it started
    with (SourceConfig is frozen for the reason it gives).
    """
    terms = _clean_terms(body.terms)
    org_id = user.organisation_id
    db.execute(delete(VocabularyTerm).where(VocabularyTerm.organisation_id == org_id))
    for i, term in enumerate(terms):
        db.add(VocabularyTerm(organisation_id=org_id, term=term, position=i))
    audit.record(db, audit.VOCABULARY_SET, organisation_id=org_id,
                 session_id=None, actor="human", detail={"terms": len(terms)})
    db.commit()
    return _vocabulary_payload(terms)


# --------------------------------------------------------------- catalogue ---
CATALOGUE_MAX_ROWS: Final = 500
CATALOGUE_MAX_SKU_CHARS: Final = 64


class CataloguePartIn(BaseModel):
    sku: str
    description: str = ""


class CatalogueRequest(BaseModel):
    parts: list[CataloguePartIn]


def catalogue_index(db: SASession, org_id: uuid.UUID) -> CatalogueIndex:
    """The organisation's catalogue as the runner matches against it, read once
    per session. Never another organisation's: this is what vouches."""
    return CatalogueIndex((r.sku, r.description) for r in db.scalars(
        select(CataloguePart).where(CataloguePart.organisation_id == org_id)))


def _catalogue_payload(db: SASession, org_id: uuid.UUID) -> dict[str, Any]:
    rows = list(db.scalars(select(CataloguePart)
                           .where(CataloguePart.organisation_id == org_id)
                           .order_by(CataloguePart.sku)))
    return {
        "parts": [{"sku": r.sku, "description": r.description} for r in rows],
        "max_rows": CATALOGUE_MAX_ROWS,
        "max_sku_chars": CATALOGUE_MAX_SKU_CHARS,
    }


@router.get("/api/catalogue")
def get_catalogue(user: User = Depends(auth.current_user),
                  db: SASession = Depends(get_db)) -> dict[str, Any]:
    """ARCH 3.9: the organisation's part catalogue, which stands in for a check
    digit. A row here is exactly what the runner will vouch for on the
    `catalogue` format -- for this organisation's sessions and no one else's.
    """
    return _catalogue_payload(db, user.organisation_id)


@router.put("/api/catalogue")
def put_catalogue(body: CatalogueRequest,
                  user: User = Depends(auth.current_user),
                  db: SASession = Depends(get_db)) -> dict[str, Any]:
    """Replace the catalogue. Whole-list, like the vocabulary, and for the same
    reason. Takes effect on the next session."""
    kept: dict[str, tuple[str, str]] = {}
    for part in body.parts:
        sku = " ".join(part.sku.split())
        key = catalogue_normalise(sku)
        if not key:
            continue
        if len(sku) > CATALOGUE_MAX_SKU_CHARS:
            raise bad_request(
                "sku_too_long",
                f"a part number is {len(sku)} characters; the cap is {CATALOGUE_MAX_SKU_CHARS}.",
            )
        if key in kept:
            continue
        kept[key] = (sku, " ".join(part.description.split())[:255])
    if len(kept) > CATALOGUE_MAX_ROWS:
        raise bad_request(
            "too_many_parts",
            f"{len(kept)} parts; the cap is {CATALOGUE_MAX_ROWS}.",
        )
    org_id = user.organisation_id
    db.execute(delete(CataloguePart).where(CataloguePart.organisation_id == org_id))
    for sku, description in kept.values():
        db.add(CataloguePart(organisation_id=org_id, sku=sku, description=description,
                             rhyme_signature=catalogue_signature(sku)))
    audit.record(db, audit.CATALOGUE_SET, organisation_id=user.organisation_id,
                 session_id=None, actor="human", detail={"parts": len(kept)})
    db.commit()
    return _catalogue_payload(db, org_id)
