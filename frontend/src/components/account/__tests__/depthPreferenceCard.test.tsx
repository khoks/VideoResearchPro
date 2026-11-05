/**
 * T-1.15.3.9: the control on `/account/ai-models`. The real hooks run with only
 * the HTTP layer replaced, so this pins the request, and that a save reaches
 * every page reading `usePreferredDepth` without a refetch. Auto clears the
 * preference with an explicit `auto`.
 *
 * Mutation checks, run by hand on 2026-11-04: sending `null` in place of `auto`
 * fails "Auto clears it" (the route takes both, so this pins the body we chose);
 * dropping the cache write fails "reaches the pages at once".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const getMock = vi.fn();
const patchMock = vi.fn();
vi.mock('../../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    patch: (...args: unknown[]) => patchMock(...args),
  },
}));
vi.mock('../../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, token: 'fixture' }) }));

import { DepthPreferenceCard } from '../DepthPreferenceCard';
import { usePreferredDepth } from '../../../hooks/useMe';

let host: HTMLDivElement;
let root: Root;
let client: QueryClient;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

function PageReading() {
  return <output data-testid="reading">{usePreferredDepth() ?? 'none'}</output>;
}

async function mount(preferred: string | null) {
  getMock.mockResolvedValue({ data: { id: 'u1', tier: 'free', preferred_output_length: preferred } });
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <DepthPreferenceCard />
        <PageReading />
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const select = () => host.querySelector<HTMLSelectElement>('select[aria-label="Default depth"]')!;
const reading = () => host.querySelector('[data-testid="reading"]')!.textContent;

function pick(value: string) {
  const el = select();
  act(() => {
    el.value = value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

beforeEach(() => {
  getMock.mockReset();
  patchMock.mockReset();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('DepthPreferenceCard', () => {
  it('offers Auto and the three depths, and shows Auto for someone who never chose', async () => {
    await mount(null);
    expect(Array.from(select().options).map((o) => o.textContent)).toEqual(['Auto', 'Brief', 'Standard', 'Deep']);
    expect(select().value).toBe('');
    expect(patchMock).not.toHaveBeenCalled();
  });

  it('shows the stored choice', async () => {
    await mount('standard');
    expect(select().value).toBe('standard');
  });

  it('saves a pick at once, and it reaches the pages at once', async () => {
    await mount(null);
    patchMock.mockResolvedValue({ data: { output_length: 'deep' } });
    pick('deep');
    await flush();
    expect(patchMock).toHaveBeenCalledTimes(1);
    expect(patchMock).toHaveBeenCalledWith('/auth/me/preferences', { output_length: 'deep' });
    expect(reading()).toBe('deep');
    expect(getMock).toHaveBeenCalledTimes(1);
  });

  it('Auto clears it', async () => {
    await mount('deep');
    patchMock.mockResolvedValue({ data: { output_length: null } });
    pick('');
    await flush();
    expect(patchMock).toHaveBeenCalledWith('/auth/me/preferences', { output_length: 'auto' });
    expect(reading()).toBe('none');
  });

  it('keeps the old choice when a save fails', async () => {
    await mount('brief');
    patchMock.mockRejectedValue(new Error('down'));
    pick('deep');
    await flush();
    expect(select().value).toBe('brief');
    expect(select().disabled).toBe(false);
  });

  it('waits for the account before it takes a pick', async () => {
    getMock.mockReturnValue(new Promise(() => undefined));
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    act(() =>
      root.render(
        <QueryClientProvider client={client}>
          <DepthPreferenceCard />
        </QueryClientProvider>,
      ),
    );
    await flush();
    expect(select().disabled).toBe(true);
  });
});
