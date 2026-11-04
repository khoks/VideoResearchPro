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

/**
 * T-8.3.3.8: a new notification for the signed-in user. A doorbell, not the
 * letter: the bell refetches `GET /notifications` for the text.
 */
export interface WSNotificationMessage {
  type: 'notification';
  id: string;
  kind?: string;
}
