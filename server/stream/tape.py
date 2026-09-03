# tape.py -- one name, one implementation.
#
# There were two rolling tapes in this repository: this file and
# `server/pipeline/tape.py`, written by different hands on the same day, both
# claiming to enforce ARCHITECTURE 3.4's two structural rules. Two
# implementations of a rule described as "enforced structurally rather than by
# convention" is precisely the drift that phrasing exists to prevent -- and they
# had already diverged, on the one decision that matters at a turn boundary:
# this one flattened by `(start, end)`, which reshuffles words across a boundary
# whenever two turns overlap by a millisecond, and that boundary is exactly the
# one an identifier straddles.
#
# The pipeline implementation is the one the detector and the runner read, so it
# is the one that survives. This file keeps its name and its dict-shaped API so
# that stream-side callers do not have to care, and adapts: `push` takes a wire
# `Turn` and `words()` gives them back, while replacement, dedupe, eviction and
# the refusal to be pickled all happen once, in one place.
from __future__ import annotations

from server.pipeline.tape import MAX_SPAN_MS, MAX_WORDS
from server.pipeline.tape import Tape as _Tape

from .source import Turn, Word


class Tape:
    """Finished turns plus the live partial, flattened into one word timeline.

    Two rules, and they are now enforced in exactly one file:

    1. REPLACE, NEVER APPEND, keyed on `turn_order`. Partials mutate -- the
       documentation is explicit that the latest frame supersedes the previous
       one. Appending produces a transcript containing every hypothesis the
       recogniser abandoned, which reads plausibly and is wrong in exactly the
       places the solver is about to reason over.
    2. A partial never displaces a final for the same turn. With
       `format_turns=false` on universal-3-5-pro there is one final per turn, so
       this costs nothing today; it is what stops a late or out-of-order partial
       from un-finishing a committed turn if that ever changes.
    """

    __slots__ = ("_inner",)

    def __init__(self, max_words: int = MAX_WORDS,
                 max_span_ms: int = MAX_SPAN_MS) -> None:
        self._inner = _Tape(max_span_ms=max_span_ms, max_words=max_words)

    @property
    def max_words(self) -> int:
        return self._inner.max_words

    @property
    def max_span_ms(self) -> int:
        return self._inner.max_span_ms

    def push(self, turn: Turn) -> bool:
        """Add or replace a turn. Returns False if the frame was rejected."""
        return self._inner.ingest(turn)

    # -- reading -------------------------------------------------------------
    @property
    def turns(self) -> list[Turn]:
        return [
            {
                "type": "Turn",
                "turn_order": t.turn_order,
                "turn_is_formatted": t.turn_is_formatted,
                "end_of_turn": t.end_of_turn,
                "transcript": t.transcript,
                "end_of_turn_confidence": t.end_of_turn_confidence,
                "words": [
                    {"text": w.text, "start": w.start, "end": w.end,
                     "confidence": w.confidence, "word_is_final": w.is_final}
                    for w in t.words
                ],
            }
            for t in self._inner.turns
        ]

    def words(self, finals_only: bool = False) -> list[Word]:
        """The flattened word timeline. A turn boundary is never a parse
        boundary (3.4) -- this is the structure that makes that true.

        Ordered by `(turn_order, position in turn)`, which is the order the
        recogniser committed to, and not by `start`.
        """
        finals = {t.turn_order for t in self._inner.turns if t.end_of_turn}
        return [
            {"text": w.text, "start": w.start, "end": w.end,
             "confidence": w.confidence, "word_is_final": w.is_final}
            for w in self._inner.words
            if not finals_only or w.turn_order in finals
        ]

    def text(self, finals_only: bool = False) -> str:
        return " ".join(w["text"] for w in self.words(finals_only))

    def confidences(self, finals_only: bool = False) -> list[float]:
        return [w["confidence"] for w in self.words(finals_only)]

    def clear(self) -> None:
        """Session end. The tape is never persisted (3.9)."""
        self._inner.clear()

    def __len__(self) -> int:
        return len(self._inner.turns)


__all__ = ["MAX_SPAN_MS", "MAX_WORDS", "Tape"]
