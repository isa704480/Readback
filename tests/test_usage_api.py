"""GET /api/usage -- the deployment's daily budget and this organisation's own
spend, side by side.

Deterministic and offline: sessions are written straight to the table with
explicit billed_seconds, and the token is minted with auth.issue_token.

Runs under pytest or as a script.
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from server import auth
from server.config import Settings, get_settings
from server.db import create_all, get_db, make_engine
from server.main import app
from server.models import Organisation, Session, User

PLACEHOLDER_HASH = "pbkdf2_sha256$1$00$00"
BUDGET = 120_000


def _settings() -> Settings:
    return Settings(replay_mode=True, session_secret="test-secret-usage-1",
                    daily_budget_seconds=BUDGET)


class _Fixture:
    def __init__(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_usage_")
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

    def organisation(self, name: str, email: str) -> tuple[uuid.UUID, str]:
        with self.Factory() as db:
            org = Organisation(name=name)
            user = User(organisation=org, email=email, name=name.split()[0],
                        password_hash=PLACEHOLDER_HASH, role="owner")
            db.add(org)
            db.add(user)
            db.commit()
            return org.id, auth.issue_token(user, _settings())

    def session(self, org_id: uuid.UUID, *, billed: int, sockets: int = 1,
                started_at: datetime) -> None:
        with self.Factory() as db:
            db.add(Session(organisation_id=org_id, consent_version="2026-08-01",
                           consent_at=started_at, disclosure_played=True,
                           source="replay", started_at=started_at,
                           billed_seconds=billed, sockets=sockets))
            db.commit()

    def usage(self, token: str | None) -> object:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.get("/api/usage", headers=headers)


def test_deployment_budget_and_organisation_spend_are_both_reported() -> None:
    fx = _Fixture()
    try:
        docks, docks_token = fx.organisation("Docks Ltd", "ada@docks.example")
        rival, _rival_token = fx.organisation("Rival Freight", "eve@rival.example")
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1, hours=1)

        fx.session(docks, billed=30, started_at=now)            # today, 30 s
        fx.session(docks, billed=45, sockets=2, started_at=now)  # today, 90 socket-s
        fx.session(docks, billed=100, started_at=yesterday)      # not today
        fx.session(rival, billed=500, started_at=now)            # another tenant

        r = fx.usage(docks_token)
        assert r.status_code == 200, r.text
        body = r.json()

        dep = body["deployment"]
        assert dep["daily_budget_seconds"] == BUDGET
        # The deployment figure is every tenant's spend today: 30 + 90 + 500.
        assert dep["spent_today_seconds"] == 620
        assert dep["remaining_seconds"] == BUDGET - 620
        assert dep["alarm"] is False and dep["exhausted"] is False
        assert dep["replay_mode"] is True and dep["live_capture"] is False

        org = body["organisation"]
        # The organisation figure is Docks' own, today and in total.
        assert org["seconds_today"] == 120
        assert org["seconds_total"] == 220
        assert org["sessions_today"] == 2
        assert org["sessions_total"] == 3
        assert org["captures_total"] == 0
        assert org["daily_budget_seconds"] is None
    finally:
        fx.close()


def test_usage_needs_a_token() -> None:
    fx = _Fixture()
    try:
        fx.organisation("Docks Ltd", "ada@docks.example")
        assert fx.usage(None).status_code == 401
        assert fx.usage("rb1.not.a-token").status_code == 401
    finally:
        fx.close()


TESTS = [
    test_deployment_budget_and_organisation_spend_are_both_reported,
    test_usage_needs_a_token,
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
