/**
 * S-6.3.2: the deck's create modal offers documents with a knowledge report
 * beside runs. Ticking one sends `document:<id>` in `source_ids` (to the
 * estimate and to create), a deck can be made from knowledge reports alone,
 * and a refusal (409: no knowledge report) shows the server's sentence.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CreateOutputPayload, KnowledgeSource } from '../../services/authorApi';
import { useJobStore } from '../../stores/jobStore';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DOC: KnowledgeSource = {
  document_id: 'doc-1',
  title: 'BP tablets: what happens if you stop?',
  source_type: 'video',
  channel_name: 'Dr Raju Health',
  published_at: '2025-03-02T00:00:00',
  knowledge_extracted_at: '2026-11-01T10:00:00',
};
const PDF: KnowledgeSource = {
  document_id: 'doc-2',
  title: 'Hypertension guideline',
  source_type: 'pdf',
  channel_name: '',
  published_at: null,
  knowledge_extracted_at: null,
};

const api = {
  knowledge: vi.fn<(p?: { q?: string; limit?: number }) => Promise<KnowledgeSource[]>>(),
  create: vi.fn<(p: CreateOutputPayload) => Promise<unknown>>(),
  estimate: vi.fn<(p: CreateOutputPayload) => Promise<unknown>>(),
};
vi.mock('../../services/authorApi', () => ({
  authorApi: {
    listKinds: async () => ({ available: ['book', 'deck'], supported: ['book', 'deck'], formats: {} }),
    listOutputs: async () => [],
    listKnowledgeSources: (p?: { q?: string; limit?: number }) => api.knowledge(p),
    createOutput: (p: CreateOutputPayload) => api.create(p),
    estimateOutput: (p: CreateOutputPayload) => api.estimate(p),
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
        id: 'job-1', topic: 'Smoking and lungs', job_type: 'topic', status: 'completed', has_report: true,
        video_count: 3, created_at: '2026-10-19T10:00:00', channel_list: [],
      },
    ],
  }),
}));
vi.mock('../../hooks/useShelves', () => ({ useShelves: () => ({ isLoading: false, data: [] }) }));
vi.mock('../../hooks/useOutputProgress', () => ({ useOutputsProgress: () => undefined }));
vi.mock('../../components/author/NewsletterCard', () => ({ NewsletterCard: () => null }));

import { AuthorPage } from '../AuthorPage';

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mountDeckModal() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/author?new=deck']}>
          <Routes>
            <Route path="/author" element={<AuthorPage />} />
            <Route path="*" element={null} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

/** Past the filter's debounce. */
async function settleFilter() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 300));
  });
  await flush();
}

function typeInto(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

const titleInput = () =>
  document.querySelector('input[placeholder="e.g. Two years of the AI policy debate"]') as HTMLInputElement;
const filterInput = () =>
  document.querySelector('input[placeholder="Filter knowledge reports by source…"]') as HTMLInputElement;
const picker = () => document.querySelector('[data-testid="knowledge-picker"]');
const generate = () =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Generate') as HTMLButtonElement;
const rowCheckbox = (text: string) =>
  Array.from(document.querySelectorAll('label'))
    .find((l) => l.textContent?.includes(text))
    ?.querySelector('input[type="checkbox"]') as HTMLInputElement;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  api.knowledge.mockResolvedValue([DOC, PDF]);
  api.estimate.mockResolvedValue({ calls: [], cost_usd: 0.02 });
  api.create.mockImplementation(async (p) => ({ id: 'out-1', kind: 'deck', title: p.title, status: 'pending', source_ids: p.source_ids }));
  useJobStore.setState({ toasts: [] });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('deck create modal (S-6.3.2)', () => {
  it('lists the knowledge reports beside the runs, with what each source is', async () => {
    await mountDeckModal();
    const picker = document.querySelector('[data-testid="knowledge-picker"]');
    expect(picker?.textContent).toContain('BP tablets: what happens if you stop?');
    expect(picker?.textContent).toContain('YouTube video · Dr Raju Health · report 1 Nov 2026');
    expect(picker?.textContent).toContain('Hypertension guideline');
    expect(picker?.textContent).toContain('PDF');
    expect(document.body.textContent).toContain('Smoking and lungs');
    expect(api.knowledge).toHaveBeenCalledTimes(1);
  });

  it('makes a deck from a knowledge report alone, sent as document:<id>', async () => {
    await mountDeckModal();
    typeInto(titleInput(), 'Pills deck');
    expect(generate().disabled).toBe(true);
    act(() => rowCheckbox('BP tablets').click());
    await flush();
    expect(generate().disabled).toBe(false);
    expect(api.estimate).toHaveBeenCalledWith(expect.objectContaining({ kind: 'deck', source_ids: ['document:doc-1'] }));
    await act(async () => generate().click());
    await flush();
    expect(api.create).toHaveBeenCalledWith({ kind: 'deck', title: 'Pills deck', source_ids: ['document:doc-1'], parameters: {} });
  });

  it('mixes runs and knowledge reports in one deck', async () => {
    await mountDeckModal();
    typeInto(titleInput(), 'Mixed');
    act(() => rowCheckbox('Smoking and lungs').click());
    act(() => rowCheckbox('Hypertension guideline').click());
    await flush();
    await act(async () => generate().click());
    await flush();
    expect(api.create.mock.calls[0][0].source_ids).toEqual(['job-1', 'document:doc-2']);
  });

  it('shows the server’s sentence when a document has no knowledge report', async () => {
    const detail = '“BP tablets: what happens if you stop?” has no knowledge report yet. Extract one from the library first, then make the deck.';
    api.create.mockRejectedValue({ response: { status: 409, data: { detail } } });
    await mountDeckModal();
    typeInto(titleInput(), 'Pills deck');
    act(() => rowCheckbox('BP tablets').click());
    await flush();
    await act(async () => generate().click());
    await flush();
    expect(useJobStore.getState().toasts.map((t) => t.message)).toContain(detail);
  });

  it('asks the server when filtering, so a report older than the list is found', async () => {
    const OLDER = { ...PDF, document_id: 'doc-old', title: 'An older report' };
    api.knowledge.mockImplementation(async (p) => (p?.q ? [OLDER] : [DOC, PDF]));
    await mountDeckModal();
    expect(picker()?.textContent).not.toContain('An older report');
    typeInto(filterInput(), '  older ');
    await settleFilter();
    expect(api.knowledge).toHaveBeenLastCalledWith({ q: 'older', limit: 200 });
    expect(picker()?.textContent).toContain('An older report');
    expect(picker()?.textContent).not.toContain('BP tablets');
  });

  it('says a filter matched nothing only once the server has answered', async () => {
    let answer: (rows: KnowledgeSource[]) => void = () => undefined;
    api.knowledge.mockImplementation((p) =>
      p?.q ? new Promise((resolve) => { answer = resolve; }) : Promise.resolve([]),
    );
    await mountDeckModal();
    typeInto(filterInput(), 'nothing like this');
    await settleFilter();
    expect(picker()?.textContent).not.toContain('No knowledge reports match that filter.');
    expect(picker()?.textContent).not.toContain('No knowledge reports yet.');
    await act(async () => answer([]));
    await flush();
    expect(picker()?.textContent).toContain('No knowledge reports match that filter.');
    expect(picker()?.textContent).not.toContain('No knowledge reports yet.');
  });

  it('says the list is cut off when it comes back full', async () => {
    const full = Array.from({ length: 200 }, (_, i) => ({ ...DOC, document_id: `doc-${i}`, title: `Report ${i}` }));
    api.knowledge.mockResolvedValue(full);
    await mountDeckModal();
    expect(api.knowledge).toHaveBeenCalledWith({ limit: 200 });
    expect(document.querySelector('[data-testid="knowledge-picker-cap"]')?.textContent).toBe(
      'Showing the 200 most recent. Filter by source to find an older one.',
    );
    api.knowledge.mockResolvedValue([DOC]);
    typeInto(filterInput(), 'bp');
    await settleFilter();
    expect(document.querySelector('[data-testid="knowledge-picker-cap"]')).toBeNull();
  });

  it('says how to get a knowledge report when there is none', async () => {
    api.knowledge.mockResolvedValue([]);
    await mountDeckModal();
    expect(document.querySelector('[data-testid="knowledge-picker"]')?.textContent).toContain('No knowledge reports yet.');
  });
});
