/**
 * T-5.4.22: a session that expires while a page is open brings the reader back
 * to that page. Until now the interceptor did a hard redirect to `/login` with
 * no page, so an old tab, or an email link a day later, ended at `/`.
 *
 * The real client, interceptor and `AuthProvider` run over the routes the app
 * mounts; only axios's transport is replaced. A page's own request meets the
 * 401, so the path under test is the production one: interceptor, session end,
 * `ProtectedRoute`, sign-in, `PublicOnlyRoute`, `signInReturn`.
 *
 * Across tabs: the tab that met the 401 keeps its page. Another tab hears only
 * that the token went, cannot tell that from a sign-out, and gives its page up,
 * as D-140 says; "in another tab" below pins that. `tests/shell.spec.ts` has
 * both in a real browser.
 *
 * A token can also leave storage with this tab hearing nothing: then every request
 * goes out bare and comes back 401, and the first of them ends the session. Nothing
 * says who took the token, so that counts as a sign-out and leaves no page.
 *
 * Mutation checks, run by hand on 2026-11-05: `setSignedOut(true)` in the expired
 * handler fails "comes back"; `setSignedOut(false)` there fails "a poll refused
 * during a sign-out"; dropping `signingOut.current = true` fails the same one;
 * dropping the store resets fails "takes the Echo thread" and "says nothing else".
 * The old interceptor, put back, fails the four tests in `tests/shell.spec.ts` that
 * go through it (the streaming one has its own path). No `LOST` event fails "at the
 * next 401"; no `holdsSession` check in its listener fails "a bare 401 on a public
 * page"; the expired handler not clearing `holdsSession` fails "several requests are
 * refused at once"; the ref not following `token` fails "a session begun in this tab";
 * `setSignedOut(false)` there fails "counts as a sign-out"; leaving the stored user
 * fails "at the next 401"; `e.key === null` not heard fails "a browser-wide clear",
 * and heard with no session fails "a clear elsewhere".
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('../../services/shareTarget', () => ({
  SHARE_REVIEW_PATH: '/echo/incoming',
  hasPendingShares: async () => false,
  clearPendingShares: async () => undefined,
}));
vi.mock('../../services/wsClient', () => ({ wsClient: { disconnect: vi.fn(), subscribe: () => () => undefined } }));
vi.mock('../../layouts/AppLayout', async () => {
  const { Outlet, useNavigate: useNav } = await import('react-router-dom');
  const { useAuth } = await import('../../contexts/AuthContext');
  return {
    AppLayout: () => {
      const { logout } = useAuth();
      const navigate = useNav();
      return (
        <>
          <button
            onClick={async () => {
              await logout();
              navigate('/login', { replace: true });
            }}
          >
            Sign out
          </button>
          <Outlet />
        </>
      );
    },
  };
});
// Pages that load something, the way the real ones do.
vi.mock('../../pages/JobDetailPage', async () => {
  const { useEffect: effect } = await import('react');
  const { default: client } = await import('../../services/api');
  const { useJobStore } = await import('../../stores/jobStore');
  return {
    JobDetailPage: () => {
      effect(() => {
        void client.get('/jobs/run-1').catch(() => useJobStore.getState().pushToast('error', 'Could not load the run.'));
      }, []);
      return <p>the run</p>;
    },
  };
});
vi.mock('../../pages/SubmitJobPage', () => ({ SubmitJobPage: () => <p>the submit page</p> }));
vi.mock('../../pages/EchoConnectorCallbackPage', async () => {
  const { useEffect: effect } = await import('react');
  const { default: client } = await import('../../services/api');
  return {
    EchoConnectorCallbackPage: () => {
      effect(() => {
        void client.post('/echo/connectors/github/callback', {}).catch(() => undefined);
      }, []);
      return <p>the connector callback</p>;
    },
  };
});

import { AuthProvider } from '../../contexts/AuthContext';
import api from '../../services/api';
import { useEchoPanelStore } from '../../stores/echoPanelStore';
import { useJobStore } from '../../stores/jobStore';
import { routes } from '../index';

const TOKEN_KEY = 'videoresearchpro.authToken';
const USER_KEY = 'videoresearchpro.authUser';
const DEEP = '/jobs/run-1?exchange=e7#notes';

let host: HTMLDivElement;
let root: Root;
let router: ReturnType<typeof createMemoryRouter>;
let client: QueryClient;
let accepted: string[] = [];
let password = 'correct horse';
let logoutGate: Promise<void> | null = null;

/** What the server says. Only tokens in `accepted` are good, as on a real one. */
const transport: AxiosAdapter = async (config: InternalAxiosRequestConfig) => {
  const answer = (status: number, data: unknown) => {
    const response = { status, statusText: '', data, headers: {}, config };
    if (status < 400) return response;
    throw new AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_REQUEST', config, null, response);
  };
  const url = config.url ?? '';
  if (url === '/auth/login') {
    if (JSON.parse(config.data as string).password !== password) return answer(401, { detail: 'Invalid email or password' });
    accepted.push('jwt.new');
    return answer(200, { access_token: 'jwt.new', user: { id: 'u1', email: 'me@x.com' } });
  }
  if (url === '/auth/oauth/providers') return answer(200, { providers: [] });
  const sent = String(config.headers.Authorization ?? '').replace('Bearer ', '');
  if (url === '/auth/logout' && logoutGate) await logoutGate;
  if (!accepted.includes(sent)) return answer(401, { detail: 'Could not validate credentials' });
  if (url === '/auth/me/onboarding') return answer(200, { should_onboard: false });
  return answer(200, {});
};

async function flush() {
  for (let i = 0; i < 10; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function load(url: string | { pathname: string; state: unknown }, seed: (qc: QueryClient) => void = () => undefined) {
  act(() => root.unmount());
  root = createRoot(host);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  seed(client);
  router = createMemoryRouter(routes, { initialEntries: [url] });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </QueryClientProvider>,
    );
  });
  await flush();
}

const where = () => {
  const { pathname, search, hash } = router.state.location;
  return pathname + search + hash;
};

async function type(el: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function signIn(typed = 'correct horse') {
  const [email, secret] = Array.from(host.querySelectorAll('input'));
  await type(email, 'me@x.com');
  await type(secret, typed);
  await act(async () => {
    host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
}

const button = (label: string) => {
  const b = Array.from(host.querySelectorAll('button')).find((x) => x.textContent?.trim() === label);
  if (!b) throw new Error(`no button "${label}" in: ${host.textContent}`);
  return b;
};

/** All a tab hears of another: a storage event. */
async function storageEvent(newValue: string | null) {
  if (newValue) localStorage.setItem(TOKEN_KEY, newValue);
  else localStorage.removeItem(TOKEN_KEY);
  await act(async () => {
    window.dispatchEvent(new StorageEvent('storage', { key: TOKEN_KEY, newValue }));
  });
  await flush();
}

/** `localStorage.clear()` elsewhere reads this way here: no key, no value. */
async function storageCleared() {
  localStorage.clear();
  await act(async () => {
    window.dispatchEvent(new StorageEvent('storage', { key: null, newValue: null }));
  });
  await flush();
}

/** Requests from whatever is on the page, all landing before React next renders. */
async function requests(...urls: string[]) {
  await act(async () => {
    await Promise.all(urls.map((url) => api.get(url).catch(() => undefined)));
  });
  await flush();
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  accepted = [];
  password = 'correct horse';
  logoutGate = null;
  api.defaults.adapter = transport;
  useJobStore.setState({ toasts: [] });
  useEchoPanelStore.setState({ open: false, askText: '', turns: [] });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  api.defaults.adapter = undefined;
});

describe('a session that expires while a page is open', () => {
  beforeEach(() => {
    localStorage.setItem(TOKEN_KEY, 'jwt.expired');
    localStorage.setItem(USER_KEY, JSON.stringify({ email: 'me@x.com' }));
  });

  it('goes to the sign-in page, keeping the page, and says nothing else', async () => {
    await load(DEEP);
    expect(where()).toBe('/login');
    expect((router.state.location.state as { from: { pathname: string } }).from.pathname).toBe('/jobs/run-1');
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(USER_KEY)).toBeNull();
    expect(useJobStore.getState().toasts).toEqual([]);
  });

  it('comes back to that page after a sign-in, with its query and fragment', async () => {
    await load(DEEP);
    await signIn();
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt.new');
    expect(where()).toBe(DEEP);
    expect(host.textContent).toContain('the run');
  });

  it('stays on the sign-in page for a wrong password, with the message and the page', async () => {
    await load(DEEP);
    await signIn('wrong');
    expect(where()).toBe('/login');
    expect(host.textContent).toContain('Invalid email or password');
    await signIn();
    expect(where()).toBe(DEEP);
  });

  it('drops a provider’s one-time code from a callback page, as every sign-in does', async () => {
    await load('/echo/connectors/github/callback?code=one-time&state=s');
    expect(where()).toBe('/login');
    await signIn();
    expect(where()).toBe('/echo/connectors/github/callback');
  });

  it('takes the Echo thread with it: the next sign-in may be someone else’s', async () => {
    useEchoPanelStore.setState({ open: true, askText: 'half a question', turns: [{ id: 't1', kind: 'library', text: 'their question', status: 'done' }] });
    await load(DEEP);
    expect(useEchoPanelStore.getState()).toMatchObject({ open: false, askText: '', turns: [] });
  });

  it('forgets what the account loaded', async () => {
    await load(DEEP, (qc) => qc.setQueryData(['job', 'run-1'], { title: 'their run' }));
    expect(client.getQueryData(['job', 'run-1'])).toBeUndefined();
  });

  it('never leaves the app, whatever a page’s address says', async () => {
    await load({ pathname: '/login', state: { from: { pathname: '//evil.example/x' } } });
    await signIn();
    expect(where()).toBe('/submit');
  });

  it('keeps the page when several requests are refused at once', async () => {
    accepted = ['jwt.expired'];
    await load(DEEP);
    expect(where()).toBe(DEEP);
    accepted = [];
    await requests('/shelves', '/notes', '/library/videos');
    expect(where()).toBe('/login');
    expect((router.state.location.state as { from: { pathname: string } }).from.pathname).toBe('/jobs/run-1');
  });
});

describe('a token that left storage with nobody here hearing', () => {
  beforeEach(() => {
    accepted = ['jwt.live'];
    localStorage.setItem(TOKEN_KEY, 'jwt.live');
    localStorage.setItem(USER_KEY, JSON.stringify({ email: 'me@x.com' }));
  });

  it('ends the session at the next 401, since every request now goes out bare', async () => {
    await load(DEEP);
    expect(where()).toBe(DEEP);
    localStorage.removeItem(TOKEN_KEY);
    await requests('/shelves');
    expect(where()).toBe('/login');
    expect(localStorage.getItem(USER_KEY)).toBeNull();
    expect(useJobStore.getState().toasts).toEqual([]);
  });

  it('counts as a sign-out, since nothing says who took it: the next sign-in leaves no page', async () => {
    await load(DEEP);
    localStorage.removeItem(TOKEN_KEY);
    await requests('/shelves');
    expect(router.state.location.state).toBeNull();
    await signIn();
    expect(where()).toBe('/submit');
  });

  it('forgets what the account loaded, as any session end does', async () => {
    await load(DEEP, (qc) => qc.setQueryData(['job', 'run-1'], { title: 'their run' }));
    localStorage.removeItem(TOKEN_KEY);
    await requests('/shelves');
    expect(client.getQueryData(['job', 'run-1'])).toBeUndefined();
  });

  it('hears a browser-wide clear at once, which names no key', async () => {
    await load(DEEP);
    await storageCleared();
    expect(where()).toBe('/login');
    expect(router.state.location.state).toBeNull();
  });

  it('does the same for a session begun in this tab', async () => {
    localStorage.clear();
    await load(DEEP);
    await signIn();
    expect(where()).toBe(DEEP);
    localStorage.removeItem(TOKEN_KEY);
    await requests('/shelves');
    expect(where()).toBe('/login');
  });
});

describe('a tab with no session to end', () => {
  async function goDeep() {
    await act(async () => {
      await router.navigate(DEEP);
    });
    await flush();
  }

  it('a bare 401 on a public page leaves the next sign-in its page', async () => {
    await load('/landing');
    await requests('/shelves');
    await goDeep();
    expect(where()).toBe('/login');
    expect(router.state.location.state).not.toBeNull();
    await signIn();
    expect(where()).toBe(DEEP);
  });

  it('a clear elsewhere leaves it too: nothing ended here', async () => {
    await load('/landing');
    await storageCleared();
    await goDeep();
    expect(where()).toBe('/login');
    expect(router.state.location.state).not.toBeNull();
  });
});

describe('a deliberate sign-out still leaves no page (D-140)', () => {
  it('when the session had already expired and the sign-out call is refused', async () => {
    // Nothing on this page loads, so the session is only found out at sign-out.
    accepted = [];
    localStorage.setItem(TOKEN_KEY, 'jwt.expired');
    await load('/submit');
    await act(async () => button('Sign out').click());
    await flush();
    expect(where()).toBe('/login');
    expect(router.state.location.state).toBeNull();
    await signIn();
    expect(where()).toBe('/submit');
  });

  it('when a poll refused during a sign-out lands before the sign-out’s own answer', async () => {
    accepted = ['jwt.live'];
    localStorage.setItem(TOKEN_KEY, 'jwt.live');
    await load(DEEP);
    expect(where()).toBe(DEEP);

    let revoked: () => void = () => undefined;
    logoutGate = new Promise((resolve) => (revoked = resolve));
    await act(async () => button('Sign out').click());
    // The server has revoked it; the sign-out's answer is still on its way.
    accepted = [];
    await act(async () => {
      await api.get('/shelves').catch(() => undefined);
    });
    await flush();
    expect(where()).toBe('/login');
    expect(router.state.location.state).toBeNull();

    await act(async () => revoked());
    await flush();
    await signIn();
    expect(where()).toBe('/submit');
  });
});

describe('in another tab', () => {
  it('a session that ended there costs this tab its page: it cannot tell a 401 from a sign-out', async () => {
    accepted = ['jwt.live'];
    localStorage.setItem(TOKEN_KEY, 'jwt.live');
    await load(DEEP);
    await storageEvent(null);
    expect(where()).toBe('/login');
    expect(router.state.location.state).toBeNull();
    await signIn();
    expect(where()).toBe('/submit');
  });

  it('a sign-in there sends the tab that kept its page back to it', async () => {
    localStorage.setItem(TOKEN_KEY, 'jwt.expired');
    await load(DEEP);
    expect(where()).toBe('/login');
    accepted = ['jwt.there'];
    await storageEvent('jwt.there');
    expect(where()).toBe(DEEP);
  });

  it('a sign-in there begins a session here too, so the next expiry keeps the page', async () => {
    accepted = ['jwt.live'];
    localStorage.setItem(TOKEN_KEY, 'jwt.live');
    await load(DEEP);
    await storageEvent(null);
    accepted = ['jwt.there'];
    await storageEvent('jwt.there');
    await act(async () => {
      await router.navigate(DEEP);
    });
    await flush();
    expect(where()).toBe(DEEP);

    accepted = [];
    await act(async () => {
      await api.get('/shelves').catch(() => undefined);
    });
    await flush();
    expect(where()).toBe('/login');
    expect((router.state.location.state as { from: { pathname: string } }).from.pathname).toBe('/jobs/run-1');
  });
});
