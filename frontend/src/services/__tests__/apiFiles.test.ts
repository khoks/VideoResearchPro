/**
 * T-8.8.1.5: API files reach the browser as blob: URLs fetched with the
 * bearer header, never as links carrying the JWT. The helpers create each
 * URL, hand it over, and revoke it. Only the routes listed as openable are
 * fetched for a tab, re-wrapped in their own type, and the tab is opened
 * inside the click so the browser does not block it after the download.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const getMock = vi.fn<(path: string, config?: unknown) => Promise<{ data: Blob }>>(async () => ({ data: new Blob(['bytes'], { type: 'application/pdf' }) }));
vi.mock('../api', () => ({
  default: {
    get: (path: string, config?: unknown) => getMock(path, config),
    defaults: { baseURL: 'http://localhost:8000/api/v1' },
  },
}));

import {
  BLOB_URL_TTL_MS,
  TabBlockedError,
  downloadApiFile,
  isApiUrl,
  openApiFile,
  openApiLink,
  openBlobInNewTab,
  openableApiFile,
  saveBlob,
  splitApiUrl,
} from '../apiFiles';
import { EXPORT_FILES, exportsApi, type ExportFile } from '../exportsApi';
import { libraryApi } from '../libraryApi';
import { stubNewTabs } from './newTab';

let created: string[];
let wrapped: Blob[];
let openSpy: ReturnType<typeof vi.fn>;
let clicked: Array<{ href: string; download: string }>;

async function settle() {
  for (let i = 0; i < 3; i++) await Promise.resolve();
}

beforeEach(() => {
  vi.useFakeTimers();
  created = [];
  wrapped = [];
  let n = 0;
  URL.createObjectURL = vi.fn((b: Blob | MediaSource) => {
    wrapped.push(b as Blob);
    const url = `blob:http://localhost:5173/u${++n}`;
    created.push(url);
    return url;
  });
  URL.revokeObjectURL = vi.fn();
  openSpy = vi.fn(() => null);
  window.open = openSpy as unknown as typeof window.open;
  clicked = [];
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push({ href: this.href, download: this.download });
  });
  getMock.mockClear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('splitApiUrl', () => {
  it('strips the API prefix and keeps the fragment apart', () => {
    expect(splitApiUrl('/api/v1/library/pdf/abc.pdf#page=3')).toEqual({ path: '/library/pdf/abc.pdf', fragment: '#page=3' });
    expect(splitApiUrl('/exports/notes.md')).toEqual({ path: '/exports/notes.md', fragment: '' });
    expect(splitApiUrl('http://localhost:8000/api/v1/library/pdf/abc.pdf?x=1#page=2')).toEqual({
      path: '/library/pdf/abc.pdf?x=1',
      fragment: '#page=2',
    });
  });
});

describe('isApiUrl', () => {
  it('is true for this app’s API and false for the open web', () => {
    expect(isApiUrl('/api/v1/library/pdf/abc.pdf#page=3')).toBe(true);
    expect(isApiUrl(`${window.location.origin}/api/v1/library/pdf/abc.pdf`)).toBe(true);
    expect(isApiUrl('http://localhost:8000/api/v1/library/pdf/abc.pdf')).toBe(true);
    expect(isApiUrl('https://www.youtube.com/watch?v=abc&t=12')).toBe(false);
    expect(isApiUrl('https://evil.example/api/v1/library/pdf/abc.pdf')).toBe(false);
    expect(isApiUrl('/library?document=1')).toBe(false);
    expect(isApiUrl(null)).toBe(false);
  });
});

describe('openableApiFile', () => {
  it('names an uploaded PDF, wherever its URL is written', () => {
    expect(openableApiFile('/api/v1/library/pdf/abc.pdf#page=3')).toEqual({
      path: '/library/pdf/abc.pdf',
      fragment: '#page=3',
      type: 'application/pdf',
    });
    expect(openableApiFile('http://localhost:8000/api/v1/library/pdf/abc.pdf?x=1')).toEqual({
      path: '/library/pdf/abc.pdf?x=1',
      fragment: '',
      type: 'application/pdf',
    });
  });

  it('refuses every other API route, dot segments resolved first', () => {
    expect(openableApiFile('/api/v1/jobs/x/report')).toBeNull();
    expect(openableApiFile('/api/v1/exports/notes.md')).toBeNull();
    expect(openableApiFile('/api/v1/videos/v1/frames/f1/image')).toBeNull();
    expect(openableApiFile('/api/v1/library/pdf/../../jobs/x/report')).toBeNull();
    expect(openableApiFile('/api/v1/library/pdf/%2e%2e/%2E%2E/jobs/x/report')).toBeNull();
    expect(openableApiFile('/api/v1/library/pdf/..\\..\\jobs/x/report')).toBeNull();
    expect(openableApiFile('https://evil.example/api/v1/library/pdf/abc.pdf')).toBeNull();
    expect(openableApiFile(undefined)).toBeNull();
  });
});

describe('blob URL lifecycle', () => {
  it('opens bytes in a new tab with the fragment, then revokes the URL', () => {
    openBlobInNewTab(new Blob(['x']), '#page=4');
    expect(openSpy).toHaveBeenCalledWith(`${created[0]}#page=4`, '_blank', 'noopener');
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(BLOB_URL_TTL_MS);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[0]);
  });

  it('saves bytes through an <a download>, then revokes the URL', () => {
    saveBlob(new Blob(['x']), 'notes.md');
    expect(clicked).toEqual([{ href: created[0], download: 'notes.md' }]);
    expect(document.querySelector('a[download]')).toBeNull(); // the anchor is cleaned up
    vi.advanceTimersByTime(BLOB_URL_TTL_MS);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[0]);
  });
});

describe('fetching with the header', () => {
  it('a PDF citation fetches the bytes as a blob and opens them on their page', async () => {
    const { tabs } = stubNewTabs();
    await openApiFile('/api/v1/library/pdf/abc.pdf#page=3');
    expect(getMock).toHaveBeenCalledWith('/library/pdf/abc.pdf', { responseType: 'blob' });
    expect(tabs).toHaveLength(1);
    expect(tabs[0].location.href).toBe(`${created[0]}#page=3`);
    vi.advanceTimersByTime(BLOB_URL_TTL_MS);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(created[0]);
  });

  it('the Library row’s PDF button goes through the same path', async () => {
    const { tabs } = stubNewTabs();
    await libraryApi.openPdf('/api/v1/library/pdf/abc.pdf');
    expect(getMock).toHaveBeenCalledWith('/library/pdf/abc.pdf', { responseType: 'blob' });
    expect(tabs[0].location.href).toBe(created[0]);
  });

  it('downloads save under the given name', async () => {
    await downloadApiFile('/exports/notes.md', 'notes.md');
    expect(clicked).toEqual([{ href: created[0], download: 'notes.md' }]);
  });

  it('every export is fetched with the header — no token in any URL', async () => {
    const files = Object.keys(EXPORT_FILES) as ExportFile[];
    expect(files).toHaveLength(6);
    for (const file of files) await exportsApi.download(file);
    expect(getMock.mock.calls.map((c) => c[0])).toEqual([
      '/exports/qa-dataset/openai.jsonl',
      '/exports/qa-dataset/tuple.jsonl',
      '/exports/knowledge-dataset/openai.jsonl',
      '/exports/knowledge-dataset/tuple.jsonl',
      '/exports/notes.jsonl',
      '/exports/notes.md',
    ]);
    for (const call of getMock.mock.calls) {
      expect(call[0]).not.toMatch(/token/i);
      expect(call[1]).toEqual({ responseType: 'blob' });
    }
    expect(clicked.map((c) => c.download)).toEqual(files.map((f) => EXPORT_FILES[f].filename));
    expect(clicked.every((c) => c.href.startsWith('blob:'))).toBe(true);
    vi.advanceTimersByTime(BLOB_URL_TTL_MS);
    expect(vi.mocked(URL.revokeObjectURL).mock.calls.map((c) => c[0])).toEqual(created);
  });
});

describe('the tab opens inside the click', () => {
  it('before the download resolves, with the opener cut', async () => {
    const { open, tabs } = stubNewTabs();
    let deliver!: (r: { data: Blob }) => void;
    getMock.mockImplementationOnce(() => new Promise((r) => (deliver = r)));
    const pending = openApiFile('/api/v1/library/pdf/abc.pdf#page=7');
    // Synchronously, in the click's own task: a later window.open is blocked
    // once the user activation lapses, and with 'noopener' it returns null.
    expect(open).toHaveBeenCalledWith('', '_blank');
    expect(tabs[0].opener).toBeNull();
    expect(tabs[0].location.href).toBe('about:blank');
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    deliver({ data: new Blob(['%PDF-1.7'], { type: 'application/pdf' }) });
    await pending;
    expect(open).toHaveBeenCalledTimes(1);
    expect(tabs[0].location.href).toBe(`${created[0]}#page=7`);
  });

  it('a blocked tab is reported, and nothing is fetched', async () => {
    window.open = vi.fn(() => null) as unknown as typeof window.open;
    await expect(openApiFile('/api/v1/library/pdf/abc.pdf')).rejects.toBeInstanceOf(TabBlockedError);
    expect(getMock).not.toHaveBeenCalled();

    const onError = vi.fn();
    expect(openApiLink({ button: 0, preventDefault: vi.fn() }, '/api/v1/library/pdf/abc.pdf', onError)).toBe(true);
    await settle();
    expect(onError).toHaveBeenCalledWith(expect.any(TabBlockedError));
  });

  it('a failed download closes the tab it opened', async () => {
    const { tabs } = stubNewTabs();
    getMock.mockRejectedValueOnce(new Error('404'));
    await expect(openApiFile('/api/v1/library/pdf/gone.pdf')).rejects.toThrow('404');
    expect(tabs[0].closed).toBe(true);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('a tab the reader closed while waiting gets nothing', async () => {
    const { tabs } = stubNewTabs();
    let deliver!: (r: { data: Blob }) => void;
    getMock.mockImplementationOnce(() => new Promise((r) => (deliver = r)));
    const pending = openApiFile('/api/v1/library/pdf/abc.pdf');
    tabs[0].close();
    deliver({ data: new Blob(['%PDF-1.7'], { type: 'application/pdf' }) });
    await pending;
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});

describe('only openable files, as their own type', () => {
  it('a PDF route that answers with HTML still opens as a PDF', async () => {
    stubNewTabs();
    getMock.mockResolvedValueOnce({ data: new Blob(['<script>steal()</script>'], { type: 'text/html' }) });
    await openApiFile('/api/v1/library/pdf/abc.pdf');
    expect(wrapped).toHaveLength(1);
    expect(wrapped[0].type).toBe('application/pdf');
  });

  it('openApiFile refuses any other API route without fetching it', async () => {
    const { open } = stubNewTabs();
    await expect(openApiFile('/api/v1/jobs/x/report')).rejects.toThrow();
    await expect(openApiFile('/api/v1/library/pdf/../../jobs/x/report')).rejects.toThrow();
    expect(open).not.toHaveBeenCalled();
    expect(getMock).not.toHaveBeenCalled();
  });
});

describe('openApiLink', () => {
  const event = (button = 0) => ({ button, preventDefault: vi.fn() });

  it('takes a click on an API file and opens it as a blob', async () => {
    const { tabs } = stubNewTabs();
    const e = event();
    expect(openApiLink(e, '/api/v1/library/pdf/abc.pdf#page=2')).toBe(true);
    expect(e.preventDefault).toHaveBeenCalled();
    await settle();
    expect(tabs[0].location.href).toBe(`${created[0]}#page=2`);
  });

  it('takes a middle click too, but leaves a right click and the open web alone', () => {
    stubNewTabs();
    expect(openApiLink(event(1), '/api/v1/library/pdf/abc.pdf')).toBe(true);
    const right = event(2);
    expect(openApiLink(right, '/api/v1/library/pdf/abc.pdf')).toBe(false);
    expect(right.preventDefault).not.toHaveBeenCalled();
    const web = event();
    expect(openApiLink(web, 'https://www.youtube.com/watch?v=abc')).toBe(false);
    expect(web.preventDefault).not.toHaveBeenCalled();
  });

  it('leaves a model-written link to any other API route to the browser', async () => {
    const { open } = stubNewTabs();
    for (const href of [
      '/api/v1/jobs/x/report',
      `${window.location.origin}/api/v1/jobs/x/report`,
      '/api/v1/library/pdf/../../jobs/x/report',
    ]) {
      const e = event();
      expect(openApiLink(e, href)).toBe(false);
      expect(e.preventDefault).not.toHaveBeenCalled();
    }
    await settle();
    expect(getMock).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('reports a failed fetch', async () => {
    const { tabs } = stubNewTabs();
    getMock.mockRejectedValueOnce(new Error('404'));
    const onError = vi.fn();
    openApiLink(event(), '/api/v1/library/pdf/gone.pdf', onError);
    await settle();
    expect(onError).toHaveBeenCalled();
    expect(tabs[0].closed).toBe(true);
  });
});
