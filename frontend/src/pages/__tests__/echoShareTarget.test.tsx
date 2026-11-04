/**
 * The page a share from the Android share sheet lands on (T-3.7.6.1): that
 * nothing leaves it without a tap, and what it does with each outcome. The
 * stash and its rules are tested in services/__tests__/shareTarget.test.ts.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { deliver, discard, read } = vi.hoisted(() => ({ deliver: vi.fn(), discard: vi.fn(), read: vi.fn() }));
vi.mock('../../services/shareTarget', async (original) => ({
  ...(await original<typeof import('../../services/shareTarget')>()),
  deliverPendingShares: deliver,
  discardPendingShares: discard,
  readPendingShares: read,
}));

import type { PendingShare } from '../../services/shareTarget';
import { useJobStore } from '../../stores/jobStore';
import { EchoShareTargetPage } from '../EchoShareTargetPage';

const PATH = '/echo/incoming';
let host: HTMLDivElement;
let root: Root;

const waiting = (over: Partial<PendingShare> = {}): PendingShare => ({
  key: 'http://localhost/echo/share-target/pending/one',
  title: '',
  text: 'A line worth keeping',
  url: '',
  files: [],
  sent: [],
  ...over,
});

async function renderAt(path: string) {
  await act(async () => {
    root.render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={PATH} element={<EchoShareTargetPage />} />
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
const tap = (name: string) => act(async () => buttonNamed(name)?.click());
const alertText = () => host.querySelector('[role="alert"]')?.textContent;

beforeEach(() => {
  deliver.mockReset();
  discard.mockReset().mockResolvedValue(undefined);
  read.mockReset().mockResolvedValue([waiting()]);
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
  it('posts nothing until the user taps, whatever is waiting', async () => {
    await renderAt(PATH);
    expect(host.textContent).toContain('A line worth keeping');
    expect(buttonNamed('Add to Echo')).toBeDefined();
    expect(deliver).not.toHaveBeenCalled();
  });

  it('adds what was shown on the tap, once, and lands in the inbox', async () => {
    deliver.mockResolvedValue({ kind: 'added', count: 1, skipped: 0 });
    await renderAt(PATH);
    await tap('Add to Echo');
    expect(deliver).toHaveBeenCalledTimes(1);
    expect(deliver).toHaveBeenCalledWith([waiting().key]);
    expect(host.textContent).toContain('The inbox');
    expect(lastToast()).toBe('Added to Echo.');
  });

  it('shows each thing it would add: words, a link and a file, with no live link', async () => {
    const file = new File(['bytes'], 'scan.png', { type: 'image/png' });
    read.mockResolvedValue([waiting({ text: 'Different words', url: 'http://169.254.169.254/latest/', files: [file] })]);
    await renderAt(PATH);
    expect(host.textContent).toContain('Different words');
    expect(host.textContent).toContain('http://169.254.169.254/latest/');
    expect(host.textContent).toContain('scan.png');
    expect(linkNamed('http://169.254.169.254/latest/')).toBeUndefined();
  });

  it('shows what is left of a share that went part of the way', async () => {
    read.mockResolvedValue([waiting({ url: 'https://a.example/x', text: 'Different words', sent: [0] })]);
    await renderAt(PATH);
    expect(host.textContent).toContain('Different words');
    expect(host.textContent).not.toContain('https://a.example/x');
  });

  it('cuts a long text to a preview, and renders markup as text', async () => {
    read.mockResolvedValue([waiting({ text: `<img src=x onerror=alert(1)> ${'x'.repeat(400)}` })]);
    await renderAt(PATH);
    expect(host.querySelector('img')).toBeNull();
    expect(host.textContent).toContain('<img src=x');
    expect(host.textContent).not.toContain('x'.repeat(300));
  });

  it('says before the tap when files will be left out', async () => {
    const files = Array.from({ length: 12 }, (_, i) => new File(['x'], `f${i}.txt`));
    read.mockResolvedValue([waiting({ text: '', files })]);
    await renderAt(PATH);
    expect(host.textContent).toContain('Only the first files are kept.');
    expect(host.querySelectorAll('li')).toHaveLength(10);
  });

  it('discards what was shown and posts nothing', async () => {
    await renderAt(PATH);
    await tap('Discard');
    expect(discard).toHaveBeenCalledWith([waiting().key]);
    expect(deliver).not.toHaveBeenCalled();
    expect(host.textContent).toContain('The inbox');
    expect(lastToast()).toBe('Discarded. Nothing was added.');
  });

  it('says when files were left out', async () => {
    deliver.mockResolvedValue({ kind: 'added', count: 10, skipped: 2 });
    await renderAt(PATH);
    await tap('Add to Echo');
    expect(lastToast()).toContain('2 left out');
  });

  it('shows the server’s refusal with the way to a plan that has Echo', async () => {
    deliver.mockResolvedValue({ kind: 'refused', count: 0, refused: 1, status: 403, detail: 'Echo needs the Studio plan.' });
    await renderAt(PATH);
    await tap('Add to Echo');
    expect(alertText()).toContain('Echo needs the Studio plan.');
    expect(linkNamed('See the plans')?.getAttribute('href')).toBe('/account/subscription');
    expect(buttonNamed('Try again')).toBeUndefined();
    expect(host.textContent).not.toContain('refused.');
  });

  it('counts what went and what was refused, and offers no plans a plan would not change', async () => {
    deliver.mockResolvedValue({ kind: 'refused', count: 2, refused: 1, status: 413, detail: 'file is over 25 MB' });
    await renderAt(PATH);
    await tap('Add to Echo');
    expect(alertText()).toBe('file is over 25 MB');
    expect(host.textContent).toContain('2 added, 1 refused.');
    expect(host.textContent).not.toContain('The rest was added.');
    expect(linkNamed('See the plans')).toBeUndefined();
  });

  it('counts refusals when nothing went', async () => {
    deliver.mockResolvedValue({ kind: 'refused', count: 0, refused: 3, status: 413, detail: 'file is over 25 MB' });
    await renderAt(PATH);
    await tap('Add to Echo');
    expect(host.textContent).toContain('0 added, 3 refused.');
  });

  it('keeps the share and retries when the server could not be reached', async () => {
    deliver.mockResolvedValueOnce({ kind: 'failed', detail: null });
    deliver.mockResolvedValueOnce({ kind: 'added', count: 1, skipped: 0 });
    await renderAt(PATH);
    await tap('Add to Echo');
    expect(alertText()).toContain('still on this device');
    await tap('Try again');
    expect(host.textContent).toContain('The inbox');
    expect(deliver).toHaveBeenCalledTimes(2);
    expect(deliver).toHaveBeenLastCalledWith([waiting().key]);
  });

  it('can give up on a share that keeps failing', async () => {
    deliver.mockResolvedValue({ kind: 'failed', detail: null });
    await renderAt(PATH);
    await tap('Add to Echo');
    await tap('Discard');
    expect(discard).toHaveBeenCalledWith([waiting().key]);
  });

  it('says so when nothing is waiting', async () => {
    read.mockResolvedValue([]);
    await renderAt(PATH);
    expect(host.textContent).toContain('Nothing is waiting');
    expect(buttonNamed('Add to Echo')).toBeUndefined();
  });

  it('treats an unreadable stash as nothing waiting', async () => {
    read.mockRejectedValue(new Error('no Cache API'));
    await renderAt(PATH);
    expect(host.textContent).toContain('Nothing is waiting');
  });

  it('says so when the device could not keep the share, and posts nothing', async () => {
    await renderAt(`${PATH}?failed=1`);
    expect(host.textContent).toContain('could not keep what you shared');
    expect(read).not.toHaveBeenCalled();
    expect(deliver).not.toHaveBeenCalled();
  });
});
