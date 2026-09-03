# Readback — design brief

Hand this to a designer, or paste it into a design tool. It deliberately does
**not** specify colours, typefaces or a visual style. Those are yours to choose;
what follows is what the product is, who is looking at it, and the constraints
any solution has to survive.

---

## 1. What the product is

Readback listens in the background of a phone call and writes down reference
numbers — shipping container numbers, IBANs, vehicle VINs, patient numbers, card
numbers — correctly.

It does not transcribe the call. It does not summarise it. It waits, silent,
until it hears somebody start reading out a code, and then it writes that code
down. Most of the time it fixes what it misheard without saying anything. When
it cannot, it interrupts the conversation **once**, to ask about **one
character**, and then goes quiet again.

The one line for the top of the page:

> Readback writes reference numbers down correctly — not by hearing better, but
> by knowing what a valid answer is allowed to be.

## 2. The idea a viewer has to arrive at in ten seconds

Speech recognition mishears `B` as `D`, `5` as `9`, `M` as `N`. Nothing fixes
that acoustically; the information is not in the audio.

But a container number carries a check digit. An IBAN carries mod-97. A card
carries Luhn. **The format knows things the microphone does not.** So Readback
does not try to hear better — it works out which of the things it might have
heard is a legal answer, and usually there is only one.

Measured across eight accents: constraining the answer this way multiplies the
error rate the system can absorb by **15×**, while accents differ in recognition
error rate by at most **2×**. That is why there is no accent training and no
accent detection.

## 3. Who is looking at it, and when

Three audiences, and they are not the same person.

**The hackathon judge.** Alone, at a laptop, thirty-ninth submission of the
evening, decides in twenty seconds whether to keep watching. Owes us nothing.
Does not know what a container number is and should not have to.

**The agent operator.** Wearing a headset, on a live call with a customer who is
talking. Is *not looking at the screen* — they are listening to a person. The
interface has to be readable in the fraction of a second they glance down, and
it must never demand attention the call needs.

**The team leader.** Afterwards, at a desk, looking at what was captured and how
often the agent had to interrupt.

Design for the operator. The judge is served by making the operator's view
legible to a stranger; the team leader's view is a separate, calmer screen.

## 4. The screens

### 4.1 The rack — the main screen, and the one that matters

An identifier being captured, character by character, live.

Each character is a slot. A slot can be:

- **empty** — not heard yet
- **provisional** — heard, may still change; the recogniser revises partials
  constantly and the display must show that honestly rather than pretending to a
  certainty it does not have
- **settled** — final, and the system believes it
- **repaired** — the system silently changed what it heard, and the viewer must
  be able to see both what was heard and what it became
- **asked about** — the one character the agent is currently querying
- **locked** — the human answered; it will not change again

Six states is a lot for one component, and collapsing any of them loses
something real. The hardest pair is *provisional* versus *settled*: partials
flicker as the recogniser revises, and that flicker is the most honest thing on
the screen. Do not smooth it away.

Alongside the rack: which format it thinks this is, and how confident it is that
it is a format at all.

### 4.2 The silence indicator

The product's central claim is that the agent **stays quiet**. That is invisible
by construction, and a screen that shows nothing looks broken.

Something has to make "it is listening, it has understood, and it has decided
not to speak" a visible, positive state. Not a spinner. Not a waveform — every
voice product has a waveform and none of them mean anything. This is the single
hardest thing in the brief and the most valuable if you solve it.

### 4.3 The question

When the agent does speak, it asks about exactly one character:

> *"I have five characters then a four — was that four-seven, or four-eleven?"*

On screen this needs: which position, what the alternatives are, and what the
agent will do if nobody answers. It has to be answerable by voice without
looking, and by tapping if the operator prefers.

### 4.4 The record

What was captured this session: the identifiers, whether each was silent or
asked about, and how long it took. The team-leader view. Calm, scannable,
exportable.

### 4.5 The demo entry

A judge arrives at a link and has no call to listen to. Something has to give
them the experience in one click — a recorded exchange playing through the real
pipeline, or their own microphone with a number on screen to read out. This
screen has one job: get a stranger from arrival to understanding in under twenty
seconds.

## 5. Constraints — these are not negotiable

**Accessibility.** Every foreground/background pair at 4.5:1 or better, measured
rather than eyeballed. Every interactive target at least 44×44px. Colour is
never the only carrier of meaning — the six slot states must be distinguishable
in greyscale and by a screen reader. Respect `prefers-reduced-motion`;
the flicker in 4.1 is meaningful, so give it a still equivalent rather than
removing the information.

**No horizontal scroll at 375px.** Verified, not assumed.

**Icons are vector, from one family.** No emoji.

**Motion carries meaning or does not exist.** 150–300ms, transform and opacity
only. The flicker of a mutating partial is meaning; a decorative pulse is not.

**Nothing on screen may be fake.** Every number displayed comes from the
pipeline. If something is simulated for the demo it says so, on screen.

## 6. What the interface must never do

- **Show a transcript of the call.** Readback captures identifiers; it is not a
  recorder, and the architecture deliberately never persists the conversation.
  An interface that displays one contradicts the product and creates a privacy
  problem the backend was built to avoid.
- **Show a confidence percentage.** Meaningless to an operator and an invitation
  to argue with the machine. The system's uncertainty is expressed by *asking*.
- **Claim certainty it does not have.** About 5% of realistic mishearings are
  invisible to the check digit — twelve known character pairs. The agent asks
  about those every time, and the interface should make that visible as
  diligence rather than hide it as doubt.
- **Interrupt visually while the agent is silent.** No toasts, no badges, no
  attention-seeking during a live call. Silence is the product; the screen must
  observe it too.

## 7. Colour, type and style — open, with one requirement

Choose freely. The only requirement is that the choice be **argued from the
product**, not from a trend: this is an instrument that sits beside a working
person during a phone call, it is looked at in glances, and its most important
state is *nothing is wrong*.

Two notes that may or may not be useful:

- Nearly every voice-AI product on the market looks the same — dark, purple or
  cyan, a glowing orb, a waveform. Looking like a piece of professional
  equipment rather than a consumer AI toy is available and nobody is taking it.
- The palette has to express three ideas cleanly: *heard but not settled*,
  *quietly repaired*, and *I need one thing from you*. If the colours cannot
  carry those three, nothing else about them matters.

## 8. What to deliver

1. The rack, in all six slot states.
2. The silence indicator (§4.2) — the hardest problem here.
3. The question moment (§4.3).
4. The demo entry screen (§4.5).
5. The record (§4.4), lower priority.
6. Tokens: colour with measured contrast ratios, type scale, spacing scale,
   motion durations.

Mobile-first at 375px, then a desktop layout. Light or dark is your call —
argue it from §3, the operator on a call, and remember they may be in a bright
office or a dim night-shift room.

## 9. Context, if you want it

- `README.md` — what it is and the measured numbers
- `docs/FINDINGS.md` — the checksum-blind classes and why the agent asks about
  twelve specific character pairs
- `docs/ARCHITECTURE.md` — the full technical specification
