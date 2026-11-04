/**
 * The output reader's Sources list at its production caller (S-6.7.3).
 *
 * `GET /author/outputs/{id}/citations` had no UI. The reader now lists every
 * cited source under the manuscript, in first-cited order, with the
 * timestamp links the API recorded; a citation nothing matched is shown
 * without a link. An output with no recorded citations asks for none.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { OutputCitation, OutputItem } from '../../services/authorApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const state: { output: OutputItem; citations: OutputCitation[] | 'fail' } = {
  output: null as unknown as OutputItem,
  citations: [],
};
const calls: string[] = [];
vi.mock('../../services/api', () => ({
  default: {
    get: async (path: string) => {
      calls.push(path);
      if (path === '/author/outputs/o1') return { data: state.output };
      if (path === '/author/outputs/o1/content') return { data: MANUSCRIPT };
      if (path === '/author/outputs/o1/citations') {
        if (state.citations === 'fail') throw Object.assign(new Error('500'), { response: { status: 500 } });
        return { data: state.citations };
      }
      throw Object.assign(new Error('no fixture'), { response: { status: 404 } });
    },
    defaults: { baseURL: 'http://localhost:8000/api/v1' },
  },
}));
vi.mock('../../hooks/useOutputProgress', () => ({ useOutputsProgress: () => undefined }));

import { OutputReaderPage } from '../OutputReaderPage';

const MANUSCRIPT = '# Tidal energy\n\n## 1. Storage\n\nWater is held behind a barrage [0:42](https://www.youtube.com/watch?v=aaaaaaaaaaa&t=42)[^1].\n';

function output(overrides: Partial<OutputItem> = {}): OutputItem {
  return {
    id: 'o1',
    kind: 'book',
    title: 'Tidal energy',
    status: 'completed',
    source_ids: ['j1'],
    parameters: {},
    error_message: null,
    created_at: '2026-11-04T10:00:00Z',
    updated_at: '2026-11-04T10:00:00Z',
    has_content: true,
    formats: ['md'],
    citation_count: 4,
    ...overrides,
  };
}

function cite(position: number, overrides: Partial<OutputCitation>): OutputCitation {
  return {
    position,
    label: '0:00',
    url: null,
    seconds: null,
    document_id: null,
    source_type: null,
    source_id: null,
    resolved_by: null,
    title: null,
    channel_name: null,
    ...overrides,
  };
}

const TALK = { document_id: 'doc-a', source_type: 'video', resolved_by: 'video_id', title: 'How tidal storage works', channel_name: 'Energy Explained' };
const ESSAY = { document_id: 'doc-b', source_type: 'article', resolved_by: 'url', title: 'Pumped storage, a primer', channel_name: null };

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  calls.length = 0;
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/author/outputs/o1']}>
          <Routes>
            <Route path="/author/outputs/:outputId" element={<OutputReaderPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const sources = () => host.querySelector('section[aria-labelledby="output-sources-title"]');
const squash = (s: string | null | undefined) => (s ?? '').replace(/\s+/g, ' ').trim();

describe('OutputReaderPage Sources list', () => {
  it('lists every cited source in first-cited order with its timestamp links', async () => {
    state.output = output();
    state.citations = [
      cite(1, { ...TALK, label: '0:42', seconds: 42, url: 'https://www.youtube.com/watch?v=aaaaaaaaaaa&t=42' }),
      cite(2, { ...ESSAY, label: 'the primer', url: 'https://example.com/primer' }),
      cite(3, { ...TALK, label: '1:05:03', seconds: 3903, url: 'https://www.youtube.com/watch?v=aaaaaaaaaaa&t=3903' }),
      cite(4, { label: '2:10', seconds: 130 }),
    ];
    await mount();

    expect(calls).toContain('/author/outputs/o1/citations');
    const section = sources();
    expect(section).not.toBeNull();
    // The list sits under the manuscript, not inside it.
    const body = host.querySelector('.reader-body')!;
    expect(body.compareDocumentPosition(section!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(section!.classList.contains('reader-no-print')).toBe(true);
    expect(squash(section!.querySelector('h2')?.textContent)).toBe('Sources · 2 sources, 4 citations');

    const items = [...section!.querySelectorAll('ol > li')];
    expect(items.map((li) => squash(li.firstElementChild?.textContent))).toEqual([
      'How tidal storage works',
      'Pumped storage, a primer',
      'Not matched to a source in your library',
    ]);
    expect(squash(items[0].textContent)).toContain('— Energy Explained');

    const talkLinks = [...items[0].querySelectorAll('a')];
    expect(talkLinks.map((a) => [a.textContent, a.getAttribute('href'), a.getAttribute('target')])).toEqual([
      ['0:42', 'https://www.youtube.com/watch?v=aaaaaaaaaaa&t=42', '_blank'],
      ['1:05:03', 'https://www.youtube.com/watch?v=aaaaaaaaaaa&t=3903', '_blank'],
    ]);
    expect(talkLinks[0].getAttribute('rel')).toBe('noopener noreferrer');
    expect(talkLinks[1].getAttribute('aria-label')).toBe('1:05:03, endnote 3');

    // No timestamp: the manuscript's own link text.
    const essayLinks = [...items[1].querySelectorAll('a')];
    expect(essayLinks.map((a) => [a.textContent, a.getAttribute('href')])).toEqual([
      ['the primer', 'https://example.com/primer'],
    ]);

    // Unmatched: the API gives no URL, so none is invented.
    expect(items[2].querySelectorAll('a')).toHaveLength(0);
    expect(squash(items[2].textContent)).toContain('2:10');
  });

  it('never makes a link of a URL that is not a web or API address', async () => {
    state.output = output({ citation_count: 1 });
    state.citations = [cite(1, { ...TALK, label: 'x', url: 'javascript:alert(1)' })];
    await mount();
    const section = sources()!;
    expect(section.querySelectorAll('a')).toHaveLength(0);
    expect(squash(section.textContent)).toContain('How tidal storage works');
  });

  it('asks for no citations when the output recorded none', async () => {
    state.output = output({ citation_count: 0 });
    state.citations = [];
    await mount();
    expect(host.querySelector('.reader-body')).not.toBeNull();
    expect(calls).not.toContain('/author/outputs/o1/citations');
    expect(sources()).toBeNull();
  });

  it('says the list could not be loaded instead of failing the page', async () => {
    state.output = output();
    state.citations = 'fail';
    await mount();
    expect(host.querySelector('.reader-body')).not.toBeNull();
    const failed = host.querySelector('section[aria-label="Sources"]');
    expect(squash(failed?.textContent)).toMatch(/could not be loaded/);
  });
});
