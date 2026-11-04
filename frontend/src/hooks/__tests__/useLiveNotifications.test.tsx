/**
 * T-8.3.3.8: the bell updates live. While signed in, the layout's
 * `useLiveNotifications` subscribes the shared socket to this user's
 * notifications; a push refetches the bell's list (it carries no text), so
 * the count moves without waiting for the one-minute poll. Signing out
 * unsubscribes, and a new sign-in subscribes afresh.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { NotificationList } from '../../services/notificationsApi';
import type { WSNotificationMessage } from '../../types/ws';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Listener = (msg: WSNotificationMessage) => void;
const listeners = new Set<Listener>();
const subscribeNotifications = vi.fn((cb: Listener) => {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
});
vi.mock('../../services/wsClient', () => ({
  wsClient: { subscribeNotifications: (cb: Listener) => subscribeNotifications(cb) },
}));

let token: string | null = 'token-a';
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: !!token, token }) }));

const list = vi.fn<() => Promise<NotificationList>>();
vi.mock('../../services/notificationsApi', () => ({
  notificationsApi: { list: () => list(), markRead: vi.fn(), readAll: vi.fn() },
}));

import { useLiveNotifications } from '../useNotifications';
import { NotificationBell } from '../../components/notifications/NotificationBell';

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;

function Layout() {
  useLiveNotifications();
  return <NotificationBell />;
}

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function render() {
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Layout />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const bell = () => host.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!;
const push = async (id: string) => {
  await act(async () => listeners.forEach((cb) => cb({ type: 'notification', id, kind: 'saved_search_changed' })));
  await flush();
};
const notice = (id: string) => ({
  id, kind: 'saved_search_changed', title: `Notice ${id}`, body: null, href: null, read_at: null,
  created_at: new Date().toISOString().slice(0, 19),
});

beforeEach(() => {
  token = 'token-a';
  listeners.clear();
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('useLiveNotifications', () => {
  it('a push refetches the list, so the count moves at once', async () => {
    list.mockResolvedValueOnce({ unread: 0, items: [] });
    await render();
    expect(subscribeNotifications).toHaveBeenCalledTimes(1);
    expect(bell().getAttribute('aria-label')).toBe('Notifications');
    expect(list).toHaveBeenCalledTimes(1);

    list.mockResolvedValueOnce({ unread: 1, items: [notice('n1')] });
    await push('n1');
    expect(list).toHaveBeenCalledTimes(2);
    expect(bell().getAttribute('aria-label')).toBe('Notifications, 1 unread');
  });

  it('never subscribes while signed out', async () => {
    token = null;
    await render();
    expect(subscribeNotifications).not.toHaveBeenCalled();
    expect(listeners.size).toBe(0);
  });

  it('unsubscribes on unmount and on sign-out, and a new sign-in subscribes afresh', async () => {
    list.mockResolvedValue({ unread: 0, items: [] });
    await render();
    expect(listeners.size).toBe(1);

    token = null;
    await render();
    expect(listeners.size).toBe(0);

    token = 'token-b';
    await render();
    expect(subscribeNotifications).toHaveBeenCalledTimes(2);
    expect(listeners.size).toBe(1);

    act(() => root.unmount());
    expect(listeners.size).toBe(0);
    root = createRoot(host);
  });

  it('the layout mounts it once, for both bells', () => {
    const src = Object.values(
      import.meta.glob('../../layouts/AppLayout.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
    )[0];
    expect(src.match(/useLiveNotifications\(\)/g)?.length).toBe(1);
    expect(src.match(/<NotificationBell\b/g)?.length).toBe(2);
  });
});
