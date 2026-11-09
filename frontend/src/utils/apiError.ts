import { isAxiosError } from 'axios';

/**
 * The backend's `detail` string when the error is an HTTP response with
 * one (409 "You already have a shelf named …", 403 tier messages), else
 * the caller's fallback. Pydantic 422 bodies carry a list; those are
 * summarised to their first message. A quota refusal whose detail is an
 * object with a `message` (the document cap, T-5.2.10) shows that message.
 */
export function apiErrorMessage(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const detail: unknown = err.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    const message = (detail as { message?: unknown } | null | undefined)?.message;
    if (detail && typeof detail === 'object' && typeof message === 'string' && message.trim()) {
      return message;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: unknown };
      if (typeof first?.msg === 'string') return first.msg.replace(/^Value error, /, '');
    }
  }
  return fallback;
}

export function isNotFound(err: unknown): boolean {
  return isAxiosError(err) && err.response?.status === 404;
}

/**
 * A refusal by the document cap (T-5.2.10): 429 with
 * `detail.resource === 'documents'`. Every action that can meet it (approve,
 * upload, paste, subscribe, sync, a subscription run) says so where it was
 * started, so the global error toast stays out of the way.
 */
export function isDocumentCapRefusal(err: unknown): boolean {
  if (!isAxiosError(err) || err.response?.status !== 429) return false;
  const detail: unknown = err.response?.data?.detail;
  return !!detail && typeof detail === 'object' && (detail as { resource?: unknown }).resource === 'documents';
}

/**
 * "Sync now" refused at the job limit (T-5.2.15): a 429 like any other job's.
 * The channel list and the channel page say so where it was pressed.
 */
export function isSyncRefusal(err: unknown): boolean {
  return (
    isAxiosError(err) &&
    err.response?.status === 429 &&
    /\/channels\/[^/]+\/sync$/.test(err.config?.url ?? '')
  );
}

/**
 * A 401. The API client has dealt with it and the route guard is taking the
 * reader to the sign-in page (T-5.4.22), so there is nothing to say and nothing
 * to try next.
 */
export function isSessionEnded(err: unknown): boolean {
  return isAxiosError(err) && err.response?.status === 401;
}

/**
 * What a failure line on the page says, where the reader acted: the server's
 * words, else `fallback`. Null for a 401, which the session-expiry path owns,
 * as the toasts do (T-3.4.1.18). The mutation behind such a line sets
 * `meta: ERRORS_SHOWN_HERE`, or the global toast says the failure a second time.
 */
export function inlineErrorMessage(err: unknown, fallback: string): string | null {
  return isSessionEnded(err) ? null : apiErrorMessage(err, fallback);
}

const UNEXPECTED = 'An unexpected error occurred.';

/**
 * What the global query / mutation error toast says: the server's own
 * message when the response carries one (it used to show axios's
 * "Request failed with status code 429"), else the error's text. Null for a
 * document-cap refusal or a refused sync, which their pages already show
 * inline, and for a session that ended, where the reader is already on the way
 * out.
 */
export function globalErrorToastMessage(err: unknown): string | null {
  if (isDocumentCapRefusal(err) || isSyncRefusal(err) || isSessionEnded(err)) return null;
  if (!err) return UNEXPECTED;
  if (typeof err === 'string') return err;
  return apiErrorMessage(err, err instanceof Error && err.message ? err.message : UNEXPECTED);
}
