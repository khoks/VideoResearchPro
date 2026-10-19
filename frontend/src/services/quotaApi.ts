import api from './api';

/** `GET /auth/quota` (T-5.5.5): this reader's usage against tier limits. */
export interface QuotaResource {
  resource: string;
  period_kind: string;
  period_start: string;
  period_end: string | null;
  consumed: number;
  /** -1 means unlimited. */
  limit: number;
  over_limit: boolean;
}

export interface QuotaResponse {
  tier: string;
  resources: QuotaResource[];
}

export const quotaApi = {
  get: () => api.get<QuotaResponse>('/auth/quota').then(r => r.data),
};

/** How many more uses of `resource` remain this period; Infinity when unlimited. */
export function remainingQuota(quota: QuotaResponse | undefined, resource: string): number {
  const r = quota?.resources.find((x) => x.resource === resource);
  if (!r) return Infinity;
  if (r.limit < 0) return Infinity;
  return Math.max(0, r.limit - r.consumed);
}
