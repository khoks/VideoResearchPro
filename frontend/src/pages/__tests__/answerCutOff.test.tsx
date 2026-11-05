/**
 * T-1.15.4.5 on the pages: an answer that stopped at its token budget says so.
 *
 * The real hooks run on the library page and the shelf panel, with only the HTTP
 * layer replaced, so this is the whole path: the reply carries `answer_cut_off`,
 * the history refetch does not, and the card still shows the note because the
 * hook kept it (`qaCutOffStore`). The job page's two ask paths are pinned on its
 * hooks below, and its card in `jobQADepth.test.tsx`.
 *
 * Mutation checks, run by hand on 2026-11-04:
 * - any hook dropping `rememberCutOff` fails its "says so" test;
 * - `AnswerCutOffNote` keeping the offer at Deep fails "note alone";
 * - the offer sending an ask fails "fills the composer";
 * - `askAtDeep` not picking Deep fails the same test;
 * - `asksHere` always true fails "a shelf's answer", "another source" and "while
 *   the page is on one source";
 * - `asksHere` dropping its shelf check fails "a shelf's answer";
 * - `asksHere` comparing nothing but "no source" fails "on that same source";
 * - `askAgain` not reading `asking` fails "while clarify runs".
 */
import { act, useEffect, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LibraryQAExchange, LibraryQARequest, QAExchange, QARequest } from '../../types/qa';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const askMock = vi.fn<(body: LibraryQARequest) => Promise<unknown>>();
const historyMock = vi.fn<() => Promise<LibraryQAExchange[]>>();
const clarifyMock = vi.fn();
const shelfAskMock = vi.fn<(id: string, body: LibraryQARequest) => Promise<unknown>>();
const shelfQuestionsMock = vi.fn<(id: string) => Promise<LibraryQAExchange[]>>();
const jobAskMock = vi.fn<(jobId: string, body: QARequest) => Promise<QAExchange>>();

vi.mock('../../services/libraryQaApi', () => ({
  libraryQaApi: {
    getHistory: () => historyMock(),
    ask: (body: LibraryQARequest) => askMock(body),
    clarify: (body: unknown) => clarifyMock(body),
  },
}));
vi.mock('../../services/shelvesApi', async (orig) => ({
  ...(await orig<typeof import('../../services/shelvesApi')>()),
  shelvesApi: {
    list: async () => [{ id: 's1', name: 'Rates', job_ids: [] }],
    documents: async () => [{ id: 'd1' }],
    questions: (id: string) => shelfQuestionsMock(id),
    ask: (id: string, body: LibraryQARequest) => shelfAskMock(id, body),
  },
}));
vi.mock('../../services/qaApi', () => ({
  qaApi: {
    ask: (jobId: string, body: QARequest) => jobAskMock(jobId, body),
    getHistory: async () => [],
    clarify: vi.fn(),
  },
}));
vi.mock('../../services/suggestionsApi', () => ({
  suggestionsApi: {
    get: async () => ({ context: 'library', cached: false, generated: false, suggestions: [] }),
    feedback: async () => undefined,
  },
}));
vi.mock('../../hooks/useLibrary', () => ({ useLibraryVideos: () => ({ data: [{ id: 'd1' }], isSuccess: true }) }));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../components/notes', () => ({ NotesPanel: () => null }));
vi.mock('../../components/citation', () => ({ CitationLink: () => null }));
vi.mock('../../components/savedSearches/PinQuestionButton', () => ({ PinQuestionButton: () => null }));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));

import { LibraryQAPage } from '../LibraryQAPage';
import { ShelfQAPanel } from '../../components/shelves/ShelfQAPanel';
import { AnswerCutOffNote } from '../../components/qa/AnswerCutOffNote';
import { useAskQuestion, useAskQuestionStreaming } from '../../hooks/useQA';
import { useQACutOffStore } from '../../stores/qaCutOffStore';

const QUESTION = 'What changed in rates?';
const NOTE = 'This answer stopped at its length limit';
const OFFER = 'Ask again at Deep depth';
/** How the knowledge drawer lands on this page: asking about one source. */
const ONE_SOURCE = { pathname: '/library/qa', state: { question: 'Seed', source: { id: 'd1', title: 'The RBI memo' } } };

function stored(id: string): LibraryQAExchange {
  return { id, question: QUESTION, answer: 'The RBI cut', references: [], created_at: '2026-11-04T00:00:00Z', scope: null };
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

async function render(node: ReactNode, entry: string | { pathname: string; state: unknown } = '/library/qa') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  qc.setQueryData(['auth', 'me'], { preferred_output_length: null });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="*" element={node} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
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

const libraryInput = () => host.querySelector<HTMLInputElement>('input[aria-label="Question"]')!;
const depthSelect = () => host.querySelector<HTMLSelectElement>('select[aria-label="Answer depth"]')!;

function pickDepth(value: string) {
  const select = depthSelect();
  act(() => {
    select.value = value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

async function submitQuestion() {
  await act(async () => {
    host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
}

/** One card in the history, whose answer this session saw being cut. */
function cutCard(scope: LibraryQAExchange['scope']) {
  historyMock.mockResolvedValue([{ ...stored('e1'), scope }]);
  useQACutOffStore.getState().note('e1', null);
}

/** Ask on the library page; the reply is `reply`, the refetch a stored row. */
async function askLibrary(reply: Partial<LibraryQAExchange>, depth?: string) {
  historyMock.mockResolvedValueOnce([]).mockResolvedValue([stored('e1')]);
  askMock.mockResolvedValue({ ...stored('e1'), ...reply });
  await render(<LibraryQAPage />);
  if (depth) pickDepth(depth);
  type(libraryInput(), QUESTION);
  await submitQuestion();
  await press('Skip clarifications');
}

beforeEach(() => {
  useQACutOffStore.setState({ answers: {} });
  clarifyMock.mockReset();
  clarifyMock.mockResolvedValue({ interpretation: 'You mean the RBI.', clarifications: ['Which year?'] });
  askMock.mockReset();
  historyMock.mockReset();
  shelfAskMock.mockReset();
  shelfQuestionsMock.mockReset();
  jobAskMock.mockReset();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe('library Q&A', () => {
  it('says so on the card, though the refetched history knows nothing of it', async () => {
    await askLibrary({ answer_cut_off: true });
    expect(historyMock).toHaveBeenCalledTimes(2);
    expect(host.querySelector('#exchange-e1')!.textContent).toContain(NOTE);
    expect(host.querySelector('#exchange-e1 [data-answer-cut-off]')!.getAttribute('role')).toBe('note');
  });

  it('shows nothing for a finished answer', async () => {
    await askLibrary({ answer_cut_off: false });
    expect(host.querySelector('[data-answer-cut-off]')).toBeNull();
  });

  it('shows nothing for an older answer, about which nothing is known', async () => {
    historyMock.mockResolvedValue([stored('old')]);
    await render(<LibraryQAPage />);
    expect(host.textContent).toContain('The RBI cut');
    expect(host.querySelector('[data-answer-cut-off]')).toBeNull();
  });

  it('fills the composer at Deep and spends nothing', async () => {
    await askLibrary({ answer_cut_off: true });
    expect(libraryInput().value).toBe('');
    await press('Ask again at Deep depth');

    expect(libraryInput().value).toBe(QUESTION);
    expect(depthSelect().value).toBe('deep');
    expect(askMock).toHaveBeenCalledTimes(1);
    expect(clarifyMock).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(libraryInput());
  });

  it('gives an answer asked at Deep the note alone', async () => {
    await askLibrary({ answer_cut_off: true }, 'deep');
    expect(host.textContent).toContain(NOTE);
    expect(button('Ask again at Deep depth')).toBeUndefined();
  });

  it('offers Deep to an answer asked at Standard, not the next step up', async () => {
    await askLibrary({ answer_cut_off: true }, 'standard');
    expect(button('Ask again at Deep depth')).toBeDefined();
  });

  it("gives a shelf's answer the note alone: this page cannot ask over a shelf", async () => {
    cutCard({ shelf_id: 's1' });
    await render(<LibraryQAPage />);
    expect(host.querySelector('#exchange-e1')!.textContent).toContain(NOTE);
    expect(host.querySelector('[data-qa-scope]')!.textContent).toContain('Asked on shelf');
    expect(button(OFFER)).toBeUndefined();
  });

  it("gives a shelf's answer the note alone even when it also named this page's source", async () => {
    cutCard({ shelf_id: 's1', document_id: 'd1' });
    await render(<LibraryQAPage />, ONE_SOURCE);
    expect(host.querySelector('#exchange-e1')!.textContent).toContain(NOTE);
    expect(button(OFFER)).toBeUndefined();
  });

  it("gives one source's answer the note alone on the whole library: the ask would widen", async () => {
    cutCard({ document_id: 'd1' });
    await render(<LibraryQAPage />);
    expect(host.querySelector('#exchange-e1')!.textContent).toContain(NOTE);
    expect(button(OFFER)).toBeUndefined();
  });

  it("gives another source's answer the note alone", async () => {
    cutCard({ document_id: 'd2' });
    await render(<LibraryQAPage />, ONE_SOURCE);
    expect(button(OFFER)).toBeUndefined();
  });

  it('offers it on that same source, and the ask stays on the source', async () => {
    cutCard({ document_id: 'd1' });
    askMock.mockResolvedValue(stored('e2'));
    await render(<LibraryQAPage />, ONE_SOURCE);
    await press(OFFER);
    expect(libraryInput().value).toBe(QUESTION);

    await submitQuestion();
    await press('Skip clarifications');
    expect(askMock).toHaveBeenCalledTimes(1);
    expect(askMock).toHaveBeenCalledWith({
      question: QUESTION,
      answer_language: 'en',
      document_id: 'd1',
      output_length: 'deep',
    });
  });

  it('takes the offer back when the reader leaves that source', async () => {
    cutCard({ document_id: 'd1' });
    await render(<LibraryQAPage />, ONE_SOURCE);
    expect(button(OFFER)).toBeDefined();
    await press('Ask the whole library');
    expect(button(OFFER)).toBeUndefined();
  });

  it("gives a whole-library answer the note alone while the page is on one source, or it would narrow", async () => {
    cutCard(null);
    await render(<LibraryQAPage />, ONE_SOURCE);
    expect(host.querySelector('#exchange-e1')!.textContent).toContain(NOTE);
    expect(button(OFFER)).toBeUndefined();

    await press('Ask the whole library');
    expect(button(OFFER)).toBeDefined();
  });

  it('holds the offer while clarify runs: its reply would land on the offered question', async () => {
    cutCard(null);
    let land: (value: unknown) => void = () => undefined;
    clarifyMock.mockReturnValue(new Promise((resolve) => (land = resolve)));
    await render(<LibraryQAPage />);
    expect(button(OFFER)).toBeDefined();

    type(libraryInput(), 'Another question');
    await submitQuestion();
    expect(host.querySelector('#exchange-e1')!.textContent).toContain(NOTE);
    expect(button(OFFER)).toBeUndefined();

    await act(async () => land({ interpretation: 'You mean the RBI.', clarifications: [] }));
    await flush();
    expect(button(OFFER)).toBeDefined();
  });
});

describe('shelf Q&A', () => {
  async function askShelf() {
    shelfQuestionsMock.mockResolvedValueOnce([]).mockResolvedValue([stored('e2')]);
    shelfAskMock.mockResolvedValue({ ...stored('e2'), answer_cut_off: true });
    await render(<ShelfQAPanel shelfId="s1" shelfName="Rates" />);
    type(host.querySelector('textarea')!, QUESTION);
    await press('Ask this shelf');
    await press('Skip clarifications');
  }

  it('says so on the card', async () => {
    await askShelf();
    expect(host.querySelector('#exchange-e2')!.textContent).toContain(NOTE);
  });

  it('fills the question at Deep and spends nothing', async () => {
    await askShelf();
    await press('Ask again at Deep depth');
    expect(host.querySelector('textarea')!.value).toBe(QUESTION);
    expect(shelfAskMock).toHaveBeenCalledTimes(1);
    const label = Array.from(host.querySelectorAll('label')).find((l) => l.textContent?.includes('Answer depth'));
    expect(host.querySelector<HTMLSelectElement>(`[id="${label?.htmlFor}"]`)!.value).toBe('deep');
  });
});

describe('job Q&A hooks', () => {
  function Runner({ run }: { run: (ask: (body: QARequest) => Promise<unknown>) => Promise<unknown> }) {
    const plain = useAskQuestion('job-1');
    const { askStreaming } = useAskQuestionStreaming('job-1');
    useEffect(() => {
      void run((body) => (streamingRun ? askStreaming(body) : plain.mutateAsync(body)));
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return null;
  }

  let streamingRun = false;

  const exchange = (over: Partial<QAExchange>): QAExchange => ({
    id: 'q1',
    question: QUESTION,
    answer: 'The RBI cut',
    references: [],
    created_at: '2026-11-04T00:00:00Z',
    ...over,
  });

  function stubStream(reply: QAExchange) {
    const frame = `data: ${JSON.stringify({ type: 'complete', exchange: reply })}\n\ndata: [DONE]\n\n`;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(frame, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })),
    );
  }

  it('the plain path says so, with the depth the ask carried', async () => {
    streamingRun = false;
    jobAskMock.mockResolvedValue(exchange({ answer_cut_off: true }));
    await render(<Runner run={(ask) => ask({ question: QUESTION, output_length: 'brief' })} />);
    expect(useQACutOffStore.getState().answers).toEqual({ q1: 'brief' });
  });

  it('the stream says so, with no depth when the ask carried none', async () => {
    streamingRun = true;
    stubStream(exchange({ answer_cut_off: true }));
    await render(<Runner run={(ask) => ask({ question: QUESTION })} />);
    expect(useQACutOffStore.getState().answers).toEqual({ q1: null });
  });

  it('neither says anything of a finished answer', async () => {
    streamingRun = true;
    stubStream(exchange({ answer_cut_off: false }));
    await render(<Runner run={(ask) => ask({ question: QUESTION })} />);
    streamingRun = false;
    jobAskMock.mockResolvedValue(exchange({ id: 'q2' }));
    act(() => root.unmount());
    root = createRoot(host);
    await render(<Runner run={(ask) => ask({ question: QUESTION })} />);
    expect(useQACutOffStore.getState().answers).toEqual({});
  });
});

describe('AnswerCutOffNote', () => {
  const cut = (askedAt: 'brief' | 'deep' | null) => useQACutOffStore.getState().note('x', askedAt);

  it("treats an ask that carried no depth as the run's", async () => {
    cut(null);
    await render(<AnswerCutOffNote exchangeId="x" inheritedDepth="deep" onAskAgain={() => undefined} />);
    expect(host.textContent).toContain(NOTE);
    expect(button('Ask again at Deep depth')).toBeUndefined();
  });

  it('offers nothing while asking is unavailable', async () => {
    cut('brief');
    await render(<AnswerCutOffNote exchangeId="x" />);
    expect(host.textContent).toContain(NOTE);
    expect(host.textContent).not.toContain('Asking again');
    expect(host.querySelector('button')).toBeNull();
  });
});
