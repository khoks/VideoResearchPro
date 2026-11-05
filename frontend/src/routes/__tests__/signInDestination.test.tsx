/**
 * T-5.4.20: a sign-in ends on the page the reader was sent away from.
 *
 * Until now `PublicOnlyRoute` redirected to `/` the moment a token appeared,
 * racing `LoginPage`'s own `navigate(from)`, and OAuth lost the page at the
 * provider. Here the routes the app mounts run over the real AuthProvider and a
 * mocked HTTP client: a deep link while signed out, then each way of signing in.
 *
 * `/` must still work as before: with no page to go back to, the onboarding gate
 * decides, and that is where a share made while signed out is picked up.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Handler = (url: string, body?: unknown, config?: unknown) => Promise<{ data: unknown }>;
const http = vi.hoisted(() => ({
  get: null as unknown as import('vitest').Mock<Handler>,
  post: null as unknown as import('vitest').Mock<Handler>,
}));
http.get = vi.fn<Handler>();
http.post = vi.fn<Handler>();

vi.mock('../../services/api', () => ({
  default: {
    get: (url: string, config?: unknown) => http.get(url, undefined, config),
    post: (url: string, body?: unknown) => http.post(url, body),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  AUTH_TOKEN_KEY: 'videoresearchpro.authToken',
}));
const pending = vi.hoisted(() => ({ share: false }));
vi.mock('../../services/shareTarget', () => ({
  SHARE_REVIEW_PATH: '/echo/incoming',
  hasPendingShares: async () => pending.share,
  clearPendingShares: async () => undefined,
}));
vi.mock('../../services/wsClient', () => ({ wsClient: { disconnect: vi.fn(), subscribe: () => () => undefined } }));
vi.mock('../../layouts/AppLayout', async () => {
  const { Outlet, useNavigate } = await import('react-router-dom');
  const { useAuth } = await import('../../contexts/AuthContext');
  return {
    // Signs out the way the real layout's `handleLogout` does.
    AppLayout: () => {
      const { logout } = useAuth();
      const navigate = useNavigate();
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
vi.mock('../../pages/JobDetailPage', () => ({ JobDetailPage: () => <p>the run</p> }));
vi.mock('../../pages/SubmitJobPage', () => ({ SubmitJobPage: () => <p>the submit page</p> }));
vi.mock('../../pages/WelcomePage', () => ({ WelcomePage: () => <p>the wizard</p> }));
vi.mock('../../pages/EchoShareTargetPage', () => ({ EchoShareTargetPage: () => <p>the share review</p> }));

import { AuthProvider } from '../../contexts/AuthContext';
import { routes } from '../index';

const TOKEN_KEY = 'videoresearchpro.authToken';
const DEEP = '/jobs/run-1?exchange=e7#notes';

let host: HTMLDivElement;
let root: Root;
let router: ReturnType<typeof createMemoryRouter>;
let client: QueryClient;

async function flush() {
  for (let i = 0; i < 8; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

/** One page load: a tab keeps sessionStorage across it, and nothing else. */
async function load(url: string, seed: (qc: QueryClient) => void = () => undefined) {
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
const inputs = () => Array.from(host.querySelectorAll('input'));
const button = (label: string) => {
  const b = Array.from(host.querySelectorAll('button')).find((x) => x.textContent?.trim() === label);
  if (!b) throw new Error(`no button "${label}" in: ${host.textContent}`);
  return b;
};

async function followLink(label: string) {
  const link = Array.from(host.querySelectorAll('a')).find((a) => a.textContent?.trim() === label);
  if (!link) throw new Error(`no link "${label}" in: ${host.textContent}`);
  await act(async () => link.click());
  await flush();
}

async function type(el: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function submitForm() {
  await act(async () => {
    host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
}

async function signInWithPassword() {
  const [email, password] = inputs();
  await type(email, 'me@x.com');
  await type(password, 'correct horse');
  await submitForm();
}

/** Press "Continue with Google": the provider is a real page load away. */
async function leaveForGoogle() {
  const assign = vi.fn();
  const original = window.location;
  Object.defineProperty(window, 'location', { configurable: true, value: { ...original, assign } });
  try {
    await act(async () => button('Continue with Google').click());
    await flush();
    expect(assign).toHaveBeenCalledWith('https://accounts.google.com/o/oauth2/v2/auth?state=s');
  } finally {
    Object.defineProperty(window, 'location', { configurable: true, value: original });
  }
}

/** All a tab hears when another one ends the session: a storage event. */
async function sessionEndsInAnotherTab() {
  localStorage.removeItem(TOKEN_KEY);
  await act(async () => {
    window.dispatchEvent(new StorageEvent('storage', { key: TOKEN_KEY, newValue: null }));
  });
  await flush();
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  pending.share = false;
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  http.post.mockReset();
  http.post.mockImplementation(async (url) => {
    if (url === '/auth/login') return { data: { access_token: 'jwt.password' } };
    if (url === '/auth/logout') return { data: {} };
    throw new Error(`unexpected POST ${url}`);
  });
  http.get.mockReset();
  http.get.mockImplementation(async (url) => {
    if (url === '/auth/oauth/providers') return { data: { providers: ['google'] } };
    if (url === '/auth/oauth/google/start') return { data: { authorize_url: 'https://accounts.google.com/o/oauth2/v2/auth?state=s' } };
    if (url === '/auth/oauth/google/callback') return { data: { access_token: 'jwt.google' } };
    if (url === '/auth/me') return { data: { id: 'u1', email: 'g@x.com', tier: 'free' } };
    if (url === '/auth/me/onboarding') return { data: { should_onboard: false } };
    throw new Error(`unexpected GET ${url}`);
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('a deep link while signed out', () => {
  it('goes to the sign-in page and remembers the page', async () => {
    await load(DEEP);
    expect(where()).toBe('/login');
    expect((router.state.location.state as { from: { pathname: string } }).from.pathname).toBe('/jobs/run-1');
  });

  it('comes back after a password, with its query and fragment', async () => {
    await load(DEEP);
    await signInWithPassword();
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt.password');
    expect(where()).toBe(DEEP);
    expect(host.textContent).toContain('the run');
  });

  it('comes back after the second step', async () => {
    http.post.mockImplementation(async (url) => {
      if (url === '/auth/login') return { data: { requires_mfa: true, mfa_token: 'ticket' } };
      if (url === '/auth/login/mfa') return { data: { access_token: 'jwt.mfa' } };
      throw new Error(url);
    });
    await load(DEEP);
    await signInWithPassword();
    expect(where()).toBe('/login');
    await type(inputs()[0], '123456');
    await submitForm();
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt.mfa');
    expect(where()).toBe(DEEP);
    expect(host.textContent).toContain('the run');
  });

  it('comes back from an OAuth provider, and the callback address loses the code', async () => {
    await load(DEEP);
    await leaveForGoogle();
    await load('/login/oauth/google/callback?code=abc&state=xyz');
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt.google');
    expect(where()).toBe(DEEP);
    expect(host.textContent).toContain('the run');
    expect(sessionStorage.length, 'the tab keeps nothing once it is used').toBe(0);
  });

  it('comes back from an OAuth provider through the second step', async () => {
    http.get.mockImplementation(async (url) => {
      if (url === '/auth/oauth/providers') return { data: { providers: ['google'] } };
      if (url === '/auth/oauth/google/start') return { data: { authorize_url: 'https://accounts.google.com/o/oauth2/v2/auth?state=s' } };
      if (url === '/auth/oauth/google/callback') return { data: { requires_mfa: true, mfa_token: 'ticket-o' } };
      if (url === '/auth/me') return { data: { id: 'u1', email: 'g@x.com' } };
      throw new Error(`unexpected GET ${url}`);
    });
    http.post.mockImplementation(async (url) => {
      if (url === '/auth/login/mfa') return { data: { access_token: 'jwt.google.mfa' } };
      throw new Error(url);
    });
    await load(DEEP);
    await leaveForGoogle();
    await load('/login/oauth/google/callback?code=abc&state=xyz');
    expect(where()).toBe('/login/oauth/google/callback');
    await type(inputs()[0], '654321');
    await submitForm();
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt.google.mfa');
    expect(where()).toBe(DEEP);
  });

  it('keeps the page when the reader cancels at the provider and signs in another way', async () => {
    await load(DEEP);
    await leaveForGoogle();
    await load('/login/oauth/google/callback?error=access_denied');
    expect(host.textContent).toContain('You cancelled at Google');
    await act(async () => {
      Array.from(host.querySelectorAll('a')).find((a) => a.textContent === 'Back to sign in')!.click();
    });
    await flush();
    expect(where()).toBe('/login');
    await signInWithPassword();
    expect(where()).toBe(DEEP);
  });

  it('keeps the page when two-step sends an OAuth sign-in back to the password', async () => {
    http.get.mockImplementation(async (url) => {
      if (url === '/auth/oauth/providers') return { data: { providers: ['google'] } };
      if (url === '/auth/oauth/google/start') return { data: { authorize_url: 'https://accounts.google.com/o/oauth2/v2/auth?state=s' } };
      if (url === '/auth/oauth/google/callback') return { data: { requires_mfa: true, mfa_token: 'ticket-o' } };
      throw new Error(`unexpected GET ${url}`);
    });
    await load(DEEP);
    await leaveForGoogle();
    await load('/login/oauth/google/callback?code=abc&state=xyz');
    await act(async () => button('Back to sign in').click());
    await flush();
    expect(where()).toBe('/login');
    await signInWithPassword();
    expect(where()).toBe(DEEP);
  });
});

describe('with no page to go back to', () => {
  it('a password sign-in ends at the gate, which opens the submit page', async () => {
    await load('/login');
    await signInWithPassword();
    expect(where()).toBe('/submit');
  });

  it('an OAuth sign-in ends at the gate too, whatever an earlier attempt left', async () => {
    await load('/login');
    await leaveForGoogle();
    await load('/login/oauth/google/callback?code=abc&state=xyz');
    expect(where()).toBe('/submit');
  });

  it('a new account still reaches the wizard', async () => {
    http.get.mockImplementation(async (url) => {
      if (url === '/auth/oauth/providers') return { data: { providers: [] } };
      if (url === '/auth/me/onboarding') return { data: { should_onboard: true } };
      throw new Error(`unexpected GET ${url}`);
    });
    await load('/login');
    await signInWithPassword();
    expect(where()).toBe('/welcome');
  });
});

describe('a share made while signed out', () => {
  it('is picked up at `/` by the gate', async () => {
    pending.share = true;
    await load('/login');
    await signInWithPassword();
    expect(where()).toBe('/echo/incoming');
    expect(host.textContent).toContain('the share review');
  });

  it('is picked up the same way after OAuth', async () => {
    pending.share = true;
    await load('/login');
    await leaveForGoogle();
    await load('/login/oauth/google/callback?code=abc&state=xyz');
    expect(where()).toBe('/echo/incoming');
  });

  it('goes straight back when the share opened the app on its own page', async () => {
    pending.share = true;
    await load('/echo/incoming');
    expect(where()).toBe('/login');
    await signInWithPassword();
    expect(where()).toBe('/echo/incoming');
    expect(host.textContent).toContain('the share review');
  });
});

// `/` is the only place the wizard and a waiting share are picked up, so a
// marketing page must not count as a page to go back to.
describe('signing in from a marketing page', () => {
  it.each(['/landing', '/pricing'])('%s leaves the decision to the gate after a password', async (page) => {
    await load(page);
    await followLink('Sign in');
    expect(where()).toBe('/login');
    await signInWithPassword();
    expect(where()).toBe('/submit');
  });

  it('leaves it to the gate after OAuth, and nothing waits in the tab for the trip', async () => {
    await load('/landing');
    await followLink('Sign in');
    await leaveForGoogle();
    expect(sessionStorage.length).toBe(0);
    await load('/login/oauth/google/callback?code=abc&state=xyz');
    expect(where()).toBe('/submit');
  });

  it('still sends a new account to the wizard', async () => {
    http.get.mockImplementation(async (url) => {
      if (url === '/auth/oauth/providers') return { data: { providers: [] } };
      if (url === '/auth/me/onboarding') return { data: { should_onboard: true } };
      throw new Error(`unexpected GET ${url}`);
    });
    await load('/landing');
    await followLink('Sign in');
    await signInWithPassword();
    expect(where()).toBe('/welcome');
  });

  it('picks up a share made while signed out, after a password', async () => {
    pending.share = true;
    await load('/landing');
    await followLink('Sign in');
    await signInWithPassword();
    expect(where()).toBe('/echo/incoming');
  });

  it('picks up a share made while signed out, after OAuth', async () => {
    pending.share = true;
    await load('/pricing');
    await followLink('Sign in');
    await leaveForGoogle();
    await load('/login/oauth/google/callback?code=abc&state=xyz');
    expect(where()).toBe('/echo/incoming');
  });

  it('opens the app through the gate for a reader already signed in', async () => {
    localStorage.setItem(TOKEN_KEY, 'jwt.old');
    http.get.mockImplementation(async (url) => {
      if (url === '/auth/me/onboarding') return { data: { should_onboard: true } };
      throw new Error(`unexpected GET ${url}`);
    });
    await load('/landing');
    await followLink('Open app →');
    expect(where()).toBe('/welcome');
  });
});

// The race this guards against only shows in a real browser, where the guard's
// redirect lands after the layout's: `tests/shell.spec.ts` is the check that
// fails without `signedOut`. This one holds the flow together.
describe('signing out', () => {
  it('leaves no page behind for the next sign-in, perhaps someone else’s', async () => {
    localStorage.setItem(TOKEN_KEY, 'jwt.old');
    await load('/jobs/run-1');
    expect(host.textContent).toContain('the run');
    await act(async () => button('Sign out').click());
    await flush();
    expect(where()).toBe('/login');
    expect(router.state.location.state).toBeNull();
    await signInWithPassword();
    expect(where()).toBe('/submit');
  });

  it('in another tab leaves no page behind here either', async () => {
    localStorage.setItem(TOKEN_KEY, 'jwt.old');
    await load('/jobs/run-1');
    expect(host.textContent).toContain('the run');
    await sessionEndsInAnotherTab();
    expect(where()).toBe('/login');
    expect(router.state.location.state).toBeNull();
    await signInWithPassword();
    expect(where()).toBe('/submit');
  });

  it('forgets what the account loaded, in this tab', async () => {
    localStorage.setItem(TOKEN_KEY, 'jwt.old');
    await load('/jobs/run-1', (qc) => qc.setQueryData(['job', 'run-1'], { title: 'their run' }));
    await act(async () => button('Sign out').click());
    await flush();
    expect(client.getQueryData(['job', 'run-1'])).toBeUndefined();
  });

  it('forgets what the account loaded, from another tab', async () => {
    localStorage.setItem(TOKEN_KEY, 'jwt.old');
    await load('/jobs/run-1', (qc) => qc.setQueryData(['job', 'run-1'], { title: 'their run' }));
    await sessionEndsInAnotherTab();
    expect(client.getQueryData(['job', 'run-1'])).toBeUndefined();
  });

  it('leaves alone the queries of a page opened signed out', async () => {
    await load('/login', (qc) => qc.setQueryData(['public'], 'kept'));
    expect(client.getQueryData(['public'])).toBe('kept');
  });
});

describe('a signed-in reader on a sign-in page', () => {
  it('still goes to `/`', async () => {
    localStorage.setItem(TOKEN_KEY, 'jwt.old');
    await load('/login');
    expect(where()).toBe('/submit');
  });
});
