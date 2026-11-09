/**
 * T-5.2.8 / D-111: only the install's operator may switch tiers. The
 * Subscription page offers the switch to an operator (demo payment, then
 * `PUT /auth/me/tier`) and, to anyone else, shows the plans without buttons
 * and says who can change their plan. A refusal from the server is shown,
 * not swallowed. Planned features are never listed as lost on a downgrade.
 *
 * T-3.4.1.17: a refused switch is one toast under the app's own query client, not
 * the page's and the global handler's, and none for a 401. Mutation checks, run
 * on 2026-11-09: `meta` off the page's mutation fails each failure row but
 * `sessionEnded` with two toasts; `toastMutationError` without its 401 check
 * fails the `sessionEnded` row with one.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { AxiosError, AxiosHeaders } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeResponse } from '../../hooks/useMe';
import { useJobStore } from '../../stores/jobStore';
import { createQueryClient } from '../../services/queryClient';
import { FAILURE_KINDS, expectedToasts, failures, toastMessages } from '../../services/__tests__/failures';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const me: { current: MeResponse | undefined } = { current: undefined };
vi.mock('../../hooks/useMe', () => ({
  useMe: () => ({ data: me.current, refetch: async () => ({}) }),
  useInvalidateMe: () => async () => undefined,
}));
const put = vi.fn(async (_url: string, body: { tier: string }) => ({ data: { tier: body.tier, message: 'ok' } }));
// T-5.2.10: `GET /auth/quota` feeds the library-usage line.
const documentsUsage: { current: { consumed: number; limit: number } | null } = { current: null };
// E-5.2: `GET /usage` feeds the usage table below the plans.
const zero = { llm_tokens_in: 0, llm_tokens_out: 0, llm_calls: 0, youtube_units: 0, whisper_seconds: 0 };
const usage: { current: unknown } = { current: null };
function emptyUsage() {
  return {
    today: '2026-11-03', window_start: '2026-10-05', window_days: 30, metered_since: null,
    features: [], totals: { today: zero, last_30_days: zero },
  };
}
const get = vi.fn(async (url: string) => {
  if (url === '/usage') return { data: usage.current ?? emptyUsage() };
  return {
    data: {
      tier: 'free',
      resources: documentsUsage.current
        ? [{ resource: 'documents', period_kind: 'lifetime', period_start: '', period_end: null, over_limit: false, ...documentsUsage.current }]
        : [],
    },
  };
});
vi.mock('../../services/api', () => ({
  default: {
    put: (url: string, body: { tier: string }) => put(url, body),
    get: (url: string) => get(url),
  },
}));

import { SubscriptionPage } from '../SubscriptionPage';

function account(overrides: Partial<MeResponse> = {}): MeResponse {
  return {
    id: 'u1',
    email: 'me@example.com',
    created_at: '2026-05-01T00:00:00',
    tier: 'free',
    is_operator: true,
    ...overrides,
  };
}

let host: HTMLDivElement;
let root: Root;

function Where() {
  const loc = useLocation();
  return <output data-where>{loc.pathname + loc.search}</output>;
}

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount(path = '/account/subscription', qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) {
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/account/subscription" element={<SubscriptionPage />} />
          </Routes>
          <Where />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const buttons = () => Array.from(host.querySelectorAll('button')).map((b) => b.textContent?.trim() ?? '');
const button = (label: string) =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === label) as HTMLButtonElement | undefined;
const dialog = () => document.querySelector('[role="dialog"]');

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  me.current = account();
  documentsUsage.current = null;
  usage.current = null;
  useJobStore.setState({ toasts: [] });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('SubscriptionPage for the operator', () => {
  it.each(FAILURE_KINDS)('says a refused switch (%s) once, under the app’s client', async (kind) => {
    put.mockRejectedValueOnce(failures[kind]());
    await mount('/account/subscription', createQueryClient());
    act(() => button('Upgrade to Studio')!.click());
    await act(async () => button('Pay $49')!.click());
    await flush();
    expect(put).toHaveBeenCalledTimes(1);
    expect(toastMessages()).toEqual(expectedToasts(kind, 'Could not change your plan. Try again.'));
    expect(dialog()).toBeNull();
  });

  it('offers the switch and sends it through the demo payment', async () => {
    await mount();
    expect(host.textContent).toContain('Demo mode.');
    expect(host.querySelector('[data-operator-only]')).toBeNull();
    expect(buttons()).toEqual(expect.arrayContaining(['Upgrade to Pro', 'Upgrade to Studio']));

    act(() => button('Upgrade to Pro')!.click());
    expect(dialog()?.getAttribute('aria-label')).toBe('Upgrade to Pro (demo payment)');
    await act(async () => button('Pay $19')!.click());
    await flush();
    expect(put).toHaveBeenCalledTimes(1);
    expect(put.mock.calls[0][0]).toBe('/auth/me/tier');
    expect(put.mock.calls[0][1].tier).toBe('pro');
  });

  it('shows the server’s refusal instead of failing silently', async () => {
    const refusal = new AxiosError('Forbidden', 'ERR_BAD_REQUEST', undefined, undefined, {
      status: 403,
      statusText: 'Forbidden',
      headers: {},
      config: { headers: new AxiosHeaders() },
      data: { detail: "Only this install's operator can do this." },
    });
    put.mockRejectedValueOnce(refusal);
    await mount();
    act(() => button('Upgrade to Studio')!.click());
    await act(async () => button('Pay $49')!.click());
    await flush();
    const toasts = useJobStore.getState().toasts;
    expect(toasts.some((t) => t.kind === 'error' && t.message === "Only this install's operator can do this.")).toBe(true);
    expect(dialog()).toBeNull();
  });

  it('never lists a planned feature as something a downgrade takes away', async () => {
    me.current = account({ tier: 'studio' });
    await mount();
    act(() => button('Downgrade to Pro')!.click());
    const text = dialog()?.textContent ?? '';
    expect(text).toContain('Confirm downgrade');
    expect(text).toContain('Echo — personal-brain agent');
    expect(text).not.toContain('Team workspaces');
    expect(text).not.toContain('Data residency selection');
  });
});

describe('SubscriptionPage for any other account', () => {
  beforeEach(() => {
    me.current = account({ is_operator: false });
  });

  it('shows the plans without a switch and says who can change them', async () => {
    await mount();
    const note = host.querySelector('[data-operator-only]');
    expect(note?.textContent).toContain("Only this install's operator can change plans.");
    expect(note?.textContent).toContain('ADMIN_EMAILS');
    expect(host.textContent).not.toContain('Demo mode.');
    expect(buttons().filter((b) => /^(Upgrade|Downgrade) to /.test(b))).toEqual([]);
    expect(host.textContent).toContain('Current plan');
  });

  it('ignores an upgrade link from the pricing page', async () => {
    await mount('/account/subscription?upgrade=studio');
    expect(dialog()).toBeNull();
    expect(host.querySelector('[data-where]')!.textContent).toBe('/account/subscription');
    expect(put).not.toHaveBeenCalled();
  });

  it('offers nothing before the account has loaded', async () => {
    me.current = undefined;
    await mount('/account/subscription?upgrade=pro');
    expect(buttons().filter((b) => /^(Upgrade|Downgrade) to /.test(b))).toEqual([]);
    expect(host.querySelector('[data-operator-only]')).toBeNull();
    expect(dialog()).toBeNull();
  });
});

describe('SubscriptionPage library usage (T-5.2.10)', () => {
  it('shows how full the library is against the plan cap', async () => {
    documentsUsage.current = { consumed: 312, limit: 500 };
    await mount();
    expect(get).toHaveBeenCalledWith('/auth/quota');
    expect(host.querySelector('[data-document-usage]')?.textContent).toBe(
      'Your library holds 312 documents of the 500 this plan allows.',
    );
  });

  it('shows nothing when the quota does not report documents', async () => {
    await mount();
    expect(host.querySelector('[data-document-usage]')).toBeNull();
  });
});

describe('SubscriptionPage usage (E-5.2)', () => {
  it('lists the reader’s usage by feature, today and over 30 days, with a total', async () => {
    usage.current = {
      ...emptyUsage(),
      metered_since: '2026-10-20',
      features: [
        {
          feature: 'report', label: 'Reports',
          today: zero,
          last_30_days: { ...zero, llm_tokens_in: 412_300, llm_tokens_out: 51_000, llm_calls: 37 },
        },
        {
          feature: 'search', label: 'Topic search',
          today: { ...zero, llm_tokens_in: 1_200, llm_tokens_out: 300, llm_calls: 2 },
          last_30_days: { ...zero, llm_tokens_in: 1_200, llm_tokens_out: 300, llm_calls: 2 },
        },
        {
          feature: 'youtube_search', label: 'Searches (YouTube)',
          today: { ...zero, youtube_units: 200 },
          last_30_days: { ...zero, youtube_units: 200 },
        },
      ],
      totals: {
        today: { ...zero, llm_tokens_in: 1_200, llm_tokens_out: 300, llm_calls: 2, youtube_units: 200 },
        last_30_days: { ...zero, llm_tokens_in: 413_500, llm_tokens_out: 51_300, llm_calls: 39, youtube_units: 200 },
      },
    };
    await mount();
    expect(get).toHaveBeenCalledWith('/usage');
    const panel = host.querySelector('[data-usage-summary]')!;
    expect(panel.textContent).toContain('none of it is limited');
    const report = panel.querySelector('[data-usage-feature="report"]')!;
    const cells = Array.from(report.querySelectorAll('td')).map((td) => td.textContent);
    expect(report.querySelector('th')!.textContent).toBe('Reports');
    expect(cells).toEqual(['—', '412.3K in · 51K out37 model calls']);
    const search = panel.querySelector('[data-usage-feature="search"]')!;
    expect(search.querySelectorAll('td')[0].textContent).toBe('1.2K in · 300 out2 model calls');
    const ytSearch = panel.querySelector('[data-usage-feature="youtube_search"]')!;
    expect(ytSearch.querySelector('th')!.textContent).toBe('Searches (YouTube)');
    expect(ytSearch.querySelectorAll('td')[0].textContent).toBe('200 YouTube units');
    expect(panel.querySelector('[data-usage-total]')!.textContent).toContain('413.5K in · 51.3K out');
    expect(panel.querySelector('[data-usage-since]')!.textContent).toContain('Recording started on 2026-10-20');
  });

  it('shows audio sent to Whisper in sentences a reader can use, on the feature and in the total', async () => {
    usage.current = {
      ...emptyUsage(),
      metered_since: '2026-10-20',
      features: [
        {
          feature: 'ingest', label: 'Reading sources',
          today: { ...zero, whisper_seconds: 45 },
          last_30_days: { ...zero, whisper_seconds: 5_400 },
        },
        {
          feature: 'echo_shares', label: 'Echo shares',
          today: zero,
          last_30_days: { ...zero, whisper_seconds: 90 },
        },
      ],
      totals: {
        today: { ...zero, whisper_seconds: 45 },
        last_30_days: { ...zero, whisper_seconds: 5_490 },
      },
    };
    await mount();
    const panel = host.querySelector('[data-usage-summary]')!;
    const ingest = Array.from(panel.querySelectorAll('[data-usage-feature="ingest"] td')).map((td) => td.textContent);
    expect(ingest).toEqual(['45 sec of audio transcribed', '90 min of audio transcribed']);
    const echo = panel.querySelector('[data-usage-feature="echo_shares"]')!;
    expect(echo.querySelectorAll('td')[0].textContent).toBe('—');
    expect(echo.querySelectorAll('td')[1].textContent).toBe('1.5 min of audio transcribed');
    expect(panel.querySelector('[data-usage-total]')!.textContent).toContain('91.5 min of audio transcribed');
  });

  it('says nothing is recorded yet instead of showing an empty table', async () => {
    await mount();
    const panel = host.querySelector('[data-usage-summary]')!;
    expect(panel.querySelector('[data-usage-empty]')).not.toBeNull();
    expect(panel.querySelector('table')).toBeNull();
    expect(panel.querySelector('[data-usage-since]')).toBeNull();
  });
});
