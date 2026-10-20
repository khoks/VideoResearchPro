// Shared logic for the "Add to Echo" extension (S-3.7.3). No chrome.* calls
// here, so `node --test extension/tests` can test it directly.

export const SURFACE = 'browser_ext';
export const TOKEN_PREFIX = 'pec_';
export const DEFAULT_SERVER = 'http://localhost:8000';

/** The context-menu entries. Ids are what `sharePayload` dispatches on. */
export const MENUS = [
  { id: 'echo-page', title: 'Add this page to Echo', contexts: ['page'] },
  { id: 'echo-link', title: 'Add this link to Echo', contexts: ['link'] },
  { id: 'echo-selection', title: 'Add this quote to Echo', contexts: ['selection'] },
  { id: 'echo-image', title: 'Add this image to Echo', contexts: ['image'] },
];

const SHAREABLE = /^https?:\/\//i;

/**
 * The server's origin, from whatever the user pasted: trims spaces and
 * trailing slashes, drops a pasted `/api/v1`, and adds `http://` to a bare
 * `localhost:8000`. Returns null for something that is not an http(s) URL.
 */
export function normaliseServer(raw) {
  let value = String(raw ?? '').trim();
  if (!value) return null;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) value = `http://${value}`;
  let url;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  return url.origin;
}

/** The host permission the extension asks for: this server only. */
export function originPattern(server) {
  const origin = normaliseServer(server);
  return origin ? `${origin}/*` : null;
}

export function looksLikeToken(token) {
  return typeof token === 'string' && token.startsWith(TOKEN_PREFIX) && token.length >= 24;
}

function clip(text, max) {
  const value = String(text ?? '').trim();
  return value.length > max ? value.slice(0, max) : value;
}

/**
 * What to send for a context-menu click: `{ payload }`, or `{ reason }` when
 * there is nothing that can be shared (a browser-internal page, an inline
 * image). Quotes and images keep the page they came from.
 */
export function sharePayload(info, tab, annotation) {
  const note = clip(annotation, 5000) || undefined;
  const pageUrl = info?.pageUrl || tab?.url || '';
  const pageTitle = clip(tab?.title, 300) || undefined;
  const source = SHAREABLE.test(pageUrl) ? { source_url: pageUrl, source_title: pageTitle } : {};
  switch (info?.menuItemId) {
    case 'echo-page':
      if (!SHAREABLE.test(pageUrl)) return { reason: 'Only web pages can be added.' };
      return { payload: { url: pageUrl, annotation: note, surface: SURFACE } };
    case 'echo-link':
      if (!SHAREABLE.test(info.linkUrl || '')) return { reason: 'Only web links can be added.' };
      return { payload: { url: info.linkUrl, annotation: note, surface: SURFACE } };
    case 'echo-selection': {
      const text = clip(info.selectionText, 50000);
      if (!text) return { reason: 'Nothing is selected.' };
      // Someone else's words unless the user says otherwise (D-089).
      return { payload: { text, annotation: note, surface: SURFACE, ...source } };
    }
    case 'echo-image':
      if (!SHAREABLE.test(info.srcUrl || '')) {
        return { reason: 'This image is embedded in the page and has no address to send.' };
      }
      return { payload: { url: info.srcUrl, content_type: 'image', annotation: note, surface: SURFACE, ...source } };
    default:
      return { reason: 'Unknown menu item.' };
  }
}

/** Drop undefined fields so the server sees only what was set. */
export function cleanPayload(payload) {
  return Object.fromEntries(Object.entries(payload).filter(([, v]) => v !== undefined && v !== null && v !== ''));
}

export function errorText(status, detail, server) {
  if (status === 0) return `Could not reach ${server}. Is Pratidhvani running there?`;
  if (status === 401) return 'The token was refused. Make a new one on the Echo page and paste it in the settings.';
  if (status === 403) return detail || 'Echo needs the Studio plan.';
  if (status === 413) return 'Too long to add in one go.';
  if (status === 422) return detail || 'The server could not accept this.';
  if (status === 429) return 'Too many shares just now; try again in a minute.';
  return detail || `The server answered ${status}.`;
}

async function call(fetchFn, server, token, path, init = {}) {
  const origin = normaliseServer(server);
  if (!origin) return { ok: false, status: 0, error: 'Set the server address in the settings first.' };
  let response;
  try {
    response = await fetchFn(`${origin}/api/v1${path}`, {
      ...init,
      headers: { ...(init.headers || {}), Authorization: `Bearer ${token}` },
    });
  } catch {
    return { ok: false, status: 0, error: errorText(0, null, origin) };
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = body && typeof body.detail === 'string' ? body.detail : null;
    return { ok: false, status: response.status, error: errorText(response.status, detail, origin) };
  }
  return { ok: true, status: response.status, body };
}

export function postShare(fetchFn, server, token, payload) {
  return call(fetchFn, server, token, '/echo/shares', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cleanPayload(payload)),
  });
}

export function checkToken(fetchFn, server, token) {
  return call(fetchFn, server, token, '/echo/share-tokens/check');
}
