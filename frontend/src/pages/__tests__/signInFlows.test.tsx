/**
 * The sign-in surfaces of E-5.4, at the pages the router mounts, with the
 * real AuthProvider over a mocked HTTP client:
 *
 * - Sign-in: a password accepted for an account with two-step on asks for
 *   the code (or a recovery code) and finishes through `/auth/login/mfa`;
 *   a wrong code and an expired step say so where the reader typed.
 * - OAuth buttons appear only for the providers the server names.
 * - The OAuth return page exchanges `code` and `state` once, and stops at
 *   the second factor when the account has one.
 * - Forgot / reset password: the request page never shows anything from the
 *   response (a reset secret there was an account takeover), the confirm
 *   page sends the pasted code and the new password.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import type { RouteObject } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Handler = (url: string, body?: unknown, config?: unknown) => Promise<{ data: unknown }>;
const http = {
  get: vi.fn<Handler>(),
  post: vi.fn<Handler>(),
};
vi.mock('../../services/api', () => ({
  default: {
    get: (url: string, config?: unknown) => http.get(url, undefined, config),
    post: (url: string, body?: unknown) => http.post(url, body),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  AUTH_TOKEN_KEY: 'videoresearchpro.authToken',
}));

import { AuthProvider } from '../../contexts/AuthContext';
import { PublicOnlyRoute } from '../../routes/guards';
import { LoginPage } from '../LoginPage';
import { OAuthCallbackPage } from '../OAuthCallbackPage';
import { ForgotPasswordPage } from '../ForgotPasswordPage';
import { ResetPasswordPage } from '../ResetPasswordPage';

const TOKEN_KEY = 'videoresearchpro.authToken';

function axiosError(status: number, detail: unknown) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail } },
  });
}

let host: HTMLDivElement;
let root: Root;

function Where() {
  const loc = useLocation();
  return <output data-where>{loc.pathname + loc.search}</output>;
}

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

function mount(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route element={<PublicOnlyRoute />}>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/login/oauth/:provider/callback" element={<OAuthCallbackPage />} />
              </Route>
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              <Route path="/reset-password" element={<ResetPasswordPage />} />
              <Route path="*" element={<p>app home</p>} />
            </Routes>
            <Where />
          </MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>,
    ),
  );
}

const where = () => host.querySelector('[data-where]')!.textContent;
const inputs = () => Array.from(host.querySelectorAll('input'));
const button = (label: string) => {
  const b = Array.from(host.querySelectorAll('button')).find((x) => x.textContent?.trim() === label);
  if (!b) throw new Error(`no button "${label}" in: ${Array.from(host.querySelectorAll('button')).map((x) => x.textContent).join(' | ')}`);
  return b;
};
const hasButton = (label: string) => Array.from(host.querySelectorAll('button')).some((x) => x.textContent?.trim() === label);

async function type(el: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function submit(form: HTMLFormElement | null) {
  await act(async () => {
    form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
}

async function signInWithPassword() {
  const [email, password] = inputs();
  await type(email, 'me@x.com');
  await type(password, 'correct horse');
  await submit(host.querySelector('form'));
}

beforeEach(() => {
  localStorage.clear();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  http.get.mockReset();
  http.post.mockReset();
  http.get.mockImplementation(async (url) => {
    if (url === '/auth/oauth/providers') return { data: { providers: [] } };
    throw new Error(`unexpected GET ${url}`);
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('LoginPage', () => {
  it('asks for the code when the password step says a second factor is owed, then signs in', async () => {
    http.post.mockImplementation(async (url) => {
      if (url === '/auth/login') return { data: { requires_mfa: true, mfa_token: 'ticket-1', expires_in: 300 } };
      if (url === '/auth/login/mfa') return { data: { access_token: 'jwt.ok', token_type: 'bearer' } };
      throw new Error(url);
    });
    mount('/login');
    await flush();
    await signInWithPassword();

    expect(host.textContent).toContain('Enter the 6-digit code from your authenticator app.');
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    const code = inputs()[0];
    expect(code.getAttribute('autocomplete')).toBe('one-time-code');

    await type(code, '123 456');
    await submit(host.querySelector('form'));

    expect(http.post).toHaveBeenLastCalledWith('/auth/login/mfa', { mfa_token: 'ticket-1', code: '123456' });
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt.ok');
    expect(where()).toBe('/');
  });

  it('takes a recovery code instead', async () => {
    http.post.mockImplementation(async (url) => {
      if (url === '/auth/login') return { data: { requires_mfa: true, mfa_token: 'ticket-2' } };
      return { data: { access_token: 'jwt.recovered' } };
    });
    mount('/login');
    await flush();
    await signInWithPassword();
    await act(async () => button('Use a recovery code instead').click());
    expect(host.textContent).toContain('Enter one of the recovery codes');
    await type(inputs()[0], '3f9a1c0b7d');
    await submit(host.querySelector('form'));
    expect(http.post).toHaveBeenLastCalledWith('/auth/login/mfa', { mfa_token: 'ticket-2', code: '3f9a1c0b7d' });
  });

  it('says so when the code is wrong, and stays on the code step', async () => {
    http.post.mockImplementation(async (url) => {
      if (url === '/auth/login') return { data: { requires_mfa: true, mfa_token: 'ticket-3' } };
      throw axiosError(401, 'Invalid TOTP or recovery code');
    });
    mount('/login');
    await flush();
    await signInWithPassword();
    await type(inputs()[0], '000000');
    await submit(host.querySelector('form'));
    expect(host.querySelector('[role="alert"]')!.textContent).toContain('That code did not work');
    expect(hasButton('Verify and sign in')).toBe(true);
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it('offers to start over when the five-minute step expired', async () => {
    http.post.mockImplementation(async (url) => {
      if (url === '/auth/login') return { data: { requires_mfa: true, mfa_token: 'ticket-4' } };
      throw axiosError(401, 'Invalid or expired MFA session');
    });
    mount('/login');
    await flush();
    await signInWithPassword();
    await type(inputs()[0], '123456');
    await submit(host.querySelector('form'));
    expect(host.textContent).toContain('This sign-in timed out');
    await act(async () => button('Start over').click());
    expect(host.textContent).toContain('Welcome back to your library.');
  });

  it('sends the reader back to the first step when the ticket has taken too many codes', async () => {
    http.post.mockImplementation(async (url) => {
      if (url === '/auth/login') return { data: { requires_mfa: true, mfa_token: 'ticket-5' } };
      throw axiosError(401, 'Too many codes tried for this sign-in. Start over and sign in again.');
    });
    mount('/login');
    await flush();
    await signInWithPassword();
    await type(inputs()[0], '123456');
    await submit(host.querySelector('form'));
    expect(host.textContent).toContain('Too many codes tried. Start over and enter your password again.');
    expect(inputs()[0].disabled, 'the dead ticket takes no more codes').toBe(true);
    expect(hasButton('Verify and sign in')).toBe(false);
    await act(async () => button('Start over').click());
    expect(host.textContent).toContain('Welcome back to your library.');
  });

  it('shows the cause when the code cannot be checked at all', async () => {
    const detail = "The authenticator code cannot be checked (a recovery code still works): this install's BYOK_ENCRYPTION_KEY is set but is not a valid key. Ask the operator to fix it.";
    http.post.mockImplementation(async (url) => {
      if (url === '/auth/login') return { data: { requires_mfa: true, mfa_token: 'ticket-6' } };
      throw axiosError(503, detail);
    });
    mount('/login');
    await flush();
    await signInWithPassword();
    await type(inputs()[0], '123456');
    await submit(host.querySelector('form'));
    expect(host.textContent).toContain(detail);
    expect(hasButton('Verify and sign in'), 'a recovery code still works, so the step stays open').toBe(true);
  });

  it('shows OAuth buttons only for the providers the server names', async () => {
    mount('/login');
    await flush();
    expect(hasButton('Continue with Google')).toBe(false);
    expect(hasButton('Continue with GitHub')).toBe(false);

    act(() => root.unmount());
    root = createRoot(host);
    http.get.mockImplementation(async (url) => {
      if (url === '/auth/oauth/providers') return { data: { providers: ['github'] } };
      throw new Error(url);
    });
    mount('/login');
    await flush();
    expect(hasButton('Continue with GitHub')).toBe(true);
    expect(hasButton('Continue with Google')).toBe(false);
  });

  it('starts an OAuth sign-in with this app as the return address', async () => {
    const assign = vi.fn();
    const original = window.location;
    Object.defineProperty(window, 'location', { configurable: true, value: { ...original, origin: 'http://localhost:5173', assign } });
    try {
      http.get.mockImplementation(async (url, _b, config) => {
        if (url === '/auth/oauth/providers') return { data: { providers: ['google'] } };
        if (url === '/auth/oauth/google/start') {
          expect(config).toEqual({ params: { redirect_uri: 'http://localhost:5173/login/oauth/google/callback' } });
          return { data: { authorize_url: 'https://accounts.google.com/o/oauth2/v2/auth?state=s' } };
        }
        throw new Error(url);
      });
      mount('/login');
      await flush();
      await act(async () => button('Continue with Google').click());
      await flush();
      expect(assign).toHaveBeenCalledWith('https://accounts.google.com/o/oauth2/v2/auth?state=s');
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original });
    }
  });

  it('links to the forgot-password page', async () => {
    mount('/login');
    await flush();
    const link = Array.from(host.querySelectorAll('a')).find((a) => a.textContent === 'Forgot your password?');
    expect(link?.getAttribute('href')).toBe('/forgot-password');
  });
});

describe('OAuthCallbackPage', () => {
  it('exchanges the code and state once, drops them from the address, and signs in', async () => {
    http.get.mockImplementation(async (url) => {
      if (url === '/auth/oauth/google/callback') return { data: { access_token: 'jwt.google' } };
      if (url === '/auth/me') return { data: { id: 'u1', email: 'g@x.com', tier: 'free' } };
      throw new Error(url);
    });
    mount('/login/oauth/google/callback?code=abc&state=xyz');
    await flush();
    const exchanges = http.get.mock.calls.filter((c) => c[0] === '/auth/oauth/google/callback');
    expect(exchanges).toHaveLength(1);
    expect(exchanges[0][2]).toEqual({ params: { code: 'abc', state: 'xyz' } });
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt.google');
    expect(where()).toBe('/');
  });

  it('asks for the second factor when the account has one', async () => {
    http.get.mockImplementation(async (url) => {
      if (url === '/auth/oauth/github/callback') return { data: { requires_mfa: true, mfa_token: 'ticket-o' } };
      throw new Error(url);
    });
    http.post.mockResolvedValue({ data: { access_token: 'jwt.github.mfa' } });
    mount('/login/oauth/github/callback?code=abc&state=xyz');
    await flush();
    expect(where()).toBe('/login/oauth/github/callback');
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    await type(inputs()[0], '654321');
    await submit(host.querySelector('form'));
    expect(http.post).toHaveBeenCalledWith('/auth/login/mfa', { mfa_token: 'ticket-o', code: '654321' });
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt.github.mfa');
  });

  it('shows the server reason for a refused sign-in', async () => {
    http.get.mockRejectedValue(axiosError(403, 'Google has not verified this email address.'));
    mount('/login/oauth/google/callback?code=abc&state=xyz');
    await flush();
    expect(host.querySelector('[role="alert"]')!.textContent).toBe('Google has not verified this email address.');
  });

  it('calls nothing when the reader cancelled at the provider', async () => {
    mount('/login/oauth/google/callback?error=access_denied');
    await flush();
    expect(http.get).not.toHaveBeenCalled();
    expect(host.textContent).toContain('You cancelled at Google');
  });
});

describe('ForgotPasswordPage', () => {
  it('sends the address and shows only its own message, never the response', async () => {
    http.post.mockResolvedValue({ data: { message: 'If that email is registered…', debug_secret: 'LEAKED-SECRET-123' } });
    mount('/forgot-password');
    await type(inputs()[0], 'me@x.com');
    await submit(host.querySelector('form'));
    expect(http.post).toHaveBeenCalledWith('/auth/password-reset/request', { email: 'me@x.com' });
    expect(host.querySelector('[role="status"]')!.textContent).toContain('If an account uses me@x.com, a reset code is on its way.');
    expect(document.body.innerHTML).not.toContain('LEAKED-SECRET-123');
    const next = Array.from(host.querySelectorAll('a')).find((a) => a.textContent === 'I have a code');
    expect(next?.getAttribute('href')).toBe('/reset-password');
  });

  it('says when the request could not be sent', async () => {
    http.post.mockRejectedValue(axiosError(429, 'Too many requests'));
    mount('/forgot-password');
    await type(inputs()[0], 'me@x.com');
    await submit(host.querySelector('form'));
    expect(host.querySelector('[role="alert"]')!.textContent).toBe('Too many requests');
  });
});

describe('ResetPasswordPage', () => {
  async function fill(code: string, pw: string, confirm: string) {
    const [c, p, k] = inputs();
    await type(c, code);
    await type(p, pw);
    await type(k, confirm);
    await submit(host.querySelector('form'));
  }

  it('sends the pasted code and the new password', async () => {
    http.post.mockResolvedValue({ data: { message: 'ok' } });
    mount('/reset-password');
    await fill('  the-reset-code-123  ', 'new password 1', 'new password 1');
    expect(http.post).toHaveBeenCalledWith('/auth/password-reset/confirm', { token: 'the-reset-code-123', new_password: 'new password 1' });
    expect(host.textContent).toContain('Your new password works now.');
  });

  it('checks the two passwords match before sending', async () => {
    mount('/reset-password');
    await fill('the-reset-code-123', 'new password 1', 'new password 2');
    expect(http.post).not.toHaveBeenCalled();
    expect(host.querySelector('[role="alert"]')!.textContent).toBe('Passwords do not match.');
  });

  it('says a used or expired code is no good', async () => {
    http.post.mockRejectedValue(axiosError(400, 'Invalid or expired token'));
    mount('/reset-password');
    await fill('the-reset-code-123', 'new password 1', 'new password 1');
    expect(host.querySelector('[role="alert"]')!.textContent).toContain('That code is not valid any more');
  });

  it('shows the server\'s sentence for a password it refused, because the code is still good (T-5.4.18)', async () => {
    const detail = 'The new password has a character that cannot be stored: a null character or broken Unicode.';
    http.post.mockRejectedValue(axiosError(400, detail));
    mount('/reset-password');
    await fill('the-reset-code-123', 'new password 1', 'new password 1');
    expect(host.querySelector('[role="alert"]')!.textContent).toBe(detail);
  });

  it('never reads the code from the address bar', async () => {
    mount('/reset-password?token=from-the-url');
    expect(inputs()[0].value).toBe('');
  });
});

describe('routes', () => {
  function find(routes: RouteObject[], pred: (r: RouteObject) => boolean): RouteObject | undefined {
    for (const r of routes) {
      if (pred(r)) return r;
      const hit = r.children ? find(r.children, pred) : undefined;
      if (hit) return hit;
    }
    return undefined;
  }

  it('mounts the sign-in pages the app links to', async () => {
    const { router } = await import('../../routes');
    const { AccountSecurityPage } = await import('../AccountSecurityPage');
    const el = (path: string) => (find(router.routes, (r) => r.path === path)?.element as { type?: unknown } | undefined)?.type;
    expect(el('/forgot-password')).toBe(ForgotPasswordPage);
    expect(el('/reset-password')).toBe(ResetPasswordPage);
    expect(el('/login/oauth/:provider/callback')).toBe(OAuthCallbackPage);
    expect(el('account/security')).toBe(AccountSecurityPage);
  }, 60_000); // the route table imports every page
});
