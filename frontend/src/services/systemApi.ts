import api from './api';

/*
 * The system status page's reads (all existing endpoints):
 *   GET  /health/llm        the API process's startup probe, per use case
 *   GET  /health/scheduler  scheduler configuration and scheduled_runs counts
 *   GET  /health/quota      today's YouTube Data API usage
 *   POST /admin/restart     operators only (require_operator); 202 then the
 *                           services go quiet for a few seconds
 */

export type LLMHealthStatus = 'ok' | 'degraded' | 'down' | 'unknown';

/** One measured warning for the config the API process resolved (S-1.14.7). */
export interface HealthWarning {
  kind: 'unacceptable' | 'weaker' | 'not_vision_capable';
  model: string;
  why: string;
  decision_id: string | null;
}

export interface HealthUseCase {
  provider: string;
  model: string;
  reasoning: string;
  ok: boolean;
  latency_ms: number;
  error: string | null;
  guidance?: { status: 'measured' | 'unmeasured'; decision_id: string | null } | null;
  warnings?: HealthWarning[];
}

export interface HealthLLMResponse {
  summary: {
    status: LLMHealthStatus;
    unavailable_features: string[];
    /** Unix seconds; null before the first probe. */
    last_checked_at: number | null;
  };
  use_cases: Record<string, HealthUseCase>;
}

export interface SchedulerStatus {
  enabled: boolean;
  tick_seconds: number;
  lease_seconds: number;
  grace_seconds: number;
  kinds: string[];
  rows: { total: number; enabled: number; due: number; claimed: number };
  last_run_at: string | null;
}

export interface YouTubeQuotaStatus {
  date: string;
  used: number;
  daily_limit: number;
  remaining: number;
}

export interface RestartResponse {
  status: string;
  message: string;
  skip_frontend: boolean;
}

export const systemApi = {
  llm: () => api.get<HealthLLMResponse>('/health/llm').then((r) => r.data),
  scheduler: () => api.get<SchedulerStatus>('/health/scheduler').then((r) => r.data),
  quota: () => api.get<YouTubeQuotaStatus>('/health/quota').then((r) => r.data),
  /** Resolves when the API answers `/health` again. */
  ping: () => api.get('/health', { timeout: 3000 }).then(() => true),
  restart: (skipFrontend: boolean) =>
    api
      .post<RestartResponse>('/admin/restart', null, { params: { skip_frontend: skipFrontend } })
      .then((r) => r.data),
};
