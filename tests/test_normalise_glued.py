"""The recogniser welds a spoken identifier into one token. The normaliser must
read it anyway.

Pinned against the two transcripts universal-3-5-pro actually returned on
2026-09-04 (experiments/day1/FINDINGS-day1.md section 9). Before tokenise()
split code-shaped tokens, the first normalised to ZERO cells and the second to
three -- no capture could commit from a live microphone at all, while every
fixture in tests/fixtures/ passed, because every fixture spells one word per
character and the live model does not.

Runs under pytest or as a script.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.readback.normalise import pass1, tokenise
from server.pipeline.detector import COMMIT_MIN_CUES, evaluate, readable_runs, shape_cue
from server.pipeline.tape import Word
from server.readback.solver import ISO, LUHN16, NHS


def _read(text: str) -> str:
    cells, _notes = pass1(text)
    return "".join(max(cell, key=lambda x: x[1])[0] for cell in cells)


# ------------------------------------------------- the two real transcripts --
def test_letter_name_spelling_welded_into_one_token_is_read() -> None:
    """Run 1: 'M S K U four one five ...' came back as 'RMSKU4158005.' with a
    single confidence. Twelve characters, one of them a spurious leading R that
    the shape cue's edit distance is there to absorb."""
    assert _read("Container number RMSKU4158005.") == "RMSKU4158005"


def test_nato_spelling_with_a_welded_digit_run_is_read() -> None:
    """Run 2: NATO words survived as words, the digits welded into '4158005'.
    kilo -> K, uniform -> U, then seven digits. The 'RMI KCR' wreckage is
    letters-only and is correctly left alone (it is not a code)."""
    assert _read("Container number RMI KCR kilo uniform 4158005.") == "KU4158005"


def test_the_ideal_nato_reading_is_unchanged() -> None:
    """The fixture shape -- one word per character -- must read exactly as it
    did before the split existed. The split may only add, never alter."""
    text = "container number mike sierra kilo uniform four one five eight zero zero five"
    assert _read(text) == "MSKU4158005"
    assert len(pass1(text)[0]) == ISO.length


# ------------------------------------------------- the rule is narrow --
def test_words_are_never_split() -> None:
    """A letters-only token is a word. Splitting 'container' into nine
    characters would be the worst possible regression, so it is asserted."""
    toks = tokenise("container number kilo uniform rotterdam sailing thursday")
    assert toks == ["container", "number", "kilo", "uniform", "rotterdam", "sailing", "thursday"]


def test_only_digit_bearing_runs_split() -> None:
    assert tokenise("rmsku4158005") == list("rmsku4158005")
    assert tokenise("4158005") == list("4158005")
    assert tokenise("ab12") == ["a", "b", "1", "2"]
    assert tokenise("msku") == ["msku"]          # letters only: left whole
    assert tokenise("x") == ["x"]
    assert tokenise("7") == ["7"]


def test_a_digit_run_no_longer_loses_everything_after_its_first_digit() -> None:
    """_one() returns only the first character of a digit string and says
    'caller should splice the rest'. tokenise() now splits before _one() ever
    sees it, so the whole run survives."""
    assert _read("4158005") == "4158005"
    assert _read("the invoice was 1500 euros") == "1500"


# ------------------------------------------------- it must not help a phone number --
def test_split_conversational_numbers_stay_short_of_every_format() -> None:
    """The split makes '1500' and 'AB12' visible to the detector as character
    runs where they were invisible before. That must not hand the shape cue a
    new way to fire: a price and a short reference are far shorter than any
    format this system knows, and the false-capture contract in
    tests/test_detector_falsepos.py is the end-to-end guard. This pins the
    arithmetic behind it."""
    for text, longest_allowed in (
        ("the invoice was 1500 euros, reference AB12 please", 4),
        ("delivery on the 14th of March 2026 at 0930", 4),
    ):
        toks = tokenise(text)
        # longest run of consecutive single-character tokens that carry a digit
        run = best = 0
        for t in toks:
            if len(t) == 1 and (t.isdigit() or t.isalpha()):
                run += 1
                best = max(best, run)
            else:
                run = 0
        assert best <= longest_allowed, (text, best)
        assert best < min(NHS.length, ISO.length, LUHN16.length)


# ------------------------------------------------- the detector must see it too --
def _word(text: str, conf: float, i: int) -> Word:
    return Word(text=text, start=i * 600, end=i * 600 + 500, confidence=conf,
                is_final=True, turn_order=0)


# The three words universal-3-5-pro returned for a TTS reading of
# "container number M S K U four one five eight zero zero five", with their
# confidences. One welded word for the whole identifier.
RUN1_WORDS = [_word("Container", 0.89, 0), _word("number", 0.80, 1),
              _word("RMSKU4158005.", 0.80, 2)]


def test_a_welded_identifier_forms_a_run_and_fires_the_shape_cue() -> None:
    """Before: _readable() asked _one() about the whole word, got None, the
    word never joined a run, and the shape cue could not fire on any live
    audio -- the session armed on its carrier and ended with zero captures.
    Now the word is a twelve-character run and the ISO window sits inside it
    at edit distance 0."""
    for armed in (False, True):
        runs = readable_runs(RUN1_WORDS, armed)
        assert [r.chars for r in runs] == ["RMSKU4158005"], (armed, runs)
        hit = shape_cue(RUN1_WORDS, armed)
        assert hit is not None and hit.fmt == "iso6346" and hit.distance == 0, (armed, hit)
        report = evaluate(RUN1_WORDS, armed)
        assert {c.value for c in report.cues} >= {"carrier", "shape"}, (armed, report)
        assert report.commit_n >= COMMIT_MIN_CUES, (armed, report)


def test_ordinary_words_still_do_not_form_runs() -> None:
    """The readability change must not make prose readable. The end-to-end
    guard is tests/test_detector_falsepos.py; this is the unit-level pin.

    A homophone -- "to" reads as 2 -- has always formed a one-character run
    on its own; that is the normaliser's business and predates the change.
    What must hold is that no WORD of prose became a multi-character run and
    that nothing here looks like a code to the shape cue."""
    words = [_word(w, 0.9, i) for i, w in enumerate(
        "the container sails thursday from rotterdam to felixstowe".split())]
    runs = readable_runs(words, True)
    assert all(len(r.chars) <= 1 for r in runs), runs
    assert shape_cue(words, True) is None


def test_the_mangled_nato_reading_is_read_as_far_as_it_goes() -> None:
    """Run 2, as the TTS voice was heard: 'Mike Sierra' wrecked, 'kilo
    uniform' intact, digits welded. Nine cells is the honest reading and
    nine is short of ISO's eleven, so the shape cue stays quiet. Pinned so
    that nobody 'fixes' it by loosening the format length -- the input is
    wrong, not the rule."""
    words = [_word("Container", .80, 0), _word("number", .67, 1), _word("RMI", .31, 2),
             _word("KCR", .51, 3), _word("kilo", .69, 4), _word("uniform", .98, 5),
             _word("4158005.", .95, 6)]
    runs = readable_runs(words, True)
    assert [r.chars for r in runs] == ["KU4158005"], runs
    assert shape_cue(words, True) is None


TESTS = [
    test_a_welded_identifier_forms_a_run_and_fires_the_shape_cue,
    test_ordinary_words_still_do_not_form_runs,
    test_the_mangled_nato_reading_is_read_as_far_as_it_goes,
    test_letter_name_spelling_welded_into_one_token_is_read,
    test_nato_spelling_with_a_welded_digit_run_is_read,
    test_the_ideal_nato_reading_is_unchanged,
    test_words_are_never_split,
    test_only_digit_bearing_runs_split,
    test_a_digit_run_no_longer_loses_everything_after_its_first_digit,
    test_split_conversational_numbers_stay_short_of_every_format,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
