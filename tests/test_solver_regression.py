"""Regression test for the fixed solver.

The one property that must never regress: **the agent must never write down a
wrong identifier without having said anything.** A wrong number the agent asked
about is a conversation; a wrong number it accepted in silence is the failure
the whole product exists to prevent, and it is invisible until a container ends
up in the wrong port.

`tests/bench/guardhole.py` measures how often an argmax-entropy implementation
falls into that hole. This file measures whether ours does — end to end, with
the question loop closed, against the fixed solver.

Run:  PYTHONPATH=. python tests/test_solver_regression.py
"""

from __future__ import annotations

import random
import sys

from server.readback.solver import (
    IBANGB,
    ISO,
    LUHN16,
    NHS,
    W,
    decide,
)

# Confusable pairs, drawn from the same table the solver uses, so the corruption
# model and the repair model share a world. Corrupting with pairs the solver has
# never seen is a different experiment (see tests/bench/blindness.py).
CONFUSABLE: dict[str, list[str]] = {}
for (true_c, heard_c), weight in W.items():
    if weight > 0.02 and true_c != heard_c:
        CONFUSABLE.setdefault(true_c, []).append(heard_c)


def valid_identifier(fmt, rng: random.Random) -> str:
    """Rejection-sample a checksum-valid identifier for this format."""
    for _ in range(4000):
        s = "".join(rng.choice(fmt.alpha(i)) for i in range(fmt.length))
        if fmt.ok(s):
            return s
    raise RuntimeError(f"could not sample a valid {fmt.name}")


def corrupt(fmt, truth: str, rng: random.Random, p: float) -> tuple[str, list[float]]:
    """Mishear each character with probability p, biased toward confusables.

    Confidence is emitted the way a recogniser would: lower where it was wrong,
    with enough overlap that confidence alone cannot separate the two.
    """
    heard, confs = [], []
    for i, c in enumerate(truth):
        options = [o for o in CONFUSABLE.get(c, []) if o in fmt.alpha(i)]
        if options and rng.random() < p:
            heard.append(rng.choice(options))
            confs.append(rng.uniform(0.35, 0.80))
        else:
            heard.append(c)
            confs.append(rng.uniform(0.55, 0.99))
    return "".join(heard), confs


def run_one(fmt, truth: str, heard: str, confs: list[float], budget_q: int = 2):
    """Close the loop: decide, ask, take a correct answer, decide again.

    Returns (final_string, questions_asked, handed_over).
    """
    h, cf = list(heard), list(confs)
    locked: set[int] = set()

    for _ in range(budget_q + 1):
        r = decide(fmt, "".join(h), cf, locked=frozenset(locked))
        action = r["action"]

        if action == "ACCEPT":
            return "".join(r["top"]), len(locked), False

        pos = r["ask_pos"]
        if pos is None or pos in locked:
            return None, len(locked), True          # nothing left to ask

        # The human answers that one position correctly and it is now fixed.
        h[pos] = truth[pos]
        cf[pos] = 0.99
        locked.add(pos)

    return None, len(locked), True                   # budget spent, hand over


def sweep(fmt, p: float, n: int, seed: int) -> dict:
    rng = random.Random(seed)
    stats = {"n": n, "correct": 0, "silent": 0, "silently_wrong": 0,
             "questions": 0, "handover": 0}

    for _ in range(n):
        truth = valid_identifier(fmt, rng)
        heard, confs = corrupt(fmt, truth, rng, p)
        result, asked, handed = run_one(fmt, truth, heard, confs)

        stats["questions"] += asked
        if handed:
            stats["handover"] += 1
            continue
        if result == truth:
            stats["correct"] += 1
        if asked == 0:
            stats["silent"] += 1
            if result != truth:
                stats["silently_wrong"] += 1

    return stats


# Loose on purpose: the confidence model in this file is synthetic. See the
# note at the assertion below.
MAX_SILENT_WRONG = 0.02


def main() -> int:
    cases = [(ISO, 0.05), (ISO, 0.10), (IBANGB, 0.05), (NHS, 0.05), (LUHN16, 0.05)]
    N = 600
    failures = []

    print(f"{'format':10} {'p':>5} {'correct':>8} {'silent':>7} "
          f"{'SILENT-WRONG':>13} {'q/id':>6} {'handover':>9}")
    print("-" * 64)

    for fmt, p in cases:
        s = sweep(fmt, p, N, seed=hash((fmt.name, p)) & 0xFFFF)
        acc = s["correct"] / s["n"]
        silent = s["silent"] / s["n"]
        wrong = s["silently_wrong"] / s["n"]
        qpi = s["questions"] / s["n"]
        ho = s["handover"] / s["n"]

        print(f"{fmt.name:10} {p:5.2f} {acc:8.3f} {silent:7.3f} "
              f"{wrong:13.4f} {qpi:6.2f} {ho:9.3f}")

        # The contract, and it is a BOUND, not zero.
        #
        # Zero is not reachable and it was wrong to assert it. ISO 6346 sums
        # value(c)*2^i mod 11, so a substitution inside a residue class produces
        # a string the validator calls perfectly valid. If the recogniser was
        # also confident, nothing in the system has any signal at all -- there is
        # no arithmetic left to catch it.
        #
        # What bounds it is that only 5.3% of acoustic confusion weight lands in
        # a blind class (see docs/FINDINGS.md). The heavy pairs O/0, C/Z, B/D,
        # M/N are all visible; the blind ones are B/V, K/A, F/P and are lighter.
        #
        # The threshold below is deliberately loose because the confidence model
        # here is INVENTED. The real number depends on how well AssemblyAI's
        # words[].confidence separates right from wrong characters, which is the
        # day-1 experiment and cannot be measured without a key. Tighten this
        # once that AUC is known.
        if wrong > MAX_SILENT_WRONG:
            failures.append(
                f"{fmt.name} p={p}: silently-wrong {wrong:.4f} exceeds the "
                f"{MAX_SILENT_WRONG} bound ({s['silently_wrong']}/{s['n']})"
            )

    print()
    if failures:
        for f in failures:
            print("  FAIL:", f)
        return 1

    print(f"  PASS — silent-wrong within the {MAX_SILENT_WRONG} bound on every format.")
    print("  NOTE: this bound is provisional until the day-1 confidence AUC is measured.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
