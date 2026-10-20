import { describe, expect, it } from 'vitest';
import {
  authorshipLabel,
  contentTypeLabel,
  footprintTotal,
  formatBytes,
  isFootprintEmpty,
  isValidContentType,
  parseQuickShareInput,
  processingStateLabel,
  shareReadingLabel,
} from '../echoShares';
import { filenameFromDisposition } from '../../services/echoApi';

describe('parseQuickShareInput', () => {
  it('treats blank input as empty', () => {
    expect(parseQuickShareInput('   \n ')).toEqual({ kind: 'empty' });
  });

  it('treats one http(s) link as a link share', () => {
    expect(parseQuickShareInput('  https://youtu.be/abc  ')).toEqual({ kind: 'url', url: 'https://youtu.be/abc' });
    expect(parseQuickShareInput('http://example.org/a?b=1#c')).toEqual({ kind: 'url', url: 'http://example.org/a?b=1#c' });
  });

  it('keeps anything else as text, untrimmed', () => {
    const quote = 'https://example.org is where I read this:\n"the map is not the territory"';
    expect(parseQuickShareInput(quote)).toEqual({ kind: 'text', text: quote });
    expect(parseQuickShareInput('ftp://example.org/file')).toEqual({ kind: 'text', text: 'ftp://example.org/file' });
    expect(parseQuickShareInput('javascript:alert(1)')).toEqual({ kind: 'text', text: 'javascript:alert(1)' });
    expect(parseQuickShareInput('अहिंसा परमो धर्मः')).toEqual({ kind: 'text', text: 'अहिंसा परमो धर्मः' });
  });
});

describe('labels', () => {
  it('names known content types and humanises the rest', () => {
    expect(contentTypeLabel('youtube_video')).toBe('YouTube video');
    expect(contentTypeLabel('whatsapp_thread')).toBe('Whatsapp thread');
    expect(contentTypeLabel('')).toBe('Share');
  });

  it('validates content types like the backend', () => {
    expect(isValidContentType('book_quote')).toBe(true);
    expect(isValidContentType('Book Quote')).toBe(false);
    expect(isValidContentType('1abc')).toBe(false);
  });

  it('says plainly that processing has not happened yet', () => {
    expect(processingStateLabel('pending')).toBe('Waiting for processing');
    expect(processingStateLabel('mystery')).toBe('mystery');
  });

  it('explains the context-only default', () => {
    expect(authorshipLabel(false).label).toBe('Context only');
    expect(authorshipLabel(false).hint).toMatch(/never quotes/);
    expect(authorshipLabel(true).label).toBe('Your words');
  });
});

describe('formatBytes', () => {
  it('scales units', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(200 * 1024)).toBe('200 KB');
    expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB');
    expect(formatBytes(-1)).toBe('');
  });
});

describe('footprint', () => {
  it('sums every store', () => {
    const fp = { rows: { personal_context: 2, shares_inbox: 3 }, files: 1, vectors: { shares_global: 1, personal_context_global: 0 } };
    expect(footprintTotal(fp)).toBe(7);
    expect(isFootprintEmpty(fp)).toBe(false);
    expect(isFootprintEmpty({ rows: { a: 0 }, files: 0, vectors: {} })).toBe(true);
  });
});

describe('filenameFromDisposition', () => {
  it('reads the plain and the RFC 5987 forms', () => {
    expect(filenameFromDisposition('attachment; filename="echo-export-1.zip"', 'x')).toBe('echo-export-1.zip');
    expect(filenameFromDisposition("attachment; filename*=UTF-8''Meme%201.PNG", 'x')).toBe('Meme 1.PNG');
    expect(filenameFromDisposition(undefined, 'fallback.bin')).toBe('fallback.bin');
  });
});

describe('shareReadingLabel', () => {
  it('names local OCR and a vision model apart', () => {
    expect(shareReadingLabel({ extractor: 'ocr_local' })).toBe('Text read by local OCR');
    expect(shareReadingLabel({ extractor: 'ocr_vision' })).toBe('Text read by a vision model');
  });

  it('gives a recording its length and language', () => {
    expect(shareReadingLabel({ extractor: 'whisper', duration_seconds: 12.5, language: 'hindi' })).toBe(
      'Transcribed by Whisper · 0:13 · Hindi',
    );
    expect(shareReadingLabel({ extractor: 'whisper', duration_seconds: 3725, language: 'unknown' })).toBe(
      'Transcribed by Whisper · 1:02:05',
    );
    expect(shareReadingLabel({ extractor: 'whisper' })).toBe('Transcribed by Whisper');
  });

  it('counts PDF pages, and says when some had no text', () => {
    expect(shareReadingLabel({ extractor: 'pdf_text', page_count: 1, pages_with_text: 1 })).toBe('Text from 1 page');
    expect(shareReadingLabel({ extractor: 'pdf_text', page_count: 14, pages_with_text: 12 })).toBe('Text from 12 of 14 pages');
    expect(shareReadingLabel({ extractor: 'pdf_text' })).toBe('Text from the PDF');
  });

  it('says nothing about links, text files or unprocessed shares', () => {
    expect(shareReadingLabel({ extractor: 'trafilatura' })).toBeNull();
    expect(shareReadingLabel({ extractor: 'text_file' })).toBeNull();
    expect(shareReadingLabel(null)).toBeNull();
    expect(shareReadingLabel(undefined)).toBeNull();
  });
});
