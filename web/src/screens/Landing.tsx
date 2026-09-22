import { Suspense, lazy, useCallback, useMemo, useRef } from 'react';
import type { ReactNode } from 'react';
import { motion, useInView } from 'motion/react';
import type { Variants } from 'motion/react';
import { ButtonLink, NAV_PATHS, Rack, SlotStrip, asked, locked, repaired, settled } from '../components';
import type { RackRow } from '../components';
import { FormatCarousel } from '../landing/FormatCarousel';
import { useI18n } from '../i18n';
import type { I18n } from '../i18n';
import { useMotionAllowed } from '../lib/motion-prefs';
import './Landing.css';

/* The landing page. One argument, told once and in order:
 *
 *   hero     the sentence, beside the number it is about, in 3D (three.js)
 *   rack     what the product writes down
 *   how      three steps
 *   formats  the five formats, one per slide (Swiper)
 *   gain     the measured error budget, drawn to scale (Chart.js)
 *   limit    what it cannot see
 *   close    the ask
 *
 * Motion (motion/react) carries every entrance. Nothing is ever hidden at rest:
 * text rises 16px and is never faded, so every frame is readable, and under
 * reduced motion nothing moves at all.
 *
 * Every number is a constant below with its source in docs/, interpolated
 * through the pinned locale, so a translation cannot change a claim.
 * Identifier characters never pass through a catalog. three.js and Chart.js
 * are loaded lazily, after the text, so the sentence is never waiting on a
 * WebGL context. */

const ContainerScene = lazy(() => import('../landing/ContainerScene'));
const GainChart = lazy(() => import('../landing/GainChart'));

// -------------------------------------------------------- measured figures --

/** docs/EXPERIMENT.md, README.md -- the error budget, unconstrained / constrained. */
const BUDGET_ISO = { from: 0.0047, to: 0.0692 } as const;
const BUDGET_IBAN = { from: 0.0023, to: 0.0399 } as const;
const GAIN_ISO = 14.9;
const GAIN_IBAN = 17.1;
/** docs/FINDINGS.md §8 -- the headline figure. */
const GAIN_HEADLINE = 15;
/** docs/FINDINGS.md §8 -- what knowing the accent is worth. */
const ACCENT_VALUE = 0.002;
/** docs/FINDINGS.md §4 -- confusion weight blind to the ISO check digit. */
const BLIND_SHARE = 5.3;

// ---------------------------------------------------------------- the rack --

/* CSQU3054383, a published ISO 6346 vector (docs/FINDINGS.md §1). The
 * recogniser heard 9 in position 7; the speaker read check digit 3, and 3 is
 * reachable only from a 5 there. The whole product in one row -- and in the
 * hero's three.js scene, which is built from these same constants. */
const CSQU_HEAD = 'CSQU30';
const CSQU_TAIL = '438';
const REPAIR_POSITION = 7;
const HEARD_DIGIT = '9';
const WRITTEN_DIGIT = '5';
const SPOKEN_CHECK = '3';
const CSQU = `${CSQU_HEAD}${WRITTEN_DIGIT}${CSQU_TAIL}${SPOKEN_CHECK}`;
const CSQU_CHECK_POSITIONS = [10] as const;

/* MSBU4653011 / MSVU4653011: B is 12, V is 34, congruent mod 11 -- the check
 * digit cannot separate them, so this is the row the agent interrupts for. */
const ASK_POSITION = 3;
const ASK_A = 'B';
const ASK_A_WORD = 'Bravo';
const ASK_B = 'V';
const ASK_B_WORD = 'Victor';
const ASK_CHECK = '1';

/** MSKU6111115 -- docs/FINDINGS.md §1 records the day this was 9 by mistake. */
const SETTLED_BODY = 'MSKU611111';
const SETTLED_CHECK = '5';

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

// ------------------------------------------------------------------ motion --

/* One gesture, one distance: rise 16px, ease out. Transform only -- text is
 * never faded, so every frame is readable and a stalled animation leaves the
 * finished page. */
const EASE = [0.2, 0, 0, 1] as const;
const rise: Variants = {
  hidden: { y: 16 },
  shown: { y: 0, transition: { duration: 0.5, ease: EASE } },
};
const stagger: Variants = {
  hidden: {},
  shown: { transition: { staggerChildren: 0.12 } },
};

/** A section that rises into place when it scrolls into view, once. */
function Reveal({
  children,
  className,
  as = 'section',
  labelledBy,
}: {
  children: ReactNode;
  className: string;
  as?: 'section' | 'div';
  labelledBy?: string;
}) {
  const moving = useMotionAllowed();
  const Tag = as === 'section' ? motion.section : motion.div;
  return (
    <Tag
      className={className}
      {...(labelledBy ? { 'aria-labelledby': labelledBy } : {})}
      variants={rise}
      initial={moving ? 'hidden' : false}
      whileInView="shown"
      viewport={{ once: true, margin: '0px 0px -12% 0px' }}
    >
      {children}
    </Tag>
  );
}

// ------------------------------------------------------------------- page --

export function Landing() {
  const i18n = useI18n();
  const { t, n, plural } = i18n;
  const moving = useMotionAllowed();

  const rows = heroRows(i18n);
  const questions = rows.reduce((total, row) => total + row.questions, 0);
  const rackMeta = `${plural('landing.rack.meta.captures', rows.length)} · ${plural(
    'landing.rack.meta.questions',
    questions,
  )}`;

  /* The rack plays its own keyframes (motion.css) once, when it is actually
   * on screen: on mount it would play to an empty seat below the fold. */
  const rackRef = useRef<HTMLDivElement>(null);
  const rackSeen = useInView(rackRef, { once: true, margin: '0px 0px -15% 0px' });

  const steps = [
    { title: t('landing.how.step1.title'), body: t('landing.how.step1.body') },
    { title: t('landing.how.step2.title'), body: t('landing.how.step2.body') },
    {
      title: t('landing.how.step3.title'),
      body: t('landing.how.step3.body', { position: n(REPAIR_POSITION) }),
    },
  ];

  const series = useMemo(
    () => [
      { label: 'ISO 6346', unconstrained: BUDGET_ISO.from, constrained: BUDGET_ISO.to },
      { label: 'IBAN', unconstrained: BUDGET_IBAN.from, constrained: BUDGET_IBAN.to },
    ],
    [],
  );
  const formatRate = useCallback((value: number) => n(value), [n]);

  const staticStrip = (
    <SlotStrip
      className="hero__strip"
      slots={[...settled(CSQU_HEAD), repaired(HEARD_DIGIT, WRITTEN_DIGIT), ...settled(CSQU_TAIL), ...locked(SPOKEN_CHECK)]}
      label={t('landing.scene.label', {
        position: n(REPAIR_POSITION),
        heard: HEARD_DIGIT,
        written: WRITTEN_DIGIT,
        check: SPOKEN_CHECK,
      })}
    />
  );

  return (
    <div className="landing">
      <section className="hero" aria-labelledby="hero-title">
        <motion.div
          className="hero__text"
          variants={stagger}
          initial={moving ? 'hidden' : false}
          animate="shown"
        >
          {/* Two clauses, two block spans: the pivot is a line break in every
              language and in both motion modes. */}
          <h1 className="hero__title" id="hero-title">
            <motion.span className="hero__title-a" variants={rise}>
              {t('landing.hero.title.a')}
            </motion.span>{' '}
            <motion.span className="hero__title-b" variants={rise}>
              {t('landing.hero.title.b')}
            </motion.span>
          </h1>
          <motion.div className="hero__support" variants={rise}>
            <p className="hero__lede">{t('landing.hero.lede')}</p>
            <p className="hero__scope">{t('landing.hero.scope')}</p>
            <div className="hero__actions">
              {/* One action: the demo runs without an account. Log in and Get
                  a key are already in the bar. */}
              <ButtonLink to={NAV_PATHS.demo} variant="primary">
                {t('landing.hero.demo')}
              </ButtonLink>
            </div>
          </motion.div>
        </motion.div>

        <div className="hero__visual">
          <Suspense fallback={staticStrip}>
            <ContainerScene
              written={CSQU}
              repairIndex={REPAIR_POSITION - 1}
              heard={HEARD_DIGIT}
              checkPositions={CSQU_CHECK_POSITIONS}
              label={t('landing.scene.label', {
                position: n(REPAIR_POSITION),
                heard: HEARD_DIGIT,
                written: WRITTEN_DIGIT,
                check: SPOKEN_CHECK,
              })}
              fallback={staticStrip}
            />
          </Suspense>
          {/* The scene's accessible name already says this; the visible line
              is for the eye, which cannot be expected to decode a turning tile
              unaided. */}
          <p className="scene__caption" aria-hidden="true">
            {t('landing.row.repaired.note', {
              position: n(REPAIR_POSITION),
              heard: HEARD_DIGIT,
              written: WRITTEN_DIGIT,
              check: SPOKEN_CHECK,
            })}
          </p>
        </div>
      </section>

      <Reveal as="div" className="rack-wrap">
        <div ref={rackRef}>
          <Rack
            className={rackSeen ? 'hero__rack rack--animate' : 'hero__rack'}
            title={t('landing.rack.title')}
            meta={rackMeta}
            rows={rows}
          />
        </div>
      </Reveal>

      <section className="how" aria-labelledby="how-title">
        <h2 className="sr-only" id="how-title">
          {t('landing.how.title')}
        </h2>
        <motion.ol
          className="how__steps"
          variants={stagger}
          initial={moving ? 'hidden' : false}
          whileInView="shown"
          viewport={{ once: true, margin: '0px 0px -12% 0px' }}
        >
          {steps.map((step) => (
            <motion.li className="how__step" key={step.title} variants={rise}>
              <h3 className="how__title">{step.title}</h3>
              <p className="how__body">{step.body}</p>
            </motion.li>
          ))}
        </motion.ol>
      </section>

      <Reveal className="formats-section" labelledBy="formats-title">
        <h2 className="section__title" id="formats-title">
          {t('landing.formats.title')}
        </h2>
        <FormatCarousel />
      </Reveal>

      <Reveal className="gain" labelledBy="gain-title">
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
        <Suspense fallback={<div className="chart" />}>
          <GainChart
            series={series}
            unconstrainedLabel={t('landing.gain.ratio.unconstrained')}
            constrainedLabel={t('landing.gain.ratio.constrained')}
            axisLabel={t('landing.chart.axis')}
            format={formatRate}
            label={t('landing.chart.label', {
              isoFrom: n(BUDGET_ISO.from),
              isoTo: n(BUDGET_ISO.to),
              ibanFrom: n(BUDGET_IBAN.from),
              ibanTo: n(BUDGET_IBAN.to),
            })}
          />
        </Suspense>
      </Reveal>

      <Reveal className="limit" labelledBy="limit-title">
        <h2 className="limit__title" id="limit-title">
          {t('landing.limit.title')}
        </h2>
        <p className="limit__body">{t('landing.limit.body', { share: n(BLIND_SHARE) })}</p>
      </Reveal>

      <Reveal className="close" labelledBy="close-title">
        <h2 className="close__title" id="close-title">
          {t('landing.close.title')}
        </h2>
        <p className="close__body">{t('landing.close.body')}</p>
        <ButtonLink to="/signup" variant="primary">
          {t('topbar.getKey')}
        </ButtonLink>
      </Reveal>
    </div>
  );
}
