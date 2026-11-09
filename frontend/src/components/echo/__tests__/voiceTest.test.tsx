/**
 * T-3.4.1.8: the voice test on the Echo page.
 *
 * - A shut gate says why, once, and offers no test.
 * - An open one says what the test costs before the button, and nothing is
 *   called until the user clicks it.
 * - While it is written the panel polls one test, not the overview.
 * - Pairs come one at a time, in plain text, and a pick moves to the next.
 * - The result needs every pair, comes from the server, and refreshes the
 *   draft gate.
 *
 * T-3.4.1.17: a failed start, pick or score is one toast, said by the hook, under
 * the app's own query client, and none for a 401. Mutation checks, run on
 * 2026-11-09: `meta` off the three hooks fails each failure row but
 * `sessionEnded` with two toasts; the start toast moved back onto the panel's
 * `mutate` fails "once the reader has left"; `toastMutationError` without its 401
 * check fails each `sessionEnded` row.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { VoiceTest, VoiceTestOverview } from '../../../services/echoApi';
import { useJobStore } from '../../../stores/jobStore';
import { createQueryClient } from '../../../services/queryClient';
import { FAILURE_KINDS, expectedToasts, failures, toastMessages } from '../../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const api = {
  voiceTest: vi.fn<() => Promise<VoiceTestOverview>>(),
  startVoiceTest: vi.fn<() => Promise<VoiceTest>>(),
  getVoiceTest: vi.fn<(id: string) => Promise<VoiceTest>>(),
  pickVoiceTest: vi.fn<(id: string, pair: string, pick: string) => Promise<VoiceTest>>(),
  scoreVoiceTest: vi.fn<(id: string) => Promise<{ test: VoiceTest; gate: VoiceTestOverview['gate'] }>>(),
};
vi.mock('../../../services/echoApi', () => ({
  echoApi: {
    voiceTest: () => api.voiceTest(),
    startVoiceTest: () => api.startVoiceTest(),
    getVoiceTest: (id: string) => api.getVoiceTest(id),
    pickVoiceTest: (id: string, pair: string, pick: string) => api.pickVoiceTest(id, pair, pick),
    scoreVoiceTest: (id: string) => api.scoreVoiceTest(id),
  },
}));

import { VoiceTestPanel } from '../VoiceTestPanel';

const OFFER: VoiceTestOverview['offer'] = {
  available: true, blockers: [], pairs: 20, model_calls: 40, model: 'gpt-5.5', notes: 48, notes_needed: 40,
  pass_share: 0.8, tests_today: 0, tests_per_day: 3,
};
const GATE: VoiceTestOverview['gate'] = { status: 'not_run', run_at: null, pairs: 0, picked_own_share: null, notes_total: 48, notes_needed: 40 };
const NONE: VoiceTestOverview = { offer: OFFER, gate: GATE, test: null };

function test_(over: Partial<VoiceTest> = {}): VoiceTest {
  return {
    id: 't1', status: 'ready', pairs_total: 3, pairs_built: 3,
    pairs: [
      { pair: 'p01', A: 'first left', B: 'first right' },
      { pair: 'p02', A: 'second left', B: 'second right' },
      { pair: 'p03', A: 'third left', B: 'third right' },
    ],
    picks: {}, result: null, error: null, model: 'gpt-5.5', cost_usd: 0.1,
    created_at: '2026-11-04T10:00:00', ready_at: '2026-11-04T10:03:00', scored_at: null,
    ...over,
  };
}

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount(shown: string[] = [], qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) {
  act(() => root.render(<QueryClientProvider client={qc}><VoiceTestPanel shown={shown} /></QueryClientProvider>));
  await flush();
}

const button = (label: string) =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as HTMLButtonElement | undefined;

async function click(label: string) {
  const b = button(label);
  expect(b, `button "${label}"`).toBeTruthy();
  await act(async () => b!.click());
  await flush();
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  for (const fn of Object.values(api)) fn.mockReset();
  api.voiceTest.mockResolvedValue(NONE);
  useJobStore.setState({ toasts: [] });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('VoiceTestPanel', () => {
  it('says why when a gate is shut and offers no test', async () => {
    api.voiceTest.mockResolvedValue({
      ...NONE,
      offer: { ...OFFER, available: false, blockers: [
        { code: 'install_off', message: 'Speak as me is turned off on this install.' },
        { code: 'notes_needed', message: 'The test needs 40 of your notes. You have 3.' },
      ] },
    });
    await mount();
    expect(host.querySelector('[data-blocker="install_off"]')?.textContent).toContain('turned off on this install');
    expect(host.querySelector('[data-blocker="notes_needed"]')?.textContent).toContain('You have 3');
    expect(button('Start the test')).toBeUndefined();
    expect(host.querySelector('[data-cost]')).toBeNull();
  });

  it('prints a reason the card above already gave only once', async () => {
    api.voiceTest.mockResolvedValue({
      ...NONE,
      offer: { ...OFFER, available: false, blockers: [
        { code: 'install_off', message: 'off' },
        { code: 'not_ready', message: 'not ready' },
      ] },
    });
    await mount(['install_off', 'not_ready', 'voice_test_required']);
    expect(host.querySelector('[data-blocker]')).toBeNull();
    expect(host.querySelector('[data-offer-closed]')?.textContent).toContain('once the reasons above');
    expect(button('Start the test')).toBeUndefined();
  });

  it('says what the test costs, and only the click starts it', async () => {
    api.startVoiceTest.mockResolvedValue(test_({ status: 'generating', pairs: [], pairs_built: 0 }));
    await mount();
    expect(host.querySelector('[data-cost]')?.textContent).toContain('about 40 calls to gpt-5.5');
    expect(api.startVoiceTest).not.toHaveBeenCalled();

    await click('Start the test');
    expect(api.startVoiceTest).toHaveBeenCalledTimes(1);
    expect(api.voiceTest.mock.calls.length).toBeGreaterThan(1);
  });

  it('polls the one test while it is written, not the overview', async () => {
    const writing = test_({ status: 'generating', pairs: [], pairs_built: 7, pairs_total: 20 });
    api.voiceTest.mockResolvedValue({ ...NONE, test: writing });
    api.getVoiceTest.mockResolvedValue(writing);
    await mount();
    expect(host.querySelector('[data-writing]')?.textContent).toContain('7 of 20 pairs');
    expect(api.getVoiceTest).toHaveBeenCalledWith('t1');
    expect(button('Start the test')).toBeUndefined();
    expect(api.voiceTest).toHaveBeenCalledTimes(1);
  });

  it('shows the pairs as soon as the poll sees them written', async () => {
    const writing = test_({ status: 'generating', pairs: [], pairs_built: 19, pairs_total: 20 });
    const ready = test_();
    api.voiceTest.mockResolvedValueOnce({ ...NONE, test: writing }).mockResolvedValue({ ...NONE, test: ready });
    api.getVoiceTest.mockResolvedValue(ready);
    await mount();
    expect(api.voiceTest).toHaveBeenCalledTimes(2);
    expect(host.querySelector('[data-writing]')).toBeNull();
    expect(host.querySelector('[data-pairs]')).not.toBeNull();
  });

  it('shows one pair at a time, as plain text, and moves on after a pick', async () => {
    api.voiceTest.mockResolvedValue({ ...NONE, test: test_() });
    api.pickVoiceTest.mockResolvedValueOnce(test_({ picks: { p01: 'B' } }));
    await mount();
    expect(host.textContent).toContain('Pair 1 of 3, 0 picked');
    expect(host.querySelector('[data-side="A"]')?.textContent).toContain('first left');
    expect(host.querySelector('[data-side="B"]')?.textContent).toContain('first right');
    expect(host.textContent).not.toContain('second left');
    expect(host.querySelector('[data-side="A"] strong, [data-side="B"] strong')).toBeNull();

    await click('I wrote B');
    expect(api.pickVoiceTest).toHaveBeenCalledWith('t1', 'p01', 'B');
    expect(host.textContent).toContain('Pair 2 of 3, 1 picked');
    expect(host.querySelector('[data-side="A"]')?.textContent).toContain('second left');
    expect(button('See my result')).toBeUndefined();
  });

  it('resumes at the first open pair, and a pair can be changed', async () => {
    api.voiceTest.mockResolvedValue({ ...NONE, test: test_({ picks: { p01: 'A' } }) });
    api.pickVoiceTest.mockResolvedValueOnce(test_({ picks: { p01: 'B' } }));
    await mount();
    expect(host.textContent).toContain('Pair 2 of 3, 1 picked');
    await click('Back');
    expect(host.textContent).toContain('Pair 1 of 3');
    expect(button('I wrote A')?.getAttribute('aria-pressed')).toBe('true');
    await click('I wrote B');
    expect(api.pickVoiceTest).toHaveBeenCalledWith('t1', 'p01', 'B');
  });

  it('offers the result once every pair is picked and shows what the server says', async () => {
    const full = test_({ picks: { p01: 'A', p02: 'B', p03: 'A' } });
    const scored = test_({ status: 'scored', pairs: [], picks: full.picks, result: { pairs: 3, picked_own: 2, picked_own_share: 0.667, passed: true } });
    const gate = { ...GATE, status: 'passed' as const, pairs: 20, picked_own_share: 0.75, run_at: '2026-11-04T10:10:00Z' };
    api.voiceTest.mockResolvedValue({ ...NONE, test: full });
    api.scoreVoiceTest.mockResolvedValue({ test: scored, gate });
    await mount();

    api.voiceTest.mockResolvedValue({ ...NONE, gate, test: scored });
    await click('See my result');
    expect(api.scoreVoiceTest).toHaveBeenCalledWith('t1');
    expect(host.querySelector('[data-result="passed"]')?.textContent).toContain('75% of 20 pairs');
    expect(button('Start the test')).toBeUndefined();
    expect(button('Take the test again')).toBeTruthy();
  });

  it('asks a user who passed before showing the start button, and warns what a fail does', async () => {
    const gate = { ...GATE, status: 'passed' as const, pairs: 20, picked_own_share: 0.6, run_at: '2026-11-04T10:10:00Z' };
    api.voiceTest.mockResolvedValue({ ...NONE, gate });
    await mount();
    expect(button('Start the test')).toBeUndefined();
    await click('Take the test again');
    expect(host.querySelector('[data-offer]')?.textContent).toContain("If you don't pass, Speak as me turns off");
    expect(host.querySelector('[data-cost]')?.textContent).toContain('about 40 calls');
    expect(api.startVoiceTest).not.toHaveBeenCalled();
  });

  it('shows a failed test in words and offers another', async () => {
    api.voiceTest.mockResolvedValue({ ...NONE, test: test_({ status: 'failed', pairs: [], error: 'Echo could not write the test. Start a new one.' }) });
    await mount();
    expect(host.querySelector('[data-test-failed]')?.textContent).toContain('could not write the test');
    expect(button('Start the test')).toBeTruthy();
  });

  it('says so when a pick cannot be saved', async () => {
    api.voiceTest.mockResolvedValue({ ...NONE, test: test_() });
    api.pickVoiceTest.mockRejectedValueOnce({ response: { data: { detail: { code: 'not_open', message: 'This test is not open for picks.' } } } });
    await mount();
    await click('I wrote A');
    expect(useJobStore.getState().toasts.map((t) => t.message)).toContain('This test is not open for picks.');
    expect(host.textContent).toContain('Pair 1 of 3');
  });

  it('never needs the answer: the page has no field for it', async () => {
    api.voiceTest.mockResolvedValue({ ...NONE, test: test_() });
    await mount();
    expect(host.innerHTML).not.toContain('own_is');
  });
});

describe('one toast (T-3.4.1.17)', () => {
  const SITES = [
    {
      name: 'starting the test',
      overview: () => NONE,
      call: () => api.startVoiceTest,
      press: 'Start the test',
      fallback: "Couldn't start the test. Try again.",
    },
    {
      name: 'a pick',
      overview: () => ({ ...NONE, test: test_() }),
      call: () => api.pickVoiceTest,
      press: 'I wrote A',
      fallback: "Couldn't save that pick. Try again.",
    },
    {
      name: 'scoring',
      overview: () => ({ ...NONE, test: test_({ picks: { p01: 'A', p02: 'B', p03: 'A' } }) }),
      call: () => api.scoreVoiceTest,
      press: 'See my result',
      fallback: "Couldn't score the test. Try again.",
    },
  ];

  describe.each(SITES)('for $name', (site) => {
    it.each(FAILURE_KINDS)('a failure (%s) is said once, under the app’s client', async (kind) => {
      api.voiceTest.mockResolvedValue(site.overview());
      site.call().mockRejectedValueOnce(failures[kind]());
      await mount([], createQueryClient());
      await click(site.press);
      expect(toastMessages()).toEqual(expectedToasts(kind, site.fallback));
    });

    // A test is written by the model for minutes; the reader may well have left.
    it('is still said once the reader has left the panel', async () => {
      api.voiceTest.mockResolvedValue(site.overview());
      let fail: (reason: unknown) => void = () => undefined;
      site.call().mockReturnValueOnce(new Promise((_, reject) => (fail = reject)) as never);
      await mount([], createQueryClient());
      await click(site.press);
      act(() => root.unmount());
      await act(async () => fail(failures.noWords()));
      await flush();
      expect(toastMessages()).toEqual([site.fallback]);
      root = createRoot(host);
    });
  });
});
