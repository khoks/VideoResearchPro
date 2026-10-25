// Files the API serves behind the bearer header, handed to the browser as
// blob: URLs (T-8.8.1.5, D-085 addendum).
//
// A browser navigation (<a href>, <a download>, window.open, <iframe src>)
// cannot send the Authorization header the axios client adds, and a JWT put
// in the URL instead leaks into history, server and proxy logs and Referer
// headers. So the bytes are fetched through the client and the browser gets
// an object URL. Since T-8.8.1.5 no HTTP route accepts `?token=`; the only
// URL token left is the /ws/jobs WebSocket's (services/wsClient.ts), because
// a WebSocket handshake cannot carry headers either.
import api from './api';
import { downloadUrl } from '../utils/download';

const API_PREFIX = '/api/v1';

/** How long a handed-over blob: URL stays alive. A new tab or a download
 * reads it at once; the delay only bounds how long the bytes stay pinned. */
export const BLOB_URL_TTL_MS = 60_000;

/**
 * Split a stored or written URL (`/api/v1/library/pdf/<digest>.pdf#page=3`)
 * into the path the axios client wants (relative to its `/api/v1` base) and
 * the fragment, which never goes to the server but must reach the viewer.
 */
export function splitApiUrl(url: string): { path: string; fragment: string } {
  const hashAt = url.indexOf('#');
  const fragment = hashAt >= 0 ? url.slice(hashAt) : '';
  let path = hashAt >= 0 ? url.slice(0, hashAt) : url;
  if (/^https?:\/\//i.test(path)) {
    try {
      const u = new URL(path);
      path = `${u.pathname}${u.search}`;
    } catch {
      /* not a URL after all; use it as written */
    }
  }
  if (path.startsWith(API_PREFIX)) path = path.slice(API_PREFIX.length);
  return { path, fragment };
}

/**
 * Whether an href points at this app's own API, so a plain navigation to it
 * would arrive without the header and 401. Relative `/api/v1/...` paths, and
 * absolute ones on this origin or on the API client's own base URL.
 */
export function isApiUrl(href: string | null | undefined): boolean {
  if (!href) return false;
  if (href.startsWith(`${API_PREFIX}/`)) return true;
  if (!/^https?:\/\//i.test(href)) return false;
  try {
    const u = new URL(href);
    if (!u.pathname.startsWith(`${API_PREFIX}/`)) return false;
    const origins = new Set([window.location.origin]);
    try {
      if (api.defaults.baseURL) origins.add(new URL(api.defaults.baseURL, window.location.origin).origin);
    } catch {
      /* a malformed base URL only narrows the check */
    }
    return origins.has(u.origin);
  } catch {
    return false;
  }
}

/** Fetch an API file with the bearer header. */
export async function fetchApiBlob(url: string): Promise<Blob> {
  const { path } = splitApiUrl(url);
  const { data } = await api.get<Blob>(path, { responseType: 'blob' });
  return data;
}

/** Open bytes in a new tab. `fragment` (`#page=3`) survives on the blob URL,
 * which is how a PDF citation still lands on its page. */
export function openBlobInNewTab(blob: Blob, fragment = ''): void {
  const blobUrl = URL.createObjectURL(blob);
  window.open(`${blobUrl}${fragment}`, '_blank', 'noopener');
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), BLOB_URL_TTL_MS);
}

/** Save bytes as a file through a transient `<a download>`. */
export function saveBlob(blob: Blob, filename: string): void {
  const blobUrl = URL.createObjectURL(blob);
  downloadUrl(blobUrl, filename);
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), BLOB_URL_TTL_MS);
}

/** Fetch an API file with the header and open it in a new tab, keeping any
 * fragment of `url`. */
export async function openApiFile(url: string): Promise<void> {
  const { fragment } = splitApiUrl(url);
  openBlobInNewTab(await fetchApiBlob(url), fragment);
}

/**
 * Click handling for an `<a>` whose href may be an API file (a PDF citation's
 * `/api/v1/library/pdf/<digest>.pdf#page=3`). Followed as a link it would
 * arrive without the header and 401 in the new tab, so a click or a middle
 * click fetches the file and opens its blob URL instead, `#page=` intact.
 * Anything else (another site, a right click) is left to the browser.
 * Returns whether it took the event.
 */
export function openApiLink(
  e: { preventDefault(): void; button?: number },
  href: string | null | undefined,
  onError?: () => void,
): boolean {
  if (!href || !isApiUrl(href)) return false;
  if (e.button != null && e.button > 1) return false;
  e.preventDefault();
  openApiFile(href).catch(() => onError?.());
  return true;
}

/** Fetch an API file with the header and save it as `filename`. */
export async function downloadApiFile(url: string, filename: string): Promise<void> {
  saveBlob(await fetchApiBlob(url), filename);
}
