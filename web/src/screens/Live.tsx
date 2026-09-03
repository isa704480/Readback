import { useEffect, useMemo, useState } from 'react';
import { Button, ButtonLink, Icon, NAV_PATHS, Rack } from '../components';
import type { RackRow } from '../components';
import { useI18n } from '../i18n';
import type { I18n, TranslationKey } from '../i18n';
import { HeldLine } from './DashboardParts';
import { useLiveSession } from '../lib/useLiveSession';
import type { LiveFailure, LiveRow, LiveState } from '../lib/useLiveSession';
import { Consent } from './Consent';
import './Live.css';

/* THE LIVE SCREEN -- DESIGN-BRIEF 4.1, 4.2, 4.3. The operator view.
 *
 * It has one job while a call is running: show that the agent is listening,
 * has understood, and has decided not to speak -- and then, once in a while,
 * show the one character it wants to ask about. Everything else on the page
 * is furniture for those two moments.
 *
 * WHAT IS NOT HERE, AND WHY (6):
 *   no transcript        the stream carries none, and this screen would refuse
 *                        it if it did
 *   no confidence        the stream carries none; uncertainty is the question
 *   no waveform          it moves when anyone talks and says nothing about
 *                        whether Readback understood; 4.2 bans it by name
 *   no spinner           a spinner is a wait; listening is the finished state
 *   no toasts or badges  silence is the product and the screen observes it
 *
 * THE ONLY MOTION is the rack's own (it takes .rack--live so motion.css's
 * ledger and settle rules apply when the rack sets their attributes) and the
 * 4-second breath on the silence indicator, which motion.css 8 argues for
 * and pairs with a mandatory still equivalent -- the elapsed counter -- so a
 * reader under prefers-reduced-motion loses no fact. There is no scroll-linked
 * motion and no reveal on this screen; it is an operator screen.
 *
 * EVERYTHING ON THIS SCREEN CAME FROM THE PIPELINE. The rows are capture.*
 * events; the marks are silence.held events; the gate is the decider's own
 * sentence; the cap is the server's number; the microphone settings are what
 * the browser reported, not what was requested. Nothing is simulated, so
 * nothing needs a "simulated" stamp -- and when the server can only replay,
 * the screen refuses to open a session rather than show a replay as a call. */

const FORMAT_NAME = {
  iban: 'account.format.iban.name',
  iso6346: 'account.format.iso6346.name',
  nhs: 'account.format.nhs.name',
  vin: 'account.format.vin.name',
  luhn: 'account.format.luhn.name',
} as const satisfies Record<string, TranslationKey>;

type FormatId = keyof typeof FORMAT_NAME;

function formatName(id: string, t: I18n['t']): string {
  return Object.prototype.hasOwnProperty.call(FORMAT_NAME, id) ? t(FORMAT_NAME[id as FormatId]) : id;
}

const FAILURE_KEY = {
  consent_absent: 'live.fail.consent_absent',
  server_unreachable: 'live.fail.server_unreachable',
  server_refused: 'live.fail.server_refused',
  no_live_capture: 'live.fail.no_live_capture',
  mic_denied: 'live.fail.mic_denied',
  mic_missing: 'live.fail.mic_missing',
  mic_busy: 'live.fail.mic_busy',
  mic_unsupported: 'live.fail.mic_unsupported',
  audio_refused: 'live.fail.audio_refused',
  upstream_refused: 'live.fail.upstream_refused',
  connection_lost: 'live.fail.connection_lost',
  device_lost: 'live.fail.device_lost',
} as const satisfies Record<LiveFailure, TranslationKey>;

/* mm:ss. A timing, so ASCII digits regardless of locale -- the same rule the
 * rack applies to identifiers, for the same reason: it is read against a clock
 * on a wall, not a sentence. */
function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s < 10 ? '0' : ''}${s}`;
}

/* One tick a second while listening. Drives the elapsed counter, the cap
 * countdown and the held line's axis; nothing else re-renders on it. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

// --------------------------------------------------------- the indicator --

function Quiet({ state, now }: { state: LiveState; now: number }) {
  const { t, n } = useI18n();
  const elapsedMs = state.listeningSince === null ? 0 : now - state.listeningSince;
  const cap = state.capSeconds;
  const remaining = cap === null ? null : Math.max(0, cap - Math.floor(elapsedMs / 1000));
  const span = state.streamZero === null ? 0 : now - state.streamZero;
  const time = clock(elapsedMs);

  return (
    <section className="quiet card" aria-label={t('live.state.listening')}>
      <div className="quiet__head">
        {/* The breath (motion.css 8): opacity only, on a dot with no text,
            never below the measured 3:1 floor. Hidden under reduced motion,
            where the counter beside it is the still equivalent. */}
        <span className="quiet__dot rb-motion-only rb-quiet" aria-hidden="true" />
        <span className="quiet__word">{t('live.state.listening')}</span>
        <span className="quiet__elapsed">
          <span className="quiet__elapsedLabel">{t('live.elapsed.label')}</span>
          <span className="mono rb-silence-elapsed" aria-hidden="true">
            {time}
          </span>
          <span className="sr-only">{t('live.elapsed.sr', { time })}</span>
        </span>
      </div>

      <HeldLine
        marks={state.marks}
        span={span}
        mode="live"
        present={state.present}
        {...(state.heldGate !== undefined ? { gate: state.heldGate } : {})}
      />

      <p className="quiet__armed">
        {state.armedFormat ? t('live.armed', { format: formatName(state.armedFormat, t) }) : t('live.idle')}
      </p>

      {cap !== null && remaining !== null ? (
        <p className="quiet__cap mono">{t('live.cap.remaining', { s: n(remaining), cap: n(cap) })}</p>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------- the question --

function Ask({
  state,
  onAnswer,
}: {
  state: LiveState;
  onAnswer: (choice: number) => void;
}) {
  const { t, n } = useI18n();
  const q = state.question;
  if (!q) return null;

  return (
    <section className="ask card" aria-live="polite" aria-label={t('live.q.title')}>
      <p className="ask__eyebrow mono">
        <Icon name="asking" size={16} />
        <span>{t('live.q.title')}</span>
        <span aria-hidden="true">·</span>
        <span>{t('live.q.position', { n: n(q.position + 1) })}</span>
      </p>

      {q.text ? (
        <p className="ask__says">
          <span>{t('live.q.says')}</span>{' '}
          {/* The agent's sentence is English on every interface language; it
              is what is heard on the call, quoted, not translated. */}
          <q lang="en" translate="no" dir="ltr">
            {q.text}
          </q>
        </p>
      ) : null}

      <p className="ask__tap">{t('live.q.tap')}</p>
      <div className="ask__chips">
        {q.choices.map((char, index) => (
          <button
            key={`${q.questionId}-${index}`}
            type="button"
            className="ask__chip rb-press"
            aria-label={t('live.q.choice', { char })}
            disabled={state.answering}
            onClick={() => onAnswer(index)}
          >
            <span className="ask__char" translate="no" dir="ltr" lang="en">
              {char}
            </span>
          </button>
        ))}
      </div>
      {state.answering ? (
        <p className="ask__sent" role="status">
          {t('live.q.sent')}
        </p>
      ) : null}

      {q.blind ? (
        <p className="ask__blind">
          <Icon name="info" size={16} />
          <span>{t('live.q.blind')}</span>
        </p>
      ) : null}
      <p className="ask__note">{t('live.q.nobody')}</p>
      <p className="ask__note">{t('live.q.voiceNote')}</p>
    </section>
  );
}

// --------------------------------------------------- what the browser gave --

function Granted({ state }: { state: LiveState }) {
  const { t, n } = useI18n();
  const g = state.granted;
  if (!g) return null;
  const flag = (value: boolean | null) =>
    value === null ? t('live.mic.unknown') : value ? t('parts.toggle.on') : t('parts.toggle.off');

  return (
    <section className="mic card" aria-label={t('live.mic.title')}>
      <h2 className="mic__title">{t('live.mic.title')}</h2>
      <dl className="mic__facts mono">
        <div>
          <dt>{t('live.mic.device')}</dt>
          <dd>{g.deviceLabel || t('live.mic.device.unknown')}</dd>
        </div>
        <div>
          <dt>Hz</dt>
          <dd>
            {g.sampleRate !== null
              ? t('live.mic.rate', { rate: String(g.sampleRate) })
              : t('live.mic.rate.unknown', { rate: String(g.contextSampleRate) })}
          </dd>
        </div>
        <div>
          <dt>ch</dt>
          <dd>{g.channelCount !== null ? t('live.mic.channels', { n: n(g.channelCount) }) : t('live.mic.unknown')}</dd>
        </div>
        <div>
          <dt>{t('live.mic.ec')}</dt>
          <dd>{flag(g.echoCancellation)}</dd>
        </div>
        <div>
          <dt>{t('live.mic.ns')}</dt>
          <dd>{flag(g.noiseSuppression)}</dd>
        </div>
        <div>
          <dt>{t('live.mic.agc')}</dt>
          <dd>{flag(g.autoGainControl)}</dd>
        </div>
      </dl>
      <p className="mic__chunks mono">{t('live.chunks', { n: n(state.chunksSent) })}</p>
    </section>
  );
}

// ---------------------------------------------------------------- the end --

function Ended({ state, onAgain }: { state: LiveState; onAgain: () => void }) {
  const { t, n } = useI18n();
  const s = state.summary;
  const cap = n(state.capSeconds ?? 150);
  /* The cap is reported by the audio socket's close code (4408), not by the
   * event stream: the runner only ever sees its frames end, and calls that
   * "complete". The hook records which it was. */
  const reason =
    state.capReached || s?.reason === 'cap'
      ? t('live.ended.reason.cap', { cap })
      : s === null || s.reason === 'complete' || s.reason === 'user'
        ? t('live.ended.reason.stopped')
        : s.reason === 'error'
          ? t('live.ended.reason.error')
          : t('live.ended.reason.other', { reason: s.reason });

  return (
    <section className="end card" aria-live="polite">
      <p className="end__eyebrow mono">
        <Icon name="settled" size={16} />
        <span>{t('live.state.ended')}</span>
      </p>
      <h2 className="end__title">{t('live.ended.title')}</h2>
      <p className="end__reason">{reason}</p>
      <p className="end__tally mono">
        {s
          ? t('live.ended.tally', {
              captures: n(s.captures),
              silent: n(s.silent),
              questions: n(s.questions),
            })
          : t('live.ended.waiting')}
      </p>
      <div className="end__go">
        <Button variant="primary" onClick={onAgain}>
          {t('live.again')}
        </Button>
        <ButtonLink to={NAV_PATHS.record} variant="secondary">
          {t('route.pending.toRecord')}
        </ButtonLink>
      </div>
    </section>
  );
}

function Failed({ state, onAgain }: { state: LiveState; onAgain: () => void }) {
  const { t } = useI18n();
  const failure = state.failure ?? 'connection_lost';
  return (
    <section className="end card">
      <div className="notice notice--error" role="alert">
        <Icon name="alert" size={16} />
        <span>{t(FAILURE_KEY[failure])}</span>
      </div>
      {state.detail ? (
        <p className="end__detail mono">
          <span>{t('live.fail.detail')}</span>
          <span translate="no" dir="ltr">
            {state.detail}
          </span>
        </p>
      ) : null}
      <div className="end__go">
        <Button variant="primary" onClick={onAgain}>
          {t('live.again')}
        </Button>
        <ButtonLink to={NAV_PATHS.record} variant="secondary">
          {t('route.pending.toRecord')}
        </ButtonLink>
      </div>
    </section>
  );
}

// ------------------------------------------------------------- the screen --

const PHASE_WORD = {
  consent: 'consent.eyebrow',
  starting: 'live.state.starting',
  connecting: 'live.state.connecting',
  listening: 'live.state.listening',
  ended: 'live.state.ended',
  failed: 'live.state.failed',
} as const satisfies Record<LiveState['phase'], TranslationKey>;

export function Live() {
  const i18n = useI18n();
  const { t, n } = i18n;
  const { state, start, answer, stop, reset } = useLiveSession();
  const now = useNow(state.phase === 'listening');

  const rows = useMemo<RackRow[]>(
    () =>
      state.rows.map((row: LiveRow) => ({
        id: row.id,
        format: formatName(row.formatId, t),
        state: row.state,
        slots: row.slots,
        questions: row.questions,
        ...(row.reason ? { note: t('live.row.reason', { reason: row.reason }) } : {}),
      })),
    [state.rows, t],
  );

  if (state.phase === 'consent') {
    return (
      <div className="live">
        <Consent onStart={start} busy={false} capSeconds={state.capSeconds} />
      </div>
    );
  }

  const busy = state.phase === 'starting' || state.phase === 'connecting';

  return (
    <div className="live stack">
      <header className="live__head">
        <p className="live__eyebrow mono">
          <Icon name="heard" size={16} />
          <span>{t('live.eyebrow')}</span>
          <span aria-hidden="true">·</span>
          <span role="status">{t(PHASE_WORD[state.phase])}</span>
        </p>
        <h1 className="live__title">{t('live.title')}</h1>
      </header>

      {busy ? (
        <section className="quiet card" aria-live="polite">
          <div className="quiet__head">
            <span className="quiet__word">{t(PHASE_WORD[state.phase])}</span>
          </div>
        </section>
      ) : null}

      {state.phase === 'listening' ? <Quiet state={state} now={now} /> : null}

      {state.phase === 'listening' && state.noSignal ? (
        <div className="notice" role="status">
          <Icon name="alert" size={16} />
          <span>{t('live.noSignal')}</span>
        </div>
      ) : null}

      {state.hiddenMs >= 1000 && state.phase === 'listening' ? (
        <div className="notice" role="status">
          <Icon name="info" size={16} />
          <span>{t('live.hidden.notice', { s: n(Math.round(state.hiddenMs / 1000)) })}</span>
        </div>
      ) : null}

      {state.phase === 'listening' ? <Ask state={state} onAnswer={answer} /> : null}

      {state.phase === 'ended' ? <Ended state={state} onAgain={reset} /> : null}
      {state.phase === 'failed' ? <Failed state={state} onAgain={reset} /> : null}

      {state.phase === 'listening' || rows.length > 0 ? (
        <Rack
          rows={rows}
          title={t('live.rack.title')}
          {...(state.phase === 'listening' ? { meta: t('live.rack.meta') } : {})}
          className="rack--live"
        />
      ) : null}

      {state.phase === 'listening' ? (
        <>
          <p className="live__capExplain">{t('live.cap.explain', { cap: n(state.capSeconds ?? 150) })}</p>
          <div className="live__stop">
            <Button variant="secondary" onClick={stop}>
              {t('live.stop')}
            </Button>
          </div>
          <Granted state={state} />
        </>
      ) : null}
    </div>
  );
}
