/**
 * T-3.7.6.1: a share waiting on this device carries no owner, so signing out
 * has to take it away, or the next person to sign in on this browser is
 * offered it. Asserted at the auth context, the one place every sign-out runs,
 * with the Cache API faked.
 */
import { act, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from '../AuthContext';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const postMock = vi.fn();
vi.mock('../../services/api', () => ({
  default: {
    post: (...a: unknown[]) => postMock(...a),
    get: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  AUTH_TOKEN_KEY: 'videoresearchpro.authToken',
}));

let host: HTMLDivElement;
let root: Root;
let ctx: ReturnType<typeof useAuth>;
const cacheDelete = vi.fn();

function Probe() {
  const value = useAuth();
  useEffect(() => {
    ctx = value;
  });
  return null;
}

beforeEach(() => {
  cacheDelete.mockReset().mockResolvedValue(true);
  vi.stubGlobal('caches', { delete: cacheDelete });
  localStorage.clear();
  localStorage.setItem('videoresearchpro.authToken', 'token-a');
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<AuthProvider><Probe /></AuthProvider>));
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  postMock.mockReset();
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe('a waiting share and a sign-out', () => {
  it('goes with the session', async () => {
    postMock.mockResolvedValueOnce({});
    await act(async () => {
      await ctx.logout();
    });
    expect(cacheDelete).toHaveBeenCalledWith('echo-pending-shares-v1');
  });

  it('goes even when the server could not be told', async () => {
    postMock.mockRejectedValueOnce(new Error('offline'));
    await act(async () => {
      await ctx.logout();
    });
    expect(cacheDelete).toHaveBeenCalledTimes(1);
  });

  it('does not hold up a sign-out when the Cache API fails', async () => {
    cacheDelete.mockRejectedValue(new Error('storage is gone'));
    postMock.mockResolvedValueOnce({});
    await act(async () => {
      await ctx.logout();
    });
    expect(ctx.isAuthenticated).toBe(false);
  });
});
