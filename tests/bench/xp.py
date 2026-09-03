# xp.py -- THE EXPERIMENT.
# Claim under test: constraining the output space to checksum-valid strings
# makes ACCENT VARIATION largely irrelevant for identifier capture.
#
# Method: corrupt valid identifiers with accent-CONDITIONED confusion models;
# hand the corrupted string to solvers that DO NOT KNOW THE ACCENT; measure
# whether the across-accent SPREAD in accuracy collapses under constraint.
import sys, math, random, time, statistics, json
from collections import Counter
P = r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad"
sys.path.insert(0, P)
from fastval import ISO, IBANGB, D, L
from accent import ACCENTS, TABLES, BLEND, GENERIC, gen_dist, FULL, GEN_FLOOR

SOLVER_FLOOR = 0.004        # solver's floor for pairs absent from its table

# ------------------------------------------------------------- corpus --------
def gen_iso(rng):
    while True:
        s = "".join(rng.choice(L) for _ in range(3)) + rng.choice("UJZ") \
            + "".join(rng.choice(D) for _ in range(6))
        r = sum(ISO.contrib[i][s[i]] for i in range(10)) % 11
        if r != 10:
            return s + str(r)

def gen_iban(rng):
    while True:
        body = "GB00" + "".join(rng.choice(L) for _ in range(4)) \
               + "".join(rng.choice(D) for _ in range(14))
        R0 = IBANGB.residual(body)
        base = (R0 - IBANGB.contrib[2]['0'] - IBANGB.contrib[3]['0']) % 97
        for a in D:
            for b in D:
                if (base + IBANGB.contrib[2][a] + IBANGB.contrib[3][b]) % 97 == 1:
                    return "GB" + a + b + body[4:]

# -------------------------------------------------------- ASR simulation -----
# confidence regimes: (err_alpha, err_beta, ok_alpha, ok_beta) or None for flat.
# 'strong' separates errors from correct chars sharply; 'weak' barely separates
# them; 'flat' carries no information at all.  The truth for AssemblyAI's
# words[].confidence on spelled alphanumerics is unknown until day 3, so the
# experiment brackets it rather than assuming it.
CONF_MODES = {"strong": (2.2, 3.2, 9.0, 1.3),
              "weak":   (3.0, 2.2, 5.0, 1.6),
              "flat":   None}

def corrupt(truth, table, p_eff, rng, conf_mode="strong", alpha=None):
    """Emit a hypothesis over the FULL 36-char space (the ASR does not know the
    format) plus a per-character confidence.
    alpha != None  -> WITHIN-TYPE hard case: the ASR never emits a character
    that is illegal at that position, so slot typing contributes nothing and
    the checksum + acoustic posterior must do all the work."""
    cm = CONF_MODES[conf_mode]
    hyp, confs, nerr = [], [], 0
    for i, t in enumerate(truth):
        if rng.random() < p_eff:
            d = gen_dist(table, t)
            if alpha is not None:
                d = {x: v for x, v in d.items() if x in alpha[i]} or {t: 1.0}
            tot = sum(d.values()); r = rng.random() * tot; acc = 0.0
            ch = t
            for x, v in d.items():
                acc += v
                if acc >= r:
                    ch = x; break
            hyp.append(ch); nerr += 1
            confs.append(0.80 if cm is None else min(.97, max(.05, rng.betavariate(cm[0], cm[1]))))
        else:
            hyp.append(t)
            confs.append(0.80 if cm is None else min(.995, max(.30, rng.betavariate(cm[2], cm[3]))))
    return "".join(hyp), confs, nerr

# ------------------------------------------------------------- solver -------
def w_of(table, true_c, heard_c):
    if true_c == heard_c: return 1.0
    return max(table.get((true_c, heard_c), 0.0), SOLVER_FLOOR)

def project(fmt, hyp, table):
    """Pass-2 slot-typed collapse: an illegal character at position i is mapped
    to the legal character most likely to have produced it."""
    out = []
    for i, ch in enumerate(hyp):
        A = fmt.alpha[i]
        if ch in A: out.append(ch)
        else: out.append(max(A, key=lambda x: w_of(table, x, ch)))
    return "".join(out)

def pos_post(fmt, i, heard, conf, table, locked):
    if i in locked: return {heard: 1.0}
    A = fmt.alpha[i]
    if heard not in A:
        raw = {x: w_of(table, x, heard) for x in A}
    else:
        rest = {x: w_of(table, x, heard) for x in A if x != heard}
        s = sum(rest.values()) or 1.0
        raw = {x: (1.0 - conf) * v / s for x, v in rest.items()}
        raw[heard] = conf
    z = sum(raw.values()) or 1.0
    return {x: v / z for x, v in raw.items()}

def r1(fmt, h, locked):
    """All single-char edits restoring validity. O(L*A) via incremental residual."""
    out = []
    if fmt is ISO:
        R = ISO.residual(h); cd = h[10]
        for i in range(10):
            if i in locked: continue
            base = (R - ISO.contrib[i][h[i]]) % 11
            for c in ISO.alpha[i]:
                if c == h[i]: continue
                r = (base + ISO.contrib[i][c]) % 11
                if r != 10 and str(r) == cd: out.append(h[:i] + c + h[i+1:])
        if 10 not in locked and R != 10 and str(R) != cd:
            out.append(h[:10] + str(R))
    else:
        R = IBANGB.residual(h)
        for i in range(22):
            if i in locked: continue
            base = (R - IBANGB.contrib[i][h[i]]) % 97
            for c in IBANGB.alpha[i]:
                if c == h[i]: continue
                if (base + IBANGB.contrib[i][c]) % 97 == 1:
                    out.append(h[:i] + c + h[i+1:])
    return out

def r2(fmt, h, post, locked, M=5, K=6):
    order = sorted(range(fmt.length), key=lambda i: -(1.0 - post[i].get(h[i], 0.0)))
    order = [i for i in order if i not in locked][:M]
    out = set()
    for i in order:
        alts = sorted(((v, x) for x, v in post[i].items() if x != h[i]), reverse=True)[:K]
        for _, c in alts:
            seed = h[:i] + c + h[i+1:]
            if fmt.ok(seed): out.add(seed); continue
            out.update(r1(fmt, seed, locked | {i}))
    return sorted(out)

def Hent(d):
    return -sum(p * math.log2(p) for p in d.values() if p > 1e-12)

ACCEPT_P, ACCEPT_R, MIN_EDGE, DOUBT_T = 0.85, 8.0, 0.15, 0.25

def solve(fmt, hyp_raw, confs, truth, table, mode, rng, budget=2, answer_err=0.0, qfix=False):
    """mode: 'naive' | 'slot' | 'cksum' | 'post'
    Returns (written, silent, nquestions, n_cand_at_r1, status)."""
    if mode == "naive":
        return hyp_raw, True, 0, None, "NAIVE"
    h = project(fmt, hyp_raw, GENERIC if mode == "cksum" else table)
    if mode == "slot":
        return h, True, 0, None, "SLOT"

    locked, nq, first_ncand = set(), 0, None
    while True:
        post = [pos_post(fmt, i, h[i], confs[i], table, locked) for i in range(fmt.length)]
        if fmt.ok(h):
            cands = [h]
        else:
            cands = r1(fmt, h, locked)
            if not cands: cands = r2(fmt, h, post, locked)
        if first_ncand is None: first_ncand = len(cands)
        if not cands:
            return h, False, nq, first_ncand, "NOCAND"

        if mode == "cksum":
            # No confusion model and no confidence: every checksum-valid
            # candidate is equally likely.  This baseline is given the STRONGEST
            # honest form -- a uniform posterior and the same max-entropy
            # question picker as the full solver -- so that any gap to FULL is
            # attributable to the acoustic model and not to a weaker questioner.
            pr = [1.0 / len(cands)] * len(cands)
            top = cands[rng.randrange(len(cands))]
            act = "ACCEPT" if len(cands) == 1 else "ASK"
        else:
            sc = [sum(math.log(max(post[i].get(c[i], 1e-12), 1e-12)) for i in range(fmt.length))
                  for c in cands]
            mx = max(sc); ex = [math.exp(s - mx) for s in sc]; Z = sum(ex)
            pr = [e / Z for e in ex]
            o = sorted(range(len(cands)), key=lambda k: -pr[k])
            cands = [cands[k] for k in o]; pr = [pr[k] for k in o]
            top = cands[0]
            if len(cands) == 1: act = "ACCEPT"
            elif pr[0] >= ACCEPT_P and pr[0] / max(pr[1], 1e-12) >= ACCEPT_R: act = "ACCEPT"
            else: act = "ASK"
            edited = {i for i in range(fmt.length) if top[i] != h[i]}
            unexp = []
            if act == "ACCEPT":
                doubtful = {i for i in range(fmt.length)
                            if i not in locked and (1.0 - post[i].get(h[i], 0.0)) > DOUBT_T}
                unexp = sorted(doubtful - edited)
                if unexp: act = "ASK"                                   # doubt-budget guard
                elif edited and min(w_of(table, top[i], h[i]) for i in edited) < MIN_EDGE:
                    act = "FLAG"                                        # implausible repair

        if act == "ACCEPT": return top, nq == 0, nq, first_ncand, "ACCEPT"
        if act == "FLAG":   return top, False, nq, first_ncand, "FLAG"
        if nq >= budget:    return top, False, nq, first_ncand, "HANDOVER"

        # ---- pick a position to ask about ----
        marg = [dict() for _ in range(fmt.length)]
        for c, q in zip(cands, pr):
            for i, ch in enumerate(c): marg[i][ch] = marg[i].get(ch, 0.0) + q
        avail = [i for i in range(fmt.length) if i not in locked]
        if qfix and mode != "cksum" and unexp:
            # THE FIX.  The guard fired, which means the suspicion is that a
            # SECOND error exists that the checksum already absorbed.  That is a
            # DETECTION question, and marginal entropy -- which measures
            # disagreement AMONG the valid candidates -- is the wrong
            # instrument: when there is one candidate it is identically zero at
            # every position.  Ask at argmax UNEXPLAINED DOUBT instead.
            p = max(unexp, key=lambda i: 1.0 - post[i].get(h[i], 0.0))
        else:
            p = max(avail, key=lambda i: Hent(marg[i]))
            if Hent(marg[p]) < 1e-9:
                return top, nq == 0, nq, first_ncand, "ACCEPT"
        ans = truth[p]
        if answer_err and rng.random() < answer_err:
            A = [x for x in fmt.alpha[p] if x != truth[p]]
            ans = rng.choice(A)
        h = h[:p] + ans + h[p+1:]
        confs = confs[:p] + [0.999] + confs[p+1:]
        locked.add(p); nq += 1

# --------------------------------------------------------------- run ---------
CONDS = [("NAIVE",   "naive", None),
         ("SLOT",    "slot",  GENERIC),
         ("CKSUM",   "cksum", GENERIC),
         ("FULL-US", "post",  GENERIC),
         ("FULL-BL", "post",  BLEND),
         ("ORACLE",  "post",  None)]     # None -> accent-matched table

def run(fmt, gen, accents, rates, N, conf_mode="strong", answer_err=0.0,
        seed=11, budget=2, same_rate=False, within=False, qfix=False):
    res = {}
    for acc in accents:
        tbl = TABLES[acc]
        mult = 1.0 if same_rate else ACCENTS[acc]["rate"]
        for p in rates:
            p_eff = min(0.60, p * mult)
            rng = random.Random(seed + abs(hash((acc, p, fmt.name))) % 100000)
            agg = {c[0]: Counter() for c in CONDS}
            nq  = {c[0]: 0 for c in CONDS}
            ncd = Counter(); blind = 0; nerr_tot = 0; hyp_bad = 0
            for _ in range(N):
                truth = gen(rng)
                hyp, confs, nerr = corrupt(truth, tbl, p_eff, rng, conf_mode,
                                           fmt.alpha if within else None)
                nerr_tot += nerr
                if hyp != truth:
                    hyp_bad += 1
                    if fmt.ok(hyp): blind += 1
                for cname, mode, ctab in CONDS:
                    t = tbl if (ctab is None and mode == "post") else ctab
                    srng = random.Random(rng.randrange(1 << 30))
                    w, silent, q, nc, st = solve(fmt, hyp, list(confs), truth,
                                                 t, mode, srng, budget, answer_err, qfix)
                    ok = (w == truth)
                    a = agg[cname]
                    a["n"] += 1
                    a["correct"] += ok
                    a["silent"] += silent
                    a["silently_wrong"] += (silent and not ok)
                    a[st] += 1
                    nq[cname] += q
                    if cname == "FULL-US" and nc is not None:
                        ncd[0 if nc == 0 else (1 if nc == 1 else 2)] += 1
            res[(acc, p)] = dict(agg={k: dict(v) for k, v in agg.items()},
                                 nq={k: v / N for k, v in nq.items()},
                                 ncand=dict(ncd), blind_of_corrupted=blind / max(hyp_bad, 1),
                                 corrupted_frac=hyp_bad / N,
                                 p_eff=p_eff, mean_err=nerr_tot / N, N=N)
    return res

RUNS = {   # tag -> kwargs
  "main":      dict(conf_mode="strong", same_rate=False),
  "shapeonly": dict(conf_mode="strong", same_rate=True),   # isolates accent SHAPE
  "weak":      dict(conf_mode="weak",   same_rate=False),
  "flat":      dict(conf_mode="flat",   same_rate=False),
  "aerr":      dict(conf_mode="strong", same_rate=False, answer_err=0.05),
  "b0":        dict(conf_mode="strong", same_rate=False, budget=0),
  "b1":        dict(conf_mode="strong", same_rate=False, budget=1),
  "within":    dict(conf_mode="strong", same_rate=False, within=True),
  "within_sh": dict(conf_mode="strong", same_rate=True,  within=True),
  "fixed":     dict(conf_mode="strong", same_rate=False, qfix=True),
  "fixed_sh":  dict(conf_mode="strong", same_rate=True,  qfix=True),
  "fixed_wi":  dict(conf_mode="strong", same_rate=False, qfix=True, within=True),
}

if __name__ == "__main__":
    t0 = time.time()
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    tags = sys.argv[2].split(",") if len(sys.argv) > 2 else ["main"]
    RATES = [0.02, 0.05, 0.10, 0.15, 0.20, 0.30]
    ACCS = list(ACCENTS)
    for tag in tags:
        out = {}
        for fname, fmt, gen in [("ISO6346", ISO, gen_iso), ("IBAN-GB", IBANGB, gen_iban)]:
            out[fname] = run(fmt, gen, ACCS, RATES, N, **RUNS[tag])
            print(f"  [{tag}] {fname} done  {time.time()-t0:.1f}s", file=sys.stderr)
        json.dump({f"{k}|{a}|{p}": v for k, d in out.items() for (a, p), v in d.items()},
                  open(f"{P}/results_{tag}.json", "w"))
    print(f"TOTAL {time.time()-t0:.1f}s  N={N} tags={tags}", file=sys.stderr)
