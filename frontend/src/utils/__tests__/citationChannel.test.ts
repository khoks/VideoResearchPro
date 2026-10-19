import { describe, expect, it, vi } from 'vitest';
import { createBatchLoader } from '../batchLoader';
import { youtubeVideoId } from '../videoId';

describe('youtubeVideoId', () => {
  it('reads the id from the field or any YouTube URL shape', () => {
    expect(youtubeVideoId({ video_id: 'abc123def45' })).toBe('abc123def45');
    expect(youtubeVideoId({ youtube_link: 'https://www.youtube.com/watch?v=abc123def45&t=42' })).toBe('abc123def45');
    expect(youtubeVideoId({ video_url: 'https://youtu.be/abc123def45?t=3' })).toBe('abc123def45');
    expect(youtubeVideoId({ video_url: 'https://m.youtube.com/shorts/abc123def45' })).toBe('abc123def45');
  });

  it('is null for other sources and junk', () => {
    expect(youtubeVideoId({ video_url: 'https://www.reddit.com/r/x/comments/1' })).toBeNull();
    expect(youtubeVideoId({ video_url: 'not a url' })).toBeNull();
    expect(youtubeVideoId({})).toBeNull();
  });
});

describe('createBatchLoader', () => {
  it('folds loads in one window into one fetch and hands each key its value', async () => {
    const fetchMany = vi.fn(async (keys: string[]) => Object.fromEntries(keys.filter((k) => k !== 'b').map((k) => [k, k.toUpperCase()])));
    const load = createBatchLoader(fetchMany, { delayMs: 1 });
    const results = await Promise.all([load('a'), load('b'), load('c'), load('a')]);
    expect(fetchMany).toHaveBeenCalledTimes(1);
    expect(fetchMany.mock.calls[0][0]).toEqual(['a', 'b', 'c']);
    expect(results).toEqual(['A', null, 'C', 'A']);
  });

  it('splits big batches and turns a failed fetch into nulls', async () => {
    let calls = 0;
    const load = createBatchLoader(async (keys: string[]) => {
      calls += 1;
      if (keys.includes('bad')) throw new Error('boom');
      return Object.fromEntries(keys.map((k) => [k, k]));
    }, { delayMs: 1, maxBatch: 2 });
    const results = await Promise.all(['x', 'y', 'bad', 'z'].map(load));
    expect(calls).toBe(2);
    expect(results).toEqual(['x', 'y', null, null]);
  });
});
