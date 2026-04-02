export interface WSProgressMessage {
  type: 'job_progress' | 'job_status_change' | 'job_error';
  job_id: string;
  status?: string;
  progress_pct?: number;
  message?: string;
  old_status?: string;
  new_status?: string;
  error?: string;
  data?: Record<string, unknown>;
  timestamp: string;
}
