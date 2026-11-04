/**
 * Web-app manifest (S-8.12.2): the app installs from the browser and from
 * the iOS / Android home screen with the brand's icon and colours.
 *
 * Checks the files themselves (every icon exists at the size it claims, on
 * an opaque background), what the page links, and — in Chromium — the
 * browser's own installability verdict over the DevTools protocol.
 *
 * The share target (T-3.7.6.1) is driven the way Android drives it: a real
 * multipart POST navigation to the manifest's action, in Chromium, with the
 * real service worker answering it. Only the share sheet itself is missing.
 */
import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

interface ManifestIcon {
  src: string;
  sizes: string;
  type: string;
  purpose?: string;
}

const publicDir = new URL('../public/', import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('manifest.webmanifest', publicDir), 'utf-8')) as {
  name: string;
  short_name: string;
  start_url: string;
  scope: string;
  display: string;
  theme_color: string;
  background_color: string;
  icons: ManifestIcon[];
  share_target: {
    action: string;
    method: string;
    enctype: string;
    params: { title: string; text: string; url: string; files: { name: string; accept: string[] }[] };
  };
};

/** Width, height and colour type from a PNG's IHDR chunk. */
function pngHeader(file: URL): { width: number; height: number; colorType: number } {
  const b = readFileSync(file);
  expect(b.subarray(1, 4).toString('latin1')).toBe('PNG');
  return { width: b.readUInt32BE(16), height: b.readUInt32BE(20), colorType: b[25] };
}

test.describe('manifest', () => {
  test('declares a standalone app with the brand colours', () => {
    expect(manifest.name).toBe('Pratidhvani');
    expect(manifest.short_name.length).toBeLessThanOrEqual(12); // fits under a home-screen icon
    expect(manifest.display).toBe('standalone');
    expect(manifest.start_url).toBe('/');
    expect(manifest.scope).toBe('/');
    // docs/branding.md §8 and theme.ts: accent (oxblood) and paper.
    expect(manifest.theme_color).toBe('#7a2c1a');
    expect(manifest.background_color).toBe('#faf6f0');
  });

  test('every PNG icon exists at its declared size, with no transparency', () => {
    const pngs = manifest.icons.filter((i) => i.type === 'image/png');
    expect(pngs.map((i) => i.sizes)).toEqual(expect.arrayContaining(['192x192', '512x512']));
    expect(pngs.some((i) => i.purpose === 'maskable')).toBe(true);
    for (const icon of [...pngs, { src: '/apple-touch-icon.png', sizes: '180x180', type: 'image/png' }]) {
      const { width, height, colorType } = pngHeader(new URL(icon.src.slice(1), publicDir));
      expect(`${width}x${height}`, icon.src).toBe(icon.sizes);
      // Colour type 6 / 4 carry alpha; a transparent home-screen icon turns
      // black on iOS. The renderer paints the paper background.
      expect([2, 3], `${icon.src} colour type`).toContain(colorType);
    }
  });

  test('the page links the manifest, icons and theme colour, and is served them', async ({ page, request }) => {
    await page.goto('/login');
    const head = await page.evaluate(() => ({
      manifest: document.querySelector('link[rel="manifest"]')?.getAttribute('href'),
      apple: document.querySelector('link[rel="apple-touch-icon"]')?.getAttribute('href'),
      theme: document.querySelector('meta[name="theme-color"]')?.getAttribute('content'),
      viewport: document.querySelector('meta[name="viewport"]')?.getAttribute('content') ?? '',
      title: document.title,
    }));
    expect(head.manifest).toBe('/manifest.webmanifest');
    expect(head.apple).toBe('/apple-touch-icon.png');
    expect(head.theme).toBe(manifest.theme_color);
    expect(head.viewport).toContain('viewport-fit=cover');
    expect(head.viewport).not.toMatch(/maximum-scale|user-scalable\s*=\s*no/);
    expect(head.title).toContain('Pratidhvani');

    const res = await request.get('/manifest.webmanifest');
    expect(res.ok()).toBe(true);
    expect(await res.json()).toEqual(manifest);
    for (const icon of manifest.icons) {
      expect((await request.get(icon.src)).ok(), icon.src).toBe(true);
    }
  });

  test('Chromium finds nothing standing in the way of installing it', async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'installability is reported over the Chromium DevTools protocol');
    await page.goto('/login');
    await page.waitForLoadState('networkidle');
    const cdp = await page.context().newCDPSession(page);
    const { installabilityErrors } = (await cdp.send('Page.getInstallabilityErrors')) as {
      installabilityErrors: Array<{ errorId: string }>;
    };
    expect(installabilityErrors.map((e) => e.errorId)).toEqual([]);
    const { url, errors } = (await cdp.send('Page.getAppManifest')) as { url: string; errors: unknown[] };
    expect(url).toMatch(/\/manifest\.webmanifest$/);
    expect(errors).toEqual([]);
  });
});

const SECRET = 'a-private-line-that-must-stay-out-of-urls';
const FIXTURE_TOKEN = 'fixture-session-token';
const STUDIO = { id: 'u1', email: 'studio@example.com', created_at: '2026-05-16T03:18:12', tier: 'studio' };

function fixture(name: string): unknown {
  return JSON.parse(readFileSync(new URL(`./fixtures/api/${name}.json`, import.meta.url), 'utf-8'));
}

interface Stub {
  posted: Record<string, unknown>[];
  uploads: string[];
  authorizations: (string | undefined)[];
  unmatched: string[];
  /** Everything that took a URL: requests of every kind and every navigation. */
  urls: string[];
}

/** The API as the share flow meets it. An unmatched call fails the test. */
async function stubApi(page: Page, options: { refuse?: boolean } = {}): Promise<Stub> {
  const stub: Stub = { posted: [], uploads: [], authorizations: [], unmatched: [], urls: [] };
  const answers: Record<string, unknown> = {
    'GET /api/v1/health': fixture('health'),
    'GET /api/v1/auth/me': STUDIO,
    'GET /api/v1/auth/me/onboarding': { should_onboard: false, state: { checklist_dismissed: true }, milestones: {} },
    'GET /api/v1/shelves': fixture('shelves'),
    'GET /api/v1/notifications': { items: [], unread: 0 },
    'GET /api/v1/echo/shares': { items: [], total: 0, limit: 25, offset: 0 },
    'GET /api/v1/echo/imports': { items: [] },
    'POST /api/v1/echo/shares/seen': { ok: true },
  };
  page.on('request', (r) => stub.urls.push(r.url()));
  page.on('framenavigated', (f) => stub.urls.push(f.url()));
  await page.routeWebSocket(/\/ws\//, (ws) => ws.close());
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;
    if (key === 'POST /api/v1/auth/login') {
      return route.fulfill({ json: { access_token: FIXTURE_TOKEN, token_type: 'bearer', user: STUDIO } });
    }
    if (key === 'POST /api/v1/echo/shares' || key === 'POST /api/v1/echo/shares/upload') {
      stub.authorizations.push(request.headers().authorization);
      if (key.endsWith('upload')) stub.uploads.push(request.postData() ?? '');
      else stub.posted.push(request.postDataJSON());
      if (options.refuse) return route.fulfill({ status: 403, json: { detail: 'Echo needs the Studio plan.' } });
      return route.fulfill({ status: 201, json: { id: 's1' } });
    }
    if (key in answers) return route.fulfill({ json: answers[key] });
    if (request.method() === 'GET' && !stub.unmatched.includes(key)) stub.unmatched.push(key);
    return route.fulfill({ status: 404, json: { detail: 'no fixture' } });
  });
  return stub;
}

async function signIn(page: Page) {
  await page.addInitScript((token) => window.localStorage.setItem('videoresearchpro.authToken', token), FIXTURE_TOKEN);
}

async function workerActive(page: Page) {
  await page.waitForFunction(async () => {
    const registration = await navigator.serviceWorker.getRegistration('/echo/share-target');
    return registration?.active?.state === 'activated';
  });
  // Chromium can still be storing a brand-new registration as it reports
  // "activated", and a navigation in that window goes to the network (2 in
  // about 180 runs). A person cannot share that soon after installing.
  await page.waitForTimeout(250);
}

/** What the share sheet does: a form POST that navigates to the action. */
async function shareFromAndroid(page: Page, fields: Record<string, string>, file?: { name: string; mimeType: string; buffer: Buffer }) {
  await page.evaluate(
    ({ action, fields, withFile }) => {
      const form = document.createElement('form');
      form.id = 'share-sheet';
      form.method = 'POST';
      form.enctype = 'multipart/form-data';
      form.action = action;
      for (const [name, value] of Object.entries(fields)) {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = name;
        input.value = value;
        form.appendChild(input);
      }
      if (withFile) {
        const input = document.createElement('input');
        input.type = 'file';
        input.name = 'files';
        form.appendChild(input);
      }
      document.body.appendChild(form);
    },
    { action: manifest.share_target.action, fields, withFile: !!file },
  );
  if (file) await page.setInputFiles('#share-sheet input[type=file]', file);
  await page.evaluate(() => (document.getElementById('share-sheet') as HTMLFormElement).submit());
}

// A share is a full page load, and a full load of the dev server's unbundled
// modules, uncached because routes are on, can take seconds on a busy machine.
const LOAD = { timeout: 20_000 };

/** The toast the share page raises as it hands over to the inbox. */
async function expectAdded(page: Page) {
  await expect(page.getByText('Added to Echo.')).toBeVisible(LOAD);
  await expect(page).toHaveURL(/\/echo\/inbox$/);
}

/** Signed out, the app sends the share page on to the sign-in page. */
async function shareSignedOut(page: Page, stub: Stub, fields: Record<string, string>) {
  const atLogin = () => stub.urls.filter((u) => u.endsWith('/login')).length;
  const before = atLogin();
  await shareFromAndroid(page, fields);
  await expect.poll(atLogin, LOAD).toBeGreaterThan(before);
}

async function pendingCount(page: Page): Promise<number> {
  return page.evaluate(async () => {
    if (!(await caches.has('echo-pending-shares-v1'))) return 0;
    return (await (await caches.open('echo-pending-shares-v1')).keys()).length;
  });
}

test.describe('share target', () => {
  test('the manifest posts a share, so its words never enter a URL', () => {
    const target = manifest.share_target;
    expect(target.method).toBe('POST');
    expect(target.enctype).toBe('multipart/form-data');
    expect(target.action.startsWith(manifest.scope)).toBe(true);
    expect(target.params).toMatchObject({ title: 'title', text: 'text', url: 'url' });
    expect(target.params.files[0].name).toBe('files');
    expect(target.params.files[0].accept).toEqual(expect.arrayContaining(['image/*', 'application/pdf']));
  });

  test.describe('in Chromium', () => {
    test.describe.configure({ timeout: 90_000 });
    test.skip(({ browserName }) => browserName !== 'chromium', 'WebKit has no share target; an iPhone uses the Shortcut');

    test('the worker sees the share path and nothing else in the app', async ({ page }) => {
      await stubApi(page);
      await page.goto('/login');
      await workerActive(page);
      const { scope, controlled } = await page.evaluate(async () => ({
        scope: (await navigator.serviceWorker.getRegistration('/echo/share-target'))?.scope,
        controlled: navigator.serviceWorker.controller !== null,
      }));
      expect(new URL(scope ?? 'http://x').pathname).toBe(manifest.share_target.action);
      expect(controlled, 'an app page goes through no service worker').toBe(false);
    });

    test('a shared line lands in the inbox and enters no URL', async ({ page }) => {
      const stub = await stubApi(page);
      await signIn(page);
      await page.goto('/echo/inbox');
      await workerActive(page);
      await shareFromAndroid(page, { title: 'A title', text: SECRET });
      await expectAdded(page);

      expect(stub.posted).toEqual([{ text: SECRET, surface: 'os_share', source_title: 'A title' }]);
      expect(stub.authorizations).toEqual([`Bearer ${FIXTURE_TOKEN}`]);
      expect(stub.urls.filter((u) => u.includes(SECRET) || u.includes('share-target?'))).toEqual([]);
      expect(await page.evaluate(() => JSON.stringify(window.history.state))).not.toContain(SECRET);
      expect(await pendingCount(page)).toBe(0);
      expect(stub.unmatched).toEqual([]);
    });

    test('a link in the text field becomes a link share', async ({ page }) => {
      const stub = await stubApi(page);
      await signIn(page);
      await page.goto('/echo/inbox');
      await workerActive(page);
      await shareFromAndroid(page, { text: 'https://example.org/essay' });
      await expectAdded(page);
      expect(stub.posted).toEqual([{ url: 'https://example.org/essay', surface: 'os_share' }]);
    });

    test('a shared file goes to the upload route', async ({ page }) => {
      const stub = await stubApi(page);
      await signIn(page);
      await page.goto('/echo/inbox');
      await workerActive(page);
      await shareFromAndroid(page, {}, { name: 'scan.png', mimeType: 'image/png', buffer: Buffer.from('not really a png') });
      await expectAdded(page);
      expect(stub.uploads).toHaveLength(1);
      expect(stub.uploads[0]).toContain('filename="scan.png"');
      expect(stub.uploads[0]).toContain('os_share');
    });

    test('a share made signed out waits through the sign-in', async ({ page }) => {
      const stub = await stubApi(page);
      await page.goto('/login');
      await workerActive(page);
      await shareSignedOut(page, stub, { text: SECRET });
      expect(stub.posted).toEqual([]);
      expect(await pendingCount(page)).toBe(1);

      await page.getByLabel(/email/i).fill('studio@example.com');
      await page.getByLabel(/password/i).fill('not-a-real-password');
      await page.getByRole('button', { name: /sign in/i }).click();
      await expectAdded(page);

      expect(stub.posted).toEqual([{ text: SECRET, surface: 'os_share' }]);
      expect(stub.authorizations).toEqual([`Bearer ${FIXTURE_TOKEN}`]);
      const inUrls = stub.urls.filter((u) => u.includes(SECRET) || u.includes(FIXTURE_TOKEN));
      expect(inUrls, 'neither the words nor the sign-in token').toEqual([]);
      expect(await pendingCount(page)).toBe(0);
    });

    test('a sign-in that leaves the app finds the waiting share too', async ({ page }) => {
      // Google and GitHub sign-in come back to the app with no route state.
      const stub = await stubApi(page);
      await page.goto('/login');
      await workerActive(page);
      await shareSignedOut(page, stub, { text: SECRET });

      await page.evaluate((token) => window.localStorage.setItem('videoresearchpro.authToken', token), FIXTURE_TOKEN);
      await page.goto('/');
      await expectAdded(page);
      expect(stub.posted).toEqual([{ text: SECRET, surface: 'os_share' }]);
      expect(await pendingCount(page)).toBe(0);
    });

    test('an account without Echo is refused as at every intake, and nothing stays', async ({ page }) => {
      const stub = await stubApi(page, { refuse: true });
      await signIn(page);
      await page.goto('/echo/inbox');
      await workerActive(page);
      await shareFromAndroid(page, { text: SECRET });
      await expect(page.getByRole('alert')).toContainText('Echo needs the Studio plan.', LOAD);
      expect(stub.posted).toHaveLength(1);
      expect(await pendingCount(page)).toBe(0);
    });
  });
});
