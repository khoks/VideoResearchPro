/**
 * T-5.2.22: a cancel that reaches a run already over (it completed or failed
 * first, even between the route's read and its write) answers 400 with what the
 * run ended as, and the run keeps that end. The global toast says those words,
 * once, and the run is fetched again, so the page shows the end the toast names
 * rather than a Cancel button for a run that is over.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Job } from '../../types/job';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const ENDED = 'This run has already completed, so there is nothing to cancel.';

const get = vi.fn<(id: string) => Promise<Job>>();
const cancel = vi.fn<(id: string) => Promise<Job>>();
vi.mock('../../services/jobsApi', () => ({
  jobsApi: { get: (id: string) => get(id), cancel: (id: string) => cancel(id) },
}));

import { createQueryClient } from '../../services/queryClient';
import { useJobStore } from '../../stores/jobStore';
import { useCancelJob, useJob } from '../useJobs';

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
let press: () => void = () => {};

function job(status: Job['status']): Job {
  return { id: 'j1', status } as Job;
}

function Probe() {
  const { data } = useJob('j1');
  const cancelJob = useCancelJob();
  press = () => cancelJob.mutate('j1');
  return <span data-status={data?.status ?? ''} />;
}

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

function status(): string {
  return (host.querySelector('span') as HTMLSpanElement).dataset.status ?? '';
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  qc = createQueryClient();
  useJobStore.setState({ toasts: [] });
  get.mockReset();
  cancel.mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  qc.clear();
  host.remove();
});

describe('useCancelJob', () => {
  it('refetches a run that ended first and says its end once', async () => {
    get.mockResolvedValueOnce(job('generating_report')).mockResolvedValue(job('completed'));
    cancel.mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 400',
      response: { status: 400, data: { detail: ENDED } },
    });
    act(() => root.render(<QueryClientProvider client={qc}><Probe /></QueryClientProvider>));
    await flush();
    expect(status()).toBe('generating_report');

    act(() => press());
    await flush();

    expect(status()).toBe('completed');
    expect(get).toHaveBeenCalledTimes(2);
    expect(useJobStore.getState().toasts.map((t) => [t.kind, t.message])).toEqual([['error', ENDED]]);
  });

  it('takes the cancelled run the answer carries, with no toast', async () => {
    get.mockResolvedValue(job('extracting'));
    cancel.mockResolvedValue(job('cancelled'));
    act(() => root.render(<QueryClientProvider client={qc}><Probe /></QueryClientProvider>));
    await flush();

    act(() => press());
    await flush();

    expect(status()).toBe('cancelled');
    expect(useJobStore.getState().toasts).toEqual([]);
  });
});
