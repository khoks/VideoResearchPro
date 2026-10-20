/**
 * S-8.1.4: the shelf page's Q&A panel and the scope note on library answers.
 * An empty shelf offers nothing to ask; a question goes to the shelf's own
 * endpoint; a scoped answer in the library history names its shelf (or says
 * the shelf is gone) so it never reads as a library-wide answer.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ShelfQAPanel } from '../ShelfQAPanel';
import { LibraryQAExchangeCard } from '../../qa/LibraryQAExchangeCard';
import type { LibraryQAExchange, LibraryQARequest } from '../../../types/qa';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const documentsMock = vi.fn<(id: string, params?: unknown) => Promise<unknown[]>>();
const questionsMock = vi.fn<(id: string) => Promise<LibraryQAExchange[]>>();
const askMock = vi.fn<(id: string, body: LibraryQARequest) => Promise<LibraryQAExchange>>();
const listMock = vi.fn(async () => [{ id: 's1', name: 'Rates', job_ids: [] }]);

vi.mock('../../../services/shelvesApi', async (orig) => ({
  ...(await orig<typeof import('../../../services/shelvesApi')>()),
  shelvesApi: {
    list: () => listMock(),
    documents: (id: string, params?: unknown) => documentsMock(id, params),
    questions: (id: string) => questionsMock(id),
    ask: (id: string, body: LibraryQARequest) => askMock(id, body),
  },
}));
vi.mock('../../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../notes', () => ({ NotesPanel: () => null }));
vi.mock('../../citation', () => ({ CitationLink: () => null }));

function exchange(id: string, question: string, scope: LibraryQAExchange['scope'] = null): LibraryQAExchange {
  return { id, question, answer: 'An answer.', references: [], created_at: '2026-10-19T00:00:00Z', scope };
}

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function render(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>{node}</MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

function type(el: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  documentsMock.mockReset();
  questionsMock.mockReset();
  askMock.mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('ShelfQAPanel', () => {
  it('offers nothing to ask on a shelf with no sources', async () => {
    documentsMock.mockResolvedValue([]);
    questionsMock.mockResolvedValue([]);
    await render(<ShelfQAPanel shelfId="s1" shelfName="Rates" />);
    expect(host.textContent).toContain('This shelf has no sources yet');
    expect(host.querySelector('textarea')).toBeNull();
    expect(documentsMock).toHaveBeenCalledWith('s1', { limit: 1 });
  });

  it("asks the shelf's own endpoint and shows the answer without a scope note", async () => {
    documentsMock.mockResolvedValue([{ id: 'd1' }]);
    questionsMock.mockResolvedValueOnce([]).mockResolvedValue([exchange('e1', 'What about rates?', { shelf_id: 's1' })]);
    askMock.mockResolvedValue(exchange('e1', 'What about rates?', { shelf_id: 's1' }));
    await render(<ShelfQAPanel shelfId="s1" shelfName="Rates" />);

    const box = host.querySelector('textarea')!;
    type(box, 'What about rates?');
    const submit = Array.from(host.querySelectorAll('button')).find((b) => b.textContent === 'Ask this shelf')!;
    expect(submit.disabled).toBe(false);
    await act(async () => submit.click());
    await flush();

    expect(askMock).toHaveBeenCalledWith('s1', { question: 'What about rates?', answer_language: 'en' });
    expect(host.textContent).toContain('What about rates?');
    expect(host.querySelector('[data-qa-scope]')).toBeNull();
    expect(box.value).toBe('');
  });
});

describe('scope note on library answers', () => {
  it('names the shelf a question was asked on, with a link', async () => {
    await render(<LibraryQAExchangeCard qa={exchange('e1', 'Q', { shelf_id: 's1' })} />);
    const note = host.querySelector('[data-qa-scope]')!;
    expect(note.textContent).toBe('Asked on shelf Rates');
    expect(note.querySelector('a')!.getAttribute('href')).toBe('/shelves/s1');
  });

  it('says so when the shelf is gone, and stays silent for library-wide answers', async () => {
    await render(<LibraryQAExchangeCard qa={exchange('e2', 'Q', { shelf_id: 'gone' })} />);
    expect(host.querySelector('[data-qa-scope]')!.textContent).toBe('Asked on a shelf that no longer exists');
    await render(<LibraryQAExchangeCard qa={exchange('e3', 'Q', null)} />);
    expect(host.querySelector('[data-qa-scope]')).toBeNull();
  });
});
