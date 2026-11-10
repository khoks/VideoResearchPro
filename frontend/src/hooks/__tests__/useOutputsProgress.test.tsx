/**
 * Author output events on an open page (T-5.2.34).
 *
 * The worker writes an output's progress line, commits, then publishes it, so a
 * cancel that commits in between is followed by one event naming `generating`,
 * which showed the cancelled output going again. Since T-5.2.34 the server
 * writes every status and progress line in one conditional write that refuses
 * an ended output, and publishes it only once written, so an end reaches the
 * cache only on the server's word; the page writes no output status of its own
 * (`useCancelOutput` refetches). `useOutputsProgress` now drops every event for
 * an output a cached copy holds as ended (completed, failed, cancelled,
 * skipped), in each outputs list and in the reader's single output, and an
 * event that every copy drops refetches nothing.
 *
 * The real `wsClient` runs over a fake WebSocket, so events are routed by
 * output id exactly as in the app; `authorApi` is faked.
 *
 * Mutation checks, run by hand on 2026-11-10: taking the ended-status guard out
 * of `applyOutputProgress` fails the late-event, cancel-then-progress and
 * skipped cases (the output reads `generating` again, and a late `completed`
 * refetches); refetching on a terminal event whether or not a copy took it
 * fails the late-event case (refetched).
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { OutputItem } from '../../services/authorApi';
import type { WSProgressMessage } from '../../types/ws';

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

const listOutputs = vi.fn<() => Promise<OutputItem[]>>();
const getOutput = vi.fn<(id: string) => Promise<OutputItem>>();
const getContent = vi.fn<(id: string) => Promise<string>>();
vi.mock('../../services/authorApi', () => ({
  authorApi: {
    listOutputs: () => listOutputs(),
    getOutput: (id: string) => getOutput(id),
    getContent: (id: string) => getContent(id),
  },
}));

import { wsClient } from '../../services/wsClient';
import { useAuthorOutput, useAuthorOutputContent, useAuthorOutputs } from '../useAuthor';
import { useOutputsProgress } from '../useOutputProgress';

const CANCELLED_WORDS = 'Cancelled by user';
/** The key `useAuthorOutputs` gives the studio's list, no filter. */
const LIST_KEY = ['author', 'outputs', null, null];

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;

function output(id: string, status: string, progress_message = 'Chapter 1 of 3'): OutputItem {
  return { id, status, progress_pct: 30, progress_message, error_message: null, kind: 'book', title: 'B' } as OutputItem;
}

/** The studio page: its list, live. */
function StudioPage({ ids }: { ids: string[] }) {
  useAuthorOutputs();
  useOutputsProgress(ids);
  return null;
}

/** The reader page: one output and its content, live. */
function ReaderPage() {
  const { data } = useAuthorOutput('o1');
  useAuthorOutputContent('o1');
  useOutputsProgress(['o1']);
  return <span data-status={data?.status ?? ''} data-message={data?.progress_message ?? ''} />;
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

async function send(msg: Partial<WSProgressMessage>) {
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

function listRow(id: string): OutputItem | undefined {
  return qc.getQueryData<OutputItem[]>(LIST_KEY)?.find((o) => o.id === id);
}

function shown() {
  const span = host.querySelector('span') as HTMLSpanElement;
  return { status: span.dataset.status, message: span.dataset.message };
}

function fetches() {
  return [listOutputs.mock.calls.length, getOutput.mock.calls.length, getContent.mock.calls.length];
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  listOutputs.mockReset();
  getOutput.mockReset();
  getContent.mockReset().mockResolvedValue('# B');
  FakeWebSocket.instances = [];
});

afterEach(() => {
  act(() => root.unmount());
  wsClient.disconnect();
  qc.clear();
  host.remove();
});

describe('useOutputsProgress: an output the page holds as ended', () => {
  it('drops late progress and a late end in the list and the reader, and refetches nothing', async () => {
    listOutputs.mockResolvedValue([output('o1', 'cancelled', CANCELLED_WORDS)]);
    getOutput.mockResolvedValue(output('o1', 'cancelled', CANCELLED_WORDS));
    await render(
      <>
        <StudioPage ids={['o1']} />
        <ReaderPage />
      </>,
    );
    expect(fetches()).toEqual([1, 1, 1]);

    await send(progress('o1', 'generating', 'Chapter 2 of 3'));
    await send(statusChange('o1', 'generating', 'completed', 'Done'));

    expect(listRow('o1')).toMatchObject({ status: 'cancelled', progress_message: CANCELLED_WORDS });
    expect(shown()).toEqual({ status: 'cancelled', message: CANCELLED_WORDS });
    expect(fetches()).toEqual([1, 1, 1]);
  });

  it('treats skipped as an end', async () => {
    listOutputs.mockResolvedValue([output('o1', 'skipped', 'Nothing new since the last issue.')]);
    await render(<StudioPage ids={['o1']} />);

    await send(progress('o1', 'generating', 'Collecting what is new'));

    expect(listRow('o1')).toMatchObject({ status: 'skipped', progress_message: 'Nothing new since the last issue.' });
    expect(listOutputs).toHaveBeenCalledTimes(1);
  });
});

describe('useOutputsProgress: an output still going', () => {
  it('applies progress without refetching', async () => {
    listOutputs.mockResolvedValue([output('o1', 'generating'), output('o2', 'completed', 'Done')]);
    await render(<StudioPage ids={['o1']} />);

    await send(progress('o1', 'generating', 'Chapter 2 of 3'));

    expect(listRow('o1')).toMatchObject({ status: 'generating', progress_message: 'Chapter 2 of 3' });
    expect(listRow('o2')).toMatchObject({ status: 'completed', progress_message: 'Done' });
    expect(listOutputs).toHaveBeenCalledTimes(1);
  });

  it('moves to cancelled on the cancel, then drops the progress line that left after it', async () => {
    listOutputs.mockResolvedValueOnce([output('o1', 'generating')]).mockImplementation(() => new Promise(() => {}));
    getOutput.mockResolvedValueOnce(output('o1', 'generating')).mockImplementation(() => new Promise(() => {}));
    await render(
      <>
        <StudioPage ids={['o1']} />
        <ReaderPage />
      </>,
    );

    await send(statusChange('o1', 'generating', 'cancelled', CANCELLED_WORDS));
    expect(listRow('o1')?.status).toBe('cancelled');
    expect(shown()).toEqual({ status: 'cancelled', message: CANCELLED_WORDS });
    // An end refetches the lists, the output and its content, once.
    expect(fetches()).toEqual([2, 2, 2]);

    // The worker's last progress write committed before the cancel; its publish arrives now.
    await send(progress('o1', 'generating', 'Chapter 3 of 3'));
    expect(listRow('o1')).toMatchObject({ status: 'cancelled', progress_message: CANCELLED_WORDS });
    expect(shown()).toEqual({ status: 'cancelled', message: CANCELLED_WORDS });
    expect(fetches()).toEqual([2, 2, 2]);
  });

  it('takes an event in a copy still going even when another copy has ended, and refetches', async () => {
    // The list's poll read the end first; the reader still holds it going.
    listOutputs.mockResolvedValueOnce([output('o1', 'completed', 'Done')]).mockResolvedValue([output('o1', 'completed', 'Done')]);
    getOutput.mockResolvedValueOnce(output('o1', 'generating')).mockResolvedValue(output('o1', 'completed', 'Done'));
    await render(
      <>
        <StudioPage ids={['o1']} />
        <ReaderPage />
      </>,
    );

    await send(statusChange('o1', 'generating', 'completed', 'Done'));

    expect(shown()).toEqual({ status: 'completed', message: 'Done' });
    expect(fetches()).toEqual([2, 2, 2]);
  });
});
