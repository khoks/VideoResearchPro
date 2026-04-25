export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: 'Pending',
    searching: 'Searching',
    awaiting_approval: 'Awaiting Approval',
    extracting: 'Extracting',
    building_rag: 'Building Knowledge Base',
    generating_report: 'Generating Report',
    completed: 'Completed',
    cancelled: 'Cancelled',
    failed: 'Failed',
  };
  return labels[status] || status;
}

/**
 * Semantic tone for a job status — resolved by theme-aware components.
 * Prefer this over `statusColor` (deprecated) since it adapts to dark mode.
 */
export type StatusTone = 'neutral' | 'info' | 'warn' | 'accent' | 'success' | 'error';

export function statusTone(status: string): StatusTone {
  const tones: Record<string, StatusTone> = {
    pending: 'neutral',
    searching: 'info',
    awaiting_approval: 'warn',
    extracting: 'info',
    building_rag: 'accent',
    generating_report: 'accent',
    completed: 'success',
    cancelled: 'neutral',
    failed: 'error',
  };
  return tones[status] ?? 'neutral';
}

/** @deprecated Use `statusTone` with `<ProgressBar tone={...} />`. */
export function statusColor(status: string): string {
  const colors: Record<string, string> = {
    pending: '#7d756b',
    searching: '#3d5a73',
    awaiting_approval: '#c79945',
    extracting: '#3d5a73',
    building_rag: '#7a2c1a',
    generating_report: '#7a2c1a',
    completed: '#2d4a3e',
    cancelled: '#7d756b',
    failed: '#7a2c1a',
  };
  return colors[status] || '#7d756b';
}
