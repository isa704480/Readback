import { useCallback, useEffect, useState } from 'react';
import { Button, Icon, Rack } from '../components';
import type { RackRow } from '../components';
import { useI18n } from '../i18n';
import type { ApiResult } from '../lib/api';
import {
  fetchSession,
  fetchSessionSummaries,
  outcomeOf,
  slotsFor,
} from './DashboardParts';
import type {
  RecordDetail,
  SessionCursor,
  SessionSummary,
  SessionSummaryPage,
} from './DashboardParts';
import './Sessions.css';

/* The team-leader view (DESIGN-BRIEF 4.4): every session this organisation
 * ran, and inside each one, exactly what the pipeline wrote down and the audit
 * of how it got there — and no transcript, because there is no column that
 * could produce one.
 *
 * Two deliberate choices carry the product's thesis onto this screen:
 *
 *  1. The list is drawn from GET /api/session-summaries, a SESSION query, so a
 *     call that correctly captured nothing is on it. A list built by grouping
 *     capture rows could only ever show the calls that captured — which is half
 *     the story and the less interesting half. "Stayed silent, and was right
 *     to" is a row here, not an absence.
 *
 *  2. The drill-down shows which captures were written silently, which asked,
 *     and every question with the answer it got — and then says, in words, that
 *     no transcript exists. The one thing this screen must never do is invent a
 *     row or imply a recording it does not have (DESIGN-BRIEF 6).
 *
 * Signed-in only (App.tsx routes it under AppRoutes); the endpoints it calls are
 * organisation-scoped, so a row here is one this account is allowed to see. */

type ListState =
  | { status: 'loading' }
  | {
      status: 'ok';
      sessions: SessionSummary[];
      more: boolean;
      /** Where the next page starts; null once the last page is in. */
      cursor: SessionCursor | null;
      loadingMore: boolean;
    }
  | { status: 'failed' };

/** Pages are appended, never replaced: the cursor guarantees the next page is
 *  strictly older than everything already shown, so the list only grows. */
function pageState(prior: readonly SessionSummary[], page: SessionSummaryPage): ListState {
  const cursor =
    page.more && page.next_before && page.next_before_id
      ? { before: page.next_before, before_id: page.next_before_id }
      : null;
  return {
    status: 'ok',
    sessions: [...prior, ...page.sessions],
    more: cursor !== null,
    cursor,
    loadingMore: false,
  };
}

function sourceLabel(t: ReturnType<typeof useI18n>['t'], s: SessionSummary): string {
  if (s.source === 'replay' || s.demo_mode) return t('sessions.source.replay');
  if (s.source === 'live') return t('sessions.source.live');
  return s.source ?? t('sessions.source.unknown');
}

function Counts({ s }: { s: SessionSummary }) {
  const { t, n } = useI18n();
  // Only the non-zero facts, so a clean single-capture call reads "1 captured"
  // and not a row of zeroes. `captured` always shows — zero captures is itself
  // the fact on a refusal row, and it is labelled as such below.
  const parts: string[] = [t('sessions.count.captured', { n: n(s.captures) })];
  if (s.silent > 0) parts.push(t('sessions.count.silent', { n: n(s.silent) }));
  if (s.questions > 0) parts.push(t('sessions.count.asked', { n: n(s.questions) }));
  if (s.flagged > 0) parts.push(t('sessions.count.flagged', { n: n(s.flagged) }));
  return <span className="sessions__counts">{parts.join('  ·  ')}</span>;
}

function Detail({ sessionId }: { sessionId: string }) {
  const { t, d, n } = useI18n();
  const [state, setState] = useState<
    { status: 'loading' } | { status: 'ok'; detail: RecordDetail } | { status: 'failed' }
  >({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    void fetchSession(sessionId, controller.signal).then((result: ApiResult<RecordDetail>) => {
      if (controller.signal.aborted) return;
      setState(result.ok ? { status: 'ok', detail: result.data } : { status: 'failed' });
    });
    return () => controller.abort();
  }, [sessionId]);

  if (state.status === 'loading') {
    return <p className="sessions__detail-note" role="status">{t('sessions.detail.loading')}</p>;
  }
  if (state.status === 'failed') {
    return (
      <p className="sessions__detail-note sessions__detail-note--alert" role="status">
        <Icon name="alert" size={16} />
        <span>{t('sessions.detail.failed')}</span>
      </p>
    );
  }

  const { detail } = state;
  const rows: RackRow[] = detail.captures.map((c) => ({
    id: c.id,
    format: c.format,
    state: outcomeOf(c),
    slots: slotsFor(c),
    questions: c.questions_asked,
  }));

  return (
    <div className="sessions__detail stack">
      <dl className="sessions__meta">
        <div>
          <dt>{t('sessions.meta.started')}</dt>
          <dd>{detail.session?.started_at ? d(detail.session.started_at) : '—'}</dd>
        </div>
        <div>
          <dt>{t('sessions.meta.ended')}</dt>
          <dd>
            {detail.session?.ended_at
              ? d(detail.session.ended_at)
              : t('sessions.meta.ongoing')}
          </dd>
        </div>
        {detail.session?.confidence_regime ? (
          <div>
            <dt>{t('sessions.meta.regime')}</dt>
            <dd className="mono">{detail.session.confidence_regime}</dd>
          </div>
        ) : null}
      </dl>

      <section className="stack">
        <h4 className="sessions__section">{t('sessions.section.captures')}</h4>
        {rows.length > 0 ? (
          <Rack rows={rows} title={t('sessions.rackTitle')} legend />
        ) : (
          <p className="sessions__empty measure">{t('sessions.noCaptures')}</p>
        )}
      </section>

      {detail.questions.length > 0 ? (
        <section className="stack">
          <h4 className="sessions__section">{t('sessions.section.questions')}</h4>
          <ul className="sessions__questions">
            {detail.questions.map((q) => (
              <li key={q.id} className="sessions__question">
                <span className="sessions__q-pos mono">
                  {t('sessions.q.position', { n: n(q.position + 1) })}
                </span>
                <span className="sessions__q-body">
                  {q.text ?? q.form}
                  {'  '}
                  <span
                    className={
                      q.answered ? 'sessions__q-answer' : 'sessions__q-answer sessions__q-answer--none'
                    }
                  >
                    {q.answered && q.answer_char
                      ? t('sessions.q.answered', { char: q.answer_char })
                      : t('sessions.q.timedout')}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {detail.events.length > 0 ? (
        <section className="stack">
          <h4 className="sessions__section">{t('sessions.section.audit')}</h4>
          <ol className="sessions__audit">
            {detail.events.map((e) => (
              <li key={e.seq} className="sessions__audit-row">
                <span className="sessions__audit-at mono">{e.at_ms} ms</span>
                <span className="mono">{e.type}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {/* The line the whole design turns on. Not an absence to be inferred — a
          statement, on the record, that there is nothing here to reconstruct. */}
      <p className="sessions__no-transcript measure">
        <Icon name="info" size={16} />
        <span>{t('sessions.noTranscript')}</span>
      </p>
    </div>
  );
}

function Row({
  s,
  open,
  onToggle,
}: {
  s: SessionSummary;
  open: boolean;
  onToggle: (id: string) => void;
}) {
  const { t, d, n } = useI18n();
  return (
    <li className="sessions__row">
      <button
        type="button"
        className="sessions__head"
        aria-expanded={open}
        onClick={() => onToggle(s.id)}
      >
        <span className="sessions__when">
          {s.started_at ? d(s.started_at) : t('sessions.meta.ongoing')}
        </span>
        <span className="sessions__source mono">{sourceLabel(t, s)}</span>
        <Counts s={s} />
        {s.flagged > 0 ? (
          <span className="sessions__flag" title={t('sessions.count.flagged', { n: n(s.flagged) })}>
            <Icon name="alert" size={15} />
          </span>
        ) : null}
        <Icon name="chevron-down" size={16} className="sessions__chev" />
      </button>
      {open ? <Detail sessionId={s.id} /> : null}
    </li>
  );
}

export function Sessions() {
  const { t } = useI18n();
  const [list, setList] = useState<ListState>({ status: 'loading' });
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    setList({ status: 'loading' });
    void fetchSessionSummaries(signal).then((result) => {
      if (signal?.aborted) return;
      setList(result.ok ? pageState([], result.data) : { status: 'failed' });
    });
  }, []);

  const loadMore = useCallback(() => {
    if (list.status !== 'ok' || list.cursor === null || list.loadingMore) return;
    const { cursor, sessions } = list;
    setList({ ...list, loadingMore: true });
    void fetchSessionSummaries(undefined, cursor).then((result) => {
      setList((latest) => {
        // Only the page this click asked for may append. A response that lands
        // after a reload would otherwise duplicate rows under a fresh list.
        if (latest.status !== 'ok' || latest.cursor?.before_id !== cursor.before_id) return latest;
        return result.ok ? pageState(sessions, result.data) : { ...latest, loadingMore: false };
      });
    });
  }, [list]);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const onToggle = useCallback((id: string) => {
    setOpen((current) => (current === id ? null : id));
  }, []);

  return (
    <section className="sessions stack">
      <h1 className="sessions__title">{t('sessions.title')}</h1>
      <p className="sessions__intro measure">{t('sessions.intro')}</p>

      {list.status === 'loading' ? (
        <p className="sessions__empty" role="status">{t('sessions.loading')}</p>
      ) : list.status === 'failed' ? (
        <p className="sessions__empty sessions__empty--alert" role="status">
          <Icon name="alert" size={18} />
          <span>{t('sessions.failed')}</span>
        </p>
      ) : list.sessions.length === 0 ? (
        <p className="sessions__empty measure">{t('sessions.empty')}</p>
      ) : (
        <>
          <ul className="sessions__list">
            {list.sessions.map((s) => (
              <Row key={s.id} s={s} open={open === s.id} onToggle={onToggle} />
            ))}
          </ul>
          {list.more ? (
            <p className="sessions__more">
              <Button
                variant="secondary"
                onClick={loadMore}
                busy={list.loadingMore}
                busyLabel={t('sessions.loading')}
              >
                {t('sessions.loadMore')}
              </Button>
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
