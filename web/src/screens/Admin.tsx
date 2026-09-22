import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { Navigate, useSearchParams } from 'react-router-dom';
import { Button, Icon, NAV_PATHS } from '../components';
import { useI18n } from '../i18n';
import type { PlainKey } from '../i18n';
import {
  adminMe,
  fetchAudit,
  fetchBenchmark,
  fetchControls,
  fetchLive,
  fetchOrganisations,
  fetchOverview,
  fetchQuality,
  fetchSystem,
  fetchUsers,
  putControls,
  reinstateOrg,
  runBenchmark,
  setOrgBudget,
  setUserActive,
  stopSession,
  suspendOrg,
} from '../lib/admin';
import type {
  AdminOrg,
  AdminUser,
  AuditRow,
  Benchmark,
  Controls,
  LiveSessionRow,
  Overview,
  Quality,
  SystemInfo,
} from '../lib/admin';
import type { ApiResult } from '../lib/session';
import './Admin.css';

/* The platform admin panel. Operators only: GET /api/admin/me decides, and
 * anyone it refuses is sent to the record without seeing that this exists.
 *
 * An operator screen is scanned, not read, so each tab leads with the few
 * figures that say whether anything needs attention, then the table behind
 * them. State is carried by a word and a pill, never by colour alone. Every
 * write goes through the server, which audits it; nothing here is optimistic. */

const TABS = [
  'overview',
  'quality',
  'organisations',
  'users',
  'live',
  'audit',
  'controls',
  'system',
] as const;
type Tab = (typeof TABS)[number];

const TAB_LABEL: Readonly<Record<Tab, PlainKey>> = {
  overview: 'admin.tab.overview',
  quality: 'admin.tab.quality',
  organisations: 'admin.tab.organisations',
  users: 'admin.tab.users',
  live: 'admin.tab.live',
  audit: 'admin.tab.audit',
  controls: 'admin.tab.controls',
  system: 'admin.tab.system',
};

const isTab = (value: string | null): value is Tab =>
  value !== null && (TABS as readonly string[]).includes(value);

// ------------------------------------------------------------------ helpers --

/** A fetch tied to the component's life, with a manual reload. */
function useLoad<T>(load: () => Promise<ApiResult<T>>, deps: readonly unknown[]) {
  const [state, setState] = useState<
    { status: 'loading' } | { status: 'ok'; data: T } | { status: 'failed'; message: string }
  >({ status: 'loading' });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    setState((prev) => (prev.status === 'ok' ? prev : { status: 'loading' }));
    void load().then((result) => {
      if (!live) return;
      setState(result.ok ? { status: 'ok', data: result.data } : { status: 'failed', message: result.message });
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { state, reload: useCallback(() => setTick((x) => x + 1), []) };
}

function useFormat() {
  const { n, locale } = useI18n();
  return useMemo(() => {
    const dateTime = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
    const dateOnly = new Intl.DateTimeFormat(locale, { dateStyle: 'medium' });
    return {
      pct: (rate: number | null | undefined) =>
        rate === null || rate === undefined ? '—' : `${n(Math.round(rate * 1000) / 10)}%`,
      num: (value: number | null | undefined) => (value === null || value === undefined ? '—' : n(value)),
      when: (iso: string | null | undefined) => (iso ? dateTime.format(new Date(iso)) : '—'),
      day: (iso: string | null | undefined) => (iso ? dateOnly.format(new Date(iso)) : '—'),
      secs: (ms: number) => n(Math.round(ms / 100) / 10),
    };
  }, [n, locale]);
}

function Loading<T>({
  state,
  children,
}: {
  state: { status: 'loading' } | { status: 'ok'; data: T } | { status: 'failed'; message: string };
  children: (data: T) => ReactNode;
}) {
  const { t } = useI18n();
  if (state.status === 'loading') return <p className="admin__note" role="status">{t('admin.loading')}</p>;
  if (state.status === 'failed') {
    return (
      <p className="admin__note admin__note--alert" role="status">
        <Icon name="alert" size={16} />
        {t('admin.failed', { message: state.message })}
      </p>
    );
  }
  return <>{children(state.data)}</>;
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'alert' }) {
  return (
    <div className={tone ? `stat stat--${tone}` : 'stat'}>
      <dt className="stat__label">{label}</dt>
      <dd className="stat__value">{value}</dd>
      {sub ? <dd className="stat__sub">{sub}</dd> : null}
    </div>
  );
}

function Pill({ ok, children }: { ok: boolean; children: ReactNode }) {
  return <span className={ok ? 'pill pill--ok' : 'pill pill--alert'}>{children}</span>;
}

/** A proportion drawn to scale, with its value beside it in text. */
function Meter({ rate }: { rate: number | null }) {
  const width = rate === null ? 0 : Math.max(0, Math.min(1, rate)) * 100;
  return (
    <span className="meter" aria-hidden="true">
      <span className="meter__fill" style={{ width: `${width}%` }} />
    </span>
  );
}

// ----------------------------------------------------------------- overview --

function OverviewTab() {
  const { t } = useI18n();
  const f = useFormat();
  const { state, reload } = useLoad(fetchOverview, []);

  return (
    <Loading state={state}>
      {(o: Overview) => {
        const flags: string[] = [];
        if (o.budget.exhausted) flags.push(t('admin.state.exhausted'));
        else if (o.budget.alarm) flags.push(t('admin.state.alarm'));
        if (o.controls.live_paused) flags.push(t('admin.state.livePaused'));
        if (o.controls.signups_paused) flags.push(t('admin.state.signupsPaused'));
        return (
          <div className="stack">
            <div className="admin__bar">
              {flags.length ? (
                flags.map((flag) => (
                  <Pill ok={false} key={flag}>
                    {flag}
                  </Pill>
                ))
              ) : (
                <Pill ok>{t('admin.state.normal')}</Pill>
              )}
              <Button variant="quiet" onClick={reload}>
                {t('admin.refresh')}
              </Button>
            </div>

            <dl className="stats">
              <Stat
                label={t('admin.kpi.organisations')}
                value={f.num(o.organisations.total)}
                sub={t('admin.kpi.suspended', { n: f.num(o.organisations.suspended) })}
              />
              <Stat
                label={t('admin.kpi.users')}
                value={f.num(o.users.total)}
                sub={t('admin.kpi.usersSub', {
                  active: f.num(o.users.signed_in_7d),
                  disabled: f.num(o.users.disabled),
                })}
              />
              <Stat
                label={t('admin.kpi.sessions')}
                value={f.num(o.sessions.last_24h)}
                sub={t('admin.kpi.sessionsSub', { week: f.num(o.sessions.last_7d) })}
              />
              <Stat
                label={t('admin.kpi.running')}
                value={f.num(o.sessions.running_now)}
                sub={t('admin.kpi.runningSub', { capacity: f.num(o.sessions.capacity) })}
              />
              <Stat
                label={t('admin.kpi.spend')}
                value={f.pct(o.budget.daily_seconds ? o.budget.spent_today_seconds / o.budget.daily_seconds : null)}
                sub={t('admin.kpi.spendSub', {
                  spent: f.num(o.budget.spent_today_seconds),
                  budget: f.num(o.budget.daily_seconds),
                })}
                {...(o.budget.alarm || o.budget.exhausted ? { tone: 'alert' as const } : {})}
              />
              <Stat
                label={t('admin.kpi.benchmark')}
                value={o.benchmark ? `${f.num(o.benchmark.correct)}/${f.num(o.benchmark.fixtures)}` : '—'}
                sub={
                  o.benchmark
                    ? t('admin.kpi.benchmarkSub', {
                        correct: f.num(o.benchmark.correct),
                        total: f.num(o.benchmark.fixtures),
                        wrong: f.num(o.benchmark.silent_wrong),
                      })
                    : t('admin.kpi.benchmarkNone')
                }
                {...(o.benchmark && o.benchmark.silent_wrong > 0 ? { tone: 'alert' as const } : {})}
              />
            </dl>

            <h2 className="admin__h2">{t('admin.tab.quality')}</h2>
            <dl className="stats">
              <Stat label={t('admin.q.silentCommit')} value={f.pct(o.quality_7d.silent_commit_rate)} />
              <Stat label={t('admin.q.asked')} value={f.pct(o.quality_7d.asked_rate)} />
              <Stat label={t('admin.q.handover')} value={f.pct(o.quality_7d.handover_rate)} />
              <Stat label={t('admin.q.neededShort')} value={f.pct(o.quality_7d.needed_rate)} />
            </dl>
          </div>
        );
      }}
    </Loading>
  );
}

// ------------------------------------------------------------------ quality --

function RateTable({ rows, first }: { rows: (Quality['by_format'][number] | Quality['by_day'][number])[]; first: 'format' | 'day' }) {
  const { t } = useI18n();
  const f = useFormat();
  return (
    <div className="table-scroll" tabIndex={0}>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">{t(first === 'format' ? 'admin.col.format' : 'admin.col.day')}</th>
            <th scope="col" className="num">{t('admin.col.captures')}</th>
            <th scope="col" className="num">{t('admin.col.committed')}</th>
            <th scope="col" className="num">{t('admin.col.silent')}</th>
            <th scope="col" className="num">{t('admin.col.asked')}</th>
            <th scope="col" className="num">{t('admin.col.handover')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const key = 'format' in r ? r.format : r.day;
            return (
              <tr key={key}>
                <th scope="row" className="mono">{key}</th>
                <td className="num">{f.num(r.captures)}</td>
                <td className="num">{f.num(r.committed)}</td>
                <td className="num">{f.pct(r.silent_commit_rate)}</td>
                <td className="num">{f.pct(r.asked_rate)}</td>
                <td className="num">{f.pct(r.handover_rate)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function BenchmarkPanel() {
  const { t } = useI18n();
  const f = useFormat();
  const [bench, setBench] = useState<{ ran_at: string | null; result: Benchmark | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void fetchBenchmark().then((r) => r.ok && setBench(r.data));
  }, []);

  const run = () => {
    setBusy(true);
    setError(null);
    void runBenchmark().then((r) => {
      setBusy(false);
      if (r.ok) setBench(r.data);
      else setError(r.message);
    });
  };

  const result = bench?.result ?? null;
  return (
    <section className="panel stack" aria-labelledby="bench-title">
      <div className="admin__bar">
        <h2 className="admin__h2" id="bench-title">{t('admin.bench.title')}</h2>
        <Button onClick={run} busy={busy} busyLabel={t('admin.bench.running')}>
          {t('admin.bench.run')}
        </Button>
      </div>
      <p className="admin__note measure">{t('admin.bench.note')}</p>
      {error ? (
        <p className="admin__note admin__note--alert" role="status">{t('admin.failed', { message: error })}</p>
      ) : null}
      {result ? (
        <>
          <p className="admin__summary">
            <Pill ok={result.correct === result.fixtures && result.silent_wrong === 0}>
              {`${f.num(result.correct)}/${f.num(result.fixtures)}`}
            </Pill>
            {t('admin.bench.summary', {
              correct: f.num(result.correct),
              total: f.num(result.fixtures),
              wrong: f.num(result.silent_wrong),
              right: f.num(result.questions_at_right_position),
              expected: f.num(result.questions_expected),
            })}
            <span className="admin__muted">{f.when(bench?.ran_at)}</span>
          </p>
          <div className="table-scroll" tabIndex={0}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t('admin.col.fixture')}</th>
                  <th scope="col">{t('admin.col.expected')}</th>
                  <th scope="col">{t('admin.col.written')}</th>
                  <th scope="col" className="num">{t('admin.col.questions')}</th>
                  <th scope="col">{t('admin.col.result')}</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((r) => (
                  <tr key={r.fixture}>
                    <th scope="row" className="mono">{r.fixture}</th>
                    <td className="mono">{r.expected ?? t('admin.bench.nothing')}</td>
                    <td className="mono">{r.written.length ? r.written.join(', ') : t('admin.bench.nothing')}</td>
                    <td className="num">
                      {f.num(r.questions)}
                      {r.asked_right_position === false ? ' ✗' : r.asked_right_position ? ' ✓' : ''}
                    </td>
                    <td>
                      <Pill ok={r.correct && r.silent_wrong === 0}>
                        {t(r.correct && r.silent_wrong === 0 ? 'admin.result.ok' : 'admin.result.bad')}
                      </Pill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </section>
  );
}

function QualityTab() {
  const { t } = useI18n();
  const f = useFormat();
  const [days, setDays] = useState(7);
  const [source, setSource] = useState('');
  const { state } = useLoad(() => fetchQuality(days, source || undefined), [days, source]);

  return (
    <div className="stack">
      <div className="admin__bar">
        <label className="admin__field">
          <span>{t('admin.q.window')}</span>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 7, 30, 90].map((d) => (
              <option key={d} value={d}>
                {t('admin.q.days', { n: f.num(d) })}
              </option>
            ))}
          </select>
        </label>
        <label className="admin__field">
          <span>{t('admin.q.source')}</span>
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">{t('admin.q.source.all')}</option>
            <option value="live">{t('admin.q.source.live')}</option>
            <option value="replay">{t('admin.q.source.replay')}</option>
          </select>
        </label>
      </div>

      <Loading state={state}>
        {(q: Quality) =>
          q.captures.total === 0 ? (
            <p className="admin__note">{t('admin.q.none')}</p>
          ) : (
            <div className="stack">
              <dl className="stats">
                <Stat label={t('admin.q.silentCommit')} value={f.pct(q.rates.silent_commit_rate)} />
                <Stat label={t('admin.q.silentRepair')} value={f.pct(q.rates.silent_repair_rate)} />
                <Stat label={t('admin.q.asked')} value={f.pct(q.rates.asked_rate)} />
                <Stat label={t('admin.q.handover')} value={f.pct(q.rates.handover_rate)} />
                <Stat
                  label={t('admin.q.latency')}
                  value={q.latency_ms.p50 === null ? '—' : t('admin.seconds', { n: f.secs(q.latency_ms.p50) })}
                  sub={t('admin.q.latencySub', {
                    p95: q.latency_ms.p95 === null ? '—' : t('admin.seconds', { n: f.secs(q.latency_ms.p95) }),
                  })}
                />
              </dl>

              <section className="panel stack" aria-labelledby="need-title">
                <h2 className="admin__h2" id="need-title">{t('admin.q.necessity.title')}</h2>
                <p className="admin__note measure">{t('admin.q.necessity.body')}</p>
                <div className="split">
                  <span className="split__label">{t('admin.q.needed')}</span>
                  <Meter rate={q.questions.needed_rate} />
                  <span className="split__value">{f.pct(q.questions.needed_rate)}</span>
                  <span className="split__label">{t('admin.q.unneeded')}</span>
                  <Meter rate={q.questions.unnecessary_rate} />
                  <span className="split__value">{f.pct(q.questions.unnecessary_rate)}</span>
                </div>
                <p className="admin__muted">{t('admin.q.judged', { n: f.num(q.questions.judged) })}</p>
              </section>

              <h2 className="admin__h2">{t('admin.q.byFormat')}</h2>
              <RateTable rows={q.by_format} first="format" />
              <h2 className="admin__h2">{t('admin.q.byDay')}</h2>
              <RateTable rows={q.by_day} first="day" />
            </div>
          )
        }
      </Loading>

      <BenchmarkPanel />
    </div>
  );
}

// ------------------------------------------------------------ organisations --

function OrganisationsTab() {
  const { t } = useI18n();
  const f = useFormat();
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const { state, reload } = useLoad(() => fetchOrganisations(search || undefined), [search]);

  const act = (p: Promise<ApiResult<unknown>>) =>
    void p.then((r) => {
      setNotice(r.ok ? null : r.message);
      reload();
    });

  const suspend = (org: AdminOrg) => {
    const reason = window.prompt(t('admin.org.suspendPrompt', { name: org.name }));
    if (reason === null) return;
    act(suspendOrg(org.id, reason));
  };

  const budget = (org: AdminOrg) => {
    const raw = window.prompt(
      t('admin.org.budgetPrompt', { name: org.name }),
      org.daily_budget_seconds === null ? '' : String(org.daily_budget_seconds),
    );
    if (raw === null) return;
    const trimmed = raw.trim();
    if (trimmed !== '' && !/^\d+$/.test(trimmed)) {
      setNotice(t('admin.org.budgetInvalid'));
      return;
    }
    act(setOrgBudget(org.id, trimmed === '' ? null : Number(trimmed)));
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSearch(query.trim());
  };

  return (
    <div className="stack">
      <form className="admin__bar" onSubmit={submit} role="search">
        <label className="admin__field admin__field--grow">
          <span className="sr-only">{t('admin.search')}</span>
          <input
            type="search"
            value={query}
            placeholder={t('admin.org.searchPlaceholder')}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <Button type="submit" variant="secondary">
          {t('admin.search')}
        </Button>
      </form>
      {notice ? <p className="admin__note admin__note--alert" role="status">{notice}</p> : null}

      <Loading state={state}>
        {({ organisations }: { organisations: AdminOrg[] }) => (
          <div className="table-scroll" tabIndex={0}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t('admin.col.name')}</th>
                  <th scope="col" className="num">{t('admin.col.users')}</th>
                  <th scope="col" className="num">{t('admin.col.sessions7d')}</th>
                  <th scope="col" className="num">{t('admin.col.captures7d')}</th>
                  <th scope="col" className="num">{t('admin.col.spendToday')}</th>
                  <th scope="col" className="num">{t('admin.col.budget')}</th>
                  <th scope="col">{t('admin.col.lastActive')}</th>
                </tr>
              </thead>
              <tbody>
                {organisations.map((o) => (
                  <tr key={o.id}>
                    <th scope="row">
                      <span className="table__name">
                        {o.name}
                        {/* Only the abnormal state is marked: "active" on every
                            row is noise that hides the one row that is not. */}
                        {o.active ? null : <Pill ok={false}>{t('admin.status.suspended')}</Pill>}
                      </span>
                      <span className="table__actions">
                        {o.active ? (
                          <button type="button" className="link-btn" onClick={() => suspend(o)}>
                            {t('admin.org.suspend')}
                          </button>
                        ) : (
                          <button type="button" className="link-btn" onClick={() => act(reinstateOrg(o.id))}>
                            {t('admin.org.reinstate')}
                          </button>
                        )}
                        <button type="button" className="link-btn" onClick={() => budget(o)}>
                          {t('admin.org.setBudget')}
                        </button>
                      </span>
                    </th>
                    <td className="num">{f.num(o.users)}</td>
                    <td className="num">{f.num(o.sessions_7d)}</td>
                    <td className="num">{f.num(o.captures_7d)}</td>
                    <td className="num">{t('admin.seconds', { n: f.num(o.spent_today_seconds) })}</td>
                    <td className="num">
                      {o.daily_budget_seconds === null
                        ? t('admin.org.budgetDefault')
                        : t('admin.seconds', { n: f.num(o.daily_budget_seconds) })}
                    </td>
                    <td>{f.day(o.last_session_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Loading>
    </div>
  );
}

// -------------------------------------------------------------------- users --

function UsersTab() {
  const { t } = useI18n();
  const f = useFormat();
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const { state, reload } = useLoad(() => fetchUsers(search || undefined), [search]);

  const toggle = (u: AdminUser) => {
    if (u.active && !window.confirm(t('admin.user.disableConfirm', { email: u.email }))) return;
    void setUserActive(u.id, !u.active).then((r) => {
      setNotice(r.ok ? null : r.message);
      reload();
    });
  };

  return (
    <div className="stack">
      <form
        className="admin__bar"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(query.trim());
        }}
      >
        <label className="admin__field admin__field--grow">
          <span className="sr-only">{t('admin.search')}</span>
          <input
            type="search"
            value={query}
            placeholder={t('admin.user.searchPlaceholder')}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <Button type="submit" variant="secondary">
          {t('admin.search')}
        </Button>
      </form>
      {notice ? <p className="admin__note admin__note--alert" role="status">{notice}</p> : null}

      <Loading state={state}>
        {({ users }: { users: AdminUser[] }) => (
          <div className="table-scroll" tabIndex={0}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t('admin.col.email')}</th>
                  <th scope="col">{t('admin.col.name')}</th>
                  <th scope="col">{t('admin.col.org')}</th>
                  <th scope="col">{t('admin.col.role')}</th>
                  <th scope="col">{t('admin.col.lastLogin')}</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <th scope="row">
                      <span className="table__name mono">
                        {u.email}
                        {u.is_admin ? <span className="tag">{t('admin.user.admin')}</span> : null}
                        {u.active ? null : <Pill ok={false}>{t('admin.status.disabled')}</Pill>}
                      </span>
                      {u.is_admin ? null : (
                        <span className="table__actions">
                          <button type="button" className="link-btn" onClick={() => toggle(u)}>
                            {t(u.active ? 'admin.user.disable' : 'admin.user.enable')}
                          </button>
                        </span>
                      )}
                    </th>
                    <td>{u.name}</td>
                    <td>{u.organisation.name}</td>
                    <td className="mono">{u.role}</td>
                    <td>{f.day(u.last_login_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Loading>
    </div>
  );
}

// --------------------------------------------------------------------- live --

function LiveTab() {
  const { t } = useI18n();
  const f = useFormat();
  const { state, reload } = useLoad(fetchLive, []);

  const stop = (row: LiveSessionRow) => {
    if (!window.confirm(t('admin.live.stopConfirm'))) return;
    void stopSession(row.id).then(reload);
  };

  return (
    <div className="stack">
      <div className="admin__bar">
        <Button variant="quiet" onClick={reload}>
          {t('admin.refresh')}
        </Button>
      </div>
      <Loading state={state}>
        {({ sessions }: { sessions: LiveSessionRow[] }) =>
          sessions.length === 0 ? (
            <p className="admin__note">{t('admin.live.empty')}</p>
          ) : (
            <div className="table-scroll" tabIndex={0}>
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">{t('admin.col.session')}</th>
                    <th scope="col">{t('admin.col.org')}</th>
                    <th scope="col">{t('admin.col.source')}</th>
                    <th scope="col" className="num">{t('admin.col.running')}</th>
                    <th scope="col">{t('admin.col.audio')}</th>
                    <th scope="col">{t('admin.col.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s) => (
                    <tr key={s.id}>
                      <th scope="row" className="mono">{s.id.slice(0, 8)}</th>
                      <td>{s.organisation?.name ?? '—'}</td>
                      <td className="mono">{s.source ?? '—'}</td>
                      <td className="num">{t('admin.seconds', { n: f.num(s.running_seconds) })}</td>
                      <td>{s.audio_connected ? t('admin.on') : t('admin.off')}</td>
                      <td>
                        <button type="button" className="link-btn link-btn--alert" onClick={() => stop(s)}>
                          {t('admin.live.stop')}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </Loading>
    </div>
  );
}

// -------------------------------------------------------------------- audit --

function AuditTab() {
  const { t } = useI18n();
  const f = useFormat();
  const [action, setAction] = useState('admin.');
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [actions, setActions] = useState<string[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [status, setStatus] = useState<'loading' | 'ok' | 'failed'>('loading');
  const [message, setMessage] = useState('');

  const load = useCallback(
    (before?: number) => {
      void fetchAudit(action || undefined, before).then((r) => {
        if (!r.ok) {
          setStatus('failed');
          setMessage(r.message);
          return;
        }
        setStatus('ok');
        setActions(r.data.actions);
        setNext(r.data.next_before_seq);
        setRows((prev) => (before === undefined ? r.data.events : [...prev, ...r.data.events]));
      });
    },
    [action],
  );

  useEffect(() => {
    setStatus('loading');
    load();
  }, [load]);

  return (
    <div className="stack">
      <div className="admin__bar">
        <label className="admin__field">
          <span>{t('admin.col.action')}</span>
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">{t('admin.audit.all')}</option>
            <option value="admin.">{t('admin.audit.admin')}</option>
            {actions.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
      </div>
      {status === 'loading' ? <p className="admin__note">{t('admin.loading')}</p> : null}
      {status === 'failed' ? (
        <p className="admin__note admin__note--alert">{t('admin.failed', { message })}</p>
      ) : null}
      {status === 'ok' && rows.length === 0 ? <p className="admin__note">{t('admin.audit.empty')}</p> : null}
      {rows.length ? (
        <div className="table-scroll" tabIndex={0}>
          <table className="table table--dense">
            <thead>
              <tr>
                <th scope="col" className="num">{t('admin.col.seq')}</th>
                <th scope="col">{t('admin.col.at')}</th>
                <th scope="col">{t('admin.col.action')}</th>
                <th scope="col">{t('admin.col.actor')}</th>
                <th scope="col">{t('admin.col.detail')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.seq}>
                  <td className="num">{e.seq}</td>
                  <td>{f.when(e.at)}</td>
                  <th scope="row" className="mono">{e.action}</th>
                  <td className="mono" title={e.actor}>
                    {e.actor.startsWith('admin:') ? `admin:${e.actor.slice(6, 14)}…` : e.actor}
                  </td>
                  <td className="mono table__detail">{e.detail ? JSON.stringify(e.detail) : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {next !== null ? (
        <Button variant="secondary" onClick={() => load(next)}>
          {t('admin.audit.more')}
        </Button>
      ) : null}
    </div>
  );
}

// ----------------------------------------------------------------- controls --

const SWITCHES: readonly { key: keyof Controls; title: PlainKey; body: PlainKey }[] = [
  { key: 'live_paused', title: 'admin.ctl.live.title', body: 'admin.ctl.live.body' },
  { key: 'signups_paused', title: 'admin.ctl.signups.title', body: 'admin.ctl.signups.body' },
];

function ControlsTab() {
  const { t } = useI18n();
  const { state, reload } = useLoad(fetchControls, []);
  const [busy, setBusy] = useState<keyof Controls | null>(null);

  const flip = (key: keyof Controls, value: boolean) => {
    setBusy(key);
    void putControls({ [key]: value }).then(() => {
      setBusy(null);
      reload();
    });
  };

  return (
    <Loading state={state}>
      {(c: Controls) => (
        <ul className="switches">
          {SWITCHES.map((s) => (
            <li className="switch" key={s.key}>
              <div>
                <h2 className="admin__h2">{t(s.title)}</h2>
                <p className="admin__note measure">{t(s.body)}</p>
              </div>
              <label className="toggle">
                <input
                  type="checkbox"
                  role="switch"
                  checked={c[s.key]}
                  disabled={busy === s.key}
                  onChange={(e) => flip(s.key, e.target.checked)}
                />
                <span className="toggle__track" aria-hidden="true" />
                <span className="toggle__text">{c[s.key] ? t('admin.on') : t('admin.off')}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </Loading>
  );
}

// ------------------------------------------------------------------- system --

function SystemTab() {
  const { t } = useI18n();
  const f = useFormat();
  const { state } = useLoad(fetchSystem, []);
  return (
    <Loading state={state}>
      {(s: SystemInfo) => {
        const rows: [string, ReactNode][] = [
          [t('admin.sys.environment'), s.environment],
          [t('admin.sys.python'), s.python],
          [t('admin.sys.uptime'), t('admin.seconds', { n: f.num(s.uptime_seconds) })],
          [
            t('admin.sys.database'),
            <Pill ok={s.database.ok} key="db">
              {`${s.database.dialect} · ${t(s.database.ok ? 'admin.sys.ok' : 'admin.sys.down')}`}
            </Pill>,
          ],
          [
            t('admin.sys.key'),
            <Pill ok={s.assemblyai_key_present} key="key">
              {t(s.assemblyai_key_present ? 'admin.sys.present' : 'admin.sys.absent')}
            </Pill>,
          ],
          [t('admin.sys.live'), t(s.live_capture ? 'admin.on' : 'admin.off')],
          [t('admin.sys.replayMode'), t(s.replay_mode ? 'admin.on' : 'admin.off')],
          [t('admin.sys.consent'), s.consent_version],
          [t('admin.sys.cap'), t('admin.seconds', { n: f.num(s.session_cap_seconds) })],
          [t('admin.sys.slots'), `${f.num(s.sessions_running)} / ${f.num(s.max_concurrent_sessions)}`],
          [t('admin.sys.budget'), t('admin.seconds', { n: f.num(s.daily_budget_seconds) })],
          [t('admin.sys.proxy'), f.num(s.trusted_proxy_hops)],
          [t('admin.sys.docs'), t(s.api_docs ? 'admin.on' : 'admin.off')],
          [t('admin.sys.cors'), s.cors_origins.join(', ')],
          [t('admin.sys.fixtures'), f.num(s.fixtures)],
        ];
        return (
          <dl className="facts">
            {rows.map(([label, value]) => (
              <div className="facts__row" key={label}>
                <dt>{label}</dt>
                <dd className="mono">{value}</dd>
              </div>
            ))}
          </dl>
        );
      }}
    </Loading>
  );
}

// --------------------------------------------------------------------- page --

export function Admin() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const raw = params.get('tab');
  const tab: Tab = isTab(raw) ? raw : 'overview';

  useEffect(() => {
    const controller = new AbortController();
    void adminMe(controller.signal).then((r) => {
      // An aborted request is not an answer. StrictMode mounts twice in
      // development, and treating the first mount's abort as "not an admin"
      // redirected every operator away from the panel.
      if (!controller.signal.aborted) setAllowed(r.ok);
    });
    return () => controller.abort();
  }, []);

  if (allowed === false) return <Navigate to={NAV_PATHS.record} replace />;
  if (allowed === null) return <p className="admin__note">{t('admin.loading')}</p>;

  return (
    <section className="admin stack">
      <header className="stack">
        <h1 className="admin__title">{t('admin.title')}</h1>
        <p className="admin__intro measure">{t('admin.intro')}</p>
      </header>

      <nav className="tabs" aria-label={t('admin.title')}>
        {TABS.map((id) => (
          <button
            key={id}
            type="button"
            className={id === tab ? 'tabs__tab tabs__tab--current' : 'tabs__tab'}
            aria-current={id === tab ? 'page' : undefined}
            onClick={() => setParams({ tab: id })}
          >
            {t(TAB_LABEL[id])}
          </button>
        ))}
      </nav>

      <div className="admin__body">
        {tab === 'overview' ? <OverviewTab /> : null}
        {tab === 'quality' ? <QualityTab /> : null}
        {tab === 'organisations' ? <OrganisationsTab /> : null}
        {tab === 'users' ? <UsersTab /> : null}
        {tab === 'live' ? <LiveTab /> : null}
        {tab === 'audit' ? <AuditTab /> : null}
        {tab === 'controls' ? <ControlsTab /> : null}
        {tab === 'system' ? <SystemTab /> : null}
      </div>
    </section>
  );
}
