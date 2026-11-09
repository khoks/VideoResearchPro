/**
 * T-3.4.1.18: a failed ask in the Echo bubble is said in its turn alone, under
 * the app's own query client. The turn said it, and the global toast said it
 * again. Now the bubble passes `{ inlineErrors: true }` to the two ask hooks,
 * which then set `meta: ERRORS_SHOWN_HERE`, and a 401 says nothing at all: the
 * session ends, and the thread with it. The library Q&A and history pages keep
 * the global toast, since they show no line of their own.
 *
 * "A message" here is a toast or a line with `role="alert"`.
 *
 * Mutation checks, run on 2026-11-09: dropping `{ inlineErrors: true }` from the
 * bubble's `useAskLibraryQA` fails the library rows but `sessionEnded` with the
 * turn's line and a toast, and from `useAskQAHistoryChat` the history rows;
 * setting `meta` for every caller of `useAskLibraryQA` fails "the library page
 * keeps its toast"; taking out the bubble's 401 check fails both
 * `sessionEnded` rows with "Something went wrong. Try again." in the turn.
 *
 * The turn being the one message, it says the server's words when there are
 * any, as the toast beside it used to. Mutation check, run on 2026-11-09:
 * putting back `requestErrorLine(err)` alone fails both `words` rows and the
 * rate limit, quota, plan and missing-source rows of "what the turn says".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { AxiosError, AxiosHeaders } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { EchoStatus } from '../../../services/echoApi';
import { createQueryClient } from '../../../services/queryClient';
import { useEchoPanelStore } from '../../../stores/echoPanelStore';
import { useAskLibraryQA } from '../../../hooks/useLibraryQA';
import {
  FAILURE_KINDS,
  SERVER_WORDS,
  clearToasts,
  failures,
  flush,
  toastMessages,
  type FailureKind,
} from '../../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const STATUS: EchoStatus = {
  ready: false,
  total_rows: 40,
  distinct_sources: 1,
  has_personality_trait: false,
  threshold_total: 100,
  threshold_sources: 3,
};

const askLibrary = vi.fn();
const askHistory = vi.fn();

vi.mock('../../../services/echoApi', async (orig) => ({
  ...(await orig<typeof import('../../../services/echoApi')>()),
  echoApi: {
    status: async () => STATUS,
    listConnectors: async () => ({ connectors: [] }),
    draftStatus: async () => ({ available: false, blockers: [] }),
    cards: async () => ({ cards: [], muted_kinds: [] }),
    cardSettings: async () => ({ kinds: {} }),
    cardShown: async () => undefined,
  },
}));
vi.mock('../../../services/suggestionsApi', () => ({
  suggestionsApi: { get: async () => ({ suggestions: [] }), feedback: async () => undefined },
}));
vi.mock('../../../services/libraryQaApi', () => ({
  libraryQaApi: { ask: (d: unknown) => askLibrary(d), getHistory: async () => [], clarify: vi.fn() },
}));
vi.mock('../../../services/qaHistoryApi', () => ({
  qaHistoryApi: { postChat: (d: unknown) => askHistory(d), getExchanges: async () => [] },
}));

import { EchoPanelHost } from '../EchoPanel';

let host: HTMLDivElement;
let root: Root;

async function mount(node: React.ReactNode = <EchoPanelHost />) {
  act(() =>
    root.render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={['/library']}>{node}</MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const panel = () => document.querySelector<HTMLElement>('#echo-panel');

/** Every message on screen: the toasts, then each line with `role="alert"`. */
function messages(): string[] {
  const lines = Array.from(document.querySelectorAll('[role="alert"]')).map((el) => el.textContent?.trim() ?? '');
  return [...toastMessages(), ...lines];
}

async function ask(question: string) {
  const field = panel()!.querySelector('textarea')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, question);
    field.dispatchEvent(new Event('input', { bubbles: true }));
  });
  const button = Array.from(panel()!.querySelectorAll<HTMLButtonElement>('form button[type="submit"]')).find(
    (b) => b.textContent?.trim() === 'Ask',
  )!;
  await act(async () => button.click());
  await flush();
}

/** What the turn says for each failure: the server's words, else the bubble's
 * line for the status (`requestErrorLine`). */
const TURN_SAYS: Record<FailureKind, string[]> = {
  words: [SERVER_WORDS],
  noWords: ['Something went wrong. Try again.'],
  noAnswer: ['Could not reach the server.'],
  sessionEnded: [],
};

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  useEchoPanelStore.setState({ open: true, mode: 'ask', target: 'library', turns: [], askText: '' });
  askLibrary.mockReset();
  askHistory.mockReset();
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const TARGETS = [
  { target: 'library' as const, call: () => askLibrary },
  { target: 'history' as const, call: () => askHistory },
];

describe.each(TARGETS)('asking over $target', ({ target, call }) => {
  it.each(FAILURE_KINDS)('says a failure (%s) once, in its turn', async (kind) => {
    useEchoPanelStore.setState({ target });
    call().mockRejectedValueOnce(failures[kind]());
    await mount();
    await ask('What raises tariffs?');
    expect(call()).toHaveBeenCalledTimes(1);
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(TURN_SAYS[kind]);
  });
});

function answered(status: number, data: unknown): AxiosError {
  const headers = new AxiosHeaders();
  return new AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_REQUEST', undefined, undefined, {
    status, statusText: String(status), headers, config: { headers }, data,
  });
}

// The turn is the only message, so the server's reason must reach it: the
// global toast used to carry it beside the turn's generic line.
describe('what the turn says', () => {
  it.each([
    [
      'a rate limit, with its cooldown',
      answered(429, { detail: 'Too many requests. Please retry after the cooldown period.', retry_after_sec: 30 }),
      'Too many requests. Please retry after the cooldown period.',
    ],
    [
      'a quota refusal, with its message',
      answered(429, { detail: { resource: 'library_qa', message: 'You have asked today’s 20 questions.' } }),
      'You have asked today’s 20 questions.',
    ],
    ['a plan’s refusal, in its words', answered(403, { detail: 'Library Q&A is on the Pro plan.' }), 'Library Q&A is on the Pro plan.'],
    ['a scoped source that is gone', answered(404, { detail: 'Source not found' }), 'Source not found'],
    ['a 429 with no words', answered(429, {}), 'You have reached today’s limit for this. It resets tomorrow.'],
    ['a 403 with no words', answered(403, {}), 'Your plan does not include this.'],
  ])('%s', async (_label, error, line) => {
    askLibrary.mockRejectedValueOnce(error);
    await mount();
    await ask('What raises tariffs?');
    expect(askLibrary).toHaveBeenCalledTimes(1);
    expect(messages()).toEqual([line]);
  });
});

describe('a failed ask', () => {
  it('is still said once the panel was closed and opened again', async () => {
    let fail: (reason: unknown) => void = () => undefined;
    askLibrary.mockReturnValueOnce(new Promise((_, reject) => (fail = reject)));
    await mount();
    await ask('What raises tariffs?');
    act(() => useEchoPanelStore.setState({ open: false }));
    await flush();
    await act(async () => fail(failures.noWords()));
    await flush();
    expect(toastMessages()).toEqual([]);
    act(() => useEchoPanelStore.setState({ open: true }));
    await flush();
    expect(messages()).toEqual(['Something went wrong. Try again.']);
  });
});

describe('the library page', () => {
  // The hook's other caller shows no line of its own, so the global toast speaks.
  function LibraryAsker() {
    const askQuestion = useAskLibraryQA();
    return (
      <button type="button" onClick={() => askQuestion.mutate({ question: 'Q', answer_language: 'en' })}>
        Ask here
      </button>
    );
  }

  it('keeps its toast', async () => {
    askLibrary.mockRejectedValueOnce(failures.words());
    await mount(<LibraryAsker />);
    const button = Array.from(document.querySelectorAll('button')).find((b) => b.textContent === 'Ask here')!;
    await act(async () => button.click());
    await flush();
    expect(messages()).toEqual(['The server says no, in words.']);
  });
});
