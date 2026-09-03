/* Local password scoring — the half of the verdict that needs no server.
 *
 * server/password.py opens with the split this file exists to honour:
 *
 *   1. composition and length  -- arithmetic, instant, local
 *   2. predictability          -- keyboard runs, repeats, common words
 *   3. has it already leaked   -- the only question needing an external service
 *
 * The client had none of 1 and 2. Everything went to /api/auth/check-password,
 * so with the server unreachable the meter sat at "Strength not checked" with
 * four unlit segments while the person typed a password nobody was judging.
 * A network round trip to discover that eight characters is fewer than ten is
 * the wrong shape of answer even when the network is up.
 *
 * So: 1 and 2 run here, on every keystroke, offline, and the meter is coloured
 * from the first character. 3 stays on the server and arrives later, upgrading
 * the verdict when it does.
 *
 * PARITY IS THE WHOLE RISK. If this file and server/password.py disagree, the
 * meter says Strong and the signup says no, which is worse than having no meter.
 * They are kept in step by tests/test_password_parity.py, which compiles this
 * module, runs both implementations over the same vectors, and diffs every
 * field. Change one, run that, change the other.
 *
 * The advisory/authoritative rule from server/auth.py holds in both directions:
 * nothing here decides anything. The server re-runs the identical check at
 * signup and is the only opinion that counts.
 */

import type { PasswordCheck } from './api';

export const MIN_LENGTH = 10;
export const MAX_LENGTH = 200; // hashing a megabyte of input is a free denial of service

/* Sequences people reach for when told "add a number and a symbol". */
const KEYBOARD_RUNS = ['qwertyuiop', 'asdfghjkl', 'zxcvbnm', '1234567890', '!@#$%^&*()'];

const COMMON = new Set([
  'password', 'passw0rd', 'letmein', 'welcome', 'admin', 'qwerty',
  'iloveyou', 'monkey', 'dragon', 'football', 'baseball', 'sunshine',
  'princess', 'superman', 'trustno1', 'changeme', 'secret', 'master',
  'hello', 'freedom', 'whatever', 'starwars', 'abc123', '123456',
]);

const LABELS = ['Very weak', 'Weak', 'Fair', 'Strong', 'Very strong'];

interface Classes {
  lower: boolean;
  upper: boolean;
  digit: boolean;
  symbol: boolean;
}

function classesOf(password: string): Classes {
  return {
    lower: /[a-z]/.test(password),
    upper: /[A-Z]/.test(password),
    digit: /\d/.test(password),
    symbol: /[^A-Za-z0-9]/.test(password),
  };
}

/* Cheap pattern checks that catch the passwords composition rules let through.
 * "Password1!" satisfies every rule and is one of the most common passwords in
 * existence, so composition alone is not a policy.
 *
 * Order and the early return are load-bearing for parity: the Python original
 * returns as soon as it finds a keyboard run, so the findings after it are not
 * reached in that case. Reproduced exactly rather than tidied. */
function predictable(password: string): string[] {
  const found: string[] = [];
  const low = password.toLowerCase();

  const stripped = low.replace(/[^a-z]/g, '');
  if (stripped && COMMON.has(stripped)) {
    found.push('It is a very common password with numbers or symbols bolted on.');
  } else if (COMMON.has(low)) {
    found.push('It is one of the most common passwords in use.');
  }

  for (const run of KEYBOARD_RUNS) {
    for (let size = 4; size <= 6; size += 1) {
      for (let i = 0; i + size <= run.length; i += 1) {
        const chunk = run.slice(i, i + size);
        const backwards = [...chunk].reverse().join('');
        if (low.includes(chunk) || low.includes(backwards)) {
          found.push('It contains a straight run across the keyboard.');
          return found;
        }
      }
    }
  }

  if (/(.)\1{2,}/.test(password)) {
    found.push('It repeats the same character three or more times.');
  }

  if (new Set(password).size <= Math.max(2, Math.floor(password.length / 4))) {
    found.push('It uses too few distinct characters.');
  }

  /* Word-then-number-then-symbol: "Summer2024!".
   *
   * The head is a single alphabetic word on purpose. server/password.py carries
   * the measurement and the reason: the original `\D*` swallowed separators too,
   * which rejected "Tarmoq-Qishloq-42!" — eighteen characters, four classes, two
   * unrelated words. A policy that refuses good passwords teaches people to
   * fight the meter. */
  if (/^[A-Za-z]+\d{1,4}[!@#$%^&*]?$/.test(password || 'x')) {
    found.push('Word-then-number-then-symbol is the first thing an attacker tries.');
  }

  return found;
}

export interface LocalContext {
  email?: string;
  name?: string;
  company?: string;
}

/* The local verdict, shaped as a PasswordCheck so strengthOf() consumes it
 * unchanged and there is still exactly one place a state colour is decided.
 *
 * `breach_checked` is false and `breached` is false, and the pair is honest
 * rather than optimistic: this function has not asked, and "not asked" is not
 * "safe". The distinction is what lets the UI show "Not in any known breach"
 * only when the server actually said so. */
export function evaluateLocally(password: string, context: LocalContext = {}): PasswordCheck {
  const problems: string[] = [];
  const suggestions: string[] = [];

  if (password.length > MAX_LENGTH) {
    return {
      ok: false,
      score: 0,
      label: 'Too long',
      problems: [`Keep it under ${MAX_LENGTH} characters.`],
      suggestions: [],
      breached: false,
      breach_checked: false,
    };
  }

  if (password.length < MIN_LENGTH) {
    problems.push(`Use at least ${MIN_LENGTH} characters.`);
  }

  const cls = classesOf(password);
  const missing: string[] = [];
  if (!(cls.lower || cls.upper)) missing.push('a letter');
  if (!cls.digit) missing.push('a number');
  if (!cls.symbol) missing.push('a symbol');
  if (missing.length > 0) problems.push(`Include ${missing.join(', ')}.`);

  // Personal data in a password is the first guess anyone makes. The context
  // rides along rather than being kept back, which is why the signup form hands
  // over the name, company and address it already has.
  const low = password.toLowerCase();
  const pairs: Array<[string, string]> = [
    ['email', (context.email ?? '').split('@')[0] ?? ''],
    ['name', context.name ?? ''],
    ['company', context.company ?? ''],
  ];
  for (const [label, value] of pairs) {
    const token = value.trim().toLowerCase();
    if (token.length >= 4 && low.includes(token)) {
      problems.push(`Do not put your ${label} in your password.`);
    }
  }

  problems.push(...predictable(password));

  // Length does most of the work, variety and unpredictability the rest.
  let score = 0;
  if (password.length >= MIN_LENGTH) score += 1;
  if (password.length >= 14) score += 1;
  if (Number(cls.lower) + Number(cls.upper) + Number(cls.digit) + Number(cls.symbol) >= 3) {
    score += 1;
  }
  if (new Set(password).size >= 8 && predictable(password).length === 0) score += 1;
  score = Math.max(0, Math.min(4, score - (problems.length > 0 ? 1 : 0)));

  if (password.length < 14) {
    suggestions.push(
      'Length beats cleverness — four unrelated words are stronger than one word with substitutions.',
    );
  }
  if (problems.length === 0 && score < 3) {
    suggestions.push('Add a few more characters to make it comfortably strong.');
  }

  return {
    ok: problems.length === 0,
    score,
    label: LABELS[score] ?? 'Very weak',
    problems,
    suggestions,
    breached: false,
    breach_checked: false,
  };
}

/* Name the level explicitly, because the fallback in strengthOf() loses one.
 *
 * The four-level vocabulary lives in lib/api.ts. strengthOf() picks a level by
 * matching check.label against those names, and failing that by indexing on
 * score. Neither path can reach 'good': the server's labels are "Very weak /
 * Weak / Fair / Strong / Very strong", so "Very weak" and "Very strong" match
 * nothing, and the index fallback is min(3, score), which maps BOTH score 3 and
 * score 4 onto 'strong'. The visible result is a four-segment meter that only
 * ever shows one, two or four segments lit -- steel, the three-segment state, is
 * unreachable, and a person going from Fair to Strong sees the meter jump.
 *
 * Handing strengthOf() a name from the vocabulary it already declares restores
 * the missing state without creating a second place that decides a colour:
 * strengthOf still owns the colour, the word and the icon. When lib/api.ts is
 * next opened the better fix is for strengthOf to take the 0-4 score directly
 * and delete the name matching; this exists so the meter is right in the
 * meantime.
 */
const LEVEL_BY_SCORE = ['weak', 'weak', 'fair', 'good', 'strong'];

export function levelNameForScore(score: number): string {
  const index = Math.max(0, Math.min(4, Math.round(score)));
  return LEVEL_BY_SCORE[index] ?? 'weak';
}


/* Fold the server's answer onto the local one.
 *
 * The server is authoritative wherever it has spoken, and the only thing it
 * knows that this file does not is the breach lookup — so when the lookup did
 * not happen (offline, or HIBP down), the local verdict is kept rather than
 * being replaced by a server verdict that is the same arithmetic reached more
 * slowly. That is what stops a dropped connection from blanking a meter the
 * user is watching. */
export function mergeVerdicts(local: PasswordCheck, server: PasswordCheck | null): PasswordCheck {
  if (server === null) return local;
  return server;
}
