/**
 * `/shelves/:shelfId` is one route element, so the sidebar moving from one
 * shelf to another reuses the page, and a shelf already in the cache shows no
 * loading state in between. The panel's question and clarify step belong to
 * the shelf they were started on (S-8.13.2).
 *
 * Mutation check, run by hand on 2026-11-04: taking `key={shelf.id}` off
 * `ShelfQAPanel` fails both tests.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ShelfPage } from '../ShelfPage';
import type { ClarifyResponse } from '../../types/qa';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const clarifyMock = vi.fn<(body: unknown) => Promise<ClarifyResponse>>();
const askMock = vi.fn();

function shelf(id: string, name: string) {
  return {
    id,
    name,
    description: '',
    color: 'blue',
    job_count: 1,
    created_at: '2026-10-19T00:00:00Z',
    updated_at: '2026-10-19T00:00:00Z',
    jobs: [],
  };
}

vi.mock('../../services/shelvesApi', async (orig) => ({
  ...(await orig<typeof import('../../services/shelvesApi')>()),
  shelvesApi: {
    list: async () => [],
    get: async (id: string) => (id === 'a' ? shelf('a', 'Rates') : shelf('b', 'Tides')),
    documents: async () => [{ id: 'd1' }],
    questions: async () => [],
    ask: (id: string, body: unknown) => askMock(id, body),
  },
}));
vi.mock('../../services/libraryQaApi', () => ({
  libraryQaApi: { clarify: (body: unknown) => clarifyMock(body) },
}));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../hooks/useTierCapabilities', () => ({ useTierCapabilities: () => ({ has: () => true }) }));
vi.mock('../../components/library/DocumentsBrowser', () => ({ DocumentsBrowser: () => null }));
vi.mock('../../components/notes', () => ({ NotesPanel: () => null }));
vi.mock('../../components/citation', () => ({ CitationLink: () => null }));
vi.mock('../../components/savedSearches/PinQuestionButton', () => ({ PinQuestionButton: () => null }));

const STEP = 'You want the rate moves since 2024.';
const REPLY: ClarifyResponse = { interpretation: STEP, clarifications: ['Which central bank?'] };

let host: HTMLDivElement;
let root: Root;
let go: (to: string) => void = () => {};

function Navigator() {
  const navigate = useNavigate();
  go = (to) => void navigate(to);
  return null;
}

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function visit(to: string) {
  act(() => go(to));
  await flush();
}

const heading = () => host.querySelector('h1')?.textContent;

const button = (label: string) =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as HTMLButtonElement;

async function askOnRates() {
  const textarea = host.querySelector('textarea')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(textarea, 'What about rates?');
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => button('Ask this shelf').click());
  await flush();
}

beforeEach(async () => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  clarifyMock.mockReset();
  askMock.mockReset();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/shelves/b']}>
          <Navigator />
          <Routes>
            <Route path="/shelves/:shelfId" element={<ShelfPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
  // Both shelves are cached, as in a session that has opened them from the
  // sidebar: moving between them shows no loading state.
  await visit('/shelves/a');
  await visit('/shelves/b');
  await visit('/shelves/a');
  expect(heading()).toBe('Rates');
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('ShelfPage moving between shelves', () => {
  it("does not carry one shelf's clarify step to the next", async () => {
    clarifyMock.mockResolvedValue(REPLY);
    await askOnRates();
    expect(host.textContent).toContain(STEP);

    await visit('/shelves/b');

    expect(heading()).toBe('Tides');
    expect(host.textContent).not.toContain(STEP);
    expect(host.querySelector('textarea')!.value).toBe('');
    expect(button('Confirm & search')).toBeUndefined();
  });

  it('does not open a clarify step that was still running when the reader left', async () => {
    let reply: (r: ClarifyResponse) => void = () => {};
    clarifyMock.mockReturnValue(new Promise((resolve) => { reply = resolve; }));
    await askOnRates();

    await visit('/shelves/b');
    await act(async () => reply(REPLY));
    await flush();

    expect(heading()).toBe('Tides');
    expect(host.textContent).not.toContain(STEP);
    expect(button('Confirm & search')).toBeUndefined();
  });
});
