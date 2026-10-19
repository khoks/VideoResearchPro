/**
 * Report citations → sources, and sources → numbered footnotes (S-8.8.2).
 *
 * A report anchor carries at most a URL and a timestamp. The card needs the
 * source behind it (title, channel, kind), which the job's document list
 * supplies. Three ways to find it, tried in order:
 *
 *   1. the YouTube id in the href (every report since S-1.14.9);
 *   2. the href itself against each document's URL (non-YouTube sources);
 *   3. for pre-S-1.14.9 reports, whose anchors carry only `&t=123`, a known
 *      title — or failing that a channel with exactly one document in the
 *      run — found in the text around the anchor. The report writer always
 *      named the source next to the timestamp, so this recovers nearly all of
 *      them (30 of 30 in the stored smoke-test report).
 *
 * Pure functions; no React. The page builds a `CitationIndex` once per
 * report and every chip reads from it.
 */
import type { Video } from '../../types/video';
import type { ReportCitation } from './parseReport';

export type CitationSource = Pick<
  Video,
  | 'title'
  | 'channel_name'
  | 'url'
  | 'duration_seconds'
  | 'published_at'
  | 'thumbnail_url'
  | 'source_metadata'
> & {
  document_id: string | null;
  video_id: string | null;
  /** Absent from responses before S-8.8.2's schema fix; read as 'video'. */
  source_type?: string | null;
  source_url?: string | null;
};

export type ResolvedBy = 'video_id' | 'url' | 'title' | 'channel' | null;

export interface ResolvedCitation extends ReportCitation {
  source: CitationSource | null;
  /** Where the chip links: the anchor's own URL, or one rebuilt from the source. */
  resolvedHref: string | null;
  resolvedBy: ResolvedBy;
  /** 1-based footnote number; citations of the same place share one. */
  footnote: number;
}

export interface Endnote {
  footnote: number;
  label: string;
  seconds: number | null;
  source: CitationSource | null;
  href: string | null;
  /** How many chips in the body point here. */
  count: number;
}

export interface CitationIndex {
  byIndex: Map<number, ResolvedCitation>;
  endnotes: Endnote[];
  /** Citations the reader could not tie to any source. */
  unresolved: number;
}

const MIN_TITLE_CHARS = 8;

function fold(text: string): string {
  return text
    .normalize('NFKC')
    .replace(/[​-‍﻿]/g, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

/** The part of a title before hashtags or a " | channel" suffix, which writers drop. */
function titleStem(title: string): string {
  return fold(title.split(/\s[|#]|#/)[0]);
}

function urlKey(url: string): string | null {
  try {
    const u = new URL(url);
    u.hash = '';
    u.searchParams.delete('t');
    u.searchParams.delete('start');
    return `${u.host.replace(/^www\./, '')}${u.pathname.replace(/\/$/, '')}?${u.searchParams.toString()}`;
  } catch {
    return null;
  }
}

/** Link to a source at a timestamp, per source kind. */
export function timestampHref(source: CitationSource, seconds: number | null): string | null {
  const kind = source.source_type ?? 'video';
  const t = seconds != null && seconds > 0 ? seconds : null;
  if (kind === 'video' && source.video_id) {
    return `https://www.youtube.com/watch?v=${source.video_id}${t != null ? `&t=${t}` : ''}`;
  }
  const base = source.source_url || source.url || null;
  if (!base) return null;
  if (kind === 'podcast_episode' && t != null) return `${base}#t=${t}`;
  return base;
}

export function resolveCitations(
  citations: ReportCitation[],
  sources: CitationSource[],
): CitationIndex {
  const byVideoId = new Map<string, CitationSource>();
  const byUrl = new Map<string, CitationSource>();
  const titled: Array<{ needle: string; source: CitationSource }> = [];
  const byChannel = new Map<string, CitationSource[]>();

  for (const s of sources) {
    if (s.video_id) byVideoId.set(s.video_id, s);
    for (const u of [s.url, s.source_url]) {
      const k = u ? urlKey(u) : null;
      if (k) byUrl.set(k, s);
    }
    const full = fold(s.title ?? '');
    const stem = titleStem(s.title ?? '');
    if (full.length >= MIN_TITLE_CHARS) titled.push({ needle: full, source: s });
    if (stem.length >= MIN_TITLE_CHARS && stem !== full) titled.push({ needle: stem, source: s });
    const ch = fold(s.channel_name ?? '');
    if (ch) byChannel.set(ch, [...(byChannel.get(ch) ?? []), s]);
  }
  // Longest needle first, so "Part 2" titles beat their "Part 1" prefix.
  titled.sort((a, b) => b.needle.length - a.needle.length);
  const soleByChannel = [...byChannel.entries()]
    .filter(([, list]) => list.length === 1)
    .map(([name, list]) => ({ needle: name, source: list[0] }))
    .sort((a, b) => b.needle.length - a.needle.length);

  const find = (c: ReportCitation): { source: CitationSource | null; by: ResolvedBy } => {
    if (c.videoId && byVideoId.has(c.videoId)) return { source: byVideoId.get(c.videoId)!, by: 'video_id' };
    if (c.href) {
      const k = urlKey(c.href);
      if (k && byUrl.has(k)) return { source: byUrl.get(k)!, by: 'url' };
      return { source: null, by: null };
    }
    for (const ctx of c.contexts.map(fold)) {
      const t = titled.find((x) => ctx.includes(x.needle));
      if (t) return { source: t.source, by: 'title' };
    }
    for (const ctx of c.contexts.map(fold)) {
      const ch = soleByChannel.find((x) => ctx.includes(x.needle));
      if (ch) return { source: ch.source, by: 'channel' };
    }
    return { source: null, by: null };
  };

  const byIndex = new Map<number, ResolvedCitation>();
  const endnotes: Endnote[] = [];
  const footnoteByKey = new Map<string, Endnote>();
  let unresolved = 0;

  for (const c of citations) {
    const { source, by } = find(c);
    const resolvedHref = c.href ?? (source ? timestampHref(source, c.seconds) : null);
    if (!source && !resolvedHref) unresolved += 1;
    const key = resolvedHref
      ? `href:${resolvedHref}`
      : source
        ? `doc:${source.document_id ?? source.video_id}@${c.seconds}`
        : `raw:${c.index}`;
    let note = footnoteByKey.get(key);
    if (!note) {
      note = {
        footnote: endnotes.length + 1,
        label: c.label,
        seconds: c.seconds,
        source,
        href: resolvedHref,
        count: 0,
      };
      footnoteByKey.set(key, note);
      endnotes.push(note);
    }
    note.count += 1;
    byIndex.set(c.index, { ...c, source, resolvedHref, resolvedBy: by, footnote: note.footnote });
  }

  return { byIndex, endnotes, unresolved };
}
