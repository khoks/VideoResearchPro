import { describe, expect, it } from 'vitest';
import { classifyError, planBatch, runBatch, type BatchItem } from '../batchExtract';

const items: BatchItem[] = ['a', 'b', 'c', 'd'].map((id) => ({ id, title: id.toUpperCase() }));
const httpError = (status: number) => Object.assign(new Error(String(status)), { status });
const statusOf = (err: unknown) => (err as { status?: number }).status;

describe('planBatch', () => {
  it('never plans more than the reader has left', () => {
    expect(planBatch(items, 2).map((i) => i.id)).toEqual(['a', 'b']);
    expect(planBatch(items, 0)).toEqual([]);
    expect(planBatch(items, Infinity)).toHaveLength(4);
  });
});

describe('classifyError', () => {
  it('stops on quota, skips what cannot be extracted, counts the rest as failures', () => {
    expect(classifyError(429)).toBe('quota');
    expect(classifyError(403)).toBe('quota');
    expect(classifyError(409)).toBe('skipped');
    expect(classifyError(422)).toBe('skipped');
    expect(classifyError(404)).toBe('skipped');
    expect(classifyError(500)).toBe('failed');
    expect(classifyError(undefined)).toBe('failed');
  });
});

describe('runBatch', () => {
  it('runs one at a time and tallies outcomes', async () => {
    const seen: string[] = [];
    const result = await runBatch(
      items,
      async (id) => {
        seen.push(id);
        if (id === 'b') throw httpError(422);
        if (id === 'c') throw httpError(500);
      },
      { shouldStop: () => false, onProgress: () => {}, statusOf },
    );
    expect(seen).toEqual(['a', 'b', 'c', 'd']);
    expect(result).toMatchObject({ done: 4, made: 2, skipped: 1, failed: 1, stoppedBy: 'finished' });
  });

  it('stops at the first quota refusal', async () => {
    const result = await runBatch(
      items,
      async (id) => {
        if (id === 'b') throw httpError(429);
      },
      { shouldStop: () => false, onProgress: () => {}, statusOf },
    );
    expect(result).toMatchObject({ done: 1, made: 1, stoppedBy: 'quota' });
  });

  it('stops when the reader asks', async () => {
    let calls = 0;
    const result = await runBatch(
      items,
      async () => {
        calls += 1;
      },
      { shouldStop: () => calls >= 2, onProgress: () => {}, statusOf },
    );
    expect(calls).toBe(2);
    expect(result.stoppedBy).toBe('user');
  });
});
