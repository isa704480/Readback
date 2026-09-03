import random
# The port left a `sys.path.insert` pointing at the builder's scratchpad here.
# Removed: every import in this module is package-relative, so the line was
# dead, and a developer's absolute temp path on sys.path inside shipped server
# code shadows any module in it -- that directory holds probe.py, smoke.py and
# demo.py. Only the bench harness in arity.py's __main__ ever needed it, and it
# is scoped to that block now.
from .solver import *

NATO = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
 "Alfa Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliett Kilo Lima Mike November "
 "Oscar Papa Quebec Romeo Sierra Tango Uniform Victor Whiskey X-ray Yankee Zulu".split()))
ICAO = {"0":"zero","1":"wun","2":"two","3":"tree","4":"fower","5":"fife",
        "6":"six","7":"seven","8":"ait","9":"niner"}
SAY  = {"0":"zero","1":"one","2":"two","3":"three","4":"four","5":"five",
        "6":"six","7":"seven","8":"eight","9":"nine"}

def spell(c):            # how the AGENT pronounces a character it is offering
    return NATO[c] if c.isalpha() else ICAO[c]

def readback(s):         # how the agent reads a run of characters back
    out=[]; i=0
    while i < len(s):
        if i+1 < len(s) and s[i]==s[i+1] and s[i].isdigit():
            out.append("double "+SAY[s[i]]); i+=2
        elif s[i].isalpha(): out.append(NATO[s[i]]); i+=1
        else: out.append(SAY[s[i]]); i+=1
    return " ".join(out)

def anchor(fmt, h, p, k=3):
    """Positional anchor a human can actually follow: read back what came
    immediately before the doubtful character. Never an ordinal count."""
    if p == 0: return "the very first character"
    lo = max(0, p-k)
    pre = readback(h[lo:p])
    lead = "right after " if lo>0 else "after "
    return lead + pre

def question(fmt, h, r, fmt_label="container number"):
    p = r["ask_pos"]; m = dict(r["marg"])
    ranked = sorted(m.items(), key=lambda kv:-kv[1])
    top, ptop = ranked[0]
    a = anchor(fmt, h, p)
    if len(ranked)==1 or ptop > 0.80:
        form="CONFIRM"
        text = "One thing on that %s -- %s, that's %s, yes?" % (fmt_label, a, spell(top))
        grammar = ["yes","no", spell(top)]
    elif len(ranked)==2 or ranked[1][1] >= 0.20 and (len(ranked)<3 or ranked[2][1] < 0.12):
        form="ALTERNATIVE"
        b = ranked[1][0]
        text = "Quick one -- %s, was that %s or %s?" % (a, spell(top), spell(b))
        grammar = [spell(top), spell(b), top, b]
    else:
        form="RESPELL"
        opts = [spell(c) for c,_ in ranked[:3]]
        text = ("Sorry, one character -- %s, can you give me just that one again? "
                "I have it as %s or %s." % (a, ", ".join(opts[:-1]), opts[-1]))
        grammar = [spell(c) for c,_ in ranked] + [c for c,_ in ranked]
    return dict(form=form, pos=p, text=text, grammar=grammar,
                alts=[(c,round(w,3)) for c,w in ranked[:4]], bits=round(r["ask_H"],2))

if __name__ == "__main__":
    CFG["FLOOR"]=0.004; CFG["ACCEPT_P"]=0.85
    print("="*100); print("N.  THE QUESTION -- generated, not written by hand"); print("="*100)
    CASES = [
      (ISO,"container number","MSKU4198005","MSKU4158005",[.97,.96,.95,.97,.94,.93,.52,.95,.9,.92,.94]),
      (ISO,"container number","TGHU7X89231".replace("X","4"),None,[.9]*11),
      (ISO,"container number","CSQU3054383","CSQU3054383",[.95]*11),
      (NHS,"NHS number","9434765919","9434765919",[.9]*10),
      (NHS,"NHS number","9434765918","9434765919",[.96,.95,.93,.94,.9,.92,.95,.93,.94,.45]),
      (ISO,"container number","MSNU4158005","MSKU4158005",[.95,.94,.55,.96,.93,.9,.92,.95,.93,.9,.94]),
      (ISO,"container number","MSKU4158O05","MSKU4158005",[.95]*11),
      (VIN,"VIN","1HGCM82633A004352","1HGCM82633A004352",[.9]*17),
      (VIN,"VIN","1HGCN82633A004352","1HGCM82633A004352",[.96,.94,.92,.95,.48,.93,.9,.94,.95,.9,.92,.95,.93,.9,.94,.92,.95]),
      (IBANGB,"account number","GB82WEST12345698765432","GB82WEST12345698765432",[.9]*22),
    ]
    for fmt,label,heard,truth,cf in CASES:
        r = decide(fmt, heard, cf)
        print("\nheard      : %s   (valid=%s)" % (heard, fmt.ok(heard)))
        print("action     : %s   candidates=%d  top=%s p=%.3f" %
              (r["action"], r.get("n_cand",0), r.get("top"), r.get("post_top",0)))
        if r["action"]=="ACCEPT":
            print("SAYS       : <nothing>   writes %s%s" % (r["top"],
                  "  (silently corrected)" if r["top"]!=heard else ""))
        elif r["action"]=="FAIL_NOCAND":
            print("SAYS       : <span re-read>")
        else:
            q = question(fmt, heard, r, label)
            print("ask pos    : %d  H=%.2f bits  alts=%s" % (q["pos"]+1, q["bits"], q["alts"]))
            print("form       : %s" % q["form"])
            print('SAYS       : "%s"' % q["text"])
            if truth:
                h2 = heard[:q["pos"]]+truth[q["pos"]]+heard[q["pos"]+1:]
                cf2=list(cf); cf2[q["pos"]]=0.999
                r2 = decide(fmt,h2,cf2,locked=frozenset({q["pos"]}))
                print("after ans  : %s -> %s  correct=%s" % (r2["action"], r2.get("top"), r2.get("top")==truth))
                if r2["action"]=="ACCEPT":
                    print('CLOSES     : "%s. Got it."' % readback(r2["top"]))
