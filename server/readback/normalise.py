# norm.py -- spoken tokens -> slot-typed character lattice.
import re
# The port left a `sys.path.insert` pointing at the builder's scratchpad here.
# Removed: every import in this module is package-relative, so the line was
# dead, and a developer's absolute temp path on sys.path inside shipped server
# code shadows any module in it -- that directory holds probe.py, smoke.py and
# demo.py. Only the bench harness in arity.py's __main__ ever needed it, and it
# is scoped to that block now.

# ---- 1. tokens that are UNAMBIGUOUS once you know they are an identifier ----
LETTER = {
 "ay": "A", "eh": "A", "aye": "A",
 "be": "B", "bee": "B", "b": "B",
 "cee": "C", "c": "C",
 "dee": "D", "de": "D", "d": "D",
 "ee": "E", "e": "E",
 "ef": "F", "eff": "F", "f": "F",
 "gee": "G", "jee": "G", "g": "G",
 "aitch": "H", "haitch": "H", "hatch": "H", "etch": "H", "h": "H",
 "eye": "I", "i": "I",
 "jay": "J", "jai": "J", "j": "J", "yot": "J", "hota": "J", "jota": "J",
 "kay": "K", "ka": "K", "k": "K",
 "el": "L", "ell": "L", "l": "L",
 "em": "M", "emm": "M", "m": "M",
 "en": "N", "n": "N",
 "pea": "P", "pee": "P", "p": "P",
 "cue": "Q", "queue": "Q", "kyu": "Q", "q": "Q",
 "are": "R", "ar": "R", "arr": "R", "r": "R",
 "ess": "S", "es": "S", "s": "S",
 "tea": "T", "tee": "T", "ti": "T", "t": "T",
 "vee": "V", "ve": "V", "v": "V",
 "double u": "W", "double you": "W", "dubya": "W", "doubleyou": "W",
 "veh": "W", "vay": "W", "w": "W",
 "ex": "X", "x-ray": "X", "xray": "X", "x": "X",
 "why": "Y", "wye": "Y", "ypsilon": "Y", "y": "Y",
 "zed": "Z", "zee": "Z", "zeta": "Z", "said": "Z", "zet": "Z", "z": "Z",
}
DIGIT = {
 "zero": "0", "nought": "0", "naught": "0", "not": "0", "knot": "0",
 "nort": "0", "nowt": "0", "nil": "0", "zilch": "0",
 "one": "1", "won": "1", "wun": "1",
 "two": "2", "to": "2", "too": "2", "tu": "2",
 "three": "3", "tree": "3", "free": "3", "sree": "3", "thee": "3",
 "four": "4", "for": "4", "fore": "4", "fower": "4",
 "five": "5", "fife": "5", "hive": "5",
 "six": "6", "sicks": "6", "sics": "6",
 "seven": "7", "sevin": "7",
 "eight": "8", "ate": "8", "ait": "8", "eit": "8",
 "nine": "9", "niner": "9", "nein": "9", "nighn": "9",
}
# ---- 2. tokens that are AMBIGUOUS until the slot type is known -------------
#        (this is the whole "oh -> 0 or O" problem, generalised)
AMBIG = {
 "oh": ("0", "O"), "o": ("0", "O"), "owe": ("0", "O"),
 "you": ("U", "2"), "yoo": ("U", "2"), "ewe": ("U", "2"),
 "a": ("A", "8"), "ay": ("A", "8"),
 "sea": ("C", "6"), "see": ("C", "6"),
 "and": ("N", "+"),        # BrE numeric connective OR the letter N
}
MULT = {"double": 2, "treble": 3, "triple": 3, "trouble": 3, "terrible": 3, "tremble": 3}
FRAME = re.compile(r"^(?:for|as in|like|like in|wie|come|de)$", re.I)
TEENS = {"%d" % (10 + k): ("1%d" % k, "%d0" % (k + 1)) for k in range(3, 10)}
TENS = {"thirteen": ("13", "30"), "fourteen": ("14", "40"), "fifteen": ("15", "50"),
        "sixteen": ("16", "60"), "seventeen": ("17", "70"), "eighteen": ("18", "80"),
        "nineteen": ("19", "90"), "thirty": ("30", "13"), "forty": ("40", "14"),
        "fifty": ("50", "15"), "sixty": ("60", "16"), "seventy": ("70", "17"),
        "eighty": ("80", "18"), "ninety": ("90", "19")}
NATO = {"alfa": "A", "alpha": "A", "bravo": "B", "charlie": "C", "delta": "D", "dixie": "D",
        "echo": "E", "foxtrot": "F", "golf": "G", "hotel": "H", "india": "I",
        "juliett": "J", "juliet": "J", "kilo": "K", "lima": "L", "mike": "M", "mic": "M",
        "november": "N", "oscar": "O", "papa": "P", "poppa": "P", "quebec": "Q",
        "romeo": "R", "sierra": "S", "tango": "T", "uniform": "U", "victor": "V",
        "whiskey": "W", "whisky": "W", "x-ray": "X", "xray": "X", "yankee": "Y", "zulu": "Z"}

Cell = list      # a cell is [(char, weight), ...] -- one output position


def tokenise(text):
    t = text.lower().replace("-", " ").replace(".", " ")
    t = t.replace("double u", "doubleu").replace("double you", "doubleu")
    t = t.replace("x ray", "xray").replace("as in", "asin").replace("like in", "asin")
    return [w for w in re.split(r"[\s,]+", t) if w]


def pass1(text):
    """Token stream -> list of cells, each cell a list of (char, weight).
    Length-correct; slot-type ambiguity is left UNRESOLVED on purpose."""
    toks = tokenise(text)
    out, i, notes = [], 0, []
    while i < len(toks):
        w = toks[i]
        # --- disambiguator frame:  "B for Bravo" / "S as in Sugar" / "B wie Berta"
        if i + 2 < len(toks) and (FRAME.match(toks[i + 1]) or toks[i + 1] == "asin"):
            head, tail = w, toks[i + 2]
            c = NATO.get(tail) or (tail[0].upper() if tail[:1].isalpha() else None)
            if c:
                out.append([(c, 1.0)])
                notes.append("frame '%s %s %s' -> %s" % (head, toks[i + 1], tail, c))
                i += 3
                continue
        # --- multiplier: "double four", "treble seven", "double L"
        if w in MULT and i + 1 < len(toks):
            n = MULT[w]
            nxt = toks[i + 1]
            cell = _one(nxt)
            if cell:
                for _ in range(n):
                    out.append(list(cell))
                notes.append("'%s %s' -> %d x %s" % (w, nxt, n, cell[0][0]))
                i += 2
                continue
        # --- "doubleu": W, or 00 / OO.  Genuinely undecidable until slot-typed.
        if w == "doubleu":
            out.append([("W", 0.55), ("__DBL__", 0.45)])
            notes.append("'double u' ambiguous: W vs 00/OO -- deferred to slot type")
            i += 1
            continue
        # --- teens/tens: emit TWO characters, both readings kept
        if w in TENS:
            a, b = TENS[w]
            out.append([(a[0], 0.62), (b[0], 0.38)])
            out.append([(a[1], 0.62), (b[1], 0.38)])
            notes.append("'%s' -> %s|%s (teens/tens kept ambiguous)" % (w, a, b))
            i += 1
            continue
        # --- BrE numeric connective
        if w == "and":
            out.append([("N", 0.5), ("__AND__", 0.5)])
            notes.append("'and' ambiguous: letter N vs BrE numeric connective")
            i += 1
            continue
        cell = _one(w)
        if cell:
            out.append(cell)
        else:
            notes.append("ignored token '%s'" % w)
        i += 1
    return out, notes


def _one(w):
    if w in NATO and w not in LETTER:
        return [(NATO[w], 1.0)]
    if w in AMBIG:
        a, b = AMBIG[w]
        return [(a, 0.5), (b, 0.5)]
    if w in LETTER:
        return [(LETTER[w], 1.0)]
    if w in DIGIT:
        return [(DIGIT[w], 1.0)]
    if len(w) == 1 and (w.isalpha() or w.isdigit()):
        return [(w.upper(), 1.0)]
    if w.isdigit():                       # formatter leaked "123" through
        return [(w[0], 1.0)]              # (caller should splice the rest)
    return None


def pass2(cells, alpha_at, length):
    """Collapse the lattice against the format's per-position alphabet.
    This is where 'oh' becomes 0 or O, and 'double u' becomes W or 00."""
    # expand __DBL__ (occupies 2 slots) by trying both arities against `length`
    def expand(cs, dbl_as_two):
        out = []
        for c in cs:
            if any(x[0] == "__DBL__" for x in c):
                if dbl_as_two:
                    out.append([("0", .5), ("O", .5)])
                    out.append([("0", .5), ("O", .5)])
                else:
                    out.append([("W", 1.0)])
            elif any(x[0] == "__AND__" for x in c):
                if dbl_as_two:
                    continue                       # connective: contributes nothing
                out.append([("N", 1.0)])
            else:
                out.append(c)
        return out
    for two in (False, True):
        cs = expand(cells, two)
        if len(cs) == length:
            break
    else:
        cs = expand(cells, False)
    res, conf, trace = [], [], []
    for i, c in enumerate(cs[:length]):
        A = alpha_at(i)
        legal = [(ch, w) for ch, w in c if ch in A]
        if not legal:
            legal = sorted(c, key=lambda x: -x[1])[:1]     # keep, flag as impossible
            trace.append("pos %d: '%s' illegal in slot alphabet -> kept, flagged" % (i + 1, legal[0][0]))
        elif len(legal) < len(c):
            trace.append("pos %d: slot type resolved %s -> %s" %
                         (i + 1, "/".join(x[0] for x in c), legal[0][0]))
        z = sum(w for _, w in legal)
        legal = sorted(((ch, w / z) for ch, w in legal), key=lambda x: -x[1])
        res.append(legal[0][0])
        conf.append(legal[0][1])
    return "".join(res), conf, trace, len(cs)


if __name__ == "__main__":
    from .solver import ISO, VIN, NHS
    CASES = [
        ("ISO", ISO, "em ess kay you four one five eight zero zero five"),
        ("ISO", ISO, "M S K U four one five eight double oh five"),
        ("ISO", ISO, "mike sierra kilo uniform four one five eight nought nought five"),
        ("ISO", ISO, "em ess kay you fower one fife ait oh oh fife"),
        ("ISO", ISO, "M for Mike, S for Sugar, K for King, U for Uniform, 4 1 5 8 0 0 5"),
        ("ISO", ISO, "em ess kay you four one five eight oh oh five"),
        ("NHS", NHS, "nine four three, four seven six, five nine one nine"),
        ("NHS", NHS, "niner fower tree fower seven six fife niner one niner"),
        ("VIN", VIN, "one aitch gee sea em eight two six three three ay zero zero four three five two"),
        ("VIN", VIN, "one haitch gee see em eight two six treble three ay treble zero four three five two"),
    ]
    print("=" * 100)
    print("J.  NORMALISER: spoken tokens -> slot-typed characters")
    print("=" * 100)
    for name, fmt, utt in CASES:
        cells, notes = pass1(utt)
        s, conf, trace, n = pass2(cells, fmt.A, fmt.length)
        print("\n[%s] %s" % (name, utt))
        print("   -> %-20s len=%d/%d  valid=%s" % (s, n, fmt.length, fmt.ok(s) if len(s) == fmt.length else "len!"))
        for t in notes + trace:
            print("      . " + t)
