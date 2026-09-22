"""Security properties found by the 22 September audit, pinned as tests.

Each test states a property the code or its docstring already claimed, and was
written before the fix so that it failed first. Section by section:

  A  the request-body bound holds for a streamed body, not only a declared one
  B  /health says what the client needs and nothing an attacker can time
  C  the interactive API map is not served in production
  D  the client address is the one the outermost TRUSTED proxy wrote
  E  production refuses placeholder secrets whatever the database is
  F  a cross-origin PUT -- the vocabulary save -- passes preflight

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


# --------------------------------------------------------------- section D ---

def test_forwarded_client_takes_the_entry_the_outermost_trusted_proxy_wrote() -> None:
    """READBACK_TRUSTED_PROXY_HOPS: the client is entry -hops, counted from the
    right. Everything to its left was written by the client itself."""
    from server.ratelimit import forwarded_client

    spoofed = "6.6.6.6, 203.0.113.9"                   # client wrote 6.6.6.6
    assert forwarded_client(spoofed, 1) == "203.0.113.9"
    via_cdn = "6.6.6.6, 203.0.113.9, 172.64.0.1"       # CDN appended its view
    assert forwarded_client(via_cdn, 2) == "203.0.113.9"
    # One hop too few would have merged every user into the CDN's address.
    assert forwarded_client(via_cdn, 1) == "172.64.0.1"
    # Fewer entries than hops: the only entry is the one a trusted proxy wrote.
    assert forwarded_client("203.0.113.9", 2) == "203.0.113.9"
    # Zero hops: the header is not evidence at all.
    assert forwarded_client(spoofed, 0) is None
    assert forwarded_client("", 1) is None
    assert forwarded_client(" , ", 1) is None


# --------------------------------------------------------------- section E ---

def test_production_refuses_placeholder_secrets_even_on_sqlite() -> None:
    """The refusal used to key on "the database is not SQLite", so a production
    box on SQLite signed every token with the secret printed in config.py."""
    import pytest

    with pytest.raises(RuntimeError, match="READBACK_SESSION_SECRET"):
        Settings(environment="production", database_url="sqlite:///./x.db")
    # A real secret and salt: constructs.
    Settings(environment="production", database_url="sqlite:///./x.db",
             session_secret="a" * 48, ip_hash_salt="b" * 48)
    # A laptop is still a laptop.
    Settings(database_url="sqlite:///./x.db")


# --------------------------------------------------------------- section F ---

def test_a_cross_origin_put_passes_preflight() -> None:
    """The web app PUTs /api/vocabulary with a bearer token. CORS allowed GET,
    POST and OPTIONS only, so in production -- Vercel calling Render -- the
    browser refused the preflight and the vocabulary pack could never be saved.
    It worked locally because the Vite dev proxy is same-origin."""
    fx = _Fixture()
    try:
        origin = _settings().cors_origin_list[0]
        r = fx.client.options("/api/vocabulary", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        })
        assert r.status_code == 200, r.status_code
        assert "PUT" in r.headers.get("access-control-allow-methods", "")
        assert r.headers.get("access-control-allow-origin") == origin
    finally:
        fx.close()


# --------------------------------------------------------------- section G ---

def _member(fx: _Fixture, org_name: str, email: str) -> dict[str, str]:
    from server import auth
    from server.models import Organisation, User

    with fx.Factory() as db:
        org = Organisation(name=org_name)
        user = User(organisation=org, email=email, name=org_name,
                    password_hash="pbkdf2_sha256$1$00$00", role="owner")
        db.add_all([org, user])
        db.commit()
        return {"Authorization": f"Bearer {auth.issue_token(user, _settings())}"}


def test_one_organisation_cannot_read_or_replace_anothers_catalogue() -> None:
    """The catalogue was one table for the whole deployment, readable and
    replaceable by ANY signed-in account -- and sign-up is open. A stranger
    could read another company's part list, or replace it, and the catalogue is
    exactly what vouches for a `catalogue` capture: silently, at edit distance
    up to 2, with no question asked. Each organisation now has its own."""
    fx = _Fixture()
    try:
        docks = _member(fx, "Docks Ltd", "ada@docks.example")
        rival = _member(fx, "Rival Co", "eve@rival.example")

        mine = [{"sku": "BX-4471-A", "description": "Bearing housing"}]
        assert fx.client.put("/api/catalogue", headers=docks,
                             json={"parts": mine}).status_code == 200

        # The other organisation sees nothing of it...
        assert fx.client.get("/api/catalogue", headers=rival).json()["parts"] == []
        # ...and replacing "the" catalogue replaces only its own.
        theirs = [{"sku": "EV-0001-X", "description": "planted"}]
        assert fx.client.put("/api/catalogue", headers=rival,
                             json={"parts": theirs}).status_code == 200
        assert fx.client.get("/api/catalogue", headers=docks).json()["parts"] == mine
        assert fx.client.get("/api/catalogue", headers=rival).json()["parts"] == theirs
    finally:
        fx.close()


def test_an_unscoped_catalogue_table_is_set_aside_not_read() -> None:
    """A database created before catalogues had an owner keeps the old table.
    Boot renames it aside -- never dropped, never served -- and creates the
    scoped one. Running twice changes nothing."""
    import sqlalchemy as sa

    from server.db import create_all as boot

    fd, path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_legacy_")
    os.close(fd)
    eng = make_engine(f"sqlite:///{path}", echo=False, settings=_settings())
    try:
        with eng.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE catalogue_part (sku VARCHAR(64) PRIMARY KEY, "
                "description VARCHAR(255) NOT NULL, rhyme_signature VARCHAR(64) "
                "NOT NULL, updated_at TIMESTAMP NOT NULL)")
            conn.exec_driver_sql("CREATE INDEX ix_catalogue_rhyme ON catalogue_part (rhyme_signature)")
            conn.exec_driver_sql(
                "INSERT INTO catalogue_part VALUES ('BX-4471-A', 'old', 'x', '2026-09-01')")
        boot(eng)
        boot(eng)
        insp = sa.inspect(eng)
        assert "organisation_id" in {c["name"] for c in insp.get_columns("catalogue_part")}
        assert "catalogue_part_unscoped_legacy" in insp.get_table_names()
        with eng.connect() as conn:
            kept = conn.exec_driver_sql(
                "SELECT sku FROM catalogue_part_unscoped_legacy").scalars().all()
            served = conn.exec_driver_sql("SELECT COUNT(*) FROM catalogue_part").scalar()
        assert kept == ["BX-4471-A"] and served == 0
    finally:
        eng.dispose()
