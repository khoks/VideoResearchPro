export type JobType = 'topic' | 'channel' | 'subscription';

export type JobStatus =
  | 'pending'
  | 'searching'
  | 'awaiting_approval'
  | 'extracting'
  | 'building_rag'
  | 'generating_report'
  | 'completed'
  | 'cancelled'
  | 'failed';

export interface Job {
  id: string;
  job_type: JobType;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  topic: string | null;
  search_instructions: string | null;
  num_videos: number;
  min_duration_minutes: number | null;
  max_duration_minutes: number | null;
  channel_type_filters: string[] | null;
  preferred_channels: string[] | null;
  channel_list: string[] | null;
  videos_per_channel: number | null;
  progress_pct: number;
  progress_message: string | null;
  error_message: string | null;
  video_count: number;
  transcript_count: number;
  has_report: boolean;
}

export type OutputLength = 'auto' | 'brief' | 'standard' | 'deep';

export interface JobCreate {
  job_type: JobType;
  topic?: string;
  search_instructions?: string;
  num_videos?: number;
  min_duration_minutes?: number;
  max_duration_minutes?: number;
  channel_type_filters?: string[];
  preferred_channels?: string[];
  channel_list?: string[];
  videos_per_channel?: number;
  /** R4: optional report depth. Omitted/'auto' lets corpus size decide. */
  output_length?: OutputLength;
}

export interface VideoApproval {
  approved_video_ids: string[];
}
