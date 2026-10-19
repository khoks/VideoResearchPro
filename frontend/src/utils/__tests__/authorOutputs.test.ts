import { describe, expect, it } from 'vitest';
import {
  applyOutputProgress,
  downloadLabel,
  filenameFromDisposition,
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
    expect(downloadLabel('pdf', 3)).toBe('Download .pdf');
  });
});
