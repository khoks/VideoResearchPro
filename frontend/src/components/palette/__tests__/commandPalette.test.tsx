/**
 * The palette mounted the way AppLayout mounts it, in jsdom: the shortcut
 * opens it, actions filter on the client, results come from `/search`
 * grouped, Enter navigates, recents are kept, Escape closes and gives focus
 * back, the result count is announced.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CommandPalette } from '../CommandPalette';
import { countResults, loadRecent, matchesQuery, pushRecent } from '../model';
import { usePaletteStore } from '../../../stores/paletteStore';
import type { SearchResponse } from '../../../services/searchApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const searchMock = vi.fn<(q: string, signal?: AbortSignal) => Promise<SearchResponse>>();

vi.mock('../../../services/searchApi', () => ({
  searchApi: { search: (q: string, signal?: AbortSignal) => searchMock(q, signal) },
}));
vi.mock('../../../contexts/AuthContext', () => ({ useAuth: () => ({ token: 'fixture' }) }));
vi.mock('../../../hooks/useTierCapabilities', () => ({ useTierCapabilities: () => ({ has: () => true }) }));

const RESULT: SearchResponse = {
  q: 'smoke',
  backend: 'fts5',
  groups: [
    { type: 'jobs', items: [{ id: 'job-1', title: 'pratidhvani smoke test', subtitle: 'Topic · 3 sources', href: '/jobs/job-1', score: 3 }] },
    { type: 'documents', items: [{ id: 'doc-1', title: 'Smoking and lung cancer', subtitle: 'Medicover', href: '/library?document=doc-1', score: 2 }] },
    { type: 'channels', items: [] },
  ],
};

let host: HTMLDivElement;
let root: Root;
let path = '';

function Where() {
  const loc = useLocation();
  path = loc.pathname + loc.search;
  return null;
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/notes']}>
          <button id="before">focus here first</button>
          <CommandPalette />
          <Where />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
}

function press(key: string, mods: Record<string, boolean> = {}, target: EventTarget = document.activeElement ?? document.body) {
  act(() => {
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...mods }));
  });
}

/** The shortcut, then the lazily loaded panel. */
async function openWith(mods: Record<string, boolean>, target: EventTarget = document.body) {
  press('k', mods, target);
  for (let i = 0; i < 20 && !document.querySelector('[role="dialog"]'); i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  }
}

async function type(text: string) {
  const input = document.querySelector<HTMLInputElement>('[role="dialog"] input')!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setter.call(input, text);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  // Past the debounce, then let the query resolve. Separate acts: inside one
  // long act React holds the debounced re-render until the act ends, so the
  // request would only start after the wait.
  for (let i = 0; i < 4; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 120));
    });
  }
}

function options(): string[] {
  return [...document.querySelectorAll('[role="option"]')].map((o) => o.textContent ?? '');
}

beforeEach(() => {
  // jsdom has no layout: cmdk measures its list with ResizeObserver and
  // scrolls the active option into view.
  Element.prototype.scrollIntoView ??= function scrollIntoView() {};
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  window.localStorage.clear();
  usePaletteStore.setState({ open: false, singleKeyShortcuts: true });
  searchMock.mockReset();
  searchMock.mockImplementation(() => Promise.resolve(RESULT));
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('palette model', () => {
  it('matches every word of the query against label and keywords', () => {
    expect(matchesQuery({ label: 'Switch to dark mode', keywords: 'theme toggle' }, 'theme')).toBe(true);
    expect(matchesQuery({ label: 'Ask the library' }, 'ask lib')).toBe(true);
    expect(matchesQuery({ label: 'Ask the library' }, 'ask echo')).toBe(false);
  });

  it('keeps recents newest first, one per href, capped, and survives junk in storage', () => {
    window.localStorage.setItem('pratidhvani:palette-recent', '{not json');
    expect(loadRecent()).toEqual([]);
    let list = pushRecent({ href: '/a', title: 'A', subtitle: '', kind: 'Runs' }, []);
    list = pushRecent({ href: '/b', title: 'B', subtitle: '', kind: 'Runs' }, list);
    list = pushRecent({ href: '/a', title: 'A again', subtitle: '', kind: 'Runs' }, list);
    expect(list.map((r) => r.title)).toEqual(['A again', 'B']);
    for (let i = 0; i < 10; i++) list = pushRecent({ href: `/x${i}`, title: `x${i}`, subtitle: '', kind: 'Runs' }, list);
    expect(list).toHaveLength(6);
    expect(loadRecent()).toHaveLength(6);
  });

  it('counts results across groups and actions', () => {
    expect(countResults([{ items: [1, 2] }, { items: [] }], 3)).toBe(5);
  });
});

describe('CommandPalette', () => {
  it('opens on Ctrl-K with focus in a labelled combobox and the actions listed', async () => {
    mount();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    await openWith({ ctrlKey: true });
    const dialog = document.querySelector('[role="dialog"]')!;
    expect(dialog.getAttribute('aria-label')).toBe('Command palette');
    const input = dialog.querySelector('input')!;
    expect(document.activeElement).toBe(input);
    expect(input.getAttribute('role')).toBe('combobox');
    expect(options()).toEqual(expect.arrayContaining(['New research', 'Ask the library', 'Your notes']));
  });

  it('opens on the Ctrl-Alt-K alternate too', async () => {
    mount();
    await openWith({ ctrlKey: true, altKey: true });
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
  });

  it('filters actions on the client and asks the server once per settled query', async () => {
    mount();
    await openWith({ ctrlKey: true });
    await type('smoke');
    expect(searchMock).toHaveBeenCalledTimes(1);
    expect(searchMock.mock.calls[0][0]).toBe('smoke');
    const text = document.querySelector('[role="listbox"]')!.textContent!;
    expect(text).toContain('Runs');
    expect(text).toContain('pratidhvani smoke test');
    expect(text).toContain('Sources');
    expect(text).not.toContain('Channels'); // empty groups are not shown
    expect(options()).not.toContain('New research');
    expect(document.querySelector('[aria-live="polite"]')!.textContent).toBe('2 results');
  });

  it('Enter opens the selected result, remembers it, and closes', async () => {
    mount();
    await openWith({ ctrlKey: true });
    await type('smoke');
    press('Enter');
    expect(path).toBe('/jobs/job-1');
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(loadRecent()[0]).toMatchObject({ href: '/jobs/job-1', kind: 'Runs' });
  });

  it('says so when nothing matches, and keeps working when search fails', async () => {
    searchMock.mockResolvedValueOnce({ q: 'zzzz', backend: 'fts5', groups: [] });
    mount();
    await openWith({ ctrlKey: true });
    await type('zzzz');
    expect(document.querySelector('[role="dialog"]')!.textContent).toContain('Nothing in your library matches');
    searchMock.mockRejectedValueOnce(new Error('down'));
    await type('theme');
    expect(options()).toContain('Switch to dark mode');
  });

  it('Escape closes and gives focus back', async () => {
    mount();
    const before = document.getElementById('before')!;
    before.focus();
    await openWith({ ctrlKey: true }, document.activeElement ?? document.body);
    expect(document.activeElement).not.toBe(before);
    press('Escape');
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(before);
  });

  it('runs the g chords, and the setting action turns them off', async () => {
    mount();
    press('g', {}, document.body);
    press('l', {}, document.body);
    expect(path).toBe('/library');
    await openWith({ ctrlKey: true });
    const off = [...document.querySelectorAll<HTMLElement>('[role="option"]')].find((o) =>
      o.textContent?.startsWith('Turn single-key shortcuts off'),
    )!;
    act(() => off.click());
    expect(usePaletteStore.getState().singleKeyShortcuts).toBe(false);
    press('Escape');
    press('g', {}, document.body);
    press('a', {}, document.body);
    expect(path).toBe('/library');
  });
});
