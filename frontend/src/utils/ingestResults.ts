/*
 * Pure result-state logic for the Library page's "Add sources" tab.
 *
 * Kept free of React so it can be unit-tested in isolation once the
 * frontend grows a test runner (none exists today). Everything here maps
 * backend response shapes to the copy and tone the UI shows; the
 * components only render.
 */

import type { BadgeTone } from '../components/primitives';
import type { PasteUrlResult, PasteUrlStatus, UploadPdfResponse } from '../services/libraryApi';

// ---------------------------------------------------------------------------
// PDF upload
// ---------------------------------------------------------------------------

export type UploadOutcome = 'new' | 'deduped' | 'error';

export interface UploadPresentation {
  outcome: UploadOutcome;
  tone: BadgeTone;
  label: string;
  /** One line under the filename: page / word counts, or the error. */
  detail: string;
}

function formatCount(n: number | null | undefined, singular: string, plural: string): string | null {
  if (n === null || n === undefined) return null;
  return `${n.toLocaleString()} ${n === 1 ? singular : plural}`;
}

export function presentUploadResult(resp: UploadPdfResponse): UploadPresentation {
  const counts = [
    formatCount(resp.page_count, 'page', 'pages'),
    formatCount(resp.word_count, 'word', 'words'),
  ].filter((s): s is string => s !== null);
  const countLine = counts.length > 0 ? counts.join(' · ') : 'Text extracted';
  if (resp.deduped) {
    return {
      outcome: 'deduped',
      tone: 'info',
      label: 'Already in library',
      detail: `${countLine} · the same file was on the shelf already; it is now visible to you.`,
    };
  }
  return {
    outcome: 'new',
    tone: 'success',
    label: 'Added',
    detail: countLine,
  };
}

/** Minimal view of an axios error so this module stays axios-free. */
export interface HttpErrorLike {
  response?: { status?: number; data?: unknown };
  message?: string;
}

/** The body's `detail` when it is a string, or the `message` of an object
 * detail (quota refusals such as the document cap, T-5.2.10). */
export function detailFromErrorBody(data: unknown): string | null {
  if (data && typeof data === 'object' && 'detail' in data) {
    const d = (data as { detail?: unknown }).detail;
    if (typeof d === 'string' && d.trim()) return d;
    if (d && typeof d === 'object') {
      const m = (d as { message?: unknown }).message;
      if (typeof m === 'string' && m.trim()) return m;
    }
  }
  return null;
}

/**
 * Map the upload endpoint's documented failure modes to editorial copy.
 * 400 = not a .pdf or empty, 413 = over PDF_MAX_BYTES, 422 = uploaded but
 * no text (image-only or corrupt), 429 = the document cap (T-5.2.10),
 * anything else = generic.
 */
export function describeUploadError(err: HttpErrorLike | null | undefined): string {
  const status = err?.response?.status;
  const detail = detailFromErrorBody(err?.response?.data);
  switch (status) {
    case 400:
      return detail ?? 'Only non-empty .pdf files can be shelved.';
    case 413:
      return detail ?? 'This file is over the upload size limit. Split it or raise PDF_MAX_BYTES.';
    case 422:
      return (
        detail ??
        'Uploaded, but no text could be extracted. The PDF may be image-only (OCR is not supported yet) or corrupt.'
      );
    case 401:
      return 'Your session expired. Sign in again and retry.';
    case 403:
      return detail ?? 'Your plan does not allow this upload.';
    case 429:
      return detail ?? "Your library is at your plan's document cap, so this PDF was not added.";
    default:
      return detail ?? err?.message ?? 'Upload failed. Try again.';
  }
}

/** Client-side pre-check so a wrong file type never leaves the browser. */
export function isPdfFile(file: Pick<File, 'name' | 'type'>): boolean {
  return file.name.toLowerCase().endsWith('.pdf') || file.type === 'application/pdf';
}

// ---------------------------------------------------------------------------
// Paste URLs
// ---------------------------------------------------------------------------

export interface ParsedUrlLines {
  urls: string[];
  blankDropped: number;
  duplicatesDropped: number;
  /** URLs beyond the server cap, dropped before sending. */
  overCapDropped: number;
}

/**
 * One URL per line. Trims, drops blanks, de-duplicates (first occurrence
 * wins, exact-string match: the server hashes the exact string too), and
 * truncates to `max` so the batch never trips the server's 400.
 */
export function parseUrlLines(text: string, max: number): ParsedUrlLines {
  const seen = new Set<string>();
  const urls: string[] = [];
  let blankDropped = 0;
  let duplicatesDropped = 0;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) {
      blankDropped += 1;
      continue;
    }
    if (seen.has(line)) {
      duplicatesDropped += 1;
      continue;
    }
    seen.add(line);
    urls.push(line);
  }
  const overCapDropped = Math.max(0, urls.length - max);
  return { urls: urls.slice(0, max), blankDropped, duplicatesDropped, overCapDropped };
}

/**
 * Mirror of `backend/app/services/paste_url_resolver.py::resolve_source_type`
 * so the table can show the detected type before the server answers, and
 * for rows where the server omits it (`invalid_url` carries no type).
 * The server stays authoritative: its `source_type` overrides this.
 */
export function guessSourceType(url: string): string {
  let host = '';
  try {
    host = new URL(url.trim()).hostname.toLowerCase();
  } catch {
    return 'article';
  }
  if (host.startsWith('www.')) host = host.slice(4);
  if (host.startsWith('m.')) host = host.slice(2);
  const rules: Array<[string, string]> = [
    ['facebook.com', 'fb_post'],
    ['fb.com', 'fb_post'],
    ['instagram.com', 'ig_post'],
    ['linkedin.com', 'li_post'],
    ['twitter.com', 'tweet'],
    ['x.com', 'tweet'],
  ];
  for (const [suffix, type] of rules) {
    if (host === suffix || host.endsWith(`.${suffix}`)) return type;
  }
  return 'article';
}

const SOURCE_TYPE_LABELS: Record<string, string> = {
  article: 'Article',
  fb_post: 'Facebook post',
  ig_post: 'Instagram post',
  li_post: 'LinkedIn post',
  tweet: 'X / Twitter post',
  pdf: 'PDF',
  video: 'YouTube video',
};

export function sourceTypeLabel(sourceType: string | undefined): string {
  if (!sourceType) return 'Unknown';
  return SOURCE_TYPE_LABELS[sourceType] ?? sourceType.replace(/_/g, ' ');
}

export interface PasteStatusPresentation {
  tone: BadgeTone;
  label: string;
  detail: string;
}

export function presentPasteStatus(status: PasteUrlStatus): PasteStatusPresentation {
  switch (status) {
    case 'created':
      return { tone: 'success', label: 'Added', detail: 'Fetched, extracted and shelved.' };
    case 'deduped':
      return {
        tone: 'info',
        label: 'Already in library',
        detail: 'This exact URL was on the shelf already; it is now visible to you.',
      };
    case 'extraction_failed':
      return {
        tone: 'error',
        label: 'Could not extract',
        detail:
          'The page was reached but yielded no readable text. Login-walled or script-rendered pages usually need the Playwright fallback.',
      };
    case 'invalid_url':
      return { tone: 'error', label: 'Invalid URL', detail: 'Blank or unreadable entry.' };
  }
}

export interface PasteRowView {
  url: string;
  status: PasteUrlStatus;
  /** Server-detected type when present, else the client-side guess. */
  sourceType: string;
  /** True when `sourceType` came from the client-side mirror, not the server. */
  typeGuessed: boolean;
  wordCount: number | null;
  presentation: PasteStatusPresentation;
}

export function toPasteRowView(r: PasteUrlResult): PasteRowView {
  const serverType = r.source_type;
  return {
    url: r.url,
    status: r.status,
    sourceType: serverType ?? guessSourceType(r.url),
    typeGuessed: !serverType,
    wordCount: r.word_count ?? null,
    presentation: presentPasteStatus(r.status),
  };
}

export interface PasteSummary {
  created: number;
  deduped: number;
  failed: number;
  invalid: number;
  total: number;
}

export function summarizePaste(results: PasteUrlResult[]): PasteSummary {
  const s: PasteSummary = { created: 0, deduped: 0, failed: 0, invalid: 0, total: results.length };
  for (const r of results) {
    if (r.status === 'created') s.created += 1;
    else if (r.status === 'deduped') s.deduped += 1;
    else if (r.status === 'extraction_failed') s.failed += 1;
    else if (r.status === 'invalid_url') s.invalid += 1;
  }
  return s;
}

/** Sentence for the toast / summary line, e.g. "3 added · 1 already in library · 1 failed". */
export function pasteSummaryLine(s: PasteSummary): string {
  const parts: string[] = [];
  if (s.created) parts.push(`${s.created} added`);
  if (s.deduped) parts.push(`${s.deduped} already in library`);
  if (s.failed) parts.push(`${s.failed} could not be extracted`);
  if (s.invalid) parts.push(`${s.invalid} invalid`);
  return parts.length ? parts.join(' · ') : 'Nothing to report.';
}
