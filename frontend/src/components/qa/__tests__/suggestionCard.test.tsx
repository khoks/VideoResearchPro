/**
 * S-8.4.2: the "You might ask…" card. A click fills the composer, Shift-click
 * asks, each use is logged, and the card stays out of the way when there is
 * nothing to suggest, when the request fails, or when Q&A is down.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SuggestionCard } from '../SuggestionCard';
import type { SuggestionsResponse } from '../../../services/suggestionsApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getMock = vi.fn<(context: string) => Promise<SuggestionsResponse>>();
const feedbackMock = vi.fn<(body: unknown) => Promise<void>>(async () => undefined);
vi.mock('../../../services/suggestionsApi', () => ({
  suggestionsApi: {
    get: (context: string) => getMock(context),
    feedback: (body: unknown) => feedbackMock(body),
  },
}));

const RESPONSE: SuggestionsResponse = {
  context: 'job:j1',
  cached: false,
  generated: true,
  suggestions: [
    { question: 'How do tariffs change prices?', rationale: 'Ties policy to prices.', source: 'generated', origin: null },
    { question: 'What did farmers receive?', rationale: '', source: 'history', origin: { source: 'job', exchange_id: 'x', job_id: 'j2' } },
  ],
};

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 4; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount(props: Partial<Parameters<typeof SuggestionCard>[0]> = {}) {
  const onFill = vi.fn();
  const onAsk = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <SuggestionCard context="job:j1" onFill={onFill} onAsk={onAsk} {...props} />
      </QueryClientProvider>,
    ),
  );
  await flush();
  return { onFill, onAsk };
}

const buttons = () => Array.from(host.querySelectorAll('button'));

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('SuggestionCard', () => {
  it('lists the suggestions for its context', async () => {
    getMock.mockResolvedValue(RESPONSE);
    await mount();
    expect(getMock).toHaveBeenCalledWith('job:j1');
    expect(host.textContent).toContain('You might ask');
    expect(buttons().map((b) => b.textContent)).toEqual([
      expect.stringContaining('How do tariffs change prices?'),
      expect.stringContaining('You asked this before.'),
    ]);
  });

  it('a click fills the composer and logs it', async () => {
    getMock.mockResolvedValue(RESPONSE);
    const { onFill, onAsk } = await mount();
    act(() => buttons()[0].click());
    expect(onFill).toHaveBeenCalledWith('How do tariffs change prices?');
    expect(onAsk).not.toHaveBeenCalled();
    expect(feedbackMock).toHaveBeenCalledWith({ context: 'job:j1', question: 'How do tariffs change prices?', action: 'fill', source: 'generated' });
  });

  it('Shift-click asks at once', async () => {
    getMock.mockResolvedValue(RESPONSE);
    const { onFill, onAsk } = await mount();
    act(() => {
      buttons()[1].dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
    });
    expect(onAsk).toHaveBeenCalledWith('What did farmers receive?');
    expect(onFill).not.toHaveBeenCalled();
    expect(feedbackMock).toHaveBeenCalledWith(expect.objectContaining({ action: 'ask', source: 'history' }));
  });

  it('renders nothing when there is nothing to suggest or the request fails', async () => {
    getMock.mockResolvedValue({ ...RESPONSE, suggestions: [] });
    await mount();
    expect(host.textContent).toBe('');
    act(() => root.unmount());
    root = createRoot(host);
    getMock.mockRejectedValue(new Error('down'));
    await mount();
    expect(host.textContent).toBe('');
  });

  it('is hidden and asks nothing while Q&A is down', async () => {
    getMock.mockResolvedValue(RESPONSE);
    await mount({ enabled: false });
    expect(getMock).not.toHaveBeenCalled();
    expect(host.textContent).toBe('');
  });
});
