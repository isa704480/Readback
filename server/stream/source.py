# source.py -- the transcript source contract. Everything downstream is written
# against this and nothing downstream may ask which implementation it holds.
#
# There is no API key until this evening, so the only way the detector, the
# tape, the normaliser and the decider can be built and regression-tested today
# is if the thing feeding them is an interface rather than a socket. This file
# is that interface; `replay.py` and `live.py` are the two implementations, and
# the whole point of the exercise is that swapping one for the other tonight is
# a constructor argument, not an edit.
from __future__ import annotations

import abc
import time
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol, runtime_checkable

try:                                    # 3.12 has TypedDict in typing; keep the
    from typing import TypedDict        # import explicit so the wire types are
except ImportError:                     # obviously wire types and not models.
    from typing_extensions import TypedDict     # pragma: no cover


# --------------------------------------------------------------- wire shape --
# These are TypedDicts, not dataclasses, and that is a deliberate choice about
# where drift can hide. A fixture file on disk, a frame off the socket and the
# object the detector reads are then literally the same bytes: `json.loads` of a
# recorded frame IS a Turn, and `json.dumps` of a live frame IS a fixture line.
# A dataclass would put an adapter between the two implementations, and an
# adapter is exactly the place where the replay path quietly stops resembling
# the live path.

class Word(TypedDict):
    """One word as AssemblyAI Universal Streaming emits it.

    `start`/`end` are milliseconds relative to session start, not to the turn.
    `word_is_final` false means this word may still change -- see `Turn`.
    """
    text: str
    start: int
    end: int
    confidence: float
    word_is_final: bool


class Turn(TypedDict):
    """One Turn frame.

    Partials arrive with `end_of_turn` false and words whose `word_is_final` is
    false, and THEY MAY CHANGE. The documentation is explicit that the latest
    frame for a `turn_order` replaces the previous one; appending partials
    produces a transcript containing every abandoned hypothesis. `tape.Tape`
    enforces replacement structurally so no consumer has to remember.
    """
    type: Literal["Turn"]
    turn_order: int
    turn_is_formatted: bool
    end_of_turn: bool
    transcript: str
    end_of_turn_confidence: float
    words: list[Word]


# --------------------------------------------------------------- exceptions --
class SourceError(Exception):
    """Base for everything this package raises."""


class SourceClosed(SourceError):
    """Operation attempted on a source that has terminated."""


class ConfigurationError(SourceError):
    """A configuration the upstream would reject, caught before it is sent."""


# ------------------------------------------------------------ configuration --
# Documented caps on `keyterms_prompt`. They are enforced here rather than at
# the socket because the arming logic (ARCHITECTURE 3.6) sits right against the
# 100-term ceiling by design -- NATO (26) + digit variants (~15) + carriers
# (~20) is already 61 in IDLE -- so an over-long keyterm list is a plausible bug
# and a 4001 close mid-demo is an expensive way to discover it.
KEYTERM_LIMIT = 100
KEYTERM_MAX_CHARS = 50

# ARCHITECTURE 3.6: IDLE runs a short endpoint so ordinary conversation turns
# close promptly; ARMED raises it because the canonical place for a >700 ms
# human pause is in the middle of a code, and a turn boundary there costs the
# detector its span. ForceEndpoint claws the added latency back once the
# candidate is length-complete.
IDLE_MAX_TURN_SILENCE_MS = 1536
ARMED_MAX_TURN_SILENCE_MS = 2500


@dataclass(frozen=True, slots=True)
class SourceConfig:
    """The subset of session configuration that is changeable mid-stream.

    Frozen because a configuration is a fact about a point in time: the detector
    needs to be able to say "this turn was produced under that config", which is
    impossible if the config object it captured is the one that later mutated.
    """
    keyterms: tuple[str, ...] = ()
    max_turn_silence: int = IDLE_MAX_TURN_SILENCE_MS
    prompt: str | None = None
    end_of_turn_confidence_threshold: float | None = None

    def validate(self) -> None:
        if len(self.keyterms) > KEYTERM_LIMIT:
            raise ConfigurationError(
                f"{len(self.keyterms)} keyterms exceeds the {KEYTERM_LIMIT} cap"
            )
        for term in self.keyterms:
            if len(term) > KEYTERM_MAX_CHARS:
                raise ConfigurationError(
                    f"keyterm {term!r} is {len(term)} chars, cap is {KEYTERM_MAX_CHARS}"
                )
        if self.max_turn_silence < 0:
            raise ConfigurationError("max_turn_silence must be non-negative")
        if self.end_of_turn_confidence_threshold is not None and not (
            0.0 <= self.end_of_turn_confidence_threshold <= 1.0
        ):
            raise ConfigurationError("end_of_turn_confidence_threshold must be in [0, 1]")


@dataclass(slots=True)
class ControlEvent:
    """One control operation, with the turn it was requested in and the turn it
    actually reached.

    Not mutable state for its own sake: `applied_turn` is the instrument that
    makes "reconfiguration lands at a turn boundary, never inside one" a thing a
    test can assert instead of a thing a comment claims.
    """
    kind: Literal["update_configuration", "force_endpoint", "terminate"]
    at_ms: int
    requested_turn: int | None
    applied_turn: int | None = None
    config: SourceConfig | None = None
    detail: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------- the contract --
@runtime_checkable
class TranscriptSource(Protocol):
    """What the rest of the system is allowed to know about its input.

    `runtime_checkable` only checks that the names exist -- it does not check
    signatures. It is here for a cheap assertion at the composition root, not as
    a substitute for the ABC below, which is what the two implementations
    actually share.
    """

    session_id: str | None
    billed_seconds: float | None
    control_log: list[ControlEvent]

    @property
    def config(self) -> SourceConfig: ...

    @property
    def closed(self) -> bool: ...

    def __aiter__(self) -> AsyncIterator[Turn]: ...

    async def __aenter__(self) -> TranscriptSource: ...

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...

    async def send_audio(self, pcm: bytes) -> None: ...

    async def update_configuration(
        self,
        keyterms: Sequence[str] | None = None,
        max_turn_silence: int | None = None,
        prompt: str | None = None,
        *,
        end_of_turn_confidence_threshold: float | None = None,
    ) -> None: ...

    async def force_endpoint(self) -> None: ...

    async def terminate(self) -> None: ...


class BaseTranscriptSource(abc.ABC):
    """Shared machinery for both implementations.

    Only one behaviour is worth centralising, and it is the one that is easy to
    get wrong in the replay and then never notice: a configuration change lands
    at a turn BOUNDARY. Upstream cannot retroactively re-bias a turn it has
    already started emitting words for, so a replay that applies keyterms
    immediately would let the detector pass a test the live socket then fails.
    The pending/effective split lives here so both implementations inherit the
    same semantics rather than each inventing them.
    """

    def __init__(self, config: SourceConfig | None = None) -> None:
        cfg = config or SourceConfig()
        cfg.validate()
        self._config: SourceConfig = cfg
        self._pending: SourceConfig | None = None
        self._pending_events: list[ControlEvent] = []
        self.control_log: list[ControlEvent] = []
        self.session_id: str | None = None
        self.billed_seconds: float | None = None
        self._current_turn: int | None = None
        self._closed: bool = False
        self._t0: float = time.monotonic()
        self._iter: AsyncIterator[Turn] | None = None
        self._audio_bytes: int = 0

    # -- clock ---------------------------------------------------------------
    def now_ms(self) -> int:
        """Milliseconds since the source started, on the same clock the frames
        use. Replay overrides this to report fixture time rather than wall time,
        so a control event logged at 8x speed still reads as the moment in the
        conversation where it happened."""
        return int((time.monotonic() - self._t0) * 1000)

    # -- state ---------------------------------------------------------------
    @property
    def config(self) -> SourceConfig:
        """The configuration currently in force -- not the one last requested."""
        return self._config

    @property
    def pending_config(self) -> SourceConfig | None:
        """Requested but not yet at a turn boundary. None once it has landed."""
        return self._pending

    @property
    def current_turn(self) -> int | None:
        return self._current_turn

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def audio_bytes_sent(self) -> int:
        return self._audio_bytes

    # -- control -------------------------------------------------------------
    async def update_configuration(
        self,
        keyterms: Sequence[str] | None = None,
        max_turn_silence: int | None = None,
        prompt: str | None = None,
        *,
        end_of_turn_confidence_threshold: float | None = None,
    ) -> None:
        """Request a mid-stream reconfiguration. None means "leave unchanged".

        `end_of_turn_confidence_threshold` is keyword-only and beyond the three
        the detector strictly needs, because ARMED lowers it (3.6) and passing
        it positionally alongside the other three invites the wrong argument
        order in the one call site that runs during a demo.
        """
        if self._closed:
            raise SourceClosed("update_configuration on a terminated source")
        base = self._pending or self._config
        new = replace(
            base,
            keyterms=tuple(keyterms) if keyterms is not None else base.keyterms,
            max_turn_silence=(
                max_turn_silence if max_turn_silence is not None else base.max_turn_silence
            ),
            prompt=prompt if prompt is not None else base.prompt,
            end_of_turn_confidence_threshold=(
                end_of_turn_confidence_threshold
                if end_of_turn_confidence_threshold is not None
                else base.end_of_turn_confidence_threshold
            ),
        )
        new.validate()
        self._pending = new
        event = ControlEvent(
            kind="update_configuration",
            at_ms=self.now_ms(),
            requested_turn=self._current_turn,
            config=new,
        )
        self.control_log.append(event)
        self._pending_events.append(event)
        await self._on_update_configuration(new)

    def _begin_turn(self, turn_order: int) -> None:
        """Called by the implementation as each new turn_order starts.

        This is the only place a pending configuration becomes effective.
        """
        self._current_turn = turn_order
        if self._pending is None:
            return
        self._config = self._pending
        self._pending = None
        for event in self._pending_events:
            event.applied_turn = turn_order
        self._pending_events.clear()

    def _log_control(self, kind: Literal["force_endpoint", "terminate"], **detail: Any) -> ControlEvent:
        event = ControlEvent(
            kind=kind,
            at_ms=self.now_ms(),
            requested_turn=self._current_turn,
            applied_turn=self._current_turn,
            detail=dict(detail),
        )
        self.control_log.append(event)
        return event

    # -- hooks the implementations fill in ------------------------------------
    async def _on_update_configuration(self, config: SourceConfig) -> None:
        """Live sends the UpdateConfiguration frame here. Replay does nothing --
        it has no upstream to tell, only a boundary to wait for."""
        return None

    @abc.abstractmethod
    def _frames(self) -> AsyncIterator[Turn]:
        """Yield Turn frames. Must call `_begin_turn` before the first frame of
        each turn_order, and must yield frames the consumer is free to mutate."""

    @abc.abstractmethod
    async def send_audio(self, pcm: bytes) -> None:
        """Feed upstream audio.

        In the interface, not on the live class alone, and that is load-bearing:
        the browser's PCM pump must be able to run against either implementation
        without a branch. Replay is deaf and discards it (counting bytes for the
        meter), which is what lets a fixture session and a live session share one
        code path from the microphone down.
        """

    @abc.abstractmethod
    async def force_endpoint(self) -> None:
        """Close the turn in flight now, rather than waiting out
        `max_turn_silence`. Called once the candidate is length-complete."""

    @abc.abstractmethod
    async def terminate(self) -> None:
        """End the session. Billing is socket wall-clock including silence, so
        this is the single most expensive method in the codebase to forget."""

    # -- iteration and lifetime ----------------------------------------------
    def __aiter__(self) -> AsyncIterator[Turn]:
        if self._iter is None:
            self._iter = self._frames()
        return self._iter

    async def __aenter__(self) -> BaseTranscriptSource:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if not self._closed:
            await self.terminate()


# ------------------------------------------------------------- small helpers --
_REQUIRED_TURN_KEYS: dict[str, type | tuple[type, ...]] = {
    "type": str,
    "turn_order": int,
    "turn_is_formatted": bool,
    "end_of_turn": bool,
    "transcript": str,
    "end_of_turn_confidence": (int, float),
    "words": list,
}
_REQUIRED_WORD_KEYS: dict[str, type | tuple[type, ...]] = {
    "text": str,
    "start": int,
    "end": int,
    "confidence": (int, float),
    "word_is_final": bool,
}


def validate_turn(frame: object, where: str = "frame") -> Turn:
    """Assert a decoded frame is the documented Turn shape, and say where it
    failed. Cheap, and it means a hand-edited fixture fails at load with the
    offending key named rather than three components downstream as a KeyError
    inside the normaliser."""
    if not isinstance(frame, dict):
        raise SourceError(f"{where}: expected an object, got {type(frame).__name__}")
    for key, typ in _REQUIRED_TURN_KEYS.items():
        if key not in frame:
            raise SourceError(f"{where}: missing key {key!r}")
        # bool is a subclass of int, so an int field must reject True explicitly.
        if typ is int and isinstance(frame[key], bool):
            raise SourceError(f"{where}: {key!r} is a bool, expected int")
        if not isinstance(frame[key], typ):
            raise SourceError(
                f"{where}: {key!r} is {type(frame[key]).__name__}, expected {typ}"
            )
    if frame["type"] != "Turn":
        raise SourceError(f"{where}: type is {frame['type']!r}, expected 'Turn'")
    for i, word in enumerate(frame["words"]):
        if not isinstance(word, dict):
            raise SourceError(f"{where}: words[{i}] is not an object")
        for key, typ in _REQUIRED_WORD_KEYS.items():
            if key not in word:
                raise SourceError(f"{where}: words[{i}] missing key {key!r}")
            if typ is int and isinstance(word[key], bool):
                raise SourceError(f"{where}: words[{i}].{key} is a bool, expected int")
            if not isinstance(word[key], typ):
                raise SourceError(
                    f"{where}: words[{i}].{key} is {type(word[key]).__name__}, expected {typ}"
                )
        if word["end"] < word["start"]:
            raise SourceError(f"{where}: words[{i}] ends before it starts")
    return frame           # type: ignore[return-value]


def final_words(turns: Iterable[Turn]) -> list[Word]:
    """Words from finished turns only, in session time order.

    The detector runs on every partial, but anything that commits a capture runs
    on this: a partial's words are hypotheses and half of the interesting ones
    change before the turn closes.
    """
    out: list[Word] = []
    for turn in turns:
        if turn["end_of_turn"]:
            out.extend(turn["words"])
    out.sort(key=lambda w: (w["start"], w["end"]))
    return out


async def drain(source: TranscriptSource) -> list[Turn]:
    """Collect every frame a source produces. Test and bench convenience."""
    frames: list[Turn] = []
    async for frame in source:                       # type: ignore[union-attr]
        frames.append(frame)
    return frames


__all__ = [
    "ARMED_MAX_TURN_SILENCE_MS",
    "BaseTranscriptSource",
    "ConfigurationError",
    "ControlEvent",
    "IDLE_MAX_TURN_SILENCE_MS",
    "KEYTERM_LIMIT",
    "KEYTERM_MAX_CHARS",
    "SourceClosed",
    "SourceConfig",
    "SourceError",
    "TranscriptSource",
    "Turn",
    "Word",
    "drain",
    "final_words",
    "validate_turn",
]
