import sys, random, math, time, statistics
sys.path.insert(0, r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad")
from rb import *
from bench import GEN, FMTS, mishear, confs_for   # reuse generators + ASR model

random.seed(101)
MAXQ = 2          # question budget per identifier


def session(fmt, truth, h, hit, confs, policy="entropy"):
    """Full multi-turn loop. Returns (outcome, n_questions, final_string)."""
    locked = set()
    q = 0
    while True:
        r = decide(fmt, h, confs, locked=frozenset(locked))
        if r["action"] == "FAIL_NOCAND":
            return "HANDOVER_NOCAND", q, None
        if r["action"] == "ACCEPT":
            return ("RESOLVED_OK" if r["top"] == truth else "RESOLVED_WRONG"), q, r["top"]
        if q >= MAXQ:
            return "HANDOVER_BUDGET", q, r["top"]
        # choose the position to ask about
        if policy == "entropy":
            p = r["ask_pos"]
        else:   # "top2diff": first position where the top two candidates disagree
            a, b = r["cands"][0], r["cands"][1]
            p = next(i for i in range(fmt.length) if a[i] != b[i])
        q += 1
        # human answers truthfully; answer is constrained to the offered set
        h = h[:p] + truth[p] + h[p + 1:]
        confs = list(confs)
        confs[p] = 0.999
        locked.add(p)


def sweep(fmt, n_err, mode, N=350, policy="entropy"):
    gen = GEN[fmt.name]
    out = dict(n=0, blind=0, ok=0, wrong=0, ho=0, q=[], ms=[])
    for _ in range(N):
        truth = gen()
        if truth is None or not fmt.ok(truth):
            continue
        h, hit = mishear(fmt, truth, n_err)
        if len(hit) < n_err or h == truth:
            continue
        out["n"] += 1
        if fmt.ok(h):
            out["blind"] += 1
            continue
        cf = confs_for(fmt, hit, mode)
        t0 = time.perf_counter()
        res, q, fin = session(fmt, truth, h, hit, cf, policy)
        out["ms"].append((time.perf_counter() - t0) * 1e3)
        out["q"].append(q)
        if res == "RESOLVED_OK":
            out["ok"] += 1
        elif res == "RESOLVED_WRONG":
            out["wrong"] += 1
        else:
            out["ho"] += 1
    return out


def pc(a, b):
    return "%5.1f%%" % (100.0 * a / b) if b else "   -  "


print("=" * 108)
print("C.  THRESHOLD / FLOOR SWEEP  -- ISO 6346, 1 acoustic error, budget %d questions" % MAXQ)
print("=" * 108)
print("%8s %9s %8s %8s %9s %8s %8s %8s" %
      ("FLOOR", "ACCEPT_P", "conf", "silent", "silent-err", "1 ques", "2 ques", "handover"))
for floor in (0.02, 0.01, 0.004, 0.001):
    for ap in (0.70, 0.85, 0.95):
        for mode in ("calibrated", "flat"):
            CFG["FLOOR"] = floor
            CFG["ACCEPT_P"] = ap
            random.seed(5)
            s = sweep(ISO, 1, mode)
            seen = s["n"] - s["blind"]
            q = s["q"]
            n0 = sum(1 for x in q if x == 0)
            n1 = sum(1 for x in q if x == 1)
            n2 = sum(1 for x in q if x == 2)
            print("%8.3f %9.2f %8s %8s %9s %8s %8s %8s" % (
                floor, ap, mode, pc(n0, seen), pc(s["wrong"], seen),
                pc(n1, seen), pc(n2, seen), pc(s["ho"], seen)))
    print()

CFG["FLOOR"] = 0.004
CFG["ACCEPT_P"] = 0.85
CFG["ACCEPT_R"] = 8.0

print("=" * 108)
print("D.  END-TO-END, tuned (FLOOR=%.3f ACCEPT_P=%.2f), budget %d questions" % (CFG["FLOOR"], CFG["ACCEPT_P"], MAXQ))
print("=" * 108)
for mode in ("calibrated", "flat"):
    for n_err in (1, 2):
        print("\n--- confidence=%s  errors=%d ---" % (mode, n_err))
        print("%-9s %6s %8s %8s %10s %8s %9s %8s %8s" %
              ("format", "N", "blind", "SILENT", "silent-err", "1 ques", "2 ques", "handover", "ms p50"))
        for f in FMTS:
            random.seed(31)
            s = sweep(f, n_err, mode)
            seen = s["n"] - s["blind"]
            q = s["q"]
            n0 = sum(1 for x in q if x == 0)
            n1 = sum(1 for x in q if x == 1)
            n2 = sum(1 for x in q if x == 2)
            print("%-9s %6d %8s %8s %10s %8s %9s %8s %8.2f" % (
                f.name, s["n"], pc(s["blind"], s["n"]), pc(n0, seen), pc(s["wrong"], seen),
                pc(n1, seen), pc(n2, seen), pc(s["ho"], seen),
                statistics.median(s["ms"]) if s["ms"] else -1))

print()
print("=" * 108)
print("E.  QUESTION-SELECTION POLICY: max-marginal-entropy vs 'first position where top-2 differ'")
print("=" * 108)
print("%-9s %6s %14s %14s %14s %14s" % ("format", "errors", "ent 1-ques", "top2 1-ques", "ent solved", "top2 solved"))
for f in (ISO, VIN, NHS, IBANGB, LUHN16):
    for ne in (1, 2):
        row = []
        for pol in ("entropy", "top2diff"):
            random.seed(77)
            s = sweep(f, ne, "calibrated", policy=pol)
            seen = s["n"] - s["blind"]
            n1 = sum(1 for x in s["q"] if x == 1)
            row.append((pc(n1, seen), pc(s["ok"], seen)))
        print("%-9s %6d %14s %14s %14s %14s" % (f.name, ne, row[0][0], row[1][0], row[0][1], row[1][1]))
