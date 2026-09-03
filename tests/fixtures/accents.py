# accent.py -- accent-conditioned confusion model over spoken alphanumerics.
#
# PROVENANCE, stated plainly: the BASE table is the prior already used by rb.py
# (E-set / A-set / F-set / I-set rhyme groups, standard letter-confusion
# structure).  The ACCENT AMPLIFIERS are phonological priors, not measured ASR
# outputs -- each one is annotated with the phonological fact it encodes.  They
# are hypotheses about WHICH pairs move, and the experiment is designed so that
# the solver never sees them.  Magnitudes are guesses; the experiment reports
# sensitivity to them.
import sys
sys.path.insert(0, r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad")
from rb import W as BASE_W          # symmetric-ish dict[(true,heard)] -> weight
D = '0123456789'
L = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
FULL = D + L

# --------------------------------------------------------------- accents ----
# mult : multiply an existing base pair (applied both directions)
# add  : set a pair to at least this weight (both directions)
# rate : per-character error-rate multiplier vs General American.
#        Grounded in the well-replicated finding that ASR word error rate rises
#        substantially for L2 and non-mainstream varieties.
ACCENTS = {
 "en-US": dict(rate=1.00, mult={}, add={}, note="General American. Z='zee' -> Z sits IN the E-set. Reference."),

 "en-GB": dict(rate=1.05, note="RP/Southern British. Z='zed' leaves the E-set; non-rhotic R='ah'.",
    mult={("C","Z"):0.15, ("V","Z"):0.20, ("Z","E"):0.20, ("G","Z"):0.25, ("D","Z"):1.60,
          ("A","R"):3.00},
    add ={("Z","S"):0.30}),

 "en-AU": dict(rate=1.15, note="Australian. Z='zed', H='haitch', non-rhotic, DRESS/KIT raising.",
    mult={("C","Z"):0.15, ("V","Z"):0.20, ("Z","E"):0.20, ("D","Z"):1.60,
          ("A","R"):3.00, ("H","8"):1.60, ("A","H"):1.40, ("E","I"):2.20, ("Y","I"):1.30},
    add ={}),

 "en-GB-scot": dict(rate=1.25, note="Scottish. Rhotic (R stays distinct), KIT centralised, monophthongs.",
    mult={("C","Z"):0.15, ("V","Z"):0.20, ("Z","E"):0.20, ("D","Z"):1.60,
          ("E","I"):2.50, ("Y","I"):1.40, ("A","8"):0.70},
    add ={("U","O"):0.25}),

 "en-US-south": dict(rate=1.15, note="Southern US. PIN/PEN merger collapses front vowels; nasal levelling.",
    mult={("E","I"):3.00, ("M","N"):1.35, ("5","9"):1.20, ("Y","I"):1.30},
    add ={("N","I"):0.20}),

 "en-IN": dict(rate=1.60, note="Indian English. /v/-/w/ merge to a labiodental approximant; retroflex stops; /p/-/f/ variability; Z='zed'.",
    mult={("W","V"):5.00, ("D","T"):2.20, ("C","Z"):0.20, ("Z","E"):0.25,
          ("D","Z"):1.40, ("T","3"):1.30},
    add ={("P","F"):0.55, ("W","2"):0.30, ("V","B"):0.55}),

 "es-L1": dict(rate=1.90, note="Spanish L1. /b/-/v/ merger is categorical; no phonemic /z/; no /I/-/i/ contrast; J = velar fricative.",
    mult={("B","V"):2.20, ("E","I"):2.20, ("Y","I"):1.40, ("J","H"):2.00, ("V","E"):0.60},
    add ={("Z","S"):0.80, ("J","G"):0.45, ("A","8"):0.75}),

 "zh-L1": dict(rate=2.00, note="Mandarin L1. /l/-/n/ and /l/-/r/ instability, /v/ -> /w/, coda reduction.",
    mult={("L","N"):2.00, ("W","V"):4.00, ("S","F"):1.30, ("L","M"):1.40},
    add ={("L","R"):0.60, ("N","R"):0.25, ("S","3"):0.30}),
}

def build_table(acc):
    """Accent-conditioned generative confusion table."""
    spec = ACCENTS[acc]
    T = dict(BASE_W)
    for (a, b), m in spec.get("mult", {}).items():
        for k in ((a, b), (b, a)):
            if k in T: T[k] = min(0.99, T[k] * m)
    for (a, b), v in spec.get("add", {}).items():
        for k in ((a, b), (b, a)):
            T[k] = max(T.get(k, 0.0), v)
    return T

TABLES = {a: build_table(a) for a in ACCENTS}

# BLENDED table = what a builder should actually ship: the mean over accents.
BLEND = {}
_keys = set()
for t in TABLES.values(): _keys |= set(t)
for k in _keys:
    BLEND[k] = sum(t.get(k, 0.0) for t in TABLES.values()) / len(TABLES)

GENERIC = dict(BASE_W)   # the American-prior table -- what you'd naively ship

# ---------------------------------------------------------- generator --------
GEN_FLOOR = 0.010   # every off-diagonal pair has SOME mass, so the corpus
                    # contains confusions the solver's table does not know.

def gen_dist(table, t):
    """P(heard = x | true = t) shape over the FULL 36-char space, minus t."""
    return {x: table.get((t, x), 0.0) + GEN_FLOOR for x in FULL if x != t}

if __name__ == "__main__":
    import random
    random.seed(0)
    print("=== accent tables: what actually moves ===\n")
    probes = [("Z","C"),("Z","D"),("Z","S"),("W","V"),("B","V"),("E","I"),
              ("L","N"),("D","T"),("A","R"),("P","F"),("M","N"),("S","F")]
    hdr = "pair   " + "".join(f"{a:>12s}" for a in ACCENTS)
    print(hdr); print("-"*len(hdr))
    for p in probes:
        row = f"{p[0]}/{p[1]}    "
        for a in ACCENTS:
            row += f"{TABLES[a].get(p,0.0):12.2f}"
        print(row)
    print()
    # how much generative mass is on pairs the GENERIC solver table does not have
    for a in ACCENTS:
        unk = 0.0; tot = 0.0
        for t in FULL:
            d = gen_dist(TABLES[a], t)
            s = sum(d.values())
            for x, v in d.items():
                tot += v
                if GENERIC.get((t, x), 0.0) <= 0.0: unk += v
        print(f"  {a:12s} rate x{ACCENTS[a]['rate']:.2f}   "
              f"{unk/tot:5.1%} of generated error mass is on pairs ABSENT from the generic solver table")
