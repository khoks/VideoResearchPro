/**
 * T-5.2.8 / D-111: only the install's operator may switch tiers. The
 * Subscription page offers the switch to an operator (demo payment, then
 * `PUT /auth/me/tier`) and, to anyone else, shows the plans without buttons
 * and says who can change their plan. A refusal from the server is shown,
 * not swallowed. Planned features are never listed as lost on a downgrade.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { AxiosError, AxiosHeaders } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeResponse } from '../../hooks/useMe';
import { useJobStore } from '../../stores/jobStore';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const me: { current: MeResponse | undefined } = { current: undefined };
vi.mock('../../hooks/useMe', () => ({
  useMe: () => ({ data: me.current, refetch: async () => ({}) }),
  useInvalidateMe: () => async () => undefined,
}));
const put = vi.fn(async (_url: string, body: { tier: string }) => ({ data: { tier: body.tier, message: 'ok' } }));
// T-5.2.10: `GET /auth/quota` feeds the library-usage line.
const documentsUsage: { current: { consumed: number; limit: number } | null } = { current: null };
const get = vi.fn(async (_url: string) => ({
  data: {
    tier: 'free',
    resources: documentsUsage.current
      ? [{ resource: 'documents', period_kind: 'lifetime', period_start: '', period_end: null, over_limit: false, ...documentsUsage.current }]
      : [],
  },
}));
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

async function mount(path = '/account/subscription') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
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
  useJobStore.setState({ toasts: [] });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('SubscriptionPage for the operator', () => {
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
