import type { QuotaResponse } from '../services/quotaApi';

/**
 * T-5.2.10 / D-111: the document cap counts the documents this reader can
 * see (their library), reported by `GET /auth/quota` as the `documents`
 * resource. The Subscription page shows it as one line; null until the
 * quota has loaded or when the server does not report it.
 */
export function documentUsageLine(quota: QuotaResponse | undefined): string | null {
  const r = quota?.resources.find((x) => x.resource === 'documents');
  if (!r) return null;
  const held = `${r.consumed.toLocaleString('en-US')} ${r.consumed === 1 ? 'document' : 'documents'}`;
  if (r.limit < 0) return `Your library holds ${held}. This plan has no document cap.`;
  const cap = r.limit.toLocaleString('en-US');
  if (r.consumed > r.limit) {
    return `Your library holds ${held}, over this plan's cap of ${cap}. Everything stays, but nothing new can be added.`;
  }
  if (r.consumed === r.limit) {
    return `Your library is at this plan's cap of ${cap} documents. Nothing new can be added.`;
  }
  return `Your library holds ${held} of the ${cap} this plan allows.`;
}
