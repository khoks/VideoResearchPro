/**
 * T-5.4.22: the global toast says nothing about a 401. The reader is on the way to
 * the sign-in page, and a request still out when the session ended lands there
 * after everything else has been cleared. Other refusals keep their words.
 * Mutation check, run by hand on 2026-11-05: `isSessionEnded` out of
 * `globalErrorToastMessage` fails "a 401".
 */
import { AxiosError, AxiosHeaders } from 'axios';
import { describe, expect, it } from 'vitest';
import { globalErrorToastMessage, isSessionEnded } from '../apiError';

function refused(status: number, detail: unknown = 'The server’s words.') {
  const headers = new AxiosHeaders();
  return new AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_REQUEST', undefined, undefined, {
    status, statusText: '', headers, config: { headers }, data: { detail },
  });
}

describe('globalErrorToastMessage', () => {
  it('says nothing about a 401', () => {
    expect(globalErrorToastMessage(refused(401, 'Could not validate credentials'))).toBeNull();
  });

  it.each([400, 403, 404, 409, 429, 500])('keeps the server’s words for a %i', (status) => {
    expect(globalErrorToastMessage(refused(status))).toBe('The server’s words.');
  });

  it('keeps the error’s own text when nothing answered', () => {
    expect(globalErrorToastMessage(new Error('Network Error'))).toBe('Network Error');
  });
});

describe('isSessionEnded', () => {
  it('is a 401 from the server, and nothing else', () => {
    expect(isSessionEnded(refused(401))).toBe(true);
    expect(isSessionEnded(refused(403))).toBe(false);
    expect(isSessionEnded(new Error('401'))).toBe(false);
    expect(isSessionEnded(null)).toBe(false);
  });
});
