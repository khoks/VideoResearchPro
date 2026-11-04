import { describe, expect, it } from 'vitest';
import { inlineRuns, markdownBlocks } from '../markdownBlocks';

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

describe('inlineRuns', () => {
  const shown = (text: string) =>
    inlineRuns(text)
      .map((run) => run.text)
      .join('');
  const bold = (text: string) =>
    inlineRuns(text)
      .filter((run) => run.bold)
      .map((run) => run.text);
  const code = (text: string) =>
    inlineRuns(text)
      .filter((run) => run.code)
      .map((run) => run.text);

  it('takes paired marks off and keeps a link or image by its text', () => {
    expect(shown('*soft* `code` ~~gone~~ [a link](https://x.y/z) ![a chart](c.png)')).toBe('soft code gone a link a chart');
  });

  it('keeps bold, since it changes where lines wrap', () => {
    expect(inlineRuns('**Answer.** No, *not* yet.')).toEqual([
      { text: 'Answer.', bold: true },
      { text: ' No, ' },
      { text: 'not' },
      { text: ' yet.' },
    ]);
  });

  it('leaves a lone mark as written, so an answer still says what it said', () => {
    for (const text of [
      'the rate is 2 * 3 = 6',
      '2 * 3 * 4 = 24',
      'a ~~ b',
      'a stray ` here',
      '5 ** 2 = 25',
      '**open and never closed',
      '*open and never closed',
    ]) {
      expect(shown(text), text).toBe(text);
      expect(bold(text), text).toEqual([]);
    }
  });

  it('leaves marks inside code alone', () => {
    const text = 'call `f(**kwargs)` with `*args` and ``a ` tick``';
    expect(shown(text)).toBe('call f(**kwargs) with *args and a ` tick');
    expect(bold(text)).toEqual([]);
    expect(code(text)).toEqual(['f(**kwargs)', '*args', 'a ` tick']);
  });

  it('bolds only a balanced pair', () => {
    expect(bold('**one** then **two')).toEqual(['one']);
    expect(shown('**one** then **two')).toBe('one then **two');
  });

  it('reads marks nested in bold or a link', () => {
    expect(inlineRuns('**a `b` [c](d)**')).toEqual([
      { text: 'a ', bold: true },
      { text: 'b', code: true, bold: true },
      { text: ' ', bold: true },
      { text: 'c', bold: true },
    ]);
    expect(bold('[**a**](b)')).toEqual(['a']);
  });

  it('honours an escaped mark', () => {
    expect(shown('\\*not soft\\* and 2 \\* 3')).toBe('*not soft* and 2 * 3');
  });

  it('leaves underscores in names', () => {
    expect(shown('the snake_case_name field')).toBe('the snake_case_name field');
  });
});
