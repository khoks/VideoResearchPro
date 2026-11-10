/**
 * T-3.4.1.27: a poll says a run of failures once, under the app's own query
 * client (`createQueryClient`), with retries as the app has them.
 *
 * A poll whose failure no line shows used to toast on every interval. Now the
 * first failure the toast says starts a streak; later failures of the same kind
 * stay quiet until a fetch succeeds, or until nobody reads the query any more.
 * A different kind (no answer, then a status) is said once more. A 401 says
 * nothing, and a query that does not poll says every failure, as before.
 *
 * The first block pins what TanStack does, rather than what we remember: by the
 * time the cache's `onError` runs the failure is already written to the query's
 * state, a fetch with no data clears the error before it starts, and
 * `setQueryData` moves `dataUpdateCount` without calling the cache's
 * `onSuccess`. That is why the streak is the cache's own record.
 *
 * Mutation checks, run on 2026-11-10: dropping the streak check from the cache's
 * `onError` fails "fails three times" (four toasts), "each kind", "a progress
 * write", "the last reader" and "a failure a line said"; dropping the
 * `onSuccess` that ends a streak fails "fails three times" (one toast); ending
 * it on a moved `dataUpdateCount` instead fails "a progress write"; dropping the
 * `observerRemoved` listener fails "the last reader"; holding every query to a
 * streak (no `queryIsPolling`) fails "a query that does not poll" and "a
 * disabled reader with an interval"; one flag per streak in place of a set of
 * kinds fails "each kind"; counting a failure a line said as said fails "a
 * failure a line said"; and `queryIsPolling` without its `enabled` check fails
 * both "disabled reader" rows.
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryCache, QueryClient, QueryClientProvider, QueryObserver, useQuery } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ERRORS_SHOWN_HERE,
  createQueryClient,
  pollFailureKind,
  queryIsPolling,
} from '../queryClient';
import { SERVER_WORDS, clearToasts, failures, flush, recordToasts, type FailureKind } from './failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// What TanStack Query v5 does before the cache's `onError` runs
// ---------------------------------------------------------------------------

describe('TanStack, as the streak finds it', () => {
  it('writes the failure to the query before the cache’s onError runs', async () => {
    const seen: Array<{ status: string; same: boolean; errors: number; fetching: string }> = [];
    const client = new QueryClient({
      queryCache: new QueryCache({
        onError: (error, query) =>
          seen.push({
            status: query.state.status,
            same: query.state.error === error,
            errors: query.state.errorUpdateCount,
            fetching: query.state.fetchStatus,
          }),
      }),
    });
    const fail = () => Promise.reject(failures.noWords());
    await client.fetchQuery({ queryKey: ['k'], queryFn: fail, retry: false }).catch(() => undefined);
    await client.fetchQuery({ queryKey: ['k'], queryFn: fail, retry: false, staleTime: 0 }).catch(() => undefined);
    // So "was the query in error before this failure?" cannot be read here:
    // it always is by now.
    expect(seen).toEqual([
      { status: 'error', same: true, errors: 1, fetching: 'idle' },
      { status: 'error', same: true, errors: 2, fetching: 'idle' },
    ]);
  });

  it('clears the error of a query with no data when its next fetch starts', async () => {
    const client = new QueryClient();
    await client.fetchQuery({ queryKey: ['k'], queryFn: () => Promise.reject(failures.noWords()), retry: false }).catch(() => undefined);
    const query = client.getQueryCache().find({ queryKey: ['k'] })!;
    expect(query.state.status).toBe('error');
    void client.fetchQuery({ queryKey: ['k'], queryFn: () => new Promise<number>(() => undefined), retry: false, staleTime: 0 });
    expect(query.state).toMatchObject({ status: 'pending', error: null, fetchStatus: 'fetching' });
  });

  it('moves dataUpdateCount on setQueryData without calling the cache’s onSuccess', async () => {
    const onSuccess = vi.fn();
    const client = new QueryClient({ queryCache: new QueryCache({ onSuccess }) });
    await client.fetchQuery({ queryKey: ['k'], queryFn: async () => 1 });
    expect(onSuccess).toHaveBeenCalledTimes(1);
    const query = client.getQueryCache().find({ queryKey: ['k'] })!;
    const before = query.state.dataUpdateCount;
    client.setQueryData(['k'], 2);
    expect(query.state.dataUpdateCount).toBe(before + 1);
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// The pieces
// ---------------------------------------------------------------------------

describe('queryIsPolling', () => {
  const never = () => new Promise<number>(() => undefined);
  const queryOf = (client: QueryClient) => client.getQueryCache().find({ queryKey: ['k'] })!;

  it('is true while an enabled, mounted reader has an interval', () => {
    const client = new QueryClient();
    const stop = new QueryObserver(client, { queryKey: ['k'], queryFn: never, refetchInterval: 5000 }).subscribe(() => undefined);
    expect(queryIsPolling(queryOf(client))).toBe(true);
    stop();
    expect(queryIsPolling(queryOf(client))).toBe(false);
  });

  it('works an interval out from the query, as TanStack does', () => {
    const client = new QueryClient();
    const stop = new QueryObserver(client, {
      queryKey: ['k'],
      queryFn: never,
      refetchInterval: (q) => (q.state.data === 1 ? 4000 : false),
    }).subscribe(() => undefined);
    expect(queryIsPolling(queryOf(client))).toBe(false);
    client.setQueryData(['k'], 1);
    expect(queryIsPolling(queryOf(client))).toBe(true);
    stop();
  });

  it('a disabled reader, or one with no interval or a zero one, does not poll', () => {
    const client = new QueryClient();
    const stops = [
      new QueryObserver(client, { queryKey: ['k'], queryFn: never, refetchInterval: 5000, enabled: false }).subscribe(() => undefined),
      new QueryObserver(client, { queryKey: ['k'], queryFn: never }).subscribe(() => undefined),
      new QueryObserver(client, { queryKey: ['k'], queryFn: never, refetchInterval: 0 }).subscribe(() => undefined),
    ];
    expect(queryIsPolling(queryOf(client))).toBe(false);
    stops.forEach((stop) => stop());
  });
});

describe('pollFailureKind', () => {
  it('is the status the server answered with, or no answer', () => {
    expect(pollFailureKind(failures.words())).toBe('status 409');
    expect(pollFailureKind(failures.noWords())).toBe('status 500');
    expect(pollFailureKind(failures.noAnswer())).toBe('no answer');
    expect(pollFailureKind(new Error('boom'))).toBe('other');
  });
});

// ---------------------------------------------------------------------------
// A poll under the app's client
// ---------------------------------------------------------------------------

/** What the next fetch of the poll gets: a number, or a failure of a kind. */
let next: 'ok' | FailureKind = 'ok';
let served = 0;
const answer = vi.fn(() => (next === 'ok' ? Promise.resolve(++served) : Promise.reject(failures[next]())));

function Poll({ every = 5000, line = false }: { every?: number | false; line?: boolean }) {
  const q = useQuery({
    queryKey: ['poll'],
    queryFn: answer,
    refetchInterval: every,
    meta: line ? ERRORS_SHOWN_HERE : undefined,
  });
  return <p>{line && q.isError ? 'The line says it.' : String(q.data ?? '')}</p>;
}

let host: HTMLDivElement;
let root: Root;
let client: QueryClient;
let toasts: ReturnType<typeof recordToasts>;

function mount(node: ReactNode) {
  act(() => root.render(<QueryClientProvider client={client}>{node}</QueryClientProvider>));
}

/** Moves the clock on by `ms`, then lets what that started settle. */
async function advance(ms: number) {
  await flush();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
  await flush();
}

/** The next poll and its one retry. TanStack counts a poll's five seconds from
 * when the last fetch settled, so a failing poll comes round every six. */
const poll = () => advance(6000);

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  client = createQueryClient();
  next = 'ok';
  served = 0;
  answer.mockClear();
  clearToasts();
  toasts = recordToasts();
});

afterEach(() => {
  toasts.stop();
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

describe('a poll under the app’s query client', () => {
  it('fails three times, succeeds, then fails: two toasts', async () => {
    next = 'noWords';
    mount(<Poll />);
    await advance(1500); // the first read, and its one retry a second later
    expect(toasts.messages).toEqual(['Request failed with status code 500']);
    await poll();
    await poll();
    expect(answer.mock.calls.length).toBe(6); // three polls, each tried twice
    expect(toasts.messages).toHaveLength(1);
    next = 'ok';
    await poll();
    expect(host.textContent).toBe('1');
    expect(toasts.messages).toHaveLength(1);
    next = 'noWords';
    await poll();
    expect(toasts.messages).toEqual(['Request failed with status code 500', 'Request failed with status code 500']);
  });

  it('says nothing of a 401, however often it comes', async () => {
    next = 'sessionEnded';
    mount(<Poll />);
    await advance(1500);
    await poll();
    await poll();
    expect(toasts.messages).toEqual([]);
  });

  it('says each kind of failure once in a streak, a flapping poll included', async () => {
    next = 'noAnswer';
    mount(<Poll />);
    await advance(1500);
    await poll();
    expect(toasts.messages).toEqual(['Network Error']);
    next = 'words';
    await poll();
    expect(toasts.messages).toEqual(['Network Error', SERVER_WORDS]);
    next = 'noAnswer';
    await poll();
    next = 'words';
    await poll();
    expect(toasts.messages).toEqual(['Network Error', SERVER_WORDS]);
  });

  it('keeps the streak through a progress write into the cache, which is no fetch', async () => {
    next = 'noWords';
    mount(<Poll />);
    await advance(1500);
    expect(toasts.messages).toHaveLength(1);
    act(() => {
      client.setQueryData(['poll'], 41);
    });
    await poll();
    expect(toasts.messages).toHaveLength(1);
  });

  it('ends the streak when the last reader unmounts, so a return says it again', async () => {
    next = 'noWords';
    mount(<Poll />);
    await advance(1500);
    await poll();
    expect(toasts.messages).toHaveLength(1);
    mount(<p>elsewhere</p>);
    await flush();
    mount(<Poll />);
    await advance(1500);
    expect(toasts.messages).toHaveLength(2);
    await poll();
    expect(toasts.messages).toHaveLength(2);
  });

  it('does not count a failure a line said: when the line goes, the toast says the next one', async () => {
    next = 'noWords';
    // Keyed, so the silent reader stays mounted when the line's reader goes,
    // and the streak is not ended by its last reader leaving.
    mount(
      <>
        <Poll key="line" line />
        <Poll key="silent" />
      </>,
    );
    await advance(1500);
    expect(host.textContent).toContain('The line says it.');
    expect(toasts.messages).toEqual([]);
    mount(
      <>
        <Poll key="silent" />
      </>,
    );
    await poll();
    expect(toasts.messages).toHaveLength(1);
    await poll();
    expect(toasts.messages).toHaveLength(1);
  });

  it('a query that does not poll says every failure, as before', async () => {
    next = 'noWords';
    mount(<Poll every={false} />);
    await advance(1500);
    expect(toasts.messages).toHaveLength(1);
    act(() => {
      void client.refetchQueries({ queryKey: ['poll'] });
    });
    await advance(1500);
    expect(toasts.messages).toHaveLength(2);
  });

  it('a disabled reader with an interval does not make a poll', async () => {
    function Gated() {
      useQuery({ queryKey: ['poll'], queryFn: answer, refetchInterval: 5000, enabled: false });
      return null;
    }
    next = 'noWords';
    mount(
      <>
        <Gated />
        <Poll every={false} />
      </>,
    );
    await advance(1500);
    act(() => {
      void client.refetchQueries({ queryKey: ['poll'] });
    });
    await advance(1500);
    expect(toasts.messages).toHaveLength(2);
  });
});
