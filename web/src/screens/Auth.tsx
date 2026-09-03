import { useMemo, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button, Field, Icon, PasswordStrength } from '../components';
import type { IconName } from '../components';
import { listWithAnd, localisePasswordLine } from '../components/PasswordStrength';
import { login, passwordCheckFrom, signup } from '../lib/api';
import type { ApiErrorKind, ApiFailure, PasswordCheck } from '../lib/api';
import { useI18n } from '../i18n';
import type { I18n, TranslationKey } from '../i18n';
import './Auth.css';

/* Sign in and sign up are one component with two modes.
 *
 * The fields differ. The mechanics -- validation timing, how an error clears,
 * which field gets focus when a submit fails, how a server verdict is attached
 * to a field and then let go of -- are identical, and two copies of them drift
 * apart on the first change either one gets.
 */

export type AuthMode = 'login' | 'signup';

type FieldName = 'name' | 'company' | 'email' | 'password';
type Errors = Partial<Record<FieldName, string>>;
type Flags = Partial<Record<FieldName, boolean>>;

const ALL_FIELDS: readonly FieldName[] = ['name', 'company', 'email', 'password'];

/* Also the tab order, which is what "focus the first invalid field" means. */
const ORDER: Record<AuthMode, readonly FieldName[]> = {
  login: ['email', 'password'],
  signup: ['name', 'company', 'email', 'password'],
};

/* Catalog keys, not sentences.
 *
 * `as const` is load-bearing: it keeps each value a literal type, which is what
 * lets t() work out that none of these takes a parameter. Annotated as
 * Record<AuthMode, Record<string, TranslationKey>> instead, every key would
 * widen to the whole union and t() would demand the union of every placeholder
 * in the catalog at each call site. */
const COPY = {
  login: {
    title: 'auth.login.title',
    blurb: 'auth.login.blurb',
    submit: 'auth.login.submit',
    busy: 'auth.login.busy',
    footLead: 'auth.login.footLead',
    footLink: 'auth.login.footLink',
    footTo: '/signup',
  },
  signup: {
    title: 'auth.signup.title',
    blurb: 'auth.signup.blurb',
    submit: 'auth.signup.submit',
    busy: 'auth.signup.busy',
    footLead: 'auth.signup.footLead',
    footLink: 'auth.signup.footLink',
    footTo: '/login',
  },
} as const;

/** The field labels, by the same rule. */
const LABEL = {
  name: 'auth.field.name',
  company: 'auth.field.company',
  email: 'auth.field.email',
  password: 'auth.field.password',
} as const satisfies Record<FieldName, TranslationKey>;

// ------------------------------------------------------------- validation --

/* The server's minimum, restated. It is in the hint before anybody types
 * rather than in an error after they fail, because a rule you are told once you
 * have broken it is a rule that was withheld.
 *
 * THE NUMBER LIVES HERE AND THE SENTENCE LIVES IN THE CATALOG, interpolated as
 * {min}. A translator cannot turn "at least 10" into "at least 8" by accident,
 * because there is no 10 in any translation to mistype. The three classes are
 * named by three catalog keys (pw.class.letter / .number / .symbol) that both
 * the rule sentence and the error which enforces it draw from, so the rule and
 * its enforcement cannot drift into describing different policies. */
const MIN_PASSWORD = 10;

/* Unicode-aware, and the three classes partition the string: a symbol is
 * anything that is neither a letter nor a number, which includes the space a
 * passphrase is made of. Matching on [A-Za-z] instead would reject a perfectly
 * good password written in Cyrillic and then count its letters as symbols. */
const HAS_LETTER = /\p{L}/u;
const HAS_NUMBER = /\p{N}/u;
const HAS_SYMBOL = /[^\p{L}\p{N}]/u;

/* Deliberately loose. The job here is to catch "name@company" and a trailing
 * space before spending a round trip, not to adjudicate RFC 5322 -- every regex
 * that tries to ends up rejecting addresses that deliver. The server decides. */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function passwordProblem(password: string, i18n: I18n): string | null {
  // Code points, not UTF-16 units. An emoji is one character to the person
  // typing it and two to String.length, and being told a 10-character password
  // is 8 characters long is not a rule anyone can act on.
  const length = [...password].length;
  if (length < MIN_PASSWORD) {
    // Both figures through n(), so the count and the words around it come from
    // the same language rather than the count coming from the OS.
    return i18n.t('pw.problem.shortCount', {
      min: i18n.n(MIN_PASSWORD),
      have: i18n.n(length),
    });
  }

  const missing: string[] = [];
  if (!HAS_LETTER.test(password)) missing.push(i18n.t('pw.class.letter'));
  if (!HAS_NUMBER.test(password)) missing.push(i18n.t('pw.class.number'));
  if (!HAS_SYMBOL.test(password)) missing.push(i18n.t('pw.class.symbol'));

  return missing.length === 0
    ? null
    : i18n.t('pw.problem.add', { missing: listWithAnd(missing, i18n.t('pw.list.and')) });
}

/* Returns a whole, fresh error set every time. Nothing is merged into a
 * previous one, which is the only way a corrected field can still be showing
 * the error it was corrected out of: there is no previous set to survive in. */
function validate(mode: AuthMode, values: Record<FieldName, string>, i18n: I18n): Errors {
  const errors: Errors = {};

  if (mode === 'signup') {
    if (values.name.trim() === '') errors.name = i18n.t('auth.error.name');
    if (values.company.trim() === '') errors.company = i18n.t('auth.error.company');
  }

  const email = values.email.trim();
  if (email === '') errors.email = i18n.t('auth.error.email.empty');
  else if (!EMAIL.test(email)) errors.email = i18n.t('auth.error.email.shape');

  if (values.password === '') {
    errors.password = i18n.t(
      mode === 'signup' ? 'auth.error.password.choose' : 'auth.error.password.enter',
    );
  } else if (mode === 'signup') {
    // Only on signup. An existing password predates whatever the rule is today,
    // and telling someone at the login screen that their password is too short
    // is a statement about the value on the server.
    const problem = passwordProblem(values.password, i18n);
    if (problem !== null) errors.password = problem;
  }

  return errors;
}

// ----------------------------------------------------------- server errors --

/* Which field a failure belongs under, if any.
 *
 * A 401 is deliberately not in this list. The server answers one message for a
 * wrong email and a wrong password on purpose; hanging that message under the
 * email field would say which half was wrong just as clearly as the words
 * would, so it stays at form level.
 */
function failureField(mode: AuthMode, failure: ApiFailure): FieldName | null {
  if (mode === 'signup' && failure.kind === 'conflict') return 'email';
  if (failure.kind === 'bad_request' && passwordCheckFrom(failure.body) !== null) return 'password';
  return null;
}

/* Retry-After is read out of the body, not the header. Retry-After is not a
 * CORS-safelisted response header, and the front end is on a different origin
 * from the API in development and in any split deployment, so the header is
 * unreadable without Access-Control-Expose-Headers and returns null the moment
 * that is dropped. The body is always there. */
function retryAfterSeconds(failure: ApiFailure): number | null {
  if (typeof failure.body !== 'object' || failure.body === null) return null;
  const record = failure.body as Record<string, unknown>;

  for (const key of ['retry_after', 'retry_after_seconds', 'retryAfter']) {
    const value = record[key];
    if (typeof value === 'number' && Number.isFinite(value) && value > 0) return value;
    if (typeof value === 'string') {
      const parsed = Number.parseInt(value, 10);
      if (Number.isFinite(parsed) && parsed > 0) return parsed;
    }
  }
  return null;
}

/* Words, not a number of seconds. Vague on purpose past a minute: a wait
 * printed to the second is a wait somebody sits and watches.
 *
 * plural(), not a bare count. The rounding here lands on 20, 30, 40 and 50
 * seconds and on any number of minutes, and Russian needs three forms with 21
 * back on the singular. */
function humanWait(seconds: number, i18n: I18n): string {
  if (seconds <= 15) return i18n.t('wait.moment');
  if (seconds < 60) return i18n.plural('wait.seconds', Math.ceil(seconds / 10) * 10);
  if (seconds < 90) return i18n.t('wait.aboutMinute');
  return i18n.plural('wait.minutes', Math.round(seconds / 60));
}

/* WHY THE KIND AND NOT THE MESSAGE.
 *
 * ApiFailure carries a `message` that is safe to render, and it is written
 * either by the server or by DEFAULT_MESSAGE in lib/session.ts -- in English
 * both ways, with no way to ask for another language. Rendering it inside a
 * Russian form would leave the one sentence that matters the only one on screen
 * the reader cannot read.
 *
 * The KIND is a closed enum and it is what the reader actually needs. offline,
 * timeout and unauthorized are three different situations with three different
 * things to do about them; lib/session.ts already keeps them apart and this
 * table keeps them apart in three languages. The cost is that a server-authored
 * message is no longer shown here -- weighed against a message two thirds of
 * the audience cannot read, and lost. */
/* Exported for screens/Account.tsx, which renders the same nine situations.
 * One table, not two: a second copy would keep compiling while the two screens
 * disagreed about what a 409 says. */
export const FAILURE_KEY = {
  offline: 'error.offline',
  timeout: 'error.timeout',
  bad_request: 'error.badRequest',
  unauthorized: 'error.unauthorized',
  not_found: 'error.notFound',
  conflict: 'error.conflict',
  rate_limited: 'error.rateLimited',
  server: 'error.server',
  malformed: 'error.malformed',
} as const satisfies Record<ApiErrorKind, TranslationKey>;

function noticeMessage(failure: ApiFailure, i18n: I18n): string {
  if (failure.kind !== 'rate_limited') return i18n.t(FAILURE_KEY[failure.kind]);
  const seconds = retryAfterSeconds(failure);
  return seconds === null
    ? i18n.t('error.rateLimited')
    : i18n.t('error.rateLimited.wait', { when: humanWait(seconds, i18n) });
}

interface NoticeSkin {
  className: string;
  icon: IconName;
}

/* The state vocabulary, applied to a form-level message -- and the three kinds
 * are separated by the WORD and the ICON, not by a hue.
 *
 * A rate limit is a wait: nothing is wrong with what was typed, the interface
 * is asking for a minute, and it takes the info glyph and no colour at all. An
 * outage is the same shape of claim about the network rather than the input, so
 * it takes the alert glyph and its own sentence. Only a real refusal is
 * flagged, which is the single state --alert is reserved for.
 *
 * Every one of the three states its cause AND its fix in the message body; the
 * skin is reinforcement, never the distinction. */
function noticeSkin(kind: ApiErrorKind): NoticeSkin {
  if (kind === 'offline' || kind === 'timeout') return { className: 'notice--offline', icon: 'alert' };
  if (kind === 'rate_limited') return { className: 'notice--wait', icon: 'info' };
  return { className: 'notice--error', icon: 'flagged' };
}

// ----------------------------------------------------------------- screen --

export interface AuthProps {
  mode: AuthMode;
}

export function Auth({ mode }: AuthProps) {
  const navigate = useNavigate();
  const i18n = useI18n();
  const { t } = i18n;

  const [values, setValues] = useState<Record<FieldName, string>>({
    name: '',
    company: '',
    email: '',
    password: '',
  });
  const [touched, setTouched] = useState<Flags>({});
  const [edited, setEdited] = useState<Flags>({});
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [check, setCheck] = useState<PasswordCheck | null>(null);

  const refs = useRef<Record<FieldName, HTMLInputElement | null>>({
    name: null,
    company: null,
    email: null,
    password: null,
  });

  /* One stable ref callback per field. A callback whose identity changes is
   * detached and reattached on every render, and this form re-renders on every
   * keystroke. */
  const setRef = useMemo(
    () =>
      Object.fromEntries(
        ALL_FIELDS.map((field) => [
          field,
          (element: HTMLInputElement | null) => {
            refs.current[field] = element;
          },
        ]),
      ) as Record<FieldName, (element: HTMLInputElement | null) => void>,
    [],
  );

  /* /login and /signup reconcile onto the same component instance, so the mode
   * can change under a form still holding the last screen's state. A 401 raised
   * by the login form has no business sitting above the signup form. This is
   * the documented render-phase adjustment rather than an effect, so the stale
   * state is never painted. */
  const [lastMode, setLastMode] = useState<AuthMode>(mode);
  if (lastMode !== mode) {
    setLastMode(mode);
    setTouched({});
    setEdited({});
    setSubmitted(false);
    setFailure(null);
    setCheck(null);
    // The email is a courtesy to carry across. The password is not: a password
    // typed at one screen should not silently become the answer at the other.
    setValues((current) => ({ ...current, password: '' }));
  }

  const copy = COPY[mode];
  const isSignup = mode === 'signup';

  /* Derived on every render, never stored. An error set that is not state
   * cannot go stale, so "they fixed the field and the old message stayed" is
   * unreachable rather than merely guarded against. */
  const errors = validate(mode, values, i18n);

  const attributed = failure === null ? null : failureField(mode, failure);
  const failureCheck = useMemo(
    () => (failure === null ? null : passwordCheckFrom(failure.body)),
    [failure],
  );

  function errorFor(field: FieldName): string | null {
    /* The server's verdict outranks ours, but only until that field is edited
     * again: once the email in the box is a different email, "an account
     * already exists for that email" is about a value that is no longer there. */
    if (attributed === field && edited[field] !== true) {
      /* The server's password verdict is English prose from server/password.py.
         localisePasswordLine matches the sentence it produced and renders the
         catalog line for it, falling back to the English when it recognises
         nothing -- see the note at the top of components/PasswordStrength.tsx.
         Everything else is keyed off failure.kind, never failure.message. */
      if (field === 'password') {
        const line = failureCheck?.problems[0];
        if (line !== undefined) return localisePasswordLine(line, i18n);
      }
      return failure === null ? null : t(FAILURE_KEY[failure.kind]);
    }

    /* On blur, not on keystroke. Nobody wants to be told their half-typed email
     * is invalid. Once a field has been blurred once it does keep validating as
     * they type, which is the half of the rule that says a corrected field must
     * clear itself without waiting to be blurred a second time. */
    if (!submitted && touched[field] !== true) return null;
    return errors[field] ?? null;
  }

  function change(field: FieldName) {
    return (event: ChangeEvent<HTMLInputElement>) => {
      const next = event.target.value;
      setValues((current) => ({ ...current, [field]: next }));
      setEdited((current) => (current[field] === true ? current : { ...current, [field]: true }));

      // A password_check is a verdict on one exact string. The moment the string
      // changes it is describing something that is no longer in the box.
      if (field === 'password') setCheck(null);
    };
  }

  function blur(field: FieldName) {
    return () => {
      setTouched((current) => (current[field] === true ? current : { ...current, [field]: true }));
    };
  }

  function bind(field: FieldName) {
    return {
      value: values[field],
      onChange: change(field),
      onBlur: blur(field),
      error: errorFor(field),
      inputRef: setRef[field],
    };
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setSubmitted(true);
    setEdited({});
    setFailure(null);

    const problems = validate(mode, values, i18n);
    const firstBad = ORDER[mode].find((field) => problems[field] !== undefined);
    if (firstBad !== undefined) {
      refs.current[firstBad]?.focus();
      return;
    }

    setBusy(true);

    // Trimmed on the way out rather than while typing: rewriting the box under
    // somebody mid-word is worse than the stray space it removes.
    const email = values.email.trim();
    const result = isSignup
      ? await signup({
          name: values.name.trim(),
          company: values.company.trim(),
          email,
          password: values.password,
        })
      : await login({ email, password: values.password });

    setBusy(false);

    if (result.ok) {
      navigate('/account', { replace: true });
      return;
    }

    setFailure(result);
    setCheck(passwordCheckFrom(result.body));

    const field = failureField(mode, result);
    if (field !== null) refs.current[field]?.focus();
  }

  /* A failure that belongs to a field is shown under that field and nowhere
   * else. The notice is for what has no field: a refusal, a rate limit, an
   * outage. */
  const notice = failure !== null && attributed === null ? noticeMessage(failure, i18n) : null;
  const skin = failure === null ? null : noticeSkin(failure.kind);

  return (
    <div className="auth">
      <div className="card">
        <h1 className="auth__title">{t(copy.title)}</h1>
        <p className="auth__sub">{t(copy.blurb)}</p>

        {/* noValidate: the browser's own bubbles cannot be positioned under the
            field they belong to, cannot be read by the same live region, and
            disappear on the next click. */}
        <form className="stack stack--tight auth__form" onSubmit={onSubmit} noValidate>
          {notice === null || skin === null ? null : (
            <div className={`notice ${skin.className}`} role="alert">
              <Icon name={skin.icon} size={18} />
              <span>{notice}</span>
            </div>
          )}

          {isSignup ? (
            <>
              <Field
                label={t(LABEL.name)}
                name="name"
                autoComplete="name"
                required
                {...bind('name')}
              />
              <Field
                label={t(LABEL.company)}
                name="company"
                autoComplete="organization"
                required
                {...bind('company')}
              />
            </>
          ) : null}

          <Field
            label={t(LABEL.email)}
            type="email"
            name="email"
            autoComplete="email"
            inputMode="email"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            required
            {...bind('email')}
          />

          <Field
            label={t(LABEL.password)}
            type="password"
            name="password"
            autoComplete={isSignup ? 'new-password' : 'current-password'}
            reveal
            required
            hint={isSignup ? t('pw.rule', { min: i18n.n(MIN_PASSWORD) }) : undefined}
            {...bind('password')}
          >
            {isSignup ? (
              <PasswordStrength
                password={values.password}
                email={values.email}
                name={values.name}
                company={values.company}
                serverCheck={check}
              />
            ) : null}
          </Field>

          {/* Never disabled on invalid input. A disabled submit gives no reason
              and no place to put focus; pressing it and being taken to the first
              field that needs work does both. */}
          <Button type="submit" block busy={busy} busyLabel={t(copy.busy)}>
            {t(copy.submit)}
          </Button>
        </form>
      </div>

      {/* The swap link. Both halves are localised, and the destination is a
          route rather than a word, so the sentence can be reordered in a
          language that puts the question after the offer. */}
      <p className="auth__foot">
        {t(copy.footLead)} <Link to={copy.footTo}>{t(copy.footLink)}</Link>
      </p>
    </div>
  );
}
