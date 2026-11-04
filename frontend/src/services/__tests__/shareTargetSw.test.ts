// @vitest-environment node
/*
 * public/share-target-sw.js, run for real against fake worker globals
 * (T-3.7.6.1). The browser-level path is in tests/manifest.spec.ts; this one
 * pins the worker's two promises where a failure is easy to read: the shared
 * words leave the request and enter nothing but the device's cache, and no
 * page ends up in the worker's scope, so nothing else ever goes through it.
 */
import { describe, expect, it, vi } from 'vitest';
import source from '../../../public/share-target-sw.js?raw';

const ORIGIN = 'https://app.example';

function boot(open?: () => Promise<unknown>) {
  const put = vi.fn(async () => undefined);
  const listeners: Record<string, (e: unknown) => void> = {};
  const self = {
    addEventListener: (name: string, fn: (e: unknown) => void) => {
      listeners[name] = fn;
    },
    skipWaiting: vi.fn(),
  };
  const caches = { open: open ?? (async () => ({ put })) };
  // Response.redirect() in a worker resolves against the worker's own
  // location; Node has none, so the absolute URL stands in.
  class SwResponse extends Response {
    static redirect(url: string, status?: number) {
      return Response.redirect(new URL(url, ORIGIN).href, status);
    }
  }
  new Function('self', 'caches', 'Response', 'crypto', source)(self, caches, SwResponse, { randomUUID: () => 'id-1' });
  return { listeners, put, self };
}

const PAGE = `${ORIGIN}/echo/incoming`;

function dispatch(fetchHandler: (e: unknown) => void, request: Pick<Request, 'url' | 'method' | 'mode'> & Partial<Request>) {
  const respondWith = vi.fn();
  fetchHandler({ request, respondWith });
  return respondWith;
}

// What the browser sends: the form on the wire, as the share sheet posts it.
const share = () =>
  new Request(`${ORIGIN}/echo/share-target`, {
    method: 'POST',
    headers: { 'content-type': 'multipart/form-data; boundary=x' },
    body: '--x\r\nContent-Disposition: form-data; name="text"\r\n\r\na private line\r\n--x--\r\n',
  });

describe('the share-target worker', () => {
  it('keeps the POST on the device and redirects with nothing in the address', async () => {
    const { listeners, put } = boot();
    const respondWith = dispatch(listeners.fetch, share());
    const response = (await respondWith.mock.calls[0][0]) as Response;
    expect(response.status).toBe(303);
    expect(response.headers.get('location')).toBe(PAGE);
    expect(response.headers.get('location')).not.toContain('private');

    const [key, kept] = put.mock.calls[0] as unknown as [string, Response];
    expect(key).toBe('/echo/share-target/pending/id-1');
    expect(key).not.toContain('private');
    expect(Number(kept.headers.get('x-stored-at'))).toBeGreaterThan(0);
    expect((await kept.formData()).get('text')).toBe('a private line');
  });

  it('says so when the device could not keep it', async () => {
    const { listeners } = boot(async () => {
      throw new Error('quota');
    });
    const respondWith = dispatch(listeners.fetch, share());
    const response = (await respondWith.mock.calls[0][0]) as Response;
    expect(response.headers.get('location')).toBe(`${PAGE}?failed=1`);
  });

  it('sends the page outside its own scope, so no document is ever controlled', async () => {
    const { listeners } = boot();
    const respondWith = dispatch(listeners.fetch, share());
    const location = new URL(((await respondWith.mock.calls[0][0]) as Response).headers.get('location') ?? '');
    expect(location.pathname.startsWith('/echo/share-target')).toBe(false);
  });

  it('turns a plain visit to the path away as well', async () => {
    const { listeners } = boot();
    const visit = { url: `${ORIGIN}/echo/share-target`, method: 'GET', mode: 'navigate' as RequestMode };
    const respondWith = dispatch(listeners.fetch, visit);
    const response = (await respondWith.mock.calls[0][0]) as Response;
    expect(response.headers.get('location')).toBe(PAGE);
  });

  it('leaves every other request alone', () => {
    const { listeners } = boot();
    expect(dispatch(listeners.fetch, new Request(`${ORIGIN}/echo/share-target`))).not.toHaveBeenCalled();
    const other = new Request(`${ORIGIN}/echo/share-target/other`, { method: 'POST', body: 'x' });
    expect(dispatch(listeners.fetch, other)).not.toHaveBeenCalled();
  });

  it('takes over at once, so a new version is not left waiting', () => {
    const { listeners, self } = boot();
    listeners.install({});
    expect(self.skipWaiting).toHaveBeenCalled();
  });
});
