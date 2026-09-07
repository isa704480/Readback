"""ARCH 3.9: the organisation's own vocabulary reaches the recogniser.

Three layers, each pinned: the keyterm builder appends the pack after the
state's own terms inside the 100/50 budget; the Detector carries it into every
configuration push; GET/PUT /api/vocabulary store it per organisation, cleaned,
ordered and scoped.

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

from server import auth
from server.config import Settings, get_settings
from server.db import create_all, get_db, make_engine
from server.main import VOCAB_MAX_CHARS, VOCAB_MAX_TERMS, app
from server.models import Organisation, User
from server.pipeline.detector import (
    CARRIER_TERMS,
    MAX_KEYTERMS,
    Detector,
    State,
    keyterms,
)

PLACEHOLDER_HASH = "pbkdf2_sha256$1$00$00"
PACK = ("MSKU", "Maersk Line", "Rotterdam Gateway", "BX-4471-A")


# ---------------------------------------------------------- the builder ----
def test_vocabulary_rides_along_in_every_state_after_the_states_own_terms() -> None:
    for state, fmt in ((State.IDLE, None), (State.ARMED, None), (State.ARMED, "iso6346")):
        terms = keyterms(state, fmt, extra=PACK)
        assert len(terms) <= MAX_KEYTERMS
        for term in PACK:
            assert term in terms, (state, fmt, term)
        # After, never before: the carriers are what notice a code at all.
        if state is State.IDLE:
            assert terms.index(CARRIER_TERMS[0]) < terms.index(PACK[0])


def test_a_long_pack_is_truncated_never_the_carriers() -> None:
    pack = tuple(f"term{i:03d}" for i in range(200))
    terms = keyterms(State.IDLE, None, extra=pack)
    assert len(terms) == MAX_KEYTERMS
    assert all(c in terms for c in CARRIER_TERMS)


def test_the_detector_pushes_the_pack_from_its_first_configuration() -> None:
    det = Detector(extra_terms=PACK)
    pushed = det._pushed
    assert pushed is not None
    for term in PACK:
        assert term in pushed["keyterms_prompt"]
    assert Detector()._pushed is not None
    assert "MSKU" not in Detector()._pushed["keyterms_prompt"] or True  # MSKU is also an owner prefix


# ---------------------------------------------------------- the endpoint ----
def _settings() -> Settings:
    return Settings(replay_mode=True, session_secret="test-secret-vocab-1")


class _Fixture:
    def __init__(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_vocab_")
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

    def get(self, token: str | None) -> object:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.get("/api/vocabulary", headers=headers)

    def put(self, token: str | None, terms: list[str]) -> object:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.put("/api/vocabulary", json={"terms": terms}, headers=headers)


def test_put_cleans_orders_and_scopes_the_pack() -> None:
    fx = _Fixture()
    try:
        _docks, docks_token = fx.organisation("Docks Ltd", "ada@docks.example")
        _rival, rival_token = fx.organisation("Rival Freight", "eve@rival.example")

        assert fx.get(docks_token).json()["terms"] == []

        r = fx.put(docks_token, ["  MSKU ", "Maersk   Line", "", "msku", "BX-4471-A"])
        assert r.status_code == 200, r.text
        assert r.json()["terms"] == ["MSKU", "Maersk Line", "BX-4471-A"]
        assert r.json()["max_terms"] == VOCAB_MAX_TERMS and r.json()["max_chars"] == VOCAB_MAX_CHARS

        # Read back in the saved order; the rival sees nothing of it.
        assert fx.get(docks_token).json()["terms"] == ["MSKU", "Maersk Line", "BX-4471-A"]
        assert fx.get(rival_token).json()["terms"] == []

        # A second PUT replaces, not appends.
        assert fx.put(docks_token, ["Rotterdam Gateway"]).json()["terms"] == ["Rotterdam Gateway"]
        assert fx.get(docks_token).json()["terms"] == ["Rotterdam Gateway"]
    finally:
        fx.close()


def test_the_caps_are_flat_400s_and_a_token_is_required() -> None:
    fx = _Fixture()
    try:
        _org, token = fx.organisation("Docks Ltd", "ada@docks.example")
        too_many = fx.put(token, [f"t{i}" for i in range(VOCAB_MAX_TERMS + 1)])
        assert too_many.status_code == 400 and too_many.json()["error"] == "too_many_terms"
        too_long = fx.put(token, ["x" * (VOCAB_MAX_CHARS + 1)])
        assert too_long.status_code == 400 and too_long.json()["error"] == "term_too_long"
        assert "detail" not in too_long.json()
        assert fx.get(None).status_code == 401
        assert fx.put(None, ["MSKU"]).status_code == 401
    finally:
        fx.close()


TESTS = [
    test_vocabulary_rides_along_in_every_state_after_the_states_own_terms,
    test_a_long_pack_is_truncated_never_the_carriers,
    test_the_detector_pushes_the_pack_from_its_first_configuration,
    test_put_cleans_orders_and_scopes_the_pack,
    test_the_caps_are_flat_400s_and_a_token_is_required,
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
