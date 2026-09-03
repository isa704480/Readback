# tolerance.py -- THE MECHANISM.
# Exact-match accuracy for the NAIVE baseline is (1-p)^L: it depends only on
# HOW MANY characters are wrong, never on WHICH ones.  So accent SHAPE cannot
# affect it, by construction -- and the shape-only control confirms the
# constrained solver does not introduce shape sensitivity either.
# The axis on which accents genuinely differ is the ERROR RATE.  So the correct
# measure of accent robustness is: how much per-character error can the system
# absorb before capture quality falls below a target?
import sys, json, math, statistics
P = r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad"
sys.path.insert(0, P)
from accent import ACCENTS

ACCS = list(ACCENTS)
CONDS = ["NAIVE", "SLOT", "CKSUM", "FULL-US", "FULL-BL", "ORACLE"]
FMTS = {"ISO6346": 11, "IBAN-GB": 22}

def load(tag):
    try: d = json.load(open(f"{P}/results_{tag}.json"))
    except FileNotFoundError: return None
    out = {}
    for k, v in d.items():
        f, a, p = k.split("|"); out[(f, a, float(p))] = v
    return out

def A(cell, c): a = cell["agg"][c]; return a["correct"] / a["n"]

def cross(xs, ys, target):
    """p_eff at which the accuracy curve crosses `target` (log-linear interp)."""
    pts = sorted(zip(xs, ys))
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i+1]
        if y0 >= target > y1:
            t = (y0 - target) / max(y0 - y1, 1e-12)
            return x0 + t * (x1 - x0)
    return None

def tolerance(tag, target=0.95):
    R = load(tag)
    if R is None: print(f"[{tag}] missing"); return
    rates = sorted({p for (_, _, p) in R})
    N = R[("ISO6346", ACCS[0], rates[0])]["N"]
    print(f"\n{'='*104}")
    print(f"ERROR-RATE TOLERANCE [{tag}] -- per-character error rate the system absorbs")
    print(f"while still capturing {target:.0%} of identifiers exactly.  N={N}/cell.")
    print(f"'analytic NAIVE' = 1-target^(1/L), the exact value for an uncorrected transcript.")
    print(f"{'='*104}")
    for f, Lf in FMTS.items():
        an = 1 - target ** (1.0 / Lf)
        print(f"\n  {f}   (L={Lf}, analytic NAIVE tolerance = {an:.4f})")
        print(f"  {'condition':<10}" + "".join(f"{a:>11s}" for a in ACCS)
              + f"{'  mean':>9}{'min':>8}{'max':>8}{'x NAIVE':>9}")
        base = None
        for c in CONDS:
            th = []
            for a in ACCS:
                xs = [R[(f, a, p)]["p_eff"] for p in rates]
                ys = [A(R[(f, a, p)], c) for p in rates]
                th.append(cross(xs, ys, target))
            if any(t is None for t in th):
                shown = "".join(f"{('  n/a' if t is None else f'{t:.4f}'):>11s}" for t in th)
                print(f"  {c:<10}{shown}   (curve does not cross in the swept range)")
                continue
            m = statistics.mean(th)
            if base is None: base = m
            print(f"  {c:<10}" + "".join(f"{t:11.4f}" for t in th)
                  + f"{m:9.4f}{min(th):8.4f}{max(th):8.4f}{m/an:9.1f}x")

def curve(tag):
    R = load(tag)
    if R is None: return
    rates = sorted({p for (_, _, p) in R})
    print(f"\n{'='*104}\nACCURACY CURVES [{tag}] -- mean over 8 accents\n{'='*104}")
    for f in FMTS:
        print(f"\n  {f}")
        print(f"  {'p_base':>7}{'p_eff(mean)':>13}" + "".join(f"{c:>10s}" for c in CONDS))
        for p in rates:
            pe = statistics.mean(R[(f, a, p)]["p_eff"] for a in ACCS)
            print(f"  {p:>7.3f}{pe:>13.4f}"
                  + "".join(f"{statistics.mean(A(R[(f,a,p)],c) for a in ACCS):10.3f}"
                            for c in CONDS))

def qdist(tag, ps=(0.02, 0.03, 0.05)):
    R = load(tag)
    if R is None: return
    rates = sorted({p for (_, _, p) in R})
    ps = [p for p in ps if p in rates]
    print(f"\n{'='*104}")
    print(f"CANDIDATE COUNT AND QUESTION LOAD [{tag}] -- FULL-BL, pooled over accents")
    print(f"{'='*104}")
    for f in FMTS:
        print(f"\n  {f}")
        print(f"  {'p':>6}{'corrupted':>11}{'0 valid':>9}{'1 valid':>9}{'2+ valid':>10}"
              f"{'silent':>9}{'q/id':>7}{'sil.wrong':>11}{'accuracy':>10}")
        for p in ps:
            tot = c0 = c1 = c2 = 0; sil = sw = q = ac = corr = 0.0
            for a in ACCS:
                cell = R[(f, a, p)]; nc = cell["ncand"]
                s = sum(nc.values()) or 1
                c0 += nc.get("0", 0); c1 += nc.get("1", 0); c2 += nc.get("2", 0); tot += s
                ag = cell["agg"]["FULL-BL"]; n = ag["n"]
                sil += ag["silent"] / n; sw += ag["silently_wrong"] / n
                q += cell["nq"]["FULL-BL"]; ac += ag["correct"] / n
                corr += cell["corrupted_frac"]
            k = len(ACCS)
            print(f"  {p:>6.3f}{corr/k:11.3f}{c0/tot:9.3f}{c1/tot:9.3f}{c2/tot:10.3f}"
                  f"{sil/k:9.3f}{q/k:7.2f}{sw/k:11.4f}{ac/k:10.3f}")

if __name__ == "__main__":
    tags = sys.argv[1].split(",") if len(sys.argv) > 1 else ["main"]
    for t in tags:
        curve(t); tolerance(t, 0.95); tolerance(t, 0.99); qdist(t)
