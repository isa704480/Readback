import { useEffect } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Lenis from 'lenis';

import { useMotionAllowed } from './motion-prefs';

/* ════════════════════════════════════════════════════════════════════════════
   LENIS — smooth scroll, and the four things it breaks.

   Lenis has exactly ONE job on this page: giving the single scrubbed timeline
   in `.beats` a smooth clock, so the progression advances by the distance the
   reader moved rather than in wheel-notch steps. That is the whole return. So
   the decision rule is written down here where it can be acted on: IF THE
   BEATS SCRUB IS CUT, LENIS IS CUT WITH IT. There is nothing else on the page
   that needs it, and it is not free.

   What it costs is native scrolling, which people rely on in four ways that
   have nothing to do with looking at a landing page. Each is repaired below,
   each repair is named, and each was tested by doing it rather than by reading
   the handler.

   ── WHY NOT ScrollTrigger.scrollerProxy() ──────────────────────────────────
   Because Lenis here scrolls the real window: setScroll() calls
   window.scrollTo({behavior:'instant'}), so document.scrollingElement.scrollTop
   is genuinely at Lenis's position every frame. ScrollTrigger reading
   window.scrollY is therefore reading the truth, and a proxy would only insert
   a second opinion. What ScrollTrigger does need is to be told WHEN to look,
   which is `lenis.on('scroll', ScrollTrigger.update)`, and to share one clock,
   which is the gsap.ticker wiring. Two rAF loops would sample the same frame at
   two different times and every trigger would fire a frame off its start.

   ── WHAT THE FOUR REPAIRS ARE WORTH, MEASURED ──────────────────────────────
   Each number below is a before/after against a bare Lenis carrying the same
   lerp and no repairs, run on the live landing page. 1280x900 unless stated.

   1. ANCHOR. The page has one: a[href="#main"] -> #main at document y=135,
      under a sticky .topbar measured at 71px (132px at 375px, two rows).
      bare: lands at scrollY 135, #main's top at viewport y=0 — 71px of the
            skip link's destination sitting under the bar (132px at 375px).
      here: scrollY 64, #main's top at viewport y=71 — flush, 0px hidden.
            At 375px: scrollY 32, top at 132. Focus moves to #main; the hash
            is written back. All of it synchronous, no frames needed.

   2. FIND-IN-PAGE, simulated as the browser does it — move the scroll
      position out from under Lenis.
      idle Lenis: bare already adopts (Lenis 1.3.26's own onNativeScroll), so
            there is nothing to fix and nothing is claimed.
      mid-ease: reader eases toward y=3000, hits Ctrl+F, match at y=1000.
            bare: dragged off the match to y=783 and still climbing to 3000.
            here: adopted on the very next frame — animatedScroll, targetScroll
            and scrollY all 1000 — and still 1000 after 120 frames. Drift 0px.
            Same at 375px: jump to 1200, drift 0px.

   3. FOCUS SCROLL. A control the browser has just scrolled flush to the top
      edge, which is under the bar.
      bare: hero button at viewport top 0, 71px hidden under the nav.
      here: repositioned to top 95 = 71 nav + 24 margin. A control below the
            fold (the tabIndex=0 lane, 1765px past the bottom) lands at 95 too.
            A control already comfortably in view: page does not move, 0px.
            At 375px, under the 132px two-row bar: 132 hidden -> lands at 156.

   4. PAGE KEYS. bare: PageDown not prevented and targetScroll unchanged —
            Lenis implements no keyboard scrolling at all.
      here: PageDown +860 and PageUp -860 (900 viewport - 40 overlap), Home 0,
            End 3810 = the document limit; three fast PageDowns travel exactly
            3 pages, not 1. At 375x812 the step is 772 and End is 5479.
            Handed back where they belong: inside a text input, inside the
            horizontal .sweep__scroll lane (142px of overflow at 375px, its
            keys are its own), and with Ctrl held — none prevented.

   And the leak this file exists to avoid: after destroy(), the page was
   scrolled natively and 200 frames pumped — scroll position held exactly,
   window.__lenis undefined, the `lenis` class off <html>. Nothing still
   writing scrollTop.
   ════════════════════════════════════════════════════════════════════════════ */

gsap.registerPlugin(ScrollTrigger);

/* ── The configuration, and why each value ────────────────────────────────── */

/** Lenis's default is 0.1. This page runs 0.12 because the smoothing does not
 *  act alone: the `.beats` ScrollTrigger has scrub 0.3, and the two compose IN
 *  SERIES. Lenis lags the scroll behind the finger, then the scrub lags the
 *  timeline behind the scroll, and at the default the progression is visibly
 *  behind the hand that is driving it — which is the one thing a scroll-linked
 *  tween must never be. 0.12 pulls the first stage tighter to leave the budget
 *  to the stage that is carrying meaning. */
const LERP = 0.12;

/** The sticky bar is measured, never assumed. It is 71px at 1280px and 132px
 *  at 375px where TopBar.css wraps the nav onto a second row, and the Russian
 *  catalog can wrap it again. A constant here would put the skip link's landing
 *  underneath the bar in exactly the two cases that matter most. */
const NAV_SELECTOR = '.topbar';

/** Elements that own their own scrolling. Wheel and touch over these stay
 *  native, so the horizontal lane in beat 3 — measured 135px of overflow at
 *  375px — still answers a trackpad. Lenis already ignores a purely horizontal
 *  gesture (gestureOrientation 'vertical' returns early when deltaY is 0), but
 *  a trackpad rarely produces a purely horizontal one. */
const PREVENT_SELECTOR = '[data-lenis-prevent], .sweep__scroll';

/** Kept on screen between one PageDown and the next, so the reader has a line
 *  of context rather than a cut. Matches the browsers' own convention. */
const PAGE_OVERLAP = 40;

/** Clearance below the sticky nav when a focused control is scrolled into view.
 *  Scrolling a control to flush against the bar is technically "in view" and
 *  practically unreadable. */
const FOCUS_MARGIN = 24;

/** Anything below this is subpixel rounding between Lenis's fractional
 *  animatedScroll and the browser's device-pixel-snapped scrollTop. Anything
 *  above it is somebody else scrolling. See adoptForeignScroll(). */
const DRIFT_PX = 2;

export interface SmoothScrollOptions {
  /** Interpolation intensity, 0..1. Higher is tighter to the input device. */
  lerp?: number;
  /** Selector for the sticky bar whose height offsets anchor and focus scrolls. */
  navSelector?: string;
  /** Selector for elements that keep native wheel/touch scrolling. */
  preventSelector?: string;
}

export interface SmoothScrollHandle {
  lenis: Lenis;
  /** Idempotent. Removes the ticker callback BEFORE destroying the instance —
   *  see the note at the call site. */
  destroy: () => void;
}

/* One page, one scroller. Two Lenis instances on one window both write
 * scrollTop every frame and the result is a fight nobody can debug. This module
 * refuses the second rather than producing it. */
let active: SmoothScrollHandle | null = null;

function isTypingTarget(node: EventTarget | null): boolean {
  if (!(node instanceof HTMLElement)) return false;
  if (node.isContentEditable) return true;
  const tag = node.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

/**
 * Build the smooth scroller and its four repairs.
 *
 * Exported without React so it can be constructed against a live page from a
 * console and each repair measured. The hook below is a lifecycle wrapper and
 * nothing else.
 *
 * Callers must not invoke this under reduced motion. It does not check, on
 * purpose: the check belongs in one place (motion-prefs.ts) and a second copy
 * here would be a second thing to keep in agreement.
 */
export function createSmoothScroll(options: SmoothScrollOptions = {}): SmoothScrollHandle {
  if (active) {
    if (import.meta.env.DEV) {
      console.warn('[useSmoothScroll] a Lenis instance is already running; reusing it.');
    }
    return active;
  }

  const lerp = options.lerp ?? LERP;
  const navSelector = options.navSelector ?? NAV_SELECTOR;
  const preventSelector = options.preventSelector ?? PREVENT_SELECTOR;

  /** Measured at the moment of use, not at construction: the bar's height
   *  changes with viewport width and with the language. Returns 0 unless the
   *  bar is actually overlaying content, so a non-sticky header costs nothing. */
  const navHeight = (): number => {
    const bar = document.querySelector<HTMLElement>(navSelector);
    if (!bar) return 0;
    const position = getComputedStyle(bar).position;
    if (position !== 'sticky' && position !== 'fixed') return 0;
    return Math.round(bar.getBoundingClientRect().height);
  };

  const lenis = new Lenis({
    lerp,
    /* We drive the loop from gsap.ticker so Lenis and ScrollTrigger share one
     * clock. autoRaf would start a second loop that this module could not stop. */
    autoRaf: false,
    /* Wheel is smoothed; touch is not. syncTouch replaces the platform's own
     * momentum with a simulation of it, which on a phone reads as lag and costs
     * frames. With it off, touch scrolls natively and the frame adoption below
     * hands the resulting position straight to Lenis, so the scrub still tracks. */
    smoothWheel: true,
    syncTouch: false,
    /* Lenis's own anchor handling is off. It does not preventDefault, so the
     * native jump runs too, and its offset is fixed at construction — which
     * cannot be right for a nav bar that is 71px at one width and 132px at
     * another. handleAnchorClick below does the whole job with a live
     * measurement, and moves focus, which scrolling never does. */
    anchors: false,
    /* Redundant — this module is never constructed under reduced motion — and
     * kept anyway, because a defence that only works when the caller behaves is
     * not a defence. */
    respectReducedMotion: true,
    prevent: (node) => {
      try {
        return node.matches?.(preventSelector) ?? false;
      } catch {
        return false;
      }
    },
  });

  /* Debug seam, and the thing the reduced-motion verification asserts is
   * absent: `window.__lenis === undefined` under `reduce` is a one-line proof
   * that the refusal happened, checkable from a console with no build step. */
  (window as Window & { __lenis?: Lenis }).__lenis = lenis;

  /* ── ScrollTrigger, on the same clock ─────────────────────────────────── */

  /* Wrapped rather than passed by reference: Lenis calls its scroll listeners
   * with the instance, and ScrollTrigger.update's first argument is a `force`
   * flag. It only escalates on a literal `true`, so passing the instance is
   * harmless today — and would stop being harmless the day that check loosens. */
  const stopScrollTriggerSync = lenis.on('scroll', () => ScrollTrigger.update());

  const tick = (time: number) => {
    /* REPAIR 2 AND 3, both, in one exact test — see adoptForeignScroll below. */
    adoptForeignScroll();
    /* gsap.ticker reports seconds; Lenis wants milliseconds. */
    lenis.raf(time * 1000);
  };

  /**
   * REPAIR 2 (FIND-IN-PAGE) and REPAIR 3's scroll half (FOCUS SCROLL), and
   * everything else that moves the page without asking us.
   *
   * The rule is exact rather than heuristic. Lenis ends every frame with
   * setScroll(), which writes window.scrollTop synchronously, so at the START
   * of the next frame window.scrollY EQUALS lenis.animatedScroll to within
   * device-pixel rounding. Any larger difference was written by someone else
   * between the two frames: Ctrl+F jumping to a match, the browser scrolling a
   * newly-focused control into view, an extension, a scroll restoration. Adopt
   * it, and Lenis continues from where the reader actually is.
   *
   * This is checked per frame rather than on the 'scroll' event on purpose. A
   * scroll event fired during a smooth Lenis animation carries a position that
   * is legitimately behind animatedScroll by up to one frame of velocity — 100px
   * or more on a fast flick — so a drift test on that event cannot tell a find-
   * in-page jump from ordinary smoothing without a velocity-dependent fudge
   * factor. At frame boundaries there is no fudge factor: the two are equal, or
   * something else moved.
   */
  function adoptForeignScroll(): void {
    const actual = window.scrollY;
    if (Math.abs(actual - lenis.animatedScroll) <= DRIFT_PX) return;
    lenis.scrollTo(actual, { immediate: true, force: true, lock: false });
  }

  gsap.ticker.add(tick);
  /* GSAP's lag smoothing freezes its clock when a frame takes too long, which
   * on a scroll-linked page reads as the content sticking. Lenis's docs call
   * for 0 for the same reason. Restored on destroy. */
  gsap.ticker.lagSmoothing(0);

  /* ── REPAIR 1: IN-PAGE ANCHOR LINKS ──────────────────────────────────────
   * The page has exactly one: App.tsx's skip link, `a[href="#main"]`, pointing
   * at a tabIndex={-1} content box. Left alone, the native jump happens and
   * then Lenis's rAF restores its own target on the very next frame, so the
   * reader is put back where they were — the skip link silently doing nothing
   * being about the worst accessibility regression available.
   *
   * Two things have to happen and they are different things: SCROLL to the
   * target clear of the sticky bar, and MOVE FOCUS to it. Scrolling to an
   * element is not focusing it, and a skip link that scrolls without focusing
   * leaves the next Tab back at the top of the nav.
   *
   * The scroll is `immediate`. Native anchor navigation is instant, this page's
   * only anchor is an accessibility control, and animating it for 600ms would
   * put the reader's focus off screen for 600ms — focus and viewport must never
   * disagree. */
  let programmaticFocus = false;

  const handleAnchorClick = (event: MouseEvent) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    const start = event.target;
    if (!(start instanceof Element)) return;
    const anchor = start.closest('a[href]');
    if (!(anchor instanceof HTMLAnchorElement)) return;
    if (anchor.target && anchor.target !== '_self') return;

    let url: URL;
    try {
      url = new URL(anchor.href, window.location.href);
    } catch {
      return;
    }
    // Same document, and an actual fragment: anything else is navigation.
    if (url.origin !== window.location.origin) return;
    if (url.pathname !== window.location.pathname) return;
    if (url.search !== window.location.search) return;
    if (!url.hash || url.hash === '#') return;

    const id = decodeURIComponent(url.hash.slice(1));
    const target = document.getElementById(id);
    if (!target) return;

    event.preventDefault();
    lenis.scrollTo(target, { offset: -navHeight(), immediate: true, force: true });

    // preventScroll because the scroll has already been done, correctly, with
    // the nav offset the browser knows nothing about.
    programmaticFocus = true;
    try {
      target.focus({ preventScroll: true });
    } finally {
      programmaticFocus = false;
    }

    // The URL still has to change: back/forward and copy-link both depend on it,
    // and preventDefault took that away.
    if (window.location.hash !== url.hash) {
      window.history.pushState(null, '', url.hash);
    }
  };

  /* ── REPAIR 3: FOCUS SCROLL ──────────────────────────────────────────────
   * Tabbing to an off-screen control makes the browser scroll it into view
   * natively. adoptForeignScroll() already keeps Lenis from undoing that, so
   * this handler exists for the part adoption cannot fix: the browser scrolls
   * the control flush to the viewport edge, and at the top edge that is
   * underneath a 71px sticky bar. It re-places anything that is off screen or
   * behind the bar, with clearance, instantly — a keyboard user should never
   * watch an ease to find out where focus went. */
  const handleFocusIn = (event: FocusEvent) => {
    if (programmaticFocus) return;
    const el = event.target;
    if (!(el instanceof HTMLElement)) return;

    const viewport = window.innerHeight || document.documentElement.clientHeight;
    const nav = navHeight();
    const rect = el.getBoundingClientRect();
    // Zero-size targets are wrappers, not controls; moving the page for one
    // would be motion with no visible cause.
    if (rect.height === 0 && rect.width === 0) return;

    const hiddenAbove = rect.top < nav + FOCUS_MARGIN;
    const hiddenBelow = rect.bottom > viewport;
    if (!hiddenAbove && !hiddenBelow) return;

    lenis.scrollTo(el, {
      offset: -(nav + FOCUS_MARGIN),
      immediate: true,
      force: true,
    });
  };

  /* ── REPAIR 4: PageUp / PageDown / Home / End ────────────────────────────
   * Lenis implements no keyboard scrolling at all. The browser's native key
   * scroll still runs, and adoptForeignScroll() would pick it up — but the
   * native step is measured against the viewport with no knowledge of the
   * sticky bar, and on a page with a scrubbed timeline the adoption reads as a
   * jump followed by a settle. Handling the keys directly gives them the same
   * smoothing every other scroll on the page has.
   *
   * Deliberately NOT handled: arrow keys and Space. Those are line-level and
   * often belong to whatever has focus; adoption already keeps them working. */
  const PAGE_KEYS = new Set(['PageUp', 'PageDown', 'Home', 'End']);

  const handleKeyDown = (event: KeyboardEvent) => {
    if (event.defaultPrevented) return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (!PAGE_KEYS.has(event.key)) return;

    const target = event.target;
    if (isTypingTarget(target)) return;
    // The horizontal lane in beat 3 is a role="group" tabIndex=0 element with
    // 135px of overflow at 375px that the keyboard user is meant to drive. Its
    // keys are its own.
    if (target instanceof Element && target.closest(preventSelector)) return;

    const viewport = window.innerHeight || document.documentElement.clientHeight;
    const page = Math.max(viewport - PAGE_OVERLAP, 1);

    let destination: number;
    switch (event.key) {
      case 'PageDown':
        // From targetScroll, not from the current position: pressing PageDown
        // three times fast must travel three pages, not repeatedly re-aim at
        // one page past wherever the animation happens to have reached.
        destination = lenis.targetScroll + page;
        break;
      case 'PageUp':
        destination = lenis.targetScroll - page;
        break;
      case 'Home':
        destination = 0;
        break;
      default:
        destination = document.documentElement.scrollHeight;
        break;
    }

    event.preventDefault();
    /* `programmatic: false` is load-bearing, and it was measured. Lenis's
     * scrollTo defaults to programmatic:true, which leaves targetScroll
     * tracking the ANIMATED position and only reaching the destination when the
     * ease finishes. Read back one frame after a PageDown, targetScroll was
     * still 1000 — so the branch above, which aims from targetScroll so that
     * three fast presses travel three pages, would have aimed from wherever the
     * previous ease had got to and the reader would lose most of the second and
     * third press. Non-programmatic sets targetScroll to the destination at
     * once, which is how Lenis's own wheel handling works. It also stops
     * defaulting lerp, hence passing it explicitly. */
    lenis.scrollTo(destination, {
      programmatic: false,
      lerp: lenis.options.lerp,
      force: true,
    });
  };

  document.addEventListener('click', handleAnchorClick);
  document.addEventListener('focusin', handleFocusIn);
  document.addEventListener('keydown', handleKeyDown);

  let destroyed = false;
  const handle: SmoothScrollHandle = {
    lenis,
    destroy: () => {
      if (destroyed) return;
      destroyed = true;

      document.removeEventListener('click', handleAnchorClick);
      document.removeEventListener('focusin', handleFocusIn);
      document.removeEventListener('keydown', handleKeyDown);

      /* ORDER IS THE BUG. Remove the ticker callback BEFORE destroying the
       * instance: a loop left running calls lenis.raf() on a destroyed Lenis,
       * whose dimensions and virtualScroll are already torn down, and it keeps
       * writing scrollTop forever — the page becomes unscrollable and nothing
       * in the stack trace says why. */
      gsap.ticker.remove(tick);
      /* GSAP's documented defaults, restored so an operator screen mounted
       * after this one does not inherit a setting the landing page needed. */
      gsap.ticker.lagSmoothing(500, 33);

      stopScrollTriggerSync();
      lenis.destroy();

      delete (window as Window & { __lenis?: Lenis }).__lenis;
      if (active === handle) active = null;

      /* Lenis leaves the reader wherever they were, but every ScrollTrigger
       * start was measured against a page it was smoothing. Re-measure once so
       * the next scroll is not one frame wrong. */
      ScrollTrigger.refresh();
    },
  };

  active = handle;
  return handle;
}

/**
 * Lenis, for the lifetime of the component that calls this.
 *
 * Constructed only when motion is allowed, destroyed when it stops being
 * allowed. The preference is a dependency rather than a one-time check, so a
 * reader who turns reduced motion on mid-session gets the browser's own scroll
 * back on the next tick — no reload, and every one of the four repairs above
 * becomes a no-op because with Lenis gone nothing was broken.
 *
 * Pass `enabled: false` to keep native scrolling for a reason of your own; the
 * landing page passes it when the beats scrub is not being built, because Lenis
 * exists on this page to serve that scrub and nothing else.
 */
export function useSmoothScroll(
  options: SmoothScrollOptions & { enabled?: boolean } = {},
): void {
  const allowed = useMotionAllowed();
  const { enabled = true, lerp, navSelector, preventSelector } = options;

  useEffect(() => {
    if (!allowed || !enabled) return;

    const opts: SmoothScrollOptions = {};
    if (lerp !== undefined) opts.lerp = lerp;
    if (navSelector !== undefined) opts.navSelector = navSelector;
    if (preventSelector !== undefined) opts.preventSelector = preventSelector;

    const handle = createSmoothScroll(opts);
    return () => handle.destroy();
  }, [allowed, enabled, lerp, navSelector, preventSelector]);
}
