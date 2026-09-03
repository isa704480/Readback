"""The decider: ARCHITECTURE 4.4's four gates and 4.8's ambient discipline.

`solver.decide()` answers "what is this string, and how sure am I". It says
nothing about whether a human should hear about it. This file is the second
question, and it is the one the product is actually about: the agent is silent by
default and speaks only when every gate says it must.

Three things are enforced here rather than trusted:

**The budgets terminate.** ARCHITECTURE 4.6 justifies `budget_q = 2` and
`budget_span = 1` with "termination proof: each question locks a position, locks
clear only on span". That is a proof only if the code makes it one, so
`Attempt.step()` is the single place a loop iteration is granted and it refuses
to grant one unless it can charge it to a budget. Every iteration therefore
increments `questions` or `spans`, both are bounded, and the loop cannot run more
than `budget_q + budget_span + 1` times. The last term is the iteration that
returns a decision without spending anything.

**Speaking is separately budgeted from asking.** 4.6 allows two questions per
identifier; 4.8 gate 6 allows one *spoken* interruption per identifier. Those are
not in conflict, they are two budgets: the second question exists, it just lands
on the screen (rung 1) instead of in the call. Conflating them would either
silence the second question or let the agent talk twice about one number.

**Silence has a named cause.** Every path that declines to speak returns the gate
that stopped it. DESIGN-BRIEF 4.2 needs "it heard, it decided, it said nothing"
to be a visible positive state, and a reason string is the difference between
that and a screen that looks broken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Final

from server.readback.solver import Fmt, blind_alternatives

# ------------------------------------------------------------------- rungs ---


class Rung(IntEnum):
    """ARCHITECTURE 3.3. How loudly the agent responds, from not at all.

    The ordering is the whole point: everything the system does that is not
    WRITE is a cost paid by the humans on the call, and the gates below exist to
    keep the number as low as the evidence allows.
    """

    WRITE = 0        # written, nobody told
    AMBER = 1        # on screen, uncertain, no sound
    EARCON = 2       # a tone, no words
    SPEAK = 3        # the one-character question, out loud


# ----------------------------------------------------------------- budgets ---
# 4.6, from the termination proof. Two questions and one span re-read per
# identifier; the span is what clears the locks, and it is capped at one because
# a second span is a conversation the agent is having with itself.
BUDGET_QUESTIONS: Final = 2
BUDGET_SPANS: Final = 1

# 4.8 gate 6. One spoken interruption per identifier; at most two per five
# minutes; twenty seconds of hard cooldown between any two. Exhausting the
# five-minute allowance drops the session to earcon permanently -- "permanently"
# is the spec's word and it is the safe direction: an agent that has already
# interrupted twice has demonstrated it is not helping this call.
SPOKEN_PER_IDENTIFIER: Final = 1
SPOKEN_PER_WINDOW: Final = 2
SPEECH_WINDOW_MS: Final = 300_000
SPEECH_COOLDOWN_MS: Final = 20_000

# 4.8 gates 4, 5 and 7, all measured from the last word of the identifier.
#
# Gate 4 wants 700 ms of no speech from either speaker before the agent may
# open its mouth; gate 5 adds a 1.5 s politeness delay so the humans get first
# refusal at self-correcting. In milliseconds gate 5 subsumes gate 4, so only
# 1500 appears in the arithmetic -- gate 4's remaining content is "the turn
# ended and we are not talking over anybody", which is a separate boolean and is
# checked separately.
QUIET_MS: Final = 700
POLITENESS_MS: Final = 1500

# Gate 7: past this, do not speak at all. Write it unverified with the ranked
# candidates and let the human resolve it on screen, because a late interruption
# about a number the conversation has moved on from is worse than no
# interruption. This is also why ARM_TTL_MS in the detector is 12 s: 10 + 1.5,
# rounded up, so the recogniser stays biased for as long as speech is still legal.
TOO_LATE_MS: Final = 10_000

# A deferral bound, not a policy. At the ~10 partials per second a busy socket
# delivers, gate 7's 10 s window is ~100 retries of the same identifier; 400 is
# four times that and exists only so that a runner whose clock has stopped
# raises instead of spinning.
MAX_DEFERRALS: Final = 400


@dataclass(slots=True)
class SpeechBudget:
    """Session-scoped. The only mutable state 4.8 gate 6 needs."""

    spoken_at_ms: list[int] = field(default_factory=list)
    latched_to_earcon: bool = False

    def blocking_reason(self, now_ms: int) -> str | None:
        """Why the agent may not speak right now, or None."""
        if self.latched_to_earcon:
            return "speech budget exhausted for this session"
        if self.spoken_at_ms and now_ms - self.spoken_at_ms[-1] < SPEECH_COOLDOWN_MS:
            return f"within the {SPEECH_COOLDOWN_MS // 1000}s cooldown"
        recent = [t for t in self.spoken_at_ms if now_ms - t <= SPEECH_WINDOW_MS]
        if len(recent) >= SPOKEN_PER_WINDOW:
            # Latch rather than wait the window out: 4.8 says exhausted drops to
            # earcon *permanently* for the session.
            self.latched_to_earcon = True
            return "speech budget exhausted for this session"
        return None

    def note_spoken(self, now_ms: int) -> None:
        self.spoken_at_ms.append(now_ms)


@dataclass(slots=True)
class Attempt:
    """Per-identifier budget state, and the thing that makes termination a fact.

    `locked` holds positions a human has answered about. The solver never edits
    a locked position, which is what guarantees the candidate set strictly
    shrinks between questions (4.7). Locks clear only in `spend_span`, and spans
    are capped at one, so the shrinkage cannot be undone more than once.
    """

    budget_questions: int = BUDGET_QUESTIONS
    budget_spans: int = BUDGET_SPANS
    questions: int = 0
    spans: int = 0
    spoken: int = 0
    iterations: int = 0
    deferrals: int = 0
    locked: frozenset[int] = frozenset()
    flagged: bool = False

    @property
    def questions_left(self) -> int:
        return self.budget_questions - self.questions

    @property
    def spans_left(self) -> int:
        return self.budget_spans - self.spans

    @property
    def max_iterations(self) -> int:
        """The bound the loop is allowed to run to, from the budgets themselves.

        One iteration per question, one per span, plus the final iteration that
        returns without spending anything.
        """
        return self.budget_questions + self.budget_spans + 1

    def step(self) -> None:
        """Charge one loop iteration. Raises rather than looping forever.

        An exception here means the invariant above was broken by an edit
        somewhere else -- a path that neither spends a budget nor returns -- and
        a raised error in a test run is enormously cheaper than an agent that
        will not stop asking during a call.
        """
        self.iterations += 1
        if self.iterations > self.max_iterations:
            raise RuntimeError(
                f"decider ran {self.iterations} iterations with "
                f"questions={self.questions} spans={self.spans}; the budgets "
                f"bound this at {self.max_iterations} (ARCHITECTURE 4.6)"
            )

    def defer(self) -> None:
        """Un-charge an iteration that only waited.

        A deferral is not a loop iteration: the decider left the identifier
        unresolved and the runner will retry it on the next frame, which is what
        4.8 gate 5's politeness delay *is*. Charging those against the budget
        would make a quiet 1.5 s indistinguishable from an agent asking three
        questions. They get their own bound instead, and it is not a policy
        number -- gate 7 kills the identifier at 10 s, so the only thing this
        catches is a runner retrying without a clock advancing.
        """
        self.iterations -= 1
        self.deferrals += 1
        if self.deferrals > MAX_DEFERRALS:
            raise RuntimeError(
                f"decider deferred {self.deferrals} times on one identifier; "
                f"gate 7 should have ended it at {TOO_LATE_MS} ms"
            )

    def spend_question(self, position: int, *, spoken: bool) -> None:
        """Charge the question. Deliberately does not lock.

        4.9 locks after the answer arrives, not when the question is asked, and
        the distinction is the whole of 4.7's out-of-grammar rule: an unanswered
        or unparseable answer costs a question and teaches nothing, so locking
        the position would freeze a character on evidence that never came.
        """
        self.questions += 1
        if spoken:
            self.spoken += 1

    def lock(self, position: int) -> None:
        """The human answered about this character. The solver never edits it
        again, which is what guarantees the candidate set strictly shrinks."""
        self.locked = self.locked | {position}

    def spend_span(self) -> None:
        self.spans += 1
        # 4.9 clears the locks on a span re-read: the whole span is re-heard, so
        # a lock held from before it is an assertion about characters that no
        # longer exist.
        self.locked = frozenset()


# ---------------------------------------------------------------- the facts --
@dataclass(frozen=True, slots=True)
class Moment:
    """Everything outside the solver that 4.8 reads. Assembled by the runner.

    Separated from the runner so the gates are testable without a socket, a
    tape or a clock: every field here is a fact somebody can write down.
    """

    now_ms: int                     # delivery-time clock, session-relative
    last_word_end_ms: int           # end of the identifier's last word
    silence_ms: int                 # measured silence since that word -- see below
    turn_ended: bool
    length_complete: bool
    trailing_characters: int        # character-bearing words after the window
    second_signal: str              # carrier | prefix | llm | none  (3.8)
    required: bool                  # resolving it fills a required field (gate 3)
    checksum_valid_as_heard: bool
    regime: str                     # per_char | flat | block  (3.7)

    @property
    def age_ms(self) -> int:
        return max(0, self.now_ms - self.last_word_end_ms)


@dataclass(frozen=True, slots=True)
class Decision:
    """What the runner should do next, and what the screen should say about it."""

    action: str                     # commit | ask | span | flag | handover | hold
    rung: Rung
    spoken: bool
    reason: str
    gate: str | None = None         # the gate that stopped speech, if one did
    position: int | None = None     # the character being asked about
    handover_reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


COMMIT: Final = "commit"
ASK: Final = "ask"
SPAN: Final = "span"
FLAG: Final = "flag"
HANDOVER: Final = "handover"
HOLD: Final = "hold"


# ------------------------------------------------------------ the four gates --
def letter_positions(fmt: Fmt) -> frozenset[int]:
    """Positions whose alphabet contains letters. Used only by the FLAT rule."""
    return frozenset(
        i for i in range(fmt.length) if any(c.isalpha() for c in fmt.A(i))
    )


def silent_accept_blocked(fmt: Fmt, heard: str, top: str, moment: Moment) -> str | None:
    """Reasons a mathematically clean ACCEPT may still not be written silently.

    Two of them, and both come from measurements rather than from caution.

    3.7: under FLAT confidence the solver writes a wrong container number
    silently 5.0% of the time -- matching the checksum-blind rate exactly,
    because a flat confidence vector carries no information about *where* the
    error is. Silent acceptance at letter positions is therefore disabled
    outright in that regime.

    Section 10: IBAN silent correction without a second independent constraint
    "silently fixes 4.7% of genuine data errors". The second constraint is the
    national BBAN check digit, which this repository does not implement, so an
    edited IBAN is not written silently at all. When the BBAN validator exists
    this becomes a call to it rather than a refusal.

    All three tests are on `edited`, and that is the load-bearing scope: a
    checksum-valid string the recogniser and the arithmetic already agree about
    needed no confidence to decide, so it commits silently in every regime. What
    the degraded regimes forbid is a *repair* -- a character changed on the
    strength of a confidence vector that cannot say which character is wrong.
    """
    edited = {i for i in range(fmt.length) if top[i] != heard[i]}
    if not edited:
        return None
    if moment.regime == "flat" and edited & letter_positions(fmt):
        return "regime_flat"
    if moment.regime == "block":
        # 3.7, measured: BLOCK reaches 92.0% correct with 0.0% silently wrong by
        # spending a span re-read on everything. Under block-level confidence
        # every position carries the same number, so "the doubt is at position 7"
        # is a sentence the data cannot support.
        return "regime_block"
    if fmt.name.startswith("IBAN"):
        return "iban_needs_bban"
    return None


def _knows_it_is_wrong(fmt: Fmt, heard: str, result: dict[str, Any],
                       moment: Moment) -> bool:
    """4.8 gate 1: wrong, not merely unsure. Uncertainty alone is amber.

    Three ways to know, and all three are positive evidence rather than absence
    of confidence: the check digit rejected what was heard; the posterior
    distrusts a position no candidate edits, which means a second error the
    checksum has already absorbed (4.4); or the doubtful position sits in a
    residue class the check digit cannot see, in which case arithmetic will
    never object however long we wait (FINDINGS 4).
    """
    if not moment.checksum_valid_as_heard:
        return True
    if int(result.get("unexplained", 0)) > 0:
        return True
    return any(
        blind_alternatives(fmt, i, heard[i]) for i in result.get("doubtful", ())
    )


def may_speak(moment: Moment, attempt: Attempt, speech: SpeechBudget,
              knows_it_is_wrong: bool) -> str | None:
    """4.8: all seven gates. Returns the first gate that refuses, or None.

    Ordered cheapest-and-most-decisive first, so the reason the screen shows is
    the one a human would give.
    """
    if moment.age_ms > TOO_LATE_MS:
        return "too late -- more than 10 s since the last word"          # 7
    if not knows_it_is_wrong:
        return "uncertain, not wrong"                                    # 1
    if not moment.turn_ended:
        return "the turn has not ended"                                  # 2
    if not moment.length_complete:
        return "the identifier is not length-complete"                   # 2
    if moment.trailing_characters:
        # 4.8 gate 2's third clause reads "the last token was not itself a
        # letter-name or digit-word". Taken literally of the tape's last token
        # it can never pass -- the last token of a completed code IS a digit
        # word -- so it is read as what it is for: more characters after a
        # length-complete window mean the window is the wrong slice of a longer
        # string, and 4.8 says length-completeness is the only reliable signal
        # that the code finished.
        return "characters are still arriving after the candidate"       # 2
    if not moment.required:
        return "nothing downstream needs it"                             # 3
    if moment.silence_ms < QUIET_MS:
        return "the line is not quiet"                                   # 4
    if moment.silence_ms < POLITENESS_MS:
        return "inside the 1.5 s politeness delay"                       # 5
    if attempt.spoken >= SPOKEN_PER_IDENTIFIER:
        return "already spoke once about this identifier"                # 6
    return speech.blocking_reason(moment.now_ms)                         # 6


def decide(fmt: Fmt, heard: str, result: dict[str, Any], moment: Moment,
           attempt: Attempt, speech: SpeechBudget) -> Decision:
    """One iteration of 4.9's loop body, with 4.8 layered over the top.

    `result` is `solver.decide()`'s dict verbatim. Nothing in here re-derives a
    posterior: the solver owns what the string is, this owns what happens next.
    """
    attempt.step()
    action = str(result.get("action", "ASK"))
    top = result.get("top") or heard
    n_cand = int(result.get("n_cand", 0))
    unexplained = int(result.get("unexplained", 0))

    # -- 3.8, and it is absolute. A shape with no second signal is captured as
    # unvalidated free text and the agent stays silent, however confident the
    # arithmetic is. Measured: 500/500 correctly-read booking references of
    # [A-Z]{4}\d{7} shape produced a first decision of ASK without this rule.
    if moment.second_signal == "none":
        attempt.defer()
        return Decision(
            action=HOLD, rung=Rung.AMBER, spoken=False,
            reason="no second signal: captured unvalidated",
            gate="second signal (3.8)",
            detail={"status": "unverified"},
        )

    # -- Nothing is decided while the turn is still open. 4.8 gate 2 states this
    # for speaking; it binds writing just as hard, and for a sharper reason.
    # Partials MUTATE -- the recogniser revises them and the documentation is
    # explicit that the latest frame replaces the previous one -- so a commit on
    # a partial writes a hypothesis to a table whose whole purpose is to hold
    # facts. The rack still fills in, character by character, from the
    # provisional slots; the row waits for the turn to close.
    if not moment.turn_ended or moment.trailing_characters:
        if moment.age_ms > TOO_LATE_MS:
            return Decision(action=HANDOVER, rung=Rung.AMBER, spoken=False,
                            reason="the turn never closed on this identifier",
                            handover_reason="too_late")
        attempt.defer()
        return Decision(
            action=HOLD, rung=Rung.AMBER, spoken=False,
            reason=("characters are still arriving" if moment.trailing_characters
                    else "the turn has not ended"),
            gate="turn boundary (4.8 gate 2)",
        )

    # -- gate: no candidate at all. Length repair has already run in the
    # normaliser, so this is a string no single or bounded-double edit rescues.
    if action == "FAIL_NOCAND" or n_cand == 0:
        if attempt.spans_left > 0:
            attempt.spend_span()
            return Decision(action=SPAN, rung=Rung.SPEAK, spoken=True,
                            reason="no candidate: re-read the span")
        return Decision(action=HANDOVER, rung=Rung.AMBER, spoken=False,
                        reason="no candidate and no span budget",
                        handover_reason="no_candidate")

    # -- gate: one candidate, and the edit it proposes is not a substitution the
    # confusion table knows. That is evidence of a DATA error, not a hearing
    # error, and 4.4 says flag it rather than repair it. Once per string per
    # session (3.10): twice is the deadlock.
    if action == "FLAG_IMPLAUSIBLE":
        if attempt.flagged:
            return Decision(action=HANDOVER, rung=Rung.AMBER, spoken=False,
                            reason="already flagged this string once",
                            handover_reason="implausible_repair")
        attempt.flagged = True
        return Decision(action=FLAG, rung=Rung.AMBER, spoken=False,
                        reason="repair is arithmetically valid but acoustically "
                               "implausible: data error",
                        detail={"flag_reason": "implausible_repair"})

    # -- gate: silent acceptance. The product.
    if action == "ACCEPT":
        blocked = silent_accept_blocked(fmt, heard, top, moment)
        if blocked is None:
            return Decision(action=COMMIT, rung=Rung.WRITE, spoken=False,
                            reason="accepted silently",
                            detail={"silent": True})
        if attempt.questions_left <= 0:
            return Decision(action=HANDOVER, rung=Rung.AMBER, spoken=False,
                            reason=f"silent accept refused ({blocked}) and no "
                                   f"question budget",
                            handover_reason=("regime_flat"
                                             if blocked in ("regime_flat", "regime_block")
                                             else "budget_exhausted"))
        # Fall through to the question path: the string is probably right, but
        # this regime or this format is not allowed to say so without asking.
        forced_ask = blocked
    else:
        forced_ask = None

    # -- everything below asks about something. 4.9: route to a span re-read
    # when the live ambiguity is wider than the questions left, because
    # character-by-character questions to fix two errors burn the budget and
    # fail (section 10).
    need = max(int(result.get("n_amb_eff", 0)), unexplained + 1)
    ask_pos = result.get("ask_pos")

    # 3.7 does not merely disable silent acceptance in the degraded regimes, it
    # changes which instrument escalates: FLAT makes "span becomes primary
    # escalation", BLOCK makes the one-character question "a special case". Both
    # follow from the same fact -- a confidence vector that is flat or
    # block-level cannot say *where* the error is, and a one-character question
    # asked at a position chosen by a confidence that carries no information is
    # an interruption spent at random.
    degraded = forced_ask in ("regime_flat", "regime_block")
    if need > attempt.questions_left or ask_pos is None or degraded:
        if attempt.spans_left > 0:
            attempt.spend_span()
            reason = ("confidence is not localised in this regime"
                      if degraded else
                      f"{need} characters live, {attempt.questions_left} "
                      f"questions left")
            return Decision(action=SPAN, rung=Rung.SPEAK, spoken=True,
                            reason=reason,
                            detail={"regime": moment.regime} if degraded else {})
        return Decision(action=HANDOVER, rung=Rung.AMBER, spoken=False,
                        reason="ambiguity exceeds the budget",
                        handover_reason=("regime_flat" if degraded
                                         else "budget_exhausted"))

    if attempt.questions_left <= 0:
        return Decision(action=HANDOVER, rung=Rung.AMBER, spoken=False,
                        reason="question budget spent",
                        handover_reason="budget_exhausted")

    # -- 4.8: the question exists. Whether it is *spoken* is a separate decision
    # with seven gates in front of it, and the common case is that it is not.
    knows = _knows_it_is_wrong(fmt, heard, result, moment)
    gate = may_speak(moment, attempt, speech, knows)
    detail: dict[str, Any] = {"solver_action": action}
    if forced_ask is not None:
        detail["forced_ask"] = forced_ask
    if gate is None:
        speech.note_spoken(moment.now_ms)
        attempt.spend_question(int(ask_pos), spoken=True)
        return Decision(action=ASK, rung=Rung.SPEAK, spoken=True,
                        reason="asking about one character",
                        position=int(ask_pos), detail=detail)

    # Refused. An identifier we already spoke about once, or a budget already
    # spent, still deserves a tone; anything refused for a reason about *this*
    # moment -- too early, too late, the line is busy -- must not make a sound.
    earcon = (attempt.spoken >= SPOKEN_PER_IDENTIFIER
              or speech.latched_to_earcon) and moment.age_ms <= TOO_LATE_MS
    if moment.age_ms <= TOO_LATE_MS and moment.silence_ms < POLITENESS_MS:
        # Not refused, deferred. This is the only gate that is about *when*
        # rather than *whether*: the humans get first refusal at self-correcting,
        # so the runner retries this identifier on the next frame and gate 7 ends
        # the retrying at 10 s. Every other refusal below stands, and the
        # question goes to the screen instead of into the call.
        attempt.defer()
        return Decision(action=HOLD, rung=Rung.AMBER, spoken=False,
                        reason=gate, gate=gate, position=int(ask_pos),
                        detail=detail)
    attempt.spend_question(int(ask_pos), spoken=False)
    return Decision(action=ASK, rung=Rung.EARCON if earcon else Rung.AMBER,
                    spoken=False, reason=gate, gate=gate, position=int(ask_pos),
                    detail=detail)


__all__ = [
    "ASK",
    "Attempt",
    "BUDGET_QUESTIONS",
    "BUDGET_SPANS",
    "COMMIT",
    "Decision",
    "FLAG",
    "HANDOVER",
    "HOLD",
    "MAX_DEFERRALS",
    "Moment",
    "POLITENESS_MS",
    "QUIET_MS",
    "Rung",
    "SPAN",
    "SPEECH_COOLDOWN_MS",
    "SPOKEN_PER_IDENTIFIER",
    "SpeechBudget",
    "TOO_LATE_MS",
    "decide",
    "letter_positions",
    "may_speak",
    "silent_accept_blocked",
]
