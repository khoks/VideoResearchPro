/**
 * Polymorphic <ApprovalCard> TypeScript shape — locked by D-018.
 *
 * Source-of-truth: docs/source-types.md § Polymorphic ApprovalCard
 * TypeScript shape; ADR D-018 (decisions.md).
 *
 * The four sub-decisions baked into this file:
 *
 *   (a) `SourceMetadata` is hand-rolled in TS, kept synced with backend
 *       Pydantic models by convention. Drift is a PR-review concern;
 *       revisit if drift count climbs.
 *
 *   (b) Chip `field` references are `keyof T` — pure source-metadata.
 *       Document-level fields (title / published_at / source_url / etc.)
 *       render through fixed slots in <CardHeader> / <CardActions>, NOT
 *       through chips. Only per-source-unique data flows through the
 *       chip mechanism.
 *
 *   (c) Formatters are hybrid: a small named registry covers ~80% of
 *       cases; an optional `format?: (v) => string` callback overrides
 *       per-chip when the registry isn't enough. Callback wins when
 *       both are present; default is `String(v)`.
 *
 *   (d) Filter chips are a separate `FilterChip<T>` type. Source configs
 *       register two distinct arrays — `metaChips` (display) and
 *       `filterChips` (predicate). A source can register both for the
 *       same field, but each has its own type shape.
 *
 * Consumers: <ApprovalCard> primitive (T-1.5.4.1, follow-on PR), the
 * filter UI (T-1.5.4.3), and the per-source config registry (T-1.5.4.5)
 * for Reddit + HN. Adding a new source type = (1) extend the
 * SourceMetadata discriminated union, (2) add a registry entry — TS
 * compiler enforces both via the mapped-type registry.
 */
import type { ReactNode } from 'react';

// ---------------------------------------------------------------------------
// Document-level shape (fixed slots — NOT addressable by chips)
// ---------------------------------------------------------------------------

/**
 * The Document fields that render in <CardHeader> and <CardActions>
 * regardless of source_type. Mirrors the existing `Video` interface
 * (frontend/src/types/video.ts) but generalized for non-video sources.
 *
 * Per D-018(b), chips do NOT reference these fields — only per-source
 * `source_metadata` fields are chip-eligible.
 */
export interface ApprovalDocument {
  id: string;
  source_type: SourceType;
  source_id: string;
  title: string;
  source_url: string;
  thumbnail_url: string | null;
  published_at: string | null;
}

// ---------------------------------------------------------------------------
// 1. Discriminated union — backend Pydantic models per source_type
// ---------------------------------------------------------------------------

/**
 * Per-source-type metadata shape. Each variant carries the fields
 * that are unique to that source-type and that the approval card
 * surfaces beyond the standard Document-level fields. Extend this
 * union when adding a new source type — the mapped-type registry
 * (`SourceConfigRegistry`) will then refuse to compile until a
 * matching config entry is registered.
 */
export type SourceMetadata =
  | {
      source_type: 'video';
      channel: string;
      durationSec: number;
      viewCount: number;
    }
  | {
      source_type: 'reddit_post';
      subreddit: string;
      author: string;
      score: number;
      commentCount: number;
      permalink: string;
    }
  | {
      source_type: 'hn_story';
      author: string;
      points: number;
      commentCount: number;
      url: string;
    }
  | {
      source_type: 'mastodon_post';
      author: string;
      instance: string;
      favourites: number;
      replyCount: number;
      permalink: string;
    }
  | {
      source_type: 'bluesky_post';
      author: string;
      likes: number;
      replyCount: number;
      repostCount: number;
      permalink: string;
    }
  | {
      source_type: 'podcast_episode';
      showName: string;
      episodeNumber: number | null;
      durationSec: number;
      publishedAt: string;
    }
  | {
      source_type: 'pdf';
      pageCount: number;
      wordCount: number;
      uploadedAt: string;
    };

export type SourceType = SourceMetadata['source_type'];

export type MetadataFor<K extends SourceType> = Extract<
  SourceMetadata,
  { source_type: K }
>;

// ---------------------------------------------------------------------------
// 2. Classification (D-007 / D-014 / D-021) — fixed badge row
// ---------------------------------------------------------------------------

/** Mirrors backend `app.services.social_classify.StanceClassification`. */
export interface Classification {
  stance: 'for' | 'against' | 'neutral' | 'unclear';
  sentiment: 'positive' | 'negative' | 'mixed' | 'neutral';
  framing: 'technical' | 'political' | 'emotional' | 'experiential';
  topic_relevance: number; // 0..1; D-021 threshold = 0.50 for default surfacing
}

// ---------------------------------------------------------------------------
// 3. Formatter registry (D-018(c) hybrid)
// ---------------------------------------------------------------------------

/**
 * Named formatters in the registry. Concrete implementations live in
 * a separate formatters.ts module (T-1.5.4.1 follow-on); this file
 * just owns the type so configs can reference formatters by name with
 * compile-time safety.
 *
 *   durationSeconds → "12:34"           (e.g. video duration)
 *   relativeTime    → "3h ago"          (epoch ms or ISO string)
 *   signedNumber    → "+42" / "-7"      (e.g. Reddit score)
 *   numberWithCommas→ "1,234,567"       (large counts)
 *   truncate        → "abc def…"        (clamp long strings)
 */
export type FormatterName =
  | 'durationSeconds'
  | 'relativeTime'
  | 'signedNumber'
  | 'numberWithCommas'
  | 'truncate';

// ---------------------------------------------------------------------------
// 4. Display chip — pure source-metadata (D-018(b))
// ---------------------------------------------------------------------------

/**
 * One row in <CardMetaRow>. `field` is `keyof T` so the compiler
 * catches typos when registering a chip for a specific source type.
 *
 * `formatter` and `format` are both optional. Resolution order:
 *   1. If `format` callback supplied → use it (highest precedence).
 *   2. Else if `formatter` registry name supplied → look up + apply.
 *   3. Else → `String(v)`.
 */
export type MetaChip<T extends SourceMetadata> = {
  field: Exclude<keyof T, 'source_type'>;
  icon: ReactNode;
  /** Optional accessibility label / tooltip text; not always rendered. */
  label?: string;
  formatter?: FormatterName;
  format?: (v: T[Exclude<keyof T, 'source_type'>]) => string;
};

// ---------------------------------------------------------------------------
// 5. Filter chip — separate type (D-018(d))
// ---------------------------------------------------------------------------

/**
 * Filter chips operate on `source_metadata.<field>` regardless of
 * `source_type`. The chip declares a label, a target field, a
 * predicate, and (for non-boolean predicates) a comparison value.
 *
 * Filter state lives client-side; toggling a chip never re-fetches
 * or re-classifies. A source-type config registers an array of
 * filter chips; multiple chips on the same field combine with logical
 * AND in the consumer's filter logic.
 */
export type FilterChip<T extends SourceMetadata> = {
  label: string;
  field: Exclude<keyof T, 'source_type'>;
  predicate: 'eq' | 'gte' | 'lt' | 'contains';
  /** Comparison value. Type-narrowed at usage time by the consumer. */
  value?: unknown;
};

// ---------------------------------------------------------------------------
// 6. Per-source-type config — Document-level fields are NOT here
// ---------------------------------------------------------------------------

/**
 * One registry entry per source-type. Adding a new source type to
 * `SourceMetadata` will cause `SourceConfigRegistry` to fail compilation
 * until a matching config is registered — that's the structural
 * enforcement promise of D-016 / D-018.
 *
 * - `glyph` is the platform icon shown in <CardHeader>.
 * - `body.excerptField` (optional) tells <CardBody> which metadata
 *   field to render as the excerpt; if unset, the body is empty
 *   beyond the Document.title which <CardHeader> already shows.
 * - `metaChips` populates <CardMetaRow>.
 * - `filterChips` populates the filter-chip rail above the approval
 *   list (per D-021, the "Show low-relevance candidates" toggle is a
 *   global chip and lives outside this per-source list).
 * - `customSlot` is the escape hatch (D-016 § Risk + Mitigation):
 *   when a future source type genuinely needs UI not expressible in
 *   the primitive set (e.g. a podcast audio scrubber), the config
 *   can render arbitrary content. Default path stays uniform.
 */
export type ApprovalCardConfig<T extends SourceMetadata> = {
  glyph: ReactNode;
  body?: { excerptField: keyof T };
  metaChips: MetaChip<T>[];
  filterChips: FilterChip<T>[];
  customSlot?: (props: {
    metadata: T;
    document: ApprovalDocument;
    classification?: Classification;
  }) => ReactNode;
};

// ---------------------------------------------------------------------------
// 7. Mapped-type registry — exhaustive by construction
// ---------------------------------------------------------------------------

/**
 * The compile-time contract that turns "register a config, not a
 * component" from a convention into a structural invariant.
 * Adding 'mastodon_post' to `SourceMetadata` will refuse to compile
 * until the registry has a matching entry.
 */
export type SourceConfigRegistry = {
  [K in SourceType]: ApprovalCardConfig<MetadataFor<K>>;
};

// ---------------------------------------------------------------------------
// 8. Component prop shape (for the future <ApprovalCard> primitive)
// ---------------------------------------------------------------------------

/**
 * Final-shape props for <ApprovalCard> itself. The component reads
 * Document-level fields directly (header / actions) and dispatches
 * source-specific rendering through `config`.
 */
export type ApprovalCardProps<T extends SourceMetadata = SourceMetadata> = {
  document: ApprovalDocument;
  metadata: T;
  classification?: Classification;
  config: ApprovalCardConfig<T>;
  selected: boolean;
  onSelectionChange: (next: boolean) => void;
};
