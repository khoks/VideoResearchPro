/**
 * The report reader's "Download Markdown" at its production caller.
 *
 * The button fetches `GET /jobs/{id}/report.md` (S-6.1.2) through the axios
 * client, so the bearer header goes with it, and saves the bytes from a
 * blob: URL under the report's title. No URL carries a token (T-8.8.1.5).
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReportBody } from '../../types/report';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const JWT = 'header.payload.signature';
const getMock = vi.fn<(path: string, config?: unknown) => Promise<{ data: Blob }>>(async () => ({
  data: new Blob(['# Research Report: plotting\n'], { type: 'text/markdown' }),
}));
vi.mock('../../services/api', () => ({
  default: {
    get: (path: string, config?: unknown) => getMock(path, config),
    defaults: { baseURL: 'http://localhost:8000/api/v1' },
  },
}));

const report: { body: ReportBody | null } = { body: null };
vi.mock('../../hooks/useReport', () => ({
  useReportBody: () => ({ data: report.body, isLoading: false, error: null }),
}));
vi.mock('../../hooks/useJobs', () => ({ useJobVideos: () => ({ data: [] }) }));
vi.mock('../../hooks/useVideoFrames', () => ({ useCitationStills: () => undefined }));

import { ReportReaderPage } from '../ReportReaderPage';
import { useJobStore } from '../../stores/jobStore';

function body(title: string): ReportBody {
  return {
    job_id: 'j1',
    job_type: 'topic',
    title,
    html: '<h2>Executive Summary</h2><p>Charts are instruments of inference.</p>',
    statistics: null,
    generated_at: '2026-11-04 10:00',
  };
}

let host: HTMLDivElement;
let root: Root;
let saved: Array<{ href: string; download: string }>;

async function flush() {
  for (let i = 0; i < 4; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  let n = 0;
  URL.createObjectURL = vi.fn(() => `blob:http://localhost:5173/m${++n}`);
  URL.revokeObjectURL = vi.fn();
  saved = [];
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    saved.push({ href: this.href, download: this.download });
  });
  getMock.mockClear();
  useJobStore.setState({ toasts: [] });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/reports/j1']}>
          <Routes>
            <Route path="/reports/:jobId" element={<ReportReaderPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
}

const markdownButton = () =>
  Array.from(host.querySelectorAll('button')).find((b) => /Download Markdown|Preparing/.test(b.textContent ?? '')) as
    | HTMLButtonElement
    | undefined;

describe('ReportReaderPage Markdown download', () => {
  it('fetches report.md with the header and saves it from a blob: URL under the title', async () => {
    report.body = body('Research Report: plotting');
    mount();
    expect(markdownButton()).toBeDefined();

    act(() => markdownButton()!.click());
    await flush();

    expect(getMock).toHaveBeenCalledTimes(1);
    const [path, config] = getMock.mock.calls[0];
    expect(path).toBe('/jobs/j1/report.md');
    expect((config as { responseType: string }).responseType).toBe('blob');
    expect(saved).toEqual([{ href: 'blob:http://localhost:5173/m1', download: 'research-report-plotting.md' }]);
    expect(path).not.toContain(JWT);
    expect(saved[0].href).not.toContain('token');
  });

  it('falls back to the server name when the title has no letters to slug', async () => {
    report.body = body('—');
    mount();
    act(() => markdownButton()!.click());
    await flush();
    expect(saved.map((s) => s.download)).toEqual(['report-j1.md']);
  });

  it('disables the button while the file is fetched', async () => {
    report.body = body('Research Report: plotting');
    let release: (v: { data: Blob }) => void = () => {};
    getMock.mockImplementationOnce(() => new Promise((r) => { release = r; }));
    mount();
    act(() => markdownButton()!.click());
    await flush();
    expect(markdownButton()!.disabled).toBe(true);
    expect(markdownButton()!.textContent).toBe('Preparing…');
    // A second click while it waits fetches nothing more.
    act(() => markdownButton()!.click());
    await act(async () => release({ data: new Blob(['x']) }));
    await flush();
    expect(getMock).toHaveBeenCalledTimes(1);
    expect(markdownButton()!.disabled).toBe(false);
    expect(saved).toHaveLength(1);
  });

  it('says so when the file cannot be fetched', async () => {
    report.body = body('Research Report: plotting');
    getMock.mockRejectedValueOnce(Object.assign(new Error('404'), { response: { status: 404 } }));
    mount();
    act(() => markdownButton()!.click());
    await flush();
    expect(saved).toEqual([]);
    expect(useJobStore.getState().toasts.some((t) => /Markdown download/.test(t.message))).toBe(true);
    expect(markdownButton()!.disabled).toBe(false);
  });
});
