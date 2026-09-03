"""Day 1, part 1b: the limits, and the fields the echo can actually settle.

`probe.py` established that `Begin.configuration` echoes only eight fields, so
it is decisive for those and silent about everything else. This file uses that
properly: it asks about the echoed fields (where the echo is proof) and about
the documented caps (where an error frame is proof), and asks nothing whose
answer would have to be inferred from a clean connect — the bogus-parameter
control in probe.py already showed that a clean connect means nothing.

Open questions it closes:

  1. Is `MAX_KEYTERM_CHARS = 50` in detector.py a real server limit, or a number
     inherited from a different model? The 100-item cap is real and fatal; the
     per-term cap has never been checked. If it is not real, detector.py is
     discarding terms it could have sent.
  2. Is the documented `prompt` cap of 1750 characters enforced, and how?
  3. Do `voice_focus`, `speaker_labels`, `domain` and `filter_profanity` reach
     the session? These four ARE in the echo, so the answer is unambiguous.
     `voice_focus` matters because config.py's cost model already prices it in
     ("universal-3-5-pro 0.45 + voice_focus 0.10 + prompting 0.05") while
     live.py has never sent it.

Run:
    cd D:/My_apps/Readback
    PYTHONPATH=. python experiments/day1/probe2.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.day1.probe import (  # noqa: E402
    SETTLE_S,
    Case,
    Outcome,
    run_case,
)
from server.stream.live import _resolve_api_key  # noqa: E402

# 60 and 200 characters. 60 is just over detector.py's assumed 50; 200 is far
# enough past any plausible cap that a silent acceptance is meaningful.
TERM_60 = "a" * 60
TERM_200 = "b" * 200

CASES = [
    Case("baseline", {}, "connects", "the echo to diff against"),

    Case("keyterm 60 chars",
         {"keyterms_prompt": json.dumps(["MSKU", TERM_60])}, "?",
         "detector.py assumes a 50-char cap; is it real?"),
    Case("keyterm 200 chars",
         {"keyterms_prompt": json.dumps(["MSKU", TERM_200])}, "?",
         "far past any plausible cap"),
    Case("keyterms exactly 100",
         {"keyterms_prompt": json.dumps([f"t{i}" for i in range(100)])}, "connects",
         "the ARM path sits exactly here by design"),

    Case("prompt 1700 chars", {"prompt": "x" * 1700}, "connects", "under the documented 1750"),
    Case("prompt 1900 chars", {"prompt": "x" * 1900}, "?", "over it -- error frame or silent truncation?"),

    # These four are echoed, so the echo settles them.
    Case("voice_focus=near-field", {"voice_focus": "near-field"}, "?",
         "priced into config.py's cost model, never sent by live.py"),
    Case("speaker_labels=true", {"speaker_labels": "true"}, "?", "echoed field"),
    Case("domain=medical-v1", {"domain": "medical-v1"}, "?", "echoed field"),
    Case("filter_profanity=true", {"filter_profanity": "true"}, "?", "echoed field"),
]


async def main() -> int:
    api_key = _resolve_api_key()
    if not api_key:
        print("No AssemblyAI key found in .env")
        return 1

    outcomes: list[Outcome] = []
    for index, case in enumerate(CASES):
        if index:
            await asyncio.sleep(SETTLE_S)
        out = await run_case(case, api_key)
        outcomes.append(out)
        busy = any("concurrent" in str(f.get("error", "")).lower() for f in out.frames)
        note = "   <-- CONCURRENCY, discard" if busy else ""
        print(f"  {case.name:26} {out.verdict}{note}")

    base_cfg = (outcomes[0].begin or {}).get("configuration")
    print("\n" + "=" * 76)
    print("Echoed fields -- decisive, because these appear in Begin.configuration")
    print("=" * 76)
    print(f"  baseline: {json.dumps(base_cfg, sort_keys=True)}\n")
    for out in outcomes[1:]:
        if not out.begin:
            continue
        cfg = out.begin.get("configuration")
        diff = {k: v for k, v in (cfg or {}).items() if (base_cfg or {}).get(k) != v}
        print(f"  {out.case:26} {json.dumps(diff, sort_keys=True) if diff else 'no change'}")

    print("\n" + "=" * 76)
    print("Error frames -- decisive, because a cap that exists says so")
    print("=" * 76)
    any_error = False
    for out in outcomes:
        for frame in out.frames:
            if frame.get("type") == "Error" and "concurrent" not in str(frame.get("error", "")).lower():
                any_error = True
                print(f"  {out.case:26} {frame.get('error_code')}  {frame.get('error')}")
    if not any_error:
        print("  none (excluding concurrency)")

    print("\n" + "=" * 76)
    print("Reading")
    print("=" * 76)
    kt60 = next((o for o in outcomes if o.case == "keyterm 60 chars"), None)
    kt200 = next((o for o in outcomes if o.case == "keyterm 200 chars"), None)
    if kt60 and kt200:
        errs = [f for o in (kt60, kt200) for f in o.frames
                if f.get("type") == "Error" and "concurrent" not in str(f.get("error", "")).lower()]
        if not errs:
            print("  No per-term character limit was enforced at 60 or 200 characters.")
            print("  detector.py's MAX_KEYTERM_CHARS = 50 is therefore NOT a server")
            print("  rule. Keeping it is fine as a budget policy, but the comment")
            print("  should stop calling it a hard limit -- and terms it currently")
            print("  drops for being 51 characters long could have been sent.")
        else:
            print("  A per-term limit IS enforced; see the error frames above.")

    Path(__file__).with_name("probe2-results.json").write_text(
        json.dumps([{"case": o.case, "verdict": o.verdict, "frames": o.frames[:20]}
                    for o in outcomes], indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
