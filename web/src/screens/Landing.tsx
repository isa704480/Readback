import {
  ButtonLink,
  Rack,
  SlotStrip,
  asked,
  empty,
  locked,
  provisional,
  repaired,
  settled,
} from '../components';
import type { RackRow } from '../components';
import { landingChoreography } from '../animations/landing';
import { useGsapContext } from '../lib/useGsapContext';
import { useSmoothScroll } from '../lib/useSmoothScroll';
import { useI18n } from '../i18n';
import type { I18n } from '../i18n';
import './Landing.css';

/* The landing page.
 *
 * Two rules held the copy in place. First: lead with the mechanism. Everybody
 * selling into a contact centre opens with "your agents waste time"; the only
 * interesting sentence we have is the check digit, so it goes first. Second:
 * every number on this page is one that was measured. The three facts are in
 * README.md and docs/FINDINGS.md and nothing beyond them is claimed here.
 *
 * The container numbers below are real and were verified against the repo's own
 * validator, not typed from memory -- docs/FINDINGS.md records what happened the
 * last time a vector was written out by hand.
 *
 * ---------------------------------------------------------------------------
 * WHAT LOCALISATION IS AND IS NOT ALLOWED TO TOUCH HERE
 * ---------------------------------------------------------------------------
 * This screen carries the pitch, and it carries the page's only real risk of
 * lying in translation. Three lines hold:
 *
 * 1. FORMAT NAMES AND IDENTIFIER CHARACTERS NEVER CHANGE. "ISO 6346", "IBAN",
 *    "mod-97", "Luhn", "NHS", "VIN", every character of a container number and
 *    every cell of the check-digit sweep render byte-identical in all three
 *    interface languages. They are declared once as the constants below and
 *    reach the catalog only through placeholders, so no catalog file contains a
 *    character of a container number that a translator could retype. A judge
 *    who sees a localised container number concludes the demo is fake.
 *
 * 2. THE SPEECH PIPELINE IS ENGLISH AND THE PAGE SAYS SO. The agent listens in
 *    English and asks its one question in English. `landing.hero.scope` states
 *    that in every language INCLUDING English, and the demo row's question
 *    keeps the agent's actual English utterance as a quotation in uz and ru
 *    rather than passing a translation off as what the caller hears.
 *
 * 3. MEASURED NUMBERS ARE CONSTANTS, NOT PROSE. Everything with a figure in it
 *    -- 14.9x, 17.1x, +-0.002, 21 and 64 points, 5.3% -- lives in the block
 *    below with its source in docs/, is formatted through the pinned locale
 *    (so ru and uz get "14,9"), and is interpolated. Translating a sentence
 *    cannot change a claim, because the claim is not in the sentence.
 */

// -------------------------------------------------------- measured figures --
/* Every number rendered on this page, with where it was measured. Nothing on
 * screen is a figure typed straight into the markup. */

/** docs/ARCHITECTURE.md:45, docs/EXPERIMENT.md:33, README.md:33 */
const GAIN_ISO = 14.9;
/** docs/ARCHITECTURE.md:46, docs/EXPERIMENT.md:34, README.md:34 */
const GAIN_IBAN = 17.1;
/** docs/FINDINGS.md:433 -- "constraint multiplies it by 15x". The headline. */
const GAIN_HEADLINE = 15;
/** docs/FINDINGS.md:434 -- "Accents differ in ASR error rate by at most 2x". */
const ACCENT_SPREAD = 2;
/** docs/FINDINGS.md:435 -- knowing which accent is worth nothing (+-0.002). */
const ACCENT_VALUE = 0.002;
/** docs/FINDINGS.md:429, docs/ARCHITECTURE.md:29, docs/RED-TEAM.md:27 */
const SILENCE_ISO = 21;
const SILENCE_NHS = 64;
/** docs/FINDINGS.md:74 -- share of confusion weight blind to the check digit. */
const BLIND_SHARE = 5.3;

/* The ratio bar is the 15x drawn to scale: the unconstrained lane is 1/15th of
 * the constrained one. Computed rather than written as "6.7%", because a
 * hand-typed width is a number on the page with nothing behind it. */
const UNCONSTRAINED_WIDTH = `${(100 / GAIN_HEADLINE).toFixed(1)}%`;

// ---------------------------------------------------------------- the rack --

/* CSQU3054383 is a published ISO 6346 vector (docs/FINDINGS.md:18). The
 * recogniser returned 9 in position 7; the speaker read out check digit 3, and
 * 3 is only reachable from a 5 there. That is the whole product in one row. */
const CSQU_HEAD = 'CSQU30'; // positions 1-6
const CSQU_TAIL = '438'; // positions 8-10
const REPAIR_POSITION = 7;
const HEARD_DIGIT = '9';
const WRITTEN_DIGIT = '5';
const SPOKEN_CHECK = '3';

/* MSBU4653011 and MSVU4653011 are both valid container numbers: B is 12, V is
 * 34, and 34 - 12 is 22, so the two are congruent mod 11 and the check digit
 * cannot separate them. This row is the one the agent has to interrupt for.
 *
 * ASK_A_WORD and ASK_B_WORD are NATO alphabet words. The NATO alphabet is
 * English and so is the question the agent asks, which is why these are data
 * here and are quoted rather than translated in the uz and ru catalogs. */
const ASK_POSITION = 3;
const ASK_A = 'B';
const ASK_A_WORD = 'Bravo';
const ASK_B = 'V';
const ASK_B_WORD = 'Victor';
const ASK_CHECK = '1';

/** docs/FINDINGS.md:19 -- a published NHS vector, still arriving. */
const NHS_HEARD = '94347659';
const NHS_BLANKS = 2;

/** MSKU6111115. docs/FINDINGS.md:13 records the day this was 9 by mistake. */
const SETTLED_BODY = 'MSKU611111';
const SETTLED_CHECK = '5';

/* The rows are built per render rather than as module constants, because their
 * notes and the one question are catalog strings now and have to follow the
 * interface language. The slots are not: those are identifier characters and do
 * not change in any language.
 *
 * There are deliberately no `readout` overrides here any more. They used to
 * hold four paragraphs of English prose, which meant a screen reader set to
 * Russian announced English sentences in a Russian voice, and it meant the
 * rack's own localised readout -- the one every other screen uses -- never ran
 * on the page most likely to be read in another language. The generated readout
 * says the same things and says them in the reader's language. */
function heroRows(i18n: I18n): RackRow[] {
  const { t, n, plural } = i18n;

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
      id: 'nhs',
      format: 'NHS number',
      state: 'heard',
      slots: [...provisional(NHS_HEARD), ...empty(NHS_BLANKS)],
      questions: 0,
      note: plural('landing.row.arriving.digits', NHS_BLANKS),
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

// ------------------------------------------------------------- the mechanism --

/* Pairs the README names as genuinely ambiguous in noise. No weights printed:
 * the confusion table is measured, but a number on this page has to be one of
 * the three facts, and these are here to be recognised rather than counted.
 *
 * These are IDENTIFIER CHARACTERS, not words. They render inside a
 * translate="no" lang="en" run for the same reason every slot in the rack does:
 * a page translator asked for Russian will transliterate a bare Latin M sitting
 * in a Russian sentence, and "M" is not "M". */
const CONFUSABLE: readonly (readonly [string, string])[] = [
  ['5', '9'],
  ['M', 'N'],
  ['S', 'F'],
];

/* The arithmetic, as values rather than as prose, so all three catalogs carry
 * byte-identical formulae. Matches server/readback/validators.py. */
const ISO_FORMULA = 'value(c) · 2^i mod 11';
const ISO_FORMULA_FULL = 'check = sum(value(c) · 2^i) mod 11 mod 10';

/* The strip in beat 2 is the same published vector as the repaired row, whole.
 * The spoken form is derived from it so the label and the boxes cannot drift. */
const BEAT2_BODY = `${CSQU_HEAD}${WRITTEN_DIGIT}${CSQU_TAIL}`; // CSQU305438
const BEAT2_SPOKEN = [...BEAT2_BODY].join(' ');

/* Every digit that could have stood in position 7 of CSQU30?4383, and the check
 * digit each one produces. Computed with the same arithmetic as
 * server/readback/validators.py: sum(value(c) * 2**i) mod 11 mod 10, and
 * re-verified against it. The caption used to print the gap one position too
 * early -- CSQU3?54383, which is a different sweep with a different answer (a 0
 * there is the legal one, not a 5). Fixed with the code, not the table: the
 * table was right. The speaker read out 3, so exactly one column is legal. */
const SWEEP: readonly (readonly [string, string])[] = [
  ['0', '2'],
  ['1', '0'],
  ['2', '9'],
  ['3', '7'],
  ['4', '5'],
  ['5', '3'],
  ['6', '1'],
  ['7', '0'],
  ['8', '8'],
  ['9', '6'],
];

// ------------------------------------------------------------- blind pairs --

/* Why these three are invisible: ISO 6346 weights each character by 2^i and
 * sums mod 11, so two characters with the same value mod 11 are the same
 * character as far as the check digit is concerned. Letter values are the ones
 * in validators.py, which skips every multiple of 11. */
interface BlindPair {
  chars: readonly [string, string];
  values: readonly [number, number];
  residue: number;
}

const BLIND_PAIRS: readonly BlindPair[] = [
  { chars: ['B', 'V'], values: [12, 34], residue: 1 },
  { chars: ['K', 'A'], values: [21, 10], residue: 10 },
  { chars: ['F', 'P'], values: [16, 27], residue: 5 },
];

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

  /* THE PAGE'S ONE ANIMATION SYSTEM.
   *
   * This replaces lib/useReveal.ts and styles/reveal.css, which are deleted
   * rather than ported. Two systems animating one element fight, and which one
   * wins is decided by whichever wrote last in a frame -- not a decision anybody
   * made. reveal.css arrived at "content is visible by default; hiding is
   * something JavaScript does only after it has proved it can un-hide" after
   * shipping a blank page; animations/landing.ts replaces that with the stronger
   * property that there is no hiding, so there is nothing to prove.
   *
   * motion.css bans reveal-on-scroll for the OPERATOR's view and names the
   * landing page as the case it is not about; that ban stands everywhere else.
   *
   * The choreography is never invoked under reduced motion -- the branch is not
   * creating the tween, not creating it with duration 0 -- and `refreshOn`
   * re-measures every trigger when the language changes, because every start
   * point is a pixel position and the same headline wraps differently in ru. */
  const landingRoot = useGsapContext<HTMLDivElement>(landingChoreography, {
    refreshOn: [i18n.language],
  });

  /* Lenis exists on this page to give the beats scrub a smooth clock and for
     nothing else, so if that scrub is ever cut this call goes with it. It is
     not constructed under reduced motion, which is what makes the four things
     smooth scroll breaks -- anchors, find-in-page, focus scroll, and the page
     keys -- no-ops for a reader who asked for the browser's own behaviour. */
  useSmoothScroll();

  return (
    <div className="landing" ref={landingRoot}>
      <section className="hero" aria-labelledby="hero-title">
        {/* Format names, identical in every language. translate="no" keeps a
            browser translation extension from turning "Luhn" into a word. */}
        <p className="hero__eyebrow" translate="no">
          ISO 6346 · IBAN mod-97 · Luhn · NHS · VIN
        </p>
        {/* TWO CLAUSES, TWO CATALOG KEYS, TWO BLOCK SPANS -- and the split is
            LAYOUT, not animation. Measured: at 1280 the English headline sets
            three lines and the denial happens to occupy line 1 exactly, but at
            375 it sets four and the denial ends partway into line 2, where the
            reversal then begins on the same line. Splitting per LINE -- the
            reflexive way to animate a headline -- would therefore group
            "better." with "It knows what a valid" into one unit and stagger the
            pitch's pivot against its own meaning.

            Because the two clauses are separate elements in the markup rather
            than a runtime split, the reader who asked for stillness still gets
            the pivot as a line break in the one place the sentence turns, and a
            translator still controls where the sentence breaks. Splitting on
            ". " at runtime would have handed that decision to a regex. */}
        <h1 className="hero__title" id="hero-title">
          <span className="hero__title-a" data-beat>
            {t('landing.hero.title.a')}
          </span>{' '}
          <span className="hero__title-b" data-beat>
            {t('landing.hero.title.b')}
          </span>
        </h1>

        {/* One box, one arrival. The lede, the scope note and the two buttons
            are not three sibling claims arriving in order -- the scope note is
            the page's honesty line and Landing.css sets it DARKER than the pitch
            above it precisely so it does not read as a footnote. A stagger would
            demote it to third item in a list; one wrapper keeps it level with
            the lede. The wrapper is a grid item, so it establishes its own
            formatting context and the children's margins are unchanged. */}
        <div className="hero__support" data-beat>
          <p className="hero__lede">{t('landing.hero.lede')}</p>
          {/* Shown in English too, not only when the interface is translated: the
              English reader is the one being asked to buy it. */}
          <p className="hero__scope">{t('landing.hero.scope')}</p>
          <div className="hero__actions">
            <ButtonLink to="/signup" variant="primary">
              {t('topbar.getKey')}
            </ButtonLink>
            <ButtonLink to="/login" variant="secondary">
              {t('topbar.logIn')}
            </ButtonLink>
          </div>
        </div>

        {/* `l-escape` is the width ladder's one exception class. Every sentence
            on this page lives in a 720px reading spine; exactly two objects are
            allowed to cross it, and this is the first. It is not decoration:
            the rack is an eleven-slot row that must not wrap, and being the only
            wide panel on the page is what makes it read as the payload rather
            than as one more block the same size as the paragraph above it.

            NO `animate` PROP. It added `rack--animate` on mount, which played
            the product's whole claim to an empty seat: measured at 375x812 the
            rack begins below the fold and all eight animations the class starts
            finish inside 300ms, before the reader has scrolled a pixel -- zero
            of eight seen. animations/landing.ts adds the class on scroll entry
            instead. It writes no inline style on the rack or on any of its
            slots; motion.css still owns every keyframe, duration and ease. */}
        <Rack
          className="hero__rack l-escape"
          title={t('landing.rack.title')}
          meta={rackMeta}
          rows={rows}
          legend
        />
      </section>

      {/* ------------------------------------------------------ mechanism -- */}

      <section className="beats" aria-labelledby="beats-title">
        {/* Still an h2 -- it names the section for aria-labelledby and it is the
            only thing saying the three blocks below are one argument -- but it
            takes the eyebrow's TYPE rather than the section title's. The 01/02/03
            indices already say "three beats"; the sentence only has to say which
            one matters. Demoting it visually frees the largest heading below the
            hero for the silence section, which is where the argument lands. */}
        <h2 className="beats__eyebrow" id="beats-title">
          {t('landing.beats.title')}
        </h2>

        <div className="beat">
          <div className="beat__text" data-beat>
            <p className="beat__index">01</p>
            <h3 className="beat__title">{t('landing.beat1.title')}</h3>
            <p className="beat__body">{t('landing.beat1.body')}</p>
          </div>
          <div className="beat__figure" data-beat>
            <ul className="confusables">
              {CONFUSABLE.map(([a, b]) => (
                <li className="confusable" key={`${a}${b}`}>
                  {/* One utterance per pair rather than three fragments with a
                      bare "sounds like" wedged between them: neither of the two
                      languages that are not English puts the verb there. */}
                  <span className="confusable__pair" aria-hidden="true">
                    <span className="confusable__char" translate="no" dir="ltr" lang="en">
                      {a}
                    </span>
                    <span className="confusable__eq">≈</span>
                    <span className="confusable__char" translate="no" dir="ltr" lang="en">
                      {b}
                    </span>
                  </span>
                  <span className="sr-only">{t('landing.confusable.soundsLike', { a, b })}</span>
                </li>
              ))}
            </ul>
            <p className="figure__caption">{t('landing.beat1.caption')}</p>
          </div>
        </div>

        <div className="beat">
          <div className="beat__text" data-beat>
            <p className="beat__index">02</p>
            <h3 className="beat__title">{t('landing.beat2.title')}</h3>
            <p className="beat__body">{t('landing.beat2.body')}</p>
          </div>
          <div className="beat__figure" data-beat>
            <SlotStrip
              className="beat__strip"
              slots={[...settled(BEAT2_BODY), ...locked(SPOKEN_CHECK)]}
              label={t('landing.beat2.stripLabel', {
                spoken: BEAT2_SPOKEN,
                check: SPOKEN_CHECK,
              })}
            />
            <p className="figure__formula" translate="no" dir="ltr" lang="en">
              {ISO_FORMULA_FULL}
            </p>
            <p className="figure__caption">{t('landing.beat2.caption')}</p>
          </div>
        </div>

        <div className="beat">
          <div className="beat__text" data-beat>
            <p className="beat__index">03</p>
            <h3 className="beat__title">{t('landing.beat3.title')}</h3>
            <p className="beat__body">
              {t('landing.beat3.body', {
                heard: HEARD_DIGIT,
                position: n(REPAIR_POSITION),
                check: SPOKEN_CHECK,
              })}
            </p>
          </div>
          <div className="beat__figure" data-beat>
            {/* A scroll container has to be reachable without a mouse, so it
                takes focus and carries its own name. */}
            <div
              className="sweep__scroll"
              role="group"
              aria-label={t('landing.sweep.groupLabel')}
              tabIndex={0}
            >
              <table className="sweep">
                <caption className="sweep__caption">
                  {t('landing.sweep.caption', { position: n(REPAIR_POSITION) })}{' '}
                  {/* The identifier sits beside the sentence in its own
                      protected run, never inside a translated string. */}
                  <span className="sweep__code" translate="no" dir="ltr" lang="en">
                    {CSQU_HEAD}
                    <span className="sweep__gap">?</span>
                    {CSQU_TAIL}
                    {SPOKEN_CHECK}
                  </span>
                </caption>
                <tbody>
                  <tr>
                    <th className="sweep__stub" scope="row">
                      {t('landing.sweep.stub.candidate', { position: n(REPAIR_POSITION) })}
                    </th>
                    {SWEEP.map(([digit, check]) => (
                      <td
                        className="sweep__cell sweep__cell--candidate"
                        key={digit}
                        translate="no"
                        dir="ltr"
                        lang="en"
                        data-mark={
                          check === SPOKEN_CHECK
                            ? 'legal'
                            : digit === HEARD_DIGIT
                              ? 'heard'
                              : undefined
                        }
                      >
                        {digit}
                        {digit === HEARD_DIGIT ? (
                          <span className="sr-only">{`, ${t('landing.sweep.sr.heard')}`}</span>
                        ) : null}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <th className="sweep__stub" scope="row">
                      {t('landing.sweep.stub.check')}
                    </th>
                    {SWEEP.map(([digit, check]) => (
                      <td
                        className="sweep__cell sweep__cell--check"
                        key={digit}
                        translate="no"
                        dir="ltr"
                        lang="en"
                        data-mark={check === SPOKEN_CHECK ? 'legal' : undefined}
                      >
                        {check}
                        {check === SPOKEN_CHECK ? (
                          <span className="sr-only">{`, ${t('landing.sweep.sr.legal')}`}</span>
                        ) : null}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="figure__caption">{t('landing.beat3.caption')}</p>
          </div>
        </div>
      </section>

      {/* ----------------------------------------------------------- gain -- */}

      <section data-beat className="gain" aria-labelledby="gain-title">
        <p className="gain__figure">{`${n(GAIN_HEADLINE)}×`}</p>
        {/* The 64x4 accent bar that used to separate the figure from the title
            is gone: it carried nothing a reader needed, and the whitespace
            between the two says the same thing without a mark. */}
        <h2 className="gain__title" id="gain-title">
          {t('landing.gain.title')}
        </h2>
        <p className="gain__body">
          {t('landing.gain.body.measured', {
            iso: n(GAIN_ISO),
            iban: n(GAIN_IBAN),
            spread: n(ACCENT_SPREAD),
            budget: n(GAIN_HEADLINE),
          })}
        </p>
        <p className="gain__body">{t('landing.gain.body.noDetection', { value: n(ACCENT_VALUE) })}</p>

        {/* The second and last `l-escape`, and the one place on the page where
            extra width is information rather than presence: the fill is
            100/15 = 6.7% of the track, so a longer track draws the ratio more
            legibly. It carries no panel -- it is aria-hidden decoration of a
            number already stated in the paragraphs above. */}
        <div className="ratios l-escape" aria-hidden="true">
          <div className="ratio">
            <span className="ratio__label">{t('landing.gain.ratio.unconstrained')}</span>
            <span className="ratio__track">
              <span className="ratio__fill" data-beat style={{ width: UNCONSTRAINED_WIDTH }} />
            </span>
            <span className="ratio__value">{`${n(1)}×`}</span>
          </div>
          <div className="ratio">
            <span className="ratio__label">{t('landing.gain.ratio.constrained')}</span>
            <span className="ratio__track">
              <span className="ratio__fill" data-beat style={{ width: '100%' }} />
            </span>
            <span className="ratio__value">{`${n(GAIN_HEADLINE)}×`}</span>
          </div>
        </div>
      </section>

      {/* -------------------------------------------- silence, and its limit -- */}

      {/* These used to be two sections and they were never two topics. Read the
          closing sentence of what was `.blind`: "...which is why the rack at the
          top of this page has a row waiting on one character". The blind pairs
          ARE the limit of the silence claim, and the copy already said so.
          Split, the admission that twelve mishearings are invisible was a
          separate section a scroller could skip past; merged, it sits inside the
          claim it qualifies, which is the honest place for it.

          One section, two movements, one hairline between them. No cards: the
          three blind pairs are three instances of one fact and stay inside the
          single `.pairs` panel they already shared. */}
      <section data-beat className="silence" aria-labelledby="silence-title">
        {/* Movement A -- the claim. */}
        <h2 className="section__title" id="silence-title">
          {t('landing.silence.title')}
        </h2>
        <p className="silence__body">
          {t('landing.silence.body', { iso: n(SILENCE_ISO), nhs: n(SILENCE_NHS) })}
        </p>
        <p className="pull">{t('landing.silence.pull')}</p>

        {/* A real <hr>, not a bordered div. It is a thematic break between two
            movements of one argument, which is exactly what the element means,
            and it is the only way the turn is announced to a reader who never
            sees the hairline -- motion and tone are not the only carriers here. */}
        <hr className="silence__break" />

        {/* Movement B -- the limit. The heading stays: a hairline alone tells a
            screen reader nothing, and dropping it would strand
            `landing.blind.title` unused in three catalogs. It takes h3 and the
            smaller size, so the h2 above it remains the largest heading below
            the hero. */}
        <h3 className="silence__subtitle" id="blind-title">
          {t('landing.blind.title')}
        </h3>
        <p className="blind__body">
          {t('landing.blind.body.math', { formula: ISO_FORMULA, share: n(BLIND_SHARE) })}
        </p>

        <ul className="pairs">
          {BLIND_PAIRS.map((pair) => (
            <li className="pair" key={pair.chars.join('')}>
              <p className="pair__chars" aria-hidden="true" translate="no" dir="ltr" lang="en">
                <span>{pair.chars[0]}</span>
                <span className="pair__vs">/</span>
                <span>{pair.chars[1]}</span>
              </p>
              <span className="sr-only">
                {t('landing.blind.pair.chars', { a: pair.chars[0], b: pair.chars[1] })}
              </span>
              <p className="pair__math">
                {t('landing.blind.pair.math', {
                  first: n(pair.values[0]),
                  second: n(pair.values[1]),
                  residue: n(pair.residue),
                })}
              </p>
            </li>
          ))}
        </ul>

        <p className="blind__body">{t('landing.blind.body.rest')}</p>
      </section>

      {/* ---------------------------------------------------------- close -- */}
      {/* No panel. With the argument over, this is the only surface on the page
          that is neither the spine's prose nor a machine readout: bare heading,
          bare paragraph, one button on the page ground. Left-aligned on the
          spine -- centring it would break the shared left rail at the last
          moment for no reason. */}

      <section data-beat className="close" aria-labelledby="close-title">
        <h2 className="close__title" id="close-title">
          {t('landing.close.title')}
        </h2>
        <p className="close__body">{t('landing.close.body')}</p>
        <ButtonLink to="/signup" variant="primary" className="close__action">
          {t('topbar.getKey')}
        </ButtonLink>
      </section>
    </div>
  );
}
