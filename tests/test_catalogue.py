"""ARCH 3.9: the catalogue as the constraint for part numbers with no checksum.

Runs under pytest or as a script.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.readback.catalogue import (
    MAX_DISTANCE,
    CatalogueIndex,
    edit_distance,
    normalise,
    signature,
)

PARTS = [
    ("BX-4471-A", "Bearing housing"),
    ("BX-4471-B", "Bearing housing, flanged"),
    ("CR-2032", "Coin cell"),
    ("MSK-9000", "Mast bracket"),
]


def test_normalise_and_signature_ignore_case_and_punctuation() -> None:
    assert normalise("bx-4471-a") == "BX4471A"
    assert signature("BX-4471-A") == signature("bx4471a")
    # B, D, E, P, T, V, Z and 3 rhyme: a mishear among them is an identity here.
    assert signature("BX4471A") == signature("DX4471A") == signature("PX4471A")
    # Digits that rhyme with letters collapse too (5/9 with I/Y; 8 with A/H/J/K).
    assert signature("CR5") == signature("CR9")
    assert signature("MSK8") == signature("MSKA")


def test_edit_distance_gives_up_past_the_cap() -> None:
    assert edit_distance("BX4471A", "BX4471A") == 0
    assert edit_distance("BX4471A", "DX4471A") == 1
    assert edit_distance("BX4471A", "BX4471") == 1
    assert edit_distance("BX4471A", "DX4472A") == 2
    assert edit_distance("BX4471A", "CR2032") == MAX_DISTANCE + 1


def test_an_exact_part_matches_at_distance_zero_however_it_was_spelled() -> None:
    idx = CatalogueIndex(PARTS)
    assert len(idx) == 4
    m = idx.match("bx4471a")
    assert m is not None and m.sku == "BX-4471-A" and m.distance == 0
    assert idx.match("BX-4471-A") is not None


def test_one_mishear_is_corrected_when_only_one_row_is_that_close() -> None:
    idx = CatalogueIndex(PARTS)
    m = idx.match("CR2O32")            # O for 0, the classic
    assert m is not None and m.sku == "CR-2032" and m.distance == 1
    m = idx.match("MSK900")            # a dropped character
    assert m is not None and m.sku == "MSK-9000" and m.distance == 1


def test_two_rows_equally_close_is_not_a_match() -> None:
    """The constraint cannot choose between BX-4471-A and BX-4471-B for a
    run that dropped its last character; neither may the agent."""
    idx = CatalogueIndex(PARTS)
    assert idx.match("BX4471") is None
    # But a run that names the last character is unambiguous again.
    assert idx.match("BX4471B").sku == "BX-4471-B"  # type: ignore[union-attr]


def test_too_far_is_nothing() -> None:
    idx = CatalogueIndex(PARTS)
    assert idx.match("ZZZ9999") is None
    assert idx.match("") is None
    assert idx.match("---") is None


def test_the_index_dedupes_by_normalised_sku_and_exposes_skus_for_keyterms() -> None:
    idx = CatalogueIndex([("BX-4471-A", "one"), ("bx4471a", "same part"), ("", "blank")])
    assert len(idx) == 1
    assert idx.skus == ("BX-4471-A",)


TESTS = [
    test_normalise_and_signature_ignore_case_and_punctuation,
    test_edit_distance_gives_up_past_the_cap,
    test_an_exact_part_matches_at_distance_zero_however_it_was_spelled,
    test_one_mishear_is_corrected_when_only_one_row_is_that_close,
    test_two_rows_equally_close_is_not_a_match,
    test_too_far_is_nothing,
    test_the_index_dedupes_by_normalised_sku_and_exposes_skus_for_keyterms,
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
