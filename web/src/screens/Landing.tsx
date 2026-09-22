import { ButtonLink, NAV_PATHS, Rack, SlotStrip, asked, locked, repaired, settled } from '../components';
import type { RackRow } from '../components';
import { landingChoreography } from '../animations/landing';
import { useGsapContext } from '../lib/useGsapContext';
import { useI18n } from '../i18n';
import type { I18n } from '../i18n';
import './Landing.css';

/* The landing page. One argument, told once and in order:
 *
 *   hero    the sentence, and the rack that proves it
 *   how     three steps, one figure
 *   gain    the measured number
 *   limit   what it cannot see
 *   close   the ask
 *
 * Nothing on it is a figure typed into markup. Every number is a constant
 * below with its source in docs/, interpolated through the pinned locale, so a
 * translation cannot change a claim. Identifier characters and format names
 * never pass through a catalog: a localised container number reads as a fake.
 */

// -------------------------------------------------------- measured figures --

/** docs/EXPERIMENT.md, README.md -- the error budget, constrained / not. */
const GAIN_ISO = 14.9;
const GAIN_IBAN = 17.1;
/** docs/FINDINGS.md §8 -- the headline figure. */
const GAIN_HEADLINE = 15;
/** docs/FINDINGS.md §8 -- what knowing the accent is worth. */
const ACCENT_VALUE = 0.002;
/** docs/FINDINGS.md §4 -- confusion weight blind to the ISO check digit. */
const BLIND_SHARE = 5.3;

/* The ratio bar is the 15x drawn to scale, computed rather than typed. */
const UNCONSTRAINED_WIDTH = `${(100 / GAIN_HEADLINE).toFixed(1)}%`;

// ---------------------------------------------------------------- the rack --

/* CSQU3054383, a published ISO 6346 vector (docs/FINDINGS.md §1). The
 * recogniser heard 9 in position 7; the speaker read check digit 3, and 3 is
 * reachable only from a 5 there. The whole product in one row. */
const CSQU_HEAD = 'CSQU30';
const CSQU_TAIL = '438';
const REPAIR_POSITION = 7;
const HEARD_DIGIT = '9';
const WRITTEN_DIGIT = '5';
const SPOKEN_CHECK = '3';

/* MSBU4653011 and MSVU4653011 are both valid: B is 12, V is 34, congruent mod
 * 11, so the check digit cannot separate them -- the row the agent interrupts
 * for. NATO words are English data, quoted rather than translated. */
const ASK_POSITION = 3;
const ASK_A = 'B';
const ASK_A_WORD = 'Bravo';
const ASK_B = 'V';
const ASK_B_WORD = 'Victor';
const ASK_CHECK = '1';

/** MSKU6111115 -- docs/FINDINGS.md §1 records the day this was 9 by mistake. */
const SETTLED_BODY = 'MSKU611111';
const SETTLED_CHECK = '5';

/* The figure under the three steps: the repaired number, whole, with its check
 * digit locked. The spoken label is derived so the two cannot drift. */
const STRIP_BODY = `${CSQU_HEAD}${WRITTEN_DIGIT}${CSQU_TAIL}`;
const STRIP_SPOKEN = [...STRIP_BODY].join(' ');
const ISO_FORMULA = 'check = sum(value(c) · 2^i) mod 11 mod 10';

function heroRows({ t, n }: I18n): RackRow[] {
  return [
    {
      id: 'csqu',
      format: 'ISO 6346',
      state: 'repaired',
      slots: [
        ...settled(CSQU_HEAD),
        repaired(HEARD_DIGIT, WRITTEN_DIGIT),
        ...settled(CSQU_TAIL),
        ...locked(SPOKEN_CHECK),
      ],
      questions: 0,
      note: t('landing.row.repaired.note', {
        position: n(REPAIR_POSITION),
        heard: HEARD_DIGIT,
        written: WRITTEN_DIGIT,
        check: SPOKEN_CHECK,
      }),
    },
    {
      id: 'msbu',
      format: 'ISO 6346',
      state: 'asking',
      slots: [...settled('MS'), asked(ASK_A), ...settled('U465301'), ...locked(ASK_CHECK)],
      questions: 1,
      question: t('landing.row.asking.question', {
        position: n(ASK_POSITION),
        a: ASK_A,
        aWord: ASK_A_WORD,
        b: ASK_B,
        bWord: ASK_B_WORD,
        check: ASK_CHECK,
      }),
      note: t('landing.row.asking.note'),
    },
    {
      id: 'msku',
      format: 'ISO 6346',
      state: 'settled',
      slots: [...settled(SETTLED_BODY), ...locked(SETTLED_CHECK)],
      questions: 0,
      note: t('landing.row.settled.note', { check: SETTLED_CHECK }),
    },
  ];
}

// ------------------------------------------------------------------- page --

export function Landing() {
  const i18n = useI18n();
  const { t, n, plural } = i18n;

  const rows = heroRows(i18n);
  const questions = rows.reduce((total, row) => total + row.questions, 0);
  const rackMeta = `${plural('landing.rack.meta.captures', rows.length)} · ${plural(
    'landing.rack.meta.questions',
    questions,
  )}`;

  /* Motion is transform-only and never hides text; it is not created at all
   * under reduced motion. Start points are pixel positions, so they are
   * re-measured when the language changes the wrap. */
  const root = useGsapContext<HTMLDivElement>(landingChoreography, {
    refreshOn: [i18n.language],
  });

  const steps = [
    { title: t('landing.how.step1.title'), body: t('landing.how.step1.body') },
    { title: t('landing.how.step2.title'), body: t('landing.how.step2.body') },
    {
      title: t('landing.how.step3.title'),
      body: t('landing.how.step3.body', { position: n(REPAIR_POSITION) }),
    },
  ];

  return (
    <div className="landing" ref={root}>
      <section className="hero" aria-labelledby="hero-title">
        {/* Two clauses, two block spans: the pivot is a line break in every
            language and in both motion modes. */}
        <h1 className="hero__title" id="hero-title">
          <span className="hero__title-a">{t('landing.hero.title.a')}</span>{' '}
          <span className="hero__title-b">{t('landing.hero.title.b')}</span>
        </h1>

        <div className="hero__support">
          <p className="hero__lede">{t('landing.hero.lede')}</p>
          <p className="hero__scope">{t('landing.hero.scope')}</p>
          <div className="hero__actions">
            {/* One action: the demo runs without an account, so every visitor
                can take it. Log in and Get a key are already in the bar. */}
            <ButtonLink to={NAV_PATHS.demo} variant="primary">
              {t('landing.hero.demo')}
            </ButtonLink>
          </div>
        </div>

        <Rack className="hero__rack" title={t('landing.rack.title')} meta={rackMeta} rows={rows} />
      </section>

      <section className="how" aria-labelledby="how-title">
        <h2 className="sr-only" id="how-title">
          {t('landing.how.title')}
        </h2>
        <ol className="how__steps">
          {steps.map((step) => (
            <li className="how__step" key={step.title}>
              <h3 className="how__title">{step.title}</h3>
              <p className="how__body">{step.body}</p>
            </li>
          ))}
        </ol>
        <figure className="how__figure">
          <SlotStrip
            slots={[...settled(STRIP_BODY), ...locked(SPOKEN_CHECK)]}
            label={t('landing.how.stripLabel', { spoken: STRIP_SPOKEN, check: SPOKEN_CHECK })}
          />
          <figcaption className="how__formula" translate="no" dir="ltr" lang="en">
            {ISO_FORMULA}
          </figcaption>
        </figure>
      </section>

      <section className="gain" aria-labelledby="gain-title">
        <p className="gain__figure" aria-hidden="true">{`${n(GAIN_HEADLINE)}×`}</p>
        <h2 className="gain__title" id="gain-title">
          {t('landing.gain.title')}
        </h2>
        <p className="gain__body">
          {t('landing.gain.body', {
            iso: n(GAIN_ISO),
            iban: n(GAIN_IBAN),
            value: n(ACCENT_VALUE),
          })}
        </p>
        <div className="ratios" aria-hidden="true">
          <div className="ratio">
            <span className="ratio__label">{t('landing.gain.ratio.unconstrained')}</span>
            <span className="ratio__track">
              <span className="ratio__fill" style={{ width: UNCONSTRAINED_WIDTH }} />
            </span>
            <span className="ratio__value">{`${n(1)}×`}</span>
          </div>
          <div className="ratio">
            <span className="ratio__label">{t('landing.gain.ratio.constrained')}</span>
            <span className="ratio__track">
              <span className="ratio__fill" style={{ width: '100%' }} />
            </span>
            <span className="ratio__value">{`${n(GAIN_HEADLINE)}×`}</span>
          </div>
        </div>
      </section>

      <section className="limit" aria-labelledby="limit-title">
        <h2 className="limit__title" id="limit-title">
          {t('landing.limit.title')}
        </h2>
        <p className="limit__body">{t('landing.limit.body', { share: n(BLIND_SHARE) })}</p>
      </section>

      <section className="close" aria-labelledby="close-title">
        <h2 className="close__title" id="close-title">
          {t('landing.close.title')}
        </h2>
        <p className="close__body">{t('landing.close.body')}</p>
        <ButtonLink to="/signup" variant="primary">
          {t('topbar.getKey')}
        </ButtonLink>
      </section>
    </div>
  );
}
