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
};
