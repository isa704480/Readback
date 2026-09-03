import sys, random, time
P = r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad"
sys.path.insert(0, P)
from xp import *
from collections import defaultdict

rng = random.Random(3)
print("ISO corpus all valid :", all(ISO.ok(gen_iso(rng)) for _ in range(5000)))
print("IBAN corpus all valid:", all(IBANGB.ok(gen_iban(rng)) for _ in range(2000)))
print("sample ISO ", gen_iso(rng))
print("sample IBAN", gen_iban(rng))

# --- r1 correctness: incremental O(1) update vs brute-force validator ---
for _ in range(400):
    t = gen_iso(rng)
    h, c, n = corrupt(t, TABLES["en-US"], 0.15, rng)
    h = project(ISO, h, GENERIC)
    fast = set(r1(ISO, h, set()))
    brute = set()
    for i in range(11):
        for ch in ISO.alpha[i]:
            if ch == h[i]: continue
            cand = h[:i] + ch + h[i+1:]
            if ISO.ok(cand): brute.add(cand)
    assert fast == brute, (h, sorted(fast ^ brute))
print("ISO  r1 incremental == brute force, 400 cases: OK")

for _ in range(120):
    t = gen_iban(rng)
    h, c, n = corrupt(t, TABLES["zh-L1"], 0.12, rng)
    h = project(IBANGB, h, GENERIC)
    fast = set(r1(IBANGB, h, set()))
    brute = set()
    for i in range(22):
        for ch in IBANGB.alpha[i]:
            if ch == h[i]: continue
            cand = h[:i] + ch + h[i+1:]
            if IBANGB.ok(cand): brute.add(cand)
    assert fast == brute
print("IBAN r1 incremental == brute force, 120 cases: OK")

# --- confidence calibration check ---
buckets = defaultdict(lambda: [0, 0])
for _ in range(4000):
    t = gen_iso(rng)
    h, cs, n = corrupt(t, TABLES["en-US"], 0.12, rng)
    for i in range(11):
        b = round(cs[i] * 10) / 10
        buckets[b][0] += 1
        buckets[b][1] += (h[i] == t[i])
print("\nsimulated ASR confidence calibration: conf bucket -> empirical P(correct)")
for b in sorted(buckets):
    n, k = buckets[b]
    if n > 60: print(f"   {b:.1f} -> {k/n:.3f}   (n={n})")

# --- how many candidates does r1 return? ---
import statistics
for nm, fmt, gen in [("ISO", ISO, gen_iso), ("IBAN", IBANGB, gen_iban)]:
    cs_ = []
    for _ in range(600):
        t = gen(rng)
        h, cf, n = corrupt(t, TABLES["en-US"], 0.10, rng)
        h = project(fmt, h, GENERIC)
        if not fmt.ok(h):
            cs_.append(len(r1(fmt, h, set())))
    print(f"\n{nm}: r1 candidate count on invalid hypotheses  "
          f"mean {statistics.mean(cs_):.1f}  median {statistics.median(cs_):.0f}  "
          f"max {max(cs_)}  zero-candidate {sum(1 for x in cs_ if x==0)/len(cs_):.1%}")

# --- timing ---
t0 = time.time(); M = 400
for _ in range(M):
    t = gen_iso(rng); h, cs, n = corrupt(t, TABLES["en-IN"], 0.12, rng)
    solve(ISO, h, list(cs), t, GENERIC, "post", rng)
print(f"\nISO  solve() mean {1000*(time.time()-t0)/M:.3f} ms")
t0 = time.time()
for _ in range(M):
    t = gen_iban(rng); h, cs, n = corrupt(t, TABLES["en-IN"], 0.12, rng)
    solve(IBANGB, h, list(cs), t, GENERIC, "post", rng)
print(f"IBAN solve() mean {1000*(time.time()-t0)/M:.3f} ms")
