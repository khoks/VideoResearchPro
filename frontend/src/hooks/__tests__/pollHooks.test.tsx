/**
 * T-3.4.1.27: every hook that polls (has a `refetchInterval`), under the app's
 * own query client, with the real hook and API module and only the HTTP layer
 * replaced.
 *
 * Each is read by a reader with no line, as the silent readers in the app are
 * (the studio's create dialog for `useJobs`, the channel page for `useJob`, the
 * bell, the frames panel, the importer, the voice test, the layout's health
 * check). A poll that answers, fails three times, answers again and fails gives
 * two toasts: the run of failures is said once, and again after it recovered. A
 * query that did not poll would give four. `useSavedSearches` gives none: its
 * one caller says every failure on its own line (`ERRORS_SHOWN_HERE`), so the
 * toast stands aside each time and a run of failures never reaches it.
 *
 * The guard (`services/__tests__/oneToastPerFailure.test.ts`, "a poll says a run
 * of failures once") lists every `refetchInterval` in the app beside the test
 * that checks it, this file for the hooks, and fails on one not listed.
 *
 * Mutation check, run on 2026-11-10: the query client without its streak check
 * fails every row but `useSavedSearches` with four toasts.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryClient } from '../../services/queryClient';
import { clearToasts, failures, flush, recordToasts } from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** What each polled route answers when it answers: data that keeps the poll
 * going, where its interval is worked out from the data. */
const ANSWERS: Record<string, unknown> = {
  '/jobs': [],
  '/jobs/job-1': { id: 'job-1', status: 'extracting' },
  '/notifications': { items: [], unread: 0 },
  '/saved-searches': { items: [{ id: 's1', enabled: true, last_run_at: null }] },
  '/videos/v1/frames': { in_progress: true, frames: [] },
  '/echo/imports': { items: [{ id: 'i1', status: 'embedding' }] },
  '/echo/voice-test/t1': { id: 't1', status: 'generating' },
  '/health': { llm: { status: 'ok' } },
};

let failing = false;
const get = vi.fn((url: string) => {
  if (!(url in ANSWERS)) return Promise.reject(new Error(`unexpected GET ${url}`));
  return failing ? Promise.reject(failures.noWords()) : Promise.resolve({ data: ANSWERS[url] });
});
vi.mock('../../services/api', () => ({ default: { get: (url: string) => get(url) } }));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));
vi.mock('../useTierCapabilities', () => ({ useTierCapabilities: () => ({ has: () => true, tier: 'studio', isLoading: false }) }));

import { useJob, useJobs } from '../useJobs';
import { useNotifications } from '../useNotifications';
import { useSavedSearches } from '../useSavedSearches';
import { useVideoFrames } from '../useVideoFrames';
import { useImports, useVoiceTestPoll } from '../useEcho';
import { useSystemStatus } from '../useSystemStatus';

/** Each polling hook, how a silent reader calls it, and the toasts its run gives. */
const POLL_HOOKS: Array<[name: string, read: () => unknown, toasts: number]> = [
  ['useJobs', () => useJobs(), 2],
  ['useJob', () => useJob('job-1'), 2],
  ['useNotifications', () => useNotifications(), 2],
  ['useSavedSearches', () => useSavedSearches(), 0],
  ['useVideoFrames', () => useVideoFrames('v1'), 2],
  ['useImports', () => useImports(), 2],
  ['useVoiceTestPoll', () => useVoiceTestPoll('t1'), 2],
  ['useSystemStatus', () => useSystemStatus(), 2],
];

let host: HTMLDivElement;
let root: Root;
let toasts: ReturnType<typeof recordToasts>;

/** Moves the clock on in half-second steps until the route has been asked
 * `calls` times in all, then lets the answer settle. */
async function untilCalls(calls: number) {
  for (let i = 0; i < 300 && get.mock.calls.length < calls; i++) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
  }
  await flush();
  expect(get.mock.calls.length).toBe(calls);
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  failing = false;
  get.mockClear();
  clearToasts();
  toasts = recordToasts();
});

afterEach(() => {
  toasts.stop();
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

describe('every hook that polls', () => {
  it.each(POLL_HOOKS)('%s says a run of failed polls once, and again after it recovers', async (_name, read, expected) => {
    function Reader() {
      read();
      return null;
    }
    act(() =>
      root.render(
        <QueryClientProvider client={createQueryClient()}>
          <Reader />
        </QueryClientProvider>,
      ),
    );
    await untilCalls(1); // the first read answers
    failing = true;
    await untilCalls(3); // a poll and its one retry
    await untilCalls(5);
    await untilCalls(7);
    failing = false;
    await untilCalls(8); // it answers again
    failing = true;
    await untilCalls(10);
    expect(toasts.messages).toHaveLength(expected);
  });
});
