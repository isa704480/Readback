"""The HTTP and WebSocket surface.

Six routes and one of them is the product today. `/api/demo/replay` runs a named
fixture through `runner.run_session` -- the same function, the same tape, the
same detector, the same solver, the same decider, the same event stream the live
socket will drive this evening. The only difference between the two paths is
which `TranscriptSource` is constructed, which is one line, in one place, behind
`settings.live_capture`. That is the seam the whole build was arranged around and
this file is where it finally has to be a single expression rather than a plan.

Two gates stand in front of everything, in this order and never the other way
round.

**Consent (3.12).** The session row is created by the consent gate, not by the
socket, which is why `consent_version`, `consent_at` and `disclosure_played` are
NOT NULL in models.py: a session that exists is a session that consented, and
there is no ordering in which audio is captured against a row that does not yet
record consent. There is no jurisdiction toggle and there will not be one.

**Budget (3.11).** Billing is WebSocket wall-clock including silence, and
unclosed sessions are the documented first cause of surprise charges. The gate
is computed in socket-seconds rather than dollars because socket-seconds are what
`Termination.session_duration_seconds` reports and what a nightly reconciliation
can check. Exhausting it does not fail the request -- it drops the session to
replay, which is the same state a missing API key produces, so the fallback path
is the one exercised on every run today rather than the branch nobody tried.

**Tenancy.** Every row the two creating routes write -- the session, its
captures, and every audit event describing it -- belongs to
`acting_organisation(user)`: the signed-in organisation when there is one, the
demo organisation when there is not. The bearer token on `/api/demo/replay` and
`/api/session/start` is therefore OPTIONAL and decides attribution only, never
access, because 4.5 requires the demo to survive a visitor with no account. Both
routes hard-coded `DEMO_ORG_ID` until this rule existed, which is why
`GET /api/sessions` -- correctly scoped to the caller's organisation -- returned
an empty list to every human who had ever signed in.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

from fastapi import Body, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.orm import Session as SASession

from server import audit, auth, llm
from server.config import Settings, get_settings
from server.db import create_all, get_db, get_sessionmaker
from server.models import (
    AuditEvent,
    Capture,
    Organisation,
    QuestionEvent,
    Session,
    User,
    utcnow,
)
from server.pipeline import events as ev
from server.pipeline.detector import FORMAT_TOKENS, State
from server.pipeline.detector import configuration as detector_configuration
from server.pipeline.runner import Question, RunSummary, RunnerConfig, run_session
from server.pipeline.store import SqlCaptureStore, apply_observations
from server.models import Organisation as OrganisationRow
from server.models import VocabularyTerm
from server.readback.solver import IBANGB, ISO, LUHN16, NHS, VIN
from server.stream.replay import Fixture, ReplaySource, fixture_dir
from server.stream.source import SourceClosed, SourceConfig

# The organisation every demo session belongs to. A fixed UUID rather than a
# lookup by name: the row is created once at startup and referenced by id
# everywhere else, so a second worker racing the first inserts the same primary
# key and loses the race harmlessly instead of creating a duplicate tenant.
DEMO_ORG_ID: Final = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEMO_ORG_NAME: Final = "Readback demo"


def acting_organisation(user: User | None) -> uuid.UUID:
    """Whose work this is: the signed-in organisation, or the demo one.

    The single rule for every row these routes write -- the session, its
    captures, and every audit event describing it. Until this existed, both
    creating routes hard-coded `DEMO_ORG_ID`, which meant `GET /api/sessions`
    (correctly organisation-scoped) returned an empty list to every human who
    had ever signed in: 1010 sessions and 692 captures were all filed under the
    demo tenant and nothing was ever written against a real account. The
    endpoint was right and the data path was wrong.

    Anonymity is a first-class caller here, not a failure -- see
    `auth.optional_user` for why an unusable token lands in this branch too.
    """
    return user.organisation_id if user is not None else DEMO_ORG_ID


# --------------------------------------------------------------- rate limit --
@dataclass
class _Window:
    """Fixed windows, in process. Honest about what that means: with more than
    one worker each holds its own counters and the effective limit multiplies by
    the worker count. For a single-instance hackathon deployment that is the
    correct amount of machinery, and moving to Redis is a swap of the two dict
    operations below."""

    seconds: int
    counts: dict[tuple[str, int], int] = field(default_factory=dict)

    def hit(self, key: str) -> int:
        bucket = int(time.time() // self.seconds)
        self.counts = {k: v for k, v in self.counts.items() if k[1] == bucket}
        self.counts[(key, bucket)] = self.counts.get((key, bucket), 0) + 1
        return self.counts[(key, bucket)]


_PER_HOUR = _Window(3600)
_PER_DAY = _Window(86_400)
_ADMISSIONS = _Window(60)


def ip_hash(request: Request | None, settings: Settings) -> str | None:
    """Salted hash of the caller's address. The address itself never leaves this
    function, and the salt rotates daily so re-identification is bounded to one
    day -- the same window as `ip_hash_retention_hours`, by design."""
    if request is None or request.client is None:
        return None
    salt = settings.ip_hash_salt.get_secret_value()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return hashlib.sha256(f"{salt}:{day}:{request.client.host}".encode()).hexdigest()


# ------------------------------------------------------------ live sessions --
@dataclass
class LiveSession:
    """One running pipeline, and the two things the browser talks to it about.

    Held in memory only. It carries an `EventStream` and a table of unanswered
    questions; it carries no tape, no words and no audio, because ARCH 3.9 lists
    all three under never-stored and a process-lifetime cache is storage.
    """

    session_id: uuid.UUID
    stream: ev.EventStream
    source: Any = None
    task: asyncio.Task[RunSummary] | None = None
    pending: dict[str, asyncio.Future[str]] = field(default_factory=dict)
    summary: RunSummary | None = None
    opened_at: float = field(default_factory=time.monotonic)
    # The one `/audio` socket allowed to feed this session, while it is open.
    # See `session_audio`: two microphones into one upstream socket is garbage
    # in, and it is also how one tab would inject audio into another's call.
    producer: WebSocket | None = None

    @property
    def running(self) -> bool:
        """Is this session still capable of spending money?

        The distinction between running and merely remembered is the whole of the
        concurrency gate. `run_session` closes its event stream in a `finally`, so
        a closed stream means the pipeline has stopped -- no socket, no billing,
        no capture slot. A session that is remembered afterwards is a *record*
        being read, and a record must not occupy a slot: without this, three demo
        replays exhausted `max_concurrent_sessions` and every subsequent
        `/api/session/start` returned 503 until the process was restarted.
        """
        return not self.stream.closed

    def answerer(self):
        """The runner awaits this; `POST .../answer` resolves it."""

        async def _ask(q: Question) -> str | None:
            loop = asyncio.get_running_loop()
            fut: asyncio.Future[str] = loop.create_future()
            self.pending[q.question_id] = fut
            try:
                return await fut
            except asyncio.CancelledError:
                # The runner's answer timeout expired. Not an error: 4.7 counts
                # an unanswered question against the budget and re-asks, which
                # is a decision the loop makes, not an exception it handles.
                return None
            finally:
                self.pending.pop(q.question_id, None)

        return _ask

    def answer(self, question_id: str, text: str) -> bool:
        fut = self.pending.get(question_id)
        if fut is None or fut.done():
            return False
        fut.set_result(text)
        return True


_SESSIONS: dict[uuid.UUID, LiveSession] = {}

# How many finished sessions stay readable after their pipeline stops. They
# cannot be dropped at the moment they end -- `/api/sessions/{id}` and the
# WebSocket backlog both read `live.stream.history`, and a judge who opens the
# page after clicking replay would get an empty stream -- and they cannot be kept
# forever, because `_SESSIONS` is process memory bounded by nothing else. Twenty
# is more than a demo run shows and keeps the retained histories in megabytes.
FINISHED_RETAINED: Final = 20


# Grace on top of the per-session hard cap before an admitted session that never
# started capturing is treated as abandoned. `POST /api/session/start` admits a
# session and the browser is supposed to open its socket next; a browser that
# closes the tab instead would otherwise hold a capture slot for the lifetime of
# the process. One cap-length of grace, so a session that is merely running long
# is never mistaken for one that never began.
ABANDON_GRACE_S: Final = 60


def _running_sessions(settings: Settings) -> int:
    """Sessions that can still spend money. See `LiveSession.running`."""
    cutoff = settings.session_cap_seconds + ABANDON_GRACE_S
    return sum(
        1 for s in _SESSIONS.values()
        if s.running and not (s.task is None and time.monotonic() - s.opened_at > cutoff)
    )


def _reap_finished() -> None:
    """Drop the oldest finished sessions past the retention count.

    Insertion order is start order, so the first finished entries found are the
    oldest. Running sessions are never touched however old they are: the thing
    that ends a running session is the cap, the source, or a human, and none of
    them is a dictionary size.
    """
    finished = [sid for sid, s in _SESSIONS.items() if not s.running]
    for sid in finished[: max(0, len(finished) - FINISHED_RETAINED)]:
        _SESSIONS.pop(sid, None)


# ------------------------------------------------------------------- app -----
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    create_all()
    factory = get_sessionmaker()
    with factory() as db:
        if db.get(Organisation, DEMO_ORG_ID) is None:
            db.add(Organisation(id=DEMO_ORG_ID, name=DEMO_ORG_NAME,
                                daily_budget_seconds=settings.daily_budget_seconds))
            db.commit()
        # ARCH 4.6's online pseudo-count is folded into the confusion table here
        # and nowhere else. A request handler mutating `solver.W` would change
        # one caller's posterior from inside another caller's call.
        apply_observations(db)
    yield
    for live in list(_SESSIONS.values()):
        if live.task is not None and not live.task.done():
            live.task.cancel()


app = FastAPI(title="Readback", version="0.1.0", lifespan=lifespan)

# The browser refuses a cross-origin request before the route is ever reached,
# so a missing CORS layer presents as "the endpoint does not exist" in a console
# and gets diagnosed as a backend bug. Explicit origins, never "*": every
# authenticated call carries a bearer token, and a wildcard origin with
# credentials is a combination browsers reject anyway.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    # So a 429 can actually be obeyed: without this the browser hides the header
    # from the page and the client cannot tell the user how long to wait.
    expose_headers=["Retry-After"],
    max_age=600,
)

app.include_router(auth.router)


@app.exception_handler(HTTPException)
async def _flat_errors(request: Request, exc: HTTPException) -> JSONResponse:
    """Error bodies the client can actually read.

    FastAPI wraps every detail in {"detail": ...}. web/src/lib/session.ts reads
    `error` and `message` at the TOP level, and PasswordStrength reads
    `password_check` there too -- so a dict detail is emitted flat, and a plain
    string one is given the same two keys while keeping `detail` for anything
    that still expects it. One shape for every failure, or each screen invents
    its own unwrapping and they drift.
    """
    if isinstance(exc.detail, dict):
        body: dict[str, Any] = dict(exc.detail)
    else:
        body = {
            "error": "http_error",
            "message": str(exc.detail),
            "detail": exc.detail,
        }
    return JSONResponse(status_code=exc.status_code, content=body,
                        headers=dict(exc.headers or {}))


# ------------------------------------------------------------------ health ---
@app.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Says which path the next session will take, because that is the one thing
    about this deployment that changes tonight."""
    return {
        "ok": True,
        "live_capture": settings.live_capture,
        "replay_mode": settings.replay_mode,
        "consent_required": settings.consent_required,
        "consent_version": settings.consent_version,
        "fixtures": sorted(p.stem for p in fixture_dir().glob("*.json")),
        # Two numbers, because they answer different questions. `sessions_open`
        # is what the concurrency gate counts -- pipelines that can still spend
        # money. `sessions_retained` is how many finished records are still
        # readable in memory, which is a memory fact and not an admission one.
        "sessions_open": _running_sessions(settings),
        "sessions_retained": len(_SESSIONS),
    }


# ----------------------------------------------------------------- schemas ---
class Consent(BaseModel):
    """The checkbox, and the version of the words it was next to.

    A boolean alone would be unauditable: "did this session consent" is a
    question about *what they were told*, and the disclosure text changes.
    """

    accepted: bool = False
    version: str | None = None
    disclosure_played: bool = False


class StartRequest(BaseModel):
    consent: Consent = Field(default_factory=Consent)
    demo_mode: bool = True
    ab: bool = False               # 3.11: the A/B demo runs two sockets
    channel: str = "clean"


class StartResponse(BaseModel):
    session_id: uuid.UUID
    live_capture: bool
    consent_version: str
    cap_seconds: int
    sockets: int
    budget_remaining_seconds: int


class AnswerRequest(BaseModel):
    question_id: str
    text: str | None = None
    choice: int | None = None      # index into the question's `choices`


class ReplayRequest(BaseModel):
    fixture: str
    session_id: uuid.UUID | None = None
    speed: float = 0.0             # 0 = as fast as the CPU allows
    wait: bool | None = None       # None: wait iff the replay is instant
    answers: dict[str, str] = Field(default_factory=dict)
    # ARCHITECTURE 7's dead-man timer, exposed because a demo without a human in
    # the room needs it shorter than a call with one does.
    answer_timeout_ms: int | None = None


# ------------------------------------------------------------------ gates ----
def spent_socket_seconds(db: SASession, since: datetime) -> int:
    """Socket-seconds billed today. The product is computed, never stored --
    models.py keeps `billed_seconds` and `sockets` apart so that a reconciliation
    has one place to be wrong instead of two."""
    total = db.scalar(
        select(func.coalesce(func.sum(Session.billed_seconds * Session.sockets), 0))
        .where(Session.started_at >= since)
    )
    return int(total or 0)


def _budget(db: SASession, settings: Settings) -> tuple[int, bool, bool]:
    """(remaining socket-seconds, alarm, exhausted)."""
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                  microsecond=0)
    spent = spent_socket_seconds(db, midnight)
    remaining = settings.daily_budget_seconds - spent
    return (max(0, remaining),
            spent >= settings.budget_alarm_seconds,
            remaining < settings.session_socket_seconds)


@app.post("/api/session/start", response_model=StartResponse)
def session_start(body: StartRequest, request: Request = None,  # type: ignore[assignment]
                  user: User | None = Depends(auth.optional_user),
                  db: SASession = Depends(get_db),
                  settings: Settings = Depends(get_settings)) -> StartResponse:
    """Consent gate, then budget gate, then a session id. In that order.

    The order is not stylistic. A budget check that ran first would tell an
    unconsented caller how much credit the deployment has left, and would create
    a code path in which the system reasons about a session before it is allowed
    to exist.

    The token is optional and only decides *attribution*: with one the session
    and every audit event describing it belong to the caller's organisation,
    without one they belong to the demo tenant, and no gate above changes either
    way.
    """
    org_id = acting_organisation(user)
    if settings.consent_required and not body.consent.accepted:
        audit.record(db, audit.SESSION_REFUSED, organisation_id=org_id,
                     actor="api", detail={"reason": "consent_not_given"})
        db.commit()
        raise HTTPException(403, "consent is required before a session can start")

    salted = ip_hash(request, settings)
    if salted is not None:
        if _PER_HOUR.hit(salted) > settings.per_ip_per_hour:
            raise HTTPException(429, "per-hour limit reached for this address")
        if _PER_DAY.hit(salted) > settings.per_ip_per_day:
            raise HTTPException(429, "per-day limit reached for this address")
    if _ADMISSIONS.hit("global") > settings.admissions_per_minute:
        # 3.11: a queue demos better than a failure. 503 with a Retry-After is
        # the HTTP spelling of the queue screen.
        raise HTTPException(503, "admission queue full, retry in about 20 seconds",
                            headers={"Retry-After": "20"})
    _reap_finished()
    if _running_sessions(settings) >= settings.max_concurrent_sessions:
        raise HTTPException(503, "all capture slots are busy",
                            headers={"Retry-After": "20"})

    remaining, alarm, exhausted = _budget(db, settings)
    if alarm:
        audit.record(db, audit.BUDGET_ALARM, organisation_id=org_id,
                     actor="api", detail={"remaining_socket_seconds": remaining})
    sockets = settings.demo_sockets if body.ab else 1
    live = settings.live_capture and not exhausted
    if exhausted:
        audit.record(db, audit.BUDGET_EXHAUSTED, organisation_id=org_id,
                     actor="api", detail={"remaining_socket_seconds": remaining})
        audit.record(db, audit.REPLAY_ENTERED, organisation_id=org_id,
                     actor="api", detail={"reason": "daily_budget"})

    row = Session(
        id=uuid.uuid4(), organisation_id=org_id,
        started_at=utcnow(), sockets=sockets, channel=body.channel,
        source="live" if live else "replay",
        consent_version=body.consent.version or settings.consent_version,
        consent_at=utcnow(), disclosure_played=body.consent.disclosure_played,
        ip_hash=salted,
        ip_hash_purge_after=(utcnow() + timedelta(hours=settings.ip_hash_retention_hours)
                             if salted else None),
        demo_mode=body.demo_mode,
    )
    db.add(row)
    audit.record(db, audit.CONSENT_GRANTED, organisation_id=org_id,
                 session_id=row.id, actor="human",
                 detail={"version": row.consent_version,
                         "disclosure_played": row.disclosure_played})
    audit.record(db, audit.SESSION_STARTED, organisation_id=org_id,
                 session_id=row.id, actor="api",
                 detail={"source": row.source, "sockets": sockets,
                         "demo_mode": row.demo_mode})
    db.commit()

    _SESSIONS[row.id] = LiveSession(session_id=row.id, stream=ev.EventStream())
    return StartResponse(
        session_id=row.id, live_capture=live,
        consent_version=row.consent_version,
        cap_seconds=settings.session_cap_seconds, sockets=sockets,
        budget_remaining_seconds=remaining,
    )


# ------------------------------------------------------------------- live ----
@app.websocket("/api/session/{session_id}/live")
async def session_live(websocket: WebSocket, session_id: uuid.UUID) -> None:
    """The event stream, verbatim.

    Backlog first, then live. A judge who opens the page after clicking replay
    still sees the beats that explain it, and a UI written against this socket
    needs no special case for "joined late" -- the two are the same list.
    """
    await websocket.accept()
    live = _SESSIONS.get(session_id)
    if live is None:
        await websocket.send_json({"type": ev.ERROR, "seq": -1, "at_ms": 0,
                                   "wall_ms": 0, "message": "unknown session"})
        await websocket.close(code=4404)
        return
    try:
        async for event in live.stream.subscribe():
            await websocket.send_json(event.as_dict())
    except WebSocketDisconnect:
        return
    finally:
        # Never close the pipeline because a viewer left. The session is a call
        # that is still happening; the browser is a window onto it.
        with_close = websocket.client_state.name == "CONNECTED"
        if with_close:
            await websocket.close()


# ------------------------------------------------------------ audio ingress --
# The browser's microphone, arriving as binary PCM16 frames. Everything below
# exists so that the thing on the other end of `LiveSource.send_audio` can be a
# real person's voice rather than a fixture -- and so that the constraints the
# upstream socket enforces by closing (frame size, pacing) are enforced HERE,
# with a close code the browser can explain, rather than discovered as a 3007
# from AssemblyAI with no audio to show for it.

# PCM16 signed little-endian, mono, 16 kHz: 16 000 samples/s x 2 bytes = 32 000
# bytes per second = 32 bytes per millisecond. Every duration in this section is
# derived from this one number.
AUDIO_BYTES_PER_MS: Final = 32

# Upstream frame window, measured on the live socket: 50-1000 ms per binary
# frame, sent no faster than real time; outside that the socket closes with
# 3007. The ingress re-chunks to a fixed 100 ms frame -- comfortably inside the
# window, and short enough that it adds at most one frame of latency to the
# ~2 s interrupt budget (3.6).
AUDIO_CHUNK_MS: Final = 100
AUDIO_CHUNK_BYTES: Final = AUDIO_CHUNK_MS * AUDIO_BYTES_PER_MS
# The shortest frame upstream accepts. A tail shorter than this at Terminate is
# dropped: 49 ms of audio cannot carry a character and cannot be sent.
AUDIO_MIN_FRAME_BYTES: Final = 50 * AUDIO_BYTES_PER_MS
# How far ahead of real time a producer may run before it is refused. Two
# seconds absorbs network jitter and a modest client-side batch, and bounds the
# only place audio ever rests in this process at 64 KB per session.
AUDIO_MAX_AHEAD_MS: Final = 2000
AUDIO_MAX_AHEAD_BYTES: Final = AUDIO_MAX_AHEAD_MS * AUDIO_BYTES_PER_MS

# How long to wait for the pipeline to write its last row after the upstream
# socket has been told to Terminate. The runner ends on its own once the frame
# stream ends; this is the backstop, not the mechanism.
PIPELINE_DRAIN_S: Final = 5.0

# WebSocket subprotocols. The browser's WebSocket API cannot set a header, and a
# bearer token in a query string is a bearer token in every access log between
# here and the browser -- so the token travels as a second offered subprotocol,
# `readback.token.<token>`, beside `readback.audio`, and the server selects
# `readback.audio` in reply. A non-browser client may send Authorization instead.
AUDIO_SUBPROTOCOL: Final = "readback.audio"
AUDIO_TOKEN_PROTOCOL_PREFIX: Final = "readback.token."

# Close codes on the audio socket. 4xxx is the range RFC 6455 leaves to the
# application, and the last three digits are the HTTP status they rhyme with so
# a client can explain each one without a table.
WS_AUDIO_TERMINATED: Final = 1000       # the client sent Terminate; clean end
WS_AUDIO_BAD_MESSAGE: Final = 4400      # a text frame that is not a known control
WS_AUDIO_NO_CONSENT: Final = 4403       # consent withdrawn or never recorded
WS_AUDIO_UNKNOWN: Final = 4404          # no such session for this organisation
WS_AUDIO_CAP: Final = 4408              # session_cap_seconds reached (3.11)
WS_AUDIO_NOT_LIVE: Final = 4409         # a replay session has no microphone
WS_AUDIO_ENDED: Final = 4410            # the session already ended
WS_AUDIO_BAD_FRAME: Final = 4422        # a binary frame that is not PCM16
WS_AUDIO_BUSY: Final = 4423             # this session already has a producer
WS_AUDIO_TOO_FAST: Final = 4429         # more than AUDIO_MAX_AHEAD_MS ahead of real time
WS_AUDIO_UPSTREAM: Final = 4502         # AssemblyAI could not be reached, or the pipeline failed


@dataclass(frozen=True, slots=True)
class _Outcome:
    """How an audio socket ended, and whether a close frame is still owed."""

    code: int
    reason: str
    send_close: bool = True
    # What the session row should say. None leaves the runner's own verdict.
    end_reason: str | None = None
    # The client said Terminate: what is buffered is the end of a sentence and
    # goes out at real time before the socket closes. Its own flag, because the
    # code alone cannot say -- a client that closes with 1000 is also 1000.
    drain: bool = False


class _IngressStore(SqlCaptureStore):
    """The session store, with the ingress allowed to name the end reason.

    `run_session` writes `end_reason` from what it observed, and what it observes
    when the ingress terminates the upstream socket is simply that the frame
    stream ended -- "complete". The reason it ended is known one layer up: the
    cap fired, or the human hung up. Overriding at `finish` rather than after it
    keeps one `session.ended` audit row per session, carrying the true reason.
    """

    end_reason: str | None = None

    def finish(self, *, billed_seconds: int, end_reason: str,
               confidence_regime: str | None) -> None:
        super().finish(billed_seconds=billed_seconds,
                       end_reason=self.end_reason or end_reason,
                       confidence_regime=confidence_regime)


def _ws_token(websocket: WebSocket) -> str:
    """The bearer token, from the header or the token subprotocol. "" if none."""
    token = auth._bearer(websocket.headers.get("authorization"))
    if token:
        return token
    for offered in websocket.headers.get("sec-websocket-protocol", "").split(","):
        offered = offered.strip()
        if offered.startswith(AUDIO_TOKEN_PROTOCOL_PREFIX):
            return offered[len(AUDIO_TOKEN_PROTOCOL_PREFIX):]
    return ""


def _control_kind(text: str | None) -> str | None:
    """The `type` of a JSON control frame, or None for anything else."""
    if not text:
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    kind = payload.get("type")
    return kind if isinstance(kind, str) else None


class _AudioIngress:
    """One browser microphone feeding one upstream socket, at real time.

    Three tasks race: the receiver (frames in), the pacer (frames out) and the
    cap timer; the pipeline task is a fourth participant so that the session
    ending on its own -- upstream inactivity, `/stop` -- ends the ingress too.
    Whichever finishes first names the outcome, the rest are cancelled, and the
    caller terminates upstream regardless.

    THE ONLY PLACE AUDIO RESTS. `_buf` holds at most `AUDIO_MAX_AHEAD_BYTES`
    of PCM between arrival and `send_audio`, lives exactly as long as the
    socket, and is cleared on the way out. Nothing here writes bytes anywhere
    else -- not a file, not a log, not a queue -- and nothing may.
    """

    def __init__(self, websocket: WebSocket, source: Any, *,
                 cap_seconds: float, opened_at: float) -> None:
        self.ws = websocket
        self.source = source
        self.cap_seconds = cap_seconds
        self.opened_at = opened_at
        self.bytes_in = 0
        self.bytes_out = 0
        self._buf = bytearray()
        self._ready = asyncio.Event()
        self._final = False
        self._next_send_at: float | None = None

    # -- frames in ---------------------------------------------------------
    async def _receive(self) -> _Outcome:
        while True:
            try:
                msg = await self.ws.receive()
            except (WebSocketDisconnect, RuntimeError):
                return _Outcome(1006, "client disconnected", send_close=False,
                                end_reason="user")
            if msg["type"] == "websocket.disconnect":
                return _Outcome(int(msg.get("code") or 1005), "client disconnected",
                                send_close=False, end_reason="user")
            data = msg.get("bytes")
            if data is not None:
                if not data:
                    continue
                if len(data) % 2:
                    # A 16-bit sample cannot be split. Half a sample is not an
                    # off-by-one, it is a client sending something else.
                    return _Outcome(WS_AUDIO_BAD_FRAME,
                                    "not PCM16: odd byte count", end_reason="user")
                self.bytes_in += len(data)
                self._buf += data
                if len(self._buf) > AUDIO_MAX_AHEAD_BYTES:
                    return _Outcome(WS_AUDIO_TOO_FAST,
                                    f"audio more than {AUDIO_MAX_AHEAD_MS} ms ahead "
                                    "of real time", end_reason="user")
                self._ready.set()
                continue
            kind = _control_kind(msg.get("text"))
            if kind == "Terminate":
                # The pacer sends what is left, at real time, then stops.
                self._final = True
                self._ready.set()
                return _Outcome(WS_AUDIO_TERMINATED, "terminated", end_reason="user",
                                drain=True)
            if kind == "KeepAlive":
                # Accepted so a client heartbeat is not an error, and NOT
                # forwarded: live.py never sends KeepAlive upstream by policy --
                # in an always-listening product it is the burn-credits button.
                continue
            return _Outcome(WS_AUDIO_BAD_MESSAGE, "unexpected message",
                            end_reason="user")

    # -- frames out --------------------------------------------------------
    async def _forward(self, chunk: bytes) -> None:
        """Send one frame, no earlier than real time allows.

        A frame may go out the moment it is complete, but never before the
        previous frame's audio has actually elapsed on this clock. The schedule
        is `max(previous + its duration, now)`, so a client at real time pays
        nothing but its own jitter, a client that pauses does not bank credit
        it could later spend in a burst, and upstream never sees audio faster
        than the wall clock it bills by.
        """
        now = time.monotonic()
        send_at = now if self._next_send_at is None else max(self._next_send_at, now)
        # Looped, not a single sleep: the loop's timer may fire a clock
        # resolution early (about 16 ms on Windows), and "no earlier than" is
        # the property, so it is checked against the clock rather than trusted.
        while now < send_at:
            await asyncio.sleep(send_at - now)
            now = time.monotonic()
        await self.source.send_audio(chunk)
        self.bytes_out += len(chunk)
        self._next_send_at = send_at + len(chunk) / AUDIO_BYTES_PER_MS / 1000.0

    async def _drain(self, *, final: bool) -> None:
        # Peek, send, then delete: a cancellation during the paced sleep must
        # leave the frame in the buffer, not lose it.
        while len(self._buf) >= AUDIO_CHUNK_BYTES:
            await self._forward(bytes(self._buf[:AUDIO_CHUNK_BYTES]))
            del self._buf[:AUDIO_CHUNK_BYTES]
        if final and len(self._buf) >= AUDIO_MIN_FRAME_BYTES:
            await self._forward(bytes(self._buf))
            self._buf.clear()

    async def _pace(self) -> _Outcome:
        try:
            while True:
                await self._ready.wait()
                await self._drain(final=self._final)
                if self._final:
                    return _Outcome(WS_AUDIO_TERMINATED, "terminated", end_reason="user")
                if len(self._buf) < AUDIO_CHUNK_BYTES:
                    self._ready.clear()
        except SourceClosed:
            return _Outcome(WS_AUDIO_ENDED, "session ended")
        except Exception as exc:
            # The type, never the message (3.9): an upstream error can quote
            # the frame it rejected.
            return _Outcome(WS_AUDIO_UPSTREAM, f"upstream failed: {type(exc).__name__}",
                            end_reason="error")

    # -- the clock ---------------------------------------------------------
    async def _cap(self) -> _Outcome:
        remaining = self.cap_seconds - (time.monotonic() - self.opened_at)
        if remaining > 0:
            await asyncio.sleep(remaining)
        return _Outcome(WS_AUDIO_CAP, "session cap reached", end_reason="cap")

    # -- the race ----------------------------------------------------------
    async def run(self, pipeline: asyncio.Task[Any]) -> _Outcome:
        recv = asyncio.ensure_future(self._receive())
        pace = asyncio.ensure_future(self._pace())
        cap = asyncio.ensure_future(self._cap())
        try:
            done, _ = await asyncio.wait({recv, pace, cap, pipeline},
                                         return_when=asyncio.FIRST_COMPLETED)
            if cap in done:
                outcome = cap.result()
            elif recv in done:
                outcome = recv.result()
            elif pace in done:
                outcome = pace.result()
            else:
                outcome = _pipeline_outcome(pipeline)
            if outcome.drain:
                # The human finished a sentence: the pacer sends the end of it
                # at real time and returns on its own. Bounded, because the
                # buffer never holds more than AUDIO_MAX_AHEAD_MS.
                try:
                    await asyncio.wait_for(asyncio.shield(pace),
                                           AUDIO_MAX_AHEAD_MS / 1000.0 + 1.0)
                except (asyncio.TimeoutError, Exception):
                    pass
        finally:
            for task in (recv, pace, cap):
                if not task.done():
                    task.cancel()
            await asyncio.gather(recv, pace, cap, return_exceptions=True)
            self._buf.clear()
        return outcome


def _pipeline_outcome(pipeline: asyncio.Task[Any]) -> _Outcome:
    if pipeline.cancelled():
        return _Outcome(WS_AUDIO_ENDED, "session stopped")
    if pipeline.exception() is not None:
        return _Outcome(WS_AUDIO_UPSTREAM,
                        f"pipeline failed: {type(pipeline.exception()).__name__}")
    return _Outcome(WS_AUDIO_ENDED, "session ended")


@app.websocket("/api/session/{session_id}/audio")
async def session_audio(websocket: WebSocket, session_id: uuid.UUID,
                        db: SASession = Depends(get_db),
                        settings: Settings = Depends(get_settings)) -> None:
    """Audio IN. Binary PCM16 frames from the one microphone on this session.

    This is the seam's other half: `/api/session/start` recorded consent and
    admitted the session; this socket is where `open_source` finally constructs
    a `LiveSource`, hands it to the same `run_session` that replay uses, and
    feeds it the browser's audio. The pipeline starts when the microphone
    arrives, not when the session is admitted, because a session with no audio
    yet is a slot and not a call.

    NOT THE SAME SOCKET AS `/live`, ON PURPOSE. `/live` is OUT: any number of
    viewers, a backlog then a broadcast, and a viewer leaving never touches the
    pipeline because the call is still happening. This one is IN: exactly one
    producer, and the producer leaving ends the call, because an upstream socket
    with no microphone behind it bills for silence until the 3-hour ceiling.
    Folding the two together would either let a viewer's tab-close hang up the
    call, or let any viewer write audio into it.

    Gates, in order, each with its own close code so the browser can explain it:
      4404  no such session -- including one belonging to another organisation,
            answered identically so a session id never confirms a foreign row
      4403  consent withdrawn, or never recorded
      4409  a replay session; there is no microphone to accept
      4410  the session already ended
      4423  the session already has an audio producer, or a running pipeline
    The organisation check is `GET /api/sessions`' rule: the verified token's
    organisation, never anything the caller sent; anonymous is the demo tenant.

    Wire: binary frames are PCM16 LE mono 16 kHz, any size the client finds
    convenient -- they are re-chunked to 100 ms and paced at real time here
    (`_AudioIngress`). Text frames: `{"type":"Terminate"}` ends the session
    cleanly (1000), `{"type":"KeepAlive"}` is accepted and dropped, anything else
    is 4400. An odd byte count is 4422; more than 2 s ahead of real time is 4429;
    `session_cap_seconds` on this socket's own clock is 4408 and records
    `end_reason = "cap"`; upstream unreachable or the pipeline failing is 4502.

    Down the socket comes exactly one text frame, `{"type":"Ready", ...}`, once
    the pipeline is running; everything else the browser needs is on `/live`.

    On every exit -- clean, dropped, capped, errored -- `terminate()` is sent
    upstream exactly once (`LiveSource.terminate` is idempotent) and the
    pipeline is given `PIPELINE_DRAIN_S` to write its last row.
    """
    offered = [p.strip() for p in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    await websocket.accept(
        subprotocol=AUDIO_SUBPROTOCOL if AUDIO_SUBPROTOCOL in offered else None)

    user = auth.resolve_user(_ws_token(websocket), db, settings)
    org_id = acting_organisation(user)
    row = db.get(Session, session_id)
    live = _SESSIONS.get(session_id)
    if row is None or row.organisation_id != org_id:
        await websocket.close(WS_AUDIO_UNKNOWN, "unknown session")
        return
    if not row.consent_version or row.consent_withdrawn_at is not None:
        await websocket.close(WS_AUDIO_NO_CONSENT, "consent not recorded")
        return
    if row.source != "live":
        await websocket.close(WS_AUDIO_NOT_LIVE, "not a live session")
        return
    if live is None or not live.running or row.ended_at is not None:
        await websocket.close(WS_AUDIO_ENDED, "session already ended")
        return
    if live.producer is not None or (live.task is not None and not live.task.done()):
        await websocket.close(WS_AUDIO_BUSY, "session already has an audio producer")
        return
    # Claimed before the first await below, so two sockets racing for the same
    # session cannot both pass the check above.
    live.producer = websocket

    source: Any = None
    pipeline: asyncio.Task[Any] | None = None
    store: _IngressStore | None = None
    ingress: _AudioIngress | None = None
    outcome = _Outcome(WS_AUDIO_UPSTREAM, "upstream unavailable", end_reason="error")
    try:
        try:
            vocabulary = tuple(vocabulary_for(db, row.organisation_id))
            source = open_source(settings, None, config=_connect_config(vocabulary))
            await source.connect()
        except Exception:
            # The key is wrong, the network is down, or the kill switch flipped
            # between admission and now. The session cannot become a call, so
            # it ends here rather than holding a capture slot for the grace
            # period -- and the viewers on /live are told, by type only.
            live.stream.emit(ev.ERROR, 0, message="upstream_unavailable")
            live.stream.close()
            row.ended_at = utcnow()
            row.end_reason = "error"
            audit.record(db, audit.SESSION_ENDED, organisation_id=row.organisation_id,
                         session_id=row.id, actor="api",
                         detail={"reason": "upstream_unavailable"})
            db.commit()
            await websocket.close(WS_AUDIO_UPSTREAM, "upstream unavailable")
            return
        opened_at = time.monotonic()
        live.source = source
        store = _IngressStore(db, row.id, row.organisation_id)
        cfg = RunnerConfig(session_id=str(row.id), sockets=row.sockets,
                           cap_seconds=settings.session_cap_seconds,
                           source_label="live",
                           vocabulary=vocabulary,
                           identify=_identifier(settings))
        pipeline = asyncio.create_task(run_session(
            source, live.stream, store=store, answerer=live.answerer(), config=cfg))
        live.task = pipeline
        audit.record(db, audit.SOCKET_OPENED, organisation_id=row.organisation_id,
                     session_id=row.id, actor="api",
                     detail={"kind": "audio", "sockets": row.sockets})
        db.commit()
        # The one frame that ever goes DOWN this socket: the pipeline is up and
        # listening. The browser's three-state indicator (3.12) turns to
        # "listening" on this and on nothing earlier -- a microphone permission
        # is not a session, and an accepted handshake is not a pipeline.
        await websocket.send_json({"type": "Ready", "session_id": str(row.id),
                                   "cap_seconds": settings.session_cap_seconds,
                                   "chunk_ms": AUDIO_CHUNK_MS})

        ingress = _AudioIngress(websocket, source, cap_seconds=settings.session_cap_seconds,
                                opened_at=opened_at)
        try:
            outcome = await ingress.run(pipeline)
        except asyncio.CancelledError:
            # The handler itself was cancelled: the ASGI server tearing the
            # connection down, or the process going away. The runner's own
            # convention for a cancellation is "user", and the finally below
            # runs to completion regardless -- that is what it is for.
            outcome = _Outcome(1006, "connection closed", send_close=False,
                               end_reason="user")
            raise
    finally:
        live.producer = None
        if store is not None:
            # Before terminate, because terminate is what makes the runner
            # finish, and finish is what writes the row.
            store.end_reason = outcome.end_reason
        # ALWAYS. This is the line that stops the meter (3.11). Idempotent on the
        # source side, so a pipeline that already terminated costs one no-op.
        # Shielded so that a handler being cancelled still sends it: the
        # cancellation interrupts our wait, not the Terminate frame.
        if source is not None:
            await _quietly(asyncio.shield(source.terminate()))
        if pipeline is not None and not pipeline.done():
            await _quietly(asyncio.wait_for(asyncio.shield(pipeline), PIPELINE_DRAIN_S))
            if not pipeline.done():
                pipeline.cancel()
        if source is not None:
            try:
                audit.record(db, audit.SOCKET_CLOSED, organisation_id=row.organisation_id,
                             session_id=row.id, actor="api",
                             detail={"kind": "audio", "code": outcome.code,
                                     "reason": outcome.reason,
                                     "forwarded_ms": _ingress_ms(ingress)})
                db.commit()
            except Exception:
                db.rollback()
        if (outcome.send_close and websocket.client_state.name == "CONNECTED"
                and websocket.application_state.name == "CONNECTED"):
            await _quietly(websocket.close(outcome.code, outcome.reason))


async def _quietly(aw: Awaitable[Any]) -> None:
    """Await a piece of teardown without letting it mask the real exit.

    Used only inside `session_audio`'s finally, where an exception -- including
    a cancellation being re-delivered to a task that is already unwinding --
    would replace whatever actually ended the socket. A shielded awaitable
    keeps running when this returns early; that is the point of shielding it.
    """
    try:
        await aw
    except BaseException:
        pass


def _ingress_ms(ingress: _AudioIngress | None) -> int:
    """Milliseconds forwarded upstream -- a count, never the audio. The audit
    layer refuses a detail key that so much as names audio (ARCH 3.9), which is
    how this key came to be called what it is."""
    return 0 if ingress is None else ingress.bytes_out // AUDIO_BYTES_PER_MS


# ----------------------------------------------------------------- answer ----
@app.post("/api/session/{session_id}/answer")
def session_answer(session_id: uuid.UUID, body: AnswerRequest,
                   db: SASession = Depends(get_db)) -> dict[str, Any]:
    """The human's one character.

    The text is handed to the runner and parsed there, under the grammar the
    question offered (4.7). It is never stored: `question_event` records
    `answered`, `answer_in_grammar` and `answer_char`, and nothing else, because
    the answer is the one moment a human speaks directly to the agent and is
    therefore the most tempting thing in the system to keep.
    """
    live = _SESSIONS.get(session_id)
    if live is None:
        raise HTTPException(404, "unknown session")
    text = body.text
    if text is None and body.choice is not None:
        # A tapped chip. 4.3: the question must be answerable by voice without
        # looking and by tapping if the operator prefers, and both have to reach
        # the same parser or the two routes can disagree.
        asked = [e for e in live.stream.history if e.type == ev.QUESTION_ASK
                 and e.data.get("question_id") == body.question_id]
        choices = asked[-1].data.get("choices", []) if asked else []
        if 0 <= body.choice < len(choices):
            text = str(choices[body.choice])
    if text is None:
        raise HTTPException(422, "an answer needs text or a valid choice index")
    if not live.answer(body.question_id, text):
        raise HTTPException(409, "that question is not waiting for an answer")
    return {"ok": True}


# -------------------------------------------------------------- capture list --
# What the dashboard reads. One row per identifier, newest first, scoped to the
# organisation on the bearer token and to nothing wider.
#
# A bare JSON array rather than {captures: [...], next: ...}. The envelope is the
# nicer shape and it is not the one that was declared: web/src/lib/api.ts types
# this call as `Capture[]` and screens/Account.tsx guards it with
# `Array.isArray(result.data)`, so an envelope renders as a permanently empty
# dashboard rather than as an error anybody would notice. The cursor is therefore
# carried by the rows themselves -- `created_at` and `id` of the last one are the
# next page's `before` and `before_id` -- which costs the client one line and
# costs the response nothing.
CAPTURES_LIMIT_DEFAULT: Final = 50
CAPTURES_LIMIT_MAX: Final = 200


def _bad_request(error: str, message: str) -> HTTPException:
    """Flat body, same two keys as every other failure. See `_flat_errors`."""
    return HTTPException(status_code=400, detail={"error": error, "message": message})


def _parse_limit(raw: str | None) -> int:
    """Parsed here rather than declared as `limit: int = Query(le=200)`.

    FastAPI answers a bad query parameter with RequestValidationError, which is
    not an HTTPException and so never reaches `_flat_errors`: the client would
    get `{"detail": [{"loc": ...}]}` and read `error` and `message` off it as
    undefined. One shape for every failure means this one is checked by hand.
    """
    if raw is None or raw == "":
        return CAPTURES_LIMIT_DEFAULT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise _bad_request(
            "invalid_limit",
            f"limit must be a whole number between 1 and {CAPTURES_LIMIT_MAX}.",
        ) from None
    if not 1 <= value <= CAPTURES_LIMIT_MAX:
        # Clamping silently would be the friendlier-looking choice and the wrong
        # one: a client that asked for 50,000 and got 200 without being told has
        # a page that is missing rows and no way to know it.
        raise _bad_request(
            "invalid_limit",
            f"limit must be between 1 and {CAPTURES_LIMIT_MAX}.",
        )
    return value


def _parse_cursor(before: str | None,
                  before_id: str | None) -> tuple[datetime, uuid.UUID] | None:
    """Keyset, not offset. Two captures can share a millisecond, so the cursor is
    the (created_at, id) pair and the id breaks the tie; an OFFSET would skip or
    repeat a row whenever a session wrote while somebody was paging."""
    if before is None and before_id is None:
        return None
    if not before or not before_id:
        raise _bad_request(
            "invalid_cursor",
            "before and before_id travel together; take both from the last row "
            "of the previous page.",
        )
    text = before.strip()
    if text.endswith("Z"):
        # fromisoformat only learned to read the Z in 3.11 and every timestamp
        # this endpoint emits ends in +00:00 anyway, but the client is JavaScript
        # and toISOString() produces the Z.
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise _bad_request(
            "invalid_cursor", "before must be an ISO 8601 timestamp.") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        row_id = uuid.UUID(before_id)
    except (ValueError, AttributeError, TypeError):
        raise _bad_request("invalid_cursor", "before_id must be a capture id.") from None
    return moment, row_id


def capture_state(row: Capture) -> str:
    """The five-word display vocabulary, derived once here so two screens cannot
    disagree about what a row is.

    `status` on the wire is the database's own committed/flagged/unverified.
    `state` is what the rack draws, and it is not the same alphabet: "quietly
    repaired" and "needs one thing from you" are facts about how the row was
    reached, not about whether it validated.

    Repaired is deliberately narrow. --green means QUIETLY repaired, and a row
    that got there by asking was not quiet, so it settles as `settled` and the
    repair is still visible in `repaired` and `repaired_position`. Widening this
    would put the product's own claim -- silence -- on rows that interrupted.
    """
    if row.status == "flagged":
        return "flagged"
    if row.status == "committed":
        return "repaired" if (row.corrected and row.silent) else "settled"
    if row.handed_over or row.questions_asked > 0:
        return "asking"
    return "heard"


def capture_row(row: Capture, source: str) -> dict[str, Any]:
    """One capture as the dashboard needs it, and nothing else.

    There is no field here for the words around the identifier, because there is
    no column for them (models.py, Capture: "NOT ON THIS TABLE, AND WHY") and no
    confidence number, because this system expresses doubt by asking rather than
    by printing a percentage. `value` is the settled identifier, falling back to
    what was heard for a row that never settled -- `state` is what says which of
    the two it is, and it always ships beside it.

    `source` is the session's, not the capture's, and it is the one field here
    that the record view does not strictly need. It is included because a row
    replayed from a fixture and a row heard on a call look identical otherwise,
    and this project's rule is that anything simulated says so on screen. It is
    the column models.py added for exactly that reason.
    """
    return {
        # The session this belongs to. Added because the record view groups by
        # session and the client cannot invent the link -- without it every row
        # was silently dropped by the parser and the dashboard printed "no
        # identifiers captured yet" over thirteen real ones, which Dashboard.tsx
        # itself calls "a fabricated row wearing a politer face". A session id is
        # not a secret: it is already returned by /api/session/start and sits in
        # a URL, and reading one back is still organisation-scoped.
        "session_id": str(row.session_id),
        "id": str(row.id),
        "format": row.format_type,
        "value": row.final_value or row.heard_value,
        # `value` is what was written; `heard` is what the microphone said. They
        # differ only on a repaired row, and that difference IS the product --
        # the rack shows the superseded character above the one that replaced it,
        # so a client with only `value` cannot draw the state the whole system
        # exists to produce.
        "heard": row.heard_value,
        "final": row.final_value,
        "state": capture_state(row),
        "status": row.status,
        "silent": row.silent,
        "repaired": row.corrected,
        "repaired_position": row.position_corrected,
        "questions": row.questions_asked,
        "ms_to_settle": row.latency_ms,
        "source": source,
        "created_at": row.created_at.isoformat(),
    }


@app.get("/api/sessions")
def list_captures(limit: str | None = None,
                  before: str | None = None,
                  before_id: str | None = None,
                  user: User = Depends(auth.current_user),
                  db: SASession = Depends(get_db)) -> list[dict[str, Any]]:
    """Every capture this organisation made, newest first, one bounded page.

    The join to `session` is the whole security model of this route: `capture`
    carries no organisation of its own, so the only thing standing between one
    tenant and another's identifiers is this WHERE clause. It is written against
    `user.organisation_id` from the verified token and never against anything the
    caller sent.

    Bounded, never unbounded. An organisation with 50,000 captures gets 50 and a
    cursor; asking for all of them is not a request this endpoint can express.
    A page that comes back full may have more behind it -- take `created_at` and
    `id` from the last row and pass them as `before` and `before_id`.
    """
    page = _parse_limit(limit)
    cursor = _parse_cursor(before, before_id)

    stmt = (
        select(Capture, Session.source)
        .join(Session, Capture.session_id == Session.id)
        .where(Session.organisation_id == user.organisation_id)
        .order_by(Capture.created_at.desc(), Capture.id.desc())
        .limit(page)
    )
    if cursor is not None:
        moment, row_id = cursor
        stmt = stmt.where(
            or_(Capture.created_at < moment,
                and_(Capture.created_at == moment, Capture.id < row_id))
        )
    return [capture_row(row, source) for row, source in db.execute(stmt).all()]


# ------------------------------------------------------------ session list ---
SESSIONS_LIMIT_DEFAULT: Final = 50
SESSIONS_LIMIT_MAX: Final = 200


@app.get("/api/session-summaries")
def session_summaries(limit: str | None = None,
                      before: str | None = None,
                      before_id: str | None = None,
                      user: User | None = Depends(auth.optional_user),
                      db: SASession = Depends(get_db)) -> dict[str, Any]:
    """Every session this organisation ran, newest first, one bounded page, each
    carrying the counts a team leader reads before opening it.

    This is the list `GET /api/sessions/{id}` drills into, and it is a session
    query rather than the capture query `list_captures` runs, for one reason
    that is the product: a call that correctly captured NOTHING -- a
    conversation with no identifier in it, a number that was a phone number --
    is a session with zero capture rows, and a list built by grouping captures
    could never show it. Half of what this system claims is the calls on which
    it stayed silent, so the list is drawn from `session`, and the silent ones
    are in it.

    Organisation-scoped by the same rule as every other read here; anonymous
    callers are the demo tenant. Bounded, and it says whether more remain rather
    than dropping the tail in silence -- and hands back the keyset cursor
    (`next_before`, `next_before_id` = the last row's started_at and id) that
    fetches the next page, the same (moment, id) pair `list_captures` pages by.
    """
    org_id = acting_organisation(user)
    page = _parse_limit(limit)
    cursor = _parse_cursor(before, before_id)

    stmt = (
        select(Session)
        .where(Session.organisation_id == org_id)
        .order_by(Session.started_at.desc(), Session.id.desc())
        .limit(page + 1)
    )
    if cursor is not None:
        moment, row_id = cursor
        stmt = stmt.where(
            or_(Session.started_at < moment,
                and_(Session.started_at == moment, Session.id < row_id))
        )
    rows = list(db.scalars(stmt))
    more = len(rows) > page
    rows = rows[:page]
    ids = [r.id for r in rows]

    # Two grouped aggregates rather than a subquery per session: a page is up to
    # 200 rows and N+1 counting queries is the shape that looks fine in dev and
    # falls over on a busy tenant.
    caps: dict[uuid.UUID, tuple[int, int, int]] = {}
    quests: dict[uuid.UUID, int] = {}
    if ids:
        for sid, total, silent, needs_human in db.execute(
            select(
                Capture.session_id,
                func.count(),
                func.sum(case((Capture.silent, 1), else_=0)),
                func.sum(case((or_(Capture.handed_over,
                                   Capture.status == "flagged"), 1), else_=0)),
            )
            .where(Capture.session_id.in_(ids))
            .group_by(Capture.session_id)).all():
            caps[sid] = (int(total), int(silent or 0), int(needs_human or 0))
        quests = {sid: int(n) for sid, n in db.execute(
            select(QuestionEvent.session_id, func.count())
            .where(QuestionEvent.session_id.in_(ids))
            .group_by(QuestionEvent.session_id)).all()}

    def summary(row: Session) -> dict[str, Any]:
        total, silent, needs_human = caps.get(row.id, (0, 0, 0))
        return {
            "id": str(row.id),
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "end_reason": row.end_reason,
            "source": row.source,
            "demo_mode": row.demo_mode,
            "captures": total,
            "silent": silent,
            "flagged": needs_human,
            "questions": quests.get(row.id, 0),
        }

    last = rows[-1] if rows and more else None
    return {
        "sessions": [summary(r) for r in rows],
        "more": more,
        "next_before": last.started_at.isoformat() if last else None,
        "next_before_id": str(last.id) if last else None,
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
    format: str
    value: str


@app.post("/api/validate")
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
        raise _bad_request(
            "unknown_format",
            f"format must be one of {', '.join(sorted(VALIDATE_FORMATS))}.",
        )
    if len(body.value) > VALIDATE_MAX_CHARS:
        raise _bad_request(
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


# ------------------------------------------------------------------- usage ---
@app.get("/api/usage")
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
    remaining, alarm, exhausted = _budget(db, settings)
    spent_today = spent_socket_seconds(db, midnight)

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
            raise _bad_request(
                "term_too_long",
                f"a term is {len(cleaned)} characters; the cap is {VOCAB_MAX_CHARS}.",
            )
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    if len(out) > VOCAB_MAX_TERMS:
        raise _bad_request(
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


@app.get("/api/vocabulary")
def get_vocabulary(user: User = Depends(auth.current_user),
                   db: SASession = Depends(get_db)) -> dict[str, Any]:
    """ARCH 3.9: the organisation's own words for the recogniser."""
    return _vocabulary_payload(vocabulary_for(db, user.organisation_id))


@app.put("/api/vocabulary")
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


# ------------------------------------------------------------------ record ---
@app.get("/api/sessions/{session_id}")
def session_record(session_id: uuid.UUID,
                   user: User | None = Depends(auth.optional_user),
                   db: SASession = Depends(get_db)) -> dict[str, Any]:
    """The team-leader view (DESIGN-BRIEF 4.4): what was captured, and the audit.

    No transcript, and there is no column that could produce one.

    Organisation-scoped, exactly like the list this drills into: `capture` and
    the session's audit carry another tenant's identifiers, and a session id is
    not a secret -- it is handed back in a response body and sits in a URL. The
    same guard `list_captures` documents as "the whole security model" applies
    here one level deeper. `acting_organisation` folds an anonymous caller into
    the demo tenant, so the demo/replay flow reads its own fixtures unchanged
    while a real account's sessions require that account's token. 404 rather
    than 403, so the endpoint never confirms a foreign session exists.
    """
    org_id = acting_organisation(user)
    row = db.get(Session, session_id)
    if row is None or row.organisation_id != org_id:
        raise HTTPException(404, "unknown session")
    captures = list(db.scalars(
        select(Capture).where(Capture.session_id == session_id)
        .order_by(Capture.created_at)))
    questions = list(db.scalars(
        select(QuestionEvent).where(QuestionEvent.session_id == session_id)
        .order_by(QuestionEvent.asked_at)))
    events = list(db.scalars(
        select(AuditEvent).where(AuditEvent.session_id == session_id)
        .order_by(AuditEvent.seq)))
    live = _SESSIONS.get(session_id)
    return {
        "session": {
            "id": str(row.id), "started_at": row.started_at.isoformat(),
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "end_reason": row.end_reason, "source": row.source,
            "billed_seconds": row.billed_seconds, "sockets": row.sockets,
            "charged_seconds": row.charged_seconds,
            "confidence_regime": row.confidence_regime,
            "consent_version": row.consent_version,
            "disclosure_played": row.disclosure_played,
            "demo_mode": row.demo_mode,
        },
        "captures": [
            {
                "id": str(c.id), "format": c.format_type, "heard": c.heard_value,
                "final": c.final_value, "status": c.status,
                "validated_by": c.validated_by, "second_signal": c.second_signal,
                "silent": c.silent, "corrected": c.corrected,
                "position_corrected": c.position_corrected, "rung": c.rung,
                "questions_asked": c.questions_asked, "handed_over": c.handed_over,
                "handover_reason": c.handover_reason, "flag_reason": c.flag_reason,
                "latency_ms": c.latency_ms,
                "candidates": c.candidates_considered,
                "created_at": c.created_at.isoformat(),
            }
            for c in captures
        ],
        "questions": [
            {
                "id": str(q.id), "capture_id": str(q.capture_id),
                "position": q.position, "form": q.form, "rung": q.rung,
                "spoken": q.spoken, "text": q.question_text, "offered": q.offered,
                "answered": q.answered, "answer_in_grammar": q.answer_in_grammar,
                "answer_char": q.answer_char, "resolution_ms": q.resolution_ms,
            }
            for q in questions
        ],
        "audit": [
            {"seq": e.seq, "at": e.at.isoformat(), "actor": e.actor,
             "action": e.action, "detail": e.detail}
            for e in events
        ],
        "events": [e.as_dict() for e in live.stream.history] if live else [],
        "counters": {
            "captures": len(captures),
            "silent": sum(1 for c in captures if c.silent),
            "characters": sum(len(c.final_value or "") for c in captures),
            "questions": len(questions),
            "spoken_questions": sum(1 for q in questions if q.spoken),
        },
    }


# ------------------------------------------------------------------- stop ----
@app.post("/api/session/{session_id}/stop")
async def session_stop(session_id: uuid.UUID, delete: bool = Body(False, embed=True),
                       user: User | None = Depends(auth.optional_user),
                       db: SASession = Depends(get_db)) -> dict[str, Any]:
    """ARCH 3.12's stop-and-delete. Terminates the socket and visibly deletes.

    The audit row survives the deletion by construction: `audit_event` has no
    foreign keys, so the cascade that removes the captures cannot reach it. A
    record of a deletion destroyed by that deletion is not a record.

    Organisation-scoped like the read and the replay path: a session id alone
    must not let one tenant end or hard-delete another's session. Anonymous
    callers act as the demo tenant (the demo/replay flow stops its own
    fixtures), and a foreign session answers 404 before anything is terminated
    or deleted.
    """
    org_id = acting_organisation(user)
    row = db.get(Session, session_id)
    if row is None or row.organisation_id != org_id:
        raise HTTPException(404, "unknown session")
    live = _SESSIONS.pop(session_id, None)
    if live is not None:
        # Terminate before cancelling: the socket is the thing that bills, and a
        # cancelled task that never sent Terminate leaves it open. Awaited rather
        # than fired into a task, so "stop" has actually stopped by the time this
        # returns -- ARCH 3.11 names unclosed sessions the first cause of
        # surprise charges.
        if live.source is not None and getattr(live.source, "terminate", None):
            await live.source.terminate()
        if live.task is not None and not live.task.done():
            live.task.cancel()
        live.stream.close()
    if delete:
        audit.record(db, audit.SESSION_DELETED, organisation_id=row.organisation_id,
                     session_id=session_id, actor="human",
                     detail={"requested": True})
        db.delete(row)
        db.commit()
        return {"ok": True, "deleted": True}
    row.ended_at = utcnow()
    row.end_reason = "user"
    audit.record(db, audit.SESSION_ENDED, organisation_id=row.organisation_id,
                 session_id=session_id, actor="human", detail={"reason": "stopped"})
    db.commit()
    return {"ok": True, "deleted": False}


# --------------------------------------------------- what CONNECT carries ---
def _connect_config(vocabulary: tuple[str, ...]) -> SourceConfig:
    """The keyterms the CONNECT frame carries: the detector's own IDLE payload,
    with the organisation's vocabulary (ARCH 3.9) riding along.

    Built by the detector's builder rather than restated here, because the
    Detector seeds its "already pushed" state with exactly that payload
    (detector.py, `_pushed`) and only pushes an UpdateConfiguration when the
    state CHANGES. Until this existed the socket was opened with no keyterms
    at all -- `SourceConfig(keyterms=())` -- while the detector believed the
    IDLE list had gone up with CONNECT, so a live session ran its whole IDLE
    phase, carriers and NATO alphabet included, with nothing biasing the
    recogniser. Measured on a real socket that is the difference between
    "container" and "contain a".
    """
    idle = detector_configuration(State.IDLE, None, FORMAT_TOKENS, vocabulary)
    return SourceConfig(keyterms=tuple(idle["keyterms_prompt"]))


def _identifier(settings: Settings) -> Any:
    """3.8's LLM second signal for the runner, or None.

    Only a live session with a real key may make an out-of-band call; replay
    and tests get None and the runner never asks. The verdict is gated inside
    server.llm (FormatID.asserts): bare-digit formats are refused whatever the
    confidence, for the measured reason recorded there.
    """
    key = settings.assemblyai_api_key.get_secret_value()
    if not key or settings.replay_mode:
        return None

    async def identify(candidate: str, carrier: str | None) -> Any:
        return await llm.identify_with_fallback(candidate, api_key=key, carrier=carrier)

    return identify


# ------------------------------------------------------------- the one branch --
def open_source(settings: Settings, fixture: str | None = None,
                *, config: SourceConfig | None = None,
                speed: float = 0.0) -> Any:
    """Construct the session's transcript source. The only place either
    implementation is named.

    `settings.live_capture` is the single condition, and it already folds
    "no key yet" and "daily budget exhausted" into one state, so the replay path
    is exercised on every run today rather than being the branch nobody tried.
    Passing a fixture name forces replay regardless: `/api/demo/replay` is a
    demonstration of a recording by definition, and a demo that quietly opened a
    billable socket would be a surprise on the invoice.

    The key comes from `Settings`, not from `LiveSource.from_env()`. They read
    different environment variables -- `READBACK_ASSEMBLYAI_API_KEY` and
    `ASSEMBLYAI_API_KEY` -- so a `.env` that satisfies the gate but not the
    source would report `live_capture: true` on /health and then raise
    `SourceError` at the first session. One name for the secret, and the gate
    and the socket read the same one.
    """
    if fixture is None and settings.live_capture:
        from server.stream.live import LiveSource

        return LiveSource(settings.assemblyai_api_key.get_secret_value(),
                          config=config, url=settings.assemblyai_url)
    if fixture is None:
        raise HTTPException(
            503,
            "live capture is unavailable (no API key, or the daily budget is "
            "spent). Use POST /api/demo/replay with a fixture name.",
        )
    return ReplaySource(Fixture.load(_fixture_path(fixture)), speed=speed,
                        config=config)


# ------------------------------------------------------------------ replay ---
def _fixture_path(name: str) -> Path:
    """Resolve a fixture by name, refusing anything that is not one.

    `Path(name).name` strips every directory component, so a name containing
    `..` or an absolute path cannot escape the fixture directory. The endpoint
    reads files off the server's disk and is reachable without authentication,
    which is the whole reason this is a lookup rather than a join.
    """
    safe = Path(name).name
    path = fixture_dir() / f"{safe}.json"
    if not path.is_file():
        raise HTTPException(404, f"no fixture named {safe!r}")
    return path


@app.post("/api/demo/replay")
async def demo_replay(body: ReplayRequest,
                      user: User | None = Depends(auth.optional_user),
                      db: SASession = Depends(get_db),
                      settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Run a recorded session through the whole pipeline.

    This is the endpoint that makes the system demonstrable today with no key at
    all, and it is deliberately not a special path: it constructs a
    `ReplaySource` and hands it to the same `run_session` the live socket will
    use, so the events it produces are the events the live path produces. If the
    two ever diverge, this endpoint is the thing that stops working.

    A replay has no microphone and its data is fictional by construction, so a
    session created here records consent on the basis of the recording rather
    than a checkbox. `settings.consent_required` still governs the live path,
    where there is a human whose voice is being captured.

    The bearer token is OPTIONAL and decides only who the resulting rows belong
    to (`acting_organisation`). Requiring one would put a signup in front of the
    one-click path DESIGN-BRIEF 4.5 exists to protect; hard-coding the demo
    tenant, which is what this did until now, meant a signed-in operator's own
    replays were filed where they could never read them back.
    """
    # Loaded here as well as inside open_source, so a malformed recording is a
    # 404/400 before a session row exists rather than a traceback after one does.
    path = _fixture_path(body.fixture)
    Fixture.load(path)
    # A demo gets clicked repeatedly and every click leaves a readable record
    # behind. Reaping here rather than only in `session_start` keeps the bound on
    # a path that never passes through the admission gate.
    _reap_finished()

    org_id = acting_organisation(user)
    if body.session_id is not None:
        row = db.get(Session, body.session_id)
        # A caller may only replay into a session their own organisation owns.
        # Without this, a session id -- which is not a secret; it is handed back
        # in a response body and sits in a URL -- would be enough to write
        # captures into somebody else's tenancy. Answered as 404 rather than 403
        # so the endpoint never confirms that a foreign session exists.
        if row is None or row.organisation_id != org_id:
            raise HTTPException(404, "unknown session")
        live = _SESSIONS.get(body.session_id)
        if live is None:
            live = LiveSession(session_id=row.id, stream=ev.EventStream())
            _SESSIONS[row.id] = live
    else:
        row = Session(
            id=uuid.uuid4(), organisation_id=org_id, started_at=utcnow(),
            sockets=1, channel="clean", source="replay",
            consent_version=settings.consent_version, consent_at=utcnow(),
            disclosure_played=True, demo_mode=True,
        )
        db.add(row)
        audit.record(db, audit.CONSENT_GRANTED, organisation_id=org_id,
                     session_id=row.id, actor="system",
                     detail={"basis": "recorded_fixture", "fixture": path.stem})
        audit.record(db, audit.SESSION_STARTED, organisation_id=org_id,
                     session_id=row.id, actor="api",
                     detail={"source": "replay", "fixture": path.stem})
        audit.record(db, audit.REPLAY_ENTERED, organisation_id=org_id,
                     session_id=row.id, actor="api",
                     detail={"fixture": path.stem, "speed": body.speed})
        db.commit()
        live = LiveSession(session_id=row.id, stream=ev.EventStream())
        _SESSIONS[row.id] = live

    vocabulary = tuple(vocabulary_for(db, row.organisation_id))
    source = open_source(settings, path.stem, speed=body.speed,
                         config=_connect_config(vocabulary))
    live.source = source
    # The store's audit events follow the session they describe, which is the
    # same rule the rows above obey. `row.organisation_id` rather than `org_id`
    # so the reused-session branch cannot come to disagree with the new-session
    # one; the guard above has already proved the two are equal.
    store = SqlCaptureStore(db, row.id, row.organisation_id)

    # Scripted answers make the escalation path demonstrable without a human in
    # the room. Keyed by position so a fixture's own expectations can drive it;
    # absent an entry the question goes unanswered, which is itself one of the
    # behaviours worth showing.
    scripted = dict(body.answers)

    async def answerer(q: Question) -> str | None:
        if str(q.position) in scripted:
            return scripted[str(q.position)]
        return await live.answerer()(q)

    # No `identify` on a replay: a demonstration of a recording must never
    # make an out-of-band call, for the same reason it never opens a socket.
    cfg = RunnerConfig(session_id=str(row.id), sockets=row.sockets,
                       cap_seconds=settings.session_cap_seconds,
                       source_label="replay",
                       vocabulary=vocabulary,
                       **({"answer_timeout_ms": body.answer_timeout_ms}
                          if body.answer_timeout_ms else {}))
    wait = body.wait if body.wait is not None else (body.speed <= 0.0)

    async def _run() -> RunSummary:
        try:
            return await run_session(source, live.stream, store=store,
                                     answerer=answerer, config=cfg)
        finally:
            live.summary = getattr(live, "summary", None)

    if wait:
        summary = await _run()
        live.summary = summary
        return _replay_response(row.id, path.stem, summary, live)
    live.task = asyncio.create_task(_run())
    return {"session_id": str(row.id), "fixture": path.stem, "streaming": True,
            "ws": f"/api/session/{row.id}/live"}


def _replay_response(session_id: uuid.UUID, fixture: str, summary: RunSummary,
                     live: LiveSession) -> dict[str, Any]:
    return {
        "session_id": str(session_id),
        "fixture": fixture,
        "ws": f"/api/session/{session_id}/live",
        "frames": summary.frames,
        "armed_at_ms": summary.armed_at_ms,
        "regime": summary.regime,
        "billed_seconds": summary.billed_seconds,
        "counters": {
            "characters": summary.characters,
            "captures": len(summary.captures),
            "silent": summary.silent_captures,
            "questions": summary.questions_asked,
            "spoken_questions": summary.spoken_questions,
            "speech_ms": summary.speech_ms,
        },
        "captures": [
            {"format": c.format_type, "heard": c.heard_value, "final": c.final_value,
             "status": c.status, "silent": c.silent, "corrected": c.corrected,
             "position_corrected": c.position_corrected,
             "validated_by": c.validated_by, "second_signal": c.second_signal,
             "questions": c.questions_asked, "rung": c.rung,
             "handover_reason": c.handover_reason, "latency_ms": c.latency_ms}
            for c in summary.captures
        ],
        "events": [e.as_dict() for e in live.stream.history],
    }
