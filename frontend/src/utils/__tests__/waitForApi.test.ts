/**
 * After a restart is accepted, the old API still answers for a couple of
 * seconds. waitForApi must not ping before the initial delay, must keep
 * pinging through failures, and must give up at the timeout.
 */
import { describe, expect, it, vi } from 'vitest';
import { waitForApi } from '../waitForApi';

function clock() {
  let t = 0;
  const slept: number[] = [];
  return {
    now: () => t,
    sleep: async (ms: number) => {
      slept.push(ms);
      t += ms;
    },
    slept,
  };
}

describe('waitForApi', () => {
  it('waits out the initial delay before the first ping', async () => {
    const c = clock();
    const ping = vi.fn(async () => {
      // The first ping must come after the old process is gone.
      expect(c.now()).toBe(6000);
      return true;
    });
    const result = await waitForApi({ ping, isCancelled: () => false, sleep: c.sleep, now: c.now });
    expect(result).toBe('back');
    expect(ping).toHaveBeenCalledTimes(1);
    expect(c.slept).toEqual([6000]);
  });

  it('keeps pinging through failures until one answers', async () => {
    const c = clock();
    let calls = 0;
    const ping = vi.fn(async () => {
      calls += 1;
      if (calls < 4) throw new Error('down');
      return true;
    });
    const result = await waitForApi({ ping, isCancelled: () => false, sleep: c.sleep, now: c.now });
    expect(result).toBe('back');
    expect(ping).toHaveBeenCalledTimes(4);
    expect(c.slept).toEqual([6000, 2000, 2000, 2000]);
  });

  it('gives up at the timeout', async () => {
    const c = clock();
    const ping = vi.fn(async () => {
      throw new Error('down');
    });
    const result = await waitForApi({
      ping,
      isCancelled: () => false,
      sleep: c.sleep,
      now: c.now,
      timeoutMs: 12_000,
    });
    expect(result).toBe('timeout');
    // 6 s, then pings at 6, 8, 10 and 12 s.
    expect(ping).toHaveBeenCalledTimes(4);
  });

  it('stops when the caller goes away', async () => {
    const c = clock();
    let cancelled = false;
    const ping = vi.fn(async () => {
      cancelled = true;
      throw new Error('down');
    });
    const result = await waitForApi({ ping, isCancelled: () => cancelled, sleep: c.sleep, now: c.now });
    expect(result).toBe('cancelled');
    expect(ping).toHaveBeenCalledTimes(1);
  });
});
