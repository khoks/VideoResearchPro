import { isAxiosError } from 'axios';

/**
 * The backend's `detail` string when the error is an HTTP response with
 * one (409 "You already have a shelf named …", 403 tier messages), else
 * the caller's fallback. Pydantic 422 bodies carry a list; those are
 * summarised to their first message.
 */
export function apiErrorMessage(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const detail: unknown = err.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
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
