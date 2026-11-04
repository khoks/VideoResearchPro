/**
 * R4 / S-1.15.2: the library Q&A page's per-ask depth control. The API took
 * `output_length` since 2026-10-19 but no page sent it. The control sits with
 * the other per-ask option (the answer language), starts on Default, and the
 * ask carries `output_length` only when a depth was picked, on every path:
 * "Skip clarifications", "Confirm & search" and a Shift-clicked suggestion.
 * A pick is for that one ask: it clears when the answer lands, and until then
 * it shows in the docked composer. The real hooks run; only the HTTP layer is
 * replaced.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LibraryQARequest } from '../../types/qa';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const askMock = vi.fn<(body: LibraryQARequest) => Promise<unknown>>();
const clarifyMock = vi.fn();
vi.mock('../../services/libraryQaApi', () => ({
  libraryQaApi: {
    getHistory: async () => [],
    ask: (body: LibraryQARequest) => askMock(body),
    clarify: (body: unknown) => clarifyMock(body),
  },
}));
const SUGGESTED = 'What changed in agent tooling this year?';
vi.mock('../../services/suggestionsApi', () => ({
  suggestionsApi: {
    get: async () => ({
      context: 'library',
      cached: false,
      generated: true,
      suggestions: [{ question: SUGGESTED, rationale: 'Recent shifts.', source: 'generated', origin: null }],
    }),
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
const depthSelect = () => host.querySelector<HTMLSelectElement>('select[aria-label="Answer depth"]');
const composer = () => host.querySelector('.qa-composer');

function pick(depth: string) {
  const select = depthSelect()!;
  act(() => {
    select.value = depth;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

async function mount() {
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
}

/** Type the question and press Ask, which opens the clarify step. */
async function startAsk(question: string) {
  typeInto(host.querySelector<HTMLInputElement>('input[aria-label="Question"]')!, question);
  act(() => {
    host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
}

async function askThroughClarify(finish: 'Skip clarifications' | 'Confirm & search') {
  await startAsk('What changed in rates?');
  act(() => button(finish).click());
  await flush();
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  clarifyMock.mockResolvedValue({ interpretation: 'Rate moves since 2024.', clarifications: [] });
  askMock.mockResolvedValue({
    id: 'x1',
    question: 'What changed in rates?',
    answer: 'An answer.',
    references: [],
    answer_language: 'en',
    created_at: '2026-11-04T00:00:00Z',
    scope: null,
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('LibraryQAPage: answer depth', () => {
  it('renders beside the answer language, on Default', async () => {
    await mount();
    const select = depthSelect();
    expect(select).not.toBeNull();
    expect(Array.from(select!.options).map((o) => [o.value, o.textContent])).toEqual([
      ['', 'Default'],
      ['brief', 'Brief'],
      ['standard', 'Standard'],
      ['deep', 'Deep'],
    ]);
    expect(select!.value).toBe('');
  });

  it('sends no output_length when left on Default', async () => {
    await mount();
    await askThroughClarify('Skip clarifications');
    expect(askMock).toHaveBeenCalledTimes(1);
    const body = askMock.mock.calls[0][0];
    expect(body).toEqual({ question: 'What changed in rates?', answer_language: 'en' });
    expect('output_length' in body).toBe(false);
  });

  it.each(['Skip clarifications', 'Confirm & search'] as const)('sends the chosen depth via "%s"', async (finish) => {
    await mount();
    pick('brief');
    await askThroughClarify(finish);
    expect(askMock).toHaveBeenCalledTimes(1);
    expect(askMock.mock.calls[0][0].output_length).toBe('brief');
  });

  it('sends it with a suggestion asked at once (Shift-click)', async () => {
    await mount();
    pick('deep');
    const suggestion = Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.includes(SUGGESTED))!;
    await act(async () => {
      suggestion.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    });
    await flush();
    expect(clarifyMock).not.toHaveBeenCalled();
    expect(askMock).toHaveBeenCalledWith({ question: SUGGESTED, answer_language: 'en', output_length: 'deep' });
  });

  it.each(['Skip clarifications', 'Confirm & search'] as const)(
    'applies to that one ask: after "%s" the next request omits it',
    async (finish) => {
      await mount();
      pick('brief');
      await askThroughClarify(finish);
      expect(askMock.mock.calls[0][0].output_length).toBe('brief');
      expect(depthSelect()!.value).toBe('');

      await askThroughClarify('Skip clarifications');
      expect(askMock).toHaveBeenCalledTimes(2);
      expect('output_length' in askMock.mock.calls[1][0]).toBe(false);
    },
  );

  it('stays for the retry when the ask fails', async () => {
    askMock.mockRejectedValueOnce(new Error('boom'));
    await mount();
    pick('deep');
    const suggestion = Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.includes(SUGGESTED))!;
    await act(async () => {
      suggestion.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    });
    await flush();
    expect(askMock).toHaveBeenCalledTimes(1);
    expect(depthSelect()!.value).toBe('deep');
  });

  it('stays through "Edit", which is still the same ask', async () => {
    await mount();
    pick('brief');
    await startAsk('What changed in rates?');
    act(() => button('← Edit').click());
    expect(depthSelect()!.value).toBe('brief');
  });

  it('shows a picked depth in the docked composer, and drops it from there', async () => {
    await mount();
    expect(composer()!.textContent).not.toContain('Answer depth:');
    pick('standard');
    expect(composer()!.textContent).toContain('Answer depth: Standard');
    act(() => button('Clear').click());
    expect(depthSelect()!.value).toBe('');
    expect(composer()!.textContent).not.toContain('Answer depth:');
  });
});
