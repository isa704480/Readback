"""Day 1, part one: which connection parameters does the socket actually take?

No microphone, no speech, no transcript. This opens a real socket per case, feeds
a second of digital silence at real-time pace, and records what the server did.
It answers the TODO(day1-01), (day1-02), (day1-03), (day1-06), (day1-08),
(day1-09), (day1-10) and (day1-12) markers in server/stream/live.py.

WHY THIS RUNS BEFORE THE VOICE EXPERIMENT. server/pipeline/detector.py currently
pushes `end_of_turn_confidence_threshold` on every ARM and IDLE transition, and
the ARMED/IDLE comment justifies the design on that lever existing:

    "The two ARMED values pull in opposite directions on purpose: the silence
     fallback gets longer, while the confidence threshold gets lower so that a
     turn the model is *sure* has ended still closes fast."

The API reference now says that parameter is "Universal Streaming (English and
Multilingual) only" -- i.e. not Universal-3.5 Pro, which is the model this system
connects with. If that is right, half of that sentence describes a button that is
not wired to anything. Reading it in a doc is not the same as watching the server
do it, and this file is the difference.

THE CONTROL IS THE POINT. A parameter that connects cleanly has NOT been shown to
be honoured -- it has only been shown not to be fatal. So one case sends an
invented parameter that certainly does not exist. What that case does tells you
what every other case means:

    bogus param is FATAL   -> the server validates names, so a clean connect is
                              evidence the name is at least recognised
    bogus param is IGNORED -> the server ignores unknown names, so a clean
                              connect is evidence of nothing at all, and the
                              only way to know whether a parameter does anything
                              is to measure its effect on real audio

Without that case the whole run is unfalsifiable. Read it first.

Run:
    cd D:/My_apps/Readback
    PYTHONPATH=. python experiments/day1/probe.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.stream.live import DEFAULT_URL, _resolve_api_key  # noqa: E402

try:
    from websockets.asyncio.client import connect as ws_connect
except Exception as exc:  # pragma: no cover
    print(f"websockets is required: {exc}")
    raise SystemExit(1)


SAMPLE_RATE = 16_000
CHUNK_MS = 100
# 100 ms of 16 kHz mono PCM16 silence. Inside the documented 50-1000 ms window;
# anything outside it closes the socket with 3007, which would make every case
# fail for a reason that has nothing to do with the parameter under test.
SILENT_CHUNK = b"\x00\x00" * (SAMPLE_RATE * CHUNK_MS // 1000)
CHUNKS = 6                      # 0.6 s of audio per case
RECV_GRACE_S = 3.0

# The account allows only a few concurrent sessions, and the server counts a
# socket as live for a moment after it closes. The first run of this file opened
# them back to back and cases 6-18 all died with
#     1008 "Unauthorized Connection: Too many concurrent sessions"
# which reads exactly like "this parameter was rejected" and is nothing of the
# kind. All thirteen had to be thrown away. Waiting between cases is not
# politeness here -- without it the run produces confident wrong answers.
SETTLE_S = 6.0


BASE: dict[str, Any] = {
    "speech_model": "universal-3-5-pro",
    "sample_rate": SAMPLE_RATE,
    "encoding": "pcm_s16le",
}


@dataclass
class Case:
    name: str
    extra: dict[str, Any]
    expect: str
    why: str


CASES: list[Case] = [
    Case("baseline", {}, "connects",
         "if this fails nothing else in the run means anything"),

    # THE CONTROL. Read the result of this one before any other.
    Case("CONTROL bogus param", {"readback_not_a_real_parameter": "1"}, "?",
         "decides whether 'connected cleanly' is evidence or noise"),

    # The two the API reference says belong to the older model only.
    Case("end_of_turn_confidence_threshold", {"end_of_turn_confidence_threshold": 0.5}, "?",
         "detector.py pushes this on every ARM/IDLE transition"),
    Case("format_turns", {"format_turns": "false"}, "?",
         "live.py sends false; if unsupported, finals are always formatted"),

    # The ones the reference says are U3.5 Pro's actual controls.
    Case("mode=balanced", {"mode": "balanced"}, "connects",
         "documented primary knob; unused by this system so far"),
    Case("mode=max_accuracy", {"mode": "max_accuracy"}, "connects", "the ARMED candidate"),
    Case("mode=min_latency", {"mode": "min_latency"}, "connects", "the IDLE candidate"),
    Case("max_turn_silence", {"max_turn_silence": 2500}, "connects",
         "the ARMED endpointing lever; documented default 1536"),
    Case("min_turn_silence", {"min_turn_silence": 300}, "connects", "documented, mode-dependent default"),
    Case("vad_threshold", {"vad_threshold": 0.3}, "connects", "documented default 0.2"),
    Case("prompt", {"prompt": "The speaker is reading a shipping container number."}, "connects",
         "FORMAT_PROMPT depends on this; documented cap 1750 chars"),
    Case("voice_focus", {"voice_focus": "near-field"}, "connects",
         "priced into config.py's cost model but never sent"),
    Case("continuous_partials", {"continuous_partials": "false"}, "?", "listed in the pasted brief"),
    Case("include_partial_turns", {"include_partial_turns": "true"}, "?", "listed in the pasted brief"),
    Case("language_detection", {"language_detection": "true"}, "?", "adds language_code to Turn"),

    # keyterms encoding -- TODO(day1-02). Two spellings, one of them wrong.
    Case("keyterms_prompt (JSON array)",
         {"keyterms_prompt": json.dumps(["MSKU", "container number", "bravo"])}, "?",
         "what _encode_keyterms() currently sends"),
    Case("keyterms_prompt (repeated)", {"__repeat_keyterms": ["MSKU", "bravo"]}, "?",
         "the alternative encoding; exactly one of these is right"),
    Case("keyterms_prompt (over 100)",
         {"keyterms_prompt": json.dumps([f"term{i}" for i in range(120)])}, "?",
         "arming sits against the 100 ceiling by design; error frame or close?"),
]


@dataclass
class Outcome:
    case: str
    connected: bool = False
    begin: dict[str, Any] | None = None
    frames: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    close_code: int | None = None
    termination: dict[str, Any] | None = None

    @property
    def verdict(self) -> str:
        if self.error and not self.connected:
            return f"REFUSED ({self.error[:60]})"
        if self.close_code and self.close_code not in (1000, 1005, 1006):
            return f"CLOSED {self.close_code}"
        if any(f.get("type") in ("Error", "error") for f in self.frames):
            err = next(f for f in self.frames if f.get("type") in ("Error", "error"))
            return f"ERROR FRAME {json.dumps(err)[:70]}"
        if self.connected:
            return "accepted (not fatal)"
        return f"failed ({self.error})"


def build_url(extra: dict[str, Any]) -> str:
    params: list[tuple[str, str]] = []
    for key, value in {**BASE, **extra}.items():
        if key == "__repeat_keyterms":
            params.extend(("keyterms_prompt", term) for term in value)
            continue
        params.append((key, str(value)))
    return f"{DEFAULT_URL}?{urllib.parse.urlencode(params)}"


async def run_case(case: Case, api_key: str) -> Outcome:
    out = Outcome(case=case.name)
    url = build_url(case.extra)
    try:
        async with ws_connect(url, additional_headers={"Authorization": api_key},
                              open_timeout=15, close_timeout=5) as ws:
            out.connected = True

            async def reader() -> None:
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        msg = json.loads(raw)
                        out.frames.append(msg)
                        if msg.get("type") == "Begin":
                            out.begin = msg
                        if msg.get("type") == "Termination":
                            out.termination = msg
                            return
                except Exception:
                    return

            task = asyncio.create_task(reader())

            # Real-time pacing is not politeness. Faster than real time closes
            # the socket with 3007, and that close would be misread as the
            # parameter being rejected.
            for _ in range(CHUNKS):
                await ws.send(SILENT_CHUNK)
                await asyncio.sleep(CHUNK_MS / 1000)

            await ws.send(json.dumps({"type": "Terminate"}))
            try:
                await asyncio.wait_for(task, timeout=RECV_GRACE_S)
            except asyncio.TimeoutError:
                task.cancel()
        out.close_code = 1000
    except Exception as exc:
        out.error = f"{type(exc).__name__}: {exc}"
        code = getattr(exc, "code", None)
        if isinstance(code, int):
            out.close_code = code
    return out


async def probe_update_configuration(api_key: str) -> Outcome:
    """TODO(day1-06): does UpdateConfiguration get acknowledged, and with what?

    The whole ARM path assumes the swap lands on one turn boundary. If the server
    says nothing at all, the runner has no way to know its bias took effect, and
    the arm has to be treated as advisory rather than confirmed.
    """
    out = Outcome(case="UpdateConfiguration mid-session")
    url = build_url({})
    try:
        async with ws_connect(url, additional_headers={"Authorization": api_key},
                              open_timeout=15, close_timeout=5) as ws:
            out.connected = True

            async def reader() -> None:
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        msg = json.loads(raw)
                        out.frames.append(msg)
                        if msg.get("type") == "Termination":
                            return
                except Exception:
                    return

            task = asyncio.create_task(reader())
            for _ in range(5):
                await ws.send(SILENT_CHUNK)
                await asyncio.sleep(CHUNK_MS / 1000)

            await ws.send(json.dumps({
                "type": "UpdateConfiguration",
                "keyterms_prompt": ["MSKU", "MSCU", "container number"],
                "max_turn_silence": 2500,
                # Sent on purpose even though the reference says it is not a
                # U3.5 Pro parameter: this is exactly the payload detector.py
                # builds today, so the question is whether it is ignored or
                # whether it takes the whole UpdateConfiguration down with it.
                "end_of_turn_confidence_threshold": 0.5,
            }))
            for _ in range(5):
                await ws.send(SILENT_CHUNK)
                await asyncio.sleep(CHUNK_MS / 1000)

            await ws.send(json.dumps({"type": "Terminate"}))
            try:
                await asyncio.wait_for(task, timeout=RECV_GRACE_S)
            except asyncio.TimeoutError:
                task.cancel()
        out.close_code = 1000
    except Exception as exc:
        out.error = f"{type(exc).__name__}: {exc}"
        code = getattr(exc, "code", None)
        if isinstance(code, int):
            out.close_code = code
    return out


async def main() -> int:
    api_key = _resolve_api_key()
    if not api_key:
        print("No AssemblyAI key found.")
        print("Put it in D:/My_apps/Readback/.env as:")
        print("    READBACK_ASSEMBLYAI_API_KEY=...")
        return 1
    print(f"key found ({len(api_key)} chars, not printed)\n")

    outcomes: list[Outcome] = []
    for index, case in enumerate(CASES):
        if index:
            await asyncio.sleep(SETTLE_S)
        out = await run_case(case, api_key)
        outcomes.append(out)
        busy = any("concurrent" in str(f.get("error", "")).lower() for f in out.frames)
        flag = "   <-- CONCURRENCY, says nothing about the parameter" if busy else ""
        print(f"  {case.name:34} {out.verdict}{flag}")

    upd = await probe_update_configuration(api_key)
    outcomes.append(upd)
    print(f"  {upd.case:34} {upd.verdict}")

    control = next(o for o in outcomes if o.case.startswith("CONTROL"))
    print("\n" + "=" * 76)
    print("READ THIS FIRST -- the control")
    print("=" * 76)
    if control.verdict == "accepted (not fatal)":
        print("  The server ACCEPTED an invented parameter name.")
        print("  Therefore 'accepted (not fatal)' above means ONLY that: not fatal.")
        print("  It is NOT evidence that a parameter is honoured. The two the")
        print("  reference calls Universal-Streaming-only will look identical to")
        print("  the ones that work, and only measured behaviour on real audio")
        print("  can separate them.")
    else:
        print(f"  The server REJECTED an invented parameter name ({control.verdict}).")
        print("  Therefore a clean connect IS evidence the name is recognised,")
        print("  and any case above that failed names a parameter this model")
        print("  does not have.")

    base = next((o.begin for o in outcomes if o.case == "baseline"), None)
    base_cfg = (base or {}).get("configuration")
    print("\n" + "=" * 76)
    print("Begin.configuration -- what the server says it actually accepted")
    print("=" * 76)
    print(f"  baseline: {json.dumps(base_cfg, sort_keys=True)}")
    print()
    print("  This echo is a better instrument than 'did it connect'. A parameter")
    print("  that CHANGES it is honoured; one that leaves it byte-identical is not")
    print("  part of this model's configuration surface. The bogus control is what")
    print("  makes that reading safe -- it proves the server drops names it does")
    print("  not know rather than complaining about them.")
    for out in outcomes:
        if out.case == "baseline" or not out.begin:
            continue
        cfg = out.begin.get("configuration")
        if cfg == base_cfg:
            print(f"    {out.case:34} NO CHANGE  -> ignored")
        else:
            diff = {k: v for k, v in (cfg or {}).items() if (base_cfg or {}).get(k) != v}
            print(f"    {out.case:34} CHANGED    -> {json.dumps(diff, sort_keys=True)}")

    print("\n" + "=" * 76)
    print("Frame types observed (answers day1-08/09/10/12)")
    print("=" * 76)
    kinds: dict[str, int] = {}
    for out in outcomes:
        for frame in out.frames:
            kinds[str(frame.get("type"))] = kinds.get(str(frame.get("type")), 0) + 1
    for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {kind:24} x{count}")

    begin = next((o.begin for o in outcomes if o.begin), None)
    if begin:
        print(f"\n  Begin fields:       {sorted(begin)}")
    term = next((o.termination for o in outcomes if o.termination), None)
    if term:
        print(f"  Termination fields: {sorted(term)}")
        print(f"  Termination sample: {json.dumps(term)}")

    report = Path(__file__).parent / "probe-results.json"
    report.write_text(json.dumps([{
        "case": o.case, "verdict": o.verdict, "connected": o.connected,
        "close_code": o.close_code, "error": o.error,
        "frames": o.frames[:40],
    } for o in outcomes], indent=2), encoding="utf-8")
    print(f"\nraw frames written to {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
