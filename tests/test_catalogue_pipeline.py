"""ARCH 3.9 end to end: a part number with no checksum is written only when
the catalogue vouches for it, and PUT/GET /api/catalogue store the catalogue.

Runs under pytest or as a script.
"""

from __future__ import annotations

import asyncio
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
from server.main import CATALOGUE_MAX_ROWS, app
from server.models import Organisation, User
from server.pipeline import events as ev
from server.pipeline.runner import RunnerConfig, run_session
from server.pipeline.store import NullStore
from server.readback.catalogue import CatalogueIndex
from server.stream.replay import Fixture, ReplaySource
from server.stream.source import SourceConfig

PARTS = [("BX-4471-A", "Bearing housing"), ("BX-4471-B", "Bearing housing, flanged"),
         ("CR-2032", "Coin cell"), ("MSK-9000", "Mast bracket")]
NATO = {"B": "bravo", "X": "x-ray", "A": "alfa", "D": "delta", "C": "charlie",
        "R": "romeo"}
DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def _spoken(chars: str) -> list[str]:
    return [NATO[c] if c.isalpha() else DIGITS[int(c)] for c in chars]


def _fixture(words: list[str], name: str) -> Fixture:
    ws = []
    for i, w in enumerate(words):
        start = 600 + i * 480
        ws.append({"text": w, "start": start, "end": start + 360,
                   "confidence": 0.9, "word_is_final": True})
    frame = {"type": "Turn", "turn_order": 0, "turn_is_formatted": False,
             "end_of_turn": True, "transcript": " ".join(words),
             "end_of_turn_confidence": 0.9, "words": ws}
    return Fixture.from_dict({"schema": "readback.fixture/1", "name": name,
                              "frames": [{"emit_ms": ws[-1]["end"] + 250, "frame": frame}]})


def _run(fixture: Fixture, catalogue: CatalogueIndex | None):
    source = ReplaySource(fixture, speed=0.0, config=SourceConfig())
    return asyncio.run(run_session(
        source, ev.EventStream(), store=NullStore(),
        config=RunnerConfig(session_id=fixture.name, catalogue=catalogue)))


def test_a_part_number_the_catalogue_knows_is_written_silently() -> None:
    words = ["part", "number"] + _spoken("BX4471A")
    summary = _run(_fixture(words, "catalogue_exact"), CatalogueIndex(PARTS))
    assert len(summary.captures) == 1, summary.captures
    c = summary.captures[0]
    assert c.status == "committed" and c.format_type == "catalogue"
    assert c.heard_value == "BX4471A" and c.final_value == "BX-4471-A"
    assert c.validated_by == "catalogue" and c.second_signal == "carrier"
    assert c.silent and not c.corrected and c.questions_asked == 0
    assert summary.silent_captures == 1


def test_one_mishear_is_corrected_by_the_catalogue_and_shown_as_a_diff() -> None:
    words = ["part", "number"] + _spoken("DX4471A")      # D for B
    summary = _run(_fixture(words, "catalogue_mishear"), CatalogueIndex(PARTS))
    assert len(summary.captures) == 1, summary.captures
    c = summary.captures[0]
    assert c.heard_value == "DX4471A" and c.final_value == "BX-4471-A"
    assert c.corrected and c.silent and c.validated_by == "catalogue"


def test_an_ambiguous_run_writes_nothing() -> None:
    """BX4471 is one character from both BX-4471-A and BX-4471-B. The
    constraint cannot choose, so nothing is written -- and nothing is guessed."""
    words = ["part", "number"] + _spoken("BX4471")
    summary = _run(_fixture(words, "catalogue_ambiguous"), CatalogueIndex(PARTS))
    assert summary.captures == [], summary.captures


def test_without_a_catalogue_the_format_never_commits() -> None:
    words = ["part", "number"] + _spoken("BX4471A")
    summary = _run(_fixture(words, "catalogue_none"), None)
    assert [c for c in summary.captures if c.status == "committed"] == []


def test_a_container_number_is_untouched_by_the_catalogue_branch() -> None:
    """A checksummed format keeps its own path: the catalogue is only asked
    about the `catalogue` format."""
    words = ["container", "number", "mike", "sierra", "kilo", "uniform",
             "four", "one", "five", "eight", "zero", "zero", "five"]
    summary = _run(_fixture(words, "catalogue_iso"), CatalogueIndex(PARTS))
    committed = [c for c in summary.captures if c.status == "committed"]
    assert [c.final_value for c in committed] == ["MSKU4158005"], summary.captures
    assert committed[0].validated_by != "catalogue"


# ---------------------------------------------------------- the endpoint ----
PLACEHOLDER_HASH = "pbkdf2_sha256$1$00$00"


def _settings() -> Settings:
    return Settings(replay_mode=True, session_secret="test-secret-catalogue-1")


class _Fixture:
    def __init__(self) -> None:
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3", prefix="readback_cat_")
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

    def token(self) -> str:
        with self.Factory() as db:
            org = Organisation(name="Docks Ltd")
            user = User(organisation=org, email="ada@docks.example", name="Ada",
                        password_hash=PLACEHOLDER_HASH, role="owner")
            db.add(org)
            db.add(user)
            db.commit()
            return auth.issue_token(user, _settings())


def test_put_and_get_catalogue_round_trip_with_caps() -> None:
    fx = _Fixture()
    try:
        token = fx.token()
        headers = {"Authorization": f"Bearer {token}"}
        assert fx.client.get("/api/catalogue").status_code == 401
        assert fx.client.get("/api/catalogue", headers=headers).json()["parts"] == []

        r = fx.client.put("/api/catalogue", headers=headers, json={"parts": [
            {"sku": " bx-4471-a ", "description": "Bearing   housing"},
            {"sku": "BX4471A", "description": "duplicate by normalisation"},
            {"sku": "", "description": "blank"},
            {"sku": "CR-2032"},
        ]})
        assert r.status_code == 200, r.text
        parts = r.json()["parts"]
        assert [p["sku"] for p in parts] == ["CR-2032", "bx-4471-a"]
        assert parts[1]["description"] == "Bearing housing"
        assert fx.client.get("/api/catalogue", headers=headers).json()["parts"] == parts

        too_many = fx.client.put("/api/catalogue", headers=headers, json={
            "parts": [{"sku": f"P{i}"} for i in range(CATALOGUE_MAX_ROWS + 1)]})
        assert too_many.status_code == 400 and too_many.json()["error"] == "too_many_parts"
        too_long = fx.client.put("/api/catalogue", headers=headers, json={
            "parts": [{"sku": "X" * 65}]})
        assert too_long.status_code == 400 and too_long.json()["error"] == "sku_too_long"
    finally:
        fx.close()


TESTS = [
    test_a_part_number_the_catalogue_knows_is_written_silently,
    test_one_mishear_is_corrected_by_the_catalogue_and_shown_as_a_diff,
    test_an_ambiguous_run_writes_nothing,
    test_without_a_catalogue_the_format_never_commits,
    test_a_container_number_is_untouched_by_the_catalogue_branch,
    test_put_and_get_catalogue_round_trip_with_caps,
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
