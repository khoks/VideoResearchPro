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
