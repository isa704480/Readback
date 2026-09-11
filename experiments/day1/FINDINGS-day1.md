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

**Fourth: the prefix arrives as its own capitalised token, and "SKU" is a
carrier phrase.** With the last turn now surviving, `e2e_live.py --dump`
showed the pipeline's own view of the same WAV. During the partials the ISO
rack filled with digits only -- `4 1 5`, then `4 1 5 8 0 0 5`, from slot 0
-- so the recogniser was emitting the letter prefix as a separate,
letters-only token (`RMSKU`) that the digit-only split rule left whole and
`_one()` could not read. Then the final arrived and the event stream said
`format hypothesis -> catalogue`, `cues: ["carrier"]`. The carrier regex is
word-bounded, so the final must have carried `SKU` as a word of its own
(`RM SKU 4158005`), and "last carrier wins" let a three-letter phrase
spelled from inside the identifier overrule the "container number" said
six seconds earlier. MSKU is Maersk's prefix; it is on a large share of the
containers in the world, and this would have happened on most of them.

The formatter capitalises what it takes for spelled letters and nothing
else, so the signal is capitals -- but only touching digits.
`normalise.dissolve_spelled_caps()` turns a run of all-caps letters-only
tokens adjacent to a digit-bearing token into single letters (`RM SKU
4158005` -> `R M S K U 4158005`) before the text is lowercased;
`tokenise()` and `carrier_cue()` both apply it, so the dissolved "SKU" is
not a phrase anywhere, while "the SKU is 4158005" -- capitals not touching
the digits -- keeps its carrier. `RMI KCR kilo uniform` is untouched: two
words from the digits. The judgement needs the neighbours, so it is made
over the word SEQUENCE (`spelled_caps_mask`) in the detector's run builder
and in the runner's per-word token merge alike -- asked of "RM" alone it is
just an unreadable word, which is exactly how the first attempt failed its
own test.

**Measured through the browser path, both fixes live, same WAV:**

```
[4575 ms] capture.update   rack=MSKU4158___                       (partials)
[5885 ms] candidate.seen   MSKU4158005  complete  checksum_ok  aligned  second_signal=carrier
[6198 ms] capture.commit   value=MSKU4158005  heard=MSKU4158005
[6198 ms] state.idle       identifier settled
          session.end      reason=complete  captures=1  silent=1  billed_seconds=9.0
```

The first identifier this system has ever captured from live audio. Four
defects stood between the fixtures and that line, none of them visible from
a fixture, all of them visible from one measured session: the welded word,
the per-word readability test, the socket closed before its last turn, and
the capitalised prefix beside the digits. 85 tests; the false-positive
fixtures unchanged throughout.

**Fifth, argued from the first four rather than observed failing: the regime
was "unknown" at the moment it mattered.** Every split character inherits its
word's one confidence, so a welded reading is ARCH 3.7's BLOCK regime by
construction -- `wpc = 1/12`, far under `REGIME_BLOCK_WPC = 0.6`. But the
session-wide `RegimeDetector` needs 40 words, a short live call never gives
it that many before the first identifier, and the decider treats "unknown"
as per-character: the one regime in which a silent repair is allowed. A
welded reading with a bad checksum would have been silently edited by
prior alone -- twelve cells, one number, so "the doubt is at position 7" is
a sentence the data cannot support -- which is the 5.0% silently-wrong that
3.7 measured and the detector exists to prevent. `align_run()` already
knows how many cells each recogniser word produced; four or more from one
word (`BLOCK_CELLS_PER_WORD`; "treble four" is the per-character maximum at
three) flags the window, and `candidate_regime()` hands the decider BLOCK
for that candidate whatever the statistic says. A checksum-clean reading
still commits silently -- the live run did -- and a repair now becomes a
span re-read instead of a guess. Six tests in `tests/test_block_regime.py`.
The 40-word statistic stays as it was: it is still the right instrument for
a long call, and nothing here re-tunes it.

**Sixth, found by reading while wiring the vocabulary pack, not by
measurement: the CONNECT frame of a live session carried no keyterms.**
`session_audio` opened the socket with `SourceConfig(keyterms=())`, while
the Detector seeds its "already pushed" state with the IDLE configuration on
the assumption that CONNECT carried it (detector.py, `_pushed`) and only
pushes an `UpdateConfiguration` when the state changes. So the whole IDLE
phase of every live session -- the carrier phrases and the NATO alphabet
that let the detector notice a code at all -- ran with nothing biasing the
recogniser; the first keyterms the socket ever saw arrived with the ARM.
`_connect_config()` now builds CONNECT from the detector's own IDLE payload,
the organisation's vocabulary included, so the seed and the wire agree. The
effect on recognition is not measured and is not claimed; the two live
captures above were made under the old behaviour, which is a lower bound.

**Seventh: a route-by-route audit of the API, adversarially verified.** Five
readers, one per route family, then three independent refuters per finding;
19 findings survived all three, 0 were refuted. Closed the same day:

- `POST /api/session/{id}/answer` and `WS /api/session/{id}/live` had no
  caller resolution at all -- any holder of a session id (returned by `/start`,
  in every URL) could read another tenant's captures and questions off the
  stream and answer its pending question, deciding what gets written. Both now
  resolve the caller the way the audio socket does and call a foreign session
  "unknown". A test pins owner / rival / anonymous on each.
- `/audio` never re-checked admission: an idle admission older than cap +
  grace is dropped from the concurrency count, so a socket attaching to it
  later ran outside every gate. Re-checked at attach, budget included.
- `speed=NaN` and an unbounded `answer_timeout_ms` on replay could wedge a
  pipeline slot or hold a request open indefinitely: bounded at the schema.
  Replay itself had no rate gate: per-address, 120 an hour.
- Rate limits keyed on the LEFTMOST `X-Forwarded-For` entry -- the one the
  client writes -- so every per-IP limit was bypassable by header: rightmost.
- The placeholder session secret was refused only when an AssemblyAI key was
  also present, so a replay-only deployment on Postgres issued forgeable
  tokens: refused on any non-SQLite database.
- PBKDF2 (600k iterations, ~220 ms) ran inside `async` sign-in handlers,
  stalling the single worker's loop for everyone: threadpool.
- A non-ASCII bearer token raised instead of returning None -- a 500 on every
  authenticated route: one None for every way a token is wrong.
- `StartRequest.channel` reached a CHECK constraint as a free string (500 at
  commit): a Literal at the edge (422).
- The shared demo tenant listed anonymous LIVE sessions to any anonymous
  reader; the record and the summaries now show the anonymous only replayed
  fixtures, which are fictional by construction.

Left as they are, on purpose, and recorded: `optional_user` degrading an
unusable token to anonymous is a documented, tested design decision
(attribution, never access) -- its harmful consequence is the listing above,
now closed; the per-email login limit counting attempts before verification
(a known 15-minute lockout trade-off); `consent.version` unbounded at the
edge (low).

**Eighth: the repair itself never wrote a wrong number; the checksum's blind
spot did, and only under block-level confidence.** The field study named the
risk -- "a single check-digit repair can yield multiple candidate corrections
(ambiguity, transposition) without a confidence tiebreaker" -- so it was
measured (`bench_silent_wrong.py`, 400 valid ISO 6346 numbers per row,
corruptions drawn from the solver's own confusion table; offline and
synthetic, not live STT):

```
kind             regime       n  silent_ok  silent_wrong  not_silent  heard_passes
substitution     per_char   400    82   20%     1   0.2%   317   79%     23   5.8%
substitution     flat       400     0    0%    13   3.2%   387   97%     13   3.2%
transposition    per_char   400     0    0%     0   0.0%   400  100%     16   4.0%
transposition    flat       400     0    0%    15   3.8%   385   96%     15   3.8%
double_subst     per_char   400     0    0%     0   0.0%   400  100%     44  11.0%
double_subst     flat       400     0    0%    48  12.0%   352   88%     48  12.0%
```

In every flat row `silent_wrong` equals `heard_passes`: the solver never
repaired to a wrong candidate -- 0 of 800 transposed and doubly-corrupted
readings under either regime -- it only accepted a corrupted string that
already satisfied the check digit, which no check-digit system can see. Under
per-character confidence the blind-pair guard caught 22 of those 23
(BLIND_GUARD needs a doubtful position to point at); under flat confidence
it cannot point, and 13 of 400 single mishears, 15 of 400 transpositions and
48 of 400 double errors were written as heard. The account copy that said
"Readback asks about all twelve every time" was true of the first regime and
false of the second, which is the common one on the live socket; it now says
what was measured. The residual is the arithmetic's, stated, not the
repair's.

**Ninth: dependencies.** `pip-audit` on the pinned `requirements.txt` found
starlette 0.41.3 carrying nine published advisories (PYSEC-2026-161, -248,
-249, -1941, -1942, -2280, -2281); fastapi 0.115.6 pinned it. Upgraded to
fastapi 0.141.1 / starlette 1.6.0 with the full suite green; `npm audit`
on the web build reports none. A second adversarially-verified audit round
(web client, transport, secrets and logs, abuse, supply chain) and a
loop-until-dry bug hunt were launched and ran out of session budget before
any agent returned; neither produced findings, which is not the same as
"none", and both are queued to run again.

**Tenth: a second audit round and a bug hunt, and what they cost.** Five
readers over the web client, transport, secrets, abuse and supply chain, and
eight over the pipeline modules; both ran out of session budget before their
verifiers did, so the 41 candidates were re-verified afterwards by three
independent refuters each. 23 stood, 6 were refuted -- three of those six
because they had already been fixed while the verifiers were reading.

Two of the confirmed findings were regressions from the round before, both in
the same commit that scoped the sockets: the browser opened `/live` with no
token subprotocol, so a signed-in operator's viewer was told "unknown session"
about their own call while the audio socket streamed on; and `/live` took
`Depends(get_db)`, whose connection is held for the life of the handler --
which is the life of the socket. A viewer left open pinned a pooled connection
for the whole call.

Seven silent defects in the reading path: a code ending in "?" normalised to
nothing (only "." was a separator); a hyphenated code lost its letters (the
mask ran before hyphens became separators); "X for Y" collapsed three tokens
into one invented character; "double u" matched inside "double uniform"; a
format's own name beside the digits was dissolved into letters, deleting the
carrier phrase and lengthening the run; "eh" read as the letter A while the
detector called it a hesitation; and the tape evicted a turn for having
STARTED long ago, throwing away the identifier still being read.

A card number the database refuses to keep (`store.mask_pan`) was handed back
in clear by the retained event history and the replay summary, which are built
from the runner's own records. The stop button did not stop a session that was
asking, because the answerer swallowed the task's own cancellation. ARCH
3.12's auto-purge was documented as implemented and did not exist; it does
now, with one audit row per sweep. `ip_hash` keyed on the leftmost
X-Forwarded-For entry, so the admission gate moved with a header. The SPA had
no CSP and shipped full source maps; the API sent no security headers; a 422
echoed the submitted password back.

**What this cost, stated:** the starlette upgrade that closed nine advisories
also appears to have made two websocket tests flaky -- they pass alone and in
their own file every time, and fail roughly one full-suite run in five, with a
traceback entirely inside `starlette/testclient.py`'s `__exit__` and no
Readback frame but the `with` line. Clearing the module-global `_SESSIONS` in
the new fixtures removed one real cause; the residual was not confirmed
against the old version because installing the vulnerable release to A/B it is
blocked, correctly. It is a harness race, not a product one, and it is
recorded here rather than hidden.

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
