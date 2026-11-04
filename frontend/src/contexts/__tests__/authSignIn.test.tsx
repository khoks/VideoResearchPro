/**
 * Sign-in and sign-out in the auth context (E-5.4 UI): a first step that owes
 * a second factor stores nothing; the second step and an OAuth return store
 * the session; sign-out revokes the session at the server before forgetting
 * it here, and still forgets it when that call fails.
 */
import { act, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, LOGOUT_REVOKE_TIMEOUT_MS, useAuth, type SignInResult } from '../AuthContext';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const TOKEN_KEY = 'videoresearchpro.authToken';
const USER_KEY = 'videoresearchpro.authUser';

const postMock = vi.fn();
const getMock = vi.fn();
vi.mock('../../services/api', () => ({
  default: {
    post: (...a: unknown[]) => postMock(...a),
    get: (...a: unknown[]) => getMock(...a),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  AUTH_TOKEN_KEY: 'videoresearchpro.authToken',
}));

let host: HTMLDivElement;
let root: Root;
let ctx: ReturnType<typeof useAuth>;

function Probe() {
  const value = useAuth();
  useEffect(() => {
    ctx = value;
  });
  return <output data-auth>{String(value.isAuthenticated)}</output>;
}

async function run<T>(fn: () => Promise<T>): Promise<T> {
  let out!: T;
  await act(async () => {
    out = await fn();
  });
  return out;
}

const authed = () => host.querySelector('[data-auth]')!.textContent;

beforeEach(() => {
  localStorage.clear();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<AuthProvider><Probe /></AuthProvider>));
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  postMock.mockReset();
  getMock.mockReset();
});

describe('login with two-step verification', () => {
  it('returns the ticket and stores no session until the code is in', async () => {
    postMock.mockResolvedValueOnce({ data: { requires_mfa: true, mfa_token: 'ticket-1', expires_in: 300 } });
    const result = await run(() => ctx.login('me@x.com', 'pw'));
    expect(result).toEqual<SignInResult>({ status: 'mfa_required', mfaToken: 'ticket-1', expiresIn: 300 });
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(authed()).toBe('false');

    postMock.mockResolvedValueOnce({ data: { access_token: 'jwt.after.mfa', token_type: 'bearer' } });
    await run(() => ctx.completeMfa('ticket-1', ' 123456 ', 'me@x.com'));
    expect(postMock).toHaveBeenLastCalledWith('/auth/login/mfa', { mfa_token: 'ticket-1', code: '123456' });
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt.after.mfa');
    expect(JSON.parse(localStorage.getItem(USER_KEY)!).email).toBe('me@x.com');
    expect(authed()).toBe('true');
  });

  it('signs straight in when the account has no second factor', async () => {
    postMock.mockResolvedValueOnce({ data: { access_token: 'jwt.plain' } });
    const result = await run(() => ctx.login('me@x.com', 'pw'));
    expect(result).toEqual({ status: 'signed_in' });
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt.plain');
  });

  it('keeps nothing when the second step fails', async () => {
    postMock.mockRejectedValueOnce({ response: { status: 401, data: { detail: 'Invalid TOTP or recovery code' } } });
    await expect(run(() => ctx.completeMfa('ticket-1', '000000'))).rejects.toBeTruthy();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });
});

describe('completeOAuth', () => {
  it('exchanges the code and state, then asks the server who signed in', async () => {
    getMock
      .mockResolvedValueOnce({ data: { access_token: 'jwt.oauth' } })
      .mockResolvedValueOnce({ data: { id: 'u1', email: 'oauth@x.com', tier: 'free' } });
    const result = await run(() => ctx.completeOAuth('google', 'the-code', 'the-state'));
    expect(result).toEqual({ status: 'signed_in' });
    expect(getMock.mock.calls[0]).toEqual(['/auth/oauth/google/callback', { params: { code: 'the-code', state: 'the-state' } }]);
    expect(getMock.mock.calls[1][0]).toBe('/auth/me');
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt.oauth');
    expect(JSON.parse(localStorage.getItem(USER_KEY)!).email).toBe('oauth@x.com');
  });

  it('owes the second factor like a password sign-in', async () => {
    getMock.mockResolvedValueOnce({ data: { requires_mfa: true, mfa_token: 'ticket-o' } });
    const result = await run(() => ctx.completeOAuth('github', 'c', 's'));
    expect(result).toEqual({ status: 'mfa_required', mfaToken: 'ticket-o', expiresIn: 300 });
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });
});

describe('logout', () => {
  beforeEach(async () => {
    postMock.mockResolvedValueOnce({ data: { access_token: 'jwt.session' } });
    await run(() => ctx.login('me@x.com', 'pw'));
    postMock.mockReset();
  });

  it('revokes the session at the server before clearing it here', async () => {
    let tokenAtCall: string | null = 'unset';
    postMock.mockImplementationOnce(async () => {
      tokenAtCall = localStorage.getItem(TOKEN_KEY);
      return { data: { revoked: true } };
    });
    await run(() => ctx.logout());
    expect(postMock).toHaveBeenCalledWith('/auth/logout', null, { timeout: LOGOUT_REVOKE_TIMEOUT_MS });
    expect(tokenAtCall).toBe('jwt.session');
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(USER_KEY)).toBeNull();
    expect(authed()).toBe('false');
  });

  it('still signs this browser out when the call fails', async () => {
    postMock.mockRejectedValueOnce(new Error('Network Error'));
    await run(() => ctx.logout());
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(authed()).toBe('false');
  });

  it('signs this browser out when the call never settles', async () => {
    // A stalled backend: the request neither answers nor fails. The mock
    // ignores axios's own timeout, as a hung transport would.
    vi.useFakeTimers();
    try {
      postMock.mockImplementationOnce(() => new Promise(() => {}));
      let done = false;
      await act(async () => {
        void ctx.logout().then(() => {
          done = true;
        });
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(LOGOUT_REVOKE_TIMEOUT_MS - 1);
      });
      expect(done).toBe(false);
      expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt.session');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(done).toBe(true);
      expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
      expect(localStorage.getItem(USER_KEY)).toBeNull();
      expect(authed()).toBe('false');
    } finally {
      vi.useRealTimers();
    }
  });
});
