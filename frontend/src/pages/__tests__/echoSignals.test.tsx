/**
 * S-3.3.1: the signals panel on the Echo page. It lists what Echo learned
 * by layer and type with the evidence behind each signal, and its actions
 * call the API: add, correct, and "That's not me" (the tombstone). The
 * Echo page mounts it, and the data card counts signals among what a
 * delete removes.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { VoiceSignal, VoiceSignalList } from '../../services/echoApi';
import { SIGNAL_TYPES, evidenceSummary, groupSignals, learningSummary, originLabel, sourceLabel } from '../../utils/echoSignals';
import { useJobStore } from '../../stores/jobStore';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const api = {
  listSignals: vi.fn<() => Promise<VoiceSignalList>>(),
  createSignal: vi.fn(async (b: unknown) => ({ id: 'new', ...(b as object) })),
  updateSignal: vi.fn(async (_id: string, b: unknown) => b),
  rejectSignal: vi.fn(async (id: string) => ({ id })),
  exportSignals: vi.fn(async () => undefined),
  learnSignals: vi.fn(async () => ({ status: 'queued', pending: 3 })),
};
vi.mock('../../services/echoApi', () => ({
  echoApi: {
    listSignals: () => api.listSignals(),
    createSignal: (b: unknown) => api.createSignal(b),
    updateSignal: (id: string, b: unknown) => api.updateSignal(id, b),
    rejectSignal: (id: string) => api.rejectSignal(id),
    exportSignals: () => api.exportSignals(),
    learnSignals: () => api.learnSignals(),
  },
}));

import { SignalsPanel } from '../../components/echo/SignalsPanel';

function signal(over: Partial<VoiceSignal>): VoiceSignal {
  return {
    id: 's',
    signal_type: 'interest',
    layer: 'personality',
    value: 'v',
    weight: 1,
    examples: [],
    language: null,
    register: null,
    derived_from: ['user'],
    origin: 'user',
    consent_version: '2026-10-19',
    created_at: '2026-10-19T10:00:00',
    updated_at: '2026-10-19T10:00:00',
    ...over,
  };
}

const FRAMING = signal({
  id: 'sig-framing',
  signal_type: 'framing',
  layer: 'style',
  value: 'Starts from incentives',
  origin: 'llm',
  language: 'hi-Latn',
  register: 'casual',
  derived_from: ['note:n1', 'note:n2', 'qa:q1'],
  examples: [
    { text: 'pehle incentives dekho', source: 'note:n1' },
    { text: 'what is the incentive here?', source: 'qa:q1' },
  ],
});
const INTEREST = signal({ id: 'sig-interest', value: 'Monetary history' });

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
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <SignalsPanel />
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const buttons = (label: string) =>
  Array.from(document.querySelectorAll('button')).filter((b) => b.textContent?.trim() === label) as HTMLButtonElement[];

function setField(el: HTMLTextAreaElement | HTMLSelectElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLSelectElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value);
  el.dispatchEvent(new Event(el instanceof HTMLTextAreaElement ? 'input' : 'change', { bubbles: true }));
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  api.listSignals.mockReset().mockResolvedValue({ items: [FRAMING, INTEREST], consent_version: '2026-10-19' });
  api.createSignal.mockClear();
  api.updateSignal.mockClear();
  api.rejectSignal.mockClear();
  api.exportSignals.mockClear();
  api.learnSignals.mockClear();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('signal helpers', () => {
  it('carry the server’s closed vocabulary, style first', () => {
    // echo_signal_service.STYLE_TYPES + PERSONALITY_TYPES, in order.
    expect(SIGNAL_TYPES.map((t) => t.type)).toEqual([
      'vocabulary', 'cadence', 'framing', 'recurring_reference', 'formality_register', 'register_per_audience',
      'trusted_conclusion', 'preferred_solution', 'recommendation_lens', 'apprehension', 'methodology',
      'topic_emphasis', 'perception_lens', 'interest',
    ]);
    expect(SIGNAL_TYPES.filter((t) => t.layer === 'style')).toHaveLength(6);
  });

  it('group by layer and type, leaving empty types out', () => {
    const g = groupSignals([INTEREST, FRAMING]);
    expect(g.style.map((x) => x.meta.type)).toEqual(['framing']);
    expect(g.personality.map((x) => x.items.map((s) => s.id))).toEqual([['sig-interest']]);
  });

  it('name evidence in words, never a raw id', () => {
    expect(evidenceSummary(FRAMING)).toBe('2 × a note, a question you asked');
    expect(sourceLabel('share:abc')).toBe('a share in your own words');
    expect(sourceLabel('user')).toBe('you said so');
  });

  it('say who a signal belongs to', () => {
    expect(originLabel('user')).toBe('You added this');
    expect(originLabel('user', ['note:n1'])).toBe('You corrected this');
    expect(originLabel('stylometry', ['note:n1'])).toBe('Measured from your writing');
    expect(originLabel('llm', ['note:n1'])).toBe('Learned from your writing');
  });
});

describe('learning line (S-3.3.2)', () => {
  const base = { mode: 'celery', inputs: 12, by_language: { en: 12 }, pending: 0, threshold: 10, last_learned_at: null };
  const fmt = () => '19 Oct 2026';

  it('says what is waiting and when Echo will start on its own', () => {
    expect(learningSummary({ ...base, pending: 3 }, fmt)).toEqual({
      text: '3 texts are waiting to be read. Echo starts on its own once 10 are waiting.',
      canLearn: true,
    });
    expect(learningSummary({ ...base, pending: 12 }, fmt)?.text).toBe('12 texts are waiting to be read. Echo will read them shortly.');
    expect(learningSummary({ ...base, pending: 1, last_learned_at: '2026-10-19T10:00:00' }, fmt)?.text).toBe(
      '1 text is waiting to be read. Echo last learned on 19 Oct 2026. Echo starts on its own once 10 are waiting.',
    );
  });

  it('says when it is up to date, when there is nothing yet, and when learning is off', () => {
    expect(learningSummary(base, fmt)).toEqual({ text: 'Up to date: Echo has read all 12 of your texts.', canLearn: false });
    expect(learningSummary({ ...base, inputs: 0 }, fmt)?.text).toMatch(/^Echo learns from your notes/);
    const off = learningSummary({ ...base, mode: 'off', pending: 4 }, fmt)!;
    expect(off.canLearn).toBe(false);
    expect(off.text).toContain('Automatic learning is off on this install.');
    expect(learningSummary(null, fmt)).toBeNull();
  });
});

describe('SignalsPanel', () => {
  it('lists signals by layer with their evidence and examples', async () => {
    await mount();
    const text = host.textContent ?? '';
    expect(text.indexOf('How you write')).toBeLessThan(text.indexOf('What you think'));
    expect(text).toContain('How you frame things');
    expect(text).toContain('Starts from incentives');
    expect(text).toContain('Hindi (Roman script)');
    expect(text).toContain('Casual');
    expect(text).toContain('Learned from your writing');
    expect(text).toContain('from 2 × a note, a question you asked');
    expect(text).toContain('2 examples');
    expect(text).toContain('“pehle incentives dekho”');
    expect(text).toContain('You added this');
    expect(text).toContain('Learning terms version 2026-10-19');
  });

  it('says what will appear when a layer is empty', async () => {
    api.listSignals.mockResolvedValue({ items: [INTEREST], consent_version: '2026-10-19' });
    await mount();
    expect(host.textContent).toContain('Nothing learned yet.');
    expect(buttons('Export voice profile')[0].disabled).toBe(false);
  });

  it('“That’s not me” asks, then tombstones through the API', async () => {
    await mount();
    const row = host.querySelector('[data-signal="sig-framing"]')!;
    const reject = Array.from(row.querySelectorAll('button')).find((b) => b.textContent === "That's not me")!;
    act(() => reject.click());
    expect(document.body.textContent).toContain('will not learn it again');
    expect(api.rejectSignal).not.toHaveBeenCalled();
    const confirm = buttons("That's not me").find((b) => !host.contains(b))!;
    await act(async () => confirm.click());
    await flush();
    expect(api.rejectSignal).toHaveBeenCalledWith('sig-framing');
    expect(api.listSignals.mock.calls.length).toBeGreaterThan(1);
  });

  it('adds a signal the user states, in the layer they picked', async () => {
    await mount();
    act(() => buttons('Add')[0].click());
    const dialog = document.querySelector('[role="dialog"]')!;
    const [kind] = Array.from(dialog.querySelectorAll('select'));
    expect(kind.value).toBe('vocabulary');
    act(() => setField(kind, 'cadence'));
    act(() => setField(dialog.querySelector('textarea')!, '  Short sentences, then one long one. '));
    await act(async () => buttons('Add').find((b) => dialog.contains(b))!.click());
    await flush();
    expect(api.createSignal).toHaveBeenCalledWith({
      signal_type: 'cadence',
      value: 'Short sentences, then one long one.',
      language: null,
      register: null,
    });
  });

  it('corrects a signal’s wording and audience', async () => {
    await mount();
    const row = host.querySelector('[data-signal="sig-framing"]')!;
    act(() => (Array.from(row.querySelectorAll('button')).find((b) => b.textContent === 'Edit')!).click());
    const dialog = document.querySelector('[role="dialog"]')!;
    const [kind, , audience] = Array.from(dialog.querySelectorAll('select'));
    expect(kind.disabled).toBe(true);
    act(() => setField(audience, 'professional'));
    act(() => setField(dialog.querySelector('textarea')!, 'Starts from incentives, then evidence'));
    await act(async () => buttons('Save')[0].click());
    await flush();
    expect(api.updateSignal).toHaveBeenCalledWith('sig-framing', {
      value: 'Starts from incentives, then evidence',
      language: 'hi-Latn',
      register: 'professional',
    });
  });

  it('“Learn now” queues a run and says so', async () => {
    api.listSignals.mockResolvedValue({
      items: [INTEREST],
      consent_version: '2026-10-19',
      learning: { mode: 'celery', inputs: 5, by_language: { en: 5 }, pending: 3, threshold: 10, last_learned_at: null },
    });
    await mount();
    expect(host.querySelector('[data-learning]')?.textContent).toContain('3 texts are waiting to be read.');
    await act(async () => buttons('Learn now')[0].click());
    await flush();
    expect(api.learnSignals).toHaveBeenCalled();
    expect(useJobStore.getState().toasts.map((t) => t.message)).toContain('Learning started. New signals appear here in a minute or two.');
  });

  it('offers no “Learn now” when nothing is waiting', async () => {
    api.listSignals.mockResolvedValue({
      items: [INTEREST],
      consent_version: '2026-10-19',
      learning: { mode: 'celery', inputs: 5, by_language: { en: 5 }, pending: 0, threshold: 10, last_learned_at: null },
    });
    await mount();
    expect(buttons('Learn now')).toHaveLength(0);
    expect(host.textContent).toContain('Up to date: Echo has read all 5 of your texts.');
  });

  it('exports the voice profile', async () => {
    await mount();
    await act(async () => buttons('Export voice profile')[0].click());
    expect(api.exportSignals).toHaveBeenCalled();
  });
});

describe('wiring', () => {
  const raw = (glob: Record<string, string>) => Object.values(glob)[0];

  it('the Echo page mounts the panel', () => {
    const page = raw(import.meta.glob('../EchoPage.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>);
    expect(page).toMatch(/import \{ SignalsPanel \} from '\.\.\/components\/echo\/SignalsPanel'/);
    expect(page).toMatch(/<SignalsPanel \/>/);
  });

  it('the data card counts signals among what a delete removes', () => {
    const card = raw(import.meta.glob('../../components/echo/EchoDataCard.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>);
    expect(card).toContain('fp.rows.voice_signals');
  });
});
