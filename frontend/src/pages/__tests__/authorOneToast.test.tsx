/**
 * T-3.4.1.17: one toast per failure on the Author page and its digest card,
 * under the app's own query client. Making, cancelling and deleting an output,
 * and saving or sending the digest, each toasted from the page's `mutate` call
 * and again from the global handler. Now the hook says it, sets
 * `meta.errorsShownHere`, and says nothing of a 401: making an output used to
 * answer a 401 with "Your session expired", on its way to the sign-in page.
 *
 * Mutation checks, run on 2026-11-09: `meta` off the five hooks fails every
 * failure row but `sessionEnded` with two toasts; the 401 check out of
 * `useCreateOutput` fails "making an output" on `sessionEnded`;
 * `describeCreateError` falling back to axios's message fails it on `noWords`
 * and `noAnswer`.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { NewsletterSubscription, OutputItem } from '../../services/authorApi';
import { createQueryClient } from '../../services/queryClient';
import {
  FAILURE_KINDS,
  clearToasts,
  expectedToasts,
  failures,
  flush,
  press,
  toastMessages,
  typeInto,
} from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const RUNNING = {
  id: 'o1', kind: 'book', title: 'Tidal energy', status: 'generating', source_ids: ['job-1'], parameters: {},
  error_message: null, progress_pct: 10, created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  has_content: false, formats: [], citation_count: 0,
} as unknown as OutputItem;
const DIGEST: NewsletterSubscription = {
  id: 'n1', title: 'Digest', cadence: { cadence: 'weekly', hour: 9, minute: 0, weekday: 0, timezone: 'UTC' },
  sections: { new_sources: true }, enabled: true, last_issue_at: null, next_issue_at: null,
  created_at: '2026-11-01T09:00:00Z', sends: [],
};

const api = {
  getNewsletter: vi.fn<() => Promise<NewsletterSubscription | null>>(),
  createOutput: vi.fn<(p: unknown) => Promise<OutputItem>>(),
  cancelOutput: vi.fn<(id: string) => Promise<OutputItem>>(),
  deleteOutput: vi.fn<(id: string) => Promise<void>>(),
  saveNewsletter: vi.fn<(s: unknown) => Promise<NewsletterSubscription>>(),
  sendNewsletterNow: vi.fn<() => Promise<unknown>>(),
};
vi.mock('../../services/authorApi', () => ({
  authorApi: {
    listKinds: async () => ({ available: ['book'], supported: ['book'], formats: {} }),
    listOutputs: async () => [RUNNING],
    estimateOutput: async () => ({ calls: [], cost_usd: 0 }),
    getNewsletter: () => api.getNewsletter(),
    createOutput: (p: unknown) => api.createOutput(p),
    cancelOutput: (id: string) => api.cancelOutput(id),
    deleteOutput: (id: string) => api.deleteOutput(id),
    saveNewsletter: (s: unknown) => api.saveNewsletter(s),
    sendNewsletterNow: () => api.sendNewsletterNow(),
  },
}));
vi.mock('../../hooks/useTierCapabilities', () => ({
  useTierCapabilities: () => ({ has: () => true, tier: 'pro', isLoading: false }),
}));
vi.mock('../../hooks/useJobs', () => ({
  useJobs: () => ({
    isLoading: false,
    data: [
      {
        id: 'job-1', topic: 'Tides', job_type: 'topic', status: 'completed', has_report: true,
        video_count: 3, created_at: '2026-10-19T10:00:00', channel_list: [],
      },
    ],
  }),
}));
vi.mock('../../hooks/useShelves', () => ({ useShelves: () => ({ isLoading: false, data: [] }) }));
vi.mock('../../hooks/useOutputProgress', () => ({ useOutputsProgress: () => undefined }));

import { NewsletterCard } from '../../components/author/NewsletterCard';
import { AuthorPage } from '../AuthorPage';

let host: HTMLDivElement;
let root: Root;

async function mount(url = '/author') {
  act(() =>
    root.render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={[url]}>
          <Routes>
            <Route path="/author" element={<AuthorPage />} />
            <Route path="/digest" element={<NewsletterCard />} />
            <Route path="*" element={<p>elsewhere</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  for (const fn of Object.values(api)) fn.mockReset();
  api.getNewsletter.mockResolvedValue(DIGEST);
  api.createOutput.mockResolvedValue(RUNNING);
  api.cancelOutput.mockResolvedValue({ ...RUNNING, status: 'cancelled' } as OutputItem);
  api.deleteOutput.mockResolvedValue(undefined);
  api.saveNewsletter.mockResolvedValue(DIGEST);
  api.sendNewsletterNow.mockResolvedValue({});
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const SITES = [
  {
    name: 'making an output',
    url: '/author?new=book&job=job-1',
    call: () => api.createOutput,
    go: async () => {
      typeInto(document.querySelector<HTMLInputElement>('input[placeholder^="e.g."]')!, 'Tidal energy');
      await press('Generate');
    },
    fallback: 'Generation failed. Try again.',
  },
  {
    name: 'cancelling an output',
    url: '/author',
    call: () => api.cancelOutput,
    go: () => press('Cancel'),
    fallback: 'Could not cancel; it may already have finished.',
  },
  {
    name: 'deleting an output',
    url: '/author',
    call: () => api.deleteOutput,
    go: async () => {
      await press('Delete');
      await press('Delete', 'last');
    },
    fallback: 'Delete failed. The output may already be gone.',
  },
  {
    name: 'turning the digest on',
    url: '/digest',
    before: () => api.getNewsletter.mockResolvedValue(null),
    call: () => api.saveNewsletter,
    go: () => press('Turn on'),
    fallback: 'Could not save the digest settings.',
  },
  {
    name: 'sending a digest now',
    url: '/digest',
    call: () => api.sendNewsletterNow,
    go: () => press('Send one now'),
    fallback: 'Could not start an issue.',
  },
];

describe.each(SITES)('$name', (site) => {
  it.each(FAILURE_KINDS)('says a failure (%s) once', async (kind) => {
    site.before?.();
    site.call().mockRejectedValueOnce(failures[kind]());
    await mount(site.url);
    await site.go();
    expect(site.call()).toHaveBeenCalledTimes(1);
    expect(toastMessages()).toEqual(expectedToasts(kind, site.fallback));
  });
});

describe('making an output', () => {
  it('keeps its own sentence for a kind with no generator, whatever the server said', async () => {
    const e = failures.words();
    e.response!.status = 501;
    api.createOutput.mockRejectedValueOnce(e);
    await mount('/author?new=book&job=job-1');
    typeInto(document.querySelector<HTMLInputElement>('input[placeholder^="e.g."]')!, 'Tidal energy');
    await press('Generate');
    expect(toastMessages()).toEqual(['Book output has no generator yet. It is defined in the schema but nothing produces it today.']);
  });
});
