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

export function statusColor(status: string): string {
  const colors: Record<string, string> = {
    pending: '#94a3b8',
    searching: '#3b82f6',
    awaiting_approval: '#f59e0b',
    extracting: '#3b82f6',
    building_rag: '#8b5cf6',
    generating_report: '#8b5cf6',
    completed: '#22c55e',
    cancelled: '#94a3b8',
    failed: '#ef4444',
  };
  return colors[status] || '#94a3b8';
}
