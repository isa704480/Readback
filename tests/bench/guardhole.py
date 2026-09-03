# guardhole.py -- Is the ent-vs-hybrid gap a strategy difference, or is the
# doubt-budget guard being silently defeated?
#
# The design doc's loop does:
#     if doubt is unexplained -> ASK
#     ask position = argmax marginal entropy
# But when there is exactly ONE valid candidate, the marginal entropy is ZERO
# at every position.  argmax over an all-zero vector has no meaning, and any
# implementation that treats "no entropy to gain" as "nothing to ask about"
# will fall straight through to a silent accept -- defeating the guard in
# exactly the case the guard was written for.
import sys, math, random
from collections import Counter
P = r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad"
sys.path.insert(0, P)
from xp import (ISO, IBANGB, gen_iso, gen_iban, corrupt, project, pos_post,
                r1, r2, Hent, w_of, ACCEPT_P, ACCEPT_R, MIN_EDGE, DOUBT_T)
from accent import ACCENTS, TABLES, BLEND

def trace(fmt, gen, p_err, N, seed=777):
    rng = random.Random(seed)
    st = Counter()
    for k in range(N):
        acc = list(ACCENTS)[k % 8]
        truth = gen(rng)
        hyp, cf, ne = corrupt(truth, TABLES[acc], p_err, rng)
        h = project(fmt, hyp, BLEND)
        locked = set()
        post = [pos_post(fmt, i, h[i], cf[i], BLEND, locked) for i in range(fmt.length)]
        cands = [h] if fmt.ok(h) else r1(fmt, h, locked)
        if not cands and not fmt.ok(h): cands = r2(fmt, h, post, locked)
        if not cands:
            st["nocand"] += 1; continue
        sc = [sum(math.log(max(post[i].get(c[i], 1e-12), 1e-12)) for i in range(fmt.length))
              for c in cands]
        mx = max(sc); ex = [math.exp(s - mx) for s in sc]; Z = sum(ex)
        pr = sorted(((e / Z) for e in ex), reverse=True)
        top = cands[max(range(len(cands)), key=lambda j: ex[j])]
        accept = (len(cands) == 1 or (pr[0] >= ACCEPT_P and pr[0]/max(pr[1],1e-12) >= ACCEPT_R))
        if not accept:
            st["ask_normally"] += 1; continue
        edited = {i for i in range(fmt.length) if top[i] != h[i]}
        doubtful = {i for i in range(fmt.length) if (1.0 - post[i].get(h[i], 0.0)) > DOUBT_T}
        unexplained = doubtful - edited
        if not unexplained:
            st["clean_accept"] += 1
            st["clean_accept_WRONG"] += (top != truth)
            continue
        # guard fires. is there any entropy to maximise?
        marg = [dict() for _ in range(fmt.length)]
        for c, q in zip(cands, [e/Z for e in ex]):
            for i, ch in enumerate(c): marg[i][ch] = marg[i].get(ch, 0.0) + q
        maxH = max(Hent(m) for m in marg)
        if maxH < 1e-9:
            st["GUARD_FIRED_but_zero_entropy"] += 1
            st["GUARD_DEFEATED_and_WRONG"] += (top != truth)
        else:
            st["guard_fired_entropy_available"] += 1
    return st

print("=" * 100)
print("Does the doubt-budget guard get defeated by a zero-entropy candidate set?")
print("Counts are per identifier, at the FIRST decision point (before any question).")
print("=" * 100)
for fmt, gen, nm in [(ISO, gen_iso, "ISO6346"), (IBANGB, gen_iban, "IBAN-GB")]:
    for p_err in (0.05, 0.10, 0.15):
        N = 6000
        st = trace(fmt, gen, p_err, N)
        gz = st["GUARD_FIRED_but_zero_entropy"]
        gw = st["GUARD_DEFEATED_and_WRONG"]
        print(f"\n  {nm}  p={p_err}   N={N}")
        for k in ["clean_accept", "clean_accept_WRONG", "ask_normally",
                  "guard_fired_entropy_available", "GUARD_FIRED_but_zero_entropy",
                  "GUARD_DEFEATED_and_WRONG", "nocand"]:
            print(f"      {k:<32} {st[k]:6d}  ({st[k]/N:6.2%})")
        if gz:
            print(f"      --> of the {gz} identifiers where the guard fired but there was NO")
            print(f"          entropy to maximise, {gw} ({gw/gz:.1%}) would have been written WRONG")
            print(f"          and SILENTLY by an argmax-entropy implementation.")
