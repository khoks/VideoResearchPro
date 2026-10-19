import { describe, expect, it } from 'vitest';
import { outputSizeLabel, parseCreateIntent } from '../authorOutputs';

describe('parseCreateIntent', () => {
  it('opens a book with the linked run pre-selected', () => {
    expect(parseCreateIntent(new URLSearchParams('new=book&job=abc'))).toEqual({ kind: 'book', jobIds: ['abc'] });
  });

  it('dedupes and trims repeated job params', () => {
    const p = new URLSearchParams('new=Book&job=a&job=%20a%20&job=b&job=');
    expect(parseCreateIntent(p)).toEqual({ kind: 'book', jobIds: ['a', 'b'] });
  });

  it('ignores runs for kinds that do not take runs', () => {
    expect(parseCreateIntent(new URLSearchParams('new=deck&job=abc'))).toEqual({ kind: 'deck', jobIds: [] });
  });

  it('returns null for no intent or an unknown kind', () => {
    expect(parseCreateIntent(new URLSearchParams(''))).toBeNull();
    expect(parseCreateIntent(new URLSearchParams('job=abc'))).toBeNull();
    expect(parseCreateIntent(new URLSearchParams('new=podcast&job=abc'))).toBeNull();
  });
});

describe('outputSizeLabel', () => {
  it('counts chapters and words for a book', () => {
    expect(outputSizeLabel({ kind: 'book', source_ids: ['a', 'b', 'c'], word_count: 12345 })).toBe('3 chapters · 12,345 words');
    expect(outputSizeLabel({ kind: 'book', source_ids: ['a'], word_count: 1 })).toBe('1 chapter · 1 word');
  });

  it('omits words until the backend has counted them', () => {
    expect(outputSizeLabel({ kind: 'book', source_ids: ['a'], word_count: null })).toBe('1 chapter');
    expect(outputSizeLabel({ kind: 'book', source_ids: ['a'] })).toBe('1 chapter');
  });

  it('says sources for other kinds', () => {
    expect(outputSizeLabel({ kind: 'deck', source_ids: ['a', 'b'], word_count: 0 })).toBe('2 sources · 0 words');
  });
});
