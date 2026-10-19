/**
 * Report HTML sanitiser (S-8.8.1).
 *
 * Reports are LLM-written HTML stored on disk and served back verbatim; the
 * reader renders them inside the app's own DOM instead of an iframe, so every
 * byte goes through DOMPurify first. `html-react-parser` downstream is
 * explicitly NOT a sanitiser and is only ever fed this function's output.
 *
 * DOMPurify is dual-licensed MPL-2.0 / Apache-2.0; this project elects the
 * **Apache-2.0** terms (recorded here per T-8.8.1.2, as `requirements.txt`
 * comments do for the backend).
 *
 * Policy beyond the defaults:
 *   - `style` and `script` elements are dropped with their contents so the
 *     report's embedded stylesheet never fights the reader's typography.
 *   - The `style` attribute is dropped for the same reason.
 *   - Embedding and form elements, SVG and MathML are dropped: a report has no
 *     use for them and each is an mXSS surface.
 *   - `target` is allowed through so "open in new tab" anchors survive; the
 *     parser adds `rel="noopener noreferrer"` when it rebuilds them.
 */
import DOMPurify from 'dompurify';

const FORBID_TAGS = [
  'style',
  'script',
  'iframe',
  'object',
  'embed',
  'form',
  'input',
  'button',
  'textarea',
  'select',
  'link',
  'meta',
  'base',
  'title',
  'svg',
  'math',
  'noscript',
  'template',
];

export function sanitizeReportHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    FORBID_TAGS,
    FORBID_ATTR: ['style'],
    ADD_ATTR: ['target'],
    ALLOW_DATA_ATTR: false,
  });
}
