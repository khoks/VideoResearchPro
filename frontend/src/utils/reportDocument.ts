// The stored HTML report as a document the browser can show without a token
// in its URL (T-8.8.1.5, D-085 addendum).
//
// The quick peek fetches `GET /jobs/{id}/report` with the bearer header and
// frames the bytes as a blob: URL. A blob: URL takes the app's own origin, so
// the document is locked twice:
//  - the frame is sandboxed without `allow-scripts` or `allow-same-origin`.
//    A report is a <style> block and markup (the compose prompt forbids
//    <script>), so nothing in it needs to run, and an opaque origin keeps it
//    away from the app's storage, where the JWT lives. `allow-popups` and
//    `allow-popups-to-escape-sandbox` let its `target="_blank"` source links
//    open normally in a new tab.
//  - a Content-Security-Policy meta tag forbidding scripts is written in
//    ahead of everything else, because "Open in new tab" shows the same bytes
//    top-level, where no sandbox applies.

/** The quick-peek iframe's sandbox: links may open tabs, nothing may run. */
export const REPORT_FRAME_SANDBOX = 'allow-popups allow-popups-to-escape-sandbox';

/** No scripts (inline, handlers or `javascript:` URLs), plugins, base
 * rewrites or form posts. Styles and images are left alone. */
export const REPORT_DOCUMENT_CSP = "script-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";

const CSP_META = `<meta http-equiv="Content-Security-Policy" content="${REPORT_DOCUMENT_CSP}">`;

const DOCTYPE = /^\s*<!doctype[^>]*>/i;

/**
 * The report with the CSP meta tag first, so it is in force before any later
 * markup is parsed: straight after the doctype (keeping standards mode), else
 * at the very start. The parser files a leading <meta> into an implied <head>,
 * which is where a CSP meta tag must be to count.
 */
export function withScriptsBlocked(html: string): string {
  const doctype = DOCTYPE.exec(html);
  if (doctype) return `${doctype[0]}${CSP_META}${html.slice(doctype[0].length)}`;
  return `${CSP_META}${html}`;
}

export function reportDocumentBlob(html: string): Blob {
  return new Blob([withScriptsBlocked(html)], { type: 'text/html;charset=utf-8' });
}
