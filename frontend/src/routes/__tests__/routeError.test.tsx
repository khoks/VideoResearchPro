/**
 * T-4.11.2.3: a page that throws while it renders lands on the app's own error
 * screen, whichever group of routes it is in. Before this the eager pages had
 * no `errorElement`, so React Router printed the error and its stack.
 *
 * Checked on the routes the app mounts, with a page that throws. Taking the
 * root `errorElement` away fails every test here.
 */
import { act, type ReactElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { auth, explode, DETAIL } = vi.hoisted(() => {
  const DETAIL = 'TypeError: cannot read job.title at /srv/app/JobsListPage.tsx:12:3';
  return {
    auth: { isAuthenticated: true },
    DETAIL,
    explode: (): never => {
      throw new Error(DETAIL);
    },
  };
});

vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => auth }));
vi.mock('../../layouts/AppLayout', async () => {
  const { Outlet } = await import('react-router-dom');
  return { AppLayout: () => <Outlet /> };
});
vi.mock('../../pages/JobsListPage', () => ({ JobsListPage: explode }));
vi.mock('../../pages/marketing/LandingPage', () => ({ LandingPage: explode }));
vi.mock('../../pages/LoginPage', () => ({ LoginPage: explode }));
vi.mock('../../pages/LibraryPage', () => ({ LibraryPage: () => <p>the library</p> }));

import { RouteError } from '../../components/common/RouteError';
import { routes } from '../index';

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  auth.isAuthenticated = true;
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  // React and React Router both report the caught error to the console.
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
  vi.spyOn(console, 'warn').mockImplementation(() => undefined);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

async function mount(url: string) {
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  await act(async () => {
    root.render(<RouterProvider router={router} />);
  });
  return router;
}

const button = (label: string) => {
  const b = Array.from(host.querySelectorAll('button')).find((x) => x.textContent === label);
  if (!b) throw new Error(`no button "${label}" in: ${host.textContent}`);
  return b;
};

describe('the route error screen', () => {
  it('sits above every route', () => {
    expect(routes).toHaveLength(1);
    expect(routes[0].path).toBeUndefined();
    expect((routes[0].errorElement as ReactElement).type).toBe(RouteError);
    expect((routes[0].children ?? []).length).toBeGreaterThan(3);
  });

  it.each([
    ['an eager page inside the app', '/jobs', true],
    ['a marketing page', '/landing', false],
    ['a sign-in page', '/login', false],
  ])('catches %s that throws, in the brand voice, with no stack on screen', async (_name, url, signedIn) => {
    auth.isAuthenticated = signedIn;
    await mount(url);
    const text = host.textContent ?? '';
    expect(text).toContain('This page slipped off the shelf.');
    expect(text).toContain('Your library is safe.');
    for (const leak of [DETAIL, 'TypeError', '.tsx', 'Unexpected Application Error', 'Hey developer']) {
      expect(text).not.toContain(leak);
    }
    expect(host.querySelector('pre')).toBeNull();
  });

  it('has a way back that leaves the broken page', async () => {
    const router = await mount('/jobs');
    await act(async () => button('Back to your library').click());
    expect(router.state.location.pathname).toBe('/library');
    expect(host.textContent).toContain('the library');
    expect(host.textContent).not.toContain('slipped off the shelf');
  });

  it('offers a reload for what going back cannot mend', async () => {
    const reload = vi.fn();
    const original = window.location;
    Object.defineProperty(window, 'location', { configurable: true, value: { ...original, reload } });
    try {
      await mount('/jobs');
      await act(async () => button('Reload').click());
      expect(reload).toHaveBeenCalledOnce();
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original });
    }
  });
});
