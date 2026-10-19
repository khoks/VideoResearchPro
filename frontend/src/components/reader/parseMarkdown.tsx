/**
 * Markdown → React tree + outline for the reading room (S-8.8.3).
 *
 * Knowledge reports and Author Studio books are Markdown; reports are HTML.
 * Both end up in `ReaderShell` with the same outline, heading ids, table
 * scroll regions and drop cap, so this mirrors `parseReportHtml` for the
 * Markdown side.
 *
 * One deterministic pass in a `useMemo`, not `<ReactMarkdown>` plus a second
 * parse for the outline: the shell needs the outline before the body
 * renders, and two pipelines that must agree on every heading id drift.
 * The steps are react-markdown's own (remark-parse → remark-gfm →
 * remark-rehype → hast-util-to-jsx-runtime) with one tree transform between
 * them.
 *
 * Safety: remark-rehype is run without `allowDangerousHtml`, so raw HTML in
 * the Markdown is dropped, never rendered; link and image URLs go through
 * react-markdown's `defaultUrlTransform`, which blanks `javascript:` and
 * other non-allow-listed protocols. No DOMPurify needed on this path.
 */
import type { ReactNode } from 'react';
import type { Element, ElementContent, Root, RootContent } from 'hast';
import { toJsxRuntime } from 'hast-util-to-jsx-runtime';
import { Fragment, jsx, jsxs } from 'react/jsx-runtime';
import { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkParse from 'remark-parse';
import remarkRehype from 'remark-rehype';
import { unified } from 'unified';
import type { OutlineEntry } from './parseReport';
import { makeSlugger, slugify } from './slug';

export interface ParsedMarkdown {
  content: ReactNode;
  outline: OutlineEntry[];
  /** The document's own leading `# Title`, removed from the body. */
  docTitle: string | null;
}

export interface ParseMarkdownOptions {
  /** The page title; a body `h1` equal to it is dropped. */
  title?: string | null;
}

const DROP_CAP_MIN_CHARS = 120;
const ABSOLUTE_URL = /^https?:\/\//i;
const NESTING = new Set(['li', 'td', 'th', 'blockquote', 'dd']);

const processor = unified().use(remarkParse).use(remarkGfm).use(remarkRehype);

function isElement(node: RootContent | ElementContent): node is Element {
  return node.type === 'element';
}

function textOf(node: RootContent | ElementContent | Root): string {
  if (node.type === 'text') return node.value;
  if ('children' in node) return (node.children as ElementContent[]).map(textOf).join('');
  return '';
}

function norm(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

function addClass(el: Element, name: string) {
  const existing = el.properties.className;
  const list = Array.isArray(existing) ? existing.map(String) : existing ? [String(existing)] : [];
  el.properties.className = [...list, name];
}

function transform(root: Root, opts: ParseMarkdownOptions): { outline: OutlineEntry[]; docTitle: string | null } {
  const outline: OutlineEntry[] = [];
  const slug = makeSlugger();
  const ids = new Set<string>();
  const fragmentLinks: Element[] = [];
  const pageTitle = opts.title ? norm(opts.title).toLowerCase() : null;

  // 1. A leading `# Title` is the document's title, not body text.
  let docTitle: string | null = null;
  const first = root.children.find(isElement);
  if (first && first.tagName === 'h1') {
    docTitle = norm(textOf(first));
    root.children = root.children.filter((n) => n !== first);
  }

  // 2. Which heading depths feed the outline: the two shallowest present
  //    below the title. Usually h2 / h3, but a book nests each report's
  //    sections as h4 / h5 under its "## n. Chapter" heading, and an
  //    h2 / h3-only outline would then list chapters and nothing inside them.
  //    Headings inside list items, cells or quotes are content, not
  //    structure (a report that put <h3> in an <li> converts to
  //    "- ### Speaker"): they get ids but neither choose a depth nor join
  //    the outline.
  const depths = new Set<number>();
  const collect = (node: Root | Element, nested: boolean) => {
    for (const child of node.children as ElementContent[]) {
      if (!isElement(child)) continue;
      const m = /^h([1-6])$/.exec(child.tagName);
      if (m && !nested) depths.add(m[1] === '1' ? 2 : Number(m[1]));
      collect(child, nested || NESTING.has(child.tagName));
    }
  };
  collect(root, false);
  const [outerDepth, innerDepth] = [...depths].sort((a, b) => a - b);

  // 3. Headings, links, images, tables.
  const visit = (parent: Root | Element, nested = false) => {
    parent.children = (parent.children as ElementContent[]).flatMap((node): ElementContent[] => {
      if (!isElement(node)) return [node];
      const name = node.tagName;

      if (name === 'h1' && pageTitle && norm(textOf(node)).toLowerCase() === pageTitle) return [];
      if (name === 'h1') node.tagName = 'h2';

      if (/^h[2-6]$/.test(node.tagName)) {
        const text = norm(textOf(node));
        const id = slug(text);
        ids.add(id);
        node.properties.id = id;
        const depth = Number(node.tagName[1]);
        if (!nested && (depth === outerDepth || depth === innerDepth)) {
          node.properties.tabIndex = -1;
          outline.push({ id, text, level: depth === outerDepth ? 2 : 3 });
        }
      }

      if (name === 'a') {
        const href = defaultUrlTransform(String(node.properties.href ?? ''));
        if (!href) {
          visit(node, nested);
          return node.children; // unsafe or empty link: keep the text
        }
        node.properties.href = href;
        if (href.startsWith('#')) fragmentLinks.push(node);
        else if (ABSOLUTE_URL.test(href)) {
          node.properties.target = '_blank';
          node.properties.rel = ['noopener', 'noreferrer'];
        }
      }

      if (name === 'img') {
        const src = defaultUrlTransform(String(node.properties.src ?? ''));
        if (!src) return [];
        node.properties.src = src;
        node.properties.loading = 'lazy';
      }

      visit(node, nested || NESTING.has(name));

      if (name === 'table') {
        return [
          {
            type: 'element',
            tagName: 'div',
            properties: { className: ['reader-table-scroll'], role: 'region', ariaLabel: 'Table', tabIndex: 0 },
            children: [node],
          },
        ];
      }
      return [node];
    });
  };
  visit(root);

  // 4. In-page links whose target was slugged differently. The book
  //    outputter writes its table of contents against its own slug of the
  //    bare chapter title, while the heading reads "1. Title", so a link to
  //    `#title` belongs to the heading `1-title`.
  for (const a of fragmentLinks) {
    const raw = String(a.properties.href).slice(1);
    let frag = raw;
    try {
      frag = decodeURIComponent(raw);
    } catch {
      /* keep raw */
    }
    if (ids.has(frag)) continue;
    const want = slugify(frag);
    const match = [...ids].find((id) => id === want || id.endsWith(`-${want}`));
    if (match) a.properties.href = `#${match}`;
  }

  // 5. Drop cap on the first substantial top-level paragraph.
  const lead = root.children.find(
    (n): n is Element => isElement(n) && n.tagName === 'p' && norm(textOf(n)).length >= DROP_CAP_MIN_CHARS,
  );
  if (lead) addClass(lead, 'reader-dropcap');

  return { outline, docTitle };
}

export function parseMarkdownDoc(markdown: string, opts: ParseMarkdownOptions = {}): ParsedMarkdown {
  const tree = processor.runSync(processor.parse(markdown)) as Root;
  const { outline, docTitle } = transform(tree, opts);
  const content = toJsxRuntime(tree, { Fragment, jsx, jsxs, ignoreInvalidStyle: true, passKeys: true });
  return { content, outline, docTitle };
}
