import type { ReactNode } from 'react';
import { Icon } from './Icon';
import { CAPTURE_STATES } from '../lib/api';
import type { CaptureState } from '../lib/api';
import { useI18n } from '../i18n';
import type { I18n, TranslationKey } from '../i18n';
import './Rack.css';

/* The capture rack.
 *
 * This is the instrument, not a graphic. It is here rather than on the landing
 * page because the account screen renders the same thing over /api/sessions and
 * the live view will render it over the replay stream; three implementations of
 * one readout would drift within a week.
 *
 * A row is one identifier. A slot is one character position in it, and the six
 * slot states are not decoration -- each one is a distinct thing the solver did,
 * and merging any two of them hides a decision:
 *
 *   empty        the format knows this position exists; nobody has said it yet
 *   provisional  heard, not settled -- the recogniser's guess, still open
 *   settled      agreed and written
 *   repaired     the format overruled the microphone. BOTH characters stay
 *                visible, because "we changed your number" is not something an
 *                interface gets to do quietly on screen even when the agent did
 *                it quietly on the call
 *   asked        the one character the agent will interrupt about
 *   locked       computed from the other positions. The microphone cannot move
 *                it -- an ISO 6346 check digit, an IBAN's mod-97 pair
 *
 * Row state reuses CAPTURE_STATES from lib/api.ts rather than defining a second
 * vocabulary, so a state means the same thing here as it does everywhere else.
 * It takes the WORD and the ICON from that record. It no longer takes the
 * colour: the state vocabulary is tone plus weight plus, for repaired, a
 * stacked pair -- see the header of Rack.css.
 */

export type SlotState = 'empty' | 'provisional' | 'settled' | 'repaired' | 'asked' | 'locked';

export type Slot =
  | { state: 'empty' }
  | { state: 'provisional'; char: string }
  | { state: 'settled'; char: string }
  /** `heard` is what the recogniser delivered; `char` is what the format wrote. */
  | { state: 'repaired'; char: string; heard: string }
  | { state: 'asked'; char: string }
  | { state: 'locked'; char: string };

// Builders. A row reads as the code it represents at the call site, which is the
// only way a wrong character in a fixture is ever going to be spotted.
export const settled = (chars: string): Slot[] =>
  [...chars].map((char) => ({ state: 'settled', char }));

export const provisional = (chars: string): Slot[] =>
  [...chars].map((char) => ({ state: 'provisional', char }));

export const locked = (chars: string): Slot[] =>
  [...chars].map((char) => ({ state: 'locked', char }));

export const empty = (count: number): Slot[] =>
  Array.from({ length: count }, () => ({ state: 'empty' }));

export const repaired = (heard: string, char: string): Slot => ({ state: 'repaired', char, heard });

export const asked = (char: string): Slot => ({ state: 'asked', char });

export interface RackRow {
  id: string;
  /** The format that constrains this row: ISO 6346, IBAN-GB, NHS, VIN, Luhn. */
  format: string;
  state: CaptureState;
  slots: Slot[];
  /** Times the agent had to interrupt. 0 is the product working. */
  questions: number;
  /** The one-character question, while the row is waiting on an answer. */
  question?: string;
  /** What the arithmetic had to say. Mono content is expected here. */
  note?: ReactNode;
  /** Overrides the generated screen-reader readout where prose reads better. */
  readout?: string;
}

/* The strip is one accessible object, not thirty. A screen reader walking
 * eleven separate cells announces eleven fragments and the user assembles the
 * identifier themselves; role="img" plus a full readout hands over the whole
 * number, its state and its repairs in one go. tabindex keeps the strip
 * reachable by keyboard, which it has to be because it is a scroll container:
 * a 22-character IBAN does not fit 375px and scrolls inside its own lane rather
 * than widening the page. */
export interface SlotStripProps {
  slots: Slot[];
  /** Announced in place of the individual characters. */
  label: string;
  className?: string;
}

export function SlotStrip({ slots, label, className }: SlotStripProps) {
  return (
    <div
      className={['slot-strip', className ?? ''].filter(Boolean).join(' ')}
      role="img"
      aria-label={label}
      tabIndex={0}
    >
      {/* The strip is identifier territory. dir and translate are set here as
          well as on each character so the RUN is protected, not just the
          glyphs: a translator that rewrites the container would otherwise be
          free to reorder the children. See THE IDENTIFIER RULE below. */}
      <div className="slot-strip__inner" dir="ltr" translate="no">
        {slots.map((slot, index) => (
          <SlotView key={index} slot={slot} />
        ))}
      </div>
    </div>
  );
}

/* ============================================================================
 * THE IDENTIFIER RULE
 * ============================================================================
 *
 * An identifier character is NEVER localised. Not translated, not passed
 * through Intl, not re-shaped into another numbering system, not reordered by
 * bidi, and not touched by a page translator. It renders as ASCII Latin with
 * tabular figures, exactly as the solver produced it, in every interface
 * language.
 *
 * This is not stylistic. Readback's entire claim is that the number it wrote
 * down is the number the caller said. A "٣" where the pipeline emitted "3", or
 * a Cyrillic "В" where it emitted a Latin "B", is the product lying about its
 * one job -- and both are things a locale-aware formatter or a browser
 * translation extension will do to a bare string if nothing stops them.
 *
 * The guarantee used to be accidental: nothing localised anything, so nothing
 * could go wrong. With a catalog and Intl in the codebase that accident has
 * expired. Every identifier character in the rack now goes through
 * <IdentifierText>, which is the single, deliberate, enforced place the rule
 * lives:
 *
 *   translate="no"  stops Chrome/Edge auto-translation and page-translator
 *                   extensions from rewriting the glyphs. This is a real
 *                   observed failure mode, not a hypothetical: a translator
 *                   asked to render a page in Russian will happily transliterate
 *                   a bare Latin letter sitting in a Russian sentence.
 *   dir="ltr"       an identifier reads left to right regardless of the
 *                   surrounding paragraph direction. All three languages
 *                   shipped today are LTR, so this changes nothing now and
 *                   holds the line the day a fourth is not.
 *   lang="en"       marks the run as Latin-script content so a screen reader
 *                   spells "MSKU" with an English letter-name synthesiser
 *                   instead of trying Cyrillic letter names on Latin glyphs.
 *   font-variant-   in Rack.css. Plex Mono is monospaced so its figures are
 *   numeric         already tabular; declaring it means a future font change
 *                   cannot silently un-align the columns.
 *
 * And the two things that must NOT happen here: no call to t(), and no call to
 * anything in i18n/format.ts. t() does verbatim substitution and never touches
 * Intl, which is why it is safe to interpolate a character into the spoken
 * readout below; format.ts is the opposite and is for counts and dates only.
 *
 * If you are adding a new slot state: render its character through
 * <IdentifierText>, not through a bare {slot.char}.
 * ==========================================================================*/

/** The alphabet the supported formats draw from: ISO 6346, IBAN, NHS, VIN, Luhn. */
const IDENTIFIER_CHAR = /^[0-9A-Za-z]$/;

function IdentifierText({ children, className }: { children: string; className?: string }) {
  /* Dev-only tripwire. It does not throw: a rack that refuses to render is
   * worse than a rack showing an odd character, and the character came from the
   * pipeline either way. It shouts in the console so the upstream bug gets
   * found rather than absorbed. */
  if (import.meta.env.DEV && !IDENTIFIER_CHAR.test(children)) {
    console.error(
      `Rack: "${children}" is not an ASCII identifier character. ` +
        'Slot content comes from the solver and must never be localised or reshaped. ' +
        'See THE IDENTIFIER RULE in components/Rack.tsx.',
    );
  }

  return (
    <span className={className} translate="no" dir="ltr" lang="en">
      {children}
    </span>
  );
}

function SlotView({ slot }: { slot: Slot }) {
  if (slot.state === 'repaired') {
    return (
      <span className="slot slot--repaired">
        {/* The heard character stays on the row, stacked ABOVE the written one
            with a hairline between them. That stack is the point: what happened
            is a relationship -- this became that -- and no single colour can
            say a relationship. The <s> stays because it is semantically true
            (this is no longer accurate); the visible strike is gone, because
            the rule and the tone already say it. */}
        <s className="slot__heard">
          <IdentifierText>{slot.heard}</IdentifierText>
        </s>
        <IdentifierText className="slot__char">{slot.char}</IdentifierText>
      </span>
    );
  }

  if (slot.state === 'empty') {
    return <span className="slot slot--empty" />;
  }

  return (
    <span className={`slot slot--${slot.state}`}>
      <IdentifierText className="slot__char">{slot.char}</IdentifierText>
    </span>
  );
}

/* Spoken form of a row, in the interface language.
 *
 * Characters are spaced so a screen reader reads them out one at a time instead
 * of trying to pronounce MSKU as a word. The characters themselves are
 * substituted verbatim -- t() is a regex replace with no Intl anywhere in it,
 * which is what makes passing an identifier through it consistent with THE
 * IDENTIFIER RULE above.
 *
 * `row.format`, `row.readout` and `row.question` are caller-supplied strings.
 * The rack does not own that copy and does not translate it. */
function readoutFor(row: RackRow, i18n: I18n): string {
  if (row.readout) return row.readout;

  const { t, plural, n } = i18n;

  const spoken = row.slots
    .map((slot) => (slot.state === 'empty' ? t('rack.readout.blank') : slot.char))
    .join(' ');

  // The position number is prose, not an identifier, so it IS localised.
  const ordinal = (index: number) => t('rack.readout.position', { n: n(index + 1) });

  const parts: string[] = [
    `${row.format}.`,
    `${spoken}.`,
    `${t(CAPTURE_STATES[row.state].labelKey)}.`,
  ];

  row.slots.forEach((slot, index) => {
    if (slot.state === 'repaired') {
      parts.push(
        t('rack.readout.repaired', {
          position: ordinal(index),
          heard: slot.heard,
          written: slot.char,
        }),
      );
    }
    if (slot.state === 'asked') {
      parts.push(t('rack.readout.asked', { position: ordinal(index) }));
    }
    if (slot.state === 'locked') {
      parts.push(t('rack.readout.locked', { position: ordinal(index) }));
    }
  });

  /* Not `questions === 1`. Russian needs вопрос / вопроса / вопросов and puts
   * 21 back on the singular, so the category comes from Intl.PluralRules. */
  parts.push(plural('rack.readout.questions', row.questions));
  return parts.join(' ');
}

function RowView({ row }: { row: RackRow }) {
  const i18n = useI18n();
  const { t, n } = i18n;
  const meta = CAPTURE_STATES[row.state];

  return (
    <li className="rack__row" data-state={row.state}>
      <div className="row__head">
        <span className="row__format">{row.format}</span>
        {/* The word and the icon, which are the two carriers that survive
            greyscale. Tone and weight are decided in Rack.css off the row's
            data-state, not injected here from CAPTURE_STATES.token: the state
            vocabulary is tone PLUS weight now, and a `color:` custom property
            cannot carry a font-weight. meta.token is deliberately unread. */}
        <span className="row__state">
          <Icon name={meta.icon} size={16} />
          <span>{t(meta.labelKey)}</span>
        </span>
      </div>

      <SlotStrip slots={row.slots} label={readoutFor(row, i18n)} />

      {row.question ? (
        <p className="row__ask">
          <Icon name="asking" size={16} />
          <span>{row.question}</span>
        </p>
      ) : null}

      <p className="row__foot">
        <span className="row__questions">
          {row.questions === 0
            ? t('rack.asked.none')
            : t('rack.asked.count', { n: n(row.questions) })}
        </span>
        {row.note ? <span className="row__note">{row.note}</span> : null}
      </p>
    </li>
  );
}

/* The legend holds KEYS, not sentences, and is resolved at render time so it
 * follows the language without the module being re-evaluated.
 *
 * `as const satisfies` for the same reason as CAPTURE_STATES in lib/api.ts: it
 * validates every key against the catalog while keeping each one a literal, so
 * t() knows none of them take parameters. The sample characters are identifier
 * glyphs and go through SlotView like any other slot. */
const SLOT_LEGEND = [
  {
    slot: { state: 'empty' },
    labelKey: 'rack.legend.empty.label',
    noteKey: 'rack.legend.empty.note',
  },
  {
    slot: { state: 'provisional', char: 'S' },
    labelKey: CAPTURE_STATES.heard.labelKey,
    noteKey: 'rack.legend.provisional.note',
  },
  {
    slot: { state: 'settled', char: 'K' },
    labelKey: CAPTURE_STATES.settled.labelKey,
    noteKey: 'rack.legend.settled.note',
  },
  {
    slot: { state: 'repaired', char: '5', heard: '9' },
    labelKey: CAPTURE_STATES.repaired.labelKey,
    noteKey: 'rack.legend.repaired.note',
  },
  {
    slot: { state: 'asked', char: 'B' },
    labelKey: CAPTURE_STATES.asking.labelKey,
    noteKey: 'rack.legend.asked.note',
  },
  {
    slot: { state: 'locked', char: '3' },
    labelKey: 'rack.legend.locked.label',
    noteKey: 'rack.legend.locked.note',
  },
] as const satisfies readonly { slot: Slot; labelKey: TranslationKey; noteKey: TranslationKey }[];

export interface RackProps {
  rows: readonly RackRow[];
  /** Names the rack for assistive tech and titles the panel. */
  title: string;
  /** Right-hand meta line in the header. Kept short: it sits beside the title. */
  meta?: string;
  /** Plays the repair once on mount. Off by default: a rack of stored captures
   *  has nothing to animate, and re-running history is a lie. */
  animate?: boolean;
  /** The key to the six slot states. Worth showing where the rack is being
   *  explained; noise where the reader already works here. */
  legend?: boolean;
  className?: string;
}

export function Rack({ rows, title, meta, animate = false, legend = false, className }: RackProps) {
  const { t } = useI18n();
  const classes = ['rack', animate ? 'rack--animate' : '', className ?? '']
    .filter(Boolean)
    .join(' ');

  return (
    <section className={classes} aria-label={title}>
      <header className="rack__head">
        {/* No accent tick. It was an 18x3 bar that marked the top of the
            instrument "the way a bezel does" -- decoration, by its own
            description. The title is the title. */}
        <h2 className="rack__title">{title}</h2>
        {meta ? <span className="rack__meta">{meta}</span> : null}
      </header>

      {rows.length === 0 ? (
        <p className="rack__none">{t('rack.empty')}</p>
      ) : (
        <ul className="rack__rows">
          {rows.map((row) => (
            <RowView key={row.id} row={row} />
          ))}
        </ul>
      )}

      {legend ? (
        <dl className="rack__legend">
          {SLOT_LEGEND.map((item) => (
            /* Keyed on the catalog key, not on the translated word: the key is
               stable across a language change, so switching language updates
               the text in place instead of tearing down six subtrees. */
            <div className="legend__item" key={item.labelKey}>
              <span className="legend__sample" aria-hidden="true">
                <SlotView slot={item.slot} />
              </span>
              <div className="legend__text">
                <dt className="legend__term">{t(item.labelKey)}</dt>
                <dd className="legend__def">{t(item.noteKey)}</dd>
              </div>
            </div>
          ))}
        </dl>
      ) : null}
    </section>
  );
}
