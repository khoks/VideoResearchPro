/**
 * Report body as served by `GET /api/v1/jobs/{id}/report/body` (S-8.8.1).
 *
 * `html` is the LLM-written section markup with the template chrome removed.
 * It is NOT sanitised server-side: the reader must pass it through
 * `sanitizeReportHtml` before it reaches the parser.
 */
export interface ChannelBreakdownRow {
  channel_name: string;
  video_count: number | null;
  word_count: number | null;
  minutes: number | null;
}

export interface ReportStatistics {
  video_count: number | null;
  transcript_count: number | null;
  total_words: number | null;
  total_minutes: number | null;
  channel_breakdown: ChannelBreakdownRow[];
}

export interface ReportBody {
  job_id: string;
  job_type: 'topic' | 'channel' | 'subscription';
  title: string;
  html: string;
  statistics: ReportStatistics | null;
  generated_at: string | null;
}
