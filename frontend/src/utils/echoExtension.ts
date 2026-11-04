/*
 * Pure logic for adding to Echo from outside the app: the "Add to Echo"
 * browser extension (S-3.7.3) and the iPhone Shortcut (T-3.7.6.1).
 */

/**
 * The server address the extension should send to: the origin of the API.
 * In development the API lives on another port than the app (axios has an
 * absolute base URL); in production the base is relative and the API shares
 * the app's origin.
 */
export function apiOrigin(baseURL: string | undefined, windowOrigin: string): string {
  try {
    return new URL(baseURL || '/', windowOrigin).origin;
  } catch {
    return windowOrigin;
  }
}

/** The address a share is posted to, absolute: a Shortcut lives on a phone. */
export function sharesEndpoint(baseURL: string | undefined, windowOrigin: string): string {
  const base = (baseURL || '/api/v1').replace(/\/+$/, '');
  try {
    return new URL(`${base}/echo/shares`, windowOrigin).href;
  } catch {
    return `${windowOrigin}/api/v1/echo/shares`;
  }
}

/**
 * The iPhone Shortcut, step by step. iOS has no share target for web apps, so
 * a Shortcut posts to the same route as the extension. The token goes in a
 * header, never in the address. Repeated in docs/echo-share-surfaces.md.
 */
export function iosShortcutSteps(endpoint: string): string[] {
  const post = `Get Contents of URL: ${endpoint}, Method POST, a header Authorization with the value "Bearer" then a space then your token, Request Body JSON`;
  return [
    'In the Shortcuts app, make a new Shortcut and name it Add to Echo. In its details, turn on Show in Share Sheet, and set it to receive URLs, Safari web pages and Text.',
    'Add Get URLs from Input, with the Shortcut Input.',
    'Add If, on the URLs, with the condition has any value.',
    `Inside If, add ${post}, with two Text fields: url set to the URLs, and surface set to os_share.`,
    `Under Otherwise, add ${post}, with two Text fields: text set to the Shortcut Input, and surface set to os_share.`,
    'Share a page to Add to Echo. It lands in your inbox as context, not as your own words.',
  ];
}

/** "Used 3 days ago" style label for a token's last use. */
export function lastUsedLabel(lastUsedAt: string | null, now: Date = new Date()): string {
  if (!lastUsedAt) return 'Never used';
  const then = new Date(lastUsedAt);
  const minutes = Math.round((now.getTime() - then.getTime()) / 60_000);
  if (!Number.isFinite(minutes) || minutes < 0) return 'Used just now';
  if (minutes < 2) return 'Used just now';
  if (minutes < 60) return `Used ${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `Used ${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
  const days = Math.round(hours / 24);
  return `Used ${days} ${days === 1 ? 'day' : 'days'} ago`;
}
