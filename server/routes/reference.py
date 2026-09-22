"""Unauthenticated, stateless reads: is the service up, and is this string a
valid identifier. Nothing here touches a session or an organisation."""

from __future__ import annotations

from typing import Any, Final

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from server.config import Settings, get_settings
from server.http_guards import bad_request
from server.readback.solver import IBANGB, ISO, LUHN16, NHS, VIN

router = APIRouter()


# ------------------------------------------------------------------ health ---
@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Says which path the next session will take, because that is the one thing
    about this deployment that changes tonight.

    Unauthenticated, so it carries only what the consent screen reads. It used
    to publish `sessions_open` beside the known concurrency cap -- telling
    anyone the exact moment admission was one session from full, which is the
    timing a capacity-exhaustion attempt needs -- plus an in-memory record
    count and the fixture list. Tests read those from the process directly
    (`_running_sessions`, `_SESSIONS`, `fixture_dir()`), which is where an
    operator looking at load should read them too.
    """
    return {
        "ok": True,
        "live_capture": settings.live_capture,
        "replay_mode": settings.replay_mode,
        "consent_required": settings.consent_required,
        "consent_version": settings.consent_version,
    }


# ---------------------------------------------------------------- validate ---
# The five formats the solver can arbitrate, keyed by the ids the interface
# uses, each with the 0-indexed positions that hold its computed check.
VALIDATE_FORMATS: Final = {
    "iso6346": (ISO, (10,)),
    "iban": (IBANGB, (2, 3)),
    "vin": (VIN, (8,)),
    "nhs": (NHS, (9,)),
    "luhn": (LUHN16, (15,)),
}
VALIDATE_MAX_CHARS: Final = 64


class ValidateRequest(BaseModel):
    # Deliberately NOT `Field(max_length=...)`: a pydantic constraint answers
    # with FastAPI's wrapped `{"detail": [...]}`, which no client here reads
    # (see `_parse_limit`), and it would not stop the buffering either -- the
    # body is read in full before any field is validated. The length is checked
    # by hand below for the flat 400, and the BODY is bounded by the middleware
    # at the top of this file.
    format: str
    value: str


@router.post("/api/validate")
def validate_identifier(body: ValidateRequest) -> dict[str, Any]:
    """The formats reference's "try one": is this string a valid <format>, and
    if not, exactly where it fails -- the wrong length, a character the
    position cannot hold, or a check that does not agree.

    Stateless and unauthenticated on purpose: nothing is stored and nothing is
    read, and the arithmetic is the solver's own (server/readback/solver.py),
    so the page can never call a string valid that the pipeline would refuse.
    Spaces and hyphens are dropped and letters upper-cased first, because that
    is how identifiers are typed. Bounded input; an unknown format is the same
    flat 400 as every other bad request here.
    """
    entry = VALIDATE_FORMATS.get(body.format)
    if entry is None:
        raise bad_request(
            "unknown_format",
            f"format must be one of {', '.join(sorted(VALIDATE_FORMATS))}.",
        )
    if len(body.value) > VALIDATE_MAX_CHARS:
        raise bad_request(
            "value_too_long",
            f"value must be at most {VALIDATE_MAX_CHARS} characters.",
        )
    fmt, check_pos = entry
    normalised = "".join(ch for ch in body.value.upper() if ch.isalnum())
    length_ok = len(normalised) == fmt.length
    positions = []
    for i, ch in enumerate(normalised):
        in_range = i < fmt.length
        positions.append({
            "index": i,
            "char": ch,
            "allowed": bool(in_range and ch in fmt.A(i)),
            "check": i in check_pos,
        })
    alphabet_ok = length_ok and all(p["allowed"] for p in positions)
    checksum_ok = bool(fmt.ok(normalised)) if alphabet_ok else None
    return {
        "format": body.format,
        "normalised": normalised,
        "expected_length": fmt.length,
        "length_ok": length_ok,
        "positions": positions,
        "check_positions": list(check_pos),
        "checksum_ok": checksum_ok,
        "valid": bool(length_ok and alphabet_ok and checksum_ok),
    }
