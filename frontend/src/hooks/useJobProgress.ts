import { useEffect } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { wsClient } from '../services/wsClient';
import type { Job } from '../types/job';
import type { WSProgressMessage } from '../types/ws';

/** A run in one of these has ended, and the server never moves it on: no task
 * writes over a stopped row (T-5.2.20, T-5.2.23), and no route restarts one. */
const ENDED_STATUSES: ReadonlySet<string> = new Set(['completed', 'failed', 'cancelled']);

export function isRunEnded(status: string | null | undefined): boolean {
  return status != null && ENDED_STATUSES.has(status);
}

type RunFields = Pick<Job, 'status' | 'progress_pct' | 'progress_message' | 'error_message'>;

/**
 * Fold one socket event into a cached run, or `undefined` when the cache holds
 * the run as ended, which React Query reads as "leave it" (T-5.2.28).
 *
 * A worker writes a progress line to the row, commits, then publishes it, so a
 * cancel that commits in between is followed by one event that shows the run
 * going again. Dropping events for an ended run closes that gap, and hides
 * nothing: an ended status reaches the cache only on the server's word, from a
 * fetch, the cancel's answer, or an event published once the write that ended
 * the row has committed (each end a run writes, and the cancel route's, T-5.2.30).
 * The page writes no status of its own. A refetch is not an event: it replaces
 * the cache whatever the cache held, in either direction.
 */
export function applyRunEvent<T extends RunFields>(run: T, msg: WSProgressMessage): T | undefined {
  if (isRunEnded(run.status)) return undefined;
  return {
    ...run,
    status: (msg.new_status ?? msg.status ?? run.status) as T['status'],
    progress_pct: msg.progress_pct ?? run.progress_pct,
    progress_message: msg.message ?? run.progress_message,
    error_message: msg.error ?? run.error_message,
  };
}

/**
 * The event in every cached jobs list (each filter and page is its own query),
 * row by row. Until T-5.2.30 this wrote to `['jobs', undefined]`, a key no list
 * has (`useJobs` keys on status, limit and offset), so a list learned of every
 * change only at its 10-second refetch. Returns whether a row ended.
 */
function applyToLists(queryClient: QueryClient, jobId: string, msg: WSProgressMessage): boolean {
  let ended = false;
  queryClient.setQueriesData<Job[]>({ queryKey: ['jobs'] }, (old) => {
    if (!Array.isArray(old)) return undefined;
    let changed = false;
    const next = old.map((row) => {
      if (row.id !== jobId) return row;
      const applied = applyRunEvent(row, msg);
      if (!applied) return row;
      changed = true;
      ended ||= isRunEnded(applied.status);
      return applied;
    });
    return changed ? next : undefined;
  });
  return ended;
}

/** An event that ends the run: a status change to an end, or a failure, which
 * `_handle_failure` and the run's own checks publish once the row says
 * `failed` (T-5.2.35; until then a `job_error` refetched neither the run nor
 * the lists). */
function endsTheRun(msg: WSProgressMessage): boolean {
  return msg.type === 'job_error' || (msg.type === 'job_status_change' && isRunEnded(msg.new_status));
}

/** A run's videos change as it reaches these: saved for the approval list, or
 * settled by its end (each video's transcript status). */
function videosSettleAt(status: string | null | undefined): boolean {
  return status === 'awaiting_approval' || isRunEnded(status);
}

export function useJobProgress(jobId: string | null) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!jobId) return;

    const unsubscribe = wsClient.subscribe(jobId, (msg: WSProgressMessage) => {
      // Read before the event is applied: a late event for a run this page
      // already holds as ended changes nothing and refreshes nothing.
      const heldEnded = isRunEnded(queryClient.getQueryData<Job>(['job', jobId])?.status);

      queryClient.setQueryData<Job>(['job', jobId], (old) => (old ? applyRunEvent(old, msg) : undefined));
      applyToLists(queryClient, jobId, msg);
      if (heldEnded) return;

      // An event that ends the run refetches it and the lists, for what its
      // end changes beside the status (its report, its finish time, the
      // row's own words for a failure, which a `job_error` can put shorter).
      // A refetch also cancels one already in flight, which read the row
      // before the end and would show the run going again (T-5.2.33). The
      // videos are not fetched here: they follow the status the event set.
      if (endsTheRun(msg)) {
        queryClient.invalidateQueries({ queryKey: ['jobs'] });
        queryClient.invalidateQueries({ queryKey: ['job', jobId] });
      }
    });

    return unsubscribe;
  }, [jobId, queryClient]);

  useEffect(() => {
    if (!jobId) return;

    // The videos follow the run's cached status, whatever moved it: an event,
    // a poll, or this tab's cancel answer. Driven by events, they missed every
    // end a poll read first, whose event the guard above then drops, and every
    // event the socket lost. The first status the cache receives is no move:
    // the page fetches its videos as it opens.
    let held = queryClient.getQueryData<Job>(['job', jobId])?.status;
    return queryClient.getQueryCache().subscribe((event) => {
      const [scope, id] = event.query.queryKey;
      if (scope !== 'job' || id !== jobId) return;
      if (event.type === 'removed') {
        held = undefined;
        return;
      }
      if (event.type !== 'updated') return;
      const status = (event.query.state.data as Job | undefined)?.status;
      if (status === held) return;
      const moved = held != null;
      held = status;
      if (moved && videosSettleAt(status)) {
        queryClient.invalidateQueries({ queryKey: ['jobVideos', jobId] });
      }
    });
  }, [jobId, queryClient]);
}

export function useAllJobsProgress(jobIds: string[]) {
  const queryClient = useQueryClient();

  useEffect(() => {
    const unsubs = jobIds.map((jobId) =>
      wsClient.subscribe(jobId, (msg: WSProgressMessage) => {
        // A run that ends here is refetched, for what its end changes beside
        // the status (its report, its finish time).
        if (applyToLists(queryClient, jobId, msg)) {
          queryClient.invalidateQueries({ queryKey: ['jobs'] });
        }
      })
    );
    return () => unsubs.forEach((u) => u());
  }, [jobIds.join(','), queryClient]);
}
