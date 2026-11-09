/**
 * T-3.4.1.24 at the draft view (`DraftEditor`), under the app's own query
 * client, on both surfaces that show it: the Echo page's "Speak as me" card and
 * a draft turn in the Echo bubble.
 *
 * A failed "Save my version" said "Couldn't save your version. Try again." on
 * the view's line and the global toast said it again. Now `useDraftFeedback`
 * sets `meta: ERRORS_SHOWN_HERE` (the view is its one caller), the line gives
 * the server's words through `inlineErrorMessage`, and a 401 says nothing.
 *
 * The line is the one message, so the surface it sits on waits while a save is
 * in flight (D-159 point 2): on the Echo page, Open and Delete in Recent drafts
 * and the draft buttons, any of which would put another draft (or none) in the
 * view's place; in the bubble, its close button, Escape, Clear and the opener,
 * any of which would close it.
 *
 * "A message" here is a toast or a line with `role="alert"`.
 *
 * Mutation checks, run on 2026-11-09: taking `meta` off `useDraftFeedback` fails
 * both surfaces' `words`, `noWords` and `noAnswer` rows with the line and a
 * toast; the old fixed sentence back in the view fails both `words` rows;
 * `apiErrorMessage` in place of `inlineErrorMessage` fails both `sessionEnded`
 * rows with "Not authenticated"; dropping `disabled={saving}` from Recent
 * drafts' Open, or the `saving` check from the bubble's Escape, or
 * `usePanelToggle` from the bubble's opener, fails that surface's "waits for a
 * save in flight".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DraftResponse, DraftStatus, EchoDraft, EchoStatus } from '../../../services/echoApi';
import { createQueryClient } from '../../../services/queryClient';
import { useEchoPanelStore } from '../../../stores/echoPanelStore';
import { useJobStore } from '../../../stores/jobStore';
import {
  FAILURE_KINDS,
  clearToasts,
  expectedToasts,
  failures,
  flush,
  toastMessages,
} from '../../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const FALLBACK = "Couldn't save your version. Try again.";

const DRAFT: EchoDraft = {
  id: 'd1', message: 'Who pays?', draft: 'Mostly the importer pays first.', language: 'en', register: 'casual', audience: null,
  intent: 'opinion', voice_match_score: 80, confidence: 0.8, citations: [], deviation_notes: [], flags: [],
  disclosure: '', final_text: null, disclosure_kept: null, feedback_at: null, edit: null, created_at: '2026-10-20T10:00:00',
};
const OTHER: EchoDraft = { ...DRAFT, id: 'd2', draft: 'Nobody pays, in the end.' };

const GATE = { status: 'passed' as const, run_at: null, pairs: 20, picked_own_share: 0.9, notes_total: 50, notes_needed: 40 };
const ON: DraftStatus = {
  enabled: true, blockers: [], readiness: {}, voice_gate: GATE, drafts_today: 0, drafts_per_day: 20, state: 'enabled',
  reasons: [], notes: 50, notes_needed: 40, pairs_judged: 20, pairs_needed: 20,
};
const STATUS: EchoStatus = {
  ready: false, total_rows: 40, distinct_sources: 1, has_personality_trait: false, threshold_total: 100, threshold_sources: 3,
};

const api = {
  draftFeedback: vi.fn<(id: string, p: unknown) => Promise<EchoDraft>>(),
  createDraft: vi.fn<(p: unknown) => Promise<EchoDraft>>(),
  deleteDraft: vi.fn(async () => undefined),
};

vi.mock('../../../services/echoApi', async (orig) => ({
  ...(await orig<typeof import('../../../services/echoApi')>()),
  echoApi: {
    status: async () => STATUS,
    listConnectors: async () => ({ connectors: [] }),
    draftStatus: async () => ON,
    draft: vi.fn(),
    cards: async () => ({ cards: [], muted_kinds: [] }),
    cardSettings: async () => ({ kinds: {} }),
    cardShown: async () => undefined,
    listDrafts: async () => ({ items: [DRAFT, OTHER] }),
    createDraft: (p: unknown) => api.createDraft(p),
    deleteDraft: () => api.deleteDraft(),
    draftFeedback: (id: string, p: unknown) => api.draftFeedback(id, p),
    voiceTest: async () => ({
      offer: {
        available: false, blockers: [], pairs: 20, model_calls: 40, model: 'gpt-5.5', notes: 50, notes_needed: 40,
        pass_share: 0.8, tests_today: 0, tests_per_day: 3,
      },
      gate: GATE,
      test: null,
    }),
  },
}));
vi.mock('../../../services/suggestionsApi', () => ({
  suggestionsApi: { get: async () => ({ suggestions: [] }), feedback: async () => undefined },
}));
vi.mock('../../../services/libraryQaApi', () => ({
  libraryQaApi: { ask: vi.fn(), getHistory: async () => [], clarify: vi.fn() },
}));
vi.mock('../../../services/qaHistoryApi', () => ({
  qaHistoryApi: { postChat: vi.fn(), getExchanges: async () => [] },
}));

import { SpeakAsMePanel } from '../SpeakAsMePanel';
import { EchoBubble, EchoPanelHost } from '../EchoPanel';

let host: HTMLDivElement;
let root: Root;

async function mount(node: React.ReactNode) {
  act(() =>
    root.render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={['/echo']}>{node}</MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

/** Every failure said on screen: the error toasts, then each `role="alert"` line. */
function messages(): string[] {
  const toasts = useJobStore.getState().toasts.filter((t) => t.kind === 'error').map((t) => t.message);
  const lines = Array.from(document.querySelectorAll('[role="alert"]')).map((el) => el.textContent?.trim() ?? '');
  return [...toasts, ...lines.filter(Boolean)];
}

const buttons = (label: string, within: ParentNode = document) =>
  Array.from(within.querySelectorAll<HTMLButtonElement>('button')).filter((b) => b.textContent?.trim() === label);

async function click(el: HTMLElement) {
  await act(async () => el.click());
  await flush();
}

/** A request that answers when the test says. */
function held<T>() {
  let fail: (reason: unknown) => void = () => undefined;
  const promise = new Promise<T>((_resolve, reject) => {
    fail = reject;
  });
  return { promise, fail };
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  api.draftFeedback.mockReset().mockResolvedValue({ ...DRAFT, final_text: DRAFT.draft, disclosure_kept: true, feedback_at: '2026-10-20T10:05:00' });
  api.createDraft.mockReset().mockResolvedValue(OTHER);
  api.deleteDraft.mockClear();
  useEchoPanelStore.setState({ open: false, mode: 'ask', target: 'library', turns: [], askText: '' });
  clearToasts();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

// ---------------------------------------------------------------------------
// The Echo page's card
// ---------------------------------------------------------------------------

/** The page with draft d1 open from Recent drafts. */
async function openOnPage() {
  await mount(<SpeakAsMePanel />);
  await click(buttons('Open')[0]);
  expect(host.querySelector('[data-result]')).not.toBeNull();
}

const pageView = () => host.querySelector('[data-result]') as HTMLElement;

describe('the Echo page’s draft', () => {
  it.each(FAILURE_KINDS)('says a failed save (%s) once, on its own line', async (kind) => {
    api.draftFeedback.mockRejectedValueOnce(failures[kind]());
    await openOnPage();
    await click(buttons('Save my version', pageView())[0]);
    expect(api.draftFeedback).toHaveBeenCalledTimes(1);
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(expectedToasts(kind, FALLBACK));
  });

  it('says nothing when the save goes through', async () => {
    await openOnPage();
    await click(buttons('Save my version', pageView())[0]);
    expect(api.draftFeedback).toHaveBeenCalledTimes(1);
    expect(messages()).toEqual([]);
  });

  it('waits for a save in flight before another draft can take the view’s place', async () => {
    const request = held<EchoDraft>();
    api.draftFeedback.mockReturnValueOnce(request.promise);
    await openOnPage();
    await click(buttons('Save my version', pageView())[0]);
    // Open, Delete and a new draft would each replace the view and its line.
    for (const b of [...buttons('Open'), ...buttons('Delete'), ...buttons('Draft a reply')]) expect(b.disabled).toBe(true);
    await click(buttons('Open')[1]);
    expect(pageView().textContent).toContain(DRAFT.draft);
    await act(async () => request.fail(failures.noWords()));
    await flush();
    expect(messages()).toEqual([FALLBACK]);
    for (const b of [...buttons('Open'), ...buttons('Delete')]) expect(b.disabled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// A draft turn in the Echo bubble
// ---------------------------------------------------------------------------

const TURN = { id: 't1', kind: 'draft' as const, text: 'Who pays?', status: 'done' as const, result: DRAFT as DraftResponse };

async function openInBubble() {
  useEchoPanelStore.setState({ open: true, turns: [TURN] });
  await mount(
    <>
      <EchoBubble />
      <EchoPanelHost />
    </>,
  );
}

const panel = () => document.querySelector<HTMLElement>('#echo-panel');
const turnView = () => panel()!.querySelector('[data-echo-turn="draft"]') as HTMLElement;

function pressEscape() {
  act(() => {
    panel()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  });
}

describe('the bubble’s draft', () => {
  it.each(FAILURE_KINDS)('says a failed save (%s) once, in its turn', async (kind) => {
    api.draftFeedback.mockRejectedValueOnce(failures[kind]());
    await openInBubble();
    await click(buttons('Save my version', turnView())[0]);
    expect(api.draftFeedback).toHaveBeenCalledTimes(1);
    expect(toastMessages()).toEqual([]);
    expect(messages()).toEqual(expectedToasts(kind, FALLBACK));
  });

  it('says nothing when the save goes through', async () => {
    await openInBubble();
    await click(buttons('Save my version', turnView())[0]);
    expect(api.draftFeedback).toHaveBeenCalledTimes(1);
    expect(messages()).toEqual([]);
  });

  it('waits for a save in flight before it closes, then says its failure', async () => {
    const request = held<EchoDraft>();
    api.draftFeedback.mockReturnValueOnce(request.promise);
    await openInBubble();
    await click(buttons('Save my version', turnView())[0]);
    const close = panel()!.querySelector<HTMLButtonElement>('button[aria-label="Close Echo"]')!;
    expect(close.disabled).toBe(true);
    expect(buttons('Clear', panel()!)[0].disabled).toBe(true);
    pressEscape();
    await click(document.querySelector<HTMLButtonElement>('.pratidhvani-echo-bubble')!);
    expect(panel()).not.toBeNull();
    expect(useEchoPanelStore.getState().turns).toHaveLength(1);
    await act(async () => request.fail(failures.noWords()));
    await flush();
    expect(panel()).not.toBeNull();
    expect(messages()).toEqual([FALLBACK]);
    pressEscape();
    await flush();
    expect(panel()).toBeNull();
  });

  it('a save on the Echo page does not hold the bubble', async () => {
    const request = held<EchoDraft>();
    api.draftFeedback.mockReturnValueOnce(request.promise);
    useEchoPanelStore.setState({ open: true, turns: [] });
    await mount(
      <>
        <SpeakAsMePanel />
        <EchoPanelHost />
      </>,
    );
    await click(buttons('Open')[0]);
    await click(buttons('Save my version', pageView())[0]);
    pressEscape();
    await flush();
    expect(panel()).toBeNull();
    await act(async () => request.fail(failures.words()));
    await flush();
  });
});
