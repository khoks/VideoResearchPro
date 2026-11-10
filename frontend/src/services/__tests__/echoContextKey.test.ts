/**
 * S-3.1.1 / T-3.1.1.1: a fact whose label holds `/`. The delete route reads
 * the key as the rest of its path (`{key:path}`), so the form takes such a
 * label, and `echoApi.deleteContext` sends the key encoded whole: `/` as `%2F`,
 * `%` as `%25`, so the server's one decode gives the key back as written.
 *
 * Mutation checks, run on 2026-11-10: the old `if (k.includes('/'))` refusal
 * put back fails each "takes a label holding a slash" row; `deleteContext`
 * building the path with the key unencoded fails each URL row but `cooking`.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const deleteMock = vi.fn<(path: string) => Promise<{ data: { deleted: boolean } }>>(async () => ({
  data: { deleted: true },
}));
vi.mock('../api', () => ({
  default: { delete: (path: string) => deleteMock(path) },
}));

import { echoApi } from '../echoApi';
import { validateContextKey } from '../../utils/echoReadiness';

beforeEach(() => deleteMock.mockClear());

describe('validateContextKey', () => {
  it.each(['TCP/IP', 'work/2026/q4', '/etc', 'reading list/', '/'])('takes a label holding a slash: %s', (label) => {
    expect(validateContextKey(label)).toBeNull();
  });

  it('keeps the API limits', () => {
    expect(validateContextKey('   ')).toBe('Give this entry a short label.');
    expect(validateContextKey('a'.repeat(129))).toBe('Keep the label under 128 characters.');
    expect(validateContextKey('a'.repeat(128))).toBeNull();
  });
});

describe('echoApi.deleteContext', () => {
  it.each([
    ['TCP/IP', '/echo/context/interest/TCP%2FIP'],
    ['/', '/echo/context/interest/%2F'],
    ['a/b/c/', '/echo/context/interest/a%2Fb%2Fc%2F'],
    ['100%2F', '/echo/context/interest/100%252F'],
    ['what? #2', '/echo/context/interest/what%3F%20%232'],
    ['cooking', '/echo/context/interest/cooking'],
  ])('sends %s encoded whole', async (key, path) => {
    await expect(echoApi.deleteContext('interest', key)).resolves.toEqual({ deleted: true });
    expect(deleteMock).toHaveBeenCalledWith(path);
  });
});
