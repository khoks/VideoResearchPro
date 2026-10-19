/**
 * Web-app manifest (S-8.12.2): the app installs from the browser and from
 * the iOS / Android home screen with the brand's icon and colours.
 *
 * Checks the files themselves (every icon exists at the size it claims, on
 * an opaque background), what the page links, and — in Chromium — the
 * browser's own installability verdict over the DevTools protocol.
 */
import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

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
