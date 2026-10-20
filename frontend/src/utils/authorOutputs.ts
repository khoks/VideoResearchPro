/*
 * Pure presentation logic for Author Studio. No React, no axios: the page
 * renders what these functions return.
 */

import type { BadgeTone } from '../components/primitives';
import type { KindsResponse, OutputEstimate, OutputItem, OutputUsage } from '../services/authorApi';
import type { WSProgressMessage } from '../types/ws';
import { detailFromErrorBody, type HttpErrorLike } from './ingestResults';

export interface KindMeta {
  label: string;
  /** One sentence for the kind card. */
  description: string;
  /** Roadmap pointer shown on "coming later" cards. */
  epic: string;
}

/** Order here is display order. Kinds the backend reports that are missing
 * from this map still render, with a generic description. */
export const OUTPUT_KIND_META: Record<string, KindMeta> = {
  book: {
    label: 'Book',
    description:
      'A manuscript assembled from the research runs you pick: one chapter per run, with its report and Q&A, as Markdown, EPUB or PDF.',
    epic: 'E-6.1',
  },
  site: {
    label: 'Site',
    description: 'A static personal wiki generated from your library.',
    epic: 'E-6.2',
  },
  deck: {
    label: 'Deck',
    description: 'A slide deck distilled from one or more runs.',
    epic: 'E-6.3',
  },
  newsletter: {
    label: 'Newsletter',
    description: 'A recurring digest of what changed on your shelves.',
    epic: 'E-6.4',
  },
  reel: {
    label: 'Reel',
    description: 'Narrated short video stitched from cited moments.',
    epic: 'E-6.5',
  },
};

export function kindMeta(kind: string): KindMeta {
  return (
    OUTPUT_KIND_META[kind] ?? {
      label: kind.replace(/_/g, ' '),
      description: 'Defined by the backend; no description yet.',
      epic: 'I-6',
    }
  );
}

export interface KindPartition {
  available: string[];
  comingLater: string[];
}

/**
 * Split the kinds response into those with an outputter and those without,
 * keeping the backend's order. A kind listed as available but not in
 * `supported` is still shown as available: the backend's registry wins.
 */
export function partitionKinds(kinds: KindsResponse | undefined): KindPartition {
  if (!kinds) return { available: [], comingLater: [] };
  const available = new Set(kinds.available);
  const ordered = [...kinds.supported];
  for (const k of kinds.available) if (!ordered.includes(k)) ordered.push(k);
  return {
    available: ordered.filter((k) => available.has(k)),
    comingLater: ordered.filter((k) => !available.has(k)),
  };
}

export function outputStatusTone(status: string): BadgeTone {
  switch (status) {
    case 'completed':
      return 'success';
    case 'failed':
      return 'error';
    case 'generating':
      return 'info';
    case 'cancelled':
      return 'warn';
    case 'pending':
    default:
      return 'neutral';
  }
}

export function outputStatusLabel(status: string): string {
  switch (status) {
    case 'completed':
      return 'Ready';
    case 'failed':
      return 'Failed';
    case 'generating':
      return 'Generating';
    case 'pending':
      return 'Pending';
    case 'cancelled':
      return 'Cancelled';
    default:
      return status.replace(/_/g, ' ');
  }
}

function slugify(text: string): string {
  const s = text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, '')
    .trim()
    .replace(/[\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return s || 'output';
}

/** Books are served as text/markdown; everything else as text/plain. */
export function outputDownloadFilename(output: Pick<OutputItem, 'kind' | 'title'>): string {
  const ext = output.kind === 'book' ? 'md' : 'txt';
  return `${slugify(output.title)}.${ext}`;
}

export function outputMediaType(output: Pick<OutputItem, 'kind'>): string {
  return output.kind === 'book' ? 'text/markdown' : 'text/plain';
}

/** Turn a create-output failure into one honest sentence. */
export function describeCreateError(err: HttpErrorLike | null | undefined, kind: string): string {
  const status = err?.response?.status;
  const detail = detailFromErrorBody(err?.response?.data);
  switch (status) {
    case 501:
      return `${kindMeta(kind).label} output has no generator yet. It is defined in the schema but nothing produces it today.`;
    case 400:
      return detail ?? 'The request was rejected. Check the title and selected sources.';
    case 403:
      return detail ?? 'Author Studio is a Pro feature. Upgrade to create outputs.';
    case 401:
      return 'Your session expired. Sign in again and retry.';
    default:
      return detail ?? err?.message ?? 'Generation failed. Try again.';
  }
}

/**
 * S-6.1.1: "Add this run to a book" on the job page links to
 * `/author?new=book&job=<id>`. Returns the kind to open and the runs to
 * pre-select, or null when the URL asks for nothing (or for a kind this page
 * does not know). Only books take runs as sources, so `job` is ignored for
 * any other kind.
 */
export interface CreateIntent {
  kind: string;
  jobIds: string[];
}

export function parseCreateIntent(params: URLSearchParams): CreateIntent | null {
  const kind = (params.get('new') ?? '').trim().toLowerCase();
  if (!kind || !(kind in OUTPUT_KIND_META)) return null;
  const jobIds =
    kind === 'book'
      ? [...new Set(params.getAll('job').map((j) => j.trim()).filter(Boolean))]
      : [];
  return { kind, jobIds };
}

/**
 * The size line on an output row: chapters and words for a book (one
 * chapter per run), sources and words otherwise. Words appear only once
 * the backend has counted them (`word_count` is null until there is content).
 */
export function outputSizeLabel(
  output: Pick<OutputItem, 'kind' | 'source_ids' | 'word_count' | 'citation_count'>,
): string {
  const n = output.source_ids.length;
  const unit = output.kind === 'book' ? (n === 1 ? 'chapter' : 'chapters') : n === 1 ? 'source' : 'sources';
  const parts = [`${n} ${unit}`];
  if (typeof output.word_count === 'number') {
    parts.push(`${output.word_count.toLocaleString('en-US')} ${output.word_count === 1 ? 'word' : 'words'}`);
  }
  // S-6.7.3: shown once there are any, so a book from un-cited runs stays quiet.
  if (output.citation_count) {
    parts.push(`${output.citation_count.toLocaleString('en-US')} ${output.citation_count === 1 ? 'citation' : 'citations'}`);
  }
  return parts.join(' · ');
}

/** S-6.7.1: an output the worker still owns (live progress, cancellable). */
export function isActiveOutput(status: string): boolean {
  return status === 'pending' || status === 'generating';
}

/** A `pending` row with no task id was created before generation moved to the
 * worker, when a kind without a generator left its row behind. It never runs. */
export function isOrphanedPending(output: Pick<OutputItem, 'status' | 'celery_task_id'>): boolean {
  return output.status === 'pending' && !output.celery_task_id;
}

/** The progress line under an active row: "40% · Chapter 2 of 5: Tariffs". */
export function outputProgressLine(output: Pick<OutputItem, 'progress_pct' | 'progress_message'>): string {
  const pct = Math.max(0, Math.min(100, Math.round(output.progress_pct ?? 0)));
  const message = (output.progress_message ?? '').trim();
  return message ? `${pct}% · ${message}` : `${pct}%`;
}

/** Fold one socket message into an output row. Returns the same object when
 * the message is for another id, so React Query keeps referential equality. */
export function applyOutputProgress<T extends Pick<OutputItem, 'id' | 'status' | 'progress_pct' | 'progress_message' | 'error_message'>>(
  output: T,
  msg: WSProgressMessage,
): T {
  if (msg.job_id !== output.id) return output;
  return {
    ...output,
    status: msg.new_status ?? msg.status ?? output.status,
    progress_pct: msg.progress_pct ?? output.progress_pct,
    progress_message: msg.message ?? output.progress_message,
    error_message: msg.error ?? output.error_message,
  };
}

/** Statuses after which the row's content and lists must be refetched. */
export function isTerminalMessage(msg: WSProgressMessage): boolean {
  const s = msg.new_status ?? msg.status;
  return msg.type === 'job_error' || s === 'completed' || s === 'failed' || s === 'cancelled';
}

/** S-6.7.2: the file name a download's Content-Disposition carries. The
 * RFC 5987 `filename*` (UTF-8, so Devanagari titles survive) wins over the
 * ASCII `filename`; `fallback` covers a missing header. */
export function filenameFromDisposition(header: string | null | undefined, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      // fall through to the ASCII name
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(header);
  return plain ? plain[1].trim() : fallback;
}

const READABLE_FORMATS = new Set(['md', 'txt', 'html']);

/** Whether the reader can open it: it needs text, which a deck's PPTX or a
 * site's zip is not. Falls back to `has_content` for rows from older APIs. */
export function isReadableOutput(output: Pick<OutputItem, 'status' | 'has_content' | 'formats'>): boolean {
  if (output.status !== 'completed' || !output.has_content) return false;
  return output.formats ? output.formats.some((f) => READABLE_FORMATS.has(f)) : true;
}

/** Button text for one download format: "Download" alone when there is only
 * one, else "Download .pdf". */
export type CohesionLevel = 'none' | 'light' | 'full';

/** S-6.1.3: what each cohesion level does, for the create modal. The default
 * mirrors `book_cohesion.DEFAULT_LEVEL` on the server. */
export const DEFAULT_COHESION: CohesionLevel = 'none';
export const COHESION_OPTIONS: { value: CohesionLevel; label: string; description: string }[] = [
  { value: 'none', label: 'None', description: 'The chapters in the order you pick, with nothing added.' },
  {
    value: 'light',
    label: 'Light',
    description: 'A model suggests the reading order and parts, and writes a short introduction and a bridge into each chapter.',
  },
  {
    value: 'full',
    label: 'Full',
    description: 'Also a full introduction, a conclusion and a glossary. Chapters are never rewritten; the added text is labelled.',
  },
];

export function formatUsd(cost: number | null | undefined): string {
  if (cost === null || cost === undefined) return 'cost unknown';
  if (cost > 0 && cost < 0.01) return 'under $0.01';
  return `$${cost.toFixed(2)}`;
}

function models(calls: { model: string }[]): string {
  return [...new Set(calls.map((c) => c.model))].join(', ');
}

/** "About $0.09 on gpt-5.5, claude-sonnet-5", or null when nothing is called. */
export function estimateLabel(estimate: OutputEstimate | undefined): string | null {
  if (!estimate || estimate.calls.length === 0) return null;
  if (estimate.cost_usd === null) return `Cost unknown: no published pricing for ${models(estimate.calls)}`;
  return `About ${formatUsd(estimate.cost_usd)} on ${models(estimate.calls)}`;
}

/** "Framing: full · $0.09", noting when less was applied than asked for. */
export function usageLabel(usage: OutputUsage | null | undefined): string | null {
  if (!usage || usage.calls.length === 0) return null;
  const c = usage.cohesion;
  const level = c ? (c.applied === c.requested ? c.applied : `${c.applied} (asked for ${c.requested})`) : null;
  return [level ? `Framing: ${level}` : null, formatUsd(usage.cost_usd)].filter(Boolean).join(' · ');
}

/** Human names for download formats. */
export const FORMAT_NAMES: Record<string, string> = {
  md: 'Markdown',
  txt: 'Text',
  html: 'HTML',
  pdf: 'PDF',
  epub: 'EPUB',
  pptx: 'PowerPoint',
  zip: 'Zip',
  mp4: 'Video',
};

export function downloadLabel(format: string, count: number): string {
  if (count <= 1) return 'Download';
  return `Download ${FORMAT_NAMES[format] ?? `.${format}`}`;
}

export interface FileFormatOption {
  format: string;
  label: string;
  available: boolean;
  /** Why the server cannot build it, with what to install; null if it can. */
  reason: string | null;
}

/** S-6.1.5: the files a kind can be built as beside its text, for the create
 * modal. Empty when the server does not report formats (nothing to choose). */
export function fileFormatOptions(kinds: KindsResponse | undefined, kind: string): FileFormatOption[] {
  const f = kinds?.formats?.[kind];
  if (!f) return [];
  const names = [...new Set([...f.available, ...Object.keys(f.unavailable ?? {})])].filter((x) => x !== 'md');
  return names.map((format) => ({
    format,
    label: FORMAT_NAMES[format] ?? format.toUpperCase(),
    available: f.available.includes(format),
    reason: f.unavailable?.[format] ?? null,
  }));
}

/** The `parameters.formats` to send: the text plus every available file the
 * user kept ticked. Undefined when there was nothing to choose, so the server
 * applies its own default. */
export function formatsParameter(options: FileFormatOption[], chosen: Set<string>): string[] | undefined {
  if (options.length === 0) return undefined;
  return ['md', ...options.filter((o) => o.available && chosen.has(o.format)).map((o) => o.format)];
}
