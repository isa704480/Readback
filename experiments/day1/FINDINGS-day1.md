# Day 1, part one — what the socket actually does

Measured on this machine against a live `universal-3-5-pro` session, not read out
of a document. `probe.py` produced all of it; `probe-results.json` holds the raw
frames. No microphone was involved — every case sends 0.6 s of digital silence.

---

## 0. The run failed the first time, and the failure is worth keeping

Cases were opened back to back. Cases 6–18 all returned:

```
1008  "Unauthorized Connection: Too many concurrent sessions"
```

Read quickly, that is thirteen parameters being rejected. It is nothing of the
kind — the account allows only a few concurrent sessions and the server counts a
socket as live for a moment after it closes. Every one of those thirteen results
was thrown away and the run repeated with a 6 s gap between cases, at which point
eleven of them connected cleanly.

Recorded because the first table was *confident and wrong*, and looked exactly
like a table of real findings.

---

## 1. `Begin` carries a `configuration` echo — and it is only a partial one

```json
{"type":"Begin","id":...,"expires_at":...,
 "configuration":{"api_version":"2025-05-12","domain":null,"filter_profanity":false,
                  "mode":"balanced","model":"universal-3-5-pro","redact_pii":false,
                  "speaker_labels":false,"voice_focus":null}}
```

This is not in `server/stream/live.py` and should be: it is the server stating
what it believes the session is set to, and it is the only ground truth available
without measuring behaviour.

**But it lists eight fields, not the whole surface.** `max_turn_silence`,
`min_turn_silence`, `vad_threshold`, `keyterms_prompt` and `prompt` never appear
in it, even though the API reference documents all five as supported. So:

> A parameter missing from the echo has **not** been shown to be ignored.
> The echo is decisive only for the eight fields it contains.

That correction matters, because the first reading of this data said the echo
settled the `end_of_turn_confidence_threshold` question. It does not — see §3.

## 2. The control: unknown parameter names are dropped silently

`readback_not_a_real_parameter=1` connects cleanly, no error, echo unchanged.

Therefore **"it connected" is worth nothing** as evidence that a parameter is
supported. Every conclusion below either rests on the echo (for the eight fields
it covers) or on an explicit error frame.

## 3. `end_of_turn_confidence_threshold` and `format_turns` — still open, and the
   code is betting on them

| | |
|---|---|
| API reference | "Universal Streaming (English and Multilingual) only" — i.e. **not** this model |
| Socket | accepts both without error — but so does an invented name |
| Echo | neither appears — but neither does `max_turn_silence`, which *is* supported |

**Not resolved by this probe.** The docs say unsupported; the socket cannot
confirm it. The deciding test is behavioural and needs speech — does
`format_turns=false` actually stop the final turn being formatted? That is
question (C) in `listen.py`.

What the project is currently betting on it:

- `server/pipeline/detector.py` pushes `end_of_turn_confidence_threshold` on
  every ARM and IDLE transition (0.70 → 0.50), and the comment justifies the
  whole ARMED design on that lever existing.
- `server/stream/live.py` sets `FORMAT_TURNS = False` with the comment
  *"Formatting collapses 'fifteen' and 'one five'"* — the normaliser depends on
  getting the spelled form.

If the reference is right, the first is a no-op write on every state change and
the second is a switch connected to nothing, which would mean **finals arrive
formatted and the tape has to be built from partials**. That is a real
architectural change, so it waits for the measurement rather than a doc quote.

## 4. `mode` is real, and this system has never sent it

| sent | echo |
|---|---|
| nothing | `"mode":"balanced"` |
| `mode=max_accuracy` | `"mode":"max_accuracy"` |
| `mode=min_latency` | `"mode":"min_latency"` |

`balanced` is the default. The reference calls `mode` the primary latency /
accuracy control and says it sets the turn-detection defaults server-side.

**`mode` is not in the `UpdateConfiguration` updatable list**, so it is
connect-time only. That constrains the ARM/IDLE machine: it cannot switch mode
mid-session, and whatever it does to endpointing has to go through
`max_turn_silence` / `min_turn_silence` / `vad_threshold` / `keyterms_prompt` /
`prompt`.

## 5. `keyterms_prompt` — both questions in TODO(day1-02) answered

**Encoding.** A JSON array inside one query parameter is correct; the repeated
form is rejected:

```
3006  "User Input Validation Error: Invalid 'keyterms_prompt': Value error, Invalid JSON array"
```

`_encode_keyterms()` in `live.py` already does the right thing.

**The ceiling.** 120 terms:

```
3006  "User Input Validation Error: Invalid 'keyterms_prompt': Value error, Max 100 items"
```

The TODO asked whether exceeding the cap is "an error frame rather than a socket
close". **It is both** — an `Error` frame *and* the socket closes. That is worse
than either alone, and `detector.py`'s ARM path sits deliberately against that
ceiling. `MAX_KEYTERMS = 100` is now a hard requirement: one term over and the
session dies mid-call.

No per-term character limit was reported. `MAX_KEYTERM_CHARS = 50` in
`detector.py` is unverified and may be inherited from a different model — worth
one probe of its own.

## 6. Frame shapes confirmed

| TODO | Answer |
|---|---|
| day1-08 `Termination` | `{type, audio_duration_seconds, session_duration_seconds}` — the two fields the billing code reads |
| day1-10 error frame | `{type:"Error", error_code:<int>, error:"<message>"}`, followed by a close with the same code |
| day1-06 `UpdateConfiguration` | accepted mid-session, **no acknowledgement frame**. The ARM swap cannot be confirmed from the socket; treat it as advisory |
| day1-09 `Heartbeat` | not observed — sessions were 0.6 s, so this proves nothing |

## 7. Limits and echoed fields (`probe2.py`)

Asked only where an answer would be *proof*: the four echoed fields, and the
documented caps where a real cap produces an error frame.

**The `prompt` cap is exactly 1750 and precisely enforced.** 1700 characters
connect; 1900 give

```
3006  "Invalid 'prompt': Value error, prompt exceeds maximum length of 1750 characters (got 1900)"
```

**There is no per-keyterm character limit.** 60-character and 200-character terms
were both accepted without complaint. `MAX_KEYTERM_CHARS = 50` in
`detector.py` is therefore **not a server rule** — it is our own policy, and
`keyterms()` currently drops any term longer than 50 characters for a reason that
does not exist. The 100-*item* cap is real and fatal; the character cap is not.
Worth keeping as a budget heuristic, but the comment calling it a hard limit
should stop saying so.

**Exactly 100 keyterms is accepted.** The boundary is inclusive: ≤100 fine,
101 kills the session. `detector.py` sitting against 100 by design is safe.

**Three of the four echoed fields reach the session and are confirmed working:**

| sent | echoed back |
|---|---|
| `voice_focus=near-field` | `{"voice_focus": "near-field"}` |
| `domain=medical-v1` | `{"domain": "medical-v1"}` |
| `filter_profanity=true` | `{"filter_profanity": true}` |

`voice_focus` is the interesting one: `server/config.py`'s cost model already
prices it in — *"universal-3-5-pro 0.45 + voice_focus 0.10 + prompting 0.05 =
$0.60/hr"* — while `live.py` has never sent it. The budget assumes a feature the
socket is not being asked for. Either send it or re-derive the cost.

`speaker_labels` was lost to a concurrency close on this run and remains
unmeasured.

## 8. LLM Gateway is not the second signal, and the measurement is emphatic

ARCHITECTURE 3.8 allows a format to be asserted on an "LLM format-ID at >= 0.8".
`server/llm.py` implements it; `experiments/day1/llm_probe.py` measures whether it
earns the gate. It does not, and the way it fails is worse than a low score.

**Access first.** Of the ~30 model ids in the catalogue, this account can reach
exactly one:

```
qwen3.5-4b-32k-fast      200 OK
everything else          400 "Your account does not have access to this LLM Gateway model"
```

and that one refuses structured output — `400 "model qwen3.5-4b-32k-fast does not
support response_format"` — although the docs list its provider family as
supporting it. So the JSON is asked for in the prompt and parsed defensively.
One probe row came back truncated mid-object and was refused rather than
salvaged, which is the intended behaviour: no verdict beats a guessed one.

**It is good where shape is visible.** 6 of 6 on the lexically distinctive
formats: ISO 6346 0.85–0.95, IBAN 1.00, VIN 0.95, NHS-with-a-carrier-phrase 0.90.

**It is anti-correlated where it was needed.** Bare digit runs are the entire
reason a second signal exists, because shape and rhythm cannot tell ten digits of
a phone number from ten digits of a patient number:

| spoken | truth | verdict | conf |
|---|---|---|---|
| `7700900123` — 10-digit window of a UK mobile | not an identifier | **`nhs`** | **0.90** |
| `2026090114` — a date and a time run together | not an identifier | **`nhs`** | **0.80** |
| `9434765919` — a **real** NHS number | `nhs` | **`not_an_identifier`** | 0.70 |

Read the model's own reasons: the phone-number window *"matches the UK NHS
patient number format"*; the genuine patient number is *"likely a phone number"*.
It did not score 70% on this discrimination — it got it **backwards**. A
component that confidently labels a phone number as a patient number above the
assert gate is worse than an absent one, because absent already has a defined
behaviour (ask the human) and this one writes it down.

**Latency kills it independently.** 1.1–1.5 s warm, and 32–33 s on the rows that
hit the rate limiter — the account returns `429 "too many requests for this
action"` after about two calls. A per-turn call on a live phone line is not
available on this key at any quality.

**Encoded, not just noted.** `BARE_DIGIT_FORMATS = {"nhs", "luhn16"}` in
`server/llm.py`, and `FormatID.asserts` returns False for them whatever the
confidence. The measurement is in the comment beside it so the next person to
widen the set knows what to re-run first. LLM format-ID stays available for
ISO 6346, IBAN and VIN, where it is genuinely good — and off the live path
entirely would be better still.

**Consequence for the false-capture work.** The detector fix has to close the
phone-number hole structurally, on its own. There is no second signal coming to
rescue it for the bare-digit formats.

## 9. The load-bearing question, answered: characters do not arrive one per word

`live.py` TODO(day1-04) called this THE measurement — "Does 'em ess kay you'
come back as four Word objects, one, or a single word? Everything downstream
branches on it." It has now returned, twice, against the real
`universal-3-5-pro` socket. Audio was Windows System.Speech TTS at 16 kHz, so
this proves plumbing and token SHAPE, not human-voice accuracy.

**Run 1 — letter names** (`"container number M S K U four one five eight zero zero five"`):

```
[11] eot=True  fmt=True  n=3   Container(0.89) number(0.80) RMSKU4158005.(0.80)
```

Twelve frames, `turn_is_formatted: true` on every one of them — partials
included. The identifier arrived as ONE token with ONE confidence. The best
partial had zero single-character words. `format_turns=false` is sent and
ignored (section 3); there is no unformatted path on this model.

**Run 2 — NATO words** (`"... Mike Sierra Kilo Uniform, four one five eight zero zero five"`):

```
[ 3] eot=False n=1   コンテイナーナンバーR二七Rキロユニフォーム。(0.65)
[11] eot=True  n=7   Container(0.80) number(0.67) RMI(0.31) KCR(0.51) kilo(0.69) uniform(0.98) 4158005.(0.95)
```

Two partials came back in **Japanese**: the model's native code-switching,
with no `language_code` pinned, on a synthetic voice. `kilo` and `uniform`
survived as words; `Mike Sierra` did not; the digit run was again one token.

**What survives both runs and is safe to build on:**

- Per-word `confidence` exists, on partials too (`word_is_final` present).
- A spoken digit sequence is welded into one token — `4158005` (0.95–0.99),
  `RMSKU4158005` (0.80). Per-digit confidence from the recogniser does not exist
  for this input.
- Every frame is formatted. The tape's rank order `partial < final-unformatted
  < final-formatted` (tape.py) assumed a middle tier that never arrives.
- `normalise._one()` had no branch for a glued alphanumeric token and returned
  only the first digit of a digit run ("caller should splice the rest" — no
  caller did). Measured: `'Container number RMSKU4158005.'` normalised to
  **0 cells**; the NATO transcript to **3** (`KU4`). No capture could commit.

**What does NOT survive the TTS caveat:** the Japanese code-switch and the
`Mike Sierra → RMI KCR` collapse are almost certainly artefacts of a synthetic
voice and must not be read as "NATO spelling fails". A human reading NATO into
`experiments/day1/listen.py` is the only instrument for that, and it has still
not been run.

**The fix, argued from the robust half:** `normalise.tokenise()` now splits a
code-shaped token — any run of letters and digits containing at least one
digit — into single characters. It is the one function every consumer of a
transcript passes through (detector, normaliser, runner, arity), so the split
reaches all of them. Letters-only tokens are left whole: they are words, and
the NATO/LETTER tables already read them. Each split character inherits the
token's confidence downstream, which is exactly the "flat" regime
`RegimeDetector` names — except that with `REGIME_MIN_WORDS = 40` it will not
fire on a single identifier, and the decider therefore treats the regime as
unmeasured rather than flat. That is a known, documented gap and the next
thing to look at now that the probe it was waiting for has run.

**The fix was not enough, and the event stream said why.** With `tokenise()`
splitting, the WAV was driven through the browser's own path
(`experiments/day1/e2e_live.py`: consent, `/live`, `/audio`, `Terminate`).
Result: `state.armed` on the carrier at 2.1 s, `format: iso6346`,
`cues: ["carrier"]`, `commit_ok: false`, `session.end captures: 0`. The shape
cue never fired. `detector._runs()` decides whether a word joins a run by
asking `_one()` about the WHOLE word -- `_one("rmsku4158005")` is None by
contract -- so the welded word never entered a run and `_normalised_chars`
was never called on it. `_readable()` now asks the question of the word as
the normaliser will read it: `tokenise()` first, readable iff every piece is.
Offline, on the three real words: run `RMSKU4158005`, shape `iso6346` at
edit distance 0, cues `{carrier, shape}`, `commit_n = 2`, in both states.
The 74 existing tests -- the false-positive fixtures among them -- still pass.
Pinned in `tests/test_normalise_glued.py`.

**A second gap the same run exposed: `PIPELINE_DRAIN_S = 5.0` is a bet.**
On the next attempt upstream took 11.4 s to send `Begin` (3.1 s an hour
earlier) and transcripts lagged so far that when `Terminate` went up after
9.6 s of audio the tape held 4.4 s of it. The pipeline waited five seconds
for the last turn, was cancelled, and the identifier -- spoken, sent, and
almost certainly transcribed a moment later -- was lost with
`end_reason = "user"`. The right number is the measured `Terminate ->
Termination` latency under lag, not five; the driver now prints it.

**Third gap, the worst, and now closed: `terminate()` closed the socket in
the same breath as sending Terminate.** The server answers Terminate by
flushing the audio it still holds into a last Turn, then `Termination`, then
a close -- `listen.py` saw all three on every run -- and `LiveSource` was
hanging up before any of it arrived. Through the browser path that looked
like `error "SourceClosed"`, `session.end reason="error"`, `billed_seconds
0.0`, and the last turn of the call -- the one the caller pressed stop
after, i.e. the identifier -- gone. `terminate()` now waits for the reader
to see `Termination` (bounded by `TERMINATE_FLUSH_S = 10 s`, sized to the
7-11 s upstream lag measured the same afternoon) and only then closes.
Measured after the fix, upstream responsive: flush **1.5 s**, `session.end
reason="complete"`, `billed_seconds 9.0` from the `Termination` frame
(audio 9.63 s). Four unit tests in `tests/test_live_terminate.py` pin the
order `Terminate -> Turn -> Termination -> close`, billing from the frame,
the bound on a server that never answers, and idempotence. day1-12 is
answered.

**Recommendation for the live path, from run 2:** pin `language_code=en`.
The agent listens in English only (measured and stated in the UI); leaving
the model free to code-switch bought nothing and cost two Japanese partials.

## 9. What is still open

- **(C) formatting** — the one that could move architecture. Needs speech.
- **(A) day1-04** — are spelled characters separate `Word` objects? Needs speech.
- **(B) day1-05** — is `confidence` on partial-turn words? Needs speech.
- **(D)** the confidence AUC that `tests/test_solver_regression.py` is waiting for
  to replace its invented model. Needs speech, and several readings.
- whether `MAX_KEYTERM_CHARS = 50` is a real limit.

`listen.py` covers the first four. It needs somebody to read container numbers
into a microphone.
