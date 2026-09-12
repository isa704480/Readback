# Submission package

Everything that goes into the lablab.ai form, plus the video script and the
path a judge walks in sixty seconds. Deadline: **30 September 2026, 20:00
Tashkent** (8:00 PM UST on the event page).

Every number below is measured and named in `docs/EXPERIMENT.md` or
`docs/FINDINGS.md`. Nothing here may be edited to a rounder figure.

---

## 1. Title

**Readback — the reference number it refuses to get wrong**

Fallback, if a shorter field is needed: **Readback**

## 2. Short description (the card, ~240 characters)

> A voice agent that writes reference numbers down correctly — not by hearing
> better, but by knowing what a valid answer is allowed to be. It repairs most
> mishearings in silence, and when it cannot, it asks about one character.

## 3. Long description (the submission body)

> Every logistics desk, insurance line and bank support team burns the same two
> seconds a hundred times a day: *"can you spell that"*, *"was that B for Bravo
> or D for Delta"*, *"fifteen or fifty"*. One wrong character sends a container
> to the wrong port or bounces a payment. In noise, `5`/`9`, `M`/`N` and
> fifteen/fifty are genuinely ambiguous, and speech-to-text alone cannot fix
> it, because the information is not in the audio.
>
> It is in the format. A container number carries an ISO 6346 check digit; an
> IBAN carries mod-97; a card carries Luhn. The constraint does not make the
> recogniser hear better — it multiplies the error rate the system can absorb.
> Measured across 8 accents and ~12M simulated captures, with the solver never
> told which accent it was hearing: the error budget goes from 0.0047 to 0.0692
> on ISO 6346 (**14.9×**) and from 0.0023 to 0.0399 on IBAN-GB (**17.1×**),
> and it holds to within 14% across every accent. Accents differ in recogniser
> error rate by at most 2×, so a 15× budget absorbs that with an order of
> magnitude spare. That is why the answer here is not fine-tuning, and why
> there is no accent detection anywhere in the system.
>
> What the caller experiences: two thirds of the time a mishearing is repaired
> in silence and the diff appears on screen. When the arithmetic cannot settle
> it, the agent interrupts once, for about two seconds, and asks about exactly
> one character — in NATO, so the answer arrives in a different acoustic space
> than the one that just failed. Silence is the product: an agent that asks
> about every identifier is the "can you spell that" this exists to delete.
>
> Built on AssemblyAI Universal Streaming (`universal-3-5-pro`). Per-word
> confidence is the likelihood in the posterior; the format is a hard 0/1
> prior. A four-cue detector notices a code while it is still being spoken and
> arms the socket mid-stream with `UpdateConfiguration` inside the documented
> 100-keyterm budget, then `ForceEndpoint` claws back the raised
> `max_turn_silence` the moment the candidate is length-complete. The LLM
> Gateway supplies a third second-signal for windows with no carrier phrase,
> gated by a measured refusal on the formats where the model is
> anti-correlated.
>
> What it does not promise: "letters are never wrong". ISO 6346 sums
> `value(c)·2^i mod 11`, so characters congruent mod 11 are mathematically
> invisible to the check digit — 5.3% of measured confusion weight lands
> there, in twelve known pairs, and that residue is written silently. The bound
> is the promise, not zero.
>
> Runnable evidence: eight recorded sessions replay through the same runner the
> microphone uses, with no API key and no account — four that contain a
> container number, four that must stay silent. Every fixture runs at both
> clocks, instant and real-time, because a gate that is a condition on time
> passing is not tested by a replay that fast-forwards. 156 tests. MIT.

## 4. Tags

Category: **Voice Assistant**, **Business**, **Logistics**
Technology: AssemblyAI Universal Streaming, AssemblyAI LLM Gateway, FastAPI,
React, TypeScript, SQLite/Postgres, Claude Code

## 5. The video, 2:30

Judges said in the 2024 recap that they preferred a live demo to a polished
presentation. So: no title cards, no slides until the last ten seconds.

| time | on screen | said |
|---|---|---|
| 0:00–0:12 | A container number read aloud over traffic noise. The rack fills character by character, one letter visibly wrong, then corrects itself. No question asked. | "This is a container number being read out on a noisy line. The system just wrote it down. It never asked me to repeat anything — and it corrected a letter I actually got wrong." |
| 0:12–0:35 | Split screen: the raw transcript on the left, the written record on the right. The transcript says `MSAU4158005`; the record says `MSKU4158005`, with the diff highlighted. | "The recogniser heard A where I said K. A system that trusts the transcript writes a container that belongs to a different shipping line. This one doesn't, and the reason is not a better model." |
| 0:35–1:05 | The Formats screen. ISO 6346 arithmetic animates: letter values, weights `2^i`, sum mod 11. The check digit lights up. | "A container number carries its own check digit. So does an IBAN, and a card number. The constraint doesn't make the microphone better — it multiplies the error rate the system can absorb. Across eight accents and twelve million simulated captures: fifteen times on ISO, seventeen on IBAN." |
| 1:05–1:35 | A second call. This time the agent speaks once: *"position four — Kilo or Alfa?"*. The answer arrives, the rack commits. | "When the arithmetic can't settle it, it interrupts once and asks about one character — in NATO, so the answer comes back in a different acoustic space than the one that just failed. Two seconds, once, instead of spelling eleven characters back." |
| 1:35–2:00 | The Sessions screen: a session that wrote nothing, opened to show why. Then the blind-pair panel. | "It also says what it cannot do. Five point three percent of acoustic error is invisible to the ISO check digit — twelve known pairs — and inside those, a confident mishearing is written silently. That's measured, and it's in the README." |
| 2:00–2:20 | Terminal: `pytest -q` → 156 passed. Then the demo screen replaying a fixture with no key. | "Eight recorded sessions replay through the same code the microphone uses, with no API key. Every one runs at both clocks, because a politeness delay isn't tested by a replay that fast-forwards." |
| 2:20–2:30 | One frame: the five formats, and the industries that read them aloud. | "Container numbers, IBANs, policy numbers, patient numbers, booking references. Anywhere a human reads a code to another human over a phone." |

Recording rules: real audio, real latency, no sped-up footage. If a take needs
a second attempt because the agent asked a question, keep the take — the
question is the product working.

## 6. The sixty-second judge path

A judge with no account, no key and no patience:

1. Open the deployed app → **Demo**. Press the `container` fixture. The rack
   fills, one character repairs silently, the diff shows.
2. Press the `silent` fixture. Nothing is written, and the session detail says
   why in words.
3. Open **Formats** → type a container number with one character changed into
   "try one". It refuses, and names the check digit.
4. Open the repo → `docs/FINDINGS.md` §9. The bug we found in our own code
   after reading a rival's write-up, and the test that locks it.

## 7. Which judge sees what

The panel is 29 people: five from AssemblyAI, one from the organiser, and
engineers and directors from AmEx, Prudential, Zocdoc, Meta, Amazon, Qdrant and
fintech infrastructure. Nobody gets a different product — but the first thing
they should see differs, and the demo path above is ordered so each finds theirs
inside a minute.

| judge | what they work on | the thing to put in front of them |
|---|---|---|
| Luka Chkhetiani, Head of Realtime | streaming ASR, turn-taking, reliability, evaluation | The ~12M-capture harness, the accent spread (≤14%), and `UpdateConfiguration`/`ForceEndpoint` arming inside the 100-keyterm budget |
| Dylan Fox, CEO | real-world applications over public benchmarks; last-mile production problems | FINDINGS: the keyterms independence bug, the politeness-delay bug found by running both clocks, the blind-pair residue |
| Dan Ince, PM Voice Agent API | what the API makes possible | Honest framing: this is the Streaming path plus a constraint layer, and why a booking-agent shape could not do this job |
| Craig Bruder, forward deployed | deployments that survive customers | Multi-tenant orgs, budget ceiling, consent gate, retention and purge |
| Harnoor Singh, DevRel | demos that work and read clearly | The no-key fixture replay and the README's first screen |
| Neeraj Kumar Singh Beshane, staff security infra (fintech), zero-trust and agent-security papers | audit trails, governance, policy-as-code | The append-only event stream, org scoping, PAN masking, purge job, `docs/RED-TEAM.md` |
| Kumar Shivendu, Qdrant core | chaos testing, continuous benchmarking, observability | `tests/bench/`, the mutation arm, both-clocks discipline |
| Anil Mandloi, AmEx | payments | Luhn, and why there is deliberately no credit-card *localiser* (10/10 detects, never localises) |
| Bhargavi Vepuri, Prudential | insurance technology | Policy and claim references: the format-as-constraint argument with no code change |
| Mallika Rao, Zocdoc | patient-facing scheduling | NHS number, and the handover rather than a guess |
| Andrea Marazzi, organiser, ex-Amadeus airline distribution | commercial value in travel/booking | The booking reference format, and cost per avoided re-read |
| Nicole Hao, Janet AI | conversation → structured record | Every field links to the moment it was said and agreed |
| Amit Kumar Singh, data platform | metadata, data quality, governance | `validated_by` / `second_signal` provenance on every row |
| Vasu Raj Jain (Amazon Ads), Vipul Jain (Meta), Sriharsha Makineni (Meta) | scale and measurement | The error-budget table, and that silence — not accuracy — is the metric |
| Sanem Avcil | story and visuals | The 0:12–0:35 split screen: transcript versus record |

## 8. Before submitting

- [ ] **Deploy.** `docs/DEPLOY.md` is written and unrun: Render for the API,
      Vercel for `web/`. Needs a human with the accounts and the AssemblyAI
      key. Without a URL, half of the path above does not exist for a judge.
- [ ] Create the lablab team and project page; paste §1–§4.
- [ ] Record the video against the deployed app, not localhost.
- [ ] Cover image: the split screen from 0:12.
- [ ] Check the repo is public and MIT, and that `README.md` figures match
      `docs/FINDINGS.md`.
