/**
 * S-1.15.3: the drawer's depth reaches the server. The real drawer, the real
 * `useKnowledge` / `useExtractKnowledge` hooks and the real `knowledgeApi` run
 * here; only the HTTP layer is replaced. The other drawer tests mock the hook,
 * so a hook that stopped forwarding the depth would pass them all while every
 * report ran at the default and the select still showed the reader's pick.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { KnowledgeArtifact } from '../../services/knowledgeApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    post: (...args: unknown[]) => postMock(...args),
  },
}));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../components/notes', () => ({ NotesPanel: () => null }));
vi.mock('../../components/qa/SuggestionCard', () => ({ SuggestionCard: () => null }));
vi.mock('../../components/frames/VideoFramesPanel', () => ({ VideoFramesPanel: () => null }));

import { VideoKnowledgeDrawer } from '../VideoKnowledgePage';

const ARTIFACT: KnowledgeArtifact = {
  topics: ['tidal storage'],
  concepts: [],
  events: [],
  facts: [],
  knowledge_report_md: '# Tidal storage',
  knowledge_extracted_at: '2026-11-04T00:00:00Z',
  output_length: null,
};

const NOT_EXTRACTED = Object.assign(new Error('Not found'), { isAxiosError: true, response: { status: 404 } });

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount(defaultDepth?: string | null, preferred: string | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  qc.setQueryData(['auth', 'me'], { preferred_output_length: preferred });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <VideoKnowledgeDrawer videoId="doc-1" videoTitle="A talk" defaultDepth={defaultDepth} onClose={() => undefined} />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const button = (label: string) =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as HTMLButtonElement;

function pick(depth: string) {
  const select = host.querySelector<HTMLSelectElement>('select[aria-label="Report depth"]')!;
  act(() => {
    select.value = depth;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

async function press(label: string) {
  await act(async () => button(label).click());
  await flush();
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  getMock.mockRejectedValue(NOT_EXTRACTED);
  postMock.mockResolvedValue({ data: ARTIFACT });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('VideoKnowledgeDrawer: the POST it sends', () => {
  it('sends no preference on Auto', async () => {
    await mount();
    await press('Generate report');
    expect(postMock).toHaveBeenCalledTimes(1);
    expect(postMock).toHaveBeenCalledWith('/videos/doc-1/extract-knowledge', null, { params: undefined });
  });

  it('sends the depth the reader picked', async () => {
    await mount();
    pick('brief');
    await press('Generate report');
    expect(postMock).toHaveBeenCalledWith('/videos/doc-1/extract-knowledge', null, {
      params: { output_length: 'brief' },
    });
  });

  it("sends the surface's default when the reader leaves it", async () => {
    await mount('deep');
    await press('Generate report');
    expect(postMock).toHaveBeenCalledWith('/videos/doc-1/extract-knowledge', null, {
      params: { output_length: 'deep' },
    });
  });

  it("starts from the account's default depth, spending nothing until the click (T-1.15.3.9)", async () => {
    await mount(undefined, 'brief');
    expect(host.querySelector<HTMLSelectElement>('select[aria-label="Report depth"]')!.value).toBe('brief');
    expect(postMock).not.toHaveBeenCalled();
    await press('Generate report');
    expect(postMock).toHaveBeenCalledWith('/videos/doc-1/extract-knowledge', null, {
      params: { output_length: 'brief' },
    });
  });

  it("lets a run's own depth win over the account's", async () => {
    await mount('deep', 'brief');
    await press('Generate report');
    expect(postMock).toHaveBeenCalledWith('/videos/doc-1/extract-knowledge', null, {
      params: { output_length: 'deep' },
    });
  });

  it("lets Auto, picked in the drawer, win over the account's", async () => {
    await mount(undefined, 'brief');
    pick('');
    await press('Generate report');
    expect(postMock).toHaveBeenCalledWith('/videos/doc-1/extract-knowledge', null, { params: undefined });
  });

  it('regenerates a stored report with force and the depth, and says which depth it was written at', async () => {
    getMock.mockResolvedValue({ data: ARTIFACT });
    postMock.mockResolvedValue({ data: { ...ARTIFACT, output_length: 'deep' } });
    await mount();
    pick('deep');
    await press('Regenerate');
    expect(postMock).toHaveBeenCalledWith('/videos/doc-1/extract-knowledge', null, {
      params: { force: true, output_length: 'deep' },
    });
    expect(host.textContent).toContain('Written at deep depth.');
  });

  it('keeps the stored report on screen when a Regenerate fails (502)', async () => {
    getMock.mockResolvedValue({ data: ARTIFACT });
    postMock.mockRejectedValue(
      Object.assign(new Error('Bad gateway'), { isAxiosError: true, response: { status: 502 } }),
    );
    await mount();
    pick('brief');
    await press('Regenerate');
    expect(host.textContent).toContain('Tidal storage');
    expect(button('Regenerate').disabled).toBe(false);
  });
});
