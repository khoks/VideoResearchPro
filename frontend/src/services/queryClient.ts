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
 * `meta: { errorsShownHere: true }` on a mutation says it answers every failure
 * itself, so the toast stays out of the way: both would otherwise speak
 * (T-3.4.1.15). That answer goes in the hook's own `onError`. A per-call one on
 * `mutate` is dropped once its component has unmounted, and nothing would be said.
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
 * `meta` for a mutation whose hook says every failure itself with
 * `toastMutationError` in its own `onError` (D-148 point 5, T-3.4.1.17).
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
