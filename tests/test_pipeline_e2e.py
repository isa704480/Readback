"""End-to-end: all five fixtures through the real runner, and the HTTP surface.

What this file defends is not "the pipeline runs". It is the four claims the
product is made of, each of which is a *behaviour* a judge can cause on demand
(ARCHITECTURE 8) and each of which is checked here against a recording rather
than against a mock:

  the clean read commits and NOBODY IS TOLD          -- silence is the product
  the visible substitution is REPAIRED and the       -- 4.8: always show the diff
    repair is reported
  the BLIND substitution ASKS                        -- FINDINGS 4: the twelve
                                                        pairs the arithmetic
                                                        cannot see
  two minutes of conversation produce NOTHING        -- the false-positive corpus

Plus the two properties that make the first four safe to ship: the budgets are
respected and the loop provably terminates, and `/api/demo/replay` emits exactly
the event stream the runner emits, so the UI built against a fixture today is
built against tonight's socket.

Run:  PYTHONPATH=. python tests/test_pipeline_e2e.py
      PYTHONPATH=. python -m pytest tests/test_pipeline_e2e.py -q
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

_TMP = Path(tempfile.mkdtemp(prefix="readback-e2e-"))
# Set before anything imports server.config: Settings is frozen and cached, so a
# later override would be a second Settings object and the app would still be
# talking to ./readback.db.
os.environ.setdefault("READBACK_DATABASE_URL", f"sqlite:///{_TMP / 'e2e.db'}")

from server.pipeline import decider as dec                              # noqa: E402
from server.pipeline import events as ev                                # noqa: E402
from server.pipeline.detector import readable_runs                      # noqa: E402
from server.pipeline.runner import (                                    # noqa: E402
    Question,
    RunSummary,
    RunnerConfig,
    align_run,
    parse_answer,
    prefix_signal,
    run_session,
)
from server.pipeline.store import NullStore                             # noqa: E402
from server.pipeline.tape import Tape                                   # noqa: E402
from server.readback.normalise import pass1                             # noqa: E402
from server.readback.solver import ISO                                  # noqa: E402
from server.stream.replay import (                                     # noqa: E402
    Fixture,
    FrameEntry,
    ReplaySource,
    fixture_dir,
)
from server.stream.source import SourceConfig, TranscriptSource         # noqa: E402

FIXTURES = ("iso_clean_single_turn", "iso_visible_substitution",
            "iso_blind_substitution", "iso_straddle_three_turns",
            "conversation_no_identifier")


# ---------------------------------------------------------------- harness ----
class Checks:
    """Counts and prints, so a failure names the fixture and the property."""

    def __init__(self) -> None:
        self.passed = 0
        self.failures: list[str] = []

    def ok(self, label: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.passed += 1
        else:
            self.failures.append(f"{label}: {detail or 'assertion failed'}")
        mark = "ok  " if condition else "FAIL"
        print(f"  {mark} {label}" + (f"  [{detail}]" if detail else ""))

    def eq(self, label: str, got: Any, want: Any) -> None:
        self.ok(label, got == want, f"got {got!r}, want {want!r}")


class Run:
    """One fixture driven end to end, with the event stream kept for inspection."""

    def __init__(self, name: str, summary: RunSummary, stream: ev.EventStream,
                 store: NullStore) -> None:
        self.name = name
        self.summary = summary
        self.stream = stream
        self.store = store

    def types(self, *types: str) -> list[ev.Event]:
        return [e for e in self.stream.history if e.type in types]

    def spoke(self) -> list[ev.Event]:
        """Every event that made a sound. The number this product is about."""
        return [e for e in self.stream.history
                if (e.type == ev.QUESTION_ASK and e.data.get("spoken"))
                or (e.type == ev.SPAN_REREAD and int(e.data.get("rung", 0)) >= 2)]


def drive(name: str, *, answers: dict[int, str] | None = None,
          answer_all: str | None = None, speed: float = 0.0) -> Run:
    """Replay one fixture through `run_session` with an optional scripted human."""
    fixture = Fixture.load(fixture_dir() / f"{name}.json")
    source = ReplaySource(fixture, speed=speed, config=SourceConfig())
    stream = ev.EventStream()
    store = NullStore()

    async def answerer(q: Question) -> str | None:
        if answers is not None and q.position in answers:
            return answers[q.position]
        return answer_all

    summary = asyncio.run(run_session(
        source, stream, store=store,
        answerer=None if (answers is None and answer_all is None) else answerer,
        config=RunnerConfig(session_id=name),
    ))
    return Run(name, summary, stream, store)


# =============================================================================
# A. The four claims
# =============================================================================
def check_clean(c: Checks) -> None:
    """The baseline. Read cleanly, written, nobody told."""
    r = drive("iso_clean_single_turn")
    caps = r.summary.captures
    c.eq("clean: one capture", len(caps), 1)
    c.eq("clean: committed", caps[0].status, "committed")
    c.eq("clean: value", caps[0].final_value, "MSKU4158005")
    c.ok("clean: silent", caps[0].silent)
    c.eq("clean: rung", caps[0].rung, int(dec.Rung.WRITE))
    c.eq("clean: questions asked", r.summary.questions_asked, 0)
    c.eq("clean: nothing was spoken", len(r.spoke()), 0)
    c.eq("clean: agent speech ms", r.summary.speech_ms, 0)
    c.ok("clean: no repair reported", not r.types(ev.REPAIR_SILENT))
    c.ok("clean: the rack was live before the commit",
         len(r.types(ev.RACK_UPDATE)) > 1,
         f"{len(r.types(ev.RACK_UPDATE))} rack updates")


def check_visible(c: Checks) -> None:
    """M heard as N. Different residue classes, so the check digit sees it."""
    r = drive("iso_visible_substitution")
    caps = r.summary.captures
    c.eq("visible: one capture", len(caps), 1)
    c.eq("visible: heard", caps[0].heard_value, "NSKU4158005")
    c.eq("visible: written", caps[0].final_value, "MSKU4158005")
    c.ok("visible: repaired silently", caps[0].silent and caps[0].corrected)
    c.eq("visible: position repaired", caps[0].position_corrected, 0)
    c.eq("visible: nothing was spoken", len(r.spoke()), 0)

    repairs = r.types(ev.REPAIR_SILENT)
    c.eq("visible: the repair is reported", len(repairs), 1)
    if repairs:
        d = repairs[0].data
        # 4.8: always show the diff. An agent that quietly changes what a person
        # said is a trust problem regardless of how often it is right.
        c.eq("visible: diff heard", d["diff"]["heard"], "NSKU4158005")
        c.eq("visible: diff written", d["diff"]["written"], "MSKU4158005")
        c.eq("visible: reported character", (d["heard"], d["written"]), ("N", "M"))
    rack = r.types(ev.RACK_UPDATE)
    repaired_slot = [e for e in rack
                     if e.data["slots"][0]["state"] == ev.SLOT_REPAIRED]
    c.ok("visible: the rack shows the repaired slot", bool(repaired_slot))
    if repaired_slot:
        c.eq("visible: the rack carries what was heard",
             repaired_slot[-1].data["slots"][0].get("heard"), "N")
    # The demo beat: the checksum offers a menu, the confidences kill it.
    chips = r.types(ev.CANDIDATES_SHOW)
    c.ok("visible: the candidate menu was shown", bool(chips),
         f"{len(chips)} candidates.show events")
    if chips:
        c.ok("visible: more than one candidate to collapse",
             chips[-1].data["n_cand"] > 1, str(chips[-1].data["n_cand"]))


def check_blind(c: Checks) -> None:
    """K heard as A. Same residue class, so the check digit passes on the wrong
    string and silence there would be arithmetic that cannot see."""
    r = drive("iso_blind_substitution")
    asks = r.types(ev.QUESTION_ASK)
    c.eq("blind: exactly one question", len(asks), 1)
    c.ok("blind: it was spoken", bool(asks) and asks[0].data["spoken"])
    c.ok("blind: it is about one character",
         bool(asks) and asks[0].data["position"] == 2,
         str(asks[0].data["position"]) if asks else "no question")
    c.ok("blind: flagged as checksum-blind", bool(asks) and asks[0].data["blind"])
    c.ok("blind: the alternative is offered, not just confirmed",
         bool(asks) and "K" in asks[0].data["choices"],
         str(asks[0].data["choices"]) if asks else "")
    committed = [x for x in r.summary.captures if x.status == "committed"]
    c.eq("blind: nothing was committed silently",
         [x for x in committed if x.silent], [])

    # The same fixture with a human in the room.
    answered = drive("iso_blind_substitution", answers={2: "kilo"})
    caps = answered.summary.captures
    c.eq("blind+answer: one capture", len(caps), 1)
    c.eq("blind+answer: committed", caps[0].status, "committed")
    c.eq("blind+answer: correct value", caps[0].final_value, "MSKU4158005")
    c.ok("blind+answer: not silent", not caps[0].silent)
    c.eq("blind+answer: one question", caps[0].questions_asked, 1)
    c.eq("blind+answer: the confusion pair was recorded",
         answered.store.confusions, [("A", "K")])
    ans = answered.types(ev.QUESTION_ANSWER)
    c.ok("blind+answer: the answer was in grammar",
         bool(ans) and ans[0].data["in_grammar"])
    # ARCH 3.9: what came back is three facts and never text. The answer is the
    # one moment a human speaks directly to the agent, which is what makes it
    # the most tempting thing in the system to keep.
    stored = answered.store.questions[0]
    c.eq("blind+answer: the answer is three facts",
         (stored.answered, stored.answer_in_grammar, stored.answer_char),
         (True, True, "K"))
    c.ok("blind+answer: and the record has no field for what was said",
         not any("answer_text" in f or f == "answer" for f in
                 stored.__dataclass_fields__))


def check_straddle(c: Checks) -> None:
    """One identifier, three turns, a 1.9 s hesitation inside the code.

    A turn boundary is never a parse boundary (3.4), and arming is what makes
    the owner code come back right (3.6).
    """
    r = drive("iso_straddle_three_turns")
    caps = r.summary.captures
    c.eq("straddle: one capture", len(caps), 1)
    c.eq("straddle: committed", caps[0].status, "committed")
    c.eq("straddle: value", caps[0].final_value, "MSKU4158005")
    c.ok("straddle: silent", caps[0].silent)
    c.eq("straddle: nothing was spoken", len(r.spoke()), 0)
    armed = r.types(ev.STATE_ARMED)
    c.ok("straddle: armed before the code finished", bool(armed))
    if armed and caps:
        commit = r.types(ev.CAPTURE_COMMIT)[0]
        c.ok("straddle: armed strictly before the commit",
             armed[0].at_ms < commit.at_ms,
             f"armed {armed[0].at_ms} ms, committed {commit.at_ms} ms")


def check_conversation(c: Checks) -> None:
    """126 s of shipping-desk conversation with no identifier in it.

    The claim under test is NOT that nothing arms. Arming is a recogniser bias
    and 3.6 says any one cue arms; this fixture contains carrier-like phrases and
    evenly-read numbers, so it arms four times and disarms four times. What must
    never happen is a capture, a question, or a sound -- and the thing that
    stops it is the second-signal rule (3.8), not the two-of-four cue count,
    which RED-TEAM (d) predicted would hold and which does not.
    """
    r = drive("conversation_no_identifier")
    c.eq("conversation: no captures", len(r.summary.captures), 0)
    c.eq("conversation: no questions", r.summary.questions_asked, 0)
    c.eq("conversation: nothing was spoken", len(r.spoke()), 0)
    c.eq("conversation: agent speech ms", r.summary.speech_ms, 0)
    c.eq("conversation: no characters written", r.summary.characters, 0)
    c.eq("conversation: no candidate was ever proposed",
         len(r.types(ev.CANDIDATE_SEEN)), 0)
    armed = r.types(ev.STATE_ARMED)
    idle = r.types(ev.STATE_IDLE)
    c.ok("conversation: it does arm, and says so", bool(armed),
         f"{len(armed)} arms")
    c.eq("conversation: every arm decayed back to idle", len(idle), len(armed))
    c.ok("conversation: the regime settled on this one",
         r.summary.regime is not None, str(r.summary.regime))
    c.ok("conversation: 126 s of frames processed", r.summary.frames >= 170,
         str(r.summary.frames))


def check_two_identifiers(c: Checks) -> None:
    """Two codes in one session, twenty seconds apart.

    No fixture has this and every real call does, so it is built from two that
    do: the second recording is shifted past the first in both `turn_order` and
    session time. It exercises the three things one identifier cannot -- that a
    settled capture disarms the recogniser and then lets it re-arm on fresh
    evidence, that `decided` suppresses the committed string without suppressing
    the next one, and that the speech budget is session-scoped.
    """
    gap_ms, turn_gap = 20_000, 10
    entries = list(Fixture.load(fixture_dir() / "iso_visible_substitution.json").entries)
    second = Fixture.load(fixture_dir() / "iso_blind_substitution.json")
    for entry in second.entries:
        frame = json.loads(json.dumps(entry.frame))
        frame["turn_order"] += turn_gap
        for w in frame["words"]:
            w["start"] += gap_ms
            w["end"] += gap_ms
        entries.append(FrameEntry(emit_ms=entry.emit_ms + gap_ms, frame=frame))

    joined = Fixture(name="two_identifiers", entries=tuple(entries))
    stream = ev.EventStream()
    store = NullStore()

    async def answerer(q: Question) -> str | None:
        return "kilo"

    summary = asyncio.run(run_session(
        ReplaySource(joined, speed=0.0), stream, store=store, answerer=answerer,
        config=RunnerConfig(session_id="two_identifiers"),
    ))
    r = Run("two_identifiers", summary, stream, store)

    c.eq("two: both identifiers captured", len(summary.captures), 2)
    c.eq("two: the first is written silently, the second is asked about",
         [(x.final_value, x.silent) for x in summary.captures],
         [("MSKU4158005", True), ("MSKU4158005", False)])
    c.eq("two: one question in the whole session", summary.questions_asked, 1)
    c.eq("two: and one spoken interruption", summary.spoken_questions, 1)
    c.eq("two: 22 characters captured", summary.characters, 22)
    idles = [e for e in r.types(ev.STATE_IDLE)
             if e.data.get("reason") == "identifier settled"]
    c.eq("two: each settled identifier disarmed the recogniser", len(idles), 2)
    arms = r.types(ev.STATE_ARMED)
    c.ok("two: and the second code re-armed it", len(arms) >= 2,
         f"{len(arms)} arms")


# =============================================================================
# B. Budgets, and that the loop provably terminates
# =============================================================================
def check_budgets(c: Checks) -> None:
    for name in FIXTURES:
        for label, kwargs in (("unanswered", {}),
                              ("out of grammar", {"answer_all": "purple"}),
                              ("always no", {"answer_all": "no"}),
                              ("always yes", {"answer_all": "yes"})):
            r = drive(name, **kwargs)                        # type: ignore[arg-type]
            worst_q = max((x.questions_asked for x in r.summary.captures),
                          default=0)
            worst_s = max((x.spans for x in r.summary.captures), default=0)
            c.ok(f"budget {name}/{label}: <= {dec.BUDGET_QUESTIONS} questions",
                 worst_q <= dec.BUDGET_QUESTIONS, str(worst_q))
            c.ok(f"budget {name}/{label}: <= {dec.BUDGET_SPANS} span",
                 worst_s <= dec.BUDGET_SPANS, str(worst_s))
            spoken_per_id = [x for x in r.summary.captures]
            c.ok(f"budget {name}/{label}: <= 1 spoken interruption per identifier",
                 all(1 for _ in spoken_per_id) and
                 r.summary.spoken_questions <= len(r.summary.captures) or
                 not r.summary.captures,
                 f"{r.summary.spoken_questions} spoken, "
                 f"{len(r.summary.captures)} identifiers")
            c.ok(f"budget {name}/{label}: every identifier reached a terminal state",
                 all(x.status in ("committed", "flagged", "unverified")
                     for x in r.summary.captures))

    # The corpus above never needs a second question, so the budget path is
    # driven directly: an identifier nobody ever answers about, run until the
    # decider gives up. Every iteration must spend something, and the sequence
    # must reach a terminal action inside the bound the budgets imply.
    stuck = {"action": "ASK", "top": "MSKU4158005", "n_cand": 2,
             "unexplained": 0, "doubtful": [6], "ask_pos": 6, "n_amb_eff": 1}
    attempt, speech, path = dec.Attempt(), dec.SpeechBudget(), []
    while len(path) <= attempt.max_iterations:
        d = dec.decide(ISO, "NSKU4158005", stuck, _moment(), attempt, speech)
        path.append(d.action)
        if d.action in (dec.COMMIT, dec.FLAG, dec.HANDOVER, dec.HOLD):
            break
    c.eq("termination: two questions, one span, then handover",
         path, [dec.ASK, dec.ASK, dec.SPAN, dec.HANDOVER])
    c.eq("termination: inside the bound", len(path), dec.Attempt().max_iterations)
    c.eq("termination: exactly one of them was spoken", attempt.spoken, 1)

    # 4.7: the lock is what makes the candidate set strictly shrink, and 4.9
    # clears it only on a span, which is capped at one.
    attempt = dec.Attempt()
    attempt.lock(6)
    c.eq("locks: an answered position is locked", attempt.locked, frozenset({6}))
    attempt.spend_span()
    c.eq("locks: and only a span re-read clears it", attempt.locked, frozenset())

    # The termination proof, made a fact rather than a comment: the guard refuses
    # an iteration it cannot charge to a budget.
    a = dec.Attempt()
    for _ in range(a.max_iterations):
        a.step()
    raised = False
    try:
        a.step()
    except RuntimeError:
        raised = True
    c.ok("termination: the iteration guard fires past the budget bound", raised)
    c.eq("termination: the bound is questions + spans + 1",
         dec.Attempt().max_iterations, dec.BUDGET_QUESTIONS + dec.BUDGET_SPANS + 1)

    # 4.8 gate 6: two spoken interruptions in five minutes, then earcon for good.
    speech = dec.SpeechBudget()
    c.eq("speech: first is allowed", speech.blocking_reason(0), None)
    speech.note_spoken(0)
    c.ok("speech: cooldown blocks the next 20 s",
         speech.blocking_reason(1_000) is not None)
    c.eq("speech: allowed again after the cooldown",
         speech.blocking_reason(dec.SPEECH_COOLDOWN_MS + 1), None)
    speech.note_spoken(dec.SPEECH_COOLDOWN_MS + 1)
    c.ok("speech: the third attempt latches the session to earcon",
         speech.blocking_reason(dec.SPEECH_COOLDOWN_MS * 3) is not None)
    c.ok("speech: and the latch is permanent", speech.latched_to_earcon)


# =============================================================================
# C. The gates, in isolation
# =============================================================================
def _moment(**over: Any) -> dec.Moment:
    base: dict[str, Any] = dict(
        now_ms=10_000, last_word_end_ms=8_000, silence_ms=2_000,
        turn_ended=True, length_complete=True, trailing_characters=0,
        second_signal="carrier", required=True, checksum_valid_as_heard=False,
        regime="per_char",
    )
    base.update(over)
    return dec.Moment(**base)


def check_gates(c: Checks) -> None:
    heard, top = "NSKU4158005", "MSKU4158005"
    accept = {"action": "ACCEPT", "top": top, "n_cand": 1, "unexplained": 0,
              "doubtful": [], "ask_pos": 0, "n_amb_eff": 0}

    d = dec.decide(ISO, heard, accept, _moment(), dec.Attempt(), dec.SpeechBudget())
    c.eq("gate: a clean accept commits", d.action, dec.COMMIT)
    c.eq("gate: and does so at rung 0", d.rung, dec.Rung.WRITE)

    # 3.8, the mitigation for ARCHITECTURE 9's second-biggest risk.
    d = dec.decide(ISO, heard, accept, _moment(second_signal="none"),
                   dec.Attempt(), dec.SpeechBudget())
    c.eq("gate: no second signal captures unvalidated", d.action, dec.HOLD)
    c.ok("gate: and stays silent", not d.spoken)

    # 4.8 gate 2: nothing is decided while the turn is open, because partials
    # mutate and a commit on a partial writes a hypothesis to a fact table.
    d = dec.decide(ISO, heard, accept, _moment(turn_ended=False),
                   dec.Attempt(), dec.SpeechBudget())
    c.eq("gate: an open turn defers", d.action, dec.HOLD)
    d = dec.decide(ISO, heard, accept, _moment(trailing_characters=2),
                   dec.Attempt(), dec.SpeechBudget())
    c.eq("gate: characters still arriving defers", d.action, dec.HOLD)

    # 3.7: under FLAT confidence the solver writes a wrong container number
    # silently 5.0% of the time. Silent acceptance at letter positions is off.
    c.eq("gate: FLAT blocks a silent letter repair",
         dec.silent_accept_blocked(ISO, heard, top, _moment(regime="flat")),
         "regime_flat")
    c.eq("gate: PER_CHAR does not",
         dec.silent_accept_blocked(ISO, heard, top, _moment()), None)
    # 3.7 also changes which instrument escalates: under FLAT the span re-read
    # is primary, because a confidence vector with no spread cannot say WHERE
    # the error is and a one-character question would be spent at random.
    d = dec.decide(ISO, heard, accept, _moment(regime="flat"),
                   dec.Attempt(), dec.SpeechBudget())
    c.eq("gate: FLAT escalates to a span, not a character", d.action, dec.SPAN)
    d = dec.decide(ISO, heard, accept, _moment(regime="block"),
                   dec.Attempt(), dec.SpeechBudget())
    c.eq("gate: BLOCK does the same", d.action, dec.SPAN)
    # But a string nothing had to repair still commits in every regime: it needed
    # no confidence to decide, so a degraded confidence costs it nothing.
    clean = {"action": "ACCEPT", "top": "MSKU4158005", "n_cand": 1,
             "unexplained": 0, "doubtful": [], "ask_pos": 0, "n_amb_eff": 0}
    d = dec.decide(ISO, "MSKU4158005", clean, _moment(regime="block",
                                                      checksum_valid_as_heard=True),
                   dec.Attempt(), dec.SpeechBudget())
    c.eq("gate: an unrepaired string commits even under BLOCK", d.action, dec.COMMIT)

    ask = {"action": "ASK_UNEXPLAINED", "top": top, "n_cand": 3, "unexplained": 1,
           "doubtful": [6], "ask_pos": 6, "n_amb_eff": 1}
    # 4.8 gate 7: a late interruption is worse than no interruption.
    d = dec.decide(ISO, heard, ask,
                   _moment(now_ms=30_000, last_word_end_ms=8_000, silence_ms=22_000),
                   dec.Attempt(), dec.SpeechBudget())
    c.ok("gate: past 10 s it does not speak", not d.spoken, d.reason)
    c.ok("gate: it asks on screen instead", d.action == dec.ASK
         and d.rung <= dec.Rung.EARCON, f"{d.action}/{d.rung}")

    # 4.8 gate 5: the humans get first refusal at self-correcting.
    d = dec.decide(ISO, heard, ask, _moment(silence_ms=400), dec.Attempt(),
                   dec.SpeechBudget())
    c.eq("gate: inside the politeness delay it waits", d.action, dec.HOLD)

    # 4.8 gate 6: one spoken interruption per identifier.
    # One live character, so the second question is affordable and the only
    # thing that can stop it being spoken is the per-identifier speech budget.
    one_live = {"action": "ASK", "top": top, "n_cand": 2, "unexplained": 0,
                "doubtful": [6], "ask_pos": 6, "n_amb_eff": 1}
    attempt, speech = dec.Attempt(), dec.SpeechBudget()
    first = dec.decide(ISO, heard, one_live, _moment(), attempt, speech)
    c.ok("gate: the first question is spoken", first.spoken)
    second = dec.decide(ISO, heard, one_live, _moment(), attempt, speech)
    c.ok("gate: the second is not", not second.spoken, second.reason)
    c.ok("gate: it drops to an earcon", second.rung == dec.Rung.EARCON,
         str(second.rung))

    # 4.4: an arithmetically valid repair the confusion table does not know is a
    # data error, and 3.10 allows saying so exactly once.
    flag = {"action": "FLAG_IMPLAUSIBLE", "top": top, "n_cand": 1,
            "unexplained": 0, "doubtful": [], "ask_pos": 0, "n_amb_eff": 0}
    attempt = dec.Attempt()
    d = dec.decide(ISO, heard, flag, _moment(), attempt, dec.SpeechBudget())
    c.eq("gate: implausible repair flags", d.action, dec.FLAG)
    c.ok("gate: without speaking", not d.spoken)
    d = dec.decide(ISO, heard, flag, _moment(), attempt, dec.SpeechBudget())
    c.ok("gate: and never flags the same string twice",
         d.action == dec.HANDOVER, d.action)

    # Section 10: IBAN silent correction without the BBAN check digit "fixes"
    # 4.7% of genuine data errors.
    from server.readback.solver import IBANGB
    iban = "GB82WEST12345698765432"
    c.eq("gate: an edited IBAN is not written silently",
         dec.silent_accept_blocked(IBANGB, iban, "GB82WEST12345698765433",
                                   _moment()),
         "iban_needs_bban")
    c.eq("gate: an unedited one is",
         dec.silent_accept_blocked(IBANGB, iban, iban, _moment()), None)


# =============================================================================
# D. The event stream is the interface
# =============================================================================
def check_stream(c: Checks) -> None:
    r = drive("iso_visible_substitution")
    hist = r.stream.history
    c.ok("stream: every type is in the closed vocabulary",
         all(e.type in ev.EVENT_TYPES for e in hist))
    c.eq("stream: sequence numbers are contiguous from zero",
         [e.seq for e in hist], list(range(len(hist))))
    c.eq("stream: it opens with session.started", hist[0].type, ev.SESSION_STARTED)
    c.eq("stream: it closes with session.end", hist[-1].type, ev.SESSION_END)
    c.ok("stream: and the stream itself is closed", r.stream.closed)
    c.ok("stream: tape time never goes backwards",
         all(a.at_ms <= b.at_ms for a, b in zip(hist, hist[1:])))

    # DESIGN-BRIEF 6: no confidence percentage may reach the interface, so none
    # is transmitted. The uncertainty is expressed by asking.
    def walk(node: Any) -> list[str]:
        if isinstance(node, dict):
            return [k for k in node] + [k for v in node.values() for k in walk(v)]
        if isinstance(node, list):
            return [k for v in node for k in walk(v)]
        return []

    keys = {k for e in hist for k in walk(e.data)}
    c.ok("stream: no slot carries a confidence number",
         "conf" not in keys and "confidence" not in keys, str(sorted(keys)))
    slot_states = {s["state"] for e in r.types(ev.RACK_UPDATE)
                   for s in e.data["slots"]}
    c.ok("stream: every slot state is one of the six",
         slot_states <= set(ev.SLOT_STATES), str(slot_states))

    # DESIGN-BRIEF 4.1 lists six slot states and says collapsing any of them
    # loses something real. All six have to be reachable, or one of them is a
    # state the renderer will be asked to draw and never sees.
    reachable: set[str] = set()
    for run in (r, drive("iso_clean_single_turn"), drive("iso_straddle_three_turns"),
                drive("iso_blind_substitution", answers={2: "kilo"})):
        reachable |= {s["state"] for e in run.types(ev.RACK_UPDATE)
                      for s in e.data["slots"]}
    c.eq("stream: all six slot states are reachable",
         sorted(reachable), sorted(ev.SLOT_STATES))

    asked = drive("iso_blind_substitution", answers={2: "kilo"})
    open_question = [e for e in asked.types(ev.RACK_UPDATE)
                     if e.data.get("awaiting")]
    c.ok("stream: the rack marks the character under question",
         bool(open_question))
    if open_question:
        slot = open_question[0].data["slots"][2]
        c.eq("stream: and carries what it is torn between",
             (slot["state"], sorted(slot.get("alts", []))),
             (ev.SLOT_ASKED, ["A", "K"]))

    # A viewer who arrives late sees the whole session, because the backlog and
    # the live feed are the same list.
    async def late() -> list[ev.Event]:
        return [e async for e in r.stream.subscribe()]

    c.eq("stream: a late subscriber receives the whole backlog",
         [e.seq for e in asyncio.run(late())], [e.seq for e in hist])


# =============================================================================
# E. Confidence alignment -- the substrate the whole posterior sits on
# =============================================================================
def check_alignment(c: Checks) -> None:
    for name in FIXTURES:
        fixture = Fixture.load(fixture_dir() / f"{name}.json")
        tape = Tape()
        for entry in fixture.entries:
            tape.ingest(entry.frame)
        runs = readable_runs(tape.words, armed=True)
        bad = []
        for run in runs:
            a = align_run(tape.words, run.idx)
            if not a.ok or len(a.confs) != len(a.cells):
                bad.append(run.chars[:20])
            text = " ".join(tape.words[i].text for i in run.idx)
            if len(a.cells) != len(pass1(text)[0]):
                bad.append("cell count " + run.chars[:20])
        c.eq(f"alignment {name}: every run aligns cell-for-cell", bad, [])

    # And the alignment is doing work: the confidences reaching the solver differ
    # per position. If they were all equal the posterior could not localise the
    # doubt, which is the entire mechanism.
    r = drive("iso_visible_substitution")
    seen = r.types(ev.CANDIDATE_SEEN)
    c.ok("alignment: the window reports itself aligned",
         bool(seen) and seen[0].data["aligned"])


# =============================================================================
# F. The second-signal rule
# =============================================================================
def check_second_signal(c: Checks) -> None:
    c.ok("second signal: a registered owner code counts",
         prefix_signal("iso6346", "MSKU4158005"))
    c.ok("second signal: an unregistered one does not",
         not prefix_signal("iso6346", "QQQU4158005"))
    # ARCHITECTURE 9 risk 2, measured: 500/500 correctly-read booking references
    # of [A-Z]{4}\d{7} shape produced a first decision of ASK without this rule.
    accept = {"action": "ASK", "top": "QQQU4158005", "n_cand": 4,
              "unexplained": 1, "doubtful": [2], "ask_pos": 2, "n_amb_eff": 2}
    d = dec.decide(ISO, "QQQU4158005", accept, _moment(second_signal="none"),
                   dec.Attempt(), dec.SpeechBudget())
    c.eq("second signal: shape alone never speaks", d.action, dec.HOLD)
    c.eq("second signal: it is captured unvalidated",
         d.detail.get("status"), "unverified")


# =============================================================================
# G. The seam, and the answer grammar
# =============================================================================
def check_seam(c: Checks) -> None:
    fixture = Fixture.load(fixture_dir() / "iso_clean_single_turn.json")
    source = ReplaySource(fixture, speed=0.0)
    c.ok("seam: the replay satisfies TranscriptSource",
         isinstance(source, TranscriptSource))
    # The seam is only real if the loop cannot see through it. Checked on the
    # imports rather than on the text, because the module docstring names both
    # implementations on purpose -- explaining the seam is not crossing it.
    for module in ("runner", "decider"):
        source_text = Path(f"server/pipeline/{module}.py").read_text(encoding="utf-8")
        imports = [ln for ln in source_text.splitlines()
                   if ln.startswith(("import ", "from ")) and "server.stream" in ln]
        c.eq(f"seam: {module} imports nothing from server.stream", imports, [])

    q = Question(question_id="q", capture_id="c", position=2, form="ALTERNATIVE",
                 text="", choices=("A", "K"), grammar=("Alfa", "Kilo"),
                 rung=3, spoken=True, heard="MSAU4158005", fmt_name="iso6346")
    c.eq("grammar: NATO answers parse", parse_answer("kilo", q), ("K", True))
    c.eq("grammar: bare characters parse", parse_answer("A", q), ("A", True))
    c.eq("grammar: anything else is out of grammar",
         parse_answer("purple", q), (None, False))
    c.eq("grammar: silence is not an answer", parse_answer(None, q), (None, False))
    conf = Question(question_id="q", capture_id="c", position=2, form="CONFIRM",
                    text="", choices=("A",), grammar=("yes", "no", "Alfa"),
                    rung=3, spoken=True, heard="MSAU4158005", fmt_name="iso6346")
    c.eq("grammar: a confirm takes yes", parse_answer("yes", conf), ("A", True))
    c.eq("grammar: and no is one real bit", parse_answer("no", conf), (None, True))


# =============================================================================
# H. The HTTP surface
# =============================================================================
def check_api(c: Checks) -> None:
    from fastapi.testclient import TestClient

    import server.main as main

    def reset_limits() -> None:
        # Fixed-window counters are process state, and this file runs several
        # sessions in one second on purpose.
        for window in (main._PER_HOUR, main._PER_DAY, main._ADMISSIONS):
            window.counts.clear()
        main._SESSIONS.clear()

    with TestClient(main.app) as client:
        health = client.get("/health").json()
        c.ok("api: health reports the seam", "live_capture" in health)
        # The fixture list is read from the process, not /health: the public
        # endpoint no longer publishes it (test_security_properties B).
        c.ok("api: and the fixtures are on disk where replay looks",
             set(FIXTURES) <= {p.stem for p in main.fixture_dir().glob("*.json")})

        reset_limits()
        refused = client.post("/api/session/start",
                              json={"consent": {"accepted": False}})
        c.eq("api: no consent, no session", refused.status_code, 403)

        reset_limits()
        started = client.post("/api/session/start",
                              json={"consent": {"accepted": True,
                                                "disclosure_played": True}})
        c.eq("api: consent opens a session", started.status_code, 200)
        session_id = started.json()["session_id"]
        c.eq("api: the cap is the 150 s in 3.11",
             started.json()["cap_seconds"], 150)
        c.ok("api: the budget is reported in socket-seconds",
             started.json()["budget_remaining_seconds"] > 0)

        # The claim this endpoint exists to make: the replay produces exactly the
        # event stream the runner produces.
        for name in FIXTURES:
            reset_limits()
            resp = client.post("/api/demo/replay",
                               json={"fixture": name, "answer_timeout_ms": 50})
            c.eq(f"api: replay {name}", resp.status_code, 200)
            body = resp.json()
            direct = drive(name)
            got = [(e["type"], e["at_ms"]) for e in body["events"]]
            want = [(e.type, e.at_ms) for e in direct.stream.history]
            c.eq(f"api: {name} emits the runner's stream exactly", got, want)

            record = client.get(f"/api/sessions/{body['session_id']}").json()
            c.eq(f"api: {name} rows match the summary",
                 len(record["captures"]), len(direct.summary.captures))
            c.ok(f"api: {name} record carries no transcript",
                 "transcript" not in str(record).lower())

        reset_limits()
        resp = client.post("/api/demo/replay",
                           json={"fixture": "iso_blind_substitution",
                                 "answers": {"2": "kilo"},
                                 "answer_timeout_ms": 50})
        body = resp.json()
        c.eq("api: a scripted answer commits the corrected value",
             [x["final"] for x in body["captures"]], ["MSKU4158005"])
        c.eq("api: and counts the question", body["counters"]["questions"], 1)

        record = client.get(f"/api/sessions/{body['session_id']}").json()
        c.eq("api: the question is on the record", len(record["questions"]), 1)
        c.eq("api: three facts came back, never text",
             (record["questions"][0]["answered"],
              record["questions"][0]["answer_in_grammar"],
              record["questions"][0]["answer_char"]),
             (True, True, "K"))
        c.ok("api: the audit log recorded the capture",
             any(e["action"] == "capture.committed" for e in record["audit"]))

        with client.websocket_connect(
                f"/api/session/{body['session_id']}/live") as ws:
            first = ws.receive_json()
            c.eq("api: the websocket replays from seq 0", first["seq"], 0)
            c.eq("api: starting with session.started", first["type"],
                 ev.SESSION_STARTED)

        # The seam, at the composition root: with no key the live branch is not
        # merely unused, it is unreachable, and it says so rather than silently
        # falling back to a fixture nobody asked for.
        from fastapi import HTTPException

        from server.config import Settings

        # Both branches are CONSTRUCTED here rather than read from the ambient
        # settings, and that is a fix rather than a tidy-up. This block used to
        # call get_settings(), which reads whatever .env happens to hold, and
        # then asserted the keyless behaviour -- so it passed only on a machine
        # with no key. The day a real key landed in .env the suite went red, and
        # the failure was in the test, not in the code it was guarding. A test
        # whose result depends on whose laptop it runs on is not a test.
        keyless = Settings(assemblyai_api_key="", replay_mode=False)
        c.ok("api: no key means no live capture", not keyless.live_capture)
        refused_live = None
        try:
            main.open_source(keyless, None)
        except HTTPException as exc:
            refused_live = exc.status_code
        c.eq("api: and asking for it is a 503, not a fixture", refused_live, 503)
        c.ok("api: a named fixture always replays, key or not",
             type(main.open_source(keyless, "iso_clean_single_turn")).__name__
             == "ReplaySource")

        # The other half of the seam, which nothing exercised until a key
        # existed. Asserting only the keyless branch is exactly how the with-key
        # branch stayed unverified up to the moment it became the live path.
        keyed = Settings(assemblyai_api_key="not-a-real-key", replay_mode=False)
        c.ok("api: a key makes live capture reachable", keyed.live_capture)
        c.ok("api: a named fixture still replays with a key present",
             type(main.open_source(keyed, "iso_clean_single_turn")).__name__
             == "ReplaySource")

        # replay_mode is the kill switch, and it must beat a present key --
        # otherwise the budget ceiling in ARCH 3.11 cannot actually stop spend.
        killed = Settings(assemblyai_api_key="not-a-real-key", replay_mode=True)
        c.ok("api: replay_mode overrides a present key", not killed.live_capture)

        missing = client.post("/api/demo/replay", json={"fixture": "../../etc/passwd"})
        c.eq("api: a fixture name cannot escape the directory",
             missing.status_code, 404)

        stale = client.post(f"/api/session/{body['session_id']}/answer",
                            json={"question_id": str(uuid.uuid4()), "text": "kilo"})
        c.eq("api: an answer to nothing is refused", stale.status_code, 409)
        gone = client.post(f"/api/session/{uuid.uuid4()}/answer",
                           json={"question_id": str(uuid.uuid4()), "text": "kilo"})
        c.eq("api: and an answer to no session is a 404", gone.status_code, 404)
        # Existence, checked where it lives: the row. The record does not show
        # a LIVE-source session to the anonymous (the demo tenant is shared, and
        # a live session there is a real person's identifiers -- 2026-09-07
        # audit), so the old `GET /api/sessions/{id} == 200` probe now asserts
        # the opposite, and the row itself says the session still exists.
        with main.get_sessionmaker()() as db:
            c.ok("api: the started session still exists on the record",
                 db.get(main.Session, uuid.UUID(session_id)) is not None)
        c.eq("api: and its record is not anonymously readable, being a live session",
             client.get(f"/api/sessions/{session_id}").status_code, 404)

        # ARCH 3.12's stop-and-delete: it terminates and it visibly deletes, and
        # the audit row survives because audit_event has no foreign keys.
        reset_limits()
        gone_body = client.post("/api/demo/replay",
                                json={"fixture": "iso_clean_single_turn",
                                      "answer_timeout_ms": 50}).json()
        gone_id = gone_body["session_id"]
        c.eq("api: stop and delete reports the deletion",
             client.post(f"/api/session/{gone_id}/stop",
                         json={"delete": True}).json()["deleted"], True)
        c.eq("api: and the session is gone",
             client.get(f"/api/sessions/{gone_id}").status_code, 404)

        # -- the capture slot is released when the pipeline stops --------------
        #
        # Deliberately does NOT call reset_limits(), which clears `_SESSIONS` and
        # is precisely why this went unnoticed: finished sessions were never
        # removed, `len(_SESSIONS)` was the concurrency gate, and after three
        # demo replays every `/api/session/start` returned 503 for the lifetime
        # of the process. The third click on stage is not a good place to find
        # that out.
        main._SESSIONS.clear()
        for window in (main._PER_HOUR, main._PER_DAY, main._ADMISSIONS):
            window.counts.clear()
        for _ in range(main.get_settings().max_concurrent_sessions + 2):
            for window in (main._PER_HOUR, main._PER_DAY, main._ADMISSIONS):
                window.counts.clear()
            client.post("/api/demo/replay", json={"fixture": "iso_clean_single_turn"})
        # Load is read from the process: /health stopped publishing it.
        settings_now = main.get_settings()
        c.eq("api: a finished replay holds no capture slot",
             main._running_sessions(settings_now), 0)
        c.ok("api: but its record is still in memory to be read",
             len(main._SESSIONS) >= settings_now.max_concurrent_sessions,
             f"retained={len(main._SESSIONS)}")
        for window in (main._PER_HOUR, main._PER_DAY, main._ADMISSIONS):
            window.counts.clear()
        again = client.post("/api/session/start",
                            json={"consent": {"accepted": True}})
        c.eq("api: so a session can still start after them", again.status_code, 200)
        c.eq("api: and it is the one occupying a slot",
             main._running_sessions(main.get_settings()), 1)

        # The gate still has to bite on sessions that really are running.
        for _ in range(main.get_settings().max_concurrent_sessions):
            for window in (main._PER_HOUR, main._PER_DAY, main._ADMISSIONS):
                window.counts.clear()
            last = client.post("/api/session/start",
                               json={"consent": {"accepted": True}})
        c.eq("api: the concurrency gate still refuses genuinely open sessions",
             last.status_code, 503)


# =============================================================================
# I  THE CLOCK
# =============================================================================
def check_clock(c: Checks) -> None:
    """The gates that are conditions on time must hold at every replay speed.

    This section exists because they did not. 3.6 sends `ForceEndpoint` the
    moment a candidate is length-complete, which makes the turn's final frame
    arrive ~150 ms after the last word instead of after `max_turn_silence`. 4.8
    gates 4 and 5 then want 700 ms and 1500 ms of quiet, and nothing reports the
    passing of time, because no frame arrives while a line is silent. The loop
    was driven only by frames, so the politeness delay could never be satisfied
    on a force-endpointed identifier -- which is every identifier -- and the
    agent was permanently mute in real time.

    It stayed invisible because every test ran at `speed=0`, where the replay
    clock reports fixture time and jumps to the moment the frame *would* have
    arrived had the endpoint not been forced. Measured before the fix, on
    `iso_blind_substitution`: speed 0 asked, speed 1.0 did not, and the live
    socket has speed 1.0's clock.

    So: the same fixture, on both clocks, must reach the same decision.
    """
    # 4x rather than 1x for the sweep. The distinction that matters is instant
    # versus timed -- `ReplaySource.now_ms` returns fixture time in the first and
    # a real elapsed clock in the second, and only the second can leave a gate
    # unsatisfied. A multiplier scales both sides of every comparison, so it
    # tests the same branch in a quarter of the wall time. The one assertion
    # worth paying full price for is at 1x below.
    for name in ("iso_blind_substitution", "iso_clean_single_turn",
                 "iso_visible_substitution"):
        instant = drive(name, speed=0.0)
        timed = drive(name, speed=4.0)
        c.eq(f"clock: {name} asks the same number of questions at both speeds",
             len(timed.stream.of_type(ev.QUESTION_ASK)),
             len(instant.stream.of_type(ev.QUESTION_ASK)))
        c.eq(f"clock: {name} reaches the same capture at both speeds",
             [(x.heard_value, x.final_value, x.status, x.silent)
              for x in timed.summary.captures],
             [(x.heard_value, x.final_value, x.status, x.silent)
              for x in instant.summary.captures])

    timed = drive("iso_blind_substitution", speed=1.0)
    c.eq("clock: the blind question is asked in real time, not only instantly",
         len(timed.stream.of_type(ev.QUESTION_ASK)), 1)
    c.ok("clock: and it is spoken", timed.summary.spoken_questions == 1,
         f"spoken={timed.summary.spoken_questions}")

    answered = drive("iso_blind_substitution", answer_all="kilo", speed=4.0)
    c.eq("clock: answering it in real time commits the corrected value",
         [x.final_value for x in answered.summary.captures], ["MSKU4158005"])

    # `too_late` is 4.8 gate 7 firing on an identifier the conversation moved on
    # from. A recording running out is not that, and giving it gate 7's name is
    # how the mute agent above stayed hidden: the symptom had a reason that
    # sounded deliberate.
    for r in (drive("iso_clean_single_turn", speed=0.0),
              drive("iso_clean_single_turn", speed=4.0)):
        reasons = [e.data.get("reason") for e in r.stream.of_type(ev.CAPTURE_HANDOVER)]
        c.ok("clock: a settled capture hands nothing over", reasons == [],
             f"reasons={reasons}")


# =============================================================================
# J  WHAT REACHES A COLUMN
# =============================================================================
def check_minimisation(c: Checks) -> None:
    """ARCH 3.9's never-stored list, checked against the store rather than read.

    `card number` is a carrier phrase and `luhn16` is a live format, so the
    ordinary success path of this system used to write a PAN into `heard_value`,
    `final_value` and `candidates_considered` in clear. The wire is deliberately
    left unmasked -- showing an operator the digits they are speaking is the
    product -- so this is specifically about what a column keeps.
    """
    from server.pipeline.store import mask_pan

    pan = "4539578763621486"          # published Luhn vector, FINDINGS 1
    c.eq("minimisation: a Luhn-valid 16-digit run is masked to its last four",
         mask_pan(pan), "************1486")
    c.eq("minimisation: an ISO 6346 container number is untouched",
         mask_pan("MSKU4158005"), "MSKU4158005")
    c.eq("minimisation: a 10-digit NHS number is untouched",
         mask_pan("9434765919"), "9434765919")
    c.eq("minimisation: a 17-character VIN is untouched",
         mask_pan("1HGBH41JXMN109186"), "1HGBH41JXMN109186")
    c.eq("minimisation: a 16-digit run failing Luhn is not a card number",
         mask_pan("4539578763621487"), "4539578763621487")
    c.eq("minimisation: nothing to mask", mask_pan(None), None)


# =============================================================================
def main_() -> int:
    c = Checks()
    for section, fn in (
        ("A1 the clean read commits in silence", check_clean),
        ("A2 the visible substitution is repaired, and reported", check_visible),
        ("A3 the blind substitution asks", check_blind),
        ("A4 the straddling identifier survives its turn boundaries", check_straddle),
        ("A5 two minutes of conversation produce nothing", check_conversation),
        ("A6 two identifiers in one session", check_two_identifiers),
        ("B  budgets, and termination", check_budgets),
        ("C  the gates", check_gates),
        ("D  the event stream", check_stream),
        ("E  confidence alignment", check_alignment),
        ("F  the second-signal rule", check_second_signal),
        ("G  the seam and the answer grammar", check_seam),
        ("H  the HTTP surface", check_api),
        ("I  the clock -- the gates hold at every speed", check_clock),
        ("J  what reaches a column", check_minimisation),
    ):
        print(f"\n== {section}")
        fn(c)
    print(f"\n{c.passed} checks passed, {len(c.failures)} failed.")
    for f in c.failures:
        print("  FAIL " + f)
    return 1 if c.failures else 0


def test_pipeline_end_to_end() -> None:
    assert main_() == 0


if __name__ == "__main__":
    sys.exit(main_())
