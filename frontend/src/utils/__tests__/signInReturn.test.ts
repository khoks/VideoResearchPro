/**
 * T-5.4.20: the rules on the path a sign-in goes back to. The whole flow is in
 * `routes/__tests__/signInDestination.test.tsx`; these are the edges.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  forgetSignInDestination,
  recallSignInState,
  rememberSignInDestination,
  signInDestination,
} from '../signInReturn';

beforeEach(() => sessionStorage.clear());

describe('signInDestination', () => {
  it('keeps the query and fragment of a location', () => {
    expect(signInDestination({ from: { pathname: '/library/qa', search: '?exchange=1', hash: '#a' } })).toBe('/library/qa?exchange=1#a');
  });

  it('reads the path string the OAuth page hands on', () => {
    expect(signInDestination({ from: '/jobs/1?x=2' })).toBe('/jobs/1?x=2');
  });

  it.each([[null], [undefined], ['/jobs'], [{}], [{ from: null }], [{ from: 7 }], [{ from: {} }]])('falls back to / for %j', (state) => {
    expect(signInDestination(state)).toBe('/');
  });

  it.each([['https://evil.example/'], ['//evil.example/'], ['/\\evil.example/'], ['javascript:alert(1)'], ['jobs/1']])(
    'never leaves the app for %s',
    (from) => {
      expect(signInDestination({ from })).toBe('/');
      expect(signInDestination({ from: { pathname: from } })).toBe('/');
    },
  );

  it('drops a provider’s answer from a callback address', () => {
    expect(signInDestination({ from: { pathname: '/echo/connectors/github/callback', search: '?code=one-time&state=s', hash: '' } })).toBe(
      '/echo/connectors/github/callback',
    );
  });
});

describe('keeping the page across a provider', () => {
  it('survives in the tab and comes back as router state', () => {
    rememberSignInDestination({ from: { pathname: '/jobs/1', search: '?x=2', hash: '' } });
    expect(recallSignInState()).toEqual({ from: '/jobs/1?x=2' });
    forgetSignInDestination();
    expect(recallSignInState()).toBeNull();
  });

  it('replaces what an abandoned attempt left, also with nothing', () => {
    rememberSignInDestination({ from: { pathname: '/jobs/1' } });
    rememberSignInDestination(null);
    expect(recallSignInState()).toBeNull();
    rememberSignInDestination({ from: { pathname: '/' } });
    expect(sessionStorage.length).toBe(0);
  });

  it('never writes a provider’s code to storage', () => {
    rememberSignInDestination({ from: { pathname: '/echo/connectors/github/callback', search: '?code=one-time&state=s' } });
    expect(JSON.stringify({ ...sessionStorage })).not.toContain('one-time');
  });

  it('refuses a stored value that is not a path in the app', () => {
    sessionStorage.setItem('pratidhvani.signInReturn', '//evil.example/');
    expect(recallSignInState()).toBeNull();
  });

  it('carries on when storage is blocked', () => {
    const blocked = () => {
      throw new DOMException('blocked', 'SecurityError');
    };
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(blocked);
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(blocked);
    const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(blocked);
    try {
      expect(() => rememberSignInDestination({ from: { pathname: '/jobs/1' } })).not.toThrow();
      expect(recallSignInState()).toBeNull();
      expect(() => forgetSignInDestination()).not.toThrow();
    } finally {
      set.mockRestore();
      get.mockRestore();
      remove.mockRestore();
    }
  });
});
