/**
 * T-3.4.1.17: the Echo page's own failures, each one toast. Saving, forgetting
 * and revoking a fact used to toast from the page's `mutate` call and again from
 * the global handler. The page now leaves it to the hooks (`useRecordContext`,
 * `useDeleteContext`, `useRevokeSource`), which say the server's words or the
 * page's sentence and set `meta.errorsShownHere`, and nothing of a 401.
 *
 * Mutation checks, run on 2026-11-09: `meta` off the three hooks fails every
 * failure row but `sessionEnded` with two toasts; the page's old `onError` on
 * revoke put back fails each of that site's rows, a 401 included;
 * `toastMutationError` without its 401 check fails each `sessionEnded` row.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { PersonalContextItem } from '../../services/echoApi';
import { createQueryClient } from '../../services/queryClient';
import {
  FAILURE_KINDS,
  clearToasts,
  expectedToasts,
  failures,
  flush,
  press,
  toastMessages,
} from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const ROW: PersonalContextItem = {
  id: 'c1', kind: 'interest', key: 'tariffs', value: 'Trade policy', source: 'manual', confidence: 1,
  captured_at: '2026-11-01T09:00:00Z', expires_at: null, kept_deleted_by: null,
};

const pending = () => new Promise<never>(() => undefined);
const api = {
  listContext: vi.fn(async () => [ROW]),
  recordContext: vi.fn(async () => ROW),
  deleteContext: vi.fn(async () => ({ deleted: true })),
  revokeSource: vi.fn(async () => ({ deleted_count: 1 })),
};
vi.mock('../../services/echoApi', () => ({
  echoApi: {
    // Readiness and connectors stay loading: nothing here is about them.
    status: () => pending(),
    listConnectors: () => pending(),
    listFactTombstones: async () => ({ items: [] }),
    listContext: () => api.listContext(),
    recordContext: () => api.recordContext(),
    deleteContext: () => api.deleteContext(),
    revokeSource: () => api.revokeSource(),
  },
}));
vi.mock('../../hooks/useTierCapabilities', () => ({
  useTierCapabilities: () => ({ has: () => true, tier: 'studio', isLoading: false }),
}));
vi.mock('../../components/echo/EchoDataCard', () => ({ EchoDataCard: () => null }));
vi.mock('../../components/echo/ShareTokensCard', () => ({ ShareTokensCard: () => null }));
vi.mock('../../components/echo/SignalsPanel', () => ({ SignalsPanel: () => null }));
vi.mock('../../components/echo/SpeakAsMePanel', () => ({ SpeakAsMePanel: () => null }));
vi.mock('../../components/echo/ActivityTimeline', () => ({ ActivityTimeline: () => null }));
vi.mock('../../components/echo/ConnectorsPanel', () => ({ ConnectorsPanel: () => null }));
vi.mock('../../components/echo/ReadinessDomains', () => ({ ReadinessDomains: () => null }));

import { EchoPage } from '../EchoPage';

let host: HTMLDivElement;
let root: Root;

async function mount() {
  act(() =>
    root.render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={['/echo']}>
          <EchoPage />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  for (const fn of Object.values(api)) fn.mockClear();
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const SITES = [
  {
    name: 'saving a fact',
    call: () => api.recordContext,
    go: async () => {
      await press('Edit');
      await press('Save');
    },
    fallback: 'Could not save this entry.',
  },
  {
    name: 'forgetting a fact',
    call: () => api.deleteContext,
    go: async () => {
      await press('Forget');
      await press('Forget', 'last');
    },
    fallback: 'Delete failed. The entry may already be gone.',
  },
  {
    name: 'revoking a source',
    call: () => api.revokeSource,
    go: async () => {
      await press('Revoke');
      await press('Revoke and delete');
    },
    fallback: 'Revoke failed.',
  },
];

describe.each(SITES)('the Echo page, $name', (site) => {
  it.each(FAILURE_KINDS)('says a failure (%s) once', async (kind) => {
    site.call().mockRejectedValueOnce(failures[kind]());
    await mount();
    await site.go();
    expect(site.call()).toHaveBeenCalledTimes(1);
    expect(toastMessages()).toEqual(expectedToasts(kind, site.fallback));
  });
});

describe('the Echo page', () => {
  it('still thanks the reader when it works', async () => {
    await mount();
    await press('Revoke');
    await press('Revoke and delete');
    expect(toastMessages()).toEqual(['Removed 1 entry from manual.']);
  });
});
