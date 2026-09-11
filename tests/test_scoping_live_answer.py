"""The event stream and the answer route are organisation-scoped.

Before this, WS /api/session/{id}/live streamed any tenant's captured values
and questions to whoever held the id, and POST /api/session/{id}/answer let
any caller answer another tenant's question -- and an answer changes what is
written. Both now resolve the caller's organisation the way the audio socket
does (bearer header or token subprotocol; anonymous = the demo tenant) and
call a foreign session "unknown".

Runs under pytest or as a script.
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

from server import auth
from server.config import Settings, get_settings
from server.db import create_all, get_db, make_engine
from server.main import DEMO_ORG_ID, DEMO_ORG_NAME, LIVE_SUBPROTOCOL, app
from server.models import Organisation, User

PLACEHOLDER_HASH = "pbkdf2_sha256$1$00$00"


def _settings() -> Settings:
    return Settings(replay_mode=True, session_secret="test-secret-scope-1")


class _Fixture:
    def __init__(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_scope_")
        os.close(fd)
        self.engine = make_engine(f"sqlite:///{self.path}", echo=False, settings=_settings())
        create_all(self.engine)
        self.Factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        # The app's lifespan seeds the demo tenant; a bare TestClient does not.
        with self.Factory() as db:
            if db.get(Organisation, DEMO_ORG_ID) is None:
                db.add(Organisation(id=DEMO_ORG_ID, name=DEMO_ORG_NAME))
                db.commit()

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

    def organisation(self, name: str, email: str) -> str:
        with self.Factory() as db:
            org = Organisation(name=name)
            user = User(organisation=org, email=email, name=name.split()[0],
                        password_hash=PLACEHOLDER_HASH, role="owner")
            db.add(org)
            db.add(user)
            db.commit()
            return auth.issue_token(user, _settings())

    def replay(self, token: str | None) -> str:
        """A session in _SESSIONS with a history, filed under the token's tenant."""
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = self.client.post("/api/demo/replay", headers=headers,
                             json={"fixture": "iso_clean_single_turn", "answer_timeout_ms": 50})
        assert r.status_code == 200, r.text
        return r.json()["session_id"]

    def live_first_message(self, session_id: str, token: str | None) -> tuple[dict, int | None]:
        """The first frame on /live, and the close code if the server hung up."""
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with self.client.websocket_connect(f"/api/session/{session_id}/live",
                                           headers=headers,
                                           subprotocols=[LIVE_SUBPROTOCOL]) as ws:
            first = ws.receive_json()
            code: int | None = None
            if first.get("type") == "error":
                try:
                    ws.receive_json()
                except WebSocketDisconnect as exc:
                    code = exc.code
            return first, code

    def answer(self, session_id: str, token: str | None) -> int:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = self.client.post(f"/api/session/{session_id}/answer", headers=headers,
                             json={"question_id": str(uuid.uuid4()), "text": "kilo"})
        return r.status_code


def test_the_event_stream_is_scoped_to_the_session_owner() -> None:
    fx = _Fixture()
    try:
        docks = fx.organisation("Docks Ltd", "ada@docks.example")
        rival = fx.organisation("Rival Freight", "eve@rival.example")
        sid = fx.replay(docks)

        first, _ = fx.live_first_message(sid, docks)
        assert first["type"] == "session.started", first

        first, code = fx.live_first_message(sid, rival)
        assert first["type"] == "error" and first["message"] == "unknown session"
        assert code == 4404

        first, code = fx.live_first_message(sid, None)   # anonymous = demo tenant
        assert first["type"] == "error" and code == 4404
    finally:
        fx.close()


def test_an_answer_to_another_tenants_session_is_unknown_not_refused() -> None:
    """404, not 403 or 409: the route must not confirm a foreign session
    exists, and the owner's own 409 ("nothing waiting") proves the guard is
    what stopped the rival, not the absence of a question."""
    fx = _Fixture()
    try:
        docks = fx.organisation("Docks Ltd", "ada@docks.example")
        rival = fx.organisation("Rival Freight", "eve@rival.example")
        sid = fx.replay(docks)
        assert fx.answer(sid, docks) == 409
        assert fx.answer(sid, rival) == 404
        assert fx.answer(sid, None) == 404
    finally:
        fx.close()


def test_the_demo_tenant_still_reaches_its_own_sessions_anonymously() -> None:
    """The demo screen and the e2e suite create and read demo-tenant sessions
    with no token at all; scoping must not take that away."""
    fx = _Fixture()
    try:
        sid = fx.replay(None)
        first, _ = fx.live_first_message(sid, None)
        assert first["type"] == "session.started"
        assert fx.answer(sid, None) == 409
    finally:
        fx.close()


def test_the_browsers_handshake_works_with_and_without_a_token() -> None:
    """The browser cannot set a header on a WebSocket, so the token rides a
    second subprotocol and the server must SELECT the first one -- a browser
    fails a handshake whose offered subprotocol the server ignored. Both
    shapes the client sends are exercised here."""
    fx = _Fixture()
    try:
        docks = fx.organisation("Docks Ltd", "ada@docks.example")
        sid = fx.replay(docks)

        # Signed in: [readback.live, readback.token.<token>] -> readback.live.
        with fx.client.websocket_connect(
                f"/api/session/{sid}/live",
                subprotocols=[LIVE_SUBPROTOCOL, f"readback.token.{docks}"]) as ws:
            assert ws.receive_json()["type"] == "session.started"

        # Anonymous on a demo session: [readback.live] alone.
        anon_sid = fx.replay(None)
        with fx.client.websocket_connect(
                f"/api/session/{anon_sid}/live", subprotocols=[LIVE_SUBPROTOCOL]) as ws:
            assert ws.receive_json()["type"] == "session.started"
    finally:
        fx.close()


TESTS = [
    test_the_browsers_handshake_works_with_and_without_a_token,
    test_the_event_stream_is_scoped_to_the_session_owner,
    test_an_answer_to_another_tenants_session_is_unknown_not_refused,
    test_the_demo_tenant_still_reaches_its_own_sessions_anonymously,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc!r}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
