import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import type { SidebarProps } from './Sidebar';
import './AppShell.css';

/* The persistent layout for the signed-in app: the rail, and the thing the
 * rail navigates.
 *
 * WHAT THIS COMPONENT IS NOT. It does not render TopBar, it does not render
 * <main>, and it does not own the skip link. App.tsx's Shell() already has all
 * three and they work; a second copy of any of them is two navigation systems
 * on one app, which is how the account screen and the record start disagreeing
 * about where things live. This is the two-track grid and nothing else, so
 * that wiring it in is one JSX change and one prop.
 *
 *
 * HOW TO WIRE IT (the agent that owns App.tsx)
 * --------------------------------------------
 * Wrap the outlet, keeping .shell__main as the centred .page box it already
 * is, and MOVE the skip target off <main>:
 *
 *     <main className="shell__main page">          // id and tabIndex removed
 *       <AppShell written={...}>
 *         <Outlet context={context} />
 *       </AppShell>
 *     </main>
 *
 * The move matters. base.css's .skip-link points at #main, and if #main stays
 * on <main> then "skip to content" lands the keyboard user just before six nav
 * links -- which is the exact thing the skip link exists to jump over. AppShell
 * puts id="main" tabIndex={-1} on the CONTENT track instead, so the skip link
 * keeps meaning what it says.
 *
 * Because that is an edit somebody has to remember, there is a DEV-only
 * tripwire below that names the problem out loud if both ids survive. It is
 * modelled on the identifier tripwire in Rack.tsx: a check that costs nothing
 * in production and refuses to let a silent regression ship.
 *
 * AppShell is opt-in per route. Landing and the auth screens do not take it --
 * there is nothing to navigate to yet and a rail beside a signup form is
 * furniture.
 *
 *
 * WHY THE GRID SITS INSIDE <main> RATHER THAN BESIDE IT
 * ----------------------------------------------------
 * .shell__main already carries .page: max-width 1120px, centred, with the 16px
 * / 24px gutters. Putting the rail inside it means the rail inherits the
 * measure and the gutters for free and every existing screen keeps centring
 * exactly where it does today. The alternative -- a full-bleed rail in a
 * wrapper between TopBar and <main> -- centres the content column inside the
 * REMAINING width, which visually shifts every screen in the app sideways to
 * pay for a rail on one of them.
 *
 * THE TRACK IS minmax(0, 1fr) AND NOT 1fr. body has overflow-x: clip, so an
 * overflowing grid item is not scrollable, it is unreachable. A grid item's
 * automatic minimum size is its max-content width, so the implied 1fr track
 * sizes itself to the widest identifier lane on the record and pushes the page
 * out from under the viewport. Account.css:69-81 records the measurement that
 * cost: 663px document scrollWidth in a 375px viewport. */

export interface AppShellProps {
  children: ReactNode;
  /** Forwarded to the rail's one figure: identifiers written without the agent
   *  asking anybody anything, over the number of identifiers. Omit it until
   *  the pipeline has answered; nothing is rendered in its place. */
  written?: SidebarProps['written'];
  /** The skip-link target. Defaults to 'main', which is what base.css's
   *  .skip-link points at. Pass something else only if App.tsx keeps #main on
   *  <main> on purpose. */
  contentId?: string;
  className?: string;
}

export function AppShell({ children, written, contentId = 'main', className }: AppShellProps) {
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const clashes = document.querySelectorAll(`#${CSS.escape(contentId)}`).length;
    if (clashes > 1) {
      console.error(
        `AppShell: ${clashes} elements share id="${contentId}". The skip link ` +
          `resolves to the first one, which is <main>, so "skip to content" now ` +
          `lands before the navigation rail instead of after it. Remove ` +
          `id="${contentId}" tabIndex={-1} from <main> in App.tsx and let ` +
          `AppShell carry it.`,
      );
    }
  }, [contentId]);

  return (
    <div className={className ? `appshell ${className}` : 'appshell'}>
      {/* First in the DOM as well as first on the screen. A rail that is
          visually left but read last is a different product for a screen
          reader than it is for everyone else. */}
      <Sidebar {...(written ? { written } : {})} />

      {/* tabIndex={-1} so the skip link can actually move focus here; a plain
          id only moves the scroll position, and the next Tab would go back to
          the top of the document. */}
      <div className="appshell__content" id={contentId} tabIndex={-1}>
        {children}
      </div>
    </div>
  );
}
