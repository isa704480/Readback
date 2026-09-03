"""The false-positive contract: the detector may arm on a conversation, but it
may never reach COMMIT on one.

The distinction is the whole of ARM/IDLE. Arming rewrites the keyterm bias for
twelve seconds and is invisible and reversible, so one cue is allowed to do it.
COMMIT is the gate in front of everything a human can perceive -- a number
written down, a question asked out loud -- so it takes two cues, and the two are
only worth two if they fail independently.

This file exists because they did not. `tests/fixtures/conversation_no_identifier.json`
is 124 s of shipping-desk talk with no identifier in it, and on it the detector
reached commit_ok THREE times: the carrier table contained bare "booking", which
that conversation says twice ("the booking or the customs one"), and the rhythm
cue fires 3 times on ordinary speech. Nothing was captured only because the shape
cue happened to find no run -- 2-of-4 standing on one cue.

Three assertions, and they are deliberately different in kind:

  A. No carrier phrase may match a conversation. This is a PRECISION contract on
     a hand-written table, and it is the one that is enforceable, because a
     carrier phrase is chosen by a person and can be chosen better.

  B. The conversation must never reach commit_ok. This is the end-to-end
     property A exists to protect.

  C. A non-identifier fixture must not open a capture row either. B is a
     contract on the detector; C is the contract on what the runner does with
     it. They are different in kind for the same reason A and B are: 3.6 says
     ">= 2 of 4 before anything is written or spoken", and `st.open_capture` IS
     a write -- it persists `heard_value` and puts an amber row on the rack.
     `verdict.commit_ok` was computed in detector.py and read by nothing; the
     row was opened on ARMED-plus-shape, which is one cue plus a cue that fires
     on any run of ten digits. C is what holds that wired.

What is deliberately NOT asserted: that rhythm never fires on conversation. It
does, 3 windows in 332, and the measurement says to leave it alone -- those
windows run cv 0.167-0.336 while genuine dictation runs 0.083-0.336, so the
distributions OVERLAP and no threshold separates them. Tightening CV_IOI_MAX to
0.15 clears this one fixture and would be fitting a constant to a single sample
of English conversation. Rhythm alone arming is the design working; rhythm alone
committing is what B forbids.

**And the corpus B ran against could not exercise the defect it was written for.**
There was one negative fixture and its longest readable run is far short of ten
characters, so the cue that fires on any ten digits never got the chance --
B passed for two minutes of talk and said nothing at all about a phone number.
Three fixtures close that: `phone_number_in_conversation` (an eleven-digit UK
mobile given mid-call, one of whose ten-digit windows the NHS check digit
accepts), `meter_reading_sixteen_digits` (sixteen digits that pass Luhn, which is
a payment card by shape and by checksum) and `date_range_welded` (two dates
bridged by "to", which reads as the digit 2). All three are carrier-free on
purpose: a carrier phrase is an independent cue and 3.6 is entitled to open on
carrier+rhythm, so a negative fixture carrying one would be testing 3.8 instead.

Measured on those three before the independence repair: 17, 14 and 16 commit_ok
observations, and three persisted rows -- `0776773992` under `format_type="nhs"`,
`8737983960106896` under `format_type="luhn16"`, `0109208092` under `"nhs"`.

Run:  PYTHONPATH=. python tests/test_detector_falsepos.py
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import sys

from server.pipeline import events as ev
from server.pipeline.detector import CARRIERS, Detector, State, _flatten
from server.pipeline.runner import RunnerConfig, run_session
from server.pipeline.tape import Tape
from server.stream.replay import Fixture, ReplaySource
from server.stream.source import SourceConfig

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def fixture_text(fx: dict) -> str:
    """Every word ever emitted, including words later revised away.

    Revised-away words count: the detector sees each frame as it arrives, so a
    carrier phrase that appears in a partial and is corrected in the final has
    still already armed the machine by the time the correction lands.
    """
    return _flatten(" ".join(
        w["text"] for fr in fx["frames"] for w in fr["frame"].get("words", ())
    ))


def replay(fx: dict) -> dict:
    tape, det = Tape(), Detector()
    out = {"armed": [], "commit": [], "cues_at_commit": [], "collapsed": []}
    for f in fx["frames"]:
        tape.ingest(f["frame"])
        v = det.observe(tape)
        if v.state is State.ARMED and (not out["armed"] or out["armed"][-1] != "on"):
            pass
        if v.commit_ok:
            out["commit"].append(tape.now_ms)
            out["cues_at_commit"].append(sorted(c.value for c in v.cues))
        # Observations where a cue fired and was then not counted, because the
        # shape hit could not have failed its own mask. Reported rather than
        # asserted: it is the size of the hole, and a fixture where it is zero
        # is a fixture that does not exercise the repair.
        if v.report.collapsed:
            out["collapsed"].append(tape.now_ms)
        if v.state is State.ARMED:
            out["armed"].append(tape.now_ms)
    return out


def capture_rows(name: str) -> list:
    """Every capture row `run_session` persists for one fixture.

    The full runner, not the detector: assertion C is about what is written,
    and only the runner writes."""
    src = ReplaySource(Fixture.load(FIXTURES / f"{name}.json"), speed=0.0,
                       config=SourceConfig())
    summary = asyncio.run(run_session(src, ev.EventStream(),
                                      config=RunnerConfig(session_id=name)))
    return list(summary.captures)


def main() -> int:
    failures: list[str] = []

    # -- A. precision of the carrier table -----------------------------------
    conv = load("conversation_no_identifier")
    assert conv["expect"]["contains_identifier"] is False, "wrong fixture"
    text = fixture_text(conv)

    print("A. carrier phrases vs 124 s of conversation with no identifier")
    hits: list[tuple[str, str]] = []
    for phrase in sorted(CARRIERS, key=len, reverse=True):
        for m in re.finditer(r"\b%s\b" % re.escape(phrase), text):
            ctx = text[max(0, m.start() - 40):m.end() + 30]
            hits.append((phrase, ctx))
    if hits:
        for phrase, ctx in hits:
            print(f"   MATCH {phrase!r} -> {CARRIERS[phrase]}  ...{ctx}...")
        failures.append(
            f"{len(hits)} carrier phrase(s) match ordinary conversation: "
            f"{sorted({p for p, _ in hits})}. A carrier must be a phrase nobody "
            f"utters by accident -- it is the only cue that also names the format."
        )
    else:
        print(f"   none of {len(CARRIERS)} phrases match. ok")

    # -- A2. and against the three digit fixtures ----------------------------
    # The carrier table is the only cue that names a format, so its precision
    # contract has to hold against the digits too, not only against prose. If a
    # phrase ever matched here, assertion B would go on passing for the wrong
    # reason -- the fixture would be committing on a legitimate carrier cue.
    print("\nA2. carrier phrases vs the three non-identifier digit fixtures")
    for name in ("phone_number_in_conversation", "meter_reading_sixteen_digits",
                 "date_range_welded"):
        fx = load(name)
        assert fx["expect"]["contains_identifier"] is False, name
        text = fixture_text(fx)
        found = sorted({p for p in CARRIERS
                        if re.search(r"\b%s\b" % re.escape(p), text)})
        print(f"   {name:32} {len(found)} match(es) {found if found else ''}")
        if found:
            failures.append(
                f"{name}: carrier phrase(s) {found} match a fixture that was "
                f"built carrier-free. It is no longer testing 3.6's cue "
                f"independence, it is testing 3.8."
            )

    # -- B. the conversation never reaches COMMIT ----------------------------
    print("\nB. commit gate over every fixture")
    print(f"   {'fixture':32} {'has id':>7} {'armed':>6} {'commit':>7} {'collapsed':>10}")
    for path in sorted(FIXTURES.glob("*.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        has_id = fx["expect"].get("contains_identifier", True)
        r = replay(fx)
        n_arm, n_commit = len(r["armed"]), len(r["commit"])
        print(f"   {fx['name']:32} {str(has_id):>7} {n_arm:>6} {n_commit:>7} "
              f"{len(r['collapsed']):>10}")

        if not has_id and n_commit:
            for ms, cues in zip(r["commit"][:3], r["cues_at_commit"][:3]):
                print(f"        commit_ok at {ms} ms on {cues}")
            failures.append(
                f"{fx['name']}: reached commit_ok {n_commit}x on a fixture with "
                f"no identifier in it"
            )
        if has_id and not n_commit:
            failures.append(f"{fx['name']}: never reached commit_ok, but contains an identifier")

    # -- C. and nothing is written down --------------------------------------
    # B is the detector's contract. This is the runner's, and the two are not the
    # same statement: the row used to be opened on ARMED-plus-shape regardless of
    # what commit_ok said, so B could hold while a telephone number was persisted
    # anyway. The identifier fixtures are asserted in the same pass, because a
    # rule that stops the false rows by stopping every row is not a fix.
    print("\nC. capture rows written by run_session")
    print(f"   {'fixture':32} {'has id':>7} {'rows':>5}  heard")
    for path in sorted(FIXTURES.glob("*.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        has_id = fx["expect"].get("contains_identifier", True)
        rows = capture_rows(fx["name"])
        heard = ", ".join(str(c.heard_value) for c in rows) or "-"
        print(f"   {fx['name']:32} {str(has_id):>7} {len(rows):>5}  {heard}")

        if not has_id and rows:
            failures.append(
                f"{fx['name']}: {len(rows)} capture row(s) written for a fixture "
                f"with no identifier in it, heard_value={heard!r}. 3.6 puts the "
                f"2-of-4 gate in front of anything being written, and "
                f"st.open_capture is a write."
            )
        if has_id and not rows:
            failures.append(
                f"{fx['name']}: no capture row at all, but it contains an "
                f"identifier. The gate has been moved too far."
            )

    print()
    if failures:
        for f in failures:
            print("  FAIL:", f)
        return 1
    print("  PASS -- no carrier fires on conversation; the commit gate holds; "
          "and nothing was written down.")
    return 0


# `pytest -q` did not collect this file. It has always been a script with a
# `main`, and pytest collects functions named `test_*`, so the false-positive
# contract was written down, was runnable by hand, and was not run by the suite
# that everything else is gated on -- which is most of the reason a defect this
# large lived behind it. One line, and the contract is enforced where it is read.
def test_detector_false_positives() -> None:
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
