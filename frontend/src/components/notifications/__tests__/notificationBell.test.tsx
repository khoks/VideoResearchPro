/**
 * S-8.3.3: the bell. The unread count is on the button and in its label,
 * opening a notice marks it read and goes to its page, "Mark all read"
 * clears the count, Escape closes and gives focus back. The layout mounts it.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { NotificationList } from '../../../services/notificationsApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const api = {
  list: vi.fn<() => Promise<NotificationList>>(),
  markRead: vi.fn<(id: string) => Promise<unknown>>(async () => ({})),
  readAll: vi.fn<() => Promise<{ marked: number }>>(async () => ({ marked: 1 })),
};
vi.mock('../../../services/notificationsApi', () => ({
  notificationsApi: { list: () => api.list(), markRead: (id: string) => api.markRead(id), readAll: () => api.readAll() },
}));
vi.mock('../../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));

import { NotificationBell } from '../NotificationBell';

const LIST: NotificationList = {
  unread: 1,
  items: [
    { id: 'n1', kind: 'saved_search_changed', title: 'New answer: rate cuts', body: 'Now cites 1 new source.', href: '/saved-searches?search=s1&run=r1', read_at: null, created_at: new Date().toISOString().slice(0, 19) },
    { id: 'n0', kind: 'saved_search_changed', title: 'Older', body: null, href: null, read_at: '2026-10-18T10:00:00', created_at: '2026-10-18T09:00:00' },
  ],
};

let host: HTMLDivElement;
let root: Root;

function Where() {
  const loc = useLocation();
  return <output data-where>{loc.pathname + loc.search}</output>;
}

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/jobs']}>
          <Routes>
            <Route path="*" element={<NotificationBell />} />
          </Routes>
          <Where />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const bell = () => host.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!;
const byText = (t: string) => Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes(t)) as HTMLButtonElement;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  api.list.mockResolvedValue(LIST);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('NotificationBell', () => {
  it('shows the unread count on the button and in its name', async () => {
    await mount();
    expect(bell().getAttribute('aria-label')).toBe('Notifications, 1 unread');
    expect(bell().textContent).toContain('1');
  });

  it('opening a notice marks it read and goes to its page', async () => {
    await mount();
    act(() => bell().click());
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('Now cites 1 new source.');
    // Portalled: inside the sticky sidebar it would be painted under the page.
    expect(document.querySelector('[role="dialog"]')!.parentElement).toBe(document.body);
    await act(async () => byText('New answer: rate cuts').click());
    await flush();
    expect(api.markRead).toHaveBeenCalledWith('n1');
    expect(host.querySelector('[data-where]')?.textContent).toBe('/saved-searches?search=s1&run=r1');
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it('a read notice is not marked again', async () => {
    await mount();
    act(() => bell().click());
    await act(async () => byText('Older').click());
    expect(api.markRead).not.toHaveBeenCalled();
  });

  it('Mark all read, and Escape closes with focus back on the bell', async () => {
    await mount();
    act(() => bell().click());
    await act(async () => byText('Mark all read').click());
    expect(api.readAll).toHaveBeenCalled();
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(bell());
  });

  it('says what will appear when there is nothing', async () => {
    api.list.mockResolvedValue({ unread: 0, items: [] });
    await mount();
    expect(bell().getAttribute('aria-label')).toBe('Notifications');
    act(() => bell().click());
    expect(document.body.textContent).toContain('Nothing new.');
  });

  it('is mounted by the layout', () => {
    const src = Object.values(
      import.meta.glob('../../../layouts/AppLayout.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
    )[0];
    expect(src.match(/<NotificationBell\b/g)?.length).toBe(2); // sidebar and mobile bar
  });
});
