import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { parseMarkdownDoc } from '../parseMarkdown';
import knowledge from '../__fixtures__/knowledge-claude-code-tasks.md?raw';
import book from '../__fixtures__/book-two-runs.md?raw';

function render(md: string, title?: string) {
  const parsed = parseMarkdownDoc(md, { title });
  return { ...parsed, markup: renderToStaticMarkup(<>{parsed.content}</>) };
}

describe('parseMarkdownDoc', () => {
  it('takes a leading # heading as the document title and drops it from the body', () => {
    const { docTitle, markup, outline } = render('# The Title\n\n## One\n\ntext');
    expect(docTitle).toBe('The Title');
    expect(markup).not.toContain('The Title');
    expect(outline).toEqual([{ id: 'one', text: 'One', level: 2 }]);
  });

  it('demotes a later h1 and drops one that repeats the page title', () => {
    const { markup, outline } = render('intro\n\n# Page Title\n\n# Part Two\n\n### Sub', 'page title');
    expect(markup).not.toContain('Page Title');
    expect(markup).not.toContain('<h1');
    expect(outline).toEqual([
      { id: 'part-two', text: 'Part Two', level: 2 },
      { id: 'sub', text: 'Sub', level: 3 },
    ]);
  });

  it('gives headings stable, deduped, focusable ids', () => {
    const { markup, outline } = render('## Facts\n\n## Facts\n\n### Sub\n\n#### Deep');
    expect(outline.map((o) => o.id)).toEqual(['facts', 'facts-2', 'sub']);
    expect(markup).toContain('<h2 id="facts" tabindex="-1">Facts</h2>');
    expect(markup).toContain('<h2 id="facts-2" tabindex="-1">Facts</h2>');
    expect(markup).toContain('<h4 id="deep">Deep</h4>'); // targetable, not in the outline
  });

  it('never renders raw HTML or unsafe URLs', () => {
    const { markup } = render(
      'Hi <script>alert(1)</script> <img src=x onerror=alert(2)>\n\n' +
        '[bad](javascript:alert(3)) [ok](https://example.test/) ![pic](javascript:alert(4))\n\n' +
        '<iframe src="https://evil.example"></iframe>',
    );
    expect(markup).not.toContain('<script');
    expect(markup).not.toContain('onerror');
    expect(markup).not.toContain('javascript:');
    expect(markup).not.toContain('<iframe');
    expect(markup).toContain('bad'); // the text of the unsafe link survives
    expect(markup).toContain('<a href="https://example.test/" target="_blank" rel="noopener noreferrer">ok</a>');
  });

  it('renders GFM tables inside a scroll region', () => {
    const { markup } = render('| a | b |\n|---|---|\n| 1 | 2 |');
    expect(markup).toMatch(/<div class="reader-table-scroll" role="region" aria-label="Table" tabindex="0"><table>/);
  });

  it('marks the first substantial top-level paragraph for the drop cap only', () => {
    const long = 'word '.repeat(40).trim();
    const { markup } = render(`short\n\n- ${long}\n\n${long}\n\n${long}`);
    expect(markup.match(/reader-dropcap/g)).toHaveLength(1);
    expect(markup).toContain(`<p class="reader-dropcap">${long}</p>`);
  });

  it('builds the outline from the two shallowest heading levels present', () => {
    const { outline } = render('## 1. Chapter\n\n#### Section A\n\n##### Detail\n\n#### Section B');
    expect(outline).toEqual([
      { id: '1-chapter', text: '1. Chapter', level: 2 },
      { id: 'section-a', text: 'Section A', level: 3 },
      { id: 'section-b', text: 'Section B', level: 3 },
    ]);
  });

  it('keeps headings inside list items out of the outline', () => {
    const { outline, markup } = render('## Chapter\n\n- ### In a list\n\n#### Section');
    expect(outline.map((o) => o.text)).toEqual(['Chapter', 'Section']);
    expect(markup).toContain('<h3 id="in-a-list">In a list</h3>');
  });

  it('repoints in-page links whose target was slugged differently', () => {
    const { markup } = render('1. [My Chapter](#my-chapter)\n2. [Exact](#exact)\n\n## 1. My Chapter\n\n## Exact');
    expect(markup).toContain('href="#1-my-chapter"');
    expect(markup).toContain('href="#exact"');
  });
});

describe('parseMarkdownDoc on stored content', () => {
  it('renders a real knowledge report with its own headings as the outline', () => {
    const h2h3 = (knowledge.match(/^#{2,3} /gm) ?? []).length;
    const { docTitle, outline, markup } = render(knowledge);
    expect(docTitle).toBeTruthy();
    expect(outline).toHaveLength(h2h3);
    expect(new Set(outline.map((o) => o.id)).size).toBe(outline.length);
    expect(markup).toContain('reader-dropcap');
    expect(markup).not.toContain('<h1');
  });

  it('renders a real Author Studio book and every table-of-contents link lands on a heading', () => {
    const { docTitle, outline, markup } = render(book, 'Two runs, one book');
    expect(docTitle).toBe('Two runs, one book');
    const ids = new Set(outline.map((o) => o.id));
    const tocTargets = [...markup.matchAll(/href="#([^"]+)"/g)].map((m) => m[1]);
    expect(tocTargets.length).toBeGreaterThanOrEqual(2);
    for (const t of tocTargets) expect(ids.has(t)).toBe(true);
    const chapters = outline.filter((o) => o.level === 2 && /^\d+\. /.test(o.text));
    expect(chapters).toHaveLength(2); // one entry per chapter
    // Each report's sections, nested as h4 in the manuscript, sit under it.
    expect(outline.filter((o) => o.level === 3).map((o) => o.text)).toContain('Executive Summary');
    // S-6.1.2 manuscripts carry GFM tables (statistics, per-channel breakdown).
    expect((markup.match(/reader-table-scroll/g) ?? []).length).toBeGreaterThanOrEqual(2);
  });
});
