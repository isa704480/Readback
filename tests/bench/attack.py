# attack.py -- red team. Re-measures under assumptions the builder's own
# benchmark held fixed: (1) the confusion table used to CORRUPT is the same one
# used to SCORE; (2) confidence is per-character and correlated with error.
import sys, random, math
S = r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad"
sys.path.insert(0, S)
import rb
from rb import ISO, VIN, NHS, IBANGB, LUHN16, CFG, decide, doubt_order
from bench import GEN
from val import D, L, ISO_LET

W_REAL = dict(rb.W)          # the builder's table, treated as "the world"
CFG["FLOOR"] = 0.004
CFG["ACCEPT_P"] = 0.85
CFG["ACCEPT_R"] = 8.0
MAXQ = 2
SPAN_ERR = 0.06

ALLCH = D + L


def uniform_table():
    return {(a, b): 0.5 for a in ALLCH for b in ALLCH if a != b}


def novel_pairs(k, seed=5):
    """High-weight confusions the scorer's table does NOT contain -- an accent
    the table was never built for."""
    r = random.Random(seed)
    cands = [(a, b) for a in ALLCH for b in ALLCH
             if a != b and (a, b) not in W_REAL and (b, a) not in W_REAL]
    r.shuffle(cands)
    out = {}
    for a, b in cands[:k]:
        out[(a, b)] = 0.60
        out[(b, a)] = 0.60
    return out


def mishear(fmt, truth, n_err, table, rng, only_letters=False, only_digits=False):
    idx = list(range(fmt.length))
    if only_letters:
        idx = [i for i in idx if truth[i].isalpha()]
    if only_digits:
        idx = [i for i in idx if truth[i].isdigit()]
    rng.shuffle(idx)
    h = list(truth)
    hit = []
    for i in idx:
        if len(hit) == n_err:
            break
        A = [c for c in fmt.A(i) if c != truth[i]]
        wts = [table.get((truth[i], c), 0.0) for c in A]
        if sum(wts) <= 0:
            continue
        h[i] = rng.choices(A, weights=wts)[0]
        hit.append(i)
    return "".join(h), sorted(hit)


def confs_for(fmt, truth, hit, mode, rng):
    n = fmt.length
    if mode == "cal":
        return [rng.uniform(.35, .75) if i in hit else rng.uniform(.85, .99) for i in range(n)]
    if mode == "flat":
        return [0.90] * n
    if mode == "inverted":       # model is CONFIDENTLY wrong
        return [rng.uniform(.85, .99) if i in hit else rng.uniform(.55, .85) for i in range(n)]
    if mode == "block":
        # AssemblyAI emits "MSKU" as ONE word: one confidence shared by a whole
        # run of same-type characters. Position->confidence alignment is lost.
        blocks, cur = [], [0]
        for i in range(1, n):
            same = truth[i].isdigit() == truth[i - 1].isdigit()
            if same and len(cur) < 4:
                cur.append(i)
            else:
                blocks.append(cur); cur = [i]
        blocks.append(cur)
        c = [0.0] * n
        for b in blocks:
            v = rng.uniform(.35, .75) if any(i in hit for i in b) else rng.uniform(.85, .99)
            for i in b:
                c[i] = v
        return c
    raise ValueError(mode)


def span_reread(fmt, truth, h, confs, lo, hi, table, rng):
    h = list(h); confs = list(confs)
    for i in range(lo, hi):
        A = [c for c in fmt.A(i) if c != truth[i]]
        wts = [table.get((truth[i], c), 0.0) for c in A]
        if A and sum(wts) > 0 and rng.random() < SPAN_ERR:
            h[i] = rng.choices(A, weights=wts)[0]; confs[i] = rng.uniform(.40, .75)
        else:
            h[i] = truth[i]; confs[i] = rng.uniform(.90, .99)
    return "".join(h), confs


def session(fmt, truth, h, confs, table, rng):
    locked, q, spans = set(), 0, 0
    while True:
        r = decide(fmt, h, confs, locked=frozenset(locked))
        empty = (r["action"] == "FAIL_NOCAND")
        if not empty and r["action"] == "ACCEPT":
            return ("OK" if r["top"] == truth else "WRONG"), q, spans, (q == 0 and spans == 0)
        need = max(r.get("n_amb_eff", 1), r.get("unexplained", 0) + 1) if not empty else 99
        if empty or (spans == 0 and (need > (MAXQ - q) or r.get("plaus", 1.0) < CFG["MIN_PLAUS"])):
            if spans >= 1 or q >= MAXQ:
                return "HANDOVER", q, spans, False
            order = doubt_order(fmt, h, confs, locked=frozenset(locked))[:4]
            lo, hi = min(order), max(order) + 1
            if hi - lo > 6:
                lo, hi = order[0], min(order[0] + 4, fmt.length)
            spans += 1
            h, confs = span_reread(fmt, truth, h, confs, lo, hi, table, rng)
            locked = set(); continue
        if q >= MAXQ:
            return "HANDOVER", q, spans, False
        p = r["ask_pos"]; q += 1
        h = h[:p] + truth[p] + h[p + 1:]
        confs = list(confs); confs[p] = 0.999; locked.add(p)


def run(fmt, n_err=1, mode="cal", scorer=None, world=None, N=400, seed=31,
        only_letters=False, only_digits=False):
    """scorer: table the ALGORITHM believes.  world: table reality uses."""
    rng = random.Random(seed)
    scorer = W_REAL if scorer is None else scorer
    world = W_REAL if world is None else world
    rb.W.clear(); rb.W.update(scorer)
    gen = GEN[fmt.name]
    o = dict(n=0, blind=0, ok=0, wrong=0, silent_wrong=0, silent=0, ho=0, q=0, sp=0)
    while o["n"] < N:
        truth = gen()
        if truth is None or not fmt.ok(truth):
            continue
        h, hit = mishear(fmt, truth, n_err, world, rng, only_letters, only_digits)
        if len(hit) < n_err or h == truth:
            continue
        o["n"] += 1
        if fmt.ok(h):
            o["blind"] += 1              # checksum literally cannot see it
        confs = confs_for(fmt, truth, hit, mode, rng)
        res, q, sp, silent = session(fmt, truth, h, confs, world, rng)
        o["q"] += q; o["sp"] += sp
        if silent:
            o["silent"] += 1
        if res == "OK":
            o["ok"] += 1
        elif res == "WRONG":
            o["wrong"] += 1
            if silent:
                o["silent_wrong"] += 1
        else:
            o["ho"] += 1
    rb.W.clear(); rb.W.update(W_REAL)
    n = o["n"]
    return dict(n=n, blind=100*o["blind"]/n, silent=100*o["silent"]/n,
                correct=100*o["ok"]/n, wrong=100*o["wrong"]/n,
                silent_wrong=100*o["silent_wrong"]/n, ho=100*o["ho"]/n,
                q=o["q"]/n, sp=100*o["sp"]/n)


def row(tag, d):
    print(f"{tag:<34} n={d['n']:<4} blind {d['blind']:5.1f}%  silent {d['silent']:5.1f}%  "
          f"CORRECT {d['correct']:5.1f}%  wrong {d['wrong']:5.1f}%  silent-wrong {d['silent_wrong']:5.1f}%  "
          f"handover {d['ho']:5.1f}%  q/id {d['q']:.2f}  span {d['sp']:4.1f}%")


FM = [ISO, VIN, NHS, IBANGB, LUHN16]

print("=" * 150)
print("E1  ABLATION -- is the confusion table doing work, or is the checksum doing all of it?")
print("    'uniform table' keeps the checksum + confidence, and makes every substitution equally likely.")
print("=" * 150)
UNI = uniform_table()
for f in FM:
    row(f"{f.name}: full", run(f, 1, "cal"))
    row(f"{f.name}: UNIFORM table", run(f, 1, "cal", scorer=UNI))
    row(f"{f.name}: full, flat conf", run(f, 1, "flat"))
    row(f"{f.name}: UNIFORM + flat conf", run(f, 1, "flat", scorer=UNI))
    print()

print("=" * 150)
print("E2  OUT-OF-TABLE ACCENT -- errors drawn from confusions the table does not contain.")
print("=" * 150)
for k, lab in [(12, "12 novel pairs"), (40, "40 novel pairs")]:
    NOV = novel_pairs(k)
    WORLD_MIX = dict(W_REAL); WORLD_MIX.update(NOV)
    for f in [ISO, VIN, NHS]:
        row(f"{f.name}: world={W_REAL} ({lab}) mixed", run(f, 1, "cal", world=WORLD_MIX))
    print()
print("  -- and the pure case: EVERY error comes from an unknown confusion --")
for k in (40,):
    NOV = novel_pairs(k)
    for f in [ISO, VIN, NHS]:
        row(f"{f.name}: 100% unknown-pair errors", run(f, 1, "cal", world=NOV))

print()
print("=" * 150)
print("E3  CONFIDENCE SHAPE -- what the day-1 measurement is actually risking")
print("=" * 150)
for f in FM:
    for m in ("cal", "flat", "block", "inverted"):
        row(f"{f.name}: conf={m}", run(f, 1, m))
    print()
