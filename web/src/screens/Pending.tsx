import { ButtonLink, Icon, NAV_PATHS } from '../components';
import { useI18n } from '../i18n';
import type { TranslationKey } from '../i18n';
import './Pending.css';

/* A destination the rail names and nothing has been built behind yet.
 *
 * WHY THIS EXISTS AT ALL, RATHER THAN THE LINK SIMPLY NOT BEING THERE.
 * -------------------------------------------------------------------
 * components/Sidebar.tsx names six destinations. Two of them have screens --
 * Record and Account. The other four do not. There were three ways to handle
 * that and two of them are worse:
 *
 *   1. Drop the links until the screens land. The rail then disagrees with
 *      itself the moment one does, and the operator learns the shape of the
 *      product twice.
 *   2. Let the links fall through to App.tsx's catch-all. That sends a
 *      signed-in operator to the marketing page, which reads as a bug rather
 *      than as an absence -- and it is silent about which of the two it is.
 *   3. This: the route exists, is reachable, and says out loud that it is not
 *      built.
 *
 * (3) is the same rule the record's empty state already follows -- "Nothing is
 * shown here rather than something invented" -- applied one level up, to a
 * whole screen instead of a row. DESIGN-BRIEF 6 forbids claiming certainty the
 * system does not have; a placeholder chart, a greyed-out mock rack or a
 * "coming soon" spinner would all be exactly that claim about a screen.
 *
 * WHAT EACH PAGE SAYS. Not "coming soon" four times. Each names the thing that
 * is missing, and where the part of it that DOES exist lives today -- sessions
 * are already grouped on the record, formats are already listed on the account
 * screen, the demo already runs from the record's empty state. A reader leaves
 * knowing what they can do now, which a stub cannot tell them.
 *
 * NO DATE, NO ROADMAP, NO PROGRESS BAR. This project has been burned twice by
 * numbers nobody re-measured. "Q3" is a number nobody measured. */

export type PendingArea = 'live' | 'sessions' | 'formats';

/* `as const satisfies`, never an annotation: an annotation widens the values to
 * the whole TranslationKey union and t() then demands every placeholder in the
 * catalog. Same reason as CAPTURE_STATES in lib/api.ts. */
const TITLE = {
  live: 'route.pending.live.title',
  sessions: 'route.pending.sessions.title',
  formats: 'route.pending.formats.title',
} as const satisfies Record<PendingArea, TranslationKey>;

const BODY = {
  live: 'route.pending.live.body',
  sessions: 'route.pending.sessions.body',
  formats: 'route.pending.formats.body',
} as const satisfies Record<PendingArea, TranslationKey>;

export interface PendingProps {
  area: PendingArea;
}

export function Pending({ area }: PendingProps) {
  const { t } = useI18n();

  return (
    <section className="pending stack">
      <p className="pending__eyebrow mono">
        {/* 'info', not 'alert'. Nothing has gone wrong; a thing does not exist
            yet, and an alert glyph for an absence is the visual equivalent of
            over-claiming. */}
        <Icon name="info" size={16} />
        <span>{t('route.pending.eyebrow')}</span>
      </p>

      <h1 className="pending__title">{t(TITLE[area])}</h1>
      <p className="pending__body measure">{t(BODY[area])}</p>

      <p className="pending__go">
        <ButtonLink to={NAV_PATHS.record} variant="secondary">
          {t('route.pending.toRecord')}
        </ButtonLink>
      </p>
    </section>
  );
}
