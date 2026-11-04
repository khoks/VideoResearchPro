/**
 * T-1.15.3.8: a report cut off at its budget says so in the drawer and on the
 * reader page, and offers Regenerate at Deep. The real pages, hooks and
 * `knowledgeApi` run here; only the HTTP layer is replaced, so the assertion is
 * the POST the button sends. A report with no flag, which is every report from
 * before this was recorded, shows nothing.
 *
 * Mutation checks, run by hand on 2026-11-04: the note's button not passing the
 * depth fails the Regenerate tests; rendering the note without reading
 * `report_cut_off` fails the "no flag" tests.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { KnowledgeArtifact } from '../../services/knowledgeApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getMock = vi.fn();
const postMock = vi.fn();
let available = true;
vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    post: (...args: unknown[]) => postMock(...args),
  },
}));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => available }));
vi.mock('../../components/notes', () => ({ NotesPanel: () => null }));
vi.mock('../../components/qa/SuggestionCard', () => ({ SuggestionCard: () => null }));
vi.mock('../../components/frames/VideoFramesPanel', () => ({ VideoFramesPanel: () => null }));

import { KnowledgeReaderPage } from '../KnowledgeReaderPage';
import { VideoKnowledgeDrawer } from '../VideoKnowledgePage';

const ARTIFACT: KnowledgeArtifact = {
  document_id: 'doc-1',
  title: 'A talk',
  source_type: 'video',
  topics: ['tidal storage'],
  concepts: [],
  events: [],
  facts: [],
  knowledge_report_md: '# Tidal storage\n\n## Overview\n\nLagoons store',
  knowledge_extracted_at: '2026-11-04T00:00:00Z',
  output_length: null,
};
const CUT_OFF = { ...ARTIFACT, report_cut_off: true };
const LABEL = 'Regenerate at Deep depth';

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

const SURFACES: Record<string, () => React.ReactNode> = {
  drawer: () => (
    <MemoryRouter>
      <VideoKnowledgeDrawer videoId="doc-1" videoTitle="A talk" onClose={() => undefined} />
    </MemoryRouter>
  ),
  reader: () => (
    <MemoryRouter initialEntries={['/knowledge/doc-1']}>
      <Routes>
        <Route path="/knowledge/:videoId" element={<KnowledgeReaderPage />} />
      </Routes>
    </MemoryRouter>
  ),
};

async function mount(surface: string, stored: KnowledgeArtifact) {
  getMock.mockResolvedValue({ data: stored });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  act(() => root.render(<QueryClientProvider client={qc}>{SURFACES[surface]()}</QueryClientProvider>));
  await flush();
}

const note = () => host.querySelector('[data-knowledge-cut-off]');
const regenerate = () =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === LABEL) as
    | HTMLButtonElement
    | undefined;

beforeEach(() => {
  available = true;
  getMock.mockReset();
  postMock.mockReset();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe.each(Object.keys(SURFACES))('the cut-off note in the %s', (surface) => {
  it('says the report was cut off and offers Deep', async () => {
    await mount(surface, CUT_OFF);
    expect(note()!.textContent).toContain('This report stopped at its length limit, so its end is missing.');
    expect(note()!.textContent).toContain('uses one knowledge extraction');
    expect(regenerate()).toBeDefined();
  });

  it('regenerates with force at Deep, and goes once the new report fits', async () => {
    postMock.mockResolvedValue({ data: { ...ARTIFACT, output_length: 'deep', report_cut_off: false } });
    await mount(surface, { ...CUT_OFF, output_length: 'brief' });
    await act(async () => regenerate()!.click());
    await flush();
    expect(postMock).toHaveBeenCalledTimes(1);
    expect(postMock).toHaveBeenCalledWith('/videos/doc-1/extract-knowledge', null, {
      params: { force: true, output_length: 'deep' },
    });
    expect(note()).toBeNull();
  });

  it('stays when the new report was cut off too, at Deep, with nothing deeper to offer', async () => {
    postMock.mockResolvedValue({ data: { ...CUT_OFF, output_length: 'deep' } });
    await mount(surface, CUT_OFF);
    await act(async () => regenerate()!.click());
    await flush();
    expect(note()).not.toBeNull();
    expect(regenerate()).toBeUndefined();
    expect(note()!.textContent).not.toContain('uses one knowledge extraction');
  });

  it('shows nothing for a report with no flag', async () => {
    await mount(surface, ARTIFACT);
    expect(host.textContent).toContain('Tidal storage');
    expect(note()).toBeNull();
    await mount(surface, { ...ARTIFACT, report_cut_off: false });
    expect(note()).toBeNull();
  });

  it('keeps the note but offers nothing while extraction is unavailable', async () => {
    available = false;
    await mount(surface, CUT_OFF);
    expect(note()).not.toBeNull();
    expect(regenerate()).toBeUndefined();
    expect(note()!.textContent).not.toContain('uses one knowledge extraction');
  });
});

describe('the drawer after a Regenerate from the note', () => {
  it('moves the depth select to Deep, so a later Regenerate means the same', async () => {
    postMock.mockResolvedValue({ data: { ...CUT_OFF, output_length: 'deep' } });
    await mount('drawer', CUT_OFF);
    await act(async () => regenerate()!.click());
    await flush();
    expect(host.querySelector<HTMLSelectElement>('select[aria-label="Report depth"]')!.value).toBe('deep');
  });
});
