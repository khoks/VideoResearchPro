/*
 * Pure logic for connecting the "Add to Echo" browser extension (S-3.7.3).
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
