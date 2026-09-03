"""The rolling tape -- one flat word timeline per session (ARCHITECTURE.md 3.4).

**A turn is not the unit.** A spoken identifier routinely straddles two or three
turns, because the canonical place for a mid-utterance hesitation is inside a
code: "MSKU four one five eight... uh... zero zero five". `max_turn_silence`
fires in that gap, so the recogniser hands back the identifier in pieces that
line up with the speaker's breathing rather than with the format. The tape
flattens every turn into one continuous word timeline with session-relative
`start`/`end` preserved, and every consumer reads that timeline. **A turn
boundary is never a parse boundary.**

Two rules that the upstream protocol makes mandatory, and that are enforced here
structurally rather than by convention, because an implementation that gets
either wrong fails silently and in the worst possible way -- by writing down an
identifier twice as long as the one that was spoken:

1. **REPLACE, never append**, keyed on `turn_order`. Partials arrive with
   `end_of_turn: false` and `word_is_final: false` and *may change*; the
   AssemblyAI docs are explicit that the latest transcript is rendered, never
   appended. `ingest` writes into a slot keyed on `turn_order`; there is no code
   path in this file that extends a turn.
2. **Dedupe on `(turn_order, end_of_turn, turn_is_formatted)`.** With
   `format_turns=false` on `universal-3-5-pro` there is exactly one final per
   turn, so the guard is inert today. It costs nothing and it survives a model
   swap or a `format_turns` flip, which would deliver an unformatted final and a
   formatted final for the same `turn_order`.

The rank ordering `partial < final-unformatted < final-formatted` is monotone,
so a late or duplicated frame can never downgrade a slot.

**The seam.** `ingest` takes the decoded AssemblyAI `Turn` frame verbatim. Today
a fixture builds that dict; this evening the session manager writes
`tape.ingest(json.loads(message))` and nothing else in the pipeline changes.
That is the whole reason `ingest` speaks JSON-shaped `Mapping` rather than a
constructor of our own.

**Never persisted.** ARCHITECTURE.md 3.9 lists the rolling tape under "never
stored, in any environment", alongside raw audio and the sentence surrounding an
identifier. Pickling is refused rather than documented, so that a tape cannot
reach a disk by being an incidental attribute of something that is serialised.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence, TypedDict


# --- bounds ------------------------------------------------------------------
# 45 s is the semantic bound. The longest supported identifier is IBAN-GB at 22
# characters; read at a dictation pace of ~400 ms per character that is ~9 s, and
# a read with one self-correction ("no sorry, that's a five") runs to three times
# that. 45 s spans the carrier phrase, the read, and its repairs. Nothing older
# can produce an interruption anyway -- 4.8 gate 7 refuses to speak more than
# 10 s after the identifier's last word -- so the surplus exists for the LLM
# format-ID window (3.8) and for what the rack shows on screen.
MAX_SPAN_MS = 45_000

# 400 words is the failsafe, not the semantic bound. 400 words inside a 45 s
# window is 8.9 words/s, roughly three times conversational rate and faster than
# any human dictates, so in normal operation the time bound always binds first.
# This one binds when the upstream misbehaves: a stuck partial, a re-sent turn,
# or timings that do not advance. It is what keeps memory bounded when the clock
# cannot be trusted.
MAX_WORDS = 400


class WordFrame(TypedDict):
    """One element of `Turn.words` on the AssemblyAI Universal Streaming socket."""

    text: str
    start: int              # ms, relative to session start
    end: int
    confidence: float
    word_is_final: bool


class TurnFrame(TypedDict):
    """The upstream `Turn` message, verbatim. `ingest` accepts exactly this."""

    type: str
    turn_order: int
    turn_is_formatted: bool
    end_of_turn: bool
    transcript: str
    end_of_turn_confidence: float
    words: Sequence[WordFrame]


@dataclass(frozen=True, slots=True)
class Word:
    """One recognised token, with the timings the rhythm detector runs on.

    `turn_order` is carried through the flattening so that provenance survives --
    the detector reads a flat timeline, but the decider still needs to know which
    turn ended, and the audit log needs to say where a character came from.
    """

    text: str
    start: int
    end: int
    confidence: float
    is_final: bool
    turn_order: int

    @property
    def duration_ms(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class Turn:
    """One turn slot. Replaced wholesale on every frame; never extended."""

    turn_order: int
    end_of_turn: bool
    turn_is_formatted: bool
    transcript: str
    end_of_turn_confidence: float
    words: tuple[Word, ...]

    @property
    def rank(self) -> int:
        """Monotone frame strength: partial 0, final 2, formatted final 3.

        A frame may only overwrite a slot of equal or lower rank. That single
        comparison is what makes out-of-order delivery harmless: a partial that
        arrives after its own final is stale by construction and is dropped.
        """
        return (2 if self.end_of_turn else 0) + (1 if self.turn_is_formatted else 0)


def _word(raw: Mapping[str, Any], turn_order: int) -> Word:
    return Word(
        text=str(raw.get("text", "")),
        start=int(raw.get("start", 0)),
        end=int(raw.get("end", 0)),
        confidence=float(raw.get("confidence", 0.0)),
        is_final=bool(raw.get("word_is_final", False)),
        turn_order=turn_order,
    )


class Tape:
    """One per session. The only thing the detector reads.

    Turns are held in a dict keyed on `turn_order`, not a deque, and that is rule
    1 made structural rather than remembered: a deque offers `append` and a dict
    keyed on the turn's own identity does not. Ordering is recovered by sorting
    the keys, which is free at this size and is the only cost of the choice.

    Not thread-safe and deliberately not made so: one session owns one socket
    reader, and a lock here would hide a second writer rather than prevent one.
    """

    __slots__ = ("max_span_ms", "max_words", "_turns", "_flat", "_finals", "_floor")

    def __init__(self, max_span_ms: int = MAX_SPAN_MS, max_words: int = MAX_WORDS) -> None:
        self.max_span_ms = max_span_ms
        self.max_words = max_words
        self._turns: dict[int, Turn] = {}
        self._finals: set[tuple[int, bool, bool]] = set()
        self._floor = -1                           # highest turn_order ever evicted
        self._flat: list[Word] | None = None       # window cache, see _invalidate

    # -- ingest ---------------------------------------------------------------

    def ingest(self, frame: Mapping[str, Any]) -> bool:
        """Absorb one upstream frame. Returns True if the tape changed.

        Non-`Turn` frames (Begin, Termination, Heartbeat, LLMGatewayResponse) are
        ignored rather than rejected, so the session manager can hand the tape
        every message it decodes without filtering first.
        """
        if frame.get("type") != "Turn":
            return False
        if "turn_order" not in frame:
            return False

        turn_order = int(frame["turn_order"])
        if turn_order <= self._floor:
            # This turn has already rolled off the end of the tape. Re-admitting
            # it would resurrect a slot the bound deliberately dropped, and it is
            # also what makes the dedupe set safe to prune on eviction.
            return False
        end_of_turn = bool(frame.get("end_of_turn", False))
        formatted = bool(frame.get("turn_is_formatted", False))

        # Rule 2: dedupe on (turn_order, end_of_turn, turn_is_formatted). Only
        # finals are deduped -- two frames carrying the same key are the same
        # frame twice. Partials share a key with every other partial of that turn
        # and are *supposed* to differ, so they always replace.
        key = (turn_order, end_of_turn, formatted)
        if end_of_turn and key in self._finals:
            return False

        incoming = Turn(
            turn_order=turn_order,
            end_of_turn=end_of_turn,
            turn_is_formatted=formatted,
            transcript=str(frame.get("transcript", "")),
            end_of_turn_confidence=float(frame.get("end_of_turn_confidence", 0.0)),
            words=tuple(_word(w, turn_order) for w in (frame.get("words") or ())),
        )

        existing = self._turns.get(turn_order)
        if existing is not None and incoming.rank < existing.rank:
            return False                           # stale frame behind a stronger one

        # Rule 1: replace, never append. The slot is assigned, never extended.
        self._turns[turn_order] = incoming
        if end_of_turn:
            self._finals.add(key)
        self._invalidate()
        self._evict()
        return True

    def ingest_all(self, frames: Sequence[Mapping[str, Any]]) -> int:
        """Convenience for fixtures and replay. Returns the number absorbed."""
        return sum(1 for f in frames if self.ingest(f))

    # -- the flat timeline ----------------------------------------------------

    @property
    def words(self) -> list[Word]:
        """The whole tape as one word timeline, oldest first, bounded.

        Ordered by `(turn_order, position in turn)` rather than by `start`,
        because that is the order the recogniser committed to. Sorting by `start`
        would reshuffle words across a turn boundary whenever two turns overlap
        by a millisecond, which is exactly the boundary an identifier straddles.
        """
        if self._flat is None:
            flat: list[Word] = []
            for order in sorted(self._turns):
                flat.extend(self._turns[order].words)
            if len(flat) > self.max_words:
                flat = flat[-self.max_words:]
            if flat:
                # The bound is applied at read time as well as by eviction, so a
                # single pathological turn longer than the whole budget still
                # yields a bounded window.
                cutoff = flat[-1].end - self.max_span_ms
                if flat[0].end <= cutoff:
                    flat = [w for w in flat if w.end > cutoff]
            self._flat = flat
        return self._flat

    @property
    def text(self) -> str:
        """The window as text, for the carrier and shape cues.

        Built from the windowed words, not from `Turn.transcript`: the window can
        cut a turn in half, and joining transcripts would re-import the words the
        bound just dropped.
        """
        return " ".join(w.text for w in self.words if w.text)

    @property
    def turns(self) -> tuple[Turn, ...]:
        return tuple(self._turns[o] for o in sorted(self._turns))

    @property
    def now_ms(self) -> int:
        """The tape's clock: the end of the most recent word, session-relative.

        Every deadline in the pipeline is measured against this rather than
        against `time.time()`. Two reasons, and both are load-bearing: upstream
        timings are session-relative already, so mixing clocks introduces a skew
        equal to the socket latency; and a fixture replayed in 3 ms exercises the
        same 12 s decay as a live call.
        """
        w = self.words
        return w[-1].end if w else 0

    @property
    def span_ms(self) -> int:
        w = self.words
        return (w[-1].end - w[0].start) if w else 0

    def since(self, start_ms: int) -> list[Word]:
        """Words whose onset is at or after `start_ms`."""
        return [w for w in self.words if w.start >= start_ms]

    def tail(self, n: int) -> list[Word]:
        return self.words[-n:] if n > 0 else []

    def __len__(self) -> int:
        return len(self.words)

    def __iter__(self) -> Iterator[Word]:
        return iter(self.words)

    def clear(self) -> None:
        """Destroy the tape. Called at session end and by the stop-and-delete button."""
        self._turns.clear()
        self._finals.clear()
        self._floor = -1                           # a new session restarts turn_order at 0
        self._invalidate()

    # -- internals ------------------------------------------------------------

    def _invalidate(self) -> None:
        # `words` is read several times per partial -- four cues, then the
        # normaliser -- at 5-10 partials per second. The cache turns that back
        # into one flatten per frame.
        self._flat = None

    def _evict(self) -> None:
        """Drop whole turns off the front until what is *stored* is inside bounds.

        Measured on the stored turns, never on `words` -- `words` already applies
        the bound at read time, so evicting against it would stop immediately and
        the tape would grow without limit behind a correct-looking window.

        The newest turn is never evicted: it is the live partial, and a tape that
        drops it has nothing to detect on.
        """
        while len(self._turns) > 1:
            stored = [t for t in self._turns.values() if t.words]
            n = sum(len(t.words) for t in stored)
            if stored:
                span = max(t.words[-1].end for t in stored) - min(t.words[0].start for t in stored)
            else:
                span = 0
            if n <= self.max_words and span <= self.max_span_ms:
                return
            oldest = min(self._turns)
            del self._turns[oldest]
            self._floor = max(self._floor, oldest)
            self._finals.discard((oldest, True, False))
            self._finals.discard((oldest, True, True))
            self._invalidate()

    def __reduce__(self) -> Any:
        # ARCHITECTURE.md 3.9 lists the rolling tape among the things never
        # stored in any environment. Refusing here means a tape cannot reach a
        # disk by being an attribute of something else that gets serialised --
        # a Celery task argument, a cached session object, a crash dump.
        raise TypeError("the rolling tape is never persisted (ARCHITECTURE.md 3.9)")
