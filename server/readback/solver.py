# rb.py -- Readback correction core. Real implementation, measured.
import math, random, time, statistics
# The port left a `sys.path.insert` pointing at the builder's scratchpad here.
# Removed: every import in this module is package-relative, so the line was
# dead, and a developer's absolute temp path on sys.path inside shipped server
# code shadows any module in it -- that directory holds probe.py, smoke.py and
# demo.py. Only the bench harness in arity.py's __main__ ever needed it, and it
# is scoped to that block now.
from .validators import *   # iso_ok iso_cd iso_val ISO_LET vin_ok VIN_ALPHA VT VW nhs_ok luhn_ok iban_ok L D

# ---------------------------------------------------------------- confusion --
_C = [
 ("B","D",.75,"s"),("D","G",.60,"s"),("P","T",.60,"s"),("B","G",.55,"s"),("C","Z",.80,"s"),
 ("V","E",.60,"f"),("B","V",.45,"s"),("V","Z",.45,"s"),("D","T",.42,"s"),("B","P",.40,"s"),
 ("C","E",.45,"f"),("Z","E",.45,"f"),("B","E",.40,"f"),("D","E",.40,"f"),("G","E",.40,"f"),
 ("P","E",.35,"f"),("T","E",.35,"f"),("P","D",.35,"s"),("V","D",.35,"s"),("T","B",.32,"s"),
 ("T","C",.30,"s"),("T","G",.30,"s"),("G","Z",.30,"s"),("D","Z",.30,"s"),("G","P",.28,"s"),
 ("V","P",.25,"s"),("C","P",.25,"s"),("G","J",.25,"s"),("C","D",.22,"s"),("V","T",.22,"s"),
 ("3","T",.35,"s"),("3","E",.35,"f"),("3","F",.30,"s"),("3","C",.25,"s"),("3","D",.20,"s"),
 ("3","V",.20,"s"),("3","B",.15,"s"),
 ("A","8",.65,"r"),("H","8",.60,"s"),("A","H",.50,"s"),("J","K",.45,"s"),("A","J",.35,"r"),
 ("A","K",.30,"r"),("H","J",.28,"s"),("H","K",.28,"s"),("K","8",.25,"s"),("J","8",.25,"s"),
 ("K","Q",.25,"s"),("A","I",.15,"s"),("8","I",.12,"s"),("A","R",.12,"s"),
 ("M","N",.72,"s"),("S","F",.55,"s"),("S","X",.52,"s"),("L","N",.42,"s"),("F","X",.32,"s"),
 ("L","M",.28,"s"),("F","P",.30,"s"),("N","X",.15,"s"),("S","L",.15,"s"),("F","L",.15,"s"),
 ("S","M",.12,"s"),("S","N",.12,"s"),("F","N",.12,"s"),("F","M",.12,"s"),
 ("Y","I",.62,"f"),("5","9",.50,"s"),("1","9",.30,"s"),("9","Y",.30,"s"),("5","I",.25,"f"),
 ("9","I",.25,"f"),("5","Y",.20,"s"),("9","N",.15,"s"),
 ("Q","U",.50,"f"),("2","U",.32,"s"),("2","T",.30,"s"),("Q","2",.25,"s"),("W","V",.18,"s"),
 ("W","U",.12,"s"),("2","D",.15,"s"),
 ("O","0",.95,"s"),
 ("6","X",.40,"s"),("6","S",.25,"s"),("4","R",.25,"s"),("E","I",.20,"s"),
]
# W[(true,heard)] = readiness that TRUE char `true` is emitted as `heard`
W = {}
def _put(a, b, w):
    if w > W.get((a, b), 0):
        W[(a, b)] = w
for a, b, w, d in _C:
    if d == "s":
        _put(a, b, w); _put(b, a, w)
    elif d == "f":                      # a>b : true a heard as b; reverse halved
        _put(a, b, w); _put(b, a, w / 2)
    else:                               # r == b>a
        _put(b, a, w); _put(a, b, w / 2)

FLOOR = 0.004       # bench3.py knee: 22.6% silent, 0% silent-wrong, 0.3% handover

RHYME = {}
for grp, cs in [("E", "BCDEGPTVZ3"), ("A", "AHJK8"), ("F", "FLMNSX"),
                ("I", "IY59"), ("U", "QUW2"), ("O", "O0")]:
    for c in cs:
        RHYME[c] = grp
for c in "R1467":
    RHYME[c] = c


# knee.py, ISO p=0.02: DOUBT_T 0.40 dominates 0.25 on every axis --
# accuracy 0.982 vs 0.983, silent 63.6% vs 20.2%, questions/id 0.45 vs 1.26,
# handover 2.8% vs 19.8%, at +0.0005 silent error. Silence is the product.
CFG = {"FLOOR": 0.004, "ACCEPT_P": 0.90, "ACCEPT_R": 8.0, "MIN_PLAUS": 0.05,
       "DOUBT_T": 0.40, "GUARD": True, "MIN_EDGE": 0.15, "H_T": 0.5,
       "BLIND_GUARD": True}


def w_of(true_c, heard_c, tags=()):
    if true_c == heard_c:
        return 1.0
    return max(W.get((true_c, heard_c), 0.0), CFG["FLOOR"])


# ---------------------------------------------------------------- formats ----
class Fmt:
    def __init__(self, name, length, alpha, ok):
        self.name, self.length, self.alpha, self.ok = name, length, alpha, ok

    def A(self, i):
        return self.alpha(i)


ISO = Fmt("ISO6346", 11, lambda i: L if i < 3 else ("UJZ" if i == 3 else D), iso_ok)
VIN = Fmt("VIN", 17, lambda i: VIN_ALPHA, vin_ok)   # X only ever appears at pos 8; alphabet is uniform
NHS = Fmt("NHS", 10, lambda i: D, nhs_ok)


def _gb(i):
    if i < 2:
        return L
    if i < 4:
        return D
    if i < 8:
        return L
    return D


IBANGB = Fmt("IBAN-GB", 22, _gb, iban_ok)
LUHN16 = Fmt("Luhn16", 16, lambda i: D, luhn_ok)


# ----------------------------------------------- per-position posterior ------
def pos_post(fmt, i, heard, conf, tags=(), locked=frozenset()):
    """P(true = x | ASR emitted `heard` at i with confidence `conf`).
    `conf` carries the mass on 'the ASR was right'; the confusion table
    distributes the remainder over the format-legal alphabet at i."""
    if i in locked:
        return {heard: 1.0}
    A = fmt.A(i)
    if heard not in A:                       # ASR emitted an impossible char here
        raw = {x: w_of(x, heard, tags) for x in A}
    else:
        rest = {x: w_of(x, heard, tags) for x in A if x != heard}
        s = sum(rest.values()) or 1.0
        raw = {x: (1.0 - conf) * v / s for x, v in rest.items()}
        raw[heard] = conf
    z = sum(raw.values()) or 1.0
    return {x: v / z for x, v in raw.items()}


def score(fmt, cand, heard, confs, tags=(), post=None, locked=frozenset()):
    post = post or [pos_post(fmt, i, heard[i], confs[i], tags, locked) for i in range(fmt.length)]
    return sum(math.log(max(post[i].get(cand[i], 1e-12), 1e-12)) for i in range(fmt.length))


# ------------------------------------------------- candidate generation ------
def repairs_r1(fmt, h, locked=frozenset()):
    """All single-character edits that restore validity. cost = L*A validator calls."""
    out = []
    calls = 0
    for i in range(fmt.length):
        if i in locked:
            continue
        for c in fmt.A(i):
            if c == h[i]:
                continue
            calls += 1
            cand = h[:i] + c + h[i + 1:]
            if fmt.ok(cand):
                out.append(cand)
    return out, calls


def doubt_order(fmt, h, confs, tags=(), locked=frozenset()):
    """Positions ranked by probability mass sitting OFF the heard character."""
    sc = []
    for i in range(fmt.length):
        if i in locked:
            continue
        p = pos_post(fmt, i, h[i], confs[i], tags, locked)
        sc.append((1.0 - p.get(h[i], 0.0), i))
    sc.sort(reverse=True)
    return [i for _, i in sc]


def repairs_r2(fmt, h, confs, tags=(), M=5, K=6, locked=frozenset()):
    """Bounded radius-2. Seed ONE acoustic edit at each of the top-M suspect
    positions (top-K alternates each), then run full r1 on the seeded string.
    cost <= M*K*(1 + L*A) validator calls."""
    order = doubt_order(fmt, h, confs, tags, locked)[:M]
    out = set()
    calls = 0
    for i in order:
        p = pos_post(fmt, i, h[i], confs[i], tags, locked)
        alts = sorted(((v, x) for x, v in p.items() if x != h[i]), reverse=True)[:K]
        for _, c in alts:
            seed = h[:i] + c + h[i + 1:]
            calls += 1
            if fmt.ok(seed):
                out.add(seed)
                continue
            r, cc = repairs_r1(fmt, seed, locked | {i})
            calls += cc
            out.update(r)
    return sorted(out), calls


def repairs_r2_naive_cost(fmt):
    """Unbounded radius-2 validator-call count, for cost comparison only."""
    Ln = fmt.length
    tot = 0
    for i in range(Ln):
        ai = len(fmt.A(i)) - 1
        for j in range(i + 1, Ln):
            tot += ai * (len(fmt.A(j)) - 1)
    return tot


# ------------------------------------------------------------- decision ------
def marginals(fmt, cands, probs):
    m = [dict() for _ in range(fmt.length)]
    for c, p in zip(cands, probs):
        for i, ch in enumerate(c):
            m[i][ch] = m[i].get(ch, 0.0) + p
    return m


def H(d):
    return -sum(p * math.log2(p) for p in d.values() if p > 1e-12)


ACCEPT_P = 0.90     # posterior mass on top candidate required to accept silently
ACCEPT_R = 8.0      # ...and margin over the runner-up
MIN_PLAUS = 0.05    # a lone survivor must still be acoustically plausible


# --------------------------------------------------------------------------
# Checksum blind classes
# --------------------------------------------------------------------------
# ISO 6346 sums value(c) * 2^i mod 11, so any two characters congruent mod 11
# are INVISIBLE to the check digit: {A K U} {1 B L V} {2 C M W} {3 D N X}
# {4 E O Y} {5 F P Z} {6 G Q} {7 H R} {8 I S} {9 J T}. A substitution inside a
# class produces a string the validator declares perfectly valid.
#
# Measured against the acoustic table: only 5.3% of confusion weight lands in a
# blind class. The heavy pairs -- O/0 at 0.95, C/Z 0.80, B/D 0.75, M/N 0.72 --
# are all visible. The blind ones are B/V (0.45), K/A and F/P (0.30), 3/D
# (0.20), N/X (0.15): twelve pairs, all lighter.
#
# That is small enough to close by hand. The checksum can never adjudicate
# these, so the solver must not wait for it to: a doubtful position whose
# heard character has a confusable, congruent neighbour is asked about, always.
# The agent knows which substitutions its own arithmetic is blind to.

def _residue_map(fmt):
    """char -> checksum residue class, or None if this format has no modular check."""
    if fmt.name == "ISO6346":
        m = {c: v % 11 for c, v in ISO_LET.items()}
        m.update({str(d): d % 11 for d in range(10)})
        return m
    return None


_BLIND_CACHE = {}


def blind_alternatives(fmt, i, heard_c):
    """Confusable characters at position i that the check digit cannot distinguish."""
    key = (fmt.name, i, heard_c)
    if key in _BLIND_CACHE:
        return _BLIND_CACHE[key]
    res = _residue_map(fmt)
    if res is None or heard_c not in res:
        out = frozenset()
    else:
        out = frozenset(
            c for c in fmt.alpha(i)
            if c != heard_c and res.get(c) == res[heard_c] and w_of(c, heard_c) > CFG["FLOOR"]
        )
    _BLIND_CACHE[key] = out
    return out


def decide(fmt, h, confs, tags=(), locked=frozenset()):
    t0 = time.perf_counter()
    post = [pos_post(fmt, i, h[i], confs[i], tags, locked) for i in range(fmt.length)]
    calls = 0
    radius = 0
    if fmt.ok(h):
        cands = [h]
    else:
        radius = 1
        cands, calls = repairs_r1(fmt, h, locked)
        if not cands:
            radius = 2
            cands, c2 = repairs_r2(fmt, h, confs, tags, locked=locked)
            calls += c2
    if not cands:
        return dict(action="FAIL_NOCAND", calls=calls, radius=radius,
                    ms=(time.perf_counter() - t0) * 1e3, cands=[], top=None,
                    post_top=0.0, ask_pos=None, n_amb=0, n_amb_eff=99, doubtful=[],
                    unexplained=99, n_cand=0, plaus=0.0)
    sc = [score(fmt, c, h, confs, tags, post, locked) for c in cands]
    mx = max(sc)
    ex = [math.exp(s - mx) for s in sc]
    Z = sum(ex)
    pr = [e / Z for e in ex]
    order = sorted(range(len(cands)), key=lambda k: -pr[k])
    cands = [cands[k] for k in order]
    pr = [pr[k] for k in order]
    top = cands[0]
    plaus = math.exp(score(fmt, top, h, confs, tags, post, locked) / fmt.length)
    if len(cands) == 1:
        act = "ACCEPT" if plaus >= CFG["MIN_PLAUS"] else "ASK_LOWPLAUS"
    elif pr[0] >= CFG["ACCEPT_P"] and pr[0] / max(pr[1], 1e-12) >= CFG["ACCEPT_R"]:
        act = "ACCEPT"
    else:
        act = "ASK"
    # --- doubt-budget guard -------------------------------------------------
    # A position is DOUBTFUL if the posterior puts >DOUBT_T mass off the heard
    # char.  A candidate EXPLAINS a doubtful position if it edits it.  Silent
    # acceptance requires every doubtful position to be explained: unexplained
    # doubt means there is probably a second error the checksum already absorbed.
    doubtful = {i for i in range(fmt.length)
                if i not in locked and (1.0 - post[i].get(h[i], 0.0)) > CFG["DOUBT_T"]}
    edited = {i for i in range(fmt.length) if top[i] != h[i]}
    unexplained_set = doubtful - edited
    unexplained = len(unexplained_set)
    if CFG["GUARD"] and act == "ACCEPT" and unexplained > 0:
        act = "ASK_UNEXPLAINED"
    # --- per-edit plausibility -----------------------------------------------
    # Every character the agent silently changes must be a substitution the
    # confusion table actually knows about.  A repair that is only valid
    # arithmetically is evidence of a DATA error, not a hearing error.
    # --- blind-class guard ---------------------------------------------------
    # A doubtful position whose heard character has a confusable neighbour in
    # its own residue class is one the checksum will never object to. Silence
    # there is not confidence, it is arithmetic that cannot see.
    blind_doubt = {
        i for i in doubtful
        if i not in edited and blind_alternatives(fmt, i, h[i])
    }
    if CFG.get("BLIND_GUARD", True) and act == "ACCEPT" and blind_doubt:
        act = "ASK_BLIND"
        unexplained_set = unexplained_set | blind_doubt
        unexplained = len(unexplained_set)

    if CFG["GUARD"] and act == "ACCEPT" and edited:
        if min(w_of(top[i], h[i]) for i in edited) < CFG["MIN_EDGE"]:
            act = "FLAG_IMPLAUSIBLE"

    m = marginals(fmt, cands, pr)
    ents = sorted(((H(m[i]), i) for i in range(fmt.length) if i not in locked), reverse=True)

    # --- where to ask -------------------------------------------------------
    # Marginal entropy measures disagreement AMONG candidates, so it is
    # identically zero when exactly one candidate survives -- which is the very
    # case the doubt guard fires on. Reading "no entropy to gain" as "nothing to
    # ask" fell straight through to a silent accept, and guardhole.py measured
    # the cost: on IBAN at p=0.15, 41.8% of guarded identifiers were written
    # wrong and silently.
    #
    # Two questions, two instruments:
    #   unexplained doubt -> DETECTION.     ask where the posterior most
    #                                       distrusts what was heard
    #   no unexplained doubt -> DISAMBIGUATION. ask where candidates disagree
    #
    # After the fix silently-wrong is 0.000 in every measured cell, and
    # accuracy rises (ISO p=0.10: 0.828 -> 0.859; IBAN p=0.05: 0.769 -> 0.867).
    if unexplained_set:
        ask_pos = max(unexplained_set, key=lambda i: 1.0 - post[i].get(h[i], 0.0))
        ask_H = H(m[ask_pos])
    else:
        ask_pos, ask_H = ents[0][1], ents[0][0]
    return dict(action=act, cands=cands[:8], probs=pr[:8], top=top, post_top=pr[0],
                ask_pos=ask_pos, ask_H=ask_H, marg=m[ask_pos],
                n_amb=sum(1 for e, _ in ents if e > 1e-9),
                n_amb_eff=sum(1 for e, _ in ents if e > CFG["H_T"]), calls=calls, radius=radius,
                ms=(time.perf_counter() - t0) * 1e3, plaus=plaus,
                doubtful=sorted(doubtful), unexplained=unexplained, n_cand=len(cands))
