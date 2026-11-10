/**
 * Run events on an open page (T-5.2.28, T-5.2.30).
 *
 * T-5.2.28: a worker writes a progress line to the row, commits, then publishes
 * it, so a cancel that commits in between is followed by one event that showed
 * the cancelled run going again until the 5-second refetch. `useJobProgress`
 * now drops every event for a run its cache holds as ended (completed, failed,
 * cancelled). A refetch is not an event, so it still sets the cache, either way.
 *
 * T-5.2.30: the cancel route publishes a `job_status_change` to `cancelled`, so
 * another tab hears of a cancel at once. It reaches a tab whose cached run is
 * active, on the run's page and in the jobs list, which until now wrote to a
 * key no list has. The bell's notifications ride the same socket and are left
 * to their own listener.
 *
 * The run's videos follow its cached status, not its events: they are fetched
 * again when the status moves to `awaiting_approval` or to an end, whatever
 * moved it. With the guard, a poll that reads `completed` a moment before its
 * event left the event dropped and the videos as they were before the end.
 *
 * The real `wsClient` runs over a fake WebSocket, so events are routed by job
 * id exactly as in the app; `jobsApi` is faked.
 *
 * Mutation checks, run by hand on 2026-11-10: taking the ended-status guard out
 * of `applyRunEvent` fails five cases, the two late-event ones, the cancel then
 * progress one, the refetch to an end and the list's (the run reads a running
 * status again, and a late `completed` refetches); writing the list back to
 * `['jobs', undefined]` fails the three cases that read a list (the row stays as
 * it was); and reading the ended state after the event is applied, rather than
 * before, fails the cancel case (the event that ends the run refetches nothing).
 * For the videos, run by hand on 2026-11-09: taking the status watch out fails
 * the poll, event, lost-approval and own-cancel cases (the videos are never
 * fetched again); keeping the event's own videos refetch beside it fails the
 * event case (fetched twice); and counting the first status the cache receives
 * as a move fails the opening case (a page opened on an ended run fetches its
 * videos twice).
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Job } from '../../types/job';
import type { WSNotificationMessage, WSProgressMessage } from '../../types/ws';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** The socket under the real client: opened, fed and read by the test. */
class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(code = 1000) {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code });
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
}

vi.stubGlobal('WebSocket', FakeWebSocket);

const get = vi.fn<(id: string) => Promise<Job>>();
const list = vi.fn<() => Promise<Job[]>>();
const getVideos = vi.fn<(id: string) => Promise<unknown[]>>();
vi.mock('../../services/jobsApi', () => ({
  jobsApi: { get: (id: string) => get(id), list: () => list(), getVideos: (id: string) => getVideos(id) },
}));

import { wsClient } from '../../services/wsClient';
import { useJob, useJobs, useJobVideos } from '../useJobs';
import { useAllJobsProgress, useJobProgress } from '../useJobProgress';

const CANCELLED_WORDS = 'Job cancelled by user';
/** The key `useJobs` gives the jobs page's first page, no filter. */
const LIST_KEY = ['jobs', null, 20, 0];

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;

function run(id: string, status: Job['status'], progress_message = 'Video 1/5'): Job {
  return { id, status, progress_pct: 30, progress_message, error_message: null } as Job;
}

/** Never answers: what the page shows is then the event's doing, not a refetch's. */
const pending = () => new Promise<never>(() => {});

function RunPage() {
  const { data } = useJob('j1');
  useJobProgress('j1');
  return <span data-status={data?.status ?? ''} data-message={data?.progress_message ?? ''} />;
}

/** The run's page as `JobDetailPage` reads it: the run, its videos, its events. */
function RunWithVideos() {
  useJobVideos('j1');
  return <RunPage />;
}

function JobsPage({ ids }: { ids: string[] }) {
  useJobs({ limit: 20, offset: 0 });
  useAllJobsProgress(ids);
  return null;
}

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function render(node: ReactNode) {
  act(() => root.render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>));
  await flush();
  const socket = FakeWebSocket.instances.at(-1)!;
  if (socket.readyState !== FakeWebSocket.OPEN) act(() => socket.open());
}

async function send(msg: Partial<WSProgressMessage> | WSNotificationMessage) {
  const socket = FakeWebSocket.instances.at(-1)!;
  act(() => socket.onmessage?.({ data: JSON.stringify({ timestamp: '2026-11-10T00:00:00Z', ...msg }) }));
  await flush();
}

const progress = (job_id: string, status: string, message: string): Partial<WSProgressMessage> => ({
  type: 'job_progress', job_id, status, progress_pct: 60, message, data: {},
});
const statusChange = (job_id: string, old_status: string, new_status: string, message: string) => ({
  type: 'job_status_change' as const, job_id, old_status, new_status, message,
});

function shown() {
  const span = host.querySelector('span') as HTMLSpanElement;
  return { status: span.dataset.status, message: span.dataset.message };
}

function listRow(id: string): Job | undefined {
  return qc.getQueryData<Job[]>(LIST_KEY)?.find((j) => j.id === id);
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 5000 } } });
  get.mockReset();
  list.mockReset().mockImplementation(pending);
  getVideos.mockReset().mockResolvedValue([]);
  FakeWebSocket.instances = [];
});

afterEach(() => {
  act(() => root.unmount());
  wsClient.disconnect();
  qc.clear();
  host.remove();
});

describe('useJobProgress: a run the page holds as ended (T-5.2.28)', () => {
  it('drops late progress for a completed run and refetches nothing', async () => {
    get.mockResolvedValue(run('j1', 'completed', 'Job completed successfully!'));
    await render(<RunPage />);
    expect(shown()).toEqual({ status: 'completed', message: 'Job completed successfully!' });

    await send(progress('j1', 'building_rag', 'Indexed 40 new chunks'));
    await send(statusChange('j1', 'generating_report', 'completed', 'Job completed successfully!'));

    expect(shown()).toEqual({ status: 'completed', message: 'Job completed successfully!' });
    expect(get).toHaveBeenCalledTimes(1);
  });

  it('drops a late status change for a cancelled run', async () => {
    get.mockResolvedValue(run('j1', 'cancelled', CANCELLED_WORDS));
    await render(<RunPage />);

    await send(statusChange('j1', 'extracting', 'building_rag', 'Building knowledge base...'));

    expect(shown()).toEqual({ status: 'cancelled', message: CANCELLED_WORDS });
  });

  it('still applies progress to an active run', async () => {
    get.mockResolvedValue(run('j1', 'extracting'));
    await render(<RunPage />);

    await send(progress('j1', 'extracting', 'Video 3/5'));

    expect(shown()).toEqual({ status: 'extracting', message: 'Video 3/5' });
  });
});

describe('useJobProgress: a cancel from another tab (T-5.2.30)', () => {
  it('moves an active run to cancelled, then drops the progress line that left after it', async () => {
    get.mockResolvedValueOnce(run('j1', 'generating_report')).mockImplementation(pending);
    qc.setQueryData(LIST_KEY, [run('j1', 'generating_report'), run('j2', 'extracting')]);
    await render(<RunPage />);

    await send(statusChange('j1', 'generating_report', 'cancelled', CANCELLED_WORDS));
    expect(shown()).toEqual({ status: 'cancelled', message: CANCELLED_WORDS });
    expect(listRow('j1')?.status).toBe('cancelled');
    expect(listRow('j2')?.status).toBe('extracting');
    // A terminal status refetches the run, as completed and failed do.
    expect(get).toHaveBeenCalledTimes(2);

    // The worker's last write committed before the cancel; its publish arrives now.
    await send(progress('j1', 'generating_report', 'Composing the report'));
    expect(shown()).toEqual({ status: 'cancelled', message: CANCELLED_WORDS });
    expect(listRow('j1')?.status).toBe('cancelled');
  });

  it('leaves another run, and the bell, alone', async () => {
    get.mockResolvedValue(run('j1', 'extracting'));
    const bell = vi.fn();
    const stopBell = wsClient.subscribeNotifications(bell);
    await render(<RunPage />);

    await send(statusChange('j2', 'extracting', 'cancelled', CANCELLED_WORDS));
    await send({ type: 'notification', id: 'n1', kind: 'saved_search_changed' });

    expect(shown()).toEqual({ status: 'extracting', message: 'Video 1/5' });
    expect(bell).toHaveBeenCalledTimes(1);
    expect(bell).toHaveBeenCalledWith(expect.objectContaining({ type: 'notification', id: 'n1' }));
    stopBell();
  });
});

describe('useJobProgress: a refetch still wins', () => {
  it('moves an active run to its end', async () => {
    get.mockResolvedValueOnce(run('j1', 'extracting')).mockResolvedValue(run('j1', 'completed', 'Done'));
    await render(<RunPage />);

    await act(() => qc.refetchQueries({ queryKey: ['job', 'j1'] }));
    await flush();
    expect(shown()).toEqual({ status: 'completed', message: 'Done' });

    await send(progress('j1', 'building_rag', 'Indexed 40 new chunks'));
    expect(shown()).toEqual({ status: 'completed', message: 'Done' });
  });

  it('moves the cache off an ended status, and events apply again', async () => {
    // The guard reads the cache as it stands, not a memory of earlier events.
    get.mockResolvedValueOnce(run('j1', 'cancelled', CANCELLED_WORDS)).mockResolvedValue(run('j1', 'extracting'));
    await render(<RunPage />);
    expect(shown().status).toBe('cancelled');

    await act(() => qc.refetchQueries({ queryKey: ['job', 'j1'] }));
    await flush();
    expect(shown().status).toBe('extracting');

    await send(progress('j1', 'building_rag', 'Indexed 40 new chunks'));
    expect(shown()).toEqual({ status: 'building_rag', message: 'Indexed 40 new chunks' });
  });
});

describe("useJobProgress: the run's videos follow its status", () => {
  it('refetches them when a poll reads the end before its event, and the event adds nothing', async () => {
    get.mockResolvedValueOnce(run('j1', 'generating_report')).mockResolvedValue(run('j1', 'completed', 'Done'));
    await render(<RunWithVideos />);
    expect(getVideos).toHaveBeenCalledTimes(1);

    // The 5-second poll lands between the worker's commit and its publish.
    await act(() => qc.refetchQueries({ queryKey: ['job', 'j1'] }));
    await flush();
    expect(shown().status).toBe('completed');
    expect(getVideos).toHaveBeenCalledTimes(2);

    await send(statusChange('j1', 'generating_report', 'completed', 'Done'));
    expect(getVideos).toHaveBeenCalledTimes(2);
  });

  it('refetches them once when the event ends the run', async () => {
    get.mockResolvedValueOnce(run('j1', 'generating_report')).mockImplementation(pending);
    await render(<RunWithVideos />);

    await send(statusChange('j1', 'generating_report', 'completed', 'Job completed successfully!'));

    expect(shown().status).toBe('completed');
    expect(getVideos).toHaveBeenCalledTimes(2);
  });

  it('refetches them when a poll reads awaiting_approval and its event never comes', async () => {
    get
      .mockResolvedValueOnce(run('j1', 'searching'))
      .mockResolvedValue(run('j1', 'awaiting_approval', 'Found 5 candidates.'));
    await render(<RunWithVideos />);
    expect(getVideos).toHaveBeenCalledTimes(1);

    await act(() => qc.refetchQueries({ queryKey: ['job', 'j1'] }));
    await flush();

    expect(shown().status).toBe('awaiting_approval');
    expect(getVideos).toHaveBeenCalledTimes(2);
  });

  it("refetches them on this tab's own cancel answer, and not again on its event", async () => {
    get.mockResolvedValueOnce(run('j1', 'extracting')).mockImplementation(pending);
    await render(<RunWithVideos />);

    // What `useCancelJob`'s onSuccess stores: the server's answer.
    act(() => {
      qc.setQueryData(['job', 'j1'], run('j1', 'cancelled', CANCELLED_WORDS));
    });
    await flush();
    expect(getVideos).toHaveBeenCalledTimes(2);

    await send(statusChange('j1', 'extracting', 'cancelled', CANCELLED_WORDS));
    expect(shown()).toEqual({ status: 'cancelled', message: CANCELLED_WORDS });
    expect(getVideos).toHaveBeenCalledTimes(2);
  });

  it('fetches them once for a page opened on an ended run, its videos answered first', async () => {
    let answer: (job: Job) => void = () => {};
    get.mockReturnValueOnce(new Promise<Job>((resolve) => (answer = resolve)));
    get.mockResolvedValue(run('j1', 'completed', 'Done'));
    await render(<RunWithVideos />);
    expect(getVideos).toHaveBeenCalledTimes(1);

    // The run's first answer lands after the videos': the first status the
    // cache receives, not a move.
    act(() => answer(run('j1', 'completed', 'Done')));
    await flush();
    await act(() => qc.refetchQueries({ queryKey: ['job', 'j1'] }));
    await flush();

    expect(shown().status).toBe('completed');
    expect(getVideos).toHaveBeenCalledTimes(1);
  });
});

describe('useAllJobsProgress: the jobs list', () => {
  it('shows a cancel at once, refetches the list, and drops what comes after', async () => {
    qc.setQueryData(LIST_KEY, [run('j1', 'extracting'), run('j2', 'completed', 'Done')]);
    qc.setQueryData(['jobs', 'failed', 20, 0], [run('j3', 'failed', 'Failed')]);
    await render(<JobsPage ids={['j1']} />);

    await send(statusChange('j1', 'extracting', 'cancelled', CANCELLED_WORDS));
    expect(listRow('j1')).toMatchObject({ status: 'cancelled', progress_message: CANCELLED_WORDS });
    expect(listRow('j2')?.status).toBe('completed');
    expect(qc.getQueryData<Job[]>(['jobs', 'failed', 20, 0])).toEqual([run('j3', 'failed', 'Failed')]);
    expect(list).toHaveBeenCalled();

    await send(progress('j1', 'extracting', 'Video 4/5'));
    expect(listRow('j1')).toMatchObject({ status: 'cancelled', progress_message: CANCELLED_WORDS });
  });

  it('applies progress to an active row without refetching', async () => {
    qc.setQueryData(LIST_KEY, [run('j1', 'extracting')]);
    await render(<JobsPage ids={['j1']} />);

    await send(progress('j1', 'extracting', 'Video 4/5'));

    expect(listRow('j1')).toMatchObject({ status: 'extracting', progress_message: 'Video 4/5' });
    expect(list).not.toHaveBeenCalled();
  });
});
