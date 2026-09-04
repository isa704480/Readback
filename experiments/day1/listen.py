"""Day 1, part two: THE load-bearing measurement.

This is the experiment the whole build was arranged around. From the spec:
nothing else is written until it returns. Three questions, in order of how much
of the system dies if the answer is wrong.

  (A) day1-04 -- ARE SPELLED CHARACTERS SEPARATE WORDS?
      Does "em ess kay you four one five eight zero zero five" come back as
      eleven Word objects, or as "emesskayyou" and a number, or as something
      else? Every downstream component assumes one character per word, because
      that is what carries a per-character confidence. If the answer is no, the
      solver still works but the confidence model has nothing to attach to, and
      the regime detector (ARCH 3.7) is what keeps that a degraded demo rather
      than a dead build.

  (B) day1-05 -- IS CONFIDENCE ON PARTIALS, OR ONLY ON FINALS?
      The detector runs on every partial. If words[].confidence only arrives
      with the final turn, the ARM path has to move to the final and the 1.5 s
      politeness delay has to absorb it.

  (C) FORMATTING -- new, and not in the original spec.
      The API reference says `format_turns` is "Universal Streaming only", i.e.
      not on the model this system uses, and that formatting always tracks
      end_of_turn. server/stream/live.py sets FORMAT_TURNS = False with the
      comment "Formatting collapses 'fifteen' and 'one five'". If that switch is
      not real, finalized turns arrive formatted and the normaliser may be handed
      "15" where it needs "one five". This measures whether that actually
      happens.

  (D) THE AUC -- how well does confidence separate right from wrong?
      tests/test_solver_regression.py asserts a silent-wrong bound of 0.02 and
      says in its own comment that the bound is provisional because the
      confidence model there is invented. This is what replaces the invention.
      One reading is not enough for an AUC; the corpus accumulates across runs.

Usage
-----
    cd D:/My_apps/Readback

    # read three container numbers aloud, one per prompt
    PYTHONPATH=. python experiments/day1/listen.py --codes 3

    # or point it at a recording you already have (16 kHz mono WAV)
    PYTHONPATH=. python experiments/day1/listen.py --wav recording.wav --truth MSKU4158005

    # once the corpus has a few readings in it
    PYTHONPATH=. python experiments/day1/listen.py --analyse

Nothing here stores audio. Frames are appended to corpus.jsonl -- transcripts of
identifiers only, which is the same thing the product itself writes down, and
the reason the conversation around them is never in the file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import queue
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.readback.solver import ISO  # noqa: E402
from server.stream.live import DEFAULT_URL, _resolve_api_key  # noqa: E402

CORPUS = Path(__file__).parent / "corpus.jsonl"
SAMPLE_RATE = 16_000
CHUNK_MS = 100
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000

# Real container numbers, check digits verified against server/readback/validators
# at import so a typo in this list cannot be mistaken for a recogniser error --
# which is exactly what happened once already (docs/FINDINGS.md section 1).
CODES = [
    "MSKU4158005", "CSQU3054383", "TGHU7654321", "MSCU2468135", "TRHU1357924",
]


def _verified_codes() -> list[str]:
    good = [c for c in CODES if ISO.ok(c)]
    bad = [c for c in CODES if not ISO.ok(c)]
    if bad:
        print(f"  (dropping {len(bad)} code(s) with wrong check digits: {bad})")
    return good


def spoken_form(code: str) -> str:
    """How to say it, so the reading is consistent between runs."""
    nato = {"A": "Alfa", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo",
            "F": "Foxtrot", "G": "Golf", "H": "Hotel", "I": "India", "J": "Juliett",
            "K": "Kilo", "L": "Lima", "M": "Mike", "N": "November", "O": "Oscar",
            "P": "Papa", "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango",
            "U": "Uniform", "V": "Victor", "W": "Whiskey", "X": "X-ray",
            "Y": "Yankee", "Z": "Zulu"}
    return " ".join(nato.get(ch, ch) for ch in code)


def build_url() -> str:
    params = {
        "speech_model": "universal-3-5-pro",
        "sample_rate": SAMPLE_RATE,
        "encoding": "pcm_s16le",
        # No mode, no keyterms, no prompt. This run measures the RAW behaviour of
        # the model on spelled characters; every one of those knobs would change
        # what is being measured, and the point is to learn the baseline before
        # tuning against it.
    }
    return f"{DEFAULT_URL}?{urllib.parse.urlencode(params)}"


async def stream_session(audio_chunks, api_key: str) -> list[dict[str, Any]]:
    """Feed chunks, return every JSON frame the server sent."""
    from websockets.asyncio.client import connect as ws_connect

    frames: list[dict[str, Any]] = []
    async with ws_connect(build_url(), additional_headers={"Authorization": api_key},
                          open_timeout=15, close_timeout=5) as ws:

        async def reader() -> None:
            try:
                async for raw in ws:
                    if isinstance(raw, bytes):
                        continue
                    msg = json.loads(raw)
                    frames.append(msg)
                    if msg.get("type") == "Termination":
                        return
            except Exception:
                return

        task = asyncio.create_task(reader())
        async for chunk in audio_chunks:
            await ws.send(chunk)
        await ws.send(json.dumps({"type": "Terminate"}))
        try:
            await asyncio.wait_for(task, timeout=8.0)
        except asyncio.TimeoutError:
            task.cancel()
    return frames


async def mic_chunks(seconds: float):
    """Real-time microphone capture. Pacing is inherent -- the device produces
    audio at exactly 16 kHz, so nothing here can outrun real time and trip the
    3007 close."""
    import sounddevice as sd

    q: queue.Queue[bytes] = queue.Queue()

    def callback(indata, frames_n, time_info, status):  # noqa: ARG001
        q.put(bytes(indata))

    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=CHUNK_SAMPLES,
                           channels=1, dtype="int16", callback=callback):
        deadline = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < deadline:
            try:
                yield q.get(timeout=0.5)
            except queue.Empty:
                await asyncio.sleep(0.01)


async def wav_chunks(path: Path):
    """A file, paced to real time so the socket sees a legitimate stream."""
    import soundfile as sf

    data, rate = sf.read(str(path), dtype="int16", always_2d=True)
    if rate != SAMPLE_RATE:
        raise SystemExit(f"{path} is {rate} Hz; this needs {SAMPLE_RATE} Hz mono")
    mono = data[:, 0]
    for start in range(0, len(mono), CHUNK_SAMPLES):
        yield mono[start:start + CHUNK_SAMPLES].tobytes()
        await asyncio.sleep(CHUNK_MS / 1000)


# ---------------------------------------------------------------- analysis --
def summarise(frames: list[dict[str, Any]], truth: str) -> dict[str, Any]:
    turns = [f for f in frames if f.get("type") == "Turn"]
    partials = [t for t in turns if not t.get("end_of_turn")]
    finals = [t for t in turns if t.get("end_of_turn")]

    def words_of(t: dict[str, Any]) -> list[dict[str, Any]]:
        return t.get("words") or []

    last_final = finals[-1] if finals else None
    last_partial = partials[-1] if partials else None

    # (A) one word per character, or not?
    final_words = words_of(last_final) if last_final else []
    word_texts = [w.get("text", "") for w in final_words]
    single_char = sum(1 for t in word_texts if len(t.strip()) == 1)

    # (B) confidence on partials?
    partial_words = words_of(last_partial) if last_partial else []
    conf_on_partial = bool(partial_words) and all("confidence" in w for w in partial_words)
    final_flag_on_partial = bool(partial_words) and all("word_is_final" in w for w in partial_words)

    return {
        "truth": truth,
        "turns": len(turns),
        "partials": len(partials),
        "finals": len(finals),
        # (A)
        "final_word_count": len(final_words),
        "final_word_texts": word_texts,
        "single_char_words": single_char,
        "expected_chars": len(truth),
        # (B)
        "confidence_on_partial_words": conf_on_partial,
        "word_is_final_on_partial_words": final_flag_on_partial,
        "confidence_on_final_words": bool(final_words) and all("confidence" in w for w in final_words),
        # (C)
        "turn_is_formatted": last_final.get("turn_is_formatted") if last_final else None,
        "final_transcript": last_final.get("transcript") if last_final else None,
        "last_partial_transcript": last_partial.get("transcript") if last_partial else None,
        # every partial, verbatim: the language-pin question ("did the model
        # drift into another script mid-turn?") was unanswerable from the
        # count alone and had to be re-spoken once already
        "partial_transcripts": [t.get("transcript") for t in partials],
        "end_of_turn_confidence_values": sorted({t.get("end_of_turn_confidence") for t in turns}),
        # raw, so a wrong reading here can be re-derived without speaking again
        "final_words_raw": final_words,
        "frame_types": sorted({str(f.get("type")) for f in frames}),
        "at": datetime.now(timezone.utc).isoformat(),
    }


def report(rows: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 78)
    print("(A) day1-04  Are spelled characters separate Word objects?")
    print("=" * 78)
    for r in rows:
        print(f"  truth {r['truth']} ({r['expected_chars']} chars) -> "
              f"{r['final_word_count']} words, {r['single_char_words']} of them single-character")
        print(f"      words: {r['final_word_texts']}")
    verdicts = [r["final_word_count"] >= r["expected_chars"] * 0.7 for r in rows]
    if verdicts and all(verdicts):
        print("\n  ANSWER: yes -- roughly one word per character. The per-character")
        print("  confidence model has something to attach to. Proceed as designed.")
    elif verdicts and not any(verdicts):
        print("\n  ANSWER: NO. Characters are being merged into fewer words.")
        print("  The solver still works; the confidence model does not. ARCH 3.7's")
        print("  regime detector is now load-bearing, not a fallback.")
    else:
        print("\n  ANSWER: mixed. Not a stable property -- read the per-row detail.")

    print("\n" + "=" * 78)
    print("(B) day1-05  Is confidence present on PARTIAL turns?")
    print("=" * 78)
    for r in rows:
        print(f"  partials carry confidence: {r['confidence_on_partial_words']}   "
              f"word_is_final: {r['word_is_final_on_partial_words']}   "
              f"finals carry confidence: {r['confidence_on_final_words']}")
    if rows and all(r["confidence_on_partial_words"] for r in rows):
        print("\n  ANSWER: yes. The detector can keep running on partials.")
    else:
        print("\n  ANSWER: NO or partial. The ARM path has to move to the final turn")
        print("  and the 1.5 s politeness delay has to absorb the wait.")

    print("\n" + "=" * 78)
    print("(C) Formatting -- is the final turn formatted, and does it collapse digits?")
    print("=" * 78)
    for r in rows:
        print(f"  turn_is_formatted={r['turn_is_formatted']}")
        print(f"      last partial: {r['last_partial_transcript']!r}")
        print(f"      final:        {r['final_transcript']!r}")
    print("\n  Compare the two lines. If the final collapses spelled digits into")
    print("  numerals where the partial did not, live.py's FORMAT_TURNS=False is")
    print("  not doing anything and the tape must be built from partials.")

    print("\n" + "=" * 78)
    print("(D) end_of_turn_confidence -- binary, or graded?")
    print("=" * 78)
    seen = sorted({v for r in rows for v in r["end_of_turn_confidence_values"] if v is not None})
    print(f"  distinct values observed: {seen}")
    if seen and set(seen) <= {0.0, 1.0}:
        print("  ANSWER: binary. detector.py's IDLE/ARMED thresholds of 0.70 and 0.50")
        print("  cannot discriminate anything -- that lever does not exist.")
    elif seen:
        print("  ANSWER: graded. The thresholds are meaningful after all.")


def analyse_corpus() -> int:
    if not CORPUS.exists():
        print(f"no corpus yet at {CORPUS} -- run without --analyse first")
        return 1
    rows = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"{len(rows)} reading(s) in the corpus\n")
    report(rows)

    print("\n" + "=" * 78)
    print("(E) AUC of words[].confidence separating correct from incorrect")
    print("=" * 78)
    pos: list[float] = []   # confidence where the character was RIGHT
    neg: list[float] = []   # confidence where it was WRONG
    for r in rows:
        truth = r["truth"]
        words = r.get("final_words_raw") or []
        chars = [w.get("text", "").strip().upper() for w in words]
        confs = [w.get("confidence") for w in words]
        # Only aligned readings contribute. A reading whose word count does not
        # match the truth cannot be aligned position-by-position without an edit
        # distance, and guessing an alignment would manufacture the very numbers
        # this is supposed to measure.
        if len(chars) != len(truth):
            continue
        for got, want, conf in zip(chars, truth, confs):
            if conf is None:
                continue
            (pos if got == want else neg).append(float(conf))

    if not pos or not neg:
        print(f"  not enough data: {len(pos)} correct, {len(neg)} incorrect characters.")
        print("  An AUC needs both. Read more codes -- and note that if the")
        print("  recogniser never gets one wrong, that is itself the finding.")
        return 0

    # Mann-Whitney U / AUC, ties counted as half.
    wins = sum(1 for p in pos for n in neg if p > n) + 0.5 * sum(1 for p in pos for n in neg if p == n)
    auc = wins / (len(pos) * len(neg))
    print(f"  correct characters:   n={len(pos)}  mean confidence {sum(pos)/len(pos):.3f}")
    print(f"  incorrect characters: n={len(neg)}  mean confidence {sum(neg)/len(neg):.3f}")
    print(f"\n  AUC = {auc:.3f}")
    print("\n  This is the number tests/test_solver_regression.py is waiting for.")
    print("  Its MAX_SILENT_WRONG bound is provisional until it exists, and its")
    print("  invented model was uniform(0.35,0.80) wrong / uniform(0.55,0.99)")
    print("  right -- an AUC near 0.80. Compare and re-fit.")
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=int, default=0, help="how many codes to read aloud")
    ap.add_argument("--wav", type=Path, help="a 16 kHz mono WAV instead of the microphone")
    ap.add_argument("--truth", help="the identifier spoken in --wav")
    ap.add_argument("--seconds", type=float, default=12.0, help="recording window per code")
    ap.add_argument("--analyse", action="store_true", help="report over the accumulated corpus")
    args = ap.parse_args()

    if args.analyse:
        return analyse_corpus()

    api_key = _resolve_api_key()
    if not api_key:
        print("No AssemblyAI key found. Put it in D:/My_apps/Readback/.env as:")
        print("    READBACK_ASSEMBLYAI_API_KEY=...")
        return 1

    rows: list[dict[str, Any]] = []

    if args.wav:
        if not args.truth:
            return print("--wav needs --truth (what was spoken)") or 1
        frames = await stream_session(wav_chunks(args.wav), api_key)
        rows.append(summarise(frames, args.truth.upper()))
    else:
        codes = _verified_codes()[: max(1, args.codes)]
        print(f"\nReading {len(codes)} code(s). {args.seconds:.0f} s each.\n")
        for i, code in enumerate(codes, 1):
            print(f"  [{i}/{len(codes)}] Read this aloud, steadily:\n")
            print(f"        {spoken_form(code)}\n")
            input("        press Enter, then start speaking... ")
            frames = await stream_session(mic_chunks(args.seconds), api_key)
            rows.append(summarise(frames, code))
            print(f"        heard: {rows[-1]['final_transcript']!r}\n")

    with CORPUS.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    report(rows)
    print(f"\nappended {len(rows)} reading(s) to {CORPUS}")
    print("Run with --analyse once there are several, for the AUC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
