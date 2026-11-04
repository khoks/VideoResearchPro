/*
 * The Android share target, page side (T-3.7.6.1): what waits on the device,
 * what it becomes, and when it leaves. The Cache API is faked; the worker that
 * fills it is run for real in shareTargetSw.test.ts and in the browser in
 * tests/manifest.spec.ts.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  clearPendingShares,
  deliverPendingShares,
  discardPendingShares,
  hasPendingShares,
  planOsShare,
  readPendingShares,
  unsentParts,
  PENDING_MAX_AGE_MS,
  type SharePart,
} from '../shareTarget';

const NAME = 'echo-pending-shares-v1';

interface Entry {
  url: string;
  form: FormData | null;
  storedAt: string | null;
  sent?: string | null;
}

/** One cache of pending shares, answering what the page asks of the real one. */
function fakeCaches(entries: Entry[]) {
  const store = new Map(entries.map((e) => [e.url, e]));
  const cache = {
    keys: async () => [...store.values()].map((e) => ({ url: e.url })),
    match: async (req: { url: string } | string) => {
      const entry = store.get(typeof req === 'string' ? req : req.url);
      if (!entry) return undefined;
      return {
        headers: new Headers({
          ...(entry.storedAt ? { 'x-stored-at': entry.storedAt } : {}),
          ...(entry.sent ? { 'x-sent-parts': entry.sent } : {}),
        }),
        blob: async () => new Blob(['kept']),
        formData: async () => {
          if (!entry.form) throw new TypeError('not a form');
          return entry.form;
        },
      };
    },
    put: async (key: string, response: Response) => {
      const entry = store.get(key);
      if (!entry) throw new Error('rewrote an entry that is gone');
      store.set(key, { ...entry, storedAt: response.headers.get('x-stored-at'), sent: response.headers.get('x-sent-parts') });
    },
    delete: async (req: { url: string } | string) => store.delete(typeof req === 'string' ? req : req.url),
  };
  vi.stubGlobal('caches', {
    has: async (name: string) => name === NAME,
    open: async () => cache,
    delete: async (name: string) => {
      if (name === NAME) store.clear();
      return true;
    },
  });
  return store;
}

function form(fields: Record<string, string>, files: File[] = []): FormData {
  const f = new FormData();
  for (const [k, v] of Object.entries(fields)) f.set(k, v);
  for (const file of files) f.append('files', file);
  return f;
}

// A retry remembers what it sent by key, as a real key is never reused.
let next = 0;
const entry = (name: string, fields: Record<string, string>, storedAt = Date.now(), files: File[] = []): Entry => ({
  url: `http://localhost/echo/share-target/pending/${name}-${(next += 1)}`,
  form: form(fields, files),
  storedAt: String(storedAt),
});

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('planOsShare', () => {
  const none = { title: '', text: '', url: '', files: [] as File[] };

  it('takes a link from the url field or from a text that is only a link', () => {
    expect(planOsShare({ ...none, url: 'https://a.example/x' }).parts).toEqual([{ kind: 'url', url: 'https://a.example/x', title: undefined }]);
    expect(planOsShare({ ...none, text: ' https://youtu.be/abc ', title: 'A video' }).parts).toEqual([
      { kind: 'url', url: 'https://youtu.be/abc', title: 'A video' },
    ]);
  });

  it('keeps words as text, and words that only repeat the link add nothing', () => {
    expect(planOsShare({ ...none, text: 'A line worth keeping' }).parts).toEqual([{ kind: 'text', text: 'A line worth keeping', title: undefined }]);
    expect(planOsShare({ ...none, text: 'Read this https://a.example/x', url: 'https://a.example/x' }).parts).toHaveLength(1);
    expect(planOsShare({ ...none, text: 'Different words', url: 'https://a.example/x' }).parts).toHaveLength(2);
  });

  it('never asks the server to treat a share as the user’s own words', () => {
    const { parts } = planOsShare({ title: 't', text: 'words', url: 'https://a.example/x', files: [new File(['x'], 'a.txt')] });
    expect(parts.length).toBe(3);
    expect(JSON.stringify(parts)).not.toContain('author_is_tenant');
  });

  it('caps the files as a drop does, and caps the title to what the route takes', () => {
    const files = Array.from({ length: 12 }, (_, i) => new File(['x'], `f${i}.txt`));
    const plan = planOsShare({ ...none, files, title: 'x'.repeat(400), text: 'words' });
    expect(plan.parts.filter((p) => p.kind === 'file')).toHaveLength(10);
    expect(plan.skipped).toBe(2);
    expect((plan.parts.at(-1) as { title: string }).title).toHaveLength(300);
  });

  it('falls back to the title when nothing else came, and to nothing at all', () => {
    expect(planOsShare({ ...none, title: 'Only a title' }).parts).toEqual([{ kind: 'text', text: 'Only a title' }]);
    expect(planOsShare(none).parts).toEqual([]);
  });
});

describe('unsentParts', () => {
  it('leaves out what has already gone, and nothing else', () => {
    const pending = { key: 'k', title: '', text: 'words', url: 'https://a.example/x', files: [], sent: [0] };
    expect(unsentParts(pending).parts).toEqual([{ kind: 'text', text: 'words', title: undefined }]);
    expect(unsentParts({ ...pending, sent: [] }).parts).toHaveLength(2);
  });
});

describe('what waits on the device', () => {
  it('reads the oldest first and keeps the files', async () => {
    const file = new File(['bytes'], 'scan.png', { type: 'image/png' });
    fakeCaches([entry('b', { text: 'newer' }, Date.now() - 1000), entry('a', { text: 'older' }, Date.now() - 5000, [file])]);
    const pending = await readPendingShares();
    expect(pending.map((p) => p.text)).toEqual(['older', 'newer']);
    expect(pending[0].files[0].name).toBe('scan.png');
  });

  it('drops a share left too long, unread', async () => {
    const now = Date.now();
    const store = fakeCaches([entry('old', { text: 'stale' }, now - PENDING_MAX_AGE_MS - 1), entry('new', { text: 'fresh' }, now)]);
    const pending = await readPendingShares(now);
    expect(pending.map((p) => p.text)).toEqual(['fresh']);
    expect(store.size).toBe(1);
  });

  it('drops an entry that cannot be read', async () => {
    const store = fakeCaches([{ url: 'http://localhost/x', form: null, storedAt: String(Date.now()) }]);
    expect(await readPendingShares()).toEqual([]);
    expect(store.size).toBe(0);
  });

  it('drops an entry with nothing to post', async () => {
    const empty = entry('empty', {});
    const spent = { ...entry('spent', { text: 'gone already' }), sent: '0' };
    const store = fakeCaches([empty, spent]);
    expect(await readPendingShares()).toEqual([]);
    expect(store.size).toBe(0);
  });

  it('answers "nothing" where the browser has no Cache API', async () => {
    vi.stubGlobal('caches', undefined);
    expect(await hasPendingShares()).toBe(false);
    expect(await deliverPendingShares(['any'], vi.fn())).toEqual({ kind: 'nothing' });
    await expect(clearPendingShares()).resolves.toBeUndefined();
  });

  it('creates no cache just by looking', async () => {
    const open = vi.fn();
    vi.stubGlobal('caches', { has: async () => false, open });
    expect(await hasPendingShares()).toBe(false);
    expect(open).not.toHaveBeenCalled();
  });
});

describe('leaving the device unposted', () => {
  it('discards only the shares it was given', async () => {
    const store = fakeCaches([entry('seen', { text: 'seen' }), entry('newer', { text: 'newer' })]);
    const [seen] = store.keys();
    await discardPendingShares([seen]);
    expect((await readPendingShares()).map((p) => p.text)).toEqual(['newer']);
  });

  it('clears everything at sign-out', async () => {
    const store = fakeCaches([entry('a', { text: 'private' }), entry('b', { text: 'also private' })]);
    await clearPendingShares();
    expect(store.size).toBe(0);
  });

  it('does not let a broken Cache API stop a sign-out', async () => {
    vi.stubGlobal('caches', {
      delete: async () => {
        throw new Error('storage is gone');
      },
    });
    await expect(clearPendingShares()).resolves.toBeUndefined();
  });
});

describe('deliverPendingShares', () => {
  const failure = (status?: number, detail?: string) =>
    Object.assign(new Error('nope'), status ? { response: { status, data: { detail } } } : {});
  const nameOf = (p: SharePart) => (p.kind === 'file' ? p.file.name : p.kind);
  const file = (name: string) => new File(['bytes'], name, { type: 'image/png' });

  it('posts each share and removes it from the device', async () => {
    const store = fakeCaches([entry('a', { text: 'one' }), entry('b', { url: 'https://a.example/x' })]);
    const sent: SharePart[] = [];
    const out = await deliverPendingShares([...store.keys()], async (p) => void sent.push(p));
    expect(out).toEqual({ kind: 'added', count: 2, skipped: 0 });
    expect(sent.map((p) => p.kind).sort()).toEqual(['text', 'url']);
    expect(store.size).toBe(0);
  });

  it('posts only the shares the user was shown, and what came since waits its turn', async () => {
    const store = fakeCaches([entry('shown', { text: 'shown' }, Date.now() - 1000)]);
    const shown = [...store.keys()];
    const late = entry('late', { text: 'arrived while the page was open' });
    store.set(late.url, late);
    const send = vi.fn(async () => undefined);
    expect(await deliverPendingShares(shown, send)).toEqual({ kind: 'added', count: 1, skipped: 0 });
    expect(send).toHaveBeenCalledTimes(1);
    expect([...store.keys()]).toEqual([late.url]);
  });

  it.each([[403, 'Echo needs the Studio plan.'], [413, 'file is over 25 MB'], [422, 'a URL is required']])(
    'drops a share the server refuses with %i: a retry cannot change that',
    async (status, detail) => {
      const store = fakeCaches([entry('a', { text: 'one' })]);
      const out = await deliverPendingShares([...store.keys()], async () => {
        throw failure(status, detail);
      });
      expect(out).toEqual({ kind: 'refused', count: 0, refused: 1, status, detail });
      expect(store.size).toBe(0);
    },
  );

  it('sends the rest of a share past a refused part, and counts both', async () => {
    const store = fakeCaches([entry('three', {}, Date.now(), [file('a.png'), file('big.png'), file('c.png')])]);
    const sent: string[] = [];
    const out = await deliverPendingShares([...store.keys()], async (p) => {
      if (nameOf(p) === 'big.png') throw failure(413, 'file is over 25 MB');
      sent.push(nameOf(p));
    });
    expect(sent).toEqual(['a.png', 'c.png']);
    expect(out).toEqual({ kind: 'refused', count: 2, refused: 1, status: 413, detail: 'file is over 25 MB' });
    expect(store.size).toBe(0);
  });

  it('does not lose the words beside a refused link', async () => {
    const store = fakeCaches([entry('both', { url: 'https://a.example/x', text: 'different words' })]);
    const sent: string[] = [];
    const out = await deliverPendingShares([...store.keys()], async (p) => {
      if (p.kind === 'url') throw failure(422, 'not a link we can read');
      sent.push(p.kind);
    });
    expect(sent).toEqual(['text']);
    expect(out).toMatchObject({ kind: 'refused', count: 1, refused: 1 });
  });

  it('stops at a 403, which is the whole account, and keeps nothing', async () => {
    const store = fakeCaches([
      entry('a', {}, Date.now() - 1000, [file('a.png'), file('b.png')]),
      entry('b', { text: 'next share' }),
    ]);
    const send = vi.fn(async () => {
      throw failure(403, 'Echo needs the Studio plan.');
    });
    const out = await deliverPendingShares([...store.keys()], send);
    expect(send).toHaveBeenCalledTimes(1);
    expect(out).toEqual({ kind: 'refused', count: 0, refused: 3, status: 403, detail: 'Echo needs the Studio plan.' });
    expect(store.size).toBe(0);
  });

  it('lets a 403 speak over an earlier refusal, since it is the one a plan changes', async () => {
    const store = fakeCaches([entry('a', {}, Date.now(), [file('big.png'), file('b.png')])]);
    const out = await deliverPendingShares([...store.keys()], async (p) => {
      throw nameOf(p) === 'big.png' ? failure(413, 'too big') : failure(403, 'Echo needs the Studio plan.');
    });
    expect(out).toMatchObject({ kind: 'refused', status: 403, refused: 2 });
  });

  it('goes on to the next share after a refusal', async () => {
    const store = fakeCaches([entry('a', { text: 'too big' }, Date.now() - 1000), entry('b', { text: 'fine' })]);
    const send = vi.fn(async (p: SharePart) => {
      if (p.kind === 'text' && p.text === 'too big') throw failure(413, 'too big');
    });
    expect(await deliverPendingShares([...store.keys()], send)).toMatchObject({ kind: 'refused', count: 1, status: 413 });
    expect(send).toHaveBeenCalledTimes(2);
    expect(store.size).toBe(0);
  });

  it.each([[undefined], [500], [503], [429], [401]])('keeps the share when the failure may pass (%s)', async (status) => {
    const store = fakeCaches([entry('a', { text: 'one' })]);
    const out = await deliverPendingShares([...store.keys()], async () => {
      throw failure(status);
    });
    expect(out.kind).toBe('failed');
    expect(store.size).toBe(1);
  });

  it('does not send a part twice on a retry', async () => {
    const store = fakeCaches([entry('retry', { text: 'words', url: 'https://a.example/x' })]);
    const keys = [...store.keys()];
    const calls: string[] = [];
    let fail = true;
    const send = async (p: SharePart) => {
      calls.push(p.kind);
      if (p.kind === 'text' && fail) throw failure(503);
    };
    expect((await deliverPendingShares(keys, send)).kind).toBe('failed');
    fail = false;
    expect(await deliverPendingShares(keys, send)).toEqual({ kind: 'added', count: 2, skipped: 0 });
    expect(calls).toEqual(['url', 'text', 'text']);
  });

  it('remembers what was sent on the device, so closing the app does not send it again', async () => {
    const store = fakeCaches([entry('memo', { text: 'words', url: 'https://a.example/x' })]);
    const keys = [...store.keys()];
    const calls: string[] = [];
    const send = async (p: SharePart) => {
      calls.push(p.kind);
      if (p.kind === 'text' && calls.length === 2) throw failure(503);
    };
    expect((await deliverPendingShares(keys, send)).kind).toBe('failed');
    expect(store.get(keys[0])?.sent).toBe('0');

    // A reopened app is a new module: only the device remembers.
    vi.resetModules();
    const reopened = await import('../shareTarget');
    expect(await reopened.deliverPendingShares(keys, send)).toEqual({ kind: 'added', count: 2, skipped: 0 });
    expect(calls).toEqual(['url', 'text', 'text']);
    expect(store.size).toBe(0);
  });

  it('asks again about a refused part after a dropped connection, so the report stays true', async () => {
    const store = fakeCaches([entry('mix', {}, Date.now(), [file('a.png'), file('big.png'), file('c.png')])]);
    const keys = [...store.keys()];
    const calls: string[] = [];
    let down = true;
    const send = async (p: SharePart) => {
      calls.push(nameOf(p));
      if (nameOf(p) === 'big.png') throw failure(413, 'too big');
      if (nameOf(p) === 'c.png' && down) throw failure(503);
    };
    expect((await deliverPendingShares(keys, send)).kind).toBe('failed');
    down = false;
    expect(await deliverPendingShares(keys, send)).toMatchObject({ kind: 'refused', count: 2, refused: 1 });
    expect(calls).toEqual(['a.png', 'big.png', 'c.png', 'big.png', 'c.png']);
  });

  it('still works if the device cannot record a part', async () => {
    const store = fakeCaches([entry('a', { text: 'words', url: 'https://a.example/x' })]);
    const cache = await caches.open(NAME);
    cache.put = async () => {
      throw new DOMException('quota', 'QuotaExceededError');
    };
    expect(await deliverPendingShares([...store.keys()], async () => undefined)).toEqual({ kind: 'added', count: 2, skipped: 0 });
    expect(store.size).toBe(0);
  });

  it('joins a delivery already running, so nothing is posted twice', async () => {
    const store = fakeCaches([entry('a', { text: 'one' })]);
    const send = vi.fn(async () => undefined);
    const keys = [...store.keys()];
    const [first, second] = await Promise.all([deliverPendingShares(keys, send), deliverPendingShares(keys, send)]);
    expect(first).toEqual({ kind: 'added', count: 1, skipped: 0 });
    expect(second).toEqual(first);
    expect(send).toHaveBeenCalledTimes(1);
    expect(store.size).toBe(0);
  });

  it('reports nothing when nothing is waiting', async () => {
    fakeCaches([]);
    const send = vi.fn();
    expect(await deliverPendingShares(['gone'], send)).toEqual({ kind: 'nothing' });
    expect(send).not.toHaveBeenCalled();
  });
});
