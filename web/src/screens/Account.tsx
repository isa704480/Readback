/* The account area.
 *
 * Five sections, in the order somebody actually needs them: who is on the team,
 * which formats are listening, the vocabulary pack, what is and is not kept, and
 * what it costs.
 *
 * Two things about this screen that are deliberate and easy to undo by accident:
 *
 * 1. Only /api/auth/me and /api/sessions exist. Every other control here is
 *    local to this browser tab, and each one says so in the interface next to
 *    itself, not only in a comment. A settings page that accepts a change, shows
 *    it applied, and forgets it on reload is a worse failure than one that
 *    admits its endpoint is not built.
 *
 * 2. CONSENT is the longest section and that is the point. Readback listens to
 *    calls; the architecture answers the obvious worry about that by never
 *    keeping the audio or the conversation, and an interface that buried the
 *    answer would be throwing away the reason to trust it. There is no
 *    transcript anywhere in this app, which is why the ledger can say so flatly.
 */

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import type { ChangeEvent, FormEvent, ReactNode } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Button, Field, Icon } from '../components';
import { useShell } from '../App';
import { FAILURE_KEY } from './Auth';
import { getSnapshot, listSessions, signOut, subscribe } from '../lib/api';
import type { ApiErrorKind, Capture } from '../lib/api';
import { useI18n } from '../i18n';
import type { I18n, ParamsFor, TranslationKey } from '../i18n';
import {
  DISCLOSURES,
  FORMATS,
  RETENTIONS,
  TEAM_ROLES,
  VOCAB_MAX_CHARS,
  VOCAB_MAX_TERMS,
  asRole,
  capacityState,
  checkTerm,
  countByFormat,
  defaultSwitches,
  emailProblem,
  readUsage,
  usageFrom,
} from '../lib/account';
import type {
  Disclosure,
  FormatId,
  FormatSwitches,
  Retention,
  TeamMember,
  TeamRole,
} from '../lib/account';
import { Bar, Loading, Pending, Skeleton, StateTag, Toggle } from './AccountParts';
import './Account.css';

// ---------------------------------------------------------------- shared --

/* THE PARAMETERLESS KEYS.
 *
 * t() derives its parameter list from the English string for the key it is
 * given, so it needs the key as a LITERAL type. Every lookup table below would
 * otherwise widen its values to the whole TranslationKey union, and t() would
 * demand the union of every placeholder in the catalog at each call site.
 *
 * PlainKey is that union narrowed to the keys whose English carries no {braces}
 * -- which is all of them here except the counted and interpolated ones, which
 * are called by name. Annotating a table `Record<X, PlainKey>` keeps the tables
 * readable AND keeps t() happy, and it fails the build if somebody puts a key
 * that needs a parameter into a table whose call site passes none. */
type PlainKey = {
  [K in TranslationKey]: [ParamsFor<K>] extends [never] ? K : never;
}[TranslationKey];

const SECTIONS: readonly { id: string; index: string; label: PlainKey }[] = [
  { id: 'profile', index: '01', label: 'account.profile.title' },
  { id: 'formats', index: '02', label: 'account.formats.title' },
  { id: 'vocabulary', index: '03', label: 'account.vocab.title' },
  { id: 'consent', index: '04', label: 'account.consent.title' },
  { id: 'usage', index: '05', label: 'account.usage.title' },
];

/* THE SEAM WITH lib/account.ts.
 *
 * That module is the account area's fact record -- the format table, the limits
 * AssemblyAI sets, the consent vocabulary -- and it is not mine to edit. It
 * carries its prose in English with a stable `id` beside every row, so this
 * screen renders the row's id through the catalog rather than the row's English
 * through the page. The English in lib/account.ts stays as the source text.
 *
 * The structural fix, for whoever owns that file next, is a `*Key` field beside
 * each string, exactly as CAPTURE_STATES in lib/api.ts already does with
 * `labelKey` beside `label`. Until then these tables are the seam, and they are
 * exhaustive by type: adding a sixth format or a fourth role fails the build
 * here rather than rendering an English row inside a Russian page. */
const FMT_NAME: Readonly<Record<FormatId, PlainKey>> = {
  iban: 'account.format.iban.name',
  iso6346: 'account.format.iso6346.name',
  nhs: 'account.format.nhs.name',
  vin: 'account.format.vin.name',
  luhn: 'account.format.luhn.name',
};

const FMT_LENGTH: Readonly<Record<FormatId, PlainKey>> = {
  iban: 'account.format.iban.length',
  iso6346: 'account.format.iso6346.length',
  nhs: 'account.format.nhs.length',
  vin: 'account.format.vin.length',
  luhn: 'account.format.luhn.length',
};

const FMT_CHECK: Readonly<Record<FormatId, PlainKey>> = {
  iban: 'account.format.iban.check',
  iso6346: 'account.format.iso6346.check',
  nhs: 'account.format.nhs.check',
  vin: 'account.format.vin.check',
  luhn: 'account.format.luhn.check',
};

const FMT_STRENGTH: Readonly<Record<FormatId, PlainKey>> = {
  iban: 'account.format.iban.strength',
  iso6346: 'account.format.iso6346.strength',
  nhs: 'account.format.nhs.strength',
  vin: 'account.format.vin.strength',
  luhn: 'account.format.luhn.strength',
};

/* The measured lines. Empty where nothing has been measured for that format --
 * the 14.9x and 17.1x figures are ISO 6346 and IBAN-GB and nothing else, and an
 * empty list here is the honest rendering of that. */
const FMT_MEASURED: Readonly<Record<FormatId, readonly PlainKey[]>> = {
  iban: ['account.format.iban.measured.1', 'account.format.iban.measured.2'],
  iso6346: ['account.format.iso6346.measured.1', 'account.format.iso6346.measured.2'],
  nhs: ['account.format.nhs.measured.1'],
  vin: [],
  luhn: [],
};

/* ISO 6346 is absent: its note is split around the congruence classes, which are
 * arithmetic rather than prose and are rendered as mono data. See the note on
 * account.format.iso6346.note.before in i18n/en.ts. */
const FMT_NOTE: Readonly<Record<Exclude<FormatId, 'iso6346'>, PlainKey>> = {
  iban: 'account.format.iban.note',
  nhs: 'account.format.nhs.note',
  vin: 'account.format.vin.note',
  luhn: 'account.format.luhn.note',
};

/** The congruence classes, mod 11. Data, not prose: the same in every language. */
const ISO6346_CLASSES =
  '{A K U} {1 B L V} {2 C M W} {3 D N X} {4 E O Y} {5 F P Z} {6 G Q} {7 H R} {8 I S} {9 J T}';

function noteKey(id: FormatId): PlainKey | null {
  return id === 'iso6346' ? null : FMT_NOTE[id];
}

function sensitiveKey(id: FormatId): PlainKey | null {
  if (id === 'nhs') return 'account.format.nhs.sensitive';
  if (id === 'luhn') return 'account.format.luhn.sensitive';
  return null;
}

const ROLE_NAME: Readonly<Record<TeamRole, PlainKey>> = {
  owner: 'account.role.owner',
  admin: 'account.role.admin',
  operator: 'account.role.operator',
};

const ROLE_CAN: Readonly<Record<TeamRole, PlainKey>> = {
  owner: 'account.role.owner.can',
  admin: 'account.role.admin.can',
  operator: 'account.role.operator.can',
};

const RETENTION_NAME: Readonly<Record<Retention, PlainKey>> = {
  '30': 'account.retention.30',
  '90': 'account.retention.90',
  '365': 'account.retention.365',
  forever: 'account.retention.forever',
};

const DISCLOSURE_LABEL: Readonly<Record<Disclosure, PlainKey>> = {
  readback_announces: 'account.disclosure.announces.label',
  your_own_notice: 'account.disclosure.yours.label',
};

const DISCLOSURE_DETAIL: Readonly<Record<Disclosure, PlainKey>> = {
  readback_announces: 'account.disclosure.announces.detail',
  your_own_notice: 'account.disclosure.yours.detail',
};

/* The three lines of the ledger. Kicker, title and body per row; `kept` decides
 * the tick or the cross. The three items are architecture rather than status,
 * so they carry no state colour at all -- the one exception is the `kept`
 * kicker, which Account.css gives the single accent this view spends, because
 * it is the disclosure a reader must land on rather than a reassurance. */
const LEDGER: readonly {
  kept: boolean;
  kicker: PlainKey;
  title: PlainKey;
  body: PlainKey;
}[] = [
  {
    kept: false,
    kicker: 'account.ledger.audio.kicker',
    title: 'account.ledger.audio.title',
    body: 'account.ledger.audio.body',
  },
  {
    kept: false,
    kicker: 'account.ledger.talk.kicker',
    title: 'account.ledger.talk.title',
    body: 'account.ledger.talk.body',
  },
  {
    kept: true,
    kicker: 'account.ledger.id.kicker',
    title: 'account.ledger.id.title',
    body: 'account.ledger.id.body',
  },
];

/* roleLabel() in lib/account.ts returns the English word, or the server's own
 * spelling for a role this vocabulary does not know. Both cases survive: a
 * known role is translated, an unknown one is rendered exactly as the server
 * spelled it rather than coerced into one of ours. */
function roleName(role: string, t: I18n['t']): string {
  const found = TEAM_ROLES.find((spec) => spec.id === role.toLowerCase());
  return found ? t(ROLE_NAME[found.id]) : role;
}

/* emailProblem() returns prose with no code beside it, so this matches on the
 * whole sentence and hands back the English unchanged when it recognises
 * nothing -- visible, rather than a blank field error. */
const EMAIL_PROBLEM: readonly (readonly [string, PlainKey])[] = [
  ['Enter an email address.', 'account.email.empty'],
  ['An email address cannot contain a space.', 'account.email.space'],
  ['That needs one @ with a name in front of it.', 'account.email.at'],
  ['The part after the @ does not look like a domain.', 'account.email.domain'],
];

function localiseEmailProblem(line: string, t: I18n['t']): string {
  for (const [english, key] of EMAIL_PROBLEM) {
    if (line === english) return t(key);
  }
  return line;
}

/* Hours and minutes, in the reader's units. The leading number goes through
 * n(); the padded remainder does not, because it is a clock-style pair rather
 * than a quantity, and grouping "07" would be wrong in any language. */
function humanise(seconds: number, i18n: I18n): string {
  if (seconds < 60) return i18n.t('account.usage.secs', { s: i18n.n(seconds) });
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return i18n.t('account.usage.mins', {
      m: i18n.n(minutes),
      s: String(seconds % 60).padStart(2, '0'),
    });
  }
  const hours = Math.floor(minutes / 60);
  return i18n.t('account.usage.hrs', {
    h: i18n.n(hours),
    m: String(minutes % 60).padStart(2, '0'),
  });
}

/* readUsage() hands back a note AND the state it belongs to. The state is the
 * code, so the note is looked up by state rather than matched by sentence. */
const USAGE_NOTE: Readonly<Record<'settled' | 'asking' | 'flagged', PlainKey>> = {
  settled: 'account.usage.note.settled',
  asking: 'account.usage.note.asking',
  flagged: 'account.usage.note.flagged',
};

function usageNote(state: ReturnType<typeof readUsage>['state'], t: I18n['t']): string {
  if (state === 'settled' || state === 'asking' || state === 'flagged') {
    return t(USAGE_NOTE[state]);
  }
  return t('account.usage.note.none');
}

/* The vocabulary rejections come back with a `problem` CODE beside the message,
 * so nothing here has to match a sentence. */
/* WHY THESE ARE CODES AND NOT SENTENCES.
 *
 * An error held in state is an error frozen in the language it was raised in.
 * Change the interface language with one on screen and it stays in the old one,
 * because nothing recomputes a string that is already stored -- measured, on
 * this screen, before this type existed. Both carriers below hold the CODE and
 * the figures; the sentence is built during render, so it is always in the
 * language the reader is currently looking at. */
interface InviteProblem {
  /** 'email' carries the English line emailProblem() returned, matched at
   *  render time; 'duplicate' is this screen's own check. */
  kind: 'email' | 'duplicate';
  line: string;
}

interface VocabProblemState {
  problem: 'empty' | 'too_long' | 'duplicate' | 'full';
  /** The length that made it too long. Meaningless for the other three. */
  length: number;
}

function vocabMessage(
  problem: 'empty' | 'too_long' | 'duplicate' | 'full',
  length: number,
  i18n: I18n,
): string {
  if (problem === 'empty') return i18n.t('account.vocab.error.empty');
  if (problem === 'duplicate') return i18n.t('account.vocab.error.duplicate');
  if (problem === 'full') {
    return i18n.t('account.vocab.error.full', { max: i18n.n(VOCAB_MAX_TERMS) });
  }
  return i18n.t('account.vocab.error.tooLong', {
    n: i18n.n(length),
    max: i18n.n(VOCAB_MAX_CHARS),
  });
}

interface SectionProps {
  id: string;
  index: string;
  title: string;
  lede: string;
  children: ReactNode;
}

/* Numbered in mono rather than given an icon each. The five section icons that
 * would fit are all state icons with meanings already assigned, and spending
 * `heard` on a heading marked "Usage" would cost more than the decoration is
 * worth. A number is also the one label that matches the index beside it. */
function Section({ id, index, title, lede, children }: SectionProps) {
  return (
    <section className="sect" id={id} aria-labelledby={`${id}-heading`}>
      <header className="sect__head">
        <p className="sect__index mono">{index}</p>
        <h2 className="sect__title" id={`${id}-heading`}>
          {title}
        </h2>
        <p className="sect__lede">{lede}</p>
      </header>
      {children}
    </section>
  );
}

type SessionsState =
  | { status: 'loading' }
  | { status: 'ok'; captures: Capture[] }
  /* The KIND, not the message. ApiFailure.message is English whoever wrote
     it; the kind is a closed enum and FAILURE_KEY turns it into a sentence
     in the reader's language. Same reasoning as the Auth form. */
  | { status: 'error'; kind: ApiErrorKind };

// ---------------------------------------------------------------- screen --

export function AccountScreen() {
  const i18n = useI18n();
  const { t } = i18n;
  const { account, loading, unreachable, reload } = useShell();

  /* Reactive rather than a bare isSignedIn(): signing out in another tab has to
   * bounce this one too, and this screen is where somebody is most likely to be
   * sitting when that happens. */
  const token = useSyncExternalStore(subscribe, getSnapshot, () => null);

  const [refreshes, setRefreshes] = useState(0);

  /* Sign out lives here now, not in the top bar. A session is part of the
     account, so this is where it belongs — and the bar was carrying six things.
     It is the ONLY sign-out in the app, which is why it had to land somewhere
     reachable rather than simply go: this screen is one click from anywhere, by
     the organisation name in the bar or by the sidebar. */
  const navigate = useNavigate();
  const handleSignOut = () => {
    signOut();
    navigate('/', { replace: true });
  };
  const [sessions, setSessions] = useState<SessionsState>({ status: 'loading' });

  // -- local settings. None of these persist; see the mark on each section.
  const [invites, setInvites] = useState<TeamMember[]>([]);
  const [switches, setSwitches] = useState<FormatSwitches>(defaultSwitches);
  const [terms, setTerms] = useState<string[]>([]);
  const [disclosure, setDisclosure] = useState<Disclosure>('readback_announces');
  const [retention, setRetention] = useState<Retention>('90');

  useEffect(() => {
    if (token === null) return;

    const controller = new AbortController();
    setSessions({ status: 'loading' });

    void listSessions(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) {
        // A 204 or an empty body parses to null, which is not a list.
        setSessions({ status: 'ok', captures: Array.isArray(result.data) ? result.data : [] });
      } else {
        setSessions({ status: 'error', kind: result.kind });
      }
    });

    return () => controller.abort();
  }, [token, refreshes]);

  const refresh = useCallback(() => {
    reload();
    setRefreshes((n) => n + 1);
  }, [reload]);

  const captures = sessions.status === 'ok' ? sessions.captures : [];
  const counts = useMemo(() => countByFormat(captures), [captures]);
  const usage = useMemo(() => usageFrom(captures), [captures]);

  const team = useMemo<TeamMember[]>(() => {
    const rows: TeamMember[] = [];
    if (account) {
      rows.push({
        id: account.id,
        name: account.name,
        email: account.email,
        role: account.role,
        pending: false,
        isYou: true,
      });
    }
    return rows.concat(invites);
  }, [account, invites]);

  // No token at all is a different thing from a token the server cannot confirm
  // right now: only the first is grounds for sending somebody to /login.
  if (token === null) return <Navigate to="/login" replace />;

  const waiting = loading && account === null;

  return (
    <div className="account">
      <header className="account__head">
        <p className="account__eyebrow mono">{t('account.eyebrow')}</p>
        <h1 className="account__title">{t('account.title')}</h1>

        {waiting ? (
          <Loading what={t('account.loading.session')}>
            <div className="account__whose">
              <Skeleton width="14ch" height={20} />
              <Skeleton width="8ch" height={20} />
            </div>
          </Loading>
        ) : (
          <p className="account__whose">
            <span className="mono account__org">
              {account ? account.organisation.name : t('account.org.unknown')}
            </span>
            {account ? <span className="chip chip--plan mono">{account.organisation.plan}</span> : null}
            {account ? (
              <span className="account__role">{roleName(account.role, t)}</span>
            ) : null}
          </p>
        )}

        {unreachable ? (
          <div className="notice notice--offline account__notice" role="alert">
            <Icon name="alert" size={18} />
            <span>{t('account.unreachable')}</span>
          </div>
        ) : null}

        <div className="account__actions">
          <Button
            variant="secondary"
            onClick={refresh}
            busy={loading}
            busyLabel={t('account.refreshing')}
          >
            {t('account.refresh')}
          </Button>

          <Button variant="secondary" onClick={handleSignOut}>
            {t('topbar.signOut')}
          </Button>
        </div>
      </header>

      <div className="account__grid">
        <nav className="account__index" aria-label={t('account.index.label')}>
          <ul className="account__index-list">
            {SECTIONS.map((section) => (
              <li key={section.id}>
                <a className="account__index-link" href={`#${section.id}`}>
                  <span className="mono account__index-n">{section.index}</span>
                  <span>{t(section.label)}</span>
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="account__sections">
          <ProfileSection
            team={team}
            waiting={waiting}
            onRole={(id, role) =>
              setInvites((rows) => rows.map((row) => (row.id === id ? { ...row, role } : row)))
            }
            onRemove={(id) => setInvites((rows) => rows.filter((row) => row.id !== id))}
            onInvite={(member) => setInvites((rows) => rows.concat(member))}
          />

          <FormatsSection
            switches={switches}
            counts={counts}
            sessions={sessions}
            onToggle={(id, next) => setSwitches((current) => ({ ...current, [id]: next }))}
          />

          <VocabularySection
            terms={terms}
            onAdd={(term) => setTerms((rows) => rows.concat(term))}
            onRemove={(term) => setTerms((rows) => rows.filter((row) => row !== term))}
          />

          <ConsentSection
            disclosure={disclosure}
            retention={retention}
            cardEnabled={switches.luhn}
            organisation={account ? account.organisation.name : t('account.org.yours')}
            onDisclosure={setDisclosure}
            onRetention={setRetention}
          />

          <UsageSection usage={usage} sessions={sessions} />
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------- 01 profile, team --

interface ProfileProps {
  team: readonly TeamMember[];
  waiting: boolean;
  onRole: (id: string, role: TeamRole) => void;
  onRemove: (id: string) => void;
  onInvite: (member: TeamMember) => void;
}

function ProfileSection({ team, waiting, onRole, onRemove, onInvite }: ProfileProps) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<TeamRole>('operator');
  const [emailError, setEmailError] = useState<InviteProblem | null>(null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const problem = emailProblem(email);
    if (problem !== null) {
      setEmailError({ kind: 'email', line: problem });
      return;
    }
    if (team.some((member) => member.email.toLowerCase() === email.trim().toLowerCase())) {
      setEmailError({ kind: 'duplicate', line: '' });
      return;
    }

    // AWAITING ITS ENDPOINT: POST /api/team/invites. Nothing is sent. The row
    // below is added to this tab's state and is gone on reload, which is what
    // the "Invited here only" tag on it says.
    onInvite({
      id: `local-${Date.now()}`,
      name: name.trim() || email.trim(),
      email: email.trim(),
      role,
      pending: true,
      isYou: false,
    });

    setName('');
    setEmail('');
    setEmailError(null);
  };

  return (
    <Section
      id="profile"
      index="01"
      title={t('account.profile.title')}
      lede={t('account.profile.lede')}
    >
      <div className="card">
        {waiting ? (
          <Loading what={t('account.loading.team')}>
            <ul className="team">
              {[0, 1].map((row) => (
                <li className="team__row" key={row}>
                  <div className="team__who">
                    <Skeleton width="11ch" height={20} />
                    <Skeleton width="18ch" height={16} />
                  </div>
                  <Skeleton width="9ch" height={46} />
                </li>
              ))}
            </ul>
          </Loading>
        ) : team.length === 0 ? (
          <p className="empty">{t('account.team.empty')}</p>
        ) : (
          <ul className="team">
            {team.map((member) => (
              <li className="team__row" key={member.id}>
                <div className="team__who">
                  <p className="team__name">
                    {member.name}
                    {member.isYou ? (
                      <span className="chip chip--quiet mono">{t('account.team.you')}</span>
                    ) : null}
                    {member.pending ? (
                      <span className="chip chip--quiet mono">
                        {t('account.team.invitedHere')}
                      </span>
                    ) : null}
                  </p>
                  <p className="team__email mono">{member.email}</p>
                </div>

                {member.isYou ? (
                  <div className="team__role">
                    <p className="micro mono">{t('account.team.roleColumn')}</p>
                    <p className="team__role-fixed">{roleName(member.role, t)}</p>
                  </div>
                ) : (
                  <div className="team__role">
                    <label className="micro mono" htmlFor={`role-${member.id}`}>
                      {t('account.team.roleColumn')}
                    </label>
                    <select
                      id={`role-${member.id}`}
                      className="team__select"
                      value={member.role}
                      onChange={(event: ChangeEvent<HTMLSelectElement>) => {
                        const next = asRole(event.target.value);
                        if (next !== null) onRole(member.id, next);
                      }}
                    >
                      {TEAM_ROLES.map((spec) => (
                        <option key={spec.id} value={spec.id}>
                          {t(ROLE_NAME[spec.id])}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {member.isYou ? (
                  <p className="team__note">{t('account.team.cannotRemoveSelf')}</p>
                ) : (
                  <button
                    type="button"
                    className="team__remove"
                    aria-label={t('account.team.remove', { name: member.name })}
                    onClick={() => onRemove(member.id)}
                  >
                    <Icon name="close" size={20} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        {team.length === 1 ? (
          <p className="empty empty--inline">{t('account.team.onlyYou')}</p>
        ) : null}

        <dl className="roles">
          {TEAM_ROLES.map((spec) => (
            <div className="roles__row" key={spec.id}>
              <dt className="roles__name">{t(ROLE_NAME[spec.id])}</dt>
              <dd className="roles__can">{t(ROLE_CAN[spec.id])}</dd>
            </div>
          ))}
        </dl>

        <form className="invite" onSubmit={submit} noValidate>
          <h3 className="invite__title">{t('account.invite.title')}</h3>

          <Field
            label={t('account.invite.name')}
            name="invite-name"
            autoComplete="off"
            value={name}
            onChange={(event) => setName(event.target.value)}
            hint={t('account.invite.nameHint')}
          />

          <Field
            label={t('account.invite.email')}
            type="email"
            name="invite-email"
            inputMode="email"
            autoComplete="off"
            required
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
              if (emailError !== null) setEmailError(null);
            }}
            error={
              emailError === null
                ? null
                : emailError.kind === 'duplicate'
                  ? t('account.invite.duplicate')
                  : localiseEmailProblem(emailError.line, t)
            }
          />

          <div className="invite__role">
            <label className="field__label" htmlFor="invite-role">
              {t('account.invite.role')}
            </label>
            <select
              id="invite-role"
              name="invite-role"
              value={role}
              onChange={(event: ChangeEvent<HTMLSelectElement>) => {
                const next = asRole(event.target.value);
                if (next !== null) setRole(next);
              }}
            >
              {TEAM_ROLES.map((spec) => (
                <option key={spec.id} value={spec.id}>
                  {t(ROLE_NAME[spec.id])}
                </option>
              ))}
            </select>
          </div>

          <Button type="submit">{t('account.invite.submit')}</Button>
        </form>

        <Pending endpoint="POST /api/team/invites">{t('account.pending.team')}</Pending>
      </div>
    </Section>
  );
}

// ------------------------------------------------------------ 02 formats --

interface FormatsProps {
  switches: FormatSwitches;
  counts: Record<FormatId, number>;
  sessions: SessionsState;
  onToggle: (id: FormatId, next: boolean) => void;
}

function FormatsSection({ switches, counts, sessions, onToggle }: FormatsProps) {
  const i18n = useI18n();
  const { t, plural } = i18n;
  return (
    <Section
      id="formats"
      index="02"
      title={t('account.formats.title')}
      lede={t('account.formats.lede')}
    >
      <div className="card">
        <p className="prose">{t('account.formats.prose1')}</p>

        {/* The two emphasised phrases are the capture vocabulary itself, pulled
            from capture.state.* rather than respelled here, so this paragraph
            and the tag on every row below cannot end up saying different words
            in any language. The three fragments are joined with one space, and
            each translation is written so that reads correctly. */}
        <p className="prose prose--rule">
          {t('account.formats.prose2.lead')} <strong>{t('capture.state.repaired')}</strong>{' '}
          {t('account.formats.prose2.mid')} <strong>{t('capture.state.asking')}</strong>{' '}
          {t('account.formats.prose2.tail')}
        </p>

        <ul className="fmts">
          {FORMATS.map((spec) => {
            const on = switches[spec.id];
            const count = counts[spec.id];

            return (
              <li className={`fmt${on ? ' fmt--on' : ''}`} key={spec.id}>
                <div className="fmt__head">
                  <div className="fmt__id">
                    <h3 className="fmt__name">{t(FMT_NAME[spec.id])}</h3>
                    {/* The standard names itself. Not translated: "ISO 13616"
                        is not an English phrase, it is an identifier. */}
                    <p className="fmt__standard mono">{spec.standard}</p>
                  </div>
                  <Toggle
                    checked={on}
                    onChange={(next) => onToggle(spec.id, next)}
                    label={`${t(FMT_NAME[spec.id])}, ${spec.standard}`}
                  />
                </div>

                <div className="fmt__repair">
                  <StateTag state={spec.repair} />
                  <p className="fmt__strength">{t(FMT_STRENGTH[spec.id])}</p>
                </div>

                <dl className="facts">
                  <div className="facts__row">
                    <dt className="facts__key">{t('account.formats.shape')}</dt>
                    {/* A machine pattern, left alone for the same reason as the
                        standard above. */}
                    <dd className="facts__value mono">{spec.shape}</dd>
                  </div>
                  <div className="facts__row">
                    <dt className="facts__key">{t('account.formats.length')}</dt>
                    <dd className="facts__value">{t(FMT_LENGTH[spec.id])}</dd>
                  </div>
                  <div className="facts__row">
                    <dt className="facts__key">{t('account.formats.check')}</dt>
                    <dd className="facts__value">
                      {spec.check === null
                        ? t('account.formats.noCheck')
                        : t(FMT_CHECK[spec.id])}
                    </dd>
                  </div>
                  <div className="facts__row">
                    <dt className="facts__key">{t('account.formats.onRecord')}</dt>
                    <dd className="facts__value">
                      {sessions.status === 'loading' ? (
                        <Skeleton width="10ch" height={16} />
                      ) : sessions.status === 'error' ? (
                        <span className="facts__unknown">
                          {t('account.formats.notCounted')}
                        </span>
                      ) : count === 0 ? (
                        <span className="facts__unknown">{t('account.formats.noCaptures')}</span>
                      ) : (
                        /* plural(), not an appended "s". Russian needs three
                           forms and puts 21 back on the singular. */
                        <span className="mono">{plural('account.formats.captures', count)}</span>
                      )}
                    </dd>
                  </div>
                </dl>

                {FMT_MEASURED[spec.id].length > 0 ? (
                  <ul className="fmt__measured">
                    {FMT_MEASURED[spec.id].map((key) => (
                      <li key={key}>
                        <Icon name="check" size={16} />
                        <span>{t(key)}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}

                <p className="fmt__note">
                  <span className="micro mono">{t('account.formats.cannot')}</span>
                  {noteKey(spec.id) === null ? (
                    <>
                      {t('account.format.iso6346.note.before')}{' '}
                      <span className="mono">{ISO6346_CLASSES}</span>{' '}
                      {t('account.format.iso6346.note.after')}
                    </>
                  ) : (
                    t(noteKey(spec.id) as NonNullable<ReturnType<typeof noteKey>>)
                  )}
                </p>

                {sensitiveKey(spec.id) !== null ? (
                  <p className="fmt__sensitive">
                    <Icon name="lock" size={16} />
                    <span>
                      {t(sensitiveKey(spec.id) as NonNullable<ReturnType<typeof sensitiveKey>>)}{' '}
                      {t('account.formats.sensitive.before')}{' '}
                      <a className="link-hit" href="#consent">
                        {t('account.consent.title')}
                      </a>{' '}
                      {t('account.formats.sensitive.after')}
                    </span>
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>

        <Pending endpoint="PUT /api/formats">{t('account.pending.formats')}</Pending>
      </div>
    </Section>
  );
}

// --------------------------------------------------------- 03 vocabulary --

interface VocabularyProps {
  terms: readonly string[];
  onAdd: (term: string) => void;
  onRemove: (term: string) => void;
}

function VocabularySection({ terms, onAdd, onRemove }: VocabularyProps) {
  const i18n = useI18n();
  const { t, n } = i18n;
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<VocabProblemState | null>(null);

  const trimmed = draft.trim();
  const full = terms.length >= VOCAB_MAX_TERMS;
  const fraction = terms.length / VOCAB_MAX_TERMS;
  const capacity = capacityState(fraction);

  /* Validated as typed rather than capped with maxLength. A maxLength would make
   * the 51st character vanish silently, which on a pasted part number reads as
   * the app having accepted something it did not. */
  const change = (event: ChangeEvent<HTMLInputElement>) => {
    const value = event.target.value;
    setDraft(value);

    const length = value.trim().length;
    if (length > VOCAB_MAX_CHARS) {
      setError({ problem: 'too_long', length });
    } else if (error !== null) {
      setError(null);
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const check = checkTerm(draft, terms);
    if (!check.ok) {
      /* checkTerm hands back a CODE beside its English message, so nothing here
         has to recognise a sentence. */
      setError({ problem: check.problem, length: draft.trim().replace(/\s+/g, ' ').length });
      return;
    }
    // AWAITING ITS ENDPOINT: PUT /api/vocabulary. Local to this tab.
    onAdd(check.term);
    setDraft('');
    setError(null);
  };

  return (
    <Section
      id="vocabulary"
      index="03"
      title={t('account.vocab.title')}
      lede={t('account.vocab.lede')}
    >
      <div className="card">
        <div className="vocab__gauge">
          <p className="vocab__count">
            <span className="vocab__figure mono">{n(terms.length)}</span>
            <span className="vocab__of mono">
              {t('account.vocab.of', { max: n(VOCAB_MAX_TERMS) })}
            </span>
          </p>
          <Bar
            fraction={fraction}
            state={capacity}
            label={t('account.vocab.barLabel')}
            valueText={t('account.vocab.barValue', {
              used: n(terms.length),
              max: n(VOCAB_MAX_TERMS),
            })}
          />
          {fraction >= 0.8 ? <StateTag state={capacity} /> : null}
        </div>

        {/* Split around the two figures so they keep their mono setting. The
            parts are joined with one space and each translation is written to
            read correctly that way. */}
        <p className="prose">
          {t('account.vocab.prose.a')} <span className="mono">{n(VOCAB_MAX_TERMS)}</span>{' '}
          {t('account.vocab.prose.b')} <span className="mono">{n(VOCAB_MAX_CHARS)}</span>{' '}
          {t('account.vocab.prose.c')}
        </p>

        <form className="vocab__form" onSubmit={submit} noValidate>
          {/* No autoCapitalize on the field below: a pack holds carrier prefixes
              (MAEU) and place names (Felixstowe) in the same list, and forcing
              either case is wrong for the other half of them. Spellcheck is off,
              because none of these are words the dictionary has met. */}
          <Field
            className="field--mono"
            label={t('account.vocab.add')}
            name="vocab-term"
            autoComplete="off"
            spellCheck={false}
            value={draft}
            onChange={change}
            error={error === null ? null : vocabMessage(error.problem, error.length, i18n)}
            hint={
              /* The live count keeps its mono setting because it is the thing
                 that moves; the ceiling rides inside the sentence. */
              <>
                <span className="mono">{n(trimmed.length)}</span>{' '}
                {t('account.vocab.hint', { max: n(VOCAB_MAX_CHARS) })}
              </>
            }
          />
          <Button type="submit" disabled={full}>
            {t('account.vocab.addButton')}
          </Button>
          {full ? (
            <p className="vocab__full">
              {t('account.vocab.full', { max: n(VOCAB_MAX_TERMS) })}
            </p>
          ) : null}
        </form>

        {terms.length === 0 ? (
          <p className="empty">{t('account.vocab.empty')}</p>
        ) : (
          <ul className="vocab__list">
            {terms.map((term) => (
              <li className="vocab__item" key={term}>
                <span className="vocab__term mono">{term}</span>
                <button
                  type="button"
                  className="vocab__remove"
                  aria-label={t('account.vocab.remove', { term })}
                  onClick={() => onRemove(term)}
                >
                  <Icon name="close" size={20} />
                </button>
              </li>
            ))}
          </ul>
        )}

        <Pending endpoint="PUT /api/vocabulary">{t('account.pending.vocab')}</Pending>
      </div>
    </Section>
  );
}

// ------------------------------------------------------------ 04 consent --

interface ConsentProps {
  disclosure: Disclosure;
  retention: Retention;
  cardEnabled: boolean;
  organisation: string;
  onDisclosure: (next: Disclosure) => void;
  onRetention: (next: Retention) => void;
}

function ConsentSection({
  disclosure,
  retention,
  cardEnabled,
  organisation,
  onDisclosure,
  onRetention,
}: ConsentProps) {
  const { t } = useI18n();
  return (
    <Section
      id="consent"
      index="04"
      title={t('account.consent.title')}
      lede={t('account.consent.lede')}
    >
      <div className="card consent">
        <p className="prose prose--lead">{t('account.consent.lead')}</p>

        <ul className="ledger">
          {LEDGER.map((item) => (
            <li
              className={`ledger__item${item.kept ? ' ledger__item--kept' : ''}`}
              key={item.kicker}
            >
              <p className="ledger__kicker mono">
                <Icon name={item.kept ? 'check' : 'close'} size={18} />
                <span>{t(item.kicker)}</span>
              </p>
              <h3 className="ledger__title">{t(item.title)}</h3>
              <p className="ledger__body">{t(item.body)}</p>
            </li>
          ))}
        </ul>

        <p className="prose prose--seam">{t('account.consent.seam')}</p>

        {/* A div with role="radiogroup" rather than fieldset/legend. A legend has
            to hold a state tag beside its text here, and a legend with a
            non-default display is the one box in CSS that still renders
            differently in each engine. The group is labelled by its heading
            instead, which announces identically and lays out predictably. */}
        <div className="decide" role="radiogroup" aria-labelledby="disclosure-heading">
          <h3 className="decide__legend" id="disclosure-heading">
            <span>{t('account.consent.disclosure.title')}</span>
            <StateTag state="asking" />
          </h3>

          <p className="decide__body">{t('account.consent.disclosure.body')}</p>

          {DISCLOSURES.map((option) => (
            <label className="radio" key={option.id} htmlFor={`disclosure-${option.id}`}>
              <input
                className="radio__input"
                type="radio"
                id={`disclosure-${option.id}`}
                name="disclosure"
                value={option.id}
                checked={disclosure === option.id}
                onChange={() => onDisclosure(option.id)}
              />
              <span className="radio__text">
                <span className="radio__label">{t(DISCLOSURE_LABEL[option.id])}</span>
                <span className="radio__detail">{t(DISCLOSURE_DETAIL[option.id])}</span>
              </span>
            </label>
          ))}
        </div>

        <div className="decide">
          <h3 className="decide__legend">
            <span>{t('account.consent.retention.title')}</span>
            <StateTag state="asking" />
          </h3>

          <p className="decide__body">{t('account.consent.retention.body')}</p>

          <div className="decide__control">
            <label className="field__label" htmlFor="retention">
              {t('account.consent.retention.label')}
            </label>
            <select
              id="retention"
              name="retention"
              className="decide__select"
              value={retention}
              onChange={(event: ChangeEvent<HTMLSelectElement>) => {
                const value = event.target.value;
                const found = RETENTIONS.find((option) => option.id === value);
                if (found) onRetention(found.id);
              }}
            >
              {RETENTIONS.map((option) => (
                <option key={option.id} value={option.id}>
                  {t(RETENTION_NAME[option.id])}
                </option>
              ))}
            </select>
          </div>
        </div>

        {cardEnabled ? (
          <div className="notice notice--offline" role="note">
            <Icon name="alert" size={18} />
            <span>
              {t('account.consent.card.before')}{' '}
              <a className="link-hit" href="#formats">
                {t('account.formats.title')}
              </a>{' '}
              {t('account.consent.card.after')}
            </span>
          </div>
        ) : null}

        <p className="consent__scope">
          <Icon name="shield" size={18} />
          <span>
            {t('account.consent.scope.before')} <span className="mono">{organisation}</span>{' '}
            {t('account.consent.scope.mid')} <code className="mono">GET /api/sessions</code>{' '}
            {t('account.consent.scope.after')}
          </span>
        </p>

        <Pending endpoint="PUT /api/consent">{t('account.pending.consent')}</Pending>
      </div>
    </Section>
  );
}

// -------------------------------------------------------------- 05 usage --

interface UsageProps {
  usage: ReturnType<typeof usageFrom>;
  sessions: SessionsState;
}

function UsageSection({ usage, sessions }: UsageProps) {
  const i18n = useI18n();
  const { t, n } = i18n;
  const reading = readUsage(usage);
  const note = usageNote(reading.state, t);

  return (
    <Section
      id="usage"
      index="05"
      title={t('account.usage.title')}
      lede={t('account.usage.lede')}
    >
      <div className="card">
        {sessions.status === 'loading' ? (
          <Loading what={t('account.loading.usage')}>
            <div className="usage__reading">
              <Skeleton width="9ch" height={34} />
              <Skeleton width="100%" height={14} />
              <Skeleton width="24ch" height={16} />
            </div>
          </Loading>
        ) : (
          <div className="usage__reading">
            <p className="usage__figure">
              <span className="mono">
                {usage.accountedSeconds === null ? '--' : humanise(usage.accountedSeconds, i18n)}
              </span>
              <span className="usage__of">
                {t('account.usage.of')}{' '}
                <span className="mono">
                  {usage.planSeconds === null
                    ? t('account.usage.notReported')
                    : humanise(usage.planSeconds, i18n)}
                </span>
              </span>
            </p>

            <Bar
              fraction={reading.fraction}
              state={reading.state}
              label={t('account.usage.barLabel')}
              valueText={reading.state === null ? t('account.usage.noReading') : note}
            />

            {/* The bar already says NO READING in that case, and saying it a
                second time beside it would read as two separate facts. */}
            <p className="usage__note">
              {reading.state === null ? null : <StateTag state={reading.state} />}
              <span>{note}</span>
            </p>
          </div>
        )}

        {sessions.status === 'error' ? (
          <div className="notice notice--offline" role="alert">
            <Icon name="alert" size={18} />
            <span>
              {t('account.usage.error')} {t(FAILURE_KEY[sessions.kind])}
            </span>
          </div>
        ) : sessions.status === 'ok' && usage.captures === 0 ? (
          <p className="empty">{t('account.usage.empty')}</p>
        ) : (
          <dl className="counts">
            <div className="counts__cell">
              <dt className="counts__key">{t('account.usage.captures')}</dt>
              <dd className="counts__value mono">
                {sessions.status === 'loading' ? (
                  <Skeleton width="4ch" height={28} />
                ) : (
                  n(usage.captures)
                )}
              </dd>
            </div>
            <div className="counts__cell">
              <dt className="counts__key">{t('account.usage.questions')}</dt>
              <dd className="counts__value mono">
                {sessions.status === 'loading' ? (
                  <Skeleton width="4ch" height={28} />
                ) : (
                  n(usage.questions)
                )}
              </dd>
            </div>
            <div className="counts__cell">
              <dt className="counts__key">{t('account.usage.silent')}</dt>
              <dd className="counts__value mono">
                {sessions.status === 'loading' ? (
                  <Skeleton width="4ch" height={28} />
                ) : (
                  n(usage.silent)
                )}
              </dd>
            </div>
          </dl>
        )}

        <p className="prose prose--rule">
          <span className="micro mono">{t('account.usage.counts.kicker')}</span>
          {t('account.usage.counts.body')}
        </p>

        <p className="prose">
          {t('account.usage.derived.before')} <code className="mono">GET /api/sessions</code>{' '}
          {t('account.usage.derived.after')}
        </p>

        <Pending endpoint="GET /api/usage">{t('account.pending.usage')}</Pending>
      </div>
    </Section>
  );
}
