/**
 * Frontend Video / Document row shape returned by /api/v1/jobs/{id}/videos.
 *
 * Historically YouTube-only (post-PR-pre-M-1.5). Post-M-1.5 (S-1.5.4
 * page integration), the same payload carries any source_type via
 * the polymorphic `source_type` + `source_metadata` discriminator.
 *
 * Legacy fields (video_id, channel_name, etc.) remain populated for
 * source_type='video' rows. For non-video rows (reddit_post, hn_story)
 * they may be null/empty; the frontend reads source_metadata for the
 * per-source-specific data.
 */
import type {
  Classification,
  SourceMetadata,
  SourceType,
} from '../components/approval';

export interface Video {
  id: string;
  // Legacy YouTube identity (still used for source_type='video' approvals
  // and back-compat reading; null for non-video rows where document_id
  // is the canonical key).
  video_id: string | null;
  document_id: string;
  source_type: SourceType;
  source_id: string;
  source_url: string | null;
  source_metadata: Record<string, unknown>;
  classification: Classification | null;

  title: string;
  channel_name: string;
  channel_id: string | null;
  url: string;
  duration_seconds: number | null;
  published_at: string | null;
  thumbnail_url: string | null;
  approved: boolean;
  transcript_status: string;
  transcript_word_count: number | null;
  transcript_language: string | null;
}

/**
 * Helper: convert a Video to the shape <ApprovalCard> expects.
 * Returns null when the source_type isn't registered in
 * SOURCE_CONFIGS — caller can fall back to legacy rendering.
 */
export function videoToApprovalProps(
  video: Video,
): { document: import('../components/approval').ApprovalDocument; metadata: SourceMetadata } | null {
  // Build the typed metadata shape the chip dispatcher expects.
  // Different source_types declare different metadata fields; we
  // assemble per-type with sensible fallbacks. SOURCE_CONFIGS at
  // render time enforces that every chip's `field` exists on the
  // metadata for its source_type, so the runtime data must match
  // the declared shape.
  const m = video.source_metadata as Record<string, unknown>;
  let metadata: SourceMetadata;
  switch (video.source_type) {
    case 'video':
      metadata = {
        source_type: 'video',
        channel: video.channel_name ?? '',
        durationSec: video.duration_seconds ?? 0,
        viewCount: Number(m.viewCount ?? m.view_count ?? 0),
      };
      break;
    case 'reddit_post':
      metadata = {
        source_type: 'reddit_post',
        subreddit: String(m.subreddit ?? ''),
        author: String(m.author ?? ''),
        score: Number(m.score ?? 0),
        commentCount: Number(m.commentCount ?? m.comment_count ?? 0),
        permalink: String(m.permalink ?? video.source_url ?? ''),
      };
      break;
    case 'hn_story':
      metadata = {
        source_type: 'hn_story',
        author: String(m.author ?? ''),
        points: Number(m.points ?? 0),
        commentCount: Number(m.commentCount ?? m.comment_count ?? 0),
        url: String(m.url ?? video.source_url ?? ''),
      };
      break;
    default:
      return null;
  }

  return {
    document: {
      id: video.document_id,
      source_type: video.source_type,
      source_id: video.source_id,
      title: video.title,
      source_url: video.source_url ?? video.url ?? '',
      thumbnail_url: video.thumbnail_url,
      published_at: video.published_at,
    },
    metadata,
  };
}
