import { describe, expect, it } from 'vitest';
import {
  applyOutputProgress,
  downloadLabel,
  estimateLabel,
  fileFormatOptions,
  formatUsd,
  defaultNewsletterSections,
  newsletterParameters,
  usageLabel,
  filenameFromDisposition,
  formatsParameter,
  isReadableOutput,
  isActiveOutput,
  isOrphanedPending,
  isTerminalMessage,
  outputProgressLine,
  outputSizeLabel,
  outputStatusLabel,
  outputStatusTone,
  parseCreateIntent,
} from '../authorOutputs';
import type { WSProgressMessage } from '../../types/ws';

describe('parseCreateIntent', () => {
  it('opens a book with the linked run pre-selected', () => {
    expect(parseCreateIntent(new URLSearchParams('new=book&job=abc'))).toEqual({ kind: 'book', jobIds: ['abc'] });
  });

  it('dedupes and trims repeated job params', () => {
    const p = new URLSearchParams('new=Book&job=a&job=%20a%20&job=b&job=');
    expect(parseCreateIntent(p)).toEqual({ kind: 'book', jobIds: ['a', 'b'] });
  });

  it('ignores runs for kinds that do not take runs', () => {
    expect(parseCreateIntent(new URLSearchParams('new=deck&job=abc'))).toEqual({ kind: 'deck', jobIds: [] });
  });

  it('returns null for no intent or an unknown kind', () => {
    expect(parseCreateIntent(new URLSearchParams(''))).toBeNull();
    expect(parseCreateIntent(new URLSearchParams('job=abc'))).toBeNull();
    expect(parseCreateIntent(new URLSearchParams('new=podcast&job=abc'))).toBeNull();
  });
});

describe('outputSizeLabel', () => {
  it('counts chapters and words for a book', () => {
    expect(outputSizeLabel({ kind: 'book', source_ids: ['a', 'b', 'c'], word_count: 12345 })).toBe('3 chapters · 12,345 words');
    expect(outputSizeLabel({ kind: 'book', source_ids: ['a'], word_count: 1 })).toBe('1 chapter · 1 word');
  });

  it('omits words until the backend has counted them', () => {
    expect(outputSizeLabel({ kind: 'book', source_ids: ['a'], word_count: null })).toBe('1 chapter');
    expect(outputSizeLabel({ kind: 'book', source_ids: ['a'] })).toBe('1 chapter');
  });

  it('says sources for other kinds', () => {
    expect(outputSizeLabel({ kind: 'deck', source_ids: ['a', 'b'], word_count: 0 })).toBe('2 sources · 0 words');
  });

  it('adds citations once there are any (S-6.7.3)', () => {
    expect(outputSizeLabel({ kind: 'book', source_ids: ['a'], word_count: 1631, citation_count: 30 })).toBe('1 chapter · 1,631 words · 30 citations');
    expect(outputSizeLabel({ kind: 'book', source_ids: ['a'], word_count: 10, citation_count: 1 })).toBe('1 chapter · 10 words · 1 citation');
    expect(outputSizeLabel({ kind: 'book', source_ids: ['a'], word_count: 10, citation_count: 0 })).toBe('1 chapter · 10 words');
  });
});

describe('S-6.7.1 progress helpers', () => {
  const row = { id: 'o1', status: 'pending', progress_pct: 0, progress_message: 'Queued', error_message: null };
  const msg = (m: Partial<WSProgressMessage>): WSProgressMessage => ({ type: 'job_progress', job_id: 'o1', timestamp: '', ...m });

  it('folds a progress message into the matching row only', () => {
    const next = applyOutputProgress(row, msg({ status: 'generating', progress_pct: 50, message: 'Chapter 1 of 2: T' }));
    expect(next).toMatchObject({ status: 'generating', progress_pct: 50, progress_message: 'Chapter 1 of 2: T' });
    expect(applyOutputProgress(row, msg({ job_id: 'other', progress_pct: 90 }))).toBe(row);
  });

  it('takes new_status from a status change and error text from an error', () => {
    expect(applyOutputProgress(row, msg({ type: 'job_status_change', new_status: 'completed' })).status).toBe('completed');
    expect(applyOutputProgress(row, msg({ type: 'job_error', status: 'failed', error: 'boom' })).error_message).toBe('boom');
  });

  it('knows which messages end a run', () => {
    expect(isTerminalMessage(msg({ type: 'job_status_change', new_status: 'completed' }))).toBe(true);
    expect(isTerminalMessage(msg({ type: 'job_status_change', new_status: 'cancelled' }))).toBe(true);
    expect(isTerminalMessage(msg({ type: 'job_error' }))).toBe(true);
    expect(isTerminalMessage(msg({ type: 'job_status_change', new_status: 'generating' }))).toBe(false);
    expect(isTerminalMessage(msg({ progress_pct: 40 }))).toBe(false);
  });

  it('labels active, orphaned and cancelled rows', () => {
    expect(isActiveOutput('pending') && isActiveOutput('generating')).toBe(true);
    expect(isActiveOutput('completed') || isActiveOutput('cancelled')).toBe(false);
    expect(isOrphanedPending({ status: 'pending', celery_task_id: null })).toBe(true);
    expect(isOrphanedPending({ status: 'pending', celery_task_id: 'abc' })).toBe(false);
    expect(outputStatusLabel('cancelled')).toBe('Cancelled');
    expect(outputStatusTone('cancelled')).toBe('warn');
  });

  it('formats the progress line', () => {
    expect(outputProgressLine({ progress_pct: 49.6, progress_message: ' Chapter 2 of 5: Tariffs ' })).toBe('50% · Chapter 2 of 5: Tariffs');
    expect(outputProgressLine({ progress_pct: 140, progress_message: null })).toBe('100%');
    expect(outputProgressLine({})).toBe('0%');
  });
});

describe('S-6.7.2 download helpers', () => {
  it('prefers the UTF-8 file name and falls back to the ASCII one', () => {
    const h = `attachment; filename="output.pdf"; filename*=UTF-8''%E0%A4%B9%E0%A4%BF%E0%A4%82%E0%A4%A6%E0%A5%80.pdf`;
    expect(filenameFromDisposition(h, 'x.pdf')).toBe('हिंदी.pdf');
    expect(filenameFromDisposition('attachment; filename="my-book.md"', 'x')).toBe('my-book.md');
    expect(filenameFromDisposition(`attachment; filename="a.md"; filename*=UTF-8''%E0%A4`, 'x')).toBe('a.md');
    expect(filenameFromDisposition('', 'fallback.md')).toBe('fallback.md');
    expect(filenameFromDisposition(undefined, 'fallback.md')).toBe('fallback.md');
  });

  it('opens only text outputs in the reader', () => {
    expect(isReadableOutput({ status: 'completed', has_content: true, formats: ['md', 'pdf'] })).toBe(true);
    expect(isReadableOutput({ status: 'completed', has_content: true, formats: ['pptx'] })).toBe(false);
    expect(isReadableOutput({ status: 'generating', has_content: false, formats: [] })).toBe(false);
    expect(isReadableOutput({ status: 'completed', has_content: true })).toBe(true);
  });

  it('labels download buttons', () => {
    expect(downloadLabel('md', 1)).toBe('Download');
    expect(downloadLabel('pdf', 3)).toBe('Download PDF');
    expect(downloadLabel('xyz', 2)).toBe('Download .xyz');
  });

  it('builds newsletter parameters with the featured section off by default (S-6.4.1)', () => {
    const sections = defaultNewsletterSections();
    expect(sections.featured).toBe(false);
    expect(sections.library && sections.questions && sections.outputs).toBe(true);
    expect(newsletterParameters('last', sections)).toEqual({ sections });
    const now = new Date('2026-10-19T12:00:00Z');
    expect(newsletterParameters('7', { ...sections, featured: true }, now)).toEqual({
      sections: { ...sections, featured: true },
      since: '2026-10-12T12:00:00.000Z',
    });
    expect(outputStatusLabel('skipped')).toBe('Skipped');
    expect(outputStatusTone('skipped')).toBe('neutral');
  });

  it('labels cohesion estimates and recorded usage (S-6.1.3)', () => {
    const call = { use_case: 'author_book_outline', provider: 'openai', model: 'gpt-5.5', reasoning: 'medium', input_tokens: 3000, output_tokens: 1300, cost_usd: 0.05 };
    const prose = { ...call, use_case: 'author_book_prose', provider: 'anthropic', model: 'claude-sonnet-5', cost_usd: 0.04 };
    expect(estimateLabel({ calls: [], cost_usd: 0 })).toBeNull();
    expect(estimateLabel({ calls: [call, prose], cost_usd: 0.0923 })).toBe('About $0.09 on gpt-5.5, claude-sonnet-5');
    expect(estimateLabel({ calls: [call], cost_usd: null })).toBe('Cost unknown: no published pricing for gpt-5.5');
    expect(formatUsd(0.004)).toBe('under $0.01');
    expect(usageLabel({ cohesion: { requested: 'full', applied: 'full' }, calls: [call, prose], input_tokens: 1, output_tokens: 1, cost_usd: 0.092 }))
      .toBe('Framing: full · $0.09');
    expect(usageLabel({ cohesion: { requested: 'full', applied: 'light' }, calls: [call, prose], input_tokens: 1, output_tokens: 1, cost_usd: 0.1 }))
      .toBe('Framing: light (asked for full) · $0.10');
    expect(usageLabel(null)).toBeNull();
  });

  it('offers the files a kind can be built as, and why one is missing (S-6.1.5)', () => {
    const kinds = {
      available: ['book'],
      supported: ['book', 'deck'],
      formats: {
        book: { available: ['md', 'epub'], unavailable: { pdf: 'Install WeasyPrint or Chromium.' }, pdf_engine: null },
      },
    };
    const options = fileFormatOptions(kinds, 'book');
    expect(options).toEqual([
      { format: 'epub', label: 'EPUB', available: true, reason: null },
      { format: 'pdf', label: 'PDF', available: false, reason: 'Install WeasyPrint or Chromium.' },
    ]);
    expect(formatsParameter(options, new Set(['epub', 'pdf']))).toEqual(['md', 'epub']);
    expect(formatsParameter(options, new Set())).toEqual(['md']);
    expect(fileFormatOptions(kinds, 'deck')).toEqual([]);
    expect(formatsParameter([], new Set(['pdf']))).toBeUndefined();
    expect(fileFormatOptions({ available: ['book'], supported: ['book'] }, 'book')).toEqual([]);
  });
});
