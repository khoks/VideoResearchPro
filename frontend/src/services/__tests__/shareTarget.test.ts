/*
 * The Android share target, page side (T-3.7.6.1): what waits on the device,
 * what it becomes, and when it leaves. The Cache API is faked; the worker that
 * fills it is run for real in shareTargetSw.test.ts and in the browser in
 * tests/manifest.spec.ts.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  deliverPendingShares,
  hasPendingShares,
  planOsShare,
  readPendingShares,
  PENDING_MAX_AGE_MS,
  type SharePart,
} from '../shareTarget';

const NAME = 'echo-pending-shares-v1';

interface Entry {
  url: string;
  form: FormData | null;
  storedAt: string | null;
}

/** One cache of pending shares, answering what the page asks of the real one. */
function fakeCaches(entries: Entry[]) {
  const store = new Map(entries.map((e) => [e.url, e]));
  const cache = {
    keys: async () => [...store.values()].map((e) => ({ url: e.url })),
    match: async (req: { url: string }) => {
      const entry = store.get(req.url);
      if (!entry) return undefined;
      return {
        headers: new Headers(entry.storedAt ? { 'x-stored-at': entry.storedAt } : {}),
        formData: async () => {
          if (!entry.form) throw new TypeError('not a form');
          return entry.form;
        },
      };
    },
    delete: async (req: { url: string } | string) => store.delete(typeof req === 'string' ? req : req.url),
  };
  vi.stubGlobal('caches', { has: async (name: string) => name === NAME, open: async () => cache });
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

  it('answers "nothing" where the browser has no Cache API', async () => {
    vi.stubGlobal('caches', undefined);
    expect(await hasPendingShares()).toBe(false);
    expect(await deliverPendingShares(vi.fn())).toEqual({ kind: 'nothing' });
  });

  it('creates no cache just by looking', async () => {
    const open = vi.fn();
    vi.stubGlobal('caches', { has: async () => false, open });
    expect(await hasPendingShares()).toBe(false);
    expect(open).not.toHaveBeenCalled();
  });
});

describe('deliverPendingShares', () => {
  const failure = (status?: number, detail?: string) =>
    Object.assign(new Error('nope'), status ? { response: { status, data: { detail } } } : {});

  it('posts each share and removes it from the device', async () => {
    const store = fakeCaches([entry('a', { text: 'one' }), entry('b', { url: 'https://a.example/x' })]);
    const sent: SharePart[] = [];
    const out = await deliverPendingShares(async (p) => void sent.push(p));
    expect(out).toEqual({ kind: 'added', count: 2, skipped: 0 });
    expect(sent.map((p) => p.kind).sort()).toEqual(['text', 'url']);
    expect(store.size).toBe(0);
  });

  it.each([[403, 'Echo needs the Studio plan.'], [413, 'file is over 25 MB'], [422, 'a URL is required']])(
    'drops a share the server refuses with %i: a retry cannot change that',
    async (status, detail) => {
      const store = fakeCaches([entry('a', { text: 'one' })]);
      const out = await deliverPendingShares(async () => {
        throw failure(status, detail);
      });
      expect(out).toEqual({ kind: 'refused', count: 0, status, detail });
      expect(store.size).toBe(0);
    },
  );

  it('goes on to the next share after a refusal', async () => {
    const store = fakeCaches([entry('a', { text: 'too big' }, Date.now() - 1000), entry('b', { text: 'fine' })]);
    const send = vi.fn(async (p: SharePart) => {
      if (p.kind === 'text' && p.text === 'too big') throw failure(413, 'too big');
    });
    expect(await deliverPendingShares(send)).toMatchObject({ kind: 'refused', count: 1, status: 413 });
    expect(send).toHaveBeenCalledTimes(2);
    expect(store.size).toBe(0);
  });

  it.each([[undefined], [500], [503], [429], [401]])('keeps the share when the failure may pass (%s)', async (status) => {
    const store = fakeCaches([entry('a', { text: 'one' })]);
    const out = await deliverPendingShares(async () => {
      throw failure(status);
    });
    expect(out.kind).toBe('failed');
    expect(store.size).toBe(1);
  });

  it('does not send a part twice on a retry', async () => {
    fakeCaches([entry('retry', { text: 'words', url: 'https://a.example/x' })]);
    const calls: string[] = [];
    let fail = true;
    const send = async (p: SharePart) => {
      calls.push(p.kind);
      if (p.kind === 'text' && fail) throw failure(503);
    };
    expect((await deliverPendingShares(send)).kind).toBe('failed');
    fail = false;
    expect((await deliverPendingShares(send)).kind).toBe('added');
    expect(calls).toEqual(['url', 'text', 'text']);
  });

  it('joins a delivery already running, so nothing is posted twice', async () => {
    const store = fakeCaches([entry('a', { text: 'one' })]);
    const send = vi.fn(async () => undefined);
    const [first, second] = await Promise.all([deliverPendingShares(send), deliverPendingShares(send)]);
    expect(first).toEqual({ kind: 'added', count: 1, skipped: 0 });
    expect(second).toEqual(first);
    expect(send).toHaveBeenCalledTimes(1);
    expect(store.size).toBe(0);
  });

  it('reports nothing when nothing is waiting', async () => {
    fakeCaches([]);
    const send = vi.fn();
    expect(await deliverPendingShares(send)).toEqual({ kind: 'nothing' });
    expect(send).not.toHaveBeenCalled();
  });
});
