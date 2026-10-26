/**
 * T-5.2.10: starting a subscription from the Submit page is a sync entry
 * point, and a full library refuses it (429, `detail.resource ===
 * 'documents'`). The refusal is said in the form's own error box, where the
 * run was started; it used to be swallowed in favour of a global toast that
 * read "Request failed with status code 429".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AxiosError, AxiosHeaders } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const CAP_MESSAGE =
  "Your library is at the Free plan's cap of 500 documents. A sync cannot add anything new until you " +
  'move to a plan with a higher cap. Documents already in your library stay.';

function axiosError(status: number, data: unknown): AxiosError {
  const headers = new AxiosHeaders();
  return new AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_REQUEST', undefined, undefined, {
    status,
    statusText: '',
    headers,
    config: { headers },
    data,
  });
}

const capRefusal = () =>
  axiosError(429, {
    detail: {
      error: 'quota_exceeded',
      resource: 'documents',
      consumed: 500,
      limit: 500,
      requested: null,
      available: 0,
      retry_at: null,
      retry_after_sec: null,
      message: CAP_MESSAGE,
    },
  });

const mutateAsync = vi.fn();
vi.mock('../../hooks/useJobs', () => ({
  useCreateJob: () => ({ mutateAsync, isPending: false }),
}));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../hooks/useCapability', () => ({ useCapability: () => false }));
vi.mock('../../hooks/useTierCapabilities', () => ({
  useTierCapabilities: () => ({ tier: 'free', numVideosCap: 100 }),
}));
vi.mock('../../hooks/useJobTemplates', () => ({
  useJobTemplates: () => ({ data: [] }),
  useCreateTemplate: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  useUpdateTemplate: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
}));

import { SubmitJobPage } from '../SubmitJobPage';

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function submitSubscription() {
  window.localStorage.setItem(
    'vrp:submit-form',
    JSON.stringify({ jobType: 'subscription', subscriptionChannels: '@capchannel' }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/jobs/new']}>
          <SubmitJobPage />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
  const submit = host.querySelector('button[type="submit"]') as HTMLButtonElement;
  await act(async () => submit.click());
  await flush();
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  mutateAsync.mockReset();
  window.localStorage.clear();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.localStorage.clear();
});

describe('subscription run refused by the document cap', () => {
  it("shows the server's message in the form", async () => {
    mutateAsync.mockRejectedValue(capRefusal());
    await submitSubscription();

    expect(mutateAsync).toHaveBeenCalledTimes(1);
    expect(mutateAsync.mock.calls[0][0].data.job_type).toBe('subscription');
    const alerts = Array.from(host.querySelectorAll('[role="alert"]')).map((a) => a.textContent);
    expect(alerts).toContain(CAP_MESSAGE);
  });

  it('leaves other failures to the global toast', async () => {
    mutateAsync.mockRejectedValue(axiosError(500, { detail: 'Server error' }));
    await submitSubscription();

    expect(mutateAsync).toHaveBeenCalledTimes(1);
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });
});
