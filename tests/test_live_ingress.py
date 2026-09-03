# test_live_ingress.py -- ws /api/session/{id}/audio, the microphone's way in.
#
# The route feeds `LiveSource.send_audio`, which in production opens a billed
# AssemblyAI socket, so every test here replaces `main.open_source` with a stub
# source that records what it was sent and counts how many times it was told to
# Terminate. That count is the point: an abandoned upstream socket bills until
# the 3-hour ceiling (ARCH 3.11), so "exactly one Terminate on every exit" is
# the property this file exists to pin, alongside the close codes, the
# single-producer rule across two organisations, the frame rules and the cap.
#
# Deterministic and offline. No key, no network, no signup: users are inserted
# directly and tokens minted with auth.issue_token. The two timing tests (pacing
# and the cap) assert on wall-clock numbers they measured, with margins wide
# enough for a loaded CI box and tight enough to catch the property being off.
#
# Runs under pytest or as a script.
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from server import auth, main
from server.config import Settings, get_settings
from server.db import create_all, get_db, make_engine
from server.main import (
    AUDIO_BYTES_PER_MS,
    AUDIO_CHUNK_BYTES,
    AUDIO_MAX_AHEAD_BYTES,
    AUDIO_MIN_FRAME_BYTES,
    AUDIO_SUBPROTOCOL,
    AUDIO_TOKEN_PROTOCOL_PREFIX,
    WS_AUDIO_BAD_FRAME,
    WS_AUDIO_BAD_MESSAGE,
    WS_AUDIO_BUSY,
    WS_AUDIO_CAP,
    WS_AUDIO_ENDED,
    WS_AUDIO_NO_CONSENT,
    WS_AUDIO_NOT_LIVE,
    WS_AUDIO_TERMINATED,
    WS_AUDIO_TOO_FAST,
    WS_AUDIO_UNKNOWN,
    LiveSession,
    app,
)
from server.models import AuditEvent, Organisation, Session, User
from server.pipeline import events as ev
from server.stream.source import BaseTranscriptSource, SourceClosed, SourceConfig, Turn

PLACEHOLDER_HASH = "pbkdf2_sha256$1$00$00"
T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
CONSENT = {"accepted": True, "version": "2026-09-01", "disclosure_played": True}


# ------------------------------------------------------------------ stub -----
class StubSource(BaseTranscriptSource):
    """A LiveSource with no socket behind it.

    Mirrors the two behaviours the ingress depends on: `send_audio` refuses
    once closed, and `terminate` is idempotent -- it counts every call and
    separately counts the calls that would actually have sent a Terminate
    frame, which is the number the bill depends on. `_frames` yields nothing
    and ends when terminated, exactly as the real one's `async for` does when
    its socket closes.
    """

    def __init__(self) -> None:
        super().__init__(SourceConfig(keyterms=()))
        self.chunks: list[bytes] = []
        self.chunk_at: list[float] = []
        self.terminate_calls = 0
        self.terminate_sent = 0
        self.connected = False
        self._done = asyncio.Event()

    async def connect(self) -> None:
        self.connected = True
        self._t0 = time.monotonic()
        # The app's loop, so a test can drive an in-process route (/stop) on
        # it: TestClient gives every websocket its own portal thread and loop,
        # where uvicorn has one, and a cross-loop terminate wakes nobody.
        self.loop = asyncio.get_running_loop()

    async def send_audio(self, pcm: bytes) -> None:
        if self._closed:
            raise SourceClosed("send_audio on a terminated source")
        self.chunks.append(bytes(pcm))
        self.chunk_at.append(time.monotonic())

    async def force_endpoint(self) -> None:
        return None

    async def terminate(self) -> None:
        self.terminate_calls += 1
        if self._closed:
            return
        self._closed = True
        self.terminate_sent += 1
        self.billed_seconds = round(time.monotonic() - self._t0, 3)
        self._done.set()

    async def _frames(self) -> AsyncIterator[Turn]:
        await self.connect()
        try:
            await self._done.wait()
        finally:
            if not self._closed:
                await self.terminate()
        return
        yield  # pragma: no cover -- makes this an async generator


class FailingSource(StubSource):
    """Upstream that cannot be reached: the key is wrong or the network is down."""

    async def connect(self) -> None:
        raise OSError("connection refused")


# --------------------------------------------------------------- harness ----
class _Fixture:
    """A client wired to a fresh database, a live-capable Settings and no socket."""

    def __init__(self, *, cap_seconds: int = 150, source_cls: type = StubSource) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_ingress_")
        os.close(fd)
        # A key is present and replay_mode is off, so /api/session/start admits
        # a LIVE session; the limits are lifted so a test can start several
        # from the one address TestClient reports.
        self.settings = Settings(
            assemblyai_api_key="not-a-real-key", replay_mode=False,
            session_secret="test-secret-ingress-1", session_cap_seconds=cap_seconds,
            per_ip_per_hour=10_000, per_ip_per_day=10_000,
            admissions_per_minute=10_000, max_concurrent_sessions=100,
        )
        self.engine = make_engine(f"sqlite:///{self.path}", echo=False,
                                  settings=self.settings)
        create_all(self.engine)
        self.Factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Factory() as db:
            if db.get(Organisation, main.DEMO_ORG_ID) is None:
                db.add(Organisation(id=main.DEMO_ORG_ID, name=main.DEMO_ORG_NAME))
                db.commit()

        def _db():
            db = self.Factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_settings] = lambda: self.settings

        self.sources: list[StubSource] = []
        self._source_cls = source_cls
        self._real_open_source = main.open_source
        main.open_source = self._open_source
        main._SESSIONS.clear()
        for window in (main._PER_HOUR, main._PER_DAY, main._ADMISSIONS):
            window.counts.clear()
        self.client = TestClient(app, raise_server_exceptions=False)

    def _open_source(self, settings: Settings, fixture: str | None = None,
                     **kwargs: Any) -> Any:
        if fixture is not None:
            return self._real_open_source(settings, fixture, **kwargs)
        src = self._source_cls()
        self.sources.append(src)
        return src

    def close(self) -> None:
        main.open_source = self._real_open_source
        main._SESSIONS.clear()
        app.dependency_overrides.clear()
        self.engine.dispose()

    # -- tenants and sessions ------------------------------------------------
    def organisation(self, name: str, email: str) -> tuple[uuid.UUID, str]:
        with self.Factory() as db:
            org = Organisation(name=name)
            user = User(organisation=org, email=email, name=name.split()[0],
                        password_hash=PLACEHOLDER_HASH, role="owner")
            db.add(org)
            db.add(user)
            db.commit()
            return org.id, auth.issue_token(user, self.settings)

    def start(self, token: str | None = None) -> uuid.UUID:
        """A live session through the real consent gate."""
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = self.client.post("/api/session/start",
                             json={"consent": CONSENT}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["live_capture"] is True, r.json()
        return uuid.UUID(r.json()["session_id"])

    def row(self, org_id: uuid.UUID, **overrides: Any) -> uuid.UUID:
        """A session row written directly, for states the gate cannot produce."""
        fields: dict[str, Any] = dict(
            organisation_id=org_id, consent_version="2026-09-01", consent_at=T0,
            disclosure_played=True, source="live", started_at=T0,
        )
        fields.update(overrides)
        with self.Factory() as db:
            row = Session(**fields)
            db.add(row)
            db.commit()
            return row.id

    def session(self, sid: uuid.UUID) -> Session:
        with self.Factory() as db:
            row = db.get(Session, sid)
            assert row is not None
            return row

    def audit(self, sid: uuid.UUID) -> list[AuditEvent]:
        with self.Factory() as db:
            return list(db.scalars(select(AuditEvent)
                                   .where(AuditEvent.session_id == sid)
                                   .order_by(AuditEvent.seq)))

    def audio(self, sid: uuid.UUID, *, token: str | None = None,
              via_header: bool = False):
        url = f"/api/session/{sid}/audio"
        if token is None:
            return self.client.websocket_connect(url, subprotocols=[AUDIO_SUBPROTOCOL])
        if via_header:
            return self.client.websocket_connect(
                url, subprotocols=[AUDIO_SUBPROTOCOL],
                headers={"Authorization": f"Bearer {token}"})
        return self.client.websocket_connect(
            url, subprotocols=[AUDIO_SUBPROTOCOL, AUDIO_TOKEN_PROTOCOL_PREFIX + token])


def _closed_with(ws) -> WebSocketDisconnect:
    """Block until the server closes, and hand back the code and reason."""
    try:
        ws.receive_text()
    except WebSocketDisconnect as exc:
        return exc
    raise AssertionError("the server sent a message instead of closing")


def _ready(ws) -> dict:
    """The one frame the server sends: the pipeline is up. Everything a test
    does to an accepted socket happens after this, so nothing races the gates."""
    msg = ws.receive_json()
    assert msg["type"] == "Ready", msg
    assert "session_id" in msg and msg["cap_seconds"] > 0
    return msg


def _pcm(ms: int) -> bytes:
    return b"\x01\x00" * (ms * AUDIO_BYTES_PER_MS // 2)


# ----------------------------------------------------------------- gates -----
def test_unknown_session_closes_4404() -> None:
    fx = _Fixture()
    try:
        with fx.audio(uuid.uuid4()) as ws:
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_UNKNOWN, exc
        assert fx.sources == [], "no upstream socket may open for a session that does not exist"
    finally:
        fx.close()


def test_withdrawn_consent_closes_4403() -> None:
    """A row cannot exist without consent (the columns are NOT NULL), so the
    state this guards is consent WITHDRAWN after the fact, and an emptied
    version: both are refused before any socket opens."""
    fx = _Fixture()
    try:
        withdrawn = fx.row(main.DEMO_ORG_ID, consent_withdrawn_at=T0)
        main._SESSIONS[withdrawn] = LiveSession(session_id=withdrawn, stream=ev.EventStream())
        with fx.audio(withdrawn) as ws:
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_NO_CONSENT, exc

        blank = fx.row(main.DEMO_ORG_ID, consent_version="")
        main._SESSIONS[blank] = LiveSession(session_id=blank, stream=ev.EventStream())
        with fx.audio(blank) as ws:
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_NO_CONSENT, exc
        assert fx.sources == []
    finally:
        fx.close()


def test_replay_session_closes_4409() -> None:
    fx = _Fixture()
    try:
        sid = fx.row(main.DEMO_ORG_ID, source="replay")
        main._SESSIONS[sid] = LiveSession(session_id=sid, stream=ev.EventStream())
        with fx.audio(sid) as ws:
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_NOT_LIVE, exc
        assert fx.sources == []
    finally:
        fx.close()


def test_ended_session_closes_4410() -> None:
    fx = _Fixture()
    try:
        # Ended on the record, and no longer in memory (reaped or restarted).
        sid = fx.row(main.DEMO_ORG_ID, ended_at=T0, end_reason="user")
        with fx.audio(sid) as ws:
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_ENDED, exc
        # In memory but its pipeline has finished: the stream is closed.
        live = LiveSession(session_id=uuid.uuid4(), stream=ev.EventStream())
        live.stream.close()
        sid2 = fx.row(main.DEMO_ORG_ID)
        live.session_id = sid2
        main._SESSIONS[sid2] = live
        with fx.audio(sid2) as ws:
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_ENDED, exc
        assert fx.sources == []
    finally:
        fx.close()


# ---------------------------------------------------- one producer, two orgs --
def test_one_producer_per_session_scoped_to_the_organisation() -> None:
    """The single-producer rule, and the tenancy rule it depends on.

    Organisation A starts a session. A's own second socket is refused as BUSY
    (4423); organisation B's socket and an anonymous socket are refused as
    UNKNOWN (4404), the same answer a nonexistent id gets, so a session id
    never confirms a foreign row exists. When A's producer leaves, the session
    is over -- a reconnect is 4410, not a second call on the same consent.
    """
    fx = _Fixture()
    try:
        org_a, token_a = fx.organisation("Docks Ltd", "a@example.com")
        org_b, token_b = fx.organisation("Rival Ltd", "b@example.com")
        sid = fx.start(token_a)
        assert fx.session(sid).organisation_id == org_a

        with fx.audio(sid, token=token_a) as first:
            _ready(first)
            first.send_bytes(_pcm(100))
            assert len(fx.sources) == 1 and fx.sources[0].connected

            with fx.audio(sid, token=token_a, via_header=True) as second:
                exc = _closed_with(second)
            assert exc.code == WS_AUDIO_BUSY, exc

            with fx.audio(sid, token=token_b) as foreign:
                exc = _closed_with(foreign)
            assert exc.code == WS_AUDIO_UNKNOWN, exc

            with fx.audio(sid) as anonymous:
                exc = _closed_with(anonymous)
            assert exc.code == WS_AUDIO_UNKNOWN, exc

            # Refusals opened nothing upstream and touched the producer's
            # session not at all.
            assert len(fx.sources) == 1
            assert fx.sources[0].terminate_calls == 0

        # The producer left: exactly one Terminate, and the slot is not reusable.
        assert fx.sources[0].terminate_sent == 1
        with fx.audio(sid, token=token_a) as again:
            exc = _closed_with(again)
        assert exc.code == WS_AUDIO_ENDED, exc
        assert len(fx.sources) == 1
    finally:
        fx.close()


def test_anonymous_session_accepts_anonymous_audio() -> None:
    """The demo path: no account, consent through the gate, then a microphone."""
    fx = _Fixture()
    try:
        sid = fx.start()
        assert fx.session(sid).organisation_id == main.DEMO_ORG_ID
        with fx.audio(sid) as ws:
            _ready(ws)
            ws.send_bytes(_pcm(100))
            ws.send_text('{"type":"Terminate"}')
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_TERMINATED, exc
        assert exc.reason == "terminated"
        live = main._SESSIONS[sid]
        assert live.task is not None and live.task.done()
        first = live.stream.history[0]
        assert first.type == ev.SESSION_STARTED and first.data["source"] == "live"
        assert live.stream.history[-1].type == ev.SESSION_END
        assert fx.session(sid).end_reason == "user"
    finally:
        fx.close()


# --------------------------------------------------------------- frames -----
def test_frames_are_rechunked_to_100ms_and_paced_at_real_time() -> None:
    """Whatever the browser sends, upstream sees 100 ms frames no faster than
    the clock. 30 x 10 ms frames become 3 x 100 ms; the second and third go out
    no sooner than 100 ms after their predecessor; a 20 ms tail at Terminate is
    below the 50 ms upstream minimum and is dropped, not sent."""
    fx = _Fixture()
    try:
        sid = fx.start()
        with fx.audio(sid) as ws:
            _ready(ws)
            t_send = time.monotonic()
            for _ in range(30):
                ws.send_bytes(_pcm(10))
            ws.send_bytes(_pcm(20))
            ws.send_text('{"type":"Terminate"}')
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_TERMINATED
        src = fx.sources[0]
        assert [len(c) for c in src.chunks] == [AUDIO_CHUNK_BYTES] * 3, [len(c) for c in src.chunks]
        assert b"".join(src.chunks) == _pcm(300)
        assert all(AUDIO_MIN_FRAME_BYTES <= len(c) <= 1000 * AUDIO_BYTES_PER_MS
                   for c in src.chunks)
        # Paced against the schedule, not the previous send: frame k may go
        # no earlier than k x 100 ms after the first, within the 16 ms the
        # Windows loop clock is allowed to be early.
        offsets = [t - src.chunk_at[0] for t in src.chunk_at]
        assert all(off >= k * 0.1 - 0.02 for k, off in enumerate(offsets)), offsets
        total = src.chunk_at[-1] - t_send
        assert 0.18 <= total < 1.5, total
        assert src.terminate_sent == 1
        closed = [e for e in fx.audit(sid) if e.action == "socket.closed"]
        assert len(closed) == 1 and closed[0].detail["forwarded_ms"] == 300, closed
    finally:
        fx.close()


def test_a_tail_of_at_least_50ms_is_flushed_on_terminate() -> None:
    fx = _Fixture()
    try:
        sid = fx.start()
        with fx.audio(sid) as ws:
            _ready(ws)
            ws.send_bytes(_pcm(160))
            ws.send_text('{"type":"Terminate"}')
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_TERMINATED
        src = fx.sources[0]
        assert [len(c) for c in src.chunks] == [AUDIO_CHUNK_BYTES, 60 * AUDIO_BYTES_PER_MS]
        assert b"".join(src.chunks) == _pcm(160)
    finally:
        fx.close()


def test_odd_byte_count_closes_4422() -> None:
    fx = _Fixture()
    try:
        sid = fx.start()
        with fx.audio(sid) as ws:
            _ready(ws)
            ws.send_bytes(_pcm(100) + b"\x01")
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_BAD_FRAME, exc
        assert fx.sources[0].terminate_sent == 1
    finally:
        fx.close()


def test_faster_than_real_time_closes_4429() -> None:
    """Three seconds of audio in three frames, instantly. The first is accepted
    and starts draining; the accumulator crosses the 2 s bound on the third and
    the producer is refused with a reason, not with a 3007 from upstream."""
    fx = _Fixture()
    try:
        sid = fx.start()
        with fx.audio(sid) as ws:
            _ready(ws)
            for _ in range(3):
                ws.send_bytes(_pcm(1000))
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_TOO_FAST, exc
        assert "ahead of real time" in exc.reason
        src = fx.sources[0]
        # Whatever was forwarded before the refusal was still 100 ms frames.
        assert all(len(c) == AUDIO_CHUNK_BYTES for c in src.chunks)
        assert len(src.chunks) * AUDIO_CHUNK_BYTES <= AUDIO_MAX_AHEAD_BYTES + AUDIO_CHUNK_BYTES
        assert src.terminate_sent == 1
    finally:
        fx.close()


def test_unknown_text_frames_close_4400_without_a_traceback() -> None:
    fx = _Fixture()
    try:
        for payload in ('{"type":"UpdateConfiguration"}', "not json", "[1,2]"):
            sid = fx.start()
            with fx.audio(sid) as ws:
                _ready(ws)
                ws.send_text(payload)
                exc = _closed_with(ws)
            assert exc.code == WS_AUDIO_BAD_MESSAGE, (payload, exc)
            assert exc.reason == "unexpected message"
        # KeepAlive is accepted (a client heartbeat is not an error) and never
        # forwarded: the stub has no KeepAlive path and the session stays open.
        sid = fx.start()
        with fx.audio(sid) as ws:
            _ready(ws)
            ws.send_text('{"type":"KeepAlive"}')
            ws.send_bytes(_pcm(100))
            ws.send_text('{"type":"Terminate"}')
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_TERMINATED
        assert len(fx.sources[-1].chunks) == 1
        assert all(s.terminate_sent == 1 for s in fx.sources)
    finally:
        fx.close()


# ------------------------------------------------------------------ cap ------
def test_cap_fires_off_the_socket_clock_and_records_cap() -> None:
    """With a 1 s cap and a silent microphone -- no frames, so the runner's own
    frame-driven cap check never runs -- the ingress clock fires, upstream is
    terminated once, the socket closes 4408 and the row says `cap`."""
    fx = _Fixture(cap_seconds=1)
    try:
        sid = fx.start()
        t0 = time.monotonic()
        with fx.audio(sid) as ws:
            _ready(ws)
            ws.send_bytes(_pcm(100))
            exc = _closed_with(ws)
            elapsed = time.monotonic() - t0
        assert exc.code == WS_AUDIO_CAP, exc
        assert exc.reason == "session cap reached"
        assert 0.9 <= elapsed < 4.0, elapsed
        src = fx.sources[0]
        assert src.terminate_sent == 1, src.terminate_calls
        row = fx.session(sid)
        assert row.end_reason == "cap", row.end_reason
        assert row.ended_at is not None
        ended = [e for e in fx.audit(sid) if e.action == "session.ended"]
        assert len(ended) == 1 and ended[0].detail["end_reason"] == "cap", ended
        assert not main._SESSIONS[sid].running
    finally:
        fx.close()


# ------------------------------------------------------- terminate accounting --
def test_dropped_socket_sends_exactly_one_terminate() -> None:
    """The browser vanishes mid-call. Upstream gets one Terminate -- not zero,
    which bills to the 3 h ceiling, and not two, which would mean two things
    believe they own the socket."""
    fx = _Fixture()
    try:
        sid = fx.start()
        with fx.audio(sid) as ws:
            _ready(ws)
            ws.send_bytes(_pcm(100))
            ws.send_bytes(_pcm(100))
            # Drop without Terminate. The disconnect is sent explicitly and
            # the ingress given time to see it, because the test session's
            # context exit ALSO cancels the app task -- uvicorn only delivers
            # the disconnect, and that is the path being pinned here.
            ws.close(1000)
            src = fx.sources[0]
            deadline = time.monotonic() + 3.0
            while src.terminate_sent == 0 and time.monotonic() < deadline:
                time.sleep(0.02)
        assert src.terminate_sent == 1, (src.terminate_sent, src.terminate_calls)
        assert src.terminate_calls >= 1
        assert src.closed
        live = main._SESSIONS[sid]
        assert live.producer is None
        assert live.task is not None and live.task.done()
        assert not live.running
        row = fx.session(sid)
        assert row.end_reason == "user" and row.ended_at is not None
        actions = [e.action for e in fx.audit(sid)]
        assert actions.count("socket.opened") == 1
        assert actions.count("socket.closed") == 1
        assert actions.count("session.ended") == 1
        closed = next(e for e in fx.audit(sid) if e.action == "socket.closed")
        assert closed.detail["reason"] == "client disconnected"
        # The count is what was FORWARDED. A frame still in its pacing sleep
        # when the browser vanished is abandoned, not drained: a drop is not a
        # finished sentence, and the meter stops now rather than 2 s from now.
        assert closed.detail["forwarded_ms"] == 100 * len(src.chunks)
        assert 100 <= closed.detail["forwarded_ms"] <= 200
    finally:
        fx.close()


def test_cancelled_handler_still_sends_one_terminate() -> None:
    """The other way a socket dies: the server tears the handler down (shutdown,
    or the test session's context exit, which cancels the app task). The
    bookkeeping in the finally must survive its own cancellation."""
    fx = _Fixture()
    try:
        sid = fx.start()
        with fx.audio(sid) as ws:
            _ready(ws)
            ws.send_bytes(_pcm(100))
            # No close, no Terminate: straight out of the context.
        src = fx.sources[0]
        assert src.terminate_sent == 1, (src.terminate_sent, src.terminate_calls)
        assert not main._SESSIONS[sid].running
        row = fx.session(sid)
        assert row.end_reason == "user" and row.ended_at is not None
        actions = [e.action for e in fx.audit(sid)]
        assert actions.count("socket.closed") == 1 and actions.count("session.ended") == 1
    finally:
        fx.close()


def test_stop_route_ends_the_ingress_with_one_terminate() -> None:
    """ARCH 3.12's stop button while the microphone is open: the source is
    terminated by /stop, the ingress notices and closes, and the count is
    still one."""
    fx = _Fixture()
    try:
        sid = fx.start()
        with fx.audio(sid) as ws:
            _ready(ws)
            ws.send_bytes(_pcm(100))
            src = fx.sources[0]
            # The real route, on the app's own loop -- see StubSource.connect.
            with fx.Factory() as db:
                fut = asyncio.run_coroutine_threadsafe(
                    main.session_stop(sid, False, db), src.loop)
                assert fut.result(timeout=5) == {"ok": True, "deleted": False}
            exc = _closed_with(ws)
        assert exc.code == WS_AUDIO_ENDED, exc
        assert exc.reason in ("session stopped", "session ended")
        assert fx.session(sid).end_reason == "user"
        src = fx.sources[0]
        assert src.terminate_sent == 1, (src.terminate_sent, src.terminate_calls)
    finally:
        fx.close()


def test_unreachable_upstream_closes_4502_and_ends_the_session() -> None:
    fx = _Fixture(source_cls=FailingSource)
    try:
        sid = fx.start()
        with fx.audio(sid) as ws:
            exc = _closed_with(ws)
        assert exc.code == main.WS_AUDIO_UPSTREAM, exc
        assert exc.reason == "upstream unavailable"
        row = fx.session(sid)
        assert row.end_reason == "error" and row.ended_at is not None
        assert not main._SESSIONS[sid].running
        assert main._SESSIONS[sid].stream.history[-1].type == ev.ERROR
        assert "connection refused" not in str(
            [e.as_dict() for e in main._SESSIONS[sid].stream.history])
    finally:
        fx.close()


# ----------------------------------------------------------- privacy sweep --
def test_the_ingress_writes_bytes_nowhere_but_send_audio() -> None:
    """Grep the route's own source: the only sink for audio bytes is
    `send_audio`. No open(), no logging, no queue that could outlive the
    socket."""
    import inspect

    src = inspect.getsource(main._AudioIngress) + inspect.getsource(main.session_audio)
    for forbidden in ("open(", "logging", "logger", ".write(", "Queue(", "pickle",
                      "tempfile", "shelve"):
        assert forbidden not in src, forbidden
    assert src.count("send_audio(") == 1


if __name__ == "__main__":
    names = [n for n in list(globals()) if n.startswith("test_")]
    for name in names:
        globals()[name]()
        print("ok", name)
