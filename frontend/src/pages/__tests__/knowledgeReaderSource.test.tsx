/**
 * T-8.8.1.5 at the knowledge reader: "Open the source" on an uploaded PDF
 * fetches the bytes with the bearer header and opens a blob: URL, because
 * the PDF's stored url is the API's serve route, which 401s as a plain tab.
 * A source on the open web still opens as itself.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import http from '../../services/api';
import { stubNewTabs, type FakeTab } from '../../services/__tests__/newTab';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let artifact: Record<string, unknown>;
vi.mock('../../hooks/useKnowledge', () => ({
  useKnowledge: () => ({ data: artifact, isLoading: false, error: null }),
}));

import { KnowledgeReaderPage } from '../KnowledgeReaderPage';

const BASE = {
  video_id: null,
  document_id: 'doc-1',
  title: 'Annual report',
  channel_name: '',
  published_at: null,
  knowledge_extracted_at: '2026-10-20T10:00:00',
  knowledge_report_md: '# Annual report\n\n## Findings\n\nRevenue rose.',
  topics: [],
  concepts: [],
  events: [],
  facts: [],
};

let host: HTMLDivElement;
let root: Root;
let get: ReturnType<typeof vi.spyOn>;
let open: ReturnType<typeof vi.fn>;
let tabs: FakeTab[];
const saved = { create: URL.createObjectURL, revoke: URL.revokeObjectURL, open: window.open };

function mount() {
  act(() =>
    root.render(
      <MemoryRouter initialEntries={['/knowledge/doc-1']}>
        <Routes>
          <Route path="/knowledge/:videoId" element={<KnowledgeReaderPage />} />
        </Routes>
      </MemoryRouter>,
    ),
  );
}

const openSource = () =>
  Array.from(host.querySelectorAll('button')).find((b) => /open the source/i.test(b.textContent ?? '')) as HTMLButtonElement;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  get = vi.spyOn(http, 'get').mockResolvedValue({ data: new Blob(['%PDF']) } as never);
  URL.createObjectURL = vi.fn(() => 'blob:http://localhost:5173/k1');
  URL.revokeObjectURL = vi.fn();
  ({ open, tabs } = stubNewTabs());
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  get.mockRestore();
  URL.createObjectURL = saved.create;
  URL.revokeObjectURL = saved.revoke;
  window.open = saved.open;
});

describe('KnowledgeReaderPage: Open the source', () => {
  it('opens an uploaded PDF as a blob fetched with the header', async () => {
    artifact = { ...BASE, source_type: 'pdf', url: '/api/v1/library/pdf/abc.pdf' };
    mount();
    await act(async () => {
      openSource().click();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(get).toHaveBeenCalledWith('/library/pdf/abc.pdf', { responseType: 'blob' });
    expect(open).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledWith('', '_blank');
    expect(tabs[0].location.href).toBe('blob:http://localhost:5173/k1');
  });

  it('opens a source on the open web as itself', async () => {
    artifact = { ...BASE, source_type: 'video', url: 'https://www.youtube.com/watch?v=abc' };
    mount();
    await act(async () => {
      openSource().click();
    });
    expect(get).not.toHaveBeenCalled();
    expect(open).toHaveBeenCalledWith('https://www.youtube.com/watch?v=abc', '_blank', 'noopener,noreferrer');
  });
});
