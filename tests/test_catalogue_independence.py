"""ARCH 3.9a: the catalogue may not be the answer key and the bias at once.

A `catalogue` capture has no check digit. The only thing that lets it commit is
that the catalogue holds a row within edit distance 2, uniquely -- and that is
evidence only while the recogniser has never been shown the catalogue. Bias the
recogniser toward the rows and it revises its own partials onto them: a part
number nobody read out arrives spelled exactly like a row, matches at distance
0, and `_commit_catalogue` writes it with `silent=True, questions_asked=0`
because every guard downstream is intact and looking at a perfect match.

The failure is not hypothetical. It is publicly documented on the same
recogniser by another entry in this hackathon (`sadishihab/claim-intake-agent`,
"How the validator was made powerless"): three sessions with the answer key in
`keyterms`, all three writing a real policy number belonging to someone else.

Section A locks the filter. Section B locks the two call sites that used to
carry the rows -- the mutation arm: re-add `format_tokens={"catalogue":
catalogue.skus}` in `main.py` and B fails.

Runs under pytest or as a script.
"""

from __future__ import annotations

import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.pipeline.detector import State, keyterms
from server.pipeline.runner import independent_keyterms
from server.readback.catalogue import CatalogueIndex

PARTS = [("BX-4471-A", "Bearing housing"), ("CR-2032", "Coin cell"),
         ("MSK-9000", "Mast bracket")]
INDEX = CatalogueIndex(PARTS)


# --------------------------------------------------------------- section A ---

def test_vouches_for_is_spelling_blind() -> None:
    """The check is on the normalisation, so no spelling sneaks a row past."""
    for spelling in ("BX-4471-A", "bx4471a", "BX 4471 A", "bx-4471-a"):
        assert INDEX.vouches_for(spelling), spelling
    assert not INDEX.vouches_for("BX-4471-B")   # a real neighbour, not a row
    assert not INDEX.vouches_for("")


def test_format_tokens_lose_the_rows() -> None:
    tokens, vocab = independent_keyterms(
        INDEX, {"catalogue": INDEX.skus}, ())
    assert tokens is not None
    assert tuple(tokens["catalogue"]) == ()
    assert vocab == ()


def test_vocabulary_loses_the_rows_and_keeps_everything_else() -> None:
    """ARCH 3.9's vocabulary rides along in EVERY state, so the same hole is
    open through it -- and it is documented to hold part numbers. The owner
    prefixes and customer names in the same list are not what is being
    validated, so they stay: this filter is narrow on purpose."""
    vocab_in = ("MSKU", "Kowalski", "bx4471a", "CR-2032", "Deutsche Bahn")
    _, vocab = independent_keyterms(INDEX, None, vocab_in)
    assert vocab == ("MSKU", "Kowalski", "Deutsche Bahn")


def test_no_catalogue_passes_everything_through() -> None:
    """With nothing vouching for a commit there is nothing to be circular
    about, and the bias is free to help."""
    tokens_in = {"catalogue": ("BX-4471-A",)}
    tokens, vocab = independent_keyterms(None, tokens_in, ("bx4471a",))
    assert tokens is tokens_in
    assert vocab == ("bx4471a",)


def test_stand_in_catalogue_without_the_method_is_not_a_crash() -> None:
    """Tests pass sentinels as the catalogue. A filter that raised on one would
    turn a missing method into a dead session."""
    tokens, vocab = independent_keyterms(object(), {"catalogue": ("X",)}, ("Y",))
    assert tokens == {"catalogue": ("X",)}
    assert vocab == ("Y",)


def test_armed_keyterm_list_carries_no_row() -> None:
    """End of the path the filter protects: what the CONNECT/UpdateConfiguration
    frame would actually carry while ARMED on `catalogue`."""
    tokens, vocab = independent_keyterms(INDEX, {"catalogue": INDEX.skus}, ())
    pushed = keyterms(State.ARMED, "catalogue", tokens, vocab)
    assert pushed, "the state's own terms must survive -- NATO, digits"
    for row in INDEX.skus:
        assert row not in pushed
        assert row.replace("-", "") not in pushed


# --------------------------------------------------------------- section B ---

MAIN_PATH = Path(__file__).resolve().parents[1] / "server" / "main.py"


def _code_only(path: Path) -> str:
    """The file with its comments removed, so that the arm reads what runs and
    not what a comment says about it -- the comment at the call site quotes the
    very expression this test forbids."""
    with tokenize.open(path) as fh:
        return "".join(
            "" if tok.type in (tokenize.COMMENT, tokenize.NL) else tok.string + "\n"
            for tok in tokenize.generate_tokens(fh.readline))


def test_main_never_pushes_the_catalogue_at_the_recogniser() -> None:
    """The mutation arm. `catalogue.skus` reaching a keyterm list is the bug;
    this fails the moment either session builder starts carrying it again."""
    code = _code_only(MAIN_PATH)
    assert "skus" not in code, (
        "server/main.py names catalogue.skus in code again -- the rows belong "
        "to display and the reference screen, never to a session's bias list")
    assert "format_tokens" not in code, (
        "a session builder is setting format_tokens again -- if that is "
        "deliberate, it must not be able to carry catalogue rows")
