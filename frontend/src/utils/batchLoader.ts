/**
 * Collects keys requested within one short window and resolves them with a
 * single `fetchMany` call (the dataloader pattern), so a list of twenty
 * citation chips costs one request, not twenty. A key missing from the
 * response resolves to null; a failed fetch resolves every key in that batch
 * to null — a missing link is the safe failure for a decoration.
 */
export function createBatchLoader<V>(
  fetchMany: (keys: string[]) => Promise<Record<string, V>>,
  { delayMs = 15, maxBatch = 100 }: { delayMs?: number; maxBatch?: number } = {},
) {
  let pending = new Map<string, ((v: V | null) => void)[]>();
  let timer: ReturnType<typeof setTimeout> | null = null;

  async function flush() {
    const batch = pending;
    pending = new Map();
    timer = null;
    const keys = [...batch.keys()];
    for (let i = 0; i < keys.length; i += maxBatch) {
      const slice = keys.slice(i, i + maxBatch);
      let result: Record<string, V> = {};
      try {
        result = await fetchMany(slice);
      } catch {
        result = {};
      }
      for (const key of slice) {
        const value = Object.prototype.hasOwnProperty.call(result, key) ? result[key] : null;
        for (const resolve of batch.get(key) ?? []) resolve(value);
      }
    }
  }

  return function load(key: string): Promise<V | null> {
    return new Promise((resolve) => {
      const waiters = pending.get(key) ?? [];
      waiters.push(resolve);
      pending.set(key, waiters);
      if (!timer) timer = setTimeout(() => void flush(), delayMs);
    });
  };
}
