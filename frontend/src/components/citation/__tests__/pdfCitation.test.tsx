/**
 * E-1.8 / T-8.8.1.5: a PDF citation's permalink is the API's serve route,
 * which takes the bearer header only, so followed as a link it 401s in the
 * new tab. Clicking the citation fetches the PDF with the header and opens
 * its blob: URL on the cited page. Links to the open web stay plain links.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Reference } from '../../../types/qa';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getMock = vi.fn<(path: string, config?: unknown) => Promise<{ data: Blob }>>(async () => ({ data: new Blob(['%PDF-1.7'], { type: 'application/pdf' }) }));
vi.mock('../../../services/api', () => ({
  default: {
    get: (path: string, config?: unknown) => getMock(path, config),
    defaults: { baseURL: 'http://localhost:8000/api/v1' },
  },
}));

import { CitationLink } from '../CitationLink';
import { useJobStore } from '../../../stores/jobStore';

const pdf = {
  source_type: 'pdf',
  thread_title: 'Annual report',
  page_number: 3,
  permalink: '/api/v1/library/pdf/abc123.pdf#page=3',
  quote: '',
} as unknown as Reference;

const article = {
  source_type: 'article',
  thread_title: 'An essay',
  permalink: 'https://example.org/essay',
  quote: '',
} as unknown as Reference;

let host: HTMLDivElement;
let root: Root;
let openSpy: ReturnType<typeof vi.fn>;

async function flush() {
  for (let i = 0; i < 4; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

function render(reference: Reference) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <CitationLink reference={reference} />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  return host.querySelector('a') as HTMLAnchorElement;
}

function click(a: HTMLAnchorElement, init: MouseEventInit = {}): MouseEvent {
  const e = new MouseEvent(init.button === 1 ? 'auxclick' : 'click', { bubbles: true, cancelable: true, ...init });
  act(() => {
    a.dispatchEvent(e);
  });
  return e;
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  URL.createObjectURL = vi.fn(() => 'blob:http://localhost:5173/pdf1');
  URL.revokeObjectURL = vi.fn();
  openSpy = vi.fn(() => null);
  window.open = openSpy as unknown as typeof window.open;
  getMock.mockClear();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('a PDF citation', () => {
  it('fetches the PDF with the header and opens the blob on the cited page', async () => {
    const a = render(pdf);
    expect(a.textContent).toBe('Annual report · p. 3');
    const e = click(a);
    expect(e.defaultPrevented).toBe(true); // the 401-ing navigation never happens
    await flush();
    expect(getMock).toHaveBeenCalledWith('/library/pdf/abc123.pdf', { responseType: 'blob' });
    expect(openSpy).toHaveBeenCalledWith('blob:http://localhost:5173/pdf1#page=3', '_blank', 'noopener');
  });

  it('handles a middle click the same way', async () => {
    const e = click(render(pdf), { button: 1 });
    expect(e.defaultPrevented).toBe(true);
    await flush();
    expect(openSpy).toHaveBeenCalledWith('blob:http://localhost:5173/pdf1#page=3', '_blank', 'noopener');
  });

  it('says so when the PDF is gone', async () => {
    getMock.mockRejectedValueOnce(Object.assign(new Error('Not found'), { response: { status: 404 } }));
    click(render(pdf));
    await flush();
    expect(openSpy).not.toHaveBeenCalled();
    expect(useJobStore.getState().toasts.some((t) => /could not fetch the cited file/i.test(t.message))).toBe(true);
  });
});

describe('a citation to the open web', () => {
  it('stays a plain link', async () => {
    const a = render(article);
    const e = click(a);
    expect(e.defaultPrevented).toBe(false);
    await flush();
    expect(getMock).not.toHaveBeenCalled();
    expect(a.getAttribute('href')).toBe('https://example.org/essay');
  });
});
