# blindness.py -- STRUCTURAL (not Monte-Carlo) analysis:
# which confusions is each checksum mathematically incapable of detecting,
# and does that intersect the signature confusions of particular accents?
import sys
from collections import defaultdict
P = r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad"
sys.path.insert(0, P)
from val import ISO_LET, iso_val
from fastval import ISO, IBANGB, D, L
from accent import ACCENTS, TABLES, GENERIC

print("=" * 100)
print("A. ISO 6346 is a weighted sum mod 11.  Two characters are INDISTINGUISHABLE")
print("   to the check digit at the SAME position iff their ISO values are congruent mod 11.")
print("=" * 100)
cls = defaultdict(list)
for ch in L:
    cls[ISO_LET[ch] % 11].append(ch)
for ch in D:
    cls[int(ch) % 11].append(ch)
print("\n  residue | characters that collide (a substitution WITHIN a class is invisible)")
for r in sorted(cls):
    grp = cls[r]
    mark = "  <-- COLLISION" if len(grp) > 1 else ""
    print(f"     {r:>2}   | {' '.join(grp)}{mark}")

blind_pairs = set()
for r, grp in cls.items():
    for i in range(len(grp)):
        for j in range(i + 1, len(grp)):
            a, b = grp[i], grp[j]
            # only meaningful if both are legal at some common position
            blind_pairs.add(tuple(sorted((a, b))))
print(f"\n  total structurally-blind character pairs for ISO 6346: {len(blind_pairs)}")

print("\n" + "=" * 100)
print("B. Cross-reference: each accent's TOP confusions vs the ISO blind set.")
print("   'BLIND' = the ISO check digit can never detect this substitution.")
print("=" * 100)
for a in ACCENTS:
    T = TABLES[a]
    # signature = pairs where this accent is >=1.5x the American reference, weight >=0.3
    sig = []
    for (x, y), w in T.items():
        if x >= y: continue
        base = GENERIC.get((x, y), 0.0)
        if w >= 0.30 and (base < 1e-9 or w / base >= 1.5):
            sig.append((w, x, y))
    sig.sort(reverse=True)
    print(f"\n  {a:12s} {ACCENTS[a]['note']}")
    if not sig:
        print("      (reference accent -- no amplified pairs)")
    for w, x, y in sig[:6]:
        # is it legal in ISO at all?  letters at 0-3, digits at 4-10
        both_letters = x.isalpha() and y.isalpha()
        both_digits  = x.isdigit() and y.isdigit()
        if not (both_letters or both_digits):
            tag = "cross-type (slot typing kills it outright)"
        elif tuple(sorted((x, y))) in blind_pairs:
            tag = "*** BLIND to the ISO check digit ***"
        else:
            tag = "detectable"
        print(f"      {x}/{y}  w={w:.2f}   {tag}")

print("\n" + "=" * 100)
print("C. Same question for IBAN-GB (mod 97 over the decimal expansion).")
print("=" * 100)
# For IBAN, a substitution at position i is invisible iff contrib[i][x] == contrib[i][y].
blind_iban = defaultdict(set)
for i in range(22):
    inv = defaultdict(list)
    for ch, v in IBANGB.contrib[i].items():
        inv[v].append(ch)
    for v, grp in inv.items():
        if len(grp) > 1:
            for j in range(len(grp)):
                for k in range(j + 1, len(grp)):
                    blind_iban[i].add(tuple(sorted((grp[j], grp[k]))))
tot = sum(len(s) for s in blind_iban.values())
print(f"\n  positions with ANY blind pair: {sorted(blind_iban)}")
print(f"  total (position, blind-pair) combinations: {tot}")
for i in sorted(blind_iban):
    print(f"    pos {i:>2}: {sorted(blind_iban[i])}")

print("\n" + "=" * 100)
print("D. How much of each accent's total error mass is structurally undetectable")
print("   by ISO 6346?  (weighted by where the character can legally appear)")
print("=" * 100)
from accent import gen_dist
print(f"\n  {'accent':<13}{'blind mass':>12}{'cross-type':>12}{'detectable':>12}")
for a in ACCENTS:
    T = TABLES[a]
    blind = xt = det = 0.0
    for pos in range(11):
        A = ISO.alpha[pos]
        for t in A:
            d = gen_dist(T, t)
            for x, v in d.items():
                if x not in A:
                    xt += v                       # illegal char -> slot typing catches it
                elif tuple(sorted((t, x))) in blind_pairs:
                    blind += v
                else:
                    det += v
    s = blind + xt + det
    print(f"  {a:<13}{blind/s:12.1%}{xt/s:12.1%}{det/s:12.1%}")
