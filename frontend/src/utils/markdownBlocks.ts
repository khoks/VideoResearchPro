/**
 * Markdown read just far enough to lay out as text (T-8.8.4.5): paragraphs,
 * headings, lists and code blocks (`markdownBlocks`), then the inline marks
 * inside each (`inlineRuns`).
 *
 * What the page shows while the real renderer's chunk arrives, or for good if
 * it cannot load. The blocks become the same elements react-markdown would
 * write, so the styles that apply are the same and the text does not move when
 * the real one replaces it. Bold and inline code stay for the same reason: an
 * answer that opens in bold wraps a line later than one that does not, and on
 * a phone that line moves the whole thread. No dependency, on purpose: this
 * stays in the main chunk. Not a parser: tables, nested lists and quotes read
 * as paragraphs.
 *
 * This text can stay for the life of the tab, so it must not change what an
 * answer says: a mark comes off only as half of a pair, and anything else
 * stays as written.
 */
export type MarkdownBlock =
  | { kind: 'heading'; level: 1 | 2 | 3 | 4 | 5 | 6; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] };

export type InlineRun = { text: string; bold?: boolean; code?: boolean };

const HEADING = /^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$/;
const LIST_ITEM = /^\s*(?:[-*+]|(\d+)[.)])\s+(.*)$/;
const FENCE = /^\s*(```|~~~)/;
const QUOTE_MARK = /^\s*>\s?/;
// One pass from the left, so a mark inside code is a character. In order: an
// escaped character, code, a link or image, bold, emphasis, strikethrough. As
// in Markdown, `*` pairs only around text: `2 * 3` is arithmetic, and `**kwargs`
// with no partner is a name. `_` is left alone: it is in more names than
// emphasis. No lookbehind, which a browser that lacks it refuses at parse time,
// taking the whole main chunk with it.
const INLINE =
  /\\([!-/:-@[-`{-~])|(`+)(.+?)\2(?!`)|!?\[([^\]]*)\]\([^)]*\)|\*\*(?=\S)(.*?\S)\*\*|\*([^\s*](?:[^*]*[^\s*])?)\*|~~(?=\S)(.*?\S)~~/g;

export function inlineRuns(text: string, bold = false): InlineRun[] {
  const runs: InlineRun[] = [];
  const plain = (piece: string) => {
    if (piece) runs.push(bold ? { text: piece, bold } : { text: piece });
  };
  let at = 0;
  for (const match of text.matchAll(INLINE)) {
    const [whole, escaped, , code, label, strong, soft, gone] = match;
    plain(text.slice(at, match.index));
    at = match.index + whole.length;
    if (escaped !== undefined) plain(escaped);
    else if (code !== undefined) runs.push(bold ? { text: code, code: true, bold } : { text: code, code: true });
    else if (strong !== undefined) runs.push(...inlineRuns(strong, true));
    else runs.push(...inlineRuns(label ?? soft ?? gone, bold));
  }
  plain(text.slice(at));
  return runs;
}

export function markdownBlocks(source: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let code: string[] | null = null;

  const endParagraph = () => {
    if (paragraph.length > 0) blocks.push({ kind: 'paragraph', text: paragraph.join(' ').trim() });
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
      blocks.push({ kind: 'heading', level: heading[1].length as 1 | 2 | 3 | 4 | 5 | 6, text: heading[2].trim() });
      continue;
    }
    const item = LIST_ITEM.exec(line);
    if (item) {
      endParagraph();
      const ordered = item[1] !== undefined;
      const last = blocks[blocks.length - 1];
      const text = item[2].trim();
      if (last?.kind === 'list' && last.ordered === ordered) last.items.push(text);
      else blocks.push({ kind: 'list', ordered, items: [text] });
      continue;
    }
    paragraph.push(line.replace(QUOTE_MARK, ''));
  }
  endParagraph();
  if (code) blocks.push({ kind: 'code', text: code.join('\n') });
  return blocks;
}
