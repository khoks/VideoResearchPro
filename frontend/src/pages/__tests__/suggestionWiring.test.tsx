/**
 * S-8.4.2 wiring: library Q&A mounts the suggestion card for its context,
 * a click fills its composer, and a question handed over from the
 * knowledge drawer (route state) arrives in the composer. These fail if the
 * card exists but no page uses it. T-8.13.4.2: the card goes while clarify runs,
 * or a click would change the question under clarify's reply. Mutation check, run
 * by hand on 2026-11-05: `{!askQuestion.isPending && <SuggestionCard` fails it.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SuggestionsResponse } from '../../services/suggestionsApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getMock = vi.fn<(context: string) => Promise<SuggestionsResponse>>();
let clarifyPending = false;
vi.mock('../../services/suggestionsApi', () => ({
  suggestionsApi: { get: (c: string) => getMock(c), feedback: async () => undefined },
}));
vi.mock('../../hooks/useLibrary', () => ({ useLibraryVideos: () => ({ data: [{ id: 'd1' }], isSuccess: true }) }));
vi.mock('../../hooks/useLibraryQA', () => ({
  useLibraryQAHistory: () => ({ data: [] }),
  useAskLibraryQA: () => ({ mutateAsync: vi.fn(async () => undefined), isPending: false }),
  useClarifyLibraryQA: () => ({ mutateAsync: vi.fn(), isPending: clarifyPending }),
}));
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

async function mount(state?: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[{ pathname: '/library/qa', state }]}>
          <Routes>
            <Route path="/library/qa" element={<LibraryQAPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const composer = () => host.querySelector<HTMLInputElement>('form input, form textarea')!;

beforeEach(() => {
  clarifyPending = false;
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  getMock.mockResolvedValue({
    context: 'library',
    cached: false,
    generated: true,
    suggestions: [{ question: 'What changed in agent tooling this year?', rationale: 'Recent shifts.', source: 'generated', origin: null }],
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('LibraryQAPage suggestions', () => {
  it('goes while clarify runs: a click would change the question under its reply', async () => {
    await mount();
    expect(host.textContent).toContain('What changed in agent tooling this year?');
    clarifyPending = true;
    await mount();
    expect(host.textContent).not.toContain('What changed in agent tooling this year?');
  });

  it('asks for the library context and a click fills the composer', async () => {
    await mount();
    expect(getMock).toHaveBeenCalledWith('library');
    const button = Array.from(host.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('What changed in agent tooling this year?'),
    )!;
    expect(button).toBeTruthy();
    act(() => button.click());
    await flush();
    expect(composer().value).toBe('What changed in agent tooling this year?');
  });

  it('a question handed over from the knowledge drawer lands in the composer', async () => {
    await mount({ question: 'What does this source claim about latency?' });
    expect(composer().value).toBe('What does this source claim about latency?');
  });
});
