import { NavLink } from 'react-router-dom';
import { Icon } from './Icon';
import type { IconName } from './Icon';
import { useI18n } from '../i18n';
import type { TranslationKey } from '../i18n';
import './Sidebar.css';

/* The signed-in navigation rail.
 *
 * ORDER IS THE OPERATOR'S DAY, NOT A FEATURE LIST. Live, then Record (with
 * Sessions indented under it), then Formats, then Demo, and Account alone in
 * the footer. The dashboard spec argues each position; the two that a builder
 * is most likely to "tidy" are the two that must not move:
 *
 *   Sessions is INDENTED UNDER RECORD, not a peer. A session is a container
 *   for captures and the captures are the thing. Promoting sessions to a peer
 *   inverts the hierarchy the whole product rests on -- an identifier outranks
 *   a session, a session outranks the account.
 *
 *   Demo stays in the nav rather than behind a link on the empty state. It is
 *   the only thing in the app that works with no API key, and a judge who has
 *   just signed up has to be able to find it without being told.
 *
 *
 * THE COLLAPSE, AND WHY IT IS NOT A DRAWER
 * ----------------------------------------
 * At >=1024px this is a 240px persistent rail. Below that it becomes the same
 * <nav>, the same links, in the same DOM order, laid out as a horizontal strip
 * that scrolls inside itself.
 *
 * It is not a hamburger drawer, and that is a decision rather than an omission:
 *
 *   1. There is already one navigation system on this app -- TopBar -- and it
 *      already owns a wrap rule that was written after a measured 473px
 *      scrollWidth in a 375px viewport. A second overlay nav is how the account
 *      screen and the record start disagreeing about where things live.
 *   2. A drawer is an overlay, an overlay needs a focus trap, and a focus trap
 *      is the single most common way a keyboard user gets stranded. Nothing
 *      here overlays anything, so there is nothing to trap and nothing to
 *      escape from. `Esc` has no job because no state was entered.
 *   3. A drawer hides the destinations behind a guess about what the icon
 *      means. The strip keeps all six visible or one flick away.
 *
 * The precedent is not invented: screens/Account.css:69-146 already ships this
 * exact shape (overflow-x strip below 960px, sticky column above it) and its
 * comment records the 663px document scrollWidth that the explicit
 * minmax(0, 1fr) track fixed. This file matches those numbers rather than
 * inventing new ones; the only deliberate difference is 240px/1024px instead
 * of 200px/960px, because a rail row here carries icon + label + a seven
 * character mono figure and 200px does not hold it.
 *
 *
 * ICON AND TEXT, ALWAYS BOTH
 * --------------------------
 * Every item ships a glyph AND a word. Icon-only navigation fails twice here:
 * discoverability, and the fact that every glyph on this rail is the same grey
 * as every other one -- there is no colour on it at all -- so the label is the
 * only thing telling two destinations apart and it is load bearing rather than
 * decorative.
 *
 * Three of the six glyphs are borrowed from the capture-state set. That is
 * allowed and it is not a violation of THE SEMANTIC RULE in tokens.css,
 * because what carries state meaning is the TRIPLE colour+icon+word, and a nav
 * item never forms it: these icons inherit the row's own grey here, never a
 * state colour, and the word beside them is a destination, not a state. No new
 * icon family was added; the brief says five glyphs, and it stays five.
 *
 *
 * THE CURRENT ITEM IS MARKED FOUR WAYS
 * ------------------------------------
 * Colour cannot carry it alone. Under the old palette that was because the four
 * state hues collapsed to one grey; under the new one it is because the rail
 * has no state hues at all -- the accent is spent on the asked state, and a
 * navigation rail is not asking anybody anything. So the current destination
 * carries:
 *
 *   1. aria-current="page"          (the assistive path)
 *   2. font-weight 500 -> 600       (weight)
 *   3. a tone step, --text-body (10.01:1 -> 16.83:1 on --surface, computed
 *      --text                        WCAG 2.1; a luminance step greyscale and a
 *                                    monochrome print both keep)
 *   4. a 3px --accent rule          (a shape, and a position: left edge on the
 *                                    rail, bottom edge in the strip -- same
 *                                    grammar as TopBar's [aria-current] rule)
 *
 * A fifth, the --bg fill, is deliberately the weakest of them at 1.09:1: a
 * white panel cannot carry a row state in a fill and this one does not pretend
 * to. Sidebar.css has the whole ladder.
 *
 * NavLink's `end` is set on Record so that standing on /record/sessions marks
 * exactly one item. Two things claiming to be the current page is worse than
 * an ancestor going unmarked, and the indent already says where Sessions sits.
 *
 *
 * THE ONE FIGURE
 * --------------
 * Beside Record, in mono --text-meta --text-2: 117/146. Not a badge, not a dot,
 * not coloured, not animated, and it does not appear when something happens --
 * it is always there or it is not there at all. DESIGN-BRIEF §6 forbids
 * attention-seeking during a live call and this rail is on screen during
 * calls; a count that appears on an event is a toast wearing a smaller coat.
 *
 * It renders ONLY when the caller passes a real total. There is no placeholder,
 * no 0/0 and no skeleton: nothing on screen may be fake, and a denominator
 * nobody measured is the easiest fake in the product.
 */

// ------------------------------------------------------------------ paths --
/* Exported so the agent wiring App.tsx has one place to read them from, rather
 * than two lists of strings that drift. These routes do not all exist yet; a
 * NavLink to a route the table has not got lands on the catch-all, which is
 * the correct behaviour until they do. */
export const NAV_PATHS = {
  live: '/live',
  record: '/record',
  sessions: '/record/sessions',
  formats: '/formats',
  demo: '/demo',
  account: '/account',
} as const;

interface NavItem {
  path: string;
  labelKey: TranslationKey;
  icon: IconName;
  /** Match this path exactly. See the note about `end` on Record above. */
  end: boolean;
}

/* `as const satisfies` rather than a type annotation. An annotation widens
 * labelKey to the whole TranslationKey union, and t() then demands every
 * placeholder that appears anywhere in the catalog. Same reason as
 * CAPTURE_STATES in lib/api.ts and FAILURE_KEY in screens/Auth.tsx. */
const PRIMARY = [
  // The screen that is open during a call. 'heard' is the receiving glyph.
  { path: NAV_PATHS.live, labelKey: 'nav.live', icon: 'heard', end: false },
  // Where everyone who is not on a call lands. 'settled' is written-down.
  { path: NAV_PATHS.record, labelKey: 'nav.record', icon: 'settled', end: true },
  { path: NAV_PATHS.formats, labelKey: 'nav.formats', icon: 'shield', end: false },
  // The one nav item that is an action -- "run the demo call" -- so it takes
  // the arrow rather than a noun glyph.
  { path: NAV_PATHS.demo, labelKey: 'nav.demo', icon: 'arrow-right', end: false },
] as const satisfies readonly NavItem[];

// A session is a container for captures, so it takes the stacked-rectangles
// glyph and it sits one level in.
const SESSIONS = {
  path: NAV_PATHS.sessions,
  labelKey: 'nav.sessions',
  icon: 'copy',
  end: false,
} as const satisfies NavItem;

/* 'topbar.account', not a new 'nav.account'. It is the same word for the same
 * link to the same route, and the catalogs already carry two identical
 * "{n} captures" plural sets because somebody added a second one rather than
 * reusing the first. If the word changes it must change in both places, which
 * is exactly what sharing the key buys. */
const ACCOUNT = {
  path: NAV_PATHS.account,
  labelKey: 'topbar.account',
  icon: 'user',
  end: false,
} as const satisfies NavItem;

// ------------------------------------------------------------------- link --

function linkClass({ isActive }: { isActive: boolean }): string {
  return isActive ? 'sidebar__link sidebar__link--current' : 'sidebar__link';
}

export interface SidebarProps {
  /** The one figure the rail carries: identifiers written without the agent
   *  asking anybody anything, over the number of identifiers. Omit it until
   *  the pipeline has answered -- there is no placeholder, and a total of 0
   *  renders nothing rather than "0/0". */
  written?: { silent: number; total: number };
  className?: string;
}

export function Sidebar({ written, className }: SidebarProps) {
  const { t, n } = useI18n();

  const figure = written && written.total > 0 ? written : null;

  return (
    <nav
      className={className ? `sidebar ${className}` : 'sidebar'}
      aria-label={t('nav.sidebar.label')}
    >
      {/* The scroll container below 1024px. position: relative because the
          sr-only spans inside are absolutely positioned, and an unpositioned
          scroller lets them escape the clip and drag the document scrollWidth
          out past the viewport -- the failure Rack.css and Account.css both
          record having hit. */}
      <div className="sidebar__scroll">
        <ul className="sidebar__list">
          {PRIMARY.map((item) => (
            <li className="sidebar__item" key={item.path}>
              <NavLink to={item.path} end={item.end} className={linkClass}>
                <Icon name={item.icon} size={16} />
                <span className="sidebar__label">{t(item.labelKey)}</span>

                {item.path === NAV_PATHS.record && figure ? (
                  <>
                    {/* Two spellings of one fact. The mono fraction is for the
                        eye; a screen reader gets the sentence, because
                        "117 slash 146" is not a sentence. */}
                    <span className="sidebar__figure mono" aria-hidden="true">
                      {n(figure.silent)}/{n(figure.total)}
                    </span>
                    <span className="sr-only">
                      {t('nav.record.silent', {
                        silent: n(figure.silent),
                        total: n(figure.total),
                      })}
                    </span>
                  </>
                ) : null}
              </NavLink>

              {/* Sessions is a nested list, so the containment is in the
                  markup and not only in the indent. A screen reader announces
                  a list of one inside the Record item; sighted users get the
                  rule and the inset. */}
              {item.path === NAV_PATHS.record ? (
                <ul className="sidebar__sub">
                  <li className="sidebar__item">
                    <NavLink to={SESSIONS.path} end={SESSIONS.end} className={linkClass}>
                      <Icon name={SESSIONS.icon} size={16} />
                      <span className="sidebar__label">{t(SESSIONS.labelKey)}</span>
                    </NavLink>
                  </li>
                </ul>
              ) : null}
            </li>
          ))}
        </ul>

        {/* Last, and separated. Nobody comes here to do their job. */}
        <ul className="sidebar__list sidebar__list--foot">
          <li className="sidebar__item">
            <NavLink to={ACCOUNT.path} end={ACCOUNT.end} className={linkClass}>
              <Icon name={ACCOUNT.icon} size={16} />
              <span className="sidebar__label">{t(ACCOUNT.labelKey)}</span>
            </NavLink>
          </li>
        </ul>
      </div>
    </nav>
  );
}
