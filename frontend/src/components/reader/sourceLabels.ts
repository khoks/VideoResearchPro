/**
 * What a citation card says about its source, per `source_type` (S-8.8.2).
 *
 * One table so a new source type is a row, not a branch in a component —
 * the same shape `CitationLink` and `SOURCE_CONFIGS` use for Q&A citations
 * and approval cards.
 */
import { formatDuration } from '../../utils/formatters';
import type { CitationSource } from './citations';

export interface SourceDescription {
  /** "YouTube video", "Podcast episode", "PDF"… */
  kind: string;
  /** Short facts under the title: channel, date, length, host. */
  meta: string[];
  /** Whether a timestamp means something for this kind. */
  timed: boolean;
}

const KIND_LABEL: Record<string, string> = {
  video: 'YouTube video',
  podcast_episode: 'Podcast episode',
  pdf: 'PDF',
  article: 'Article',
  reddit_post: 'Reddit thread',
  hn_story: 'Hacker News story',
  mastodon_post: 'Mastodon post',
  bluesky_post: 'Bluesky post',
  fb_post: 'Facebook post',
  ig_post: 'Instagram post',
  li_post: 'LinkedIn post',
  tweet: 'Post on X',
};

const TIMED = new Set(['video', 'podcast_episode']);

function host(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).host.replace(/^www\./, '');
  } catch {
    return null;
  }
}

function str(v: unknown): string | null {
  return typeof v === 'string' && v.trim() ? v.trim() : null;
}

export function formatPublished(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

export function describeSource(source: CitationSource): SourceDescription {
  const kind = source.source_type ?? 'video';
  const m = (source.source_metadata ?? {}) as Record<string, unknown>;
  const published = formatPublished(source.published_at);
  const length =
    source.duration_seconds != null && source.duration_seconds > 0 ? formatDuration(source.duration_seconds) : null;
  const author = str(m.author);
  const link = source.source_url || source.url;

  let meta: Array<string | null>;
  switch (kind) {
    case 'video':
      meta = [str(source.channel_name), published, length];
      break;
    case 'podcast_episode':
      meta = [str(m.show_name) ?? str(source.channel_name), published, length];
      break;
    case 'pdf': {
      const pages = Number(m.page_count ?? m.pageCount);
      meta = [Number.isFinite(pages) && pages > 0 ? `${pages} pages` : null, published];
      break;
    }
    case 'reddit_post':
      meta = [str(m.subreddit) ? `r/${str(m.subreddit)}` : null, author ? `u/${author}` : null, published];
      break;
    case 'hn_story':
    case 'mastodon_post':
    case 'bluesky_post':
      meta = [author, published];
      break;
    default:
      meta = [host(link), author, published];
  }
  return {
    kind: KIND_LABEL[kind] ?? 'Source',
    meta: meta.filter((x): x is string => !!x),
    timed: TIMED.has(kind),
  };
}
