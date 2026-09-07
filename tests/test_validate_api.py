"""POST /api/validate -- the formats reference's "try one".

Stateless, unauthenticated, and the same arithmetic the solver runs on every
capture: the page must never call a string valid that the pipeline would
refuse. Every "valid" example below was verified against the solver before it
was written down (they are the ones the reference screen shows).

Runs under pytest or as a script.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from server.main import VALIDATE_MAX_CHARS, app

client = TestClient(app, raise_server_exceptions=False)

VALID = {
    "iso6346": "MSKU4158005",
    "iban": "GB82WEST12345698765432",
    "vin": "1HGCM82633A004352",
    "nhs": "9434765919",
    "luhn": "4111111111111111",
}
CHECK_AT = {"iso6346": [10], "iban": [2, 3], "vin": [8], "nhs": [9], "luhn": [15]}


def _post(fmt: str, value: str) -> object:
    return client.post("/api/validate", json={"format": fmt, "value": value})


def test_every_reference_example_is_valid() -> None:
    for fmt, value in VALID.items():
        body = _post(fmt, value).json()
        assert body["valid"] is True, (fmt, body)
        assert body["length_ok"] and body["checksum_ok"] is True
        assert body["expected_length"] == len(value)
        assert body["check_positions"] == CHECK_AT[fmt]
        assert [p["check"] for p in body["positions"]] == \
            [i in CHECK_AT[fmt] for i in range(len(value))]
        assert all(p["allowed"] for p in body["positions"])


def test_a_wrong_check_digit_fails_the_check_and_nothing_else() -> None:
    """Every position still holds a legal character; only the arithmetic says
    no. That is the difference the page has to draw."""
    body = _post("iso6346", "MSKU4158006").json()
    assert body["length_ok"] and all(p["allowed"] for p in body["positions"])
    assert body["checksum_ok"] is False and body["valid"] is False


def test_spaces_hyphens_and_case_are_normalised_first() -> None:
    body = _post("iban", "gb82 west 1234 5698 7654 32").json()
    assert body["normalised"] == "GB82WEST12345698765432"
    assert body["valid"] is True
    body = _post("iso6346", "msku-415800-5").json()
    assert body["valid"] is True


def test_the_wrong_length_says_so_and_does_not_guess_a_checksum() -> None:
    body = _post("nhs", "94347659").json()
    assert body["length_ok"] is False
    assert body["expected_length"] == 10
    assert body["checksum_ok"] is None
    assert body["valid"] is False
    assert len(body["positions"]) == 8


def test_a_character_the_position_cannot_hold_is_named_by_position() -> None:
    """ISO 6346: the fourth character is the category identifier, U, J or Z.
    'MSKA...' is the right length and the right count of letters, and still
    not a container number."""
    body = _post("iso6346", "MSKA4158005").json()
    assert body["length_ok"] is True
    bad = [p["index"] for p in body["positions"] if not p["allowed"]]
    assert bad == [3], body["positions"]
    assert body["checksum_ok"] is None and body["valid"] is False


def test_unknown_format_and_oversize_value_are_flat_400s() -> None:
    r = _post("passport", "X123")
    assert r.status_code == 400, r.text
    assert r.json().get("error") == "unknown_format" and "detail" not in r.json()
    r = _post("iso6346", "M" * (VALIDATE_MAX_CHARS + 1))
    assert r.status_code == 400
    assert r.json().get("error") == "value_too_long"


TESTS = [
    test_every_reference_example_is_valid,
    test_a_wrong_check_digit_fails_the_check_and_nothing_else,
    test_spaces_hyphens_and_case_are_normalised_first,
    test_the_wrong_length_says_so_and_does_not_guess_a_checksum,
    test_a_character_the_position_cannot_hold_is_named_by_position,
    test_unknown_format_and_oversize_value_are_flat_400s,
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
