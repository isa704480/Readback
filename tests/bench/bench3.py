import sys, random, math, time, statistics
sys.path.insert(0, r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad")
from rb import *
from bench import GEN, FMTS, mishear, confs_for

CFG["FLOOR"] = 0.004
CFG["ACCEPT_P"] = 0.85
CFG["ACCEPT_R"] = 8.0
MAXQ = 2
SPAN_ERR = 0.06     # per-char error rate on a short, deliberate re-read of one span


def span_reread(fmt, truth, h, confs, lo, hi):
    """Human re-reads positions [lo,hi). Fresh ASR pass, low error rate."""
    h = list(h)
    confs = list(confs)
    for i in range(lo, hi):
        A = [c for c in fmt.A(i) if c != truth[i]]
        wts = [W.get((truth[i], c), 0.0) for c in A]
        if A and sum(wts) > 0 and random.random() < SPAN_ERR:
            h[i] = random.choices(A, weights=wts)[0]
            confs[i] = random.uniform(0.40, 0.75)
        else:
            h[i] = truth[i]
            confs[i] = random.uniform(0.90, 0.99)
    return "".join(h), confs


def session(fmt, truth, h, confs, policy="entropy", allow_span=True):
    """Full loop.  Returns (outcome, n_char_questions, n_span_rereads)."""
    locked = set()
    q = 0
    spans = 0
    while True:
        r = decide(fmt, h, confs, locked=frozenset(locked))
        empty = (r["action"] == "FAIL_NOCAND")
        if not empty and r["action"] == "ACCEPT":
            return ("OK" if r["top"] == truth else "WRONG"), q, spans
        # A single character question can only resolve ONE position.  If more
        # positions are still ambiguous than we have questions left, or the best
        # repair is acoustically implausible, a character question is the wrong
        # instrument -- ask for a re-read of the narrowest suspect span instead.
        need = max(r.get("n_amb_eff", 1), r.get("unexplained", 0) + 1) if not empty else 99
        if empty or (allow_span and spans == 0 and
                     (need > (MAXQ - q) or r.get("plaus", 1.0) < CFG["MIN_PLAUS"])):
            # nothing repairable at radius 1 -> the whole reading is suspect.
            # ask for a re-read of the narrowest span covering the top doubt mass.
            if spans >= 1 or q >= MAXQ:
                return "HANDOVER", q, spans
            order = doubt_order(fmt, h, confs, locked=frozenset(locked))[:4]
            lo, hi = min(order), max(order) + 1
            if hi - lo > 6:
                lo, hi = order[0], min(order[0] + 4, fmt.length)
            spans += 1
            h, confs = span_reread(fmt, truth, h, confs, lo, hi)
            locked = set()
            continue
        if q >= MAXQ:
            return "HANDOVER", q, spans
        if policy == "entropy":
            p = r["ask_pos"]
        else:
            a = r["cands"][0]
            b = r["cands"][1] if len(r["cands"]) > 1 else None
            p = (next((i for i in range(fmt.length) if a[i] != b[i]), r["ask_pos"])
                 if b else r["ask_pos"])
        q += 1
        h = h[:p] + truth[p] + h[p + 1:]
        confs = list(confs)
        confs[p] = 0.999
        locked.add(p)


def sweep(fmt, n_err, mode, N=350, policy="entropy", allow_span=True, seed=31):
    random.seed(seed)
    gen = GEN[fmt.name]
    o = dict(n=0, blind=0, ok=0, wrong=0, silent_wrong=0, ho=0, q=[], sp=[], ms=[])
    for _ in range(N):
        truth = gen()
        if truth is None or not fmt.ok(truth):
            continue
        h, hit = mishear(fmt, truth, n_err)
        if len(hit) < n_err or h == truth:
            continue
        o["n"] += 1
        if fmt.ok(h):
            o["blind"] += 1
            continue
        cf = confs_for(fmt, hit, mode)
        t0 = time.perf_counter()
        res, q, sp = session(fmt, truth, h, cf, policy, allow_span)
        o["ms"].append((time.perf_counter() - t0) * 1e3)
        o["q"].append(q)
        o["sp"].append(sp)
        if res == "OK":
            o["ok"] += 1
        elif res == "WRONG":
            o["wrong"] += 1
            if q == 0 and sp == 0:
                o["silent_wrong"] += 1
        else:
            o["ho"] += 1
    return o


def pc(a, b):
    return "%5.1f%%" % (100.0 * a / b) if b else "   -  "


print("=" * 112)
print("F.  END-TO-END with span-re-read escape.  budget: %d character questions + 1 span re-read" % MAXQ)
print("    silent = 0 interruptions.  SILENT-WRONG is the safety number that must stay at zero.")
print("=" * 112)
for mode in ("calibrated", "flat"):
    for n_err in (1, 2):
        print("\n--- confidence=%s  errors=%d ---" % (mode, n_err))
        print("%-9s %5s %7s %8s %8s %8s %8s %8s %8s %13s %8s" %
              ("format", "N", "blind", "silent", "1 ques", "2 ques", "span", "handover", "CORRECT", "SILENT-WRONG", "ms p50"))
        for f in FMTS:
            s = sweep(f, n_err, mode)
            seen = s["n"] - s["blind"]
            q, sp = s["q"], s["sp"]
            n0 = sum(1 for a, b in zip(q, sp) if a == 0 and b == 0)
            n1 = sum(1 for a in q if a == 1)
            n2 = sum(1 for a in q if a == 2)
            ns = sum(1 for b in sp if b >= 1)
            print("%-9s %5d %7s %8s %8s %8s %8s %8s %8s %13s %8.2f" % (
                f.name, s["n"], pc(s["blind"], s["n"]), pc(n0, seen), pc(n1, seen), pc(n2, seen),
                pc(ns, seen), pc(s["ho"], seen), pc(s["ok"], seen), pc(s["silent_wrong"], seen),
                statistics.median(s["ms"]) if s["ms"] else -1))

print()
print("=" * 112)
print("G.  QUESTION-SELECTION POLICY  (calibrated confidence, span escape on)")
print("=" * 112)
print("%-9s %7s %14s %14s %14s %14s" % ("format", "errors", "ent CORRECT", "top2 CORRECT", "ent 0-1 ques", "top2 0-1 ques"))
for f in FMTS:
    for ne in (1, 2):
        row = []
        for pol in ("entropy", "top2diff"):
            s = sweep(f, ne, "calibrated", policy=pol, seed=77)
            seen = s["n"] - s["blind"]
            n01 = sum(1 for a, b in zip(s["q"], s["sp"]) if a <= 1 and b == 0)
            row.append((pc(s["ok"], seen), pc(n01, seen)))
        print("%-9s %7d %14s %14s %14s %14s" % (f.name, ne, row[0][0], row[1][0], row[0][1], row[1][1]))

print()
print("=" * 112)
print("H.  FALSE-CORRECTION HAZARD: the speaker reads an identifier that is genuinely INVALID")
print("    (typo on their own paperwork).  How often does the agent silently 'fix' it?")
print("=" * 112)
random.seed(9)
print("%-9s %7s %12s %12s %14s" % ("format", "N", "SILENT-fix", "asks", "FLAG/no-cand"))
for f in FMTS:
    gen = GEN[f.name]
    n = sil = ask = ho = 0
    for _ in range(300):
        t = gen()
        if t is None:
            continue
        # a genuine data error: random position, random legal char, NOT acoustically driven
        i = random.randrange(f.length)
        c = random.choice([x for x in f.A(i) if x != t[i]])
        bad = t[:i] + c + t[i + 1:]
        if f.ok(bad):
            continue
        n += 1
        cf = [random.uniform(0.88, 0.99)] * f.length   # spoken clearly, high confidence
        r = decide(f, bad, cf)
        if r["action"] == "FAIL_NOCAND":
            ho += 1
        elif r["action"] == "ACCEPT":
            sil += 1
        elif r["action"] == "FLAG_IMPLAUSIBLE":
            ho += 1
        else:
            ask += 1
    print("%-9s %7d %12s %12s %12s" % (f.name, n, pc(sil, n), pc(ask, n), pc(ho, n)))

print()
print("=" * 112)
print("I.  CLOSED-SET (catalogue) LAYER: rhyme-class signature index as a pre-filter")
print("=" * 112)
random.seed(3)


def rsig(s):
    return "".join(RHYME.get(c, c) for c in s)


for size in (40, 2000, 46000, 500000):
    cat = set()
    while len(cat) < size:
        cat.add("".join(random.choice(L + D) for _ in range(6)))
    cat = sorted(cat)
    idx = {}
    for c in cat:
        idx.setdefault(rsig(c), []).append(c)
    probe = random.sample(cat, min(200, len(cat)))
    hits = []
    for p in probe:
        h = list(p)
        i = random.randrange(6)
        A = [c for c in L + D if c != p[i]]
        wts = [W.get((p[i], c), 0.0) for c in A]
        if sum(wts) > 0:
            h[i] = random.choices(A, weights=wts)[0]
        h = "".join(h)
        b = idx.get(rsig(h), [])
        hits.append((len(b), p in b))
    mean_b = statistics.mean(x for x, _ in hits)
    recall = sum(1 for _, r in hits if r) / len(hits)
    print("catalogue %7d rows -> mean bucket %8.1f  (prune %6.1fx)   recall of truth %5.1f%%  buckets=%d"
          % (size, mean_b, size / max(mean_b, 1e-9), 100 * recall, len(idx)))
