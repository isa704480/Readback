All experiments run. Findings below; every number is from my own runs, not the builder's.

Scripts: `D:\temp\claude\D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762\c09d90d9-a412-4614-b967-92de40b55905\scratchpad\attack.py` and `attack2.py` (they import the builder's `rb.py`, `val.py`, `bench.py` unmodified).

---

# RED TEAM: READBACK

**Verdict up front.** The idea survives. Three things in the write-ups do not: the claim that the acoustic layer localises, the promise about letters, and the interrupt-rate arithmetic. One unmeasured API behaviour — *whether confidence is per-character or per-word* — is a live coin-flip that determines whether this is an ambient product or a re-read prompter. Nothing here is fatal to building it. Two things are fatal to how it is currently being described.

---

## ATTACK 1 — "Is the correction algorithm doing real work, or is the checksum doing all of it?"

**This is the attack that lands.** I ablated it properly: keep the checksum, keep the confidence, keep the question budget, and replace the confusion table with a uniform one (every substitution equally likely). 1 error, calibrated confidence, tuned config, N=400 each.

| format | full: silent / correct / span | **uniform table**: silent / correct / span |
|---|---|---|
| ISO 6346 | 21.2% / 99.8% / 12.0% | **0.0%** / **99.8%** / 33.2% |
| VIN | 8.5% / 98.8% / 35.8% | 2.2% / **98.8%** / 65.0% |
| NHS | 63.8% / 100.0% / 0.2% | **0.0%** / **100.0%** / 21.5% |
| IBAN-GB | 82.8% / 99.5% / 2.2% | 42.5% / **100.0%** / 21.2% |
| Luhn-16 | 19.5% / 100.0% / 2.2% | **0.0%** / **100.0%** / 0.2% |

**Correctness is identical to three decimal places. The confusion table contributes exactly zero accuracy.**

What it contributes is silence: 21 points on ISO, 64 on NHS, 40 on IBAN — and a 3× reduction in span re-reads. So the honest sentence is not "the checksum narrows, the acoustic model localises, and only the product decides." It is:

> **The checksum plus two questions plus one re-read gets you ~100% correct. That part genuinely is a fifty-line program. The confusion table's entire job is to decide when the agent can keep its mouth shut — and keeping its mouth shut is the product.**

Separating cases exist and they are worth showing:
- **Table decisive, checksum useless:** Luhn-16, mod 10 over digits, zero positional information. Full table: 100% correct, 19.5% silent. Uniform: 100% correct, 0% silent. Every bit of localisation there is acoustic.
- **Checksum decisive, table near-useless:** IBAN-GB. Uniform table still gets 42.5% silent because mod-97 usually admits exactly one repair.
- **Neither alone:** ISO 6346 letter positions (see Attack 6).

**Rating: SERIOUS — as a framing failure, not a technical one.** A judge who ablates this in their head reaches "you wrote a check-digit validator" and stops. **Cheapest mitigation, and it is free and it is good:** put the ablation *in the demo* as a toggle. One switch labelled "acoustic model: on / off". Flip it off and the same live session goes from 1 question to 3 questions and a re-read, on screen, with the counter moving. That converts the weakest part of the pitch into the Originality beat — "here is the ablation, run it yourself" — and it is the literal wording of the judging criterion ("ability to demonstrate behaviors"). It also stops you claiming accuracy you cannot attribute.

---

## ATTACK 2 — "If the API does not expose per-word confidence, how much survives?"

The grounding asked the wrong question. Flat confidence is the *easy* failure. The real one is **block confidence**: AssemblyAI emits "MSKU" as one word with one score, so four characters share one number and position→confidence alignment is gone. This is at least as likely as flat, and nobody has measured it.

ISO 6346, 1 error, N=400, four confidence shapes:

| confidence shape | silent | correct | silently wrong | span re-read | q/id |
|---|---|---|---|---|---|
| calibrated per-character | 24.5% | 99.2% | 0.0% | 13.8% | 0.69 |
| flat (0.90 everywhere) | 5.0% | 79.2% | **5.0%** | 58.0% | 1.20 |
| **block-shared** | **0.0%** | 92.0% | 0.0% | **100.0%** | 0.27 |
| anti-correlated | 0.0% | 1.5% | 0.0% | 100.0% | 1.99 |

Same pattern on IBAN (block: 0% silent, 99.2% span), Luhn (block: 0% silent, 100% span), NHS (block: 0% silent, 100% span).

**Under block confidence the ambient product ceases to exist.** It is still correct 85–100% of the time, but it achieves that by asking the human to re-read a span of the identifier on *every single capture*. That is the exact behaviour the product was built to delete. It does not fail loudly; it fails by becoming a re-read prompter.

I tested the obvious one-line fix — spread the block's doubt across its members, `conf_i = 1 − (1−c)/len(block)`:

| | naive block | spread |
|---|---|---|
| ISO 6346 | 0.0% silent, 0.0% silent-wrong, 100% span | 6.8% silent, **3.5% silent-wrong**, 40.5% span |
| VIN | 2.0% silent, 0.0% silent-wrong, 80.8% span | 11.0% silent, **4.0% silent-wrong**, 59.5% span |
| IBAN-GB | 0.0% silent, 0.0% silent-wrong, 99.0% span | **64.0% silent, 0.0% silent-wrong**, 13.2% span |

**There is no setting that gives both silence and safety on ISO/VIN.** Naive is safe and useless; spread is useful and writes a wrong container number silently 3.5% of the time. The doubt-budget guard — the single best line in the design — is precisely what forces this trade, because one low-confidence block marks four positions doubtful and the guard then correctly refuses to accept.

Note IBAN is the exception: spread gives 64% silent at 0% wrong, because mod-97 over 22 characters carries enough constraint to survive blurred confidence.

**Rating: FATAL TO THE PITCH, SURVIVABLE AS A PRODUCT.** Not fatal to correctness anywhere.

**Cheapest mitigations, in order:**
1. **Change the day-1 test.** It is not "is confidence calibrated". It is **"how many Word objects come back when someone says em-ess-kay-you"**, and it takes twenty minutes. Everything downstream branches on the answer. Run it before writing another line.
2. **Force one word per character.** Load the full NATO set into `keyterms_prompt` (you are doing this anyway) and have the demo card prompt NATO reading. "Mike Sierra Kilo Uniform" is four words with four confidences; "em ess kay you" may not be. If the token-per-character property holds under NATO and fails under letter-names, that is a product decision you can make: the capture is ambient, but the *format card* asks for NATO.
3. **If confidence turns out to be block-level, redesign the instrument, not the weights.** Make span re-read the primary escalation and drop the one-character question to a special case. The pitch becomes "it asks you to repeat four characters, once, instead of the whole number" — weaker, still real, and honest. Do not ship the spread fix on ISO/VIN; 3.5% silent corruption is worse than any amount of asking.

---

## ATTACK 3 — "Is 'letters must never be wrong' achievable?"

**No. Not on the lead format.** And the reason is structural, not statistical.

ISO 6346 assigns letter values skipping multiples of 11, so a substitution is invisible to the check digit iff the two letters are congruent mod 11. The classes:

```
{A K U}  {B L V}  {C M W}  {D N X}  {E O Y}  {F P Z}  {G Q}  {H R}  {I S}  {J T}
```

**B ↔ V is in the same class and is invisible to the check digit, always.** That is the single most confusable letter pair in world English — Spanish has no /v/, Indian English merges /v/–/w/, and "bee"/"vee" is the canonical E-set pair. The builder's own table rates B↔V at 0.45. The container check digit cannot see it, ever, at any SNR, on any accent.

Weighted by the builder's own confusion mass, per letter:

| letter | class-mates | share of its confusion mass that is check-digit-invisible |
|---|---|---|
| K | A U | **23.4%** |
| F | P Z | **19.2%** |
| V | B L | **18.0%** |
| B | L V | **15.7%** |
| X | D N | 15.2% |
| A | K U | 13.7% |
| P | F Z | 10.8% |

Aggregate over all letters: **5.9% of letter substitutions are mathematically invisible** — and that is against a table that may well *under*-weight B/V relative to reality.

End-to-end, restricting the error to the four letter positions vs the seven digit positions (N=500 each):

| error confined to | checksum-blind | silent repair | span re-read | correct |
|---|---|---|---|---|
| **letters** | 6.2% | **7.8%** | 21.0% | 99.6% |
| digits | 0.8% | **48.6%** | 3.6% | 100.0% |

Two things fall out of this that matter more than the headline.

**(a) The only defence against checksum-blind letter errors is per-character confidence.** Under flat confidence the numbers line up exactly: ISO blind 5.0%, silently wrong 5.0%; VIN blind 5.8%, silently wrong 5.8%. Every checksum-blind error becomes a silent wrong write. With calibrated confidence the doubt-budget guard catches them and converts them into a span re-read (blind 6.2%, silently wrong 0.0%). So Attack 2 and Attack 3 are the same attack: **the guard is the thing that makes letters safe, and the guard runs on a quantity nobody has measured.**

**(b) The demo's noise chain is aimed at the worst case.** A 300–3400 Hz band-pass amputates the fricative energy that distinguishes S/F/X — i.e. it preferentially breaks *letters*, which is the 7.8%-silent case, not the 48.6%-digit case. The demo's own honesty mechanism biases the demo toward its weakest beat.

**Rating: FATAL AS A PROMISE. Re-promise it.**

The promise it can keep, and should make instead:

> **"It never writes a letter it is not sure about. When it is not sure, you will know — on screen, in amber, before anything is saved."**

That is provable from the measurements (0.0% silently wrong on letters under calibrated confidence) and it is a better promise anyway, because it is about trust rather than infallibility.

**Cheapest real mitigation — a registry, and I measured how much it actually buys.** I simulated an owner-code registry (the BIC register is ~4,000 live 3-letter codes out of 17,576 possible) and asked how many registry members survive one acoustic letter error:

| registry size | mean surviving codes | unique winner |
|---|---|---|
| 2,000 | 2.38 | 24.5% |
| 4,000 | **3.86** | 7.1% |
| 8,000 | 6.76 | 0.8% |

So it prunes 26 → 3.9, but resolves uniquely only 7% of the time. **It is not a silver bullet — it turns a blind 26-way problem into a visible 4-way one, which is exactly what the question generator needs.** Two things make it much stronger in reality than in my uniform simulation: real container traffic is dominated by a few dozen owners (MSKU, MSCU, TGHU, CMAU, HLXU…), so a frequency-weighted prior is far sharper than uniform; and position 4 is a 3-element closed set {U, J, Z}. Ship the registry with usage weights. It is a CSV and an afternoon, and it covers the class the check digit provably cannot.

---

## ATTACK 4 — "What about an accent the confusion table does not cover?"

I sampled errors from confusion pairs the scorer's table does not contain, keeping the scorer's table fixed.

| condition | silent | correct | silently wrong | span |
|---|---|---|---|---|
| ISO, matched table | 21.2% | 99.8% | 0.0% | 12.0% |
| ISO, 40 novel pairs mixed in | 12.2% | 97.5% | 0.5% | 39.0% |
| ISO, **100% out-of-table errors** | **0.8%** | **97.2%** | 0.8% | 59.5% |
| VIN, 100% out-of-table | 0.5% | 92.0% | 0.5% | 80.5% |
| NHS, 100% out-of-table | 0.0% | 97.8% | 0.0% | 39.2% |

**Rating: SURVIVABLE**, and it degrades in the same shape as Attack 1 — correctness holds, silence dies, re-reads explode. The system fails safe: an accent it has never seen makes it chatty, not wrong. That is the right failure direction and it should be said out loud, because it is the answer to the accent question that a judge will actually probe.

The residual risk the builder already identified is real and my numbers confirm its shape: a *missing* pair produces a confident question about the wrong position. The failure is not silence-vs-noise, it is asking about character 3 when the error was at character 7.

**Cheapest mitigation, and it is also a demo beat:** every answered question is a labelled `(heard, truth)` sample. Update the table online, within the session, with a small pseudo-count. One dictionary write in the answer handler. It fixes the systematic accent (a Filipino speaker's /f/–/p/, a Cantonese speaker's /l/–/n/, a Spanish speaker's letter-E) after *one* question instead of never, and on screen it reads as "it learned your accent in one exchange", which is worth more in the Originality column than anything else in the build for the same cost.

Note a gap the table cannot express at all: **arity confusions**. Indian-English /v/–/w/ makes "vee" and "double-u" interchangeable, and that is a 1-slot vs 2-slot ambiguity, not a substitution. The length-repair pass only enumerates arity when the token is *lexically* ambiguous ("double u"), not when "W" was heard as "V". Add W↔V to the arity backtracking set, not the substitution table.

---

## ATTACK 5 — "The human reads out a genuinely invalid number. Deadlock."

The builder's framing is wrong about which failure this is. Deadlock does not happen — the budget terminates it. The real failure is **format misclassification**, and it is much worse.

The detector picks ISO 6346 from a `[A-Z]{4}\d{7}` shape. Booking references, seal numbers, airway bills and internal refs have that shape and no check digit. I fed 500 such strings, read *perfectly*, at high confidence:

```
first decision:  ASK  500/500  (100%)
outcome:         accepted as spoken   0.0%
                 SILENTLY REWRITTEN   0.8%
                 handover            99.2%
cost per string: 1.99 spoken questions + 95% chance of a full span re-read
```

**Every one of these interrupts the call twice, demands a re-read, and returns nothing** — about a correct string. And 0.8% of the time it silently rewrites a correct reference into a wrong one. That is the highest-cost event in the system and it is triggered by a regex, not by a mishearing.

The check digit has no check digit. Format identification is the weakest link in the chain and it is the one link with no validator behind it.

**Rating: SERIOUS, and it is the most likely source of the funny on-stage failure.**

**Cheapest mitigation:** never assert a format from shape alone. Require a second, independent signal before applying a checksum: a carrier phrase ("container number"), or the owner-code prefix present in the BIC register. Absent that, capture as **unvalidated free text** and stay silent. A string that fails the check digit *and* whose prefix is not a registered owner code is not a container number — it is something else, and the correct action is to write it down and shut up.

**And this is where the LLM Gateway belongs.** The architecture currently has it ranking candidates, off the critical path, doing work the deterministic solver already does well. Format identification from conversational context is a genuine language task, genuinely hard for a regex, off the interrupt path by nature, and it plugs the one hole with no validator. Same cost (~$0.0007/call), far more load-bearing, and it makes the "models, plural" story true instead of decorative — which matters directly for the Application of Technology score (see Attack 8).

The residual case — the caller's paperwork really is wrong — is handled adequately by the plausibility gate on ISO/NHS/Luhn (0% false silent fixes) and inadequately on IBAN (4.7%). The wording is already right: name the failure, don't insist. Do add one thing: **after one flag, never re-flag the same string in the same session.** The agent gets to say "that doesn't validate" once. Twice is the deadlock.

---

## ATTACK 6 — Ambient false positives: where it interrupts for no reason

Ranked by likelihood of a judge finding it funny.

**(a) The 700 ms silence gate fires inside a hesitation. Near-certain.** Human-human speech has intra-utterance pauses well over 700 ms, and the *canonical* place for one is mid-identifier: "MSKU four one five eight… uh…". That is exactly where `max_turn_silence` fires and exactly where the gate opens. The agent then asks about position 4 while the caller is drawing breath to say position 9. **Serious.** Mitigation is three conjuncts, all cheap: require `end_of_turn`, require the candidate to be *length-complete* for the hypothesised format, and never speak when the last token was itself a letter-name or digit-word. The 1.5 s politeness delay does not help, because the system cannot know the identifier finished — length-completeness is the only reliable signal that it did.

**(b) The demo's own clerk voice gets transcribed. Near-certain, and it is on stage.** Beat 1's scripted clerk line is *"Got it, MSKU four one five eight double oh five — booked."* The full container number, spoken by the page, through the laptop speakers, into an open mic. The architecture hard-mutes the upstream path only for the agent's own TTS (rung 3), not for the fixture audio. `speaker_labels` is off in the demo config, so the tape cannot separate them. Result: the demo captures its own clerk, re-parses the number, and either double-writes or fires a spurious question at the judge. **Serious, trivially fixable:** mute upstream for *all* page-generated audio, not just TTS. Same 150 ms tail.

**(c) The normaliser's own robustness is a capture vector.** Pass 1 maps `trouble | terrible | tremble → treble`. In IDLE, ordinary conversation containing "trouble" now emits a ×3 multiplier. Same for "not/knot → 0" and "and → N". **Survivable, one-line fix:** apply the multiplier and connective expansions only in the ARMED state. Never in IDLE.

**(d) Rhythm detector on non-identifiers.** Counting, a phone number, a postcode, a date read as digits ("two oh two six, oh nine, oh one"), a spelled surname, "yeah yeah yeah yeah", an IVR menu, hold music with a beat. Most of these are caught by the ≥2-of-4 rule and none of them reach rung 3, because rung 3 requires a *checksum failure* and these have no checksum. **Survivable.** The residue is FP-capture, not FP-interrupt — which is the cheaper of the two.

**(e) A non-container of container shape.** Attack 5. **This is the one that actually interrupts.**

---

## ATTACK 7 — The interrupt-rate arithmetic does not close

The architecture claims rung shares of ~90% silent write / ~7% amber / ~2% earcon / **~1% speak**, and proposes the pitch metric "1.2 spoken interruptions per 100 identifiers captured."

That is inconsistent with the algorithm's own measurements. If per-identifier probability of at least one acoustic error is *p*, and the measured conditional silent rate on ISO 6346 is 24.4%, then:

```
spoken question share  =  p × 0.70
```

At the demo's own channel — 300–3400 Hz, 11 dB SNR — a per-character error rate of 2–5% over 11 characters gives *p* ≈ 0.20–0.43. **That is a spoken question on 14–30% of identifiers, not 1%.** To reach 1% you need *p* ≈ 1.4%, i.e. a per-character error rate around 0.13%, which is a clean headset in a quiet room — the condition the pitch explicitly says does not exist.

**Rating: SERIOUS.** It is the number the whole business case rests on, it is in the `interrupt` table as "the product's own proof", and the two documents disagree by a factor of 20.

**Cheapest mitigation:** state it as a function, not a constant. *"On a clean line it never speaks. At 11 dB narrowband it asks about one character in roughly one call in five, and the alternative is the agent asking about the whole number in five calls in five."* That is defensible, it is measured, and it is still a good pitch — the comparison class is not silence, it is the "can you spell that" the call has today.

Related: the demo doc asserts silent repair is **"64% of real single mishears on this format."** My measurement is **24.4%** overall (48.6% for digit errors, 7.8% for letter errors). The 64% figure is not supported anywhere in the algorithm work and should be removed before a judge computes it.

---

## ATTACK 8 — Methodology: the benchmark is graded on its own prior

`bench.py::mishear` corrupts characters by sampling from `W`. `rb.py::score` ranks candidates using `W`. **The evaluation samples errors from exactly the distribution the scorer assumes.** Every headline number in the algorithm write-up — 100% correct, 0% silently wrong — is an upper bound obtained under the assumption that the confusion table is correct, and the table is explicitly "a set of priors, not measurements."

To the builder's credit, breaking that loop (Attack 4) shows the degradation is graceful. But the numbers as written are not measurements of the algorithm; they are measurements of the algorithm against its own beliefs, and a judge with an ML background will see it in thirty seconds.

**Rating: SERIOUS as presentation, survivable as engineering.** **Cheapest mitigation:** report every headline number as a pair — matched table and out-of-table — the way I have above. It costs one extra benchmark column and it converts the most attackable slide into the most credible one.

---

## ATTACK 9 — "Is this a product or a feature?"

**It is a feature.** Be honest about it, because pretending otherwise is what will lose the Business Value column, not admitting it.

It is a post-processing layer over a real-time transcript. Genesys, Five9, NICE, Talkdesk and Amazon Connect all already have real-time STT and an agent-assist surface with a widget slot. This drops into that slot. There is no defensible moat in the ~2,000 lines; the moat, such as it is, is the validator/registry corpus and the confusion table, and both are copyable in a week by anyone who watches the demo.

Worse for the TAM: **in most of the named verticals the identifier is not spoken any more.** Container numbers move by EDI and email. Policy numbers get captured by IVR DTMF. Banks send a link. VINs get photographed. The moment this product serves — a human reading a long identifier aloud to another human over a degraded channel — is shrinking, and the shrinkage is being driven by exactly the pain this product addresses.

**Rating: SERIOUS for the business score. Not fatal, and there is a good answer.**

The strongest answer is to name the segment where the alternative channels do not exist:
- **Maritime and port VHF/UHF radio.** Genuinely narrowband, genuinely voice-only, no SMS fallback, no DTMF, and readback is *already a mandated protocol*. The product name becomes literal.
- **Aviation ground ops, dispatch, roadside, field service** — same property.
- **Pharmacy call-in and emergency dispatch** — voice-only by regulation or by urgency.

Reposition from "call centres" (large, addressable, already served, and migrating away from voice) to "channels where voice is the only channel and readback is already the protocol" (smaller, unserved, structurally durable, and where a wrong character has a body count). That is a better Originality story too.

Second answer, for the same slide: sell it as a **capture layer with an API**, not an app. The `interrupt` table is the asset — "1.2 spoken interruptions per 100 identifiers" is a number no incumbent can currently produce about their own floor.

---

## ATTACK 10 — "Would a judge understand what a container number is?"

Mostly no, and the demo currently does not tell them. Beat 0 opens on a six-slot rack reading `OOLU 4 0` with the caption *"Three of those sounds are identical."* That explains the *puzzle* and never explains the *object*. A judge spends the first fifteen seconds — the fifteen seconds the whole design is built around — working out what they are looking at.

`OOLU` is real (OOCL), so the asset is fine. The framing is not.

**Rating: SURVIVABLE, cheapest fix in the document.** One line above the rack, before the puzzle: *"This is a shipping container number. One wrong character sends forty tons to the wrong continent."* Ten words, and it recruits the stakes before the mechanism, which is the same instinct as the alternate video opener the demo doc already prefers.

Second, smaller point: ISO 6346 is the *least* relatable of the six formats. Every judge has personally read a booking reference or a postcode aloud to a stranger and been misheard. Beat 5 gets to that at 1:30, which is too late to do any work. Move one relatable format — a flight booking reference is ideal, six alphanumerics, closed-set, no checksum — into the first thirty seconds. It also demonstrates the *second* constraint engine early, which is the "models, plural" argument the judging rubric rewards.

---

## THREE SMALLER HITS

**The clean stream argues against the product.** Beat 1 runs clean 24 kHz beside phone-line and calls the clean stream ground truth. It is not ground truth — it is the same model on better audio, and it can be wrong. Worse, when it is right and the phone stream is wrong, the demo's own visual argument is *"just use a better microphone."* Mitigation: label it "what a good headset gets" and add one line — the customer's end never has one — and let the clean stream *also* fail once, at beat 2. A demo where both streams fail and the constraint layer still wins is a much stronger demo.

**The dual socket doubles the cost model.** §4 prices a 150 s demo at $0.025 on one socket. Beats 1–2 run two sockets in parallel, so it is $0.05, and the free-credit headroom halves from ~2,000 sessions to ~1,000. Survivable, but the gating thresholds and the daily-budget kill switch are computed from the wrong number.

**Application-of-Technology risk.** The core of this system is deterministic Python. The ASR is one model; the LLM Gateway is deliberately kept off the critical path and might never fire in a two-minute demo. A judge reading the rubric's "how well the chosen MODELS — plural — are integrated" could reasonably score this as one model plus a lot of arithmetic. Attack 5's mitigation fixes this properly: give the LLM the format-identification job, which is a real language task, on a real hole, visible on screen, off the interrupt path.

---

## IF YOU CHANGE FIVE THINGS THIS WEEK

1. **Measure token granularity before anything else.** Not calibration — *granularity*. How many Word objects come back for "em ess kay you". Twenty minutes, and the answer determines whether the escalation instrument is a character question or a span re-read. Everything else is downstream.
2. **Stop claiming the acoustic layer buys accuracy. Claim it buys silence, and put the ablation toggle in the demo.** The uniform-table arm is 40 lines and it is your best Originality beat.
3. **Re-promise the letters.** "It never writes a letter it is not sure about" — provable, better, and survives B↔V being invisible to the check digit forever. Ship the frequency-weighted BIC owner registry as the letter constraint; the check digit is not one.
4. **Require a second signal before asserting a format.** Carrier phrase or registered prefix. Otherwise capture unvalidated and stay silent. This is the single change that prevents the on-stage failure, and it is where the LLM Gateway earns its place.
5. **Fix the interrupt-rate number in the pitch** to `p × 0.70`, and mute the upstream path for the clerk fixture before anyone stands in front of a room with it.