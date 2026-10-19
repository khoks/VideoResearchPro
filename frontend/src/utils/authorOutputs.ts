/*
 * Pure presentation logic for Author Studio. No React, no axios: the page
 * renders what these functions return.
 */

import type { BadgeTone } from '../components/primitives';
import type { KindsResponse, OutputItem } from '../services/authorApi';
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
      'A Markdown manuscript assembled from the research runs you pick: one chapter per run, with its report and Q&A.',
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
