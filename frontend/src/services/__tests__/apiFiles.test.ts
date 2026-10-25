/**
 * T-8.8.1.5: API files reach the browser as blob: URLs fetched with the
 * bearer header, never as links carrying the JWT. The helpers create each
 * URL, hand it over, and revoke it.
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
  downloadApiFile,
  isApiUrl,
  openApiFile,
  openApiLink,
  openBlobInNewTab,
  saveBlob,
  splitApiUrl,
} from '../apiFiles';
import { EXPORT_FILES, exportsApi, type ExportFile } from '../exportsApi';
import { libraryApi } from '../libraryApi';

let created: string[];
let openSpy: ReturnType<typeof vi.fn>;
let clicked: Array<{ href: string; download: string }>;

async function settle() {
  for (let i = 0; i < 3; i++) await Promise.resolve();
}

beforeEach(() => {
  vi.useFakeTimers();
  created = [];
  let n = 0;
  URL.createObjectURL = vi.fn(() => {
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
    await openApiFile('/api/v1/library/pdf/abc.pdf#page=3');
    expect(getMock).toHaveBeenCalledWith('/library/pdf/abc.pdf', { responseType: 'blob' });
    expect(openSpy).toHaveBeenCalledWith(`${created[0]}#page=3`, '_blank', 'noopener');
  });

  it('the Library row’s PDF button goes through the same path', async () => {
    await libraryApi.openPdf('/api/v1/library/pdf/abc.pdf');
    expect(getMock).toHaveBeenCalledWith('/library/pdf/abc.pdf', { responseType: 'blob' });
    expect(openSpy).toHaveBeenCalledWith(created[0], '_blank', 'noopener');
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

describe('openApiLink', () => {
  const event = (button = 0) => ({ button, preventDefault: vi.fn() });

  it('takes a click on an API file and opens it as a blob', async () => {
    const e = event();
    expect(openApiLink(e, '/api/v1/library/pdf/abc.pdf#page=2')).toBe(true);
    expect(e.preventDefault).toHaveBeenCalled();
    await settle();
    expect(openSpy).toHaveBeenCalledWith(`${created[0]}#page=2`, '_blank', 'noopener');
  });

  it('takes a middle click too, but leaves a right click and the open web alone', () => {
    expect(openApiLink(event(1), '/api/v1/library/pdf/abc.pdf')).toBe(true);
    const right = event(2);
    expect(openApiLink(right, '/api/v1/library/pdf/abc.pdf')).toBe(false);
    expect(right.preventDefault).not.toHaveBeenCalled();
    const web = event();
    expect(openApiLink(web, 'https://www.youtube.com/watch?v=abc')).toBe(false);
    expect(web.preventDefault).not.toHaveBeenCalled();
  });

  it('reports a failed fetch', async () => {
    getMock.mockRejectedValueOnce(new Error('404'));
    const onError = vi.fn();
    openApiLink(event(), '/api/v1/library/pdf/gone.pdf', onError);
    await settle();
    expect(onError).toHaveBeenCalled();
    expect(openSpy).not.toHaveBeenCalled();
  });
});
