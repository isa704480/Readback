# READBACK — Buildable Architecture Specification

*Everything below is decided. Where the six prior analyses disagreed, I pick one and say why in a **Disagreement resolved** note. Every number cited is from the measured runs in `D:\temp\claude\D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762\c09d90d9-a412-4614-b967-92de40b55905\scratchpad\` (`rb.py`, `val.py`, `fastval.py`, `bench*.py`, `attack*.py`, `xp.py`, `knee.py`, `guardhole.py`, `cands.py`, `tolerance.py`, `blindness.py`, `results_*.json`).*

---

## 1. WHAT IT IS

Readback is an ambient capture layer that sits over a phone call two humans were going to have anyway. It listens continuously, notices when someone starts reading out a reference identifier — a container number, a VIN, an IBAN, a part number — and writes it down correctly. It does not improve the acoustics and does not try to. It exploits the fact that the answer is not free text: it has to be a valid ISO 6346 container number, or a row in a 40-line parts catalogue, or a registered BIC owner code. That turns transcription into constrained decoding, where AssemblyAI's per-word confidence supplies the likelihood and the format supplies a hard 0/1 prior, and the posterior over valid strings decides everything — including whether to speak. Two thirds of the time it repairs a mishearing and says nothing at all; the diff appears on screen. When it cannot resolve the ambiguity it interrupts once, for about two seconds, and asks about exactly one character — in NATO, so the answer arrives in a different acoustic space than the one that just failed.

**Submission sentence:**

> **Readback listens in the background of a call and writes reference numbers down correctly — not by hearing better, but by knowing what a valid answer is allowed to be. It repairs most mishearings in silence, and when it can't, it interrupts once to ask about a single character.**

---

## 2. THE HONEST CLAIM

### 2.1 Say the ablation before a judge says it

The measured ablation (`attack.py`, N=400/cell, ISO 6346, calibrated confidence, one acoustic error): replace the confusion table with a uniform one, keep the checksum, keep two questions and one span re-read.

| | full table | uniform table |
|---|---|---|
| exact-capture correct | 99.8% | **99.8%** |
| silent repairs | 21.2% | **0.0%** |
| span re-reads | 12.0% | **33.2%** |

**Correctness is identical to three decimal places.** The confusion table contributes zero accuracy and 21 points of silence (64 points on NHS, 40 on IBAN). So the claim is not "our acoustic model makes it accurate." It is:

> **A checksum plus two questions plus one re-read gets you to ~100% correct. That part is fifty lines. The acoustic model's entire job is to decide when the agent can keep its mouth shut — and keeping its mouth shut is the whole product, because an agent that asks about every identifier is exactly the "can you spell that" this exists to delete.**

Lead with that. It is a stronger position than the one it replaces, it survives ablation because it *is* the ablation, and it converts the most attackable slide into the most credible one.

### 2.2 What we can promise about accents — and it is a strong, measured claim

The experiment ran 8 accents × 6 conditions × ~12M simulated captures, with the solver never told the accent. Two results:

**(a) Accent *shape* has no detectable effect.** Holding effective error rate constant so only the confusion shape varies: across 216 cells, spread ÷ that cell's own binomial noise floor was median 1.01, p95 1.42, max 2.02. Not for the constrained system specifically — **for every condition including the uncorrected baseline.** Exact-match accuracy is `(1−p)^L`; it depends on how many characters are wrong, never which. The load-bearing half of this is that a *mismatched* confusion table introduces no new accent sensitivity either.

**(b) Accents differ in error *rate*, and rate is exactly what constraint buys.** Per-character error rate absorbed while still capturing 95% of identifiers exactly (`tolerance.py`, N=3000/cell):

| format | unconstrained | constrained | per-accent range | gain |
|---|---|---|---|---|
| ISO 6346 (L=11) | 0.0047 | **0.0692** | 0.0651–0.0737 (1.13×) | **14.9×** |
| IBAN-GB (L=22) | 0.0023 | **0.0399** | 0.0376–0.0428 (1.14×) | **17.1×** |

**The promise, stated exactly:** *the error-rate budget is identical across every accent tested to within 14%, and constraint multiplies that budget by 15×. Accents differ in ASR error rate by at most 2×. A 15× budget absorbs a 2× accent penalty with an order of magnitude to spare.* That is the central insight, verified, and it is why the answer is not fine-tuning.

Corollary, measured and counterintuitive, and worth a slide: **knowing the accent is worth nothing.** ORACLE (accent-matched table) minus BLENDED is −0.001 to +0.002 at every error rate on both formats; an American-only table minus blended is −0.002 to +0.000. Ship one table. Build no accent detection.

### 2.3 "Letters must never come out wrong" — not achievable. Here is what replaces it.

ISO 6346 computes `Σ value(c)·2^i mod 11`, so any two characters congruent mod 11 are **mathematically invisible** to the check digit. The classes are perfectly regular:

```
{A K U} {B L V} {C M W} {D N X} {E O Y} {F P Z} {G Q} {H R} {I S} {J T}
```

45 blind pairs. **B↔V is one of them** — the Spanish `/b/–/v/` merger, the canonical E-set pair, the single most confusable letter pair in world English — and the container check digit cannot see it, ever, at any SNR, on any accent. `BMMU9233219` heard as `VMMU9233219` passes the check digit (`examples.py`). 2.8–4.7% of erroneous ISO hypotheses are undetectable this way; 5.9% of letter substitutions weighted by confusion mass.

Do not promise infallibility. Promise this instead:

> **Readback never silently writes a letter it is not sure about. When it is unsure, you see it — amber on screen, before anything is saved.**

This is provable and it is enforced by mechanism, not by accuracy. Measured, error confined to the four letter positions (N=500): checksum-blind 6.2%, **silently wrong 0.0%**, span re-read 21.0%, correct 99.6%. The doubt-budget guard converts every blind letter error into a visible re-read rather than a silent write.

**And the promise survives every confidence regime except one we are choosing not to ship.** Under block-level confidence (`attack2.py`): 0.0% silently wrong. Under naive per-character: 0.0%. The only regime that breaks it is *flat* confidence (5.0% silently wrong, exactly matching the 5.0% blind rate) and the "spread the block's doubt" hack (3.5% silently wrong). Flat is detectable at runtime (§3.7) and the spread hack is on the do-not-build list.

### 2.4 The numbers to put in the pitch

Tuned config (§4.6), ISO 6346, calibrated per-character confidence:

| per-character error rate | exact-capture | silent repairs | spoken questions / identifier | handover |
|---|---|---|---|---|
| p = 0.02 (headset, quiet room) | **98.2%** | **63.6%** | **0.45** | 2.8% |
| p = 0.05 (narrowband, moderate noise) | ~97% | ~40% | ~0.9 | ~5% |
| p = 0.15 (bad line) | ~86% | ~20% | ~1.5 | ~12% |

**Correction to the ambient spec, which claimed ~1% spoken interrupts and "1.2 per 100 identifiers."** The red team is right: spoken-question share ≈ `p_identifier × (1 − silent_rate)`, and at the demo's own channel that is tens of percent, not one. The "64% of real single mishears repaired silently" figure in the demo doc is also unsupported — measured is 24.4% at DOUBT_T=0.25, 63.6% at DOUBT_T=0.40. **State the interrupt rate as a function of line quality, never as a constant**, and state the comparison class honestly: *the alternative is not silence, it is the "can you spell that" that happens on five calls in five today.*

**Disagreement resolved — lead format.** The experiment says lead with IBAN (mod 97 is a complete single-substitution detector; ISO 6346 is not). The validator says lead with ISO 6346. **Ship ISO 6346 as the lead and IBAN as the mathematics slide.** Reasons: IBAN is 22–34 characters and 20+ seconds of speech inside a 120-second demo; it is invisible to American judges; nobody should read one aloud; and it silently "fixes" 4.7% of genuine data errors because mod-97 makes the single repair unique and confident. ISO 6346's blindness is not a reason to drop it — it is the reason the product needs a *second* constraint engine (the owner-code registry), which is the thesis, is demonstrable, and is what earns the "models, plural" criterion. The experiment's finding stands and appears on screen as one number in the format strip: `IBAN 10/97 — 85% of positions eliminated. Container mod 11 — 14%.`

---

## 3. ARCHITECTURE

### 3.1 AssemblyAI path — Universal Streaming STT WebSocket, `universal-3-5-pro`

Not the Voice Agent API. Two independent sufficient reasons:

1. `transcript.user` returns `{type, text, item_id}` — no `words`, no `confidence`, no timings. Position→confidence alignment is the substrate of the entire posterior, and Voice Agent structurally cannot supply it.
2. Voice Agent is an abstraction whose central assumption is that it is being addressed. Its VAD, `interrupt_response` and endpointing are tuned for a two-party exchange with the machine as one party. Building silent-by-default on it means suppressing the abstraction's primary behaviour on every turn.

TTS comes from browser `SpeechSynthesis`. Utterances are short and templated; the platform voice ceiling is not a constraint. Budget half a day.

**Connection shape:**

```python
CONNECT = {
  "speech_model": "universal-3-5-pro",
  "mode": "max_accuracy",
  "format_turns": False,            # verbatim; formatting destroys "fifteen" vs "one five"
  "language_codes": ["en"],         # no dialect parameter exists; §3.5 owns accents
  "encoding": "pcm_s16le", "sample_rate": 16000,
  "voice_focus": "near-field", "voice_focus_threshold": 0.7,
  "vad_threshold": 0.2,
  "continuous_partials": True, "include_partial_turns": True,
  "previous_context_n_turns": 5,
  "keyterms_prompt": [...],         # dynamic, ≤100 terms, ≤50 chars each — §3.6
  "prompt": "<domain context ≤1750 chars>",
  "session_heartbeat": True,        # this is the billed clock
  "inactivity_timeout": 15,
  "speaker_labels": False,          # ON in product; OFF in demo (it halves max_turn_silence)
}
```

**Sample-rate note, because it is easy to get wrong.** The accent analysis says "keep 24 kHz end-to-end"; the streaming contract wants 16 kHz. These do not conflict. The thing that destroys the S/F contrast is the **300–3400 Hz telephone band**, not the sample rate: /s/ energy lives at 4–8 kHz, which 16 kHz sampling (8 kHz Nyquist) preserves intact. Capture at the device's native rate, resample to 16 kHz mono s16le for the socket, and never let a G.711 leg in front of it.

`llm_gateway` is **not** a connect parameter. See §3.8.

### 3.2 Client / server split

The browser owns audio and pixels. The server owns the AssemblyAI socket, and therefore the money and the consent state — neither of which can be enforced from a page the user controls.

**Client (React/TS):**
- `getUserMedia({audio:{echoCancellation:true, noiseSuppression:false, autoGainControl:false}})` — NS off, `voice_focus` does that job better and browser NS fights it.
- 3-second PCM ring buffer, always filling, socket closed.
- Local VAD/RMS: onset → open socket and **flush the ring first** (bursts faster than realtime, costs ~0 billed seconds, makes the gate lossless); 8 s continuous silence → send `Terminate`, close.
- **Upstream mute gate**, held closed for the duration of *all page-generated audio* — our TTS and the demo's clerk fixture — plus a 150 ms tail. The red team found the clerk fixture speaks the full container number into an open mic; muting only for TTS is the on-stage failure.
- Demo-only DSP chain (AudioWorklet): 300–3400 Hz biquad band-pass → µ-law quantise → mixed room tone at a measured SNR. Produces a second PCM stream; both are sent up, tagged `clean` and `phone`.
- The rack UI, the counter, the raw drawer, `SpeechSynthesis`.

**Server (FastAPI):** consent gate → budget gate → AssemblyAI socket(s) → rolling tape → detector → normaliser → solver → decider → LLM Gateway (out-of-band) → Postgres. All the Python that already wants to be Python.

### 3.3 Data flow

```
mic ─► ring buffer ─► [VAD gate] ─► [mute gate] ─┬─► clean PCM ─┐
                                                  └─► DSP ─► phone PCM ─┤
                                                                        │ our WS
                                            ┌───────────────────────────┘
                                            ▼
  consent gate ─► budget gate ─► AssemblyAI Streaming WS (1 or 2)
                                            │
              Turn{words[{text,start,end,confidence,word_is_final}], end_of_turn}
                                            ▼
                          ROLLING TAPE  (~45 s / 400 words, memory only,
                                         replace-not-append keyed on turn_order,
                                         flattened across turn boundaries)
                                            ▼
   DETECTOR  (every partial): carrier phrase · NATO/"X for Y" · spelling rhythm ·
             format-shaped regex        require ≥2 of 4  ──► ARM (UpdateConfiguration)
                                            ▼
   NORMALISER  pass 1 lattice (length-correct, type-agnostic)
               pass 2 collapse against alphabet(i)  ──► h[], conf[], arity alternatives
                                            ▼
   SOLVER  constrained enumeration r1 → posterior → guard → r2 if empty   (p50 0.45 ms)
                                            ▼
   FORMAT GUARD  second signal required (carrier phrase | registered prefix | LLM)
                                            ▼
   DECIDER  rung 0 write silent · rung 1 amber · rung 2 earcon · rung 3 speak
                                            ▼
   Postgres (capture / session / interrupt / audit)      Browser (rack, counter, TTS)
```

### 3.4 The rolling tape

One structure per session, the only thing the detector reads. Deque of finalised turns plus the live partial, **flattened into one continuous word timeline** with session-relative `start`/`end` preserved. Bounded to 45 s or 400 words. Never persisted, destroyed at session end.

Two rules enforced structurally: **replace, never append**, keyed on `turn_order` (the docs are explicit); and dedupe on `(turn_order, end_of_turn, turn_is_formatted)` — with `format_turns=false` on `universal-3-5-pro` there is one final per turn, but the guard costs nothing and survives a model swap.

**The turn is not the unit.** A spoken identifier routinely straddles two or three turns because the canonical place for a mid-utterance hesitation is inside a code. The tape spans them; a turn boundary is never a parse boundary.

### 3.5 Normaliser — two passes, one lattice

Everything in builder requirement #1 lives here. No API parameter addresses any of it.

**Pass 1 — length-correct, type-agnostic.** Each token becomes a *cell*: `list[(char, weight)]`. Ambiguity that depends on slot type is deliberately not resolved.

- Unambiguous: `zed|zee|said|zet→Z`, `aitch|haitch|hatch|etch→H`, `ess→S`, `niner|nein→9`, `fife→5`, `tree|free|sree→3`, `fower→4`, `ait|ate→8`, `yot|hota|jota→J`, `veh|vay→W`, `ypsilon→Y`.
- **Deferred** — this set is the point: `oh|o|owe → (0, O)`, `you|yoo|ewe → (U, 2)`, `a|ay → (A, 8)`, `see|sea → (C, 6)`.
- Multipliers `double|treble|triple` × next cell; `trouble|terrible|tremble → treble`; `nought|naught|not|knot|nowt|nil → 0`; `and` as BrE numeric connective. **These three expansions run only in the ARMED state** — in IDLE, ordinary conversation containing "trouble" or "not" is a capture vector.
- `double u` emits a two-way *arity* cell: `W` (1 slot) vs `00|OO` (2 slots). Add **`W↔V` to the arity backtracking set**, not the substitution table — Indian-English /v/–/w/ makes "vee" and "double-u" interchangeable, and that is a 1-vs-2-slot ambiguity a substitution table cannot express.
- Disambiguator frames as a regex, not a table: `X for Y | X as in Y | X like Y | X wie Y | X come Y | X de Y` → `first_letter(Y)`, with a NATO override for `x-ray`. This generalises to invented words, which is most of them ("B for Bob").
- Teens/tens branch rather than collapse: `fifteen → [1|5][5|0]`. `format_turns=false` is what makes this possible.

**Pass 2 — collapse against `alphabet(i)`.** `oh` in a digit slot is `0`; in a letter slot it is `O`. An out-of-alphabet character is kept but flagged: it becomes evidence *for* an edit. This is why `MSKU4158O05` self-corrects to `MSKU4158005` with one candidate at p=1.000, silently, in three lines of code.

**Length before characters.** Ambiguous-arity tokens are enumerated (measured 2–4 combinations, k ≤ 2); only length-correct expansions reach the solver. Cost `O(T + 2^k·L)`.

Verified: all six spoken variants normalise identically.

```
"em ess kay you four one five eight zero zero five"                 → MSKU4158005 ✓
"M S K U four one five eight double oh five"                        → MSKU4158005 ✓
"mike sierra kilo uniform four one five eight nought nought five"   → MSKU4158005 ✓
"em ess kay you fower one fife ait oh oh fife"                      → MSKU4158005 ✓
"M for Mike, S for Sugar, K for King, U for Uniform, 4 1 5 8 0 0 5" → MSKU4158005 ✓
```

**The accent test is not WER.** It is: *does the normaliser emit an identical lattice from an American and a British reading of the same code?* One unit test per variant, cheap, decisive, automatable.

### 3.6 Detector and the ARM/IDLE state machine

Four cues over the tape, `≥2 of 4` before anything is written or spoken; any *one* arms.

- **(a) Carrier phrases** — "container number", "the IBAN is", "VIN", "part number", "booking", "it reads". High precision, frequently absent.
- **(b) Spelling vocabulary** — full NATO set plus the `X as in Y` construction. The most reliable indicator a human has switched into spelling mode.
- **(c) Spelling rhythm** — the metronome detector, and the one novel component. Over a sliding window of ≥5 tokens using `words[].start`: `short_ratio ≥ 0.80`, `cv_ioi < 0.35`, `mean_ioi ∈ [180, 600] ms`, zero function words. Content-agnostic, so it survives every accent; fires *while the code is still being spoken*, which is what buys time to arm.
- **(d) Format-shaped regex** over the normalised tape, including at edit distance 1–2. A poor trigger, an excellent confirmer.

**Arming, via `UpdateConfiguration` mid-stream.** This is the strongest Application-of-Technology beat in the ambient half and it exists because of a hard budget: 100 keyterms total, and a static list needs NATO (26) + digit variants (~15) + carriers (~20) ≈ 61, leaving no room for owner-code prefixes or catalogue SKUs.

```
IDLE   keyterms = carriers + NATO + digit variants          (~61)   max_turn_silence 1536
  ── trigger with format hypothesis ─►
ARMED  keyterms = NATO + digits + format tokens             (~95)   max_turn_silence 2500
       (MSKU/MSCU/TGHU/CMAU/HLXU… or the 40 catalogue SKUs)         eot_confidence_threshold ↓
       prompt = format-specific context sentence
  ── committed, or 12 s, or topic change ─► IDLE
```

`ForceEndpoint` once the candidate is length-complete, to close the turn immediately and claw back the ~1.5 s the raised `max_turn_silence` cost.

### 3.7 The confidence-regime detector — new component, and it de-risks the whole project

The day-1 unknown becomes a *runtime branch* instead of a project-killing bet. On the first ~40 words of every session:

| regime | detection | behaviour |
|---|---|---|
| **PER-CHAR** | words-per-spelled-character ≥ 0.9 and `stdev(conf) > 0.03` | ship as specified |
| **FLAT** | `stdev(conf) < 0.01` across a turn | disable silent accept at **letter** positions entirely; span becomes primary escalation |
| **BLOCK** | words-per-spelled-character < 0.6 | prompt NATO reading on the format card; span re-read primary; one-character question becomes a special case |

Measured stakes (`attack2.py`, ISO 6346, N=400): PER-CHAR → 24.5% silent, 99.2% correct, 0.0% silently wrong. FLAT → 5.0% silent, 79.2% correct, **5.0% silently wrong**. BLOCK → 0.0% silent, 92.0% correct, 0.0% silently wrong, 100% span. **Never ship the "spread the block doubt" fix** (`conf_i = 1−(1−c)/len(block)`): it buys 6.8% silence at the cost of 3.5% silent corruption on ISO and 4.0% on VIN. On IBAN it is safe (64% silent, 0% wrong) — enable it there only.

### 3.8 LLM Gateway — out-of-band HTTP, and its job is format identification

**Disagreement resolved.** The grounding proposes the in-band `llm_gateway` connect parameter ("two models, one socket"). The ambient spec says out-of-band, ranking candidates. The red team says give it format identification. **Take the red team's job, the ambient spec's transport.**

In-band fires on *every* finalised turn, and in ambient use the overwhelming majority of turns contain no identifier; it is also absent from the `UpdateConfiguration` field list, so it cannot be armed and disarmed. And candidate ranking is work the deterministic solver already does better in 0.45 ms.

Format identification has no validator behind it and is the highest-cost failure in the system. Measured (`attack.py`): 500 booking references of `[A-Z]{4}\d{7}` shape, read *perfectly*, at high confidence — **500/500 first decisions were ASK; 99.2% ended in handover; 0.8% were silently rewritten**. Two interruptions per string, about a correct string, triggered by a regex.

```python
POST https://llm-gateway.assemblyai.com/v1/chat/completions
Authorization: <ASSEMBLYAI_API_KEY>
{ "model": "claude-haiku-4-5",
  "messages": [{"role":"user","content": FORMAT_ID_PROMPT + tape_window}],
  "response_format": {"type":"json_schema","json_schema":{
      "name":"format_id","strict":true,"schema":{
        "type":"object","additionalProperties":false,
        "required":["format","confidence","evidence"],
        "properties":{
          "format":{"enum":["iso6346","vin","iban","nhs","catalogue","booking_ref","unknown"]},
          "confidence":{"type":"number"},
          "evidence":{"type":"string"}}}}},
  "post_processing_steps":[{"type":"json-repair"}] }
```

~300 in / 80 out tokens ≈ **$0.0007 per call**, a few per conversation, off the sub-second interrupt path by nature. It makes "models, plural" true rather than decorative.

**The second-signal rule, which is the actual fix:** never assert a format from shape alone. Require carrier phrase **or** a prefix present in the BIC owner registry **or** LLM format-ID confidence ≥ 0.8. Absent all three, capture as **unvalidated free text and stay silent**. A string that fails the check digit *and* whose prefix is not a registered owner code is not a container number.

Keep the in-band `llm_gateway` as a **demo-only toggle** that shows `LLMGatewayResponse` frames arriving on the same socket. Shown once, never run always.

### 3.9 Database

```sql
CREATE TABLE session (
  id UUID PRIMARY KEY, started_at TIMESTAMPTZ, ended_at TIMESTAMPTZ,
  billed_seconds INT,                    -- Termination.session_duration_seconds
  sockets INT DEFAULT 1,                 -- 2 in A/B demo mode; cost = billed_seconds*sockets
  confidence_regime TEXT,                -- per_char | flat | block   (§3.7)
  consent_version TEXT, consent_at TIMESTAMPTZ, disclosure_played BOOL,
  operator_id UUID NULL, ip_hash TEXT, demo_mode BOOL);          -- ip_hash 24h

CREATE TABLE capture (
  id UUID PRIMARY KEY, session_id UUID REFERENCES session,
  format_type TEXT, heard_value TEXT, final_value TEXT,
  validated_by TEXT,                     -- check_digit | registry | catalogue | both | none
  second_signal TEXT,                    -- carrier | prefix | llm | none  (§3.8)
  confidence_at_write REAL, corrected BOOL, position_corrected INT NULL,
  candidates_considered JSONB,           -- top 5 only
  rung SMALLINT, latency_ms INT, created_at TIMESTAMPTZ);        -- 30d

CREATE TABLE interrupt (                 -- the product's own proof; build day 1
  id UUID PRIMARY KEY, session_id UUID, capture_id UUID,
  rung SMALLINT, position INT, form TEXT,           -- confirm | alternative | respell
  question_text TEXT, offered JSONB,
  answered BOOL, answer_in_grammar BOOL, resolution_ms INT);     -- 7d, then counts

CREATE TABLE owner_code (                -- the letter constraint the check digit cannot be
  code CHAR(3) PRIMARY KEY, owner TEXT, weight REAL);            -- frequency-weighted

CREATE TABLE catalogue_part (
  sku TEXT PRIMARY KEY, description TEXT, rhyme_signature TEXT);
CREATE INDEX ON catalogue_part (rhyme_signature);

CREATE TABLE confusion_observation (     -- online pseudo-counts from answered questions
  heard CHAR(1), truth CHAR(1), n INT, last_seen TIMESTAMPTZ,
  PRIMARY KEY (heard, truth));

-- audit: existing append-only table, reused unchanged
```

**Never stored, in any environment:** raw audio; the rolling tape; turns containing no identifier; per-word confidences and timings after a capture commits; speaker embeddings (never computed at all); the sentence surrounding an identifier; IPs in clear; anything matching a 13–19 digit Luhn-valid pattern, at every stage including logs and stack traces.

### 3.10 Tool definitions

**Control frames, browser ⇄ server (our WebSocket).**

```jsonc
// client → server
{"t":"session.start","consent_token":"…","demo_mode":true,"ab":true}
// binary frames: [1-byte channel tag: 0=clean 1=phone][PCM s16le]
{"t":"answer.submit","question_id":"…","choice":0}          // or {"text":"mike"}
{"t":"slot.edit","capture_id":"…","position":6,"char":"9"}  // break-it-yourself
{"t":"ablate","acoustic_model":false}                        // the ablation toggle
{"t":"session.stop","delete":true}

// server → client
{"t":"capture.update","capture_id":"…","format":"iso6346",
 "slots":[{"char":"M","conf":0.97,"state":"settled","alts":[]},
          {"char":"9","conf":0.52,"state":"contested","alts":["9","5"]}],
 "validated_by":"check_digit","second_signal":"prefix","rung":0,
 "diff":{"heard":"MSKU4198005","written":"MSKU4158005"}}
{"t":"candidates.show","chips":[{"position":0,"char":"L"}, …]}   // the 14→1 collapse
{"t":"question.ask","question_id":"…","position":3,"form":"alternative",
 "text":"Position four — Mike, or November?","choices":["M","N"]}
{"t":"meter","characters":38,"questions":1,"speech_ms":2100,"billed_seconds":94}
{"t":"session.end","reason":"cap","billed_seconds":150,"permalink":"/s/7f3a"}
```

**Server-side HTTP tools (reuse the existing scoped-JWT / idempotency / audit endpoints).** Each takes `Authorization: Bearer <session-scoped JWT>` and `Idempotency-Key`.

```jsonc
POST /tools/capture.commit
  in : {"session_id","capture_id","format","value","validated_by","second_signal",
        "corrected":bool,"position_corrected":int|null}
  out: {"ok":true,"record_id":"…"}
  // REFUSES with 422 unless validated_by != "none" AND second_signal != "none".
  // There is no path from "probably right" to a clean row.

POST /tools/capture.flag
  in : {"session_id","capture_id","value","reason":"checksum_invalid|implausible_repair"}
  // At most once per distinct string per session. Twice is the deadlock.

POST /tools/lookup.owner_code   in:{"prefix":"MSK…","radius":1} out:{"matches":[{code,owner,weight}]}
POST /tools/lookup.catalogue    in:{"hypothesis","radius":2}    out:{"matches":[{sku,description,score}]}
POST /tools/format.identify     in:{"tape_window"}              out:{"format","confidence","evidence"}
POST /tools/session.terminate   in:{"session_id","delete":bool} out:{"billed_seconds"}
```

### 3.11 Cost and gating

Billing is **WebSocket wall-clock, including silence**, pro-rated per second; sessions hard-close at 3 h and you are billed for all of it. Unclosed sessions are the documented #1 cause of surprise charges — for an always-listening product that is the design constraint, not a footnote.

`universal-3-5-pro` 0.45 + `voice_focus` 0.10 + prompting 0.05 = **$0.60/hr = $0.01/min per socket.**

**Correction to the ambient spec:** the A/B demo runs *two* sockets. A 150 s demo session costs **$0.05**, not $0.025, and $50 of credits is **~1,000 sessions, not 2,000**. All gates below are computed from the corrected number.

| control | value |
|---|---|
| per-session hard cap | 150 s socket-open, enforced server-side off `Heartbeat.total_duration_ms` |
| backstop | `inactivity_timeout: 15`; **never send `KeepAlive`** — it is the burn-credits button |
| duty cycle | ring buffer + VAD gate; 20–35% saving in conversation, much more in a demo |
| per-IP (salted) | 3/hour, 10/day |
| concurrency | **3 sessions (6 sockets)**; admission ≤2 sessions/min (free tier allows 5 new streams/min); overflow gets a "~20 s" queue screen — a queue demos better than a failure |
| daily budget | $20/day ≈ 400 dual-socket sessions; alarm 60%, kill switch 100% → replay mode |
| ledger | `Termination.session_duration_seconds` × `sockets` into `session`; reconcile nightly |

### 3.12 Consent — the non-negotiables

*Not legal advice.* ~12 US states require all-party consent; a call centre never knows where its caller is sitting. **Always obtain all-party consent. Do not build a jurisdiction toggle** — a toggle is a liability generator that will be set wrong.

Product: disclosure in the audio channel before capture, amending the existing call announcement; a persistent three-state indicator (off/listening/speaking) plus start and end earcons — ambient is not surreptitious and that distinction must live in the UI, not the deck; no raw audio retention anywhere including dev; no transcript retention; field-level minimisation; **never compute a voiceprint or speaker embedding, never do cross-session speaker ID, no sentiment analysis, no agent quality-scoring of the humans** — say this in the pitch, refusing it is a positioning asset.

Demo: one microphone, one consenting person — the judge. The second voice is a pre-recorded fixture played by the page, never a captured call. Consent screen with an explicit checkbox before the mic opens (browser permission is not consent). Explicit click to start. A "stop and delete" button that terminates the socket and visibly deletes. Fictional data by construction; the page offers the code to read, which also stops a judge volunteering their own IBAN in a room. 24-hour auto-purge, stated and implemented.

---

## 4. THE ALGORITHM, FINAL FORM

### 4.1 The framing

There is no syndrome algebra. Measured (`cands.py`, N=4000/cell): **ISO 6346's check digit returned exactly one repair zero times in 24,000 trials.** It narrows 26 → 13.7 candidates; 86% of positions survive it. IBAN-GB does better (3.4 candidates, 15% of positions survive) but still returns a menu.

> **The validator is a hard 0/1 prior. The confusion table and `words[].confidence` are the likelihood. Multiply, normalise, read everything off the posterior — including where to ask, and including whether to speak at all.** Localisation is a property of the posterior, not of the check digit.

### 4.2 Position posterior

```
P(true = x | h_i, c_i)  ∝   c_i                        if x == h_i and x ∈ A_i
                            (1−c_i)·w(x→h_i)/S_i       otherwise
S_i = Σ_{y ∈ A_i, y ≠ h_i} w(y→h_i)
```

`A_i` is the format's alphabet at position *i*. If `h_i ∉ A_i` the `c_i` term vanishes and the distribution is pure confusion table — which is the whole `MSKU4158O05` case. `w(a,b)` carries a floor for pairs absent from the table so the search stays complete.

### 4.3 Candidate generation

**Radius 1 — full alphabet, unrestricted by the confusion table.** All `(i,c)` with `c ∈ A_i`, `c ≠ h_i`, `valid(h[i→c])`. Deliberately unrestricted: filtering the *search* by the table makes table gaps invisible instead of merely unlikely. The posterior scores them down afterwards.

**Radius 2 — bounded, only when r1 is empty.** Top-`M=5` positions by doubt × top-`K=6` acoustic alternates as a seed edit, then a full r1 with the seed locked. Finds every 2-error repair where at least one error is acoustically suspect.

Measured validator calls and end-to-end latency:

| format | L | r1 | r2 bounded | r2 unbounded | p50 `decide()` |
|---|---|---|---|---|---|
| ISO 6346 | 11 | 140 | 3,246 | 8,577 | **0.45 ms** |
| VIN | 17 | 544 | 13,086 | 139,776 | 2.09 ms |
| IBAN-GB | 22 | 294 | 8,556 | 40,695 | 0.79 ms |

The bound matters on VIN: unbounded r2 is 140k calls ≈ 0.4 s in CPython, past the interrupt budget.

`fastval.py` supplies O(1) incremental validators for ISO 6346 and IBAN mod-97 (verified against reference on 651 and 616 strings, zero disagreements). Not required at these latencies; it is the answer to "what is the worst case", and it makes VIN comfortable.

### 4.4 The decision — four gates

```
0 candidates                                  → length check → bounded r2 → SPAN RE-READ
1 candidate, edit implausible (w < 0.15)      → FLAG: data error, not mishearing (once per string)
1 candidate, edit plausible                   → ACCEPT SILENTLY   ← subject to the guard
≥2 candidates, p₁ ≥ 0.85 and p₁/p₂ ≥ 8        → ACCEPT SILENTLY   ← subject to the guard
otherwise                                     → ASK
```

**The doubt-budget guard.** A position is *doubtful* if `1 − post_i[h_i] > DOUBT_T`. A candidate *explains* a doubtful position by editing it. **Silent acceptance requires every doubtful position to be explained.** Unexplained doubt means a second error the checksum has already absorbed. This is the single highest-value line in the algorithm — before it, IBAN-GB under two errors resolved wrongly 35% of the time, silently, with high confidence:

| 2 errors, calibrated | correct before guard | correct after | silently wrong after |
|---|---|---|---|
| ISO 6346 | 47.4% | **97.2%** | 0.0% |
| VIN | 42.1% | 88.3% | 0.0% |
| IBAN-GB | 10.7% | 92.8% | 0.0% |
| Luhn-16 | 11.0% | 93.9% | 0.0% |

**The per-edit plausibility gate.** Any character the agent silently changes must be a substitution the table knows (`w ≥ 0.15`). An arithmetically-valid-only repair is evidence of a *data* error. Measured on genuinely invalid identifiers read clearly: ISO 0.0%, NHS 0.0%, Luhn 0.0% falsely "fixed"; IBAN 4.7% — which is why IBAN silent correction additionally requires the national BBAN check digit to agree.

### 4.5 Where to ask — and the bug the experiment found

`argmax_i H(marginal_i)` is **identically zero at every position when there is exactly one valid candidate** — precisely the case the guard fires for. An implementation that reads "no entropy to gain" as "nothing to ask" falls straight through to a silent accept. Measured (`guardhole.py`, N=6000/cell):

| | guard fires with zero entropy | of those, written wrong and silently |
|---|---|---|
| ISO p=0.05 | 56.3% of identifiers | 2.0% |
| ISO p=0.15 | 33.2% | 10.3% |
| IBAN p=0.15 | 19.3% | **41.8%** |

**The fix, and it is the unified rule:**

```python
unexplained = doubtful - edited
if unexplained:  p = argmax_{i ∈ unexplained} (1 - post[i][h[i]])   # detection
else:            p = argmax_i H(marginal[i])                        # disambiguation
```

Marginal entropy measures disagreement *among candidates*; the guard fires when the suspicion is a second error, which no candidate disagrees about. After the fix: **silently-wrong = 0.000 in every cell**, and accuracy *rises* (ISO p=0.10: 0.828→0.859; IBAN p=0.05: 0.769→0.867).

Where entropy does apply, it beats the obvious alternative by up to 19 points and is free:

| | max-entropy correct | "where top two differ" correct |
|---|---|---|
| ISO 6346, 1 err | **100.0%** | 96.4% |
| Luhn-16, 1 err | **100.0%** | 80.7% |

### 4.6 Parameters, and what justifies each

| parameter | value | source |
|---|---|---|
| `FLOOR` (unseen-pair weight) | **0.004** | `bench3.py` sweep — the knee: 22.6% silent, 0% silent-wrong, 0.3% handover. Lower = more silence and more handovers |
| `DOUBT_T` | **0.40** *(was 0.25)* | `knee.py`, ISO p=0.02 — 0.40 **dominates 0.25 on every axis**: accuracy 0.982 vs 0.983, silent **63.6% vs 20.2%**, questions/id **0.45 vs 1.26**, handover **2.8% vs 19.8%**, at +0.0005 silent error |
| `ACCEPT_P` | 0.85, ratio ≥ 8 | `bench.py` |
| `PLAUSIBLE_W` | 0.15 | plausibility gate; 0% false silent fixes on ISO/NHS/Luhn |
| `budget_q` / `budget_span` | 2 / 1 | termination proof: each question locks a position, locks clear only on span |
| r2 `M`, `K` | 5, 6 | 2.6× saving on ISO, **10.7× on VIN** |
| confusion table | **one, unblended, no accent detection** | ORACLE−BLENDED = −0.001…+0.002; US-only−BLENDED = −0.002…+0.000, both formats, every error rate |
| online update | pseudo-count on every answered question | out-of-table errors cost 21→0.8% silence and 12→59.5% span; one dict write fixes a systematic accent after *one* question |

**Disagreement resolved — accent adaptation.** The experiment says accent knowledge is worth zero; the red team says learn from answered questions. Both are right about different things: knowing *which accent* buys nothing, but a confusion *pair absent from the table entirely* costs a great deal of silence. **Build no accent detection and no table blending; do build the ten-line online pseudo-count.** It also reads on screen as "it learned your accent in one exchange", which is worth more in the Originality column than anything else at the same cost.

### 4.7 The question

Three rules, all falling out of the phonetics:

1. **Never anchor by ordinal.** Humans cannot count to position 7 in a string they just spoke. Anchor by readback of the two or three characters immediately before it. This is aviation practice and it is why the product is called Readback.
2. **Never pose the alternatives in the acoustic space that just failed.** "B or D?" is broken twice — both E-set, and the *answer* is another E-set letter you will also mishear. Emit NATO for letters and ICAO forms for digits (`tree`, `fower`, `fife`, `niner`). Accept anything.
3. **One character of new information.** Mirror the speaker's own convention: if they said `zed`, say zed; if they said `double four`, read back `double four`.

Form chosen by the shape of the marginal — the same quantity that chose the position: `p > 0.80` → **confirm** (yes/no, 1 bit, the cleanest answer space there is); two-way → **alternative**; three or more live → **respell**, offer the top three.

```
heard MSKU4198005  [5→9 at pos 7, conf 0.52]  → ACCEPT, 14 cands, p=0.962   SAYS: nothing
heard MSKU4158O05  [O in a digit slot]        → ACCEPT, 1 cand,  p=1.000    SAYS: nothing
heard TGHU7489231  [flat conf, 16 cands]      → ASK pos 3, H=1.45 bits
  "Sorry, one character — after Tango Golf, can you give me just that one again?
   I have it as Hotel, Alfa or Kilo."
heard 9434765918   [NHS, last digit]          → ASK pos 10, H=0.75 bits
  "Quick one — right after five nine one, was that niner or ait?"
heard 1HGCN82633A004352 [VIN, M→N, conf 0.48] → ACCEPT, 40 cands, p=0.879   SAYS: nothing
```

The last one is the product: 40 checksum-valid candidates and it still says nothing, because M/N at a low-confidence position dominates the posterior and the guard is satisfied. Show the 40-candidate menu collapsing while the agent stays silent.

**Parse the answer under constraint too** — restrict the grammar to the offered alternatives, their NATO/ICAO forms, and yes/no. Out-of-grammar counts against the budget and re-asks. **Lock** the position; the solver never edits it again, which guarantees the candidate set strictly shrinks.

### 4.8 Ambient discipline — the gates that override everything

Speaking requires **all** of:

1. We know it is *wrong*, not merely unsure — the format validated and the check failed, or no catalogue row within edit distance 1. Uncertainty alone is amber on screen.
2. `end_of_turn` is true **and** the candidate is **length-complete** for the hypothesised format **and** the last token was not itself a letter-name or digit-word. *The 700 ms silence gate alone is not enough — the canonical place for a >700 ms human pause is mid-identifier, so length-completeness is the only reliable signal that the code finished.*
3. Resolving it changes an outcome (fills a required field). Numbers mentioned in passing never trigger speech.
4. ≥700 ms with no speech from either speaker: client VAD ∧ low `Heartbeat.max_speech_probability` ∧ turn ended. Never during overlap.
5. ≥1.5 s politeness delay, so the humans get first refusal at self-correcting.
6. Budget: ≤1 spoken interruption per identifier, ≤2 per 5 minutes, 20 s hard cooldown. Exhausted → drop to earcon permanently for that session.
7. **>10 s since the identifier's last word → do not speak at all.** Write it UNVERIFIED with ranked candidates and let the human resolve it on screen. A late interruption is worse than no interruption.

Talked over → cut mid-word, **never repeat**, drop to earcon. Confirm by writing, never by speaking — no "got it, thanks." **Always show the diff:** any silent correction appears as `heard → written`. An agent that quietly changes what a person said is a trust problem regardless of how often it is right.

### 4.9 Core loop

```python
def readback(fmt, tokens, budget_q=2, budget_span=1):
    cells, _ = pass1(tokens, armed=True)
    h, conf, n = pass2(cells, fmt.A, fmt.length)
    if n != fmt.length:
        h, conf = arity_backtrack(cells, fmt) or REREAD_ALL     # LENGTH BEFORE CHARACTERS

    if second_signal(h, tape) is None:
        return CAPTURE_UNVALIDATED(h)                            # §3.8 — and stay silent

    locked, q, spans = set(), 0, 0
    while True:
        post  = [pos_post(fmt, i, h[i], conf[i], tags, locked) for i in range(fmt.length)]
        cands = [h] if fmt.ok(h) else repairs_r1(fmt, h, locked)
        if not cands: cands = repairs_r2(fmt, h, conf, locked, M=5, K=6)
        pr    = softmax([score(fmt, c, h, post) for c in cands])
        top   = cands[argmax(pr)]

        doubtful  = {i for i in range(fmt.length)
                     if i not in locked and 1 - post[i][h[i]] > 0.40}      # DOUBT_T
        edited    = {i for i in range(fmt.length) if top[i] != h[i]}
        unexplained = doubtful - edited
        plausible = all(w_of(top[i], h[i]) >= 0.15 for i in edited)

        if cands and (len(cands) == 1 or (pr[0] >= 0.85 and pr[0]/pr[1] >= 8)):
            if not plausible:      return FLAG_INVALID(top, h)
            if not unexplained:
                if regime == "flat" and edited & fmt.letter_positions:
                    pass                                          # §3.7: no silent letters
                else:
                    return ACCEPT(top)                            # ← silent. the product.

        marg = marginals(fmt, cands, pr)
        need = max(count(H(m) > 0.5 for m in marg), len(unexplained) + 1)

        if not cands or need > budget_q - q or not plausible:
            if spans >= budget_span: return HANDOVER("budget")
            spans += 1
            h, conf = await span_reread(*narrowest_span(doubt_order(fmt,h,conf,locked)[:4]))
            locked = set(); continue

        if q >= budget_q: return HANDOVER("budget")
        p = (argmax_over(unexplained, lambda i: 1 - post[i][h[i]])   # ← the guardhole fix
             if unexplained else argmax_i(H(marg[i])))
        q += 1
        ans = await ask(question(fmt, h, p, marg, speaker_convention))
        if ans is None: continue
        observe_confusion(heard=h[p], truth=ans)                  # online pseudo-count
        h = h[:p] + ans + h[p+1:]; conf[p] = 0.999; locked.add(p)
```

---

## 5. WHAT IS REUSED, FILE BY FILE

The existing voice-agent codebase is not in this worktree (`grep -i assemblyai` over it returns nothing) — it lives in the builder's other project. Below is the reuse map by module role, with the target path in the new repo. Copy, do not import across repos.

### Reused essentially unchanged

| existing asset | target | change required |
|---|---|---|
| Browser voice client, ~490 lines: WebSocket transport, PCM mic capture, resampler, live amplitude, barge-in | `web/src/audio/client.ts` | **Swap the socket URL to our FastAPI proxy and change the frame envelope to add a 1-byte channel tag.** Barge-in becomes "cut our TTS mid-word", which is the same code path. |
| Gapless playback | `web/src/audio/playback.ts` | Used for the demo's clerk fixture and the voice bench. Add the upstream mute hook. |
| Client-side tool dispatch | `web/src/rpc/dispatch.ts` | Retarget from Voice-Agent function calls to our control frames (§3.10). Same dispatcher. |
| Server HTTP tool endpoints: per-session scoped JWT, idempotency keys, rate limiting | `server/tools/` | New handlers, unchanged middleware. This is the biggest single saving — the JWT scoping and idempotency are exactly what `capture.commit` needs. |
| Append-only audit log | `server/audit.py` | Unchanged. Add the four new event types. |
| FastAPI + SQLAlchemy skeleton, auth, migrations | `server/` | Add the six tables in §3.9. |
| Render/Vercel deploy config | root | Add `ASSEMBLYAI_API_KEY`, the daily-budget env flag, the replay-mode kill switch. |
| PDF generation | `server/pdf.py` | Repurposed for the session permalink export — a judge who wants to take the artefact away. Low priority; cut first. |

### Reused from this workflow's scratchpad — port, do not rewrite

All under `D:\temp\claude\D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762\c09d90d9-a412-4614-b967-92de40b55905\scratchpad\`:

| file | becomes | note |
|---|---|---|
| `val.py` | `server/readback/validators.py` | All 14 validators, already checked against published test vectors |
| `fastval.py` | `server/readback/fastval.py` | O(1)-update ISO 6346 + IBAN mod-97; verified 0 disagreements on 1,267 strings |
| `rb.py` | `server/readback/solver.py` | Core posterior + enumeration. **Apply the §4.5 guardhole fix and set `DOUBT_T=0.40` before anything else.** |
| `norm.py` | `server/readback/normalise.py` | Two-pass lattice; add the ARMED-only multiplier rule and W↔V arity |
| `ask.py` | `server/readback/question.py` | Question generator, already produces the §4.7 output |
| `lenfix.py` | `server/readback/arity.py` | Length repair |
| `bench*.py`, `xp.py`, `knee.py`, `guardhole.py`, `tolerance.py` | `tests/bench/` | The regression harness. Re-run every parameter change. |
| `accent.py` | `tests/fixtures/accents.py` | Eight accent tables — **for testing the solver against mismatch, not for shipping.** Production ships one table. |

### New, and roughly sized

| component | lines | week |
|---|---|---|
| Server-side AssemblyAI session manager (connect, tape, UpdateConfiguration, ForceEndpoint, Terminate, heartbeat meter) | ~400 | 1 |
| Confidence-regime detector (§3.7) | ~60 | 1 |
| Detector: 4 cues + ARM/IDLE state machine | ~300 | 2 |
| Owner-code registry loader + frequency weights + multi-probe rhyme index | ~200 | 2 |
| Decider: rungs, gates, budgets | ~250 | 2 |
| Rack UI: slots, flicker, chip collapse, counter, raw drawer | ~700 | 1–3 |
| Phone-line DSP AudioWorklet + dual upstream | ~200 | 3 |
| LLM Gateway format-ID + second-signal rule | ~150 | 3 |
| Consent gate, budget gate, replay mode, permalink | ~350 | 3 |
| Ablation toggle, break-it-yourself, type-any-number | ~150 | 3 |

≈ 2,800 new lines, ≈ 1,500 ported, ≈ 900 reused. One developer, 28 days, comfortable with three days of slack.

---

## 6. THE 28-DAY PLAN

### Week 1 — the probe and the spine

**Day 1 is the falsification experiment. Nothing else is written until it returns.**

> **THE ONE-DAY EXPERIMENT.** Twelve container numbers × six readings (two native accents live, four TTS voices covering en-IN, en-NG, fil, es-L1) × three conditions (clean 16 kHz, 300–3400 Hz band-passed, +11 dB babble), streamed through the real socket with `format_turns=false`, both as letter-names ("em ess kay you") and as NATO ("mike sierra kilo uniform"). Log every raw frame. Compute two numbers:
>
> **(A) Words per spelled character.** Does "MSKU" return four `Word` objects, one, or `"em ess kay you"`? *This, not calibration, is the load-bearing measurement* — it determines whether the escalation instrument is a one-character question or a span re-read, and everything downstream branches on it.
> **(B) AUC of `words[].confidence` separating correct from incorrect characters** on the induced confusions (B/D, 5/9, M/N, S/F).
>
> **Branch table:** (A≥0.9, B≥0.70) → build exactly as specified. (A≥0.9, B<0.60) → FLAT regime: no silent accept at letter positions, span primary; forecast is 79% correct, 5% silent-wrong without that guard, 0% with it. (A<0.6) → BLOCK regime: NATO reading on the format card, span primary, the pitch becomes *"it asks you to repeat four characters, once, instead of the whole number"* — weaker, still real, honest.
>
> **Nothing in this plan is falsified by the outcome. What changes is which instrument the product uses to escalate.** Ship the regime detector (§3.7) either way, so a wrong day-1 answer degrades a demo rather than killing a build. Also answer in the same afternoon: how fast does `UpdateConfiguration` take effect; where do turn boundaries fall in dictated codes at default `max_turn_silence`; does `redact_pii` really disable partials; and does `cv_ioi` separate 20 dictated codes from 20 minutes of conversation.

Days 2–7: server session manager + rolling tape + replay harness (the fixtures from day 1 become the regression corpus). Port `norm.py` and write the US↔UK lattice-equality tests. Port `val.py` + `rb.py`, apply the guardhole fix and `DOUBT_T=0.40`. Rack UI skeleton with the flicker.

**True at end of week 1:** a person speaks a container number into the browser; raw AssemblyAI words appear; a single-character error is silently repaired on screen with the diff shown. The confidence regime is measured and written down.

### Week 2 — the constraint layers and the ambient discipline

Owner-code registry (BIC CSV, frequency-weighted) + 40-row catalogue + **multi-probe** rhyme-signature index (single-probe loses the truth 20% of the time; multi-probe recovers 97–99% at ~10 extra hash lookups — do not ship the single probe). Detector with all four cues including the rhythm detector. ARM/IDLE + `UpdateConfiguration` + `ForceEndpoint`. Decider rungs 0–3 with every gate in §4.8. `SpeechSynthesis` + echo mute for **all** page audio. Run the measured confusion matrix (36 characters × N voices × 3 noise × 2 bandwidths) and replace the inferred priors where measured — this is also the heatmap the video needs.

**True at end of week 2:** the agent stays silent through a two-minute conversation, writes three identifiers, and speaks exactly once, on the one it could not resolve. The `interrupt` table has real rows.

### Week 3 — the demo, the honesty, the fallbacks

Phone-line DSP + dual socket + A/B strips + the adaptive SNR sweep. **The ablation toggle.** Break-it-yourself, type-any-number, raw drawer, replay of the judge's own contested audio window. Voice bench (six accent recordings streamed *from file into the same live socket*). Replay mode. LLM Gateway format-ID + the second-signal rule. Consent gate, budget gates, cost meter, session permalink.

**True at end of week 3:** the demo runs end-to-end from a cold link — on a phone, muted, with the mic denied, and with the network down. All four fallback paths tested by someone who is not the builder.

### Week 4 — hardening, the video, the numbers

Days 22–24: run the accent test set through the real pipeline; re-sweep `FLOOR` and `DOUBT_T` on the *measured* confusion matrix rather than the priors; fix whatever the real data breaks. Day 25: the 90-second video. Day 26: submission text, the ablation slide, the `(alphabet ÷ modulus) × length` slide, the heatmap. Day 27: freeze. Day 28: three dry runs on three devices and three networks.

**True at end of week 4:** every number in the pitch comes from real sessions, and each headline is reported as a **pair** — matched table and out-of-table (§8). The simulated numbers stay in the appendix, labelled as simulation.

---

## 7. THE DEMO — final beat sheet

Total 120 s. Every beat has a 6-second dead-man timer that auto-advances to the voice-bench version of the same beat. **It must never stall for an unattended judge, and it must land muted** — test it muted before shipping.

**Beat 0 · 0:00–0:15 — the homophone. Fires 100% of the time, by construction.**
Above the rack, *first*, ten words of stakes: **"This is a shipping container number. One wrong character sends forty tons to the wrong continent."** Then the puzzle: a six-slot rack showing `[O O L U][4 0]`, **"Read it out loud"**, and **"Three of those sounds are identical. Two are letters, one is a digit. No microphone can tell them apart. The format can."** Beside the mic button: *can't talk right now? play a real caller →*. At 0:06 the waveform reacts to a desk tap before any speech — the cheapest proof the stream is live — and a room reading paints (`47 dB — quiet, we'll add the phone line` / `68 dB — noisy, you already have a phone line`; either verdict wins). Tokens land as AssemblyAI's raw words `oh · oh · el · you · four · oh`, then three lines animate down into slots 1, 2 and 6 — two letter `O`, one digit `0`. Caption: *ISO 6346: positions 1–4 are letters, 5–10 are digits.* If the judge says **"double oh"**, the screen calls it out: `heard "double oh" → 00 → positions 1–2 are letters → OO`. A free, unscripted accent beat inside fifteen seconds.
*(`OOLU` is OOCL and real. Verify against the BIC register before shipping; fallback `TOLU`.)*

**Beat 1 · 0:15–0:40 — the repair that happens in silence.**
The rack shrinks to a sidebar and a conversation panel takes centre — the demotion *is* the ambient argument. Clerk fixture: *"Right — and which box is that on?"* **The upstream mute gate is closed for the whole fixture.** Judge reads `MSKU4158005`. Both transcript strips fill and visibly disagree: clean `MSKU4158005`, phone `MSKU4198005`. The clean strip is labelled **"what a good headset gets — your customer doesn't have one"**, never "ground truth". Check digit flips red; **fourteen candidate chips appear, one per position** — *"the checksum says one character is wrong. It gives you a menu, not an answer."* Over 600 ms, thirteen grey out and fall: *"the model's own confidences kill thirteen of them."* Slot 7 flickers `9/5/9/5` for 400 ms, settles green. Grey line: `repaired silently · position 7 · no question asked`. Then **nothing**. Clerk: *"Got it — booked."* Counter: `characters 11 · questions 0 · agent speech 0.0s`.

*Guarantee ladder if the phone stream transcribes clean:* adaptive SNR sweep, −4 dB, *"Nice mic. Let's turn the line down."* → the model's own second choice, labelled → judge clicks a slot and types a wrong character. Tier 0 (the homophone) already fired, so the demo cannot have failed by here.

**Beat 2 · 0:40–0:55 — the one time it speaks.**
A second identifier where two candidates survive (M/N at 0.72, or S/F under narrowband at 0.80). Slot 4 goes amber and flickers between the *actual* competing letters — not a `?`. Two seconds of speech: *"Position four — Mike, or November?"* One character, in NATO so the answer lands in a different acoustic space, and in the judge's own convention. Question also rendered as two clickable chips, so a judge on mute loses nothing. Counter ticks to `questions 1 · agent speech 2.1s`. **Do not narrate the contrast. The counter says it.**

**Beat 3 · 0:55–1:10 — American and British converge.**
Part number `HZ-3080`: seven characters, four seconds, and every token diverges. The page already saw `zed` or `zee` in the judge's stream: *"You're a zed speaker. Here's Chicago."* Two raw rows sit there looking word-for-word different — `aitch · zee · three · zero · eight · zero` vs `haitch · zed · three · oh · eight · oh` — and converge into one box: **`HZ-3080 — brake caliper, left front`**, matched against the 40-row catalogue. Caption: *"Seven different words. One part."* **This is the second constraint engine** — beat 1 proved the algebraic one, beat 3 proves the closed set, and they are independent. That pairing is the "models, plural" argument.

**Beat 4 · 1:10–1:30 — the proof beat, and the ablation.**
*"Listen to the 1.2 seconds we were arguing about."* The judge's **own voice**, that window, through the same phone-line chain. They cannot tell five from nine either. The failure stops being a product weakness and becomes a property of the channel — which is the thesis.
Then the toggle: **`acoustic model: on / off`**. Flip it off and the same live session goes from one question to three questions and a re-read, on screen, counter moving. *This is the red team's best idea and it is the Originality beat:* it is the ablation a technical judge is already running in their head, run for them, honestly, and it is the literal wording of "ability to demonstrate behaviors."
Alongside: click any slot and type a wrong character; type any container number and watch it validate (`check digit should be 3, you typed 7`); and the blind spots printed in small type — *"ISO 6346 detection is 96%, not 100%. B and V are invisible to the check digit, always. That is what the owner registry is for."* A demo that admits blind spots was not animated.

**Beat 5 · 1:30–1:45 — it generalises.**
Six live-validating tiles: ISO 6346, VIN, IBAN, NHS, NPI, catalogue. One line of maths: **`expected candidates ≈ (alphabet ÷ modulus) × length`**, with IBAN (10/97) and CPF lit green, Luhn and EAN (10/10) greyed — *"detects, never localises."* This is the slide that says you did the analysis rather than the demo, and it is why there is no credit-card validator.

**End card · 1:45–2:00.** Three figures from the session that just happened: `38 characters captured · 1 question asked · 2.1 seconds of agent speech in 2 minutes`. **`Your session: readback.app/s/7f3a`** — a permalink replaying exactly what they did, raw payloads intact, so the judge leaves with a citable artefact for their scoring notes. One line, no CTA: *"It listens to the call that was happening anyway. It writes down the reference. It speaks when it must."*

**Video, 90 s, a different cut.** Opens on a failing transcript with one character red, burned-in caption: **"Nobody can hear the difference between five and nine on a phone line. Neither can the model. So we stopped trying to."** Shows what the link cannot: the measured confusion heatmap, a single voice degraded across five SNRs, a real second human for the accent beat, and one honest shot where **the judge's answer is also misheard and the agent escalates to NATO** — six seconds that prove the design rule. Ends on the URL, held five seconds.

**Fallbacks.** Mic denied / silent room / open-plan → the voice bench, six real accent recordings streamed from file into the same live socket, offered from second 0 as a first-class element. Network down → labelled offline replay of a real captured session's JSON at its real timestamps, with a persistent banner naming the date and session id (never silently fake it — the banner is itself a credibility asset). Room too noisy for even the clean stream → **the best case**: say so at second 7 and skip the filter.

---

## 8. SCORING AGAINST THE FOUR CRITERIA

**Application of Technology — strong, with one deliberate repair.** The build uses `words[].confidence` and `words[].start/.end` as the *substrate of an algorithm*, not as a UI garnish; `format_turns=false` because formatting is a lossy collapse that destroys the "fifteen vs one five" evidence; `UpdateConfiguration` to rewrite keyterm bias mid-stream based on what the conversation is doing; `ForceEndpoint` to reclaim latency; `voice_focus` and `max_accuracy` for the noisy room; and the LLM Gateway with `strict: true` structured outputs on the one job that has no validator behind it. Two models on two time-scales for two jobs: the ASR on the millisecond path, the LLM on the turn path. **The honest risk is that a judge sees one model plus a lot of arithmetic.** The repair is that the LLM job is load-bearing (without it, 500/500 booking references interrupt the call twice and return nothing) and visible on screen, plus a demo-only in-band `llm_gateway` toggle showing both models' frames on one socket. Also load-bearing for this criterion: **we measured the model rather than assuming it** — the day-1 probe and the confusion heatmap.

**Presentation — strong, and the strength is a single UI invention.** Contested slots flicker between the *actual* competing characters at 3 Hz. Sound off, no legend, no caption, a viewer reads "the machine is torn between five and nine, at position seven" in under a second. It works in the live demo, in the video, in the still screenshot on the submission page, and in the thumbnail. Around it: the fourteen-chip collapse animating the intersection thesis with no words; the persistent counter making silence legible as a feature rather than as nothing happening; the session permalink; and a demo that is designed to land muted.

**Business Value — good, provided we are honest about what it is.** It is a feature, not a platform — a widget in the agent-assist slot every contact-centre suite already has. Saying so is stronger than pretending otherwise. **Reposition from "call centres" to channels where voice is the only channel and readback is already the protocol**: maritime and port VHF/UHF (genuinely narrowband, no SMS fallback, no DTMF, and IMO SMCP already mandates readback), aviation ground ops and dispatch, roadside and field service, pharmacy call-in, emergency dispatch. Smaller, unserved, structurally durable, and a wrong character has a body count. The asset is the `interrupt` table: *"1.2 spoken interruptions per 100 identifiers, 94% resolved in one word, median 2.1 s"* is a number no incumbent can currently produce about their own floor — sell the capture layer with an API, not the app.

**Originality — the strongest column, and "ability to demonstrate behaviors" is where it is won.** The counter-position is the pitch: *everyone else is trying to hear better; we stopped trying.* The novel components are the constrained-decoding posterior, the spelling-rhythm detector, the flicker, and the ablation toggle.

**Specifically on "ability to demonstrate behaviors" — nine behaviours a judge can *cause* on demand, in two minutes, with no setup:**

1. Make it stay silent — read a code and watch it repair position 7 without speaking.
2. Make it speak — read the one where two candidates survive.
3. Make it escalate — answer the question wrong and watch it go to NATO.
4. **Turn the acoustic model off and watch one question become three and a re-read.**
5. Break a slot by typing a wrong character and watch the candidate set re-collapse.
6. Type a container number the builder never saw and watch it validate or not.
7. Hear the 1.2 seconds of their own voice that the argument was about.
8. Watch an American and a British reading of the same part number converge into one row.
9. Turn the line down 4 dB and watch the system get chattier rather than wronger.

Every one is a *behaviour*, not a claim; every one is falsifiable on the spot; and #4 is the one that converts a sceptic, because it is the experiment they were already running in their head.

---

## 9. THE THREE BIGGEST RISKS

**Risk 1 — `words[].confidence` is block-level or flat, and the ambient product quietly stops existing.**
Under block confidence the system is still 92% correct on ISO but achieves it by asking for a span re-read on **100% of captures** — it does not fail loudly, it degrades into a re-read prompter, which is the exact behaviour the product was built to delete. Under flat confidence it writes a wrong container number silently 5% of the time, matching the checksum-blind rate exactly.
**Mitigation, three layers.** (a) Measure it on day 1, before another line is written, and measure *granularity* first — how many `Word` objects come back for "em ess kay you" — because that determines the instrument. (b) Ship the runtime regime detector (§3.7) so a wrong answer degrades the demo rather than killing the build: FLAT disables silent letter accepts, BLOCK makes span the primary escalation and NATO the prompted reading. (c) Force the token-per-character property where possible by loading the full NATO set into `keyterms_prompt` (already planned) and having the demo card prompt NATO reading — "Mike Sierra Kilo Uniform" is four words with four confidences. **Do not ship the spread-the-block-doubt fix on ISO or VIN**; 3.5% silent corruption is worse than any amount of asking.

**Risk 2 — format misclassification interrupts a correct string, on stage.**
The highest-cost event in the system, and it is triggered by a regex rather than by a mishearing. Booking references, seal numbers and airway bills all have `[A-Z]{4}\d{7}` shape and no check digit; measured, 500/500 read perfectly still produce a first decision of ASK, 99.2% end in handover, 0.8% get silently rewritten. Two interruptions and a re-read demand, about a correct string. This is the most likely funny failure in front of a room.
**Mitigation.** The second-signal rule is absolute and lives in `capture.commit`, which returns 422 without it: never assert a format from shape alone; require a carrier phrase, a registered BIC prefix, or LLM format-ID at confidence ≥ 0.8. Absent all three, capture as unvalidated free text and stay silent. Plus: after one flag, never re-flag the same string in the same session — the agent gets to say "that doesn't validate" once; twice is the deadlock. And on stage specifically, mute the upstream path for the clerk fixture, which otherwise speaks the full container number into an open mic.

**Risk 3 — a technical judge ablates it in their head and concludes you shipped a check-digit validator.**
This is the highest-probability judgement failure and it is entirely a framing problem: the measured ablation shows the confusion table contributes 0.000 accuracy. Compounded by a methodology issue — `bench.py::mishear` samples errors from the same table `rb.py::score` ranks with, so every headline number is the algorithm graded against its own beliefs.
**Mitigation, and it is free.** (a) Put the ablation *in the demo* as a toggle the judge flips (§7 beat 4) and claim the right thing: the acoustic layer buys silence, not accuracy, and silence is the product. (b) Report every headline number as a **pair** — matched table and out-of-table — which costs one benchmark column and converts the most attackable slide into the most credible one. The out-of-table arm is a good story on its own: with 100% of errors drawn from pairs the table has never seen, ISO is still 97.2% correct; it just becomes chatty. **The system fails safe: an accent it has never heard makes it talk more, never makes it wrong.** That is the answer to the accent question a judge will actually ask.

---

## 10. WHAT NOT TO BUILD

**Architecture**
- The **Voice Agent API**. No `words`, no confidence, and its whole abstraction assumes it is being addressed.
- **In-band `llm_gateway` on the always path.** Fires on every finalised turn, most of which contain no identifier, and it cannot be armed or disarmed via `UpdateConfiguration`. Demo toggle only.
- **`KeepAlive`.** In an ambient product it is the burn-credits button.
- **`format_turns=true`**, `word_boost` (deprecated, rejected by `universal-3-5-pro`), **LeMUR** (deprecated 31 Mar 2026), any N-best handling (no alternatives field exists on any model), a second TTS vendor, or any third-party API with an approval gate.
- Letting the browser hold the AssemblyAI credential. Cost gating and consent state must be server-authoritative.

**Algorithm**
- **Accent detection, accent-conditioned tables, or table blending.** Measured worth: −0.002 to +0.002. Ship one table.
- **Any fine-tuning.** There is nothing to fine-tune and no need.
- **Syndrome algebra as the primary path.** Enumerate against the validator instead: it is 140 calls on ISO, it handles Luhn and CPF and ISIN's parity fold with no special cases, and the syndrome stays available as an `O(L)` fast path if ever needed.
- The **spread-the-block-doubt** confidence hack on ISO or VIN.
- **Single-probe rhyme-class indexing.** It loses the truth 20% of the time because real confusions cross rhyme classes. Multi-probe costs ~10 extra hash lookups and recovers 97–99%.
- **Character-by-character questions to fix two errors.** It burns the budget and fails. Route to a span re-read when `effective_ambiguity > questions_remaining`.
- Silent IBAN correction without a second independent constraint (the national BBAN check digit); it silently "fixes" 4.7% of genuine data errors.

**Demo and product**
- **A credit-card / Luhn demo.** Luhn has ratio 10/10 and zero positional information — the central mechanism would visibly fail on stage; a judge should never be asked to read a card aloud; and the compliance smell follows the submission. Hard-blocklist any 13–19 digit Luhn-valid sequence at every stage, including logs and stack traces.
- **IBAN as the opener** (20+ seconds, invisible to US judges) or **VIN as the opener in Europe** (check digit is mandatory only in North America; a European judge's own VIN may legitimately fail).
- **EAN-13 / ISBN-13** anywhere — the weakest checksum in the set, blind to |a−b|=5 adjacent transpositions, and a wrong barcode carries no drama.
- Calling the clean 24 kHz stream "ground truth". It is the same model on better audio and it can be wrong; label it *"what a good headset gets — your customer doesn't have one"*, and let it fail once.
- Smoothing the latency. Perfect timing reads as animation; show the ms figure on each partial.
- Any beat that requires the judge to already know what a container number is.

**Ethics and data**
- **Voiceprints, speaker embeddings, cross-session speaker ID, sentiment analysis, or agent quality-scoring of the humans.** Never computed at all. Refusing this is a positioning asset.
- **Raw audio persistence, in any environment including dev.** Readback is not a call recorder and must never become one by accident.
- Transcript retention beyond the 45-second in-memory tape; the sentence surrounding an identifier (that is the sensitive part and it has no product value); IPs in the clear.
- **A jurisdiction toggle for consent.** A toggle is a liability generator that will be set wrong. Always all-party.
- A demo that starts listening on page load. The click is the consent event.

**Scope**
- A mobile app, offline models, languages beyond `en`, and any format with neither a checksum nor a closed set — the algorithm degenerates to "read it back and hope", so do not demo them.