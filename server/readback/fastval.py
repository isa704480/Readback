# fastval.py -- O(1)-update validators for ISO 6346 and IBAN, built as
# per-position contribution tables over a modular sum.  Verified against the
# reference implementations in val.py.
# The port left a `sys.path.insert` pointing at the builder's scratchpad here.
# Removed: every import in this module is package-relative, so the line was
# dead, and a developer's absolute temp path on sys.path inside shipped server
# code shadows any module in it -- that directory holds probe.py, smoke.py and
# demo.py. Only the bench harness in arity.py's __main__ ever needed it, and it
# is scoped to that block now.
from .validators import iso_ok, iban_ok, ISO_LET, iso_val

D = '0123456789'
L = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

# ---------------------------------------------------------------- ISO 6346 --
# owner(3 letters) + category(U/J/Z) + serial(6 digits) + check(1 digit)
# sum_{i<10} value(c_i) * 2^i  ==  R (mod 11);  valid iff R != 10 and R == c_10.
# The STRICT reading (R==10 is unassignable) is used here; val.py's iso_ok uses
# the lenient R%10 fold, which is measurably weaker -- quantified in the run.
ISO_ALPHA = [L, L, L, 'UJZ', D, D, D, D, D, D, D]

class ISO:
    name   = "ISO6346"
    length = 11
    mod    = 11
    alpha  = ISO_ALPHA
    # contrib[i][ch] -> residue contribution mod 11 (positions 0..9)
    contrib = [{ch: (iso_val(ch) * (2 ** i)) % 11 for ch in (ISO_ALPHA[i])} for i in range(10)]

    @staticmethod
    def residual(s):
        return sum(ISO.contrib[i][s[i]] for i in range(10)) % 11

    @staticmethod
    def ok(s):
        if len(s) != 11: return False
        for i, ch in enumerate(s):
            if ch not in ISO_ALPHA[i]: return False
        r = ISO.residual(s)
        return r != 10 and r == int(s[10])

    @staticmethod
    def ok_lenient(s):
        if len(s) != 11: return False
        for i, ch in enumerate(s):
            if ch not in ISO_ALPHA[i]: return False
        return ISO.residual(s) % 10 == int(s[10])


# ------------------------------------------------------------------- IBAN ----
# GB: GB kk BBBB SSSSSS AAAAAAAA  ->  2 letters, 2 digits, 4 letters, 14 digits
IBAN_GB_PATTERN = "LL" + "DD" + "LLLL" + "D" * 14
IBAN_GB_ALPHA   = [L if p == 'L' else D for p in IBAN_GB_PATTERN]

def _build_iban(pattern, alphas):
    """rearranged = s[4:] + s[:4]; letters expand to 2 digits; value mod 97 == 1."""
    order = list(range(4, len(pattern))) + [0, 1, 2, 3]
    # how many output digits each source position produces
    outlen = [2 if pattern[i] == 'L' else 1 for i in range(len(pattern))]
    N = sum(outlen)
    # weight of output digit index j (leftmost = most significant)
    wj = [pow(10, N - 1 - j, 97) for j in range(N)]
    start = {}
    j = 0
    for i in order:
        start[i] = j
        j += outlen[i]
    contrib = []
    for i in range(len(pattern)):
        d = {}
        j0 = start[i]
        for ch in alphas[i]:
            if ch.isalpha():
                v = ord(ch) - 55                     # A=10 .. Z=35
                d[ch] = ((v // 10) * wj[j0] + (v % 10) * wj[j0 + 1]) % 97
            else:
                d[ch] = (int(ch) * wj[j0]) % 97
        contrib.append(d)
    return contrib

class IBANGB:
    name    = "IBAN-GB"
    length  = 22
    mod     = 97
    alpha   = IBAN_GB_ALPHA
    contrib = _build_iban(IBAN_GB_PATTERN, IBAN_GB_ALPHA)

    @staticmethod
    def residual(s):
        return sum(IBANGB.contrib[i][s[i]] for i in range(22)) % 97

    @staticmethod
    def ok(s):
        if len(s) != 22: return False
        for i, ch in enumerate(s):
            if ch not in IBAN_GB_ALPHA[i]: return False
        return IBANGB.residual(s) == 1


if __name__ == "__main__":
    import random
    random.seed(1)
    print("=== fastval agreement with reference validators ===")

    # IBAN: known-good
    good = "GB82WEST12345698765432"
    print(f"  IBANGB.ok({good}) = {IBANGB.ok(good)}   reference iban_ok = {iban_ok(good)}")

    # exhaustive-ish agreement test on random GB strings + single edits of good ones
    dis = 0; n = 0
    pool = []
    for _ in range(300):
        s = "GB" + "".join(random.choice(D) for _ in range(2)) \
                 + "".join(random.choice(L) for _ in range(4)) \
                 + "".join(random.choice(D) for _ in range(14))
        pool.append(s)
    # add every single edit of the known-good IBAN
    for i in range(22):
        for c in IBAN_GB_ALPHA[i]:
            pool.append(good[:i] + c + good[i+1:])
    for s in pool:
        n += 1
        if IBANGB.ok(s) != iban_ok(s):
            dis += 1
            if dis < 4: print("   MISMATCH", s, IBANGB.ok(s), iban_ok(s))
    print(f"  IBAN: {n} strings tested, {dis} disagreements with val.iban_ok")

    # ISO: strict vs reference lenient
    pool = []
    for _ in range(500):
        s = "".join(random.choice(L) for _ in range(3)) + random.choice("UJZ") \
            + "".join(random.choice(D) for _ in range(7))
        pool.append(s)
    for i in range(11):
        for c in ISO_ALPHA[i]:
            pool.append("CSQU3054383"[:i] + c + "CSQU3054383"[i+1:])
    dl = sum(1 for s in pool if ISO.ok_lenient(s) != iso_ok(s))
    print(f"  ISO lenient vs val.iso_ok: {len(pool)} strings, {dl} disagreements")
    ds = sum(1 for s in pool if ISO.ok(s) != iso_ok(s))
    print(f"  ISO STRICT vs val.iso_ok : {len(pool)} strings, {ds} disagreements"
          f"  (expected>0: strict rejects remainder-10)")
    print(f"  ISO.ok(CSQU3054383) = {ISO.ok('CSQU3054383')}  (known-good, must be True)")
    print(f"  ISO.ok(MSKU4158005) = {ISO.ok('MSKU4158005')}")

    # how often does strict differ from lenient over the valid space?
    tot = 0; ten = 0
    for _ in range(20000):
        s10 = "".join(random.choice(L) for _ in range(3)) + random.choice("UJZ") \
              + "".join(random.choice(D) for _ in range(6))
        r = sum(ISO.contrib[i][s10[i]] for i in range(10)) % 11
        tot += 1
        if r == 10: ten += 1
    print(f"  fraction of ISO bodies with remainder 10 (unassignable): {ten/tot:.4f}")
