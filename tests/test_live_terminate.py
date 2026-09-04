"""LiveSource.terminate() must let the server's last Turn through before it
closes the socket.

Until 2026-09-04 it sent Terminate and closed in the same breath. The server
answers Terminate by flushing the audio it still holds into a final Turn,
then a Termination frame, then a close (measured: experiments/day1/listen.py
saw all three on every run) -- and the final turn of a call is the one the
caller pressed stop after, i.e. the identifier. Driven through the browser
path the session ended `reason="error"`, `billed_seconds=0.0`, zero captures
(experiments/day1/FINDINGS-day1.md section 9).

A fake socket stands in for the wire. It replies to Terminate the way the
server does, or not at all, and records the order in which things happened.

Runs under pytest or as a script.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.stream.live import LiveSource

FINAL_TURN = {
    "type": "Turn", "turn_order": 0, "turn_is_formatted": True, "end_of_turn": True,
    "transcript": "Container number RMSKU4158005.", "end_of_turn_confidence": 0.775,
    "words": [
        {"text": "Container", "start": 0, "end": 1944, "confidence": 0.89, "word_is_final": True},
        {"text": "number", "start": 1987, "end": 3283, "confidence": 0.80, "word_is_final": True},
        {"text": "RMSKU4158005.", "start": 3300, "end": 7100, "confidence": 0.80, "word_is_final": True},
    ],
}
TERMINATION = {"type": "Termination", "audio_duration_seconds": 9.63,
               "session_duration_seconds": 12.4}


class FakeSocket:
    """What the server does after Terminate is the whole parameter."""

    def __init__(self, replies_after_terminate: list[dict], reply_delay: float = 0.05) -> None:
        self._replies = replies_after_terminate
        self._delay = reply_delay
        self._q: asyncio.Queue[str | None] = asyncio.Queue()
        self.sent: list[dict] = []
        self.log: list[str] = []          # the order of everything observable

    async def send(self, data: str) -> None:
        payload = json.loads(data)
        self.sent.append(payload)
        self.log.append(f"sent:{payload['type']}")
        if payload["type"] == "Terminate":
            asyncio.get_running_loop().create_task(self._reply())

    async def _reply(self) -> None:
        for frame in self._replies:
            await asyncio.sleep(self._delay)
            self.log.append(f"server:{frame['type']}")
            await self._q.put(json.dumps(frame))
        # a server that has said Termination closes; one that has not, hangs

    async def close(self) -> None:
        self.log.append("closed")
        await self._q.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        item = await self._q.get()
        if item is None:
            raise StopAsyncIteration
        return item


def _source(fake: FakeSocket, flush_s: float) -> LiveSource:
    src = LiveSource("test-key", terminate_flush_s=flush_s)

    async def fake_connect() -> None:
        src._ws = fake
        src._connected_at = time.monotonic()

    src.connect = fake_connect  # type: ignore[method-assign]
    return src


async def _drive(fake: FakeSocket, flush_s: float) -> tuple[LiveSource, list, float]:
    """Consume frames in one task, terminate from another, as the runner and
    the audio ingress do."""
    src = _source(fake, flush_s)
    turns: list = []

    async def consume() -> None:
        async for turn in src._frames():
            turns.append(turn)

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    t0 = time.monotonic()
    await src.terminate()
    took = time.monotonic() - t0
    await asyncio.wait_for(consumer, timeout=2)
    return src, turns, took


def test_the_last_turn_arrives_before_the_socket_is_closed() -> None:
    fake = FakeSocket([FINAL_TURN, TERMINATION])
    src, turns, _took = asyncio.run(_drive(fake, flush_s=5.0))
    assert [t["transcript"] for t in turns] == ["Container number RMSKU4158005."], turns
    assert fake.log == ["sent:Terminate", "server:Turn", "server:Termination", "closed"], fake.log
    detail = src.control_log[-1].detail
    assert detail.get("flush_timeout") is None, detail
    assert 0 <= detail["flush_seconds"] < 1.0, detail


def test_billing_comes_from_the_termination_frame_not_the_local_clock() -> None:
    fake = FakeSocket([FINAL_TURN, TERMINATION])
    src, _turns, _took = asyncio.run(_drive(fake, flush_s=5.0))
    assert src.billed_seconds == 12.4
    assert src.audio_duration_seconds == 9.63
    assert src.control_log[-1].detail.get("billed_seconds_source") is None


def test_a_server_that_never_answers_is_closed_after_the_flush_budget() -> None:
    """The bound exists so a hung upstream cannot keep the meter running."""
    fake = FakeSocket([])
    src, turns, took = asyncio.run(_drive(fake, flush_s=0.2))
    assert turns == []
    assert fake.log == ["sent:Terminate", "closed"], fake.log
    detail = src.control_log[-1].detail
    assert detail["flush_timeout"] is True, detail
    assert 0.2 <= took < 1.0, took
    assert detail["billed_seconds_source"] == "local_clock", detail


def test_terminate_is_idempotent_and_sends_exactly_one_terminate() -> None:
    fake = FakeSocket([TERMINATION])

    async def go() -> LiveSource:
        src, _turns, _took = await _drive(fake, flush_s=5.0)
        await src.terminate()
        await src.terminate()
        return src

    asyncio.run(go())
    assert [p["type"] for p in fake.sent] == ["Terminate"], fake.sent
    assert fake.log.count("closed") == 1, fake.log


TESTS = [
    test_the_last_turn_arrives_before_the_socket_is_closed,
    test_billing_comes_from_the_termination_frame_not_the_local_clock,
    test_a_server_that_never_answers_is_closed_after_the_flush_budget,
    test_terminate_is_idempotent_and_sends_exactly_one_terminate,
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
