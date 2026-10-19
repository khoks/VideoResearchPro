/**
 * The library map in a real browser (S-8.9.2): a canvas has no DOM, so this
 * checks the accessibility layer the M9 plan makes part of the story — one
 * tab stop, arrow keys between nodes, Enter opens and Escape closes the
 * card, button alternatives to pan and zoom, a table with the same nodes,
 * reduced motion skipping the animated layout, and the table as the narrow
 * screen default. Hermetic: `/api/v1` from fixtures (the graph is
 * synthetic), WebSocket closed.
 */
import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

function fixture(name: string): unknown {
  return JSON.parse(readFileSync(new URL(`./fixtures/api/${name}.json`, import.meta.url), 'utf-8'));
}

const ROUTES: Record<string, string> = {
  'GET /api/v1/health': 'health',
  'GET /api/v1/auth/me': 'auth-me',
  'GET /api/v1/shelves': 'shelves',
  'GET /api/v1/library/graph': 'graph',
};

/** 14 nodes; one source links only to the channel, so 13 are drawn. */
const DRAWN = 13;

async function boot(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('videoresearchpro.authToken', 'fixture-token');
    window.localStorage.setItem('vrp:theme', 'light');
    // Every value the canvas's layout state takes, from the first render.
    const seen: string[] = [];
    (window as unknown as { __layoutSeen: string[] }).__layoutSeen = seen;
    new MutationObserver(records => {
      for (const r of records) {
        const v = (r.target as Element).getAttribute?.('data-layout');
        if (v && seen[seen.length - 1] !== v) seen.push(v);
      }
    }).observe(document, { subtree: true, attributes: true, attributeFilter: ['data-layout'], childList: true });
  });
  await page.routeWebSocket(/\/ws\//, ws => ws.close());
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const key = `${route.request().method()} ${url.pathname}`;
    if (ROUTES[key]) return route.fulfill({ json: fixture(ROUTES[key]) });
    if (key === 'GET /api/v1/notes') return route.fulfill({ json: { items: [], total: 0, limit: 2000, offset: 0 } });
    return route.fulfill({ json: [] });
  });
}

test('one tab stop: arrows move between nodes, Enter opens the card, Escape closes it', async ({ page }) => {
  await boot(page);
  await page.goto('/library/graph');
  const map = page.getByRole('application', { name: 'Library map' });
  await expect(map).toHaveAttribute('data-node-count', String(DRAWN));
  await expect(map).toHaveAttribute('data-layout', 'settled', { timeout: 10_000 });
  await expect(page.locator('[data-graph-summary]')).toContainText('1 single-link node is hidden');

  // Tab from the control just before the map lands on it, on the most connected node.
  await page.getByRole('checkbox', { name: /Single-link nodes/ }).focus();
  await page.keyboard.press('Tab');
  await expect(map).toBeFocused();
  const announcer = page.locator('[data-graph-announcer]');
  await expect(announcer).toHaveText(/^Channel: Synthetic channel\. 8 connections\. Group \d+\.$/);
  await expect(page.locator('[data-focus-ring]')).toBeVisible();

  // Some arrow moves focus to another node (which ones depends on the layout).
  const start = await map.getAttribute('data-active-node');
  let moved = false;
  for (const key of ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp']) {
    await page.keyboard.press(key);
    if ((await map.getAttribute('data-active-node')) !== start) {
      moved = true;
      break;
    }
  }
  expect(moved).toBe(true);
  await expect(announcer).toHaveText(/^(Source|Topic|Your question|Channel): .+\. \d+ connections?\. Group \d+\.$/);

  await page.keyboard.press('Enter');
  const card = page.locator('[data-graph-card]');
  await expect(card).toBeVisible();
  await expect(card.getByRole('heading')).toBeVisible();
  await expect(announcer).toContainText('Details are open after the map.');
  await expect(map).toBeFocused();

  await page.keyboard.press('Escape');
  await expect(card).toBeHidden();
  await expect(announcer).toHaveText('Details closed.');

  // Home returns to the start; every gesture has a button (WCAG 2.5.7).
  await page.keyboard.press('Home');
  await expect(map).toHaveAttribute('data-active-node', start!);
  for (const name of ['Zoom in', 'Zoom out', 'Reset view', 'Pan up', 'Pan down', 'Pan left', 'Pan right']) {
    await expect(page.getByRole('button', { name, exact: true })).toBeVisible();
  }
});

test('the table lists exactly the drawn nodes and opens the same card', async ({ page }) => {
  await boot(page);
  await page.goto('/library/graph');
  const map = page.getByRole('application', { name: 'Library map' });
  await expect(map).toHaveAttribute('data-node-count', String(DRAWN));

  await page.getByRole('button', { name: 'Table', exact: true }).click();
  await expect(page).toHaveURL(/view=table/);
  const rows = page.locator('[data-graph-table] tbody tr');
  await expect(rows).toHaveCount(DRAWN);
  await expect(rows.first()).toContainText('▸ Synthetic channel');
  await expect(page.locator('[data-graph-table]')).not.toContainText('Synthetic source 9');

  await page.locator('[data-graph-table]').getByRole('button', { name: '? Synthetic question: what moves rates?' }).click();
  const card = page.locator('[data-graph-card]');
  await expect(card.getByRole('link', { name: 'Open the answer' })).toHaveAttribute('href', '/library/qa?exchange=synthetic-qa-1');

  await page.getByRole('button', { name: /Show all 22 connections/ }).click();
  await expect(page.locator('[data-graph-edges] tbody tr')).toHaveCount(22);
});

test('reduced motion lays the map out before the first frame', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await boot(page);
  await page.goto('/library/graph');
  const map = page.getByRole('application', { name: 'Library map' });
  await expect(map).toHaveAttribute('data-layout', 'settled');
  await page.waitForTimeout(500);
  const seen = await page.evaluate(() => (window as unknown as { __layoutSeen: string[] }).__layoutSeen);
  expect(seen).not.toContain('running');
});

test('without reduced motion the layout animates, then freezes', async ({ page }) => {
  await boot(page);
  await page.goto('/library/graph');
  const map = page.getByRole('application', { name: 'Library map' });
  await expect(map).toHaveAttribute('data-layout', 'settled', { timeout: 10_000 });
  const seen = await page.evaluate(() => (window as unknown as { __layoutSeen: string[] }).__layoutSeen);
  expect(seen).toEqual(expect.arrayContaining(['running', 'settled']));
});

test('a narrow screen opens on the table', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await boot(page);
  await page.goto('/library/graph');
  await expect(page.locator('[data-graph-table] tbody tr')).toHaveCount(DRAWN);
  await expect(page.getByRole('application', { name: 'Library map' })).toHaveCount(0);
});
