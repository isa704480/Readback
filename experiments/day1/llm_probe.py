"""Does the LLM Gateway actually close the false-capture hole?

server/llm.py exists to be ARCHITECTURE 3.8's second signal. The claim it has to
earn is narrow and testable: for a bare-digit run with no carrier phrase, where
shape and rhythm are useless because a phone number produces exactly the same
evidence a patient number does, can a model tell them apart well enough to gate
on at 0.8?

The rows that decide it are the ones marked HARD. A ten-digit window cut out of
an eleven-digit phone number IS an NHS number as far as every other signal in
this system is concerned -- same length, same alphabet, same dictation rhythm,
and it passes the mod-11 check one time in eleven. If the model cannot decline on
those, the second signal does not close the hole and docs/FINDINGS.md has to say
so rather than the README claiming a fix.

The rows marked EASY exist to catch the opposite failure: a model that declines
on everything scores perfectly on the hard rows and is worthless. Both directions
are measured, and a pass requires both.

Run:
    cd D:/My_apps/Readback
    PYTHONPATH=. python experiments/day1/llm_probe.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.llm import (  # noqa: E402
    SECOND_SIGNAL_MIN_CONFIDENCE,
    LLMUnavailable,
    identify_format,
)
from server.stream.live import _resolve_api_key  # noqa: E402

# (candidate, carrier, expected format, difficulty)
CASES: list[tuple[str, str | None, str, str]] = [
    # EASY -- a model that declines on everything must fail these.
    ("MSKU4158005", "container number", "iso6346", "EASY"),
    ("MSKU4158005", None, "iso6346", "EASY"),
    ("CSQU3054383", None, "iso6346", "EASY"),
    ("GB82WEST12345698765432", None, "iban", "EASY"),
    ("1HGBH41JXMN109186", None, "vin", "EASY"),
    ("4539578763621486", "card number", "luhn16", "EASY"),
    ("9434765919", "nhs number", "nhs", "EASY"),

    # HARD -- these are the false-capture population. Every one must come back
    # not_an_identifier, or below the 0.8 gate.
    ("07700900123", None, "not_an_identifier", "HARD"),      # UK mobile, 11 digits
    ("7700900123", None, "not_an_identifier", "HARD"),       # its 10-digit window = NHS shape
    ("02071234567", None, "not_an_identifier", "HARD"),       # London landline
    ("4471234567", None, "not_an_identifier", "HARD"),        # +44 form, 10 digits
    ("2026090114", None, "not_an_identifier", "HARD"),        # a date and a time run together
    ("1234567890", None, "not_an_identifier", "HARD"),        # counting
    ("1500250075", None, "not_an_identifier", "HARD"),        # prices read in a row

    # HARDEST -- a real NHS number and a phone number of the same length. The
    # model has to separate these two on content alone, which is the entire
    # question. Getting the first wrong is a missed capture; getting the second
    # wrong writes a phone number into a medical record.
    ("9434765919", None, "nhs", "HARDEST"),
    ("7911123456", None, "not_an_identifier", "HARDEST"),
]


# This account's LLM Gateway answers about twice before returning
#     429 "too many requests for this action"
# so an unpaced run measures the rate limiter, not the model. Slow and complete
# beats fast and empty: the point of the file is the HARD rows, and they are at
# the bottom of the list where an unpaced run never reaches them.
PACE_S = 12.0
RETRIES = 4
BACKOFF_S = 30.0


async def _with_retry(candidate: str, carrier: str | None, api_key: str):
    """Retry only on 429. Everything else is a real answer about the model."""
    last: LLMUnavailable | None = None
    for attempt in range(RETRIES):
        try:
            return await identify_format(candidate, api_key=api_key, carrier=carrier)
        except LLMUnavailable as exc:
            last = exc
            if "429" not in str(exc) and "too many requests" not in str(exc).lower():
                raise
            await asyncio.sleep(BACKOFF_S * (attempt + 1))
    raise last if last else LLMUnavailable("exhausted retries")


async def main() -> int:
    api_key = _resolve_api_key()
    if not api_key:
        print("No AssemblyAI key found in .env")
        return 1

    print(f"gate: assert only at confidence >= {SECOND_SIGNAL_MIN_CONFIDENCE}\n")
    print(f"  {'candidate':24} {'carrier':18} {'want':18} {'got':18} {'conf':>5}  {'ok':4} ms")
    print("  " + "-" * 96)

    rows = []
    for index, (candidate, carrier, want, difficulty) in enumerate(CASES):
        if index:
            await asyncio.sleep(PACE_S)
        start = time.perf_counter()
        try:
            result = await _with_retry(candidate, carrier, api_key)
        except LLMUnavailable as exc:
            # NOT a gate failure. The first run of this file counted these as
            # "got through the 0.8 gate" and printed a confident finding about a
            # component that had not been called once. An unreachable model and a
            # model that answered wrongly are different facts.
            print(f"  {candidate:24} UNAVAILABLE: {str(exc)[:110]}")
            rows.append((difficulty, None, None))
            continue
        ms = (time.perf_counter() - start) * 1000

        # The test is not "did it name the right format" -- it is "does the GATE
        # behave". A wrong format below 0.8 is harmless; a wrong format above it
        # is the failure this whole component exists to prevent.
        if want == "not_an_identifier":
            ok = not result.asserts
        else:
            ok = result.asserts and result.fmt == want

        rows.append((difficulty, ok, result))
        print(f"  {candidate:24} {str(carrier or '-'):18} {want:18} {result.fmt:18} "
              f"{result.confidence:5.2f}  {'ok' if ok else 'FAIL':4} {ms:.0f}")
        if not ok:
            print(f"      reason: {result.reason[:110]}")

    unreachable = sum(1 for _, ok, _ in rows if ok is None)
    print()
    for difficulty in ("EASY", "HARD", "HARDEST"):
        group = [ok for d, ok, _ in rows if d == difficulty]
        answered = [ok for ok in group if ok is not None]
        if not group:
            continue
        note = f"   ({len(group) - len(answered)} unreachable)" if len(answered) != len(group) else ""
        print(f"  {difficulty:8} {sum(1 for ok in answered if ok)}/{len(answered)} answered{note}")

    easy = [ok for d, ok, _ in rows if d == "EASY" and ok is not None]
    hard = [ok for d, ok, _ in rows if d in ("HARD", "HARDEST") and ok is not None]
    easy_ok = sum(1 for ok in easy if ok)
    hard_ok = sum(1 for ok in hard if ok)

    print("\n" + "=" * 78)
    print("Reading")
    print("=" * 78)
    if unreachable:
        print(f"  {unreachable} call(s) never reached a model. Those rows are not")
        print("  evidence in either direction and are excluded from every count.")
    if not easy and not hard:
        print("  Nothing was measured. There is no finding here, only an outage.")
        return 1
    if hard_ok == len(hard) and easy_ok == len(easy):
        print("  The second signal closes the hole AND still identifies real")
        print("  identifiers. It is safe to gate the bare-digit formats on it.")
    elif hard_ok < len(hard):
        print(f"  {len(hard) - hard_ok} false-capture case(s) got through the 0.8 gate.")
        print("  The second signal does NOT close the hole on its own. Whatever")
        print("  the detector fix does structurally has to stand without it.")
    else:
        print(f"  Declines too much: {len(easy) - easy_ok} real identifier(s) rejected.")
        print("  A gate that refuses genuine captures is a different failure, not")
        print("  a safe one -- it turns every capture into a question, which is")
        print("  the 'can you spell that' this product exists to delete.")

    latencies = [r for _, ok, r in rows if r is not None]
    print(f"\n  {len(latencies)} calls made. This sits on the latency path of a live")
    print("  call, so anything over ~1 s is a design problem, not a detail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
