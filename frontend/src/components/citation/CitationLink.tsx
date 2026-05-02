/**
 * <CitationLink>
 *
 * Polymorphic citation renderer dispatched by `Reference.source_type`
 * per S-1.5.5 (T-1.5.5.1 + T-1.5.5.2). One component handles every
 * source type's permalink + display format; new source types slot in
 * by extending the dispatch table.
 *
 * Display formats:
 *   - video       (YouTube): "<video_title> · <channel_name> · <timestamp>"  → youtube_link with &t= anchor
 *   - reddit_post:            "r/<subreddit> · u/<author> · <thread_title>"   → permalink (#comment-<id> when set by backend)
 *   - hn_story:               "HN · <author> · <story_title>"                  → permalink (HN item URL)
 *
 * Back-compat: references without `source_type` (pre-S-1.5.5 rows in
 * existing Q&A history) render as YouTube — that was the only shape
 * before this PR.
 */
import type { CSSProperties } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize } from '../../theme';
import type { Reference } from '../../types/qa';

export interface CitationLinkProps {
  reference: Reference;
  /** Open in a new tab? Defaults to true (citations almost always open externally). */
  newTab?: boolean;
  style?: CSSProperties;
}

interface RenderedCitation {
  href: string;
  label: string;
}

/**
 * Source-type → URL + label dispatch. Centralizing the mapping here
 * means new source types are a config-table addition, not new
 * component code.
 */
function renderCitation(ref: Reference): RenderedCitation {
  const sourceType = ref.source_type ?? 'video';

  if (sourceType === 'reddit_post') {
    const subreddit = ref.subreddit ? `r/${ref.subreddit}` : 'Reddit';
    const author = ref.author ? `u/${ref.author}` : '';
    const title = ref.thread_title ?? ref.video_title ?? '';
    const labelParts = [subreddit, author, title].filter(Boolean);
    return {
      href: ref.permalink ?? ref.video_url ?? '#',
      label: labelParts.join(' · '),
    };
  }

  if (sourceType === 'hn_story') {
    const author = ref.author ?? '';
    const title = ref.thread_title ?? ref.video_title ?? '';
    const labelParts = ['HN', author, title].filter(Boolean);
    return {
      href: ref.permalink ?? ref.video_url ?? '#',
      label: labelParts.join(' · '),
    };
  }

  // Default: YouTube / "video" path. This is the back-compat fallback
  // for legacy Q&A history rows that lack a source_type discriminator.
  const labelParts = [
    ref.video_title,
    ref.channel_name,
    ref.timestamp_display,
  ].filter(Boolean);
  return {
    href: ref.youtube_link ?? ref.video_url ?? '#',
    label: labelParts.join(' · '),
  };
}

export function CitationLink({ reference, newTab = true, style }: CitationLinkProps) {
  const c = useColors();
  const { href, label } = renderCitation(reference);

  return (
    <a
      href={href}
      target={newTab ? '_blank' : undefined}
      rel={newTab ? 'noopener noreferrer' : undefined}
      style={{
        color: c.accent,
        textDecoration: 'none',
        fontFamily: fonts.ui,
        fontSize: fontSize.xs,
        ...style,
      }}
    >
      {label}
    </a>
  );
}

// Re-export the dispatcher so tests can drive it directly without
// rendering React components.
export { renderCitation };
