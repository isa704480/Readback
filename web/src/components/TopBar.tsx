import { useEffect, useState, useSyncExternalStore } from 'react';
import { NavLink } from 'react-router-dom';
import { Icon, Logo } from './Icon';
import { ButtonLink } from './Button';
import { getSnapshot, subscribe } from '../lib/session';
import type { Account } from '../lib/session';
import { LanguageSwitcher, useI18n } from '../i18n';
import './TopBar.css';

export interface TopBarProps {
  /** Supply once /api/auth/me has answered, to show who is signed in. The bar
   *  does not fetch it: sign-in state comes from the token, which is
   *  synchronous, so the bar never flashes signed-out on a reload. */
  account?: Account | null;
}

export function TopBar({ account }: TopBarProps) {
  const { t } = useI18n();

  // The token lives outside React, and it changes from other tabs as well as
  // from this one. Subscribing keeps the bar honest without a context provider.
  const token = useSyncExternalStore(subscribe, getSnapshot, () => null);
  const signedIn = token !== null;

  /* THE SCROLL EDGE.
   *
   * The bar is sticky and translucent, so at the top of an unscrolled page it
   * sits flush on the ground and draws no line -- there is nothing underneath
   * it to be separated from. The hairline and its 1px contact shadow appear
   * only once content is genuinely beneath it. That is the whole state this
   * boolean carries; the appearance is entirely in tokens.css's .glass-nav /
   * .glass-nav.is-scrolled pair.
   *
   * 8px, not 0: at 0 the class flips on and off on every sub-pixel scroll
   * restoration and on the elastic overscroll iOS produces at the top of a
   * page, which is a line flickering under a bar during a call.
   *
   * The listener is passive -- it never calls preventDefault, and saying so
   * lets the browser scroll without waiting to find out. The state write is
   * gated on an actual change, so a scroll gesture writes once per crossing
   * rather than once per frame. Read once on mount as well, because a reload
   * restores scroll position before this effect runs and the bar would
   * otherwise draw itself flush over content it is sitting on top of. */
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const sync = () => {
      const next = window.scrollY > 8;
      setScrolled((prev) => (prev === next ? prev : next));
    };

    sync();
    window.addEventListener('scroll', sync, { passive: true });
    return () => window.removeEventListener('scroll', sync);
  }, []);

  return (
    /* glass-nav is the recipe (tokens.css); .topbar is the position and the
       type. The two are separate classes on purpose -- the material is a system
       decision and this component only says "I am the surface it belongs on". */
    <header className={`topbar glass-nav${scrolled ? ' is-scrolled' : ''}`}>
      <div className="topbar__inner page">
        {/* "Readback" is the product's name, not a word. It is deliberately not
            in the catalog and does not change with the interface language. */}
        <NavLink to="/" className="topbar__brand">
          <Logo size={26} />
          Readback
        </NavLink>

        {/* SIGN OUT IS NOT HERE. It moved to the account screen's own action
            row, beside Refresh, because that is where a session belongs and the
            bar was carrying six things.

            It MOVED rather than went: this was the only sign-out in the app, and
            deleting it would have left no way out at all — the one thing the
            wayfinding rules say an interface must never do. The account screen
            is one click from anywhere, via the organisation name to the left and
            via the sidebar. */}
        <nav className="topbar__nav" aria-label={t('topbar.nav.label')}>
          {signedIn ? (
            <>
              {/* ONE control, where there used to be two. The bar carried the
                  organisation's name as inert text AND a separate "Account"
                  link to the same destination — two answers to one question,
                  and the inert one could not show that you were already on the
                  page it pointed at. The name is now the link: it says which
                  account you are in and how to reach it with the same thing,
                  and it takes aria-current like any other nav item.

                  The sidebar owns navigation once you are signed in, so this is
                  the only nav item the bar still needs — and it has to stay,
                  because the landing page has no sidebar. */}
              <NavLink to="/account" className="topbar__who topbar__link">
                <Icon name="building" size={16} />
                <span className="topbar__who-name">
                  {account?.organisation.name ?? account?.name ?? t('topbar.signedIn')}
                </span>
                {/* The visible text is a company name, which does not say where
                    the link goes. This does, for a reader who cannot see that
                    it sits in the account corner of the bar. */}
                {/* Leading space so the accessible name reads "Docks Ltd Account"
                    and not "Docks LtdAccount" — textContent concatenates, and
                    not every screen reader inserts a boundary. */}
                <span className="sr-only">{' '}{t('topbar.account')}</span>
              </NavLink>
            </>
          ) : (
            <>
              <NavLink to="/login" className="topbar__link">
                {t('topbar.logIn')}
              </NavLink>
              <ButtonLink to="/signup" variant="primary">
                {t('topbar.getKey')}
              </ButtonLink>
            </>
          )}

          {/* Last in the row. It is display:contents, so its honesty note lands
              as a sibling of these items and can take a row of its own instead
              of widening a flex item. See LanguageSwitcher.css. */}
          <LanguageSwitcher />
        </nav>
      </div>
    </header>
  );
}
