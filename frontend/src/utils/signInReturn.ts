/*
 * Where a sign-in ends (T-5.4.20).
 *
 * `ProtectedRoute` sends a signed-out reader to `/login` with the page they
 * wanted in `location.state.from`. `PublicOnlyRoute` reads it the moment a
 * token appears, and that is the only redirect a sign-in makes: a second one
 * in the sign-in page raced it, and `/` often won.
 *
 * Router state does not survive leaving the app, so an OAuth sign-in keeps the
 * same page in this tab's storage for the trip to the provider. The value is
 * only ever a path in this app. A provider's answer on a callback address
 * (`?code=&state=`) is a one-time credential and is left out: such a page
 * comes back bare and asks the reader to start again, as it always has.
 */
const STORAGE_KEY = 'pratidhvani.signInReturn';

const HOME = '/';

function isAppPath(path: string): boolean {
  // `//host` and `/\host` are other sites to a browser.
  return /^\/(?![/\\])/.test(path);
}

function pathOf(from: unknown): string | null {
  if (typeof from === 'string') return isAppPath(from) ? from : null;
  if (!from || typeof from !== 'object') return null;
  const { pathname, search, hash } = from as { pathname?: unknown; search?: unknown; hash?: unknown };
  if (typeof pathname !== 'string' || !isAppPath(pathname)) return null;
  if (pathname.endsWith('/callback')) return pathname;
  return `${pathname}${typeof search === 'string' ? search : ''}${typeof hash === 'string' ? hash : ''}`;
}

function fromOf(state: unknown): unknown {
  return state && typeof state === 'object' ? (state as { from?: unknown }).from : undefined;
}

/** The page a router state asks to return to, or `/`, which the onboarding gate resolves. */
export function signInDestination(state: unknown): string {
  return pathOf(fromOf(state)) ?? HOME;
}

/** Before leaving for an OAuth provider: keep this page's destination in the tab. */
export function rememberSignInDestination(state: unknown): void {
  const path = pathOf(fromOf(state));
  try {
    if (path && path !== HOME) sessionStorage.setItem(STORAGE_KEY, path);
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* blocked storage: the sign-in still works and ends at `/` */
  }
}

/** Back from the provider: the router state that carries the kept destination on. */
export function recallSignInState(): { from: string } | null {
  try {
    const path = pathOf(sessionStorage.getItem(STORAGE_KEY));
    return path ? { from: path } : null;
  } catch {
    return null;
  }
}

export function forgetSignInDestination(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* nothing to forget */
  }
}
