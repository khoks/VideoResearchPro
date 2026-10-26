import type { ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { parseCitationHref, parseReportHtml, type ReportCitation } from '../parseReport';
import { ReaderCitation } from '../ReaderCitation';
import { sanitizeReportHtml } from '../sanitize';
import { makeSlugger, slugify } from '../slug';

// Three stored real reports (copied verbatim from the data directory):
// a topic report from before S-1.14.9 (bare `&t=` anchors), a topic report
// with full YouTube URLs, and a channel report with no citations at all.
const fixtures = import.meta.glob('../__fixtures__/*.html', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

function render(html: string, opts?: Parameters<typeof parseReportHtml>[1]) {
  const parsed = parseReportHtml(html, opts);
  return { ...parsed, markup: renderToStaticMarkup(<>{parsed.content}</>) };
}

describe('slugify', () => {
  it('folds case, diacritics and punctuation into hyphenated ids', () => {
    expect(slugify('Executive Summary')).toBe('executive-summary');
    expect(slugify('  Q&A: what’s next?  ')).toBe('qa-whats-next');
    expect(slugify('Café résumé')).toBe('cafe-resume');
    expect(slugify('!!!')).toBe('section');
  });

  it('keeps Devanagari letters', () => {
    expect(slugify('प्रतिध्वनि परिचय')).toBe('प्रतिध्वनि-परिचय');
  });

  it('dedupes repeated headings', () => {
    const slug = makeSlugger();
    expect(slug('Alpha')).toBe('alpha');
    expect(slug('Alpha')).toBe('alpha-2');
    expect(slug('alpha')).toBe('alpha-3');
  });
});

describe('parseCitationHref', () => {
  it('parses a full YouTube URL', () => {
    const c = parseCitationHref('https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=841', '14:01', 1);
    expect(c).toEqual({
      index: 1,
      href: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=841',
      videoId: 'dQw4w9WgXcQ',
      seconds: 841,
      label: '14:01',
      contexts: [],
    });
  });

  it('marks a bare &t= anchor unresolved instead of linking it', () => {
    const c = parseCitationHref('&t=12', '0:12', 2);
    expect(c).toMatchObject({ href: null, videoId: null, seconds: 12, label: '0:12' });
  });

  it('ignores ordinary links', () => {
    expect(parseCitationHref('https://example.test/post', 'post', 1)).toBeNull();
    expect(parseCitationHref('https://example.test/?start=5', 'x', 1)).toBeNull();
  });

  it('never links an href the browser repaired out of a truncated tag', () => {
    const swallowed =
      'https://www.youtube.com/watch?v=5\n<h2>Lost</h2><a href=https://www.youtube.com/watch?v=abcdefghijk&t=9';
    const c = parseCitationHref(swallowed, '0:09', 3);
    expect(c).toMatchObject({ href: null, videoId: null, seconds: 9 });
  });
});

describe('parseReportHtml', () => {
  it('assigns ids to headings and collects the outline in document order', () => {
    const { outline, markup } = render('<h2>Alpha</h2><p>a</p><h3>Beta</h3><h2>Alpha</h2>');
    expect(outline).toEqual([
      { id: 'alpha', text: 'Alpha', level: 2 },
      { id: 'beta', text: 'Beta', level: 3 },
      { id: 'alpha-2', text: 'Alpha', level: 2 },
    ]);
    expect(markup).toContain('<h2 id="alpha" tabindex="-1">Alpha</h2>');
    expect(markup).toContain('<h3 id="beta" tabindex="-1">Beta</h3>');
  });

  it('demotes a body h1 to h2 and drops one that repeats the title', () => {
    const { outline, markup } = render('<h1>The Title</h1><h1>Another</h1><p>x</p>', { title: 'the title ' });
    expect(markup).not.toContain('The Title');
    expect(markup).not.toContain('<h1');
    expect(outline).toEqual([{ id: 'another', text: 'Another', level: 2 }]);
  });

  it('hands every &t= anchor to renderCitation and numbers them', () => {
    const seen: ReportCitation[] = [];
    const { citations, markup } = render(
      '<p>One <a href="https://www.youtube.com/watch?v=abcdefghijk&t=10" target="_blank">0:10</a> ' +
        'two <a href="&t=20" target="_blank">0:20</a> ' +
        'plain <a href="https://example.test/">link</a></p>',
      { renderCitation: (c) => { seen.push(c); return <cite>#{c.index}</cite>; } },
    );
    expect(citations).toHaveLength(2);
    expect(seen.map((c) => c.index)).toEqual([1, 2]);
    expect(seen[0].videoId).toBe('abcdefghijk');
    expect(seen[1].href).toBeNull();
    expect(markup).toContain('<cite>#1</cite>');
    expect(markup).toContain('<cite>#2</cite>');
    // The ordinary link is kept and made safe to open in a new tab.
    expect(markup).toContain('<a href="https://example.test/" target="_blank" rel="noopener noreferrer">link</a>');
  });

  it('renders unresolved citations without an href through ReaderCitation', () => {
    const { markup } = render('<p><a href="&t=5">0:05</a></p>', {
      renderCitation: (c) => <ReaderCitation key={c.index} citation={c} />,
    });
    expect(markup).toContain('reader-citation--unresolved');
    expect(markup).not.toContain('href="&amp;t=5"');
    expect(markup).not.toContain('href="&t=5"');
  });

  it('unlinks an ordinary anchor whose href the browser repaired out of a truncated tag', () => {
    const { citations, markup } = render(
      '<p>x <a href="https://www.youtube.com/watch?v=5\n<h2>Lost</h2>" target="_blank">16:56</a> y</p>',
    );
    expect(citations).toHaveLength(0);
    expect(markup).toBe('<p>x <span>16:56</span> y</p>');
  });

  it('keeps block content a repaired anchor swallowed, after the chip', () => {
    const { outline, citations, markup } = render(
      '<p>See <a href="https://www.youtube.com/watch?v=abcdefghijk&t=10">0:10</a></p>' +
        '<a href="https://www.youtube.com/watch?v=abcdefghijk&t=20">0:20<h2>Swallowed</h2><p>Body text.</p></a>',
      { renderCitation: (c) => <cite>{c.label}</cite> },
    );
    expect(citations.map((c) => c.label)).toEqual(['0:10', '0:20']);
    expect(outline).toEqual([{ id: 'swallowed', text: 'Swallowed', level: 2 }]);
    expect(markup).toContain('<cite>0:20</cite><h2 id="swallowed" tabindex="-1">Swallowed</h2><p>Body text.</p>');
  });

  it('records the enclosing paragraph and list item as citation context', () => {
    const { citations } = render(
      '<ul><li><p>Fact: something.</p><p class="source">Source: Chan — The Title, <a href="&t=7">0:07</a></p></li></ul>' +
        '<section><p>Loose <a href="&t=9">0:09</a></p></section>',
    );
    expect(citations[0].contexts).toEqual([
      'Source: Chan — The Title, 0:07',
      'Fact: something.Source: Chan — The Title, 0:07',
    ]);
    expect(citations[1].contexts).toEqual(['Loose 0:09']);
  });

  it('wraps tables in a scroll region', () => {
    const { markup } = render('<table><tbody><tr><td>1</td></tr></tbody></table>');
    expect(markup).toContain('<div class="reader-table-scroll" role="region" aria-label="Table" tabindex="0"><table>');
  });

  it('tags the first substantial paragraph for the drop cap, skipping sources and list items', () => {
    const long = 'x'.repeat(130);
    const { markup } = render(
      `<ul><li><p>${long}</p></li></ul><p class="source">${long}</p><p>short</p><p>${long}</p><p>${long}</p>`,
    );
    const matches = markup.match(/reader-dropcap/g) ?? [];
    expect(matches).toHaveLength(1);
    expect(markup).toContain(`<li><p>${long}</p></li>`);
    expect(markup).toContain(`<p class="source">${long}</p>`);
    expect(markup).toContain(`<p>short</p><p class="reader-dropcap">${long}</p><p>${long}</p>`);
  });

  it('does not emit script or style even if handed some', () => {
    const { markup } = render('<p>a</p><script>x()</script><style>p{}</style>');
    expect(markup).toBe('<p>a</p>');
  });
});

describe('parseReportHtml processing notes (T-8.8.4.4)', () => {
  const note =
    'the "Key Facts" section was cut off mid-markup on both attempts to write it and was closed ' +
    'where it stopped, so it may end abruptly.';
  const noteMarkup = (p: { processingNotes: ReactNode[] }) => renderToStaticMarkup(<>{p.processingNotes}</>);

  it('lifts the classed note out of the body, without its label', () => {
    const long = 'x'.repeat(130);
    const html = sanitizeReportHtml(
      `<h2>Key Facts</h2><p>${long}</p>` +
        `<p class="processing-note" style="color:#8a6d3b"><strong>Processing note:</strong> ${note}</p>`,
    );
    const parsed = render(html);
    expect(parsed.processingNotes).toHaveLength(1);
    expect(noteMarkup(parsed).trim()).toBe(note.replace(/"/g, '&quot;'));
    expect(parsed.markup).not.toContain('Processing note');
    expect(parsed.markup).not.toContain('cut off mid-markup');
    // The body's own paragraph still gets the drop cap.
    expect(parsed.markup).toContain(`<p class="reader-dropcap">${long}</p>`);
  });

  it('finds a note written before the class by its label', () => {
    // What a stored report looks like after the sanitiser drops `style`.
    const parsed = render(
      sanitizeReportHtml(
        '<p>Body.</p><p style="color:#8a6d3b"><strong>Processing note:</strong> 3 segments could not be analyzed.</p>',
      ),
    );
    expect(parsed.processingNotes).toHaveLength(1);
    expect(noteMarkup(parsed).trim()).toBe('3 segments could not be analyzed.');
    expect(parsed.markup).toBe('<p>Body.</p>');
  });

  it('leaves a report without a note alone', () => {
    const parsed = render('<p><strong>Note:</strong> a body paragraph that starts in bold.</p>');
    expect(parsed.processingNotes).toEqual([]);
    expect(parsed.markup).toContain('a body paragraph that starts in bold.');
  });
});

describe('parseReportHtml on stored real reports', () => {
  const names = Object.keys(fixtures).sort();

  it('ships three fixtures', () => {
    expect(names).toHaveLength(3);
  });

  it.each(names)('%s renders through the full pipeline', (name) => {
    const raw = fixtures[name];
    // Expected counts come from the browser's own reading of the document:
    // one stored report was cut mid-tag by the writer, so a regex over the
    // source would count headings that the DOM folds into an attribute.
    const doc = new DOMParser().parseFromString(raw, 'text/html');
    const title = doc.title;
    const headingCount = doc.querySelectorAll('h2, h3').length;
    const citationCount = Array.from(doc.querySelectorAll('a[href]')).filter((a) =>
      /(?:^|[?&#])t=\d+/.test(a.getAttribute('href') ?? ''),
    ).length;
    const tableCount = doc.querySelectorAll('table').length;
    expect(headingCount).toBeGreaterThan(0);

    const clean = sanitizeReportHtml(raw);
    const { outline, citations, markup } = render(clean, {
      title,
      renderCitation: (c) => <ReaderCitation key={c.index} citation={c} />,
    });

    expect(outline).toHaveLength(headingCount);
    expect(new Set(outline.map((o) => o.id)).size).toBe(outline.length);
    expect(citations).toHaveLength(citationCount);
    expect((markup.match(/class="reader-citation/g) ?? []).length).toBe(citationCount);
    expect((markup.match(/reader-table-scroll/g) ?? []).length).toBe(tableCount);
    expect(markup).not.toContain('<script');
    expect(markup).not.toContain('<style');
    expect(markup).not.toMatch(/<h[23](?![^>]*\bid=)/); // every heading carries an id
    expect(markup).not.toContain('href="&amp;t='); // no dead links
    expect(markup).not.toContain('<h1'); // the shell owns the page title
    expect(markup.length).toBeGreaterThan(1000);
  });
});
