import { useNavigate } from 'react-router-dom';
import { useJobs, useCancelJob, useDeleteJob } from '../hooks/useJobs';
import { useAllJobsProgress } from '../hooks/useJobProgress';
import { StatusBadge } from '../components/common/StatusBadge';
import { ProgressBar } from '../components/common/ProgressBar';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { formatDate, statusColor } from '../utils/formatters';

export function JobsListPage() {
  const navigate = useNavigate();
  const { data: jobs, isLoading } = useJobs();
  const cancelJob = useCancelJob();
  const deleteJob = useDeleteJob();

  // Subscribe to progress for all active jobs
  const activeJobIds = (jobs || [])
    .filter(j => !['completed', 'cancelled', 'failed'].includes(j.status))
    .map(j => j.id);
  useAllJobsProgress(activeJobIds);

  if (isLoading) return <div style={{ textAlign: 'center', padding: '3rem' }}><LoadingSpinner size={40} /></div>;

  if (!jobs || jobs.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '3rem', color: '#64748b' }}>
        <p style={{ fontSize: '1.1rem' }}>No jobs yet. Submit your first research job!</p>
      </div>
    );
  }

  return (
    <div>
      <h2 style={{ marginBottom: '1rem', color: '#1e293b' }}>Research Jobs</h2>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {jobs.map((job) => (
          <div key={job.id} onClick={() => navigate(`/jobs/${job.id}`)} style={{
            background: '#fff', borderRadius: 12, padding: '1.2rem', cursor: 'pointer',
            boxShadow: '0 1px 3px rgba(0,0,0,0.08)', border: '1px solid #e2e8f0',
            transition: 'box-shadow 0.2s',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <span style={{ fontWeight: 600, color: '#1e293b' }}>
                  {job.job_type === 'topic' ? job.topic : 'Channel Collection'}
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
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#94a3b8' }}>
              <span>{job.progress_message || ''}</span>
              <span>{formatDate(job.created_at)}</span>
            </div>
          </div>
        ))}
      </div>
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
