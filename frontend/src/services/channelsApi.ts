import api from './api';

/**
 * `ChannelResponse` — the shared channel record plus THIS tenant's state.
 *
 * `name`, `subscriber_count`, `uploads_playlist_id` and `url` are global
 * facts; `subscribed`, `source_weight` and `last_synced_at` are per tenant
 * (D-065); `video_count` counts only documents this tenant can see (D-063).
 */
export interface Channel {
  /** Mirrors `channel_id`. Rows and mutations key on it. */
  id: string;
  channel_id: string;
  name: string;
  /** Public page for the creator; null for creator types with no derivable URL. */
  url: string | null;
  subscribed: boolean;
  /**
   * Per-tenant trust weight, 1.0 = neutral. Read-only until S-7.1.1 ships
   * `PUT /channels/{id}/weight` and the retrieval re-rank (D-068).
   */
  source_weight: number;
  subscriber_count: number | null;
  uploads_playlist_id: string | null;
  last_synced_at: string | null;
  created_at: string | null;
  video_count: number;
}

/**
 * `SubscribeResponse` — returned by subscribe and sync. `job_id` is the
 * dispatched subscription-sync job, or null when dispatch failed (the
 * subscription state still flipped).
 */
export interface SubscribeResponse {
  channel_id: string;
  job_id: string | null;
}

export const channelsApi = {
  list: () => api.get<Channel[]>('/channels').then(r => r.data),
  get: (id: string) => api.get<Channel>(`/channels/${id}`).then(r => r.data),
  subscribe: (id: string) =>
    api.post<SubscribeResponse>(`/channels/${id}/subscribe`).then(r => r.data),
  unsubscribe: (id: string) =>
    api.post<Channel>(`/channels/${id}/unsubscribe`).then(r => r.data),
  sync: (id: string) =>
    api.post<SubscribeResponse>(`/channels/${id}/sync`).then(r => r.data),
};
