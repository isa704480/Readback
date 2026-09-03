"""Regression test for the transcript-source seam and the replay implementation.

The property this file defends is not "the replay works". It is that **the rest
of the system can be built and measured today against something that behaves
like the socket that does not exist yet** — and therefore that the awkward parts
survive the substitution. Four of them, each with its own check below:

  partials MUTATE               a consumer that appends instead of replacing
                                ends up with words the speaker never said
  identifiers STRADDLE turns    the canonical place for a human pause is inside
                                a code, so a turn boundary is never a parse
                                boundary
  confidence has SPREAD         and it overlaps, so confidence alone can never
                                separate right from wrong; that is the whole
                                reason there is a posterior
  reconfiguration is LATE       upstream cannot re-bias a turn it has already
                                started, so keyterms land one turn after the
                                request and the detector has to be built knowing it

Run:  PYTHONPATH=. python tests/test_replay.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any, Sequence

from server.readback.normalise import pass1, pass2
from server.readback.solver import ISO, decide
from server.readback.validators import iso_ok
from server.stream.live import LiveSource
from server.stream.replay import Fixture, FrameEntry, ReplaySource, fixture_dir, load_all
from server.stream.source import (
    SourceConfig,
    TranscriptSource,
    Turn,
    Word,
    validate_turn,
)
from server.stream.tape import Tape


# --------------------------------------------------------------- utilities --
def gated(entries: Sequence[FrameEntry], keyterms: Sequence[str] = ()) -> list[FrameEntry]:
    """The entries a replay should deliver under this arming state."""
    armed = {k.upper() for k in keyterms}
    out = []
    for e in entries:
        if e.requires_keyterm and e.requires_keyterm.upper() not in armed:
            continue
        if e.forbids_keyterm and e.forbids_keyterm.upper() in armed:
            continue
        out.append(e)
    return out


def cells_with_conf(words: Sequence[Word]) -> list[tuple[list, float]]:
    """Per-word normalisation, carrying each word's confidence onto every cell
    it produces.

    Per-word rather than over the joined text, because the solver needs a
    confidence per POSITION and the joined-text path loses the alignment. The
    cost is that multi-token constructions ("double four", "B for Bravo") are
    not seen; none of the identifier fixtures uses one, and the conversation
    fixture is checked both ways below precisely because it does.
    """
    out: list[tuple[list, float]] = []
    for w in words:
        cells, _notes = pass1(w["text"])
        for cell in cells:
            out.append((cell, w["confidence"]))
    return out


def scan(pairs: Sequence[tuple[list, float]], fmt=ISO) -> tuple[int, str, list[float]] | None:
    """Slide the format's length along the normalised timeline and return the
    first window that validates.

    ARCHITECTURE 3.6 cue (d). This is how a straddling identifier is recovered
    without anybody telling the system where it starts, and running it over two
    minutes of conversation is the false-positive test.
    """
    for i in range(0, max(0, len(pairs) - fmt.length) + 1):
        window = pairs[i:i + fmt.length]
        value, _c, _t, n = pass2([p[0] for p in window], fmt.A, fmt.length)
        if n == fmt.length and len(value) == fmt.length and fmt.ok(value):
            return i, value, [p[1] for p in window]
    return None


def greedy(pairs: Sequence[tuple[list, float]], fmt=ISO) -> tuple[str, list[float]]:
    """The first `length` cells, valid or not. What the detector hands the
    solver when nothing validates -- which is the case the solver is for."""
    value, _c, _t, _n = pass2([p[0] for p in pairs], fmt.A, fmt.length)
    return value, [p[1] for p in pairs][:fmt.length]


async def collect(fx: Fixture, keyterms: Sequence[str] = (), speed: float = 0.0) -> tuple[list[Turn], Tape, ReplaySource]:
    src = ReplaySource(fx, speed=speed, config=SourceConfig(keyterms=tuple(keyterms)))
    tape = Tape()
    frames: list[Turn] = []
    async with src:
        async for frame in src:
            frames.append(frame)
            tape.push(frame)
    return frames, tape, src


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
        print(f"  {mark} {label}" + (f"  [{detail}]" if detail and not condition else ""))

    def eq(self, label: str, got: Any, want: Any) -> None:
        self.ok(label, got == want, f"got {got!r}, want {want!r}")


# ----------------------------------------------------------------- checks ---
def check_round_trip(c: Checks, fx: Fixture) -> None:
    """Every frame in the file comes out of the source unchanged, in order."""
    frames, _tape, src = asyncio.run(collect(fx))
    expected = [e.frame for e in gated(fx.entries)]

    c.eq(f"{fx.name}: frame count", len(frames), len(expected))
    c.ok(f"{fx.name}: frames identical to file", frames == expected)
    c.ok(
        f"{fx.name}: every frame is the documented Turn shape",
        all(validate_turn(f, fx.name) is f for f in frames),
    )
    c.ok(
        f"{fx.name}: delivery order is monotone",
        all(a.emit_ms <= b.emit_ms for a, b in zip(fx.entries, fx.entries[1:])),
    )
    orders = [f["turn_order"] for f in frames]
    c.eq(f"{fx.name}: turn count", len(set(orders)), fx.expect.get("turns", len(set(orders))))
    # One final per turn, and it is that turn's last frame. With
    # format_turns=false there is exactly one; the count is what would catch a
    # model swap that started emitting a formatted second final.
    multi = [o for o in set(orders)
             if sum(1 for f in frames if f["turn_order"] == o and f["end_of_turn"]) != 1]
    not_last = [o for o in set(orders)
                if not [f for f in frames if f["turn_order"] == o][-1]["end_of_turn"]]
    c.ok(f"{fx.name}: exactly one final per turn", not multi, f"turns {multi}")
    c.ok(f"{fx.name}: each turn's final is its last frame", not not_last, f"turns {not_last}")
    # Two runs must be equal AND independent: a consumer mutates what it is
    # given, and a fixture that mutates under it is a debugging session nobody
    # should have to have.
    for f in frames:
        f["transcript"] = "MUTATED BY THE CONSUMER"
    again, _t2, _s2 = asyncio.run(collect(fx))
    c.ok(f"{fx.name}: replay is repeatable and isolated", again == expected)
    c.ok(f"{fx.name}: billed seconds reported", isinstance(src.billed_seconds, float))


def check_partial_mutation(c: Checks, fx: Fixture) -> None:
    """Replacement, not appending -- and the check has teeth only if appending
    would demonstrably produce something else."""
    stale = fx.expect.get("mutating_words") or []
    if not stale:
        return
    frames, tape, _src = asyncio.run(collect(fx))
    order = frames[0]["turn_order"]
    of_turn = [f for f in frames if f["turn_order"] == order]
    final = of_turn[-1]

    appended = " ".join(f["transcript"] for f in of_turn)
    replaced = tape.turns[0]["transcript"]

    c.eq(f"{fx.name}: tape holds the final transcript", replaced, final["transcript"])
    c.ok(
        f"{fx.name}: appending would be longer",
        len(appended) > len(replaced),
        f"{len(appended)} vs {len(replaced)}",
    )
    seen_stale = [w for w in stale if w in appended]
    c.ok(
        f"{fx.name}: appending resurrects abandoned hypotheses",
        len(seen_stale) > 0,
        f"expected any of {stale} in the concatenation",
    )
    c.ok(
        f"{fx.name}: replacement contains none of them",
        not any(w in replaced.split() for w in stale),
        f"{[w for w in stale if w in replaced.split()]} survived into the final",
    )
    # The mutation is real at the word level too, not just in the transcript.
    mutated = False
    for word in final["words"]:
        earlier = [
            w for f in of_turn[:-1] for w in f["words"]
            if w["start"] == word["start"] and w["text"] != word["text"]
        ]
        if earlier:
            mutated = True
            c.ok(
                f"{fx.name}: '{earlier[0]['text']}' -> '{word['text']}' was not final while it changed",
                not earlier[0]["word_is_final"],
            )
    c.ok(f"{fx.name}: at least one word mutated", mutated)
    # A partial arriving after the final must not un-finish the turn.
    late_partial: Turn = json.loads(json.dumps(final))
    late_partial["end_of_turn"] = False
    late_partial["transcript"] = "a late partial that must be ignored"
    c.ok(f"{fx.name}: a late partial cannot displace a final", not tape.push(late_partial))
    c.eq(f"{fx.name}: final survived the late partial", tape.turns[0]["transcript"], final["transcript"])


def check_straddle(c: Checks, fx: Fixture) -> None:
    """The identifier is recoverable from the flattened timeline, across three
    turns, a hesitation and trailing conversational noise."""
    for keyterms, key in ((), "normalised_unarmed"), (("MSKU",), "normalised_armed"):
        want = fx.expect[key]
        _frames, tape, _src = asyncio.run(collect(fx, keyterms))

        c.ok(
            f"{fx.name}: spans {fx.expect['turns']} turns ({key})",
            len({t['turn_order'] for t in tape.turns}) == fx.expect["turns"],
        )
        words = tape.words(finals_only=True)
        c.ok(
            f"{fx.name}: flattened timeline is time-ordered ({key})",
            all(a["start"] <= b["start"] for a, b in zip(words, words[1:])),
        )
        # The identifier is not aligned to a turn: it starts inside turn 0 and
        # ends inside turn 2. Recovering it per-turn is impossible by
        # construction, which is the point of the fixture.
        per_turn = [scan(cells_with_conf(t["words"])) for t in tape.turns if t["end_of_turn"]]
        c.ok(f"{fx.name}: no single turn contains it ({key})", not any(per_turn))

        found = scan(cells_with_conf(words))
        c.ok(f"{fx.name}: recovered from the flattened timeline ({key})", found is not None)
        if found:
            _i, value, _confs = found
            c.eq(f"{fx.name}: recovered value ({key})", value, want)
            c.ok(f"{fx.name}: recovered value validates ({key})", iso_ok(value))


def check_config_is_one_turn_late(c: Checks, fx: Fixture) -> None:
    """update_configuration takes effect from the NEXT turn, never the one in
    flight. Proved twice: arming during turn 0 changes turn 1, and arming during
    turn 1 does not change turn 1."""

    async def arm_at(target_turn: int) -> tuple[ReplaySource, Tape, list[str]]:
        src = ReplaySource(fx, speed=0.0)
        tape = Tape()
        trace: list[str] = []
        armed = False
        async with src:
            async for frame in src:
                tape.push(frame)
                if not armed and frame["turn_order"] == target_turn:
                    # Mid-turn, exactly as the detector would: it fires on a
                    # partial, while the code is still being spoken.
                    await src.update_configuration(keyterms=["MSKU"], max_turn_silence=2500)
                    armed = True
                    trace.append(f"requested during turn {frame['turn_order']}")
                trace.append(
                    f"turn {frame['turn_order']} delivered under keyterms={src.config.keyterms}"
                )
        return src, tape, trace

    # (a) armed during turn 0 -> effective from turn 1
    src, tape, _trace = asyncio.run(arm_at(0))
    event = next(e for e in src.control_log if e.kind == "update_configuration")
    c.eq(f"{fx.name}: requested during turn", event.requested_turn, 0)
    c.eq(f"{fx.name}: applied at turn", event.applied_turn, 1)
    c.eq(f"{fx.name}: effective keyterms at end", src.config.keyterms, ("MSKU",))
    c.eq(f"{fx.name}: max_turn_silence followed the same boundary", src.config.max_turn_silence, 2500)
    found = scan(cells_with_conf(tape.words(finals_only=True)))
    c.ok(f"{fx.name}: turn 1 came back armed", found is not None)
    if found:
        c.eq(f"{fx.name}: armed value", found[1], fx.expect["normalised_armed"])

    # (b) armed during turn 1 -> turn 1 is already gone; it lands at turn 2
    src2, tape2, _trace2 = asyncio.run(arm_at(1))
    event2 = next(e for e in src2.control_log if e.kind == "update_configuration")
    c.eq(f"{fx.name}: late request logged against turn", event2.requested_turn, 1)
    c.eq(f"{fx.name}: late request applied at turn", event2.applied_turn, 2)
    found2 = scan(cells_with_conf(tape2.words(finals_only=True)))
    c.ok(f"{fx.name}: turn 1 was NOT retroactively re-biased", found2 is not None)
    if found2:
        c.eq(f"{fx.name}: late-armed value", found2[1], fx.expect["normalised_unarmed"])

    # And the pending configuration is visible while it waits, so the detector
    # can tell "asked for" from "in force".
    src3 = ReplaySource(fx, speed=0.0)

    async def peek() -> tuple[Any, Any]:
        seen_pending = None
        async with src3:
            async for frame in src3:
                if frame["turn_order"] == 0 and src3.pending_config is None:
                    await src3.update_configuration(keyterms=["MSKU"])
                    seen_pending = (src3.pending_config, src3.config.keyterms)
                    break
        return seen_pending or (None, None)

    pending, effective = asyncio.run(peek())
    c.ok(f"{fx.name}: pending config is visible while it waits", pending is not None)
    c.eq(f"{fx.name}: config in force is unchanged meanwhile", effective, ())


def check_force_endpoint(c: Checks, fx: Fixture) -> None:
    """ForceEndpoint closes the turn in flight: the partials that would have
    arrived during the endpoint timer never do, and the final lands now."""

    async def run() -> tuple[list[Turn], ReplaySource]:
        src = ReplaySource(fx, speed=0.0)
        frames: list[Turn] = []
        async with src:
            async for frame in src:
                frames.append(frame)
                if len(frames) == 3:
                    await src.force_endpoint()
        return frames, src

    frames, src = asyncio.run(run())
    baseline = [e.frame for e in gated(fx.entries)]
    event = next(e for e in src.control_log if e.kind == "force_endpoint")

    c.ok("force_endpoint: partials were dropped", len(frames) < len(baseline),
         f"{len(frames)} vs {len(baseline)}")
    c.ok("force_endpoint: dropped count recorded", event.detail.get("frames_dropped", 0) > 0)
    c.ok("force_endpoint: reclaimed time recorded", event.detail.get("ms_saved", 0) > 0,
         f"ms_saved={event.detail.get('ms_saved')}")
    c.ok("force_endpoint: the final still arrives", frames[-1]["end_of_turn"])
    c.eq("force_endpoint: and it is the recorded final", frames[-1], baseline[-1])


def check_timing(c: Checks, fx: Fixture) -> None:
    """Relative timing is reproduced, and the speed factor scales it.

    Worth a test because the rhythm detector (3.6) reads `words[].start` over a
    sliding window: a replay that delivered everything at once would let a
    broken IOI window pass, and a replay that delivered on a fixed tick would
    make cv_ioi meaningless.
    """
    speed = 40.0
    t0 = time.monotonic()
    frames, _tape, _src = asyncio.run(collect(fx, speed=speed))
    wall_ms = (time.monotonic() - t0) * 1000.0
    want_ms = fx.duration_ms / speed

    c.ok(
        f"timing: {fx.name} at {speed:g}x took about {want_ms:.0f} ms",
        want_ms * 0.7 <= wall_ms <= want_ms + 900,
        f"{wall_ms:.0f} ms, wanted ~{want_ms:.0f} ms",
    )
    # Word timings inside the frames are session-relative and untouched by speed.
    instant, _t, _s = asyncio.run(collect(fx))
    c.ok("timing: word timestamps are unaffected by the speed factor", frames == instant)

    starts = [w["start"] for f in frames if f["end_of_turn"] for w in f["words"]]
    iois = [b - a for a, b in zip(starts, starts[1:]) if b > a]
    c.ok("timing: inter-onset intervals are not uniform", len(set(iois)) > 3,
         f"{len(set(iois))} distinct IOIs")


def check_conversation(c: Checks, fx: Fixture) -> None:
    """Two minutes with no identifier in it. The false-positive corpus."""
    frames, tape, _src = asyncio.run(collect(fx))

    c.ok("conversation: at least two minutes", fx.duration_ms >= fx.expect["min_duration_ms"],
         f"{fx.duration_ms} ms")
    c.eq("conversation: turn count", len({f["turn_order"] for f in frames}), fx.expect["turns"])
    # The tape holds 45 s / 400 words and no more (3.4, 3.12), so it must NOT
    # still be holding two minutes of a conversation nobody has consented to
    # keep. That it drops turns here is the privacy control working.
    c.ok("conversation: the tape dropped what it is not allowed to keep",
         len(tape.turns) < fx.expect["turns"],
         f"tape holds {len(tape.turns)} of {fx.expect['turns']} turns")

    # The tape is bounded, so it cannot hold two minutes; that is the design
    # (3.4, 3.12). Scan the full timeline separately from what the tape retains.
    all_words: list[Word] = []
    for order in sorted({f["turn_order"] for f in frames}):
        final = [f for f in frames if f["turn_order"] == order and f["end_of_turn"]][-1]
        all_words.extend(final["words"])
    all_words.sort(key=lambda w: (w["start"], w["end"]))

    per_word = scan(cells_with_conf(all_words))
    c.ok("conversation: per-word scan finds no identifier", per_word is None,
         f"found {per_word[1] if per_word else None}")

    joined = " ".join(w["text"] for w in all_words)
    cells, _notes = pass1(joined)
    whole = None
    for i in range(0, max(0, len(cells) - ISO.length) + 1):
        value, _cf, _tr, n = pass2(cells[i:i + ISO.length], ISO.A, ISO.length)
        if n == ISO.length and len(value) == ISO.length and iso_ok(value):
            whole = value
            break
    c.ok("conversation: whole-text scan finds no identifier either", whole is None,
         f"found {whole}")
    c.ok(
        "conversation: and it does produce characters to be wrong about",
        len(cells) > 20,
        f"{len(cells)} cells normalised out of ordinary speech",
    )

    late = fx.expect.get("late_finals", 0)
    c.ok("conversation: finals arrive late, as a 1536 ms endpoint makes them", late > 0,
         f"{late} late finals")


def check_solver(c: Checks, fx: Fixture) -> None:
    """The corpus reaches the solver as the corpus intends.

    Not a test of the solver -- that is tests/test_solver_regression.py. It is a
    test that the fixture, the tape and the normaliser hand it the string and
    the confidences the fixture says they do, because a fixture whose documented
    behaviour has silently drifted is worse than no fixture.
    """
    if not fx.expect.get("contains_identifier"):
        return
    variants: list[tuple[tuple[str, ...], str, str, str | None]]
    if "solver_action_armed" in fx.expect:
        variants = [
            ((), "solver_action_unarmed", "solver_top_unarmed", "ask_position_unarmed"),
            (("MSKU",), "solver_action_armed", "solver_top_armed", None),
        ]
    else:
        variants = [((), "solver_action", "solver_top", "ask_position")]

    for keyterms, action_key, top_key, ask_key in variants:
        if action_key not in fx.expect:
            continue
        _frames, tape, _src = asyncio.run(collect(fx, keyterms))
        pairs = cells_with_conf(tape.words(finals_only=True))
        found = scan(pairs)
        value, confs = (found[1], found[2]) if found else greedy(pairs)
        result = decide(ISO, value, confs)
        tag = f"{fx.name}{'/armed' if keyterms else ''}"

        c.eq(f"{tag}: solver action", result["action"], fx.expect[action_key])
        c.eq(f"{tag}: solver top candidate", result["top"], fx.expect[top_key])
        if ask_key and fx.expect.get(ask_key) is not None:
            c.eq(f"{tag}: asks about position", result["ask_pos"], fx.expect[ask_key])
        if fx.expect.get("must_not_accept_silently"):
            c.ok(f"{tag}: does not accept a blind substitution silently",
                 result["action"] != "ACCEPT", result["action"])
        if fx.expect.get("silent_repair"):
            c.ok(f"{tag}: repairs in silence", result["action"] == "ACCEPT", result["action"])


def check_seam(c: Checks) -> None:
    """Both implementations satisfy one contract, and neither leaks.

    LiveSource is constructed with a dummy key and never connected -- there is
    no key today, which is the entire premise. What this asserts is that when
    one arrives, the substitution is a constructor argument.
    """
    fx = Fixture.load(fixture_dir() / "iso_clean_single_turn.json")
    replay = ReplaySource(fx)
    live = LiveSource("not-a-real-key-and-never-connected")

    for name, src in (("ReplaySource", replay), ("LiveSource", live)):
        c.ok(f"seam: {name} satisfies TranscriptSource", isinstance(src, TranscriptSource))
        for attr in ("send_audio", "update_configuration", "force_endpoint",
                     "terminate", "config", "control_log", "session_id",
                     "billed_seconds", "__aiter__", "__aenter__", "__aexit__"):
            c.ok(f"seam: {name}.{attr}", hasattr(src, attr))

    # Configuration semantics are shared, not reimplemented per source.
    async def cfg() -> None:
        await live.update_configuration(keyterms=["MSKU", "TGHU"], max_turn_silence=2500)

    asyncio.run(cfg())
    c.eq("seam: live config is pending before any turn", live.config.keyterms, ())
    c.ok("seam: live pending config recorded", live.pending_config is not None)
    c.eq("seam: control log shared", live.control_log[0].kind, "update_configuration")

    # The caps are enforced in the contract, not at the socket, because arming
    # sits right against the 100-term ceiling by design (3.6).
    async def too_many() -> bool:
        try:
            await replay.update_configuration(keyterms=[f"T{i:03d}" for i in range(101)])
        except Exception as exc:
            return "101" in str(exc) or "cap" in str(exc)
        return False

    c.ok("seam: an over-long keyterm list is refused before it is sent", asyncio.run(too_many()))


def check_send_audio_and_terminate(c: Checks, fx: Fixture) -> None:
    """Audio goes through the interface on both sides, and terminate cuts the
    stream where it stands."""

    async def run() -> tuple[ReplaySource, int]:
        src = ReplaySource(fx, speed=0.0)
        n = 0
        async with src:
            async for _frame in src:
                await src.send_audio(b"\x00" * 640)     # 20 ms of 16 kHz s16le
                n += 1
                if n == 4:
                    await src.terminate()
        return src, n

    src, n = asyncio.run(run())
    c.eq("terminate: iteration stopped where it was told", n, 4)
    c.eq("terminate: audio accounted for", src.audio_bytes_sent, 4 * 640)
    c.ok("terminate: source is closed", src.closed)
    c.ok("terminate: billed seconds set", isinstance(src.billed_seconds, float))
    c.eq("terminate: logged", src.control_log[-1].kind, "terminate")

    async def after_close() -> bool:
        try:
            await src.send_audio(b"\x00")
        except Exception:
            return True
        return False

    c.ok("terminate: sending after close is refused", asyncio.run(after_close()))


# -------------------------------------------------------------------- main --
def main() -> int:
    fixtures = load_all()
    if not fixtures:
        print("no fixtures found -- run: python tests/fixtures/make_fixtures.py")
        return 1

    c = Checks()
    print(f"corpus: {len(fixtures)} fixtures in {fixture_dir()}")
    for fx in fixtures:
        frames = len(fx.entries)
        print(f"\n[{fx.name}]  {len(fx.turn_orders)} turns, {frames} frames, "
              f"{fx.duration_ms / 1000:.1f} s")
        check_round_trip(c, fx)
        check_partial_mutation(c, fx)
        check_solver(c, fx)

    print("\n[straddling identifier]")
    straddle = next(f for f in fixtures if f.name == "iso_straddle_three_turns")
    check_straddle(c, straddle)

    print("\n[mid-stream reconfiguration]")
    check_config_is_one_turn_late(c, straddle)

    print("\n[force endpoint]")
    check_force_endpoint(c, next(f for f in fixtures if f.name == "iso_clean_single_turn"))

    print("\n[timing]")
    check_timing(c, next(f for f in fixtures if f.name == "iso_clean_single_turn"))

    print("\n[two minutes of nothing]")
    check_conversation(c, next(f for f in fixtures if f.name == "conversation_no_identifier"))

    print("\n[the seam]")
    check_seam(c)
    check_send_audio_and_terminate(
        c, next(f for f in fixtures if f.name == "iso_clean_single_turn")
    )

    print()
    if c.failures:
        for f in c.failures:
            print("  FAIL:", f)
        print(f"\n  {len(c.failures)} failed, {c.passed} passed.")
        return 1
    print(f"  PASS -- {c.passed} checks over {len(fixtures)} fixtures.")
    print("  NOTE: the confidence values in this corpus are invented. Regenerate "
          "from recorded\n        sessions once the key lands; the frames are already "
          "the wire format.")
    return 0


def test_replay() -> None:
    """pytest entry point; the script above is the readable one."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
