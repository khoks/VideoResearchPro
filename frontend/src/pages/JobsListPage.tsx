import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useJobs, useCancelJob, useDeleteJob } from '../hooks/useJobs';
import { useAllJobsProgress } from '../hooks/useJobProgress';
import { ProgressBar } from '../components/common/ProgressBar';
import { Button, Card, EmptyState, Input, Select, Spinner, StatusPill } from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../theme';
import { formatDate, statusTone } from '../utils/formatters';
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
  if (job.job_type === 'subscription') {
    const list = channels && channels.length > 0 ? channels.join(', ') : '';
    return `Subscription: ${list}`;
  }
  if (channels && channels.length > 0) return channels.join(', ');
  return 'Channel Collection';
}

function jobTypeLabel(type: Job['job_type']): string {
  if (type === 'topic') return 'Topic';
  if (type === 'channel') return 'Channel';
  return 'Subscription';
}

export function JobsListPage() {
  const navigate = useNavigate();
  const c = useColors();
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
    return (
      <div style={{ textAlign: 'center', padding: space['8'] }}>
        <Spinner size={32} />
      </div>
    );
  }

  const hasNextPage = (jobs?.length ?? 0) === PAGE_SIZE;
  const showingEmpty = !isLoading && (!jobs || jobs.length === 0) && page === 0;

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
      <header style={{ marginBottom: space['5'] }}>
        <h1
          style={{
            fontFamily: fonts.display,
            fontSize: fontSize['2xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            margin: 0,
            lineHeight: lineHeight.tight,
          }}
        >
          Active runs
        </h1>
        <p
          style={{
            fontFamily: fonts.body,
            fontStyle: 'italic',
            fontSize: fontSize.sm,
            color: c.textMuted,
            margin: `${space['2']} 0 0`,
          }}
        >
          Every volume in progress, every volume retired.
        </p>
      </header>

      <Card style={{ marginBottom: space['4'] }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['3'], alignItems: 'center' }}>
          <div style={{ flex: '1 1 240px' }}>
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by topic or channel name…"
              aria-label="Search jobs"
            />
          </div>
          <div style={{ flex: '0 0 200px' }}>
            <Select
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value as '' | JobStatus); resetPage(); }}
              aria-label="Filter by status"
            >
              {STATUS_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </Select>
          </div>
          <div style={{ flex: '0 0 160px' }}>
            <Select
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value as SortOrder)}
              aria-label="Sort order"
            >
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
            </Select>
          </div>
        </div>
      </Card>

      {showingEmpty ? (
        <EmptyState
          title="No volumes on your shelf yet."
          description="Begin your first research run to start building your personal library."
          action={<Button onClick={() => navigate('/submit')}>New research</Button>}
        />
      ) : filteredJobs.length === 0 ? (
        <EmptyState
          size="sm"
          title="Nothing matches these filters."
          description="Adjust the search term or status filter to find the run you're after."
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
          {filteredJobs.map((job) => (
            <Card
              key={job.id}
              interactive
              onClick={() => navigate(`/jobs/${job.id}`)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  navigate(`/jobs/${job.id}`);
                }
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: space['3'],
                  marginBottom: space['3'],
                  flexWrap: 'wrap',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], minWidth: 0, flex: 1 }}>
                  <span
                    style={{
                      fontFamily: fonts.display,
                      fontWeight: fontWeight.semibold,
                      fontSize: fontSize.md,
                      color: c.textPrimary,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {jobTitle(job)}
                  </span>
                  <StatusPill status={job.status} size="sm" />
                  <span
                    style={{
                      fontFamily: fonts.ui,
                      fontSize: fontSize.xs,
                      color: c.textMuted,
                      textTransform: 'uppercase',
                      letterSpacing: '0.08em',
                      fontWeight: fontWeight.medium,
                    }}
                  >
                    {jobTypeLabel(job.job_type)}
                  </span>
                </div>
                <div
                  style={{ display: 'flex', gap: space['2'] }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <Button
                    size="sm"
                    variant="tertiary"
                    onClick={() => navigate('/submit', { state: { cloneFrom: job } })}
                  >
                    Duplicate
                  </Button>
                  {!['completed', 'cancelled', 'failed'].includes(job.status) && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => cancelJob.mutate(job.id)}
                    >
                      Cancel
                    </Button>
                  )}
                  {['completed', 'cancelled', 'failed'].includes(job.status) && (
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={() => deleteJob.mutate(job.id)}
                    >
                      Delete
                    </Button>
                  )}
                </div>
              </div>
              <ProgressBar value={job.progress_pct} tone={statusTone(job.status)} />
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: space['4'],
                  marginTop: space['2'],
                  fontFamily: fonts.ui,
                  fontSize: fontSize.xs,
                  color: c.textMuted,
                }}
              >
                <span
                  style={{
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {job.progress_message || '\u00a0'}
                </span>
                <span style={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
                  {job.video_count} videos · {job.transcript_count} transcripts · {formatDate(job.created_at)}
                </span>
              </div>
            </Card>
          ))}
        </div>
      )}

      {(page > 0 || hasNextPage) && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            gap: space['4'],
            marginTop: space['6'],
          }}
        >
          <Button
            size="sm"
            variant="tertiary"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            leadingIcon={<span aria-hidden>←</span>}
          >
            Previous
          </Button>
          <span
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              color: c.textSecondary,
              padding: `${space['1']} ${space['3']}`,
              border: `1px solid ${c.border}`,
              borderRadius: radius.pill,
            }}
          >
            Page {page + 1}
          </span>
          <Button
            size="sm"
            variant="tertiary"
            disabled={!hasNextPage}
            onClick={() => setPage((p) => p + 1)}
            trailingIcon={<span aria-hidden>→</span>}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
