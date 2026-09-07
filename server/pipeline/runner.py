"""The loop: source -> tape -> detector -> normalise -> solver -> decider -> capture.

One function, `run_session`, and it is the same function on both sides of the
seam. `/api/demo/replay` hands it a `ReplaySource`; this evening the live path
hands it a `LiveSource`. Nothing in this file asks which it has, which is the
only way the event stream a UI is built against today can be the event stream it
gets tonight.

Three things in here are more than plumbing.

**The runner solves exactly the window the detector fired on.** `shape_cue`
reports a format-shaped stretch of the tape and returns the run and offset it
found it at; the runner takes the cells at that offset rather than scanning for
itself. Two scanners would drift, and the drift is invisible: the cue reports a
container number, the solver is handed a different eleven characters, and both
components look correct in isolation.

**Confidence is attached per position, not per string.** The solver's whole
mechanism is `words[].confidence` localising the doubt, so a normalisation that
loses which word produced which character throws away the substrate. The
alignment walk below reproduces `pass1`'s own multi-token constructions to keep
the mapping, and *checks itself* -- when the check fails the confidences fall
back to the run mean and the event stream says `aligned: false`, because a
silently wrong alignment would look exactly like a working system with a badly
calibrated recogniser.

**Silence is measured, not assumed.** 4.8 gates 4 and 5 need to know how long
the line has been quiet, and the tape's clock cannot answer: it advances only
when a word arrives, so it freezes during exactly the interval being measured.
Silence is read off delivery time instead, and a naturally-ended turn additionally
proves `max_turn_silence` of it -- the endpoint timer firing IS the measurement.
A turn closed by `ForceEndpoint` proves nothing, and is not counted.

**The loop is driven by two things, not one.** A frame arriving is the obvious
one. The other is the clock, and leaving it out made the agent permanently mute:
3.6 sends `ForceEndpoint` the moment a candidate is length-complete, which is the
whole point -- it reclaims the ~1.5 s the raised `max_turn_silence` cost. But a
forced turn proves no silence (above), so the final frame arrives ~150 ms after
the last word with gate 4 unsatisfied, and gates 4 and 5 are conditions on *time
passing*, which no further frame reports because nobody is speaking. Waiting for
a frame to tell us the line went quiet is waiting for the line to stop being
quiet. Measured on `iso_blind_substitution` before the fix: at `speed=0` the
question was asked, at `speed=1.0` it was not, and the live socket has the same
clock as `speed=1.0`. So the frame pump is raced against a deadline, and the
identifier is re-decided when the politeness delay expires whether or not
anything was said.
"""

from __future__ import annotations

import asyncio
import statistics
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from server.pipeline import decider as dec
from server.pipeline import events as ev
from server.pipeline.detector import (
    ARMED_MAX_TURN_SILENCE_MS,
    CARRIERS,
    FORMAT_TOKENS,
    Detector,
    ShapeHit,
    State,
    readable_runs,
    shape_is_evidence,
)
from server.pipeline.store import (
    CaptureRecord,
    CaptureStore,
    NullStore,
    QuestionRecord,
)
from server.pipeline.tape import Tape, Word
from server.readback.normalise import (
    FRAME, MULT, NATO, _one, pass1, pass2, spelled_caps_mask, spelled_letters, tokenise,
)
from server.readback.question import ICAO, SAY
from server.readback.question import NATO as NATO_SPOKEN
from server.readback.question import question as make_question
from server.readback.question import readback
from server.readback.solver import ISO, IBANGB, LUHN16, NHS, VIN, Fmt, decide as solve
from server.readback.solver import blind_alternatives, doubt_order, w_of

# --------------------------------------------------------------- formats -----
FORMATS: Final[dict[str, Fmt]] = {
    "iso6346": ISO, "vin": VIN, "nhs": NHS, "iban": IBANGB, "luhn16": LUHN16,
}
# What the agent calls each format out loud. Never "ISO 6346" -- a clerk on a
# shipping desk says "container number", and 4.7 rule 3 is that the agent mirrors
# the speaker's convention rather than the specification's.
LABELS: Final[dict[str, str]] = {
    "iso6346": "container number", "vin": "VIN", "nhs": "NHS number",
    "iban": "account number", "luhn16": "card number",
}


def _registry(fmt_name: str) -> frozenset[str]:
    """Bootstrap prefix registries for the second-signal rule (3.8).

    Derived from the detector's arming lists rather than written out again: the
    prefixes the recogniser is biased toward and the prefixes that count as a
    registered owner have to be the same set, or arming would improve
    recognition of codes the capture path then refuses. Week 2 replaces this with
    the frequency-weighted `owner_code` table; the shape of the lookup does not
    change.
    """
    return frozenset(
        t.upper() for t in FORMAT_TOKENS.get(fmt_name, ()) if t.isalnum() and t.isupper()
    )


def prefix_signal(fmt_name: str, value: str) -> bool:
    """Is this value's prefix in a registry, as opposed to merely shaped right?

    ISO 6346 owner codes are the first three characters; the fourth is the
    equipment category, which carries no ownership information. IBAN's bank code
    is characters 5-8. VIN's world manufacturer identifier is the first three.
    """
    reg = _registry(fmt_name)
    if not reg:
        return False
    if fmt_name == "iso6346":
        return value[:4].upper() in reg or value[:3].upper() in {r[:3] for r in reg}
    if fmt_name == "iban":
        return value[4:8].upper() in reg
    if fmt_name == "vin":
        return value[:3].upper() in reg
    return False


# ----------------------------------------------------- confidence alignment --
# The three merges `normalise.tokenise` performs on the joined string. They are
# reproduced here because they can span a word boundary -- "double" and "u" are
# two Word objects with two confidences and one character between them -- and a
# per-word tokenisation would miss them. The joined-string result is the
# authority; this list exists so the per-word walk can agree with it.
_TOKEN_MERGES: Final[dict[tuple[str, str], str]] = {
    ("double", "u"): "doubleu", ("double", "you"): "doubleu",
    ("x", "ray"): "xray", ("as", "in"): "asin", ("like", "in"): "asin",
}


@dataclass(frozen=True, slots=True)
class Aligned:
    """One run's cells, with each cell's ASR confidence and source word."""

    cells: list[list[tuple[str, float]]]
    confs: list[float]
    words: list[int]            # index into the tape's word list, per cell
    ok: bool                    # False when the walk could not match pass1
    # True when one recogniser word produced BLOCK_CELLS_PER_WORD or more of
    # these cells: the confidences are then one number copied per position,
    # not per-position doubt, and the decider must treat them as ARCH 3.7's
    # BLOCK regime for this candidate whatever the session-wide detector
    # says. Measured 2026-09-04: universal-3-5-pro returns a spoken
    # identifier as one formatted word, so on live audio this is the common
    # case, and RegimeDetector's 40-word window never fills in a short call.
    block: bool = False


# The most cells a per-character speaker's single word ever yields is three
# ("treble four"). Four from one word means the recogniser welded a spelling
# into a code, and its one confidence is the whole block's.
BLOCK_CELLS_PER_WORD: Final = 4


def align_run(words: Sequence[Word], idx: Sequence[int]) -> Aligned:
    """Attach a confidence and a source word to every cell `pass1` produces.

    The cells come from one `pass1` call over the whole run, which is the same
    call `_normalised_chars` makes, so the characters the runner solves are
    byte-identical to the characters the cue matched. Only the *mapping* is
    derived here, by walking the same multi-token constructions `pass1` walks
    and asking it how many cells each one produced.
    """
    run_words = [words[i] for i in idx]
    text = " ".join(w.text for w in run_words)
    cells, _notes = pass1(text)

    toks = _merge_tokens(run_words)
    mean = statistics.fmean([w.confidence for w in run_words]) if run_words else 0.0
    # Unaligned, so no per-word count; the average is the honest proxy.
    welded_on_average = bool(run_words) and len(cells) >= BLOCK_CELLS_PER_WORD * len(run_words)
    spread = Aligned(cells, [mean] * len(cells), [idx[-1]] * len(cells) if idx else [],
                     ok=False, block=welded_on_average)
    if [t for t, _c, _w in toks] != tokenise(text):
        return spread

    confs: list[float] = []
    owners: list[int] = []
    i = 0
    while i < len(toks):
        size = _group_size(toks, i)
        piece = " ".join(t for t, _c, _w in toks[i:i + size])
        produced, _n = pass1(piece)
        # The character-bearing token is the last of every multi-token
        # construction pass1 has -- "B for Bravo" carries it in "Bravo",
        # "double four" in "four" -- so the group's confidence is its last
        # token's, not an average that would dilute the one that matters.
        _tok, conf, word = toks[i + size - 1]
        confs.extend([conf] * len(produced))
        # `word` counts within the run; `idx` maps that back to the tape. Both
        # are ints and neither is checkable by eye, which is how this shipped
        # wrong once: a run-local index read as a tape index puts a candidate's
        # "last word" on some earlier word of an earlier code, so the ambient
        # gates measure their silence from the wrong moment and every question
        # about a second identifier arrives already too late (4.8 gate 7).
        # Caught by the two-identifier session in tests/test_pipeline_e2e.py,
        # which is the only case where the two indices differ enough to matter.
        owners.extend([idx[word]] * len(produced))
        i += size
    if len(confs) != len(cells):
        return spread
    welded = max(Counter(owners).values(), default=0) >= BLOCK_CELLS_PER_WORD
    return Aligned(cells, confs, owners, ok=True, block=welded)


def _merge_tokens(run_words: Sequence[Word]) -> list[tuple[str, float, int]]:
    flat: list[tuple[str, float, int]] = []
    # Per word, but the spelled-caps judgement needs the neighbours: "RM" beside
    # "4158005" is two letters, "RM" alone is a word tokenise() leaves whole.
    # Ask over the run first so the per-word tokens concatenate to exactly
    # tokenise(joined text) -- the consistency check in align_run demands it.
    spelled = spelled_caps_mask([w.text for w in run_words])
    for j, w in enumerate(run_words):
        for t in (spelled_letters(w.text) if spelled[j] else tokenise(w.text)):
            flat.append((t, w.confidence, j))
    out: list[tuple[str, float, int]] = []
    i = 0
    while i < len(flat):
        if i + 1 < len(flat):
            merged = _TOKEN_MERGES.get((flat[i][0], flat[i + 1][0]))
            if merged is not None:
                out.append((merged, max(flat[i][1], flat[i + 1][1]), flat[i + 1][2]))
                i += 2
                continue
        out.append(flat[i])
        i += 1
    return out


def _group_size(toks: Sequence[tuple[str, float, int]], i: int) -> int:
    """How many tokens `pass1` consumes starting at i. Mirrors its own loop."""
    t = toks[i][0]
    if i + 2 < len(toks) and (FRAME.match(toks[i + 1][0]) or toks[i + 1][0] == "asin"):
        tail = toks[i + 2][0]
        if NATO.get(tail) or (tail[:1].isalpha() if tail else False):
            return 3
    if t in MULT and i + 1 < len(toks) and _one(toks[i + 1][0]):
        return 2
    return 1


# ------------------------------------------------------------------ window ---
@dataclass(frozen=True, slots=True)
class CandidateWindow:
    """The stretch of tape the runner is about to solve."""

    fmt_name: str
    fmt: Fmt
    value: str
    confs: list[float]
    aligned: bool
    complete: bool
    checksum_ok: bool
    first_word: int
    last_word: int
    # Carried as well as the index, because the index is into a *bounded* word
    # window that shifts as the tape rolls: a pending identifier re-examined two
    # frames later would read someone else's word, or none.
    last_word_turn: int
    last_word_end_ms: int
    trailing_cells: int
    cells_used: int
    # Aligned.block for the run this window was cut from: the confidences are
    # one recogniser word's number per position. The decider reads it as the
    # BLOCK regime for this candidate (see the Moment it is folded into).
    block_confidence: bool = False


# 4.9's "LENGTH BEFORE CHARACTERS". `pass2` expands "double u" into one slot or
# two and drops the BrE connective "and", so a window of L cells is not always L
# characters. Widening by up to two cells covers every arity case the normaliser
# can emit (measured 2-4 combinations, k <= 2 in 3.5) and is five `pass2` calls,
# not the full arity backtrack -- `arity.lenfix` re-tokenises from text and
# returns no per-position confidences, which is the one thing this path cannot
# lose.
ARITY_SLACK: Final = 2


def build_window(words: Sequence[Word], shape: ShapeHit, armed: bool) -> CandidateWindow | None:
    """Turn the cue's hit into a solvable string with per-position confidence."""
    fmt = FORMATS.get(shape.fmt)
    if fmt is None:
        return None
    runs = readable_runs(words, armed)
    run = next((r for r in runs if r.last == shape.word_last), None)
    if run is None or not run.idx:
        return None
    a = align_run(words, run.idx)
    start = shape.at
    if start + fmt.length > len(a.cells):
        return None

    for extra in range(0, ARITY_SLACK + 1):
        for size in ({fmt.length + extra, fmt.length - extra}
                     if extra else {fmt.length}):
            if size <= 0 or start + size > len(a.cells):
                continue
            cells = a.cells[start:start + size]
            value, _w, _trace, n = pass2(cells, fmt.A, fmt.length)
            if n != fmt.length or len(value) != fmt.length:
                continue
            source = _expansion_map(cells, fmt.length)
            confs = [a.confs[start + source[p]] for p in range(fmt.length)]
            last_cell = start + size - 1
            return CandidateWindow(
                fmt_name=shape.fmt, fmt=fmt, value=value, confs=confs,
                aligned=a.ok,
                complete=start + size == len(a.cells) and shape.complete,
                checksum_ok=fmt.ok(value),
                first_word=a.words[start], last_word=a.words[last_cell],
                last_word_turn=words[a.words[last_cell]].turn_order,
                last_word_end_ms=words[a.words[last_cell]].end,
                trailing_cells=len(a.cells) - (start + size),
                cells_used=size,
                block_confidence=a.block,
            )
    return None


def candidate_regime(window: CandidateWindow, measured: str | None) -> str:
    """ARCH 3.7's regime for THIS candidate.

    The session-wide RegimeDetector needs 40 words and a live call rarely
    gives it that many before the first identifier, so `measured` is usually
    None -- "unknown", which the decider treats as per-character, the one
    regime in which a silent repair is allowed. But a window cut from a welded
    word carries no per-position doubt at all: twelve cells, one number. That
    is the BLOCK regime by construction, known from the alignment, not from a
    statistic, and it overrides the unmeasured session-wide answer for this
    candidate only. A checksum-clean capture still commits silently in every
    regime; what BLOCK forbids is changing a character nobody can localise.
    """
    if window.block_confidence:
        return "block"
    return measured or "unknown"


def _expansion_map(cells: Sequence[Any], length: int) -> list[int]:
    """Position -> source cell, mirroring `pass2`'s own arity expansion.

    `pass2` tries the one-slot reading of "double u" first and the two-slot
    reading second, keeping whichever lands on the format's length. The mapping
    has to make the same choice or a confidence lands on the wrong character,
    which is worse than no confidence at all.
    """
    for two in (False, True):
        out: list[int] = []
        for j, cell in enumerate(cells):
            head = {c for c, _w in cell}
            if "__DBL__" in head:
                out.extend([j, j] if two else [j])
            elif "__AND__" in head:
                if two:
                    continue
                out.append(j)
            else:
                out.append(j)
        if len(out) == length:
            return out
    return list(range(len(cells)))[:length]


# ------------------------------------------------------- confidence regime ---
# 3.7. The day-1 unknown as a runtime branch rather than a bet. Thresholds are
# the spec's, unchanged: they were chosen against measured stakes (PER-CHAR
# 24.5% silent / 0.0% silently wrong; FLAT 5.0% silent / 5.0% silently wrong;
# BLOCK 0.0% silent / 100% span) and re-tuning them before the probe has run
# would be tuning against an assumption.
REGIME_MIN_WORDS: Final = 40
REGIME_FLAT_STDEV: Final = 0.01
REGIME_PER_CHAR_STDEV: Final = 0.03
REGIME_BLOCK_WPC: Final = 0.6
REGIME_PER_CHAR_WPC: Final = 0.9


class RegimeDetector:
    """Words per spelled character, and the spread of their confidences.

    Returns None until it has seen `REGIME_MIN_WORDS`, and None is not
    "per_char": it is "not measured", which is why models.py leaves the column
    NULL. The decider treats an unmeasured regime as not-FLAT, because FLAT is a
    *detected degradation* and asserting a degradation nobody has observed would
    make the system chattier for no reason. Every identifier fixture in this
    repository is shorter than the window, so the fixture corpus runs unmeasured
    and says so.
    """

    __slots__ = ("_confs", "_words", "_chars", "_regime")

    def __init__(self) -> None:
        self._confs: list[float] = []
        self._words = 0
        self._chars = 0
        self._regime: str | None = None

    def observe(self, cells_per_word: Sequence[tuple[int, float]]) -> str | None:
        for chars, conf in cells_per_word:
            if chars <= 0:
                continue
            self._words += 1
            self._chars += chars
            self._confs.append(conf)
        if self._regime is not None or self._words < REGIME_MIN_WORDS:
            return self._regime
        wpc = self._words / max(self._chars, 1)
        sd = statistics.pstdev(self._confs) if len(self._confs) > 1 else 0.0
        if wpc < REGIME_BLOCK_WPC:
            self._regime = "block"
        elif sd < REGIME_FLAT_STDEV:
            self._regime = "flat"
        elif wpc >= REGIME_PER_CHAR_WPC and sd > REGIME_PER_CHAR_STDEV:
            self._regime = "per_char"
        else:
            # Between the named regimes. per_char is the specified behaviour and
            # the others are named degradations; refusing to name one is not the
            # same as detecting one.
            self._regime = "per_char"
        return self._regime

    @property
    def regime(self) -> str | None:
        return self._regime


# ----------------------------------------------------------------- answers ---
@dataclass(frozen=True, slots=True)
class Question:
    """What the runner asked, and everything an answerer needs to answer it."""

    question_id: str
    capture_id: str
    position: int
    form: str
    text: str
    choices: tuple[str, ...]
    grammar: tuple[str, ...]
    rung: int
    spoken: bool
    heard: str
    fmt_name: str


Answerer = Callable[[Question], Awaitable[str | None]]

# 4.7: the answer is parsed under constraint too -- the offered alternatives,
# their NATO/ICAO forms, and yes/no. Anything else is out of grammar, counts
# against the budget and re-asks.
_NATO_TO_CHAR: Final[dict[str, str]] = {v.lower(): k for k, v in NATO_SPOKEN.items()}
_ICAO_TO_CHAR: Final[dict[str, str]] = {v.lower(): k for k, v in ICAO.items()}
_SAY_TO_CHAR: Final[dict[str, str]] = {v.lower(): k for k, v in SAY.items()}

# A "no" to a confirm question is one bit of real information -- the human has
# ruled the heard character out -- and it has to move the posterior off it
# without pretending to know what the character is. Not zero: pos_post divides
# by the remaining mass, and a position with a one-character alphabet would
# become degenerate.
NO_CONF: Final = 0.02

# The answer is worth more than any acoustic evidence, but not certainty: a
# human can misspeak, and 4.9 writes 0.999 rather than 1.0 for exactly that.
ANSWER_CONF: Final = 0.999


def parse_answer(text: str | None, q: Question) -> tuple[str | None, bool]:
    """(character, in_grammar). A confirm's "no" is in grammar and has no char."""
    if text is None:
        return None, False
    t = " ".join(text.lower().replace("-", " ").split())
    if not t:
        return None, False
    if q.form == "CONFIRM":
        if t in ("yes", "yeah", "yep", "correct", "that's right"):
            return q.choices[0] if q.choices else None, True
        if t in ("no", "nope", "negative"):
            return None, True
    allowed = {c.upper() for c in q.choices}
    for table in (_NATO_TO_CHAR, _ICAO_TO_CHAR, _SAY_TO_CHAR):
        if t in table and table[t] in allowed:
            return table[t], True
    if len(t) == 1 and t.upper() in allowed:
        return t.upper(), True
    return None, False


# ------------------------------------------------------------------ config ---
@dataclass(frozen=True, slots=True)
class RunnerConfig:
    """Everything the loop is allowed to be told. All of it has a default."""

    session_id: str = "local"
    sockets: int = 1
    cap_seconds: int = 150            # 3.11 per-session hard cap
    source_label: str = "replay"
    # ARCHITECTURE 7 gives every demo beat a 6-second dead-man timer, and a
    # question is a beat: past this the agent stops waiting, counts the question
    # against the budget (4.7) and carries on. It must never stall for an
    # unattended judge.
    answer_timeout_ms: int = 6000
    # A capture that has already been decided stays decided for the rest of the
    # tape's life. Without this the identifier sits on the 45 s tape and is
    # re-detected on every subsequent frame, which is one commit per partial.
    suppress_repeat: bool = True
    # ARCH 3.9: the organisation's own words -- owner prefixes, part numbers,
    # customer names -- ride along in every keyterm push after the state's own
    # terms, inside the 100/50 budget. Loaded by the session manager from
    # vocabulary_term; empty for a tenant that has set none, and in tests.
    vocabulary: tuple[str, ...] = ()
    # Per-format ARMED keyterm overrides (catalogue SKUs, extra prefixes),
    # merged over detector.FORMAT_TOKENS.
    format_tokens: Mapping[str, Sequence[str]] | None = None
    # ARCH 3.8's third second-signal: an out-of-band format identification for
    # a window that has neither a carrier phrase nor a registered prefix.
    # Injected by the session manager (server.llm.identify_with_fallback with
    # the key); None in replay and in tests, where nothing may leave the
    # process. Called at most once per candidate, under a timeout, and its
    # verdict counts only when FormatID.asserts -- which already refuses the
    # bare-digit formats the model is measured anti-correlated on.
    identify: Callable[[str, str | None], Awaitable[Any]] | None = None
    identify_timeout_s: float = 2.5


@dataclass(slots=True)
class RunSummary:
    """What the session did, in the numbers the counter and the record show."""

    session_id: str
    captures: list[CaptureRecord] = field(default_factory=list)
    questions: list[QuestionRecord] = field(default_factory=list)
    characters: int = 0
    questions_asked: int = 0
    spoken_questions: int = 0
    speech_ms: int = 0
    silent_captures: int = 0
    armed_at_ms: int | None = None
    billed_seconds: float = 0.0
    end_reason: str = "complete"
    regime: str | None = None
    frames: int = 0


# Two seconds of agent speech per spoken question, from the demo counter in
# ARCHITECTURE 7 beat 2 ("agent speech 2.1s" after one question). Estimated
# rather than measured because the browser owns SpeechSynthesis and the server
# never hears it; the browser corrects the figure when it finishes speaking.
SPEECH_MS_PER_QUESTION: Final = 2100


# The frame pump has to distinguish "no frame yet" from "no more frames", and
# `StopAsyncIteration` cannot cross a Task boundary intact -- asyncio converts it
# into a RuntimeError on the way out. A sentinel value is the only shape that
# survives being awaited.
_STREAM_END: Final = object()


async def _next_frame(frames: Any) -> Any:
    try:
        return await frames.__anext__()
    except StopAsyncIteration:
        return _STREAM_END


# How much slack to add to a deadline computed from the gates. One frame of
# scheduling jitter: waking a millisecond early re-decides, finds the gate still
# shut by that millisecond, and re-arms, which costs a deferral for nothing.
WAKE_MARGIN_MS: Final = 60


# -------------------------------------------------------------- the loop -----
async def run_session(
    source: Any,
    stream: ev.EventStream,
    *,
    store: CaptureStore | None = None,
    answerer: Answerer | None = None,
    config: RunnerConfig | None = None,
) -> RunSummary:
    """Drive one session end to end. Returns when the source is exhausted.

    `source` is anything satisfying `stream.source.TranscriptSource`. It is typed
    `Any` deliberately: importing `ReplaySource` or `LiveSource` here would put a
    concrete implementation in the one file that must not name one.
    """
    cfg = config or RunnerConfig()
    st: CaptureStore = store or NullStore()
    tape = Tape()
    detector = Detector(format_tokens=cfg.format_tokens, extra_terms=cfg.vocabulary)
    regime = RegimeDetector()
    speech = dec.SpeechBudget()
    summary = RunSummary(session_id=cfg.session_id)

    stream.emit(ev.SESSION_STARTED, 0, session_id=cfg.session_id,
                source=cfg.source_label, sockets=cfg.sockets,
                cap_seconds=cfg.cap_seconds)

    forced_turns: set[int] = set()
    decided: set[str] = set()
    pending: _Pending | None = None
    partial_id: str | None = None
    last_partial = ""
    seen_words = 0

    # The frame pump is a task rather than a bare `async for` so that waiting for
    # a frame can be raced against the clock. It is never cancelled while the
    # session is running -- cancelling `__anext__` mid-flight leaves the source's
    # generator unusable -- so a deadline that fires simply leaves it pending and
    # picks it up on the next pass.
    frames = source.__aiter__()
    pump: asyncio.Task[Any] | None = None
    clock_ms = _now_ms(source)
    ended = False

    try:
        while True:
            if pump is None and not ended:
                pump = asyncio.ensure_future(_next_frame(frames))
            wake = pending.wake_after_ms if pending is not None else None

            if ended and not wake:
                # Nothing left to deliver and nothing left to wait for.
                break
            if ended:
                await asyncio.sleep(wake / 1000.0)
                fired = True
            else:
                done, _ = await asyncio.wait(
                    {pump}, timeout=(wake / 1000.0) if wake else None)
                fired = not done

            if fired:
                # The politeness delay expired with nobody speaking. 4.8 gates 4
                # and 5 are conditions on time passing and this is the only thing
                # that reports it: no frame arrives while a line is quiet, so
                # waiting for one is waiting for the quiet to end.
                #
                # Guarded on the clock having actually moved, because an instant
                # replay reports fixture time, which advances only when a frame is
                # delivered. Firing a deadline against a frozen clock would spin
                # until `Attempt.defer` raised, so a source whose clock does not
                # track real time simply stops being waited on.
                now = _now_ms(source)
                if pending is None or now <= clock_ms:
                    if pending is not None:
                        pending.wake_after_ms = None
                    continue
                clock_ms = now
                pending = await _resolve(pending, source, tape, stream, st, speech,
                                         summary, answerer, cfg, regime.regime,
                                         decided, forced_turns)
                if pending is None:
                    await _disarm(detector, source, stream, tape)
                    partial_id, last_partial = None, ""
                continue

            frame = pump.result()          # re-raises whatever the source raised
            pump = None
            if frame is _STREAM_END:
                # Not `break`: an identifier can still be inside its politeness
                # delay when the last frame lands, and a recording that stops
                # 150 ms after the final word is a call that is still going. The
                # loop settles the pending obligation first, bounded by gate 7.
                ended = True
                continue
            clock_ms = max(clock_ms, _now_ms(source))

            summary.frames += 1
            if not tape.ingest(frame):
                continue

            verdict = detector.observe(tape)
            await _push_config(source, verdict.config)
            if verdict.state is State.ARMED and summary.armed_at_ms is None:
                summary.armed_at_ms = tape.now_ms
            if verdict.reason:
                stream.emit(
                    ev.STATE_ARMED if verdict.state is State.ARMED else ev.STATE_IDLE,
                    tape.now_ms, reason=verdict.reason,
                    cues=sorted(c.value for c in verdict.cues),
                    format=verdict.fmt, commit_ok=verdict.commit_ok,
                )

            # 3.6: close the turn the moment the candidate is length-complete,
            # reclaiming the ~1.5 s the ARMED endpoint just cost. Once per turn:
            # the shape stays complete on every subsequent partial of the same
            # turn and a second ForceEndpoint is a socket write for nothing.
            cur = getattr(source, "current_turn", None)
            if verdict.force_endpoint and cur is not None and cur not in forced_turns:
                forced_turns.add(cur)
                await source.force_endpoint()

            # Words are counted by how far the timeline has advanced, not by an
            # index into `tape.words`: that list is a rolling window and its
            # indices shift under eviction, so an index would silently re-count
            # or skip. A word's end time is monotone and survives the roll.
            new_words = [w for w in tape.words if w.end > seen_words and w.is_final]
            if new_words:
                seen_words = new_words[-1].end
            settled = regime.observe(
                [(len(pass1(w.text)[0]), w.confidence) for w in new_words]
            )
            if settled is not None and summary.regime is None:
                summary.regime = settled
                stream.emit(ev.REGIME, tape.now_ms, regime=settled)

            # 3.6, wired. "Four cues over the tape, >= 2 of 4 before anything is
            # written or spoken; any *one* arms." `verdict.commit_ok` is that
            # gate and until now nothing read it -- `grep commit_ok` found two
            # hits in this file and both were event payloads. The capture row
            # below was opened on ARMED-plus-shape, which is 1-of-4 plus a cue
            # that fires on any run of ten digits, and `st.open_capture` is a
            # write: it persists `heard_value`, it puts an amber row on the rack,
            # and on the too_late path `_handover` keeps it as `unverified`.
            # Measured before this line: 400/400 evenly-read telephone numbers
            # produced a persisted CaptureRecord whose heard_value was the
            # caller's phone number under format_type='nhs'. The second-signal
            # rule stopped the commit and did not stop the row, because it is a
            # different gate and 3.8 says so.
            #
            # The provisional rack below is deliberately NOT gated on it: it
            # writes nothing and commits nothing (see `_partial_rack`), and 3.6's
            # sentence is about what is written down, not about what the armed
            # state is willing to show as still being heard.
            shape = verdict.report.shape
            if verdict.state is not State.ARMED or shape is None or not verdict.commit_ok:
                closed = False
                if pending is not None:
                    pending = await _resolve(pending, source, tape, stream, st,
                                             speech, summary, answerer, cfg,
                                             regime.regime, decided, forced_turns)
                    closed = pending is None
                if closed:
                    await _disarm(detector, source, stream, tape)
                if verdict.state is State.ARMED:
                    partial = _partial_rack(tape, verdict.fmt, partial_id)
                    if partial is not None and partial[1] != last_partial:
                        partial_id, last_partial = partial[0], partial[1]
                        stream.emit(ev.RACK_UPDATE, tape.now_ms,
                                    capture_id=partial_id, format=verdict.fmt,
                                    slots=partial[2], second_signal="none",
                                    validated_by="none", diff=None,
                                    provisional=True)
                else:
                    partial_id, last_partial = None, ""
                continue

            window = build_window(tape.words, shape, armed=True)
            if window is None:
                continue
            if cfg.suppress_repeat and window.value in decided:
                continue

            if pending is None or pending.window.value != window.value:
                if pending is not None:
                    # The window changed under an undecided candidate: the
                    # recogniser revised a partial, or the code grew past the
                    # length of the format first hypothesised for it. The old row
                    # was opened so a question could reference it and no question
                    # ever did, so it is a withdrawn hypothesis rather than a
                    # capture, and the record must not show it as one.
                    st.abandon_capture(uuid.UUID(pending.capture_id))
                pending = _Pending(
                    window=window,
                    capture_id=str(uuid.uuid4()),
                    attempt=dec.Attempt(),
                    heard=window.value,
                    confs=list(window.confs),
                    carrier=verdict.report.carrier,
                    carrier_fmt=verdict.fmt,
                    started_ms=tape.now_ms,
                )
                st.open_capture(uuid.UUID(pending.capture_id), window.fmt_name,
                                window.value)
                stream.emit(ev.CANDIDATE_SEEN, tape.now_ms,
                            capture_id=pending.capture_id, format=window.fmt_name,
                            value=window.value, complete=window.complete,
                            checksum_ok=window.checksum_ok, aligned=window.aligned,
                            second_signal=_second_signal(pending))
            else:
                pending.window = window
                if not pending.locked_any:
                    # Partials mutate. Until a human has answered about a
                    # position, the freshest reading wins; after that the locked
                    # characters are facts and the recogniser does not get to
                    # revise them.
                    pending.heard = window.value
                    pending.confs = list(window.confs)

            pending = await _resolve(pending, source, tape, stream, st, speech,
                                     summary, answerer, cfg, regime.regime,
                                     decided, forced_turns)
            if pending is None:
                # 3.6's third exit from ARMED, alongside the 12 s TTL and the
                # topic change. Without it the recogniser keeps the raised
                # max_turn_silence and the owner-code bias for another twelve
                # seconds after the identifier is settled, and the committed
                # string -- still on the tape for 45 s -- goes on voting to
                # re-arm on every partial.
                await _disarm(detector, source, stream, tape)
                partial_id, last_partial = None, ""

            if _elapsed_s(source) >= cfg.cap_seconds:
                summary.end_reason = "cap"
                await source.terminate()
                break
    except asyncio.CancelledError:
        # The stop-and-delete button, or the process shutting down. A cancelled
        # session ended because a human said so, which is `user` and not `error`.
        summary.end_reason = "user"
        raise
    except Exception as exc:
        summary.end_reason = "error"
        # The type, never the message. An exception raised anywhere below the
        # tape can carry a fragment of it in its text, and ARCH 3.9's
        # never-stored list applies "at every stage including logs and stack
        # traces". The traceback goes to the process log; the wire gets a name.
        stream.emit(ev.ERROR, tape.now_ms, message=type(exc).__name__)
        raise
    finally:
        # Everything here is bookkeeping, and an exception in bookkeeping would
        # mask whatever actually went wrong three lines up. The billed seconds
        # in particular must reach the ledger even when the session died badly:
        # the socket was open and the invoice will say so.
        if pump is not None and not pump.done():
            # Only at shutdown, where interrupting the source's generator costs
            # nothing because nobody will read from it again.
            pump.cancel()
        try:
            if pending is not None:
                # The stream ended with an identifier still on the table. 4.8
                # gate 7 forbids speaking about it now, so it is written
                # unverified with its ranked candidates for a human to resolve.
                #
                # The reason is measured rather than assumed. It used to be
                # hardcoded `too_late`, which read on the record as "the agent
                # let this go stale" when what actually happened was that the
                # call ended -- and it hid the ForceEndpoint bug above by giving
                # its symptom a plausible-looking name.
                age = max(0, _now_ms(source) - pending.window.last_word_end_ms)
                _handover(pending, stream, st, summary, tape.now_ms,
                          "too_late" if age > dec.TOO_LATE_MS else "stream_ended")
        except Exception:
            pass
        billed = getattr(source, "billed_seconds", None)
        summary.billed_seconds = float(billed) if billed is not None else 0.0
        summary.regime = summary.regime or regime.regime
        stream.emit(ev.METER, tape.now_ms, characters=summary.characters,
                    questions=summary.questions_asked,
                    speech_ms=summary.speech_ms,
                    billed_seconds=summary.billed_seconds,
                    socket_seconds=round(summary.billed_seconds * cfg.sockets, 3))
        try:
            st.finish(billed_seconds=int(summary.billed_seconds),
                      end_reason=summary.end_reason,
                      confidence_regime=summary.regime)
        except Exception:
            pass
        stream.emit(ev.SESSION_END, tape.now_ms, reason=summary.end_reason,
                    billed_seconds=summary.billed_seconds,
                    captures=len(summary.captures),
                    silent=summary.silent_captures,
                    questions=summary.questions_asked,
                    regime=summary.regime)
        stream.close()
        tape.clear()
    return summary


# ------------------------------------------------------------ the attempt ----
@dataclass(slots=True)
class _Pending:
    """One identifier under consideration, across as many frames as it takes."""

    window: CandidateWindow
    capture_id: str
    attempt: dec.Attempt
    heard: str
    confs: list[float]
    carrier: str | None
    carrier_fmt: str | None
    started_ms: int
    locked_any: bool = False
    asked: int = 0
    last_result: dict[str, Any] = field(default_factory=dict)
    # Milliseconds until this identifier is worth deciding again on the strength
    # of the clock alone, or None when it is waiting on something only a frame
    # can supply -- the turn closing, a second signal. Set by `_resolve`, read by
    # the loop, and the whole reason 4.8 gate 5 is reachable after a
    # ForceEndpoint.
    wake_after_ms: int | None = None
    # 3.8's LLM second signal: asked for at most once per candidate, and only
    # when nothing on the tape named the format. `llm` holds the FormatID (or
    # None when nobody answered -- which is not evidence of anything).
    llm_asked: bool = False
    llm: Any = None


def _second_signal(p: _Pending) -> str:
    """3.8, in order of strength. Never assert a format from shape alone.

    A carrier phrase counts only when it does not name a *different* format:
    "the IBAN is" followed by something ISO-shaped is evidence against the
    hypothesis, not for it.

    And, for the same sentence read the other way round, a carrier phrase that
    names NO format cannot supply the second signal for a hypothesis that came
    from shape alone. Three of the twenty-one phrases in `CARRIERS` carry
    `None` -- "it reads", "reads as", "spelled" -- because they announce that a
    code is coming without saying which. When the shape hit is one the mask
    could not have rejected (`shape_is_evidence` false: any ten digits are an
    NHS number, any sixteen a card, any seventeen characters a VIN), the format
    being asserted came from nothing but the length of the run, and "it reads"
    does not know that it is an NHS number either. Taking it as the second
    signal is 3.8's own sentence -- *never assert a format from shape alone* --
    failing on the word "alone".

    Measured before this clause: a telephone number preceded anywhere in the
    45 s window by "it reads", "reads as" or "spelled" committed at rung 0,
    silently, as a checksum-validated NHS number, on the ~18% of UK numbers that
    contain a ten-digit window mod-11 accepts. The cost is stated in
    docs/FINDINGS.md 7 and it is a recall trade, not a free win: a genuine NHS
    number introduced only by "it reads" now stays unverified.

    A phrase that DOES name the format is untouched -- "nhs number", "card
    number", "container number" -- and so is a shape hit whose mask could have
    said no, which is every ISO 6346 and every IBAN.
    """
    if p.carrier is not None and p.carrier_fmt in (None, p.window.fmt_name):
        if (CARRIERS.get(p.carrier) is not None
                or shape_is_evidence(p.window.fmt, p.heard)):
            return "carrier"
    if prefix_signal(p.window.fmt_name, p.heard):
        return "prefix"
    # The third signal is LLM format-ID at confidence >= 0.8 (3.8). It is an
    # out-of-band HTTP call against a key that does not exist yet, so today it
    # is absent rather than stubbed true -- a stub here would silently disable
    # 3.8's third signal, weakest and last: the LLM Gateway's format
    # identification, asked for by _resolve only when the two above were absent.
    # Its own gate -- FormatID.asserts -- already refuses bare-digit formats and
    # anything under 0.8, for the measured reason in server/llm.py (a phone
    # number scored `nhs 0.90`; a real NHS number `not_an_identifier`), so the
    # only question left here is whether it named THIS hypothesis.
    verdict = p.llm
    if (verdict is not None and getattr(verdict, "asserts", False)
            and getattr(verdict, "fmt", None) == p.window.fmt_name):
        return "llm"
    # the rule that ARCHITECTURE 9 calls the mitigation for its second-biggest
    # risk.
    return "none"


def _silence_ms(source: Any, turn_ended: bool, window: CandidateWindow,
                turn_forced: bool) -> int:
    """How long the line has been quiet since the identifier's last word.

    Delivery time, not tape time: the tape's clock is the end of the newest
    word, so during silence it does not move and the quantity being measured is
    identically zero. A turn that ended on its own endpoint timer additionally
    proves `max_turn_silence` of silence -- that timer firing IS the
    measurement -- while a turn closed by ForceEndpoint proves nothing, because
    we closed it ourselves.
    """
    delivered = max(0, _now_ms(source) - window.last_word_end_ms)
    implied = 0
    if turn_ended and not turn_forced:
        cfgobj = getattr(source, "config", None)
        implied = int(getattr(cfgobj, "max_turn_silence", None)
                      or ARMED_MAX_TURN_SILENCE_MS)
    return max(delivered, implied)


async def _push_config(source: Any, config: dict[str, Any] | None) -> None:
    """Send one UpdateConfiguration, in the wire names 3.6 specifies.

    The detector returns None when nothing changed, and that check lives there
    rather than here because this is a socket write called several times a
    second.
    """
    if config is None:
        return
    if getattr(source, "closed", False):
        # The identifier can now settle *after* the stream has closed -- the
        # settle loop waits out the politeness delay past the last frame -- and
        # reconfiguring a socket nobody is listening on is not worth turning a
        # completed session into an `error`. The keyterm list only ever biases
        # the next word, and there is no next word.
        return
    await source.update_configuration(
        keyterms=config.get("keyterms_prompt"),
        max_turn_silence=config.get("max_turn_silence"),
        prompt=config.get("prompt"),
        end_of_turn_confidence_threshold=config.get(
            "end_of_turn_confidence_threshold"),
    )


async def _disarm(detector: Detector, source: Any, stream: ev.EventStream,
                  tape: Tape) -> None:
    """The identifier is settled -- committed, flagged or handed over. Either
    way it is finished, and an armed recogniser biased toward a code nobody is
    reading any more is the state the detector's re-arm guard exists to avoid."""
    was = detector.state
    config = detector.committed()
    await _push_config(source, config)
    if was is State.ARMED:
        stream.emit(ev.STATE_IDLE, tape.now_ms, reason="identifier settled",
                    cues=[], format=None, commit_ok=False)


def _now_ms(source: Any) -> int:
    fn = getattr(source, "now_ms", None)
    return int(fn()) if callable(fn) else 0


def _elapsed_s(source: Any) -> float:
    return _now_ms(source) / 1000.0


def _moment(p: _Pending, source: Any, tape: Tape, regime: str | None,
            forced_turns: set[int]) -> dec.Moment:
    order = p.window.last_word_turn
    turn = next((t for t in tape.turns if t.turn_order == order), None)
    ended = bool(turn is not None and turn.end_of_turn)
    return dec.Moment(
        now_ms=_now_ms(source),
        last_word_end_ms=p.window.last_word_end_ms,
        silence_ms=_silence_ms(source, ended, p.window, order in forced_turns),
        turn_ended=ended,
        length_complete=len(p.heard) == p.window.fmt.length,
        trailing_characters=p.window.trailing_cells,
        second_signal=_second_signal(p),
        # 4.8 gate 3: resolving it has to change an outcome. In this build the
        # outcome is the capture row, and a candidate with a second signal is by
        # construction the thing the session exists to write down. A deployment
        # that binds this to a specific form field replaces one expression.
        required=_second_signal(p) != "none",
        checksum_valid_as_heard=p.window.fmt.ok(p.heard),
        regime=candidate_regime(p.window, regime),
    )


async def _resolve(p: _Pending, source: Any, tape: Tape, stream: ev.EventStream,
                   st: CaptureStore, speech: dec.SpeechBudget,
                   summary: RunSummary, answerer: Answerer | None,
                   cfg: RunnerConfig, regime: str | None,
                   decided: set[str], forced_turns: set[int]) -> _Pending | None:
    """Run 4.9's loop body until it commits, asks, defers or gives up.

    Returns the pending attempt if it is still open, None once it is closed. The
    loop is bounded by `Attempt.step`, which refuses an iteration it cannot
    charge to a budget.
    """
    while True:
        fmt = p.window.fmt
        # 3.8's third second-signal, asked for exactly once per candidate and
        # only when the tape supplied neither a carrier phrase nor a registered
        # prefix. Bounded by a timeout so an out-of-band call can never hold
        # the politeness gates hostage; a timeout or a refusal is None, which
        # `_second_signal` reads as "nobody answered", never as evidence.
        if (cfg.identify is not None and not p.llm_asked and p.window.complete
                and _second_signal(p) == "none"):
            p.llm_asked = True
            try:
                p.llm = await asyncio.wait_for(cfg.identify(p.window.value, p.carrier),
                                               timeout=cfg.identify_timeout_s)
            except Exception:  # noqa: BLE001 -- network, timeout, malformed: no evidence
                p.llm = None
        result = solve(fmt, p.heard, p.confs, locked=p.attempt.locked)
        p.last_result = result
        moment = _moment(p, source, tape, regime, forced_turns)
        top = result.get("top") or p.heard

        stream.emit(ev.RACK_UPDATE, tape.now_ms, capture_id=p.capture_id,
                    format=p.window.fmt_name,
                    slots=[s.as_dict() for s in
                           _slots(p, result, top, settled=moment.turn_ended)],
                    second_signal=moment.second_signal,
                    validated_by=_validated_by(p, top, moment),
                    diff=({"heard": p.heard, "written": top}
                          if top != p.heard else None))
        cands = list(result.get("cands", []))[:5]
        if len(cands) > 1:
            stream.emit(ev.CANDIDATES_SHOW, tape.now_ms, capture_id=p.capture_id,
                        n_cand=int(result.get("n_cand", 0)),
                        chips=[{"position": i, "char": c[i]}
                               for c in cands for i in range(fmt.length)
                               if c[i] != p.heard[i]][:24])

        d = dec.decide(fmt, p.heard, result, moment, p.attempt, speech)

        if d.action == dec.HOLD:
            stream.emit(ev.SILENCE_HELD, tape.now_ms, capture_id=p.capture_id,
                        reason=d.reason, gate=d.gate, rung=int(d.rung),
                        position=d.position)
            if moment.age_ms > dec.TOO_LATE_MS:
                _handover(p, stream, st, summary, tape.now_ms, "too_late")
                decided.add(p.window.value)
                return None
            # Only the politeness deferral is worth a timer, and it is the only
            # HOLD the decider names a position on: the other two are waiting for
            # the turn to close or for a second signal, neither of which the
            # passage of time supplies. Bounded by gate 7 -- past that there is
            # nothing left to wake up for.
            p.wake_after_ms = (
                min(dec.POLITENESS_MS - moment.silence_ms,
                    dec.TOO_LATE_MS - moment.age_ms) + WAKE_MARGIN_MS
                if d.position is not None and moment.silence_ms < dec.POLITENESS_MS
                else None
            )
            if p.wake_after_ms is not None and p.wake_after_ms <= 0:
                p.wake_after_ms = None
            return p

        if d.action == dec.COMMIT:
            _commit(p, result, top, moment, stream, st, summary, tape.now_ms)
            decided.add(p.window.value)
            decided.add(top)
            return None

        if d.action == dec.FLAG:
            _flag(p, result, stream, st, summary, tape.now_ms,
                  str(d.detail.get("flag_reason", "implausible_repair")))
            decided.add(p.window.value)
            return None

        if d.action == dec.HANDOVER:
            _handover(p, stream, st, summary, tape.now_ms,
                      d.handover_reason or "budget_exhausted")
            decided.add(p.window.value)
            return None

        if d.action == dec.SPAN:
            positions = _span_positions(fmt, p, result)
            stream.emit(ev.SPAN_REREAD, tape.now_ms, capture_id=p.capture_id,
                        positions=positions, rung=int(d.rung),
                        text=_span_text(p.heard, positions))
            answer = await _ask_human(answerer, _span_question(p, positions), cfg)
            re_read = _reread(answer, fmt) if answer is not None else None
            if re_read is None:
                # Nobody re-read it, or what came back does not fit the format.
                # 4.9 calls this the budget outcome rather than the no-candidate
                # one: the span was the last instrument and it was spent.
                _handover(p, stream, st, summary, tape.now_ms, "budget_exhausted")
                decided.add(p.window.value)
                return None
            p.heard, p.confs = re_read
            p.locked_any = False
            continue

        # d.action == ASK
        q = _question(p, result, d)
        summary.questions_asked += 1
        if d.spoken:
            summary.spoken_questions += 1
            summary.speech_ms += SPEECH_MS_PER_QUESTION
        stream.emit(ev.QUESTION_ASK, tape.now_ms, question_id=q.question_id,
                    capture_id=p.capture_id, position=q.position, form=q.form,
                    text=q.text, choices=list(q.choices), grammar=list(q.grammar),
                    rung=int(d.rung), spoken=d.spoken, gate=d.gate,
                    # DESIGN-BRIEF 6: the twelve pairs the check digit cannot see
                    # should read on screen as diligence, not as doubt. Taken
                    # from blind_alternatives rather than from the solver's
                    # action label, which never says ASK_BLIND -- see the note in
                    # tests/test_pipeline_e2e.py.
                    blind=bool(blind_alternatives(fmt, q.position,
                                                  p.heard[q.position])))
        # The question moment (DESIGN-BRIEF 4.3): the rack has to show WHICH
        # character is being asked about and WHAT the alternatives are, while the
        # agent is waiting. Emitted before the await, or the slot only turns
        # `asked` after the answer has already made it moot.
        stream.emit(ev.RACK_UPDATE, tape.now_ms, capture_id=p.capture_id,
                    format=p.window.fmt_name,
                    slots=[s.as_dict() for s in _asked_slots(p, top, q)],
                    second_signal=moment.second_signal,
                    validated_by=_validated_by(p, top, moment), diff=None,
                    awaiting=q.question_id)
        t0 = time.monotonic()
        raw = await _ask_human(answerer, q, cfg)
        char, in_grammar = parse_answer(raw, q)
        took = int((time.monotonic() - t0) * 1000)
        record = QuestionRecord(
            question_id=uuid.UUID(q.question_id), capture_id=uuid.UUID(p.capture_id),
            rung=int(d.rung), spoken=d.spoken, position=q.position,
            form=q.form.lower(), question_text=q.text, offered=list(q.choices),
            answered=raw is not None, answer_in_grammar=(in_grammar if raw is not None else None),
            answer_char=(char if raw is not None else None), resolution_ms=took,
        )
        st.write_question(record)
        summary.questions.append(record)
        stream.emit(ev.QUESTION_ANSWER, tape.now_ms, question_id=q.question_id,
                    capture_id=p.capture_id, answered=raw is not None,
                    in_grammar=in_grammar, char=char, resolution_ms=took)

        if char is not None:
            if char != p.heard[q.position]:
                # 4.6's online pseudo-count. Recorded, not applied in process --
                # see store.observe_confusion for why the dict write happens at
                # a boundary rather than mid-call.
                st.observe_confusion(heard=p.heard[q.position], truth=char)
            p.heard = p.heard[:q.position] + char + p.heard[q.position + 1:]
            p.confs[q.position] = ANSWER_CONF
            p.attempt.lock(q.position)
            p.locked_any = True
        elif in_grammar:
            # A confirm answered "no": one real bit. The character is ruled out
            # without being identified, so the posterior moves off it and the
            # position stays unlocked.
            p.confs[q.position] = NO_CONF
        # Out of grammar: 4.7 says it counts against the budget and re-asks. The
        # budget was already spent by the decider, so continuing is the re-ask.


def _partial_rack(tape: Tape, fmt_name: str | None,
                  capture_id: str | None) -> tuple[str, str, list[dict[str, Any]]] | None:
    """The rack while the code is still being read: DESIGN-BRIEF 4.1's `empty`.

    A screen that only fills in once eleven characters exist shows nothing for
    the four seconds that are the demo, so the armed state publishes what it has
    heard so far against the shape of the format it thinks it is hearing. These
    slots are provisional by construction -- no capture exists yet, there is no
    second signal, and nothing here can commit.
    """
    fmt = FORMATS.get(fmt_name or "")
    if fmt is None:
        return None
    runs = readable_runs(tape.words, armed=True)
    if not runs:
        return None
    chars = runs[-1].chars[-fmt.length:]
    if not chars or len(chars) >= fmt.length:
        return None
    slots = [ev.Slot(c, ev.SLOT_PROVISIONAL).as_dict() for c in chars]
    slots += [ev.Slot("", ev.SLOT_EMPTY).as_dict()
              for _ in range(fmt.length - len(chars))]
    return capture_id or str(uuid.uuid4()), chars, slots


def _slots(p: _Pending, result: dict[str, Any], top: str, *,
           settled: bool) -> list[ev.Slot]:
    """The rack, in the six states of DESIGN-BRIEF 4.1."""
    marg = result.get("marg") or {}
    ask_pos = result.get("ask_pos")
    doubtful = set(result.get("doubtful", ()))
    out: list[ev.Slot] = []
    for i, ch in enumerate(p.heard):
        written = top[i]
        if i in p.attempt.locked:
            out.append(ev.Slot(written, ev.SLOT_LOCKED))
        elif i == ask_pos and p.asked:
            alts = tuple(sorted(marg, key=lambda c: -marg[c])[:3])
            out.append(ev.Slot(written, ev.SLOT_ASKED, alts=alts))
        elif written != ch:
            out.append(ev.Slot(written, ev.SLOT_REPAIRED, heard=ch))
        elif not settled or i in doubtful:
            alts = tuple(sorted(marg, key=lambda c: -marg[c])[:3]) if i == ask_pos else ()
            out.append(ev.Slot(written, ev.SLOT_PROVISIONAL, alts=alts))
        else:
            out.append(ev.Slot(written, ev.SLOT_SETTLED))
    return out


def _asked_slots(p: _Pending, top: str, q: Question) -> list[ev.Slot]:
    """The rack while a question is open: one slot asked, the rest as they were."""
    out: list[ev.Slot] = []
    for i, ch in enumerate(p.heard):
        if i == q.position:
            out.append(ev.Slot(ch, ev.SLOT_ASKED, alts=q.choices))
        elif i in p.attempt.locked:
            out.append(ev.Slot(top[i], ev.SLOT_LOCKED))
        elif top[i] != ch:
            out.append(ev.Slot(top[i], ev.SLOT_REPAIRED, heard=ch))
        else:
            out.append(ev.Slot(ch, ev.SLOT_SETTLED))
    return out


def _validated_by(p: _Pending, top: str, moment: dec.Moment) -> str:
    if p.window.fmt.ok(top):
        return "both" if moment.second_signal == "prefix" else "check_digit"
    return "registry" if moment.second_signal == "prefix" else "none"


# 4.7 sends a marginal whose top exceeds 0.80 to a yes/no confirm, because a
# peak that sharp is worth one bit. At a blind position the peak is not evidence:
# the check digit contributed exactly nothing there, so the mass on the heard
# character is one instrument's opinion rather than two agreeing. A confirm would
# then cost two exchanges to reach an answer -- "no" rules a character out
# without naming one -- against a budget of one spoken interruption per
# identifier (4.8 gate 6). The top is capped just under the threshold so the
# alternative is offered outright, which is the whole promise of FINDINGS 4.
BLIND_MAX_TOP: Final = 0.75


def _blind_marginal(fmt: Fmt, heard: str, pos: int,
                    marg: dict[str, float]) -> dict[str, float] | None:
    """Widen a degenerate marginal to the characters the checksum cannot see.

    A blind substitution leaves a string that validates, so `repairs_r1` never
    runs, exactly one candidate survives, and the marginal is {heard: 1.0}. The
    question generated from that asks the speaker to confirm the character the
    agent already has -- which is answerable only with "no", and "no" identifies
    nothing, because nothing downstream can propose the alternative either.

    The alternatives are not unknown. FINDINGS 4 enumerates them -- twelve pairs
    -- and `blind_alternatives` returns the ones live at this position. Their
    weights are the confusion table's, not the posterior's, for the reason above:
    a posterior at a blind position is the ASR's opinion wearing arithmetic's
    clothes.
    """
    alts = blind_alternatives(fmt, pos, heard[pos])
    if not alts or len(marg) > 1:
        return None
    raw = {heard[pos]: 1.0}
    raw.update({c: w_of(c, heard[pos]) for c in alts})
    z = sum(raw.values()) or 1.0
    out = {c: v / z for c, v in raw.items()}
    top = out[heard[pos]]
    if top > BLIND_MAX_TOP and len(out) > 1:
        spare = top - BLIND_MAX_TOP
        rest = 1.0 - top
        out[heard[pos]] = BLIND_MAX_TOP
        for c in out:
            if c != heard[pos]:
                out[c] += spare * (out[c] / rest if rest > 0 else
                                   1.0 / (len(out) - 1))
    return out


def _question(p: _Pending, result: dict[str, Any], d: dec.Decision) -> Question:
    pos = int(result["ask_pos"])
    widened = _blind_marginal(p.window.fmt, p.heard, pos,
                              dict(result.get("marg") or {}))
    if widened is not None:
        result = {**result, "marg": widened}
    q = make_question(p.window.fmt, p.heard, result,
                      LABELS.get(p.window.fmt_name, "reference"))
    p.asked += 1
    choices = tuple(c for c, _w in q["alts"][:3])
    return Question(
        question_id=str(uuid.uuid4()), capture_id=p.capture_id,
        position=int(q["pos"]), form=str(q["form"]), text=str(q["text"]),
        choices=choices, grammar=tuple(q["grammar"]), rung=int(d.rung),
        spoken=d.spoken, heard=p.heard, fmt_name=p.window.fmt_name,
    )


def _span_positions(fmt: Fmt, p: _Pending, result: dict[str, Any]) -> list[int]:
    """4.9: the narrowest span covering the four most doubtful positions."""
    order = doubt_order(fmt, p.heard, p.confs, (), p.attempt.locked)[:4]
    if not order:
        return list(range(fmt.length))
    return list(range(min(order), max(order) + 1))


def _span_text(heard: str, positions: Sequence[int]) -> str:
    if not positions:
        return ""
    lo, hi = positions[0], positions[-1] + 1
    return ("Sorry, could you read me that stretch again -- I have "
            f"{readback(heard[lo:hi])}.")


def _span_question(p: _Pending, positions: Sequence[int]) -> Question:
    return Question(
        question_id=str(uuid.uuid4()), capture_id=p.capture_id,
        position=positions[0] if positions else 0, form="SPAN",
        text=_span_text(p.heard, positions), choices=(), grammar=(),
        rung=int(dec.Rung.SPEAK), spoken=True, heard=p.heard,
        fmt_name=p.window.fmt_name,
    )


def _reread(answer: str, fmt: Fmt) -> tuple[str, list[float]] | None:
    """A re-read span comes back as speech, so it goes through the normaliser."""
    cells, _notes = pass1(answer)
    value, weights, _trace, n = pass2(cells, fmt.A, fmt.length)
    if n != fmt.length or len(value) != fmt.length:
        return None
    # A re-read is a deliberate, slow repetition; the weights pass2 returns are
    # lattice weights rather than ASR confidence, and treating them as
    # confidence is the only honest thing available without a second recognition
    # pass. They are conservative -- an ambiguous cell comes back at 0.5.
    return value, [float(w) for w in weights]


async def _ask_human(answerer: Answerer | None, q: Question,
                     cfg: RunnerConfig) -> str | None:
    if answerer is None:
        return None
    try:
        return await asyncio.wait_for(answerer(q), cfg.answer_timeout_ms / 1000.0)
    except (asyncio.TimeoutError, TimeoutError):
        return None


# ------------------------------------------------------------- terminals -----
def _candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"value": c, "p": round(float(pr), 4)}
            for c, pr in zip(result.get("cands", [])[:5], result.get("probs", [])[:5])]


def _commit(p: _Pending, result: dict[str, Any], top: str, moment: dec.Moment,
            stream: ev.EventStream, st: CaptureStore, summary: RunSummary,
            at_ms: int) -> None:
    # Latency is measured from the identifier's last WORD, in delivery time, not
    # from the first frame that showed a candidate. It is the number an operator
    # experiences -- how long after the speaker stopped did the code appear --
    # and tape time cannot express it, because tape time stops when speech does.
    # Against the value the row calls `heard`, not against the working string.
    # `p.heard` is mutated in place as answers arrive, so comparing to it made an
    # answered correction report `corrected=False` with `position_corrected=None`
    # while the same row carried heard=MSAU4158005 and final=MSKU4158005 -- a
    # record whose flag contradicted its own two columns, and a `repair.silent`
    # the screen never got. The invariant is now structural: `corrected` is true
    # exactly when the two stored values differ.
    heard0 = p.window.value
    corrected = top != heard0
    position = next((i for i in range(len(top)) if top[i] != heard0[i]), None)
    silent = p.attempt.questions == 0 and p.attempt.spans == 0
    if corrected:
        # 4.8: always show the diff. An agent that quietly changes what a person
        # said is a trust problem regardless of how often it is right -- and a
        # correction the human supplied is still a diff worth drawing, which is
        # why this is keyed on the change and not on the silence.
        stream.emit(ev.REPAIR_SILENT, at_ms, capture_id=p.capture_id,
                    position=position,
                    heard=heard0[position] if position is not None else None,
                    written=top[position] if position is not None else None,
                    diff={"heard": heard0, "written": top}, silent=silent)
    record = CaptureRecord(
        capture_id=uuid.UUID(p.capture_id), format_type=p.window.fmt_name,
        heard_value=p.window.value, final_value=top,
        validated_by=_validated_by(p, top, moment),
        second_signal=moment.second_signal, status="committed",
        rung=int(dec.Rung.WRITE if silent else dec.Rung.SPEAK),
        silent=silent, corrected=corrected, position_corrected=position,
        questions_asked=p.attempt.questions, spans=p.attempt.spans,
        handed_over=False, handover_reason=None, flag_reason=None,
        confidence_at_write=round(float(result.get("post_top", 0.0)), 4),
        candidates=_candidates(result),
        latency_ms=moment.age_ms,
    )
    st.write_capture(record)
    summary.captures.append(record)
    summary.characters += len(top)
    if silent:
        summary.silent_captures += 1
    stream.emit(ev.CAPTURE_COMMIT, at_ms, capture_id=p.capture_id,
                format=p.window.fmt_name, value=top, heard=p.window.value,
                validated_by=record.validated_by, second_signal=record.second_signal,
                silent=silent, corrected=corrected, position_corrected=position,
                questions=record.questions_asked, rung=record.rung,
                latency_ms=record.latency_ms)


def _flag(p: _Pending, result: dict[str, Any], stream: ev.EventStream,
          st: CaptureStore, summary: RunSummary, at_ms: int, reason: str) -> None:
    record = CaptureRecord(
        capture_id=uuid.UUID(p.capture_id), format_type=p.window.fmt_name,
        heard_value=p.window.value, final_value=None,
        validated_by="none", second_signal=_second_signal(p), status="flagged",
        rung=int(dec.Rung.AMBER), silent=False, corrected=False,
        position_corrected=None, questions_asked=p.attempt.questions,
        spans=p.attempt.spans, handed_over=False, handover_reason=None,
        flag_reason=reason, confidence_at_write=None,
        candidates=_candidates(result), latency_ms=max(0, at_ms - p.started_ms),
    )
    st.write_capture(record)
    summary.captures.append(record)
    stream.emit(ev.CAPTURE_FLAG, at_ms, capture_id=p.capture_id,
                format=p.window.fmt_name, value=p.window.value, reason=reason)


def _handover(p: _Pending, stream: ev.EventStream, st: CaptureStore,
              summary: RunSummary, at_ms: int, reason: str) -> None:
    result = p.last_result
    record = CaptureRecord(
        capture_id=uuid.UUID(p.capture_id), format_type=p.window.fmt_name,
        heard_value=p.window.value, final_value=None, validated_by="none",
        second_signal=_second_signal(p), status="unverified",
        rung=int(dec.Rung.AMBER), silent=False, corrected=False,
        position_corrected=None, questions_asked=p.attempt.questions,
        spans=p.attempt.spans, handed_over=True, handover_reason=reason,
        flag_reason=None, confidence_at_write=None,
        candidates=_candidates(result), latency_ms=max(0, at_ms - p.started_ms),
    )
    st.write_capture(record)
    summary.captures.append(record)
    stream.emit(ev.CAPTURE_HANDOVER, at_ms, capture_id=p.capture_id,
                format=p.window.fmt_name, value=p.window.value, reason=reason,
                candidates=record.candidates)


__all__ = [
    "Aligned",
    "Answerer",
    "CandidateWindow",
    "FORMATS",
    "LABELS",
    "Question",
    "RegimeDetector",
    "RunSummary",
    "RunnerConfig",
    "align_run",
    "build_window",
    "parse_answer",
    "prefix_signal",
    "run_session",
]
