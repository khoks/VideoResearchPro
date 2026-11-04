import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { parseMarkdownDoc } from '../parseMarkdown';
import manuscript from './fixtures/book-contents.manuscript.txt?raw';

/*
 * T-8.8.4.2: the book outputter takes its contents links from the ids the
 * backend's Markdown parser gives, and the reader parses the same manuscript
 * with another one. The fixture is a real manuscript, kept current by
 * backend/tests/test_services/test_book_toc_anchors.py, with the headings most
 * likely to split the two: a book title equal to a section, repeats, a quoted
 * heading, typed punctuation and Devanagari.
 *
 * The links are read from the Markdown, not from the rendered page: the reader
 * repoints a link it cannot resolve, for books stored before the fix, and this
 * must pass without that help.
 */
const CONTENTS_LINK = /\[((?:\\.|[^\]\\])*)\]\(#([^)]*)\)/g;

function contentsLinks(): [label: string, id: string][] {
  const section = manuscript.split('## Table of Contents')[1].split('\n## ')[0];
  return [...section.matchAll(CONTENTS_LINK)].map(([, label, id]) => [label.replace(/\\(.)/g, '$1'), id]);
}

function render(): Document {
  const { content } = parseMarkdownDoc(manuscript, { title: 'Introduction' });
  const html = renderToStaticMarkup(<>{content}</>);
  return new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html');
}

describe('a book manuscript in the reader', () => {
  it('has the links the fixture promises', () => {
    expect(contentsLinks().map(([, id]) => id)).toEqual([
      'introduction-2',
      'part-i-beginnings-ends',
      '1-att-draft-notes',
      '2-हिंदी-पुस्तक-भाग-१',
      'conclusion-3',
      'glossary-2',
    ]);
  });

  it('gives each contents link the id of the book heading it names', () => {
    const doc = render();
    for (const [label, id] of contentsLinks()) {
      const target = doc.getElementById(id);
      expect(target?.tagName, `no heading for #${id}`).toBe('H2');
      expect(target?.textContent?.endsWith(label), `#${id} is "${target?.textContent}"`).toBe(true);
    }
  });

  it('keeps the links as written, with nothing to repoint', () => {
    const doc = render();
    const hrefs = [...doc.querySelectorAll('a[href^="#"]')].map((a) => decodeURIComponent(a.getAttribute('href')!.slice(1)));
    expect(hrefs).toEqual(contentsLinks().map(([, id]) => id));
  });

  it('shows typed punctuation as typed', () => {
    const doc = render();
    expect(doc.getElementById('1-att-draft-notes')?.textContent).toBe('1. AT&T <draft> ] notes');
    expect(doc.getElementById('part-i-beginnings-ends')?.textContent).toBe('Part I: Beginnings & ends');
  });
});
