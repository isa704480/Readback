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

The pipeline runs end to end against five recorded fixtures with no API key,
and against the live `universal-3-5-pro` socket with one:

```
$ PYTHONPATH=. python -m pytest tests/ -q                       85 passed
$ PYTHONPATH=. python experiments/day1/e2e_live.py --wav container.wav --truth MSKU4158005
  [4575 ms] capture.update   rack=MSKU4158___
  [5885 ms] candidate.seen   MSKU4158005  complete  checksum_ok  aligned
  [6198 ms] capture.commit   value=MSKU4158005  heard=MSKU4158005
  VERDICT: truth MSKU4158005 committed: YES
```

Built and tested: validators, solver, normaliser, question generator, arity
repair, the rolling tape, the detector and ARM/IDLE state machine, the replay
source and fixture corpus, the decider, the runner, the event stream, the
persistence layer, the FastAPI surface, sign-in and organisations, the
browser microphone path (AudioWorklet → PCM16 → `/api/session/{id}/audio` →
the same runner the fixtures use), the rack UI, a demo screen that runs any
of the eight fixtures through that runner and shows what came back — four
that contain a container number, four that must stay silent — reachable
without an account, and a trilingual interface.

Every fixture runs at **both** clocks — instant and real-time — because a gate
that is a condition on time passing is not tested by a replay that
fast-forwards. That check found the bug that would have lost the demo: the agent
could not satisfy 4.8's politeness delay after a `ForceEndpoint`, so in real
time it never spoke. See section I of `tests/test_pipeline_e2e.py`.

### What the live socket taught us, and what we decided against

The day-1 experiment was written to answer one question — *do spelled
characters come back as separate `Word` objects?* — because everything
downstream branches on it. It has now run (`experiments/day1/FINDINGS-day1.md`).
The answer is **no**: every frame arrives formatted, partials included, and a
spoken identifier comes back as **one word with one confidence** —
`RMSKU4158005.` (0.80) — or as a capitalised prefix beside a welded digit
block, `RM SKU 4158005`. There is no unformatted path on this model;
`format_turns=false` is accepted and ignored.

Every fixture in this repository spells one word per character, so all of them
passed while the live path produced zero captures. One measured session found
four defects between the fixtures and the first live capture, none visible
from a fixture:

1. the welded word, which `_one()` could not read (`tokenise()` now splits
   code-shaped tokens);
2. the detector judging readability per word, so the welded word never joined
   a run and the shape cue could not fire;
3. `terminate()` closing the socket in the same breath as sending `Terminate`
   — the server flushes a last Turn, then `Termination`, then closes, and we
   were hanging up first, losing the turn the caller pressed stop after;
4. the capitalised prefix, and "SKU" inside it matching a carrier phrase that
   flipped the format away from the "container number" said six seconds
   earlier. MSKU is Maersk's prefix.

Decided against, from measurement rather than preference:

- **Per-character confidence from the recogniser.** It does not exist for this
  input. The solver's substrate is per-position doubt; on welded output every
  position shares one number. The regime detector (ARCH 3.7) names this and
  the decider forbids a silent repair in it; a checksum-clean capture still
  commits silently, which is what the live run did.
- **The LLM Gateway as a format identifier for bare digit strings.** Measured
  anti-correlated: a phone-number window scored `nhs 0.90`, a real NHS number
  `not_an_identifier 0.70`. It is not consulted for those formats.
- **The `end_of_turn_confidence_threshold` lever the ARM path was designed
  around.** Universal-Streaming-only per the reference; accepted without error
  here, like any unknown name — the day-1 control proved the server drops
  unknown parameters silently, which is why "it connected" is worth nothing as
  evidence. `mode` is real and connect-time only.
- **Tuning the rhythm threshold on the false-positive fixture.** The
  conversational and dictation distributions overlap (cv 0.167–0.336 on pure
  conversation); a threshold that separates them does not exist. The
  independence test on cues (`shape_is_evidence`) is what holds the gate shut:
  16 false commits before, 0 after.
- **A dialect hint.** There is no such parameter; `language_code=en` is pinned
  because, left free, the model code-switched a synthetic voice into Japanese.

Not yet measured: a human voice reading NATO spelling. The synthetic voice used
for the measurements mangled "Mike Sierra" into `RMI KCR`; a person would not,
but that is an expectation, not a number. `experiments/day1/listen.py --codes 3`
is the instrument.

## Path

**Universal Streaming STT**, not the Voice Agent API. `transcript.user` carries
only a flat string — no `confidence`, no `words` array — and the whole mechanism
needs per-word confidence to localise the suspect character. Streaming returns
`words[].confidence`, `words[].start/end`, and `end_of_turn_confidence`.
