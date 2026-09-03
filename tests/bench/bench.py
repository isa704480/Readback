import sys, random, math, time, statistics
sys.path.insert(0, r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad")
from rb import *

random.seed(23)

# ------------------------------------------------------------- generators ---
def gen_iso():
    while True:
        s = "".join(random.choice(L) for _ in range(3)) + "U" + "".join(random.choice(D) for _ in range(6))
        raw = sum(iso_val(c) * (2 ** i) for i, c in enumerate(s)) % 11
        if raw == 10:
            continue                      # degenerate: remainder 10 folds onto 0
        return s + str(raw % 10)

def gen_vin():
    while True:
        s = [random.choice(VIN_ALPHA) for _ in range(17)]
        s[8] = "0"
        t = sum((int(c) if c.isdigit() else VT[c]) * VW[i] for i, c in enumerate(s))
        r = t % 11
        s[8] = "X" if r == 10 else str(r)
        c = "".join(s)
        if vin_ok(c):
            return c

def gen_nhs():
    while True:
        b = "".join(random.choice(D) for _ in range(9))
        t = sum(int(b[i]) * (10 - i) for i in range(9))
        c = 11 - (t % 11)
        if c == 10:
            continue
        return b + str(0 if c == 11 else c)

def gen_iban():
    bban = "".join(random.choice(L) for _ in range(4)) + "".join(random.choice(D) for _ in range(14))
    for k in range(100):
        c = "GB%02d" % k + bban
        if iban_ok(c):
            return c
    return None

def gen_luhn16():
    b = "".join(random.choice(D) for _ in range(15))
    for d in D:
        if luhn_ok(b + d):
            return b + d

GEN = {"ISO6346": gen_iso, "VIN": gen_vin, "NHS": gen_nhs, "IBAN-GB": gen_iban, "Luhn16": gen_luhn16}
FMTS = [ISO, VIN, NHS, IBANGB, LUHN16]

# ------------------------------------------------------------- ASR model ----
def mishear(fmt, truth, n_err):
    """Corrupt exactly n_err positions with an acoustically-sampled substitution."""
    idx = list(range(fmt.length))
    random.shuffle(idx)
    h = list(truth)
    hit = []
    for i in idx:
        if len(hit) == n_err:
            break
        A = [c for c in fmt.A(i) if c != truth[i]]
        wts = [W.get((truth[i], c), 0.0) for c in A]
        if sum(wts) <= 0:
            continue
        h[i] = random.choices(A, weights=wts)[0]
        hit.append(i)
    return "".join(h), sorted(hit)

def confs_for(fmt, hit, mode):
    if mode == "flat":
        return [0.90] * fmt.length
    return [random.uniform(0.35, 0.75) if i in hit else random.uniform(0.85, 0.99)
            for i in range(fmt.length)]

# ------------------------------------------------------------- experiment ---
def run(fmt, n_err, mode, N=400):
    gen = GEN[fmt.name]
    stats = dict(n=0, blind=0, accept=0, accept_right=0, ask=0, ask_right_pos=0,
                 ask_fix=0, fail=0, calls=[], ms=[], namb=[], ncand=[], r2=0)
    for _ in range(N):
        truth = gen()
        if truth is None or not fmt.ok(truth):
            continue
        h, hit = mishear(fmt, truth, n_err)
        if len(hit) < n_err or h == truth:
            continue
        stats["n"] += 1
        if fmt.ok(h):
            stats["blind"] += 1          # checksum cannot see this error at all
            continue
        cf = confs_for(fmt, hit, mode)
        r = decide(fmt, h, cf)
        stats["calls"].append(r["calls"])
        stats["ms"].append(r["ms"])
        if r.get("radius") == 2:
            stats["r2"] += 1
        if r["action"] == "FAIL_NOCAND":
            stats["fail"] += 1
            continue
        stats["ncand"].append(len(r["cands"]) if len(r["cands"]) < 8 else 8)
        if r["action"] == "ACCEPT":
            stats["accept"] += 1
            stats["accept_right"] += (r["top"] == truth)
        else:
            stats["ask"] += 1
            stats["namb"].append(r["n_amb"])
            p = r["ask_pos"]
            stats["ask_right_pos"] += (p in hit)
            # simulate a correct human answer at the asked position, then re-decide
            h2 = h[:p] + truth[p] + h[p + 1:]
            cf2 = list(cf)
            cf2[p] = 0.995
            r2 = decide(fmt, h2, cf2)
            stats["ask_fix"] += (r2.get("top") == truth and r2["action"] == "ACCEPT")
    return stats

def pct(a, b):
    return "%5.1f%%" % (100.0 * a / b) if b else "   -  "

if __name__ == '__main__':
    print("=" * 104)
    print("A.  DECISION OUTCOMES  (N valid ids per cell; exactly n_err acoustically-sampled substitutions)")
    print("=" * 104)
    for mode in ("calibrated", "flat"):
        for n_err in (1, 2):
            print("\n--- confidence=%s   errors=%d ---" % (mode, n_err))
            print("%-9s %6s %7s %8s %8s %8s %8s %8s %7s %7s" %
                  ("format", "N", "blind", "SILENT", "->right", "ASK", "pos-hit", "1Q-fix", "FAIL", "cands"))
            for f in FMTS:
                s = run(f, n_err, mode)
                seen = s["n"] - s["blind"]
                print("%-9s %6d %7s %8s %8s %8s %8s %8s %7s %7.1f" % (
                    f.name, s["n"], pct(s["blind"], s["n"]),
                    pct(s["accept"], seen), pct(s["accept_right"], max(s["accept"], 1)),
                    pct(s["ask"], seen), pct(s["ask_right_pos"], max(s["ask"], 1)),
                    pct(s["ask_fix"], max(s["ask"], 1)), pct(s["fail"], seen),
                    statistics.mean(s["ncand"]) if s["ncand"] else 0))

    print()
    print("=" * 104)
    print("B.  SEARCH COST   (validator calls; r2-naive is the unbounded two-error search we do NOT do)")
    print("=" * 104)
    print("%-9s %4s %6s %14s %16s %16s %12s" % ("format", "L", "|A|max", "r1 calls", "r2 bounded calls", "r2 naive calls", "median ms"))
    for f in FMTS:
        gen = GEN[f.name]
        t = gen()
        h, hit = mishear(f, t, 1)
        cf = confs_for(f, hit, "calibrated")
        _, c1 = repairs_r1(f, h)
        _, c2 = repairs_r2(f, h, cf)
        ms = []
        for _ in range(60):
            t = gen()
            h, hit = mishear(f, t, 1)
            if f.ok(h):
                continue
            cf = confs_for(f, hit, "calibrated")
            r = decide(f, h, cf)
            ms.append(r["ms"])
        print("%-9s %4d %6d %14d %16d %16d %12.2f" % (
            f.name, f.length, max(len(f.A(i)) for i in range(f.length)),
            c1, c2, repairs_r2_naive_cost(f), statistics.median(ms) if ms else -1))
