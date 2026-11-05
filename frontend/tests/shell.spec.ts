/**
 * The app shell in a real browser: a deep link through sign-in (T-5.4.20), a
 * session that expires under an open page (T-5.4.22), the error screen
 * (T-4.11.2.3) and the tab keyboard (T-2.2.5). The vitest suites settle
 * everything between steps, so a race between the route guard and a sign-in
 * page, or the real trip through an OAuth provider, can only show here.
 * Hermetic like palette.spec.ts: `/api/v1` from fixtures, WebSocket closed. The
 * "provider" is a redirect straight back to the app's callback address, so the
 * page really does unload and load again.
 */
import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

const JOB = '1c222ce6-086e-464d-a366-403111963d39';
const DEEP = `/jobs/${JOB}?exchange=synthetic-qa-2`;

function fixture(name: string): unknown {
  return JSON.parse(readFileSync(new URL(`./fixtures/api/${name}.json`, import.meta.url), 'utf-8'));
}

const ROUTES: Record<string, string> = {
  'GET /api/v1/health': 'health',
  'GET /api/v1/auth/me': 'auth-me',
  'GET /api/v1/shelves': 'shelves',
  [`GET /api/v1/jobs/${JOB}`]: 'job',
  [`GET /api/v1/jobs/${JOB}/videos`]: 'job-videos',
  [`GET /api/v1/jobs/${JOB}/qa`]: 'job-qa',
};

const SESSION = { access_token: 'fixture-token', token_type: 'bearer', user: { id: 'u1', email: 'reader@example.com', tier: 'free' } };

interface Options {
  mfa?: boolean;
  answers?: Record<string, unknown>;
}

async function boot(page: Page, { mfa = false, answers = {} }: Options = {}) {
  await page.addInitScript(() => window.localStorage.setItem('vrp:theme', 'light'));
  await page.routeWebSocket(/\/ws\//, (ws) => ws.close());
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const key = `${route.request().method()} ${url.pathname}`;
    if (key in answers) return route.fulfill({ json: answers[key] });
    if (ROUTES[key]) return route.fulfill({ json: fixture(ROUTES[key]) });
    if (key === 'POST /api/v1/auth/login') {
      return route.fulfill({ json: mfa ? { requires_mfa: true, mfa_token: 'ticket', expires_in: 300 } : SESSION });
    }
    if (key === 'POST /api/v1/auth/login/mfa') return route.fulfill({ json: SESSION });
    if (key === 'GET /api/v1/auth/oauth/providers') return route.fulfill({ json: { providers: ['google'] } });
    if (key === 'GET /api/v1/auth/oauth/google/start') {
      const back = `${url.searchParams.get('redirect_uri')}?code=one-time&state=s`;
      return route.fulfill({ json: { authorize_url: back } });
    }
    if (key === 'GET /api/v1/auth/oauth/google/callback') {
      return route.fulfill({ json: mfa ? { requires_mfa: true, mfa_token: 'ticket', expires_in: 300 } : SESSION });
    }
    if (key === 'GET /api/v1/notes') return route.fulfill({ json: { items: [], total: 0, limit: 2000, offset: 0 } });
    // Lists the pages behind this test read but it does not check.
    return route.fulfill({ json: [] });
  });
}

async function signIn(page: Page) {
  await page.getByLabel('Email').fill('reader@example.com');
  await page.getByLabel('Password').fill('correct horse');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
}

async function arriveAtTheRun(page: Page) {
  await expect(page).toHaveURL(new RegExp(`${DEEP.replace('?', '\\?')}$`));
  await expect(page.getByRole('heading', { level: 1 })).toContainText('pratidhvani smoke test');
}

test.describe('a deep link while signed out', () => {
  test('comes back after a password', async ({ page }) => {
    await boot(page);
    await page.goto(DEEP);
    await expect(page).toHaveURL(/\/login$/);
    await signIn(page);
    await arriveAtTheRun(page);
  });

  test('comes back after the second step', async ({ page }) => {
    await boot(page, { mfa: true });
    await page.goto(DEEP);
    await signIn(page);
    await page.getByLabel('Authentication code').fill('123456');
    await page.getByRole('button', { name: 'Verify and sign in' }).click();
    await arriveAtTheRun(page);
  });

  test('comes back from an OAuth provider, with the code gone from the address', async ({ page }) => {
    await boot(page);
    await page.goto(DEEP);
    await page.getByRole('button', { name: 'Continue with Google' }).click();
    await arriveAtTheRun(page);
    expect(page.url()).not.toContain('one-time');
    expect(await page.evaluate(() => window.sessionStorage.length)).toBe(0);
  });

  test('comes back from an OAuth provider through the second step', async ({ page }) => {
    await boot(page, { mfa: true });
    await page.goto(DEEP);
    await page.getByRole('button', { name: 'Continue with Google' }).click();
    await page.getByLabel('Authentication code').fill('654321');
    await page.getByRole('button', { name: 'Verify and sign in' }).click();
    await arriveAtTheRun(page);
  });
});

test('a sign-in with no page to return to opens the app', async ({ page }) => {
  await boot(page);
  await page.goto('/login');
  await signIn(page);
  await expect(page).toHaveURL(/\/submit$/);
});

test('signing out leaves no page behind for the next sign-in', async ({ page }) => {
  await page.addInitScript(() => {
    if (!window.sessionStorage.getItem('booted')) {
      window.sessionStorage.setItem('booted', '1');
      window.localStorage.setItem('videoresearchpro.authToken', 'fixture-token');
    }
  });
  await boot(page);
  await page.goto(`/jobs/${JOB}`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('pratidhvani smoke test');
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await signIn(page);
  await expect(page).toHaveURL(/\/submit$/);
});

test('a sign-out in another tab leaves no page behind here either', async ({ page, context }) => {
  await page.addInitScript(() => {
    if (!window.sessionStorage.getItem('booted')) {
      window.sessionStorage.setItem('booted', '1');
      window.localStorage.setItem('videoresearchpro.authToken', 'fixture-token');
    }
  });
  await boot(page);
  await page.goto(`/jobs/${JOB}`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('pratidhvani smoke test');

  const other = await context.newPage();
  await boot(other);
  await other.goto(`/jobs/${JOB}`);
  await other.getByRole('button', { name: 'Sign out' }).click();

  await expect(page).toHaveURL(/\/login$/);
  await signIn(page);
  await expect(page).toHaveURL(/\/submit$/);
});

test.describe('a session that expires while a page is open', () => {
  const OLD_TOKEN = 'fixture-token-yesterday';
  const REFUSED = 'Could not validate credentials';

  /** Yesterday's token, in this tab's storage on its first load only. */
  async function holdYesterdaysToken(page: Page) {
    await page.addInitScript((token) => {
      if (!window.sessionStorage.getItem('booted')) {
        window.sessionStorage.setItem('booted', '1');
        window.localStorage.setItem('videoresearchpro.authToken', token);
      }
    }, OLD_TOKEN);
  }

  /** From now on the server refuses yesterday's token, and only that one. */
  async function serverStopsAccepting(page: Page) {
    await page.route('**/api/v1/**', (route) => {
      if (route.request().headers().authorization === `Bearer ${OLD_TOKEN}`) {
        return route.fulfill({ status: 401, json: { detail: REFUSED } });
      }
      return route.fallback();
    });
  }

  async function askAQuestion(page: Page) {
    await page.getByPlaceholder('Ask a question about the research…').fill('What does a lagoon cost?');
    await page.getByRole('button', { name: 'Ask', exact: true }).click();
  }

  test('an email link a day later comes back to its page', async ({ page }) => {
    await holdYesterdaysToken(page);
    await boot(page);
    await serverStopsAccepting(page);
    await page.goto(DEEP);
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText(REFUSED)).toHaveCount(0);
    await signIn(page);
    await arriveAtTheRun(page);
  });

  test('an old tab comes back to its page, with no error on the way', async ({ page }) => {
    await holdYesterdaysToken(page);
    await boot(page);
    await page.goto(DEEP);
    await arriveAtTheRun(page);

    await serverStopsAccepting(page);
    await askAQuestion(page);
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText(REFUSED)).toHaveCount(0);
    await signIn(page);
    await arriveAtTheRun(page);
  });

  test('the streaming ask, which does not use the API client, ends the session the same way', async ({ page }) => {
    await holdYesterdaysToken(page);
    await boot(page, { answers: { [`POST /api/v1/jobs/${JOB}/qa/clarify`]: { interpretation: 'Lagoon costs.', clarifications: [] } } });
    await page.goto(DEEP);
    await arriveAtTheRun(page);
    await askAQuestion(page);

    await serverStopsAccepting(page);
    await page.getByRole('button', { name: 'Skip clarifications' }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText('Q&A stream request failed')).toHaveCount(0);
    await signIn(page);
    await arriveAtTheRun(page);
  });

  test('a wrong password stays put, shows the message and keeps the page', async ({ page }) => {
    await holdYesterdaysToken(page);
    await boot(page);
    await serverStopsAccepting(page);
    await page.goto(DEEP);
    await expect(page).toHaveURL(/\/login$/);

    let attempts = 0;
    await page.route('**/api/v1/auth/login', (route) => {
      attempts += 1;
      if (attempts === 1) return route.fulfill({ status: 401, json: { detail: 'Invalid email or password' } });
      return route.fallback();
    });
    let loads = 0;
    page.on('load', () => (loads += 1));
    await signIn(page);
    await expect(page.getByText('Invalid email or password')).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
    expect(loads, 'a wrong password does not reload the page').toBe(0);

    await signIn(page);
    await arriveAtTheRun(page);
  });

  test('across tabs: the tab that met the 401 keeps its page, the other cannot tell and gives its up', async ({ page, context }) => {
    await holdYesterdaysToken(page);
    await boot(page);
    await page.goto(DEEP);
    await arriveAtTheRun(page);

    const other = await context.newPage();
    await boot(other);
    await other.goto(`/jobs/${JOB}`);
    await expect(other.getByRole('heading', { level: 1 })).toContainText('pratidhvani smoke test');

    await serverStopsAccepting(page);
    await askAQuestion(page);
    await expect(page).toHaveURL(/\/login$/);
    await expect(other).toHaveURL(/\/login$/);

    // Signing in there starts a session here too, and each goes where it may.
    await signIn(other);
    await expect(other).toHaveURL(/\/submit$/);
    await arriveAtTheRun(page);
  });
});

test('the tab bar is one stop, and the arrows, Home and End move along it', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem('videoresearchpro.authToken', 'fixture-token'));
  await boot(page);
  await page.goto('/library');
  const tabs = page.getByRole('tablist', { name: 'Library sections' }).getByRole('tab');
  await expect(tabs).toHaveText(['Sources', 'Channels', 'Add sources']);

  const channels = page.getByRole('tab', { name: 'Channels' });
  const add = page.getByRole('tab', { name: 'Add sources' });
  const sources = page.getByRole('tab', { name: 'Sources', exact: true });
  await sources.focus();

  await page.keyboard.press('ArrowRight');
  await expect(channels).toBeFocused();
  await expect(channels).toHaveAttribute('aria-selected', 'true');

  await page.keyboard.press('End');
  await expect(add).toBeFocused();
  await expect(add).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('tab', { selected: true })).toHaveCount(1);

  await page.keyboard.press('ArrowRight');
  await expect(sources).toBeFocused();
  await expect(sources).toHaveAttribute('aria-selected', 'true');

  await page.keyboard.press('ArrowLeft');
  await expect(add).toBeFocused();
  await page.keyboard.press('Home');
  await expect(sources).toBeFocused();

  // Tab leaves the row from the active tab, in one press.
  await page.keyboard.press('Tab');
  await expect(tabs.and(page.locator(':focus'))).toHaveCount(0);
  await page.keyboard.press('Shift+Tab');
  await expect(sources).toBeFocused();
});

test('a sign-in from a marketing page ends at the gate, not back on that page', async ({ page }) => {
  await boot(page);
  await page.goto('/landing');
  await page.getByRole('navigation', { name: 'Marketing' }).getByRole('link', { name: 'Sign in' }).click();
  await signIn(page);
  await expect(page).toHaveURL(/\/submit$/);
});

test('a page that throws lands on the error screen, with a way back and no stack', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem('videoresearchpro.authToken', 'fixture-token'));
  // Text where the page expects a list: rendering it throws.
  const broken = { ...(fixture('job') as object), preferred_channels: 'not a list' };
  await boot(page, { answers: { [`GET /api/v1/jobs/${JOB}`]: broken } });
  await page.goto(`/jobs/${JOB}`);
  await expect(page.getByRole('heading', { name: 'This page slipped off the shelf.' })).toBeVisible();
  await expect(page.locator('pre')).toHaveCount(0);
  await expect(page.getByText('Unexpected Application Error')).toHaveCount(0);
  await expect(page.getByText('TypeError')).toHaveCount(0);

  await page.getByRole('button', { name: 'Back to your library' }).click();
  await expect(page).toHaveURL(/\/library$/);
  await expect(page.getByRole('heading', { name: 'This page slipped off the shelf.' })).toHaveCount(0);
});
