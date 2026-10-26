/**
 * T-8.8.1.5: the job page's quick peek frames the report through a blob: URL
 * fetched with the bearer header — no `?token=` in the frame's src or in the
 * new tab — sandboxed, and the URL is revoked when the modal closes.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ReportPeekModal } from '../ReportPeekModal';
import { REPORT_DOCUMENT_CSP, REPORT_FRAME_SANDBOX } from '../../../utils/reportDocument';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getReportMock = vi.fn<(id: string) => Promise<string>>();
vi.mock('../../../services/jobsApi', () => ({
  jobsApi: { getReport: (id: string) => getReportMock(id) },
}));

const REPORT = '<!DOCTYPE html><html><head><title>R</title></head><body><h1>R</h1></body></html>';

let host: HTMLDivElement;
let root: Root;
let blobs: Blob[];
let openSpy: ReturnType<typeof vi.fn>;

function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount(onClose = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <ReportPeekModal jobId="job-1" onClose={onClose} />
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const button = (label: RegExp) =>
  Array.from(host.querySelectorAll('button')).find((b) => label.test(b.textContent ?? '')) as HTMLButtonElement;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  blobs = [];
  URL.createObjectURL = vi.fn((b: Blob | MediaSource) => {
    blobs.push(b as Blob);
    return `blob:http://localhost:5173/r${blobs.length}`;
  });
  URL.revokeObjectURL = vi.fn();
  openSpy = vi.fn(() => null);
  window.open = openSpy as unknown as typeof window.open;
  getReportMock.mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('ReportPeekModal', () => {
  it('frames the header-fetched report as a sandboxed blob: URL and revokes it on close', async () => {
    getReportMock.mockResolvedValue(REPORT);
    await mount();

    expect(getReportMock).toHaveBeenCalledWith('job-1');
    const frame = host.querySelector('iframe')!;
    expect(frame).not.toBeNull();
    expect(frame.getAttribute('src')).toBe('blob:http://localhost:5173/r1');
    expect(frame.getAttribute('src')).not.toMatch(/token/i);
    expect(frame.getAttribute('sandbox')).toBe(REPORT_FRAME_SANDBOX);
    // The framed bytes are the report with scripts blocked.
    const text = await readBlob(blobs[0]);
    expect(text).toContain(`content="${REPORT_DOCUMENT_CSP}"`);
    expect(text).toContain('<h1>R</h1>');

    act(() => root.unmount());
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:http://localhost:5173/r1');
    root = createRoot(host); // for afterEach
  });

  it('opens the same bytes in a new tab under their own URL, never the API route', async () => {
    getReportMock.mockResolvedValue(REPORT);
    await mount();
    act(() => button(/open in new tab/i).click());
    expect(openSpy).toHaveBeenCalledTimes(1);
    const [url, target, features] = openSpy.mock.calls[0];
    expect(url).toBe('blob:http://localhost:5173/r2');
    expect(target).toBe('_blank');
    expect(features).toBe('noopener');
    expect(blobs[1]).toBe(blobs[0]);
  });

  it('waits for the report before offering a frame or a new tab', async () => {
    getReportMock.mockReturnValue(new Promise(() => {}));
    await mount();
    expect(host.querySelector('iframe')).toBeNull();
    expect(host.textContent).toContain('Loading the report');
    expect(button(/open in new tab/i).disabled).toBe(true);
  });

  it('says so when the run has no report', async () => {
    getReportMock.mockRejectedValue(Object.assign(new Error('Not found'), { response: { status: 404 } }));
    await mount();
    expect(host.querySelector('iframe')).toBeNull();
    expect(host.textContent).toContain('This run has no report.');
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
