import api from './api';

/** A human cadence (S-8.3.1): `weekday` 0 = Monday … 6 = Sunday; `day_of_month` 1–28. */
export interface Cadence {
  cadence: 'daily' | 'weekly' | 'monthly';
  hour: number;
  minute?: number;
  weekday?: number;
  day_of_month?: number;
  timezone: string;
}

export type SavedSearchStatus =
  | 'ok'
  | 'failed'
  | 'quota_exceeded'
  | 'feature_unavailable'
  | 'scope_missing';

/** `SavedSearchResponse` (S-8.3.2). Times are UTC ISO strings without a zone. */
export interface SavedSearch {
  id: string;
  question: string;
  answer_language: string;
  scope: { shelf_id: string } | null;
  cadence: Cadence | null;
  next_run_at: string | null;
  notify_email: boolean;
  enabled: boolean;
  created_at: string;
  last_run_at: string | null;
  last_status: SavedSearchStatus | null;
  last_error: string | null;
  last_success_at: string | null;
  last_exchange_id: string | null;
  last_answer: string | null;
}

export interface SavedSearchList {
  items: SavedSearch[];
  active: number;
  /** -1 = unlimited. */
  cap: number;
}

export interface SavedSearchCreate {
  question: string;
  cadence: Cadence;
  answer_language?: string;
  scope?: { shelf_id: string } | null;
  notify_email?: boolean;
}

export type SavedSearchUpdate = Partial<Omit<SavedSearchCreate, 'question'>> & {
  question?: string;
  enabled?: boolean;
};

export const savedSearchesApi = {
  list: () => api.get<SavedSearchList>('/saved-searches').then((r) => r.data),
  create: (body: SavedSearchCreate) => api.post<SavedSearch>('/saved-searches', body).then((r) => r.data),
  update: (id: string, body: SavedSearchUpdate) =>
    api.patch<SavedSearch>(`/saved-searches/${id}`, body).then((r) => r.data),
  remove: (id: string) => api.delete(`/saved-searches/${id}`).then(() => undefined),
  runNow: (id: string) => api.post<{ status: 'queued' }>(`/saved-searches/${id}/run-now`).then((r) => r.data),
};
