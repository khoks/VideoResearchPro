import { MutationCache, QueryCache, QueryClient, type Query } from '@tanstack/react-query';
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
 *
 * A query follows the same rule (T-3.4.1.26). Its toast comes once its retry has
 * failed too, as before, unless a reader of it on the page now says the failure
 * there: see `queryFailureShownOnPage`.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 1, staleTime: 5000 },
    },
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (!queryFailureShownOnPage(query)) toastError(error);
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (!mutation.meta?.errorsShownHere) toastError(error);
      },
    }),
  });
}

/**
 * Whether a reader of `query` that is mounted now says its failure on the page,
 * so the toast stands aside: an enabled reader whose `meta` is
 * `ERRORS_SHOWN_HERE`, or `LOAD_ERRORS_SHOWN_HERE` while the query has no data
 * to keep on screen. Each reader (a `useQuery` call) carries its own `meta`,
 * read here when the failure lands, so a key read by a page with a line and by a
 * component without one still toasts wherever the silent one is mounted alone,
 * and a reader that has unmounted says nothing. `query.meta` would not do: it is
 * whichever reader rendered last.
 */
export function queryFailureShownOnPage<TError>(query: Query<unknown, TError, unknown, readonly unknown[]>): boolean {
  return query.observers.some((observer) => {
    const { enabled, meta } = observer.options;
    if ((typeof enabled === 'function' ? enabled(query) : enabled) === false) return false;
    const shown = meta?.errorsShownHere;
    return shown === true || (shown === 'load' && query.state.data === undefined);
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
 *
 * On a query it says that this reader shows every failure of the query on the
 * page, through `inlineErrorMessage` (T-3.4.1.26), a failed refresh behind data
 * still on screen included.
 */
export const ERRORS_SHOWN_HERE = { errorsShownHere: true } as const;

/**
 * `meta` for a query reader whose line shows only while the query has no data:
 * a section that keeps what it last read on screen, and shows its line only in
 * place of a first load. A refresh that fails behind that data shows no line,
 * so its toast stays (T-3.4.1.26).
 */
export const LOAD_ERRORS_SHOWN_HERE = { errorsShownHere: 'load' } as const;

/**
 * How a reader says a query's failure on the page: always (`true`), only while
 * the query has no data (`'load'`), or not at all.
 */
export type InlineErrors = boolean | 'load';

/** The option a query hook takes when its callers say its failure differently. */
export interface QueryLineOptions {
  inlineErrors?: InlineErrors;
}

/**
 * The `meta` a query hook sets from its caller's `inlineErrors`. A hook whose
 * callers differ (one shows a line and another does not, or one shows it only
 * on one tab or one step) takes the option, as the ask hooks do for mutations
 * (D-153 point 2); a hook every caller answers the same way sets its `meta`.
 */
export function queryErrorsMeta(inlineErrors: InlineErrors | undefined) {
  if (inlineErrors === 'load') return LOAD_ERRORS_SHOWN_HERE;
  return inlineErrors ? ERRORS_SHOWN_HERE : undefined;
}

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
