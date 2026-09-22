/* The platform admin API (server/routes/admin.py). Operators only: every call
 * answers 404 for anyone else, and `adminMe` is how the shell decides whether
 * to show the Admin link at all. */

import { useEffect, useState } from 'react';
import { getToken, request } from './session';
import type { ApiResult } from './session';

export interface QualityBlock {
  captures: number;
  committed: number;
  silent_commit_rate: number | null;
  asked_rate: number | null;
  handover_rate: number | null;
}

export interface Quality {
  since: string;
  truncated: boolean;
  sessions: number;
  captures: { total: number; committed: number; flagged: number; unverified: number };
  rates: {
    silent_commit_rate: number | null;
    silent_repair_rate: number | null;
    asked_rate: number | null;
    handover_rate: number | null;
    flag_rate: number | null;
    questions_per_capture: number | null;
  };
  latency_ms: { p50: number | null; p95: number | null; n: number };
  questions: {
    asked: number;
    spoken: number;
    answered_rate: number | null;
    in_grammar_rate: number | null;
    judged: number;
    needed_rate: number | null;
    unnecessary_rate: number | null;
    resolution_ms_p50: number | null;
  };
  by_format: (QualityBlock & { format: string })[];
  by_day: (QualityBlock & { day: string })[];
  regimes: Record<string, number>;
}

export interface BenchmarkRow {
  fixture: string;
  expected: string | null;
  written: string[];
  correct: boolean;
  silent_wrong: number;
  questions: number;
  question_positions: number[];
  expected_question_position: number | null;
  asked_right_position: boolean | null;
}

export interface Benchmark {
  fixtures: number;
  correct: number;
  accuracy: number | null;
  silent_wrong: number;
  questions: number;
  questions_at_right_position: number;
  questions_expected: number;
  results: BenchmarkRow[];
}

export interface Controls {
  live_paused: boolean;
  signups_paused: boolean;
}

export interface Overview {
  organisations: { total: number; suspended: number };
  users: { total: number; disabled: number; admins: number; signed_in_7d: number };
  sessions: { last_24h: number; last_7d: number; running_now: number; capacity: number };
  budget: {
    daily_seconds: number;
    spent_today_seconds: number;
    remaining_seconds: number;
    alarm: boolean;
    exhausted: boolean;
  };
  quality_7d: {
    captures: number;
    silent_commit_rate: number | null;
    asked_rate: number | null;
    handover_rate: number | null;
    needed_rate: number | null;
    latency_p50_ms: number | null;
  };
  benchmark: { ran_at: string; fixtures: number; correct: number; silent_wrong: number } | null;
  controls: Controls;
  live_capture: boolean;
}

export interface AdminOrg {
  id: string;
  name: string;
  active: boolean;
  daily_budget_seconds: number | null;
  created_at: string;
  users: number;
  sessions_7d: number;
  captures_7d: number;
  spent_today_seconds: number;
  last_session_at: string | null;
}

export interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: string;
  active: boolean;
  created_at: string;
  last_login_at: string | null;
  organisation: { id: string; name: string; active: boolean };
  is_admin: boolean;
}

export interface LiveSessionRow {
  id: string;
  organisation: { id: string; name: string } | null;
  source: string | null;
  started_at: string | null;
  running_seconds: number;
  audio_connected: boolean;
}

export interface AuditRow {
  seq: number;
  at: string;
  action: string;
  actor: string;
  organisation_id: string | null;
  session_id: string | null;
  detail: Record<string, unknown> | null;
}

export interface SystemInfo {
  environment: string;
  python: string;
  uptime_seconds: number;
  database: { dialect: string; ok: boolean };
  assemblyai_key_present: boolean;
  live_capture: boolean;
  replay_mode: boolean;
  consent_version: string;
  session_cap_seconds: number;
  max_concurrent_sessions: number;
  sessions_running: number;
  daily_budget_seconds: number;
  trusted_proxy_hops: number;
  api_docs: boolean;
  cors_origins: string[];
  fixtures: number;
}

const A = { auth: true } as const;
const q = (params: Record<string, string | number | undefined>): string => {
  const pairs = Object.entries(params).filter(
    (entry): entry is [string, string | number] => entry[1] !== undefined && entry[1] !== '',
  );
  return pairs.length ? `?${new URLSearchParams(pairs.map(([k, v]) => [k, String(v)])).toString()}` : '';
};

export const adminMe = (signal?: AbortSignal) =>
  request<{ email: string; name: string }>('/api/admin/me', { ...A, ...(signal ? { signal } : {}) });

export const fetchOverview = () => request<Overview>('/api/admin/overview', A);

export const fetchQuality = (days: number, source?: string) =>
  request<Quality>(`/api/admin/quality${q({ days, source })}`, A);

export const fetchBenchmark = () =>
  request<{ ran_at: string | null; result: Benchmark | null }>('/api/admin/quality/benchmark', A);

/* Replays every fixture; generous timeout because a fixture with a question
 * waits out the answer path. */
export const runBenchmark = () =>
  request<{ ran_at: string; result: Benchmark }>('/api/admin/quality/benchmark', {
    ...A,
    method: 'POST',
    timeoutMs: 120_000,
  });

export const fetchOrganisations = (search?: string) =>
  request<{ organisations: AdminOrg[] }>(`/api/admin/organisations${q({ q: search })}`, A);

export const suspendOrg = (id: string, reason: string) =>
  request<AdminOrg>(`/api/admin/organisations/${id}/suspend`, {
    ...A,
    method: 'POST',
    body: { reason },
  });

export const reinstateOrg = (id: string) =>
  request<AdminOrg>(`/api/admin/organisations/${id}/reinstate`, { ...A, method: 'POST' });

export const setOrgBudget = (id: string, seconds: number | null) =>
  request<AdminOrg>(`/api/admin/organisations/${id}/budget`, {
    ...A,
    method: 'PUT',
    body: { daily_budget_seconds: seconds },
  });

export const fetchUsers = (search?: string) =>
  request<{ users: AdminUser[] }>(`/api/admin/users${q({ q: search })}`, A);

export const setUserActive = (id: string, active: boolean): Promise<ApiResult<AdminUser>> =>
  request<AdminUser>(`/api/admin/users/${id}/${active ? 'enable' : 'disable'}`, {
    ...A,
    method: 'POST',
  });

export const fetchLive = () => request<{ sessions: LiveSessionRow[] }>('/api/admin/sessions/live', A);

export const stopSession = (id: string) =>
  request<{ ok: boolean }>(`/api/admin/sessions/${id}/stop`, { ...A, method: 'POST' });

export const fetchAudit = (action?: string, beforeSeq?: number) =>
  request<{ events: AuditRow[]; next_before_seq: number | null; actions: string[] }>(
    `/api/admin/audit${q({ action, before_seq: beforeSeq })}`,
    A,
  );

export const fetchControls = () => request<Controls>('/api/admin/controls', A);

export const putControls = (patch: Partial<Controls>) =>
  request<Controls>('/api/admin/controls', { ...A, method: 'PUT', body: patch });

export const fetchSystem = () => request<SystemInfo>('/api/admin/system', A);

// ---------------------------------------------------------- the nav link --


/* One /api/admin/me per token, shared by every caller: the rail renders on
 * every signed-in screen and must not ask on each navigation. A new token
 * (sign in as someone else) asks again. */
let cache: { token: string; answer: Promise<boolean> } | null = null;

export function useIsAdmin(): boolean {
  const token = getToken();
  const [admin, setAdmin] = useState(false);
  useEffect(() => {
    if (!token) {
      setAdmin(false);
      return;
    }
    if (!cache || cache.token !== token) {
      cache = { token, answer: adminMe().then((r) => r.ok) };
    }
    let live = true;
    void cache.answer.then((ok) => live && setAdmin(ok));
    return () => {
      live = false;
    };
  }, [token]);
  return admin;
}
