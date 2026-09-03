import { useEffect, useLayoutEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

import { MOTION_QUERY } from './motion-prefs';

/* ════════════════════════════════════════════════════════════════════════════
   THE GSAP CONTEXT — the landing page's one animation scope.

   This replaces lib/useReveal.ts + styles/reveal.css. Two systems animating the
   same elements fight, and which one wins is decided by whichever wrote last in
   a given frame, which is not a decision anybody made. The landing page ends
   with ONE.

   ── THE SAFETY PROPERTY, CARRIED OVER AND MADE STRONGER ────────────────────
   reveal.css arrived at its rule after shipping a BLANK PAGE:

       Content is visible by default. Hiding is something JavaScript does only
       after it has proved it can un-hide.

   That property was necessary because reveal.css hid things. This file does not
   hide things, and the choreography it hosts is forbidden to: no animated
   opacity, no autoAlpha, no visibility, no scale-from-zero on anything holding
   text. The only property a text element animates is `transform`, and the
   largest offset anything holds is 14px of translateY.

   So the property becomes: THERE IS NO HIDING, SO THERE IS NOTHING TO PROVE.
   If the script dies anywhere — at the import, inside the context callback,
   between tween creation and ScrollTrigger's first refresh — the worst page a
   reader can get is the FINISHED page with a few elements sitting 14px low.
   Every word readable, every link clickable.

   This file cannot enforce that rule on the callback it is handed, so it does
   the next best thing: it makes the recovery total. See UNSTRAND below, which
   strips exactly the properties GSAP writes, including the opacity and
   visibility that are not supposed to be there — because a guard that only
   handles the mistakes you predicted is not a guard.

   ── WHY useLayoutEffect ────────────────────────────────────────────────────
   Same reason useReveal documented: the hero's load tweens set their from-value
   before the browser paints. In useEffect the page paints at rest, then jumps
   14px down, then rises — a visible blink on a slow device, and the one blink
   nobody asked for.

   ── WHY EVERY TWEEN MUST BE fromTo ─────────────────────────────────────────
   Not enforceable here, but it belongs written next to the cleanup that makes
   it matter. from() records the element's CURRENT value as its destination. Run
   it twice — React 19 StrictMode's double mount, a re-render, a cleanup that
   missed — and the second run's destination is the first run's start, and the
   element settles 14px low forever. ctx.revert() below removes the first run's
   inline styles precisely so the second run starts from the markup's state, but
   fromTo with an explicit `to` is what makes that robust rather than lucky.
   ════════════════════════════════════════════════════════════════════════════ */

gsap.registerPlugin(ScrollTrigger);

/* Mobile browsers fire a resize every time the URL bar slides. Without this,
 * ScrollTrigger recomputes every start/end mid-scroll on a phone, which both
 * costs frames and moves the trigger points under the reader's finger. Height-
 * only resizes are ignored; a real orientation change still refreshes. */
ScrollTrigger.config({ ignoreMobileResize: true });

/** Everything the choreography is handed. Use THIS gsap, not a fresh import:
 *  tweens created with it inside the callback are collected by the context and
 *  therefore reverted by the cleanup. A tween created outside is a leak. */
export interface MotionApi {
  /** The `.landing` element the context is scoped to. Selector strings inside
   *  the callback resolve within it, so '.hero__title' cannot reach the rack in
   *  the dashboard. */
  root: HTMLElement;
  gsap: typeof gsap;
  ScrollTrigger: typeof ScrollTrigger;
}

/** Runs once per mount, only when motion is allowed. It may return a cleanup,
 *  which gsap.matchMedia calls when the preference flips to `reduce`. */
export type Choreography = (api: MotionApi) => void | (() => void);

export interface GsapContextOptions {
  /**
   * Elements the timeout backstop is allowed to un-strand, as a selector
   * resolved inside the root. Defaults to '[data-beat]' — the attribute the
   * choreography puts on everything it displaces.
   *
   * Scoping it matters. A backstop that cleared every inline transform under
   * the root would also clear the ones a live scrub is writing that frame.
   */
  failsafeSelector?: string;
  /**
   * Milliseconds before the backstop runs. 4000 is inherited from useReveal at
   * the same value and for the same reason: long enough never to pre-empt a
   * normal arrival on a slow phone, short enough that a reader who hit a bug is
   * not left looking at it.
   */
  failsafeMs?: number;
}

/** Handle for the non-React entry point. */
export interface ChoreographyHandle {
  /** Idempotent. Reverts every inline style GSAP wrote and kills every
   *  ScrollTrigger the callback created, leaving the DOM byte-identical to the
   *  markup React rendered. */
  destroy: () => void;
  /** Re-measure every trigger's start/end. Cheap, and correct to call often. */
  refresh: () => void;
}

const DEFAULT_FAILSAFE_SELECTOR = '[data-beat]';
const DEFAULT_FAILSAFE_MS = 4000;

/* The properties GSAP is capable of writing inline for this design's vocabulary,
 * plus the three it is forbidden to write. Forbidden ones are listed BECAUSE
 * they are forbidden: if one ever appears, it appeared by accident, which is
 * exactly the case a failsafe is for. `width` is deliberately absent — the
 * ratio bars carry authored inline widths that are content, not motion. */
const MOTION_PROPS = [
  'transform',
  'transform-origin',
  'translate',
  'rotate',
  'scale',
  'opacity',
  'visibility',
] as const;

/**
 * Strip motion's inline styles from a subtree, without touching anything else.
 *
 * This is the recovery path, and it is written to work when GSAP is the thing
 * that broke: it uses no GSAP API, only style.removeProperty. If gsap itself
 * threw on import there would be no context to revert and no tween to kill —
 * but there could still be inline values on screen, and this removes them.
 *
 * Returns the number of elements it touched, so callers can log a real count
 * rather than a suspicion.
 */
export function unstrand(scope: ParentNode): number {
  let touched = 0;
  const nodes = scope.querySelectorAll<HTMLElement>('[style]');
  for (const node of nodes) {
    let hit = false;
    for (const prop of MOTION_PROPS) {
      if (node.style.getPropertyValue(prop) === '') continue;
      node.style.removeProperty(prop);
      hit = true;
    }
    if (hit) touched += 1;
    /* An emptied `style=""` is invisible but it is not nothing: the cleanup's
     * promise is that the DOM comes back byte-identical to the markup React
     * rendered, and gsap.context().revert() leaves the husk behind. Measured:
     * after revert the attribute is present and empty. Only ever removed once
     * it holds no declarations, so the ratio bars' authored inline widths —
     * which are content, not motion — survive untouched. */
    if (node.style.length === 0 && node.getAttribute('style') === '') {
      node.removeAttribute('style');
    }
  }
  return touched;
}

/**
 * Build the landing page's animation context. The React hook below is a thin
 * wrapper; this is the whole mechanism, and it is exported without React so it
 * can be driven from a console against a live page and measured.
 */
export function createChoreography(
  root: HTMLElement,
  choreograph: Choreography,
  options: GsapContextOptions = {},
): ChoreographyHandle {
  const failsafeSelector = options.failsafeSelector ?? DEFAULT_FAILSAFE_SELECTOR;
  const failsafeMs = options.failsafeMs ?? DEFAULT_FAILSAFE_MS;

  let ctx: gsap.Context | null = null;
  let mm: gsap.MatchMedia | null = null;
  let failsafe = 0;
  let destroyed = false;

  const refresh = () => {
    if (destroyed) return;
    try {
      ScrollTrigger.refresh();
    } catch {
      /* A refresh that throws must not take the page with it. */
    }
  };

  const destroy = () => {
    if (destroyed) return;
    destroyed = true;
    window.clearTimeout(failsafe);
    /* Order matters and each step is separately guarded, because the whole
     * point of a teardown is that it runs on the path where something already
     * went wrong. mm.revert() first: it owns the media-query block, and
     * reverting the outer context while the inner block is live has been known
     * to leave a ScrollTrigger alive with no context to kill it. */
    try {
      mm?.revert();
    } catch {
      /* fall through to ctx.revert() */
    }
    try {
      ctx?.revert();
    } catch {
      /* fall through to unstrand() */
    }
    /* Belt and braces. revert() should have done this. If a tween was created
     * outside the context by mistake, or a scrub wrote a transform in the frame
     * the context died, this is what puts the page back at rest. */
    unstrand(root);
  };

  try {
    ctx = gsap.context(() => {
      mm = gsap.matchMedia();
      /* THE GATE. Not a duration of 0 — the callback simply never runs, so no
       * tween and no ScrollTrigger is ever constructed. And because this is
       * gsap.matchMedia rather than a one-time matchMedia().matches read, a
       * reader who turns reduced motion ON mid-session gets the whole block
       * reverted on the spot: inline styles removed, triggers killed, page at
       * rest, no reload. Turning it back off rebuilds it. */
      mm.add(MOTION_QUERY, () => choreograph({ root, gsap, ScrollTrigger }));
    }, root);
  } catch (error) {
    /* The callback threw. Anything it managed to set before throwing is inline
     * on the page right now, so clear it and report. The page is at rest and
     * complete; nothing here is allowed to rethrow into React's render path. */
    unstrand(root);
    if (import.meta.env.DEV) {
      console.error('[useGsapContext] choreography threw; page left at rest.', error);
    }
    destroyed = true;
    return { destroy: () => {}, refresh: () => {} };
  }

  /* Every start/end in the choreography is a measured pixel position, and web
   * fonts move all of them. Measured on this page: the same English headline
   * sets 3 lines at 1280px and 4 at 375px, and the Russian catalog wraps
   * differently again. Start points computed before layout settles are wrong. */
  if (typeof document !== 'undefined' && document.fonts) {
    document.fonts.ready.then(refresh).catch(() => {});
  }

  /* THE TIMEOUT BACKSTOP.
   *
   * It cannot un-hide anything, because nothing is hidden. Its only job is the
   * one failure this design still admits: a ScrollTrigger that never fires
   * because a late layout shift left its start point above the reader's current
   * scroll position, leaving its section parked 14px low forever.
   *
   * So it refreshes first — which is the actual fix, and re-fires anything that
   * should already have run — and only then clears what is still displaced AND
   * ON SCREEN. On screen is the condition that makes this safe: an element the
   * reader can see, still displaced, four seconds in, with no tween touching
   * it, is a bug. An element below the fold is just waiting its turn. */
  failsafe = window.setTimeout(() => {
    if (destroyed) return;
    refresh();

    const viewport = window.innerHeight || document.documentElement.clientHeight;
    let cleared = 0;
    for (const el of root.querySelectorAll<HTMLElement>(failsafeSelector)) {
      if (el.style.transform === '') continue;
      if (gsap.isTweening(el)) continue;
      const rect = el.getBoundingClientRect();
      if (rect.bottom <= 0 || rect.top >= viewport) continue;
      gsap.set(el, { clearProps: 'transform' });
      cleared += 1;
    }
    if (cleared > 0 && import.meta.env.DEV) {
      console.warn(
        `[useGsapContext] failsafe cleared ${cleared} stranded element(s) after ${failsafeMs}ms.`,
      );
    }
  }, failsafeMs);

  return { destroy, refresh };
}

/**
 * The landing page's animation scope, as a hook.
 *
 * Returns a ref to put on the `.landing` root. The choreography runs once per
 * mount, inside a gsap.context() scoped to that root, inside a
 * gsap.matchMedia() gated on the reader's motion preference.
 *
 *     const root = useGsapContext<HTMLDivElement>(
 *       ({ root, gsap, ScrollTrigger }) => {
 *         gsap.fromTo('.hero__title-a', { y: 14 }, { y: 0, duration: 0.2 });
 *       },
 *       { refreshOn: [i18n.language] },
 *     );
 *
 * `choreograph` is read from a ref, so an inline arrow function does not
 * rebuild the context on every render. It is called ONCE per mount, with the
 * identity it had at mount.
 */
export function useGsapContext<T extends HTMLElement>(
  choreograph: Choreography,
  options: GsapContextOptions & {
    /** Values whose change means the layout moved and triggers must be
     *  re-measured — the i18n language, most importantly. Refreshing is not
     *  rebuilding: a `once: true` trigger that already fired stays fired,
     *  because re-running history is a lie. Keep the array length constant. */
    refreshOn?: readonly unknown[];
  } = {},
) {
  const root = useRef<T | null>(null);
  const handle = useRef<ChoreographyHandle | null>(null);

  const latest = useRef(choreograph);
  latest.current = choreograph;

  const { failsafeSelector, failsafeMs, refreshOn } = options;

  /* Primitives joined into one dependency. A raw array in the dep list would be
   * a new identity every render, and spreading it would crash React the first
   * time a caller passed a different length. */
  const refreshKey = (refreshOn ?? []).map((value) => String(value)).join('|');

  useLayoutEffect(() => {
    const el = root.current;
    if (!el) return;

    const opts: GsapContextOptions = {};
    if (failsafeSelector !== undefined) opts.failsafeSelector = failsafeSelector;
    if (failsafeMs !== undefined) opts.failsafeMs = failsafeMs;

    const created = createChoreography(el, (api) => latest.current(api), opts);
    handle.current = created;

    return () => {
      handle.current = null;
      created.destroy();
    };
  }, [failsafeSelector, failsafeMs]);

  /* Separate effect, and deliberately not in the dep list above: a language
   * change must re-MEASURE, not rebuild. useEffect rather than useLayoutEffect
   * because the new text has to be laid out before there is anything to
   * measure. Skips the mount pass; createChoreography already refreshes on
   * fonts.ready. */
  const firstRefresh = useRef(true);
  useEffect(() => {
    if (firstRefresh.current) {
      firstRefresh.current = false;
      return;
    }
    handle.current?.refresh();
  }, [refreshKey]);

  return root;
}
