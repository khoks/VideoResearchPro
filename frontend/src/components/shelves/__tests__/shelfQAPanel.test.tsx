/**
 * S-8.1.4: the shelf page's Q&A panel and the scope note on library answers.
 * An empty shelf offers nothing to ask; a question goes to the shelf's own
 * endpoint; a scoped answer in the library history names its shelf (or says
 * the shelf is gone) so it never reads as a library-wide answer.
 *
 * S-8.13.2: a question goes through the clarify step, as on the library page.
 * The clarify call carries the question and nothing about the shelf; "Confirm
 * & search" sends what the reader typed as `context`, "Skip clarifications"
 * sends none. Clarifying is optional, so when that call fails the question
 * goes to the shelf directly: a shelf ask worked before this step existed.
 * Mutation checks, run by hand on 2026-11-04: dropping the context from `send`
 * fails the "Confirm & search" test; dropping the direct ask fails "asks the
 * shelf directly"; dropping the mounted check fails "asks nothing"; dropping
 * the form's own pending state fails "shows the direct ask running".
 *
 * T-1.15.4.6: the same depth control as the job and library panels. Mutation
 * checks, run by hand on 2026-11-04: `send` dropping `withDepth` fails "sends the
 * picked depth"; `send` not resetting fails "for that one ask"; dropping the
 * select's `disabled` fails "while the answer runs"; dropping the language
 * select's `disabled` fails "holds the language".
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

async function render(node: React.ReactNode, preferred: string | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(['auth', 'me'], { preferred_output_length: preferred });
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

/** The panel on a shelf with a source, before anything is asked. */
async function panel(preferred: string | null = null) {
  documentsMock.mockResolvedValue([{ id: 'd1' }]);
  questionsMock.mockResolvedValue([]);
  await render(<ShelfQAPanel shelfId="s1" shelfName="Rates" />, preferred);
}

/** The panel on a shelf with a source, the question typed and sent to clarify. */
async function clarifyQuestion(question = 'What about rates?') {
  await panel();
  type(host.querySelector('textarea')!, question);
  await press('Ask this shelf');
}

const depthSelect = () => {
  const label = Array.from(host.querySelectorAll('label')).find((l) => l.textContent?.includes('Answer depth'));
  return host.querySelector<HTMLSelectElement>(`[id="${label?.htmlFor}"]`);
};

function pickDepth(value: string) {
  const select = depthSelect()!;
  act(() => {
    select.value = value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
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

describe('ShelfQAPanel: answer depth', () => {
  it('is labelled, starts on Default, and sends nothing when left there', async () => {
    askMock.mockResolvedValue(exchange('e1', 'What about rates?'));
    await panel();
    expect(Array.from(depthSelect()!.options).map((o) => o.textContent)).toEqual([
      'Default',
      'Brief',
      'Standard',
      'Deep',
    ]);
    expect(depthSelect()!.value).toBe('');

    type(host.querySelector('textarea')!, 'What about rates?');
    await press('Ask this shelf');
    await press('Skip clarifications');
    expect(askMock.mock.calls[0][1]).toEqual({ question: 'What about rates?', answer_language: 'en' });
  });

  it('sends the picked depth on Confirm, on Skip and on a direct ask', async () => {
    askMock.mockResolvedValue(exchange('e1', 'What about rates?'));
    const sent = { question: 'What about rates?', answer_language: 'en', output_length: 'deep' };

    await panel();
    pickDepth('deep');
    type(host.querySelector('textarea')!, 'What about rates?');
    await press('Ask this shelf');
    await press('Skip clarifications');
    expect(askMock.mock.calls[0][1]).toEqual(sent);

    pickDepth('deep');
    type(host.querySelector('textarea')!, 'What about rates?');
    await press('Ask this shelf');
    await press('Confirm & search');
    expect(askMock.mock.calls[1][1]).toMatchObject(sent);

    clarifyMock.mockRejectedValue(new Error('clarify is down'));
    pickDepth('deep');
    type(host.querySelector('textarea')!, 'What about rates?');
    await press('Ask this shelf');
    expect(askMock.mock.calls[2][1]).toEqual(sent);
  });

  it('holds a pick for that one ask: it clears when the answer lands', async () => {
    askMock.mockResolvedValue(exchange('e1', 'What about rates?'));
    await panel();
    pickDepth('brief');
    type(host.querySelector('textarea')!, 'What about rates?');
    await press('Ask this shelf');
    await press('Skip clarifications');
    expect(depthSelect()!.value).toBe('');
  });

  it('keeps a pick through a failed ask, for the retry', async () => {
    askMock.mockRejectedValue(new Error('down'));
    await panel();
    pickDepth('brief');
    type(host.querySelector('textarea')!, 'What about rates?');
    await press('Ask this shelf');
    await press('Skip clarifications');
    await press('← Edit');
    expect(depthSelect()!.value).toBe('brief');
  });

  it('cannot change while the answer runs', async () => {
    askMock.mockReturnValue(new Promise(() => undefined));
    clarifyMock.mockRejectedValue(new Error('clarify is down'));
    await panel();
    type(host.querySelector('textarea')!, 'What about rates?');
    await press('Ask this shelf');
    expect(depthSelect()!.disabled).toBe(true);
  });

  it("starts from the account's default depth, and goes back to it after an ask", async () => {
    askMock.mockResolvedValue(exchange('e1', 'What about rates?'));
    await panel('standard');
    expect(depthSelect()!.value).toBe('standard');

    type(host.querySelector('textarea')!, 'What about rates?');
    await press('Ask this shelf');
    await press('Skip clarifications');
    expect(askMock.mock.calls[0][1]).toMatchObject({ output_length: 'standard' });
    expect(depthSelect()!.value).toBe('standard');
  });

  it('lets Default win over the preference, for that ask', async () => {
    askMock.mockResolvedValue(exchange('e1', 'What about rates?'));
    await panel('deep');
    pickDepth('');
    type(host.querySelector('textarea')!, 'What about rates?');
    await press('Ask this shelf');
    await press('Skip clarifications');
    expect(askMock.mock.calls[0][1]).toEqual({ question: 'What about rates?', answer_language: 'en' });
  });
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

  it('asks the shelf directly when the clarify call fails', async () => {
    clarifyMock.mockRejectedValue(new Error('Bad gateway'));
    askMock.mockResolvedValue(exchange('e1', 'What about rates?', { shelf_id: 's1' }));
    await clarifyQuestion();
    expect(askMock).toHaveBeenCalledTimes(1);
    expect(askMock).toHaveBeenCalledWith('s1', { question: 'What about rates?', answer_language: 'en' });
    expect(host.querySelector('textarea')!.value).toBe('');
  });

  it('holds the language while clarify runs: a failed clarify asks with it', async () => {
    clarifyMock.mockReturnValue(new Promise(() => undefined));
    await clarifyQuestion();
    const label = Array.from(host.querySelectorAll('label')).find((l) => l.textContent?.includes('Answer in'));
    expect(host.querySelector<HTMLSelectElement>(`[id="${label?.htmlFor}"]`)!.disabled).toBe(true);
  });

  it('shows the direct ask running', async () => {
    clarifyMock.mockRejectedValue(new Error('Bad gateway'));
    askMock.mockReturnValue(new Promise(() => {}));
    await clarifyQuestion();
    expect(host.textContent).toContain('Searching this shelf and writing the answer…');
    expect(host.querySelector('textarea')!.disabled).toBe(true);
  });

  it('keeps the question when the clarify call and the direct ask both fail', async () => {
    clarifyMock.mockRejectedValue(new Error('Bad gateway'));
    askMock.mockRejectedValue(new Error('Bad gateway'));
    await clarifyQuestion();
    expect(host.querySelector('textarea')!.value).toBe('What about rates?');
    expect(button('Ask this shelf').disabled).toBe(false);
  });

  it('asks nothing when the clarify call fails after the reader has left', async () => {
    let fail: (e: Error) => void = () => {};
    clarifyMock.mockReturnValue(new Promise((_, reject) => { fail = reject; }));
    await clarifyQuestion();
    act(() => root.render(null));
    await act(async () => fail(new Error('Bad gateway')));
    await flush();
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
