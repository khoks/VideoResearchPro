/**
 * T-8.8.4.1: a lazy route whose chunk cannot be fetched offers a reload.
 *
 * Mid-restart, or after a redeploy replaces a chunk's hash, the dynamic import
 * rejects. React.lazy caches that rejection, so the route stays broken in
 * the tab until a full reload. Without an `errorElement` React Router shows its
 * default "Unexpected Application Error" screen with a stack trace.
 *
 * Checked on the routes the app mounts: each page module here rejects on
 * import, the way a missing chunk does.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { createMemoryRouter, RouterProvider, type RouteObject } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Hoisted above any helper, so each factory throws for itself.
vi.mock('../../pages/ReportReaderPage', () => {
  throw new TypeError('Failed to fetch dynamically imported module');
});
vi.mock('../../pages/KnowledgeReaderPage', () => {
  throw new TypeError('Failed to fetch dynamically imported module');
});
vi.mock('../../pages/OutputReaderPage', () => {
  throw new TypeError('Failed to fetch dynamically imported module');
});
vi.mock('../../pages/GraphPage', () => {
  throw new TypeError('Failed to fetch dynamically imported module');
});

import { router } from '../index';

function find(routes: RouteObject[], path: string): RouteObject | undefined {
  for (const r of routes) {
    if (r.path === path) return r;
    const hit = r.children ? find(r.children, path) : undefined;
    if (hit) return hit;
  }
  return undefined;
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  // React and React Router both report the caught error.
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
  vi.spyOn(console, 'warn').mockImplementation(() => undefined);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function mount(path: string, url: string) {
  const route = find(router.routes as RouteObject[], path);
  expect(route, path).toBeDefined();
  const memory = createMemoryRouter(
    [{ path: `/${path}`, element: route!.element, errorElement: route!.errorElement }],
    { initialEntries: [url] },
  );
  await act(async () => {
    root.render(<RouterProvider router={memory} />);
  });
  for (let i = 0; i < 12; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

describe('a lazy route whose chunk cannot load', () => {
  it.each([
    ['reports/:jobId', '/reports/j1'],
    ['knowledge/:videoId', '/knowledge/v1'],
    ['author/outputs/:outputId', '/author/outputs/o1'],
    ['library/graph', '/library/graph'],
  ])('%s offers a reload instead of the router’s error screen', async (path, url) => {
    await mount(path, url);
    expect(host.textContent).toContain('This page could not be loaded');
    expect(host.textContent).not.toContain('Unexpected Application Error');
    expect(host.textContent).not.toContain('Failed to fetch');
  });

  it('reloads the tab, which is what clears the cached rejection', async () => {
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
    await mount('reports/:jobId', '/reports/j1');
    const button = [...host.querySelectorAll('button')].find((b) => b.textContent === 'Reload');
    expect(button).toBeDefined();
    act(() => button!.click());
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
