import { MutationCache, QueryCache, QueryClient, type Query } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { useJobStore } from '../stores/jobStore';
import { apiErrorMessage, globalErrorToastMessage, isSessionEnded } from '../utils/apiError';
import { detailFromErrorBody } from '../utils/ingestResults';

function toastError(error: unknown): void {
  // Null for errors the page already shows where the action started.
  const message = globalErrorToastMessage(error);
  if (message) useJobStore.getState().pushToast('error', message);
}

type AnyQuery = Query<unknown, unknown, unknown, readonly unknown[]>;

/**
 * Whether `query` is a poll now: an enabled, mounted reader asks for it again
 * every so many milliseconds (`refetchInterval`, a number or worked out from the
 * query, as TanStack works it out). A reader with no interval, or one whose
 * interval says `false` now (a capture that has finished), does not poll.
 */
export function queryIsPolling<TError>(query: Query<unknown, TError, unknown, readonly unknown[]>): boolean {
  return query.observers.some((observer) => {
    const { enabled, refetchInterval } = observer.options;
    if ((typeof enabled === 'function' ? enabled(query) : enabled) === false) return false;
    const every = typeof refetchInterval === 'function' ? refetchInterval(query) : refetchInterval;
    return typeof every === 'number' && every > 0 && Number.isFinite(every);
  });
}

/**
 * What kind of failure `error` is, for a poll's streak: the status the server
 * answered with, or no answer at all (a dropped connection, a timeout). On the
 * polled routes the words under one status are one fixed sentence for an
 * account (a 404's not found, a plan's 403, the rate limiter's 429), and words
 * with a count or a time in them must not toast every interval.
 */
export function pollFailureKind(error: unknown): string {
  if (isAxiosError(error)) return error.response ? `status ${error.response.status}` : 'no answer';
  return 'other';
}

/**
 * One toast per run of failures of a poll (T-3.4.1.27). A poll that keeps
 * failing used to toast on every interval: the health check every minute, a
 * run's page every five seconds behind the run already on screen.
 *
 * A streak starts with the first failure the toast says, and lasts until a
 * fetch of the query succeeds (the cache's `onSuccess`, which `setQueryData`
 * never calls) or nobody reads the query any more (its last reader unmounts),
 * so coming back to a page whose poll still fails says so again, as a first
 * read would. Within a streak each kind of failure (`pollFailureKind`) is said
 * once: no answer, then the server's words, says both, and a poll flapping
 * between the two says each once, not every interval.
 *
 * The query's own state cannot mark a streak: TanStack writes the failure
 * before the cache's `onError` runs (status `'error'`, the new error, one more
 * `errorUpdateCount`), a fetch with no data clears the error before it starts,
 * and `dataUpdateCount` moves on every `setQueryData` too. So the cache keeps
 * the record itself.
 *
 * Only a poll is held to its streak. Any other query is asked again by the
 * reader (a page visit, a focus, a retry), and says every failure, as before. A
 * failure a line on the page says is not counted as said: when that line has
 * gone, the toast says the next one.
 */
class PollFailureStreaks {
  private said = new WeakMap<AnyQuery, Set<string>>();

  /** Whether the toast should say this failure of `query`: always for a query
   * that does not poll, and for a poll, the first of its kind in this streak. */
  firstSaying(query: AnyQuery, error: unknown): boolean {
    const kinds = this.said.get(query) ?? new Set<string>();
    const kind = pollFailureKind(error);
    if (kinds.has(kind) && queryIsPolling(query)) return false;
    this.said.set(query, kinds.add(kind));
    return true;
  }

  end(query: AnyQuery): void {
    this.said.delete(query);
  }
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
 *
 * A poll says a run of failures once (T-3.4.1.27): see `PollFailureStreaks`.
 */
export function createQueryClient(): QueryClient {
  const streaks = new PollFailureStreaks();
  const queryCache = new QueryCache({
    onError: (error, query) => {
      if (queryFailureShownOnPage(query, error)) return;
      // Null for a 401 (the session ends in one place, T-5.4.22) and for the
      // refusals their pages say where they were started.
      const message = globalErrorToastMessage(error);
      if (message && streaks.firstSaying(query, error)) useJobStore.getState().pushToast('error', message);
    },
    // Called for a fetch that succeeded, and never for `setQueryData`, so a
    // run's progress written into the cache over the socket ends no streak.
    onSuccess: (_data, query) => streaks.end(query),
  });
  queryCache.subscribe((event) => {
    if (event.type === 'observerRemoved' && event.query.getObserversCount() === 0) streaks.end(event.query);
  });
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 1, staleTime: 5000 },
    },
    queryCache,
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
 * `ERRORS_SHOWN_HERE`, `LOAD_ERRORS_SHOWN_HERE` while the query has no data
 * to keep on screen, or a `ShownOnPage` that says so of this failure. Each
 * reader (a `useQuery` call) carries its own `meta`, read here when the failure
 * lands, so a key read by a page with a line and by a component without one
 * still toasts wherever the silent one is mounted alone, and a reader that has
 * unmounted says nothing. `query.meta` would not do: it is whichever reader
 * rendered last. `error` is the failure landing; TanStack has already written it
 * to `query.state.error` when the cache's `onError` runs.
 */
export function queryFailureShownOnPage<TError>(
  query: Query<unknown, TError, unknown, readonly unknown[]>,
  error: unknown = query.state.error,
): boolean {
  return query.observers.some((observer) => {
    const { enabled, meta } = observer.options;
    if ((typeof enabled === 'function' ? enabled(query) : enabled) === false) return false;
    const shown = meta?.errorsShownHere;
    if (typeof shown === 'function') return (shown as ShownOnPage)(error, query.state.data !== undefined);
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
 * A reader that works out, for each failure as it lands, whether its page says
 * it: handed the failure and whether the query still has data on screen. The
 * Echo page's readiness says a first load's failure on its line and a 403 on
 * the upgrade card, whatever readiness it still shows (T-3.4.1.27).
 */
export type ShownOnPage = (error: unknown, hasData: boolean) => boolean;

/**
 * How a reader says a query's failure on the page: always (`true`), only while
 * the query has no data (`'load'`), by a rule of its own (`ShownOnPage`), or
 * not at all.
 */
export type InlineErrors = boolean | 'load' | ShownOnPage;

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
export function queryErrorsMeta(inlineErrors: InlineErrors | undefined): { errorsShownHere: true | 'load' | ShownOnPage } | undefined {
  if (inlineErrors === 'load') return LOAD_ERRORS_SHOWN_HERE;
  if (typeof inlineErrors === 'function') return { errorsShownHere: inlineErrors };
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
