import api from './api';

// Mirrors backend/app/routers/echo.py (I-3 foundation, PR #172).

export interface EchoStatus {
  ready: boolean;
  total_rows: number;
  distinct_sources: number;
  has_personality_trait: boolean;
  threshold_total: number;
  threshold_sources: number;
}

export interface PersonalContextItem {
  id: string;
  kind: string;
  key: string;
  /** Stored as text; non-string values are JSON-encoded by the service. */
  value: string;
  source: string;
  confidence: number;
  captured_at: string;
  expires_at: string | null;
}

/** `source` is fixed to `manual` by the endpoint. Re-posting an existing
 * (kind, key) updates that row in place (service-level upsert). */
export interface RecordContextPayload {
  kind: string;
  key: string;
  value: string;
  expires_at?: string | null;
  confidence?: number;
}

export interface ListContextParams {
  kind?: string;
  source?: string;
  include_expired?: boolean;
}

export interface ConnectorListResponse {
  connectors: string[];
  supported_kinds: string[];
}

export const echoApi = {
  status: () => api.get<EchoStatus>('/echo/status').then(r => r.data),

  listContext: (params?: ListContextParams) =>
    api.get<PersonalContextItem[]>('/echo/context', { params }).then(r => r.data),

  recordContext: (payload: RecordContextPayload) =>
    api.post<PersonalContextItem>('/echo/context', payload).then(r => r.data),

  /** Path-param delete. Keys are URL-encoded; a key containing `/` cannot
   * be addressed this way (Starlette decodes before routing), so the form
   * refuses such keys up front. */
  deleteContext: (kind: string, key: string) =>
    api
      .delete<{ deleted: boolean }>(
        `/echo/context/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`,
      )
      .then(r => r.data),

  /** Deletes every row attributed to `source`. Idempotent. */
  revokeSource: (source: string) =>
    api
      .delete<{ deleted_count: number }>(`/echo/sources/${encodeURIComponent(source)}`)
      .then(r => r.data),

  listConnectors: () => api.get<ConnectorListResponse>('/echo/connectors').then(r => r.data),
};
