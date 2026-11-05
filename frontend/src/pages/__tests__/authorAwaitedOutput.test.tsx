/**
 * T-6.7.1.7 at the Author page: the output a visit just queued opens when it
 * finishes. The effect that did this set state before it navigated
 * (react-hooks/set-state-in-effect). It now reads a value derived in render, so
 * the thing to pin is what the state update gave for free: each output is
 * announced once, however many times the list refetches, and the page stops
 * following it.
 *
 * Taking the `announced` guard out fails the refetch test; dropping `finished`
 * from the progress list fails "stops following".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CreateOutputPayload, OutputItem } from '../../services/authorApi';
import { useJobStore } from '../../stores/jobStore';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const state = vi.hoisted(() => ({
  rows: [] as unknown[],
  followed: [] as string[],
}));

vi.mock('../../services/authorApi', () => ({
  authorApi: {
    listKinds: async () => ({ available: ['book'], supported: ['book'], formats: {} }),
    listOutputs: async () => state.rows,
    estimateOutput: async () => ({ calls: [], cost_usd: 0 }),
    createOutput: async (p: CreateOutputPayload) => {
      const row = { ...output(), title: p.title, source_ids: p.source_ids };
      state.rows = [row];
      return row;
    },
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
vi.mock('../../hooks/useOutputProgress', () => ({
  useOutputsProgress: (ids: string[]) => {
    state.followed = ids;
  },
}));
vi.mock('../../components/author/NewsletterCard', () => ({ NewsletterCard: () => null }));

import { AuthorPage } from '../AuthorPage';

function output(overrides: Partial<OutputItem> = {}): OutputItem {
  return {
    id: 'o1',
    kind: 'book',
    title: 'Tidal energy',
    status: 'pending',
    source_ids: ['job-1'],
    parameters: {},
    error_message: null,
    progress_pct: 10,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    has_content: false,
    formats: [],
    citation_count: 0,
    ...overrides,
  } as OutputItem;
}

function Where() {
  return <output data-where>{useLocation().pathname}</output>;
}

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount(url: string) {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[url]}>
          <Routes>
            <Route path="/author" element={<AuthorPage />} />
            <Route path="*" element={<p>the reader</p>} />
          </Routes>
          <Where />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

/** What a progress event does: the list comes back with fresh row objects. */
async function refetch(rows: OutputItem[]) {
  state.rows = rows;
  await act(async () => {
    await qc.invalidateQueries({ queryKey: ['author'] });
  });
  await flush();
}

async function queueBook() {
  await mount('/author?new=book&job=job-1');
  const title = document.querySelector<HTMLInputElement>('input[placeholder^="e.g."]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(title, 'Tidal energy');
    title.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => {
    Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Generate')!.click();
  });
  await flush();
  // The create flow's own "queued" line: what comes after is what is under test.
  useJobStore.setState({ toasts: [] });
}

const where = () => host.querySelector('[data-where]')!.textContent;
const toasts = () => useJobStore.getState().toasts.map((t) => `${t.kind}: ${t.message}`);

beforeEach(() => {
  state.rows = [];
  state.followed = [];
  useJobStore.setState({ toasts: [] });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('the output this visit queued', () => {
  it('is followed while it runs, then opens', async () => {
    await queueBook();
    expect(where()).toBe('/author');
    expect(state.followed).toContain('o1');

    await refetch([output({ status: 'generating' })]);
    expect(where()).toBe('/author');
    expect(toasts()).toEqual([]);

    await refetch([output({ status: 'completed' })]);
    expect(where()).toBe('/author/outputs/o1');
    expect(toasts()).toEqual(['success: “Tidal energy” is ready.']);
  });

  it('announces a failure once, however often the list refetches, and stops following it', async () => {
    await queueBook();
    const failed = () => [output({ status: 'failed', error_message: 'The model refused.' })];
    await refetch(failed());
    await refetch(failed());
    await refetch(failed());
    expect(where()).toBe('/author');
    expect(toasts()).toEqual(['error: The model refused.']);
    expect(state.followed).not.toContain('o1');
  });

  it('says so when a run had nothing new', async () => {
    await queueBook();
    await refetch([output({ status: 'skipped', progress_message: 'Nothing new this week.' })]);
    expect(where()).toBe('/author');
    expect(toasts()).toEqual(['info: Nothing new this week.']);
  });
});

describe('an output this visit did not queue', () => {
  it('finishes quietly', async () => {
    state.rows = [output({ status: 'generating' })];
    await mount('/author');
    await refetch([output({ status: 'completed' })]);
    expect(where()).toBe('/author');
    expect(toasts()).toEqual([]);
  });
});
