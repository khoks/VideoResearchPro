import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';
import { useJobStore } from '../stores/jobStore';
import { globalErrorToastMessage } from '../utils/apiError';

function toastError(error: unknown): void {
  // Null for errors the page already shows where the action started.
  const message = globalErrorToastMessage(error);
  if (message) useJobStore.getState().pushToast('error', message);
}

/**
 * The app's one client, with the global error toast.
 *
 * `meta: { errorsShownHere: true }` on a mutation says its caller answers every
 * failure, so the toast stays out of the way: a per-call `onError` is invisible
 * from here, and both would otherwise speak (T-3.4.1.15).
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
