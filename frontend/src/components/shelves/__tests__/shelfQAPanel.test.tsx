/**
 * S-8.1.4: the shelf page's Q&A panel and the scope note on library answers.
 * An empty shelf offers nothing to ask; a question goes to the shelf's own
 * endpoint; a scoped answer in the library history names its shelf (or says
 * the shelf is gone) so it never reads as a library-wide answer.
 *
 * S-8.13.2: a question goes through the clarify step, as on the library page.
 * The clarify call carries the question and nothing about the shelf; "Confirm
 * & search" sends what the reader typed as `context`, "Skip clarifications"
 * sends none. Mutation check, run by hand on 2026-11-04: dropping the context
 * from `send` fails the "Confirm & search" test.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ShelfQAPanel } from '../ShelfQAPanel';
import { LibraryQAExchangeCard } from '../../qa/LibraryQAExchangeCard';
import type { ClarifyResponse, LibraryQAExchange, LibraryQARequest } from '../../../types/qa';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const documentsMock = vi.fn<(id: string, params?: unknown) => Promise<unknown[]>>();
const questionsMock = vi.fn<(id: string) => Promise<LibraryQAExchange[]>>();
const askMock = vi.fn<(id: string, body: LibraryQARequest) => Promise<LibraryQAExchange>>();
const listMock = vi.fn(async () => [{ id: 's1', name: 'Rates', job_ids: [] }]);
const clarifyMock = vi.fn<(body: unknown) => Promise<ClarifyResponse>>();

vi.mock('../../../services/shelvesApi', async (orig) => ({
  ...(await orig<typeof import('../../../services/shelvesApi')>()),
  shelvesApi: {
    list: () => listMock(),
    documents: (id: string, params?: unknown) => documentsMock(id, params),
    questions: (id: string) => questionsMock(id),
    ask: (id: string, body: LibraryQARequest) => askMock(id, body),
  },
}));
vi.mock('../../../services/libraryQaApi', () => ({
  libraryQaApi: { clarify: (body: unknown) => clarifyMock(body) },
}));
vi.mock('../../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../notes', () => ({ NotesPanel: () => null }));
vi.mock('../../citation', () => ({ CitationLink: () => null }));
vi.mock('../../savedSearches/PinQuestionButton', () => ({ PinQuestionButton: () => null }));

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

function type(el: HTMLTextAreaElement | HTMLInputElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

const button = (label: string) =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as HTMLButtonElement;

async function press(label: string) {
  await act(async () => button(label).click());
  await flush();
}

/** The panel on a shelf with a source, the question typed and sent to clarify. */
async function clarifyQuestion(question = 'What about rates?') {
  documentsMock.mockResolvedValue([{ id: 'd1' }]);
  questionsMock.mockResolvedValue([]);
  await render(<ShelfQAPanel shelfId="s1" shelfName="Rates" />);
  type(host.querySelector('textarea')!, question);
  await press('Ask this shelf');
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  documentsMock.mockReset();
  questionsMock.mockReset();
  askMock.mockReset();
  clarifyMock.mockReset();
  clarifyMock.mockResolvedValue({
    interpretation: 'You want the rate moves since 2024.',
    clarifications: ['Which central bank?', 'Over what period?'],
  });
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

    type(host.querySelector('textarea')!, 'What about rates?');
    expect(button('Ask this shelf').disabled).toBe(false);
    await press('Ask this shelf');
    await press('Skip clarifications');

    expect(askMock).toHaveBeenCalledWith('s1', { question: 'What about rates?', answer_language: 'en' });
    expect(host.textContent).toContain('What about rates?');
    expect(host.querySelector('[data-qa-scope]')).toBeNull();
    expect(host.querySelector('textarea')!.value).toBe('');
  });

  it('runs the clarify step first, sending only the question', async () => {
    await clarifyQuestion();
    expect(clarifyMock).toHaveBeenCalledTimes(1);
    expect(clarifyMock).toHaveBeenCalledWith({ question: 'What about rates?' });
    expect(askMock).not.toHaveBeenCalled();
    expect(host.textContent).toContain('You want the rate moves since 2024.');
    expect(host.textContent).toContain('Which central bank?');
    expect(host.querySelector('textarea')).toBeNull();
  });

  it('"Confirm & search" sends the interpretation and the answered clarifications as context', async () => {
    askMock.mockResolvedValue(exchange('e1', 'What about rates?', { shelf_id: 's1' }));
    await clarifyQuestion();
    type(host.querySelector<HTMLInputElement>('input[placeholder="Your answer (optional)"]')!, 'The RBI');
    await press('Confirm & search');

    expect(askMock).toHaveBeenCalledTimes(1);
    expect(askMock).toHaveBeenCalledWith('s1', {
      question: 'What about rates?',
      answer_language: 'en',
      context: 'My interpretation: You want the rate moves since 2024.\n\nWhich central bank?\nThe RBI',
    });
    expect(host.querySelector('textarea')!.value).toBe('');
  });

  it('"Edit" goes back to the question, which it keeps, and asks nothing', async () => {
    await clarifyQuestion();
    await press('← Edit');
    expect(host.querySelector('textarea')!.value).toBe('What about rates?');
    expect(askMock).not.toHaveBeenCalled();
  });

  it('keeps the question when the clarify call fails', async () => {
    clarifyMock.mockRejectedValue(new Error('Bad gateway'));
    await clarifyQuestion();
    expect(host.querySelector('textarea')!.value).toBe('What about rates?');
    expect(askMock).not.toHaveBeenCalled();
  });

  it('keeps the step and what was typed when the ask fails', async () => {
    askMock.mockRejectedValue(new Error('Bad gateway'));
    await clarifyQuestion();
    const answer = host.querySelector<HTMLInputElement>('input[placeholder="Your answer (optional)"]')!;
    type(answer, 'The RBI');
    await press('Confirm & search');
    expect(host.querySelector<HTMLInputElement>('input[placeholder="Your answer (optional)"]')!.value).toBe('The RBI');
    expect(button('Confirm & search').disabled).toBe(false);
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
