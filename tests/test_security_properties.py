"""Security properties found by the 22 September audit, pinned as tests.

Each test states a property the code or its docstring already claimed, and was
written before the fix so that it failed first. Section by section:

  A  the request-body bound holds for a streamed body, not only a declared one
  B  /health says what the client needs and nothing an attacker can time
  C  the interactive API map is not served in production

Runs under pytest or as a script.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from server.config import Settings, get_settings
from server.db import create_all, get_db, make_engine
from server.main import MAX_BODY_BYTES, app


def _settings() -> Settings:
    return Settings(replay_mode=True, session_secret="test-secret-secprop-1")


class _Fixture:
    def __init__(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_secprop_")
        os.close(fd)
        self.engine = make_engine(f"sqlite:///{self.path}", echo=False, settings=_settings())
        create_all(self.engine)
        self.Factory = sessionmaker(bind=self.engine, expire_on_commit=False)

        def _db():
            db = self.Factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_settings] = _settings
        self.client = TestClient(app, raise_server_exceptions=False)

    def close(self) -> None:
        app.dependency_overrides.clear()
        self.engine.dispose()


# --------------------------------------------------------------- section A ---

def _streamed(total: int, chunk: int = 64 * 1024):
    """A body with no Content-Length: httpx sends an iterator as chunked."""
    prefix = b'{"format":"iso6346","value":"'
    yield prefix
    sent = len(prefix)
    while sent < total:
        n = min(chunk, total - sent)
        yield b"M" * n
        sent += n
    yield b'"}'


def test_a_streamed_body_past_the_cap_is_refused() -> None:
    """`_bound_body`'s docstring promised that "a chunked body that runs past
    the cap is cut off rather than buffered". The code only read the
    Content-Length header, so a body that declared no length was buffered in
    full and parsed. Same flat 413 either way."""
    fx = _Fixture()
    try:
        r = fx.client.post("/api/validate", content=_streamed(MAX_BODY_BYTES + 64 * 1024),
                           headers={"Content-Type": "application/json"})
        assert r.status_code == 413, (r.status_code, r.text[:200])
        assert r.json().get("error") == "body_too_large"
    finally:
        fx.close()


def test_a_streamed_body_under_the_cap_still_works() -> None:
    """The bound must not break the ordinary chunked path."""
    fx = _Fixture()
    try:
        def small():
            yield b'{"format":"iso6346",'
            yield b'"value":"MSKU4158005"}'
        r = fx.client.post("/api/validate", content=small(),
                           headers={"Content-Type": "application/json"})
        assert r.status_code == 200, (r.status_code, r.text[:200])
        assert r.json()["valid"] is True
    finally:
        fx.close()


def test_a_lying_content_length_cannot_smuggle_a_bigger_body() -> None:
    """Content-Length is a claim. A small declared length with a larger body
    behind it is the other way around the header check."""
    fx = _Fixture()
    try:
        r = fx.client.post("/api/validate", content=_streamed(MAX_BODY_BYTES + 64 * 1024),
                           headers={"Content-Type": "application/json",
                                    "Content-Length": "40"})
        # Either refused as too large, or rejected as malformed -- never a 200.
        assert r.status_code in (400, 413, 422), r.status_code
    finally:
        fx.close()


# --------------------------------------------------------------- section B ---

def test_health_carries_no_load_counters() -> None:
    """The consent screen reads `live_capture` and `consent_version`; nothing
    reads the rest. `sessions_open` against the concurrency cap told anyone,
    unauthenticated, the exact moment admission was one session from full --
    the timing a capacity-exhaustion attempt needs. `sessions_retained` was an
    in-memory size. The fixture list is already in the client bundle."""
    fx = _Fixture()
    try:
        body = fx.client.get("/health").json()
        assert body["ok"] is True
        for needed in ("live_capture", "consent_required", "consent_version"):
            assert needed in body, needed
        for leaked in ("sessions_open", "sessions_retained", "fixtures"):
            assert leaked not in body, leaked
    finally:
        fx.close()


# --------------------------------------------------------------- section C ---

def test_the_api_map_is_off_unless_asked_for() -> None:
    """/docs, /redoc and /openapi.json hand a visitor every route and schema.
    Useful on a laptop, not on the deployment: off by default, on with
    READBACK_API_DOCS=true."""
    from server.main import _docs_urls

    assert _docs_urls(Settings(replay_mode=True)) == (None, None, None)
    assert _docs_urls(Settings(replay_mode=True, api_docs=True)) == (
        "/docs", "/redoc", "/openapi.json")
