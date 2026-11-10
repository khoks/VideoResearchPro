/**
 * T-3.4.1.27: a change of plan while the Echo page is open shows the upgrade
 * card, and no toast beside it, whatever order the page's reads answer in.
 *
 * The plan changes in another tab, then the reader comes back to this one: a
 * window focus refreshes every Echo read at once, and each answers 403 (the
 * Studio gate, every Echo route's one 403). The card takes the place of the
 * page's sections, so a section's refusal that lands after it has no reader left
 * to stand aside, and used to toast beside the card, once per section. The page
 * now takes every Echo 403 while it is open and shows the card from the first
 * one on (`useEchoPlanRefusal`), worked out from the failure itself, so neither
 * the status read answering first, the account's plan answering first, nor the
 * sections answering first leaves a toast. A failure that is not a 403 still
 * toasts, and a 403 that lands once the page has gone toasts as before.
 *
 * Every section is the real one, under the app's own query client (retries as
 * the app has them); only Echo's API, the account read and the voice test panel
 * are stand-ins.
 *
 * Mutation checks, run on 2026-11-10: the page without `useEchoPlanRefusal`
 * fails every "no toast" row (a toast per section beside the card); the hook
 * without its `sayFailuresOnPage` rule fails the same rows; the hook without its
 * listener (no card until the status or context read is refused) fails "shows
 * the card for a section's refusal"; without the status-success clause, "a
 * status read that succeeds again" keeps the card; a rule left registered after
 * unmount fails "once the page has gone".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DraftStatus } from '../../services/echoApi';
import { createQueryClient } from '../../services/queryClient';
import { ME_QUERY_KEY, type Tier } from '../../hooks/useMe';
import { PLAN_WORDS, clearToasts, failures, flush, refusedByPlan, toastMessages } from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// Echo's API: every read answers, or is refused, each held until its gate opens
// ---------------------------------------------------------------------------

const STATUS = {
  ready: false,
  total_rows: 40,
  distinct_sources: 1,
  has_personality_trait: false,
  threshold_total: 100,
  threshold_sources: 3,
};
const DRAFTS_OFF: DraftStatus = {
  enabled: false,
  blockers: [{ code: 'install_off', message: 'Speak as me is turned off on this install.' }],
  readiness: {},
  voice_gate: { status: 'not_run', run_at: null, pairs: 0, picked_own_share: null, notes_total: 3, notes_needed: 40 },
  drafts_today: 0,
  drafts_per_day: 20,
  state: 'install_off',
  reasons: [],
  notes: 3,
  notes_needed: 40,
  pairs_judged: 0,
  pairs_needed: 20,
};

/** How each read answers now: with its data, refused by the plan, or with a 500. */
let mode: 'answer' | 'refuse' | 'fail' = 'answer';
/** Reads held until their gate opens, by method name; `*` holds the rest. */
const holds = new Map<string, Promise<void>>();
/** The reads asked for since the last `beginRefresh`. */
const asked: string[] = [];

function read<T>(name: string, data: T): Promise<T> {
  if (mode === 'answer' && holds.size === 0) return Promise.resolve(data);
  asked.push(name);
  const hold = holds.get(name) ?? holds.get('*') ?? Promise.resolve();
  return hold.then(() => {
    if (mode === 'refuse') return Promise.reject(refusedByPlan());
    if (mode === 'fail') return Promise.reject(failures.noWords());
    return data;
  });
}

vi.mock('../../services/echoApi', () => ({
  echoApi: {
    status: () => read('status', STATUS),
    listConnectors: () => read('listConnectors', { connectors: [], supported_kinds: [], items: [] }),
    listContext: () => read('listContext', []),
    listFactTombstones: () => read('listFactTombstones', { items: [] }),
    listActivity: () => read('listActivity', { items: [], next_before: null }),
    listSignals: () => read('listSignals', { items: [], consent_version: '2026-10-19', learning: null }),
    listRejectedSignals: () => read('listRejectedSignals', { items: [] }),
    draftStatus: () => read('draftStatus', DRAFTS_OFF),
    listDrafts: () => read('listDrafts', { items: [] }),
    listShareTokens: () => read('listShareTokens', { items: [], max: 10 }),
    footprint: () => read('footprint', { rows: {}, files: 0, vectors: {} }),
  },
}));

// The account's plan, read as the app reads it (`useTierCapabilities` → `useMe`).
let plan: Tier = 'studio';
vi.mock('../../services/api', () => ({
  default: {
    defaults: { baseURL: 'http://localhost:8000/api/v1' },
    get: (url: string) =>
      url === '/auth/me'
        ? Promise.resolve({ data: { id: 'u1', email: 'reader@example.com', created_at: '2026-10-01T00:00:00', tier: plan } })
        : Promise.reject(new Error(`unexpected GET ${url}`)),
  },
}));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));
// Reads the voice test overview, a shape of its own; nothing here is about it.
vi.mock('../../components/echo/VoiceTestPanel', () => ({ VoiceTestPanel: () => null }));

import { EchoPage } from '../EchoPage';

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

let host: HTMLDivElement;
let root: Root;

function gate(): { promise: Promise<void>; open: () => void } {
  let open = () => undefined as void;
  const promise = new Promise<void>((resolve) => {
    open = resolve;
  });
  return { promise, open };
}

async function settle() {
  await flush();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  await flush();
}

function render(client: QueryClient, page = true) {
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/echo']}>{page ? <EchoPage /> : <p>Elsewhere</p>}</MemoryRouter>
      </QueryClientProvider>,
    ),
  );
}

/** The Echo page with every read answered and readiness on screen. */
async function openPage(): Promise<QueryClient> {
  const client = createQueryClient();
  render(client);
  await settle();
  expect(text()).toContain("You're on the way.");
  expect(text()).not.toContain(UPGRADE);
  return client;
}

/** A window focus once the plan has changed: every Echo read refreshed at once,
 * and the account's plan with them. */
function beginRefresh(client: QueryClient, how: typeof mode) {
  asked.length = 0;
  mode = how;
  act(() => {
    void client.invalidateQueries({ queryKey: ['echo'] });
    void client.invalidateQueries({ queryKey: ME_QUERY_KEY });
  });
}

const UPGRADE = 'Echo opens at Studio.';
/** The sections the card takes the place of, by the read each starts with. */
const SECTION_READS = ['listActivity', 'listFactTombstones', 'listSignals', 'draftStatus', 'listShareTokens', 'footprint'];
const text = () => document.body.textContent ?? '';
const count = (needle: string) => text().split(needle).length - 1;
const failed = (client: QueryClient, queryKey: readonly unknown[]) => client.getQueryState(queryKey)?.status === 'error';

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  mode = 'answer';
  plan = 'studio';
  holds.clear();
  asked.length = 0;
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// The rows
// ---------------------------------------------------------------------------

describe('a change of plan while the Echo page is open', () => {
  it('shows the card and no toast when the status read is refused first', async () => {
    const client = await openPage();
    const sections = gate();
    holds.set('*', sections.promise);
    holds.set('status', Promise.resolve());
    beginRefresh(client, 'refuse');
    await settle();
    // The status read is refused (after its retry) and the card has taken the
    // sections' place, while their reads are still out.
    expect(count(UPGRADE)).toBe(1);
    expect(text()).not.toContain("You're on the way.");
    expect(asked).toEqual(expect.arrayContaining(SECTION_READS));

    act(() => sections.open());
    await settle();
    // Each section's refusal has landed, with its reader gone.
    expect(failed(client, ['echo', 'share-tokens'])).toBe(true);
    expect(failed(client, ['echo', 'fact-tombstones'])).toBe(true);
    expect(failed(client, ['echo', 'footprint'])).toBe(true);
    expect(count(UPGRADE)).toBe(1);
    expect(toastMessages()).toEqual([]);
  });

  it('shows the card and no toast when the account read answers first', async () => {
    const client = await openPage();
    const echo = gate();
    holds.set('*', echo.promise);
    plan = 'pro';
    beginRefresh(client, 'refuse');
    await settle();
    // The plan says no Echo: the card, while every Echo read is still out. The
    // page's own readers stay mounted, but disabled, so none stands aside.
    expect(count(UPGRADE)).toBe(1);
    expect(text()).toContain('Your plan is pro.');

    act(() => echo.open());
    await settle();
    await settle();
    expect(failed(client, ['echo', 'status'])).toBe(true);
    expect(failed(client, ['echo', 'share-tokens'])).toBe(true);
    expect(count(UPGRADE)).toBe(1);
    expect(toastMessages()).toEqual([]);
  });

  it('shows the card for a section’s refusal, before the status read answers, and no toast', async () => {
    const client = await openPage();
    const own = gate();
    // The page's own two reads, whose 403 shows the card on its own, are held.
    holds.set('status', own.promise);
    holds.set('listContext', own.promise);
    beginRefresh(client, 'refuse');
    await settle();
    expect(failed(client, ['echo', 'share-tokens'])).toBe(true);
    expect(client.getQueryState(['echo', 'status'])?.fetchStatus).toBe('fetching');
    expect(count(UPGRADE)).toBe(1);
    expect(toastMessages()).toEqual([]);

    act(() => own.open());
    await settle();
    await settle();
    expect(failed(client, ['echo', 'status'])).toBe(true);
    expect(count(UPGRADE)).toBe(1);
    expect(toastMessages()).toEqual([]);
  });

  it('takes the card away when a status read succeeds again (the plan is back)', async () => {
    const client = await openPage();
    holds.set('status', Promise.resolve());
    holds.set('*', Promise.resolve());
    beginRefresh(client, 'refuse');
    await settle();
    await settle();
    expect(count(UPGRADE)).toBe(1);

    holds.clear();
    beginRefresh(client, 'answer');
    await settle();
    expect(text()).toContain("You're on the way.");
    expect(text()).not.toContain(UPGRADE);
    expect(toastMessages()).toEqual([]);
  });

  it('still toasts a refresh that fails otherwise behind the sections', async () => {
    const client = await openPage();
    holds.set('*', Promise.resolve());
    beginRefresh(client, 'fail');
    await settle();
    await settle();
    expect(text()).not.toContain(UPGRADE);
    // The share tokens, the tombstones and the activity say nothing on the page;
    // readiness keeps what it read, so its refresh toasts too.
    expect(toastMessages().length).toBeGreaterThan(0);
    expect(toastMessages().every((m) => m === 'Request failed with status code 500')).toBe(true);
  });

  it('toasts a refusal that lands once the page has gone', async () => {
    const client = await openPage();
    const echo = gate();
    holds.set('*', echo.promise);
    beginRefresh(client, 'refuse');
    await flush();
    render(client, false);
    await flush();
    act(() => echo.open());
    await settle();
    await settle();
    expect(toastMessages()).toContain(PLAN_WORDS);
  });
});
