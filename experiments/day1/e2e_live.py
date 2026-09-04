"""Drive a WAV through the SAME path a browser microphone takes, and report
whether a capture committed.

    PYTHONPATH=. python experiments/day1/e2e_live.py --wav container.wav --truth MSKU4158005

It talks to a running server (default http://localhost:8000) exactly as
web/src/lib/useLiveSession.ts does: POST /api/session/start with consent, a
listener on ws /api/session/{id}/live for the event stream, PCM16 pushed down
ws /api/session/{id}/audio under the `readback.audio` subprotocol at real time
in the server's own chunk size, then {"type":"Terminate"}. Afterwards it reads
GET /api/sessions and prints the row for this session.

No token is sent, so the session lands in the demo organisation -- the same
place an unauthenticated browser lands (main.py: the token decides attribution,
never access). Nothing here writes audio anywhere; the WAV is read and sent.

Why this exists: listen.py answers questions about the RECOGNISER. It does not
run the detector, the normaliser or the decider. Until 2026-09-04 every fixture
passed while the live path produced zero captures, because the two were never
joined -- this is the join.

What it measures besides the verdict: the time from the socket opening to
`Ready` (upstream connect latency -- seen at 3 s and at 11 s on the same day),
and the time from `Terminate` to the server's own close, which is how long the
last turn took to flush through upstream (1.5 s when upstream was responsive).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import httpx
import websockets

INTERESTING = {
    "session.started", "state.armed", "state.idle", "regime.detected",
    "candidate.seen", "candidates.show", "repair.silent", "question.ask",
    "capture.commit", "capture.flag", "capture.handover", "session.end", "error",
}

# A dev server under `--reload` restarts a moment after any .py edit, and its
# session registry is in memory: `start` answered by the outgoing process and
# the sockets by the incoming one shows as "unknown session" on /live and 4410
# on /audio. That is the reloader, not the product; one retry after a pause is
# the whole workaround.
RELOAD_RACE = 99


def _pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2, \
            f"{path} must be 16 kHz mono PCM16 (got {w.getframerate()} Hz, " \
            f"{w.getnchannels()} ch, {w.getsampwidth() * 8} bit)"
        return w.readframes(w.getnframes()), w.getframerate()


async def _listen(ws_url: str, events: list[dict], stop: asyncio.Event) -> None:
    async with websockets.connect(ws_url, max_size=2**22) as ws:
        while not stop.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except websockets.ConnectionClosed:
                return
            ev = json.loads(raw)
            events.append(ev)
            if ev.get("type") in INTERESTING:
                t = ev.get("type")
                extra = {k: v for k, v in ev.items()
                         if k not in ("type", "seq", "at_ms")}
                print(f"  [{ev.get('at_ms', 0):>6} ms] {t:<20} "
                      f"{json.dumps(extra, ensure_ascii=False)[:150]}")
            if ev.get("type") == "session.end":
                return


async def _attempt(args: argparse.Namespace, pcm: bytes, rate: int, ws_base: str) -> int:
    async with httpx.AsyncClient(base_url=args.base, timeout=15) as http:
        r = await http.post("/api/session/start", json={
            "consent": {"accepted": True, "disclosure_played": True},
            "demo_mode": args.demo_mode, "ab": False, "channel": "clean",
        })
        if r.status_code != 200:
            print(f"start failed: {r.status_code} {r.text}")
            return 2
        start = r.json()
        sid = start["session_id"]
        print(f"session {sid}  live_capture={start['live_capture']}  "
              f"cap={start['cap_seconds']}s  budget_left={start['budget_remaining_seconds']}s")
        if not start["live_capture"]:
            print("NOT a live session (budget exhausted or live capture off) -- "
                  "the audio socket would answer 4409. Stopping.")
            return 3

        events: list[dict] = []
        stop = asyncio.Event()
        listener = asyncio.create_task(_listen(f"{ws_base}/api/session/{sid}/live", events, stop))
        await asyncio.sleep(0.3)

        t0 = time.monotonic()
        try:
            async with websockets.connect(f"{ws_base}/api/session/{sid}/audio",
                                          subprotocols=["readback.audio"]) as audio:
                ready = json.loads(await asyncio.wait_for(audio.recv(), timeout=30))
                assert ready.get("type") == "Ready", ready
                chunk_ms = int(ready["chunk_ms"])
                chunk = rate * 2 * chunk_ms // 1000
                print(f"Ready after {time.monotonic() - t0:.1f}s; chunk={chunk_ms} ms "
                      f"({chunk} bytes); sending {len(pcm) / (rate * 2):.2f}s of audio")
                sent_at = time.monotonic()
                for i in range(0, len(pcm), chunk):
                    await audio.send(pcm[i:i + chunk])
                    # stay at real time: never more than ~1 s ahead of the clock
                    ahead = (i + chunk) / (rate * 2) - (time.monotonic() - sent_at)
                    if ahead > 1.0:
                        await asyncio.sleep(ahead - 1.0)
                await audio.send(json.dumps({"type": "Terminate"}))
                terminated_at = time.monotonic()
                # The server closes this socket (1000) only after upstream has
                # flushed and the pipeline has drained. Wait for THAT, not for a
                # fixed pause: the whole question is whether the last identifier
                # survives a lagging upstream.
                try:
                    while True:
                        msg = await asyncio.wait_for(audio.recv(), timeout=args.drain)
                        print(f"  audio socket said: {str(msg)[:120]}")
                except asyncio.TimeoutError:
                    print(f"  audio socket STILL OPEN {args.drain:.0f}s after Terminate -- giving up")
                except websockets.ConnectionClosed as exc:
                    code = exc.rcvd.code if exc.rcvd else "?"
                    print(f"  audio socket closed code={code} "
                          f"{time.monotonic() - terminated_at:.1f}s after Terminate")
        except websockets.InvalidStatus as exc:
            print(f"audio socket refused: {exc}")
        except websockets.ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd else "?"
            print(f"audio socket closed early: code={code}")

        # the listener returns on session.end; give it a moment past the close
        try:
            await asyncio.wait_for(listener, timeout=8)
        except asyncio.TimeoutError:
            stop.set()
            await asyncio.sleep(0.6)
            listener.cancel()

        if events and all(e.get("type") == "error" and e.get("message") == "unknown session"
                          for e in events):
            return RELOAD_RACE

        if args.dump:
            with open(args.dump, "w", encoding="utf-8") as fh:
                for e in events:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            print(f"  ({len(events)} events written to {args.dump})")
        kinds: dict[str, int] = {}
        for e in events:
            kinds[e.get("type")] = kinds.get(e.get("type"), 0) + 1
        print(f"\n{len(events)} events: {json.dumps(kinds)}")

        r = await http.get("/api/sessions")
        if r.status_code == 401:
            print("\nGET /api/sessions -> 401: the listing needs a signed-in user; "
                  "the event stream above is the record for an unauthenticated session")
            rows = []
        else:
            rows = [row for row in r.json() if str(row.get("session_id")) == str(sid)] \
                if r.status_code == 200 else []
            print(f"\nGET /api/sessions -> {r.status_code}; rows for this session: {len(rows)}")
        for row in rows:
            print("  " + json.dumps(row, ensure_ascii=False)[:400])

        commits = [e for e in events if e.get("type") == "capture.commit"]
        flags = [e for e in events if e.get("type") == "capture.flag"]
        if args.truth:
            got = [str(e.get("value") or e.get("final") or "") for e in commits]
            hit = any(g.upper().replace(" ", "") == args.truth.upper() for g in got)
            print(f"\nVERDICT: {len(commits)} commit(s), {len(flags)} flag(s); "
                  f"truth {args.truth} committed: {'YES' if hit else 'NO'}  got={got}")
            return 0 if hit else 1
        return 0 if commits else 1


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--truth", default="")
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--demo-mode", action="store_true",
                    help="send demo_mode=true (stored on the row; the pipeline ignores it)")
    ap.add_argument("--tail-silence", type=float, default=2.5,
                    help="seconds of silence appended so the turn can end")
    ap.add_argument("--dump", default="",
                    help="write every /live event, verbatim, to this JSON-lines file")
    ap.add_argument("--drain", type=float, default=25.0,
                    help="seconds to wait for the server to close the audio socket "
                         "after Terminate; upstream has been seen to lag 10 s+")
    args = ap.parse_args()

    pcm, rate = _pcm(Path(args.wav))
    pcm += b"\x00" * int(rate * 2 * args.tail_silence)
    ws_base = args.base.replace("http://", "ws://").replace("https://", "wss://")

    for _attempt_no in (1, 2):
        rc = await _attempt(args, pcm, rate, ws_base)
        if rc != RELOAD_RACE:
            return rc
        print("\n-- the dev server reloaded under us; retrying in 6 s --\n")
        await asyncio.sleep(6)
    return 4


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
