/**
 * Command palette in a real desktop browser (S-8.2.2): the chords reach the
 * page, the combobox / listbox semantics hold, a question result lands on
 * its exchange card, `/` and the `g` chords stay out of text fields.
 * Hermetic like mobile.spec.ts: `/api/v1` from fixtures (the search answer
 * is synthetic), WebSocket closed.
 */
import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

const JOB = '1c222ce6-086e-464d-a366-403111963d39';

function fixture(name: string): unknown {
  return JSON.parse(readFileSync(new URL(`./fixtures/api/${name}.json`, import.meta.url), 'utf-8'));
}

const ROUTES: Record<string, string> = {
  'GET /api/v1/health': 'health',
  'GET /api/v1/auth/me': 'auth-me',
  'GET /api/v1/shelves': 'shelves',
  'GET /api/v1/search': 'search-smoke',
  [`GET /api/v1/jobs/${JOB}`]: 'job',
  [`GET /api/v1/jobs/${JOB}/videos`]: 'job-videos',
  [`GET /api/v1/jobs/${JOB}/qa`]: 'job-qa',
};

async function boot(page: Page): Promise<string[]> {
  const searches: string[] = [];
  await page.addInitScript(() => {
    window.localStorage.setItem('videoresearchpro.authToken', 'fixture-token');
    window.localStorage.setItem('vrp:theme', 'light');
  });
  await page.routeWebSocket(/\/ws\//, (ws) => ws.close());
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const key = `${route.request().method()} ${url.pathname}`;
    if (key === 'GET /api/v1/search') searches.push(url.searchParams.get('q') ?? '');
    if (ROUTES[key]) return route.fulfill({ json: fixture(ROUTES[key]) });
    if (key === 'GET /api/v1/notes') return route.fulfill({ json: { items: [], total: 0, limit: 2000, offset: 0 } });
    // Lists the pages behind this test read but it does not check.
    return route.fulfill({ json: [] });
  });
  return searches;
}

test('Ctrl-K opens a labelled combobox; results group; Enter lands on the exchange', async ({ page }) => {
  const searches = await boot(page);
  await page.goto('/notes');
  await expect(page.getByRole('button', { name: /Search…/ })).toBeVisible();

  await page.keyboard.press('Control+k');
  const dialog = page.getByRole('dialog', { name: 'Command palette' });
  await expect(dialog).toBeVisible();
  const combobox = dialog.getByRole('combobox');
  await expect(combobox).toBeFocused();
  await expect(dialog.getByRole('listbox')).toBeVisible();
  await expect(dialog.getByRole('option', { name: /New research/ })).toBeVisible();

  await combobox.fill('smoke');
  await expect(dialog.getByRole('option', { name: /only cause of lung cancer/ })).toBeVisible();
  await expect(dialog.getByText('Questions', { exact: true })).toBeVisible();
  await expect(dialog.getByText('Runs', { exact: true })).toBeVisible();
  await expect(dialog.getByText('Sources', { exact: true })).toBeVisible();
  await expect(dialog.getByText('Channels', { exact: true })).toHaveCount(0);
  await expect(dialog.locator('[aria-live="polite"]')).toHaveText('3 results');
  expect(searches).toEqual(['smoke']); // debounced: one request for five keystrokes
  await expect(combobox).toHaveAttribute('aria-activedescendant', /.+/);

  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(new RegExp(`/jobs/${JOB}\\?exchange=synthetic-qa-2$`));
  await expect(dialog).toBeHidden();
  await expect(page.locator('#exchange-synthetic-qa-2')).toBeFocused();
});

test('Ctrl-Alt-K is the alternate; Escape closes and gives focus back', async ({ page }) => {
  await boot(page);
  await page.goto('/notes');
  const button = page.getByRole('button', { name: /Search…/ });
  await button.focus();
  await page.keyboard.press('Control+Alt+k');
  const dialog = page.getByRole('dialog', { name: 'Command palette' });
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(button).toBeFocused();
});

test('"/" focuses the page search and is typed normally inside a field; g l goes to the library', async ({ page }) => {
  await boot(page);
  await page.goto('/notes');
  const field = page.getByPlaceholder('Search your notes…');
  await page.locator('body').click({ position: { x: 5, y: 5 } });
  await page.keyboard.press('/');
  await expect(field).toBeFocused();
  await page.keyboard.type('a/b');
  await expect(field).toHaveValue('a/b');
  await expect(page.getByRole('dialog', { name: 'Command palette' })).toHaveCount(0);

  await page.locator('body').click({ position: { x: 5, y: 5 } });
  await page.keyboard.press('g');
  await page.keyboard.press('l');
  await expect(page).toHaveURL(/\/library$/);
});
