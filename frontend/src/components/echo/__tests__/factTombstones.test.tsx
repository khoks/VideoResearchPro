/**
 * T-3.2.4.4: deleted derived facts stay deleted. The Echo page lists them
 * under "Kept deleted" and "Allow again" clears one through the API; the
 * delete dialog says a derived fact will be kept deleted.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { FactTombstone } from '../../../services/echoApi';
import { useJobStore } from '../../../stores/jobStore';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const api = {
  listFactTombstones: vi.fn<() => Promise<{ items: FactTombstone[] }>>(),
  clearFactTombstone: vi.fn(async (_id: string) => ({ cleared: true })),
};
vi.mock('../../../services/echoApi', () => ({
  echoApi: {
    listFactTombstones: () => api.listFactTombstones(),
    clearFactTombstone: (id: string) => api.clearFactTombstone(id),
  },
}));

import { FactTombstones, clearedToast, isDerivedSource, keptDeletedNote } from '../FactTombstones';

const PYTHON: FactTombstone = {
  id: 'tomb-1',
  connector: 'github',
  connector_display_name: 'GitHub',
  kind: 'skill',
  key: 'Python (GitHub)',
  created_at: '2026-11-01T09:00:00Z',
};

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount(enabled = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <FactTombstones enabled={enabled} />
      </QueryClientProvider>,
    ),
  );
  await flush();
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  api.listFactTombstones.mockReset().mockResolvedValue({ items: [PYTHON] });
  api.clearFactTombstone.mockClear();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('FactTombstones', () => {
  it('lists deleted derived facts with where they came from', async () => {
    await mount();
    const section = host.querySelector('[data-fact-tombstones]')!;
    expect(section.querySelector('summary')?.textContent).toBe('Kept deleted (1)');
    const row = section.querySelector('[data-fact-tombstone="tomb-1"]')!;
    expect(row.textContent).toContain('Python (GitHub)');
    expect(row.textContent).toContain('Skill');
    expect(row.textContent).toContain('from GitHub');
  });

  it('“Allow again” clears the tombstone through the API and says what happens next', async () => {
    await mount();
    const before = api.listFactTombstones.mock.calls.length;
    const allow = Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Allow again')!;
    await act(async () => allow.click());
    await flush();
    expect(api.clearFactTombstone).toHaveBeenCalledWith('tomb-1');
    expect(api.listFactTombstones.mock.calls.length).toBeGreaterThan(before);
    expect(useJobStore.getState().toasts.map((t) => t.message)).toContain(clearedToast(PYTHON));
  });

  it('shows nothing when no fact is kept deleted, and asks nothing while Echo is not allowed', async () => {
    api.listFactTombstones.mockResolvedValue({ items: [] });
    await mount();
    expect(host.querySelector('[data-fact-tombstones]')).toBeNull();
    act(() => root.unmount());
    root = createRoot(host);
    api.listFactTombstones.mockClear();
    await mount(false);
    expect(api.listFactTombstones).not.toHaveBeenCalled();
  });
});

describe('the delete dialog note', () => {
  it('names connector and import facts as kept deleted, not facts the user typed', () => {
    expect(isDerivedSource('connector:github')).toBe(true);
    expect(isDerivedSource('import:abc')).toBe(true);
    expect(isDerivedSource('manual')).toBe(false);
    expect(keptDeletedNote('connector:github')).toContain('keep it deleted');
    expect(keptDeletedNote('manual')).toBeNull();
    expect(keptDeletedNote(undefined)).toBeNull();
  });
});

describe('wiring', () => {
  it('the Echo page mounts the list and adds the note to its delete dialog', () => {
    const page = Object.values(
      import.meta.glob('../../../pages/EchoPage.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
    )[0];
    expect(page).toMatch(/<FactTombstones enabled=\{allowed\} \/>/);
    expect(page).toContain('keptDeletedNote(deleting?.source)');
  });
});
