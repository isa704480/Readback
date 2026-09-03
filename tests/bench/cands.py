# cands.py -- the candidate-set question, asked precisely:
# GIVEN a hypothesis that actually contains at least one error, how often does
# radius-1 enumeration return 0 / exactly 1 / 2+ checksum-valid strings, and how
# often is the truth in that set at all?
import sys, random
from collections import Counter
P = r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad"
sys.path.insert(0, P)
from xp import ISO, IBANGB, gen_iso, gen_iban, corrupt, project, pos_post, r1, r2
from accent import ACCENTS, TABLES, BLEND

N = 4000
print("=" * 104)
print("RADIUS-1 CANDIDATE SETS, conditioned on the hypothesis ACTUALLY being wrong.")
print("'valid hyp' = corrupted but still passes the checksum (undetectable).")
print("'truth in set' = the correct string is among the radius-1 repairs.")
print("=" * 104)
for fmt, gen, nm in [(ISO, gen_iso, "ISO6346"), (IBANGB, gen_iban, "IBAN-GB")]:
    print(f"\n  {nm}")
    print(f"  {'p_eff':>7}{'slotfix':>7}{'valid hyp':>11}{'0 cand':>9}{'1 cand':>9}"
          f"{'2+ cand':>9}{'mean|2+':>9}{'truth in':>10}{'r2 saves':>10}")
    for p in (0.01, 0.02, 0.03, 0.05, 0.08, 0.12):
        rng = random.Random(2024)
        st = Counter(); ncsum = 0; nc2 = 0
        for k in range(N):
            acc = list(ACCENTS)[k % 8]
            truth = gen(rng)
            hyp, cf, ne = corrupt(truth, TABLES[acc], p, rng)
            if ne == 0: continue
            h = project(fmt, hyp, BLEND)
            st["wrong"] += 1
            if h == truth:
                st["fixed_by_slot"] += 1; continue
            st["still_wrong"] += 1
            if fmt.ok(h):
                st["valid_hyp"] += 1; continue
            c = r1(fmt, h, set())
            if len(c) == 0:
                st["c0"] += 1
                post = [pos_post(fmt, i, h[i], cf[i], BLEND, set()) for i in range(fmt.length)]
                c2 = r2(fmt, h, post, set())
                st["r2_found"] += (len(c2) > 0)
                st["r2_had_truth"] += (truth in c2)
            elif len(c) == 1:
                st["c1"] += 1; st["c1_truth"] += (c[0] == truth)
            else:
                st["c2"] += 1; ncsum += len(c); nc2 += 1
            if len(c) >= 1: st["truth_in"] += (truth in c)
        d = st["still_wrong"] or 1
        det = d - st["valid_hyp"]                      # detectable by the checksum
        print(f"  {p:>7.3f}{st['fixed_by_slot']/max(st['wrong'],1):>7.3f}"
              f"{st['valid_hyp']/d:11.3f}{st['c0']/max(det,1):9.3f}"
              f"{st['c1']/max(det,1):9.3f}{st['c2']/max(det,1):9.3f}"
              f"{(ncsum/max(nc2,1)):9.1f}{st['truth_in']/max(det,1):10.3f}"
              f"{st['r2_had_truth']/max(st['c0'],1):10.3f}")
    print(f"    (columns 0/1/2+ are conditioned on the checksum actually FAILING;")
    print(f"     'r2 saves' = of the 0-candidate cases, fraction where bounded")
    print(f"     radius-2 recovers the truth)")
