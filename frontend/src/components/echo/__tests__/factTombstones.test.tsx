/**
 * T-3.2.4.4: deleted derived facts stay deleted. The Echo page lists them
 * under "Kept deleted" and "Allow again" clears one through the API; the
 * delete dialog says which rows will be kept deleted, from the server's answer
 * (T-3.2.1.14), so a row the user wrote that a connector wants is included.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { FactTombstone, PersonalContextItem } from '../../../services/echoApi';
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

import { FactTombstones, clearedToast, isDerivedSource, keptDeletedNote, revokedKeptNote } from '../FactTombstones';

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
  it('says a derived fact will be kept deleted, and names who worked it out', () => {
    expect(isDerivedSource('connector:github')).toBe(true);
    expect(isDerivedSource('import:abc')).toBe(true);
    expect(isDerivedSource('manual')).toBe(false);
    expect(keptDeletedNote({ source: 'connector:github', kept_deleted_by: 'GitHub' })).toBe(
      'Echo worked this out from GitHub, so it will keep it deleted: later syncs and re-imports skip it. You can allow it again under "Kept deleted".',
    );
  });

  it('says so for a row the user wrote that a connector wants: source alone reads manual', () => {
    expect(keptDeletedNote({ source: 'manual', kept_deleted_by: 'GitHub' })).toBe(
      'You wrote this, but GitHub works out the same entry, so Echo will keep it deleted: later syncs and re-imports skip it. You can allow it again under "Kept deleted".',
    );
  });

  it('says nothing for a row nothing wants, whatever its source claims', () => {
    expect(keptDeletedNote({ source: 'manual', kept_deleted_by: null })).toBeNull();
    expect(keptDeletedNote({ source: 'manual' })).toBeNull();
    expect(keptDeletedNote({ source: 'import:gone', kept_deleted_by: null })).toBeNull();
    expect(keptDeletedNote(undefined)).toBeNull();
    expect(keptDeletedNote(null)).toBeNull();
  });
});

describe('the revoke dialog note', () => {
  const row = (source: string, kept_deleted_by: string | null): PersonalContextItem => ({
    id: source + String(kept_deleted_by), kind: 'skill', key: 'python', value: 'x', source, confidence: 1,
    captured_at: '2026-11-01T09:00:00Z', expires_at: null, kept_deleted_by,
  });

  it('keeps what it said about a connector', () => {
    expect(revokedKeptNote('connector:github', [])).toContain('skip these facts from now on');
  });

  it('counts the rows of this source that will stay deleted, and only those', () => {
    const rows = [row('manual', 'GitHub'), row('manual', null), row('connector:github', 'GitHub')];
    expect(revokedKeptNote('manual', rows)).toBe(
      'One of them is also worked out by a connector or an import, so Echo will keep it deleted (see "Kept deleted").',
    );
    expect(revokedKeptNote('manual', [...rows, row('manual', 'Apple Health')])).toBe(
      '2 of them are also worked out by a connector or an import, so Echo will keep those deleted (see "Kept deleted").',
    );
  });

  it('says nothing when nothing wants any of them', () => {
    expect(revokedKeptNote('manual', [row('manual', null)])).toBeNull();
    expect(revokedKeptNote(undefined, [])).toBeNull();
  });
});

describe('wiring', () => {
  it('the Echo page mounts the list and adds the note to its delete dialog', () => {
    const page = Object.values(
      import.meta.glob('../../../pages/EchoPage.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
    )[0];
    expect(page).toMatch(/<FactTombstones enabled=\{allowed\} \/>/);
    expect(page).toContain('keptDeletedNote(deleting)');
    expect(page).toContain('revokedKeptNote(revoking?.source, allRows)');
  });
});
