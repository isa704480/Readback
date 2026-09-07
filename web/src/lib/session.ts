/* Session and transport.
 *
 * This is the base layer: it owns the API origin, the token, and the one fetch
 * wrapper everything else goes through. lib/api.ts sits on top and adds the
 * typed endpoints. The dependency runs one way only -- api.ts imports from
 * here, never the reverse -- so there is no import cycle to reason about.
 */

/* The server agent is building against :8000. Set VITE_READBACK_API to an empty
 * string to go same-origin instead, which routes through the dev proxy in
 * vite.config.ts and is what a deployed build wants. */
const RAW_BASE = import.meta.env.VITE_READBACK_API;

export const apiBase: string =
  RAW_BASE === undefined ? 'http://localhost:8000' : RAW_BASE.replace(/\/+$/, '');

const TOKEN_KEY = 'readback.token';

/* Every request gets this long before it is treated as "the server is not
 * there". Long enough for a cold container start, short enough that a screen
 * does not sit blank while a user wonders whether they clicked. */
const TIMEOUT_MS = 12_000;

// ---------------------------------------------------------------- results --

export type ApiErrorKind =
  | 'offline' // no response at all: server down, DNS, CORS, dropped connection
  | 'timeout'
  | 'bad_request' // 400
  | 'unauthorized' // 401 / 403
  | 'not_found' // 404
  | 'conflict' // 409
  | 'rate_limited' // 429
  | 'server' // 5xx
  | 'malformed'; // 2xx whose body was not the shape the contract promises

export interface ApiFailure {
  ok: false;
  status: number; // 0 when no response was received
  kind: ApiErrorKind;
  /** Machine-readable code from the server, or a local one when it never replied. */
  error: string;
  /** Safe to render. Always populated, so no screen has to invent copy. */
  message: string;
  /** Whatever else the body carried, e.g. password_check on a 400 from signup. */
  body?: unknown;
}

export interface ApiSuccess<T> {
  ok: true;
  status: number;
  data: T;
}

export type ApiResult<T> = ApiSuccess<T> | ApiFailure;

// ------------------------------------------------------------------ types --

export interface Organisation {
  id: string;
  name: string;
  plan: string;
}

export interface Account {
  id: string;
  name: string;
  email: string;
  role: string;
  organisation: Organisation;
}

export interface AuthPayload {
  token: string;
  account: Account;
}

// ---------------------------------------------------------------- storage --

/* Reading localStorage throws outright in a Safari private window and wherever
 * site data is blocked by policy -- not just on write, but on the property
 * access itself. Everything here is guarded, and a blocked store degrades to
 * memory: the user stays signed in for the life of the tab instead of being
 * bounced to /login by an exception. */
let memoryToken: string | null = null;

function store(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  try {
    const value = store()?.getItem(TOKEN_KEY);
    if (value) return value;
  } catch {
    /* fall through to the memory copy */
  }
  return memoryToken;
}

export function setToken(token: string): void {
  memoryToken = token;
  try {
    store()?.setItem(TOKEN_KEY, token);
  } catch {
    /* quota, private mode, blocked site data. The memory copy already took. */
  }
  emit();
}

export function clearToken(): void {
  memoryToken = null;
  try {
    store()?.removeItem(TOKEN_KEY);
  } catch {
    /* nothing to do: if it cannot be removed it was never written */
  }
  emit();
}

export function isSignedIn(): boolean {
  return getToken() !== null;
}

// ------------------------------------------------------------ subscription --

/* Small store so TopBar and route guards can track sign-in without prop
 * drilling. Shaped for useSyncExternalStore. */
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);

  // Signing out in one tab should sign out the others.
  const onStorage = (event: StorageEvent) => {
    if (event.key === TOKEN_KEY || event.key === null) {
      memoryToken = null;
      listener();
    }
  };
  window.addEventListener('storage', onStorage);

  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

/** getSnapshot for useSyncExternalStore. Returns the token itself so a
 *  component re-renders when the identity changes, not merely when it appears. */
export function getSnapshot(): string | null {
  return getToken();
}

// ----------------------------------------------------------------- headers --

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// --------------------------------------------------------------- transport --

function kindFor(status: number): ApiErrorKind {
  if (status === 400) return 'bad_request';
  if (status === 401 || status === 403) return 'unauthorized';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 429) return 'rate_limited';
  if (status >= 500) return 'server';
  return 'malformed';
}

const DEFAULT_MESSAGE: Record<ApiErrorKind, string> = {
  offline: 'Cannot reach the Readback service. Check your connection and try again.',
  timeout: 'The Readback service did not answer in time. Try again.',
  bad_request: 'Some of those details were not accepted.',
  unauthorized: 'That email and password did not match an account.',
  not_found: 'That is not available.',
  conflict: 'An account already exists for that email.',
  rate_limited: 'Too many attempts. Wait a minute, then try again.',
  server: 'The Readback service had a problem at its end. Try again shortly.',
  malformed: 'The Readback service returned something unexpected.',
};

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  /** Attach the bearer token. */
  auth?: boolean;
  signal?: AbortSignal;
  /** Override TIMEOUT_MS for a call that is known to take longer -- a replay
   *  that asks a question and waits out the answer budget in real time. */
  timeoutMs?: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/* The whole client returns results rather than throwing. A screen with the
 * server absent has to render an error state, and code that throws makes a
 * blank page the default outcome instead. */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<ApiResult<T>> {
  const { method = 'GET', body, auth = false, signal, timeoutMs = TIMEOUT_MS } = options;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  // A caller-supplied signal has to be able to cancel the request too, e.g. an
  // unmounting screen.
  const onExternalAbort = () => controller.abort();
  signal?.addEventListener('abort', onExternalAbort);

  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (auth) Object.assign(headers, authHeaders());

  let response: Response;
  try {
    response = await fetch(`${apiBase}${path}`, {
      method,
      headers,
      signal: controller.signal,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    // fetch rejects identically for a dead server, a CORS refusal and an abort,
    // so the timer is the only way to tell a timeout from an outage.
    const kind: ApiErrorKind = controller.signal.aborted ? 'timeout' : 'offline';
    return { ok: false, status: 0, kind, error: kind, message: DEFAULT_MESSAGE[kind] };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onExternalAbort);
  }

  // 204, or an endpoint that answers with an empty body.
  const text = await response.text().catch(() => '');
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }

  if (!response.ok) {
    const kind = kindFor(response.status);

    // A 401 means the token is gone or was never good. Dropping it here keeps
    // every screen from having to remember to.
    if (response.status === 401 && auth) clearToken();

    const error = isRecord(parsed) && typeof parsed['error'] === 'string' ? parsed['error'] : kind;
    const message =
      isRecord(parsed) && typeof parsed['message'] === 'string'
        ? parsed['message']
        : DEFAULT_MESSAGE[kind];

    return { ok: false, status: response.status, kind, error, message, body: parsed };
  }

  return { ok: true, status: response.status, data: parsed as T };
}

// ------------------------------------------------------------- who is this --

function isAccount(value: unknown): value is Account {
  if (!isRecord(value)) return false;
  const org = value['organisation'];
  return (
    typeof value['id'] === 'string' &&
    typeof value['email'] === 'string' &&
    isRecord(org) &&
    typeof org['id'] === 'string'
  );
}

/** GET /api/auth/me. Validates the shape rather than trusting it, so a screen
 *  never renders `undefined` into the page because the contract drifted. */
export async function fetchAccount(signal?: AbortSignal): Promise<ApiResult<Account>> {
  const result = await request<{ account: unknown }>('/api/auth/me', {
    auth: true,
    ...(signal ? { signal } : {}),
  });
  if (!result.ok) return result;

  const account = isRecord(result.data) ? result.data['account'] : null;
  if (!isAccount(account)) {
    return {
      ok: false,
      status: result.status,
      kind: 'malformed',
      error: 'malformed_account',
      message: DEFAULT_MESSAGE.malformed,
    };
  }
  return { ok: true, status: result.status, data: account };
}

/** Sign out locally. There is no server call in the contract, and a token that
 *  is gone from this device is gone regardless of what the server thinks. */
export function signOut(): void {
  clearToken();
}
