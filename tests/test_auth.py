# test_auth.py -- signup, login, tokens, and the CORS layer the browser hits
# first.
#
# Deterministic and offline. server/password.py's breach lookup calls Have I Been
# Pwned, so every test here patches it: a suite whose result depends on a third
# party's uptime reports "the auth layer is broken" when the truth is "somebody
# else's DNS is slow". The patched-out path is covered by asserting that an
# unavailable lookup degrades to breach_checked=False rather than to "safe".
#
# PBKDF2 is turned down for the functional tests and measured at its real cost in
# exactly one place, because 600,000 iterations x 20 verifications is 12 seconds
# of a suite that is otherwise 24. The real figure is still asserted, so a
# misconfiguration that made hashing cheap would fail here rather than ship.
#
# Runs under pytest or as a script.
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from server import auth
from server import password as pw
from server import ratelimit as rl
from server.config import Settings, get_settings
from server.db import create_all, get_db, make_engine
from server.main import app

ORIGIN = "http://localhost:5173"

GOOD_PASSWORD = "Tarmoq-Qishloq-42!"        # 18 chars, 4 classes, no run, no repeat
WEAK_PASSWORD = "abc"


# --------------------------------------------------------------- harness ----
def _settings() -> Settings:
    return Settings(replay_mode=True, session_secret="test-secret-abc123")


class _Fixture:
    """A client wired to a fresh database, a known secret and no network."""

    def __init__(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_auth_")
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

        # No network, and no shared rate-limit counters between tests: the
        # buckets are module-level, so a previous test's 5 signups would trip
        # SIGNUP_PER_IP in this one and the failure would look like a bug in the
        # code under test.
        self._real_breach = pw.breach_count
        pw.breach_count = self._no_breach
        rl._buckets.clear()

        # Cheap KDF, and the dummy hash moved with it so the "unknown address"
        # path costs the same as the "wrong password" path, which is the whole
        # point of the dummy.
        self._real_iterations = auth.PBKDF2_ITERATIONS
        self._real_dummy = auth._DUMMY_HASH
        auth.PBKDF2_ITERATIONS = 1_000
        auth._DUMMY_HASH = auth.hash_password("not-a-real-password")

        self.client = TestClient(app, raise_server_exceptions=False)

    @staticmethod
    async def _no_breach(password: str) -> int | None:
        return None

    def close(self) -> None:
        pw.breach_count = self._real_breach
        auth.PBKDF2_ITERATIONS = self._real_iterations
        auth._DUMMY_HASH = self._real_dummy
        app.dependency_overrides.clear()
        rl._buckets.clear()
        self.engine.dispose()

    # convenience
    def signup(self, email="a@example.com", password=GOOD_PASSWORD,
               name="Ada", company="Docks Ltd"):
        return self.client.post("/api/auth/signup", json={
            "name": name, "company": company, "email": email, "password": password,
        }, headers={"Origin": ORIGIN})

    def login(self, email="a@example.com", password=GOOD_PASSWORD):
        return self.client.post("/api/auth/login",
                                json={"email": email, "password": password},
                                headers={"Origin": ORIGIN})


# ------------------------------------------------------------------ cors ----
def test_cors_preflight_is_answered() -> None:
    """The failure the browser actually shows first.

    A missing Access-Control-Allow-Origin presents in the console as
    "Failed to load resource", which reads like a dead endpoint, so this is
    asserted separately from anything about auth.
    """
    fx = _Fixture()
    try:
        r = fx.client.options("/api/auth/check-password", headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        assert r.status_code in (200, 204), r.status_code
        assert r.headers.get("access-control-allow-origin") == ORIGIN, dict(r.headers)

        # An origin nobody configured must NOT be allowed. A permissive default
        # would make this whole layer decorative.
        evil = fx.client.options("/api/auth/check-password", headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        })
        assert evil.headers.get("access-control-allow-origin") != "http://evil.example"
    finally:
        fx.close()


# -------------------------------------------------------- password check ----
def test_check_password_shape_matches_the_client_contract() -> None:
    """web/src/lib/api.ts declares seven fields and reads `breached` as a
    BOOLEAN while the server counts. Getting that wrong renders "Found in a
    breach" for every password, so it is asserted rather than assumed."""
    fx = _Fixture()
    try:
        r = fx.client.post("/api/auth/check-password",
                           json={"password": GOOD_PASSWORD}, headers={"Origin": ORIGIN})
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"ok", "score", "label", "problems", "suggestions",
                             "breached", "breach_checked"}, sorted(body)
        assert isinstance(body["breached"], bool)
        assert isinstance(body["score"], int) and 0 <= body["score"] <= 4
        assert isinstance(body["problems"], list) and isinstance(body["suggestions"], list)

        # Unavailable lookup degrades to "unknown", never to "safe".
        assert body["breach_checked"] is False
        assert body["breached"] is False
    finally:
        fx.close()


def test_check_password_flags_a_weak_one_without_creating_anything() -> None:
    fx = _Fixture()
    try:
        r = fx.client.post("/api/auth/check-password",
                           json={"password": WEAK_PASSWORD, "name": "Ada"},
                           headers={"Origin": ORIGIN})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["problems"], "a three-character password must say why"
        # Advisory only: nothing was written.
        with fx.Factory() as db:
            from server.models import User
            assert db.query(User).count() == 0
    finally:
        fx.close()


def test_personal_data_in_a_password_is_caught() -> None:
    """"Do not put your name in your password" only fires if the context
    actually reaches the scorer, so the wiring is asserted, not the rule."""
    fx = _Fixture()
    try:
        r = fx.client.post("/api/auth/check-password", json={
            "password": "Islombek-1234!x", "name": "Islombek",
        }, headers={"Origin": ORIGIN})
        problems = " ".join(r.json()["problems"]).lower()
        assert "name" in problems, r.json()["problems"]
    finally:
        fx.close()


def test_predictability_catches_the_pattern_not_the_passphrase() -> None:
    r"""The word-then-number rule, both directions.

    The salvaged form of this rule used \D* for the head, which swallows
    separators, so it rejected any passphrase ending in a number. Narrowing the
    head to a single alphabetic word keeps every case it was written for. Both
    halves are asserted, because a rule that only ever gets tested on the things
    it should catch is how a false positive survives.
    """
    from server.password import evaluate

    def flagged(password: str) -> bool:
        return any("Word-then-number" in p for p in evaluate(password).problems)

    for caught in ("Summer2024!", "Password1!", "Welcome2024", "Dragon99"):
        assert flagged(caught), f"{caught} should be caught"

    for allowed in ("Tarmoq-Qishloq-42!", "correct-horse-battery-9", "Qishloq7Tarmoq!x"):
        assert not flagged(allowed), f"{allowed} is a passphrase, not the pattern"
        assert evaluate(allowed).ok, f"{allowed} should pass the whole policy"


# ---------------------------------------------------------------- signup ----
def test_signup_then_me_round_trip() -> None:
    fx = _Fixture()
    try:
        r = fx.signup()
        assert r.status_code == 201, r.text
        body = r.json()
        assert set(body) == {"token", "account"}
        account = body["account"]
        assert set(account) == {"id", "name", "email", "role", "organisation"}
        assert set(account["organisation"]) == {"id", "name", "plan"}
        assert account["role"] == "owner"
        assert account["email"] == "a@example.com"

        me = fx.client.get("/api/auth/me",
                           headers={"Authorization": f"Bearer {body['token']}"})
        assert me.status_code == 200, me.text
        assert me.json()["account"]["id"] == account["id"]
    finally:
        fx.close()


def test_weak_password_is_rejected_flat_with_the_check_attached() -> None:
    """The 400 body has to be FLAT. FastAPI wraps details in {"detail": ...} and
    the client reads `error`, `message` and `password_check` at the top level --
    if that wrapping is not undone the form shows a generic failure and the
    person never learns what was wrong with their password."""
    fx = _Fixture()
    try:
        r = fx.signup(password=WEAK_PASSWORD)
        assert r.status_code == 400, r.text
        body = r.json()
        assert body.get("error") == "weak_password", body
        assert isinstance(body.get("message"), str) and body["message"]
        assert isinstance(body.get("password_check"), dict), body
        assert body["password_check"]["ok"] is False
        assert "detail" not in body, "the error body must not be wrapped"
    finally:
        fx.close()


def test_duplicate_email_is_409_and_case_folds() -> None:
    fx = _Fixture()
    try:
        assert fx.signup(email="Ada@Example.COM").status_code == 201
        again = fx.signup(email="ada@example.com")
        assert again.status_code == 409, again.text
        assert again.json()["error"] == "email_taken"
        # And the stored address is the folded one, so login can match on it.
        assert fx.login(email="ADA@example.com").status_code == 200
    finally:
        fx.close()


def test_malformed_email_is_rejected() -> None:
    fx = _Fixture()
    try:
        r = fx.signup(email="not-an-email")
        assert r.status_code == 400, r.text
        assert r.json()["error"] == "invalid_email"
    finally:
        fx.close()


# ----------------------------------------------------------------- login ----
def test_login_right_and_wrong() -> None:
    fx = _Fixture()
    try:
        assert fx.signup().status_code == 201
        assert fx.login().status_code == 200

        bad = fx.login(password="Totally-Wrong-99!")
        assert bad.status_code == 401, bad.text
        assert bad.json()["error"] == "unauthorized"
        # The same sentence for both failures, so the response is not an oracle.
        missing = fx.login(email="nobody@example.com")
        assert missing.status_code == 401
        assert missing.json()["message"] == bad.json()["message"]
    finally:
        fx.close()


def test_unknown_address_costs_the_same_as_a_wrong_password() -> None:
    """The dummy-hash timing defence, measured.

    Without it, "no such user" returns before any KDF work and login timing
    becomes an account-existence oracle that no rate limit hides.
    """
    fx = _Fixture()
    try:
        assert fx.signup().status_code == 201

        def timed(fn, n=5) -> float:
            samples = []
            for _ in range(n):
                rl._buckets.clear()          # the limits are not what is measured
                start = time.perf_counter()
                fn()
                samples.append(time.perf_counter() - start)
            samples.sort()
            return samples[len(samples) // 2]      # median, not mean

        wrong = timed(lambda: fx.login(password="Totally-Wrong-99!"))
        unknown = timed(lambda: fx.login(email="nobody@example.com"))
        ratio = max(wrong, unknown) / max(1e-9, min(wrong, unknown))
        print(f"    login timing: wrong-password {wrong*1000:.1f} ms, "
              f"unknown-address {unknown*1000:.1f} ms, ratio {ratio:.2f}x")
        # Loose on purpose. This is a shared laptop under a test runner, so the
        # assertion is that one path is not an order of magnitude cheaper -- not
        # that the two are identical, which no wall clock here could show.
        assert ratio < 5.0, f"timing ratio {ratio:.2f}x looks like an oracle"
    finally:
        fx.close()


# ---------------------------------------------------------------- tokens ----
def test_token_rejects_tampering_expiry_and_a_foreign_secret() -> None:
    fx = _Fixture()
    try:
        token = fx.signup().json()["token"]
        settings = _settings()
        assert auth.verify_token(token, settings) is not None

        prefix, body, sig = token.split(".", 2)

        # A flipped signature. The replacement character is chosen against the
        # original rather than fixed, and that is a bug fix: this line used to
        # append a literal "A", so whenever the real signature already ended in
        # "A" the "tampered" token was the genuine one and verify_token was
        # right to accept it. Base64url has 64 characters, so the test failed
        # about one run in sixty-four -- often enough to be seen, rarely enough
        # to be blamed on something else.
        flipped = "B" if sig[-1] != "B" else "C"
        assert auth.verify_token(f"{prefix}.{body}.{sig[:-1]}{flipped}", settings) is None
        # a re-signed payload under a different secret
        other = Settings(replay_mode=True, session_secret="a-different-secret")
        assert auth.verify_token(token, other) is None
        # wrong prefix
        assert auth.verify_token(f"xx1.{body}.{sig}", settings) is None
        # not a token at all
        assert auth.verify_token("garbage", settings) is None
        assert auth.verify_token("", settings) is None

        # expired
        expired = Settings(replay_mode=True, session_secret="test-secret-abc123",
                           session_ttl_hours=1)
        with fx.Factory() as db:
            from server.models import User
            user = db.query(User).first()
            assert user is not None
            issued = auth.issue_token(user, expired)
        # rewind the clock past the expiry rather than sleeping an hour
        real_time = time.time
        try:
            time.time = lambda: real_time() + 3601 * 2
            assert auth.verify_token(issued, expired) is None
        finally:
            time.time = real_time
    finally:
        fx.close()


def test_me_is_401_without_a_usable_token() -> None:
    fx = _Fixture()
    try:
        assert fx.client.get("/api/auth/me").status_code == 401
        assert fx.client.get("/api/auth/me",
                             headers={"Authorization": "Bearer garbage"}).status_code == 401
        assert fx.client.get("/api/auth/me",
                             headers={"Authorization": "Basic abc"}).status_code == 401

        token = fx.signup().json()["token"]
        # A token whose account has been deactivated is not a session, however
        # good its signature.
        with fx.Factory() as db:
            from server.models import User
            user = db.query(User).first()
            user.active = False
            db.commit()
        r = fx.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, r.text
    finally:
        fx.close()


# ----------------------------------------------------------- rate limiting --
def test_signup_is_rate_limited_per_ip() -> None:
    fx = _Fixture()
    try:
        limit = rl.SIGNUP_PER_IP.max_hits
        for i in range(limit):
            r = fx.signup(email=f"user{i}@example.com")
            assert r.status_code == 201, (i, r.text)
        blocked = fx.signup(email="one-too-many@example.com")
        assert blocked.status_code == 429, blocked.text
        assert blocked.json()["error"] == "rate_limited"
        assert int(blocked.headers["retry-after"]) >= 1
    finally:
        fx.close()


# --------------------------------------------------------------- the cost --
def test_real_kdf_cost_is_not_cheap() -> None:
    """One measurement at the shipped iteration count.

    A KDF that got fast is a KDF that got misconfigured, and it is the kind of
    change that passes every functional test.
    """
    assert auth.PBKDF2_ITERATIONS >= 600_000, auth.PBKDF2_ITERATIONS
    start = time.perf_counter()
    stored = auth.hash_password("measure-me-please")
    hashed = time.perf_counter() - start

    start = time.perf_counter()
    assert auth.verify_password("measure-me-please", stored)
    verified = time.perf_counter() - start

    print(f"    PBKDF2 {auth.PBKDF2_ITERATIONS:,} iterations: "
          f"hash {hashed*1000:.0f} ms, verify {verified*1000:.0f} ms")
    assert not auth.verify_password("measure-me-wrong", stored)
    assert hashed > 0.02, f"{hashed*1000:.1f} ms is too cheap to be 600k iterations"


TESTS = [
    test_cors_preflight_is_answered,
    test_check_password_shape_matches_the_client_contract,
    test_check_password_flags_a_weak_one_without_creating_anything,
    test_personal_data_in_a_password_is_caught,
    test_predictability_catches_the_pattern_not_the_passphrase,
    test_signup_then_me_round_trip,
    test_weak_password_is_rejected_flat_with_the_check_attached,
    test_duplicate_email_is_409_and_case_folds,
    test_malformed_email_is_rejected,
    test_login_right_and_wrong,
    test_unknown_address_costs_the_same_as_a_wrong_password,
    test_token_rejects_tampering_expiry_and_a_foreign_secret,
    test_me_is_401_without_a_usable_token,
    test_signup_is_rate_limited_per_ip,
    test_real_kdf_cost_is_not_cheap,
]


def main() -> int:
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
    sys.exit(main())
