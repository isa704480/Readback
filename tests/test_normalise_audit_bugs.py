"""Seven defects the adversarial bug hunt found in the reading path, each
pinned by the repro that demonstrated it.

Every one of these was silent: no exception, no flag, just a capture that was
shorter, longer or absent. They are grouped here rather than scattered because
they share a cause -- the tokeniser and the spelled-caps mask disagreed about
where a token ends, and a frame rule trusted a word that is also an ordinary
English one.

Runs under pytest or as a script.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.pipeline.detector import carrier_cue
from server.pipeline.tape import Tape
from server.readback.normalise import pass1, tokenise


def read(text: str) -> str:
    cells, _notes = pass1(text)
    return "".join(max(cell, key=lambda x: x[1])[0] for cell in cells)


# ------------------------------------------------- the disambiguator frame --
def test_the_frame_requires_its_two_halves_to_agree() -> None:
    """"B for Bravo" is one character said twice. "four for five" is three
    tokens that happen to sit in that order, and the frame used to swallow all
    three and invent an F -- two characters gone from the middle of a code."""
    assert read("b for bravo") == "B"
    assert read("s as in sugar") == "S"
    assert read("m for mike") == "M"
    # "for" is a documented homophone of "four", so three tokens read as three
    # characters. What matters is that no character is invented and none lost.
    assert read("four for five") == "445"
    assert read("nine for seven") == "947"


# ------------------------------------------------------------ punctuation --
def test_a_welded_code_survives_any_sentence_ending() -> None:
    """The formatter attaches whatever ended the sentence. Only "." was being
    turned into a separator, so a question or an exclamation left the token
    unsplittable and the whole identifier normalised to NOTHING."""
    for ending in (".", "?", "!", ";", ",", ")", '"', ""):
        text = f"Container number MSKU4158005{ending}"
        assert read(text) == "MSKU4158005", (ending, read(text))


def test_a_hyphenated_code_keeps_its_letters() -> None:
    """The mask ran before hyphens became separators, so "MSKU-4158005" was one
    token with no digit-bearing neighbour; the letters were never marked and
    the capture lost its prefix."""
    assert read("Container number MSKU-4158005") == "MSKU4158005"
    assert read("Container number MSKU 4158005") == "MSKU4158005"
    assert read("account number GB82-WEST-1234-5698-7654-32") == "GB82WEST12345698765432"


# ------------------------------------------------------------- the folds --
def test_double_u_folds_only_on_a_whole_token() -> None:
    """As a substring replace, "double u" matched inside "double uniform" and
    swallowed both the doubling and the U."""
    assert tokenise("double uniform") == ["double", "uniform"]
    assert tokenise("double u") == ["doubleu"]
    assert tokenise("double you") == ["doubleu"]
    assert tokenise("x ray") == ["xray"]
    assert tokenise("x rayed") == ["x", "rayed"]


# ------------------------------------------------- the carrier is a word --
def test_a_format_name_beside_the_digits_is_a_carrier_not_spelled_letters() -> None:
    """A lone all-caps token that IS a format's name names the format; a caps
    RUN of two or more is a spelled prefix. Dissolving "IBAN" deleted the
    carrier phrase from the sentence and added four characters to the run."""
    assert carrier_cue("IBAN GB82WEST12345698765432") == ("iban", "iban")
    assert carrier_cue("VIN 1HGCM82633A004352") == ("vin", "vin")
    assert tokenise("IBAN GB82WEST12345698765432")[0] == "iban"
    assert tokenise("NHS 9434765919")[0] == "nhs"

    # And the case the mask exists for is untouched: two caps tokens beside the
    # digits are a spelled prefix, so "SKU" there is not the catalogue carrier.
    assert carrier_cue("Container number RM SKU 4158005") == ("container number", "iso6346")
    assert tokenise("Container number RM SKU 4158005")[2:6] == ["r", "m", "s", "k"]
    # A spoken carrier away from the digits still names its format.
    assert carrier_cue("the SKU is 4158005") == ("sku", "catalogue")
    # A caps block that is not a format name is still spelled.
    assert tokenise("PO 12345")[:2] == ["p", "o"]


# ------------------------------------------------------------ hesitation --
def test_a_hesitation_inside_a_code_adds_no_character() -> None:
    """The detector calls "eh" a filler; the normaliser called it the letter A,
    so a hesitation in the middle of a code inserted a character."""
    assert read("mike eh sierra") == "MS"
    assert read("mike sierra") == "MS"
    # The real letter-name readings are untouched.
    assert read("ay") == "A"
    assert read("aye") == "A"


# ------------------------------------------------------------- the tape --
def _frame(order: int, words: list[tuple[str, int, int]], final: bool = True) -> dict:
    return {
        "type": "Turn", "turn_order": order, "turn_is_formatted": False,
        "end_of_turn": final, "transcript": " ".join(w[0] for w in words),
        "end_of_turn_confidence": 0.9,
        "words": [{"text": t, "start": s, "end": e, "confidence": 0.9,
                   "word_is_final": final} for t, s, e in words],
    }


def test_a_long_turn_is_not_evicted_for_having_started_long_ago() -> None:
    """Staleness was measured from the tape's FIRST word, so a turn that opened
    46 s ago and whose closing word arrived a second ago was dropped whole --
    and a caller who pauses inside a long code is exactly that turn."""
    tape = Tape()
    tape.ingest(_frame(0, [("container", 0, 500), ("number", 1000, 1500),
                           ("mike", 47000, 47400), ("sierra", 48000, 48400)]))
    tape.ingest(_frame(1, [("kilo", 49000, 49400)], final=False))
    kept = [w.text for w in tape.words]
    assert "sierra" in kept and "mike" in kept, kept
    assert "kilo" in kept


def test_a_genuinely_stale_turn_is_still_dropped() -> None:
    tape = Tape()
    tape.ingest(_frame(0, [("old", 0, 400)]))
    tape.ingest(_frame(1, [("new", 60000, 60400)], final=False))
    assert [w.text for w in tape.words] == ["new"]


TESTS = [
    test_the_frame_requires_its_two_halves_to_agree,
    test_a_welded_code_survives_any_sentence_ending,
    test_a_hyphenated_code_keeps_its_letters,
    test_double_u_folds_only_on_a_whole_token,
    test_a_format_name_beside_the_digits_is_a_carrier_not_spelled_letters,
    test_a_hesitation_inside_a_code_adds_no_character,
    test_a_long_turn_is_not_evicted_for_having_started_long_ago,
    test_a_genuinely_stale_turn_is_still_dropped,
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
