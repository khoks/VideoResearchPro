/**
 * T-5.4.22, at the client: what a 401 does to the session. The real interceptor
 * runs here, with only axios's transport replaced. `routes/__tests__/
 * sessionExpiry.test.tsx` takes it from there to the page, and `tests/shell.spec.ts`
 * does the same in a real browser.
 *
 * Mutation checks, run by hand on 2026-11-05: taking `/auth/logout` out of
 * `OWN_ANSWER` fails "leaves a sign-out to the sign-out"; taking `login` out fails
 * "a wrong password"; dropping the token comparison in `sessionRefused` fails "a
 * late refusal"; a `window.location` write in the interceptor fails "moves nothing";
 * saying a token is gone only of a bare request fails "gone from storage since".
 */
import { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import api, { AUTH_TOKEN_KEY } from '../api';
import { onSessionExpired, onSessionLost, sessionRefused } from '../sessionExpiry';

const expired = vi.fn();
const lost = vi.fn();
let stop: () => void;
let stopLost: () => void;
let seen: InternalAxiosRequestConfig[] = [];

function answering(status: number, then: () => void = () => undefined): AxiosAdapter {
  return async (config) => {
    seen.push(config);
    then();
    const response = { status, statusText: '', data: { detail: 'no' }, headers: {}, config };
    if (status < 400) return response;
    throw new AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_REQUEST', config, null, response);
  };
}

async function refused(call: Promise<unknown>) {
  await expect(call).rejects.toMatchObject({ response: { status: expect.any(Number) } });
}

beforeEach(() => {
  localStorage.clear();
  seen = [];
  expired.mockReset();
  lost.mockReset();
  stop = onSessionExpired(expired);
  stopLost = onSessionLost(lost);
});

afterEach(() => {
  stop();
  stopLost();
  api.defaults.adapter = undefined;
});

describe('a 401 with the current token', () => {
  beforeEach(() => localStorage.setItem(AUTH_TOKEN_KEY, 'jwt.live'));

  it('ends the session once, and the caller still hears of it', async () => {
    api.defaults.adapter = answering(401);
    await refused(api.get('/jobs/run-1'));
    expect(seen[0].headers.Authorization).toBe('Bearer jwt.live');
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    expect(expired).toHaveBeenCalledTimes(1);
    expect(lost).not.toHaveBeenCalled();
  });

  it('counts once when a page has several requests out', async () => {
    api.defaults.adapter = answering(401);
    await Promise.all([refused(api.get('/jobs/run-1')), refused(api.get('/shelves')), refused(api.get('/auth/me'))]);
    expect(expired).toHaveBeenCalledTimes(1);
  });

  it('moves nothing itself: the route guard does that, with the page', async () => {
    const original = window.location;
    const address = { href: 'http://localhost/jobs/run-1', pathname: '/jobs/run-1', assign: vi.fn(), replace: vi.fn() };
    Object.defineProperty(window, 'location', { configurable: true, value: address });
    try {
      api.defaults.adapter = answering(401);
      await refused(api.get('/jobs/run-1'));
      expect(address.href).toBe('http://localhost/jobs/run-1');
      expect(address.assign).not.toHaveBeenCalled();
      expect(address.replace).not.toHaveBeenCalled();
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original });
    }
  });
});

describe('a 401 that says nothing about the session', () => {
  beforeEach(() => localStorage.setItem(AUTH_TOKEN_KEY, 'jwt.live'));

  it.each([
    ['a wrong password', '/auth/login'],
    ['a wrong code', '/auth/login/mfa'],
    ['a refused OAuth sign-in', '/auth/oauth/google/callback'],
    ['a sign-up', '/auth/register'],
    ['a password reset', '/auth/password-reset/confirm'],
  ])('%s is the page’s to show', async (_name, url) => {
    api.defaults.adapter = answering(401);
    await refused(api.post(url, {}));
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBe('jwt.live');
    expect(expired).not.toHaveBeenCalled();
    expect(lost).not.toHaveBeenCalled();
  });

  it('a wrong password with nothing in storage is still only the page’s to show', async () => {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    api.defaults.adapter = answering(401);
    await refused(api.post('/auth/login', {}));
    expect(lost).not.toHaveBeenCalled();
  });

  it('leaves a sign-out to the sign-out, which leaves no page (D-140)', async () => {
    api.defaults.adapter = answering(401);
    await refused(api.post('/auth/logout'));
    expect(expired).not.toHaveBeenCalled();
    expect(lost).not.toHaveBeenCalled();
  });

  it('a late refusal of the last token leaves a new sign-in alone', async () => {
    api.defaults.adapter = answering(401, () => localStorage.setItem(AUTH_TOKEN_KEY, 'jwt.new'));
    await refused(api.get('/jobs/run-1'));
    expect(seen[0].headers.Authorization).toBe('Bearer jwt.live');
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBe('jwt.new');
    expect(expired).not.toHaveBeenCalled();
    expect(lost).not.toHaveBeenCalled();
  });

  it('a request sent bare that lands after a sign-in leaves that sign-in alone', async () => {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    api.defaults.adapter = answering(401, () => localStorage.setItem(AUTH_TOKEN_KEY, 'jwt.new'));
    await refused(api.get('/library/videos'));
    expect(seen[0].headers.Authorization).toBeUndefined();
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBe('jwt.new');
    expect(expired).not.toHaveBeenCalled();
    expect(lost).not.toHaveBeenCalled();
  });

  it.each([403, 404, 429, 500])('a %i is not a 401', async (status) => {
    api.defaults.adapter = answering(status);
    await refused(api.get('/jobs/run-1'));
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBe('jwt.live');
    expect(expired).not.toHaveBeenCalled();
  });
});

describe('a 401 with no token in storage', () => {
  // Either this tab ended the session already, or the token went with nobody here
  // hearing: `AuthProvider` knows which, and `routes/__tests__/sessionExpiry.test.tsx`
  // has what it does.
  it('says the token is gone, and not that this request expired it', async () => {
    api.defaults.adapter = answering(401);
    await refused(api.get('/library/videos'));
    expect(seen[0].headers.Authorization).toBeUndefined();
    expect(expired).not.toHaveBeenCalled();
    expect(lost).toHaveBeenCalledTimes(1);
  });

  it('says the same of a request that carried a token, gone from storage since', () => {
    sessionRefused('jwt.live');
    expect(expired).not.toHaveBeenCalled();
    expect(lost).toHaveBeenCalledTimes(1);
  });
});

describe('sessionRefused', () => {
  it('takes a token that is no longer the current one for nothing', () => {
    localStorage.setItem(AUTH_TOKEN_KEY, 'jwt.new');
    sessionRefused('jwt.old');
    sessionRefused(null);
    sessionRefused(undefined);
    expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBe('jwt.new');
    expect(expired).not.toHaveBeenCalled();
    expect(lost).not.toHaveBeenCalled();
  });

  it('stops telling a listener that has gone', () => {
    localStorage.setItem(AUTH_TOKEN_KEY, 'jwt.live');
    stop();
    sessionRefused('jwt.live');
    expect(expired).not.toHaveBeenCalled();
    stopLost();
    sessionRefused(null);
    expect(lost).not.toHaveBeenCalled();
  });
});
