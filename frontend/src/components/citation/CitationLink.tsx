/**
 * <CitationLink>
 *
 * Polymorphic citation renderer dispatched by `Reference.source_type`
 * per S-1.5.5 (T-1.5.5.1 + T-1.5.5.2). One component handles every
 * source type's permalink + display format; new source types slot in
 * by extending the dispatch table.
 *
 * Display formats:
 *   - video         (YouTube):  "<video_title> · <channel_name> · <timestamp>"  → youtube_link with &t= anchor
 *   - reddit_post:              "r/<subreddit> · u/<author> · <thread_title>"   → permalink (#comment-<id> when set by backend)
 *   - hn_story:                 "HN · <author> · <story_title>"                  → permalink (HN item URL)
 *   - mastodon_post:            "@<author>@<instance> · <status_title>"          → permalink (status URL; reply URL when comment_url indexed)
 *   - bluesky_post:             "@<author> · <post_title>"                        → permalink (bsky.app web URL; reply URL when comment_url indexed)
 *
 * Back-compat: references without `source_type` (pre-S-1.5.5 rows in
 * existing Q&A history) render as YouTube — that was the only shape
 * before this PR.
 */
import type { CSSProperties, MouseEvent } from 'react';
import { Link } from 'react-router-dom';
import { useColors } from '../../hooks/useTheme';
import { useVideoChannel } from '../../hooks/useVideoChannel';
import { openApiLink } from '../../services/apiFiles';
import { citedFileFailed } from './citedFile';
import { fonts, fontSize } from '../../theme';
import type { Reference } from '../../types/qa';
import { noteTargetHref, type NoteTargetType } from '../../services/notesApi';
import { formatDate } from '../../utils/formatters';
import { youtubeVideoId } from '../../utils/videoId';

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

  if (sourceType === 'note') {
    // S-8.5.2: the same phrasing as the note cards (NoteCard), so the
    // inline list, the notes page and an answer read the same. The link
    // goes to what the note is on, inside the app.
    const when = ref.note_created_at ? formatDate(ref.note_created_at) : '';
    const href =
      noteTargetHref({
        target_type: (ref.note_target_type ?? '') as NoteTargetType,
        target_id: ref.note_target_id ?? '',
        target_parent_id: ref.note_target_parent_id ?? null,
      }) ?? '/notes';
    const on = ref.note_target_label ? `on ${ref.note_target_label}` : '';
    return {
      href,
      label: [when ? `You wrote this on ${when}` : 'Your note', on].filter(Boolean).join(' · '),
    };
  }

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

  if (sourceType === 'mastodon_post') {
    // The author handle from the backend is `user@instance`-shaped or
    // bare `user` (when the instance was carried separately in the
    // `instance` field). Render it as `@user@instance` regardless so
    // the citation is unambiguous across the federated network.
    const rawAuthor = ref.author ?? '';
    const instance = ref.instance ?? '';
    let handle: string;
    if (rawAuthor && rawAuthor.includes('@')) {
      handle = `@${rawAuthor}`;
    } else if (rawAuthor && instance) {
      handle = `@${rawAuthor}@${instance}`;
    } else if (rawAuthor) {
      handle = `@${rawAuthor}`;
    } else {
      handle = 'Mastodon';
    }
    const title = ref.thread_title ?? ref.video_title ?? '';
    const labelParts = [handle, title].filter(Boolean);
    return {
      href: ref.permalink ?? ref.video_url ?? '#',
      label: labelParts.join(' · '),
    };
  }

  if (sourceType === 'bluesky_post') {
    // Bluesky handles already include the instance/domain
    // (`alice.bsky.social`), so we just prefix `@` for readability.
    // Strip a leading `@` if the backend sent one in already so we
    // don't render `@@`.
    const rawAuthor = (ref.author ?? '').replace(/^@/, '');
    const handle = rawAuthor ? `@${rawAuthor}` : 'Bluesky';
    const title = ref.thread_title ?? ref.video_title ?? '';
    const labelParts = [handle, title].filter(Boolean);
    return {
      href: ref.permalink ?? ref.video_url ?? '#',
      label: labelParts.join(' · '),
    };
  }

  // ---- Paste-mode source types (S-1.5.8) — share the same shape -----
  if (
    sourceType === 'article' ||
    sourceType === 'fb_post' ||
    sourceType === 'ig_post' ||
    sourceType === 'li_post' ||
    sourceType === 'tweet'
  ) {
    const platformLabel = {
      article: '',
      fb_post: 'Facebook',
      ig_post: 'Instagram',
      li_post: 'LinkedIn',
      tweet: 'X / Twitter',
    }[sourceType];
    const author = ref.author ?? '';
    const title = ref.thread_title ?? ref.video_title ?? '';
    let host = '';
    const url = ref.permalink ?? ref.video_url ?? '';
    try {
      if (url) host = new URL(url).host.replace(/^www\./, '');
    } catch {
      host = '';
    }
    // Format: "<title> · <author> · <host>" for articles
    //         "<platform_label> · <author> · <title-or-host>" for social
    const labelParts =
      sourceType === 'article'
        ? [title, author, host].filter(Boolean)
        : [platformLabel, author, title || host].filter(Boolean);
    return {
      href: url || '#',
      label: labelParts.join(' · '),
    };
  }

  if (sourceType === 'pdf') {
    // Format: "<doc_title> · p. <page_number>"
    // The permalink already carries the `#page=<N>` deep-link
    // fragment for standard PDF viewers when chunked from a
    // specific page.
    const title = ref.thread_title ?? ref.video_title ?? '';
    const page = ref.page_number ?? '';
    const pageLabel = page ? `p. ${page}` : '';
    const labelParts = [title, pageLabel].filter(Boolean);
    return {
      href: ref.permalink ?? ref.video_url ?? '#',
      label: labelParts.join(' · '),
    };
  }

  if (sourceType === 'podcast_episode') {
    // Format: "<episode_title> · <show_name> · <timestamp>"
    // The permalink already carries the `#t=<sec>` deep-link fragment
    // when chunking promoted a per-segment timestamp; we just render
    // it as-is.
    const author = ref.author ?? '';
    const title = ref.thread_title ?? ref.video_title ?? '';
    const ts = ref.timestamp_display ?? '';
    const labelParts = [title, author, ts].filter(Boolean);
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
  // E-1.8 / T-8.8.1.5: a PDF's permalink is the API's serve route, which
  // takes the bearer header only, so following it 401s in the new tab. Fetch
  // the bytes and open them as a blob URL, keeping `#page=<N>`.
  const apiFile = {
    onClick: (e: MouseEvent<HTMLAnchorElement>) => void openApiLink(e, href, citedFileFailed),
    onAuxClick: (e: MouseEvent<HTMLAnchorElement>) => void openApiLink(e, href, citedFileFailed),
  };
  // S-8.7.4: a YouTube citation names its channel as a link to the channel
  // page, when the reader can see the cited video (resolved at read time,
  // batched across every chip on screen; no change to stored references).
  const isVideo = (reference.source_type ?? 'video') === 'video';
  const videoId = isVideo ? youtubeVideoId(reference) : null;
  const { data: channel } = useVideoChannel(videoId);

  if (isVideo && channel) {
    const sourceLabel = [reference.video_title, reference.timestamp_display].filter(Boolean).join(' · ');
    const channelName = reference.channel_name || channel.channel_name;
    return (
      <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, ...style }}>
        <a
          href={href}
          target={newTab ? '_blank' : undefined}
          rel={newTab ? 'noopener noreferrer' : undefined}
          style={{ color: c.accent, textDecoration: 'none', fontSize: 'inherit' }}
        >
          {sourceLabel || label}
        </a>
        {channelName && (
          <>
            <span aria-hidden style={{ color: c.textMuted }}>
              {' · '}
            </span>
            <Link
              to={`/library/channels/${channel.channel_id}`}
              title={`Open ${channelName} in your library`}
              style={{ color: c.textSecondary, textDecoration: 'underline', textUnderlineOffset: 2, fontSize: 'inherit' }}
            >
              {channelName}
            </Link>
          </>
        )}
      </span>
    );
  }

  if (reference.source_type === 'note') {
    // An in-app link: the note's target is a page of this app, not a
    // source on the web.
    return (
      <Link
        to={href}
        title={reference.quote || undefined}
        style={{
          color: c.accent,
          textDecoration: 'none',
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          fontStyle: 'italic',
          ...style,
        }}
      >
        {label}
      </Link>
    );
  }

  return (
    <a
      href={href}
      target={newTab ? '_blank' : undefined}
      rel={newTab ? 'noopener noreferrer' : undefined}
      {...apiFile}
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
