"""The platform admin panel (server/routes/admin.py, docs/ADMIN.md).

  A  who gets in: operators only, and a tenant cannot tell the panel exists
  B  every switch the panel sets is enforced where it matters, not only stored
  C  users: disable takes effect on the next request; no self- or peer-lockout
  D  quality: the traffic metrics compute what they claim to
  E  the benchmark scores against truth -- and can fail
  F  the CLI is the only way in, and it is audited

Runs under pytest.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from server import auth, main, quality
from server.config import Settings, get_settings
from server.db import create_all, get_db, make_engine
from server.models import (
    AuditEvent,
    Capture,
    Organisation,
    PlatformAdmin,
    QuestionEvent,
    Session,
    User,
)

HASH = "pbkdf2_sha256$1$00$00"
SECRET = "test-secret-admin-1"


def _settings(**over) -> Settings:
    base = dict(replay_mode=True, session_secret=SECRET)
    base.update(over)
    return Settings(**base)


class _Fixture:
    def __init__(self, **settings_over) -> None:
        self.settings = _settings(**settings_over)
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_admin_")
        os.close(fd)
        self.engine = make_engine(f"sqlite:///{self.path}", echo=False, settings=self.settings)
        create_all(self.engine)
        self.Factory = sessionmaker(bind=self.engine, expire_on_commit=False)

        def _db():
            db = self.Factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = _db
        main.app.dependency_overrides[get_settings] = lambda: self.settings
        for window in (main._PER_HOUR, main._PER_DAY, main._ADMISSIONS):
            window.counts.clear()
        main._SESSIONS.clear()
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def close(self) -> None:
        main.app.dependency_overrides.clear()
        main._SESSIONS.clear()
        self.engine.dispose()

    def member(self, org_name: str, email: str, *, admin: bool = False,
               org_id: uuid.UUID | None = None) -> tuple[dict[str, str], User]:
        with self.Factory() as db:
            org = db.get(Organisation, org_id) if org_id else Organisation(name=org_name)
            user = User(organisation=org, email=email, name=org_name, password_hash=HASH,
                        role="owner")
            db.add_all([org, user])
            db.flush()
            if admin:
                db.add(PlatformAdmin(user_id=user.id, granted_by="test"))
            db.commit()
            return {"Authorization": f"Bearer {auth.issue_token(user, self.settings)}"}, user

    def audit(self, action: str) -> list[AuditEvent]:
        with self.Factory() as db:
            return list(db.scalars(select(AuditEvent).where(AuditEvent.action == action)))


def _start(fx: _Fixture, headers: dict[str, str] | None = None):
    for window in (main._PER_HOUR, main._PER_DAY, main._ADMISSIONS):
        window.counts.clear()
    main._SESSIONS.clear()
    return fx.client.post("/api/session/start", headers=headers or {},
                          json={"consent": {"accepted": True}})


# --------------------------------------------------------------- section A ---

def test_only_an_operator_gets_in_and_a_tenant_sees_404() -> None:
    fx = _Fixture()
    try:
        owner, _ = fx.member("Docks Ltd", "ada@docks.example")
        op, _ = fx.member("Readback", "ops@readback.example", admin=True)
        assert fx.client.get("/api/admin/me").status_code == 401
        for path in ("/api/admin/me", "/api/admin/overview", "/api/admin/organisations",
                     "/api/admin/users", "/api/admin/system", "/api/admin/audit"):
            r = fx.client.get(path, headers=owner)
            assert r.status_code == 404, (path, r.status_code)
        assert fx.client.get("/api/admin/me", headers=op).json()["email"] == "ops@readback.example"
        for path in ("/api/admin/overview", "/api/admin/organisations", "/api/admin/users",
                     "/api/admin/system", "/api/admin/audit", "/api/admin/controls",
                     "/api/admin/quality", "/api/admin/sessions/live"):
            assert fx.client.get(path, headers=op).status_code == 200, path
    finally:
        fx.close()


def test_a_disabled_operator_loses_the_panel() -> None:
    fx = _Fixture()
    try:
        op, user = fx.member("Readback", "ops@readback.example", admin=True)
        with fx.Factory() as db:
            db.get(User, user.id).active = False
            db.commit()
        assert fx.client.get("/api/admin/me", headers=op).status_code in (401, 404)
    finally:
        fx.close()


def test_system_reports_presence_of_the_key_never_the_key() -> None:
    fx = _Fixture(assemblyai_api_key="sk-live-DO-NOT-LEAK-123")
    try:
        op, _ = fx.member("Readback", "ops@readback.example", admin=True)
        r = fx.client.get("/api/admin/system", headers=op)
        assert r.status_code == 200
        assert r.json()["assemblyai_key_present"] is True
        assert "DO-NOT-LEAK" not in r.text and SECRET not in r.text
    finally:
        fx.close()


# --------------------------------------------------------------- section B ---

def test_suspension_refuses_sessions_and_replays_and_reinstating_restores() -> None:
    fx = _Fixture()
    try:
        op, _ = fx.member("Readback", "ops@readback.example", admin=True)
        owner, user = fx.member("Docks Ltd", "ada@docks.example")
        org_id = str(user.organisation_id)

        assert _start(fx, owner).status_code == 200
        r = fx.client.post(f"/api/admin/organisations/{org_id}/suspend", headers=op,
                           json={"reason": "chargeback"})
        assert r.status_code == 200 and r.json()["active"] is False

        refused = _start(fx, owner)
        assert refused.status_code == 403
        assert refused.json()["error"] == "organisation_suspended"
        replay = fx.client.post("/api/demo/replay", headers=owner,
                                json={"fixture": "iso_clean_single_turn"})
        assert replay.status_code == 403

        assert fx.client.post(f"/api/admin/organisations/{org_id}/reinstate",
                              headers=op).status_code == 200
        assert _start(fx, owner).status_code == 200

        suspended = fx.audit("admin.org.suspended")
        assert len(suspended) == 1 and suspended[0].actor.startswith("admin:")
        assert suspended[0].detail["reason"] == "chargeback"
        assert fx.audit("admin.org.reinstated")
    finally:
        fx.close()


def test_an_organisation_budget_drops_its_sessions_to_replay() -> None:
    """`Organisation.daily_budget_seconds` existed and was read by nothing."""
    fx = _Fixture(replay_mode=False, assemblyai_api_key="k")
    try:
        op, _ = fx.member("Readback", "ops@readback.example", admin=True)
        owner, user = fx.member("Docks Ltd", "ada@docks.example")
        assert _start(fx, owner).json()["live_capture"] is True

        r = fx.client.put(f"/api/admin/organisations/{user.organisation_id}/budget",
                          headers=op, json={"daily_budget_seconds": 0})
        assert r.status_code == 200
        assert _start(fx, owner).json()["live_capture"] is False
        assert any(e.detail.get("reason") == "organisation_budget"
                   for e in fx.audit("replay.entered"))

        # Clearing it hands the organisation back to the deployment's budget.
        fx.client.put(f"/api/admin/organisations/{user.organisation_id}/budget",
                      headers=op, json={"daily_budget_seconds": None})
        assert _start(fx, owner).json()["live_capture"] is True
        assert fx.client.put(f"/api/admin/organisations/{user.organisation_id}/budget",
                             headers=op, json={"daily_budget_seconds": -5}).status_code == 422
    finally:
        fx.close()


def test_live_pause_sends_new_sessions_to_replay() -> None:
    fx = _Fixture(replay_mode=False, assemblyai_api_key="k")
    try:
        op, _ = fx.member("Readback", "ops@readback.example", admin=True)
        owner, _ = fx.member("Docks Ltd", "ada@docks.example")
        assert fx.client.put("/api/admin/controls", headers=op,
                             json={"live_paused": True}).json()["live_paused"] is True
        assert _start(fx, owner).json()["live_capture"] is False
        assert any(e.detail.get("reason") == "live_paused" for e in fx.audit("replay.entered"))
        fx.client.put("/api/admin/controls", headers=op, json={"live_paused": False})
        assert _start(fx, owner).json()["live_capture"] is True
        assert len(fx.audit("admin.control.set")) == 2
    finally:
        fx.close()


def test_signup_pause_refuses_new_accounts_only() -> None:
    fx = _Fixture()
    try:
        op, _ = fx.member("Readback", "ops@readback.example", admin=True)
        fx.client.put("/api/admin/controls", headers=op, json={"signups_paused": True})
        r = fx.client.post("/api/auth/signup", json={
            "name": "Eve", "company": "Rival Co", "email": "eve@rival.example",
            "password": "correct horse battery staple 91"})
        assert r.status_code == 403 and r.json()["error"] == "signups_paused"
        assert fx.client.get("/api/auth/me", headers=op).status_code == 200
    finally:
        fx.close()


def test_controls_refuse_unknown_keys() -> None:
    fx = _Fixture()
    try:
        op, _ = fx.member("Readback", "ops@readback.example", admin=True)
        assert fx.client.put("/api/admin/controls", headers=op,
                             json={"make_me_root": True}).status_code == 400
        assert fx.client.put("/api/admin/controls", headers=op, json={}).status_code == 400
    finally:
        fx.close()


# --------------------------------------------------------------- section C ---

def test_disabling_a_user_revokes_their_token_on_the_next_request() -> None:
    fx = _Fixture()
    try:
        op, admin_user = fx.member("Readback", "ops@readback.example", admin=True)
        owner, user = fx.member("Docks Ltd", "ada@docks.example")
        assert fx.client.get("/api/auth/me", headers=owner).status_code == 200
        assert fx.client.post(f"/api/admin/users/{user.id}/disable",
                              headers=op).status_code == 200
        assert fx.client.get("/api/auth/me", headers=owner).status_code == 401
        assert fx.client.post(f"/api/admin/users/{user.id}/enable",
                              headers=op).status_code == 200
        assert fx.client.get("/api/auth/me", headers=owner).status_code == 200

        # No lockouts: not yourself, and not another operator.
        assert fx.client.post(f"/api/admin/users/{admin_user.id}/disable",
                              headers=op).json()["error"] == "cannot_disable_self"
        _, peer = fx.member("Readback", "ops2@readback.example", admin=True,
                            org_id=admin_user.organisation_id)
        assert fx.client.post(f"/api/admin/users/{peer.id}/disable",
                              headers=op).json()["error"] == "target_is_admin"
    finally:
        fx.close()


# --------------------------------------------------------------- section D ---

def test_quality_metrics_compute_what_they_claim() -> None:
    fx = _Fixture()
    try:
        op, user = fx.member("Readback", "ops@readback.example", admin=True)
        now = datetime.now(timezone.utc)
        with fx.Factory() as db:
            s = Session(organisation_id=user.organisation_id, started_at=now,
                        consent_version="2026-09-01", consent_at=now, source="live",
                        confidence_regime="per_char")
            db.add(s)
            db.flush()

            def cap(**kw):
                c = Capture(session_id=s.id, format_type="iso6346", heard_value="MSAU4158005",
                            final_value="MSKU4158005", validated_by="check_digit",
                            second_signal="prefix", rung=0, **kw)
                db.add(c)
                db.flush()
                return c

            cap(status="committed", silent=True, corrected=True, questions_asked=0, latency_ms=300)
            cap(status="committed", silent=True, corrected=False, questions_asked=0, latency_ms=500)
            asked_right = cap(status="committed", silent=False, corrected=True,
                              questions_asked=1, latency_ms=2100)
            asked_needless = cap(status="committed", silent=False, corrected=False,
                                 questions_asked=1, latency_ms=1900)
            cap(status="flagged", silent=False, corrected=False, questions_asked=0,
                handed_over=True, handover_reason="budget_exhausted")
            # Heard A at position 2; the person said K -> the question was needed.
            db.add(QuestionEvent(session_id=s.id, capture_id=asked_right.id, rung=3,
                                 spoken=True, position=2, form="alternative", question_text="q",
                                 offered=["A", "K"], answered=True, answer_in_grammar=True,
                                 answer_char="K", resolution_ms=1500))
            # Heard M at position 0; the person said M -> it was not.
            db.add(QuestionEvent(session_id=s.id, capture_id=asked_needless.id, rung=3,
                                 spoken=True, position=0, form="confirm", question_text="q",
                                 offered=["M", "N"], answered=True, answer_in_grammar=True,
                                 answer_char="M", resolution_ms=1700))
            db.commit()

        q = fx.client.get("/api/admin/quality?days=1", headers=op).json()
        assert q["captures"] == {"total": 5, "committed": 4, "flagged": 1, "unverified": 0}
        assert q["rates"]["silent_commit_rate"] == 0.5
        assert q["rates"]["silent_repair_rate"] == 0.25
        assert q["rates"]["asked_rate"] == 0.4
        assert q["rates"]["handover_rate"] == 0.2
        assert q["questions"]["needed_rate"] == 0.5
        assert q["questions"]["unnecessary_rate"] == 0.5
        assert q["regimes"] == {"per_char": 1}
        assert q["by_format"][0]["format"] == "iso6346"
        assert fx.client.get("/api/admin/quality?days=0", headers=op).status_code == 400
    finally:
        fx.close()


# --------------------------------------------------------------- section E ---

def test_benchmark_scores_every_fixture_against_truth() -> None:
    fx = _Fixture()
    try:
        op, _ = fx.member("Readback", "ops@readback.example", admin=True)
        r = fx.client.post("/api/admin/quality/benchmark", headers=op).json()["result"]
        assert r["fixtures"] >= 8
        assert r["correct"] == r["fixtures"] and r["silent_wrong"] == 0
        assert r["questions_at_right_position"] == r["questions_expected"] >= 1
        assert fx.audit("admin.benchmark.run")
    finally:
        fx.close()


def test_the_benchmark_can_fail() -> None:
    """An instrument that cannot report a failure measures nothing. A person
    who answers every question WRONG must turn the blind fixture red."""
    real = quality._spoken
    quality._spoken = lambda char: "zulu"
    try:
        r = asyncio.run(quality.run_benchmark())
    finally:
        quality._spoken = real
    blind = next(x for x in r["results"] if x["fixture"] == "iso_blind_substitution")
    assert blind["correct"] is False
    assert r["accuracy"] < 1.0


# --------------------------------------------------------------- section F ---

def test_the_cli_grants_and_revokes_and_both_are_audited(monkeypatch) -> None:
    from server import admin_cli

    fx = _Fixture()
    try:
        _, user = fx.member("Docks Ltd", "ada@docks.example")
        monkeypatch.setattr(admin_cli, "get_sessionmaker", lambda: fx.Factory)
        monkeypatch.setattr(admin_cli, "create_all", lambda: None)

        assert admin_cli.main(["grant", "nobody@example.com"]) == 1
        assert admin_cli.main(["grant", "ADA@docks.example"]) == 0
        with fx.Factory() as db:
            assert db.get(PlatformAdmin, user.id) is not None
        assert admin_cli.main(["revoke", "ada@docks.example"]) == 0
        with fx.Factory() as db:
            assert db.get(PlatformAdmin, user.id) is None
        assert fx.audit("admin.granted") and fx.audit("admin.revoked")
        assert admin_cli.main(["make-root"]) == 2
    finally:
        fx.close()


def test_no_http_route_writes_the_admin_table() -> None:
    """The grant path is the CLI. If a route ever names PlatformAdmin in a
    write, it has to be looked at by a person first."""
    src = (Path(__file__).resolve().parents[1] / "server").rglob("*.py")
    writers = [p.name for p in src
               if p.name not in ("admin_cli.py", "models.py")
               and "PlatformAdmin(" in p.read_text(encoding="utf-8")]
    assert writers == [], writers


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
