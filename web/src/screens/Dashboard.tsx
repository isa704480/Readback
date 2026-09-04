import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import type { KeyboardEvent } from 'react';
import { Navigate } from 'react-router-dom';
import { Button, Icon, Rack } from '../components';
import type { RackRow } from '../components';
import { getSnapshot, subscribe } from '../lib/api';
import type { ApiErrorKind } from '../lib/api';
import { useI18n } from '../i18n';
import type { TranslationKey } from '../i18n';
import {
  HeldLine,
  RecordRow,
  fetchRecord,
  fetchSession,
  marksFromCaptures,
  marksFromEvents,
  outcomeOf,
  replayAsRecord,
  replayFixture,
  slotsFor,
  toCsv,
} from './DashboardParts';
import type {
  RecordCapture,
  RecordDetail,
  RecordPayload,
  RecordSession,
  ReplayCapture,
} from './DashboardParts';
import './Dashboard.css';

/* THE RECORD -- DESIGN-BRIEF 4.4.
 *
 * The signed-in team-leader screen: what was written down, how long it took,
 * what it had to ask, and what decided each row. It is not a transcript, it
 * carries no confidence number, and it claims nothing it cannot show the
 * denominator for.
 *
 *
 * THE ONE NUMBER, AND WHY IT IS A FRACTION
 * ----------------------------------------
 * The headline is the count of identifiers written without asking anybody
 * anything, over its denominator. Not accuracy: the README says checksum plus
 * two questions plus one re-read reaches ~100% correct in BOTH arms of the
 * comparison, so an accuracy tile measures nothing about this product, and
 * FINDINGS 5 is explicit that silently-wrong is a provisional bound rather than
 * zero. Printing "99.8% accurate" is the third 6 prohibition rendered at 48px.
 * Not capture volume, which measures how busy the phone was. Not questions
 * asked, which makes the headline a number you want to be small and trains
 * people to suppress the questions the product exists to ask.
 *
 * The fraction is the large element and the percentage is small, and that
 * ordering IS the argument. A percentage is the quotable, screenshotable,
 * over-claimable form: it survives being copied out of context. A fraction
 * cannot be quoted without its denominator, and the denominator is the only
 * thing that makes the claim checkable. This project has been burned by
 * threshold overfitting twice, so the headline is the shape that resists it.
 *
 * `silent` means rung = 0 AND questions_asked = 0 -- enforced in the schema by
 * ck_capture_silent_means_rung0, whose comment says rung 1 is excluded
 * deliberately because "counting that as silence would inflate the one number
 * the pitch rests on". The definition is printed under the number, in full,
 * always visible, and never as a tooltip, so the screen defines the number the
 * same way the schema does.
 *
 *
 * WHAT IS DELIBERATELY NOT HERE (6)
 * ---------------------------------
 *   A transcript, an utterance column, an "in context" preview. models.py's
 *   Session docstring: there is deliberately no transcript, turn, utterance or
 *   context column, and none may be added. There is nothing to render.
 *
 *   A confidence percentage, bar, quality score, or sortable certainty.
 *   confidence_at_write is stripped at the API boundary in DashboardParts, not
 *   in a component, so no future screen can reach it.
 *
 *   An accuracy tile. See above.
 *
 *   Toasts, unread badges, notification dots, a pulsing live indicator. A new
 *   row appears BY EXISTING, with an opacity fade. No highlight flash, no
 *   count-up on the headline, no row-slide.
 *
 *   An operator leaderboard. Session.operator_id exists, so this will be
 *   proposed; it must be refused on what the data means. These rows measure the
 *   format's constraint and the caller's diction, not the operator's skill --
 *   an operator whose callers read IBANs (17.1x error budget) would outrank one
 *   whose callers read NHS numbers for reasons that have nothing to do with
 *   either person. And it creates pressure to suppress the questions.
 *
 *   Audio playback or a waveform. No audio is retained; there is no column and
 *   no file.
 *
 *   A TREND CHART OF SILENCE OVER TIME -- NOT YET, AND THIS IS A GATE RATHER
 *   THAN AN OMISSION. Measured against readback.db on 2026-09-01: 176 captures,
 *   TWO distinct final values, ONE format. A trend line over that corpus is a
 *   picture of the fixture set, not of performance. The gate: a real deployment
 *   producing enough distinct identifiers across more than one format to trend.
 *   Until then the fraction with its denominator is the whole honest story.
 */

// ------------------------------------------------------------ error copy --

/* The KIND, not ApiFailure.message: the message is English whoever wrote it and
 * the kind is a closed enum. Same pattern as FAILURE_KEY in screens/Auth.tsx. */
const FAILURE_KEY = {
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

// ---------------------------------------------------------------- states --

type ListState =
  | { status: 'loading' }
  | { status: 'ok'; payload: RecordPayload }
  | { status: 'error'; kind: ApiErrorKind };

type ExampleState =
  | { status: 'idle' }
  | { status: 'running' }
  | { status: 'ok'; capture: ReplayCapture }
  | { status: 'failed' };

/** The README's own headline result, and it is in the database. Run, not typed. */
const EXAMPLE_FIXTURE = 'iso_visible_substitution';

const SMALL_N = 20;
const WINDOW_DAYS = 30;

// -------------------------------------------------------------- headline --

interface HeadlineProps {
  silent: number;
  total: number;
  questions: number;
  /** Null when the payload did not say. It is never inferred: see below. */
  spokenQuestions: number | null;
  answered: number | null;
  allReplay: boolean;
}

function Headline({
  silent,
  total,
  questions,
  spokenQuestions,
  answered,
  allReplay,
}: HeadlineProps) {
  const { t, n } = useI18n();

  /* n = 0: no fraction, no percentage, no zero. The slot is occupied and the
     same height, so the screen does not jump when the first row lands. No
     shimmer skeleton -- a skeleton claims data is arriving when none is. */
  if (total === 0) {
    return (
      <section className="headline headline--empty">
        <h2 className="headline__empty-title">{t('record.headline.empty.title')}</h2>
        <p className="headline__empty-body measure">{t('record.headline.empty.body')}</p>
      </section>
    );
  }

  const percent = Math.round((silent / total) * 100);
  const perId = Math.round((questions / total) * 100) / 100;

  return (
    <section className="headline">
      <p className="headline__figure mono" aria-hidden="true">
        {n(silent)} / {n(total)}
      </p>
      {/* "117 slash 146" is not a sentence. The eye gets the fraction; a screen
          reader gets the claim with its denominator inside it. */}
      <p className="sr-only">{t('record.headline.sr', { silent: n(silent), total: n(total) })}</p>

      {/* The definition, in full, always visible. Not a tooltip. */}
      <p className="headline__definition measure">{t('record.headline.definition')}</p>

      <p className="headline__meta">
        {/* n < 20: the fraction only. A percentage over eleven rows is a picture
            of eleven rows, not a measurement of anything. */}
        {total >= SMALL_N ? (
          <span className="headline__percent mono">{n(percent)}%</span>
        ) : (
          <span className="headline__smalln">{t('record.headline.smallN')}</span>
        )}
        <span className="headline__window mono">{t('record.headline.window')}</span>
        {allReplay ? (
          <span className="headline__window mono">{t('record.headline.replay')}</span>
        ) : null}
      </p>

      <p className="headline__retention">{t('record.headline.retention')}</p>

      {/* Two supporting figures on one line at body size. Never a second hero.
          0.20 q/id earns its place because FINDINGS 3 sweeps this exact
          quantity (1.26 -> 0.45 at ISO p=0.02), so a reader can line it up
          against a documented measurement. The asked/answered breakdown is what
          makes the headline non-suspicious: it shows the questions did not
          vanish. */}
      <p className="headline__figures">
        <span>{t('record.headline.perId', { v: n(perId) })}</span>
        <span aria-hidden="true"> · </span>
        {/* Three shapes, chosen by what the payload actually said. The full
            triple needs an answered count, which main.py:570's counters block
            does not carry today; the pair needs spoken_questions. Neither is
            inferred from the other -- "15 timed out" computed from a number
            nobody sent is exactly the fake this screen exists to refuse. */}
        <span>
          {answered !== null
            ? t('record.headline.triple', {
                asked: n(questions),
                answered: n(answered),
                timedOut: n(Math.max(0, questions - answered)),
              })
            : spokenQuestions !== null
              ? t('record.headline.pair', { asked: n(questions), spoken: n(spokenQuestions) })
              : t('record.headline.asked', { asked: n(questions) })}
        </span>
      </p>
    </section>
  );
}

// ---------------------------------------------------------- empty state ---

function EmptyState({
  example,
  onRun,
}: {
  example: ExampleState;
  onRun: () => void;
}) {
  const { t } = useI18n();

  const row = useMemo<RackRow | null>(() => {
    if (example.status !== 'ok') return null;
    const capture = example.capture;
    /* Every field came back from POST /api/demo/replay, which runs the same
       runner.run_session the live socket does. Nothing is filled in. */
    const asRecord = replayAsRecord(capture, 'example');
    return {
      id: 'example',
      format: capture.format,
      state: outcomeOf(asRecord),
      slots: slotsFor(asRecord),
      questions: capture.questions,
    };
  }, [example]);

  return (
    <div className="record__empty stack">
      {/* 2. The held line at rest. This is the only moment in the product's life
          when the silence indicator can be taught, because it is the only
          moment when it is legibly empty. */}
      <HeldLine marks={[]} span={0} mode="live" present className="held--rest" />

      {/* 3. One worked example, labelled as one. Non-dismissible: 5 says
          anything simulated for a demo says so, on screen. */}
      <div className="record__example">
        <p className="stamp stamp--example">
          <Icon name="alert" size={16} />
          <span>{t('record.empty.chip')}</span>
        </p>

        {example.status === 'failed' ? (
          <div className="notice notice--offline" role="status">
            <Icon name="alert" size={18} />
            <span>{t('record.empty.failed')}</span>
          </div>
        ) : row ? (
          <Rack rows={[row]} title={t('record.empty.exampleTitle')} legend />
        ) : (
          <p className="record__waiting">{t('record.empty.running')}</p>
        )}
      </div>

      <div className="record__actions">
        <Button onClick={onRun} busy={example.status === 'running'} busyLabel={t('record.empty.running')}>
          {t('record.empty.run')}
        </Button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------- one session --

interface SessionPanelProps {
  session: RecordSession | null;
  captures: RecordCapture[];
  detail: RecordDetail | null;
  detailState: 'idle' | 'loading' | 'error';
  openRow: string | null;
  onToggle: (id: string) => void;
}

function SessionPanel({
  session,
  captures,
  detail,
  detailState,
  openRow,
  onToggle,
}: SessionPanelProps) {
  const { t, n, plural } = useI18n();
  const list = useRef<HTMLUListElement>(null);

  /* The true held line where the per-decision history exists -- which is only
     while the session is still live in _SESSIONS -- and the summary form
     everywhere else, with a caption saying where the positions came from. */
  const live = detail !== null && detail.events.length > 0;
  const summary = useMemo(() => marksFromCaptures(captures), [captures]);
  const liveMarks = useMemo(
    () => (detail ? marksFromEvents(detail.events) : []),
    [detail],
  );
  const marks = live ? liveMarks : summary.marks;
  const span = live
    ? Math.max(1, ...liveMarks.map((mark) => mark.at))
    : summary.span;

  /* Rows form a list: up and down move between them, Enter and Space expand
     (the native button does that), Escape collapses. */
  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLUListElement>) => {
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'Escape') return;
      const buttons = Array.from(
        list.current?.querySelectorAll<HTMLButtonElement>('.rec__toggle') ?? [],
      );
      const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
      if (index === -1) return;

      if (event.key === 'Escape') {
        if (openRow !== null) {
          event.preventDefault();
          onToggle(openRow);
        }
        return;
      }
      const next = event.key === 'ArrowDown' ? index + 1 : index - 1;
      const target = buttons[next];
      if (target) {
        event.preventDefault();
        target.focus();
      }
    },
    [onToggle, openRow],
  );

  const open = session !== null && session.ended_at === null;

  return (
    <section className="sess">
      <header className="sess__head">
        <h3 className="sess__title mono">
          {t('record.session.title')} {session ? session.id.slice(0, 8) : ''}
        </h3>
        <p className="sess__facts mono">
          {session?.source ? (
            <span className="stamp">
              {session.source === 'replay' ? t('record.stamp.replay') : session.source}
            </span>
          ) : null}
          {session?.demo_mode ? <span className="stamp">{t('record.stamp.demo')}</span> : null}
          {/* C. 68 of 262 sessions have ended_at IS NULL. The state word is
              "open"; a duration measured from now on a session abandoned three
              days ago is a fabricated number, so none is computed. */}
          {open ? <span className="sess__open">{t('record.session.open')}</span> : null}
          <span className="sess__count">{plural('landing.rack.meta.captures', captures.length)}</span>
        </p>
      </header>

      <HeldLine
        marks={marks}
        span={span}
        mode={live ? 'live' : 'summary'}
        {...(live ? { present: true } : {})}
        counts={{
          captures: captures.length,
          spoken: captures.filter((capture) => capture.questions_asked > 0).length,
        }}
      />

      {captures.length === 0 ? (
        /* E. A session with zero captures is a RESULT, not a blank. 71 of the
           spec's 217 sessions produced no capture and that is the system
           working: a non-identifier fixture must open no row. */
        <div className="sess__none">
          <p className="sess__none-title">{t('record.session.none')}</p>
          <p className="sess__none-note">{t('record.session.none.note')}</p>
        </div>
      ) : (
        <>
          <p className="sess__list-label mono">
            {t('record.list.title')}
            <span className="sess__list-n">{n(captures.length)}</span>
          </p>
          <ul className="rec__list" onKeyDown={onKeyDown} ref={list} aria-label={t('record.list.title')}>
            {captures.map((capture) => (
              <RecordRow
                key={capture.id}
                capture={capture}
                session={session}
                detail={detail}
                detailState={detailState}
                open={openRow === capture.id}
                onToggle={onToggle}
              />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- screen --

export function Dashboard() {
  const { t, n } = useI18n();

  /* Reactive rather than a bare isSignedIn(): signing out in another tab has to
   * bounce this one too. */
  const token = useSyncExternalStore(subscribe, getSnapshot, () => null);

  const [state, setState] = useState<ListState>({ status: 'loading' });
  const [reloads, setReloads] = useState(0);
  const [openRow, setOpenRow] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, RecordDetail>>({});
  const [detailState, setDetailState] = useState<'idle' | 'loading' | 'error'>('idle');
  const [example, setExample] = useState<ExampleState>({ status: 'idle' });
  const exampleAsked = useRef(false);

  useEffect(() => {
    if (token === null) return;
    const controller = new AbortController();
    setState({ status: 'loading' });

    void fetchRecord(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setState(result.ok ? { status: 'ok', payload: result.data } : { status: 'error', kind: result.kind });
    });

    return () => controller.abort();
  }, [token, reloads]);

  const payload = state.status === 'ok' ? state.payload : null;
  const captures = useMemo(() => payload?.captures ?? [], [payload]);

  const sessions = useMemo(() => {
    const map = new Map<string, RecordSession>();
    for (const session of payload?.sessions ?? []) map.set(session.id, session);
    return map;
  }, [payload]);

  /* Grouped by session, newest first. A session is a container for captures and
   * the captures are the thing, so the group is a heading and never a route. */
  const groups = useMemo(() => {
    const byId = new Map<string, RecordCapture[]>();
    for (const capture of captures) {
      const list = byId.get(capture.session_id);
      if (list) list.push(capture);
      else byId.set(capture.session_id, [capture]);
    }
    // Sessions the server listed that produced nothing still get a panel: that
    // is honesty surface E and it is the commonest correct outcome in the DB.
    for (const id of sessions.keys()) if (!byId.has(id)) byId.set(id, []);

    return Array.from(byId.entries())
      .map(([id, rows]) => ({
        id,
        session: sessions.get(id) ?? null,
        captures: rows
          .slice()
          .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)),
      }))
      .sort((a, b) => {
        const at = a.captures[0]?.created_at ?? a.session?.started_at ?? '';
        const bt = b.captures[0]?.created_at ?? b.session?.started_at ?? '';
        return Date.parse(bt) - Date.parse(at);
      });
  }, [captures, sessions]);

  /* Counters come from the server when it sends them -- models.py gives silence
   * a column rather than a derivation, and the reason is written on it. Falling
   * back to counting the rows in hand is the only other honest option, and it
   * is what the denominator then describes: the rows on this screen. */
  const counters = payload?.counters ?? null;
  const total = counters?.captures ?? captures.length;
  const silent = counters?.silent ?? captures.filter((capture) => capture.silent).length;
  const questions =
    counters?.questions ?? captures.reduce((sum, capture) => sum + capture.questions_asked, 0);
  /* NOT `?? questions`. Whether a question was spoken out loud lives on
   * QuestionEvent.spoken, which the list does not carry, so with no counters
   * block there is no honest value -- and defaulting it to the number asked
   * would assert that every question was spoken. It happens to be true of every
   * row in the dev database (35 of 35 spoken), which is precisely why it would
   * never have been caught. */
  const spokenQuestions = counters?.spoken_questions ?? null;

  /* A. Every session in the dev database carries demo_mode = 1 and 234 of 262
   * are source='replay'. When EVERY visible session is a replay the banner is
   * always there, which is what makes it a caption and not a toast. On a MIXED
   * set there is no banner -- a banner over a mixed list mislabels the live
   * rows, which is worse than no banner -- and the per-row stamp says which. */
  const visibleSessions = Array.from(sessions.values());
  const allReplay =
    visibleSessions.length > 0 &&
    visibleSessions.every((session) => session.demo_mode || session.source === 'replay');

  // L3 reads the per-session endpoint once per session, on first expand.
  useEffect(() => {
    if (openRow === null) return;
    const capture = captures.find((row) => row.id === openRow);
    if (!capture) return;
    if (details[capture.session_id]) {
      setDetailState('idle');
      return;
    }
    const controller = new AbortController();
    setDetailState('loading');
    void fetchSession(capture.session_id, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) {
        setDetails((current) => ({ ...current, [capture.session_id]: result.data }));
        setDetailState('idle');
      } else {
        setDetailState('error');
      }
    });
    return () => controller.abort();
  }, [openRow, captures, details]);

  const runExample = useCallback(() => {
    setExample({ status: 'running' });
    void replayFixture(EXAMPLE_FIXTURE).then((result) => {
      const first = result.ok ? result.data[0] : undefined;
      setExample(first ? { status: 'ok', capture: first } : { status: 'failed' });
    });
  }, []);

  // The example is fetched once, when the screen is actually empty. It is not
  // fetched speculatively: it is a POST that opens a real session row.
  const isEmpty = state.status === 'ok' && captures.length === 0;
  useEffect(() => {
    if (!isEmpty || exampleAsked.current) return;
    exampleAsked.current = true;
    runExample();
  }, [isEmpty, runExample]);

  const onToggle = useCallback((id: string) => {
    setOpenRow((current) => (current === id ? null : id));
  }, []);

  const onExport = useCallback(() => {
    const disclosure = [
      t('record.export.window', { days: n(WINDOW_DAYS), rows: n(captures.length) }),
      allReplay ? t('record.export.replay.all') : t('record.export.replay.mixed'),
    ].join(' ');
    const blob = new Blob([toCsv(captures, sessions, disclosure)], {
      type: 'text/csv;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'readback-record.csv';
    anchor.click();
    URL.revokeObjectURL(url);
  }, [allReplay, captures, n, sessions, t]);

  // No token at all is a different thing from a token the server cannot confirm
  // right now: only the first is grounds for sending somebody to /login.
  if (token === null) return <Navigate to="/login" replace />;

  const openDetail = openRow
    ? (details[captures.find((row) => row.id === openRow)?.session_id ?? ''] ?? null)
    : null;

  /* THE RAIL IS NOT RENDERED HERE, AND THAT IS DELIBERATE.
   *
   * 5 puts a 240px navigation rail beside this screen, and components/Sidebar
   * .tsx already exists for it -- a second one is exactly the drift that rule
   * warns about, so this screen does not draw one. But it does not MOUNT that
   * one either, for two reasons and only the first is about today:
   *
   *   1. The rail spans Live, Record, Formats and Demo. Mounted inside one
   *      screen it unmounts on every route change and does not exist on the
   *      other three. It belongs in Shell, beside <Outlet />, which is the
   *      arrangement the app-shell notes already describe.
   *   2. As of this writing Sidebar.tsx renders seven catalog keys that the
   *      catalogs have not got (nav.live, nav.record, nav.sessions,
   *      nav.formats, nav.demo, nav.account, nav.sidebar.label,
   *      nav.record.silent). t() on a missing key returns undefined, and the
   *      one call that passes params -- nav.record.silent -- then throws
   *      inside interpolate(). Verified in the browser: mounting it here took
   *      the whole screen down with "Cannot read properties of undefined
   *      (reading 'replace')".
   *
   * The wiring, for whoever owns App.tsx: render <Sidebar /> as the first child
   * of <main className="shell__main page">, move id="main" tabIndex={-1} onto
   * the div that wraps <Outlet /> so the skip link still lands on content, and
   * pass written={{ silent, total }} once the shell has the counters. */
  return (
    <div className="record">
      <div className="record__main stack">
        <header className="record__head">
          <p className="record__eyebrow mono">{t('record.eyebrow')}</p>
          <h1 className="record__title">{t('record.title')}</h1>
          <p className="record__lede measure">{t('record.lede')}</p>

          {allReplay ? (
            /* Always there, so it never interrupts. A caption, not a toast. */
            <p className="record__replay">
              <Icon name="alert" size={18} />
              <span>{t('record.replay.banner')}</span>
            </p>
          ) : null}
        </header>

        {/* The headline renders only once the record has actually answered.
            Its n = 0 branch says "No identifiers captured yet", which is a
            CLAIM -- and while the request is in flight, or after it failed, we
            do not know whether that is true. Printing it anyway would be the
            screen asserting something it has not been told, which is the same
            failure as a fabricated row wearing a politer face. */}
        {state.status === 'ok' ? (
          <Headline
            silent={silent}
            total={total}
            questions={questions}
            spokenQuestions={spokenQuestions}
            answered={counters?.answered ?? null}
            allReplay={allReplay}
          />
        ) : null}

        {state.status === 'loading' ? (
          <p className="record__waiting" role="status">
            {t('record.loading')}
          </p>
        ) : null}

        {state.status === 'error' ? (
          <div className="notice notice--offline" role="alert">
            <Icon name="alert" size={18} />
            <span>
              {state.kind === 'not_found' ? t('record.error.noEndpoint') : t(FAILURE_KEY[state.kind])}
            </span>
          </div>
        ) : null}

        {state.status === 'error' ? (
          <div className="record__actions">
            <Button variant="secondary" onClick={() => setReloads((count) => count + 1)}>
              {t('record.retry')}
            </Button>
          </div>
        ) : null}

        {isEmpty ? <EmptyState example={example} onRun={runExample} /> : null}

        {state.status === 'ok' && groups.length > 0 ? (
          <>
            <div className="record__actions">
              <Button variant="secondary" onClick={onExport}>
                {t('record.export')}
              </Button>
            </div>

            <div className="record__sessions">
              {groups.map((group) => (
                <SessionPanel
                  key={group.id}
                  session={group.session}
                  captures={group.captures}
                  detail={group.captures.some((capture) => capture.id === openRow) ? openDetail : null}
                  detailState={detailState}
                  openRow={openRow}
                  onToggle={onToggle}
                />
              ))}
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
