import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Icon, SlotStrip, repaired, settled, provisional } from '../components';
import type { Slot } from '../components';
import { CAPTURE_STATES } from '../lib/api';
import type { CaptureState } from '../lib/api';
import { request } from '../lib/session';
import type { ApiResult } from '../lib/session';
import { useI18n } from '../i18n';
import './Dashboard.css';

/* The record: its data layer, its state ladder, and the parts the screen is
 * assembled from.
 *
 * WHY THIS FILE EXISTS RATHER THAN lib/api.ts
 * -------------------------------------------
 * The dashboard spec puts the state ladder "beside CAPTURE_STATES in
 * lib/api.ts", and that is where it belongs once the dust settles. It is here
 * instead because a sibling agent is writing GET /api/sessions and owns
 * lib/api.ts's `Capture` block this hour -- api.ts says so on the type itself:
 * "the one place to change when /api/sessions lands". Two agents editing that
 * block is how work gets lost. Everything under THE STAGING AREA below is
 * written to be MOVED, not rewritten: the types, the ladder, the adapter and
 * the fetchers lift into api.ts verbatim, and this file then imports them.
 *
 * Nothing here reaches around the transport: `request()` from lib/session is
 * the same call api.ts makes, so timeout, offline, 401-clears-the-token and the
 * ApiResult discipline are all inherited rather than re-implemented.
 */

// ============================================================================
// THE STAGING AREA -- destined for lib/api.ts
// ============================================================================

/** One written identifier. Mirrors `models.Capture`, minus two fields. */
export interface RecordCapture {
  id: string;
  session_id: string;
  format: string;
  heard: string | null;
  final: string | null;
  status: string;
  validated_by: string | null;
  second_signal: string | null;
  silent: boolean;
  corrected: boolean;
  position_corrected: number | null;
  rung: number;
  questions_asked: number;
  handed_over: boolean;
  handover_reason: string | null;
  flag_reason: string | null;
  latency_ms: number;
  created_at: string;
}

/** The container. A session outranks the account and is outranked by a capture. */
export interface RecordSession {
  id: string;
  source: string | null;
  demo_mode: boolean;
  end_reason: string | null;
  started_at: string | null;
  ended_at: string | null;
  confidence_regime: string | null;
}

/** Computed by the server (main.py:570), not by whoever draws the chart. */
export interface RecordCounters {
  captures: number;
  silent: number;
  characters: number;
  questions: number;
  spoken_questions: number;
  /* How many of the questions got an answer. NOT in main.py:570's counters
   * block today, and the headline renders the two-part figure instead of the
   * three-part one until it is: "15 timed out" computed from a number nobody
   * sent is exactly the fake this screen exists to refuse. */
  answered: number | null;
}

export interface RecordPayload {
  captures: RecordCapture[];
  sessions: RecordSession[];
  counters: RecordCounters | null;
  /** Days the server aggregated over. Null when it did not say. */
  window_days: number | null;
}

/** One QuestionEvent, from the per-session detail call. RETENTION is 7 days. */
export interface RecordQuestion {
  id: string;
  capture_id: string;
  position: number;
  form: string;
  rung: number;
  spoken: boolean;
  text: string | null;
  offered: string[];
  answered: boolean;
  answer_in_grammar: boolean;
  answer_char: string | null;
  resolution_ms: number | null;
}

export interface RecordDetail {
  session: RecordSession | null;
  captures: RecordCapture[];
  questions: RecordQuestion[];
  /** capture id -> the near misses the solver threw away. Detail call only. */
  candidates: Record<string, string[]>;
  /** Per-decision history. Present only while the session is live in _SESSIONS. */
  events: RecordEvent[];
}

export interface RecordEvent {
  seq: number;
  type: string;
  at_ms: number;
  gate?: number;
  spoken?: boolean;
}

// ------------------------------------------------------------- boundary ----

/* THE TWO FIELDS THAT MAY NOT CROSS THIS LINE.
 *
 * `confidence_at_write` is a real Float on models.Capture and it is in the
 * /api/sessions/{id} payload today. DESIGN-BRIEF 6 forbids the interface from
 * ever showing a confidence number; events.py already refuses to put one on the
 * event stream ("No confidence numbers reach the wire"). The REST path has to
 * refuse it too, and the refusal belongs HERE rather than in a component,
 * because a component's restraint only binds that component. A field that never
 * makes it into RecordCapture cannot be rendered by accident by a screen nobody
 * has written yet.
 *
 * `candidates_considered` is not forbidden, it is misplaced: five near-miss
 * identifiers beside the real one on a team-leader table is an invitation to
 * read the wrong number off the screen. It survives on the single-session
 * detail call, where it is labelled "what it ruled out" behind a disclosure,
 * and it is dropped from the list.
 */
const FORBIDDEN_ON_THE_WIRE = ['confidence_at_write', 'confidence'] as const;
const LIST_ONLY_DROP = ['candidates', 'candidates_considered'] as const;

function isRecordObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function str(raw: Record<string, unknown>, key: string): string | null {
  const value = raw[key];
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function num(raw: Record<string, unknown>, key: string, fallback: number): number {
  const value = raw[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function maybeNum(raw: Record<string, unknown>, key: string): number | null {
  const value = raw[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function bool(raw: Record<string, unknown>, key: string): boolean {
  const value = raw[key];
  // SQLite hands booleans back as 0/1 through some serialisers. Both are read,
  // and anything else is false rather than truthy -- `silent` decides the one
  // number the pitch rests on, and a string "0" must not inflate it.
  return value === true || value === 1;
}

/** Dev-only tripwire. It does not throw: the row still renders, stripped. */
function warnIfForbidden(raw: Record<string, unknown>): void {
  if (!import.meta.env.DEV) return;
  for (const field of FORBIDDEN_ON_THE_WIRE) {
    if (field in raw) {
      console.error(
        `Record: the list payload carried "${field}". DESIGN-BRIEF 6 forbids a ` +
          'confidence number on screen, so it is stripped here -- but it should ' +
          'not be on the wire at all. See events.py, which already refuses it.',
      );
    }
  }
}

function readCapture(raw: unknown, sessionHint: string | null): RecordCapture | null {
  if (!isRecordObject(raw)) return null;
  warnIfForbidden(raw);

  const id = str(raw, 'id');
  const sessionId = str(raw, 'session_id') ?? sessionHint;
  const created = str(raw, 'created_at');
  if (id === null || sessionId === null || created === null) return null;

  return {
    id,
    session_id: sessionId,
    /* THE SERVER NAME FIRST, the database column name second.
     *
     * This parser was written before GET /api/sessions existed, against the
     * column names in models.py, and the endpoint that eventually shipped uses
     * its own vocabulary. Only four names happened to agree, so eleven of the
     * fifteen fields on a real row read as missing: the identifier rendered as
     * "No identifier read out", every latency as "0 s", every question count as
     * zero, and every repair as settled. The rows were correct in the database
     * and correct on the wire; they were lost in the last three metres.
     *
     * The server owns the shape -- lib/api.ts says so itself, calling its
     * Capture type "the one place to change when /api/sessions lands" -- so the
     * server name is tried first. The old names are kept as a fallback rather
     * than deleted because tests/test_sessions_api.py builds rows by hand in
     * column form, and a parser that accepts both cannot be broken by whichever
     * shape arrives. */
    format: str(raw, 'format') ?? str(raw, 'format_type') ?? '',
    heard: str(raw, 'heard') ?? str(raw, 'heard_value'),
    final: str(raw, 'final') ?? str(raw, 'value') ?? str(raw, 'final_value'),
    status: str(raw, 'status') ?? '',
    validated_by: str(raw, 'validated_by'),
    second_signal: str(raw, 'second_signal'),
    silent: bool(raw, 'silent'),
    corrected: bool(raw, 'repaired') || bool(raw, 'corrected'),
    position_corrected: maybeNum(raw, 'repaired_position') ?? maybeNum(raw, 'position_corrected'),
    rung: num(raw, 'rung', 0),
    questions_asked: num(raw, 'questions', 0) || num(raw, 'questions_asked', 0),
    handed_over: bool(raw, 'handed_over'),
    handover_reason: str(raw, 'handover_reason'),
    flag_reason: str(raw, 'flag_reason'),
    latency_ms: num(raw, 'ms_to_settle', 0) || num(raw, 'latency_ms', 0),
    created_at: created,
  };
}

function readSession(raw: unknown): RecordSession | null {
  if (!isRecordObject(raw)) return null;
  const id = str(raw, 'id') ?? str(raw, 'session_id');
  if (id === null) return null;
  return {
    id,
    source: str(raw, 'source'),
    demo_mode: bool(raw, 'demo_mode'),
    end_reason: str(raw, 'end_reason'),
    started_at: str(raw, 'started_at'),
    ended_at: str(raw, 'ended_at'),
    confidence_regime: str(raw, 'confidence_regime'),
  };
}

function readCounters(raw: unknown): RecordCounters | null {
  if (!isRecordObject(raw)) return null;
  return {
    captures: num(raw, 'captures', 0),
    silent: num(raw, 'silent', 0),
    characters: num(raw, 'characters', 0),
    questions: num(raw, 'questions', 0),
    spoken_questions: num(raw, 'spoken_questions', 0),
    answered: maybeNum(raw, 'answered_questions') ?? maybeNum(raw, 'answered'),
  };
}

function malformed(status: number): ApiResult<never> {
  return {
    ok: false,
    status,
    kind: 'malformed',
    error: 'malformed_record',
    message: 'The Readback service returned something unexpected.',
  };
}

/* GET /api/sessions.
 *
 * The endpoint does not exist yet (server/main.py has only the per-session
 * route at line 504), so this is written against the declared contract in the
 * spec and is deliberately generous about the envelope: an object with
 * `captures`, or a bare array of captures, both parse. It is NOT generous about
 * the fields -- a row without an id, a session id and a created_at is dropped
 * rather than rendered with holes in it.
 *
 * Until the route lands this returns kind:'not_found', and the screen says so
 * in those words. That is the honest failure and it is why there is no fixture
 * behind this call. */
export async function fetchRecord(signal?: AbortSignal): Promise<ApiResult<RecordPayload>> {
  const result = await request<unknown>('/api/sessions', {
    auth: true,
    ...(signal ? { signal } : {}),
  });
  if (!result.ok) return result;

  const body = result.data;
  const rawCaptures = Array.isArray(body)
    ? body
    : isRecordObject(body) && Array.isArray(body['captures'])
      ? body['captures']
      : null;
  if (rawCaptures === null) return malformed(result.status);

  const rawSessions =
    isRecordObject(body) && Array.isArray(body['sessions']) ? body['sessions'] : [];

  const captures: RecordCapture[] = [];
  for (const raw of rawCaptures) {
    if (import.meta.env.DEV && isRecordObject(raw)) {
      for (const field of LIST_ONLY_DROP) {
        if (field in raw) {
          console.error(
            `Record: the list payload carried "${field}". Near-miss identifiers ` +
              'belong in the row disclosure, not beside the written number. ' +
              'It is dropped here.',
          );
        }
      }
    }
    const capture = readCapture(raw, null);
    if (capture) captures.push(capture);
  }

  const sessions: RecordSession[] = [];
  for (const raw of rawSessions) {
    const session = readSession(raw);
    if (session) sessions.push(session);
  }

  return {
    ok: true,
    status: result.status,
    data: {
      captures,
      sessions,
      counters: isRecordObject(body) ? readCounters(body['counters']) : null,
      window_days: isRecordObject(body) ? maybeNum(body, 'window_days') : null,
    },
  };
}

/** GET /api/sessions/{id}. This one exists today, and it is what L3 reads. */
export async function fetchSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<ApiResult<RecordDetail>> {
  const result = await request<unknown>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    auth: true,
    ...(signal ? { signal } : {}),
  });
  if (!result.ok) return result;
  const body = result.data;
  if (!isRecordObject(body)) return malformed(result.status);

  const captures: RecordCapture[] = [];
  if (Array.isArray(body['captures'])) {
    for (const raw of body['captures']) {
      const capture = readCapture(raw, sessionId);
      if (capture) captures.push(capture);
    }
  }

  const candidates: Record<string, string[]> = {};
  if (Array.isArray(body['captures'])) {
    for (const raw of body['captures']) {
      if (!isRecordObject(raw)) continue;
      const id = str(raw, 'id');
      const list = raw['candidates'];
      if (id !== null && Array.isArray(list)) {
        candidates[id] = list.filter((c): c is string => typeof c === 'string');
      }
    }
  }

  const questions: RecordQuestion[] = [];
  if (Array.isArray(body['questions'])) {
    for (const raw of body['questions']) {
      if (!isRecordObject(raw)) continue;
      const id = str(raw, 'id');
      const captureId = str(raw, 'capture_id');
      if (id === null || captureId === null) continue;
      const offered = raw['offered'];
      questions.push({
        id,
        capture_id: captureId,
        position: num(raw, 'position', 0),
        form: str(raw, 'form') ?? '',
        rung: num(raw, 'rung', 0),
        spoken: bool(raw, 'spoken'),
        text: str(raw, 'text'),
        offered: Array.isArray(offered)
          ? offered.filter((c): c is string => typeof c === 'string')
          : [],
        answered: bool(raw, 'answered'),
        answer_in_grammar: bool(raw, 'answer_in_grammar'),
        answer_char: str(raw, 'answer_char'),
        resolution_ms: maybeNum(raw, 'resolution_ms'),
      });
    }
  }

  const events: RecordEvent[] = [];
  if (Array.isArray(body['events'])) {
    for (const raw of body['events']) {
      if (!isRecordObject(raw)) continue;
      const type = str(raw, 'type');
      if (type === null) continue;
      const gate = maybeNum(raw, 'gate');
      events.push({
        seq: num(raw, 'seq', 0),
        type,
        at_ms: num(raw, 'at_ms', 0),
        ...(gate === null ? {} : { gate }),
        ...('spoken' in raw ? { spoken: bool(raw, 'spoken') } : {}),
      });
    }
  }

  const rawSession = body['session'];
  return {
    ok: true,
    status: result.status,
    data: {
      session: readSession(isRecordObject(rawSession) ? { ...rawSession, id: sessionId } : null),
      captures,
      questions,
      candidates,
      events,
    },
  };
}

/** One row of GET /api/session-summaries: a session and the counts a team
 * leader reads before opening it. Drawn from `session`, so a call that captured
 * nothing is here too. */
export interface SessionSummary {
  id: string;
  started_at: string | null;
  ended_at: string | null;
  end_reason: string | null;
  source: string | null;
  demo_mode: boolean;
  captures: number;
  silent: number;
  /** Captures that were handed over or flagged -- the ones that need a human. */
  flagged: number;
  questions: number;
}

export interface SessionSummaryPage {
  sessions: SessionSummary[];
  /** True when the bounded page left older sessions behind, said rather than
   *  dropped silently. */
  more: boolean;
}

/** GET /api/session-summaries. Newest first, bounded, organisation-scoped. */
export async function fetchSessionSummaries(
  signal?: AbortSignal,
): Promise<ApiResult<SessionSummaryPage>> {
  const result = await request<unknown>('/api/session-summaries', {
    auth: true,
    ...(signal ? { signal } : {}),
  });
  if (!result.ok) return result;
  const body = result.data;
  if (!isRecordObject(body) || !Array.isArray(body['sessions'])) {
    return malformed(result.status);
  }
  const sessions: SessionSummary[] = [];
  for (const raw of body['sessions']) {
    if (!isRecordObject(raw)) continue;
    const id = str(raw, 'id');
    if (id === null) continue;
    sessions.push({
      id,
      started_at: str(raw, 'started_at'),
      ended_at: str(raw, 'ended_at'),
      end_reason: str(raw, 'end_reason'),
      source: str(raw, 'source'),
      demo_mode: bool(raw, 'demo_mode'),
      captures: num(raw, 'captures', 0),
      silent: num(raw, 'silent', 0),
      flagged: num(raw, 'flagged', 0),
      questions: num(raw, 'questions', 0),
    });
  }
  return {
    ok: true,
    status: result.status,
    data: { sessions, more: bool(body, 'more') },
  };
}

/** One capture out of POST /api/demo/replay, which needs no key and no login. */
export interface ReplayCapture {
  format: string;
  heard: string | null;
  final: string | null;
  status: string;
  silent: boolean;
  corrected: boolean;
  questions: number;
  handed_over: boolean;
  handover_reason: string | null;
  latency_ms: number;
}

/* The worked example on the empty state is FETCHED, not written down.
 *
 * `speed` defaults to 0.0 on the server and `wait` defaults to "wait iff the
 * replay is instant", so a bare {fixture} body runs the whole session through
 * the same runner.run_session the live socket uses and answers with its
 * captures. A hard-coded MSKU4158005 here would be the first fake number in the
 * product, on the first screen a judge sees. */
/* A replay that asks a question waits out the answer budget in REAL time --
 * gates 4 and 5 are conditions on time passing, and a fixture with no scripted
 * human never answers. Measured 2026-09-04: iso_blind_substitution returns
 * after 12.3 s (one question, no answer, handed over), which the transport's
 * 12 s default cut off by a hair and showed as "the server did not answer".
 * Thirty seconds covers that path with room; the fast fixtures are unaffected. */
const REPLAY_TIMEOUT_MS = 30_000;

export async function replayFixture(
  fixture: string,
  signal?: AbortSignal,
): Promise<ApiResult<ReplayCapture[]>> {
  const result = await request<unknown>('/api/demo/replay', {
    method: 'POST',
    body: { fixture },
    timeoutMs: REPLAY_TIMEOUT_MS,
    ...(signal ? { signal } : {}),
  });
  if (!result.ok) return result;
  const body = result.data;
  if (!isRecordObject(body) || !Array.isArray(body['captures'])) return malformed(result.status);

  const captures: ReplayCapture[] = [];
  for (const raw of body['captures']) {
    if (!isRecordObject(raw)) continue;
    warnIfForbidden(raw);
    captures.push({
      format: str(raw, 'format') ?? '',
      heard: str(raw, 'heard'),
      final: str(raw, 'final'),
      status: str(raw, 'status') ?? '',
      silent: bool(raw, 'silent'),
      corrected: bool(raw, 'corrected'),
      questions: num(raw, 'questions', 0),
      /* The replay response does not carry `handed_over` (main.py:763's
       * _replay_response omits it), but it does carry `handover_reason`, and a
       * reason is only written when the pipeline gave up. Deriving it from the
       * field that IS on the wire beats defaulting the ladder's top rung to
       * false and rendering a handover as "settled". */
      handed_over: bool(raw, 'handed_over') || str(raw, 'handover_reason') !== null,
      handover_reason: str(raw, 'handover_reason'),
      latency_ms: num(raw, 'latency_ms', 0),
    });
  }
  return { ok: true, status: result.status, data: captures };
}

/** A replay capture in the record's own shape, so the rack and the state
 * ladder read it exactly as they read a row from the database. `validated_by`,
 * `second_signal`, `position_corrected` and `flag_reason` are not on the replay
 * wire: they are null here, not invented. Shared by the record's empty state
 * and the demo screen so the two cannot drift. */
export function replayAsRecord(capture: ReplayCapture, id: string): RecordCapture {
  return {
    id,
    session_id: id,
    format: capture.format,
    heard: capture.heard,
    final: capture.final,
    status: capture.status,
    validated_by: null,
    second_signal: null,
    silent: capture.silent,
    corrected: capture.corrected,
    position_corrected: null,
    rung: 0,
    questions_asked: capture.questions,
    handed_over: capture.handed_over,
    handover_reason: capture.handover_reason,
    flag_reason: null,
    latency_ms: capture.latency_ms,
    created_at: new Date().toISOString(),
  };
}

// ---------------------------------------------------------- the ladder -----

/* THE STATE LADDER. Evaluated top to bottom, first match wins.
 *
 * STATE IS NEVER READ FROM `status` ALONE, and that is measured rather than
 * stylistic. Re-measured against readback.db on 2026-09-01, 176 capture rows:
 *
 *     status = 'flagged'                    0 rows
 *     handed_over = 1                      18 rows  (handover_reason
 *                                                    'budget_exhausted')
 *
 * A status-only mapping renders those eighteen as a neutral "unverified" and
 * tells a team leader that nothing needs a human when eighteen things do. So
 * `handed_over` sits ABOVE `status`.
 *
 * The five outcomes are CAPTURE_STATES, not a second vocabulary:
 *   flagged  <- handed over, or flagged
 *   asking   <- the agent interrupted
 *   repaired <- silent and a character changed
 *   settled  <- silent and nothing changed          (the spec's "Silent")
 *   heard    <- none of the above                   (the spec's "Open")
 */
export function outcomeOf(capture: RecordCapture): CaptureState {
  if (capture.handed_over) return 'flagged';
  if (capture.status === 'flagged') return 'flagged';
  if (capture.questions_asked > 0) return 'asking';
  if (capture.silent && capture.corrected) return 'repaired';
  if (capture.silent) return 'settled';
  return 'heard';
}

/* THE TEST, AND WHY IT IS HERE.
 *
 * The spec asks for a unit test of the ladder against the six buckets. There is
 * no JavaScript test runner in this workspace -- web/package.json has dev,
 * build, typecheck and preview and no test script, and adding a runner is not
 * this agent's file to add. So the test runs in development, once, on module
 * load, and shouts rather than throwing.
 *
 * The fixture is one row per bucket rather than the spec's absolute counts, and
 * that is deliberate: the spec quotes 146 captures / 217 sessions, and the same
 * query against the same database on 2026-09-01 returned 176 captures / 262
 * sessions, because other agents in this workflow have been clicking the replay
 * endpoint all afternoon. The SHARES held exactly (silent 141/176 = 80.1%,
 * against the spec's 117/146 = 80.1%) and every load-bearing fact held --
 * zero status='flagged', every session demo_mode=1 -- but any test pinned to
 * 146 would now be failing for a reason that is not a bug. Buckets are stable;
 * counts in a live dev database are not.
 */
function ladderSelfCheck(): void {
  const base: RecordCapture = {
    id: 'x',
    session_id: 's',
    format: 'iso6346',
    heard: null,
    final: null,
    status: 'committed',
    validated_by: null,
    second_signal: null,
    silent: false,
    corrected: false,
    position_corrected: null,
    rung: 0,
    questions_asked: 0,
    handed_over: false,
    handover_reason: null,
    flag_reason: null,
    latency_ms: 0,
    created_at: '2026-09-01T00:00:00Z',
  };

  const cases: [string, RecordCapture, CaptureState][] = [
    // 100 rows in the spec's snapshot, 121 in the re-measure.
    ['silent, written unchanged', { ...base, silent: true }, 'settled'],
    // 17 / 20.
    ['silent, quietly repaired', { ...base, silent: true, corrected: true }, 'repaired'],
    // 14 / 17: asked, answered, committed.
    ['asked and answered', { ...base, rung: 3, questions_asked: 1 }, 'asking'],
    // 15 / 18: asked, nobody answered, handed over. THE ROW THAT MATTERS.
    [
      'handed over, status still committed',
      {
        ...base,
        rung: 1,
        questions_asked: 1,
        handed_over: true,
        handover_reason: 'budget_exhausted',
      },
      'flagged',
    ],
    // 0 rows in both snapshots, and it still has to map.
    ['status flagged', { ...base, status: 'flagged' }, 'flagged'],
    // Nothing settled and nothing asked: open.
    ['open', base, 'heard'],
  ];

  for (const [name, capture, expected] of cases) {
    const actual = outcomeOf(capture);
    if (actual !== expected) {
      console.error(
        `Record: the state ladder is wrong for "${name}": expected ${expected}, got ${actual}. ` +
          'See THE STATE LADDER in screens/DashboardParts.tsx.',
      );
    }
  }
}

if (import.meta.env.DEV) ladderSelfCheck();

// --------------------------------------------------------- the adapter -----

/* Capture -> Slot[]. This is the seam where "nothing on screen may be fake" is
 * won or lost, so it is deliberately conservative and every rule is a refusal:
 *
 *   - A slot is `repaired` ONLY where the two strings are the same length and
 *     the characters at that position actually differ. That is the one repair
 *     claim the payload supports.
 *   - Lengths that disagree produce no per-character diff at all. The written
 *     value renders settled and the row says, in the disclosure, that the
 *     characters are not lined up. Aligning two strings of different lengths
 *     means guessing where the insertion was, and a guessed repair is a fake.
 *   - `locked` is never emitted. Which position holds a check digit is a fact
 *     about the format that this payload does not carry, and painting the last
 *     ISO 6346 character as computed because it usually is would be inventing
 *     provenance.
 *   - `asked` is never emitted here. The position the agent asked about lives
 *     on QuestionEvent, which the list does not carry, and marking the wrong
 *     character as the contested one is worse than marking none.
 *   - Nothing at all is emitted when there is no value: a session that heard no
 *     identifier renders a sentence, not an empty strip. */
export function slotsFor(capture: RecordCapture): Slot[] {
  const final = capture.final;
  const heard = capture.heard;

  if (final === null) {
    // Heard but never written: the recogniser's guess, still open.
    return heard === null ? [] : provisional(heard);
  }
  if (heard === null || heard === final || heard.length !== final.length) {
    return settled(final);
  }

  const written = [...final];
  const said = [...heard];
  return written.map((char, index) => {
    const was = said[index];
    return was !== undefined && was !== char ? repaired(was, char) : { state: 'settled', char };
  });
}

/** True when the two strings cannot be lined up, so the row says so. */
export function lengthsDisagree(capture: RecordCapture): boolean {
  return (
    capture.heard !== null &&
    capture.final !== null &&
    capture.heard.length !== capture.final.length
  );
}

// ============================================================================
// THE GATE VOCABULARY
// ============================================================================
/* The seven reasons decider.may_speak() has for not speaking, as catalog keys.
 *
 * gateKey's return type is the eight gate keys and NOT TranslationKey. An
 * annotation that wide makes t() demand every placeholder that appears
 * anywhere in the catalog -- the same widening that CAPTURE_STATES in
 * lib/api.ts and FAILURE_KEY in screens/Auth.tsx both avoid. None of these
 * eight carry a placeholder, so t() correctly refuses a second argument here.
 *
 * (This file used to carry a 100-key staging table in all three languages,
 * because the i18n catalogs were owned by another agent while the record was
 * being built. Those keys have landed in en.ts / uz.ts / ru.ts verbatim --
 * same names, same placeholders, same translations -- so the table is gone
 * and every t() in this file and in Dashboard.tsx is now a t().) */

// ============================================================================
// THE HELD LINE -- DESIGN-BRIEF 4.2
// ============================================================================
/* Silence is not an absence here, so the indicator does not have to invent a
 * metaphor for nothing happening. events.py emits `silence.held` every time the
 * decider declines to speak and carries the gate that stopped it, and
 * decider.may_speak() returns that gate as a sentence already written for a
 * person to read. This component renders a stream of decisions that already
 * exist and already carry causes. That is the whole answer.
 *
 * WHY IT IS NOT A SPINNER. A spinner carries zero bits: it looks identical when
 * the system is thinking, when it is hung, and when the socket has dropped.
 * Marks here are appended one per decision while the elapsed axis keeps
 * advancing, so a dead pipeline looks different from a quiet one -- the axis
 * moves and no marks arrive. That is the single distinction an operator most
 * needs and the one a spinner cannot express.
 *
 * WHY IT IS NOT A WAVEFORM. A waveform is a function of the microphone: it
 * moves when anyone speaks and says nothing about whether Readback understood
 * anything. This line moves only when decide() runs. And a waveform is loudest
 * exactly while the caller is talking, which is precisely the moment the
 * operator must be listening to a person rather than looking at a screen.
 *
 * WHY IT DOES NOT VIOLATE "NO VISUAL INTERRUPTION DURING SILENCE" (6). The line
 * never changes size, never flashes, never enters or leaves the layout and
 * never moves anything else. Marks are appended at the right in --text-4
 * (2.21:1 on the panel -- decoration inside an aria-hidden figure), outside the
 * foveal path, and they do not animate at all: a mark appears by existing. The
 * opacity fade this used to run was an entrance keyframe on asynchronously
 * rendered content, which styles/motion.css bans by name because a re-render
 * mid-animation can strand the element at opacity 0.
 *
 * THE SHAPE IS THE MESSAGE. Measured: 0.20 spoken questions per identifier. The
 * honest silhouette of a working session is a long quiet texture of short grey
 * ticks with an occasional tall accent one, so the only thing that ever changes
 * SHAPE is an interruption. Success has one silhouette and failure has another,
 * and the good state is the flat one.
 */

export type HeldMark =
  | { kind: 'held'; at: number; gate: number }
  | { kind: 'spoke'; at: number };

export interface HeldLineProps {
  marks: readonly HeldMark[];
  /** The elapsed axis, in the same units as `at`. Zero renders one mark at now. */
  span: number;
  /** 'live' has per-decision history. 'summary' places marks by capture time. */
  mode: 'live' | 'summary';
  /** The gate currently holding, 1-7. Live only. */
  gate?: number | null;
  /** The session socket is open. Lights the presence cap. */
  present?: boolean;
  /** Summary mode only: what the counts are counting. */
  counts?: { captures: number; spoken: number };
  className?: string;
}

/* ANNOUNCE AT MOST ONCE PER FOUR SECONDS, AND ONLY ON A CHANGE OF GATE.
 *
 * This is measured discipline, not caution. The live pipeline emits
 * `silence.held` far more often than it emits captures -- 176 captures came out
 * of a decision stream many times that size -- and an unthrottled polite live
 * region under that load is a screen reader that never stops talking, which is
 * the 6 visual-interruption ban happening in audio instead. The count keeps
 * updating silently in between. */
const ANNOUNCE_EVERY_MS = 4000;

function useThrottled(value: string): string {
  const [announced, setAnnounced] = useState(value);
  const lastAt = useRef(0);
  const pending = useRef(value);

  pending.current = value;

  useEffect(() => {
    if (value === announced) return;
    const elapsed = Date.now() - lastAt.current;
    if (elapsed >= ANNOUNCE_EVERY_MS) {
      lastAt.current = Date.now();
      setAnnounced(value);
      return;
    }
    const timer = setTimeout(() => {
      lastAt.current = Date.now();
      setAnnounced(pending.current);
    }, ANNOUNCE_EVERY_MS - elapsed);
    return () => clearTimeout(timer);
  }, [value, announced]);

  return announced;
}

type GateKey =
  | 'record.held.gate.1'
  | 'record.held.gate.2'
  | 'record.held.gate.3'
  | 'record.held.gate.4'
  | 'record.held.gate.5'
  | 'record.held.gate.6'
  | 'record.held.gate.7'
  | 'record.held.gate.unknown';

function gateKey(gate: number | null | undefined): GateKey {
  switch (gate) {
    case 1:
      return 'record.held.gate.1';
    case 2:
      return 'record.held.gate.2';
    case 3:
      return 'record.held.gate.3';
    case 4:
      return 'record.held.gate.4';
    case 5:
      return 'record.held.gate.5';
    case 6:
      return 'record.held.gate.6';
    case 7:
      return 'record.held.gate.7';
    default:
      return 'record.held.gate.unknown';
  }
}

export function HeldLine({
  marks,
  span,
  mode,
  gate,
  present = false,
  counts,
  className,
}: HeldLineProps) {
  const { t, n } = useI18n();

  const held = marks.filter((mark) => mark.kind === 'held').length;
  const spoke = marks.length - held;

  const sentence =
    mode === 'summary'
      ? t('record.held.summary.say')
      : marks.length === 0 && gate === undefined
        ? t('record.held.rest')
        : t('record.held.holding', { gate: t(gateKey(gate)) });

  // Only the live line announces. A static summary has nothing to interrupt for.
  const announced = useThrottled(mode === 'live' ? sentence : '');

  const summary =
    mode === 'summary'
      ? t('record.held.sr.summary', {
          captures: n(counts?.captures ?? 0),
          spoken: n(counts?.spoken ?? 0),
        })
      : marks.length === 0
        ? t('record.held.sr.rest')
        : t('record.held.sr.live', {
            held: n(held),
            spoke: n(spoke),
            gate: t(gateKey(gate)),
          });

  const at = (value: number): string =>
    span <= 0 ? '100%' : `${Math.min(100, Math.max(0, (value / span) * 100))}%`;

  return (
    <figure className={className ? `held ${className}` : 'held'} aria-label={summary}>
      <div className="held__say">
        {/* Polite, and only the sentence. Assertive would interrupt the
            operator's screen reader mid-call, which is 6 in audio.

            The live region exists ONLY on the live line. A stored session's
            sentence never changes, and a page carrying one live region per
            stored session -- forty of them on a busy record -- is a screen
            reader announcing the whole list on load. */}
        {mode === 'live' ? (
          <p className="held__gate" role="status" aria-live="polite">
            {announced}
          </p>
        ) : (
          <p className="held__gate">{sentence}</p>
        )}
        {/* Outside the live region on purpose: the count changes constantly and
            must never be spoken. It is still readable. */}
        <span className="held__count mono">
          {mode === 'summary'
            ? t('record.held.summary.count', {
                captures: n(counts?.captures ?? 0),
                spoken: n(counts?.spoken ?? 0),
              })
            : t('record.held.count', { n: n(held) })}
        </span>
      </div>

      {/* A 2px rule with marks on it. Decorative: everything it says is in the
          figure's label and in the sentence above. A 2px mark cannot be a 44px
          target, so the marks are never controls -- the row disclosure is. */}
      <div className="held__line" aria-hidden="true">
        {present ? <span className="held__cap" /> : null}
        {marks.map((mark, index) => (
          <span
            key={index}
            className={mark.kind === 'spoke' ? 'held__mark held__mark--spoke' : 'held__mark'}
            style={{ left: at(mark.at) }}
          />
        ))}
      </div>

      <figcaption className="held__caption">
        {mode === 'summary' ? t('record.held.summary.caption') : t('record.held.caption')}
      </figcaption>
    </figure>
  );
}

/* Marks from the true per-decision history, when there is one. `/api/sessions/
 * {id}` returns `events` ONLY while the session is still live in _SESSIONS, so
 * this runs on an open session and never on a stored one. */
export function marksFromEvents(events: readonly RecordEvent[]): HeldMark[] {
  const marks: HeldMark[] = [];
  for (const event of events) {
    if (event.type === 'silence.held') {
      marks.push({ kind: 'held', at: event.at_ms, gate: event.gate ?? 0 });
    } else if (event.type === 'question.ask' && event.spoken === true) {
      marks.push({ kind: 'spoke', at: event.at_ms });
    }
  }
  return marks;
}

/* Marks for a stored session: one per capture, positioned by created_at, and
 * twice as tall in the accent where the agent asked.
 *
 * NEVER INTERPOLATE MARKS TO MAKE THE LINE LOOK BUSY. A fabricated tick is a
 * fake number under 5, and it is the exact fake this component would be most
 * tempted into -- the summary line of a one-capture session is one mark, and it
 * has to stay one mark. */
export function marksFromCaptures(captures: readonly RecordCapture[]): {
  marks: HeldMark[];
  span: number;
} {
  const times = captures
    .map((capture) => Date.parse(capture.created_at))
    .filter((value) => Number.isFinite(value));
  if (times.length === 0) return { marks: [], span: 0 };

  const first = Math.min(...times);
  const last = Math.max(...times);
  const span = last - first;

  const marks: HeldMark[] = captures.map((capture) => {
    const at = Date.parse(capture.created_at);
    const offset = Number.isFinite(at) ? at - first : span;
    return capture.questions_asked > 0
      ? { kind: 'spoke', at: offset }
      : { kind: 'held', at: offset, gate: 0 };
  });

  return { marks, span };
}

// ============================================================================
// THE ROW
// ============================================================================

export interface RecordRowProps {
  capture: RecordCapture;
  session: RecordSession | null;
  detail: RecordDetail | null;
  detailState: 'idle' | 'loading' | 'error';
  open: boolean;
  onToggle: (id: string) => void;
}

export function RecordRow({
  capture,
  session,
  detail,
  detailState,
  open,
  onToggle,
}: RecordRowProps) {
  const { t, n, d } = useI18n();
  const panelId = useId();

  const state = outcomeOf(capture);
  const meta = CAPTURE_STATES[state];
  const slots = slotsFor(capture);
  const value = capture.final ?? capture.heard;

  return (
    <li className="rec" data-state={state}>
      <div className="rec__head">
        {/* The identifier keeps its own scroll lane and sits ABOVE the
            stretched hit area below, so a 22-character IBAN can still be
            dragged sideways without expanding the row. */}
        <div className="rec__id">
          {value === null ? (
            <p className="rec__none">
              {t('record.row.none')} <span className="rec__none-note">{t('record.row.none.note')}</span>
            </p>
          ) : (
            <SlotStrip
              slots={slots}
              label={`${capture.format}. ${[...value].join(' ')}. ${t(meta.labelKey)}.`}
            />
          )}
        </div>

        <span className="rec__format mono">{capture.format}</span>

        {/* The word and the icon. These are the carriers -- the two things that
            survive a monochrome print of an exported record, which is why the
            per-state coloured left rule on the <li> could be dropped without
            anything being lost. Tone and weight come from Dashboard.css off the
            row's data-state rather than from CAPTURE_STATES.token: the state
            vocabulary is tone PLUS weight now, and a colour custom property
            cannot carry a font-weight. meta.token is deliberately unread. */}
        <span className="rec__state">
          <Icon name={meta.icon} size={16} />
          <span>{t(meta.labelKey)}</span>
        </span>

        <span className="rec__asked mono">
          {capture.questions_asked === 0
            ? t('rack.asked.none')
            : t('rack.asked.count', { n: n(capture.questions_asked) })}
        </span>

        <span className="rec__latency mono">
          {t('record.row.settledIn', { s: n(Math.round(capture.latency_ms / 100) / 10) })}
        </span>

        <span className="rec__when mono">{d(capture.created_at)}</span>

        {/* A real button, not a div with a handler. Its ::after stretches
            across the whole row, so the target is the row and not the chevron;
            the row itself is >= 48px tall. */}
        <button
          type="button"
          className="rec__toggle"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => onToggle(capture.id)}
        >
          <span className="sr-only">{t('record.row.expand')}</span>
          <Icon name="chevron-down" size={20} className="rec__chevron" />
        </button>
      </div>

      {open ? (
        <div className="rec__detail" id={panelId}>
          <RowDetail
            capture={capture}
            session={session}
            detail={detail}
            detailState={detailState}
          />
        </div>
      ) : (
        <div className="rec__detail" id={panelId} hidden />
      )}
    </li>
  );
}

// ------------------------------------------------------------------- L3 ----

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="kv">
      <span className="kv__key">{label}</span>
      <span className="kv__value">{children}</span>
    </div>
  );
}

function CopyId({ label, value }: { label: string; value: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  const copy = useCallback(() => {
    void navigator.clipboard
      ?.writeText(value)
      .then(() => setCopied(true))
      .catch(() => setCopied(false));
  }, [value]);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  return (
    <div className="kv">
      <span className="kv__key">{label}</span>
      <span className="kv__value rec__id-row">
        <span className="rec__uuid">{value}</span>
        <button type="button" className="rec__copy" onClick={copy}>
          <Icon name="copy" size={16} />
          <span>{copied ? t('record.detail.copied') : t('record.detail.copy')}</span>
        </button>
      </span>
    </div>
  );
}

function RowDetail({
  capture,
  session,
  detail,
  detailState,
}: {
  capture: RecordCapture;
  session: RecordSession | null;
  detail: RecordDetail | null;
  detailState: 'idle' | 'loading' | 'error';
}) {
  const { t, n } = useI18n();

  const none = <span className="rec__unknown">{t('record.detail.none')}</span>;
  const questions = (detail?.questions ?? []).filter((q) => q.capture_id === capture.id);
  const candidates = detail?.candidates[capture.id] ?? null;

  return (
    <div className="rec__facts">
      {lengthsDisagree(capture) ? (
        <p className="rec__caveat">{t('record.row.lengths')}</p>
      ) : null}

      <Fact label={t('record.detail.validatedBy')}>{capture.validated_by ?? none}</Fact>
      <Fact label={t('record.detail.secondSignal')}>{capture.second_signal ?? none}</Fact>
      <Fact label={t('record.detail.rung')}>{n(capture.rung)}</Fact>
      <Fact label={t('record.detail.positionCorrected')}>
        {capture.position_corrected === null ? none : n(capture.position_corrected)}
      </Fact>
      {capture.handed_over || capture.handover_reason !== null ? (
        <Fact label={t('record.detail.handover')}>{capture.handover_reason ?? none}</Fact>
      ) : null}
      {capture.flag_reason !== null ? (
        <Fact label={t('record.detail.flagReason')}>{capture.flag_reason}</Fact>
      ) : null}

      <Fact label={t('record.session.regime')}>
        {/* D. models.py refuses to default this, and gives the reason:
            per_char is the regime that permits silent acceptance at letter
            positions, and granting the most permissive behaviour before any
            evidence arrives is the wrong way round. 244 of 262 sessions in the
            dev database have no regime. */}
        {session?.confidence_regime ?? (
          <span className="rec__unknown">{t('record.session.regime.unknown')}</span>
        )}
      </Fact>

      <Fact label={t('record.detail.questions')}>
        {detailState === 'loading' ? (
          <span className="rec__unknown">{t('record.detail.loading')}</span>
        ) : detailState === 'error' ? (
          <span className="rec__unknown">{t('record.detail.unavailable')}</span>
        ) : capture.questions_asked === 0 ? (
          none
        ) : questions.length === 0 ? (
          /* THE 7-DAY TRAP. QuestionEvent.RETENTION is 7 days and Capture's is
             30, so past a week a capture still says questions_asked = 2 while
             its question rows are gone. That renders as "detail no longer
             retained" -- never as "no questions", and never as an empty list. */
          <span className="rec__unknown">{t('record.detail.questions.unretained')}</span>
        ) : (
          <ul className="rec__questions">
            {questions.map((question) => (
              <li key={question.id}>
                {t('record.detail.question.line', {
                  position: n(question.position),
                  offered: question.offered.join(' / '),
                })}
                {' · '}
                {question.answered && question.answer_char !== null
                  ? t('record.detail.question.answered', { char: question.answer_char })
                  : t('record.detail.question.unanswered')}
                {' · '}
                {/* QuestionEvent.spoken is "the column that separates the two",
                    so this is what the record reads for "did the agent actually
                    speak". capture.rung is read for nothing -- see the note in
                    the report about the 18 rows where they disagree. */}
                {question.spoken
                  ? t('record.detail.question.spoken')
                  : t('record.detail.question.silent')}
              </li>
            ))}
          </ul>
        )}
      </Fact>

      <Fact label={t('record.detail.ruledOut')}>
        {candidates === null ? (
          <span className="rec__unknown">{t('record.detail.ruledOut.absent')}</span>
        ) : candidates.length === 0 ? (
          none
        ) : (
          <span className="rec__ruled">{candidates.join(' · ')}</span>
        )}
      </Fact>

      <CopyId label={t('record.detail.captureId')} value={capture.id} />
      <CopyId label={t('record.detail.sessionId')} value={capture.session_id} />
    </div>
  );
}

// ============================================================================
// EXPORT
// ============================================================================
/* B. The export carries the same disclosure the screen does. A disclosure that
 * exists on screen and vanishes on export is defeated by the first person who
 * pastes the file into a deck, so row 1 of the file is a comment line carrying
 * the window, the row count and the replay status.
 *
 * Column names are the API's field names and are NOT translated: a CSV header
 * is machine output that another program reads, and a localised header is a
 * file that only opens correctly in the language it was exported from.
 *
 * confidence_at_write is not here because it is not in RecordCapture --
 * see THE TWO FIELDS THAT MAY NOT CROSS THIS LINE. candidates_considered is not
 * here either. */
const CSV_COLUMNS = [
  'identifier',
  'heard',
  'format',
  'outcome',
  'questions_asked',
  'latency_ms',
  'created_at',
  'validated_by',
  'second_signal',
  'rung',
  'silent',
  'corrected',
  'position_corrected',
  'handed_over',
  'handover_reason',
  'flag_reason',
  'status',
  'source',
  'demo_mode',
  'session_id',
  'capture_id',
] as const;

function csvCell(value: string | number | boolean | null): string {
  if (value === null) return '';
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(
  captures: readonly RecordCapture[],
  sessions: ReadonlyMap<string, RecordSession>,
  disclosure: string,
): string {
  const lines: string[] = [`# ${disclosure}`, CSV_COLUMNS.join(',')];
  for (const capture of captures) {
    const session = sessions.get(capture.session_id) ?? null;
    lines.push(
      [
        capture.final ?? capture.heard,
        capture.heard,
        capture.format,
        outcomeOf(capture),
        capture.questions_asked,
        capture.latency_ms,
        capture.created_at,
        capture.validated_by,
        capture.second_signal,
        capture.rung,
        capture.silent,
        capture.corrected,
        capture.position_corrected,
        capture.handed_over,
        capture.handover_reason,
        capture.flag_reason,
        capture.status,
        session?.source ?? null,
        session === null ? null : session.demo_mode,
        capture.session_id,
        capture.id,
      ]
        .map(csvCell)
        .join(','),
    );
  }
  return lines.join('\n');
}
