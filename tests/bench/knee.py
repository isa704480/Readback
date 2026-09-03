# knee.py -- the doubt threshold governs the three-way trade between SILENCE,
# ACCURACY and SILENT ERRORS.  The design doc fixes DOUBT_T = 0.25 without
# measuring it.  Swept here with the fixed questioner.
import sys, random, statistics
from collections import Counter
P = r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad"
sys.path.insert(0, P)
import xp
from xp import ISO, IBANGB, gen_iso, gen_iban, corrupt, solve
from accent import ACCENTS, TABLES, BLEND

N = 4000
print("=" * 104)
print("DOUBT THRESHOLD SWEEP (fixed questioner, blended table, budget 2, 8 accents pooled)")
print("  DOUBT_T = posterior mass off the heard character above which a position")
print("  counts as doubtful.  Lower = more suspicious = more questions, less silence.")
print("=" * 104)
for fmt, gen, nm in [(ISO, gen_iso, "ISO6346"), (IBANGB, gen_iban, "IBAN-GB")]:
    for p_err in (0.02, 0.05):
        print(f"\n  {nm}  base p={p_err}   (N={N})")
        print(f"  {'DOUBT_T':>8}{'accuracy':>10}{'silent':>9}{'sil.wrong':>11}"
              f"{'q/id':>7}{'handover':>10}{'   silent AND correct':>22}")
        for dt in (0.15, 0.25, 0.40, 0.55, 0.70, 0.85, 1.01):
            xp.DOUBT_T = dt
            rng = random.Random(8080)
            st = Counter(); q = 0
            for k in range(N):
                acc = list(ACCENTS)[k % 8]
                truth = gen(rng)
                hyp, cf, ne = corrupt(truth, TABLES[acc], p_err * ACCENTS[acc]["rate"], rng)
                w, sil, nq, nc, stt = solve(fmt, hyp, list(cf), truth, BLEND,
                                            "post", rng, 2, 0.0, True)
                ok = (w == truth)
                st["ok"] += ok; st["sil"] += sil; st["sw"] += (sil and not ok)
                st["ho"] += (stt == "HANDOVER"); st["sc"] += (sil and ok); q += nq
            print(f"  {dt:>8.2f}{st['ok']/N:10.3f}{st['sil']/N:9.3f}{st['sw']/N:11.4f}"
                  f"{q/N:7.2f}{st['ho']/N:10.3f}{st['sc']/N:22.3f}")
xp.DOUBT_T = 0.25
