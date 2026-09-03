/* The account area's model: the format table, the vocabulary limits, the consent
 * vocabulary, and the usage derivation.
 *
 * It sits apart from the screen because most of it is fact rather than
 * interface. What an ISO 6346 check digit is blind to does not change when the
 * layout does, and every claim below is traceable to docs/FINDINGS.md, to the
 * README measurement table, or to the validator in server/readback that
 * implements the arithmetic. A number with no source does not go in this file.
 *
 * Nothing here touches the network. Most of these settings have no endpoint yet
 * -- the contract covers auth, sessions, replay and health, and no more -- so
 * the screen marks every unsaved control in the interface as well as in a
 * comment. A settings page that silently forgets is worse than one that says
 * out loud it cannot save.
 */

import type { Capture, CaptureState } from './api';

// --------------------------------------------------------------- formats --

export type FormatId = 'iso6346' | 'iban' | 'vin' | 'nhs' | 'luhn';

/* Only two of the five state colours can appear on a format row, and the choice
 * between them is not a grade for the standard. It is a prediction about how
 * often this company will be interrupted:
 *
 *   repaired (green)  the arithmetic is strong enough that most mishearings are
 *                     fixed without anyone being asked
 *   asking  (amber)   the arithmetic is weaker, so the agent speaks more often
 *
 * That is the same meaning these colours carry in the capture rack, which is the
 * whole point of the semantic rule. Nothing here invents a third sense of green.
 */
export type RepairState = Extract<CaptureState, 'repaired' | 'asking'>;

export interface FormatSpec {
  id: FormatId;
  name: string;
  /** The standard, as the standard names itself. */
  standard: string;
  /** What one looks like. Mono, because a machine reads it. */
  shape: string;
  length: string;
  /** The arithmetic. null would mean a format carrying no check digit at all;
   *  none of these five are, and a format that were would be `asking` by
   *  definition, since there would be nothing for the solver to check against. */
  check: string | null;
  repair: RepairState;
  /** One line on how much the check digit can absorb. Sits under the tag. */
  strength: string;
  /** Measured, with its source. Empty where we have not measured this format --
   *  the 14.9x and 17.1x figures are ISO 6346 and IBAN-GB and nothing else. */
  measured: readonly string[];
  /** The caveat. Always rendered, never behind a disclosure. */
  note: string;
  /** What Readback captures here is worth thinking about before it is on. */
  sensitive?: string;
  onByDefault: boolean;
}

/* Ordered by how much the arithmetic buys, strongest first, so the row a reader
 * lands on first is the one the product is most confident about. */
export const FORMATS: readonly FormatSpec[] = [
  {
    id: 'iban',
    name: 'IBAN',
    standard: 'ISO 13616 / ISO 7064',
    shape: 'GB00 BANK 0000 0000 0000 00',
    length: '16 to 34 characters, fixed per country',
    check: 'Two check digits, mod-97-10',
    repair: 'repaired',
    strength: 'The strongest arithmetic here. Two check digits over the whole string.',
    measured: [
      'Error budget 0.0023 unconstrained, 0.0399 constrained: 17.1x, the largest gain measured.',
      'Spread across the eight accents tested: 1.14x.',
    ],
    note:
      'The country code fixes the length before the arithmetic runs, so a dropped character is caught by the shape rather than by the checksum. Ten country lengths are known to the validator; an IBAN from anywhere else is checked by mod-97 alone.',
    onByDefault: true,
  },
  {
    id: 'iso6346',
    name: 'Container',
    standard: 'ISO 6346',
    shape: 'AAAU 000000 0',
    length: '11 characters',
    check: 'Check digit, sum of value(c) x 2^i, mod 11, mod 10',
    repair: 'repaired',
    strength: 'Strong, with twelve known blind spots the agent asks about by hand.',
    measured: [
      'Error budget 0.0047 unconstrained, 0.0692 constrained: 14.9x.',
      'The acoustic model is worth 21 points of silent repair here, and zero accuracy.',
    ],
    note:
      'Characters congruent mod 11 are mathematically invisible to this check digit: {A K U} {1 B L V} {2 C M W} {3 D N X} {4 E O Y} {5 F P Z} {6 G Q} {7 H R} {8 I S} {9 J T}. Twelve of those pairs are also acoustically confusable, B/V, K/A, F/P and nine more, which is 5.3% of measured confusion weight. Readback asks about all twelve every time. Silence there would not be confidence, it would be arithmetic that cannot see.',
    onByDefault: true,
  },
  {
    id: 'nhs',
    name: 'NHS number',
    standard: 'NHS Data Dictionary',
    shape: '000 000 0000',
    length: '10 digits',
    check: 'Check digit, weights 10 down to 2, mod 11',
    repair: 'repaired',
    strength: 'Strong, and the digits-only alphabet keeps the confusion set small.',
    measured: [
      'The acoustic model is worth 64 points of silent repair here, the largest of the formats measured.',
    ],
    note:
      'Ten digits and no letters, so most of the confusion table does not apply; 5 against 9 at weight 0.50 is the heaviest pair that does. A remainder of 10 has no valid check digit, so those numbers are rejected outright rather than repaired quietly.',
    sensitive: 'A captured NHS number identifies a patient.',
    onByDefault: false,
  },
  {
    id: 'vin',
    name: 'VIN',
    standard: 'ISO 3779 / FMVSS 115',
    shape: '00000000X000000000',
    length: '17 characters, check digit at position 9',
    check: 'Check digit at position 9, transliterated, weighted, mod 11',
    repair: 'repaired',
    strength: 'Strong, and the alphabet itself removes the worst confusion before the arithmetic runs.',
    measured: [],
    note:
      'The VIN alphabet excludes I, O and Q. That deletes the heaviest confusable pair in the measured table, O against 0 at weight 0.95, before the check digit is ever reached. A VIN whose position 9 does not agree is not repaired quietly; it goes to a person.',
    onByDefault: false,
  },
  {
    id: 'luhn',
    name: 'Card',
    standard: 'ISO/IEC 7812, Luhn',
    shape: '0000 0000 0000 0000',
    length: '13 to 19 digits',
    check: 'Check digit, Luhn mod 10 with alternate doubling',
    repair: 'asking',
    strength: 'The weakest arithmetic here. Expect the agent to interrupt more often.',
    measured: [],
    note:
      'Luhn catches every single-digit substitution and every adjacent transposition except 0 next to 9, and it carries no length rule of its own, so a dropped digit leaves a shorter number the sum can still accept. More questions on card numbers is the arithmetic being honest, not the microphone failing.',
    sensitive: 'A captured card number is stored in full, like every other captured identifier.',
    onByDefault: false,
  },
];

export type FormatSwitches = Record<FormatId, boolean>;

/* Derived from the table rather than restated beside it. Two hand-written lists
 * of which formats start on is one list too many: they drift, and the one the
 * screen reads wins silently. */
export function defaultSwitches(): FormatSwitches {
  const switches: FormatSwitches = { iso6346: false, iban: false, vin: false, nhs: false, luhn: false };
  for (const spec of FORMATS) switches[spec.id] = spec.onByDefault;
  return switches;
}

/* Capture.format is whatever the server calls it -- 'ISO6346', 'IBAN-GB', 'NHS',
 * 'VIN', 'Luhn'. Matching on a prefix rather than on equality means a server
 * that starts sending 'IBAN-DE' does not silently drop out of the counts. */
export function formatIdOf(raw: string): FormatId | null {
  const key = raw.trim().toUpperCase();
  if (key.startsWith('ISO')) return 'iso6346';
  if (key.startsWith('IBAN')) return 'iban';
  if (key.startsWith('VIN')) return 'vin';
  if (key.startsWith('NHS')) return 'nhs';
  if (key.startsWith('LUHN') || key.startsWith('CARD') || key.startsWith('PAN')) return 'luhn';
  return null;
}

export function countByFormat(captures: readonly Capture[]): Record<FormatId, number> {
  const counts: Record<FormatId, number> = { iso6346: 0, iban: 0, vin: 0, nhs: 0, luhn: 0 };
  for (const capture of captures) {
    const id = formatIdOf(capture.format);
    if (id !== null) counts[id] += 1;
  }
  return counts;
}

// ------------------------------------------------------------ vocabulary --

/* AssemblyAI's keyterms prompt takes at most 100 terms of at most 50 characters.
 * Both numbers are the platform's, not ours, and Readback cannot raise either:
 * the pack is sent verbatim to the recogniser at session start. Showing the
 * count against the ceiling is the only honest way to present a limit somebody
 * else set. */
export const VOCAB_MAX_TERMS = 100;
export const VOCAB_MAX_CHARS = 50;

export type VocabProblem = 'empty' | 'too_long' | 'duplicate' | 'full';

export type TermCheck =
  | { ok: true; term: string }
  | { ok: false; problem: VocabProblem; message: string };

/* Case-insensitive, because the recogniser is. Two terms differing only in case
 * would spend two of the hundred slots on the same word. */
function sameTerm(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

export function checkTerm(raw: string, existing: readonly string[]): TermCheck {
  const term = raw.trim().replace(/\s+/g, ' ');

  if (term.length === 0) {
    return { ok: false, problem: 'empty', message: 'Type a term before adding it.' };
  }
  if (term.length > VOCAB_MAX_CHARS) {
    return {
      ok: false,
      problem: 'too_long',
      message: `That is ${term.length} characters. The platform limit is ${VOCAB_MAX_CHARS}.`,
    };
  }
  if (existing.some((other) => sameTerm(other, term))) {
    return { ok: false, problem: 'duplicate', message: 'That term is already in the pack.' };
  }
  if (existing.length >= VOCAB_MAX_TERMS) {
    return {
      ok: false,
      problem: 'full',
      message: `The pack holds ${VOCAB_MAX_TERMS} terms. Remove one to make room.`,
    };
  }
  return { ok: true, term };
}

// ---------------------------------------------------------------- consent --

export type Disclosure = 'readback_announces' | 'your_own_notice';

export interface DisclosureOption {
  id: Disclosure;
  label: string;
  detail: string;
}

export const DISCLOSURES: readonly DisclosureOption[] = [
  {
    id: 'readback_announces',
    label: 'Readback announces itself',
    detail:
      'One spoken line at the start of the call, before anything is captured: this call uses an assistant that writes down reference numbers.',
  },
  {
    id: 'your_own_notice',
    label: 'Your own notice covers it',
    detail:
      'You tell callers yourself, in the recording announcement or the script you already use. Readback stays silent until a number is read out.',
  },
];

export type Retention = '30' | '90' | '365' | 'forever';

export interface RetentionOption {
  id: Retention;
  label: string;
}

export const RETENTIONS: readonly RetentionOption[] = [
  { id: '30', label: '30 days' },
  { id: '90', label: '90 days' },
  { id: '365', label: '365 days' },
  { id: 'forever', label: 'Until someone deletes it' },
];

// ------------------------------------------------------------------ team --

export type TeamRole = 'owner' | 'admin' | 'operator';

export interface RoleSpec {
  id: TeamRole;
  label: string;
  /** What the role is for. Intent, not enforcement: the server decides, and the
   *  server does not have this endpoint yet. */
  can: string;
}

export const TEAM_ROLES: readonly RoleSpec[] = [
  { id: 'owner', label: 'Owner', can: 'Everything, including billing and this screen.' },
  { id: 'admin', label: 'Admin', can: 'This screen, the team, and every capture.' },
  {
    id: 'operator',
    label: 'Operator',
    can: 'Every capture. Cannot change formats, consent or the team.',
  },
];

export function roleLabel(role: string): string {
  const found = TEAM_ROLES.find((spec) => spec.id === role.toLowerCase());
  return found ? found.label : role;
}

/** Narrows a select's value back to a role. Returns null rather than a default,
 *  because guessing which role somebody meant is not a thing to do quietly. */
export function asRole(value: string): TeamRole | null {
  const found = TEAM_ROLES.find((spec) => spec.id === value);
  return found ? found.id : null;
}

export interface TeamMember {
  id: string;
  name: string;
  email: string;
  /* Not narrowed to TeamRole. The signed-in account's role comes from the server
   * and the server has not agreed to this vocabulary yet, so an unrecognised
   * role is displayed as the server spelled it instead of being coerced into one
   * of ours. Only rows invited here carry a role from the select. */
  role: string;
  /** Invited in this browser tab and nowhere else. See the mark on the section. */
  pending: boolean;
  /** The signed-in account. Cannot be removed from here. */
  isYou: boolean;
}

/* Not an RFC 5322 validator, and not trying to be. It rejects the shapes a
 * person actually mistypes -- no @, nothing before it, nothing after it, a space
 * in the middle -- and leaves the rest to the server, which is the only thing
 * that can tell a deliverable address from a well-formed one. */
export function emailProblem(raw: string): string | null {
  const value = raw.trim();
  if (value.length === 0) return 'Enter an email address.';
  if (/\s/.test(value)) return 'An email address cannot contain a space.';
  const at = value.indexOf('@');
  if (at < 1 || at !== value.lastIndexOf('@')) return 'That needs one @ with a name in front of it.';
  const domain = value.slice(at + 1);
  if (!domain.includes('.') || domain.startsWith('.') || domain.endsWith('.')) {
    return 'The part after the @ does not look like a domain.';
  }
  return null;
}

// ----------------------------------------------------------------- usage --

export interface UsageSnapshot {
  /** Seconds this screen can actually account for, derived from ms_to_settle on
   *  real captures. null when no capture carries a timing. This is a floor on
   *  listening time, never the whole of it. */
  accountedSeconds: number | null;
  /** The plan's allowance. null until an endpoint reports it, and the meter
   *  draws a no-reading track rather than a zero, because a zero is a claim. */
  planSeconds: number | null;
  captures: number;
  questions: number;
  /** Captures that reached a number without the agent speaking once. */
  silent: number;
}

export function usageFrom(captures: readonly Capture[]): UsageSnapshot {
  let ms = 0;
  let timed = 0;
  let questions = 0;
  let silent = 0;

  for (const capture of captures) {
    if (typeof capture.ms_to_settle === 'number') {
      ms += capture.ms_to_settle;
      timed += 1;
    }
    questions += capture.questions;
    if (capture.questions === 0 && (capture.state === 'settled' || capture.state === 'repaired')) {
      silent += 1;
    }
  }

  return {
    accountedSeconds: timed > 0 ? Math.round(ms / 1000) : null,
    // No endpoint reports the allowance. GET /api/usage is not in the contract.
    planSeconds: null,
    captures: captures.length,
    questions,
    silent,
  };
}

/* 80% is a UI threshold and nothing measured it. It is the point where a monthly
 * allowance stops being information and becomes a decision, which is what the
 * amber in this palette means. Stated rather than buried, because every other
 * number in this file has a source and this one does not. */
export const USAGE_ATTENTION = 0.8;

/* One capacity reading, shared by the usage meter and the vocabulary counter so
 * a bar that is 90% full never means two different things on one screen.
 *
 *   settled  inside the allowance: spent seconds and used slots are facts
 *   asking   close to the ceiling: somebody has a decision to make
 *   flagged  past it: only reachable for usage, since the pack refuses the 101st
 */
export function capacityState(fraction: number): CaptureState {
  if (fraction > 1) return 'flagged';
  if (fraction >= USAGE_ATTENTION) return 'asking';
  return 'settled';
}

export interface UsageReading {
  /** 0..1, or null when there is nothing to divide by. */
  fraction: number | null;
  /* The state vocabulary again, and it lands honestly here: seconds already
   * spent are settled fact, an allowance running out is a decision somebody has
   * to make, and going over is flagged. null is the fourth case and it is not a
   * state at all -- the instrument has no reading, so it says so in words rather
   * than borrowing a colour that would imply one. */
  state: CaptureState | null;
  note: string;
}

export function readUsage(usage: UsageSnapshot): UsageReading {
  const { accountedSeconds, planSeconds } = usage;

  if (accountedSeconds === null || planSeconds === null || planSeconds <= 0) {
    return {
      fraction: null,
      state: null,
      note: 'The server has not reported an allowance for this plan.',
    };
  }

  const fraction = accountedSeconds / planSeconds;
  const state = capacityState(fraction);

  const NOTE: Record<'settled' | 'asking' | 'flagged', string> = {
    settled: 'Inside the allowance for this period.',
    asking: 'Close to the allowance for this period.',
    flagged: 'Over the allowance for this period.',
  };

  // capacityState only ever returns these three; the wider CaptureState exists
  // so the rack and this screen keep one type, not so a bar can go steel.
  const note = state === 'asking' || state === 'flagged' ? NOTE[state] : NOTE.settled;

  return { fraction: Math.min(1, fraction), state, note };
}

/* Seconds, spoken the way an operations person says them. Hours and minutes, no
 * decimal hours: nobody reconciles a bill against 3.47 hours. */
export function humaniseSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, '0')}m`;
}
