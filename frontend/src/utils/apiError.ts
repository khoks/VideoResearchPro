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

const UNEXPECTED = 'An unexpected error occurred.';

/**
 * What the global query / mutation error toast says: the server's own
 * message when the response carries one (it used to show axios's
 * "Request failed with status code 429"), else the error's text. Null for a
 * document-cap refusal, which its page already shows inline.
 */
export function globalErrorToastMessage(err: unknown): string | null {
  if (isDocumentCapRefusal(err)) return null;
  if (!err) return UNEXPECTED;
  if (typeof err === 'string') return err;
  return apiErrorMessage(err, err instanceof Error && err.message ? err.message : UNEXPECTED);
}
