/**
 * S-3.1.1 / T-3.1.1.1: on the Echo page, a fact whose label holds `/` is added
 * and forgotten like any other. The form refused such a label because the
 * delete route could not address it; the route now reads the key as the rest
 * of its path, so the refusal is gone.
 *
 * Mutation checks, run on 2026-11-10: the old slash refusal in
 * `validateContextKey` put back fails "adds a fact whose label holds a slash"
 * (the Add button stays disabled and the error shows).
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { PersonalContextItem, RecordContextPayload } from '../../services/echoApi';
import { createQueryClient } from '../../services/queryClient';
import { buttonsLabelled, clearToasts, flush, press, typeInto } from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const ROW: PersonalContextItem = {
  id: 'c1', kind: 'skill', key: 'TCP/IP', value: 'Networking basics', source: 'manual', confidence: 1,
  captured_at: '2026-11-01T09:00:00Z', expires_at: null, kept_deleted_by: null,
};

const pending = () => new Promise<never>(() => undefined);
const api = {
  listContext: vi.fn(async () => [ROW]),
  recordContext: vi.fn(async (payload: RecordContextPayload) => ({ ...ROW, ...payload, id: 'c2' }) as PersonalContextItem),
  deleteContext: vi.fn(async (_kind: string, _key: string) => ({ deleted: true })),
};
vi.mock('../../services/echoApi', () => ({
  echoApi: {
    status: () => pending(),
    listConnectors: () => pending(),
    listFactTombstones: async () => ({ items: [] }),
    listContext: () => api.listContext(),
    recordContext: (payload: RecordContextPayload) => api.recordContext(payload),
    deleteContext: (kind: string, key: string) => api.deleteContext(kind, key),
    revokeSource: async () => ({ deleted_count: 0 }),
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

describe('the Echo page, a label holding a slash', () => {
  it('adds a fact whose label holds a slash', async () => {
    await mount();
    await press('Add a fact');
    const dialog = document.querySelector('[role="dialog"]') as HTMLElement;
    const [label] = Array.from(dialog.querySelectorAll('input')) as HTMLInputElement[];
    typeInto(label, 'work/2026/q4');
    typeInto(dialog.querySelector('textarea') as HTMLTextAreaElement, 'Planning the quarter');
    await flush();

    expect(document.body.textContent).not.toContain('cannot contain a slash');
    // The cards carry Add shortcuts too; the dialog's own button is the last.
    const add = buttonsLabelled('Add').at(-1)!;
    expect(dialog.contains(add)).toBe(true);
    expect(add.disabled).toBe(false);
    await press('Add', 'last');

    expect(api.recordContext).toHaveBeenCalledTimes(1);
    expect(api.recordContext.mock.calls[0][0]).toMatchObject({ kind: 'interest', key: 'work/2026/q4' });
  });

  it('forgets a fact whose label holds a slash by its whole key', async () => {
    await mount();
    await press('Forget');
    await press('Forget', 'last');

    expect(api.deleteContext).toHaveBeenCalledTimes(1);
    expect(api.deleteContext).toHaveBeenCalledWith('skill', 'TCP/IP');
  });
});
