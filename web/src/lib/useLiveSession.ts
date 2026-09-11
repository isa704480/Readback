/* One live session, end to end: consent record -> session -> the two sockets
 * -> the microphone -> the event stream reduced into what the screen draws.
 *
 * THE ORDER IS THE CONSENT MODEL. `start()` will not touch the microphone until
 * POST /api/session/start has accepted `consent.accepted: true` with the version
 * the person was shown, and will not touch it at all if the server refuses.
 * The server is the gate (ARCHITECTURE 3.12); this hook is arranged so that a
 * browser cannot arrive at getUserMedia by any path that skips it.
 *
 * THE TWO SOCKETS.
 *   /api/session/{id}/live   server -> browser. The event stream, backlog
 *                            first, exactly as the replay path emits it.
 *   /api/session/{id}/audio  browser -> server. Binary PCM16 frames in; the
 *                            text frame {"type":"Terminate"} to end. The bearer
 *                            token travels as a second offered subprotocol,
 *                            `readback.token.<token>`, because a browser
 *                            WebSocket cannot set a header and a token in a
 *                            query string is a token in every access log. The
 *                            server answers one frame, {"type":"Ready"}, once
 *                            the upstream socket is open and the pipeline is
 *                            running -- and the microphone is opened on that
 *                            frame and nothing earlier. Its close codes rhyme
 *                            with HTTP: 4403 no consent, 4404 unknown, 4408
 *                            cap, 4409 not a live session, 4410 already ended,
 *                            4423 busy, 4429 too far ahead of real time, 4502
 *                            upstream refused. Each one is a different sentence
 *                            on screen.
 *
 * WHAT THIS HOOK NEVER HOLDS. No audio beyond the chunk in flight; no
 * transcript, because the stream carries none; no confidence, because the
 * stream carries none. `rows` is a projection of capture.* events into the
 * rack's slot vocabulary and nothing else.
 *
 * A HIDDEN TAB STOPS SENDING. Audio is produced at wall-clock rate by the
 * device, so pacing is free while the tab is visible. A backgrounded tab is
 * the one case where the browser may stall the main thread and then release
 * a burst of queued messages, which is exactly the faster-than-real-time
 * delivery AssemblyAI closes with 3007. On visibilitychange the chunks are
 * dropped -- not queued -- and on return nothing is replayed. The screen is
 * told how long it was deaf so it can say so.
 */

import { useCallback, useEffect, useReducer, useRef } from 'react';
import { apiBase, getToken, request } from './session';
import type { ApiResult } from './session';
import type { RackRow, Slot } from '../components';
import type { CaptureState } from './api';
import type { HeldMark } from '../screens/DashboardParts';
import { openMicrophone, MicError } from './useMicrophone';
import type { MicGranted, MicHandle } from './useMicrophone';

// ------------------------------------------------------------------ types --

export type LivePhase = 'consent' | 'starting' | 'connecting' | 'listening' | 'ended' | 'failed';

/* Each of these is a different thing that happened, and the screen gives each
 * one its own sentence. Collapsing two of them would make a person debug the
 * wrong thing. */
export type LiveFailure =
  | 'consent_absent' // the server refused the session: no consent recorded
  | 'server_unreachable' // /api/session/start got no answer
  | 'server_refused' // 429, 503 or another refusal, with the server's own words
  | 'no_live_capture' // the session opened but the server has no key / no budget
  | 'mic_denied'
  | 'mic_missing'
  | 'mic_busy'
  | 'mic_unsupported'
  | 'audio_refused' // /audio closed before the first chunk was accepted
  | 'upstream_refused' // the pipeline emitted `error`: AssemblyAI said no
  | 'connection_lost' // a socket dropped mid-session
  | 'device_lost'; // the microphone track ended

export interface LiveQuestion {
  questionId: string;
  captureId: string;
  position: number;
  choices: string[];
  /** The agent's own English sentence. Quoted as such on screen. */
  text: string;
  spoken: boolean;
  blind: boolean;
  askedAt: number;
}

export interface LiveSummary {
  reason: string;
  captures: number;
  silent: number;
  questions: number;
  billedSeconds: number;
}

export interface LiveRow extends RackRow {
  /** The pipeline's format id: iso6346, iban, nhs, vin, luhn. */
  formatId: string;
  reason?: string;
  /** The runner's partial rack (`provisional: true`): what is being heard
   *  right now, under an id of its own. Superseded the moment a real capture
   *  opens or the recogniser disarms -- see reduceEvent. */
  partial?: boolean;
}

export interface LiveState {
  phase: LivePhase;
  failure: LiveFailure | null;
  /** Machine detail beside the failure: a close code, an exception name, the
   *  server's message. Rendered in mono, never as the only explanation. */
  detail: string | null;
  sessionId: string | null;
  capSeconds: number | null;
  /** Wall-clock ms when the audio socket opened; the cap counts from here. */
  listeningSince: number | null;
  /** The recogniser is armed on a format it suspects. Null while idle. */
  armedFormat: string | null;
  rows: LiveRow[];
  question: LiveQuestion | null;
  marks: HeldMark[];
  /** Wall-clock ms of the pipeline's clock zero, derived from the first event. */
  streamZero: number | null;
  heldGate: number | null | undefined;
  /** The /live socket is open. */
  present: boolean;
  granted: MicGranted | null;
  summary: LiveSummary | null;
  chunksSent: number;
  /** Milliseconds of audio dropped because the tab was hidden. */
  hiddenMs: number;
  /** True after 5 s of chunks with no signal at all: the device is open but
   *  silent, which is usually an OS-level mute. */
  noSignal: boolean;
  answering: boolean;
  /** The audio socket closed with 4408: the server's own clock hit the cap. */
  capReached: boolean;
}

export interface ConsentRecord {
  version: string;
  disclosurePlayed: boolean;
}

// ------------------------------------------------------------------ state --

const INITIAL: LiveState = {
  phase: 'consent',
  failure: null,
  detail: null,
  sessionId: null,
  capSeconds: null,
  listeningSince: null,
  armedFormat: null,
  rows: [],
  question: null,
  marks: [],
  streamZero: null,
  heldGate: undefined,
  present: false,
  granted: null,
  summary: null,
  chunksSent: 0,
  hiddenMs: 0,
  noSignal: false,
  answering: false,
  capReached: false,
};

type Action =
  | { type: 'reset' }
  | { type: 'phase'; phase: LivePhase }
  | { type: 'fail'; failure: LiveFailure; detail?: string }
  | { type: 'session'; sessionId: string; capSeconds: number }
  | { type: 'present'; present: boolean }
  | { type: 'listening'; granted: MicGranted; at: number }
  | { type: 'chunk'; noSignal: boolean }
  | { type: 'hidden'; ms: number }
  | { type: 'answering'; answering: boolean }
  | { type: 'capped' }
  | { type: 'event'; event: StreamEvent; receivedAt: number };

interface StreamEvent {
  seq: number;
  type: string;
  at_ms: number;
  wall_ms: number;
  [key: string]: unknown;
}

function isEvent(value: unknown): value is StreamEvent {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as StreamEvent).type === 'string' &&
    typeof (value as StreamEvent).seq === 'number'
  );
}

const str = (v: unknown): string => (typeof v === 'string' ? v : '');
const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);

/* capture.update slots -> the rack's slot vocabulary. Same six words, so the
 * mapping is a rename of the shape, not a reinterpretation. */
function toSlots(raw: unknown): Slot[] {
  if (!Array.isArray(raw)) return [];
  const out: Slot[] = [];
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue;
    const rec = item as Record<string, unknown>;
    const state = str(rec['state']);
    const char = str(rec['char']);
    switch (state) {
      case 'empty':
        out.push({ state: 'empty' });
        break;
      case 'provisional':
        out.push(char ? { state: 'provisional', char } : { state: 'empty' });
        break;
      case 'settled':
        out.push({ state: 'settled', char });
        break;
      case 'repaired':
        out.push({ state: 'repaired', char, heard: str(rec['heard']) || char });
        break;
      case 'asked':
        out.push({ state: 'asked', char });
        break;
      case 'locked':
        out.push({ state: 'locked', char });
        break;
      default:
        out.push(char ? { state: 'provisional', char } : { state: 'empty' });
    }
  }
  return out;
}

function upsert(rows: LiveRow[], id: string, patch: (row: LiveRow) => LiveRow, make: () => LiveRow) {
  const index = rows.findIndex((r) => r.id === id);
  if (index === -1) return [patch(make()), ...rows]; // newest first
  const next = rows.slice();
  const current = next[index];
  if (current) next[index] = patch(current);
  return next;
}

/* On commit the question is closed and the characters are final: what was
 * provisional or asked is now settled. Locked and repaired keep their marks --
 * a human answered one, the format overruled the other, and both facts stay
 * on the row. */
function settleSlots(slots: Slot[]): Slot[] {
  return slots.map((s) =>
    s.state === 'provisional' || s.state === 'asked' ? { state: 'settled', char: s.char } : s,
  );
}

/* silence.held carries the decider's sentence in `reason` (decider.may_speak
 * returns it verbatim) and a longer label in `gate`. HeldLine numbers the seven
 * gates 1-7 to read them from the catalog, so the sentence is mapped back to
 * its number here. The table is the decider's own list, in its own order. */
const GATE_SENTENCES: readonly string[] = [
  'uncertain, not wrong',
  'the turn has not ended',
  'nothing downstream needs it',
  'the line is not quiet',
  'inside the 1.5 s politeness delay',
  'already spoke once about this identifier',
  'too late -- more than 10 s since the last word',
];

function gateNumber(reason: string, gate: string): number {
  const index = GATE_SENTENCES.indexOf(reason);
  if (index !== -1) return index + 1;
  const m = /gate (\d)/.exec(gate);
  return m ? Number(m[1]) : 0;
}

function reduceEvent(state: LiveState, ev: StreamEvent, receivedAt: number): LiveState {
  const captureId = str(ev['capture_id']);
  const format = str(ev['format']);
  const streamZero = state.streamZero ?? receivedAt - num(ev.wall_ms);
  const make = (): LiveRow => ({
    id: captureId,
    format,
    formatId: format,
    state: 'heard',
    slots: [],
    questions: 0,
  });
  let next: LiveState = { ...state, streamZero };

  switch (ev.type) {
    case 'session.started': {
      const cap = num(ev['cap_seconds']);
      return cap > 0 ? { ...next, capSeconds: cap } : next;
    }
    case 'state.armed':
      return { ...next, armedFormat: str(ev['format']) || null };
    case 'state.idle':
      // Disarmed: whatever was being heard provisionally is not being heard
      // any more. The runner drops its partial id here too.
      return { ...next, armedFormat: null, rows: next.rows.filter((row) => !row.partial) };
    case 'capture.update': {
      if (!captureId) return next;
      const slots = toSlots(ev['slots']);
      const awaiting = str(ev['awaiting']);
      const partial = ev['provisional'] === true;
      // The runner's partial rack has its own id. Once a real capture opens
      // on the same words, the partial row is that capture's past, not a
      // second identifier -- so it goes.
      const rows = partial ? next.rows : next.rows.filter((row) => !row.partial);
      return {
        ...next,
        rows: upsert(
          rows,
          captureId,
          (row) => ({
            ...row,
            partial,
            formatId: format || row.formatId,
            format: format || row.format,
            slots,
            // A row already decided keeps its outcome; a late update on a
            // committed row is the same characters restated.
            state:
              row.state === 'settled' || row.state === 'repaired' || row.state === 'flagged'
                ? row.state
                : awaiting
                  ? 'asking'
                  : row.state,
          }),
          make,
        ),
      };
    }
    case 'silence.held': {
      const gate = gateNumber(str(ev['reason']), str(ev['gate']));
      return {
        ...next,
        heldGate: gate,
        marks: [...next.marks, { kind: 'held', at: num(ev.wall_ms), gate }],
      };
    }
    case 'question.ask': {
      const choices = Array.isArray(ev['choices']) ? ev['choices'].map(String) : [];
      const question: LiveQuestion = {
        questionId: str(ev['question_id']),
        captureId,
        position: num(ev['position']),
        choices,
        text: str(ev['text']),
        spoken: ev['spoken'] === true,
        blind: ev['blind'] === true,
        askedAt: receivedAt,
      };
      const marks = question.spoken
        ? [...next.marks, { kind: 'spoke' as const, at: num(ev.wall_ms) }]
        : next.marks;
      return {
        ...next,
        question,
        marks,
        rows: upsert(
          next.rows,
          captureId,
          (row) => ({ ...row, state: 'asking', questions: row.questions + 1 }),
          make,
        ),
      };
    }
    case 'question.answer': {
      const id = str(ev['question_id']);
      const cleared = next.question && next.question.questionId === id ? null : next.question;
      return { ...next, question: cleared, answering: false };
    }
    case 'capture.commit': {
      const corrected = ev['corrected'] === true;
      const value = str(ev['value']);
      const heard = str(ev['heard']);
      const state: CaptureState = corrected ? 'repaired' : 'settled';
      return {
        ...next,
        question: next.question && next.question.captureId === captureId ? null : next.question,
        rows: upsert(
          next.rows,
          captureId,
          (row) => ({
            ...row,
            state,
            questions: num(ev['questions']) || row.questions,
            slots:
              row.slots.length === value.length
                ? settleSlots(row.slots)
                : [...value].map((char, i) =>
                    heard[i] !== undefined && heard[i] !== char
                      ? { state: 'repaired', char, heard: heard[i] as string }
                      : { state: 'settled', char },
                  ),
          }),
          make,
        ),
      };
    }
    case 'capture.flag':
    case 'capture.handover': {
      const reason = str(ev['reason']);
      return {
        ...next,
        question: next.question && next.question.captureId === captureId ? null : next.question,
        rows: upsert(next.rows, captureId, (row) => ({ ...row, state: 'flagged', reason }), make),
      };
    }
    case 'error':
      return {
        ...next,
        phase: 'failed',
        failure: 'upstream_refused',
        detail: str(ev['message']) || null,
      };
    case 'session.end': {
      const summary: LiveSummary = {
        reason: str(ev['reason']),
        captures: num(ev['captures']),
        silent: num(ev['silent']),
        questions: num(ev['questions']),
        billedSeconds: num(ev['billed_seconds']),
      };
      // An `error` already put the screen in the failed state with the cause;
      // the end event that follows carries the tally, not a new verdict.
      return next.phase === 'failed'
        ? { ...next, summary, question: null }
        : { ...next, phase: 'ended', summary, question: null };
    }
    default:
      return next;
  }
}

function reducer(state: LiveState, action: Action): LiveState {
  switch (action.type) {
    case 'reset':
      return INITIAL;
    case 'phase':
      return state.phase === 'failed' || state.phase === 'ended' ? state : { ...state, phase: action.phase };
    case 'fail':
      if (state.phase === 'ended') return state;
      return { ...state, phase: 'failed', failure: action.failure, detail: action.detail ?? null };
    case 'session':
      return { ...state, sessionId: action.sessionId, capSeconds: action.capSeconds };
    case 'present':
      return { ...state, present: action.present };
    case 'listening':
      return state.phase === 'connecting'
        ? { ...state, phase: 'listening', granted: action.granted, listeningSince: action.at }
        : { ...state, granted: action.granted };
    case 'chunk':
      return {
        ...state,
        chunksSent: state.chunksSent + 1,
        noSignal: action.noSignal,
      };
    case 'hidden':
      return { ...state, hiddenMs: state.hiddenMs + action.ms };
    case 'answering':
      return { ...state, answering: action.answering };
    case 'capped':
      return state.phase === 'failed' ? state : { ...state, phase: 'ended', capReached: true, question: null };
    case 'event':
      return reduceEvent(state, action.event, action.receivedAt);
  }
}

// ------------------------------------------------------------- transport --

function wsUrl(path: string): string {
  const base = apiBase || window.location.origin;
  return base.replace(/^http/i, 'ws') + path;
}

const AUDIO_SUBPROTOCOL = 'readback.audio';
const LIVE_SUBPROTOCOL = 'readback.live';
const AUDIO_TOKEN_PROTOCOL_PREFIX = 'readback.token.';
const TERMINATE = JSON.stringify({ type: 'Terminate' });

/* The server's close codes on /audio, each to the sentence that explains it.
 * Unlisted codes -- 1006 for a handshake the server never answered, 4400 and
 * 4422 for frames this client does not send -- fall to audio_refused before
 * the first chunk and connection_lost after it. */
function failureForClose(code: number, accepted: boolean): LiveFailure {
  switch (code) {
    case 4403:
      return 'consent_absent';
    case 4409:
      return 'no_live_capture';
    case 4502:
      return 'upstream_refused';
    default:
      return accepted ? 'connection_lost' : 'audio_refused';
  }
}

class CloseError extends Error {
  readonly code: number;
  constructor(code: number, reason: string) {
    super(reason);
    this.code = code;
  }
}

interface StartResponse {
  session_id: string;
  live_capture: boolean;
  consent_version: string;
  cap_seconds: number;
}

function startSession(consent: ConsentRecord, signal: AbortSignal): Promise<ApiResult<StartResponse>> {
  return request<StartResponse>('/api/session/start', {
    method: 'POST',
    auth: true,
    signal,
    body: {
      consent: { accepted: true, version: consent.version, disclosure_played: consent.disclosurePlayed },
      demo_mode: false,
      ab: false,
      channel: 'clean',
    },
  });
}

/* Chunks whose peak sits under -54 dBFS for this long mean the device is open
 * and delivering nothing: an OS mute, a hardware switch, a dead input. Speech
 * at any distance clears it in one chunk. */
const NO_SIGNAL_PEAK = 0.002;
const NO_SIGNAL_MS = 5000;

// ------------------------------------------------------------------ hook --

export interface LiveSession {
  state: LiveState;
  start(consent: ConsentRecord): void;
  /** Tap a chip: the index into the question's `choices`. */
  answer(choice: number): void;
  /** Send Terminate, release the microphone, close both sockets. */
  stop(): void;
  /** Back to the consent step. Only valid once ended or failed. */
  reset(): void;
}

export function useLiveSession(): LiveSession {
  const [state, dispatch] = useReducer(reducer, INITIAL);

  const liveRef = useRef<WebSocket | null>(null);
  const audioRef = useRef<WebSocket | null>(null);
  const micRef = useRef<MicHandle | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endedRef = useRef(false); // we asked for the end, or the server ended it
  const acceptedRef = useRef(false); // at least one chunk went out on an open socket
  const quietSinceRef = useRef<number | null>(null);
  const hiddenSinceRef = useRef<number | null>(null);
  const sessionRef = useRef<string | null>(null);

  /* Release everything that can cost money or hold a device: the mic first,
   * then Terminate on the audio socket, then the sockets themselves. With
   * `keepLive` the event stream stays open a few seconds longer so the
   * server's session.end -- the tally -- can still arrive after a stop. */
  const teardown = useCallback(async (keepLive = false) => {
    abortRef.current?.abort();
    abortRef.current = null;
    const mic = micRef.current;
    micRef.current = null;
    if (mic) await mic.close();
    const audio = audioRef.current;
    audioRef.current = null;
    if (audio && audio.readyState <= WebSocket.OPEN) {
      try {
        if (audio.readyState === WebSocket.OPEN) audio.send(TERMINATE);
      } catch {
        /* closing anyway */
      }
      // The server sends the tail at real time and closes with 1000 itself;
      // closing here first would drop that tail. It is closed below if it
      // has not closed on its own.
      setTimeout(() => {
        if (audio.readyState <= WebSocket.OPEN) audio.close(1000, 'terminate');
      }, 4000);
    }
    const live = liveRef.current;
    if (!live) return;
    const closeLive = () => {
      if (liveRef.current === live) liveRef.current = null;
      if (live.readyState <= WebSocket.OPEN) live.close(1000, 'done');
    };
    if (keepLive) setTimeout(closeLive, 8000);
    else closeLive();
  }, []);

  const fail = useCallback(
    (failure: LiveFailure, detail?: string) => {
      dispatch(detail === undefined ? { type: 'fail', failure } : { type: 'fail', failure, detail });
      void teardown();
    },
    [teardown],
  );

  // Unmount: nothing may keep billing after the screen is gone.
  useEffect(() => {
    return () => {
      endedRef.current = true;
      void teardown();
    };
  }, [teardown]);

  // A hidden tab stops sending. The gap is measured, not hidden.
  useEffect(() => {
    const onVisibility = () => {
      const mic = micRef.current;
      if (document.hidden) {
        hiddenSinceRef.current = Date.now();
        mic?.mute();
      } else {
        const since = hiddenSinceRef.current;
        hiddenSinceRef.current = null;
        if (since !== null) dispatch({ type: 'hidden', ms: Date.now() - since });
        mic?.unmute();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

  const openLive = useCallback(
    (sessionId: string) =>
      new Promise<void>((resolve, reject) => {
        /* The token rides the same subprotocol the audio socket uses, and for
           the same reason: a browser cannot set a header on a WebSocket. The
           event stream is organisation-scoped server-side, so a signed-in
           operator whose viewer connected anonymously would be told "unknown
           session" about their own call. */
        const liveToken = getToken();
        const ws = new WebSocket(
          wsUrl(`/api/session/${sessionId}/live`),
          liveToken
            ? [LIVE_SUBPROTOCOL, AUDIO_TOKEN_PROTOCOL_PREFIX + liveToken]
            : [LIVE_SUBPROTOCOL],
        );
        liveRef.current = ws;
        let opened = false;
        ws.onopen = () => {
          opened = true;
          dispatch({ type: 'present', present: true });
          resolve();
        };
        ws.onmessage = (message: MessageEvent<string>) => {
          let parsed: unknown;
          try {
            parsed = JSON.parse(message.data);
          } catch {
            return;
          }
          if (!isEvent(parsed)) return;
          if (parsed.type === 'session.end' || parsed.type === 'error') endedRef.current = true;
          dispatch({ type: 'event', event: parsed, receivedAt: Date.now() });
        };
        ws.onclose = (close) => {
          if (liveRef.current === ws) liveRef.current = null;
          dispatch({ type: 'present', present: false });
          if (!opened) {
            reject(new Error(`live socket refused (${close.code})`));
            return;
          }
          if (!endedRef.current) fail('connection_lost', `live ${close.code}`);
        };
        ws.onerror = () => {
          /* onclose follows and carries the code */
        };
      }),
    [fail],
  );

  const openAudio = useCallback(
    (sessionId: string) =>
      new Promise<WebSocket>((resolve, reject) => {
        const token = getToken();
        const protocols = token
          ? [AUDIO_SUBPROTOCOL, AUDIO_TOKEN_PROTOCOL_PREFIX + token]
          : [AUDIO_SUBPROTOCOL];
        const ws = new WebSocket(wsUrl(`/api/session/${sessionId}/audio`), protocols);
        ws.binaryType = 'arraybuffer';
        audioRef.current = ws;
        let ready = false;
        ws.onopen = () => {
          /* An accepted handshake is not a pipeline. The server sends Ready
             once the upstream socket is open; until then nothing is sent and
             the microphone stays closed. */
        };
        ws.onmessage = (message: MessageEvent<string | ArrayBuffer>) => {
          if (typeof message.data !== 'string') return;
          let parsed: unknown;
          try {
            parsed = JSON.parse(message.data);
          } catch {
            return;
          }
          if (
            typeof parsed === 'object' &&
            parsed !== null &&
            (parsed as { type?: unknown }).type === 'Ready'
          ) {
            ready = true;
            const cap = (parsed as { cap_seconds?: unknown }).cap_seconds;
            if (typeof cap === 'number' && cap > 0) {
              dispatch({ type: 'session', sessionId, capSeconds: cap });
            }
            resolve(ws);
          }
        };
        ws.onclose = (close) => {
          if (audioRef.current === ws) audioRef.current = null;
          if (!ready) {
            reject(new CloseError(close.code, close.reason));
            return;
          }
          if (close.code === 4408) {
            // The server's own clock reached the cap. Not a failure: the
            // session ended the way every session is told it will.
            endedRef.current = true;
            dispatch({ type: 'capped' });
            void teardown();
            return;
          }
          if (endedRef.current) return;
          fail(
            failureForClose(close.code, acceptedRef.current),
            `audio ${close.code}${close.reason ? ` ${close.reason}` : ''}`,
          );
        };
        ws.onerror = () => {
          /* onclose carries the code */
        };
      }),
    [fail, teardown],
  );

  const start = useCallback(
    (consent: ConsentRecord) => {
      if (state.phase !== 'consent') return;
      endedRef.current = false;
      acceptedRef.current = false;
      quietSinceRef.current = null;
      const controller = new AbortController();
      abortRef.current = controller;
      dispatch({ type: 'phase', phase: 'starting' });

      void (async () => {
        // 1. The consent record, and the server's verdict on it.
        const started = await startSession(consent, controller.signal);
        if (controller.signal.aborted) return;
        if (!started.ok) {
          if (started.kind === 'offline' || started.kind === 'timeout') {
            fail('server_unreachable');
          } else if (started.status === 403) {
            fail('consent_absent', started.message);
          } else {
            fail('server_refused', `${started.status} ${started.message}`);
          }
          return;
        }
        const { session_id: sessionId, live_capture: live, cap_seconds: cap } = started.data;
        sessionRef.current = sessionId;
        dispatch({ type: 'session', sessionId, capSeconds: cap });
        if (!live) {
          fail('no_live_capture');
          return;
        }
        dispatch({ type: 'phase', phase: 'connecting' });

        // 2. The event stream, then the audio socket. Both before the mic.
        try {
          await openLive(sessionId);
        } catch (error) {
          fail('connection_lost', error instanceof Error ? error.message : undefined);
          return;
        }
        let audio: WebSocket;
        try {
          audio = await openAudio(sessionId);
        } catch (error) {
          endedRef.current = true;
          if (error instanceof CloseError) {
            fail(
              failureForClose(error.code, false),
              `audio ${error.code}${error.message ? ` ${error.message}` : ''}`,
            );
          } else {
            fail('audio_refused', error instanceof Error ? error.message : undefined);
          }
          return;
        }
        if (controller.signal.aborted) return;

        // 3. Only now, the microphone.
        try {
          const mic = await openMicrophone(({ pcm, peak }) => {
            const socket = audioRef.current;
            if (!socket || socket.readyState !== WebSocket.OPEN) return;
            if (hiddenSinceRef.current !== null) return; // deaf on purpose
            // Back-pressure: if the browser has not flushed the last few
            // chunks, this one is dropped rather than queued. A queue is the
            // burst that closes the upstream socket.
            if (socket.bufferedAmount > 4 * pcm.byteLength) return;
            socket.send(pcm);
            acceptedRef.current = true;
            const now = Date.now();
            if (peak < NO_SIGNAL_PEAK) {
              if (quietSinceRef.current === null) quietSinceRef.current = now;
            } else {
              quietSinceRef.current = null;
            }
            dispatch({
              type: 'chunk',
              noSignal: quietSinceRef.current !== null && now - quietSinceRef.current >= NO_SIGNAL_MS,
            });
          });
          if (controller.signal.aborted) {
            await mic.close();
            return;
          }
          micRef.current = mic;
          if (document.hidden) {
            hiddenSinceRef.current = Date.now();
            mic.mute();
          }
          dispatch({ type: 'listening', granted: mic.granted, at: Date.now() });
        } catch (error) {
          const detail = error instanceof Error ? error.message : undefined;
          const failure: LiveFailure =
            error instanceof MicError
              ? error.failure === 'denied'
                ? 'mic_denied'
                : error.failure === 'missing'
                  ? 'mic_missing'
                  : error.failure === 'busy'
                    ? 'mic_busy'
                    : error.failure === 'unsupported'
                      ? 'mic_unsupported'
                      : 'device_lost'
              : 'device_lost';
          // The session was admitted and the socket opened: tell the server
          // it is over so the slot and the upstream socket are released.
          try {
            if (audio.readyState === WebSocket.OPEN) audio.send(TERMINATE);
          } catch {
            /* closing regardless */
          }
          endedRef.current = true;
          fail(failure, detail);
        }
      })();
    },
    [state.phase, fail, openLive, openAudio],
  );

  const answer = useCallback(
    (choice: number) => {
      const question = state.question;
      const sessionId = sessionRef.current;
      if (!question || !sessionId || state.answering) return;
      dispatch({ type: 'answering', answering: true });
      void request<{ ok: boolean }>(`/api/session/${sessionId}/answer`, {
        method: 'POST',
        auth: true,
        body: { question_id: question.questionId, choice },
      }).then((result) => {
        // 409 means the runner already moved on (its own timeout). The
        // question.answer event, or the next capture event, clears the card.
        if (!result.ok) dispatch({ type: 'answering', answering: false });
      });
    },
    [state.question, state.answering],
  );

  const stop = useCallback(() => {
    endedRef.current = true;
    void teardown(true);
    // The server's session.end may still arrive on a socket we are closing;
    // the screen does not wait for it.
    dispatch({ type: 'phase', phase: 'ended' });
  }, [teardown]);

  const reset = useCallback(() => {
    if (state.phase !== 'ended' && state.phase !== 'failed') return;
    void teardown();
    sessionRef.current = null;
    dispatch({ type: 'reset' });
  }, [state.phase, teardown]);

  return { state, start, answer, stop, reset };
}
