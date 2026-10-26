/**
 * T-8.8.1.5: the quick peek's report document blocks scripts with a CSP meta
 * tag that the parser files into <head> ahead of everything else, so it holds
 * for the top-level "Open in new tab" too, where no sandbox applies.
 */
import { describe, expect, it } from 'vitest';
import { REPORT_DOCUMENT_CSP, REPORT_FRAME_SANDBOX, reportDocumentBlob, withScriptsBlocked } from '../reportDocument';

const REPORT = `<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Research Report: x</title><style>body { color: #222; }</style></head>
<body><h1>Research Report: x</h1><p>Said at <a href="https://www.youtube.com/watch?v=abc&t=12" target="_blank">0:12</a>.</p></body>
</html>`;

function parse(html: string): Document {
  return new DOMParser().parseFromString(html, 'text/html');
}

describe('withScriptsBlocked', () => {
  it('puts the policy first in <head>, after the doctype, and keeps the report intact', () => {
    const out = withScriptsBlocked(REPORT);
    expect(out.startsWith('<!DOCTYPE html><meta http-equiv="Content-Security-Policy"')).toBe(true);
    const doc = parse(out);
    expect(doc.compatMode).toBe('CSS1Compat'); // still standards mode
    const first = doc.head.firstElementChild as HTMLMetaElement;
    expect(first.httpEquiv).toBe('Content-Security-Policy');
    expect(first.content).toBe(REPORT_DOCUMENT_CSP);
    expect(doc.documentElement.lang).toBe('en');
    expect(doc.title).toBe('Research Report: x');
    expect(doc.head.querySelector('style')).not.toBeNull();
    expect(doc.body.querySelector('a[target="_blank"]')?.getAttribute('href')).toContain('youtube.com');
  });

  it('comes before a script anywhere in the document, with or without a doctype', () => {
    for (const html of ['<script>alert(1)</script><p>x</p>', '<html><head><script>alert(1)</script></head></html>']) {
      const doc = parse(withScriptsBlocked(html));
      const first = doc.head.firstElementChild as HTMLMetaElement;
      expect(first.tagName).toBe('META');
      expect(first.httpEquiv).toBe('Content-Security-Policy');
    }
  });

  it('forbids scripts and leaves styles alone', () => {
    expect(REPORT_DOCUMENT_CSP).toContain("script-src 'none'");
    expect(REPORT_DOCUMENT_CSP).not.toMatch(/style-src|default-src/);
  });
});

describe('the frame sandbox', () => {
  it('lets links open tabs and nothing run or share the app’s origin', () => {
    const tokens = REPORT_FRAME_SANDBOX.split(/\s+/);
    expect(tokens).toEqual(expect.arrayContaining(['allow-popups', 'allow-popups-to-escape-sandbox']));
    expect(tokens).not.toContain('allow-scripts');
    expect(tokens).not.toContain('allow-same-origin');
  });
});

describe('reportDocumentBlob', () => {
  it('is HTML carrying the policy', async () => {
    const blob = reportDocumentBlob(REPORT);
    expect(blob.type).toBe('text/html;charset=utf-8');
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob);
    });
    expect(text).toContain(`content="${REPORT_DOCUMENT_CSP}"`);
  });
});
