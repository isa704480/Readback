import { useCallback, useState } from 'react';
import type { FormEvent } from 'react';
import { Button, Icon } from '../components';
import { useI18n } from '../i18n';
import type { TranslationKey } from '../i18n';
import { validateIdentifier } from '../lib/api';
import type { ValidateResult } from '../lib/api';
import './Formats.css';

/* The format reference (the screen the Pending stub promised: "the reference
 * that explains how each check digit is computed").
 *
 * It reuses the per-format copy that already lives in the account catalog
 * (account.format.*) rather than re-writing it, so the two screens cannot
 * disagree, and adds the two things a reference needs and the account tab does
 * not: the SHAPE of each format, drawn position by position, and a REAL valid
 * example with its check character marked.
 *
 * Every example below is checksum-valid: each was run through the actual solver
 * (server/readback/solver.py) before being written here, so the page shows only
 * numbers the system itself accepts. A made-up example that failed its own
 * check would be exactly the fabricated data this product refuses. */

interface FormatDef {
  id: string;
  name: TranslationKey;
  length: TranslationKey;
  check: TranslationKey;
  strength: TranslationKey;
  measured: readonly TranslationKey[];
  /** A valid identifier, verified against the solver. */
  example: string;
  /** 0-indexed positions that hold the computed check character(s). */
  checkPos: readonly number[];
  /** Rendered when the format identifies a real person. */
  sensitive: TranslationKey | null;
}

/* The congruence classes mod 11 — arithmetic, identical in every language, so
 * data rather than a catalog string (a `{A K U}` would read as a placeholder to
 * the i18n type checker). Mirrors ISO6346_CLASSES in the account screen. */
const ISO6346_CLASSES =
  '{A K U} {1 B L V} {2 C M W} {3 D N X} {4 E O Y} {5 F P Z} {6 G Q} {7 H R} {8 I S} {9 J T}';

const FORMATS: readonly FormatDef[] = [
  {
    id: 'iso6346',
    name: 'account.format.iso6346.name',
    length: 'account.format.iso6346.length',
    check: 'account.format.iso6346.check',
    strength: 'account.format.iso6346.strength',
    measured: ['account.format.iso6346.measured.1', 'account.format.iso6346.measured.2'],
    example: 'MSKU4158005',
    checkPos: [10],
    sensitive: null,
  },
  {
    id: 'iban',
    name: 'account.format.iban.name',
    length: 'account.format.iban.length',
    check: 'account.format.iban.check',
    strength: 'account.format.iban.strength',
    measured: ['account.format.iban.measured.1', 'account.format.iban.measured.2'],
    example: 'GB82WEST12345698765432',
    checkPos: [2, 3],
    sensitive: null,
  },
  {
    id: 'vin',
    name: 'account.format.vin.name',
    length: 'account.format.vin.length',
    check: 'account.format.vin.check',
    strength: 'account.format.vin.strength',
    measured: [],
    example: '1HGCM82633A004352',
    checkPos: [8],
    sensitive: null,
  },
  {
    id: 'nhs',
    name: 'account.format.nhs.name',
    length: 'account.format.nhs.length',
    check: 'account.format.nhs.check',
    strength: 'account.format.nhs.strength',
    measured: ['account.format.nhs.measured.1'],
    example: '9434765919',
    checkPos: [9],
    sensitive: 'account.format.nhs.sensitive',
  },
  {
    id: 'luhn',
    name: 'account.format.luhn.name',
    length: 'account.format.luhn.length',
    check: 'account.format.luhn.check',
    strength: 'account.format.luhn.strength',
    measured: [],
    example: '4111111111111111',
    checkPos: [15],
    sensitive: 'account.format.luhn.sensitive',
  },
];

function Shape({
  example,
  checkPos,
  bad,
}: {
  example: string;
  checkPos: readonly number[];
  /** Positions the format cannot accept as typed -- drawn, not just coloured. */
  bad?: ReadonlySet<number>;
}) {
  const { t } = useI18n();
  const check = new Set(checkPos);
  return (
    <div
      className="fmt__shape"
      role="img"
      aria-label={`${example} — ${t('formats.legend.check')}: ${checkPos
        .map((i) => i + 1)
        .join(', ')}`}
    >
      {[...example].map((ch, i) => {
        const isCheck = check.has(i);
        const isBad = bad?.has(i) ?? false;
        const kind = isCheck ? 'check' : /\d/.test(ch) ? 'digit' : 'letter';
        return (
          <span
            key={i}
            className={`fmt__slot fmt__slot--${kind}${isBad ? ' fmt__slot--bad' : ''}`}
            aria-hidden="true"
          >
            <span className="fmt__char">{ch}</span>
            {isCheck ? <span className="fmt__tick">{t('formats.legend.check')}</span> : null}
            {isBad ? <span className="fmt__tick fmt__tick--bad">!</span> : null}
          </span>
        );
      })}
    </div>
  );
}

/* "Try one": type any string, pick a format, and the solver's own arithmetic
 * says whether it is valid and, if not, exactly where it fails. POST
 * /api/validate is stateless and unauthenticated; nothing typed here is kept. */
function TryOne() {
  const { t, n } = useI18n();
  const [format, setFormat] = useState<string>(FORMATS[0]?.id ?? 'iso6346');
  const [value, setValue] = useState('');
  const [state, setState] = useState<
    { status: 'idle' } | { status: 'busy' } | { status: 'ok'; result: ValidateResult } | { status: 'failed' }
  >({ status: 'idle' });

  const submit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (value.trim() === '') return;
      setState({ status: 'busy' });
      void validateIdentifier(format, value).then((result) => {
        setState(result.ok ? { status: 'ok', result: result.data } : { status: 'failed' });
      });
    },
    [format, value],
  );

  const result = state.status === 'ok' ? state.result : null;
  const bad = result ? new Set(result.positions.filter((p) => !p.allowed).map((p) => p.index)) : undefined;
  const firstBad = result?.positions.find((p) => !p.allowed) ?? null;

  let verdict: string | null = null;
  let tone: 'ok' | 'bad' = 'bad';
  if (result) {
    if (result.valid) {
      verdict = t('formats.try.valid');
      tone = 'ok';
    } else if (!result.length_ok) {
      verdict = t('formats.try.length', {
        expected: n(result.expected_length),
        got: n(result.normalised.length),
      });
    } else if (firstBad) {
      verdict = t('formats.try.badChar', { n: n(firstBad.index + 1), char: firstBad.char });
    } else {
      verdict = t('formats.try.checkFails');
    }
  }

  return (
    <form className="fmt__try stack" onSubmit={submit}>
      <h2 className="fmt__try-title">{t('formats.try.title')}</h2>
      <div className="fmt__try-row">
        <label className="fmt__try-field">
          <span className="fmt__try-label">{t('formats.try.format')}</span>
          <select value={format} onChange={(e) => setFormat(e.target.value)}>
            {FORMATS.map((f) => (
              <option key={f.id} value={f.id}>
                {t(f.name)}
              </option>
            ))}
          </select>
        </label>
        <label className="fmt__try-field fmt__try-field--grow">
          <span className="fmt__try-label">{t('formats.try.value')}</span>
          <input
            type="text"
            className="mono"
            value={value}
            placeholder={t('formats.try.placeholder')}
            autoCapitalize="characters"
            autoCorrect="off"
            spellCheck={false}
            maxLength={64}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
        <Button busy={state.status === 'busy'} busyLabel={t('formats.try.button')}>
          {t('formats.try.button')}
        </Button>
      </div>

      {state.status === 'failed' ? (
        <p className="fmt__try-verdict fmt__try-verdict--bad" role="status">
          <Icon name="alert" size={16} />
          <span>{t('formats.try.failed')}</span>
        </p>
      ) : result ? (
        <div className="stack" role="status">
          {result.normalised.length > 0 ? (
            <Shape example={result.normalised} checkPos={result.check_positions} bad={bad} />
          ) : null}
          <p className={`fmt__try-verdict fmt__try-verdict--${tone}`}>
            <Icon name={tone === 'ok' ? 'check' : 'alert'} size={16} />
            <span>{verdict}</span>
          </p>
        </div>
      ) : null}
    </form>
  );
}

function Legend() {
  const { t } = useI18n();
  return (
    <p className="fmt__legend" aria-hidden="true">
      <span className="fmt__key fmt__key--letter">{t('formats.legend.letter')}</span>
      <span className="fmt__key fmt__key--digit">{t('formats.legend.digit')}</span>
      <span className="fmt__key fmt__key--check">{t('formats.legend.check')}</span>
    </p>
  );
}

function FormatCard({ f }: { f: FormatDef }) {
  const { t } = useI18n();
  return (
    <li className="fmt__row">
      <div className="fmt__head">
        <h2 className="fmt__name">{t(f.name)}</h2>
        <span className="fmt__length mono">{t(f.length)}</span>
        {f.sensitive ? (
          <span className="fmt__sensitive">
            <Icon name="lock" size={14} />
            <span>{t('formats.sensitive')}</span>
          </span>
        ) : null}
      </div>

      <p className="fmt__example-label">{t('formats.example')}</p>
      <Shape example={f.example} checkPos={f.checkPos} />

      <dl className="fmt__facts">
        <div>
          <dt>{t('formats.method')}</dt>
          <dd>{t(f.check)}</dd>
        </div>
        <div>
          <dt>{t('formats.advantage')}</dt>
          <dd>
            {t(f.strength)}
            {f.measured.map((k) => (
              <span key={k} className="fmt__measured mono">
                {t(k)}
              </span>
            ))}
          </dd>
        </div>
      </dl>

      {f.id === 'iso6346' ? (
        <p className="fmt__note measure">
          {t('account.format.iso6346.note.before')}{' '}
          <span className="fmt__classes mono">{ISO6346_CLASSES}</span>{' '}
          {t('account.format.iso6346.note.after')}
        </p>
      ) : (
        <p className="fmt__note measure">
          {t(`account.format.${f.id}.note` as TranslationKey)}
        </p>
      )}
    </li>
  );
}

export function Formats() {
  const { t } = useI18n();
  return (
    <section className="fmt stack">
      <h1 className="fmt__title">{t('formats.title')}</h1>
      <p className="fmt__intro measure">{t('formats.intro')}</p>
      <TryOne />
      <Legend />
      <ul className="fmt__list">
        {FORMATS.map((f) => (
          <FormatCard key={f.id} f={f} />
        ))}
      </ul>
    </section>
  );
}
