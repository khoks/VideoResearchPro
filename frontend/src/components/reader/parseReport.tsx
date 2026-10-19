/**
 * Sanitised report HTML → React tree + outline + citations (S-8.8.1).
 *
 * One pass over the DOM with `html-react-parser`'s `replace` hook:
 *   - `h2` / `h3` get stable ids and are collected into the outline;
 *     an `h1` inside the body is demoted to `h2` (the reader owns the page
 *     title) or dropped when it merely repeats the title.
 *   - Anchors whose href carries `&t=SECONDS` are citations and are handed to
 *     `renderCitation`. Reports written before S-1.14.9 carry bare
 *     `href="&t=123"` anchors with no video URL; those become unresolved
 *     citations (`href: null`) instead of dead links.
 *   - Other absolute links open in a new tab with `rel="noopener noreferrer"`.
 *   - Tables are wrapped in a horizontal scroll region (WCAG 1.4.10).
 *   - The first substantial paragraph is tagged for the drop cap.
 *
 * MUST be fed `sanitizeReportHtml` output. The parser does not sanitise.
 */
import type { ReactNode } from 'react';
import parse, {
  attributesToProps,
  domToReact,
  Element,
  Text,
  type DOMNode,
  type HTMLReactParserOptions,
} from 'html-react-parser';
import { makeSlugger } from './slug';

export interface OutlineEntry {
  id: string;
  text: string;
  level: 2 | 3;
}

export interface ReportCitation {
  /** 1-based position in document order. */
  index: number;
  /** Absolute URL when the anchor carried one; null for bare `&t=` anchors. */
  href: string | null;
  /** YouTube id parsed from `v=`; null when absent or not a YouTube URL. */
  videoId: string | null;
  seconds: number | null;
  /** The anchor's visible text, usually an `mm:ss` stamp. */
  label: string;
  /**
   * Text of the enclosing blocks, nearest first (at most two: the `<p>` and,
   * when it sits in one, the `<li>` / cell around it). Pre-S-1.14.9 reports
   * carry no URL on their anchors, so the reader resolves the source by
   * finding a known title or channel in this text (S-8.8.2).
   */
  contexts: string[];
}

export interface ParseReportOptions {
  /** The page title; a body `h1` equal to it is dropped. */
  title?: string;
  renderCitation?: (citation: ReportCitation) => ReactNode;
}

export interface ParsedReport {
  content: ReactNode;
  outline: OutlineEntry[];
  citations: ReportCitation[];
}

const CITATION_HREF = /(?:^|[?&#])t=(\d+)/;
const YOUTUBE_ID = /[?&]v=([\w-]{11})/;
const ABSOLUTE_URL = /^https?:\/\//i;
// A report cut mid-tag by the writer leaves an unterminated attribute that
// swallows the following markup up to the next quote; the browser then hands
// us an "href" full of whitespace and tags. Never link to one.
const GARBAGE_URL = /[\s<>"]/;
const BLOCK_TAGS = new Set([
  'p', 'div', 'section', 'article', 'header', 'footer', 'aside', 'nav',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'table', 'blockquote',
  'pre', 'figure', 'hr', 'dl',
]);
const CONTEXT_TAGS = new Set(['p', 'li', 'td', 'th', 'dd', 'blockquote', 'figcaption']);
const CONTEXT_STOP = new Set(['section', 'article', 'div', 'table', 'ul', 'ol', 'body']);
const CONTEXT_MAX_CHARS = 800;
const DROP_CAP_MIN_CHARS = 120;
const NO_DROP_CAP_PARENTS = new Set(['li', 'td', 'th', 'blockquote', 'figcaption']);

function textOf(node: DOMNode): string {
  if (node instanceof Text) return node.data;
  if (node instanceof Element) return (node.children as DOMNode[]).map(textOf).join('');
  return '';
}

function normalise(text: string): string {
  return text.replace(/\s+/g, ' ').trim().toLowerCase();
}

function contextsOf(node: Element): string[] {
  const out: string[] = [];
  let cur = node.parent;
  while (cur instanceof Element && out.length < 2) {
    if (CONTEXT_TAGS.has(cur.name)) {
      out.push(textOf(cur).replace(/\s+/g, ' ').trim().slice(0, CONTEXT_MAX_CHARS));
    } else if (CONTEXT_STOP.has(cur.name) && out.length > 0) {
      break;
    }
    cur = cur.parent;
  }
  return out;
}

export function parseCitationHref(
  href: string,
  label: string,
  index: number,
  contexts: string[] = [],
): ReportCitation | null {
  const t = CITATION_HREF.exec(href);
  if (!t) return null;
  const absolute = ABSOLUTE_URL.test(href) && !GARBAGE_URL.test(href);
  return {
    index,
    href: absolute ? href : null,
    videoId: absolute ? (YOUTUBE_ID.exec(href)?.[1] ?? null) : null,
    seconds: Number(t[1]),
    label: label.trim() || `${t[1]}s`,
    contexts,
  };
}

export function parseReportHtml(cleanHtml: string, opts: ParseReportOptions = {}): ParsedReport {
  const outline: OutlineEntry[] = [];
  const citations: ReportCitation[] = [];
  const slug = makeSlugger();
  const title = opts.title ? normalise(opts.title) : null;
  const renderCitation =
    opts.renderCitation ??
    ((c: ReportCitation) =>
      c.href ? (
        <a href={c.href} target="_blank" rel="noopener noreferrer">
          {c.label}
        </a>
      ) : (
        <span>{c.label}</span>
      ));
  let dropCapDone = false;

  const options: HTMLReactParserOptions = {
    replace(domNode) {
      if (!(domNode instanceof Element)) return undefined;
      const { name, attribs } = domNode;
      const children = domNode.children as DOMNode[];

      // Belt and braces: the sanitiser already removed these.
      if (name === 'script' || name === 'style') return <></>;

      if (name === 'h1' || name === 'h2' || name === 'h3') {
        const text = textOf(domNode).replace(/\s+/g, ' ').trim();
        if (name === 'h1' && title && normalise(text) === title) return <></>;
        const level: 2 | 3 = name === 'h3' ? 3 : 2;
        const id = slug(text);
        outline.push({ id, text, level });
        const props = attributesToProps(attribs);
        const Tag = level === 3 ? 'h3' : 'h2';
        return (
          <Tag {...props} id={id} tabIndex={-1}>
            {domToReact(children, options)}
          </Tag>
        );
      }

      if (name === 'a') {
        const href = attribs.href ?? '';
        // Block content inside an anchor (a writer's unclosed `<a>` that the
        // browser repaired) belongs to the document, not to the chip: label the
        // citation from the inline run before it and emit the rest after.
        const firstBlock = children.findIndex((n) => n instanceof Element && BLOCK_TAGS.has(n.name));
        const inline = firstBlock === -1 ? children : children.slice(0, firstBlock);
        const rest = firstBlock === -1 ? [] : children.slice(firstBlock);
        const citation = parseCitationHref(
          href,
          inline.map(textOf).join(''),
          citations.length + 1,
          CITATION_HREF.test(href) ? contextsOf(domNode) : [],
        );
        if (citation) {
          citations.push(citation);
          return (
            <>
              {renderCitation(citation)}
              {rest.length > 0 && domToReact(rest, options)}
            </>
          );
        }
        if (GARBAGE_URL.test(href)) {
          // The same repaired-attribute case without a timestamp: keep the
          // text, lose the link.
          return <span>{domToReact(children, options)}</span>;
        }
        const props = attributesToProps(attribs);
        if (ABSOLUTE_URL.test(href)) {
          props.target = '_blank';
          props.rel = 'noopener noreferrer';
        }
        return <a {...props}>{domToReact(children, options)}</a>;
      }

      if (name === 'table') {
        return (
          <div className="reader-table-scroll" role="region" aria-label="Table" tabIndex={0}>
            <table {...attributesToProps(attribs)}>{domToReact(children, options)}</table>
          </div>
        );
      }

      if (name === 'p' && !dropCapDone) {
        const parent = domNode.parent;
        const parentName = parent instanceof Element ? parent.name : '';
        const classes = (attribs.class ?? '').split(/\s+/);
        if (
          !NO_DROP_CAP_PARENTS.has(parentName) &&
          !classes.includes('source') &&
          textOf(domNode).trim().length >= DROP_CAP_MIN_CHARS
        ) {
          dropCapDone = true;
          const props = attributesToProps(attribs);
          props.className = [props.className, 'reader-dropcap'].filter(Boolean).join(' ');
          return <p {...props}>{domToReact(children, options)}</p>;
        }
      }

      return undefined;
    },
  };

  const content = parse(cleanHtml, options);
  return { content, outline, citations };
}
