/**
 * S-3.4.1 / S-3.4.2: the "Speak as me" panel. While any gate is shut it says which, in
 * the server's words, and offers no composer; once open it drafts, shows the
 * draft with its disclosure, voice score, citations and notes, handles the
 * private-person confirmation, and says when the daily cap is reached. The
 * Echo page mounts it for tiers with the feature. T-3.4.1.11: a first draft in
 * a register waits for a go-ahead, and a reply with nothing behind it is refused
 * on screen, in the server's words.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { AxiosError, AxiosHeaders } from 'axios';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DraftStatus, EchoDraft } from '../../services/echoApi';
import { useJobStore } from '../../stores/jobStore';
import { globalErrorToastMessage } from '../../utils/apiError';
import { citationLabel, draftErrorOf, learnedLine, withDisclosure } from '../../utils/echoDrafts';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const api = {
  draftStatus: vi.fn<() => Promise<DraftStatus>>(),
  createDraft: vi.fn<(p: unknown) => Promise<EchoDraft>>(),
  listDrafts: vi.fn(async () => ({ items: [] as EchoDraft[] })),
  deleteDraft: vi.fn(async () => undefined),
  draftFeedback: vi.fn<(id: string, p: unknown) => Promise<EchoDraft>>(),
  voiceTest: vi.fn(async () => ({
    offer: {
      available: false, blockers: [], pairs: 20, model_calls: 40, model: 'gpt-5.5', notes: 3, notes_needed: 40,
      pass_share: 0.8, tests_today: 0, tests_per_day: 3,
    },
    gate: { status: 'not_run', run_at: null, pairs: 0, picked_own_share: null, notes_total: 3, notes_needed: 40 },
    test: null,
  })),
};
vi.mock('../../services/echoApi', () => ({
  echoApi: {
    draftStatus: () => api.draftStatus(),
    voiceTest: () => api.voiceTest(),
    createDraft: (p: unknown) => api.createDraft(p),
    listDrafts: () => api.listDrafts(),
    deleteDraft: () => api.deleteDraft(),
    draftFeedback: (id: string, p: unknown) => api.draftFeedback(id, p),
  },
}));

import { SpeakAsMePanel } from '../../components/echo/SpeakAsMePanel';
import http from '../../services/api';
import { stubNewTabs } from '../../services/__tests__/newTab';

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
  final_text: null, disclosure_kept: null, feedback_at: null, edit: null, created_at: '2026-10-20T10:00:00',
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

function refusedWith(code: string, message: string, extra: object = {}, status = 409) {
  const headers = new AxiosHeaders();
  return new AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_REQUEST', undefined, undefined, {
    status, statusText: 'Conflict', headers, config: { headers }, data: { detail: { code, message, ...extra } },
  });
}

function choose(el: HTMLSelectElement, value: string) {
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!.call(el, value);
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

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
  api.draftFeedback.mockReset();
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

  it('put the disclosure on the clipboard unless it was removed', () => {
    expect(withDisclosure(' Mine. ', 'Drafted with Echo, reviewed by sam', true)).toBe('Mine.\n\nDrafted with Echo, reviewed by sam');
    expect(withDisclosure(' Mine. ', 'Drafted with Echo, reviewed by sam', false)).toBe('Mine.');
  });

  it('say what Echo learns from a saved version', () => {
    const edit = { written_words: 6, removed_words: 1, quoted_words: 0, kept_words: 5, written: ['x'], removed: ['y'], quoted: [] };
    expect(learnedLine(edit)).toBe('Saved. Echo learns your voice from the 6 words you wrote, never from the ones it drafted.');
    expect(learnedLine({ ...edit, written_words: 0 })).toBe('Saved. You used it as drafted, so Echo has nothing new to learn.');
    expect(learnedLine({ ...edit, quoted_words: 9, quoted: ['their words'] })).toBe(
      'Saved. Echo learns your voice from the 6 words you wrote, never from the ones it drafted. Words you repeated from their message are theirs, so Echo leaves them out.',
    );
    expect(learnedLine(null)).toBe('');
  });

  it('read the API error shapes', () => {
    expect(draftErrorOf({ response: { data: { detail: { code: 'names_need_confirmation', names: ['Priya'], message: 'm' } } } }))
      .toEqual({ code: 'names_need_confirmation', names: ['Priya'], message: 'm' });
    expect(draftErrorOf(new Error('x')).message).toBe('Could not draft a reply. Try again.');
  });
});

describe('SpeakAsMePanel', () => {
  it('hosts the voice test, which does not repeat the gates above it (T-3.4.1.8)', async () => {
    api.voiceTest.mockResolvedValueOnce({
      offer: {
        available: false,
        blockers: [
          { code: 'install_off', message: 'Speak as me is turned off on this install.' },
          { code: 'notes_needed', message: 'The test needs 40 of your notes. You have 3.' },
        ],
        pairs: 20, model_calls: 40, model: 'gpt-5.5', notes: 3, notes_needed: 40, pass_share: 0.8, tests_today: 0, tests_per_day: 3,
      },
      gate: GATE,
      test: null,
    } as never);
    await mount();
    const section = host.querySelector('[data-voice-test-panel]');
    expect(section).not.toBeNull();
    expect(section?.querySelector('[data-blocker="install_off"]')).toBeNull();
    expect(section?.querySelector('[data-blocker="notes_needed"]')?.textContent).toContain('You have 3');
    expect(host.querySelectorAll('[data-blocker="install_off"]')).toHaveLength(1);
  });

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
    expect((result.querySelector('textarea[data-version]') as HTMLTextAreaElement).value).toBe('Mostly the importer pays first.');
    expect(result.querySelector('[data-disclosure]')?.textContent).toBe('Drafted with Echo, reviewed by sam');
    expect(result.textContent).toContain('Sounds like you: 88%');
    expect(result.querySelector('a[href="https://youtube.com/watch?v=x&t=42s"]')?.textContent).toBe('Tariff study — Econ');
    expect(result.textContent).toContain('what Echo knows about you');
    expect(result.querySelector('[data-notes]')?.textContent).toContain('Slightly more formal than you.');
  });

  describe('a first draft in a register (T-3.4.1.11)', () => {
    const WORDS = 'You have not approved a casual draft yet, so Echo asks before it speaks in that register.';
    const askCasual = async () => {
      api.draftStatus.mockResolvedValue(ON);
      api.createDraft.mockRejectedValueOnce(refusedWith('register_needs_approval', WORDS, { register: 'casual' }));
      await mount();
      act(() => type(host.querySelector('textarea')!, 'Who pays?'));
      act(() => choose(host.querySelector('select')!, 'casual'));
      await act(async () => buttons('Draft a reply')[0].click());
      await flush();
    };

    it('says so before the first one, in the server’s words, and stays on screen', async () => {
      await askCasual();
      expect(host.querySelector('[data-register-stop]')?.textContent).toContain(WORDS);
      expect(useJobStore.getState().toasts).toHaveLength(0);
      expect(host.querySelector('[data-result]')).toBeNull();
      expect(host.textContent).toContain('Echo asks before its first draft in a register. Saving your version approves it.');
    });

    it('sends the go-ahead for that register, and only when the user gives it', async () => {
      await askCasual();
      expect(api.createDraft).toHaveBeenCalledWith({ message: 'Who pays?', register: 'casual' });
      await act(async () => buttons('Draft in this register')[0].click());
      await flush();
      expect(api.createDraft).toHaveBeenLastCalledWith({ message: 'Who pays?', register: 'casual', acknowledge_register: 'casual' });
      expect(host.querySelector('[data-register-stop]')).toBeNull();
      expect(host.querySelector('[data-result]')).not.toBeNull();
    });

    it('keeps the go-ahead through a private name, so the user is not asked twice', async () => {
      await askCasual();
      api.createDraft.mockRejectedValueOnce(refusedWith('names_need_confirmation', 'm', { names: ['Priya'] }));
      await act(async () => buttons('Draft in this register')[0].click());
      await flush();
      await act(async () => buttons('Draft anyway')[0].click());
      await flush();
      expect(api.createDraft).toHaveBeenLastCalledWith({
        message: 'Who pays?', register: 'casual', acknowledge_names: ['Priya'], acknowledge_register: 'casual',
      });
    });

    it('does not carry a go-ahead to another register or to the next draft', async () => {
      await askCasual();
      await act(async () => buttons('Draft in this register')[0].click());
      await flush();
      await act(async () => buttons('Draft a reply')[0].click());
      await flush();
      expect(api.createDraft).toHaveBeenLastCalledWith({ message: 'Who pays?', register: 'casual' });
    });

    it('goes away when the register changes or the user cancels', async () => {
      await askCasual();
      act(() => choose(host.querySelector('select')!, ''));
      expect(host.querySelector('[data-register-stop]')).toBeNull();
      api.createDraft.mockRejectedValueOnce(refusedWith('register_needs_approval', WORDS, { register: 'casual' }));
      act(() => choose(host.querySelector('select')!, 'casual'));
      await act(async () => buttons('Draft a reply')[0].click());
      await flush();
      act(() => buttons('Cancel')[0].click());
      expect(host.querySelector('[data-register-stop]')).toBeNull();
    });
  });

  it('keeps the stops it shows on screen out of the app’s global error toast, and only those', () => {
    for (const code of ['names_need_confirmation', 'register_needs_approval', 'ungrounded']) {
      expect(globalErrorToastMessage(refusedWith(code, 'words'))).toBeNull();
    }
    expect(globalErrorToastMessage(refusedWith('install_off', 'Turned off.'))).toBe('Turned off.');
    expect(globalErrorToastMessage(refusedWith('daily_cap', 'More tomorrow.', {}, 429))).toBe('More tomorrow.');
    expect(globalErrorToastMessage(refusedWith('ungrounded', 'Not a stop.', {}, 500))).toBe('Not a stop.');
  });

  it('shows a refused reply in the server’s words, on screen, with nothing to click past it', async () => {
    const WORDS = 'Echo did not write this reply: nothing in your library backs it. To go ahead, add a source on this.';
    api.draftStatus.mockResolvedValue(ON);
    api.createDraft.mockRejectedValueOnce(refusedWith('ungrounded', WORDS));
    await mount();
    act(() => type(host.querySelector('textarea')!, 'Who pays?'));
    await act(async () => buttons('Draft a reply')[0].click());
    await flush();
    const box = host.querySelector('[data-refused]')!;
    expect(box.textContent).toBe(WORDS);
    expect(box.querySelector('button')).toBeNull();
    expect(useJobStore.getState().toasts).toHaveLength(0);
    expect(host.querySelector('[data-result]')).toBeNull();

    await act(async () => buttons('Draft a reply')[0].click());
    await flush();
    expect(host.querySelector('[data-refused]')).toBeNull();
    expect(host.querySelector('[data-result]')).not.toBeNull();
  });

  it('opens an uploaded PDF it drew on as a blob fetched with the header, not the route that 401s (T-8.8.1.5)', async () => {
    api.draftStatus.mockResolvedValue(ON);
    api.createDraft.mockResolvedValue({
      ...DRAFT,
      citations: [{ kind: 'source', ref: 'S1', label: 'Annual report', url: '/api/v1/library/pdf/abc.pdf' }],
    });
    const get = vi.spyOn(http, 'get').mockResolvedValue({ data: new Blob(['%PDF']) } as never);
    const createObjectURL = URL.createObjectURL;
    const revokeObjectURL = URL.revokeObjectURL;
    const windowOpen = window.open;
    URL.createObjectURL = vi.fn(() => 'blob:http://localhost:5173/p1');
    URL.revokeObjectURL = vi.fn();
    const { open, tabs } = stubNewTabs();
    try {
      await mount();
      act(() => type(host.querySelector('textarea')!, 'What does the report say?'));
      await act(async () => buttons('Draft a reply')[0].click());
      await flush();
      const link = host.querySelector('[data-result] a[href="/api/v1/library/pdf/abc.pdf"]')!;
      expect(link.textContent).toBe('Annual report');
      const e = new MouseEvent('click', { bubbles: true, cancelable: true });
      act(() => {
        link.dispatchEvent(e);
      });
      expect(e.defaultPrevented).toBe(true);
      expect(open).toHaveBeenCalledWith('', '_blank'); // inside the click, before the download
      await flush();
      expect(get).toHaveBeenCalledWith('/library/pdf/abc.pdf', { responseType: 'blob' });
      expect(tabs[0].location.href).toBe('blob:http://localhost:5173/p1');
    } finally {
      get.mockRestore();
      URL.createObjectURL = createObjectURL;
      URL.revokeObjectURL = revokeObjectURL;
      window.open = windowOpen;
    }
  });

  it("saves the user's version without the disclosure, and says what Echo learns from", async () => {
    api.draftStatus.mockResolvedValue(ON);
    const edit = { written_words: 5, removed_words: 0, quoted_words: 0, kept_words: 5, written: ['and so does the buyer.'], removed: [], quoted: [] };
    api.draftFeedback.mockResolvedValue({ ...DRAFT, final_text: 'Mostly the importer pays first, and so does the buyer.', disclosure_kept: false, feedback_at: '2026-10-20T10:05:00', edit });
    await mount();
    act(() => type(host.querySelector('textarea')!, 'Who pays?'));
    await act(async () => buttons('Draft a reply')[0].click());
    await flush();
    const result = host.querySelector('[data-result]')!;
    act(() => type(result.querySelector('textarea[data-version]') as HTMLTextAreaElement, 'Mostly the importer pays first, and so does the buyer. '));
    await act(async () => (result.querySelector('[data-keep-disclosure]') as HTMLInputElement).click());
    expect(result.querySelector('[data-disclosure]')).toBeNull();
    await act(async () => buttons('Save my version')[0].click());
    await flush();
    expect(api.draftFeedback).toHaveBeenCalledWith('d1', { final_text: 'Mostly the importer pays first, and so does the buyer.', disclosure_kept: false });
    expect(result.querySelector('[data-saved]')?.textContent).toBe('Saved. Echo learns your voice from the 5 words you wrote, never from the ones it drafted.');
    expect(buttons('Save my version')[0].disabled).toBe(true);
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
  it('the page card and the bubble share one edit-and-save view', () => {
    const sources = import.meta.glob(['../../components/echo/SpeakAsMePanel.tsx', '../../components/echo/EchoPanel.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
    const src = (name: string) => Object.entries(sources).find(([k]) => k.endsWith(name))![1];
    expect(src('SpeakAsMePanel.tsx')).toMatch(/<DraftEditor\s/);
    expect(src('EchoPanel.tsx')).toMatch(/<DraftEditor draft=\{draft\} compact/);
  });

  it('the Echo page mounts the panel for tiers with the feature', () => {
    const page = Object.values(import.meta.glob('../EchoPage.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>)[0];
    expect(page).toMatch(/\{has\('echo_speak_as_me'\) && \(/);
    expect(page).toMatch(/<SpeakAsMePanel \/>/);
  });
});
