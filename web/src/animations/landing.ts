import type { Choreography, MotionApi } from '../lib/useGsapContext';

/* The landing page's motion.

   One rule: nothing is ever hidden. The only property text animates is
   `transform`, by at most 14px, so every frame is readable and a script that
   dies leaves the finished page. The one exception is `.ratio__fill`, a pure
   graphic whose meaning is stated beside it as "1×" and "15×".

   No pin and no scrub. A pin takes the reader's scroll away from them, and on
   a page whose pitch is "it interrupts once, briefly" that is the message
   contradicting itself.

   Durations and eases are READ from tokens.css at runtime, not retyped. This
   function is never called under prefers-reduced-motion: useGsapContext gates
   it inside gsap.matchMedia(), so under reduced motion none of it exists. */

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
 * Scoped to the `.landing` root by useGsapContext, which reverts every tween
 * and kills every ScrollTrigger on unmount. Returns a cleanup for the one thing
 * it cannot undo: a class this function added by hand.
 */
export const landingChoreography: Choreography = ({ root, gsap, ScrollTrigger }: MotionApi) => {
  /* A throw in here means useGsapContext never receives the context, so any
   * trigger created before it would be orphaned. Kill ours on the way out and
   * rethrow, so the hook still unstrands the page and logs. */
  const preexisting = new Set(ScrollTrigger.getAll());

  try {
    const BASE = readDuration('--motion-base', FALLBACK.base);
    const SLOW = readDuration('--motion-slow', FALLBACK.slow);
    const easeOut = readEase('--ease-out', FALLBACK.easeOut);
    const easeOutQuart = readEase('--ease-out-quart', FALLBACK.easeOutQuart);

    const clauseA = one(root, '.hero__title-a');
    const clauseB = one(root, '.hero__title-b');
    const support = one(root, '.hero__support');
    const rack = one(root, '.hero__rack');
    const gain = one(root, '.gain');
    const fills = many(root, '.ratio__fill');
    const arrivals = many(root, '.how, .gain, .limit, .close');

    /* The denial enters; the reversal lands later and slower -- --motion-slow
     * is the token reserved for what a reader is meant to notice, and clause B
     * is that claim in prose. The support block arrives as one object. */
    if (clauseA) gsap.fromTo(clauseA, { y: RISE }, { y: 0, duration: BASE, ease: easeOut });
    if (clauseB) {
      gsap.fromTo(clauseB, { y: RISE }, { y: 0, duration: SLOW, ease: easeOutQuart, delay: SLOW });
    }
    if (support) {
      gsap.fromTo(support, { y: RISE }, { y: 0, duration: BASE, ease: easeOut, delay: SLOW * 2 });
    }

    /* The rack plays its own keyframes (motion.css) when it is actually on
     * screen, once. A scrub would run the repair backwards -- the microphone
     * overruling the format, the product's claim inverted. */
    if (rack) {
      ScrollTrigger.create({
        trigger: rack,
        start: 'top 85%',
        once: true,
        onEnter: () => rack.classList.add('rack--animate'),
      });
    }

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

    /* immediateRender: false -- scaleX(0) is an invisible bar, so the from-value
     * is written only when the tween starts; every failure before that leaves
     * both bars at their authored widths. */
    if (gain && fills.length > 0) {
      gsap.fromTo(
        fills,
        { scaleX: 0, transformOrigin: 'left center' },
        {
          scaleX: 1,
          duration: SLOW,
          ease: easeOutQuart,
          delay: 0.15,
          immediateRender: false,
          scrollTrigger: { trigger: gain, start: 'top 80%', once: true },
        },
      );
    }

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
