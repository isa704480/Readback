# Findings from porting the solver

Work done after the design workflow, while moving the verified modules into
this repo. Everything here was measured on this machine; nothing is inherited
from the spec unchecked.

---

## 1. The validators are correct. One of my test vectors was not.

`MSKU6111119` failed `iso_ok`. I had written that vector from memory. Computing
the ISO 6346 check digit independently — letter values skipping multiples of 11,
weights `2^i`, sum mod 11 mod 10 — gives **5**, not 9. `MSKU6111115` validates.

Cross-checked the ported validator against an independent implementation over
2,000 randomly generated bodies: **0 disagreements**.

Published vectors that pass: `CSQU3054383`, `GB82WEST12345698765432`,
`4539578763621486` (Luhn), `9434765919` (NHS), `1HGBH41JXMN109186` (VIN).

## 2. The guardhole fix is applied, and it was a real bug

`ask_pos` was `argmax_i H(marginal_i)` unconditionally. Marginal entropy measures
disagreement *among surviving candidates*, so it is identically zero when exactly
one candidate survives — which is the case the doubt guard fires on. An
implementation reading "no entropy to gain" as "nothing to ask" falls through to
a silent accept.

`tests/bench/guardhole.py` quantifies what that costs an argmax-entropy
implementation:

| | guard fires with zero entropy | of those, written wrong and silently |
|---|---|---|
| IBAN-GB p=0.10 | 28.9% of identifiers | 17.4% |
| IBAN-GB p=0.15 | 19.3% | **41.8%** |

Now split into two instruments:

```python
unexplained = doubtful - edited
if unexplained:  ask where the posterior most distrusts what was heard  # detection
else:            ask where candidates disagree most                     # disambiguation
```

## 3. Parameters set from the sweeps

`FLOOR` 0.01 → **0.004**, `DOUBT_T` 0.25 → **0.40**. The second matters most:
at ISO p=0.02 it takes silence from 20.2% to **63.6%** and questions per
identifier from 1.26 to **0.45**, at +0.0005 silent error. Silence is the
product.

---

## 4. New: only 5.3% of acoustic error is invisible to the check digit

This was not in the spec and it changes what we can honestly promise.

ISO 6346 sums `value(c) · 2^i mod 11`, so characters congruent mod 11 are
**mathematically invisible** to the check digit. The classes are perfectly
regular:

```
{A K U} {1 B L V} {2 C M W} {3 D N X} {4 E O Y}
{5 F P Z} {6 G Q} {7 H R} {8 I S} {9 J T}
```

The obvious worry is that this is fatal — a whole class of errors the checksum
declares valid. Measured against the acoustic confusion table, it is not:

| | |
|---|---|
| Confusable pairs (weight > 0.02) | 170 |
| Falling inside a blind class | 12 (7.1%) |
| **Share of confusion weight that is blind** | **5.3%** |

The pairs that matter acoustically are almost all visible:

| Visible to the check digit | weight | Blind | weight |
|---|---|---|---|
| O ↔ 0 | 0.95 | B ↔ V | 0.45 |
| C ↔ Z | 0.80 | K ↔ A | 0.30 |
| B ↔ D | 0.75 | F ↔ P | 0.30 |
| M ↔ N | 0.72 | 3 ↔ D | 0.20 |
| 8 ↔ A | 0.65 | N ↔ X | 0.15 |

**Twelve pairs is small enough to close by hand**, and that is now
`blind_alternatives()` in `solver.py`: a doubtful position whose heard character
has a confusable neighbour in its own residue class is asked about, always,
because the checksum will never object to it. Silence there would not be
confidence — it would be arithmetic that cannot see.

This turns the concession into a claim worth making out loud — but the claim has
to carry the word *doubtful*, which an earlier draft of this section and of the
README both dropped:

> The agent knows the twelve substitutions its own arithmetic is blind to, and
> asks about any of them it has the slightest acoustic doubt about.

**Not "every time", and the difference is measured.** `blind_alternatives` is
consulted at doubtful positions only. Making it unconditional was tried and
rejected on the numbers: 67% of valid ISO 6346 codes contain at least one
blind-capable position (mean 0.93 of 11), so an unconditional rule asks about two
container numbers in three. Sweeping the blind-position doubt threshold on
N=3000, ISO, p=0.05, correct answers:

| blind threshold | silent | silently wrong | extra questions/id |
|---|---|---|---|
| off — doubtful only (shipped) | **0.201** | 0.0017 | 0.000 |
| 0.20 | 0.119 | 0.0007 | 0.229 |
| 0.00 — ask always | 0.068 | 0.0003 | 0.347 |

Two thirds of the silence for 0.0014 of silent error is the same trade the
`DOUBT_T` sweep in §3 already rejected in the other direction. Shipped as is.

The residue is real and is §5's subject: a blind substitution the recogniser was
*confident* about has no signal anywhere in the system — not in the arithmetic,
which cannot see it, and not in the confidence, which did not flag it.

---

## 5. Correction: "silently wrong = 0" is not a reachable contract

The spec states silently-wrong reaches 0.000 in every cell after the guardhole
fix. Reproducing that end to end with the question loop closed, it does not —
not because the fix failed, but because the two claims measure different things.

`tests/bench/bench.py` computes its failure rate over `seen = n - blind`, i.e.
**excluding** the errors the checksum cannot see. That is the right denominator
for judging the *solver*. It is the wrong one for judging the *product*: a blind
substitution is a wrong number written in silence, whatever the arithmetic
thinks.

`tests/test_solver_regression.py` counts them, and asserts a **bound** rather
than zero. With the blind guard in place it currently measures 0.0000 across
ISO / IBAN / NHS / Luhn at p=0.05–0.10, N=600, but earlier seeds produced 1–4
cases in 600. Treat it as small and bounded, not zero.

**The bound is provisional.** The confidence model in that test is invented —
`uniform(0.35, 0.80)` where wrong, `uniform(0.55, 0.99)` where right. The real
number depends on how well `words[].confidence` separates correct from incorrect
characters on real audio, which is exactly the day-1 experiment and cannot be
measured without an API key. Tighten `MAX_SILENT_WRONG` once that AUC exists.

---

## 6. New: two carrier phrases were ordinary English, and opened the commit gate

Found by running the fixtures end to end, not by reading the code.

`conversation_no_identifier.json` is the false-positive corpus: 124 s of
shipping-desk talk with no identifier in it. On it the detector reached
`commit_ok` **three times**. Nothing was captured, but only because the shape cue
happened to find no run — the gate itself was open.

The cause was two entries in `CARRIERS`:

| phrase | what the conversation actually said |
|---|---|
| `booking` | "which reference, the booking or the customs one" — twice |
| `container is` | never fired here, same class: "the container is late" |

The carrier cue is justified in its own docstring by precision — *"nobody says
'container number' by accident"* — which is true of `container number` and false
of `booking`. And carrier is the only cue that also **names the format**
(`fmt = carrier[1]`), so a false one does not just add a vote, it asserts
`booking_ref` about a conversation.

Paired with rhythm, which fires 3 times in that fixture, 2-of-4 was standing on
one cue. That is the same collapse the module docstring warns about for cue (b)
counting letter-runs, arrived at from the other side.

Removed. Measured on the same fixture:

| | arms | of those, `commit_ok` | format asserted |
|---|---|---|---|
| before | 4 | **3** | `booking_ref` |
| after | 2 | **0** | none |

Neither remaining arm is a defect: both are rhythm-only, which is invisible and
reversible by design, and the topic-change rule disarms both within 7–9 s.
Recall cost is zero measured — `booking` and `container is` appear in no
identifier fixture, and the two-word forms `booking reference` and
`container number` survive.

`tests/test_detector_falsepos.py` holds it shut, with two assertions of different
kinds: no carrier phrase may match the conversation corpus (a precision contract
on a hand-written table, enforceable because a person chooses the phrases), and
the corpus must never reach `commit_ok` (the end-to-end property the first one
protects).

### What was deliberately NOT changed

The rhythm cue fires on 3 of 332 windows of pure conversation. Tightening
`CV_IOI_MAX` from 0.35 to 0.15 clears all three and keeps all four identifier
fixtures firing, which looks like a free win and is not one:

| | cv range |
|---|---|
| dictation windows (4 fixtures, 44 firing) | 0.083 – 0.336 |
| conversation false windows (3) | 0.167 – 0.336 |

**The distributions overlap.** The false window at cv=0.167 sits inside the
dictation range, and 6 of 9 windows in each ISO fixture are above 0.15. A
threshold at 0.15 would be fitted to one sample of one conversation and would
start dropping real dictation the moment the sample changed.

The honest statement is that cv_ioi does not separate dictation from
conversation on its own — which is the reason the design has four cues and
requires two, and the reason rhythm alone is only ever allowed to arm.

---

## 7. The shape cue was a length detector, and 2-of-4 was 1-of-1 on digits

Found by asking §6's question on the other axis. §6 removed two carrier phrases
because they were ordinary English and made cue (a) fire on conversation. The
same collapse exists between cue (c) and cue (d), it is total rather than
partial, and the corpus could not see it: five fixtures, and not one of them
contained a run of digits that was not an identifier.

### The measurement

`NHS.A(i)` is `0123456789` at all ten positions and `LUHN16.A(i)` is the same at
all sixteen, so `shape_cue`'s mismatch count is identically zero for **any** ten
or sixteen consecutive digits, at every offset, for every digit value. 300
uniform random all-digit runs per length, read at a fixed 350 ms:

| run length | 6 | 7 | 8 | 9 | 10 | 11 … 19 |
|---|---|---|---|---|---|---|
| shape cue fires | 0/300 | 0/300 | 0/300 | 0/300 | **300/300** | **300/300** |

The cue is not reporting the content of the run. It is reporting its length,
which is a property of the same words cue (c) timed. And it is not only the
bare-digit formats: at length 17, 131 of 300 random **digit** runs come back as
`vin`, because VIN's alphabet is uniform and holds every digit.

8,000 generated non-identifier utterances — twenty categories drawn from the
red team's own list, 400 each, spoken form and cadence sampled:

| | before | after |
|---|---|---|
| rhythm fires | 0.9890 | 0.9890 |
| shape fires | 0.7070 | 0.7070 |
| carrier fires | 0.0000 | 0.0000 |
| spelling fires | 0.0000 | 0.0000 |
| **reaches the COMMIT gate** | **0.7070** | **0.0000** |
| carries a window a real check digit accepts | 0.1782 | 0.1782 |
| **both** | **0.1782** | **0.0000** |

Every one of those 5,656 commits was rhythm+shape and nothing else. The last row
is the one that matters, and it is arithmetic rather than luck: `nhs_ok` accepts
182,040/2,000,000 = **0.0910** of random ten-digit strings (analytic 10/11 × 1/10
= 0.0909) and `luhn_ok` 49,866/500,000 = **0.0997** of random sixteen-digit
strings. An eleven-digit UK mobile offers two ten-digit windows, so 34,941 of
200,000 generated ones = **17.5%** contain a window the NHS check digit accepts.
Roughly one spoken UK phone number in six is a valid patient number by every test
this system had.

### What changed

Four edits, each of them a rule the design already states.

**1. Cue independence, enforced (`detector.py`).** The module docstring says
*"2-of-4 is only worth 2-of-4 if the cues fail independently"* and then guards
exactly one case. `shape_is_evidence(fmt, window)` now asks the exact question —
*could this mask have rejected this window?* — by taking the characters the
window actually contains and computing the most positions any arrangement of them
could get wrong, which is a maximum bipartite matching on the illegal
(character, position) pairs. If that maximum is within `SHAPE_MAX_DIST`, no
rearrangement could have failed, the match restates the run length, and rhythm
and shape are counted **once**. `commit_cues` is that count; `cues` is untouched,
so **ARM is untouched** — one cue still arms, and arming is invisible and
reversible.

Derived from `Fmt.A(i)`, never from a literal `{"nhs", "luhn16"}`: a hard-coded
set would drift, and it would also miss seventeen digits matching VIN.

**2. §3.6's write gate, wired (`runner.py`).** `verdict.commit_ok` was computed
and read by nothing — `grep commit_ok server/pipeline/runner.py` returned two
hits and both were event payloads. The capture row was opened on
ARMED-plus-shape, i.e. one cue plus a cue that fires on any ten digits, and
`st.open_capture` is a write: it persists `heard_value` and puts an amber row on
the rack. §3.6 says `≥2 of 4` *"before anything is written or spoken"*. It is now
the condition.

**3. §3.8, on the word "alone" (`runner.py`).** Three of the twenty-one carrier
phrases name no format — `it reads`, `reads as`, `spelled` — and
`_second_signal` accepted `carrier_fmt in (None, window.fmt_name)`, so any of
them satisfied the second-signal rule for every format. When the format came from
a shape hit that could not have failed its mask, that is still *asserting a
format from shape alone*: "it reads" does not know it is an NHS number either.
For those hits the carrier must now name the format.

**4. The "X for Y" frame (`detector.py`), found by building a fixture.** The head
of a frame was tested with `len(tokens[i - 1]) <= 2`, a proxy for "is a
character" that is not one. `date_range_welded` opens with *"what window did they
give us for the collection"* — `us` is two characters long, so the frame fired
and the SPELLING cue voted on a sentence about a collection window: 16 commit_ok
observations on a fixture with no identifier in it. Head and tail are now both
checked against the normaliser — the head must read as one character and Y must
name it, by starting with it ("B for Bravo", "S as in Sugar") or by reading as it
("four, as in four"). The same defect as the main one, one cue over: standing on
a proxy for the evidence rather than on the evidence.

### The three fixtures that should have existed

`conversation_no_identifier` is 126 s of talk whose longest readable run is far
short of ten characters, so the cue that fires on any ten digits never had the
chance. Three negatives close that, all carrier-free on purpose — a carrier is an
independent cue and §3.6 is entitled to open on carrier+rhythm:

| fixture | commit_ok before | after | rows before | after | what was persisted |
|---|---|---|---|---|---|
| `phone_number_in_conversation` | 17 | **0** | 1 | **0** | `0776773992` as `nhs` |
| `meter_reading_sixteen_digits` | 14 | **0** | 1 | **0** | `8737983960106896` as `luhn16` |
| `date_range_welded` | 16 | **0** | 1 | **0** | `0109208092` as `nhs` |

`tests/test_detector_falsepos.py` gains assertion **C** — a non-identifier
fixture may not open a capture row either — which is a contract on the runner
where B is a contract on the detector, different in kind for the same reason A
and B are. It also gains a `test_` function: `pytest -q` was not collecting that
file at all, so the false-positive contract was written down, was runnable by
hand, and was not run by the suite everything else is gated on. That is most of
why a defect this size lived behind it. 35 tests before, 36 after.

### The recall cost, plainly

The four shipped fixtures are unchanged at both gates: `commit_ok` 10/10/13/10
observations as before, `collapsed` 0 on all four — the repair never touches
them — and end to end three commit while `iso_blind_substitution` stays
`unverified`, which it also did before this change, for an unrelated reason.

Generated genuine identifiers, 200 each, through the real `run_session`:

| | before | after |
|---|---|---|
| NHS + "nhs number" | 200 committed | 200 |
| NHS + "patient number" | 200 | 200 |
| card + "card number" | 200 | 200 |
| VIN in NATO + "vin" | 200 | 200 |
| VIN in letter-names + "chassis number" | 200 | 200 |
| NHS carrier-free | 0 committed, 200 rows | 0 committed, **0 rows** |
| **NHS + "it reads"** | **200 committed** | **0** |
| **VIN in letter-names, carrier-free** | **200 committed** | **0** |

Two real losses, and neither is hidden. A genuine NHS number introduced only by
"it reads" no longer commits: that is edit 3, and it is a trade rather than a bug
fix — "it reads" is in the table precisely to catch the case where nobody names
the format, and removing it for shape-only hypotheses prefers a missed patient
number over a captured phone number. A VIN read in letter-names with no carrier
no longer commits either: it used to reach the commit gate on rhythm+shape and
then find its second signal in the registered `1HG` prefix. In NATO — which is
how a seventeen-character code is actually read over a phone — it still commits,
200/200, on rhythm+spelling.

Neither loss has a fixture behind it, and that is the honest limit of these
numbers: every recall figure here for a non-ISO format comes from generated
reads, not from recorded audio. One real NHS, one real card and one real VIN
fixture would be worth more than another 200,000 draws.

### What did not work

**A negative phone-number grammar, rejected on the overlap — measured first, per
§6.** Rejecting digit strings a phone grammar recognises before the shape cue may
fire looks free against the shipped corpus, because all four identifier fixtures
are ISO 6346 and it costs them nothing. Measured over 200,000 generated
check-digit-valid NHS numbers, **128,018 = 64.0%** match the North American
grammar `[2-9]dd[2-9]dddddd`, and only 10.0% begin with the `0` that would exempt
them. In the other direction 9.2% of NANP numbers pass `nhs_ok` outright and
17.5% of UK mobiles contain a valid window. The two populations are not separable
by digit grammar: the guard would discard two genuine NHS numbers in three to
remove one false capture in eleven. **No negative guard was added.** This is §6's
failure mode verbatim, and reporting it is the finding.

**Requiring the shape hit's own check digit before shape may count.** The
best-looking number available and worth nothing. On the same 8,000-utterance
corpus it takes the COMMIT rate from 0.7070 to **0.1785**, a 74.7% reduction that
would read very well in a summary — and the share of utterances that commit
*carrying a check-digit-valid window* goes 0.1782 → **0.1782**, a reduction of
**0.0000**. It removes precisely the false captures that were already harmless
and keeps every single one that mattered, because the check digit is what defines
the dangerous population.

**No rhythm constant was touched.** `CV_IOI_MAX`, `SHORT_MS`, `IOI_MIN_MS`,
`IOI_MAX_MS`, `SHORT_RATIO_MIN`, `RHYTHM_MIN_TOKENS`, `NATO_MIN`, `NATO_SPAN`,
`SHAPE_MAX_DIST` and `COMMIT_MIN_CUES` are all unchanged. Rhythm fires on 0.9890
of these non-identifiers and that is not a defect: reading digits aloud *is*
metronomic, the distributions overlap (§6), and the separable quantity was never
the cadence.

### What is still open

**A receptionist asking for an NHS number, answered with a phone number, is not
closable by this design and was not closed.** 200 UK mobiles read after the words
"nhs number": **18 committed before, 18 after.** Carrier format and shape format
agree, the second signal is genuine, and one number in six passes the check
digit. Nothing in the system separates a ten-digit phone from a ten-digit NHS
number once a human has said the words. The only instruments that could are
§3.8's two unwired legs — the LLM format-ID call, and a prefix registry that is
empty for `nhs`, `luhn16`, `catalogue` and `booking_ref`, so four formats of
seven have the carrier as the only second signal they can ever have.

**A format-agnostic carrier still opens a row, and should.** "it reads" plus a
phone number is carrier+rhythm, two genuinely independent cues, so §3.6's gate is
open and §3.8's answer is *capture as unvalidated free text and stay silent* —
200/200 now end `unverified` with 0 committed, where 20/200 ("it reads") and
12/200 ("spelled") committed silently at rung 0 before. The row is the design
working. That it holds a caller's telephone number under `format_type="nhs"` sits
badly against DESIGN-BRIEF's *"the conversation around an identifier is never
persisted"*, and resolving that is a decision about §3.8, not a bug to fix here.

**VIN has no lexical surface either, and nobody had said so.** Its alphabet is
uniform and 33 of 36 characters, so a genuine VIN's shape hit is a length test
exactly like an NHS number's: `max_illegal` is 0 on `1HGBH41JXMN109186`. The
repair treats it correctly, and edit 3's second recall loss is the consequence. A
per-position VIN alphabet — position 8 is the check digit, positions 0-2 the WMI
— would restore some discrimination and is not written here.

---

## 8. What this means for the pitch

Do not promise "letters are never wrong." Promise this instead, all of it
measured:

- A checksum plus two questions plus one re-read reaches ~100% correct. That
  part is fifty lines and anyone could write it.
- The acoustic model's entire job is deciding **when the agent can stay quiet** —
  worth 21 points of silence on ISO, 64 on NHS, and zero accuracy. Silence is
  the product, because an agent that asks about every identifier is the
  "can you spell that" this exists to delete.
- The error-rate budget is identical across all eight accents tested to within
  14%, and constraint multiplies it by 15×. Accents differ in ASR error rate by
  at most 2×.
- Knowing which accent is worth **nothing** (±0.002). Ship one table, build no
  accent detection.
- 5.3% of acoustic error is invisible to the check digit, in twelve known pairs.
  At those positions the agent asks on the slightest doubt, because there is no
  arithmetic to back the confidence up — and it says out loud that a *confident*
  mishearing inside a residue class is written silently, because nothing in the
  system can see it. That residue is bounded and measured, not zero.
