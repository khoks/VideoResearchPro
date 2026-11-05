/**
 * S-8.13.1: library Q&A's clarify step reaches the request. "Confirm &
 * search" sends the interpretation the reader confirmed and the clarifying
 * questions they answered as `context` on `POST /library/qa`; "Skip
 * clarifications" sends no context. The backend half (the route folding
 * `context` into the agent's question) is pinned in
 * backend/tests/test_routers/test_library.py; this pins what the page sends.
 *
 * S-8.13.3: clarifying is optional, as on the shelf panel (D-132). A failed
 * clarify becomes a direct ask with no context, and the reader sees that ask
 * running. Before this, an outage in the optional step stopped the question.
 * Mutation checks, run by hand on 2026-11-04: removing the direct ask fails
 * "goes straight to the library"; removing the mounted check fails "asks
 * nothing"; removing the stripe, or `askQuestion.isPending` from the input's
 * disabled state, fails "shows the direct ask running"; letting
 * `handleSkipAndAsk` rethrow fails "keeps the question".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LibraryQARequest } from '../../types/qa';
import { CLARIFY_ANSWER_MAX_CHARS, CLARIFY_CONTEXT_MAX_CHARS } from '../../utils/clarifyContext';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// The real hooks run; only the HTTP layer is replaced, so the test sees the
// exact body the page hands to the API client.
const askMock = vi.fn<(body: LibraryQARequest) => Promise<unknown>>();
const clarifyMock = vi.fn();
vi.mock('../../services/libraryQaApi', () => ({
  libraryQaApi: {
    getHistory: async () => [],
    ask: (body: LibraryQARequest) => askMock(body),
    clarify: (body: unknown) => clarifyMock(body),
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
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));

import { LibraryQAPage } from '../LibraryQAPage';

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

function typeInto(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

const button = (label: string) =>
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as HTMLButtonElement;

const questionInput = () => host.querySelector<HTMLInputElement>('input[aria-label="Question"]')!;

async function mountAndClarify() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/library/qa']}>
          <Routes>
            <Route path="/library/qa" element={<LibraryQAPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
  typeInto(questionInput(), 'What changed in rates?');
  const form = host.querySelector('form')!;
  act(() => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
  expect(clarifyMock).toHaveBeenCalledWith({ question: 'What changed in rates?' });
}

const answerFields = () =>
  Array.from(host.querySelectorAll<HTMLInputElement>('input[placeholder="Your answer (optional)"]'));

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  clarifyMock.mockResolvedValue({
    interpretation: 'You want the rate moves since 2024.',
    clarifications: ['Which central bank?', 'Over what period?'],
  });
  askMock.mockResolvedValue({
    id: 'x1',
    question: 'What changed in rates?',
    answer: 'An answer.',
    references: [],
    answer_language: 'en',
    created_at: '2026-10-25T00:00:00Z',
    scope: null,
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('LibraryQAPage clarify step', () => {
  it('"Confirm & search" sends the interpretation and the answered clarifications as context', async () => {
    await mountAndClarify();
    expect(answerFields()).toHaveLength(2);
    typeInto(answerFields()[0], 'The RBI');

    act(() => button('Confirm & search').click());
    await flush();

    expect(askMock).toHaveBeenCalledTimes(1);
    // The unanswered "Over what period?" is left out.
    expect(askMock).toHaveBeenCalledWith({
      question: 'What changed in rates?',
      answer_language: 'en',
      context: 'My interpretation: You want the rate moves since 2024.\n\nWhich central bank?\nThe RBI',
    });
  });

  it('never sends more context than the server accepts, and keeps the answer whole', async () => {
    // The interpretation is model output with no length bound; over the
    // server's 4,000 characters the ask was a 422 and no answer came back.
    clarifyMock.mockResolvedValue({ interpretation: 'x'.repeat(6000), clarifications: ['Which central bank?'] });
    await mountAndClarify();
    expect(answerFields()[0].maxLength).toBe(CLARIFY_ANSWER_MAX_CHARS);
    typeInto(answerFields()[0], 'The RBI');

    act(() => button('Confirm & search').click());
    await flush();

    expect(askMock).toHaveBeenCalledTimes(1);
    const context = askMock.mock.calls[0][0].context!;
    expect(context.length).toBeLessThanOrEqual(CLARIFY_CONTEXT_MAX_CHARS);
    expect(context.endsWith('\n\nWhich central bank?\nThe RBI')).toBe(true);
  });

  it('"Skip clarifications" sends the bare question with no context', async () => {
    await mountAndClarify();
    typeInto(answerFields()[0], 'The RBI');

    act(() => button('Skip clarifications').click());
    await flush();

    expect(askMock).toHaveBeenCalledTimes(1);
    const body = askMock.mock.calls[0][0];
    expect(body).toEqual({ question: 'What changed in rates?', answer_language: 'en' });
    expect('context' in body).toBe(false);
  });
});

describe('LibraryQAPage when clarify fails', () => {
  beforeEach(() => {
    clarifyMock.mockReset();
    clarifyMock.mockRejectedValue(new Error('clarify is down'));
  });

  it('goes straight to the library with no context, and clears the composer', async () => {
    await mountAndClarify();

    expect(askMock).toHaveBeenCalledTimes(1);
    expect(askMock).toHaveBeenCalledWith({ question: 'What changed in rates?', answer_language: 'en' });
    expect(button('Skip clarifications')).toBeUndefined();
    expect(questionInput().value).toBe('');
  });

  it('shows the direct ask running, and takes no second question meanwhile', async () => {
    let land: (value: unknown) => void = () => undefined;
    askMock.mockReturnValue(new Promise((resolve) => (land = resolve)));
    await mountAndClarify();

    expect(host.textContent).toContain('Searching the library and generating answer…');
    expect(questionInput().disabled).toBe(true);

    await act(async () => land({ id: 'x2', question: 'q', answer: 'a', references: [], created_at: '2026-10-25T00:00:00Z' }));
    await flush();
    expect(host.textContent).not.toContain('Searching the library and generating answer…');
    expect(questionInput().disabled).toBe(false);
  });

  it('keeps the question when the direct ask fails too', async () => {
    askMock.mockRejectedValue(new Error('the agent is down'));
    await mountAndClarify();

    expect(askMock).toHaveBeenCalledTimes(1);
    expect(questionInput().value).toBe('What changed in rates?');
    expect(questionInput().disabled).toBe(false);
  });

  it('asks nothing for a reader who has left the page', async () => {
    let fail: (reason: Error) => void = () => undefined;
    clarifyMock.mockReturnValue(new Promise((_, reject) => (fail = reject)));
    await mountAndClarify();

    act(() => root.unmount());
    await act(async () => fail(new Error('clarify is down')));
    await flush();
    expect(askMock).not.toHaveBeenCalled();
    root = createRoot(host);
  });
});
