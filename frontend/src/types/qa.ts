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
 *   - "video"       (YouTube): video_title + channel_name + timestamp_display + youtube_link
 *   - "reddit_post":           thread_title + subreddit + author + permalink (#comment-<id> when applicable)
 *   - "hn_story":              story_title + author + permalink (item id deep-link)
 *
 * The connector contract (docs/source-types.md § Citations) defines
 * the per-source URL shape; backends building references should use
 * that contract.
 */
export type ReferenceSourceType = 'video' | 'reddit_post' | 'hn_story';

export interface Reference {
  /** Absent on legacy rows; defaults to "video" in the renderer. */
  source_type?: ReferenceSourceType;

  // YouTube fields (legacy, still primary for video sources)
  video_url: string;
  video_title: string;
  channel_name: string;
  timestamp_seconds: number;
  timestamp_display: string;
  youtube_link: string;

  // Polymorphic fields populated per source_type. The renderer reads
  // the appropriate set based on `source_type`.
  /** Reddit + HN: the canonical platform link, optionally with a
   *  comment / item anchor (`permalink#comment-<id>`). */
  permalink?: string;
  /** Reddit + HN: thread/story title (mirrors video_title for video). */
  thread_title?: string;
  /** Reddit: subreddit name (without leading "r/"). */
  subreddit?: string;
  /** Reddit + HN: post / story author handle. */
  author?: string;
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

export interface LibraryQAExchange {
  id: string;
  question: string;
  answer: string;
  references: Reference[];
  created_at: string;
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
