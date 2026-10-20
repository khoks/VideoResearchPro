/*
 * Pure logic for Echo's drop zone (S-3.7.3). No React, no DOM events: the
 * component hands over the types and payloads of a drag, and this decides
 * what the drop becomes.
 */
import { parseQuickShareInput } from './echoShares';

/** At most this many files per drop; more is almost always a mistake. */
export const MAX_DROP_FILES = 10;

export type DropPlan =
  | { kind: 'none' }
  | { kind: 'files'; files: File[]; exports: File[]; skipped: number }
  | { kind: 'url'; url: string }
  | { kind: 'text'; text: string };

/** The parts of a DataTransfer this module reads. */
export interface DropData {
  types: readonly string[];
  files: ArrayLike<File>;
  getData: (type: string) => string;
}

/** A drag worth catching: files, a link or text from outside the page. */
export function isShareableDrag(types: readonly string[] | null | undefined): boolean {
  if (!types) return false;
  return types.includes('Files') || types.includes('text/uri-list') || types.includes('text/plain');
}

/** File names WhatsApp and Google Takeout give their exports: these go to the
 * importer, not into the inbox as opaque files. */
export function looksLikeExport(name: string): boolean {
  const base = name.replace(/\\/g, '/').split('/').pop()?.toLowerCase() ?? '';
  return (
    base === '_chat.txt' ||
    (base.startsWith('whatsapp chat') && (base.endsWith('.txt') || base.endsWith('.zip'))) ||
    (base.startsWith('takeout') && base.endsWith('.zip'))
  );
}

function firstUri(list: string): string | null {
  for (const line of list.split(/\r?\n/)) {
    const value = line.trim();
    if (value && !value.startsWith('#')) return value;
  }
  return null;
}

export function planDrop(data: DropData): DropPlan {
  const files = Array.from(data.files ?? []);
  if (files.length) {
    const kept = files.slice(0, MAX_DROP_FILES);
    return {
      kind: 'files',
      files: kept.filter((f) => !looksLikeExport(f.name)),
      exports: kept.filter((f) => looksLikeExport(f.name)),
      skipped: files.length - kept.length,
    };
  }
  if (data.types.includes('text/uri-list')) {
    const uri = firstUri(data.getData('text/uri-list'));
    if (uri && /^https?:\/\//i.test(uri)) return { kind: 'url', url: uri };
  }
  if (data.types.includes('text/plain')) {
    const parsed = parseQuickShareInput(data.getData('text/plain'));
    if (parsed.kind === 'url') return { kind: 'url', url: parsed.url };
    if (parsed.kind === 'text') return { kind: 'text', text: parsed.text };
  }
  return { kind: 'none' };
}
