/**
 * Per-citation reference returned by the Q&A agent.
 *
 * Pre-S-1.5.5 the shape was YouTube-only (video_title, channel_name,
 * timestamp). Post-S-1.5.5 it carries an optional `source_type`
 * discriminator that the frontend dispatches on for rendering. When
 * absent the renderer falls back to the YouTube format for back-compat
 * with existing Q&A history rows.
 *
 * The polymorphic fields below are populated based on `source_type`:
 *   - "video"          (YouTube):  video_title + channel_name + timestamp_display + youtube_link
 *   - "reddit_post":               thread_title + subreddit + author + permalink (#comment-<id> when applicable)
 *   - "hn_story":                  story_title + author + permalink (item id deep-link)
 *   - "mastodon_post":             status_title + author + instance + permalink (status URL — points at reply
 *                                  when comment_id was indexed alongside `comment_url`)
 *   - "bluesky_post":              post_title + author + permalink (bsky.app web URL — points at reply
 *                                  when comment_id was indexed alongside `comment_url`)
 *
 * The connector contract (docs/source-types.md § Citations) defines
 * the per-source URL shape; backends building references should use
 * that contract.
 */
export type ReferenceSourceType =
  | 'video'
  | 'reddit_post'
  | 'hn_story'
  | 'mastodon_post'
  | 'bluesky_post'
  | 'podcast_episode'
  | 'pdf'
  | 'article'
  | 'fb_post'
  | 'ig_post'
  | 'li_post'
  | 'tweet'
  | 'note';

export interface Reference {
  /** Absent on legacy rows; defaults to "video" in the renderer. */
  source_type?: ReferenceSourceType;

  // YouTube fields (legacy, still primary for video sources)
  /** Present on library Q&A references; job references carry it in the URL. */
  video_id?: string;
  video_url: string;
  video_title: string;
  channel_name: string;
  timestamp_seconds: number;
  timestamp_display: string;
  youtube_link: string;

  // Polymorphic fields populated per source_type. The renderer reads
  // the appropriate set based on `source_type`.
  /** Reddit + HN + Mastodon: the canonical platform link, optionally with a
   *  comment / item anchor (`permalink#comment-<id>`) or a per-reply
   *  status URL (Mastodon). */
  permalink?: string;
  /** Reddit + HN + Mastodon: thread/story title (mirrors video_title for video). */
  thread_title?: string;
  /** Reddit: subreddit name (without leading "r/"). */
  subreddit?: string;
  /** Reddit + HN + Mastodon: post / story / status author handle. */
  author?: string;
  /** Mastodon: instance host (e.g. `mastodon.social`). Empty string when unknown. */
  instance?: string;
  /** PDF: 1-indexed page number where the chunk's dominant segment lives. */
  page_number?: string;

  // S-8.5.2: the asker's own note, cited like a source. The renderer shows
  // "You wrote this on <date>" and links to what the note is on.
  note_id?: string;
  note_target_type?: string;
  note_target_id?: string;
  note_target_label?: string | null;
  /** qa_exchange targets only: the job that holds the exchange. */
  note_target_parent_id?: string | null;
  /** ISO-8601 with offset. */
  note_created_at?: string;
  /** The note's opening, for the hover title. */
  quote?: string;
}

export interface QAExchange {
  id: string;
  question: string;
  answer: string;
  references: Reference[];
  created_at: string;
}

export interface QARequest {
  question: string;
  context?: string;
}

export interface ClarifyRequest {
  question: string;
}

export interface ClarifyResponse {
  interpretation: string;
  clarifications: string[];
}

export type AnswerLanguage = 'en' | 'hi' | 'es' | 'fr';

/**
 * What a library question was asked over (S-8.1.4; backend
 * `app/schemas/qa_scope.py`). Null is the whole library. `shelf_id` narrows to
 * a shelf's documents; `saved_search_id` only records that a saved search's run
 * asked it. Unknown keys may appear from newer builds: keep, don't interpret.
 */
export interface QAScope {
  shelf_id?: string | null;
  saved_search_id?: string | null;
  [key: string]: unknown;
}

export interface LibraryQAExchange {
  id: string;
  question: string;
  answer: string;
  references: Reference[];
  /** The backend has always sent it; typed for S-8.3.2's pin. */
  answer_language?: string;
  created_at: string;
  scope?: QAScope | null;
}

export interface LibraryQARequest {
  question: string;
  answer_language: AnswerLanguage;
  context?: string;
}

export interface LibraryClarifyRequest {
  question: string;
}

export type QAHistorySourceType = 'job' | 'library' | 'history';

export interface QAHistoryReference {
  source_type: QAHistorySourceType;
  exchange_id: string;
  question_preview: string;
  job_id?: string | null;
  original_created_at: string;
}

export interface QAHistoryExchange {
  id: string;
  question: string;
  answer: string;
  references: QAHistoryReference[];
  answer_language: AnswerLanguage;
  created_at: string;
}

export interface QAHistoryChatRequest {
  question: string;
  answer_language?: AnswerLanguage;
}
