import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { parseMarkdownDoc } from '../../components/reader';

/*
 * S-6.1.4: a book's endnotes are GFM footnotes written by
 * `output_citation_service` (backend). This renders a manuscript in exactly
 * the shape the book outputter writes, through the reading room's own
 * Markdown pipeline, and checks every footnote reference and the table of
 * contents land on an element that exists.
 */
const BOOK = [
  '# The Book',
  '',
  '## Table of Contents',
  '',
  '1. [First Topic](#1-first-topic)',
  '2. [हिंदी पुस्तक — भाग १](#2-हिंदी-पुस्तक-भाग-१)',
  '',
  '## 1. First Topic',
  '',
  '#### Key Facts',
  '',
  '- **Fact:** prices rose.',
  '',
  '  **Source:** *Inflation and the long run*, [1:15](https://www.youtube.com/watch?v=abcdefghijk&t=75)[^1]',
  '- **Fact:** unknown, 0:09[^2]',
  '',
  '## 2. हिंदी पुस्तक — भाग १',
  '',
  'Body [0:30](https://www.youtube.com/watch?v=abcdefghijk&t=30)[^3].',
  '',
  '## Endnotes',
  '',
  '[^1]: *Inflation and the long run* — Macro Minute, 1:15. <https://www.youtube.com/watch?v=abcdefghijk&t=75>',
  '[^2]: Source not identified (cited as 0:09).',
  '[^3]: *Inflation and the long run* — Macro Minute, 0:30. <https://www.youtube.com/watch?v=abcdefghijk&t=30>',
  '',
].join('\n');

function render(md: string): Document {
  const { content } = parseMarkdownDoc(md, { title: 'The Book' });
  const html = renderToStaticMarkup(<>{content}</>);
  return new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html');
}

describe('book endnotes in the reading room (S-6.1.4)', () => {
  it('every footnote reference links to a definition that exists', () => {
    const doc = render(BOOK);
    const refs = [...doc.querySelectorAll('a[data-footnote-ref]')];
    expect(refs.map((a) => a.textContent)).toEqual(['1', '2', '3']);
    for (const a of refs) {
      const id = decodeURIComponent(a.getAttribute('href')!.slice(1));
      expect(doc.getElementById(id), `missing target for ${id}`).not.toBeNull();
    }
    const items = doc.querySelectorAll('section[data-footnotes] li');
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toContain('Macro Minute, 1:15');
    expect(items[1].textContent).toContain('Source not identified');
  });

  it('table-of-contents links point at the chapter headings, Devanagari included', () => {
    const doc = render(BOOK);
    const toc = [...doc.querySelectorAll('a[href^="#"]')].filter((a) => !a.hasAttribute('data-footnote-ref') && !a.hasAttribute('data-footnote-backref'));
    expect(toc.length).toBe(2);
    for (const a of toc) {
      const id = decodeURIComponent(a.getAttribute('href')!.slice(1));
      const target = doc.getElementById(id);
      expect(target?.tagName, `TOC link ${id}`).toMatch(/^H[1-6]$/);
    }
  });

  it('timestamp links open the source in a new tab', () => {
    const doc = render(BOOK);
    const ts = [...doc.querySelectorAll('a[href^="https://www.youtube.com/"]')];
    expect(ts.length).toBeGreaterThanOrEqual(2);
    expect(ts.every((a) => a.getAttribute('target') === '_blank')).toBe(true);
  });
});
