/* The typed client for the Readback API.
 *
 * Contract:
 *   POST /api/auth/signup          {name, company, email, password}
 *                                  -> {token, account} | 400 | 409 | 429
 *   POST /api/auth/login           {email, password} -> {token, account} | 401 | 429
 *   GET  /api/auth/me              -> {account}
 *   POST /api/auth/check-password  {password, email, name, company} -> PasswordCheck
 *   GET  /api/sessions             -> Capture[] for the signed-in company
 *                                  ?limit=1..200 &before &before_id | 400 | 401
 *   POST /api/demo/replay          {fixture} -> the event stream, no key needed
 *   GET  /health
 *
 * Nothing here throws. Every call hands back a discriminated ApiResult so a
 * screen renders an error state instead of a blank page when the server is not
 * there -- which, while the backend is being written in parallel, is the
 * common case rather than the edge one.
 */

import { request, setToken, clearToken } from './session';
import type { ApiResult, AuthPayload } from './session';
import type { IconName } from '../components/Icon';
/* Type-only. The label vocabulary names catalog keys so a localised screen can
 * resolve them; this file itself never calls t() and never imports the runtime. */
import type { TranslationKey } from '../i18n';

export type {
  Account,
  Organisation,
  AuthPayload,
  ApiResult,
  ApiFailure,
  ApiSuccess,
  ApiErrorKind,
} from './session';

export { apiBase, fetchAccount, getToken, isSignedIn, signOut, subscribe, getSnapshot } from './session';

// ------------------------------------------------------------------- auth --

export interface SignupInput {
  name: string;
  company: string;
  email: string;
  password: string;
}

export interface LoginInput {
  email: string;
  password: string;
}

/* Both auth calls store the token on the way through. Doing it here rather than
 * in each screen means there is exactly one place a session can begin. */
async function authenticate(
  path: string,
  body: SignupInput | LoginInput,
): Promise<ApiResult<AuthPayload>> {
  const result = await request<AuthPayload>(path, { method: 'POST', body });
  if (result.ok && typeof result.data?.token === 'string') {
    setToken(result.data.token);
  }
  return result;
}

export function signup(input: SignupInput): Promise<ApiResult<AuthPayload>> {
  return authenticate('/api/auth/signup', input);
}

export function login(input: LoginInput): Promise<ApiResult<AuthPayload>> {
  return authenticate('/api/auth/login', input);
}

export function logout(): void {
  clearToken();
}

// -------------------------------------------------------- password checking --

export interface PasswordCheck {
  ok: boolean;
  /** 0-3, one per meter segment. Clamped on read: see strengthOf. */
  score: number;
  label: string;
  problems: string[];
  suggestions: string[];
  breached: boolean;
  breach_checked: boolean;
}

const EMPTY_CHECK: PasswordCheck = {
  ok: false,
  score: 0,
  label: 'weak',
  problems: [],
  suggestions: [],
  breached: false,
  breach_checked: false,
};

export function checkPassword(
  input: { password: string; email?: string; name?: string; company?: string },
  signal?: AbortSignal,
): Promise<ApiResult<PasswordCheck>> {
  return request<PasswordCheck>('/api/auth/check-password', {
    method: 'POST',
    body: input,
    ...(signal ? { signal } : {}),
  });
}

/* A 400 from signup carries password_check alongside the error. Pulling it out
 * is fiddly enough, and needed in enough places, to be worth doing once. */
export function passwordCheckFrom(body: unknown): PasswordCheck | null {
  if (typeof body !== 'object' || body === null) return null;
  const raw = (body as Record<string, unknown>)['password_check'];
  if (typeof raw !== 'object' || raw === null) return null;
  const record = raw as Record<string, unknown>;
  return {
    ...EMPTY_CHECK,
    ...(typeof record['ok'] === 'boolean' ? { ok: record['ok'] } : {}),
    ...(typeof record['score'] === 'number' ? { score: record['score'] } : {}),
    ...(typeof record['label'] === 'string' ? { label: record['label'] } : {}),
    ...(Array.isArray(record['problems']) ? { problems: record['problems'] as string[] } : {}),
    ...(Array.isArray(record['suggestions'])
      ? { suggestions: record['suggestions'] as string[] }
      : {}),
    ...(typeof record['breached'] === 'boolean' ? { breached: record['breached'] } : {}),
    ...(typeof record['breach_checked'] === 'boolean'
      ? { breach_checked: record['breach_checked'] }
      : {}),
  };
}

// ------------------------------------------------------- strength vocabulary --

export type StrengthLevel = 'weak' | 'fair' | 'good' | 'strong';

export interface Strength {
  level: StrengthLevel;
  /** Segments lit, 1-4. */
  filled: number;
  /** A CSS custom property from tokens.css. Never a literal colour. */
  token: string;
  /** Colour is never the only carrier: this word ships next to the meter. */
  label: string;
  icon: IconName;
}

/* THE SEMANTIC RULE, applied.
 *
 * This is not a red-to-amber-to-green ramp that happens to have four stops. The
 * four state colours already mean something in the capture rack and the
 * meanings carry over unchanged:
 *
 *   weak / breached -> --red    flagged, the same red as a flagged capture
 *   fair            -> --amber  needs one thing from you
 *   good            -> --steel  heard, not settled
 *   strong          -> --green  settled and quietly correct
 *
 * measured luminance puts red, steel, green and amber within 1.3 points of each
 * other, so they are one greyscale. Hence `label` and `icon`, which are not
 * decoration. */
const STRENGTH: Record<StrengthLevel, Strength> = {
  weak: { level: 'weak', filled: 1, token: '--red', label: 'Weak', icon: 'flagged' },
  fair: { level: 'fair', filled: 2, token: '--amber', label: 'Fair', icon: 'asking' },
  good: { level: 'good', filled: 3, token: '--steel', label: 'Good', icon: 'heard' },
  strong: { level: 'strong', filled: 4, token: '--green', label: 'Strong', icon: 'settled' },
};

const BY_SCORE: readonly StrengthLevel[] = ['weak', 'fair', 'good', 'strong'];

export function strengthOf(check: PasswordCheck | null): Strength {
  if (!check) return STRENGTH.weak;

  // A breached password is flagged whatever it scores. Length and entropy say
  // nothing about a string that is already in a wordlist.
  if (check.breached) {
    return { ...STRENGTH.weak, label: 'Found in a breach', icon: 'flagged' };
  }

  const named = check.label.trim().toLowerCase();
  for (const level of BY_SCORE) {
    if (named === level) return STRENGTH[level];
  }

  // zxcvbn-style 0-4 scales collapse to four segments: 0 and 1 are both weak.
  const index = Math.min(BY_SCORE.length - 1, Math.max(0, Math.round(check.score)));
  return STRENGTH[BY_SCORE[index] ?? 'weak'];
}

export const STRENGTH_SEGMENTS = BY_SCORE.length; // 4

// --------------------------------------------------------------- captures --

/* No longer provisional. GET /api/sessions has landed and this is the shape it
 * ships, field for field -- server/main.py:capture_row, asserted key-for-key by
 * tests/test_sessions_api.py so the two cannot drift without a red test.
 *
 * `state` is the display vocabulary and `status` is the database's own word for
 * the row. They are deliberately different alphabets: "quietly repaired" and
 * "needs one thing from you" describe how a row was reached, not whether it
 * validated, and the server derives `state` once so two screens cannot disagree.
 *
 * Nothing here can hold the conversation an identifier came out of, because no
 * column behind it can either. There is no transcript, no surrounding text, no
 * per-word anything -- and no confidence number, because this system says it is
 * unsure by asking rather than by printing a percentage. */
export type CaptureState = 'heard' | 'repaired' | 'asking' | 'settled' | 'flagged';

/** What the row is to the database. Three values, not five. */
export type CaptureStatus = 'committed' | 'flagged' | 'unverified';

export interface Capture {
  id: string;
  /** ISO6346, IBAN-GB, NHS, VIN, Luhn ... */
  format: string;
  /** The settled identifier, or what was heard when it never settled. `state`
   *  is what says which of the two this is, and it always ships beside it. */
  value: string;
  state: CaptureState;
  status: CaptureStatus;
  /** Written without the agent speaking once. The product, in one boolean. */
  silent: boolean;
  /** Repaired from the check digit. `repaired && silent` is the green state. */
  repaired: boolean;
  /** 0-based index of the character that changed; null when nothing did. */
  repaired_position: number | null;
  /** Times the agent had to interrupt. 0 is the product working. */
  questions: number;
  /** Last word of the identifier to the row being written. null when untimed. */
  ms_to_settle: number | null;
  /** 'replay' is a fixture, not a call. Carried so a simulated row can say so
   *  on screen rather than pass for one heard on a live line. */
  source: 'live' | 'replay';
  created_at: string;
}

export interface CaptureStateMeta {
  /* The English word, kept as a plain string.
   *
   * Still read directly by screens that have not been moved onto the catalog
   * yet (screens/Account.tsx, screens/AccountParts.tsx). Removing it would
   * break them, so it stays as the English source text and `labelKey` is added
   * beside it. Anything still reading `label` renders visible English rather
   * than failing quietly, which is the honest failure mode of the two. */
  label: string;
  /** The localised label. Resolve through t() from src/i18n. */
  labelKey: TranslationKey;
  token: string;
  icon: IconName;
}

/* The vocabulary, in one place, with a word and a shape attached to every
 * colour. Measured luminance for steel/green/muted/red lands between 8.0 and
 * 9.3 -- they are the same grey. Any screen that renders state from colour
 * alone is unreadable to a monochrome display and to most colour-blind users,
 * so this record makes the label and the icon as easy to reach as the token.
 *
 * `as const satisfies` rather than a type annotation: an annotation would widen
 * labelKey to the whole TranslationKey union, and t() would then demand the
 * union of every placeholder in the catalog at each call site. `satisfies`
 * checks the shape while `as const` keeps each labelKey as its own literal, so
 * the compiler knows these five keys take no parameters -- and it still rejects
 * a key that is not in the catalog. */
export const CAPTURE_STATES = {
  heard: {
    label: 'Heard, not settled',
    labelKey: 'capture.state.heard',
    token: '--steel',
    icon: 'heard',
  },
  repaired: {
    label: 'Quietly repaired',
    labelKey: 'capture.state.repaired',
    token: '--green',
    icon: 'repaired',
  },
  asking: {
    label: 'Needs one thing from you',
    labelKey: 'capture.state.asking',
    token: '--amber',
    icon: 'asking',
  },
  settled: { label: 'Settled', labelKey: 'capture.state.settled', token: '--ink', icon: 'settled' },
  flagged: { label: 'Flagged', labelKey: 'capture.state.flagged', token: '--red', icon: 'flagged' },
} as const satisfies Record<CaptureState, CaptureStateMeta>;

/* Bounded, and the server refuses to be talked out of it: 50 newest by default,
 * 200 the ceiling, and a limit above it is a 400 rather than a silent clamp --
 * a page quietly missing rows is worse than one that says so. There is more
 * behind a page that comes back full, and the cursor is the last row itself:
 * pass its `created_at` as `before` and its `id` as `before_id`. No screen needs
 * page two yet, so this call does not take the parameters; adding them is one
 * line here when one does. */
export function listSessions(signal?: AbortSignal): Promise<ApiResult<Capture[]>> {
  return request<Capture[]>('/api/sessions', { auth: true, ...(signal ? { signal } : {}) });
}

// ------------------------------------------------------------------- demo --

/* The replay stream. Deliberately has no transcript field and no confidence
 * field: the architecture never stores the conversation, and the system
 * expresses uncertainty by asking rather than by printing a number. */
export type ReplayEvent =
  | { type: 'listening'; at_ms: number }
  | { type: 'heard'; at_ms: number; format: string; raw: string }
  | { type: 'repaired'; at_ms: number; position: number; from: string; to: string }
  | { type: 'question'; at_ms: number; position: number; prompt: string }
  | { type: 'answer'; at_ms: number; character: string }
  | { type: 'settled'; at_ms: number; value: string; questions: number }
  | { type: 'flagged'; at_ms: number; value: string; reason: string };

export interface ReplayResponse {
  fixture: string;
  format: string;
  events: ReplayEvent[];
}

/* auth: true, on a route that does not require it.
 *
 * The server treats a token here as ATTRIBUTION, never as access: with one, the
 * session and its captures are filed under that user's organisation; without
 * one — or with a stale one — the caller gets the identical demo as an anonymous
 * visitor, because DESIGN-BRIEF section 4.5 exists for a judge who arrives with
 * no account and must reach the experience in one click.
 *
 * Without this flag the server's new attribution was unreachable from the
 * browser: a signed-in operator clicking the demo still filed everything under
 * the demo tenant and their own dashboard stayed empty. authHeaders() returns {}
 * when there is no token, so the signed-out path sends nothing extra and is
 * unchanged. */
export function demoReplay(fixture: string, signal?: AbortSignal): Promise<ApiResult<ReplayResponse>> {
  return request<ReplayResponse>('/api/demo/replay', {
    method: 'POST',
    auth: true,
    body: { fixture },
    ...(signal ? { signal } : {}),
  });
}

// ----------------------------------------------------------------- health --

export interface Health {
  status: string;
}

export function health(signal?: AbortSignal): Promise<ApiResult<Health>> {
  return request<Health>('/health', { ...(signal ? { signal } : {}) });
}
