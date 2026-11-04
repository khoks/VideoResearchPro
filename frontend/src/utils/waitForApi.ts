/**
 * After `POST /admin/restart` returns 202, the restart script waits a couple
 * of seconds and then kills the API, so a ping in the first seconds would
 * still reach the OLD process and report "back" too early. Wait out
 * `initialDelayMs` first, then ping every `intervalMs` until one answers or
 * `timeoutMs` (counted from the start) runs out.
 *
 * Resolves `'back'`, `'timeout'`, or `'cancelled'` (the caller unmounted).
 */
export interface WaitForApiOptions {
  ping: () => Promise<unknown>;
  isCancelled: () => boolean;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
  initialDelayMs?: number;
  intervalMs?: number;
  timeoutMs?: number;
}

export type WaitForApiResult = 'back' | 'timeout' | 'cancelled';

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export async function waitForApi({
  ping,
  isCancelled,
  sleep = defaultSleep,
  now = () => Date.now(),
  initialDelayMs = 6000,
  intervalMs = 2000,
  timeoutMs = 90_000,
}: WaitForApiOptions): Promise<WaitForApiResult> {
  const started = now();
  await sleep(initialDelayMs);
  for (;;) {
    if (isCancelled()) return 'cancelled';
    try {
      await ping();
      return isCancelled() ? 'cancelled' : 'back';
    } catch {
      // Still down (or still going down): try again.
    }
    if (now() - started >= timeoutMs) return 'timeout';
    await sleep(intervalMs);
  }
}
