"""A welded word is the BLOCK regime by construction, and the decider must
be told so per candidate.

universal-3-5-pro returns a spoken identifier as one formatted word with one
confidence (experiments/day1/FINDINGS-day1.md section 9). tokenise() splits
it into cells, and every cell inherits that one number. ARCH 3.7 names this
BLOCK: no per-position doubt, so no silent repair -- the decider may commit a
checksum-clean reading but must not change a character nobody can localise.

The session-wide RegimeDetector needs 40 words and a short live call never
gives it that many, so its answer is "unknown" -- which the decider treats as
per-character, the one regime where a silent repair is allowed. Left there,
a welded reading with a bad checksum would be silently edited by prior
alone: the 5% silently-wrong the regime detector exists to prevent, live.

align_run() knows how many cells each recogniser word produced. That is the
signal, and it needs no window of 40.

Runs under pytest or as a script.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.pipeline import decider as dec
from server.pipeline.detector import shape_cue
from server.pipeline.runner import (
    BLOCK_CELLS_PER_WORD,
    align_run,
    build_window,
    candidate_regime,
)
from server.pipeline.tape import Word
from server.readback.solver import ISO


def _word(text: str, conf: float, i: int) -> Word:
    return Word(text=text, start=i * 600, end=i * 600 + 500, confidence=conf,
                is_final=True, turn_order=0)


# The three words the live socket returned for a TTS reading of
# "container number M S K U four one five eight zero zero five".
WELDED = [_word("Container", 0.89, 0), _word("number", 0.80, 1),
          _word("RMSKU4158005.", 0.80, 2)]

# The same identifier the way every fixture in tests/fixtures/ spells it.
PER_CHAR = [_word("container", .9, 0), _word("number", .9, 1)] + [
    _word(w, c, i + 2) for i, (w, c) in enumerate([
        ("mike", .92), ("sierra", .88), ("kilo", .95), ("uniform", .91),
        ("four", .97), ("one", .93), ("five", .90), ("eight", .96),
        ("zero", .94), ("zero", .89), ("five", .95)])]


def test_a_welded_word_is_flagged_by_the_alignment() -> None:
    a = align_run(WELDED, [2])
    assert a.ok, a
    assert len(a.cells) == 12
    assert a.block is True
    assert len(set(a.confs)) == 1, "one number copied per cell -- the whole point"


def test_word_per_character_spelling_is_not() -> None:
    a = align_run(PER_CHAR, list(range(2, 13)))
    assert a.ok, a
    assert len(a.cells) == ISO.length
    assert a.block is False
    assert len(set(a.confs)) > 1, "per-position doubt survives"


def test_treble_is_below_the_threshold() -> None:
    """'treble four' is the most cells a per-character speaker gets from one
    word. Three. The threshold sits above it on purpose."""
    words = [_word("treble", .9, 0), _word("four", .9, 1)]
    a = align_run(words, [0, 1])
    assert a.ok and len(a.cells) == 3, a
    assert a.block is False
    assert BLOCK_CELLS_PER_WORD == 4


def test_the_window_carries_the_flag_into_the_regime() -> None:
    hit = shape_cue(WELDED, True)
    assert hit is not None and hit.fmt == "iso6346"
    window = build_window(WELDED, hit, True)
    assert window is not None and window.value == "MSKU4158005", window
    assert window.block_confidence is True
    assert candidate_regime(window, None) == "block"
    assert candidate_regime(window, "per_char") == "block", \
        "the alignment knows more about this candidate than the statistic does"

    hit = shape_cue(PER_CHAR, True)
    assert hit is not None
    window = build_window(PER_CHAR, hit, True)
    assert window is not None and window.block_confidence is False
    assert candidate_regime(window, None) == "unknown"
    assert candidate_regime(window, "flat") == "flat"


def _moment(regime: str, *, checksum_ok: bool) -> dec.Moment:
    return dec.Moment(now_ms=9000, last_word_end_ms=7100, silence_ms=1900,
                      turn_ended=True, length_complete=True, trailing_characters=0,
                      second_signal="carrier", required=True,
                      checksum_valid_as_heard=checksum_ok, regime=regime)


def test_block_forbids_the_silent_repair_that_unknown_would_allow() -> None:
    """Heard NSKU4158005 (bad checksum); the solver's top reading edits one
    letter to MSKU4158005. With the regime unknown the edit goes through
    silently. With the window flagged BLOCK it is refused, and the reason
    names the regime."""
    heard, top = "NSKU4158005", "MSKU4158005"
    assert not ISO.ok(heard) and ISO.ok(top)
    assert dec.silent_accept_blocked(ISO, heard, top, _moment("unknown", checksum_ok=False)) is None
    assert dec.silent_accept_blocked(ISO, heard, top, _moment("block", checksum_ok=False)) == "regime_block"


def test_block_still_commits_a_clean_reading_silently() -> None:
    """What BLOCK forbids is a repair, not a capture. The live run committed
    MSKU4158005 exactly like this."""
    clean = "MSKU4158005"
    assert dec.silent_accept_blocked(ISO, clean, clean, _moment("block", checksum_ok=True)) is None


TESTS = [
    test_a_welded_word_is_flagged_by_the_alignment,
    test_word_per_character_spelling_is_not,
    test_treble_is_below_the_threshold,
    test_the_window_carries_the_flag_into_the_regime,
    test_block_forbids_the_silent_repair_that_unknown_would_allow,
    test_block_still_commits_a_clean_reading_silently,
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
