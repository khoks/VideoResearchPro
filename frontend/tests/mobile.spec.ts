/**
 * Mobile reading pass (S-8.12.1): the three reading pages on an iPhone
 * (WebKit), a Pixel (Chromium) and a 320 px phone, light and dark.
 *
 * Each page asserts what the acceptance criteria name — no horizontal scroll
 * (WCAG 1.4.10), 44 px primary controls, the composer reachable — and then
 * compares a screenshot with the checked-in baseline.
 */
import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

const JOB = '1c222ce6-086e-464d-a366-403111963d39';
const VIDEO = '4_2j5wgt_ds';

function fixture(name: string): unknown {
  return JSON.parse(readFileSync(new URL(`./fixtures/api/${name}.json`, import.meta.url), 'utf-8'));
}

const ROUTES: Record<string, string> = {
  'GET /api/v1/health': 'health',
  'GET /api/v1/auth/me': 'auth-me',
  'GET /api/v1/shelves': 'shelves',
  [`GET /api/v1/jobs/${JOB}`]: 'job',
  [`GET /api/v1/jobs/${JOB}/videos`]: 'job-videos',
  [`GET /api/v1/jobs/${JOB}/report/body`]: 'report-body',
  [`GET /api/v1/jobs/${JOB}/qa`]: 'job-qa',
  [`GET /api/v1/videos/${VIDEO}/knowledge`]: 'knowledge',
  'GET /api/v1/library/qa': 'job-qa',
};

const EMPTY: Record<string, unknown> = {
  'GET /api/v1/notes': { items: [], total: 0, limit: 2000, offset: 0 },
};

async function boot(page: Page, scheme: 'light' | 'dark'): Promise<string[]> {
  const unmatched: string[] = [];
  await page.addInitScript((theme) => {
    window.localStorage.setItem('videoresearchpro.authToken', 'fixture-token');
    window.localStorage.setItem('vrp:theme', theme);
  }, scheme);
  await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' });
  await page.routeWebSocket(/\/ws\//, (ws) => ws.close());
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const key = `${route.request().method()} ${url.pathname}`;
    if (ROUTES[key]) return route.fulfill({ json: fixture(ROUTES[key]) });
    if (key in EMPTY) return route.fulfill({ json: EMPTY[key] });
    unmatched.push(key + url.search);
    return route.fulfill({ status: 404, json: { detail: 'no fixture' } });
  });
  return unmatched;
}

async function expectNoHorizontalScroll(page: Page) {
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(scrollWidth, 'page scrolls sideways').toBeLessThanOrEqual(innerWidth);
}

async function expectTargets(page: Page, selector: string, min = 44) {
  const boxes = await page.locator(selector).evaluateAll((els) =>
    els
      .filter((el) => (el as HTMLElement).offsetParent !== null)
      .map((el) => {
        const r = el.getBoundingClientRect();
        return { label: (el.getAttribute('aria-label') ?? el.textContent ?? '').trim(), w: r.width, h: r.height };
      }),
  );
  expect(boxes.length, `no visible ${selector}`).toBeGreaterThan(0);
  for (const b of boxes) {
    expect.soft(Math.round(b.h), `${b.label} height`).toBeGreaterThanOrEqual(min);
    expect.soft(Math.round(b.w), `${b.label} width`).toBeGreaterThanOrEqual(min);
  }
}

for (const scheme of ['light', 'dark'] as const) {
  test.describe(`${scheme}`, () => {
    test(`report reader (${scheme})`, async ({ page }) => {
      const unmatched = await boot(page, scheme);
      await page.goto(`/reports/${JOB}`);
      await expect(page.locator('.reader-body h2').first()).toBeVisible();
      await expect(page.locator('.reader-dropcap')).toHaveCount(1);
      await expect(page.locator('.reader-outline')).toBeHidden();
      await expect(page.getByRole('toolbar', { name: 'Reading controls' })).toBeVisible();
      await expectNoHorizontalScroll(page);
      await expectTargets(page, '.reader-toolbar button');
      await expectTargets(page, '.pratidhvani-mobile-bar button[aria-expanded]');
      await expect(page).toHaveScreenshot(`reader-${scheme}.png`);

      // Contents sheet: the outline on a phone.
      await page.getByRole('button', { name: 'Contents' }).click();
      const sheet = page.getByRole('dialog', { name: 'Contents' });
      await expect(sheet).toBeVisible();
      await expectTargets(page, '[role="dialog"] a');
      await sheet.getByRole('link').nth(1).click();
      await expect(sheet).toBeHidden();
      expect(unmatched).toEqual([]);
    });

    test(`job Q&A thread (${scheme})`, async ({ page }) => {
      const unmatched = await boot(page, scheme);
      await page.goto(`/jobs/${JOB}`);
      const thread = page.locator('.qa-thread');
      await expect(thread).toBeVisible();
      await thread.scrollIntoViewIfNeeded();
      const composer = page.locator('.qa-composer');
      await expect(composer).toBeInViewport();
      // The composer comes after the thread on a phone, chat-like.
      const [t, c] = await Promise.all([thread.boundingBox(), composer.boundingBox()]);
      expect(c!.y).toBeGreaterThan(t!.y);
      await expectNoHorizontalScroll(page);
      await expectTargets(page, '.qa-composer button[type="submit"]');
      await expectTargets(page, '.qa-composer input');
      // A field under 16 px makes iOS zoom on focus.
      const fontPx = await page.locator('.qa-composer input').evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
      expect(fontPx).toBeGreaterThanOrEqual(16);
      await expect(page).toHaveScreenshot(`job-qa-${scheme}.png`);

      // A shorter viewport (the keyboard, as far as emulation goes) keeps the
      // composer on screen.
      const vp = page.viewportSize()!;
      await page.setViewportSize({ width: vp.width, height: Math.round(vp.height * 0.55) });
      await expect(composer).toBeInViewport();
      expect(unmatched).toEqual([]);
    });

    test(`knowledge report (${scheme})`, async ({ page }) => {
      const unmatched = await boot(page, scheme);
      await page.goto(`/knowledge/${VIDEO}`);
      await expect(page.locator('.reader-body h2').first()).toBeVisible();
      await expectNoHorizontalScroll(page);
      await expectTargets(page, '.reader-toolbar button');
      await expect(page).toHaveScreenshot(`knowledge-${scheme}.png`);
      expect(unmatched).toEqual([]);
    });
  });
}

test('library Q&A docks its composer too', async ({ page }) => {
  const unmatched = await boot(page, 'light');
  await page.goto('/library/qa');
  await expect(page.locator('.qa-thread')).toBeVisible();
  await page.locator('.qa-thread').scrollIntoViewIfNeeded();
  await expect(page.locator('.qa-composer')).toBeInViewport();
  await expectTargets(page, '.qa-composer button[type="submit"]');
  await expectNoHorizontalScroll(page);
  expect(unmatched).toEqual([]);
});
