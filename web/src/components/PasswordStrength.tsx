import { useEffect, useMemo, useRef, useState } from 'react';
import { Icon } from './Icon';
import type { IconName } from './Icon';
import { STRENGTH_SEGMENTS, checkPassword, strengthOf } from '../lib/api';
import type { PasswordCheck, StrengthLevel } from '../lib/api';
import { evaluateLocally, levelNameForScore } from '../lib/password';
import { useI18n } from '../i18n';
import type { I18n } from '../i18n';
import './PasswordStrength.css';

// ------------------------------------------------------------ localisation --

/* WHERE THE ENGLISH COMES FROM, and why this is a matcher rather than a lookup.
 *
 * The problem and suggestion lines are produced in two places -- lib/password.ts
 * for the local half of the verdict and server/password.py for the breach half
 * -- and both produce ENGLISH. Neither is mine to change, and the client half is
 * held character-for-character in step with the Python by
 * tests/test_password_parity.py over 1,756 vectors, so rewriting either would
 * break the thing that keeps the meter and the signup from disagreeing.
 *
 * That parity is also what makes matching on the sentence sound rather than
 * fragile: the set is CLOSED (ten problems and two suggestions, all literals in
 * one file), and the two producers cannot drift apart without a Python test
 * failing first. A line that matches nothing here falls through as the English
 * it already was -- visible, and obviously untranslated, rather than blank.
 *
 * The structural fix, when lib/password.ts is next opened by whoever owns it, is
 * for PasswordCheck to carry a code beside each line, the way CAPTURE_STATES in
 * lib/api.ts carries `labelKey` beside `label`. This is the seam until then.
 */

/** ", " up to the last pair, then the language's own "and". */
export function listWithAnd(parts: readonly string[], and: string): string {
  if (parts.length <= 1) return parts[0] ?? '';
  return `${parts.slice(0, -1).join(', ')} ${and} ${parts.at(-1) ?? ''}`;
}

/* `as const` on each return, so the compiler keeps the key as a literal. A
 * widened TranslationKey would make t() demand the union of every placeholder
 * in the catalog at the call site. */
function classKey(phrase: string) {
  if (phrase === 'a letter') return 'pw.class.letter' as const;
  if (phrase === 'a number') return 'pw.class.number' as const;
  if (phrase === 'a symbol') return 'pw.class.symbol' as const;
  return null;
}

function contextKey(which: string) {
  if (which === 'email') return 'pw.problem.context.email' as const;
  if (which === 'name') return 'pw.problem.context.name' as const;
  if (which === 'company') return 'pw.problem.context.company' as const;
  return null;
}

/* Whole-sentence matches. Anchored equality, not a substring search: a
 * substring match would quietly claim a sentence it only partly recognised. */
const EXACT = [
  ['It is a very common password with numbers or symbols bolted on.', 'pw.problem.commonBolted'],
  ['It is one of the most common passwords in use.', 'pw.problem.commonPlain'],
  ['It contains a straight run across the keyboard.', 'pw.problem.keyboardRun'],
  ['It repeats the same character three or more times.', 'pw.problem.repeats'],
  ['It uses too few distinct characters.', 'pw.problem.fewDistinct'],
  [
    'Word-then-number-then-symbol is the first thing an attacker tries.',
    'pw.problem.wordNumberSymbol',
  ],
  [
    'Length beats cleverness — four unrelated words are stronger than one word with substitutions.',
    'pw.suggestion.length',
  ],
  ['Add a few more characters to make it comfortably strong.', 'pw.suggestion.addMore'],
] as const;

const AT_LEAST = /^Use at least (\d+) characters\.$/;
const UNDER = /^Keep it under (\d+) characters\.$/;
const INCLUDE = /^Include (.+)\.$/;
const CONTEXT = /^Do not put your (email|name|company) in your password\.$/;

/**
 * One English line from the scorer, rendered in the interface language.
 *
 * Returns the input unchanged when nothing matches. That is the honest failure:
 * a reader sees an English sentence among translated ones and knows something
 * was missed, where a blank line or a raw key would tell them nothing.
 */
export function localisePasswordLine(line: string, i18n: I18n): string {
  const text = line.trim();

  for (const [english, key] of EXACT) {
    if (text === english) return i18n.t(key);
  }

  const atLeast = AT_LEAST.exec(text);
  if (atLeast?.[1] !== undefined) {
    return i18n.t('pw.problem.short', { min: i18n.n(Number(atLeast[1])) });
  }

  const under = UNDER.exec(text);
  if (under?.[1] !== undefined) {
    return i18n.t('pw.problem.long', { max: i18n.n(Number(under[1])) });
  }

  const context = CONTEXT.exec(text);
  if (context?.[1] !== undefined) {
    const key = contextKey(context[1]);
    if (key !== null) return i18n.t(key);
  }

  const include = INCLUDE.exec(text);
  if (include?.[1] !== undefined) {
    const phrases = include[1].split(', ');
    const keys = phrases.map(classKey);
    // All or nothing. A half-translated list reads as a bug rather than as a
    // rule, so an unexpected class word leaves the whole line in English.
    if (keys.every((key) => key !== null)) {
      const words = keys.map((key) => i18n.t(key as NonNullable<typeof key>));
      return i18n.t('pw.problem.include', {
        missing: listWithAnd(words, i18n.t('pw.list.and')),
      });
    }
  }

  return line;
}

/* The strength word. `breached` is checked before the level because
 * strengthOf() reports a breached password as `weak` with an overridden label,
 * and "found in a breach" is a different claim from "weak" -- the two must not
 * collapse into one word in any language. */
function strengthKey(breached: boolean, level: StrengthLevel) {
  if (breached) return 'pw.strength.breached' as const;
  if (level === 'fair') return 'pw.strength.fair' as const;
  if (level === 'good') return 'pw.strength.good' as const;
  if (level === 'strong') return 'pw.strength.strong' as const;
  return 'pw.strength.weak' as const;
}

/* The four-segment strength readout.
 *
 * The segments are not a red-to-green ramp with four stops, and they are no
 * longer four hues at all. The four state colours measured within 1.3 points of
 * one another in greyscale, so the hue never separated the levels for a
 * monochrome display or for most colour-blind readers -- the COUNT of lit
 * segments, the word and the icon did, and they still do. Every segment is
 * therefore --text on a --track groove, computed 13.78, at every level.
 *
 * Tone survives on the WORD, one step of the capture vocabulary each:
 *
 *   weak / breached -> flagged   --alert        6.12 on --surface
 *   fair            -> asking    --accent-text  5.57
 *   good            -> heard     --text-2       5.07
 *   strong          -> settled   --text        16.83, weight 600
 *
 * The level-to-state mapping is not restated here: strengthOf() in lib/api.ts
 * already names the state for each level in the icon it picks, and the same
 * word is handed to CSS as data-state. One place decides the state; one place
 * decides what a state looks like.
 *
 * WHERE THE VERDICT COMES FROM, and this is the part that was wrong.
 *
 * Every verdict used to come from the server. With the API unreachable -- which
 * is most of a hackathon build -- the meter sat at "Strength not checked" with
 * four unlit segments while somebody typed, and the form offered no opinion at
 * all until submit. Even with the server up, a network round trip to discover
 * that eight characters is fewer than ten is the wrong shape of answer.
 *
 * server/password.py already names the split: composition and predictability are
 * arithmetic and local; only "has it leaked" needs a service. So the local half
 * runs here on every keystroke (lib/password.ts, held in step with the Python by
 * tests/test_password_parity.py over 1,756 vectors), and the server call is now
 * only the breach lookup -- arriving late, and upgrading the verdict when it
 * does.
 *
 * The meter is therefore lit from the first character typed, works offline, and
 * the server can no longer blank it.
 */

/* 500ms. A comfortable typing rhythm sits near 150-250ms between keys, so
 * anything under ~350ms still fires mid-word and turns the breach lookup into a
 * network call per character. 500ms fires once per pause, which is also once per
 * thing the user might actually want an outside opinion on. */
const DEBOUNCE_MS = 500;

/* The visible meter updates per keystroke; the SCREEN READER announcement does
 * not. An aria-live region that changes on every character is unusable -- it
 * interrupts the person typing with a running commentary on their own password.
 * So the announcement lags a beat and settles once, which is the quiet the
 * network debounce used to provide for free before the meter went local. */
const ANNOUNCE_MS = 900;

type BreachPhase = 'idle' | 'checking' | 'answered' | 'unavailable';

export interface PasswordStrengthProps {
  password: string;
  /** Context the scorer weighs. A password built out of the account's own name,
   *  company or email is weak however long it is, so these ride along rather
   *  than being kept back. Both scorers use them. */
  email: string;
  name: string;
  company: string;
  /** The password_check a 400 from /api/auth/signup carried. It outranks
   *  everything because it is the server's verdict on this exact string, and the
   *  form clears it the moment the string changes. */
  serverCheck?: PasswordCheck | null;
}

interface BreachCopy {
  /** The sentence, cut around the figure so the figure can be set larger
   *  without a word of it being rewritten here. */
  before: string;
  count: string;
  after: string;
}

/** The server's breach line, and the only thing wanted from it: the number. */
function breachLine(check: PasswordCheck): string | null {
  const found = [...check.problems, ...check.suggestions].find((line) =>
    line.toLowerCase().includes('breach'),
  );
  return found ?? null;
}

/* The count, parsed out of the server's English sentence ("This password
 * appears in 3,196 known breaches. ..."). The FIGURE is the claim and it is the
 * server's; the sentence around it is this interface's, so the sentence is
 * rebuilt from the catalog in the reader's language and the figure is dropped
 * back into it through Intl. Nothing here invents a number. */
function breachCount(check: PasswordCheck): number | null {
  const source = breachLine(check);
  if (source === null) return null;
  const figure = /\d[\d,]*\d|\d/.exec(source);
  if (figure === null) return null;
  const value = Number.parseInt(figure[0].replace(/,/g, ''), 10);
  return Number.isFinite(value) ? value : null;
}

/* Cut the localised sentence around the localised figure so the figure alone
 * can be promoted typographically. The needle is the string plural() itself
 * substituted, so it matches whatever group separator the language uses -- a
 * narrow no-break space in ru, a comma in en. */
function splitAround(text: string, needle: string): BreachCopy {
  const at = needle === '' ? -1 : text.indexOf(needle);
  if (at === -1) return { before: text, count: '', after: '' };
  return { before: text.slice(0, at), count: needle, after: text.slice(at + needle.length) };
}

export function PasswordStrength({
  password,
  email,
  name,
  company,
  serverCheck = null,
}: PasswordStrengthProps) {
  const i18n = useI18n();
  const { t, n, plural } = i18n;
  const [remote, setRemote] = useState<PasswordCheck | null>(null);
  const [phase, setPhase] = useState<BreachPhase>('idle');
  const [announced, setAnnounced] = useState('');

  /* Instant, synchronous, and the reason there is always something to show.
   * Recomputed on every keystroke because it costs microseconds: the whole
   * scorer is a handful of regexes over a string capped at 200 characters. */
  const local = useMemo(
    () => evaluateLocally(password, { email, name, company }),
    [password, email, name, company],
  );

  /* A sequence number, not only an abort. Aborting the previous fetch is not
   * enough on its own: an abort and a response race, so a reply for an earlier
   * password can still land after the reply for a later one. Every dispatch
   * takes a number and only the current number is allowed to write. */
  const generation = useRef(0);
  const localOk = local.ok;

  useEffect(() => {
    const mine = generation.current + 1;
    generation.current = mine;

    // A breach verdict belongs to the exact string it was asked about. Holding
    // the old one while the new one is in flight would print "Found in a breach"
    // over a password that has since been edited.
    setRemote(null);

    if (password.length === 0) {
      setPhase('idle');
      return;
    }

    // The lookup is only worth making for a password that would otherwise be
    // accepted. server/password.py skips it for the same reason: one already
    // rejected for being eight characters long does not need a network call, and
    // not making it keeps the common rejection path instant and private.
    if (!localOk) {
      setPhase('idle');
      return;
    }

    setPhase('checking');
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void checkPassword({ password, email, name, company }, controller.signal).then((result) => {
        // Stale, including the aborted case: request() reports an abort as a
        // timeout, and acting on a reply nobody is waiting for any more would
        // overwrite the verdict for a different string.
        if (mine !== generation.current) return;

        if (result.ok) {
          setRemote(result.data);
          setPhase('answered');
        } else {
          setPhase('unavailable');
        }
      });
    }, DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [password, email, name, company, localOk]);

  /* Precedence, strongest first. The signup rejection is the server's word on
   * this exact string; the live check is the server's word a moment ago; the
   * local verdict is always underneath. Nothing can leave this null, which is
   * what removes the old "Strength not checked" dead end. */
  const shown: PasswordCheck = serverCheck ?? remote ?? local;

  /* strengthOf() owns the colour, the word and the icon. It is handed a level
   * NAME rather than the server's prose label, because its own fallback
   * collapses two states -- levelNameForScore in lib/password.ts carries the
   * measurement. `breached` is preserved and strengthOf checks that before it
   * looks at the label, so a breached password is still flagged whatever it
   * scores. */
  const strength = strengthOf({ ...shown, label: levelNameForScore(shown.score) });
  const empty = password.length === 0;
  const filled = empty ? 0 : strength.filled;

  /* The word, not strength.label. strengthOf() hands back English, and the word
   * is the carrier here rather than the colour -- see THE STRENGTH WORDS in
   * i18n/en.ts. The icon and the segment count still come from strengthOf, so
   * there is still exactly one place a level is decided.
   *
   * `state` is the icon's own name, which IS the capture-state word strengthOf
   * assigned to this level (flagged / asking / heard / settled). Handing it to
   * CSS as data-state keeps the tone table in one stylesheet instead of pushing
   * a colour token through the component, and it means no screen holds a
   * literal colour. */
  let label = t('pw.strength.idle');
  let icon: IconName | null = null;
  let state: IconName | undefined;

  if (!empty) {
    label = t(strengthKey(shown.breached, strength.level));
    icon = strength.icon;
    state = strength.icon;
  }

  const breachSource = shown.breached ? breachLine(shown) : null;
  const count = shown.breached ? breachCount(shown) : null;

  /* The breach sentence is shown once, in its own block. It used to be rendered
   * there AND again in the problem list below, because it arrives from the
   * server inside `problems` -- an English defect, fixed here rather than
   * translated three times. */
  const problems = empty
    ? []
    : shown.problems
        .filter((line) => line !== breachSource)
        .map((line) => localisePasswordLine(line, i18n));

  const spoken = empty ? '' : [label, ...problems].join('. ');

  useEffect(() => {
    const timer = window.setTimeout(() => setAnnounced(spoken), ANNOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [spoken]);

  /* Localised sentence, server's figure. When the figure cannot be parsed the
   * server's own line is shown verbatim rather than a sentence with a hole in
   * it -- an untranslated claim beats an invented one. */
  const breach =
    count !== null
      ? splitAround(plural('pw.breach.count', count), n(count))
      : breachSource !== null
        ? { before: breachSource, count: '', after: '' }
        : null;

  const clean = !empty && shown.breach_checked && !shown.breached;
  // `!empty` first: advice about how to choose a password, offered before the
  // person has typed a character, is the interface talking to itself.
  const rawTip =
    !empty && !shown.breached && problems.length === 0 && strength.level !== 'strong'
      ? (shown.suggestions[0] ?? null)
      : null;
  const tip = rawTip === null ? null : localisePasswordLine(rawTip, i18n);

  /* Only once the local rules pass, and only when the lookup actually failed.
   * Saying "not checked against breaches" under a password that is already too
   * short is piling on, and the person has a more useful problem to fix first.
   * It is a note and never a block: an outage at a third party must not stop
   * somebody creating an account. */
  const breachMissing = phase === 'unavailable' && localOk && !shown.breach_checked;

  return (
    /* Always mounted on the signup form, idle segments and all. The space is
     * reserved by being occupied rather than by a min-height guess, so there is
     * no moment at which the meter appears and pushes the button down. */
    <div className="pwmeter">
      {/* The segments repeat what the label says. They are decoration for a
          screen reader and the live region below is the announcement. */}
      <div className="pwmeter__track" aria-hidden="true">
        {Array.from({ length: STRENGTH_SEGMENTS }, (_, index) => (
          <span
            key={index}
            className={`pwmeter__seg${index < filled ? ' pwmeter__seg--on' : ''}`}
          >
            <span className="pwmeter__fill" />
          </span>
        ))}
      </div>

      <div className="pwmeter__say">
        {/* aria-hidden because the live region carries the same words on a
            delay. Announcing both would say everything twice, once per key. */}
        <p className="pwmeter__label" data-state={state} aria-hidden="true">
          {icon === null ? null : <Icon name={icon} size={18} />}
          <span>{label}</span>
        </p>

        {/* polite, so a verdict waits for a gap rather than cutting across the
            person typing. atomic, so the problems are read together with the
            word they belong to instead of arriving as loose fragments. */}
        <p className="sr-only" aria-live="polite" aria-atomic="true">
          {announced}
        </p>

        {breach === null ? null : (
          <div className="pwbreach">
            <p className="pwbreach__lead">
              {breach.before}
              <strong className="pwbreach__count">{breach.count}</strong>
              {breach.after}
            </p>
            <p className="pwbreach__tail">{t('pw.breach.advice')}</p>
          </div>
        )}

        {/* The problems are the whole point of judging locally: they say WHY, on
            the keystroke, instead of at submit. */}
        {problems.length === 0
          ? null
          : problems.map((problem) => (
              <p key={problem} className="pwnote pwnote--tip">
                <Icon name="info" size={16} />
                <span>{problem}</span>
              </p>
            ))}

        {clean ? (
          <p className="pwnote pwnote--clean">
            <Icon name="shield" size={16} />
            <span>{t('pw.breach.clean')}</span>
          </p>
        ) : null}

        {breachMissing ? (
          <p className="pwnote pwnote--tip">
            <Icon name="info" size={16} />
            <span>{t('pw.breach.unchecked')}</span>
          </p>
        ) : null}

        {tip === null ? null : (
          <p className="pwnote pwnote--tip">
            <Icon name="info" size={16} />
            <span>{tip}</span>
          </p>
        )}
      </div>
    </div>
  );
}
