import api from './api';

/**
 * BYOK provider keys (E-5.6), `/auth/credentials`, Studio tier only.
 *
 * The server returns metadata, never the key. `set` sends the key once, in
 * the request body; callers keep it out of React state, React Query
 * variables and logs (the keys panel clears its field the moment it submits).
 */
export interface CredentialMetadata {
  provider: string;
  label: string | null;
  created_at: string;
  updated_at: string;
  has_secret: boolean;
}

/**
 * What a "Verify key" press found (T-5.6.8): `unreachable` means the provider
 * gave no answer about the key, so nothing is known about it. The server
 * sends this word and nothing from the provider.
 */
export type KeyCheckResult = 'valid' | 'refused' | 'unreachable';

export const CREDENTIALS_QUERY_KEY = ['auth', 'credentials'] as const;

export const credentialsApi = {
  list: () => api.get<CredentialMetadata[]>('/auth/credentials').then((r) => r.data),
  set: (provider: string, secret: string, label: string | null) =>
    api
      .put<CredentialMetadata>(`/auth/credentials/${encodeURIComponent(provider)}`, {
        secret,
        label,
      })
      .then((r) => r.data),
  remove: (provider: string) =>
    api
      .delete<{ deleted: boolean }>(`/auth/credentials/${encodeURIComponent(provider)}`)
      .then((r) => r.data),
  verify: (provider: string) =>
    api
      .post<{ provider: string; result: KeyCheckResult }>(
        `/auth/credentials/${encodeURIComponent(provider)}/verify`,
      )
      .then((r) => r.data),
};

/**
 * The API writes SQLite timestamps without a zone; they are UTC. Read a
 * zone-less ISO string as UTC so "last changed" is not off by the reader's
 * offset.
 */
export function parseServerTime(value: string): Date {
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`);
}
