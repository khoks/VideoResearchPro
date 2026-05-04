/**
 * Source-type configs for the polymorphic <ApprovalCard>.
 *
 * Each entry is a tiny config-table addition (~15-30 lines) that
 * declares: platform glyph, body excerpt field, meta chips, filter
 * chips. Adding a new source type — Mastodon, Bluesky, podcast,
 * article — = adding an entry here. The mapped-type registry in
 * types.ts will refuse to compile until every source_type has an
 * entry (T-1.5.4.5 closure pattern).
 */
import type { SourceConfigRegistry } from './types';

// ---------------------------------------------------------------------------
// Inline glyph constants — small, dependency-free SVG so we don't pull
// in a new icon-pack package. Replace with proper iconography post-MVP.
// ---------------------------------------------------------------------------

function YouTubeGlyph() {
  return (
    <svg width="20" height="14" viewBox="0 0 20 14" aria-hidden>
      <rect x="0" y="0" width="20" height="14" rx="3" fill="currentColor" />
      <polygon points="8,4 14,7 8,10" fill="white" />
    </svg>
  );
}

function RedditGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
      <circle cx="9" cy="9" r="9" fill="currentColor" />
      <text
        x="9"
        y="13"
        textAnchor="middle"
        fill="white"
        fontFamily="serif"
        fontSize="11"
        fontWeight="bold"
      >
        r
      </text>
    </svg>
  );
}

function HNGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
      <rect x="0" y="0" width="18" height="18" rx="2" fill="currentColor" />
      <text
        x="9"
        y="13"
        textAnchor="middle"
        fill="white"
        fontFamily="sans-serif"
        fontSize="9"
        fontWeight="bold"
      >
        Y
      </text>
    </svg>
  );
}

function MastodonGlyph() {
  // Stylised "M" inside a rounded square — visually distinct from
  // the HN "Y" while staying within the dependency-free SVG envelope
  // we use for every other source glyph.
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
      <rect x="0" y="0" width="18" height="18" rx="3" fill="currentColor" />
      <text
        x="9"
        y="13"
        textAnchor="middle"
        fill="white"
        fontFamily="sans-serif"
        fontSize="10"
        fontWeight="bold"
      >
        M
      </text>
    </svg>
  );
}

function BlueskyGlyph() {
  // Stylised butterfly silhouette — Bluesky's logo is a simple two-
  // wing shape. We render a minimal version with overlapping
  // circles to evoke the wings without pulling in an icon package.
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
      <rect x="0" y="0" width="18" height="18" rx="3" fill="currentColor" />
      <circle cx="6" cy="9" r="3" fill="white" />
      <circle cx="12" cy="9" r="3" fill="white" />
    </svg>
  );
}

function PDFGlyph() {
  // Document silhouette with folded corner — universally recognised
  // as a "page / file" mark. Same dimensions as other glyphs.
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
      <rect x="0" y="0" width="18" height="18" rx="3" fill="currentColor" />
      <path
        d="M5 4 L11 4 L13 6 L13 14 L5 14 Z M11 4 L11 6 L13 6"
        fill="white"
        stroke="white"
        strokeWidth="0.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PodcastGlyph() {
  // Microphone silhouette via two concentric rounded shapes — recall
  // a podcast mic without pulling in an icon-pack. Same dimensions
  // as the other glyphs so the approval-card grid stays uniform.
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
      <rect x="0" y="0" width="18" height="18" rx="3" fill="currentColor" />
      <rect x="7" y="3" width="4" height="7" rx="2" fill="white" />
      <path
        d="M5 9 a4 4 0 0 0 8 0 M9 13 v2 M7 15 h4"
        stroke="white"
        strokeWidth="1.2"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  );
}

// Tiny inline icon helpers for chip glyphs.
function DotGlyph({ color = 'currentColor' }: { color?: string } = {}) {
  return (
    <svg width="6" height="6" viewBox="0 0 6 6" aria-hidden>
      <circle cx="3" cy="3" r="3" fill={color} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// The registry — mapped type forces an entry per SourceType
// ---------------------------------------------------------------------------

export const SOURCE_CONFIGS: SourceConfigRegistry = {
  // -------------------------------------------------------------------------
  // YouTube video
  // -------------------------------------------------------------------------
  video: {
    glyph: <YouTubeGlyph />,
    metaChips: [
      {
        field: 'channel',
        icon: <DotGlyph />,
        label: 'Channel',
      },
      {
        field: 'durationSec',
        icon: <DotGlyph />,
        label: 'Duration',
        formatter: 'durationSeconds',
      },
      {
        field: 'viewCount',
        icon: <DotGlyph />,
        label: 'Views',
        formatter: 'numberWithCommas',
      },
    ],
    filterChips: [
      // Display-only stub for now; real filter wiring lands with
      // T-1.5.4.3 once the approval UI integrates the filter rail.
    ],
  },

  // -------------------------------------------------------------------------
  // Reddit post
  // -------------------------------------------------------------------------
  reddit_post: {
    glyph: <RedditGlyph />,
    metaChips: [
      {
        field: 'subreddit',
        icon: <DotGlyph />,
        label: 'Subreddit',
        format: (v) => `r/${v}`,
      },
      {
        field: 'author',
        icon: <DotGlyph />,
        label: 'Author',
        format: (v) => `u/${v}`,
      },
      {
        field: 'score',
        icon: <DotGlyph />,
        label: 'Score',
        formatter: 'signedNumber',
      },
      {
        field: 'commentCount',
        icon: <DotGlyph />,
        label: 'Comments',
        formatter: 'numberWithCommas',
      },
    ],
    filterChips: [
      // T-1.5.4.3: Filter rail comes with the page-integration PR.
    ],
  },

  // -------------------------------------------------------------------------
  // Hacker News story
  // -------------------------------------------------------------------------
  hn_story: {
    glyph: <HNGlyph />,
    metaChips: [
      {
        field: 'author',
        icon: <DotGlyph />,
        label: 'Author',
      },
      {
        field: 'points',
        icon: <DotGlyph />,
        label: 'Points',
        formatter: 'numberWithCommas',
      },
      {
        field: 'commentCount',
        icon: <DotGlyph />,
        label: 'Comments',
        formatter: 'numberWithCommas',
      },
    ],
    filterChips: [
      // T-1.5.4.3: Filter rail comes with the page-integration PR.
    ],
  },

  // -------------------------------------------------------------------------
  // Mastodon post
  // -------------------------------------------------------------------------
  mastodon_post: {
    glyph: <MastodonGlyph />,
    metaChips: [
      {
        field: 'author',
        icon: <DotGlyph />,
        label: 'Author',
        format: (v) => `@${v}`,
      },
      {
        field: 'instance',
        icon: <DotGlyph />,
        label: 'Instance',
      },
      {
        field: 'favourites',
        icon: <DotGlyph />,
        label: 'Favourites',
        formatter: 'numberWithCommas',
      },
      {
        field: 'replyCount',
        icon: <DotGlyph />,
        label: 'Replies',
        formatter: 'numberWithCommas',
      },
    ],
    filterChips: [
      // M-1.6: filter rail parity — same staged-out pattern as Reddit/HN.
    ],
  },

  // -------------------------------------------------------------------------
  // Bluesky post
  // -------------------------------------------------------------------------
  bluesky_post: {
    glyph: <BlueskyGlyph />,
    metaChips: [
      {
        field: 'author',
        icon: <DotGlyph />,
        label: 'Author',
        format: (v) => `@${v}`,
      },
      {
        field: 'likes',
        icon: <DotGlyph />,
        label: 'Likes',
        formatter: 'numberWithCommas',
      },
      {
        field: 'replyCount',
        icon: <DotGlyph />,
        label: 'Replies',
        formatter: 'numberWithCommas',
      },
      {
        field: 'repostCount',
        icon: <DotGlyph />,
        label: 'Reposts',
        formatter: 'numberWithCommas',
      },
    ],
    filterChips: [
      // M-1.6: filter rail parity — same staged-out pattern as Reddit/HN/Mastodon.
    ],
  },

  // -------------------------------------------------------------------------
  // PDF / e-book (M-1.8)
  // -------------------------------------------------------------------------
  pdf: {
    glyph: <PDFGlyph />,
    metaChips: [
      {
        field: 'pageCount',
        icon: <DotGlyph />,
        label: 'Pages',
        formatter: 'numberWithCommas',
      },
      {
        field: 'wordCount',
        icon: <DotGlyph />,
        label: 'Words',
        formatter: 'numberWithCommas',
      },
      {
        field: 'uploadedAt',
        icon: <DotGlyph />,
        label: 'Uploaded',
        formatter: 'relativeTime',
      },
    ],
    filterChips: [],
  },

  // -------------------------------------------------------------------------
  // Podcast episode (M-1.7)
  // -------------------------------------------------------------------------
  podcast_episode: {
    glyph: <PodcastGlyph />,
    metaChips: [
      {
        field: 'showName',
        icon: <DotGlyph />,
        label: 'Show',
      },
      {
        field: 'episodeNumber',
        icon: <DotGlyph />,
        label: 'Episode',
        format: (v) => (v == null ? '—' : `#${v}`),
      },
      {
        field: 'durationSec',
        icon: <DotGlyph />,
        label: 'Duration',
        formatter: 'durationSeconds',
      },
      {
        field: 'publishedAt',
        icon: <DotGlyph />,
        label: 'Published',
        formatter: 'relativeTime',
      },
    ],
    filterChips: [
      // M-1.7: filter rail parity — same staged-out pattern.
    ],
  },
};
