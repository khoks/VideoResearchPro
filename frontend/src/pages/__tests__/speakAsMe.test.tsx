/**
 * S-3.4.1: the "Speak as me" panel. While any gate is shut it says which, in
 * the server's words, and offers no composer; once open it drafts, shows the
 * draft with its disclosure, voice score, citations and notes, handles the
 * private-person confirmation, and says when the daily cap is reached. The
 * Echo page mounts it for tiers with the feature.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DraftStatus, EchoDraft } from '../../services/echoApi';
import { useJobStore } from '../../stores/jobStore';
import { citationLabel, draftErrorOf } from '../../utils/echoDrafts';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const api = {
  draftStatus: vi.fn<() => Promise<DraftStatus>>(),
  createDraft: vi.fn<(p: unknown) => Promise<EchoDraft>>(),
  listDrafts: vi.fn(async () => ({ items: [] as EchoDraft[] })),
  deleteDraft: vi.fn(async () => undefined),
};
vi.mock('../../services/echoApi', () => ({
  echoApi: {
    draftStatus: () => api.draftStatus(),
    createDraft: (p: unknown) => api.createDraft(p),
    listDrafts: () => api.listDrafts(),
    deleteDraft: () => api.deleteDraft(),
  },
}));

import { SpeakAsMePanel } from '../../components/echo/SpeakAsMePanel';

const GATE = { status: 'not_run' as const, run_at: null, pairs: 0, picked_own_share: null, notes_total: 3, notes_needed: 40 };
const OFF: DraftStatus = {
  enabled: false,
  blockers: [
    { code: 'install_off', message: 'Speak as me is turned off on this install.' },
    { code: 'voice_test_required', message: 'Speak as me turns on after you pass the test. It needs 40 of your notes; you have 3.' },
  ],
  readiness: {},
  voice_gate: GATE,
  drafts_today: 0,
  drafts_per_day: 20,
  state: 'install_off',
  reasons: [],
  notes: 3,
  notes_needed: 40,
  pairs_judged: 0,
  pairs_needed: 20,
};
const ON: DraftStatus = { ...OFF, enabled: true, blockers: [], state: 'enabled', voice_gate: { ...GATE, status: 'passed' } };
const DRAFT: EchoDraft = {
  id: 'd1', message: 'Who pays?', draft: 'Mostly the importer pays first.', language: 'en', register: 'casual', audience: 'my brother',
  intent: 'opinion', voice_match_score: 87.5, confidence: 0.8,
  citations: [{ kind: 'source', ref: 'S1', label: 'Tariff study — Econ', url: 'https://youtube.com/watch?v=x&t=42s' }, { kind: 'fact', ref: 'F1', label: 'what Echo knows about you' }],
  deviation_notes: ['Slightly more formal than you.'], flags: [], disclosure: 'Drafted with Echo, reviewed by sam',
  final_text: null, disclosure_kept: null, created_at: '2026-10-20T10:00:00',
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

async function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  act(() => root.render(<QueryClientProvider client={qc}><SpeakAsMePanel /></QueryClientProvider>));
  await flush();
}

const buttons = (label: string) =>
  Array.from(document.querySelectorAll('button')).filter((b) => b.textContent?.trim() === label) as HTMLButtonElement[];

function type(el: HTMLTextAreaElement | HTMLInputElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  api.draftStatus.mockReset().mockResolvedValue(OFF);
  api.createDraft.mockReset().mockResolvedValue(DRAFT);
  useJobStore.setState({ toasts: [] });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('helpers', () => {
  it('name citations in words', () => {
    expect(citationLabel({ kind: 'source', label: 'Tariff study' })).toBe('Tariff study');
    expect(citationLabel({ kind: 'note', label: 'x' })).toBe('your note');
    expect(citationLabel({ kind: 'qa', label: 'x' })).toBe('a question you asked before');
  });

  it('read the API error shapes', () => {
    expect(draftErrorOf({ response: { data: { detail: { code: 'names_need_confirmation', names: ['Priya'], message: 'm' } } } }))
      .toEqual({ code: 'names_need_confirmation', names: ['Priya'], message: 'm' });
    expect(draftErrorOf(new Error('x')).message).toBe('Could not draft a reply. Try again.');
  });
});

describe('SpeakAsMePanel', () => {
  it('while off, shows every gate in words and no composer', async () => {
    await mount();
    expect(host.textContent).toContain('Off');
    expect(host.querySelector('[data-blocker="install_off"]')?.textContent).toBe('Speak as me is turned off on this install.');
    expect(host.querySelector('[data-blocker="voice_test_required"]')?.textContent).toContain('you have 3');
    expect(host.querySelector('textarea')).toBeNull();
    expect(buttons('Draft a reply')).toHaveLength(0);
  });

  it('once on, drafts and shows the draft with its disclosure, score and sources', async () => {
    api.draftStatus.mockResolvedValue(ON);
    await mount();
    expect(host.textContent).toContain('On · 0 of 20 drafts today');
    act(() => type(host.querySelector('textarea')!, ' Who pays? '));
    act(() => type(host.querySelector('input')!, 'my brother'));
    await act(async () => buttons('Draft a reply')[0].click());
    await flush();
    expect(api.createDraft).toHaveBeenCalledWith({ message: 'Who pays?', audience: 'my brother' });
    const result = host.querySelector('[data-result]')!;
    expect(result.textContent).toContain('Mostly the importer pays first.');
    expect(result.querySelector('[data-disclosure]')?.textContent).toBe('Drafted with Echo, reviewed by sam');
    expect(result.textContent).toContain('Sounds like you: 88%');
    expect(result.querySelector('a[href="https://youtube.com/watch?v=x&t=42s"]')?.textContent).toBe('Tariff study — Econ');
    expect(result.textContent).toContain('what Echo knows about you');
    expect(result.querySelector('[data-notes]')?.textContent).toContain('Slightly more formal than you.');
  });

  it('asks before drafting about a private person, then sends the acknowledgement', async () => {
    api.draftStatus.mockResolvedValue(ON);
    api.createDraft.mockRejectedValueOnce({ response: { status: 409, data: { detail: { code: 'names_need_confirmation', names: ['Priya'], message: 'm' } } } });
    await mount();
    act(() => type(host.querySelector('textarea')!, 'Priya asked about dinner'));
    await act(async () => buttons('Draft a reply')[0].click());
    await flush();
    expect(host.querySelector('[data-names]')?.textContent).toContain('This message names Priya');
    await act(async () => buttons('Draft anyway')[0].click());
    await flush();
    expect(api.createDraft).toHaveBeenLastCalledWith({ message: 'Priya asked about dinner', acknowledge_names: ['Priya'] });
    expect(host.querySelector('[data-result]')).toBeTruthy();
  });

  it('says when the daily cap is reached', async () => {
    api.draftStatus.mockResolvedValue(ON);
    api.createDraft.mockRejectedValueOnce({ response: { status: 429, data: { detail: { code: 'daily_cap', message: "You have used today's 20 drafts. More tomorrow." } } } });
    await mount();
    act(() => type(host.querySelector('textarea')!, 'Who pays?'));
    await act(async () => buttons('Draft a reply')[0].click());
    await flush();
    expect(useJobStore.getState().toasts.map((t) => t.message)).toContain("You have used today's 20 drafts. More tomorrow.");
  });
});

describe('wiring', () => {
  it('the Echo page mounts the panel for tiers with the feature', () => {
    const page = Object.values(import.meta.glob('../EchoPage.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>)[0];
    expect(page).toMatch(/\{has\('echo_speak_as_me'\) && \(/);
    expect(page).toMatch(/<SpeakAsMePanel \/>/);
  });
});
