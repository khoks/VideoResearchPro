/**
 * T-1.15.4.9 on the Q&A history page: an answer that stopped at its token budget
 * shows the same note as the other Q&A cards, read from the stored row. The real
 * hooks run, with only the HTTP layer replaced. This page has no depth to raise,
 * so the note stands alone.
 *
 * Mutation check, run by hand on 2026-11-05: the card not passing `cutOff` fails
 * both "says so" tests.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QAHistoryExchange } from '../../types/qa';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const exchangesMock = vi.fn<() => Promise<QAHistoryExchange[]>>();
const chatMock = vi.fn<(body: unknown) => Promise<QAHistoryExchange>>();

vi.mock('../../services/qaHistoryApi', () => ({
  qaHistoryApi: {
    getExchanges: () => exchangesMock(),
    postChat: (body: unknown) => chatMock(body),
  },
}));
vi.mock('../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => true }));
vi.mock('../../components/notes', () => ({ NotesPanel: () => null }));

import { QAHistoryChatPage } from '../QAHistoryChatPage';

const NOTE = 'This answer stopped at its length limit';

function row(over: Partial<QAHistoryExchange> = {}): QAHistoryExchange {
  return {
    id: 'h1',
    question: 'What have I learned about tariffs?',
    answer: 'Mostly that they',
    references: [],
    answer_language: 'en',
    created_at: '2026-11-05T00:00:00Z',
    ...over,
  };
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

async function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <QAHistoryChatPage />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

beforeEach(() => {
  exchangesMock.mockReset();
  chatMock.mockReset();
  Element.prototype.scrollIntoView = vi.fn();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('Q&A history page', () => {
  it('says so on a fresh load, from the stored row, with no offer', async () => {
    exchangesMock.mockResolvedValue([row({ answer_cut_off: true })]);
    await mount();
    const note = host.querySelector('#exchange-h1 [data-answer-cut-off]')!;
    expect(note.textContent).toContain(NOTE);
    expect(note.querySelector('button')).toBeNull();
  });

  it('says so after an ask, from the refetch', async () => {
    exchangesMock.mockResolvedValueOnce([]).mockResolvedValue([row({ answer_cut_off: true })]);
    chatMock.mockResolvedValue(row({ answer_cut_off: true }));
    await mount();

    const input = host.querySelector('input')!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(input, 'What have I learned about tariffs?');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    await flush();

    expect(chatMock).toHaveBeenCalledTimes(1);
    expect(host.querySelector('#exchange-h1')!.textContent).toContain(NOTE);
  });

  it('shows nothing for a finished answer, or one from before the check', async () => {
    exchangesMock.mockResolvedValue([row()]);
    await mount();
    expect(host.textContent).toContain('Mostly that they');
    expect(host.querySelector('[data-answer-cut-off]')).toBeNull();
  });
});
