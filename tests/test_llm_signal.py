"""ARCH 3.8's third second-signal: the LLM Gateway's format identification,
wired into the runner behind a seam and gated by FormatID.asserts.

No network. `identify` is a fake, and what is pinned is the plumbing and the
gate: asked exactly once, only when nothing on the tape named the format; a
verdict that asserts the window's format supplies second_signal="llm" and the
capture commits; a bare-digit verdict never asserts however confident (the
measured refusal in server/llm.py); nobody answering is not evidence.

Runs under pytest or as a script.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.llm import FormatID
from server.pipeline import events as ev
from server.pipeline.runner import RunnerConfig, run_session
from server.pipeline.store import NullStore
from server.readback.solver import ISO
from server.stream.replay import Fixture, ReplaySource, fixture_dir
from server.stream.source import SourceConfig

NATO = {"X": "x-ray", "Q": "quebec", "Z": "zulu", "U": "uniform", "W": "whiskey", "J": "juliett"}
DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def _unregistered_iso() -> str:
    """A checksum-valid container number whose owner code no registry knows,
    so the tape carries no prefix signal and no carrier phrase -- the case the
    third signal exists for."""
    for base in ("XQZU415800", "XQZU415801", "XQWU415800", "XQJU415802"):
        for d in range(10):
            value = f"{base}{d}"
            if ISO.ok(value):
                return value
    raise AssertionError("no check digit fits any base")


def _spoken(value: str) -> list[str]:
    return [NATO[ch] if ch.isalpha() else DIGITS[int(ch)] for ch in value]


def _fixture(words: list[str], name: str) -> Fixture:
    step = 480
    ws = []
    for i, w in enumerate(words):
        start = 800 + i * step
        ws.append({"text": w, "start": start, "end": start + 360,
                   "confidence": 0.9, "word_is_final": True})
    frame = {"type": "Turn", "turn_order": 0, "turn_is_formatted": False,
             "end_of_turn": True, "transcript": " ".join(words),
             "end_of_turn_confidence": 0.91, "words": ws}
    return Fixture.from_dict({"schema": "readback.fixture/1", "name": name,
                              "frames": [{"emit_ms": ws[-1]["end"] + 250, "frame": frame}]})


class _Fake:
    def __init__(self, verdict: FormatID | None) -> None:
        self.verdict = verdict
        self.calls: list[tuple[str, str | None]] = []

    async def __call__(self, candidate: str, carrier: str | None) -> FormatID | None:
        self.calls.append((candidate, carrier))
        return self.verdict


def _run(fixture: Fixture, identify: _Fake | None):
    source = ReplaySource(fixture, speed=0.0, config=SourceConfig())
    return asyncio.run(run_session(
        source, ev.EventStream(), store=NullStore(),
        config=RunnerConfig(session_id=fixture.name, identify=identify)))


def _committed(summary) -> list:
    return [c for c in summary.captures if c.status == "committed"]


def test_an_asserting_verdict_supplies_the_second_signal_and_the_capture_commits() -> None:
    value = _unregistered_iso()
    fake = _Fake(FormatID(fmt="iso6346", confidence=0.92,
                          reason="four letters then seven digits", model="fake"))
    summary = _run(_fixture(_spoken(value), "llm_no_carrier"), fake)
    assert len(fake.calls) == 1, fake.calls
    assert fake.calls[0] == (value, None)
    assert [c.final_value for c in _committed(summary)] == [value], summary.captures
    assert _committed(summary)[0].second_signal == "llm"


def test_without_the_identifier_the_same_tape_commits_nothing() -> None:
    """The control: shape alone never asserts a format (3.8)."""
    value = _unregistered_iso()
    summary = _run(_fixture(_spoken(value), "llm_absent"), None)
    assert _committed(summary) == [], summary.captures


def test_nobody_answering_is_not_evidence() -> None:
    value = _unregistered_iso()
    fake = _Fake(None)
    summary = _run(_fixture(_spoken(value), "llm_silent"), fake)
    assert len(fake.calls) == 1
    assert _committed(summary) == [], summary.captures


def test_a_verdict_for_a_different_format_does_not_count() -> None:
    value = _unregistered_iso()
    fake = _Fake(FormatID(fmt="vin", confidence=0.95, reason="looks like a VIN", model="fake"))
    summary = _run(_fixture(_spoken(value), "llm_wrong_format"), fake)
    assert _committed(summary) == [], summary.captures


def test_a_bare_digit_verdict_never_asserts_however_confident() -> None:
    """The measured anti-correlation: a phone number scored `nhs 0.90`. The
    gate lives in FormatID.asserts and the runner may not bypass it."""
    fixture = Fixture.load(fixture_dir() / "meter_reading_sixteen_digits.json")
    fake = _Fake(FormatID(fmt="luhn16", confidence=0.99, reason="sixteen digits", model="fake"))
    summary = _run(fixture, fake)
    assert _committed(summary) == [], summary.captures


TESTS = [
    test_an_asserting_verdict_supplies_the_second_signal_and_the_capture_commits,
    test_without_the_identifier_the_same_tape_commits_nothing,
    test_nobody_answering_is_not_evidence,
    test_a_verdict_for_a_different_format_does_not_count,
    test_a_bare_digit_verdict_never_asserts_however_confident,
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
