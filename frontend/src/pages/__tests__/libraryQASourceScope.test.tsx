/**
 * T-8.4.2.4: a question handed over from a source's knowledge drawer is
 * asked about that source alone. The library Q&A page says so beside its
 * composer, sends `document_id` with every ask (Shift-click, Skip and
 * Confirm alike), shows that source's suggestions, and "Ask the whole
 * library" goes back to the library. Its answer card says it was asked
 * about one source and offers no pin (a saved search takes a library or a
 * shelf, so pinning would widen it). The drawer hands the source over.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LibraryQAExchange, LibraryQARequest } from '../../types/qa';
import type { SuggestionCardProps } from '../../components/qa/SuggestionCard';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const ask = vi.fn<(body: LibraryQARequest) => Promise<unknown>>(async () => undefined);
const clarify = vi.fn(async () => ({ interpretation: 'You want the claim.', clarifications: [] }));
let history: LibraryQAExchange[] = [];
const cards: SuggestionCardProps[] = [];

vi.mock('../../components/qa/SuggestionCard', () => ({
  SuggestionCard: (props: SuggestionCardProps) => {
    cards.push(props);
    return <p data-card-context={props.context}>{props.note}</p>;
  },
}));
vi.mock('../../hooks/useLibrary', () => ({ useLibraryVideos: () => ({ data: [{ id: 'd1' }], isSuccess: true }) }));
vi.mock('../../hooks/useLibraryQA', () => ({
  useLibraryQAHistory: () => ({ data: history }),
  useAskLibraryQA: () => ({ mutateAsync: ask, isPending: false }),
  useClarifyLibraryQA: () => ({ mutateAsync: clarify, isPending: false }),
}));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../hooks/useShelves', () => ({ useShelves: () => ({ data: [], isLoading: false }) }));
vi.mock('../../components/notes', () => ({ NotesPanel: () => null }));
vi.mock('../../components/savedSearches/PinQuestionButton', () => ({ PinQuestionButton: () => <button>Pin this question</button> }));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));
vi.mock('../../hooks/useKnowledge', () => ({
  useKnowledge: () => ({
    data: { topics: ['rates'], concepts: [], events: [], facts: [], knowledge_report_md: null, extracted_at: '2026-10-19' },
    isLoading: false,
    isError: false,
  }),
  useExtractKnowledge: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false, isError: false, data: undefined }),
}));
vi.mock('../../components/frames/VideoFramesPanel', () => ({ VideoFramesPanel: () => null }));

import { LibraryQAPage } from '../LibraryQAPage';
import { VideoKnowledgeDrawer } from '../VideoKnowledgePage';

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

function Where() {
  const loc = useLocation();
  return <output data-state={JSON.stringify(loc.state ?? null)}>{loc.pathname}</output>;
}

async function mount(entry: { pathname: string; state?: unknown }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="/library/qa" element={<LibraryQAPage />} />
          </Routes>
          <Where />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const SOURCE = { id: 'doc-rates', title: 'Rates explained' };
const composer = () => host.querySelector<HTMLInputElement>('form input')!;
const chip = () => host.querySelector('[data-source-scope]');
const button = (text: string) =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === text) as HTMLButtonElement | undefined;
const lastCard = () => cards[cards.length - 1];

function type(value: string) {
  const input = composer();
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

function pickDepth(value: string) {
  const select = host.querySelector<HTMLSelectElement>('select[aria-label="Answer depth"]')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(select, value);
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

beforeEach(() => {
  history = [];
  cards.length = 0;
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('library Q&A about one source', () => {
  it('a handed-over question says which source and is asked about it alone', async () => {
    await mount({ pathname: '/library/qa', state: { question: 'What does it claim?', source: SOURCE } });
    expect(composer().value).toBe('What does it claim?');
    expect(chip()?.textContent).toContain('Asking about one source:');
    expect(chip()?.textContent).toContain('Rates explained');
    expect(host.querySelector('h1')?.textContent).toBe('Ask one source');
    expect(composer().placeholder).toBe('Ask a question about this source…');
    expect(lastCard().context).toBe('document:doc-rates');

    // Ask → clarify → Skip clarifications.
    await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    await flush();
    await act(async () => button('Skip clarifications')!.click());
    await flush();
    expect(ask).toHaveBeenLastCalledWith({ question: 'What does it claim?', answer_language: 'en', document_id: 'doc-rates' });
  });

  it('Shift-click in the drawer asks at once, about that source', async () => {
    await mount({ pathname: '/library/qa', state: { question: 'Who is quoted?', ask: true, source: SOURCE } });
    expect(ask).toHaveBeenCalledWith({ question: 'Who is quoted?', answer_language: 'en', document_id: 'doc-rates' });
  });

  it('a depth picked for the ask goes with the source, on every path', async () => {
    await mount({ pathname: '/library/qa', state: { question: 'What does it claim?', source: SOURCE } });
    pickDepth('deep');
    await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    await flush();
    await act(async () => button('Skip clarifications')!.click());
    await flush();
    expect(ask).toHaveBeenLastCalledWith({
      question: 'What does it claim?', answer_language: 'en', document_id: 'doc-rates', output_length: 'deep',
    });

    pickDepth('brief');
    await act(async () => lastCard().onAsk!('Second?'));
    expect(ask).toHaveBeenLastCalledWith({
      question: 'Second?', answer_language: 'en', document_id: 'doc-rates', output_length: 'brief',
    });
  });

  it('a suggestion on the page asks about the source too, until the reader clears it', async () => {
    await mount({ pathname: '/library/qa', state: { question: 'First?', source: SOURCE } });
    await act(async () => lastCard().onAsk!('Second?'));
    expect(ask).toHaveBeenLastCalledWith({ question: 'Second?', answer_language: 'en', document_id: 'doc-rates' });

    act(() => button('Ask the whole library')!.click());
    await flush();
    expect(chip()).toBeNull();
    expect(host.querySelector('h1')?.textContent).toBe('Ask the whole library');
    expect(lastCard().context).toBe('library');
    await act(async () => lastCard().onAsk!('Third?'));
    expect(ask).toHaveBeenLastCalledWith({ question: 'Third?', answer_language: 'en' });
  });

  it('without a source the page asks the whole library, as before', async () => {
    await mount({ pathname: '/library/qa', state: { question: 'Anything?' } });
    expect(chip()).toBeNull();
    type('Anything at all?');
    await act(async () => lastCard().onAsk!('Anything at all?'));
    expect(ask).toHaveBeenLastCalledWith({ question: 'Anything at all?', answer_language: 'en' });
  });

  it('an answer about one source says so, links to it, and offers no pin', async () => {
    const base = { answer: 'An answer.', references: [], answer_language: 'en', created_at: '2026-10-19T10:00:00' };
    history = [
      { ...base, id: 'x1', question: 'About the source?', scope: { document_id: 'doc-rates', shelf_id: null, saved_search_id: null } },
      { ...base, id: 'x2', question: 'About the library?', scope: null },
    ];
    await mount({ pathname: '/library/qa' });
    const [scoped, whole] = ['exchange-x1', 'exchange-x2'].map((id) => host.querySelector(`#${id}`)!);
    expect(scoped.querySelector('[data-qa-scope]')?.textContent).toBe('Asked about one source');
    expect(scoped.querySelector('a')?.getAttribute('href')).toBe('/library?document=doc-rates');
    expect(scoped.textContent).not.toContain('Pin this question');
    expect(whole.querySelector('[data-qa-scope]')).toBeNull();
    expect(whole.textContent).toContain('Pin this question');
  });
});

describe('the knowledge drawer', () => {
  async function mountDrawer(seen: unknown[]) {
    function Spy() {
      const loc = useLocation();
      seen.push(loc.state);
      return null;
    }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    act(() =>
      root.render(
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={['/drawer']}>
            <Routes>
              <Route
                path="/drawer"
                element={<VideoKnowledgeDrawer videoId="doc-rates" videoTitle="Rates explained" sourceType="article" onClose={() => {}} />}
              />
              <Route path="/library/qa" element={<Spy />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>,
      ),
    );
    await flush();
  }

  it('says its suggestions are asked about this source', async () => {
    await mountDrawer([]);
    expect(lastCard().context).toBe('document:doc-rates');
    expect(lastCard().note).toBe('Asked about this source only.');
    expect(host.textContent).not.toContain('Asked across your library');
  });

  it('a click hands the question and the source to library Q&A', async () => {
    const seen: unknown[] = [];
    await mountDrawer(seen);
    act(() => lastCard().onFill('What does it claim?'));
    await flush();
    expect(seen.at(-1)).toEqual({ question: 'What does it claim?', source: SOURCE });
  });

  it('Shift-click hands over the source with the ask', async () => {
    const seen: unknown[] = [];
    await mountDrawer(seen);
    act(() => lastCard().onAsk!('Who is quoted?'));
    await flush();
    expect(seen.at(-1)).toEqual({ question: 'Who is quoted?', ask: true, source: SOURCE });
  });
});
