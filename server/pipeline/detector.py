"""Four cues over the tape, and the ARM/IDLE state machine (ARCHITECTURE.md 3.6).

The detector answers two different questions with the same four cues, and the
difference between them is the whole design:

    >= 1 cue   ARM.    Rewrite the keyterm bias and the endpointing so the
                       recogniser is listening for a code. Invisible, reversible,
                       costs nothing if wrong.
    >= 2 cues  COMMIT. Only now may anything be written down or spoken.

One cue is allowed to arm because arming has no user-visible failure mode: a
false arm biases the recogniser toward NATO words for twelve seconds during a
conversation that contains none, and then decays. Two are required before a
capture, because each cue on its own has a known false-positive population --
"delta" is an airline, a phone number has ten digits, and someone reading a date
aloud has the rhythm of dictation.

**Cue independence is a precondition, not a nicety.** 2-of-4 is only worth 2-of-4
if the cues fail independently. That is why cue (b) counts NATO words and the
"X for Y" frame and deliberately does *not* count runs of letter-names: those are
already what cue (c) fires on, and counting the same evidence twice silently
turns 2-of-4 back into 1-of-4.

That was stated, and guarded on one axis only. On the (c)-vs-(d) axis the same
collapse was total: `NHS.A(i)` is every digit at all ten positions, so cue (d)
fires on ANY ten digits at distance 0 and is not a statement about the run's
content at all -- it is a statement about the run's LENGTH, which is a property of
the very words cue (c) timed. Measured: the shape cue fires 0/300 at run lengths
6-9 and 300/300 at every length 10-19, and 0.7070 of 8,000 generated
non-identifier utterances reached the COMMIT gate, every one of them on
rhythm+shape alone, 0.1782 of them carrying a window a real check digit accepts.
So `evaluate` reports two sets: `cues`, what fired, which is what ARM counts; and
`commit_cues`, what fired *independently*, which is what COMMIT counts. They
differ only where `shape_is_evidence` says the mask could not have rejected the
window it matched. docs/FINDINGS.md 7.

**This is not the second-signal rule.** 2-of-4 gates the *capture*; the
second-signal rule (3.8) gates the *format assertion* and needs a carrier phrase,
a registered owner-code prefix, or LLM format-ID at >= 0.8. Rhythm plus NATO
opens this gate and does not open that one, which is correct: they are evidence
that someone is spelling something, not evidence of what it is.

**No socket is opened here.** `observe` returns the `UpdateConfiguration` payload
the session manager should push, and returns it only when it differs from what
was last pushed. `observe` also never reads the wall clock -- every deadline is
measured against `tape.now_ms`, the session-relative end of the most recent word.
That is what lets a fixture replayed in three milliseconds exercise the same 12 s
decay as a live call, and it is the reason this file is testable today with no
API key.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from server.pipeline.tape import Tape, Word
from server.readback.normalise import (
    AMBIG,
    DIGIT,
    LETTER,
    MULT,
    NATO,
    TENS,
    _one,          # the single-token reader; imported rather than re-listed,
    pass1,         # because a second copy of the spoken vocabulary would drift
    tokenise,
)
from server.readback.solver import IBANGB, ISO, LUHN16, NHS, VIN, Fmt


class Cue(Enum):
    CARRIER = "carrier"
    SPELLING = "spelling"
    RHYTHM = "rhythm"
    SHAPE = "shape"


class State(Enum):
    IDLE = "idle"
    ARMED = "armed"


# Format identifiers are the enum from the LLM Gateway's json_schema (3.8) so
# that a hypothesis from the detector and one from the LLM are the same string.
# One addition: "luhn16". Card numbers are one of the five formats the product
# claims and the 3.8 schema enum omits them -- add it there when that call is
# wired, or the LLM can never agree with the detector about a card.
FORMATS = ("iso6346", "vin", "iban", "nhs", "luhn16", "catalogue", "booking_ref")


# =============================================================================
# (a) Carrier phrases -- high precision, frequently absent
# =============================================================================
# Precision is the point: nobody says "container number" by accident. Recall is
# poor and known to be poor, because in a real call the identifier arrives as an
# answer ("...four one five eight zero zero five") to a question asked ten
# seconds earlier by a speaker whose audio may not even be on this socket.
#
# The value is None where a phrase says "a code is coming" without saying which,
# which is still worth a cue and still worth the keyterm.
#
# **Every phrase here has to be one nobody utters by accident, and two of them
# were not.** `booking` and `container is` were in this table and both are
# ordinary language in exactly the call this runs on -- "the booking or the
# customs one", "the container is late". Measured on
# tests/fixtures/conversation_no_identifier.json, bare `booking` matched twice in
# 124 s of conversation containing no identifier, and because rhythm also fires 3
# times on that fixture (cv 0.167-0.336, inside the dictation distribution and so
# not separable by threshold), carrier+rhythm opened the 2-of-4 COMMIT gate on
# pure conversation. Nothing was captured only because the shape cue found no
# run -- which is 2-of-4 collapsed to 1-of-1, the failure the module docstring
# warns about, reached from the other side.
#
# Recall is the thing being spent here and that is the right trade: a missed
# carrier costs one cue, while a false one also *names the format* (`fmt =
# carrier[1]` below) and that assertion propagates. The two-word forms survive;
# "booking reference" and "container number" are said on purpose.
# tests/test_detector_falsepos.py holds this shut.
CARRIERS: dict[str, str | None] = {
    "container number": "iso6346",
    "box number": "iso6346",
    "equipment number": "iso6346",
    "unit number": "iso6346",
    "iban": "iban",
    "account number": "iban",
    "sort code": "iban",
    "vin": "vin",
    "chassis number": "vin",
    "vehicle identification": "vin",
    "nhs number": "nhs",
    "patient number": "nhs",
    "card number": "luhn16",
    "part number": "catalogue",
    "stock code": "catalogue",
    "sku": "catalogue",
    "booking reference": "booking_ref",
    "reference number": "booking_ref",
    "it reads": None,
    "reads as": None,
    "spelled": None,
}

# Longest first, so a phrase that is a prefix of a longer one never shadows it
# and the returned format is the more specific one.
_CARRIER_RE = re.compile(
    r"\b(?:%s)\b" % "|".join(re.escape(p) for p in sorted(CARRIERS, key=len, reverse=True)),
    re.I,
)


def carrier_cue(text: str) -> tuple[str, str | None] | None:
    """The last carrier phrase in the window, with its format hypothesis.

    Last, not first: two identifiers can sit inside one 45 s window, and when
    they do the later carrier is the one that governs what is being said now.
    """
    hits = _CARRIER_RE.findall(_flatten(text))
    if not hits:
        return None
    phrase = hits[-1].lower()
    return phrase, CARRIERS.get(phrase)


# =============================================================================
# (b) Spelling vocabulary -- the most reliable indicator of a mode switch
# =============================================================================
# A single NATO word is not evidence. Nineteen of the twenty-six are ordinary
# English words or common given names -- alpha, delta, echo, golf, hotel, india,
# kilo, lima, mike, november, oscar, papa, quebec, romeo, sierra, tango, uniform,
# victor, yankee -- and a logistics call is exactly the place where "delta" and
# "hotel" and "uniform" turn up meaning themselves. Two inside a short span is a
# different thing: the birthday-problem arithmetic on conversational unigrams
# makes two of them landing within five tokens vanishingly unlikely by accident.
NATO_MIN = 2
NATO_SPAN = 5

# The "X for Y" frame fires on its own. "B for Bravo" has no conversational use
# at all; it exists only to disambiguate a character. normalise.tokenise already
# folds "as in" / "like in" to "asin", so the frame words are single tokens here.
_FRAME_WORDS = frozenset({"for", "asin", "like", "wie", "come", "de"})


def spelling_cue(tokens: Sequence[str]) -> tuple[int, int]:
    """(NATO words inside the tightest span, count of "X for Y" frames)."""
    nato_at = [i for i, t in enumerate(tokens) if t in NATO]
    best = 0
    for k, i in enumerate(nato_at):
        j = k
        while j + 1 < len(nato_at) and nato_at[j + 1] - i < NATO_SPAN:
            j += 1
        best = max(best, j - k + 1)

    frames = sum(1 for i in range(1, len(tokens) - 1) if _frame_at(tokens, i))
    return best, frames


def _frame_at(tokens: Sequence[str], i: int) -> bool:
    """Is "X for Y" here, with X a character and Y naming it?

    The head of a frame is a character, not a word: "B for Bravo", not "thanks
    for calling". That was written as `len(tokens[i - 1]) <= 2`, a proxy for
    "is a character" that is not one -- and the proxy leaks, because plenty of
    two-letter words are not characters. Found by building `date_range_welded`,
    whose opening line is "what window did they give us for the collection":
    `us` is two characters long, so the frame fired and the SPELLING cue voted
    on a sentence about a collection window. Paired with rhythm that is 2-of-4
    on conversation, which is the same shape of defect as the one this change is
    about -- a cue standing on a proxy for its evidence rather than on the
    evidence. Measured on the fixture: 16 commit_ok before, 0 after.

    Both halves are now checked against the normaliser rather than against a
    length. The head must be readable as a single character, and Y must name
    that character -- either by starting with it ("B for Bravo", "S as in
    Sugar") or by reading as it ("four, as in four"). That is the whole of the
    construction: it exists to say which character, so a Y that does not say
    which character is not one.
    """
    if tokens[i] not in _FRAME_WORDS:
        return False
    head = _one(tokens[i - 1])
    if head is None:
        return False
    chars = {c.upper() for c, _w in head}
    tail = tokens[i + 1]
    if tail[:1].upper() in chars:
        return True
    read = _one(tail)
    return read is not None and bool(chars & {c.upper() for c, _w in read})


# =============================================================================
# (c) Spelling rhythm -- the metronome detector
# =============================================================================
# The novel component, and the only cue that fires WHILE the code is still being
# spoken, which is what buys the time to arm before the last character arrives.
# It reads nothing but words[].start, words[].end and a closed-class stoplist, so
# it is content-agnostic and survives every accent -- an accent changes which
# phonemes carry a character, not the fact that a person dictating a code emits
# one character per beat.
RHYTHM_MIN_TOKENS = 5           # 5 tokens = 4 inter-onset intervals; see the note on cv noise
SHORT_RATIO_MIN = 0.80
CV_IOI_MAX = 0.35
IOI_MIN_MS = 180.0
IOI_MAX_MS = 600.0

# A token is "short" by duration, not by spelling. Duration is the accent-proof
# measure: "november" and "en" are both one character of a code and both occupy
# one foot. 500 ms is set from published speaking rates -- dictation runs about
# 2 to 3 characters per second, so a character token including a three-syllable
# NATO word lands at 200-500 ms, while the polysyllabic conversational words that
# never appear inside a code run past it.
#
# PROVISIONAL. This is the one constant here derived from the literature rather
# than from this system's own audio, and it is the first thing to re-fit against
# the live socket. tests/test_detector.py reports how much work it is actually
# doing relative to cv_ioi.
SHORT_MS = 500.0

# Function words are derived by subtraction, and the subtraction is the load-
# bearing part. Half of the closed class is also identifier vocabulary: "a" is A
# or 8, "i" is I, "you" is U or 2, "are" is R, "for" is 4, "to" is 2, "and" is
# the BrE numeric connective, "not" is 0, "be" is B, "o" is 0 or O. A hand-written
# stoplist that keeps any of those can never fire on a real dictation -- "em ess
# kay you four one five" contains three of them. So the stoplist is whatever
# remains after everything the normaliser can read as a character is removed.
_CLOSED_CLASS = frozenset("""
    an the this that these those
    he she it we they me him her us them my your his its our their
    is am was were being been do does did done have has had
    will would shall should may might must can could
    or but so because if then than when while
    of in on at by from with about into over under after before
    what which who whom whose how where
    no yes just really very quite much more most some any all
    okay yeah right well now sorry please thanks
""".split())
_IDENTIFIER_TOKENS = frozenset(LETTER) | frozenset(DIGIT) | frozenset(AMBIG) | frozenset(NATO) | frozenset(MULT)
FUNCTION_WORDS = frozenset(w for w in _CLOSED_CLASS if w not in _IDENTIFIER_TOKENS)


@dataclass(frozen=True, slots=True)
class WindowStats:
    """One slid window, with each criterion's verdict kept separate.

    The four criteria are reported individually rather than collapsed into a
    boolean because which one does the rejecting is a measurable property of the
    detector, and a criterion that is never the sole rejector is a criterion that
    is not earning its place. tests/test_detector.py reports exactly that.
    """

    at: int
    cv_ioi: float
    mean_ioi: float
    short_ratio: float
    function_words: int

    @property
    def ok_cv(self) -> bool:
        return self.cv_ioi < CV_IOI_MAX

    @property
    def ok_mean(self) -> bool:
        return IOI_MIN_MS <= self.mean_ioi <= IOI_MAX_MS

    @property
    def ok_short(self) -> bool:
        return self.short_ratio >= SHORT_RATIO_MIN

    @property
    def ok_fw(self) -> bool:
        return self.function_words == 0

    @property
    def fired(self) -> bool:
        return self.ok_cv and self.ok_mean and self.ok_short and self.ok_fw


@dataclass(frozen=True, slots=True)
class RhythmStats:
    """The best window's numbers, reported whether or not the cue fired.

    "Best" is the lowest cv_ioi over every tested window, which is the window the
    detector came closest to firing on. Returning it unconditionally is what lets
    the test measure the separation between dictation and conversation instead of
    only counting pass/fail.
    """

    fired: bool
    tested: int
    passed: int
    cv_ioi: float
    mean_ioi: float
    short_ratio: float
    function_words: int
    at: int = -1
    last_fired_at: int = -1     # index of the LAST word of the last firing window


_NO_RHYTHM = RhythmStats(False, 0, 0, float("nan"), float("nan"), 0.0, 0)


def rhythm_windows(words: Sequence[Word],
                   min_tokens: int = RHYTHM_MIN_TOKENS) -> list[WindowStats]:
    """Every timeable `min_tokens` window over the timeline.

    Only the minimum window is slid. A longer window can only be more demanding
    -- a code with one hesitation in the middle of it has a ragged 8-token window
    and two clean 5-token ones -- and hesitation mid-code is the normal case, not
    the exception.
    """
    out: list[WindowStats] = []
    for s in range(len(words) - min_tokens + 1):
        win = words[s:s + min_tokens]
        iois = [win[i + 1].start - win[i].start for i in range(len(win) - 1)]
        if any(d <= 0 for d in iois):
            # Non-advancing onsets mean a revised partial or a broken clock, not
            # a fast talker. A window we cannot time does not vote.
            continue
        mean = statistics.fmean(iois)
        out.append(WindowStats(
            at=s,
            cv_ioi=statistics.stdev(iois) / mean,
            mean_ioi=mean,
            # An unknown duration (end <= start) counts as not-short: a cue that
            # cannot be assessed must fail, never pass.
            short_ratio=sum(1 for w in win if 0 < w.duration_ms <= SHORT_MS) / len(win),
            function_words=sum(1 for w in win if _norm(w.text) in FUNCTION_WORDS),
        ))
    return out


def rhythm_cue(words: Sequence[Word], min_tokens: int = RHYTHM_MIN_TOKENS) -> RhythmStats:
    """Fire if any window over the timeline is metronomic."""
    wins = rhythm_windows(words, min_tokens)
    if not wins:
        return _NO_RHYTHM
    best = min(wins, key=lambda w: w.cv_ioi)
    fired = [w for w in wins if w.fired]
    last = (fired[-1].at + min_tokens - 1) if fired else -1
    return RhythmStats(bool(fired), len(wins), len(fired), best.cv_ioi, best.mean_ioi,
                       best.short_ratio, best.function_words, best.at, last)


# =============================================================================
# (d) Format-shaped mask -- a poor trigger, an excellent confirmer
# =============================================================================
# Implemented as a per-position alphabet mask rather than as a literal regex, so
# that the shapes come from the solver's verified Fmt definitions instead of a
# second, drifting copy of them. `fmt.A(i)` is the character class at position i;
# a mismatch count is edit distance under substitution.
#
# It is a poor trigger because NHS is ten digits and Luhn16 is sixteen, and at
# distance 2 that matches a phone number, an order quantity, or a date read
# aloud. It is an excellent confirmer because a window that also passes the check
# digit is not a coincidence: 1 in 11 for ISO 6346, 1 in 97 for IBAN.
SHAPE_FORMATS: tuple[tuple[Fmt, str], ...] = (
    (IBANGB, "iban"), (VIN, "vin"), (LUHN16, "luhn16"), (ISO, "iso6346"), (NHS, "nhs"),
)
SHAPE_MAX_DIST = 2


@dataclass(frozen=True, slots=True)
class ShapeHit:
    fmt: str
    text: str
    at: int
    distance: int
    checksum_ok: bool
    complete: bool          # the window ends at the tail of the tape
    word_last: int          # index of the last word of the run that carried it


@dataclass(frozen=True, slots=True)
class _Run:
    """A maximal stretch of words the normaliser can read as characters."""

    chars: str
    first: int
    last: int
    # The word indices the run actually consumed. NOT range(first, last+1): a
    # filler in the middle of a code is skipped rather than ending the run, so
    # the span is contiguous and the membership is not. The runner needs the
    # membership, because it has to attach each word's confidence to the
    # characters that word produced.
    idx: tuple[int, ...] = ()


# A shape window must never span a word the normaliser could not read. The
# normaliser drops what it cannot read, and dropping is what welds: it reads "i",
# "a", "you", "and", "to", "for", "see", "be" and "o" as characters and discards
# everything between them.
#
# Measured (tests/test_detector.py section B): a 200-word prose corpus collapses
# to 24 characters, and an unsegmented scan matches VIN on them at distance 2 --
# `2ZIUDHNIUUNCGRM3V`, seventeen characters assembled from words spoken tens of
# seconds apart, because VIN's alphabet is 33 of the 36 characters and two
# mismatches are forgiven. Per sentence it never fires; it fires at tape scale,
# which is the only scale this runs at. With runs, none of it fires.
#
# The one thing allowed to bridge a run is a filler, because ARCHITECTURE.md 3.4
# is explicit that the canonical place for a hesitation is the middle of a code.
# A filler is not evidence that the code ended; any other unreadable word is.
_FILLERS = frozenset({"uh", "um", "er", "erm", "ah", "eh", "hmm", "hm", "mm", "sorry"})


def _readable_token(token: str) -> bool:
    return (token in _IDENTIFIER_TOKENS or token in TENS
            or _one(token) is not None)


def _readable(token: str) -> bool:
    """Could the normaliser turn this word into one or more characters?

    Asked of the word the way the normaliser will read it, not the way the
    recogniser wrote it. universal-3-5-pro welds a spoken identifier into one
    formatted word -- "RMSKU4158005", "4158005" -- and `_one()` has one cell per
    token by contract, so asking it about the whole word says "no", the word
    never joins a run, and the shape cue can never fire on live audio. Measured
    2026-09-04: a real reading armed on its carrier and ended with zero
    captures (experiments/day1/FINDINGS-day1.md section 9).

    `tokenise()` splits a code-shaped word into its characters; a word is
    readable iff every piece is. For every ordinary word that is one piece,
    and the answer is what it always was.
    """
    pieces = tokenise(token)
    if not pieces:
        return False
    return all(_readable_token(p) for p in pieces)


def _runs(words: Sequence[Word], armed: bool) -> list[_Run]:
    groups: list[list[int]] = []
    cur: list[int] = []
    for i, w in enumerate(words):
        t = _norm(w.text)
        if _readable(t):
            cur.append(i)
        elif t in _FRAME_WORDS and cur and i + 1 < len(words):
            cur.append(i)                       # "S as in Sugar" is one character
        elif t in _FILLERS:
            continue                            # a hesitation does not end a code
        else:
            if cur:
                groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    out: list[_Run] = []
    for g in groups:
        chars = _normalised_chars(" ".join(words[i].text for i in g), armed)
        if chars:
            out.append(_Run(chars, g[0], g[-1], tuple(g)))
    return out


def readable_runs(words: Sequence[Word], armed: bool = False) -> list[_Run]:
    """The run segmentation, for consumers outside this file.

    The runner solves the string the shape cue fired on, and it has to segment
    the tape the same way to find it. If it re-derived its own segmentation the
    two would drift, and the failure mode is the worst one available: the cue
    reports a container number, the solver is handed a different seventeen
    characters welded out of prose, and both components look correct in
    isolation. One function, one definition of where a code can start.
    """
    return _runs(words, armed)


def shape_cue(words: Sequence[Word], armed: bool = False) -> ShapeHit | None:
    """Best format-shaped window in the normalised tape, at edit distance <= 2.

    Windows are scanned inside runs, never across them.
    """
    runs = _runs(words, armed)
    best: ShapeHit | None = None
    for r, run in enumerate(runs):
        s = run.chars
        tail_run = r == len(runs) - 1
        for fmt, name in SHAPE_FORMATS:
            L = fmt.length
            if len(s) < L:
                continue
            for i in range(len(s) - L + 1):
                win = s[i:i + L]
                d = sum(1 for k, ch in enumerate(win) if ch not in fmt.A(k))
                if d > SHAPE_MAX_DIST:
                    continue
                hit = ShapeHit(name, win, i, d, d == 0 and fmt.ok(win),
                               tail_run and i + L == len(s), run.last)
                if best is None or (hit.checksum_ok, -hit.distance, len(hit.text)) > \
                                   (best.checksum_ok, -best.distance, len(best.text)):
                    best = hit
    return best


# -----------------------------------------------------------------------------
# Whether a shape hit is evidence at all -- the independence precondition
# -----------------------------------------------------------------------------
# The module docstring states the rule this enforces: *2-of-4 is only worth
# 2-of-4 if the cues fail independently*, and it names the one case that was
# guarded -- cue (b) refuses to count runs of letter-names because cue (c)
# already fires on them. The same collapse exists on the shape axis and was not
# guarded, and there it is total rather than partial.
#
# `NHS.A(i)` is "0123456789" at all ten positions and `LUHN16.A(i)` is
# "0123456789" at all sixteen, so the mismatch count in `shape_cue` is
# identically zero for ANY ten (or sixteen) consecutive digits, at every offset,
# for every digit value. Measured, 300 uniform random all-digit runs per length
# read at a fixed 350 ms: the shape cue fires 0/300 at run lengths 6, 7, 8 and 9
# and 300/300 at every length from 10 to 19. The cue is not reporting anything
# about the content of the run. It is reporting the run's length -- a property of
# the very same words cue (c) timed. Two cues, one observation, and the 2-of-4
# COMMIT gate silently becomes 1-of-1 for the formats with no lexical surface to
# fall back on. Measured over 8,000 generated non-identifier utterances (phone
# numbers, dates, times, money, quantities, meter readings, an ISBN): 5,656
# reached the COMMIT gate and every one of them did it on rhythm+shape alone.
#
# The test below is the exact statement of "could this cue have said no?". Take
# the characters the window actually contains and ask whether ANY arrangement of
# them over the format's positions would exceed the forgiveness budget.
# Maximising illegal placements over permutations is a maximum bipartite matching
# on the ILLEGAL (character-slot, position) pairs: any matching of illegal pairs
# extends to a full permutation, and any permutation's illegal positions are
# themselves such a matching, so the two quantities are equal.
#
# If that maximum is <= SHAPE_MAX_DIST, no rearrangement of these characters
# could have failed the mask, and the match carries nothing beyond the length of
# the run. Derived from `Fmt.A(i)` rather than from a literal {"nhs", "luhn16"}
# set, deliberately: a hard-coded set is exactly the drift the `readable_runs`
# docstring above warns about, and it would also miss the case that is not a
# bare-digit format at all -- seventeen digits match VIN at distance 0, because
# VIN's alphabet is uniform and contains every digit. Measured: at run length 17,
# 131 of 300 random digit runs are reported as `vin`, not as `nhs`.
def _augment(c: int, legal: list[list[bool]], match: list[int],
             seen: list[bool]) -> bool:
    """Kuhn's augmenting path, run over the ILLEGAL pairs rather than the legal."""
    for i in range(len(match)):
        if legal[c][i] or seen[i]:
            continue
        seen[i] = True
        if match[i] == -1 or _augment(match[i], legal, match, seen):
            match[i] = c
            return True
    return False


def max_illegal(fmt: Fmt, window: str) -> int:
    """Most positions any arrangement of `window`'s characters could get wrong."""
    legal = [[ch in fmt.A(i) for i in range(fmt.length)] for ch in window]
    match: list[int] = [-1] * fmt.length          # position -> character slot
    total = 0
    for c in range(len(window)):
        if _augment(c, legal, match, [False] * fmt.length):
            total += 1
    return total


def shape_is_evidence(fmt: Fmt, window: str) -> bool:
    """Could this mask have rejected this window, or is it only a length test?

    False means the hit says nothing cue (c) did not already say, so the two must
    not be counted as two. It does NOT mean the window is not an identifier -- a
    genuine NHS number is ten digits and lands here too. It means the shape cue
    is not the instrument that can tell you so, which is what 3.8 says in words:
    never assert a format from shape alone.
    """
    return max_illegal(fmt, window) > SHAPE_MAX_DIST


_FMT_BY_NAME: dict[str, Fmt] = {name: fmt for fmt, name in SHAPE_FORMATS}


def fmt_by_name(name: str) -> Fmt | None:
    """One definition of name -> Fmt, so the runner and this file cannot drift."""
    return _FMT_BY_NAME.get(name)


def _normalised_chars(text: str, armed: bool) -> str:
    """Text -> one character per cell, taking the heaviest reading of each.

    Collapsing the lattice to its argmax is lossy and deliberately so: this cue
    only decides whether something code-shaped is present. The lattice itself is
    preserved for the solver, which is where the ambiguity has to survive.
    """
    cells, _ = _pass1(text, armed)
    out: list[str] = []
    for cell in cells:
        ch = max(cell, key=lambda x: x[1])[0]
        # The two sentinels the normaliser emits for genuinely undecidable arity.
        # For a shape test, take the single-slot reading of each; the solver gets
        # to try both.
        out.append({"__DBL__": "W", "__AND__": "N"}.get(ch, ch))
    return "".join(out)


def _pass1(text: str, armed: bool) -> tuple[list, list]:
    # normalise.pass1 will grow an `armed` flag (3.5: the multiplier, "nought"
    # and "and" expansions run only in ARMED, because in IDLE an ordinary
    # sentence containing "trouble" or "not" is a capture vector). Until it does,
    # the flag is accepted here and dropped, so the call site is already correct.
    return pass1(text)


# =============================================================================
# The four cues together
# =============================================================================
COMMIT_MIN_CUES = 2
ARM_MIN_CUES = 1


@dataclass(frozen=True, slots=True)
class CueReport:
    cues: frozenset[Cue]
    fmt: str | None
    carrier: str | None
    nato: int
    frames: int
    rhythm: RhythmStats
    shape: ShapeHit | None
    function_words: int
    tokens: int
    evidence_ms: int        # when the newest word supporting a cue ended
    # The cues that survive the independence test, which is what COMMIT counts.
    # `cues` is what fired; `commit_cues` is what fired *independently*. They
    # differ by at most one element and only ever in one way: when the shape hit
    # could not have failed its own mask, rhythm and shape are the same
    # observation seen twice and count once. ARM reads `n`, COMMIT reads
    # `commit_n`, and keeping both is what lets the tests report the gap.
    commit_cues: frozenset[Cue] = frozenset()

    @property
    def n(self) -> int:
        return len(self.cues)

    @property
    def commit_n(self) -> int:
        return len(self.commit_cues)

    @property
    def collapsed(self) -> bool:
        """Did the independence test remove a cue that had in fact fired?"""
        return self.commit_n < self.n


_CARRIER_WORDS = frozenset(w for phrase in CARRIERS for w in phrase.split())


def evaluate(words: Sequence[Word], armed: bool = False) -> CueReport:
    """Run all four cues over a word timeline. Pure; no state, no clock."""
    text = " ".join(w.text for w in words if w.text)
    tokens = tokenise(text) if text else []

    carrier = carrier_cue(text)
    nato, frames = spelling_cue(tokens)
    rhythm = rhythm_cue(words)
    shape = shape_cue(words, armed)

    cues: set[Cue] = set()
    if carrier is not None:
        cues.add(Cue.CARRIER)
    if nato >= NATO_MIN or frames >= 1:
        cues.add(Cue.SPELLING)
    if rhythm.fired:
        cues.add(Cue.RHYTHM)
    if shape is not None:
        cues.add(Cue.SHAPE)

    # When the evidence was spoken, not when it was noticed.
    #
    # The arm decays 12 s after the last cue, and a cue evaluated over a 45 s
    # tape keeps firing on an identifier that finished half a minute ago -- so a
    # TTL measured from "the last observation in which a cue fired" never expires
    # at all. It has to be measured from the newest *word* that supports a cue.
    # Each cue reports its own: rhythm the last word of its last firing window,
    # shape the last word of the run that carried the hit, the lexical cues the
    # last word they matched on.
    evidence = 0
    if Cue.RHYTHM in cues and rhythm.last_fired_at >= 0:
        evidence = max(evidence, words[rhythm.last_fired_at].end)
    if Cue.SHAPE in cues and shape is not None:
        evidence = max(evidence, words[shape.word_last].end)
    if cues & {Cue.CARRIER, Cue.SPELLING}:
        lexical = _CARRIER_WORDS | frozenset(NATO) | _FRAME_WORDS
        for w in reversed(words):
            if _norm(w.text) in lexical:
                evidence = max(evidence, w.end)
                break

    # Format hypothesis: the carrier names one outright, the shape only guesses.
    # A carrier with no format attached ("it reads") still leaves the shape free
    # to name it -- that pair is the cheapest way to reach the second-signal rule.
    fmt = None
    if carrier is not None and carrier[1] is not None:
        fmt = carrier[1]
    elif shape is not None:
        fmt = shape.fmt

    # The independence test, applied to the COMMIT count only. ARM is untouched:
    # one cue still arms, arming is invisible and reversible, and a false arm
    # costs a keyterm list for twelve seconds. What is stopped here is two cues
    # standing on one observation in front of the gate that writes and speaks.
    #
    # Only rhythm+shape are collapsed, and only when the shape hit could not have
    # failed its own mask. The carrier and spelling cues read the lexicon and are
    # independent of both by construction -- that is why they, and not a tighter
    # rhythm threshold, are what a bare-digit candidate now has to find.
    commit = set(cues)
    if (Cue.RHYTHM in cues and Cue.SHAPE in cues and shape is not None):
        sfmt = _FMT_BY_NAME.get(shape.fmt)
        if sfmt is not None and not shape_is_evidence(sfmt, shape.text):
            commit.discard(Cue.SHAPE)

    return CueReport(
        cues=frozenset(cues), fmt=fmt,
        carrier=carrier[0] if carrier else None,
        nato=nato, frames=frames, rhythm=rhythm, shape=shape,
        function_words=sum(1 for t in tokens if t in FUNCTION_WORDS),
        tokens=len(tokens), evidence_ms=evidence,
        commit_cues=frozenset(commit),
    )


# =============================================================================
# Keyterms, and the budget that is the reason this state machine exists
# =============================================================================
# **100 keyterms per session, 50 characters each.** That hard limit is the entire
# reason for ARM/IDLE. A static list has to carry NATO (26) plus the digit
# variants (15) plus the carriers (23) just to notice that a code is being read,
# and that leaves no room whatsoever for the ~40 owner-code prefixes or the
# catalogue SKUs that are what actually make the recogniser get the code right.
# The two lists cannot coexist, so the state machine swaps one for the other at
# the moment the conversation stops being a conversation. Nothing else in this
# file would need to exist if the budget were 200.
MAX_KEYTERMS = 100
MAX_KEYTERM_CHARS = 50

NATO_TERMS: tuple[str, ...] = (
    "alfa", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
    "india", "juliett", "kilo", "lima", "mike", "november", "oscar", "papa",
    "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey",
    "x-ray", "yankee", "zulu",
)

# The unusual readings only. Biasing "one".."nine" would spend the budget on
# words the recogniser already has strong priors for; these are the ones it gets
# wrong -- the aviation forms, the BrE/AmE splits, and the multipliers that carry
# a whole extra character each.
DIGIT_TERMS: tuple[str, ...] = (
    "zero", "nought", "naught", "nil", "oh", "niner", "fife", "fower", "tree",
    "ait", "double", "treble", "triple", "zed", "aitch",
)

# Derived from the carrier table rather than written twice, so the phrase the
# detector matches and the phrase the recogniser is biased toward cannot drift
# apart.
CARRIER_TERMS: tuple[str, ...] = tuple(CARRIERS)

# Bootstrap lists. The real ISO source is the frequency-weighted BIC owner-code
# registry (3.9 `owner_code`, week 2); these are the highest-volume prefixes and
# they are here so that the ARMED path is exercisable today.
FORMAT_TOKENS: dict[str, tuple[str, ...]] = {
    "iso6346": (
        "container", "MSKU", "MSCU", "MAEU", "MRKU", "TGHU", "TRHU", "TCNU",
        "TCLU", "TEMU", "TTNU", "CMAU", "CXDU", "GESU", "GLDU", "HLXU", "HLBU",
        "OOLU", "OOCU", "FCIU", "FSCU", "SEGU", "SUDU", "UACU", "APZU", "BEAU",
        "BMOU", "CAIU", "CRXU", "DFSU", "EITU", "EMCU", "INKU", "KKFU", "WHLU",
        "ZCSU", "YMLU", "NYKU", "HJCU", "PONU", "TLLU",
    ),
    "iban": (
        "IBAN", "sort code", "GB", "BARC", "NWBK", "LOYD", "HSBC", "MIDL",
        "ABBY", "RBOS", "TSBS", "SANT", "CITI", "COUT", "HBUK", "NAIA", "BUKB",
        "CLYD", "SRLG", "DABA", "AIBK",
    ),
    "vin": (
        "chassis", "1HG", "1FT", "1G1", "2T1", "3VW", "4T1", "5YJ", "JHM",
        "JN1", "JTD", "KMH", "KNA", "SAJ", "SAL", "VF1", "WAU", "WBA", "WDB",
        "WVW", "ZFF",
    ),
    # NHS numbers are ten digits with no lexical surface at all. Arming for NHS
    # buys the timing changes and nothing else, and saying so is more useful than
    # inventing terms to fill the budget with.
    "nhs": (),
    "luhn16": (),
    # Injected by the session manager from the 40-row catalogue (3.9).
    "catalogue": (),
    "booking_ref": (),
}

FORMAT_PROMPT: dict[str, str] = {
    "iso6346": "The speaker is reading an ISO 6346 shipping container number: "
               "four letters then seven digits, often spelled with the NATO alphabet.",
    "iban": "The speaker is reading a UK IBAN: GB, two digits, a four-letter bank "
            "code, then fourteen digits, often in groups of four.",
    "vin": "The speaker is reading a vehicle identification number: seventeen "
           "characters, no I, O or Q.",
    "nhs": "The speaker is reading an NHS number: ten digits, usually grouped "
           "three, three, four.",
    "luhn16": "The speaker is reading a payment card number: sixteen digits in "
              "groups of four.",
    "catalogue": "The speaker is reading a part number from a catalogue.",
    "booking_ref": "The speaker is reading a booking reference.",
}

# IDLE tolerates the default endpointing. ARMED raises max_turn_silence because
# the canonical place for a >700 ms human pause is the middle of a code, and a
# turn that ends there hands the solver half an identifier. The two ARMED values
# pull in opposite directions on purpose: the silence fallback gets longer, while
# the confidence threshold gets lower so that a turn the model is *sure* has
# ended still closes fast. ForceEndpoint (below) reclaims the rest.
IDLE_MAX_TURN_SILENCE_MS = 1536
ARMED_MAX_TURN_SILENCE_MS = 2500
IDLE_EOT_CONFIDENCE = 0.70
ARMED_EOT_CONFIDENCE = 0.50

# 12 s, measured from the last cue rather than from the moment of arming. It has
# to outlive the identifier, not the trigger: 4.8 gate 7 refuses to speak more
# than 10 s after the identifier's last word, so an arm that expired earlier than
# that would disarm the recogniser while the interruption it exists to support
# is still legal. 12 = 10 + the 1.5 s politeness delay, rounded up.
ARM_TTL_MS = 12_000

# One finalised turn of prose ends the arm early. Three function words cannot
# occur inside a code; one can ("the IBAN is"), which is why the threshold is not
# one. This is what claws back the raised max_turn_silence when the conversation
# moves on, rather than waiting out the full TTL.
TOPIC_CHANGE_FUNCTION_WORDS = 3


def keyterms(state: State, fmt: str | None,
             format_tokens: Mapping[str, Sequence[str]] = FORMAT_TOKENS) -> list[str]:
    """The keyterm list for a state, already inside the 100/50 budget."""
    if state is State.IDLE:
        groups: tuple[Sequence[str], ...] = (CARRIER_TERMS, NATO_TERMS, DIGIT_TERMS)
    elif fmt is None:
        # Armed on rhythm alone, with no idea what is being read. The carriers
        # stay: they are the cheapest thing that could still name the format, and
        # there is nothing to spend the budget on instead.
        groups = (CARRIER_TERMS, NATO_TERMS, DIGIT_TERMS)
    else:
        # With a format in hand the carriers are dropped, and that is the trade
        # the budget forces: we already know a code is being read, so the terms
        # that told us so are the cheapest thing to spend on owner codes.
        groups = (NATO_TERMS, DIGIT_TERMS, tuple(format_tokens.get(fmt, ())))
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for term in group:
            key = term.lower()
            if key in seen or len(term) > MAX_KEYTERM_CHARS:
                continue
            seen.add(key)
            out.append(term)
            if len(out) == MAX_KEYTERMS:
                return out
    return out


def configuration(state: State, fmt: str | None,
                  format_tokens: Mapping[str, Sequence[str]] = FORMAT_TOKENS) -> dict[str, Any]:
    """The payload the session manager pushes. This file never opens a socket.

    Field names are those in 3.6. They are the one thing here that cannot be
    checked without the key, and they are all in this function: if a wire name
    differs, exactly one line changes and no logic moves.
    """
    cfg: dict[str, Any] = {
        "type": "UpdateConfiguration",
        "keyterms_prompt": keyterms(state, fmt, format_tokens),
    }
    if state is State.IDLE:
        cfg["max_turn_silence"] = IDLE_MAX_TURN_SILENCE_MS
        cfg["end_of_turn_confidence_threshold"] = IDLE_EOT_CONFIDENCE
    else:
        cfg["max_turn_silence"] = ARMED_MAX_TURN_SILENCE_MS
        cfg["end_of_turn_confidence_threshold"] = ARMED_EOT_CONFIDENCE
        if fmt in FORMAT_PROMPT:
            cfg["prompt"] = FORMAT_PROMPT[fmt]
    return cfg


# =============================================================================
# The state machine
# =============================================================================
@dataclass(frozen=True, slots=True)
class Verdict:
    state: State
    cues: frozenset[Cue]
    fmt: str | None
    commit_ok: bool
    config: dict[str, Any] | None
    force_endpoint: bool
    reason: str
    report: CueReport

    @property
    def n_cues(self) -> int:
        return len(self.cues)


class Detector:
    """One per session. `observe` on every frame the tape accepts.

    Holds no clock, no socket and no audio. Everything it knows about time comes
    from `tape.now_ms`.
    """

    def __init__(self, *, arm_ttl_ms: int = ARM_TTL_MS,
                 format_tokens: Mapping[str, Sequence[str]] | None = None) -> None:
        self.arm_ttl_ms = arm_ttl_ms
        self.format_tokens: Mapping[str, Sequence[str]] = dict(FORMAT_TOKENS)
        if format_tokens:
            self.format_tokens = {**self.format_tokens, **format_tokens}
        self.state = State.IDLE
        self.fmt: str | None = None
        self._last_cue_ms = 0
        self._now = 0
        # Evidence at or before this moment has already been disarmed on, and
        # may not arm again. Without it the machine oscillates: the identifier
        # stays on the tape for 45 s, so every disarm is followed by an
        # immediate re-arm on the same words, and each flip is a socket write.
        self._rearm_after_ms = -1
        # Seeded with the IDLE payload because that is what the CONNECT frame
        # already carried (3.1). Without the seed the first partial of every
        # session pushes an UpdateConfiguration identical to the connect config.
        self._pushed: dict[str, Any] | None = configuration(State.IDLE, None, self.format_tokens)
        self._seen_finals: set[int] = set()

    # -- the loop -------------------------------------------------------------

    def observe(self, tape: Tape) -> Verdict:
        now = self._now = tape.now_ms
        report = evaluate(tape.words, armed=self.state is State.ARMED)
        reason = ""

        # Always, not only while ARMED: a finalised turn seen for the first time
        # immediately after arming is prose from *before* the trigger, and acting
        # on it would disarm on the same frame that armed.
        prose_turn = self._note_finals(tape)

        if report.n >= ARM_MIN_CUES:
            # Refreshed on every cue, not only on the first: a 22-character IBAN
            # read with two hesitations takes longer than the TTL, and disarming
            # in the middle of it is the one failure this whole component is for.
            # Refreshed to when the evidence was *spoken*, not to now -- see the
            # note on evidence_ms.
            self._last_cue_ms = max(self._last_cue_ms, report.evidence_ms)

        if self.state is State.IDLE:
            # Fresh evidence only. A cue firing on an identifier that finished
            # thirty seconds ago is the tape remembering, not the conversation
            # doing something, and evidence already disarmed on never arms again.
            fresh = (report.evidence_ms > self._rearm_after_ms
                     and now - report.evidence_ms <= self.arm_ttl_ms)
            if report.n >= ARM_MIN_CUES and fresh:
                self.state = State.ARMED
                self.fmt = report.fmt
                reason = "armed on " + ",".join(sorted(c.value for c in report.cues))
        else:
            if report.fmt is not None and report.fmt != self.fmt:
                # A carrier naming a different format mid-arm is a correction,
                # not a second identifier: re-bias rather than wait out the TTL.
                self.fmt = report.fmt
                reason = f"format hypothesis -> {report.fmt}"
            if now - self._last_cue_ms > self.arm_ttl_ms:
                reason = f"decayed after {self.arm_ttl_ms} ms with no cue"
                self._disarm()
            elif prose_turn:
                reason = "topic change"
                self._disarm()

        cfg = self._config_if_changed()
        return Verdict(
            state=self.state,
            cues=report.cues,
            fmt=self.fmt if self.state is State.ARMED else report.fmt,
            commit_ok=report.commit_n >= COMMIT_MIN_CUES,
            config=cfg,
            # ForceEndpoint the moment the candidate is length-complete at the
            # tail of the tape: it closes the turn immediately and claws back the
            # ~1.5 s that the raised max_turn_silence just cost (3.6).
            force_endpoint=(self.state is State.ARMED and report.shape is not None
                            and report.shape.complete and report.shape.distance == 0),
            reason=reason,
            report=report,
        )

    def committed(self) -> dict[str, Any] | None:
        """The session manager calls this once a capture commits. Returns config.

        Disarming here is also what stops the committed identifier -- still on
        the tape for another 45 s -- from arming the machine all over again.
        """
        self._disarm()
        return self._config_if_changed()

    def reset(self) -> None:
        self.state = State.IDLE
        self.fmt = None
        self._last_cue_ms = 0
        self._now = 0
        self._rearm_after_ms = -1
        self._pushed = configuration(State.IDLE, None, self.format_tokens)
        self._seen_finals.clear()

    # -- internals ------------------------------------------------------------

    def _disarm(self) -> None:
        self.state = State.IDLE
        self.fmt = None
        self._rearm_after_ms = self._now

    def _note_finals(self, tape: Tape) -> bool:
        """A whole finalised turn of prose, with no cue of its own, ends the arm.

        Judged on the turn alone rather than on the tape, and that distinction is
        what makes the rule fire at all: the tape still holds the identifier, so
        its cues would keep voting for another 45 s and the arm would only ever
        expire on the TTL.
        """
        changed = False
        turns = tape.turns
        for turn in turns:
            if not turn.end_of_turn or turn.turn_order in self._seen_finals:
                continue
            self._seen_finals.add(turn.turn_order)
            if not turn.words:
                continue
            local = evaluate(turn.words, armed=True)
            if local.n == 0 and local.function_words >= TOPIC_CHANGE_FUNCTION_WORDS:
                changed = True
        if turns:
            # Pruned with the tape, or an hour-long session accumulates one entry
            # per turn for turns nobody can see any more.
            floor = turns[0].turn_order
            self._seen_finals = {o for o in self._seen_finals if o >= floor}
        return changed

    def _config_if_changed(self) -> dict[str, Any] | None:
        """Emit only on a real change. UpdateConfiguration is a socket write, and
        this is called several times per second."""
        cfg = configuration(self.state, self.fmt, self.format_tokens)
        if cfg == self._pushed:
            return None
        self._pushed = cfg
        return cfg


# =============================================================================
def _flatten(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())
