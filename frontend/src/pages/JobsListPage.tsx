import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useJobs, useCancelJob, useDeleteJob } from '../hooks/useJobs';
import { useAllJobsProgress } from '../hooks/useJobProgress';
import { StatusBadge } from '../components/common/StatusBadge';
import { ProgressBar } from '../components/common/ProgressBar';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { formatDate, statusColor } from '../utils/formatters';
import type { Job, JobStatus } from '../types/job';

const PAGE_SIZE = 20;

const STATUS_OPTIONS: { value: '' | JobStatus; label: string }[] = [
  { value: '', label: 'All statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'searching', label: 'Searching' },
  { value: 'awaiting_approval', label: 'Awaiting Approval' },
  { value: 'extracting', label: 'Extracting' },
  { value: 'building_rag', label: 'Building Knowledge Base' },
  { value: 'generating_report', label: 'Generating Report' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'failed', label: 'Failed' },
];

type SortOrder = 'newest' | 'oldest';

function jobTitle(job: Job): string {
  if (job.job_type === 'topic') return job.topic ?? 'Untitled topic';
  const channels = job.channel_list;
  if (channels && channels.length > 0) return channels.join(', ');
  return 'Channel Collection';
}

export function JobsListPage() {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState<'' | JobStatus>('');
  const [search, setSearch] = useState('');
  const [sortOrder, setSortOrder] = useState<SortOrder>('newest');
  const [page, setPage] = useState(0);

  const { data: jobs, isLoading } = useJobs({
    status: statusFilter || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });
  const cancelJob = useCancelJob();
  const deleteJob = useDeleteJob();

  const activeJobIds = (jobs || [])
    .filter(j => !['completed', 'cancelled', 'failed'].includes(j.status))
    .map(j => j.id);
  useAllJobsProgress(activeJobIds);

  const filteredJobs = useMemo(() => {
    if (!jobs) return [];
    const term = search.trim().toLowerCase();
    const matched = term
      ? jobs.filter(job => {
          if (job.job_type === 'topic') return (job.topic ?? '').toLowerCase().includes(term);
          return (job.channel_list ?? []).some(c => c.toLowerCase().includes(term));
        })
      : jobs;
    return [...matched].sort((a, b) => {
      const diff = new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      return sortOrder === 'newest' ? diff : -diff;
    });
  }, [jobs, search, sortOrder]);

  const resetPage = () => setPage(0);

  if (isLoading && page === 0) {
    return <div style={{ textAlign: 'center', padding: '3rem' }}><LoadingSpinner size={40} /></div>;
  }

  const hasNextPage = (jobs?.length ?? 0) === PAGE_SIZE;
  const showingEmpty = !isLoading && (!jobs || jobs.length === 0) && page === 0;

  return (
    <div>
      <h2 style={{ marginBottom: '1rem', color: 'var(--color-text)' }}>Research Jobs</h2>

      <div style={{
        background: 'var(--color-surface)', borderRadius: 12, padding: '1rem', marginBottom: '1rem',
        boxShadow: 'var(--shadow-card)', display: 'flex', flexWrap: 'wrap',
        gap: '0.75rem', alignItems: 'center',
      }}>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by topic or channel name..."
          style={{
            flex: '1 1 240px', padding: '0.5rem 0.75rem', borderRadius: 8,
            border: '1px solid var(--color-border)', fontSize: '0.9rem',
            background: 'var(--color-surface)', color: 'var(--color-text)',
          }}
        />
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value as '' | JobStatus); resetPage(); }}
          style={{
            padding: '0.5rem 0.75rem', borderRadius: 8, border: '1px solid var(--color-border)',
            fontSize: '0.9rem', background: 'var(--color-surface)', color: 'var(--color-text)',
          }}
        >
          {STATUS_OPTIONS.map(opt => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
        <select
          value={sortOrder}
          onChange={(e) => setSortOrder(e.target.value as SortOrder)}
          style={{
            padding: '0.5rem 0.75rem', borderRadius: 8, border: '1px solid var(--color-border)',
            fontSize: '0.9rem', background: 'var(--color-surface)', color: 'var(--color-text)',
          }}
        >
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
        </select>
      </div>

      {showingEmpty ? (
        <div style={{ textAlign: 'center', padding: '3rem', color: '#64748b' }}>
          <p style={{ fontSize: '1.1rem' }}>No jobs yet. Submit your first research job!</p>
        </div>
      ) : filteredJobs.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '2rem', color: '#64748b' }}>
          <p>No jobs match the current filters.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {filteredJobs.map((job) => (
            <div key={job.id} onClick={() => navigate(`/jobs/${job.id}`)} style={{
              background: '#fff', borderRadius: 12, padding: '1.2rem', cursor: 'pointer',
              boxShadow: '0 1px 3px rgba(0,0,0,0.08)', border: '1px solid #e2e8f0',
              transition: 'box-shadow 0.2s',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', minWidth: 0, flex: 1 }}>
                  <span style={{
                    fontWeight: 600, color: '#1e293b', overflow: 'hidden',
                    textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {jobTitle(job)}
                  </span>
                  <StatusBadge status={job.status} />
                  <span style={{ fontSize: '0.8rem', color: '#94a3b8', textTransform: 'uppercase' }}>
                    {job.job_type}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem' }} onClick={(e) => e.stopPropagation()}>
                  {!['completed', 'cancelled', 'failed'].includes(job.status) && (
                    <SmallButton color="#f59e0b" onClick={() => cancelJob.mutate(job.id)}>Cancel</SmallButton>
                  )}
                  {['completed', 'cancelled', 'failed'].includes(job.status) && (
                    <SmallButton color="#ef4444" onClick={() => deleteJob.mutate(job.id)}>Delete</SmallButton>
                  )}
                </div>
              </div>
              <div style={{ marginBottom: '0.5rem' }}>
                <ProgressBar value={job.progress_pct} color={statusColor(job.status)} />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#94a3b8', gap: '1rem' }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {job.progress_message || ''}
                </span>
                <span style={{ flexShrink: 0 }}>
                  {job.video_count} videos | {job.transcript_count} transcripts | {formatDate(job.created_at)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {(page > 0 || hasNextPage) && (
        <div style={{
          display: 'flex', justifyContent: 'center', alignItems: 'center',
          gap: '1rem', marginTop: '1.5rem',
        }}>
          <button
            onClick={() => setPage(p => Math.max(0, p - 1))}
            disabled={page === 0}
            style={{
              background: '#fff', color: '#667eea', border: '1px solid #e2e8f0',
              padding: '0.5rem 1rem', borderRadius: 8,
              cursor: page === 0 ? 'not-allowed' : 'pointer',
              opacity: page === 0 ? 0.5 : 1, fontWeight: 600, fontSize: '0.85rem',
            }}
          >
            &larr; Previous
          </button>
          <span style={{ fontSize: '0.85rem', color: '#64748b' }}>Page {page + 1}</span>
          <button
            onClick={() => setPage(p => p + 1)}
            disabled={!hasNextPage}
            style={{
              background: '#fff', color: '#667eea', border: '1px solid #e2e8f0',
              padding: '0.5rem 1rem', borderRadius: 8,
              cursor: !hasNextPage ? 'not-allowed' : 'pointer',
              opacity: !hasNextPage ? 0.5 : 1, fontWeight: 600, fontSize: '0.85rem',
            }}
          >
            Next &rarr;
          </button>
        </div>
      )}
    </div>
  );
}

function SmallButton({ color, onClick, children }: {
  color: string; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button onClick={onClick} style={{
      background: 'transparent', color, border: `1px solid ${color}`,
      padding: '0.25rem 0.75rem', borderRadius: 6, fontSize: '0.75rem',
      cursor: 'pointer', fontWeight: 600,
    }}>
      {children}
    </button>
  );
}
