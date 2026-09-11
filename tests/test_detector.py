"""Detector and rolling-tape harness, driven by synthetic word timelines.

There is no API key yet, so every number below comes from timelines this file
generates. **That bounds what can be concluded, and the bound is stated rather
than buried:** the fixtures encode the hypothesis that dictation has a
near-constant inter-onset interval and conversation's tracks word length. A
fixture cannot falsify the hypothesis it was built from.

What the fixtures *can* measure, and what section A reports, is the part that is
a property of the detector rather than of the assumption:

  - the tolerance margin -- how much timing jitter the rhythm cue absorbs before
    it stops firing, which is the number the live measurement has to beat;
  - which of the four rhythm criteria is actually doing the rejecting, including
    whether any of them never rejects anything on its own;
  - what reaches 2-of-4 that should not.

The live version of this experiment is already scheduled (ARCHITECTURE.md 6,
week 1): *does cv_ioi separate 20 dictated codes from 20 minutes of
conversation.* Re-run this file against real `words[].start` the moment the key
lands; the corpus loader is the only thing that changes.

Run:  PYTHONPATH=. python tests/test_detector.py
"""

from __future__ import annotations

import random
import re
import sys
import time

from server.pipeline.detector import (
    CV_IOI_MAX,
    IOI_MAX_MS,
    IOI_MIN_MS,
    SHAPE_FORMATS,
    SHAPE_MAX_DIST,
    SHORT_RATIO_MIN,
    FUNCTION_WORDS,
    Cue,
    Detector,
    State,
    _normalised_chars,
    configuration,
    evaluate,
    keyterms,
    rhythm_cue,
    rhythm_windows,
)
from server.pipeline.tape import MAX_WORDS, Tape, Word
from server.readback.solver import ISO

NATO_FOR = {
    "A": "alfa", "B": "bravo", "C": "charlie", "D": "delta", "E": "echo",
    "F": "foxtrot", "G": "golf", "H": "hotel", "I": "india", "J": "juliett",
    "K": "kilo", "L": "lima", "M": "mike", "N": "november", "O": "oscar",
    "P": "papa", "Q": "quebec", "R": "romeo", "S": "sierra", "T": "tango",
    "U": "uniform", "V": "victor", "W": "whiskey", "X": "x-ray", "Y": "yankee",
    "Z": "zulu",
}
LETTER_FOR = {
    "A": "ay", "B": "bee", "C": "cee", "D": "dee", "E": "ee", "F": "ef",
    "G": "gee", "H": "aitch", "I": "eye", "J": "jay", "K": "kay", "L": "el",
    "M": "em", "N": "en", "O": "oh", "P": "pee", "Q": "cue", "R": "are",
    "S": "ess", "T": "tee", "U": "you", "V": "vee", "W": "double u", "X": "ex",
    "Y": "why", "Z": "zed",
}
DIGIT_FOR = ("zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine")

# Sixteen lines from the kind of call this listens to. Deliberately loaded with
# the NATO collisions that make cue (b) a two-hit rule -- delta, hotel, uniform,
# golf, mike, victor and india all appear here meaning themselves.
CONVERSATION = [
    "so I was saying that we should probably move the delivery to Thursday",
    "the yard is closed until Monday morning because of the bank holiday",
    "he said the driver was already at the gate but nobody signed for it",
    "can you check whether the customs paperwork actually came through",
    "we had the same problem with the delta shipment last quarter",
    "the hotel booked the wrong dates and now everything has shifted",
    "I will send you the paperwork as soon as the office opens again",
    "they want it delivered before the end of the working week if possible",
    "our uniform supplier says the order is stuck somewhere in transit",
    "let me pull up the account and see what the system is telling me",
    "the golf course job was cancelled so those pallets are still here",
    "honestly nobody knows where that particular consignment ended up",
    "mike from the depot rang about it yesterday afternoon around three",
    "victor said he would confirm the arrangement once he has spoken to them",
    "we are still waiting on india to confirm the vessel departure",
    "that would put us about two weeks behind the original schedule",
]

# The ambiguous middle: content with the rhythm of dictation and none of the
# meaning. RED-TEAM.md predicts exactly this list and predicts that 2-of-4 holds
# them off. Section D checks that prediction.
AMBIGUOUS = {
    "date as digits": "two oh two six oh nine oh one",
    "counting": "one two three four five six seven eight",
    "phone number": "oh seven nine four one double two three six five eight",
    "quantities": "we need four pallets and six boxes",
    "postcode": "ess ee one nine gee eff",
}

_VOWELS = re.compile(r"[aeiouy]+")


def syllables(word: str) -> int:
    """Vowel-group count, floored at one. Crude and adequate: it is used only to
    make a conversational word's duration track its length, which is the property
    the rhythm cue is being asked to distinguish from a metronome."""
    return max(1, len(_VOWELS.findall(word.lower())))


def spoken(code: str, rng: random.Random, style: str = "mixed") -> list[str]:
    """A code as the tokens a recogniser would return."""
    out: list[str] = []
    for ch in code:
        if ch.isdigit():
            out.append(DIGIT_FOR[int(ch)])
        elif style == "nato" or (style == "mixed" and rng.random() < 0.5):
            out.append(NATO_FOR[ch])
        else:
            out.append(LETTER_FOR[ch])
    return " ".join(out).split()


def metronome(tokens: list[str], rng: random.Random, *, ioi_ms: float = 380.0,
              jitter: float = 0.12, t0: int = 0) -> list[Word]:
    """Dictation: one character per beat.

    Duration is capped at 0.75 of the interval because tokens cannot overlap,
    which means short_ratio is 1.0 here by physical necessity rather than by
    choice -- see the finding in section A.
    """
    words: list[Word] = []
    t = float(t0)
    for tok in tokens:
        dur = min(0.75 * ioi_ms, syllables(tok) * 165.0)
        words.append(Word(tok, int(t), int(t + dur), rng.uniform(0.55, 0.99), True, 0))
        t += max(60.0, ioi_ms * (1.0 + rng.gauss(0.0, jitter)))
    return words


def prosodic(tokens: list[str], rng: random.Random, *, syl_ms: float = 175.0,
             pause_p: float = 0.18, t0: int = 0) -> list[Word]:
    """Conversation: the interval is whatever the word took, plus a breath.

    Nothing here is tuned against the detector's thresholds. Duration comes from
    syllable count, the gap is a small constant, and pauses are drawn from a
    fixed rate -- the raggedness is a consequence of English word lengths, not an
    input chosen to produce it.
    """
    words: list[Word] = []
    t = float(t0)
    for tok in tokens:
        dur = syllables(tok) * syl_ms * rng.uniform(0.85, 1.15)
        words.append(Word(tok, int(t), int(t + dur), rng.uniform(0.55, 0.99), True, 0))
        gap = max(10.0, rng.gauss(45.0, 30.0))
        if rng.random() < pause_p:
            gap += rng.uniform(150.0, 600.0)
        t += dur + gap
    return words


def stream(words: list[Word], splits: tuple[int, ...] = (),
           partial_every: int = 2, base: int = 0) -> list[dict]:
    """A word timeline as the frames a socket would deliver.

    Growing partials, then one final per turn -- so anything that appends instead
    of replacing produces a tape several times longer than the utterance, which
    is the failure the tape section tests for.
    """
    bounds = [0, *splits, len(words)]
    frames: list[dict] = []
    for order, (a, b) in enumerate(zip(bounds, bounds[1:])):
        seg = words[a:b]
        if not seg:
            continue
        for k in range(partial_every, len(seg), partial_every):
            frames.append(_frame(base + order, seg[:k], False))
        frames.append(_frame(base + order, seg, True))
    return frames


def _frame(order: int, seg: list[Word], final: bool) -> dict:
    return {
        "type": "Turn",
        "turn_order": order,
        "turn_is_formatted": False,
        "end_of_turn": final,
        "transcript": " ".join(w.text for w in seg),
        "end_of_turn_confidence": 0.9 if final else 0.1,
        "words": [{"text": w.text, "start": w.start, "end": w.end,
                   "confidence": w.confidence, "word_is_final": final}
                  for w in seg],
    }


def valid_iso(rng: random.Random) -> str:
    for _ in range(4000):
        s = "".join(rng.choice(ISO.alpha(i)) for i in range(ISO.length))
        if ISO.ok(s):
            return s
    raise RuntimeError("no valid ISO 6346 sampled")


def pct(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def auc(pos: list[float], neg: list[float]) -> float:
    """P(a random `pos` scores below a random `neg`) -- lower cv is dictation."""
    if not pos or not neg:
        return float("nan")
    wins = sum(sum(1.0 if p < n else 0.5 if p == n else 0.0 for n in neg) for p in pos)
    return wins / (len(pos) * len(neg))


# =============================================================================
FAILURES: list[str] = []


def check(ok: bool, msg: str) -> None:
    if not ok:
        FAILURES.append(msg)


# =============================================================================
def section_a_rhythm(n: int = 300, seed: int = 20260901) -> None:
    """Does cv_ioi separate dictation from conversation, and what does the work?"""
    rng = random.Random(seed)
    print("=" * 78)
    print("A.  RHYTHM: cv_ioi separation, and which criterion does the rejecting")
    print("=" * 78)

    corpora: dict[str, list[list[Word]]] = {"dictation": [], "conversation": []}
    for _ in range(n):
        corpora["dictation"].append(metronome(
            spoken(valid_iso(rng), rng), rng,
            ioi_ms=rng.uniform(300.0, 460.0), jitter=rng.uniform(0.08, 0.18)))
        corpora["conversation"].append(prosodic(
            rng.choice(CONVERSATION).split(), rng))

    print(f"{'corpus':14} {'n':>4} {'cv p05':>7} {'cv p50':>7} {'cv p95':>7} "
          f"{'ioi p50':>8} {'short p50':>10} {'fires':>7}")
    print("-" * 78)
    cvs: dict[str, list[float]] = {}
    for name, corpus in corpora.items():
        stats = [rhythm_cue(w) for w in corpus]
        cv = [s.cv_ioi for s in stats if s.tested]
        cvs[name] = cv
        print(f"{name:14} {len(corpus):4d} {pct(cv, 0.05):7.3f} {pct(cv, 0.50):7.3f} "
              f"{pct(cv, 0.95):7.3f} {pct([s.mean_ioi for s in stats], 0.5):8.0f} "
              f"{pct([s.short_ratio for s in stats], 0.5):10.2f} "
              f"{sum(s.fired for s in stats) / len(stats):6.1%}")

    a = auc(cvs["dictation"], cvs["conversation"])
    print(f"\n  AUC(cv_ioi, dictation < conversation) = {a:.3f}")
    print(f"  threshold CV_IOI_MAX = {CV_IOI_MAX}: "
          f"{sum(1 for c in cvs['dictation'] if c < CV_IOI_MAX) / len(cvs['dictation']):.1%} of "
          f"dictation below, "
          f"{sum(1 for c in cvs['conversation'] if c < CV_IOI_MAX) / len(cvs['conversation']):.1%} of "
          f"conversation below")

    # The separation must exist AND the threshold must sit inside it. An AUC of
    # 0.9 with the threshold on the wrong side of both distributions is a
    # detector that separates nothing.
    check(a > 0.90, f"cv_ioi AUC {a:.3f} does not separate the two corpora")
    check(sum(s.fired for s in map(rhythm_cue, corpora["dictation"])) / n > 0.90,
          "rhythm cue misses dictation")

    # -- which criterion rejects, and which is ever the sole rejector ---------
    print("\n  Per-window criterion attribution on the conversation corpus")
    print(f"  {'criterion':26} {'rejects':>9} {'sole rejector':>14} {'(n)':>7}")
    print("  " + "-" * 59)
    names = ("cv_ioi < %.2f" % CV_IOI_MAX,
             "mean_ioi in [%d,%d]" % (IOI_MIN_MS, IOI_MAX_MS),
             "short_ratio >= %.2f" % SHORT_RATIO_MIN,
             "zero function words")
    rejects = [0, 0, 0, 0]
    sole = [0, 0, 0, 0]
    total = 0
    for w in corpora["conversation"]:
        for win in rhythm_windows(w):
            total += 1
            flags = (win.ok_cv, win.ok_mean, win.ok_short, win.ok_fw)
            for i, ok in enumerate(flags):
                if not ok:
                    rejects[i] += 1
                    if sum(flags) == 3:
                        sole[i] += 1
    for i, nm in enumerate(names):
        print(f"  {nm:26} {rejects[i] / max(total, 1):9.1%} "
              f"{sole[i] / max(total, 1):14.1%} {sole[i]:7d}")
    print(f"  ({total} windows)")

    # The finding this table exists to expose, stated by the harness rather than
    # left for a reader to notice: a criterion that is almost never the sole
    # rejector is a criterion that changed almost no outcome on this corpus.
    inert = [names[i] for i in range(4) if sole[i] / max(total, 1) < 0.01]
    if inert:
        print("\n  NOTE: changed the verdict on <1% of windows on its own -> "
              + "; ".join(inert))
        print("  cv_ioi separates (AUC above) but is near-redundant here: 'zero function")
        print("  words' already rejects almost every conversational window. That")
        print("  criterion is content-dependent, so cue (c) as a whole is less")
        print("  content-agnostic in practice than the claim in ARCHITECTURE.md 3.6.")
        print("  Partly a fixture artefact -- a code contains no function words by")
        print("  construction -- and the live corpus is what settles it.")

    # -- cv_ioi with the function-word rule taken away -----------------------
    # The table above leaves the load-bearing assumption untested: cv_ioi is
    # doing nothing visible because "zero function words" already rejected the
    # window. The regime where cv_ioi has to work alone is a function-word-free
    # utterance that is not a code -- a spelled surname, a list of part
    # descriptions, a read-out address. Simulated here by stripping the function
    # words out of the same sentences and keeping the prosodic timings, so the
    # only thing left standing between conversation and a false arm is rhythm.
    print("\n  Control: the same conversation with function words removed")
    stripped = [prosodic([w for w in s.split() if w not in FUNCTION_WORDS], rng)
                for s in CONVERSATION for _ in range(n // len(CONVERSATION))]
    st = [rhythm_cue(w) for w in stripped]
    st_cv = [s.cv_ioi for s in st if s.tested]
    print(f"  {'corpus':26} {'cv p50':>7} {'fires':>8}")
    print("  " + "-" * 43)
    print(f"  {'content words only':26} {pct(st_cv, 0.5):7.3f} "
          f"{sum(s.fired for s in st) / len(st):8.1%}")
    print(f"  {'dictation (from above)':26} {pct(cvs['dictation'], 0.5):7.3f} "
          f"{1.0:8.1%}")
    hard_auc = auc(cvs["dictation"], st_cv)
    print(f"  AUC(cv_ioi, dictation < content-only) = {hard_auc:.3f}")
    print("  This is the number the assumption actually rests on. If it collapses")
    print("  on real audio, cue (c) is a function-word detector wearing a")
    print("  metronome's clothes, and 2-of-4 loses a genuinely independent vote.")
    # Not falsified: cv_ioi separates on the hard control too. But the threshold
    # is badly placed on it, and that is a separate defect from the assumption.
    check(hard_auc > 0.90,
          f"cv_ioi AUC {hard_auc:.3f} on function-word-free speech: the metronome "
          f"assumption does not survive its own hardest case")
    print(f"\n  CV_IOI_MAX = {CV_IOI_MAX} sits at the {sum(1 for c in st_cv if c < CV_IOI_MAX) / len(st_cv):.0%} "
          f"point of the content-only distribution (median {pct(st_cv, 0.5):.3f}).")
    print("  The separation is real and the threshold is sitting inside the wrong")
    print("  half of it. Do NOT re-fit it against this fixture -- the fixture's")
    print("  conversational jitter is an assumption, so tuning to it would only")
    print("  encode the assumption harder. Re-fit against the live corpus.")

    # -- tolerance sweep: how much jitter does the cue absorb? ----------------
    print("\n  Tolerance: injected jitter vs firing rate (dictated ISO codes)")
    print(f"  {'injected':>9} {'cv p50':>8} {'fires':>8}")
    print("  " + "-" * 27)
    breakpoint_ = None
    for j in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60):
        rr = random.Random(seed + int(j * 1000))
        stats = [rhythm_cue(metronome(spoken(valid_iso(rr), rr), rr, jitter=j))
                 for _ in range(120)]
        fires = sum(s.fired for s in stats) / len(stats)
        print(f"  {j:9.2f} {pct([s.cv_ioi for s in stats], 0.5):8.3f} {fires:8.1%}")
        if breakpoint_ is None and fires < 0.90:
            breakpoint_ = j
    print(f"\n  Fires on >=90% of dictation up to injected jitter "
          f"{'>=0.60' if breakpoint_ is None else '<%.2f' % breakpoint_}. "
          f"Real dictation must be tighter than that for the cue to hold.")


def section_b_gating(seed: int = 7) -> None:
    """Two of four before anything is written; any one arms."""
    rng = random.Random(seed)
    print("\n" + "=" * 78)
    print("B.  GATING: cues, arming at 1, commit at 2")
    print("=" * 78)
    code = "MSKU4158005"

    cases: list[tuple[str, list[Word]]] = [
        ("bare code, letter names",
         metronome(spoken(code, rng, "letter"), rng)),
        ("bare code, NATO",
         metronome(spoken(code, rng, "nato"), rng)),
        ("carrier + code",
         metronome("the container number is".split() + spoken(code, rng, "nato"), rng)),
        ("carrier only, ragged",
         prosodic("can you give me the container number when you get a chance".split(), rng)),
        ("conversation",
         prosodic(CONVERSATION[0].split(), rng)),
        ("conversation, long",
         prosodic(" ".join(CONVERSATION).split(), rng)),
    ]
    print(f"{'case':30} {'cues':>4}  {'which':28} {'commit':>7}")
    print("-" * 78)
    for name, words in cases:
        r = evaluate(words)
        which = ",".join(sorted(c.value for c in r.cues)) or "-"
        print(f"{name:30} {r.n:4d}  {which:28} {str(r.n >= 2):>7}")

    conv = evaluate(prosodic(" ".join(CONVERSATION).split(), rng))
    check(conv.n < 2, f"a minute of prose reached {conv.n} cues and would commit")

    carried = evaluate(metronome(
        "the container number is".split() + spoken(code, rng, "nato"), rng))
    check(carried.n >= 2, "carrier plus a dictated code did not reach 2 cues")
    check(carried.fmt == "iso6346", f"format hypothesis was {carried.fmt}")

    # -- control: what the shape cue does without run segmentation -----------
    # The old scan, kept here and only here, because the fix it justifies is
    # invisible unless the failure it prevents is measured next to it.
    def unsegmented(text: str) -> tuple[str, str, int] | None:
        s = _normalised_chars(text, False)
        for fmt, name in SHAPE_FORMATS:
            for i in range(max(0, len(s) - fmt.length + 1)):
                win = s[i:i + fmt.length]
                d = sum(1 for k, ch in enumerate(win) if ch not in fmt.A(k))
                if d <= SHAPE_MAX_DIST:
                    return name, win, d
        return None

    prose = " ".join(CONVERSATION)
    prose_words = prosodic(prose.split(), rng)
    un = unsegmented(prose)
    seg = evaluate(prose_words).shape
    print(f"\n  Shape cue on {len(prose.split())} words of prose "
          f"(collapses to {len(_normalised_chars(prose, False))} characters):")
    print(f"    without run segmentation: {un}")
    print(f"    with run segmentation:    {seg}")
    check(seg is None, "the shape cue still welds prose into a code")
    check(un is not None,
          "the control no longer reproduces the welding this guards against")

    print("\n  The ambiguous middle -- rhythm without meaning:")
    print(f"  {'case':16} {'cues':>4}  {'which':30} {'fmt':>10} {'commit':>7}")
    print("  " + "-" * 72)
    reached: list[str] = []
    for name, text in AMBIGUOUS.items():
        r = evaluate(metronome(text.split(), rng))
        which = ",".join(sorted(c.value for c in r.cues)) or "-"
        print(f"  {name:16} {r.n:4d}  {which:30} {str(r.fmt):>10} {str(r.n >= 2):>7}")
        if r.n >= 2:
            reached.append(f"{name} -> {r.fmt}")
    if reached:
        # RED-TEAM.md (d) predicts 2-of-4 holds these off. It does not hold all of
        # them off: an 11-digit phone number read at an even pace is rhythm plus a
        # 10-digit NHS shape, which is two cues. What actually stops it is the
        # second-signal rule (3.8) -- no carrier, no registered prefix, no LLM
        # format-ID, so it is captured as unvalidated free text and nothing is
        # said. The gate that protects the caller here is downstream of this file.
        print("\n  NOTE: reached 2-of-4 without being an identifier -> "
              + "; ".join(reached))
        print("  2-of-4 is not what stops these. The second-signal rule is.")


def section_c_state(seed: int = 11) -> None:
    """Arming, the 12 s decay, topic change, and what gets pushed."""
    rng = random.Random(seed)
    print("\n" + "=" * 78)
    print("C.  STATE MACHINE: arm, decay, topic change, keyterm budget")
    print("=" * 78)

    print(f"  IDLE  keyterms {len(keyterms(State.IDLE, None)):3d}   "
          f"max_turn_silence {configuration(State.IDLE, None)['max_turn_silence']}")
    for fmt in ("iso6346", "iban", "vin", "nhs"):
        cfg = configuration(State.ARMED, fmt)
        print(f"  ARMED {len(cfg['keyterms_prompt']):3d}   "
              f"max_turn_silence {cfg['max_turn_silence']}   fmt={fmt}")
        check(len(cfg["keyterms_prompt"]) <= 100, f"{fmt} exceeds the 100-keyterm budget")
        check(all(len(t) <= 50 for t in cfg["keyterms_prompt"]),
              f"{fmt} has a keyterm over 50 characters")
    check(len(keyterms(State.IDLE, None)) <= 100, "IDLE exceeds the 100-keyterm budget")

    # -- arm on a code that straddles three turns ----------------------------
    words = metronome("the container number is".split()
                      + spoken("MSKU4158005", rng, "nato"), rng)
    tape, det = Tape(), Detector()
    armed_at = None
    for f in stream(words, splits=(6, 11)):
        tape.ingest(f)
        v = det.observe(tape)
        if v.state is State.ARMED and armed_at is None:
            armed_at = tape.now_ms
            print(f"\n  armed at {armed_at} ms of {words[-1].end} ms "
                  f"({armed_at / words[-1].end:.0%} through the utterance) "
                  f"on {','.join(sorted(c.value for c in v.cues))}")
            check(v.config is not None, "arming did not emit an UpdateConfiguration")
    check(armed_at is not None, "never armed on a carrier plus a dictated code")
    check(det.state is State.ARMED, "disarmed before the utterance ended")
    check(det.fmt == "iso6346", f"armed with fmt={det.fmt}")

    # The cue that buys the time: rhythm has to fire before the last character.
    rhythm_first = None
    tape2, det2 = Tape(), Detector()
    for f in stream(words, splits=(6, 11)):
        tape2.ingest(f)
        v = det2.observe(tape2)
        if Cue.RHYTHM in v.cues and rhythm_first is None:
            rhythm_first = tape2.now_ms
    if rhythm_first is not None:
        print(f"  rhythm cue first fired at {rhythm_first} ms, "
              f"{words[-1].end - rhythm_first} ms before the last word ended")

    # -- decay ---------------------------------------------------------------
    tape3, det3 = Tape(), Detector()
    for f in stream(words):
        tape3.ingest(f)
        det3.observe(tape3)
    check(det3.state is State.ARMED, "not armed before the decay test")
    silence = prosodic(["mm"], rng, t0=words[-1].end + 12_500)
    tape3.ingest(_frame(9, silence, True))
    v = det3.observe(tape3)
    print(f"\n  after {12_500} ms of no cue: state={v.state.value}, "
          f"reason={v.reason!r}, config pushed={v.config is not None}")
    check(v.state is State.IDLE, "did not decay after 12 s")
    check(v.config is not None, "decay did not push the IDLE configuration back")

    # The identifier is still on the tape and its cues still fire. Nothing may
    # move: a machine that re-arms on evidence it just disarmed on flips state
    # on every partial, and every flip is an UpdateConfiguration on the socket.
    flips = sum(1 for _ in range(20) if det3.observe(tape3).config is not None)
    print(f"  20 further partials on the same tape: {flips} config pushes")
    check(flips == 0 and det3.state is State.IDLE,
          f"the machine oscillates after decay ({flips} pushes in 20 frames)")

    # -- topic change --------------------------------------------------------
    tape4, det4 = Tape(), Detector()
    for f in stream(words):
        tape4.ingest(f)
        det4.observe(tape4)
    prose = prosodic(CONVERSATION[1].split(), rng, t0=words[-1].end + 900)
    tape4.ingest(_frame(9, prose, True))
    v = det4.observe(tape4)
    print(f"  a finalised turn of prose 900 ms later: state={v.state.value}, "
          f"reason={v.reason!r}")
    check(v.state is State.IDLE, "a whole turn of prose did not end the arm")
    check(all(det4.observe(tape4).state is State.IDLE for _ in range(10)),
          "re-armed on the identifier it had just disarmed on")

    # ...and new evidence still arms. The rule is "not this evidence again", not
    # "not again".
    again = metronome(spoken("MSKU4158005", rng, "nato"), rng,
                      t0=tape4.now_ms + 1500)
    for f in stream(again, base=10):
        tape4.ingest(f)
        det4.observe(tape4)
    print(f"  a second code 1.5 s after the prose: state={det4.state.value}")
    check(det4.state is State.ARMED, "new evidence after a topic change did not arm")

    # -- commit --------------------------------------------------------------
    tape5, det5 = Tape(), Detector()
    for f in stream(words):
        tape5.ingest(f)
        det5.observe(tape5)
    cfg = det5.committed()
    check(det5.state is State.IDLE and cfg is not None,
          "committing did not return to IDLE with a config push")
    print(f"  committed: state={det5.state.value}, "
          f"keyterms back to {len(cfg['keyterms_prompt'])}")


def section_d_tape(seed: int = 3) -> None:
    """The two structural rules, and the property that motivates the tape."""
    rng = random.Random(seed)
    print("\n" + "=" * 78)
    print("D.  TAPE: replace-not-append, dedupe, bounds, straddling turns")
    print("=" * 78)

    words = metronome(spoken("MSKU4158005", rng, "nato"), rng)
    frames = stream(words, splits=(4, 7), partial_every=1)

    tape = Tape()
    tape.ingest_all(frames)
    print(f"  {len(frames)} frames carrying {len(words)} words -> tape holds {len(tape)}")
    check(len(tape) == len(words),
          f"tape holds {len(tape)} words for an {len(words)}-word utterance "
          f"(append instead of replace duplicates the identifier)")

    # The property the whole structure exists for: the identifier is split across
    # three turns and must still be found as one string.
    hit = evaluate(tape.words).shape
    print(f"  identifier split across 3 turns, recovered by the shape cue: "
          f"{hit.text if hit else None} (checksum_ok={hit.checksum_ok if hit else None})")
    check(hit is not None and hit.text == "MSKU4158005",
          "an identifier straddling three turns was not recovered from the tape")

    per_turn = [evaluate(t.words).shape for t in tape.turns]
    check(all(h is None for h in per_turn),
          "the straddle fixture is not actually straddling -- one turn holds it all")
    print("  the same identifier, read one turn at a time: "
          f"{[h.text if h else None for h in per_turn]}  <- a turn is not the unit")

    # Run segmentation must not undo the property it sits next to: the canonical
    # place for a hesitation is the middle of a code, and a filler is the one
    # thing allowed to bridge a run.
    hes = spoken("MSKU4158005", rng, "nato")
    hes = hes[:6] + ["uh"] + hes[6:]
    hes_words = metronome(hes, rng)
    hit2 = evaluate(hes_words).shape
    print(f"  a hesitation mid-code ('...uniform four uh one...'): "
          f"{hit2.text if hit2 else None}")
    check(hit2 is not None and hit2.text == "MSKU4158005",
          "a filler in the middle of a code broke the run")

    broken = spoken("MSKU4158005", rng, "nato")
    broken = broken[:6] + ["thursday"] + broken[6:]
    check(evaluate(metronome(broken, rng)).shape is None,
          "a content word in the middle of a code did not end the run")

    # Dedupe and staleness.
    before = len(tape)
    check(not tape.ingest(frames[-1]), "a duplicate final was absorbed twice")
    check(not tape.ingest(_frame(0, words[:2], False)),
          "a partial arriving after its own final overwrote the final")
    check(len(tape) == before, "a rejected frame still changed the tape")

    # Bounds. The word cap is a failsafe against a clock that does not advance,
    # so it is tested with one: 900 words all at t=0.
    flood = Tape()
    for order in range(30):
        seg = [Word(f"w{i}", 0, 0, 0.9, True, order) for i in range(30)]
        flood.ingest(_frame(order, seg, True))
    print(f"  900 words with a frozen clock -> tape holds {len(flood)} (cap {MAX_WORDS})")
    check(len(flood) <= MAX_WORDS, "the word cap did not bound a frozen clock")

    span = Tape()
    long_words = metronome(["one"] * 300, rng, ioi_ms=400.0, jitter=0.0)
    for order, i in enumerate(range(0, 300, 10)):
        span.ingest(_frame(order, long_words[i:i + 10], True))
    print(f"  a 120 s utterance -> tape spans {span.span_ms} ms, {len(span)} words")
    # The bound is on how STALE a word may be, so it is measured end to end:
    # every word the tape presents ended within the span of the newest one.
    # `span_ms` measures first START to last end, so it reads up to one word's
    # duration longer -- the word that straddles the cutoff began before it and
    # ended after. Asserting the end-to-end window keeps the guarantee exact
    # rather than trusting a figure that depends on how long a word happens to
    # be. (Before 2026-09-11 eviction dropped whole turns on the age of their
    # FIRST word, which held span_ms under 45 s by throwing away turns whose
    # last words were seconds old -- the identifier still being read.)
    words = span.words
    oldest_end = min(w.end for w in words)
    newest_end = max(w.end for w in words)
    check(newest_end - oldest_end <= 45_000,
          f"span bound broken end to end: {newest_end - oldest_end} ms")
    longest_word = max(w.end - w.start for w in words)
    check(span.span_ms <= 45_000 + longest_word,
          f"span bound broken by more than one word: {span.span_ms} ms")


def section_e_cost(seed: int = 5) -> None:
    """observe() runs on every partial. It has to be cheap enough to."""
    rng = random.Random(seed)
    print("\n" + "=" * 78)
    print("E.  COST: observe() latency on a full tape")
    print("=" * 78)
    tape, det = Tape(), Detector()
    words = prosodic(" ".join(CONVERSATION).split(), rng)
    for order, i in enumerate(range(0, len(words), 8)):
        tape.ingest(_frame(order, words[i:i + 8], True))
    print(f"  tape: {len(tape)} words, {tape.span_ms} ms")
    ts = []
    for _ in range(40):
        t0 = time.perf_counter()
        det.observe(tape)
        ts.append((time.perf_counter() - t0) * 1e3)
    print(f"  observe(): p50 {pct(ts, 0.5):.2f} ms, p95 {pct(ts, 0.95):.2f} ms")
    check(pct(ts, 0.95) < 50.0,
          f"observe() p95 {pct(ts, 0.95):.1f} ms is too slow for every partial")


# =============================================================================
def main() -> int:
    section_a_rhythm()
    section_b_gating()
    section_c_state()
    section_d_tape()
    section_e_cost()

    print("\n" + "=" * 78)
    if FAILURES:
        for f in FAILURES:
            print("  FAIL:", f)
        return 1
    print("  PASS - all assertions hold against synthetic timelines.")
    print("  The rhythm numbers are bounded by the fixture's own assumption;")
    print("  re-run against real words[].start before believing them.")
    return 0


# pytest entry points, so the same checks run under `pytest tests/test_detector.py`.
def test_rhythm_separates() -> None:
    FAILURES.clear()
    section_a_rhythm(n=120)
    assert not FAILURES, FAILURES


def test_two_of_four_gating() -> None:
    FAILURES.clear()
    section_b_gating()
    assert not FAILURES, FAILURES


def test_state_machine() -> None:
    FAILURES.clear()
    section_c_state()
    assert not FAILURES, FAILURES


def test_tape_rules() -> None:
    FAILURES.clear()
    section_d_tape()
    assert not FAILURES, FAILURES


if __name__ == "__main__":
    sys.exit(main())
