import { useSyncExternalStore } from 'react';

/* ════════════════════════════════════════════════════════════════════════════
   ONE PLACE THAT ANSWERS "MAY WE ANIMATE?"

   Everything that moves on the landing page asks this file, and gets the same
   answer at the same moment: the Motion entrances (screens/Landing.tsx), the
   three.js scene (landing/ContainerScene.tsx), the Swiper autoplay
   (landing/FormatCarousel.tsx) and the Chart.js bars (landing/GainChart.tsx).
   Four libraries each asking the browser on their own would disagree the day
   one of them reads the preference differently -- and a page where the tiles
   float but the text is still, or the reverse, has lost the preference.

   ── WHY THE QUERY IS `no-preference` AND NOT `not reduce` ───────────────────
   On a browser that does not support the media feature, both `reduce` and
   `no-preference` evaluate false. There `not reduce` says "animate" and
   `no-preference` says "do not". This file asks `no-preference`, so a browser
   too old to report the preference gets NO motion. That is the safe direction
   of the error: motion is never the only carrier of meaning on this page,
   while a reader who asked for stillness and got motion has been handed the
   exact harm the query exists to prevent.

   ── REDUCED MOTION IS A REFUSAL, NOT A DEGRADATION ─────────────────────────
   base.css collapses CSS animation and transition durations under `reduce`.
   That cannot reach a requestAnimationFrame loop, a WebGL render or a canvas
   chart. So the preference is a JavaScript branch, and the branch is NOT
   CREATING THE MOTION -- the scene draws one still frame, the carousel has no
   autoplay, the chart is created with animation off, and Motion is given
   `initial={false}` -- never "the same motion with duration 0", which still
   writes a from-value for a frame.

   Callers therefore use this file to decide whether a thing EXISTS, never how
   fast it runs.
   ════════════════════════════════════════════════════════════════════════════ */

/** The gate: '(prefers-reduced-motion: no-preference)'. See the header. */
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
