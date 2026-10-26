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
  /** R4: null means auto. */
  output_length: OutputLength | null;
  /** R1 opt-in, carried through Duplicate and templates. */
  visual_analysis: boolean;
  /**
   * S-1.5.13: what the run searches, resolved (`['video']` by default).
   * Optional for responses from a server older than the field.
   */
  source_types?: string[];
  /** E-8.6: the template version this run started from, if any. */
  template_id: string | null;
  template_version: number | null;
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
  /** R1 opt-in; only ever carried from a run or template (S-1.18.2 deferred). */
  visual_analysis?: boolean;
  /** S-1.5.13: topic runs only; omitted means YouTube only. */
  source_types?: string[];
}

/** E-8.6: which template version a submission started from. */
export interface JobProvenance {
  templateId: string;
  templateVersion?: number;
}

export interface VideoApproval {
  approved_video_ids: string[];
}
