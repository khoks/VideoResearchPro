/**
 * T-3.4.1.27: the health poll, where the app runs it, in `AppLayout` (the real
 * `useSystemStatus`, under the app's own query client; only the HTTP layer and
 * the layout's other parts are replaced).
 *
 * Nothing on the page says a failed health check (the banner shows the last one
 * read), so the toast does, and once per run of failures: the first failed
 * check is said, the checks that keep failing every minute are not, and a
 * failure after a check that succeeds is said again. A 401 says nothing, and a
 * different kind of failure in the same run (the server answering with words
 * after not answering at all) is said once more.
 *
 * Mutation checks, run on 2026-11-10: the query client without its streak check
 * fails "says a run of failed checks once" (a toast a minute) and "says a new
 * kind of failure once more"; without the `onSuccess` that ends a run, "says a
 * run of failed checks once" fails with one toast; `globalErrorToastMessage`
 * without its 401 check fails "says nothing of a 401".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryClient } from '../../services/queryClient';
import { useSystemStatusStore } from '../../stores/systemStatusStore';
import {
  SERVER_WORDS,
  clearToasts,
  failures,
  flush,
  recordToasts,
  type FailureKind,
} from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** What the next health check gets: an answer, or a failure of a kind. */
let next: 'ok' | FailureKind = 'ok';
const health = vi.fn((url: string) => {
  if (url !== '/health') return Promise.reject(new Error(`unexpected GET ${url}`));
  if (next !== 'ok') return Promise.reject(failures[next]());
  return Promise.resolve({ data: { llm: { status: 'degraded', unavailable_features: ['qa'] } } });
});
vi.mock('../../services/api', () => ({ default: { get: (url: string) => health(url) } }));

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { email: 'reader@example.test' }, logout: vi.fn(), isAuthenticated: true, token: 'fixture' }),
}));
vi.mock('../../hooks/useTierCapabilities', () => ({
  useTierCapabilities: () => ({ has: () => false, tier: 'free', isLoading: false }),
}));
vi.mock('../../hooks/useShelves', () => ({ useShelves: () => ({ data: [] }) }));
vi.mock('../../hooks/useOnboarding', () => ({ useShowGettingStarted: () => false }));
vi.mock('../../hooks/useNotifications', () => ({ useLiveNotifications: () => undefined }));
vi.mock('../../components/echo/QuickShare', () => ({ QuickShare: () => null }));
vi.mock('../../components/echo/EchoDropZone', () => ({ EchoDropZone: () => null }));
vi.mock('../../components/echo/EchoPanel', () => ({
  EchoBubble: () => null,
  EchoHeaderButton: () => null,
  EchoPanelHost: () => null,
}));
vi.mock('../../components/echo/WaitingShareNotice', () => ({ WaitingShareNotice: () => null }));
vi.mock('../../components/palette/CommandPalette', () => ({ CommandPalette: () => null }));
vi.mock('../../components/palette/SearchButton', () => ({ SearchButton: () => null }));
vi.mock('../../components/notifications/NotificationBell', () => ({ NotificationBell: () => null }));

import { AppLayout } from '../AppLayout';

let host: HTMLDivElement;
let root: Root;
let toasts: ReturnType<typeof recordToasts>;

async function mount() {
  act(() =>
    root.render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={['/jobs']}>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/jobs" element={<p>the runs page</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

/** Moves the clock on by `ms`, then lets what that started settle. */
async function advance(ms: number) {
  await flush();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
  await flush();
}

/** The next check, a minute after the last one settled, and its one retry a
 * second later. */
const nextCheck = () => advance(62_000);

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  next = 'ok';
  health.mockClear();
  useSystemStatusStore.getState().setStatus('ok', [], 0);
  clearToasts();
  toasts = recordToasts();
});

afterEach(() => {
  toasts.stop();
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

describe('the health poll in the app layout', () => {
  it('says a run of failed checks once, and again after a check succeeds', async () => {
    next = 'noAnswer';
    await mount();
    await advance(1500); // the first check, and its one retry a second later
    expect(host.textContent).toContain('the runs page');
    expect(toasts.messages).toEqual(['Network Error']);
    await nextCheck();
    await nextCheck();
    expect(health.mock.calls.length).toBe(6); // three checks, each tried twice
    expect(toasts.messages).toEqual(['Network Error']);
    next = 'ok';
    await nextCheck();
    // The check read again: the banner shows what it says.
    expect(useSystemStatusStore.getState().llmStatus).toBe('degraded');
    expect(toasts.messages).toEqual(['Network Error']);
    next = 'noAnswer';
    await nextCheck();
    expect(toasts.messages).toEqual(['Network Error', 'Network Error']);
  });

  it('says nothing of a 401, check after check', async () => {
    next = 'sessionEnded';
    await mount();
    await advance(1500);
    await nextCheck();
    await nextCheck();
    expect(health.mock.calls.length).toBe(6);
    expect(toasts.messages).toEqual([]);
  });

  it('says a new kind of failure once more in the same run', async () => {
    next = 'noAnswer';
    await mount();
    await advance(1500);
    next = 'words';
    await nextCheck();
    await nextCheck();
    expect(toasts.messages).toEqual(['Network Error', SERVER_WORDS]);
  });
});
