import sys, itertools, random, statistics
from .normalise import tokenise, MULT, _one, pass1, pass2, FRAME, NATO
from .solver import *

def arity_options(text):
    """Every ambiguous-arity token gets a small set of expansions.
    Returns (fixed_cells_builder, n_combos)."""
    toks = tokenise(text)
    slots = []
    i = 0
    while i < len(toks):
        w = toks[i]
        if i + 2 < len(toks) and (FRAME.match(toks[i+1]) or toks[i+1] == "asin"):
            tail = toks[i+2]
            c = NATO.get(tail) or (tail[0].upper() if tail[:1].isalpha() else None)
            if c:
                slots.append([[[(c,1.0)]]]); i += 3; continue
        if w in MULT and i + 1 < len(toks):
            cell = _one(toks[i+1])
            if cell:
                n = MULT[w]
                slots.append([[list(cell) for _ in range(n)],   # multiplier reading
                              [list(cell)]])                    # mis-transcribed word
                i += 2; continue
        if w == "doubleu":
            slots.append([[[("W",1.0)]], [[("0",.5),("O",.5)],[("0",.5),("O",.5)]]])
            i += 1; continue
        if w == "and":
            slots.append([[], [[("N",1.0)]]])
            i += 1; continue
        c = _one(w)
        if c: slots.append([[c]])
        i += 1
    return slots

def lenfix(text, fmt):
    slots = arity_options(text)
    combos = 1
    for s in slots: combos *= len(s)
    hits = []
    for choice in itertools.product(*slots):
        cells = [c for grp in choice for c in grp]
        if len(cells) != fmt.length: continue
        s, conf, tr, n = pass2(cells, fmt.A, fmt.length)
        hits.append((s, conf, fmt.ok(s)))
    return hits, combos

if __name__ == "__main__":
    # The bench harnesses still live in the builder's scratchpad and are not
    # part of the package. Scoped to __main__ so that importing this module
    # never puts an absolute temp path on a running server's sys.path.
    sys.path.insert(0, r"D:/temp/claude/D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762/c09d90d9-a412-4614-b967-92de40b55905/scratchpad")
    print("="*100); print("K.  LENGTH REPAIR by arity backtracking"); print("="*100)
    for utt, fmt, nm in [
      ("one haitch gee see em eight two six treble three ay treble zero four three five two", VIN, "VIN"),
      ("em ess kay you four one five eight double oh five", ISO, "ISO"),
      ("zero zero seven double u nine two one one one one one one one one one", VIN, "VIN"),
    ]:
        hits, combos = lenfix(utt, fmt)
        print("\n[%s] %s" % (nm, utt))
        print("   arity combos enumerated = %d ; length-correct = %d ; valid = %d"
              % (combos, len(hits), sum(1 for _,_,v in hits if v)))
        for s,c,v in hits[:4]:
            print("      %s  valid=%s" % (s, v))

    print(); print("="*100)
    print("L.  DOES THE CHECKSUM POINT AT A POSITION?  positions admitting >=1 valid single repair")
    print("="*100)
    from bench import GEN, FMTS, mishear, confs_for
    random.seed(4)
    print("%-9s %4s %10s %14s %16s" % ("format","L","mean cand","positions hit","frac of positions"))
    for f in FMTS:
        gen = GEN[f.name]; cs=[]; ps=[]
        for _ in range(200):
            t = gen()
            if t is None: continue
            h,hit = mishear(f,t,1)
            if h==t or f.ok(h): continue
            r,_ = repairs_r1(f,h)
            cs.append(len(r)); ps.append(len({i for c in r for i in range(f.length) if c[i]!=h[i]}))
        print("%-9s %4d %10.1f %14.1f %15.0f%%" % (f.name, f.length, statistics.mean(cs),
              statistics.mean(ps), 100*statistics.mean(ps)/f.length))

    print(); print("="*100)
    print("M.  RHYME-CLASS INDEX with cross-class multi-probe (closed-set pre-filter)")
    print("="*100)
    CROSS = {}
    for (a,b),w in W.items():
        if RHYME.get(a) != RHYME.get(b) and w >= 0.15:
            CROSS.setdefault(b,set()).add(a)
    def rsig(s): return "".join(RHYME.get(c,c) for c in s)
    random.seed(3)
    for size in (2000, 46000, 500000):
        cat=set()
        while len(cat)<size: cat.add("".join(random.choice(L+D) for _ in range(6)))
        cat=sorted(cat); idx={}
        for c in cat: idx.setdefault(rsig(c),[]).append(c)
        probe=random.sample(cat,300)
        b1=[];b2=[];r1c=0;r2c=0
        for p in probe:
            h=list(p); i=random.randrange(6)
            A=[c for c in L+D if c!=p[i]]; wts=[W.get((p[i],c),0.0) for c in A]
            if sum(wts)>0: h[i]=random.choices(A,weights=wts)[0]
            h="".join(h)
            base=rsig(h)
            s1=set(idx.get(base,[]))
            sigs={base}
            for j,ch in enumerate(h):
                for alt in CROSS.get(ch,()):
                    sigs.add(base[:j]+RHYME.get(alt,alt)+base[j+1:])
            s2=set()
            for sg in sigs: s2.update(idx.get(sg,[]))
            b1.append(len(s1)); b2.append(len(s2)); r1c+= (p in s1); r2c+= (p in s2)
        print("cat %7d: single-probe bucket %6.1f recall %5.1f%%  |  multi-probe bucket %7.1f recall %5.1f%%  (prune %.0fx)"
              % (size, statistics.mean(b1), 100*r1c/len(probe),
                 statistics.mean(b2), 100*r2c/len(probe), size/max(statistics.mean(b2),1e-9)))
