# Readback

A voice agent that listens in the background of a call and writes reference
numbers down correctly — not by hearing better, but by knowing what a valid
answer is allowed to be. It repairs most mishearings in silence, and when it
can't, it interrupts once to ask about a single character.

Built for the AssemblyAI Voice Agent Hackathon, September 2026.

---

## The problem

Every call centre, logistics desk, insurance line and support team burns time on
*"can you spell that"*, *"was that B for Bravo or D for Delta"*, *"did you say
fifteen or fifty"*. One wrong character sends a container to the wrong port,
bounces a payment, or dispenses the wrong drug. In noise, `5`/`9`, `M`/`N`,
`S`/`F` and fifteen/fifty are genuinely ambiguous — speech-to-text alone cannot
fix this, because the information is not in the audio.

## What makes it work

It is not in the audio, but it is in the **format**. A container number carries
an ISO 6346 check digit; an IBAN carries mod-97; a card carries Luhn. The
constraint does not make the recogniser hear better — it multiplies the
error rate the system can absorb.

Measured across 8 accents, ~12M simulated captures, the solver never told which
accent it was hearing:

| format | unconstrained error budget | constrained | spread across accents | gain |
|---|---|---|---|---|
| ISO 6346 | 0.0047 | **0.0692** | 1.13× | **14.9×** |
| IBAN-GB | 0.0023 | **0.0399** | 1.14× | **17.1×** |

Accents differ in ASR error rate by at most 2×. A 15× budget absorbs that with
an order of magnitude to spare. **This is why the answer is not fine-tuning** —
and knowing *which* accent is worth ±0.002, so there is no accent detection and
one confusion table.

## Silence is the product

The acoustic confusion model contributes **zero accuracy** — checksum plus two
questions reaches ~100% either way. What it buys is 21 points of silent repair
on ISO, 64 on NHS. An agent that asks about every identifier is exactly the
"can you spell that" this exists to delete.

## What it does not promise

Not "letters are never wrong". ISO 6346 sums `value(c)·2^i mod 11`, so the
classes `{A K U}`, `{1 B L V}`, `{2 C M W}` … are invisible to the check digit.
Measured against the acoustic table, **5.3% of confusion weight lands there**,
in twelve known pairs.

At a position in one of those classes the checksum contributes nothing, so the
agent asks whenever it has *any* acoustic doubt there — the ordinary threshold,
applied to a position the arithmetic will never object to. It does **not** ask
about every such position unconditionally, and the reason is measured rather than
economical: 67% of valid container numbers contain a blind-capable position
(mean 0.93 of 11), so asking about all of them costs two thirds of the silence —
20.1% → 6.8% — to move silently-wrong by 0.0014. That is the same trade the
`DOUBT_T` sweep already rejected, and silence is the product.

What is left is the honest residue: a substitution inside a residue class that
the recogniser was also *confident* about has no signal anywhere in the system,
and is written silently. `tests/test_solver_regression.py` bounds how often, and
the bound — not zero — is the promise. See [docs/FINDINGS.md](docs/FINDINGS.md) §5.

## Layout

```
server/readback/
  validators.py   14 identifier formats, checked against published vectors
  fastval.py      O(1)-update ISO 6346 + IBAN mod-97
  solver.py       posterior, candidate generation, the four decision gates
  normalise.py    spoken-form lattice (zed/zee, double four, niner, NATO)
  question.py     the one-character question
  arity.py        length repair
server/stream/
  source.py       TranscriptSource -- the seam a fixture and a socket both satisfy
  replay.py       a recorded session, replayed at its own timings
  live.py         the AssemblyAI Universal Streaming socket (written, not yet run)
  tape.py         wire-shaped view of the rolling tape
server/pipeline/
  tape.py         the rolling tape (3.4): replace-not-append, one flat timeline
  detector.py     the four cues and the ARM/IDLE state machine (3.6)
  decider.py      4.4's gates, 4.8's ambient discipline, the budgets
  runner.py       the loop, and the confidence-regime detector (3.7)
  events.py       the event stream -- the product's interface, not logging
  store.py        captures, questions, the online confusion pseudo-count
server/
  main.py         FastAPI: consent gate, budget gate, the demo replay endpoint
  models.py db.py audit.py config.py
tests/
  test_solver_regression.py   the silent-wrong bound
  test_detector.py            the cues and the state machine
  test_replay.py              the seam and the four awkward stream properties
  test_persistence.py         the schema and the append-only log
  test_pipeline_e2e.py        all five fixtures through the whole pipeline
  fixtures/                   five recorded sessions, wire format verbatim
  bench/                      the harnesses the parameters came from
docs/
  ARCHITECTURE.md  the full spec
  EXPERIMENT.md    the ~12M-capture measurement
  FINDINGS.md      what changed while porting
```

## Status

The pipeline runs end to end today, with no API key, against five recorded
fixtures:

```
$ PYTHONPATH=. python -m pytest tests/ -q          19 passed
$ PYTHONPATH=. python tests/test_pipeline_e2e.py   272 checks passed
$ curl -X POST localhost:8000/api/demo/replay -d '{"fixture":"iso_visible_substitution"}'
  heard NSKU4158005 -> wrote MSKU4158005, silently, 0 questions
```

Built and tested: validators, solver, normaliser, question generator, arity
repair, the rolling tape, the detector and ARM/IDLE state machine, the replay
source and fixture corpus, the decider, the runner, the event stream, the
persistence layer, and the FastAPI surface.

Every fixture is now run at **both** clocks — instant and real-time — because a
gate that is a condition on time passing is not tested by a replay that
fast-forwards. That check found the one bug that would have lost the demo: the
agent could not satisfy 4.8's politeness delay after a `ForceEndpoint`, so in
real time it never spoke. See section I of `tests/test_pipeline_e2e.py`.

Not built yet: the rack UI, the LLM Gateway format-ID call, the browser audio
client, the BIC owner-code registry beyond a bootstrap list.

The live socket is the thing least exercised, but no longer entirely
unexercised: with a junk key `LiveSource` reaches the real endpoint and is
rejected by it — `Error 1008, Unauthorized Connection` in about a second, raised
as `SourceError` — so the URL, the auth header shape and the error-frame path are
confirmed against the live service. What remains unverified is every frame shape
*after* a successful handshake. Those are the twelve `TODO(day1-NN)` markers in
`server/stream/live.py`. Swapping the source in is a constructor argument behind
`settings.live_capture`, which is a `.env` edit.

**Blocked on day 1:** the falsification experiment needs an API key. It measures
(A) whether spelled characters return as separate `Word` objects, and (B) the
AUC of `words[].confidence` separating correct from incorrect characters. The
answer decides whether escalation is a one-character question or a span re-read.
Nothing else is written until it returns.

## Path

**Universal Streaming STT**, not the Voice Agent API. `transcript.user` carries
only a flat string — no `confidence`, no `words` array — and the whole mechanism
needs per-word confidence to localise the suspect character. Streaming returns
`words[].confidence`, `words[].start/end`, and `end_of_turn_confidence`.
