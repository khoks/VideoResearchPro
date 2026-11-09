import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';
import { useJobStore } from '../stores/jobStore';
import { apiErrorMessage, globalErrorToastMessage, isSessionEnded } from '../utils/apiError';
import { detailFromErrorBody } from '../utils/ingestResults';

function toastError(error: unknown): void {
  // Null for errors the page already shows where the action started.
  const message = globalErrorToastMessage(error);
  if (message) useJobStore.getState().pushToast('error', message);
}

/**
 * The app's one client, with the global error toast.
 *
 * `meta: { errorsShownHere: true }` on a mutation says every failure is answered
 * already, so the toast stays out of the way: both would otherwise speak
 * (T-3.4.1.15). A toast goes in the hook's own `onError`. A per-call one on
 * `mutate` is dropped once its component has unmounted, and nothing would be said.
 * A line on the page, where the reader acted, needs no toast beside it
 * (T-3.4.1.18): see `ERRORS_SHOWN_HERE`.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 1, staleTime: 5000 },
    },
    queryCache: new QueryCache({ onError: toastError }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (!mutation.meta?.errorsShownHere) toastError(error);
      },
    }),
  });
}

/**
 * `meta` for a mutation whose every failure is said once already, in one of two
 * ways:
 * - its hook toasts it with `toastMutationError` in its own `onError` (D-148
 *   point 5, T-3.4.1.17);
 * - every caller shows it on the page, where the reader acted, through
 *   `inlineErrorMessage`, which says nothing for a 401 (T-3.4.1.18). Such a
 *   hook sets this and no toast. A hook whose callers differ takes an option
 *   (D-153 point 2), and only the callers with a line of their own pass it.
 */
export const ERRORS_SHOWN_HERE = { errorsShownHere: true } as const;

/**
 * The one toast for a failed mutation whose hook answers its own failures: the
 * server's words when the answer carries any, else `fallback`, which beats the
 * global toast's "Network Error" or "Request failed with status code 500".
 * Nothing for a 401: the session-expiry path owns it, and the reader may be on
 * the sign-in page already (T-5.4.22). Call it from the hook's `onError`, never
 * from a per-call one, which TanStack drops once the component has gone and
 * runs for the last `mutate` only.
 */
export function toastMutationError(error: unknown, fallback: string): void {
  if (isSessionEnded(error)) return;
  const data = (error as { response?: { data?: unknown } } | null | undefined)?.response?.data;
  useJobStore.getState().pushToast('error', detailFromErrorBody(data) ?? apiErrorMessage(error, fallback));
}
