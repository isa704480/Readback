# qstrat.py -- WHICH POSITION SHOULD THE AGENT ASK ABOUT?
# Max marginal entropy is greedy-optimal for INFORMATION, but the product's
# objective is P(resolved within the remaining budget), which is not the same
# thing.  Measured head-to-head.
import sys, math, random, statistics
from collections import Counter
P = r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad"
sys.path.insert(0, P)
from xp import (ISO, IBANGB, gen_iso, gen_iban, corrupt, project, pos_post,
                r1, r2, Hent, w_of, ACCEPT_P, ACCEPT_R, MIN_EDGE, DOUBT_T)
from accent import ACCENTS, TABLES, BLEND, GENERIC


def solve_q(fmt, hyp_raw, confs, truth, table, rng, strat, budget=2):
    h = project(fmt, hyp_raw, table)
    locked, nq = set(), 0
    while True:
        post = [pos_post(fmt, i, h[i], confs[i], table, locked) for i in range(fmt.length)]
        cands = [h] if fmt.ok(h) else r1(fmt, h, locked)
        if not cands and not fmt.ok(h): cands = r2(fmt, h, post, locked)
        if not cands: return h, nq, "NOCAND"
        sc = [sum(math.log(max(post[i].get(c[i], 1e-12), 1e-12)) for i in range(fmt.length))
              for c in cands]
        mx = max(sc); ex = [math.exp(s - mx) for s in sc]; Z = sum(ex)
        pr = [e / Z for e in ex]
        o = sorted(range(len(cands)), key=lambda k: -pr[k])
        cands = [cands[k] for k in o]; pr = [pr[k] for k in o]
        top = cands[0]
        act = "ACCEPT" if (len(cands) == 1 or
                           (pr[0] >= ACCEPT_P and pr[0] / max(pr[1], 1e-12) >= ACCEPT_R)) else "ASK"
        edited = {i for i in range(fmt.length) if top[i] != h[i]}
        if act == "ACCEPT":
            doubtful = {i for i in range(fmt.length)
                        if i not in locked and (1.0 - post[i].get(h[i], 0.0)) > DOUBT_T}
            if doubtful - edited: act = "ASK"
            elif edited and min(w_of(table, top[i], h[i]) for i in edited) < MIN_EDGE:
                return top, nq, "FLAG"
        if act == "ACCEPT": return top, nq, "ACCEPT"
        if nq >= budget:    return top, nq, "HANDOVER"

        avail = [i for i in range(fmt.length) if i not in locked]
        marg = [dict() for _ in range(fmt.length)]
        for c, q in zip(cands, pr):
            for i, ch in enumerate(c): marg[i][ch] = marg[i].get(ch, 0.0) + q

        if strat == "ent":            # max marginal entropy = max information
            p = max(avail, key=lambda i: Hent(marg[i]))
        elif strat == "doubt":        # where the ASR is least trusted
            p = max(avail, key=lambda i: 1.0 - post[i].get(h[i], 0.0))
        elif strat == "top":          # confirm/deny the leading candidate's edit
            cand_e = [i for i in sorted(edited) if i in avail]
            p = cand_e[0] if cand_e else max(avail, key=lambda i: Hent(marg[i]))
        elif strat == "resolve":
            # maximise expected posterior of the winner AFTER the answer:
            # for each position, sum over answers of P(answer) * (mass of the
            # single largest candidate consistent with that answer)
            best, p = -1.0, avail[0]
            for i in avail:
                if len(marg[i]) < 2: continue
                s = 0.0
                for chv, pv in marg[i].items():
                    m = max((q for c, q in zip(cands, pr) if c[i] == chv), default=0.0)
                    s += m                      # P(ans)*[max/P(ans)] telescopes
                if s > best: best, p = s, i
            if best < 0: p = max(avail, key=lambda i: Hent(marg[i]))
        elif strat == "hybrid":
            # If some position carries doubt that the leading candidate does NOT
            # explain, that is the signature of a SECOND error the checksum has
            # already absorbed -- no amount of disambiguating among the valid
            # candidates can help, because none of them is right.  Ask there.
            # Otherwise the candidate set really is the ambiguity: ask at argmax
            # marginal entropy.
            unexp = [i for i in avail
                     if (1.0 - post[i].get(h[i], 0.0)) > DOUBT_T and i not in edited]
            if unexp:
                p = max(unexp, key=lambda i: 1.0 - post[i].get(h[i], 0.0))
            else:
                p = max(avail, key=lambda i: Hent(marg[i]))
        elif strat == "rand":
            cand_d = [i for i in avail if len(marg[i]) > 1]
            p = rng.choice(cand_d) if cand_d else avail[0]
        if len(marg[p]) < 2 and strat not in ("doubt", "hybrid"):
            p = max(avail, key=lambda i: Hent(marg[i]))
            if Hent(marg[p]) < 1e-9: return top, nq, "ACCEPT"

        h = h[:p] + truth[p] + h[p+1:]
        confs = confs[:p] + [0.999] + confs[p+1:]
        locked.add(p); nq += 1


STRATS = ["ent", "doubt", "hybrid"]

if __name__ == "__main__":
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    print("=" * 104)
    print("QUESTION-POSITION STRATEGY, head to head.  Budget = 2 questions.")
    print("  ent     = argmax marginal entropy (the design doc's choice)")
    print("  doubt   = argmax posterior mass sitting off the heard character")
    print("  top     = confirm the leading candidate's own edit")
    print("  resolve = argmax expected posterior of the post-answer winner")
    print("  rand    = uniform over positions where candidates disagree")
    print("=" * 104)
    for fmt, gen, nm in [(ISO, gen_iso, "ISO6346"), (IBANGB, gen_iban, "IBAN-GB")]:
        for p_err in (0.05, 0.10, 0.15):
            print(f"\n  {nm}  per-char error rate {p_err}   (N={N} per cell, "
                  f"pooled over 8 accents, solver uses the BLENDED table)")
            print(f"  {'strategy':<10}{'correct':>9}{'q/id':>8}{'silent':>9}"
                  f"{'sil.wrong':>11}{'handover':>10}")
            base = {}
            for st in STRATS:
                rng = random.Random(4242)
                ok = q = sil = sw = ho = 0
                for k in range(N):
                    acc = list(ACCENTS)[k % 8]
                    truth = gen(rng)
                    hyp, cf, ne = corrupt(truth, TABLES[acc], p_err, rng)
                    w, nq, stt = solve_q(fmt, hyp, list(cf), truth, BLEND, rng, st)
                    ok += (w == truth); q += nq
                    sil += (nq == 0 and stt == "ACCEPT")
                    sw += (nq == 0 and stt == "ACCEPT" and w != truth)
                    ho += (stt == "HANDOVER")
                print(f"  {st:<10}{ok/N:9.3f}{q/N:8.2f}{sil/N:9.3f}{sw/N:11.3f}{ho/N:10.3f}")
