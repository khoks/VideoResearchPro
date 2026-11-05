/*
 * A session the server stopped accepting (T-5.4.22).
 *
 * This is the one place a 401 ends a session. It takes the token out of storage
 * and tells `AuthProvider`, which ends the session in React; `ProtectedRoute`
 * then sends the reader to the sign-in page with the page they were on, and
 * `PublicOnlyRoute` brings them back through `utils/signInReturn.ts`. Nothing
 * here navigates, so a 401 on a public page leaves that page where it is.
 *
 * A refusal only counts for the token it refused. A page opens several requests
 * at once, and one that was still on its way when the reader signed in again
 * must not take the new session with it.
 *
 * Kept apart from `api.ts` so the streaming Q&A path, which uses `fetch`, ends a
 * session the same way as everything that goes through the client.
 */
export const AUTH_TOKEN_KEY = 'videoresearchpro.authToken';

const EXPIRED = 'pratidhvani:session-expired';

/** A request carrying `token` came back 401. */
export function sessionRefused(token: string | null | undefined): void {
  if (!token || localStorage.getItem(AUTH_TOKEN_KEY) !== token) return;
  localStorage.removeItem(AUTH_TOKEN_KEY);
  window.dispatchEvent(new Event(EXPIRED));
}

/** For `AuthProvider`. Returns the way to stop listening. */
export function onSessionExpired(listener: () => void): () => void {
  window.addEventListener(EXPIRED, listener);
  return () => window.removeEventListener(EXPIRED, listener);
}
