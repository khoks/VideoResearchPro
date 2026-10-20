import { describe, expect, it } from 'vitest';
import { MAX_DROP_FILES, isShareableDrag, looksLikeExport, planDrop, type DropData } from '../echoDrop';

function drop(parts: { files?: File[]; uri?: string; text?: string }): DropData {
  const types: string[] = [];
  if (parts.files?.length) types.push('Files');
  if (parts.uri !== undefined) types.push('text/uri-list');
  if (parts.text !== undefined) types.push('text/plain');
  return {
    types,
    files: parts.files ?? [],
    getData: (type) => (type === 'text/uri-list' ? parts.uri ?? '' : type === 'text/plain' ? parts.text ?? '' : ''),
  };
}

const file = (name: string) => new File(['x'], name);

describe('isShareableDrag', () => {
  it('catches files, links and text, and nothing else', () => {
    expect(isShareableDrag(['Files'])).toBe(true);
    expect(isShareableDrag(['text/uri-list', 'text/plain'])).toBe(true);
    expect(isShareableDrag(['text/plain'])).toBe(true);
    expect(isShareableDrag(['application/x-moz-node'])).toBe(false);
    expect(isShareableDrag(null)).toBe(false);
  });
});

describe('looksLikeExport', () => {
  it('knows the names WhatsApp and Takeout give their exports', () => {
    expect(looksLikeExport('WhatsApp Chat with Asha.txt')).toBe(true);
    expect(looksLikeExport('WhatsApp Chat - Priya.zip')).toBe(true);
    expect(looksLikeExport('_chat.txt')).toBe(true);
    expect(looksLikeExport('takeout-20241019T101010Z-001.zip')).toBe(true);
    expect(looksLikeExport('notes.txt')).toBe(false);
    expect(looksLikeExport('photo.zip')).toBe(false);
  });
});

describe('planDrop', () => {
  it('splits dropped files into plain files and exports, and caps the count', () => {
    const plan = planDrop(drop({ files: [file('a.png'), file('WhatsApp Chat with Asha.txt'), file('b.pdf')] }));
    expect(plan.kind).toBe('files');
    if (plan.kind !== 'files') return;
    expect(plan.files.map((f) => f.name)).toEqual(['a.png', 'b.pdf']);
    expect(plan.exports.map((f) => f.name)).toEqual(['WhatsApp Chat with Asha.txt']);
    expect(plan.skipped).toBe(0);

    const many = planDrop(drop({ files: Array.from({ length: MAX_DROP_FILES + 3 }, (_, i) => file(`f${i}.txt`)) }));
    expect(many.kind === 'files' && many.files.length).toBe(MAX_DROP_FILES);
    expect(many.kind === 'files' && many.skipped).toBe(3);
  });

  it('takes a dragged link from the uri list, skipping comments', () => {
    expect(planDrop(drop({ uri: '# from Firefox\nhttps://example.org/a\nhttps://example.org/b', text: 'ignored' }))).toEqual({
      kind: 'url',
      url: 'https://example.org/a',
    });
  });

  it('treats dragged text as a link when it is one, and as text otherwise', () => {
    expect(planDrop(drop({ text: '  https://example.org/x  ' }))).toEqual({ kind: 'url', url: 'https://example.org/x' });
    expect(planDrop(drop({ text: 'The map is not the territory.' }))).toEqual({ kind: 'text', text: 'The map is not the territory.' });
  });

  it('drops nothing for an empty or non-web drag', () => {
    expect(planDrop(drop({ text: '   ' }))).toEqual({ kind: 'none' });
    expect(planDrop(drop({ uri: 'file:///C:/secret.txt' }))).toEqual({ kind: 'none' });
    expect(planDrop(drop({}))).toEqual({ kind: 'none' });
  });
});
