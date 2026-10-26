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
 * The API files a click may open in a tab, and the one type each opens as.
 *
 * A blob: URL shown top-level takes this app's origin, so whatever it renders
 * runs beside the app's storage, where the JWT lives. A citation's href can
 * be written by the model (a report chip's own href wins over the server's),
 * so a generic "fetch any /api/v1 href and open it" would hand a
 * prompt-injected link an authenticated GET whose body renders on the app's
 * origin. Only these routes are fetched for a tab, and their bytes are
 * re-wrapped in the type the route serves, whatever Content-Type came back,
 * so they can never open as HTML or SVG. Any other API href is left to the
 * browser, where it arrives without the header and 401s. The report's own
 * "Open in new tab" is a separate path with its own guard
 * (utils/reportDocument.ts).
 */
export const OPENABLE_API_FILES: ReadonlyArray<{ prefix: string; type: string }> = [
  { prefix: '/library/pdf/', type: 'application/pdf' },
];

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

/**
 * The openable API file an href names (see OPENABLE_API_FILES), or null:
 * the path to fetch, relative to the API base, the fragment to keep and the
 * type the bytes open as. Dot segments are resolved first, the way the
 * browser resolves them when the request goes out, so
 * `/api/v1/library/pdf/../../jobs/x/report` is the report route, not a PDF.
 */
export function openableApiFile(
  href: string | null | undefined,
): { path: string; fragment: string; type: string } | null {
  if (!href || !isApiUrl(href)) return null;
  const { path, fragment } = splitApiUrl(href);
  let resolved: URL;
  try {
    resolved = new URL(`${API_PREFIX}${path}`, window.location.origin);
  } catch {
    return null;
  }
  if (!resolved.pathname.startsWith(`${API_PREFIX}/`)) return null;
  const apiPath = resolved.pathname.slice(API_PREFIX.length);
  const file = OPENABLE_API_FILES.find((f) => apiPath.startsWith(f.prefix));
  return file ? { path: `${apiPath}${resolved.search}`, fragment, type: file.type } : null;
}

/** The browser refused the new tab a file was to open in (pop-ups blocked). */
export class TabBlockedError extends Error {
  constructor() {
    super('The browser blocked the new tab.');
    this.name = 'TabBlockedError';
  }
}

/** Fetch an API file with the bearer header. */
export async function fetchApiBlob(url: string): Promise<Blob> {
  const { path } = splitApiUrl(url);
  const { data } = await api.get<Blob>(path, { responseType: 'blob' });
  return data;
}

/** Open bytes the caller already holds in a new tab. `fragment` survives on
 * the blob URL. For bytes still to be fetched use openApiFile, which opens
 * the tab before it waits. */
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

/**
 * Fetch an openable API file (OPENABLE_API_FILES) with the header and show
 * it in a new tab, keeping any fragment of `url` (`#page=3` lands a PDF on
 * its page). Call it from the click itself.
 *
 * The tab is opened before the download, while the click's user activation
 * lasts. A window.open after the await is blocked once that has passed
 * (about 5 s in Chrome and Firefox, any async gap in Safari), and with
 * 'noopener' it returns null even when it succeeds, so a blocked tab could
 * not even be noticed. Opened without 'noopener' the handle comes back; the
 * opener link is cut by hand and the blob URL is set once the bytes arrive.
 * A tab the browser refuses rejects with TabBlockedError; a failed fetch
 * closes the tab and rejects with the fetch's error.
 */
export async function openApiFile(url: string): Promise<void> {
  const file = openableApiFile(url);
  if (!file) throw new Error('Not an API file that opens in a tab.');
  const tab = window.open('', '_blank');
  if (!tab) throw new TabBlockedError();
  tab.opener = null;
  try {
    tab.document.title = 'Opening…';
    tab.document.body.textContent = 'Opening the file…';
  } catch {
    /* cosmetic only */
  }
  let blob: Blob;
  try {
    blob = (await api.get<Blob>(file.path, { responseType: 'blob' })).data;
  } catch (err) {
    tab.close();
    throw err;
  }
  if (tab.closed) return; // the reader gave up waiting
  const blobUrl = URL.createObjectURL(new Blob([blob], { type: file.type }));
  tab.location.href = `${blobUrl}${file.fragment}`;
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), BLOB_URL_TTL_MS);
}

/**
 * Click handling for an `<a>` whose href may be an openable API file (a PDF
 * citation's `/api/v1/library/pdf/<digest>.pdf#page=3`). Followed as a link
 * it would arrive without the header and 401 in the new tab, so a click or a
 * middle click fetches the file and opens its blob URL instead, `#page=`
 * intact. Anything else (another site, any other API route, a right click)
 * is left to the browser. Returns whether it took the event.
 */
export function openApiLink(
  e: { preventDefault(): void; button?: number },
  href: string | null | undefined,
  onError?: (err: unknown) => void,
): boolean {
  if (!href || !openableApiFile(href)) return false;
  if (e.button != null && e.button > 1) return false;
  e.preventDefault();
  openApiFile(href).catch((err: unknown) => onError?.(err));
  return true;
}

/** Fetch an API file with the header and save it as `filename`. */
export async function downloadApiFile(url: string, filename: string): Promise<void> {
  saveBlob(await fetchApiBlob(url), filename);
}
