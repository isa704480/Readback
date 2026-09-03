"""The event stream. This file is the product's interface, not its logging.

Everything a human ever sees about a session arrives here: the rack in
DESIGN-BRIEF 4.1, the silence indicator in 4.2, the question in 4.3, the record
in 4.4. The browser holds no model of its own and computes nothing -- it renders
this stream and nothing else -- so an event that is missing is a thing the
product cannot show, and a field that is present is a thing the product is
allowed to show.

Two consequences of taking that literally, and both are decisions rather than
omissions:

**No confidence numbers reach the wire.** ARCHITECTURE 3.10's sketch of
`capture.update` carries `"conf":0.97` on every slot. DESIGN-BRIEF 6 forbids the
interface from ever displaying a confidence percentage -- meaningless to an
operator, an invitation to argue with the machine -- and the system's uncertainty
is expressed by *asking*. A number that may not be displayed and is not needed to
render anything is a number that should not be transmitted, so slots carry one of
the six states from 4.1 and the live alternatives, which is exactly what the
flicker needs.

**Silence is an event.** The central claim is that the agent stays quiet, and a
screen showing nothing looks broken (4.2). `silence.held` is emitted every time
the decider declines to speak, carrying the gate that stopped it, so "it heard,
it decided, it said nothing" is a positive fact on the wire rather than an
absence to be inferred from a gap.

The stream is also the reason the replay path is worth anything: `/api/demo/replay`
and a live socket run the same `runner.run_session`, so they emit the same events
in the same order, and a UI built against a fixture today needs no changes when
the key lands.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Final

# ---------------------------------------------------------------- vocabulary --
# A closed set, for the same reason audit.ACTIONS is closed: the UI switches on
# these strings and a typo is a beat that silently never renders rather than an
# error anyone sees. Where ARCHITECTURE 3.10 already names a control frame, that
# name is kept verbatim so the two documents cannot drift.
SESSION_STARTED: Final = "session.started"
SESSION_END: Final = "session.end"

STATE_ARMED: Final = "state.armed"
STATE_IDLE: Final = "state.idle"
REGIME: Final = "regime.detected"

CANDIDATE_SEEN: Final = "candidate.seen"
RACK_UPDATE: Final = "capture.update"          # 3.10
CANDIDATES_SHOW: Final = "candidates.show"     # 3.10 -- the 14 -> 1 collapse
REPAIR_SILENT: Final = "repair.silent"

QUESTION_ASK: Final = "question.ask"           # 3.10
QUESTION_ANSWER: Final = "question.answer"
SPAN_REREAD: Final = "span.reread"

CAPTURE_COMMIT: Final = "capture.commit"
CAPTURE_FLAG: Final = "capture.flag"
CAPTURE_HANDOVER: Final = "capture.handover"

SILENCE_HELD: Final = "silence.held"
METER: Final = "meter"                         # 3.10
ERROR: Final = "error"

EVENT_TYPES: Final[frozenset[str]] = frozenset({
    SESSION_STARTED, SESSION_END, STATE_ARMED, STATE_IDLE, REGIME,
    CANDIDATE_SEEN, RACK_UPDATE, CANDIDATES_SHOW, REPAIR_SILENT,
    QUESTION_ASK, QUESTION_ANSWER, SPAN_REREAD,
    CAPTURE_COMMIT, CAPTURE_FLAG, CAPTURE_HANDOVER,
    SILENCE_HELD, METER, ERROR,
})

# DESIGN-BRIEF 4.1. Six states, and collapsing any of them loses something real.
# The hardest pair is provisional vs settled: partials flicker as the recogniser
# revises, and that flicker is the most honest thing on the screen.
SLOT_EMPTY: Final = "empty"
SLOT_PROVISIONAL: Final = "provisional"
SLOT_SETTLED: Final = "settled"
SLOT_REPAIRED: Final = "repaired"
SLOT_ASKED: Final = "asked"
SLOT_LOCKED: Final = "locked"
SLOT_STATES: Final[tuple[str, ...]] = (
    SLOT_EMPTY, SLOT_PROVISIONAL, SLOT_SETTLED, SLOT_REPAIRED, SLOT_ASKED, SLOT_LOCKED,
)


@dataclass(frozen=True, slots=True)
class Slot:
    """One character of the rack.

    `alts` is what the slot flickers between (ARCHITECTURE 8: contested slots
    flicker between the *actual* competing characters, not a question mark).
    It is empty for a settled slot, which is how the renderer knows to hold still
    without being told a confidence.
    """

    char: str
    state: str
    alts: tuple[str, ...] = ()
    heard: str | None = None       # set only when state is repaired: the diff

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"char": self.char, "state": self.state}
        if self.alts:
            out["alts"] = list(self.alts)
        if self.heard is not None:
            out["heard"] = self.heard
        return out


@dataclass(frozen=True, slots=True)
class Event:
    """One thing that happened, with both clocks.

    `at_ms` is tape time -- session-relative, taken from the end of the newest
    word -- and it is the one a fixture and a live call agree on, so it is what
    the record and any regression test read. `wall_ms` is elapsed real time,
    which differs by the replay speed and exists only so an animation can be
    paced. Carrying both is cheaper than discovering downstream that the single
    clock chosen was the wrong one.
    """

    seq: int
    type: str
    at_ms: int
    wall_ms: int
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.type,
            "at_ms": self.at_ms,
            "wall_ms": self.wall_ms,
            **self.data,
        }


# ------------------------------------------------------------------- stream --
# A demo session is ~120 s and emits a few hundred events; the conversation
# fixture, which is the busiest thing this will ever carry, emits one rack update
# per frame at most. 5000 is roughly forty times the worst observed session and
# still a bounded list, which matters because a browser that never connects must
# not turn a finished session into a memory leak.
MAX_HISTORY: Final = 5000


class EventStream:
    """Fan-out with a replayable backlog.

    The backlog is not a convenience. `POST /api/demo/replay` starts the pipeline
    and the browser opens the WebSocket afterwards, so without history the judge
    misses the first beats of the demo -- which are the beats that explain it.
    A subscriber therefore receives everything from seq 0 and then follows live,
    and the two paths are the same list.

    One `asyncio.Queue` per subscriber, unbounded: dropping events under back
    pressure would silently rewrite what the record says happened. The bound that
    matters is `MAX_HISTORY`, which is applied to the stored backlog only.
    """

    __slots__ = ("_history", "_subscribers", "_closed", "_seq", "_t0", "_dropped")

    def __init__(self) -> None:
        self._history: list[Event] = []
        self._subscribers: list[asyncio.Queue[Event | None]] = []
        self._closed = False
        self._seq = 0
        self._t0 = time.monotonic()
        self._dropped = 0

    # -- writing --------------------------------------------------------------
    def emit(self, type_: str, at_ms: int = 0, **data: Any) -> Event:
        if type_ not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type_!r}; add it to EVENT_TYPES first")
        ev = Event(
            seq=self._seq,
            type=type_,
            at_ms=int(at_ms),
            wall_ms=int((time.monotonic() - self._t0) * 1000),
            data=data,
        )
        self._seq += 1
        self._history.append(ev)
        if len(self._history) > MAX_HISTORY:
            # Trim from the front and count it, so a truncated record says so
            # rather than looking like a session that started late.
            self._dropped += len(self._history) - MAX_HISTORY
            del self._history[: len(self._history) - MAX_HISTORY]
        for q in self._subscribers:
            q.put_nowait(ev)
        return ev

    def close(self) -> None:
        """No further events. Subscribers drain the backlog and then stop."""
        if self._closed:
            return
        self._closed = True
        for q in self._subscribers:
            q.put_nowait(None)

    # -- reading --------------------------------------------------------------
    @property
    def history(self) -> list[Event]:
        return list(self._history)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def dropped(self) -> int:
        return self._dropped

    def of_type(self, type_: str) -> list[Event]:
        return [e for e in self._history if e.type == type_]

    async def subscribe(self) -> AsyncIterator[Event]:
        """Backlog first, then live. Cancels cleanly on client disconnect."""
        q: asyncio.Queue[Event | None] = asyncio.Queue()
        backlog = list(self._history)
        self._subscribers.append(q)
        try:
            for ev in backlog:
                yield ev
            if self._closed and q.empty():
                return
            seen = backlog[-1].seq if backlog else -1
            while True:
                ev = await q.get()
                if ev is None:
                    return
                # The backlog was copied before the queue was registered, so an
                # event emitted between those two statements arrives twice. Drop
                # by sequence number rather than by locking the writer.
                if ev.seq <= seen:
                    continue
                seen = ev.seq
                yield ev
        finally:
            if q in self._subscribers:
                self._subscribers.remove(q)


__all__ = [
    "CANDIDATES_SHOW",
    "CANDIDATE_SEEN",
    "CAPTURE_COMMIT",
    "CAPTURE_FLAG",
    "CAPTURE_HANDOVER",
    "ERROR",
    "EVENT_TYPES",
    "Event",
    "EventStream",
    "METER",
    "QUESTION_ANSWER",
    "QUESTION_ASK",
    "RACK_UPDATE",
    "REGIME",
    "REPAIR_SILENT",
    "SESSION_END",
    "SESSION_STARTED",
    "SILENCE_HELD",
    "SLOT_ASKED",
    "SLOT_EMPTY",
    "SLOT_LOCKED",
    "SLOT_PROVISIONAL",
    "SLOT_REPAIRED",
    "SLOT_SETTLED",
    "SLOT_STATES",
    "SPAN_REREAD",
    "STATE_ARMED",
    "STATE_IDLE",
    "Slot",
]
