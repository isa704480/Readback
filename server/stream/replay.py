# replay.py -- a TranscriptSource backed by a recorded fixture file.
#
# This is the file that makes the system buildable before the key arrives, and
# it is only worth anything if it reproduces the awkward parts. A replay that
# hands the detector one clean final per turn tests nothing: the four properties
# that actually break downstream code are partials that MUTATE, an identifier
# that STRADDLES turn boundaries, a confidence spread wide enough that
# confidence alone cannot separate right from wrong, and a reconfiguration that
# lands one turn LATE. All four are reproduced here.
#
# The fixture file is the wire format verbatim -- each entry's "frame" is
# exactly the JSON the socket would have delivered -- so a session captured
# tonight becomes a fixture with no conversion step, and no adapter sits between
# the two implementations where drift could hide.
from __future__ import annotations

import asyncio
import copy
import json
import math
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .source import (
    BaseTranscriptSource,
    ControlEvent,
    SourceClosed,
    SourceConfig,
    SourceError,
    Turn,
    validate_turn,
)

SCHEMA = "readback.fixture/1"


@dataclass(frozen=True, slots=True)
class FrameEntry:
    """One frame plus the moment the socket delivered it.

    `emit_ms` is session-relative delivery time, which is deliberately NOT the
    same as the end time of the last word in the frame: recognition lags the
    audio, and the detector's whole job is to fire while the code is still being
    spoken, so the gap between "the word finished" and "we heard about it" is
    part of what is being tested.

    `requires_keyterm` / `forbids_keyterm` select between recorded variants of
    the same turn according to the keyterms in force when that turn STARTED.
    This is how a fixture reproduces the payoff of arming (ARCHITECTURE 3.6):
    the same audio comes back differently once the owner-code prefix is biased
    in, and it comes back differently starting one turn after the request.
    """
    emit_ms: int
    frame: Turn
    requires_keyterm: str | None = None
    forbids_keyterm: str | None = None


@dataclass(frozen=True, slots=True)
class Fixture:
    """A recorded session. `truth` and `expect` are metadata for tests; nothing
    in the streaming path reads them, because the live socket has neither."""
    name: str
    description: str = ""
    entries: tuple[FrameEntry, ...] = ()
    truth: dict[str, Any] = field(default_factory=dict)
    expect: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    initial_config: SourceConfig = field(default_factory=SourceConfig)

    @property
    def duration_ms(self) -> int:
        return max((e.emit_ms for e in self.entries), default=0)

    @property
    def turn_orders(self) -> list[int]:
        seen: list[int] = []
        for entry in self.entries:
            order = entry.frame["turn_order"]
            if order not in seen:
                seen.append(order)
        return seen

    # -- serialisation --------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict[str, Any], where: str = "fixture") -> Fixture:
        schema = data.get("schema")
        if schema != SCHEMA:
            raise SourceError(f"{where}: schema is {schema!r}, expected {SCHEMA!r}")
        entries: list[FrameEntry] = []
        last_ms = -1
        for i, raw in enumerate(data.get("frames", [])):
            emit_ms = raw.get("emit_ms")
            if not isinstance(emit_ms, int) or isinstance(emit_ms, bool):
                raise SourceError(f"{where}: frames[{i}].emit_ms must be an int")
            # Monotone delivery is a property of a socket, so a fixture that
            # violates it is a broken recording rather than an interesting case.
            if emit_ms < last_ms:
                raise SourceError(
                    f"{where}: frames[{i}].emit_ms {emit_ms} goes back in time from {last_ms}"
                )
            last_ms = emit_ms
            frame = validate_turn(raw.get("frame"), f"{where}: frames[{i}].frame")
            entries.append(
                FrameEntry(
                    emit_ms=emit_ms,
                    frame=frame,
                    requires_keyterm=raw.get("requires_keyterm"),
                    forbids_keyterm=raw.get("forbids_keyterm"),
                )
            )
        cfg = data.get("initial_config") or {}
        config = SourceConfig(
            keyterms=tuple(cfg.get("keyterms", ())),
            max_turn_silence=cfg.get("max_turn_silence", SourceConfig().max_turn_silence),
            prompt=cfg.get("prompt"),
            end_of_turn_confidence_threshold=cfg.get("end_of_turn_confidence_threshold"),
        )
        config.validate()
        return cls(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            entries=tuple(entries),
            truth=data.get("truth", {}) or {},
            expect=data.get("expect", {}) or {},
            notes=tuple(data.get("notes", ()) or ()),
            initial_config=config,
        )

    @classmethod
    def load(cls, path: str | Path) -> Fixture:
        p = Path(path)
        with p.open("r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh), where=p.name)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema": SCHEMA,
            "name": self.name,
            "description": self.description,
        }
        if self.notes:
            out["notes"] = list(self.notes)
        if self.truth:
            out["truth"] = self.truth
        if self.expect:
            out["expect"] = self.expect
        cfg = self.initial_config
        if cfg != SourceConfig():
            out["initial_config"] = {
                "keyterms": list(cfg.keyterms),
                "max_turn_silence": cfg.max_turn_silence,
                "prompt": cfg.prompt,
                "end_of_turn_confidence_threshold": cfg.end_of_turn_confidence_threshold,
            }
        frames: list[dict[str, Any]] = []
        for entry in self.entries:
            item: dict[str, Any] = {"emit_ms": entry.emit_ms, "frame": entry.frame}
            if entry.requires_keyterm:
                item["requires_keyterm"] = entry.requires_keyterm
            if entry.forbids_keyterm:
                item["forbids_keyterm"] = entry.forbids_keyterm
            frames.append(item)
        out["frames"] = frames
        return out

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.to_dict(), fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        return p


def load_fixture(path: str | Path) -> Fixture:
    return Fixture.load(path)


class ReplaySource(BaseTranscriptSource):
    """Replays a fixture at its recorded timing.

    `speed` multiplies the clock: 1.0 is real time, 8.0 is eight times faster,
    and 0 (or inf) removes the waiting entirely. Tests default to instant --
    reproducing two minutes of conversation in two minutes is not a test, it is
    a wait -- but the timing path is exercised by the timing test, because the
    detector's rhythm cue (3.6) reads `words[].start` and a replay that
    delivered everything at once would let a broken IOI window pass.
    """

    def __init__(
        self,
        fixture: Fixture | str | Path,
        *,
        speed: float = 0.0,
        config: SourceConfig | None = None,
    ) -> None:
        fx = fixture if isinstance(fixture, Fixture) else Fixture.load(fixture)
        super().__init__(config or fx.initial_config)
        self.fixture: Fixture = fx
        self._speed: float = float(speed)
        self._instant: bool = self._speed <= 0.0 or math.isinf(self._speed)
        self._stop: asyncio.Event = asyncio.Event()
        self._clock_ms: int = 0
        self._last_word_end_ms: int = 0
        # Keyterms in force when each turn STARTED. Not the same as the config
        # at delivery: a turn's final is emitted after the endpoint timer, by
        # which time the next turn -- and a reconfiguration with it -- may have
        # begun. Gating a late final on the current config selects the armed
        # recording of a turn that was recognised unarmed, which is upstream
        # retroactively re-biasing a turn it has already finished.
        self._turn_keyterms: dict[int, frozenset[str]] = {}
        self._forced_turn: int | None = None
        self._force_event: ControlEvent | None = None
        self.emitted: list[Turn] = []
        self.skipped: list[FrameEntry] = []

    # -- clock ---------------------------------------------------------------
    def now_ms(self) -> int:
        """Fixture time, not wall time. A control call logged during an 8x replay
        should read as the moment in the conversation where it happened, or the
        control log is useless for reasoning about the demo."""
        if self._instant:
            return self._clock_ms
        return int((time.monotonic() - self._t0) * 1000.0 * self._speed)

    # -- control -------------------------------------------------------------
    async def send_audio(self, pcm: bytes) -> None:
        """Replay is deaf, on purpose.

        The browser's PCM pump has to run unchanged against both implementations
        or the seam leaks: the moment the caller has to ask "am I on a fixture?"
        before deciding whether to send audio, half the pipeline is no longer
        under test. Bytes are counted so the meter has something to show.
        """
        if self._closed:
            raise SourceClosed("send_audio on a terminated source")
        self._audio_bytes += len(pcm)

    async def force_endpoint(self) -> None:
        """Close the turn in flight immediately.

        Faithful to what the real frame does: the partials that would have
        arrived during the remaining `max_turn_silence` never arrive, and the
        final lands now rather than after the endpoint timer. The reclaimed
        milliseconds are recorded because that reclaim is the entire reason the
        ARMED state can afford a 2500 ms endpoint (3.6).
        """
        if self._closed:
            raise SourceClosed("force_endpoint on a terminated source")
        self._forced_turn = self._current_turn
        self._force_event = self._log_control("force_endpoint", ms_saved=0, frames_dropped=0)

    async def terminate(self) -> None:
        """End the replay. Sets billed seconds the way Termination does."""
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        self.billed_seconds = round(max(self._clock_ms, self._last_word_end_ms) / 1000.0, 3)
        self._log_control("terminate", billed_seconds=self.billed_seconds)

    # -- the stream ----------------------------------------------------------
    async def _frames(self) -> AsyncIterator[Turn]:
        self._t0 = time.monotonic()
        self.session_id = f"replay:{self.fixture.name}"
        for entry in self.fixture.entries:
            if self._stop.is_set():
                break
            order = entry.frame["turn_order"]
            # Forward-only: a turn's final is emitted after the endpoint timer
            # and the next speaker rarely waits that long, so a final for turn N
            # routinely arrives after partials for turn N+1. That late frame is
            # not a new turn starting and must not commit a pending config.
            if self._current_turn is None or order > self._current_turn:
                # The only place a pending configuration becomes effective.
                # Everything about mid-stream reconfiguration being one turn
                # late follows from this line and nothing else.
                self._begin_turn(order)
                self._turn_keyterms[order] = frozenset(
                    k.upper() for k in self._config.keyterms
                )
                if self._forced_turn is not None and order > self._forced_turn:
                    self._forced_turn = None
            if not self._entry_enabled(entry):
                self.skipped.append(entry)
                continue
            forced = self._forced_turn == order
            if forced and not entry.frame["end_of_turn"]:
                # A partial that the endpoint pre-empted. It never happened.
                self.skipped.append(entry)
                self._bump_force_counters(frames_dropped=1)
                continue
            if forced:
                self._bump_force_counters(ms_saved=max(0, entry.emit_ms - self.now_ms()))
            elif not await self._wait_until(entry.emit_ms):
                break
            self._clock_ms = max(self._clock_ms, entry.emit_ms)
            words = entry.frame["words"]
            if words:
                self._last_word_end_ms = max(self._last_word_end_ms, words[-1]["end"])
            # Deep copy: the tape hands these to the normaliser and the solver,
            # and a fixture that mutates under a second replay is a debugging
            # session nobody should have to have.
            frame: Turn = copy.deepcopy(entry.frame)
            self.emitted.append(frame)
            yield frame
        if not self._closed:
            await self.terminate()

    def _entry_enabled(self, entry: FrameEntry) -> bool:
        """Variant selection against the config in force at this turn's start."""
        if entry.requires_keyterm is None and entry.forbids_keyterm is None:
            return True
        armed = self._turn_keyterms.get(
            entry.frame["turn_order"],
            frozenset(k.upper() for k in self._config.keyterms),
        )
        if entry.requires_keyterm is not None and entry.requires_keyterm.upper() not in armed:
            return False
        if entry.forbids_keyterm is not None and entry.forbids_keyterm.upper() in armed:
            return False
        return True

    def _bump_force_counters(self, ms_saved: int = 0, frames_dropped: int = 0) -> None:
        if self._force_event is None:
            return
        d = self._force_event.detail
        d["ms_saved"] = max(int(d.get("ms_saved", 0)), ms_saved)
        d["frames_dropped"] = int(d.get("frames_dropped", 0)) + frames_dropped

    async def _wait_until(self, emit_ms: int) -> bool:
        """Sleep until this frame is due. False if terminate() cut the wait --
        which is what a real Terminate does to a turn in flight."""
        if self._instant:
            return True
        delay = (self._t0 + (emit_ms / 1000.0) / self._speed) - time.monotonic()
        if delay <= 0:
            return not self._stop.is_set()
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except (asyncio.TimeoutError, TimeoutError):
            return True
        return False


async def replay_all(
    fixture: Fixture | str | Path,
    *,
    speed: float = 0.0,
    config: SourceConfig | None = None,
) -> list[Turn]:
    """Every frame a fixture produces, with no control operations. The baseline
    a round-trip test compares against."""
    src = ReplaySource(fixture, speed=speed, config=config)
    async with src:
        return [frame async for frame in src]


def fixture_dir() -> Path:
    """tests/fixtures, located from this file rather than the cwd."""
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def load_all(directory: str | Path | None = None) -> list[Fixture]:
    """Every fixture in the corpus, name-sorted so a regression report is
    diffable run to run."""
    d = Path(directory) if directory is not None else fixture_dir()
    return [Fixture.load(p) for p in sorted(d.glob("*.json"))]


__all__ = [
    "SCHEMA",
    "Fixture",
    "FrameEntry",
    "ReplaySource",
    "fixture_dir",
    "load_all",
    "load_fixture",
    "replay_all",
]
