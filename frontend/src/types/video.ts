export interface Video {
  id: string;
  video_id: string;
  title: string;
  channel_name: string;
  channel_id: string;
  url: string;
  duration_seconds: number;
  published_at: string | null;
  thumbnail_url: string | null;
  approved: boolean;
  transcript_status: string;
  transcript_word_count: number | null;
  transcript_language: string | null;
}
