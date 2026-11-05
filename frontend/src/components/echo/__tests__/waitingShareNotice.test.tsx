/**
 * T-3.7.6.3: a deep link passes the gate at `/` by, so a waiting share was out of
 * reach until the next visit there, up to 24 hours later. The notice makes it one
 * tap away from wherever the reader landed, and does nothing else: no redirect, and
 * nothing posted (D-137). `tests/manifest.spec.ts` has the whole flow on a real
 * service worker, through the layout.
 *
 * Mutation checks, run by hand on 2026-11-05: `pathname` out of the effect's list
 * fails "finds a share that arrived"; setting only a found share fails "goes when the
 * review page has dealt with it"; `elsewhere` always true fails both "leaves it to".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const pending = vi.hoisted(() => ({ share: false }));
const posted = vi.hoisted(() => ({ calls: 0 }));
vi.mock('../../../services/shareTarget', () => ({
  SHARE_REVIEW_PATH: '/echo/incoming',
  hasPendingShares: async () => pending.share,
  deliverPendingShares: async () => {
    posted.calls += 1;
    return { kind: 'nothing' };
  },
}));

import { WaitingShareNotice } from '../WaitingShareNotice';

let host: HTMLDivElement;
let root: Root;

function Where() {
  const { pathname } = useLocation();
  return <output data-testid="where">{pathname}</output>;
}

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount(entry: string) {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[entry]}>
        <WaitingShareNotice />
        <Where />
        <Link to="/library">to the library</Link>
        <Routes>
          <Route path="*" element={null} />
        </Routes>
      </MemoryRouter>,
    );
  });
  await flush();
}

const review = () => Array.from(host.querySelectorAll('a')).find((a) => a.textContent === 'Review it');
const where = () => host.querySelector('[data-testid="where"]')!.textContent;

async function follow(link: HTMLAnchorElement) {
  await act(async () => link.click());
  await flush();
}

beforeEach(() => {
  pending.share = false;
  posted.calls = 0;
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('WaitingShareNotice', () => {
  it('stays on the page the reader came for, with the share one tap away', async () => {
    pending.share = true;
    await mount('/jobs/run-1');
    expect(where()).toBe('/jobs/run-1');
    expect(review()!.getAttribute('href')).toBe('/echo/incoming');
    expect(host.querySelector('[role="status"]')!.textContent).toContain('Nothing is added until you say so.');
  });

  it('posts nothing, and the tap only opens the review page', async () => {
    pending.share = true;
    await mount('/jobs/run-1');
    await follow(review()!);
    expect(where()).toBe('/echo/incoming');
    expect(posted.calls).toBe(0);
  });

  it('shows nothing when no share is waiting', async () => {
    await mount('/jobs/run-1');
    expect(host.querySelector('[role="status"]')).toBeNull();
  });

  it('leaves it to the gate at `/`, which has its own redirect', async () => {
    pending.share = true;
    await mount('/');
    expect(review()).toBeUndefined();
  });

  it('leaves it to the review page, which shows the share itself', async () => {
    pending.share = true;
    await mount('/echo/incoming');
    expect(review()).toBeUndefined();
  });

  it('goes when the review page has dealt with it', async () => {
    pending.share = true;
    await mount('/jobs/run-1');
    await follow(review()!);
    pending.share = false;
    const away = Array.from(host.querySelectorAll('a')).find((a) => a.textContent === 'to the library')!;
    await follow(away);
    expect(where()).toBe('/library');
    expect(review()).toBeUndefined();
  });

  it('finds a share that arrived while the app was open, on the next move', async () => {
    await mount('/jobs/run-1');
    expect(review()).toBeUndefined();
    pending.share = true;
    await follow(Array.from(host.querySelectorAll('a')).find((a) => a.textContent === 'to the library')!);
    expect(review()).toBeDefined();
  });
});
