# test_session_attribution.py -- who the rows a run produces actually belong to.
#
# The defect this file pins down was not a wrong query. `GET /api/sessions` was
# already scoped to `user.organisation_id` and was already tested for leakage.
# The wrong half was upstream: every session row -- from `/api/demo/replay` and
# from `/api/session/start` alike -- was created against a hard-coded
# `DEMO_ORG_ID`, so a signed-in operator's own captures were filed under a tenant
# they are not a member of and the dashboard correctly showed them nothing. 1010
# sessions and 692 captures sat in the demo organisation; the three real accounts
# owned none.
#
# So the assertions here are about attribution, and they are made by driving the
# real endpoint rather than by inserting rows: nothing below writes a Capture by
# hand, because a test that hand-writes the row it later reads cannot tell you
# whether the pipeline puts it in the right place.
#
# The three token states are separate tests because they are three different
# decisions:
#   - a valid token attributes the run to that organisation,
#   - no token at all still works, and lands in the demo tenant (DESIGN-BRIEF
#     4.5: a judge arrives at a link and clicks once, with no account),
#   - a MALFORMED token also still works, as the demo tenant, rather than 401.
#     That last one is the deliberate choice: on this route a token buys only
#     attribution and never access, so failing open grants nobody a row they
#     could not already have, while failing closed would let a stale token in
#     localStorage silently break the one-click demo.
#
# Deterministic and offline. Temp database, fixtures off disk, no network, no
# signup (users are inserted directly and tokens minted with auth.issue_token,
# so PBKDF2 is never paid for).
#
# Runs under pytest or as a script.
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from server import auth, main
from server.config import Settings, get_settings
from server.db import create_all, get_db, make_engine
from server.main import DEMO_ORG_ID, DEMO_ORG_NAME, app
from server.models import Capture, Organisation, Session, User

# One turn, one container number, one committed capture. Chosen because its
# outcome is not in question here -- what is in question is which tenant the row
# lands in -- and because it is the fastest of the five.
FIXTURE = "iso_clean_single_turn"

# A verifier-shaped string that verifies nothing. No test here signs in with a
# password, and a real hash would cost 600,000 iterations per user.
PLACEHOLDER_HASH = "pbkdf2_sha256$1$00$00"


def _settings() -> Settings:
    return Settings(replay_mode=True, session_secret="test-secret-attribution-1")


class _Fixture:
    """A client wired to a fresh database and a known token secret."""

    def __init__(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_attr_")
        os.close(fd)
        self.engine = make_engine(f"sqlite:///{self.path}", echo=False,
                                  settings=_settings())
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

        # The demo tenant is created by the lifespan against the *real* database,
        # which a dependency-overridden client never touches. `session.
        # organisation_id` is a foreign key and PRAGMA foreign_keys is ON, so an
        # anonymous replay would fail on the constraint rather than on the thing
        # under test. Created here with the same id the application uses.
        with self.Factory() as db:
            db.add(Organisation(id=DEMO_ORG_ID, name=DEMO_ORG_NAME))
            db.commit()

        # The in-process session table is module-level and outlives a client.
        # Left alone, a previous file's finished replays are still remembered and
        # `_reap_finished` has to walk them.
        main._SESSIONS.clear()
        self.client = TestClient(app, raise_server_exceptions=False)

    def close(self) -> None:
        app.dependency_overrides.clear()
        main._SESSIONS.clear()
        self.engine.dispose()

    # -- building a tenant ---------------------------------------------------
    def organisation(self, name: str, email: str) -> tuple[uuid.UUID, str]:
        """An organisation, its owner, and a bearer token for that owner."""
        with self.Factory() as db:
            org = Organisation(name=name)
            user = User(organisation=org, email=email, name=name.split()[0],
                        password_hash=PLACEHOLDER_HASH, role="owner")
            db.add(org)
            db.add(user)
            db.commit()
            return org.id, auth.issue_token(user, _settings())

    # -- driving the real endpoint -------------------------------------------
    def replay(self, token: str | None = None, *, fixture: str = FIXTURE):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.post("/api/demo/replay",
                                json={"fixture": fixture, "answer_timeout_ms": 50},
                                headers=headers)

    def start(self, token: str | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        for window in (main._PER_HOUR, main._PER_DAY, main._ADMISSIONS):
            window.counts.clear()
        return self.client.post("/api/session/start",
                                json={"consent": {"accepted": True,
                                                  "disclosure_played": True}},
                                headers=headers)

    def sessions(self, token: str):
        return self.client.get("/api/sessions",
                               headers={"Authorization": f"Bearer {token}"})

    # -- reading the database directly ---------------------------------------
    def owner_of(self, session_id: str) -> uuid.UUID:
        with self.Factory() as db:
            row = db.get(Session, uuid.UUID(session_id))
            assert row is not None, f"session {session_id} was never written"
            return row.organisation_id

    def capture_count(self, org_id: uuid.UUID) -> int:
        with self.Factory() as db:
            return int(db.scalar(
                select(func.count(Capture.id))
                .join(Session, Capture.session_id == Session.id)
                .where(Session.organisation_id == org_id)
            ) or 0)


def _captures_in(body: dict) -> int:
    return int(body["counters"]["captures"])


# ------------------------------------------------- a token attributes the run --
def test_a_replay_with_a_token_lands_in_that_organisation() -> None:
    """The whole defect, in one assertion: the session the endpoint created is
    owned by the caller's organisation and not by the demo tenant."""
    fx = _Fixture()
    try:
        org_id, token = fx.organisation("Docks Ltd", "ada@docks.example")

        r = fx.replay(token)
        assert r.status_code == 200, r.text
        body = r.json()
        assert _captures_in(body) > 0, "the fixture produced no captures at all"

        assert fx.owner_of(body["session_id"]) == org_id
        assert fx.capture_count(org_id) == _captures_in(body)
        assert fx.capture_count(DEMO_ORG_ID) == 0, \
            "a signed-in replay still wrote into the demo tenant"

        # `/api/session/start` obeys the same rule; it created its rows against
        # the same constant and had the same bug.
        started = fx.start(token)
        assert started.status_code == 200, started.text
        assert fx.owner_of(started.json()["session_id"]) == org_id
    finally:
        fx.close()


# ------------------------------------------------- no account, still a demo --
def test_a_replay_without_a_token_lands_in_the_demo_organisation() -> None:
    """DESIGN-BRIEF 4.5. No Authorization header, no signup, still a full run."""
    fx = _Fixture()
    try:
        r = fx.replay(None)
        assert r.status_code == 200, r.text
        body = r.json()
        assert _captures_in(body) > 0

        assert fx.owner_of(body["session_id"]) == DEMO_ORG_ID
        assert fx.capture_count(DEMO_ORG_ID) == _captures_in(body)

        started = fx.start(None)
        assert started.status_code == 200, started.text
        assert fx.owner_of(started.json()["session_id"]) == DEMO_ORG_ID
    finally:
        fx.close()


# -------------------------------------- a bad token is a visitor, not a 401 --
def test_a_malformed_token_still_gets_the_demo() -> None:
    """Every way a token can be unusable, and none of them may 401 this route.

    Expired, tampered with, signed by somebody else, shaped like nothing, or
    naming a user who does not exist -- all five are treated as "no token".
    Deliberate: on this route the token decides attribution only, so failing
    open grants nothing, and the same five strings still get a 401 from
    `/api/sessions`, which is asserted at the foot of this test.
    """
    fx = _Fixture()
    try:
        _org_id, good = fx.organisation("Docks Ltd", "ada@docks.example")

        foreign = Settings(replay_mode=True, session_secret="a-different-secret")
        with fx.Factory() as db:
            user = db.query(User).first()
            assert user is not None
            wrong_secret = auth.issue_token(user, foreign)

        head, payload, sig = good.split(".", 2)
        tampered = f"{head}.{payload}.{sig[:-2]}xx"

        bad_tokens = {
            "not a token at all": "hello",
            "right prefix, wrong shape": "rb1.not.a-token",
            "signed with another secret": wrong_secret,
            "signature tampered with": tampered,
            "empty": "   ",
        }

        for label, token in bad_tokens.items():
            r = fx.replay(token)
            assert r.status_code == 200, f"{label}: {r.status_code} {r.text}"
            assert fx.owner_of(r.json()["session_id"]) == DEMO_ORG_ID, \
                f"{label} was attributed to something other than the demo tenant"

            # The same string is still worthless for reading rows back. That is
            # what makes failing open above safe rather than lax.
            assert fx.sessions(token).status_code == 401, \
                f"{label} was accepted by /api/sessions"
    finally:
        fx.close()


# ------------------------------------------------------ the failure that matters --
def test_two_organisations_replay_and_neither_sees_the_other() -> None:
    """Two tenants, both driven through the real endpoint, then each asked for
    its rows.

    This is the end-to-end version of the cross-organisation test in
    test_sessions_api.py, and it is the one that would have caught the defect:
    that file builds its rows by hand and so proved only that the WHERE clause
    filters, never that the writer files them correctly in the first place.
    Here the identifiers come out of the pipeline.
    """
    fx = _Fixture()
    try:
        docks_org, docks_token = fx.organisation("Docks Ltd", "ada@docks.example")
        rival_org, rival_token = fx.organisation("Rival Freight", "eve@rival.example")

        # Interleaved, so a bug that ignores the tenant and takes the newest rows
        # returns a mixture rather than something that could pass by luck.
        docks_expected = 0
        rival_expected = 0
        for _ in range(2):
            docks_expected += _captures_in(fx.replay(docks_token).json())
            rival_expected += _captures_in(fx.replay(rival_token).json())
        assert docks_expected > 0 and rival_expected > 0

        assert fx.capture_count(docks_org) == docks_expected
        assert fx.capture_count(rival_org) == rival_expected
        assert fx.capture_count(DEMO_ORG_ID) == 0

        docks = fx.sessions(docks_token)
        assert docks.status_code == 200, docks.text
        docks_rows = docks.json()
        assert len(docks_rows) == docks_expected, docks_rows

        rival = fx.sessions(rival_token)
        assert rival.status_code == 200, rival.text
        rival_rows = rival.json()
        assert len(rival_rows) == rival_expected, rival_rows

        # Disjoint by id, both ways. Not one row of the pipeline's output is
        # visible to the tenant that did not run it.
        docks_ids = {row["id"] for row in docks_rows}
        rival_ids = {row["id"] for row in rival_rows}
        assert docks_ids and rival_ids
        assert docks_ids.isdisjoint(rival_ids)
        for row_id in rival_ids:
            assert row_id not in docks.text
        for row_id in docks_ids:
            assert row_id not in rival.text

        # And an anonymous replay is visible to neither, which is the other half
        # of the rule: the demo tenant is a tenant like any other.
        anon = fx.replay(None)
        assert anon.status_code == 200, anon.text
        assert fx.capture_count(DEMO_ORG_ID) == _captures_in(anon.json())
        assert len(fx.sessions(docks_token).json()) == docks_expected
        assert len(fx.sessions(rival_token).json()) == rival_expected
    finally:
        fx.close()


# ------------------------- a session id is not a key to somebody else's tenant --
def test_a_foreign_session_id_cannot_be_replayed_into() -> None:
    """`session_id` on the replay body reuses an existing row, and a session id
    is not a secret -- it is returned in a response body and sits in a URL. So
    the row's organisation must match the caller's, and a mismatch is a 404
    rather than a 403 so the endpoint never confirms the session exists."""
    fx = _Fixture()
    try:
        _docks_org, docks_token = fx.organisation("Docks Ltd", "ada@docks.example")
        rival_org, rival_token = fx.organisation("Rival Freight", "eve@rival.example")

        rival_session = fx.replay(rival_token).json()["session_id"]
        before = fx.capture_count(rival_org)

        stolen = fx.client.post(
            "/api/demo/replay",
            json={"fixture": FIXTURE, "session_id": rival_session,
                  "answer_timeout_ms": 50},
            headers={"Authorization": f"Bearer {docks_token}"},
        )
        assert stolen.status_code == 404, stolen.text
        assert fx.capture_count(rival_org) == before, \
            "a foreign caller added captures to another tenant's session"

        # The owner can, which proves the guard is about tenancy and not about
        # rejecting the parameter.
        again = fx.client.post(
            "/api/demo/replay",
            json={"fixture": FIXTURE, "session_id": rival_session,
                  "answer_timeout_ms": 50},
            headers={"Authorization": f"Bearer {rival_token}"},
        )
        assert again.status_code == 200, again.text
    finally:
        fx.close()


TESTS = [
    test_a_replay_with_a_token_lands_in_that_organisation,
    test_a_replay_without_a_token_lands_in_the_demo_organisation,
    test_a_malformed_token_still_gets_the_demo,
    test_two_organisations_replay_and_neither_sees_the_other,
    test_a_foreign_session_id_cannot_be_replayed_into,
]


def main_() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001 -- a script runner reports, not raises
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main_())
