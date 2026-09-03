import { useSyncExternalStore } from 'react';

/* ════════════════════════════════════════════════════════════════════════════
   ONE PLACE THAT ANSWERS "MAY WE ANIMATE?"

   Everything that moves on the landing page asks this file, and gets the same
   answer at the same moment. Two subsystems disagreeing about the reader's
   preference is not a small bug: it produces a page where Lenis is smoothing
   the scroll but no tween is running, or the reverse — tweens playing at full
   length for someone who asked for stillness.

   ── WHY THE QUERY IS `no-preference` AND NOT `not reduce` ───────────────────
   gsap.matchMedia() gates the choreography on '(prefers-reduced-motion:
   no-preference)'. If this file asked the opposite question — "is `reduce`
   absent?" — the two would agree on every browser that supports the media
   feature and DISAGREE on every browser that does not, where both `reduce` and
   `no-preference` evaluate false. There, `not reduce` says yes and
   `no-preference` says no, and Lenis would initialise for a page with no
   tweens to smooth.

   So this file asks GSAP's question, verbatim. The consequence is deliberate:
   a browser too old to report the preference gets NO motion. That is the safe
   direction of the error. A reader who wanted motion and did not get it has
   lost nothing the page needed — motion.css's rule holds across this whole
   design that motion is never the only carrier of meaning — while a reader who
   asked for stillness and got motion has been handed the exact harm the query
   exists to prevent.

   ── REDUCED MOTION IS A REFUSAL, NOT A DEGRADATION ─────────────────────────
   base.css collapses animation-duration and transition-duration to 1ms under
   `reduce`. That is a CSS mechanism and it CANNOT reach GSAP, which runs on
   requestAnimationFrame and writes inline styles. So on this page the
   preference has to be a JavaScript branch, and the branch must be NOT
   CREATING THE TWEEN — not creating it with duration 0. A zero-duration
   fromTo() still writes its from-value inline for a frame, and a 14px jump in
   one frame is motion.

   Callers therefore use this file to decide whether a thing EXISTS, never how
   fast it runs.
   ════════════════════════════════════════════════════════════════════════════ */

/** The gate. Identical string to the one handed to gsap.matchMedia(), on
 *  purpose — see the header. Exported so the choreography can pass the same
 *  constant rather than retyping the query and drifting from it. */
export const MOTION_QUERY = '(prefers-reduced-motion: no-preference)';

/** The complement, for anything that needs to assert the reader opted out
 *  rather than merely failed to opt in. Note that these two are NOT negations
 *  of one another on a browser without support, where both are false. */
export const REDUCE_QUERY = '(prefers-reduced-motion: reduce)';

function query(q: string): MediaQueryList | null {
  // SSR, jsdom without matchMedia, and ancient browsers all land here. Every
  // one of them gets the still page.
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null;
  try {
    return window.matchMedia(q);
  } catch {
    return null;
  }
}

/**
 * May we animate, right now?
 *
 * The single question. `false` when the reader asked for reduced motion, and
 * also `false` when we cannot tell — see the header for why those two answers
 * are the same answer.
 */
export function motionAllowed(): boolean {
  return query(MOTION_QUERY)?.matches ?? false;
}

/** True only when the reader has explicitly asked for reduced motion. Use
 *  `motionAllowed()` to decide whether to build something; use this only to
 *  report or log why. */
export function prefersReducedMotion(): boolean {
  return query(REDUCE_QUERY)?.matches ?? false;
}

/**
 * Subscribe to the preference CHANGING.
 *
 * A reader can turn reduced motion on mid-session — in macOS System Settings,
 * in Windows animation settings, in a DevTools emulation — and the page must
 * stop animating without a reload. Both hooks in this folder are wired through
 * here so that flip is a teardown, not a request to refresh.
 *
 * Returns an unsubscribe function. Safe to call where matchMedia is absent: it
 * subscribes to nothing and returns a no-op, because a preference that cannot
 * be read cannot change.
 */
export function onMotionPreferenceChange(listener: (allowed: boolean) => void): () => void {
  const mql = query(MOTION_QUERY);
  if (!mql) return () => {};

  const handler = (event: MediaQueryListEvent) => listener(event.matches);

  // addListener is the Safari <14 spelling. Kept because the failure mode of
  // not having it is the one this whole file exists to prevent: motion that
  // keeps running after the reader asked it to stop.
  if (typeof mql.addEventListener === 'function') {
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }
  const legacy = mql as MediaQueryList & {
    addListener?: (cb: (e: MediaQueryListEvent) => void) => void;
    removeListener?: (cb: (e: MediaQueryListEvent) => void) => void;
  };
  legacy.addListener?.(handler);
  return () => legacy.removeListener?.(handler);
}

/**
 * The React reading of the same answer.
 *
 * useSyncExternalStore rather than useState + useEffect so that the first
 * render already knows. With useState the first paint would assume motion is
 * allowed, and a reduced-motion reader would get one frame of the animated
 * page before the effect corrected it — a flash, which is motion.
 *
 * The server snapshot is `false`: nothing prerendered ever animates.
 */
export function useMotionAllowed(): boolean {
  return useSyncExternalStore(onMotionPreferenceChange, motionAllowed, () => false);
}
