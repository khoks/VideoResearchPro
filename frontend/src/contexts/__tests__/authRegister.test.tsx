/**
 * Registration signs the new account in. `/auth/register` returns the user,
 * not a token, so the context must follow it with `/auth/login`; before
 * this, a fresh account was stored with no token and bounced to /login.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from '../AuthContext';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const postMock = vi.fn();
vi.mock('../../services/api', () => ({
  default: { post: (...a: unknown[]) => postMock(...a), interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  AUTH_TOKEN_KEY: 'videoresearchpro.authToken',
}));

let host: HTMLDivElement;
let root: Root;

/** Registers on click and renders whether the context is signed in. */
function Probe() {
  const { register, isAuthenticated } = useAuth();
  return (
    <>
      <button onClick={() => void register('new@example.com', 'longenough1')}>register</button>
      <output data-auth>{String(isAuthenticated)}</output>
    </>
  );
}

async function registerOnce() {
  await act(async () => {
    host.querySelector('button')!.click();
  });
  for (let i = 0; i < 3; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

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
});

describe('AuthContext.register', () => {
  it('signs in after registering when the response carries no token', async () => {
    postMock
      .mockResolvedValueOnce({ data: { id: 'u1', email: 'new@example.com', tier: 'free' } })
      .mockResolvedValueOnce({ data: { access_token: 'jwt.from.login', token_type: 'bearer' } });
    await registerOnce();
    expect(postMock.mock.calls.map((c) => c[0])).toEqual(['/auth/register', '/auth/login']);
    expect(localStorage.getItem('videoresearchpro.authToken')).toBe('jwt.from.login');
    expect(host.querySelector('[data-auth]')!.textContent).toBe('true');
  });

  it('uses a token the register response does carry', async () => {
    postMock.mockResolvedValueOnce({ data: { access_token: 'jwt.from.register' } });
    await registerOnce();
    expect(postMock).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('videoresearchpro.authToken')).toBe('jwt.from.register');
  });
});
