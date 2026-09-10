"""Solver-level bench of the risk named in the field study: does a single
check-digit repair ever silently write a WRONG number when the true error was
a transposition, a second substitution, or a checksum-blind substitution?

Offline, synthetic, deterministic (seeded). Not a live-STT measurement: the
corruptions are drawn from the solver's own confusion table, which is the
best available model of what a recogniser mishears. Reports, per corruption
kind and confidence regime:
  silent_ok     ACCEPT and top == truth          (the product working)
  silent_wrong  ACCEPT and top != truth          (the failure the product must not have)
  not_silent    anything else (asks / hands over / no candidate)
and, for the flat regime, how many silent_wrong the BLOCK-regime guard stops.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.pipeline import decider as dec
from server.readback.solver import ISO, W, decide

random.seed(7)
N = 400
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"

# Confusable substitutions, from the solver's own table, per character class.
conf_pairs = sorted(W.items(), key=lambda kv: -kv[1])
sub_for: dict[str, list[str]] = {}
for (a, b), w in conf_pairs:
    if w >= 0.3:
        sub_for.setdefault(a, []).append(b)


def valid_iso() -> str:
    while True:
        base = "".join(random.choice(LETTERS) for _ in range(3)) + "U" + \
               "".join(random.choice(DIGITS) for _ in range(6))
        for d in DIGITS:
            if ISO.ok(base + d):
                return base + d


def substitute(v: str, pos: int) -> str | None:
    alpha = ISO.A(pos)
    opts = [c for c in sub_for.get(v[pos], []) if c in alpha and c != v[pos]]
    if not opts:
        opts = [c for c in alpha if c != v[pos]]
    if not opts:
        return None
    return v[:pos] + random.choice(opts) + v[pos + 1:]


def transpose(v: str) -> str | None:
    cands = [i for i in range(len(v) - 1)
             if v[i] != v[i + 1] and v[i] in ISO.A(i + 1) and v[i + 1] in ISO.A(i)]
    if not cands:
        return None
    i = random.choice(cands)
    return v[:i] + v[i + 1] + v[i] + v[i + 2:]


def double(v: str) -> str | None:
    i, j = random.sample(range(len(v)), 2)
    a = substitute(v, i)
    return substitute(a, j) if a else None


def moment(regime: str, checksum_ok: bool) -> dec.Moment:
    return dec.Moment(now_ms=9000, last_word_end_ms=7100, silence_ms=1900,
                      turn_ended=True, length_complete=True, trailing_characters=0,
                      second_signal="carrier", required=True,
                      checksum_valid_as_heard=checksum_ok, regime=regime)


def run(kind: str, corrupt, regime: str) -> Counter:
    c = Counter()
    for _ in range(N):
        truth = valid_iso()
        heard = corrupt(truth)
        if heard is None or heard == truth:
            continue
        if regime == "per_char":
            confs = [0.95] * 11
            for i in range(11):
                if heard[i] != truth[i]:
                    confs[i] = 0.45
        else:
            confs = [0.80] * 11
        r = decide(ISO, heard, confs)
        top = r.get("top")
        if ISO.ok(heard):
            c["heard_passes_check"] += 1
        if r["action"] == "ACCEPT":
            if top == truth:
                c["silent_ok"] += 1
            else:
                c["silent_wrong"] += 1
                if regime == "flat":
                    blocked = dec.silent_accept_blocked(ISO, heard, top, moment("block", ISO.ok(heard)))
                    if blocked:
                        c["silent_wrong_blocked_by_BLOCK"] += 1
        else:
            c["not_silent"] += 1
        c["n"] += 1
    return c


print(f"{'kind':16} {'regime':9} {'n':>4} {'silent_ok':>10} {'silent_wrong':>13} {'not_silent':>11} {'heard_passes':>13} {'blocked':>8}")
for kind, fn in (("substitution", lambda v: substitute(v, random.randrange(11))),
                 ("transposition", transpose),
                 ("double_subst", double)):
    for regime in ("per_char", "flat"):
        c = run(kind, fn, regime)
        n = c["n"] or 1
        print(f"{kind:16} {regime:9} {c['n']:4d} {c['silent_ok']:5d} {100*c['silent_ok']/n:4.0f}% "
              f"{c['silent_wrong']:5d} {100*c['silent_wrong']/n:5.1f}% "
              f"{c['not_silent']:5d} {100*c['not_silent']/n:4.0f}% "
              f"{c['heard_passes_check']:6d} {100*c['heard_passes_check']/n:5.1f}% "
              f"{c['silent_wrong_blocked_by_BLOCK']:7d}")
