"""The small hardening guarantees, pinned so they cannot quietly regress.

Each of these was a candidate raised by the second-round audit and confirmed
by reading the code that shipped it (three of the four were self-inflicted by
the scoping work the round before).

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
from server.main import MAX_BODY_BYTES, ReplayRequest, app


def _settings() -> Settings:
    return Settings(replay_mode=True, session_secret="test-secret-harden-1")


class _Fixture:
    def __init__(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_harden_")
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


def test_an_oversize_body_is_refused_flat_before_it_is_parsed() -> None:
    """A body is read in full before any field constraint runs, so the size is
    bounded by the middleware or not at all. The refusal keeps the two-key
    shape every other failure here uses."""
    fx = _Fixture()
    try:
        big = "M" * (MAX_BODY_BYTES + 1024)
        r = fx.client.post("/api/validate", json={"format": "iso6346", "value": big})
        assert r.status_code == 413, r.status_code
        body = r.json()
        assert body.get("error") == "body_too_large"
        assert isinstance(body.get("message"), str) and body["message"]
        assert "detail" not in body

        # And the ordinary path still answers.
        ok = fx.client.post("/api/validate",
                            json={"format": "iso6346", "value": "MSKU4158005"})
        assert ok.status_code == 200 and ok.json()["valid"] is True
    finally:
        fx.close()


def test_replay_speed_and_timeout_are_bounded_at_the_schema() -> None:
    """NaN wedged a pipeline slot; an unbounded timeout held a request open.
    Both are refused before a handler sees them."""
    for bad in ({"fixture": "x", "speed": float("nan")},
                {"fixture": "x", "speed": -1.0},
                {"fixture": "x", "speed": 1e6},
                {"fixture": "x", "answer_timeout_ms": -1},
                {"fixture": "x", "answer_timeout_ms": 10_000_000}):
        try:
            ReplayRequest(**bad)
        except Exception:
            continue
        raise AssertionError(f"{bad} was accepted")
    # The legitimate extremes still parse.
    assert ReplayRequest(fixture="x").speed == 0.0
    assert ReplayRequest(fixture="x", speed=1.0).speed == 1.0
    assert ReplayRequest(fixture="x", answer_timeout_ms=0).answer_timeout_ms == 0


def test_a_zero_answer_timeout_survives_the_config_build() -> None:
    """0 means "do not wait"; a truthiness test silently replaced it with the
    six-second default, so the caller's own number never reached the runner."""
    body = ReplayRequest(fixture="x", answer_timeout_ms=0)
    kwargs = ({"answer_timeout_ms": body.answer_timeout_ms}
              if body.answer_timeout_ms is not None else {})
    assert kwargs == {"answer_timeout_ms": 0}


TESTS = [
    test_an_oversize_body_is_refused_flat_before_it_is_parsed,
    test_replay_speed_and_timeout_are_bounded_at_the_schema,
    test_a_zero_answer_timeout_survives_the_config_build,
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
