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
    case 'mastodon_post': {
      // Mastodon `acct` is `user@instance`; split for chip rendering
      // unless the backend already supplied an `instance` field
      // (forward-compat for when chunking starts emitting it).
      const acct = String(m.author ?? m.acct ?? '');
      const explicitInstance = m.instance ? String(m.instance) : '';
      const splitInstance = acct.includes('@') ? acct.split('@')[1] : '';
      const splitUser = acct.includes('@') ? acct.split('@')[0] : acct;
      metadata = {
        source_type: 'mastodon_post',
        author: splitUser,
        instance: explicitInstance || splitInstance,
        favourites: Number(
          m.favourites ?? m.favourites_count ?? m.favorites ?? 0,
        ),
        replyCount: Number(m.replyCount ?? m.replies_count ?? m.reply_count ?? 0),
        permalink: String(m.permalink ?? video.source_url ?? ''),
      };
      break;
    }
    case 'bluesky_post':
      metadata = {
        source_type: 'bluesky_post',
        // Bluesky author is the bare handle (e.g. `alice.bsky.social`).
        // Strip a leading `@` if present so chip formatters that prepend
        // `@` don't double it.
        author: String(m.author ?? m.handle ?? '').replace(/^@/, ''),
        likes: Number(m.likes ?? m.likeCount ?? m.like_count ?? 0),
        replyCount: Number(m.replyCount ?? m.replies ?? m.replyCount ?? 0),
        repostCount: Number(m.repostCount ?? m.repostCount ?? m.reposts ?? 0),
        permalink: String(m.permalink ?? video.source_url ?? ''),
      };
      break;
    case 'podcast_episode':
      metadata = {
        source_type: 'podcast_episode',
        showName: String(m.show_name ?? m.showName ?? video.channel_name ?? ''),
        // `episode_number` is optional in podcasts — many shows don't
        // number episodes. We coerce to `null` so the chip formatter
        // can render an em-dash when absent.
        episodeNumber:
          m.episode_number != null
            ? Number(m.episode_number)
            : m.episodeNumber != null
            ? Number(m.episodeNumber)
            : null,
        durationSec: Number(video.duration_seconds ?? 0),
        publishedAt: String(video.published_at ?? ''),
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
