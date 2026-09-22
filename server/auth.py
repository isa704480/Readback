"""Signup, login, and the password check the signup form leans on.

Three decisions in here are worth reading before changing anything.

**One token type, one verifier.** An earlier project in this lineage grew a
second token shape and a `verify()` that demanded fields only the first shape
carried, so every session token was rejected by a function that looked correct.
There is exactly one token format here (`rb1.<payload>.<signature>`) and exactly
one function that checks it. If a second kind of token is ever needed it gets its
own prefix and its own verifier, and neither may fall through to the other.

**The password meter is not a permission slip.** `/api/auth/check-password`
exists so the signup form can tell somebody their password is weak *before* they
submit it. It is advisory. `/api/auth/signup` re-runs the identical check and is
the only opinion that decides anything, so a client that skips the advisory call
or lies about its result changes nothing. The rule is both halves at once: never
trust a check the client performed, and never make the user discover a rejection
only at submit. This file is where the two are kept consistent.

**Nothing is sent to a language model.** The strength verdict is arithmetic
(server/password.py). The only external call is Have I Been Pwned over
k-anonymity: the first five hex characters of the SHA-1 go out, the match happens
in this process, and the service never learns the password. Handing a plaintext
credential to a model API to be scored would be a worse answer to an easier
question, and it would put the password in somebody else's request log.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from typing import Any, Final

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as SASession
from starlette.concurrency import run_in_threadpool

from server import password as pw
from server import ratelimit as rl
from server.config import Settings, get_settings
from server.db import get_db
from server.models import Organisation, User, utcnow

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# =============================================================================
# password hashing
# =============================================================================
# PBKDF2-HMAC-SHA256 from the standard library. Not argon2 or scrypt, and the
# reason is deployability rather than preference: argon2 needs a compiled wheel,
# and a dependency that fails to build on the deploy host the night before a demo
# is a worse security outcome than a slower KDF that is already installed.
# 600,000 iterations is the OWASP 2023 figure for this construction.
#
# The cost is real and is paid on every login. It is also the timing defence: an
# unknown address is verified against a dummy hash so that "no such user" and
# "wrong password" cost the same wall-clock.
PBKDF2_ALGO: Final = "pbkdf2_sha256"
PBKDF2_ITERATIONS: Final = 600_000
SALT_BYTES: Final = 16


def hash_password(plain: str) -> str:
    """`algo$iterations$salt_hex$hash_hex` -- printable, so the column is text.

    A bytes column would be rejected by the guard at the foot of models.py, and
    that guard is right: a column that can hold bytes is one somebody eventually
    puts audio in.
    """
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_ALGO}${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """Constant-time compare. Returns False for anything malformed rather than
    raising: a corrupt row must fail closed, not 500."""
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$", 3)
        if algo != PBKDF2_ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", plain.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


# A real verifier for an address that does not exist, so the failing path does
# the same work as the succeeding one. Computed once at import, not per request.
_DUMMY_HASH: Final = hash_password(secrets.token_urlsafe(32))


# =============================================================================
# tokens
# =============================================================================
TOKEN_PREFIX: Final = "rb1"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _secret(settings: Settings) -> bytes:
    return settings.session_secret.get_secret_value().encode("utf-8")


def issue_token(user: User, settings: Settings) -> str:
    """Signed, not encrypted. The payload is readable by anyone holding the
    token, which is fine: it holds two opaque ids and an expiry, and the holder
    is the person those ids belong to."""
    payload = {
        "uid": str(user.id),
        "oid": str(user.organisation_id),
        "exp": int(time.time()) + settings.session_ttl_hours * 3600,
    }
    body = _b64u(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64u(hmac.new(_secret(settings), body.encode("ascii"), hashlib.sha256).digest())
    return f"{TOKEN_PREFIX}.{body}.{sig}"


def verify_token(token: str, settings: Settings) -> dict[str, Any] | None:
    """The ONLY token verifier. Returns the payload, or None for every failure.

    One return value for "expired", "tampered with", "wrong shape" and "not
    ours", because the caller's response to all four is identical and a caller
    that can tell them apart will eventually tell an attacker which it was.
    """
    try:
        prefix, body, sig = token.split(".", 2)
    except ValueError:
        return None
    if prefix != TOKEN_PREFIX:
        return None

    try:
        expected = _b64u(hmac.new(_secret(settings), body.encode("ascii"),
                                  hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
    except (UnicodeEncodeError, TypeError, ValueError):
        # A non-ASCII token is not ours. It is also not a 500: this function's
        # contract is one None for every way a token can be wrong.
        return None

    try:
        payload = json.loads(_b64u_decode(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        expires = int(payload.get("exp", 0))
    except (TypeError, ValueError):
        return None
    if expires < int(time.time()):
        return None
    return payload


# =============================================================================
# request and response shapes
# =============================================================================
# Email is validated with a regex rather than pydantic's EmailStr, which needs
# the email-validator package. One more wheel on the deploy host to reject "a@b"
# is not worth it, and the address is proved by nothing here anyway since there
# is no confirmation mail. What this catches is a typo before it becomes an
# account nobody can sign in to.
EMAIL_RE: Final = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
MAX_EMAIL: Final = 320
MAX_NAME: Final = 120


class SignupBody(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME)
    company: str = Field(min_length=1, max_length=MAX_NAME)
    email: str = Field(min_length=3, max_length=MAX_EMAIL)
    password: str = Field(min_length=1, max_length=pw.MAX_LENGTH)


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=MAX_EMAIL)
    password: str = Field(min_length=1, max_length=pw.MAX_LENGTH)


class CheckBody(BaseModel):
    password: str = Field(default="", max_length=pw.MAX_LENGTH)
    email: str = Field(default="", max_length=MAX_EMAIL)
    name: str = Field(default="", max_length=MAX_NAME)
    company: str = Field(default="", max_length=MAX_NAME)


def check_payload(verdict: pw.Verdict) -> dict[str, Any]:
    """The PasswordCheck shape web/src/lib/api.ts declares.

    `breached` is a BOOLEAN on the wire while server/password.py counts, and the
    difference is deliberate. The count is the most persuasive thing on the
    screen, so it travels inside the server's own sentence in `problems`, where
    PasswordStrength.breachCopy() promotes it typographically. Sending the number
    twice would let the sentence and the field disagree after a translation.
    """
    return {
        "ok": verdict.ok,
        "score": verdict.score,
        "label": verdict.label,
        "problems": verdict.problems,
        "suggestions": verdict.suggestions,
        "breached": bool(verdict.breached),
        "breach_checked": verdict.breach_checked,
    }


def account_payload(user: User) -> dict[str, Any]:
    org = user.organisation
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "organisation": {
            "id": str(org.id),
            "name": org.name,
            # There is no billing tier in this system, so this is a constant
            # rather than a lookup. It is a label, not a measurement; when plans
            # exist it becomes a column and this line changes.
            "plan": "hackathon",
        },
    }


# =============================================================================
# helpers
# =============================================================================
def _ip_key(request: Request, settings: Settings) -> str:
    """Rate-limit key over a salted hash, never the address itself (ARCH 3.11).

    The salt rotates daily in deployment, which bounds re-identification to the
    same 24 hours as ip_hash_retention_hours. Counting is all this needs; knowing
    which machine it was is not.
    """
    raw = rl.client_ip(request)
    salt = settings.ip_hash_salt.get_secret_value()
    return hashlib.sha256(f"{salt}:{raw}".encode("utf-8")).hexdigest()[:32]


def _too_many(exc: rl.RateLimited) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"error": "rate_limited", "message": exc.message},
        headers={"Retry-After": str(exc.retry_after)},
    )


def _weak_password(verdict: pw.Verdict) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "error": "weak_password",
            "message": verdict.problems[0] if verdict.problems else "Choose a stronger password.",
            "password_check": check_payload(verdict),
        },
    )


_UNAUTHORIZED: Final = {"error": "unauthorized", "message": "Sign in to continue."}


def _bearer(authorization: str | None) -> str:
    """The token out of an Authorization header, or "" for anything else."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def resolve_user(token: str, db: SASession, settings: Settings) -> User | None:
    """Token to User, or None for every failure.

    One resolver, shared by both dependencies below, for the same reason there is
    one `verify_token`: two functions that answer "who is this" eventually answer
    it differently, and the one that is wrong is the one nobody is looking at.
    The dependencies differ only in what they do with None.
    """
    payload = verify_token(token, settings) if token else None
    if payload is None:
        return None
    try:
        uid = uuid.UUID(str(payload.get("uid")))
    except (ValueError, TypeError):
        return None
    user = db.get(User, uid)
    if user is None or not user.active:
        # A token for a deleted or suspended account is not a valid session even
        # though its signature is perfectly good.
        return None
    return user


async def current_user(
    authorization: str | None = Header(default=None),
    db: SASession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """Bearer token to User. 401 for every failure, with no hint about which."""
    user = resolve_user(_bearer(authorization), db, settings)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_UNAUTHORIZED)
    return user


async def optional_user(
    authorization: str | None = Header(default=None),
    db: SASession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | None:
    """The same check as `current_user`, except that failing it is not an error.

    Two routes need this and only two: `/api/demo/replay` and
    `/api/session/start`. DESIGN-BRIEF 4.5 says a judge arrives at a link with no
    call to listen to and gets the experience in one click, so those routes must
    work with no account at all. They must ALSO attribute the work to the caller
    when there is one, because a session written against the demo tenant is a
    session its owner can never see.

    **An unusable token degrades to anonymous rather than 401, deliberately.** A
    token buys exactly one thing on these two routes -- attribution -- and never
    access: an unidentified caller is served the identical demo the anonymous
    visitor is served, and reading those rows back still goes through
    `current_user`, which rejects the same bad token with a 401. So failing open
    here hands nobody a row they could not already have. Failing closed, by
    contrast, would mean a stale token left in localStorage silently breaks the
    twenty-second demo for the person least equipped to clear it.
    """
    return resolve_user(_bearer(authorization), db, settings)


# =============================================================================
# routes
# =============================================================================
@router.post("/check-password")
async def check_password_route(
    body: CheckBody,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Advisory only. Creates nothing, decides nothing.

    Rate limited per IP because it is an unauthenticated endpoint that makes an
    outbound HTTP request; without a limit it is a free proxy to HIBP and a way
    to make this server the origin of somebody else's traffic.
    """
    try:
        rl.check(rl.PASSWORD_CHECK_PER_IP, _ip_key(request, settings),
                 "Too many password checks. Wait a moment and try again.")
    except rl.RateLimited as exc:
        raise _too_many(exc) from None

    if not body.password:
        return check_payload(pw.Verdict(ok=False, score=0, label="Very weak"))

    verdict = await pw.full_check(
        body.password, email=body.email, name=body.name, company=body.company
    )
    return check_payload(verdict)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup_route(
    body: SignupBody,
    request: Request,
    db: SASession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        rl.check(rl.SIGNUP_PER_IP, _ip_key(request, settings),
                 "Too many accounts created from here. Try again later.")
    except rl.RateLimited as exc:
        raise _too_many(exc) from None

    # The operator's abuse switch (platform_state, set from the admin panel).
    # Checked before the password work, so a paused signup costs no KDF.
    from server import platform_state  # late: keeps auth importable on its own
    if platform_state.controls(db)["signups_paused"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "signups_paused",
                    "message": "New accounts are paused right now. Try again later."},
        )

    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_email",
                    "message": "That does not look like an email address."},
        )

    # The authoritative check. The form has almost certainly asked already; this
    # is the one that decides, because a client's opinion about its own password
    # is not evidence.
    verdict = await pw.full_check(
        body.password, email=email, name=body.name, company=body.company
    )
    if not verdict.ok:
        raise _weak_password(verdict)

    # 409 on a duplicate address is an account-enumeration oracle, and it is a
    # deliberate trade rather than an oversight. The alternative -- accept the
    # signup and mail the existing owner -- needs an outbound mail path this
    # system does not have, and silently pretending to create an account leaves
    # the person staring at a dashboard that never fills. So the address is
    # confirmed, and SIGNUP_PER_IP at 5/hour is what stops the response being
    # mined at scale. Revisit when there is mail.
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "email_taken",
                    "message": "There is already an account for that address."},
        )

    # Every signup creates its own organisation. "One account per company,
    # everyone else joins by invitation" is the product's promise and the
    # invitation path is not built yet, so joining an existing company is
    # deliberately impossible rather than half-possible by matching on a name two
    # unrelated firms could share.
    org = Organisation(name=body.company.strip())
    # PBKDF2 at 600k iterations is ~220 ms of CPU. In an async handler that is
    # 220 ms during which the single worker's loop serves nobody -- every
    # socket, every partial. The threadpool releases the GIL for it.
    password_hash = await run_in_threadpool(hash_password, body.password)
    user = User(
        organisation=org,
        email=email,
        name=body.name.strip(),
        password_hash=password_hash,
        role="owner",
        last_login_at=utcnow(),
    )
    db.add(org)
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"token": issue_token(user, settings), "account": account_payload(user)}


@router.post("/login")
async def login_route(
    body: LoginBody,
    request: Request,
    db: SASession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    email = body.email.strip().lower()
    ip_key = _ip_key(request, settings)

    # Both limits, defending against different attacks. Per-IP stops one machine
    # working through a list; per-email stops a distributed run against one known
    # account, where every request arrives from a different address.
    try:
        rl.check(rl.LOGIN_PER_IP, ip_key, "Too many sign-in attempts. Wait a few minutes.")
        rl.check(rl.LOGIN_PER_EMAIL, hashlib.sha256(email.encode("utf-8")).hexdigest()[:32],
                 "Too many sign-in attempts for that address. Wait a few minutes.")
    except rl.RateLimited as exc:
        raise _too_many(exc) from None

    user = db.scalar(select(User).where(User.email == email))

    # Verify against a dummy hash when there is no such user, so the two failures
    # cost the same wall-clock. Skipping it turns login timing into an
    # account-existence oracle that no rate limit hides.
    stored = user.password_hash if user is not None else _DUMMY_HASH
    # Off the event loop, for the reason given at signup.
    ok = await run_in_threadpool(verify_password, body.password, stored)

    if user is None or not ok or not user.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized",
                    "message": "That email and password do not match."},
        )

    user.last_login_at = utcnow()
    db.commit()
    db.refresh(user)
    return {"token": issue_token(user, settings), "account": account_payload(user)}


@router.get("/me")
async def me_route(user: User = Depends(current_user)) -> dict[str, Any]:
    return {"account": account_payload(user)}
