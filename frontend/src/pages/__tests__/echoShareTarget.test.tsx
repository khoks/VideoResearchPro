/**
 * The page a share from the Android share sheet lands on (T-3.7.6.1): what it
 * does with each outcome. The stash and its rules are tested in
 * services/__tests__/shareTarget.test.ts.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const deliver = vi.hoisted(() => vi.fn());
vi.mock('../../services/shareTarget', () => ({ deliverPendingShares: deliver }));

import { useJobStore } from '../../stores/jobStore';
import { EchoShareTargetPage } from '../EchoShareTargetPage';

let host: HTMLDivElement;
let root: Root;

async function renderAt(path: string) {
  await act(async () => {
    root.render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/echo/share-target" element={<EchoShareTargetPage />} />
            <Route path="/echo/inbox" element={<p>The inbox</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
}

const lastToast = () => useJobStore.getState().toasts.at(-1)?.message;
const buttonNamed = (name: string) => [...host.querySelectorAll('button')].find((b) => b.textContent === name);
const linkNamed = (name: string) => [...host.querySelectorAll('a')].find((a) => a.textContent === name);

beforeEach(() => {
  deliver.mockReset();
  useJobStore.setState({ toasts: [] });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('EchoShareTargetPage', () => {
  it('adds what is waiting once and lands in the inbox', async () => {
    deliver.mockResolvedValue({ kind: 'added', count: 1, skipped: 0 });
    await renderAt('/echo/share-target');
    expect(host.textContent).toContain('The inbox');
    expect(deliver).toHaveBeenCalledTimes(1);
    expect(lastToast()).toBe('Added to Echo.');
  });

  it('says when files were left out', async () => {
    deliver.mockResolvedValue({ kind: 'added', count: 10, skipped: 2 });
    await renderAt('/echo/share-target');
    expect(lastToast()).toContain('2 left out');
  });

  it('shows the server’s refusal with the way to a plan that has Echo', async () => {
    deliver.mockResolvedValue({ kind: 'refused', count: 0, status: 403, detail: 'Echo needs the Studio plan.' });
    await renderAt('/echo/share-target');
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Echo needs the Studio plan.');
    expect(linkNamed('See the plans')?.getAttribute('href')).toBe('/account/subscription');
    expect(buttonNamed('Try again')).toBeUndefined();
  });

  it('offers no plans for a refusal a plan would not change', async () => {
    deliver.mockResolvedValue({ kind: 'refused', count: 1, status: 413, detail: 'file is over 25 MB' });
    await renderAt('/echo/share-target');
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('The rest was added.');
    expect(linkNamed('See the plans')).toBeUndefined();
  });

  it('keeps the share and retries when the server could not be reached', async () => {
    deliver.mockResolvedValueOnce({ kind: 'failed', detail: null });
    deliver.mockResolvedValueOnce({ kind: 'added', count: 1, skipped: 0 });
    await renderAt('/echo/share-target');
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('still on this device');
    await act(async () => buttonNamed('Try again')?.click());
    expect(host.textContent).toContain('The inbox');
    expect(deliver).toHaveBeenCalledTimes(2);
  });

  it('says so when nothing is waiting', async () => {
    deliver.mockResolvedValue({ kind: 'nothing' });
    await renderAt('/echo/share-target');
    expect(host.textContent).toContain('Nothing is waiting');
  });

  it('says so when the device could not keep the share, and posts nothing', async () => {
    await renderAt('/echo/share-target?failed=1');
    expect(host.textContent).toContain('could not keep what you shared');
    expect(deliver).not.toHaveBeenCalled();
  });
});
