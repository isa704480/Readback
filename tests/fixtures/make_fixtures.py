# make_fixtures.py -- generates the recorded-shape fixture corpus.
#
# Committed rather than hand-written JSON because the corpus has to grow: every
# accent recording, every failure a judge produces on stage and every session
# captured after the key lands is another fixture, and hand-editing 200-frame
# JSON is how a corpus stops being extended.
#
# The identifiers are checksum-valid by construction -- computed here with
# server.readback.validators, then asserted -- so a fixture can never quietly
# drift into testing the solver against a string the validator rejects for a
# reason nobody intended. (docs/FINDINGS.md 1: one published test vector in the
# original set was wrong from memory. Compute, do not remember.)
#
# Run:  PYTHONPATH=D:/My_apps/Readback python tests/fixtures/make_fixtures.py
from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from server.readback.normalise import pass1, pass2
from server.readback.solver import ISO
from server.readback.validators import iso_cd, iso_ok, luhn_ok, nhs_ok
from server.stream.replay import Fixture, FrameEntry
from server.stream.source import IDLE_MAX_TURN_SILENCE_MS, SourceConfig, Turn, Word

OUT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------- constants --
# Confidence bands. CONF_PHONE and CONF_WRONG are the ones in
# tests/test_solver_regression.py, so the corpus and the regression harness
# share one invented world -- and INVENTED is the operative word: the real
# distribution is the day-1 measurement (AUC of words[].confidence separating
# correct from incorrect characters) and cannot be known without a key. The
# bands deliberately overlap; a model where confidence alone separated right
# from wrong would make the entire posterior unnecessary and every fixture built
# on it a lie.
#
# CONF_HEADSET is not cosmetic and it is not a claim about real audio; it is
# what isolating one variable costs, and two separate effects set it.
#
# (a) DOUBT_T = 0.40 makes a position doubtful when more than 0.40 of the
#     posterior sits off the heard character, which for an emitted character is
#     1 - conf. Anything below 0.60 is therefore doubtful, and ONE unexplained
#     doubtful position anywhere in the string makes the agent speak. Drawing
#     correct characters from (0.55, 0.99) puts ~11% under that line: over
#     eleven characters, a question roughly three times in four, for reasons
#     that have nothing to do with what the fixture is testing.
#
# (b) Less obviously, the silent-repair decision is sensitive to the confidence
#     of the positions that are NOT being repaired, because a competing repair
#     elsewhere needs (1 - conf) there to score. Measured on NSKU4158005 with a
#     single M->N at the given confidence, 200 draws per cell, share of runs
#     the solver repairs SILENTLY:
#
#             heard-char conf   0.47   0.44   0.40   0.38   0.35
#       band (0.82, 0.99)         4%     6%    16%    26%    46%
#       band (0.85, 0.99)        14%    22%    48%    52%    82%
#       band (0.88, 0.99)        34%    52%    84%    94%   100%
#
#     A three-point shift in the band a fixture never mentions swings the
#     headline behaviour from 4% to 94%. That is the strongest argument in this
#     file for treating the day-1 confidence measurement as load-bearing, and
#     the reason a fixture's silence must never be read as a measurement.
CONF_PHONE = (0.55, 0.99)
CONF_HEADSET = (0.88, 0.99)
CONF_WRONG = (0.35, 0.80)

# Recognition lag: the gap between a word finishing in the audio and the partial
# carrying it arriving. Placeholder, and one of the day-1 questions -- the
# rhythm detector fires "while the code is still being spoken" (3.6), so this
# number is the difference between arming during the code and arming after it.
PARTIAL_LAG_MS = 90

# Endpoint latency: max_turn_silence plus the model's own emit delay. The
# fixtures run at the IDLE value; ARMED raises it to 2500 and ForceEndpoint
# claws that back, which is what replay.force_endpoint() exercises.
ENDPOINT_EMIT_MS = IDLE_MAX_TURN_SILENCE_MS + 120

# A word is marked word_is_final once two more words have landed behind it.
# Placeholder: the real stabilisation depth is a day-1 observation. What matters
# for the corpus is that it is greater than zero, because a lookback of zero
# would mean partials never mutate and the awkward case would vanish.
STABILISE_LOOKBACK = 2

# Dictation cadence. Chosen to sit inside the rhythm detector's window (3.6:
# mean_ioi in [180, 600] ms, cv_ioi < 0.35): mean 360, sd 70 gives cv 0.19, far
# enough inside the boundary that a fixture is not testing the boundary itself.
DICT_IOI_MEAN, DICT_IOI_SD = 360, 70
DICT_IOI_MIN, DICT_IOI_MAX = 200, 560

# Conversation cadence, the other side of the same detector. Function words are
# reduced and content words are not, which is where cv_ioi > 0.35 comes from --
# the discriminator is the variance, not the speed.
SPEECH_FUNCTION_IOI = (120, 260)
SPEECH_CONTENT_IOI = (300, 520)
FUNCTION_WORDS = {
    "a", "an", "and", "as", "at", "be", "but", "by", "can", "did", "do", "for",
    "he", "her", "him", "his", "i", "if", "in", "is", "it", "its", "me", "my",
    "no", "not", "of", "on", "or", "our", "so", "that", "the", "them", "then",
    "they", "this", "to", "up", "us", "was", "we", "what", "when", "will",
    "with", "you", "your",
}

# The demo container number (ARCHITECTURE 3.5). Its check digit is recomputed
# below rather than trusted.
OWNER_BODY = "MSKU415800"


# ------------------------------------------------------------------- model --
@dataclass(frozen=True, slots=True)
class Tok:
    """One spoken word.

    `partial` is what the recogniser shows before the word stabilises. It is the
    single most important field in this file: partials MUTATE, the docs say
    render-latest-never-append, and a corpus without mutation lets an appending
    consumer pass every test.
    """
    text: str
    partial: str | None = None
    conf: float | None = None
    wrong: bool = False


@dataclass(frozen=True, slots=True)
class Variant:
    """An alternative recording of the same turn, selected by the keyterms in
    force when the turn started. This is how a fixture reproduces the payoff of
    arming: the same audio, biased differently, one turn later."""
    requires_keyterm: str | None = None
    forbids_keyterm: str | None = None
    overrides: dict[int, str] = field(default_factory=dict)
    conf_overrides: dict[int, float] = field(default_factory=dict)


PLAIN = (Variant(),)


def _conf(rng: random.Random, tok: Tok, band: tuple[float, float]) -> float:
    if tok.conf is not None:
        return tok.conf
    lo, hi = CONF_WRONG if tok.wrong else band
    return round(rng.uniform(lo, hi), 3)


def _ioi(rng: random.Random, tok: Tok, cadence: str) -> int:
    if cadence == "dictation":
        return int(min(DICT_IOI_MAX, max(DICT_IOI_MIN,
                                         rng.gauss(DICT_IOI_MEAN, DICT_IOI_SD))))
    lo, hi = SPEECH_FUNCTION_IOI if tok.text.lower() in FUNCTION_WORDS else SPEECH_CONTENT_IOI
    return rng.randint(lo, hi)


def emit_turn(
    order: int,
    start_ms: int,
    toks: Sequence[Tok],
    rng: random.Random,
    *,
    cadence: str = "dictation",
    band: tuple[float, float] = CONF_HEADSET,
    partial_every: int = 1,
    variants: Sequence[Variant] = PLAIN,
) -> tuple[list[FrameEntry], int, int]:
    """Build one turn's partial/final frame sequence.

    Returns (entries, last_word_end_ms, final_emit_ms). The caller merges the
    entries of every turn by delivery time rather than concatenating them,
    because a turn's final is emitted after `max_turn_silence` and in real
    conversation the next speaker has usually started by then. A corpus that
    concatenates turns hides that, and hiding it is how the tape's
    "a partial never displaces a final" rule goes untested.
    """
    starts: list[int] = []
    ends: list[int] = []
    confs: list[float] = []
    cursor = start_ms
    for tok in toks:
        gap = _ioi(rng, tok, cadence)
        starts.append(cursor)
        # Spoken duration is shorter than the inter-onset interval; the
        # remainder is the pause the rhythm detector measures.
        ends.append(cursor + max(80, int(gap * 0.62)))
        confs.append(_conf(rng, tok, band))
        cursor += gap

    last = len(toks) - 1
    breakpoints = [k for k in range(len(toks)) if k % partial_every == 0 or k == last]

    def build(upto: int, is_final: bool, variant: Variant) -> Turn:
        words: list[Word] = []
        for j in range(upto + 1):
            tok = toks[j]
            settled = is_final or j <= upto - STABILISE_LOOKBACK
            final_text = variant.overrides.get(j, tok.text)
            words.append(Word(
                text=final_text if settled else (tok.partial or final_text),
                start=starts[j],
                end=ends[j],
                confidence=variant.conf_overrides.get(j, confs[j]),
                word_is_final=settled,
            ))
        return Turn(
            type="Turn",
            turn_order=order,
            # format_turns is false by contract (3.1): formatting collapses
            # "fifteen" and "one five", which is the evidence the arity branch
            # in normalise.py runs on.
            turn_is_formatted=False,
            end_of_turn=is_final,
            transcript=" ".join(w["text"] for w in words),
            end_of_turn_confidence=round(
                rng.uniform(0.82, 0.97) if is_final else rng.uniform(0.02, 0.30), 3
            ),
            words=words,
        )

    entries: list[FrameEntry] = []
    for k in breakpoints:
        emit = ends[k] + PARTIAL_LAG_MS
        for variant in variants:
            entries.append(FrameEntry(
                emit_ms=emit,
                frame=build(k, False, variant),
                requires_keyterm=variant.requires_keyterm,
                forbids_keyterm=variant.forbids_keyterm,
            ))
    final_emit = ends[last] + ENDPOINT_EMIT_MS
    for variant in variants:
        entries.append(FrameEntry(
            emit_ms=final_emit,
            frame=build(last, True, variant),
            requires_keyterm=variant.requires_keyterm,
            forbids_keyterm=variant.forbids_keyterm,
        ))
    return entries, ends[last], final_emit


def assemble(groups: Iterable[list[FrameEntry]]) -> tuple[FrameEntry, ...]:
    """Merge every turn's entries into one delivery-ordered stream.

    Stable sort on emit_ms only: variants of the same frame keep their order,
    and a late final lands where the socket would actually have put it -- in the
    middle of the next turn's partials.
    """
    flat = [e for group in groups for e in group]
    flat.sort(key=lambda e: e.emit_ms)
    return tuple(flat)


def words(spec: str, **marks: Tok) -> list[Tok]:
    """'container number em ess' -> tokens, with named overrides spliced in by
    position marker. Keeps the fixture definitions readable as sentences."""
    out: list[Tok] = []
    for i, w in enumerate(spec.split()):
        key = f"w{i}"
        out.append(marks[key] if key in marks else Tok(w))
    return out


# ------------------------------------------------------- normalisation check --
def normalise_window(text: str, fmt=ISO) -> str | None:
    """Slide the format's length over the normalised token stream and return the
    first window that validates.

    This is ARCHITECTURE 3.6 cue (d) -- format-shaped match over the normalised
    tape -- and it is how a straddling identifier is recovered without anyone
    telling the system where it starts. It is also the false-positive test: run
    it over two minutes of conversation and it must find nothing.
    """
    cells, _ = pass1(text)
    for i in range(0, max(0, len(cells) - fmt.length) + 1):
        window = cells[i:i + fmt.length]
        value, _conf, _trace, n = pass2(window, fmt.A, fmt.length)
        if n == fmt.length and len(value) == fmt.length and fmt.ok(value):
            return value
    return None


def final_text(entries: Sequence[FrameEntry], keyterms: Sequence[str] = ()) -> str:
    """The flattened final-word timeline a Tape would hold, for the given arming
    state. Used to check the fixtures before they are written."""
    armed = {k.upper() for k in keyterms}
    latest: dict[int, Turn] = {}
    for e in entries:
        if e.requires_keyterm and e.requires_keyterm.upper() not in armed:
            continue
        if e.forbids_keyterm and e.forbids_keyterm.upper() in armed:
            continue
        if not e.frame["end_of_turn"]:
            continue
        latest[e.frame["turn_order"]] = e.frame
    out: list[Word] = []
    for order in sorted(latest):
        out.extend(latest[order]["words"])
    out.sort(key=lambda w: (w["start"], w["end"]))
    return " ".join(w["text"] for w in out)


# ----------------------------------------------------------------- fixtures --
def fixture_clean() -> Fixture:
    """1. A container number dictated cleanly, one turn."""
    rng = random.Random(1_0001)
    value = OWNER_BODY + str(iso_cd(OWNER_BODY))
    assert iso_ok(value), value
    spoken = "container number mike sierra kilo uniform four one five eight zero zero five"
    toks = words(
        spoken,
        # Four mutating words. All settle correctly; the point is that a
        # consumer which appends partials ends up with "sarah" and "keno" in the
        # transcript of a turn that never contained either.
        w3=Tok("sierra", partial="sarah"),
        w4=Tok("kilo", partial="keno"),
        w6=Tok("four", partial="for"),
        w9=Tok("eight", partial="ate"),
    )
    entries, _last, _final = emit_turn(0, 1200, toks, rng)
    got = normalise_window(final_text(entries))
    assert got == value, got
    return Fixture(
        name="iso_clean_single_turn",
        description=(
            "ISO 6346 container number dictated in NATO, cleanly, in one turn. "
            "Four words mutate across partials before settling."
        ),
        entries=assemble([entries]),
        truth={"format": "iso6346", "value": value, "spoken": spoken},
        expect={
            "contains_identifier": True,
            "normalised": value,
            "checksum_valid_as_heard": True,
            "turns": 1,
            "mutating_words": ["sarah", "keno", "for", "ate"],
            "solver_action": "ACCEPT",
            "solver_top": value,
        },
        notes=[
            "The baseline. If this one does not round-trip, nothing else means anything.",
            "One word per spoken character, which is the day-1 (A) assumption. If "
            "words-per-spelled-character comes back below 0.6 the corpus needs a "
            "BLOCK-regime sibling of every fixture here.",
        ],
        initial_config=SourceConfig(),
    )


def fixture_straddle() -> Fixture:
    """2. The same number straddling three turns, with a hesitation mid-code.

    Also the arming fixture: unarmed, the owner code's K comes back as A -- a
    substitution inside ISO 6346's {A K U} residue class, which the check digit
    declares perfectly valid. Armed with the owner-code keyterm from the next
    turn onward, it comes back correct. One file, both mechanisms, because they
    are the same moment in a real call.
    """
    rng = random.Random(1_0002)
    value = OWNER_BODY + str(iso_cd(OWNER_BODY))
    blind = "MSAU" + value[4:]
    assert iso_ok(value) and iso_ok(blind), (value, blind)

    t0, last0, _ = emit_turn(
        0, 900,
        words("right so the container number is em ess"),
        rng, cadence="speech",
    )
    # The hesitation. 1900 ms of nothing is past the IDLE endpoint, so the turn
    # closes in the middle of the code -- which is the canonical place for a
    # human pause, and why a turn boundary is never a parse boundary (3.4).
    t1, last1, _ = emit_turn(
        1, last0 + 1900,
        words("uh kay you four one", w1=Tok("kay", conf=0.46, wrong=True)),
        rng,
        variants=(
            Variant(forbids_keyterm="MSKU", overrides={1: "ay"}, conf_overrides={1: 0.46}),
            Variant(requires_keyterm="MSKU", conf_overrides={1: 0.88}),
        ),
    )
    t2, _last2, _ = emit_turn(
        2, last1 + 700,
        words("five eight zero zero five that's the one", w1=Tok("eight", partial="ate")),
        rng,
    )
    entries = assemble([t0, t1, t2])

    unarmed = normalise_window(final_text(entries))
    armed = normalise_window(final_text(entries, keyterms=["MSKU"]))
    assert unarmed == blind, unarmed
    assert armed == value, armed

    return Fixture(
        name="iso_straddle_three_turns",
        description=(
            "The same container number spread over three turns, broken by a "
            "1.9 s hesitation inside the code. Unarmed, the owner code's K is "
            "heard as A; armed with the MSKU keyterm from the next turn, it is not."
        ),
        entries=entries,
        truth={"format": "iso6346", "value": value, "spoken": "em ess kay you four one five eight zero zero five"},
        expect={
            "contains_identifier": True,
            "normalised_unarmed": blind,
            "normalised_armed": value,
            "arming_keyterm": "MSKU",
            "arming_effective_from_turn": 1,
            "checksum_valid_as_heard": True,
            "turns": 3,
            "hesitation_after_turn": 0,
            # Arming turns a question into silence: unarmed, position 2 is
            # doubtful and blind, so the agent has to speak; armed, there is
            # nothing to be doubtful about.
            "solver_action_unarmed": "ASK_UNEXPLAINED",
            "solver_top_unarmed": blind,
            "ask_position_unarmed": 2,
            "solver_action_armed": "ACCEPT",
            "solver_top_armed": value,
            # "that's the one" adds a trailing 1 and the window scan has to find
            # the identifier anyway. A fixture whose identifier is the only thing
            # in the timeline tests a scanner that does not exist.
            "trailing_noise_chars": 1,
        },
        notes=[
            "Both readings pass the check digit: MSAU and MSKU differ by 11 at "
            "weight 2^2, so the sum is unchanged mod 11 (docs/FINDINGS.md 4). "
            "Nothing arithmetic separates them -- which is the case for arming, "
            "and the case for asking.",
            "update_configuration issued during turn 0 must not change turn 0. "
            "The variants make that a visible difference rather than a claim.",
        ],
        initial_config=SourceConfig(),
    )


def fixture_visible() -> Fixture:
    """3. One substitution the check digit CAN see: M heard as N."""
    rng = random.Random(1_0003)
    value = OWNER_BODY + str(iso_cd(OWNER_BODY))
    heard = "N" + value[1:]
    assert iso_ok(value), value
    # M and N sit in different residue classes ({2 C M W} and {3 D N X}), so the
    # sum moves by 1 at weight 2^0 and the check digit objects. This is the
    # 21-points-of-silence case: the solver repairs it and says nothing.
    assert not iso_ok(heard), heard
    spoken = "container number em ess kay you four one five eight zero zero five"
    toks = words(
        spoken,
        # 0.38, not 0.47: see the sweep at CONF_HEADSET. This fixture's job is
        # to be the silent repair -- demo beat 1, and the 21 points of silence
        # the acoustic model exists to buy -- and at 0.47 on this band the same
        # string asks a question two times in three instead.
        w2=Tok("en", conf=0.38, wrong=True),          # "em" heard as "en"
        w7=Tok("one", partial="won"),
        w9=Tok("eight", partial="ate"),
    )
    entries, _last, _final = emit_turn(0, 1100, toks, rng)
    got = normalise_window(final_text(entries))
    assert got is None, got          # nothing in the timeline validates as heard
    return Fixture(
        name="iso_visible_substitution",
        description=(
            "M heard as N at position 1. Different residue classes, so the ISO "
            "6346 check digit fails and the solver has arithmetic to work with."
        ),
        entries=assemble([entries]),
        truth={"format": "iso6346", "value": value, "spoken": spoken},
        expect={
            "contains_identifier": True,
            "normalised": heard,
            "checksum_valid_as_heard": False,
            "checksum_sees_it": True,
            "substitution": {"position": 0, "truth": "M", "heard": "N", "weight": 0.72},
            "turns": 1,
            "solver_action": "ACCEPT",
            "solver_top": value,
            "silent_repair": True,
        },
        notes=[
            "M/N carries 0.72 in the confusion table, the fourth heaviest pair, "
            "and it is visible to the check digit. The heavy pairs almost all are "
            "(docs/FINDINGS.md 4).",
            "normalise_window finds nothing here on purpose: as heard, no window "
            "validates. Recovering this one is the solver's job, not the scanner's.",
        ],
        initial_config=SourceConfig(),
    )


def fixture_blind() -> Fixture:
    """4. One substitution the check digit CANNOT see: K heard as A."""
    rng = random.Random(1_0004)
    value = OWNER_BODY + str(iso_cd(OWNER_BODY))
    heard = "MSAU" + value[4:]
    assert iso_ok(value), value
    # {A K U} is one of the ten residue classes. K and A differ by 11, at weight
    # 2^2, so the sum is unchanged mod 11: the validator declares the wrong
    # string perfectly valid, at any SNR, on any accent, forever. There is no
    # arithmetic left. Only the confidence at that position, and the fact that
    # the solver knows which twelve pairs its own arithmetic is blind to.
    assert iso_ok(heard) and heard != value, heard
    spoken = "container number em ess kay you four one five eight zero zero five"
    toks = words(
        spoken,
        # 0.46 is below the 0.60 that DOUBT_T=0.40 implies for a heard character
        # in a 26-letter slot, so the position is doubtful and the blind guard
        # fires. Above 0.60 the agent writes a wrong container number in silence
        # and nothing in the system objects -- which is the honest failure mode
        # and is why this fixture exists.
        w4=Tok("ay", conf=0.46, wrong=True),          # "kay" heard as "ay"
        w6=Tok("four", partial="for"),
    )
    entries, _last, _final = emit_turn(0, 1000, toks, rng)
    got = normalise_window(final_text(entries))
    assert got == heard, got
    return Fixture(
        name="iso_blind_substitution",
        description=(
            "K heard as A at position 3. Same residue class mod 11, so the check "
            "digit passes and the wrong number is arithmetically indistinguishable "
            "from the right one."
        ),
        entries=assemble([entries]),
        truth={"format": "iso6346", "value": value, "spoken": spoken},
        expect={
            "contains_identifier": True,
            "normalised": heard,
            "checksum_valid_as_heard": True,
            "checksum_sees_it": False,
            "substitution": {"position": 2, "truth": "K", "heard": "A", "weight": 0.30},
            "doubtful_position": 2,
            "must_not_accept_silently": True,
            "ask_position": 2,
            "solver_top": heard,
            "turns": 1,
        },
        notes=[
            "5.3% of acoustic confusion weight lands in a blind class, in twelve "
            "known pairs (docs/FINDINGS.md 4). This is one of them.",
            "The contract this fixture defends: the agent asks about all twelve "
            "every time rather than pretending the arithmetic can see them.",
        ],
        initial_config=SourceConfig(),
    )


# Two minutes of a shipping desk talking shop. No identifier anywhere, and
# seeded with the words that look like one: "not" -> 0, "for" -> 4, "to" -> 2,
# "ate" -> 8, "a" -> A/8, "and" -> N, "are" -> R, "be" -> B, "see" -> C/6,
# "one"/"six" -> digits, plus "double", "trouble" and "the reference", which are
# the multiplier and carrier-phrase traps. ARCHITECTURE 3.5 requires the
# multiplier expansions to run ARMED-only for exactly this reason; this fixture
# is the corpus that measures whether they do.
CONVERSATION: list[tuple[str, int]] = [
    ("right so where are we with the Rotterdam sailing", 500),
    ("it slipped again they have us on the Thursday now", 350),
    ("Thursday is fine as long as the paperwork clears customs", 600),
    ("I spoke to the broker this morning he said no trouble at all", 400),
    ("did he say that in writing or was that just on the phone", 900),
    ("on the phone but I can double check with him after lunch", 350),
    ("please do because last time we had that whole mess with the bill of lading", 500),
    ("that was not our fault the shipper sent the wrong weights", 1800),
    ("I know but we still ate the demurrage did we not", 400),
    ("about fifteen hundred euros give or take", 700),
    ("and the forty tons on the second trailer is that still going out today", 450),
    ("should be the driver said he would be here in about twenty minutes", 2400),
    ("okay I see so we are looking at a Thursday departure and a Monday arrival", 500),
    ("roughly yes give it a day either side for the weather", 800),
    ("fine I will tell the customer Monday and hope for the best", 350),
    ("you always say that and then it is Wednesday", 400),
    ("not always", 300),
    ("usually", 1500),
    ("alright what else is on the list", 450),
    ("the insurance renewal and the thing with the crane hire", 600),
    ("the crane can wait the insurance cannot", 500),
    ("I will get the paperwork over to you before I leave", 2100),
    ("one more thing the yard says they need the reference before six", 400),
    ("which reference the booking or the customs one", 350),
    ("the booking I think but check with Maria she had it open earlier", 700),
    ("I will find it and send it over this afternoon", 900),
    ("also did anyone chase the port about the gate slot", 400),
    ("I left a message but nobody has come back to me", 600),
    ("try the duty line they actually answer that one", 1900),
    ("will do and what about the empty return", 350),
    ("same depot as last month nothing has changed there", 700),
    ("good that is one less thing to worry about", 500),
    ("great and if anything changes with Thursday just call me", 450),
    ("will do talk later", 300),
]


def fixture_conversation() -> Fixture:
    """5. Two minutes of ordinary conversation containing no identifier at all.

    The most important fixture in the corpus and the least interesting to look
    at. Everything else measures whether the agent gets an identifier right;
    this measures whether it stays out of the way for the 98% of a call that has
    no identifier in it, which is the entire ambient claim.
    """
    rng = random.Random(1_0005)
    groups: list[list[FrameEntry]] = []
    cursor = 800
    for order, (line, gap) in enumerate(CONVERSATION):
        toks = [Tok(w) for w in line.split()]
        # Every third word, not every word: at conversational rates a partial
        # per word is thousands of frames of no additional information, and the
        # detector reads a window, not a frame.
        entries, last_end, _ = emit_turn(
            order, cursor, toks, rng, cadence="speech", band=CONF_PHONE, partial_every=3
        )
        groups.append(entries)
        cursor = last_end + gap
    entries = assemble(groups)

    text = final_text(entries)
    found = normalise_window(text)
    assert found is None, f"conversation fixture contains a valid ISO 6346: {found}"
    duration = entries[-1].emit_ms
    assert duration >= 120_000, f"only {duration/1000:.1f} s of conversation"

    # A late final is a final that arrives after the next turn's first partials,
    # because the endpoint timer runs 1656 ms past the last word and the next
    # speaker does not wait that long. It is the case the tape's
    # "a partial never displaces a final" rule exists for.
    late = _count_late_finals(entries)
    assert late > 0, "no late finals: the corpus lost its most awkward property"

    return Fixture(
        name="conversation_no_identifier",
        description=(
            f"{duration/1000:.0f} s of shipping-desk conversation with no identifier "
            "in it, seeded with the words that normalise to characters anyway."
        ),
        entries=entries,
        truth={"format": None, "value": None},
        expect={
            "contains_identifier": False,
            "normalised": None,
            "turns": len(CONVERSATION),
            "min_duration_ms": 120_000,
            "late_finals": late,
            "trap_words": ["not", "for", "to", "ate", "a", "and", "are", "be",
                           "see", "one", "six", "double", "trouble", "reference"],
        },
        notes=[
            "The false-positive corpus. Anything that speaks during this fixture "
            "is a bug you would only find on stage.",
            "It contains 'the reference' and 'double' on purpose: a carrier-like "
            "phrase and a multiplier, neither of which may arm anything on its own "
            "(3.6 requires 2 of 4 cues; 3.5 makes the multiplier expansions "
            "ARMED-only).",
            f"{late} finals arrive after the following turn's first partials, "
            "which is what a 1536 ms endpoint does to real turn-taking.",
        ],
        initial_config=SourceConfig(),
    )


# =============================================================================
# Non-identifier digits. The hole the corpus had.
# =============================================================================
# Five fixtures and not one of them contained a run of digits that was not an
# identifier, which is why the shape cue's collapse on bare-digit formats
# survived: `conversation_no_identifier` is 126 s of talk whose longest readable
# run is far short of ten characters, so the cue that fires on any ten digits
# never had a chance to fire on it, and the commit gate was measured against a
# corpus that could not exercise it.
#
# These three are the missing negatives. All are carrier-free, deliberately: a
# carrier phrase is a real, independent cue and 3.6's gate is entitled to open on
# carrier+rhythm, so a negative fixture carrying one would be testing 3.8 rather
# than 3.6. What these test is the thing that must never happen -- a run of
# digits nobody labelled, reaching the write gate on rhythm plus a shape match
# that is a restatement of the run's length.
_DIGIT_WORD = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
               "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}


def say_digits(digits: str, zero: str = "oh") -> list[str]:
    return [zero if d == "0" else _DIGIT_WORD[d] for d in digits]


def _find(rng: random.Random, make, want) -> str:
    """First generated value satisfying `want`. Computed, never remembered."""
    for _ in range(200_000):
        v = make()
        if want(v):
            return v
    raise AssertionError("no value found")


def fixture_phone_in_conversation() -> Fixture:
    """6. A caller giving a mobile number in the middle of an ordinary call.

    The number is chosen so that one of its ten-digit windows passes the NHS
    mod-11 check digit, because that is the dangerous population and it is not
    rare: measured over 200,000 generated UK 07 numbers, 17.5% contain such a
    window. Nothing in the audio says "NHS number" and nothing in the audio is
    an identifier. If this fixture ever reaches the commit gate, a caller's
    telephone number is on its way into a clinical record as a patient number.
    """
    rng = random.Random(1_0006)

    def a_mobile() -> str:
        return "07" + rng.choice("789") + "".join(rng.choice("0123456789") for _ in range(8))

    number = _find(rng, a_mobile, lambda s: nhs_ok(s[:10]) or nhs_ok(s[1:]))
    assert nhs_ok(number[:10]) or nhs_ok(number[1:]), number

    groups: list[list[FrameEntry]] = []
    cursor = 800
    lines: list[tuple[str, str, int]] = [
        ("speech", "sorry before you go what is the best number for you", 420),
        ("dictation", " ".join(say_digits(number)), 500),
        ("speech", "let me read that back to make sure I have it right", 380),
        ("speech", "yes that is the one you can get me on that all day", 400),
    ]
    for order, (cadence, line, gap) in enumerate(lines):
        toks = [Tok(w) for w in line.split()]
        entries, last_end, _ = emit_turn(
            order, cursor, toks, rng, cadence=cadence,
            band=CONF_HEADSET if cadence == "dictation" else CONF_PHONE,
            partial_every=1 if cadence == "dictation" else 3,
        )
        groups.append(entries)
        cursor = last_end + gap
    entries = assemble(groups)

    assert normalise_window(final_text(entries)) is None, "an ISO 6346 appeared"
    return Fixture(
        name="phone_number_in_conversation",
        description=(
            "A caller gives an eleven-digit UK mobile number in the middle of an "
            "ordinary call. No carrier phrase, no identifier, and one of its "
            "ten-digit windows passes the NHS check digit."
        ),
        entries=entries,
        truth={"format": None, "value": None, "spoken_number": number},
        expect={
            "contains_identifier": False,
            "normalised": None,
            "turns": len(lines),
            "digits": number,
            "nhs_valid_window": True,
            "carrier_phrases": 0,
            # Both of these DO fire, and saying so is the point of the fixture:
            # a person reading a phone number aloud is metronomic, and ten
            # digits are an NHS number by shape at distance 0. Two cues, one
            # observation. The commit gate has to see through that.
            "expected_cues": ["rhythm", "shape"],
        },
        notes=[
            "17.5% of UK 07 numbers contain a ten-digit window the NHS mod-11 "
            "check accepts (200,000 draws). This one does, on purpose.",
            "Carrier-free on purpose. A carrier phrase is an independent cue and "
            "3.6 is entitled to open on carrier+rhythm; what must not open the "
            "gate is rhythm plus a shape match that only restates the run length.",
            "The readback line is there because the brief's own scenario is a "
            "readback, and a readback is MORE metronomic than the original.",
        ],
        initial_config=SourceConfig(),
    )


def fixture_meter_reading() -> Fixture:
    """7. A sixteen-digit meter reading, read out at a utilities desk.

    Investigation B's table, and the case DESIGN-BRIEF names: sixteen digits are
    a payment card by shape at distance 0, and 1 in 10 random sixteen-digit
    strings passes Luhn. This one does.
    """
    rng = random.Random(1_0007)
    reading = _find(rng,
                    lambda: "".join(rng.choice("0123456789") for _ in range(16)),
                    luhn_ok)
    assert luhn_ok(reading), reading

    groups: list[list[FrameEntry]] = []
    cursor = 900
    lines: list[tuple[str, str, int]] = [
        ("speech", "and while I have you what does the meter say this morning", 450),
        ("dictation", " ".join(say_digits(reading)), 520),
        ("speech", "that is a big jump on last quarter is the heating on again", 400),
    ]
    for order, (cadence, line, gap) in enumerate(lines):
        toks = [Tok(w) for w in line.split()]
        entries, last_end, _ = emit_turn(
            order, cursor, toks, rng, cadence=cadence,
            band=CONF_HEADSET if cadence == "dictation" else CONF_PHONE,
            partial_every=1 if cadence == "dictation" else 3,
        )
        groups.append(entries)
        cursor = last_end + gap
    entries = assemble(groups)

    assert normalise_window(final_text(entries)) is None, "an ISO 6346 appeared"
    return Fixture(
        name="meter_reading_sixteen_digits",
        description=(
            "A sixteen-digit meter reading dictated at a utilities desk. No "
            "carrier phrase and no identifier, and the digits pass the Luhn "
            "check, so by shape and by checksum it is a payment card."
        ),
        entries=entries,
        truth={"format": None, "value": None, "spoken_number": reading},
        expect={
            "contains_identifier": False,
            "normalised": None,
            "turns": len(lines),
            "digits": reading,
            "luhn_valid": True,
            "carrier_phrases": 0,
            "expected_cues": ["rhythm", "shape"],
        },
        notes=[
            "10.0% of uniform random sixteen-digit strings pass Luhn (500,000 "
            "draws). A checksum is not evidence of a format; it is evidence "
            "about a string whose format something else has to assert.",
            "This is the second bare-digit format, and it is here so the fix is "
            "not tested only against NHS. Sixteen digits also match NHS at "
            "distance 0 in seven different windows.",
        ],
        initial_config=SourceConfig(),
    )


def fixture_date_range() -> Fixture:
    """8. Two dates in one breath, which weld into one thirteen-character run.

    Single dates are eight or nine characters and fall short of NHS's ten, so
    they are caught by LENGTH rather than by the cue logic -- RED-TEAM 6(d)'s own
    example is one. A range defeats that, because "to" normalises to the digit 2
    and bridges the two dates into a single run. It is also the commonest thing
    a shipping desk says.
    """
    rng = random.Random(1_0008)
    groups: list[list[FrameEntry]] = []
    cursor = 700
    lines: list[tuple[str, str, int]] = [
        ("speech", "what window did they give us for the collection", 430),
        ("dictation", "oh one oh nine to oh eight oh nine two oh two six", 500),
        ("speech", "fine I will put that on the booking and tell the yard", 400),
    ]
    for order, (cadence, line, gap) in enumerate(lines):
        toks = [Tok(w) for w in line.split()]
        entries, last_end, _ = emit_turn(
            order, cursor, toks, rng, cadence=cadence,
            band=CONF_HEADSET if cadence == "dictation" else CONF_PHONE,
            partial_every=1 if cadence == "dictation" else 3,
        )
        groups.append(entries)
        cursor = last_end + gap
    entries = assemble(groups)

    assert normalise_window(final_text(entries)) is None, "an ISO 6346 appeared"
    return Fixture(
        name="date_range_welded",
        description=(
            "A collection window read as two dates in one breath. \"to\" reads "
            "as the digit 2 and welds them into one thirteen-character run, "
            "which is long enough to be an NHS number by shape."
        ),
        entries=entries,
        truth={"format": None, "value": None},
        expect={
            "contains_identifier": False,
            "normalised": None,
            "turns": len(lines),
            "welded_by": "to",
            "carrier_phrases": 0,
            "expected_cues": ["rhythm", "shape"],
        },
        notes=[
            "A single date is caught by length, not by the cue logic. Saying so "
            "matters: length is an accident of vocabulary, and one more spoken "
            "element crosses it.",
            "The third turn says 'the booking', which the carrier table used to "
            "match and no longer does (docs/FINDINGS.md 6). It is here to keep "
            "that shut.",
        ],
        initial_config=SourceConfig(),
    )


def _count_late_finals(entries: Sequence[FrameEntry]) -> int:
    """Finals delivered after a frame from a later turn has already arrived."""
    seen_max = -1
    late = 0
    for e in entries:
        order = e.frame["turn_order"]
        if e.frame["end_of_turn"] and order < seen_max:
            late += 1
        seen_max = max(seen_max, order)
    return late


BUILDERS = [
    fixture_clean,
    fixture_straddle,
    fixture_visible,
    fixture_blind,
    fixture_conversation,
    fixture_phone_in_conversation,
    fixture_meter_reading,
    fixture_date_range,
]


def main(argv: Sequence[str] = ()) -> int:
    out_dir = Path(argv[0]) if argv else OUT_DIR
    print(f"{'fixture':32} {'turns':>6} {'frames':>7} {'dur s':>7}  identifier")
    print("-" * 74)
    for build in BUILDERS:
        fx = build()
        path = fx.save(out_dir / f"{fx.name}.json")
        ident = fx.truth.get("value") or "-"
        print(f"{fx.name:32} {len(fx.turn_orders):6d} {len(fx.entries):7d} "
              f"{fx.duration_ms/1000:7.1f}  {ident}")
        # Round-trip through the loader here as well as in the test: a fixture
        # that cannot be read back is worse than one that was never written.
        reloaded = Fixture.load(path)
        assert len(reloaded.entries) == len(fx.entries)
    print(f"\nwritten to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
