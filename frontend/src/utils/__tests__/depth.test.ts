/**
 * R4: the depth a reader picks for one ask or one knowledge report reaches the
 * request only when picked. With none, the request is byte-for-byte the one
 * sent before the control existed, so the server's default stands (the job's
 * depth, the corpus size, or a knowledge report's size-based budget).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { depthOf, withDepth } from '../depth';

const postMock = vi.fn();
vi.mock('../../services/api', () => ({
  default: { post: (...args: unknown[]) => postMock(...args), get: vi.fn() },
}));

import { knowledgeApi } from '../../services/knowledgeApi';

describe('depthOf', () => {
  it('reads the three explicit depths and nothing else', () => {
    expect(depthOf('brief')).toBe('brief');
    expect(depthOf('standard')).toBe('standard');
    expect(depthOf('deep')).toBe('deep');
    // 'auto' is "no preference", as the server normalises it.
    for (const none of ['auto', '', null, undefined, 'enormous', 'DEEP']) expect(depthOf(none)).toBeNull();
  });
});

describe('withDepth', () => {
  it('adds output_length only when a depth was chosen', () => {
    const body = { question: 'Why?', answer_language: 'en' };
    expect(withDepth(body, null)).toBe(body);
    expect('output_length' in withDepth(body, null)).toBe(false);
    expect(withDepth(body, 'deep')).toEqual({ ...body, output_length: 'deep' });
    expect(body).toEqual({ question: 'Why?', answer_language: 'en' }); // not mutated
  });
});

describe('knowledgeApi.extract (S-1.15.3)', () => {
  beforeEach(() => {
    postMock.mockReset();
    postMock.mockResolvedValue({ data: {} });
  });

  it('sends output_length as a query parameter only when a depth was chosen', async () => {
    await knowledgeApi.extract('doc-1');
    expect(postMock).toHaveBeenLastCalledWith('/videos/doc-1/extract-knowledge', null, { params: undefined });

    await knowledgeApi.extract('doc-1', true);
    expect(postMock).toHaveBeenLastCalledWith('/videos/doc-1/extract-knowledge', null, { params: { force: true } });

    await knowledgeApi.extract('doc-1', false, 'brief');
    expect(postMock).toHaveBeenLastCalledWith('/videos/doc-1/extract-knowledge', null, {
      params: { output_length: 'brief' },
    });

    await knowledgeApi.extract('doc-1', true, 'deep');
    expect(postMock).toHaveBeenLastCalledWith('/videos/doc-1/extract-knowledge', null, {
      params: { force: true, output_length: 'deep' },
    });
  });
});
