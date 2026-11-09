/**
 * T-5.4.22: the global toast says nothing about a 401. The reader is on the way to
 * the sign-in page, and a request still out when the session ended lands there
 * after everything else has been cleared. Other refusals keep their words.
 * Mutation check, run by hand on 2026-11-05: `isSessionEnded` out of
 * `globalErrorToastMessage` fails "a 401".
 */
import { AxiosError, AxiosHeaders } from 'axios';
import { describe, expect, it } from 'vitest';
import { FormValidationError, globalErrorToastMessage, inlineErrorMessage, isSessionEnded } from '../apiError';

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

/**
 * T-3.4.1.25: a line on the page shows words written for the reader, and no
 * others. The server's `detail` and a `FormValidationError` qualify; any other
 * exception's text never does, whatever it holds. Mutation checks, run on
 * 2026-11-09: dropping the `FormValidationError` branch fails "a form's own
 * validation"; returning `err.message` for any `Error` fails "never an
 * arbitrary exception's text".
 */
describe('inlineErrorMessage', () => {
  it('says the server’s words, else the fallback, and nothing for a 401', () => {
    expect(inlineErrorMessage(refused(409), 'Our sentence.')).toBe('The server’s words.');
    expect(inlineErrorMessage(new AxiosError('Network Error', 'ERR_NETWORK'), 'Our sentence.')).toBe('Our sentence.');
    expect(inlineErrorMessage(refused(401, 'Not authenticated'), 'Our sentence.')).toBeNull();
  });

  it('says a form’s own validation as written', () => {
    expect(inlineErrorMessage(new FormValidationError('Choose at least one source to search.'), 'Our sentence.')).toBe(
      'Choose at least one source to search.',
    );
  });

  it('never an arbitrary exception’s text', () => {
    expect(inlineErrorMessage(new Error('TypeError at chunk-3f9a.js:12 token=abc'), 'Our sentence.')).toBe('Our sentence.');
    expect(inlineErrorMessage(new TypeError('Cannot read properties of undefined'), 'Our sentence.')).toBe('Our sentence.');
    expect(inlineErrorMessage('a string thrown', 'Our sentence.')).toBe('Our sentence.');
    expect(inlineErrorMessage(null, 'Our sentence.')).toBe('Our sentence.');
  });
});
