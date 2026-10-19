/*
 * The "Extract knowledge for all" loop, kept pure so it can be tested
 * (S-8.7.3). It runs the per-document extraction one at a time through the
 * existing endpoint, which enforces visibility and the monthly quota on
 * every call; it never runs more than the reader has left, stops at the
 * first quota refusal, and skips what cannot be extracted.
 */

export interface BatchItem {
  id: string;
  title: string;
}

export type BatchOutcome = 'made' | 'skipped' | 'failed' | 'quota';

export interface BatchProgress {
  done: number;
  total: number;
  made: number;
  skipped: number;
  failed: number;
  current: BatchItem | null;
  stoppedBy: 'finished' | 'user' | 'quota' | null;
}

/** Map an extraction error to what the loop should do with it. */
export function classifyError(status: number | undefined): BatchOutcome {
  if (status === 429 || status === 403) return 'quota';
  // 409 already extracted, 422 no transcript, 404 gone or no longer visible.
  if (status === 409 || status === 422 || status === 404) return 'skipped';
  return 'failed';
}

export function planBatch(items: BatchItem[], remaining: number): BatchItem[] {
  return Number.isFinite(remaining) ? items.slice(0, Math.max(0, remaining)) : items.slice();
}

export async function runBatch(
  items: BatchItem[],
  extract: (id: string) => Promise<unknown>,
  {
    shouldStop,
    onProgress,
    statusOf,
  }: {
    shouldStop: () => boolean;
    onProgress: (p: BatchProgress) => void;
    statusOf: (err: unknown) => number | undefined;
  },
): Promise<BatchProgress> {
  const p: BatchProgress = {
    done: 0,
    total: items.length,
    made: 0,
    skipped: 0,
    failed: 0,
    current: null,
    stoppedBy: null,
  };
  for (const item of items) {
    if (shouldStop()) {
      p.stoppedBy = 'user';
      break;
    }
    p.current = item;
    onProgress({ ...p });
    try {
      await extract(item.id);
      p.made += 1;
    } catch (err) {
      const outcome = classifyError(statusOf(err));
      if (outcome === 'quota') {
        p.stoppedBy = 'quota';
        break;
      }
      if (outcome === 'skipped') p.skipped += 1;
      else p.failed += 1;
    }
    p.done += 1;
    onProgress({ ...p });
  }
  p.current = null;
  if (!p.stoppedBy) p.stoppedBy = 'finished';
  onProgress({ ...p });
  return p;
}
