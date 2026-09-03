import type { Choreography, MotionApi } from '../lib/useGsapContext';

/* ════════════════════════════════════════════════════════════════════════════
   THE LANDING PAGE CHOREOGRAPHY.

   Ten seconds to make a stranger understand one sentence: Readback does not
   hear better, it knows what a valid answer is allowed to be. Everything below
   exists to serve that sentence and nothing below decorates it.

   ── THE ONE RULE THIS FILE IS BUILT ON ─────────────────────────────────────
   NOTHING ON THIS PAGE IS EVER HIDDEN. No animated opacity, no autoAlpha, no
   visibility, no display:none, no scale-from-zero on anything holding text.
   The only property a text element animates is `transform`, and the largest
   offset anything ever holds is 14px of translateY.

   That single rule buys three things at once:

     1. It obeys motion.css rule 1 ("NO ANIMATED OPACITY ON TEXT... the usable
        range is 1.00 down to 0.99") without a landing-page carve-out.
     2. Every frame of every animation is readable, which is what a page with
        ten seconds actually needs.
     3. It answers the failsafe problem BY CONSTRUCTION. GSAP writes tween
        values as inline styles, so an opacity-0 resting state plus a script
        that dies is reveal.css's blank page in a different costume. If opacity
        is never a tweened property there is no code path to that bug. The worst
        page a reader can get is the FINISHED page with at most fourteen
        elements sitting 14px low.

   The one element allowed to move differently is `.ratio__fill`, and it is the
   one element on the page that is a pure graphic: `.ratios` is aria-hidden and
   holds no text, and its meaning is stated independently as the "1×" and "15×"
   labels beside it. Landing.css already records the test it has to pass --
   "nothing here depends on seeing the bar at all".

   ── DURATIONS AND EASES COME FROM tokens.css, NOT FROM THIS FILE ───────────
   Every duration and every ease below is READ from the CSS custom properties at
   runtime and parsed, rather than retyped as a number. The design says clause B
   takes --motion-slow because tokens.css reserves that duration for "a capture
   row settling -- the one duration a user is meant to actually notice". If that
   token moves, this file moves with it. A comment claiming a number is the
   token is not the same as the number being the token.

   Parsing a cubic-bezier into an easing function costs about forty lines and no
   bundle: CustomEase would have imported a plugin to do arithmetic the platform
   already specifies exactly.

   ── REDUCED MOTION ────────────────────────────────────────────────────────
   This function is never called under `(prefers-reduced-motion: reduce)`.
   useGsapContext gates it inside gsap.matchMedia(), so the branch is NOT
   CREATING THE TWEEN rather than creating it with duration 0 -- a zero-duration
   fromTo still writes its from-value inline for a frame, and a 14px jump in one
   frame is motion. Nothing in this file needs a reduced-motion path, because
   under reduced motion nothing in this file exists.

   What the still reader gets instead is the page as authored: both hero clauses
   are separate block spans in BOTH modes, so the pivot from denial to reversal
   survives as a line break rather than as a stagger; the beats are numbered
   01/02/03 and ruled apart; the rack's repair state keeps both characters
   visible with the asking ring and sentence intact; the ratio bars render at
   their authored widths. The motion re-encodes a structure the page already
   draws, which was the test each beat had to pass in order to exist.
   ════════════════════════════════════════════════════════════════════════════ */

/** The displacement ladder's smallest rung, and the only one this page uses.
 *  reveal.css measured it: past roughly 20px the eye tracks the movement
 *  instead of the content, which is decoration by the brief's own definition. */
const RISE = 14;

/* Token names, resolved once per mount off the document element. Fallbacks are
 * the values in tokens.css today; they are here so a stylesheet that failed to
 * load produces a slightly-wrong animation rather than a NaN duration, which
 * GSAP renders as an element stuck at its from-value forever. */
const FALLBACK = {
  base: 0.2,
  slow: 0.3,
  easeOut: [0.2, 0, 0, 1] as const,
  easeOutQuart: [0.25, 1, 0.5, 1] as const,
};

function readToken(name: string): string {
  if (typeof window === 'undefined') return '';
  try {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  } catch {
    return '';
  }
}

/** "200ms" / "0.2s" -> seconds. GSAP counts in seconds; tokens.css counts in ms. */
function readDuration(name: string, fallback: number): number {
  const raw = readToken(name);
  const match = /^(-?[\d.]+)(ms|s)?$/.exec(raw);
  if (!match) return fallback;
  const value = Number.parseFloat(match[1] ?? '');
  if (!Number.isFinite(value) || value <= 0) return fallback;
  return match[2] === 's' ? value : value / 1000;
}

/**
 * A CSS cubic-bezier() timing function as a GSAP ease.
 *
 * Newton-Raphson with a bisection fallback, which is what every browser does
 * internally. Eight iterations is past the precision a 300ms tween can show.
 */
function cubicBezier(x1: number, y1: number, x2: number, y2: number): (t: number) => number {
  const a = (u: number, v: number) => 1 - 3 * v + 3 * u;
  const b = (u: number, v: number) => 3 * v - 6 * u;
  const c = (u: number) => 3 * u;
  const calc = (t: number, u: number, v: number) => ((a(u, v) * t + b(u, v)) * t + c(u)) * t;
  const slope = (t: number, u: number, v: number) => 3 * a(u, v) * t * t + 2 * b(u, v) * t + c(u);

  return (x: number): number => {
    if (!(x > 0)) return 0;
    if (x >= 1) return 1;

    let t = x;
    for (let i = 0; i < 8; i += 1) {
      const error = calc(t, x1, x2) - x;
      if (Math.abs(error) < 1e-6) return calc(t, y1, y2);
      const d = slope(t, x1, x2);
      if (Math.abs(d) < 1e-6) break;
      t -= error / d;
    }

    /* Newton diverges on the near-vertical segment of an aggressive ease --
     * --ease-out is cubic-bezier(0.2, 0, 0, 1), whose x-curve is exactly that.
     * Bisection cannot diverge, so it is what the answer actually comes from
     * in the cases that matter. */
    let lo = 0;
    let hi = 1;
    t = x;
    for (let i = 0; i < 24; i += 1) {
      const value = calc(t, x1, x2);
      if (Math.abs(value - x) < 1e-6) break;
      if (value > x) hi = t;
      else lo = t;
      t = (lo + hi) / 2;
    }
    return calc(t, y1, y2);
  };
}

function readEase(name: string, fallback: readonly [number, number, number, number]) {
  const raw = readToken(name);
  const match = /cubic-bezier\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)/.exec(
    raw,
  );
  const parts = match
    ? ([1, 2, 3, 4].map((i) => Number.parseFloat(match[i] ?? '')) as [
        number,
        number,
        number,
        number,
      ])
    : null;
  const [x1, y1, x2, y2] = parts && parts.every(Number.isFinite) ? parts : fallback;
  return cubicBezier(x1, y1, x2, y2);
}

function one<T extends HTMLElement>(root: ParentNode, selector: string): T | null {
  return root.querySelector<T>(selector);
}

function many<T extends HTMLElement>(root: ParentNode, selector: string): T[] {
  return Array.from(root.querySelectorAll<T>(selector));
}

/**
 * The whole page's motion, in one function.
 *
 * Handed to useGsapContext, which runs it inside a gsap.context() scoped to the
 * `.landing` root and inside a gsap.matchMedia() gated on the reader's
 * preference. Every tween it creates is collected by that context and reverted
 * on unmount; every ScrollTrigger it creates is killed with it.
 *
 * Returns a cleanup for the one thing gsap.context() cannot undo: a class name
 * this function added to the DOM by hand.
 */
export const landingChoreography: Choreography = ({ root, gsap, ScrollTrigger }: MotionApi) => {
  /* MEASURED, AND THE REASON THIS FUNCTION HAS A try/catch AT ALL.
   *
   * useGsapContext wraps this call in `try { ctx = gsap.context(...) } catch`,
   * and its catch unstrands the page -- which works. But `ctx` is assigned by
   * the RETURN of gsap.context(), so a throw in here means `ctx` is never
   * assigned, and every ScrollTrigger created before the throw is orphaned with
   * nothing left holding a reference to kill it. Verified by injecting a throw
   * before beat 6 and reloading: the page came back complete, readable and with
   * zero displaced elements -- and with FOUR live ScrollTriggers, two per
   * StrictMode mount, that no `destroy()` could reach. A live scroll listener on
   * a page that no longer exists is exactly the leak the brief names.
   *
   * The fix belongs here rather than in the hook, because this is the function
   * that knows which triggers are new. Anything created after this snapshot is
   * killed on the way out; the error is then rethrown so the hook still does its
   * own unstranding and still logs. */
  const preexisting = new Set(ScrollTrigger.getAll());

  try {
    const BASE = readDuration('--motion-base', FALLBACK.base);
    const SLOW = readDuration('--motion-slow', FALLBACK.slow);
    const easeOut = readEase('--ease-out', FALLBACK.easeOut);
    const easeOutQuart = readEase('--ease-out-quart', FALLBACK.easeOutQuart);

    /* The load metronome: 0 / SLOW / 2*SLOW. Three ticks at --motion-slow, so the
     * gap between the hero's clauses is the same interval as the gap between the
     * pitch and everything supporting it. reveal.css measured 70ms as the
     * interval that reads as "these are a list"; 300ms is four times that and
     * reads as a pause, which is what a pivot is. */
    const TICK = SLOW;

    /* Elements are looked up and passed by reference rather than as selector
     * strings. gsap.context() would scope the strings correctly, but a missing
     * node then fails as a silent no-op instead of as a null this file can see. */
    const clauseA = one(root, '.hero__title-a');
    const clauseB = one(root, '.hero__title-b');
    const support = one(root, '.hero__support');
    const rack = one(root, '.hero__rack');
    const beatsSection = one(root, '.beats');
    const beats = many(root, '.beat');
    const gain = one(root, '.gain');
    const fills = many(root, '.ratio__fill');
    const arrivals = [one(root, '.silence'), one(root, '.close')].filter(
      (el): el is HTMLElement => el !== null,
    );

    /* ── BEAT 1 — the denial rises alone ──────────────────────────────────────
     * "It does not hear better."
     *
     * MEASURED, and this is the beat that forced the page's structure. At
     * 1280x900 the English title sets three lines and clause A occupies line 1
     * exactly. At 375x812 it sets four, and clause A spans lines 1 AND 2, ending
     * 89px into line 2 -- where clause B then begins, on that same line. Line 2
     * on a phone therefore carries the end of the denial and the start of the
     * reversal at once. A per-line split -- the reflexive way to do this --
     * would group "better." with "It knows what a valid" into one animated unit
     * and stagger the pitch's pivot against its own meaning.
     *
     * Splitting by clause costs nothing to do: line tops inside the h1 are
     * 163/215/268 at 1280 and 215/252/288/324 at 375, identical with and without
     * the split, in all three languages. The break lands where the text already
     * wrapped; only the ownership of line 2 changes.
     *
     * So the split is by CLAUSE, a clause has to be a block box to be
     * transformable, and that is a copy-structure change rather than a motion
     * trick: two catalog keys, two block spans, in both motion modes.
     *
     * --motion-base, whose token comment is "an element entering or leaving".
     * Clause A merely enters. Opacity is not touched; nothing else moves. */
    if (clauseA) {
      gsap.fromTo(clauseA, { y: RISE }, { y: 0, duration: BASE, ease: easeOut });
    }

    /* ── BEAT 2 — the reversal lands, later and slower ────────────────────────
     * "It knows what a valid answer is allowed to be."
     *
     * Same distance, same direction. The contrast is served through TIME and
     * DURATION, because distance and direction are already spoken for:
     * motion.css's displacement ladder is "one gesture, three magnitudes", so
     * giving clause B a second direction to mean "opposition" would invent a
     * gesture the product's vocabulary does not have.
     *
     * The duration is the argument. tokens.css reserves --motion-slow for "a
     * capture row settling -- the one duration a user is meant to actually
     * notice", and clause B IS that claim in prose. A reader who catches nothing
     * else catches that the second half took longer to arrive than the first.
     * --ease-out-quart decelerates harder than clause A's --ease-out, so clause B
     * lands rather than merely stops. Two eases doing two jobs. Settles at 600ms. */
    if (clauseB) {
      gsap.fromTo(
        clauseB,
        { y: RISE },
        { y: 0, duration: SLOW, ease: easeOutQuart, delay: TICK },
      );
    }

    /* ── BEAT 3 — the lede, the scope note and the buttons, as ONE object ─────
     * Staggering these three would assert that the lede, the English-pipeline
     * scope note and the two buttons are three sibling claims arriving in order.
     * They are not: the scope note is the page's honesty line -- Landing.css sets
     * it in --text, DARKER than the pitch above it, precisely so it does not read
     * as a footnote -- and a 70ms stagger would demote it to third item in a
     * list. One tween on one wrapper keeps it level with the lede.
     *
     * `.hero__eyebrow` is excluded and does not animate at all: it sits ABOVE the
     * headline, so animating it would put motion before the pitch and delay the
     * only sentence that matters. The whole load sequence ends at 800ms. */
    if (support) {
      gsap.fromTo(support, { y: RISE }, { y: 0, duration: BASE, ease: easeOut, delay: TICK * 2 });
    }

    /* ── BEAT 4 — the rack, by class handoff. NO TWEEN TOUCHES IT ─────────────
     * GSAP writes no inline style on the rack or on any of its slots. Scroll
     * decides WHEN; motion.css keeps WHAT -- rb-steel-out, rb-repair-in,
     * rb-heard-recede and rb-ask run exactly as written, at their own 300ms and
     * 200ms, with their own --ease-out. No keyframe is duplicated here.
     *
     * MEASURED, and this is why the `animate` prop came off the <Rack> call: on
     * mount the class plays the product's whole claim to an empty seat. At
     * 375x812 the rack begins BELOW the fold and the repaired slot that carries
     * the claim is further below again; all eight animations the class starts
     * finish inside 300ms, before the reader has scrolled a pixel. Zero of eight
     * seen. Moving the trigger to entry is the difference between the reader
     * seeing the format overrule the microphone and not.
     *
     * Explicitly NOT scrubbed, for two reasons. A scrub is reversible, and
     * running rb-repair-in backwards asserts that the microphone overruled the
     * format, which is the product's claim inverted. And Rack.tsx's own comment
     * on this prop says "re-running history is a lie", which a scrub does on
     * every direction change. once: true. */
    if (rack) {
      ScrollTrigger.create({
        trigger: rack,
        start: 'top 85%',
        once: true,
        onEnter: () => rack.classList.add('rack--animate'),
      });
    }

    /* ── BEAT 5 — THE ONE SCRUB ───────────────────────────────────────────────
     * One ScrollTrigger on `.beats` driving one timeline of three equal segments;
     * segment n moves that beat's text and figure TOGETHER. Nothing inside a beat
     * staggers against itself. Segments abut with no gap, so the playhead's
     * position IS "which of the three steps the reader is on".
     *
     * The argument for scrubbing rather than threshold-triggering is geometric,
     * and it was measured. The three beat tops fall inside about 630px at
     * 1280x900, which is less than the 900px viewport -- so a conventional
     * one-shot per beat can have all three trigger points crossed by a single
     * ordinary scroll gesture, and the reader sees "three things appeared"
     * instead of "one, then two, then three". The section's entire structure
     * collapses into one event.
     *
     * Bound to travel instead of to a threshold, the progression advances by
     * exactly the distance the reader moved and the three cannot land together at
     * any scroll speed. That is the difference between motion that decorates the
     * mechanism and motion that IS the mechanism: it mishears, the format
     * constrains, one answer is legal -- one step per third of the reader's own
     * travel.
     *
     * scrub: 0.3 rather than `true`, so even the smoothing lag is a token with a
     * documented meaning: 300ms of catch-up is --motion-slow.
     *
     * ease: 'none' on the timeline and on every segment is MANDATORY. Easing a
     * scrub makes content move at a rate that does not match the finger, which is
     * the one thing a scroll-linked tween must never do. */
    if (beatsSection && beats.length > 0) {
      const scrubbed = gsap.timeline({
        defaults: { ease: 'none', duration: 1 },
        scrollTrigger: {
          trigger: beatsSection,
          start: 'top 80%',
          end: 'bottom 70%',
          scrub: SLOW,
        },
      });

      beats.forEach((beat, index) => {
        const parts = many(beat, '.beat__text, .beat__figure');
        if (parts.length === 0) return;
        scrubbed.fromTo(parts, { y: RISE }, { y: 0, ease: 'none' }, index);
      });
    }

    /* ── BEAT 6 — the 15x panel arrives whole ─────────────────────────────────
     * Landing.css says this section is "one number with room around it.
     * Deliberately not a row of stat tiles" -- the design decision is that the
     * 15x is a single object, and putting a stagger inside it would rebuild the
     * row of tiles that was deliberately removed. It arrives whole because it is
     * one claim. */
    if (gain) {
      gsap.fromTo(
        gain,
        { y: RISE },
        {
          y: 0,
          duration: BASE,
          ease: easeOut,
          scrollTrigger: { trigger: gain, start: 'top 88%', once: true },
        },
      );
    }

    /* ── BEAT 7 — the ratio bars, the page's one non-text gesture ─────────────
     * The authored inline widths (6.7% and 100%) are untouched, so the two bars
     * grow at proportional rates over the same duration and the long one travels
     * fifteen times as far in the same time. No opacity. No width animation --
     * width would relayout every frame; scaleX does not touch layout at all.
     *
     * UNCONSTRAINED_WIDTH is computed in Landing.tsx as 100/15 rather than typed,
     * precisely so the bar is the 15x drawn to scale instead of a hand-set
     * number. Growing both from the same origin in the same time is the only
     * gesture that turns "one is fifteen times the other" from a comparison the
     * reader performs into one they watch happen.
     *
     * --motion-slow, because the ratio is the strongest measured fact on the site
     * and takes the token reserved for what a user is meant to notice.
     *
     * immediateRender: false is the one place this file departs from the default,
     * and it is a failsafe decision. This is the only tween on the page whose
     * from-value is not readable: scaleX(0) is an invisible bar. With
     * immediateRender the bars would sit at zero from load until the reader
     * arrived, and a script that died in between would leave them at zero
     * forever. Deferred, the from-value is written at the moment the tween
     * actually starts, so every failure path before that leaves both bars at
     * their authored, correct, fully-drawn widths. */
    if (gain && fills.length > 0) {
      gsap.fromTo(
        fills,
        { scaleX: 0, transformOrigin: 'left center' },
        {
          scaleX: 1,
          transformOrigin: 'left center',
          duration: SLOW,
          ease: easeOutQuart,
          delay: 0.15,
          immediateRender: false,
          scrollTrigger: { trigger: gain, start: 'top 80%', once: true },
        },
      );
    }

    /* ── BEAT 8 — silence and close: arrivals, not a choreography ─────────────
     * Two independent assertions, so they get an arrival and nothing more. Each
     * section moves as ONE unit; nothing inside them staggers. That rule is
     * load-bearing inside `.silence`, which now carries the blind-pair movement
     * after the merge: Landing.css describes the three `.pair` items as "three
     * instances of one fact" deliberately unified into one panel rather than
     * three bordered cards, and staggering them would assert an order among three
     * things that have none. That is motion.css ban 14 -- "a stagger
     * misrepresents when things arrived" -- applied to prose instead of to
     * capture rows.
     *
     * 88% rather than the scrub's 80% so a short section has finished arriving
     * before it is centred and being read. */
    arrivals.forEach((section) => {
      gsap.fromTo(
        section,
        { y: RISE },
        {
          y: 0,
          duration: BASE,
          ease: easeOut,
          scrollTrigger: { trigger: section, start: 'top 88%', once: true },
        },
      );
    });

    /* ── NOTHING PINS ─────────────────────────────────────────────────────────
     * The answer to "exactly one thing pinned" is zero, and it was measured
     * before it was argued. The only candidate is `.beats`, and it is taller than
     * the viewport at both sizes, so a pin would hold the reader in place while
     * part of the pinned section is already scrolled off the top. There is no
     * room to pin it.
     *
     * Mechanically, ScrollTrigger's pin is position:fixed plus a spacer, and that
     * breaks two things this page is required to protect: find-in-page locates a
     * match inside pinned content and scrolls to the SPACER, so Ctrl+F lands on
     * blank space; and focus-scroll into the tabIndex=0 `.sweep__scroll` group in
     * beat 3 fails the same way.
     *
     * Editorially it is the worst fit of all. A pin takes the reader's scroll
     * away from them for a fixed distance. On a landing page whose single pitch
     * is that the product interrupts once, briefly, and then goes quiet, holding
     * the reader hostage to finish an animation is the message contradicting
     * itself in the medium. */

    /* The one thing gsap.context() cannot revert, because GSAP did not write it. */
    return () => {
      rack?.classList.remove('rack--animate');
    };
  } catch (error) {
    for (const trigger of ScrollTrigger.getAll()) {
      if (!preexisting.has(trigger)) trigger.kill();
    }
    throw error;
  }
};
