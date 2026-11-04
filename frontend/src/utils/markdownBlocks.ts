/**
 * Markdown read just far enough to lay out as text (T-8.8.4.5): paragraphs,
 * headings, lists and code blocks, with the inline marks taken off.
 *
 * What the page shows while the real renderer's chunk arrives, or for good if
 * it cannot load. The blocks become the same elements react-markdown would
 * write, so the styles that apply are the same and the text does not move when
 * the real one replaces it. No dependency, on purpose: this stays in the main
 * chunk. Not a parser: tables, nested lists and quotes read as paragraphs.
 */
export type MarkdownBlock =
  | { kind: 'heading'; level: 1 | 2 | 3 | 4 | 5 | 6; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] };

const HEADING = /^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$/;
const LIST_ITEM = /^\s*(?:[-*+]|(\d+)[.)])\s+(.*)$/;
const FENCE = /^\s*(```|~~~)/;
const LINK = /!?\[([^\]]*)\]\([^)]*\)/g;
// `_` is left alone: it is in more names than emphasis.
const INLINE_MARK = /\*\*|__|~~|[*`]/g;
const QUOTE_MARK = /^\s*>\s?/;

function plain(text: string): string {
  return text.replace(LINK, '$1').replace(INLINE_MARK, '').trim();
}

export function markdownBlocks(source: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let code: string[] | null = null;

  const endParagraph = () => {
    if (paragraph.length > 0) blocks.push({ kind: 'paragraph', text: plain(paragraph.join(' ')) });
    paragraph = [];
  };

  for (const line of source.split(/\r?\n/)) {
    if (code) {
      if (FENCE.test(line)) {
        blocks.push({ kind: 'code', text: code.join('\n') });
        code = null;
      } else {
        code.push(line);
      }
      continue;
    }
    if (FENCE.test(line)) {
      endParagraph();
      code = [];
      continue;
    }
    if (!line.trim()) {
      endParagraph();
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      endParagraph();
      blocks.push({ kind: 'heading', level: heading[1].length as 1 | 2 | 3 | 4 | 5 | 6, text: plain(heading[2]) });
      continue;
    }
    const item = LIST_ITEM.exec(line);
    if (item) {
      endParagraph();
      const ordered = item[1] !== undefined;
      const last = blocks[blocks.length - 1];
      if (last?.kind === 'list' && last.ordered === ordered) last.items.push(plain(item[2]));
      else blocks.push({ kind: 'list', ordered, items: [plain(item[2])] });
      continue;
    }
    paragraph.push(line.replace(QUOTE_MARK, ''));
  }
  endParagraph();
  if (code) blocks.push({ kind: 'code', text: code.join('\n') });
  return blocks;
}
