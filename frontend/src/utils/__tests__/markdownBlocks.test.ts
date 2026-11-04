import { describe, expect, it } from 'vitest';
import { markdownBlocks } from '../markdownBlocks';

describe('markdownBlocks', () => {
  it('splits paragraphs on blank lines and joins their lines', () => {
    expect(markdownBlocks('one\r\ntwo\r\n\r\nthree')).toEqual([
      { kind: 'paragraph', text: 'one two' },
      { kind: 'paragraph', text: 'three' },
    ]);
  });

  it('keeps heading levels and drops a closing run of hashes', () => {
    expect(markdownBlocks('# One\n\n#### Four ##\n\n#hashtag')).toEqual([
      { kind: 'heading', level: 1, text: 'One' },
      { kind: 'heading', level: 4, text: 'Four' },
      { kind: 'paragraph', text: '#hashtag' },
    ]);
  });

  it('takes the inline marks off and keeps a link or image by its text', () => {
    expect(markdownBlocks('*soft* `code` ~~gone~~ [a link](https://x.y/z) ![a chart](c.png)')).toEqual([
      { kind: 'paragraph', text: 'soft code gone a link a chart' },
    ]);
  });

  it('keeps bold for the caller, since it changes where lines wrap', () => {
    expect(markdownBlocks('**Answer.** No, *not* yet.')).toEqual([{ kind: 'paragraph', text: '**Answer.** No, not yet.' }]);
  });

  it('leaves underscores in names', () => {
    expect(markdownBlocks('the snake_case_name field')[0]).toEqual({ kind: 'paragraph', text: 'the snake_case_name field' });
  });

  it('groups list items, across blank lines, and starts a new list when the kind changes', () => {
    expect(markdownBlocks('- a\n* b\n\n+ c\n\n1. d\n2) e')).toEqual([
      { kind: 'list', ordered: false, items: ['a', 'b', 'c'] },
      { kind: 'list', ordered: true, items: ['d', 'e'] },
    ]);
  });

  it('keeps code as written, marks and all, and survives a fence left open', () => {
    expect(markdownBlocks('```python\n# not a heading\n**x**\n```\nafter')).toEqual([
      { kind: 'code', text: '# not a heading\n**x**' },
      { kind: 'paragraph', text: 'after' },
    ]);
    expect(markdownBlocks('~~~\nnever closed')).toEqual([{ kind: 'code', text: 'never closed' }]);
  });

  it('reads a quote as its text', () => {
    expect(markdownBlocks('> quoted\n> words')).toEqual([{ kind: 'paragraph', text: 'quoted words' }]);
  });

  it('has nothing to show for an empty answer', () => {
    expect(markdownBlocks('')).toEqual([]);
    expect(markdownBlocks('  \n\n ')).toEqual([]);
  });
});
