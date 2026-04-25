import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { useJob, useJobVideos, useApproveJob, useCancelJob, useDeleteJob } from '../hooks/useJobs';
import { useJobProgress } from '../hooks/useJobProgress';
import { useQAHistory, useAskQuestion, useClarifyQuestion } from '../hooks/useQA';
import { useFeatureAvailable } from '../hooks/useFeatureAvailable';
import { ProgressBar } from '../components/common/ProgressBar';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  FormField,
  Input,
  Select,
  Spinner,
  StatusPill,
} from '../components/primitives';
import { useColors, useShadows } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space, z } from '../theme';
import { formatDuration, formatDate, statusTone } from '../utils/formatters';
import { useJobStore } from '../stores/jobStore';
import { useAuth } from '../contexts/AuthContext';
import { wsClient } from '../services/wsClient';
import { VideoKnowledgeDrawer } from './VideoKnowledgePage';
import type { Video } from '../types/video';
import type { QAExchange } from '../types/qa';
import type { Job } from '../types/job';

const FEATURE_UNAVAILABLE_MSG = 'LLM-dependent feature is temporarily unavailable';

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const c = useColors();
  const { data: job, isLoading } = useJob(jobId || null);
  const { data: videos } = useJobVideos(jobId || null);
  const approveJob = useApproveJob();
  const cancelJob = useCancelJob();
  const deleteJob = useDeleteJob();
  const { isReportModalOpen, openReportModal, closeReportModal } = useJobStore();

  useJobProgress(jobId || null);
  const syncCounts = useSubscriptionSyncCounts(jobId || null);
  const [knowledgeVideo, setKnowledgeVideo] = useState<Video | null>(null);
  const knowledgeExtractionAvailable = useFeatureAvailable('knowledge_extraction');

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: space['8'] }}>
        <Spinner size={32} />
      </div>
    );
  }
  if (!job) {
    return (
      <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
        <EmptyState
          title="We can't find that job."
          description="It may have been deleted, or the link is stale."
          action={<Button onClick={() => navigate('/jobs')}>Back to active runs</Button>}
        />
      </div>
    );
  }

  const isSubscription = job.job_type === 'subscription';
  const showApproval = !isSubscription && job.status === 'awaiting_approval';
  const showReportButton = job.has_report && !isSubscription;
  const videosHeading = isSubscription ? 'Synced videos' : 'Videos';
  const isSyncing = job.status === 'extracting' || job.status === 'building_rag';
  const isActive = !['completed', 'cancelled', 'failed'].includes(job.status);

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: space['4'] }}>
      <Button
        variant="tertiary"
        size="sm"
        onClick={() => navigate('/jobs')}
        leadingIcon={<span aria-hidden>←</span>}
        style={{ alignSelf: 'flex-start' }}
      >
        Back to active runs
      </Button>

      <Card>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: space['4'],
            marginBottom: space['4'],
            flexWrap: 'wrap',
          }}
        >
          <div style={{ flex: '1 1 360px', minWidth: 0 }}>
            <h1
              style={{
                fontFamily: fonts.display,
                fontSize: fontSize['2xl'],
                fontWeight: fontWeight.semibold,
                color: c.textPrimary,
                margin: 0,
                lineHeight: lineHeight.tight,
                overflowWrap: 'anywhere',
              }}
            >
              {jobHeaderTitle(job)}
            </h1>
            <p
              style={{
                margin: `${space['2']} 0 0`,
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                color: c.textMuted,
              }}
            >
              Created {formatDate(job.created_at)} · {jobTypeLabel(job.job_type)} job
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
            <StatusPill status={job.status} />
            <Button
              variant="tertiary"
              size="sm"
              onClick={() => navigate('/submit', { state: { cloneFrom: job } })}
              title="Open the submit form pre-filled from this job's parameters"
            >
              Duplicate · Re-run
            </Button>
            {isActive && (
              <Button variant="secondary" size="sm" onClick={() => cancelJob.mutate(job.id)}>
                Cancel
              </Button>
            )}
            {!isActive && (
              <Button
                variant="danger"
                size="sm"
                onClick={() => { deleteJob.mutate(job.id); navigate('/jobs'); }}
              >
                Delete
              </Button>
            )}
          </div>
        </div>
        <ProgressBar value={job.progress_pct} tone={statusTone(job.status)} />
        <p
          style={{
            margin: `${space['2']} 0 0`,
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            color: c.textSecondary,
          }}
        >
          {job.progress_message} ({job.progress_pct}%)
        </p>
        {job.error_message && (
          <p
            style={{
              color: c.error,
              margin: `${space['2']} 0 0`,
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
            }}
          >
            Error: {job.error_message}
          </p>
        )}
      </Card>

      <JobParamsCard job={job} />

      {isSubscription && isSyncing && syncCounts && <SubscriptionSyncCard counts={syncCounts} />}

      {showApproval && videos && (
        <VideoApprovalSection videos={videos} jobId={job.id} onApprove={approveJob.mutateAsync} />
      )}

      {!showApproval && videos && videos.length > 0 && (
        <Card>
          <SectionHeader title={`${videosHeading} (${videos.length})`} />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {videos.map((v, i) => (
              <div
                key={v.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: space['3'],
                  padding: `${space['3']} 0`,
                  borderBottom: i < videos.length - 1 ? `1px solid ${c.border}` : 'none',
                }}
              >
                <div style={{ minWidth: 0, flex: 1 }}>
                  <a
                    href={v.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      color: c.accent,
                      textDecoration: 'none',
                      fontFamily: fonts.ui,
                      fontWeight: fontWeight.medium,
                      fontSize: fontSize.sm,
                    }}
                  >
                    {v.title}
                  </a>
                  <div
                    style={{
                      fontFamily: fonts.ui,
                      fontSize: fontSize.xs,
                      color: c.textMuted,
                      marginTop: 2,
                    }}
                  >
                    {v.channel_name} · {formatDuration(v.duration_seconds)} · {v.transcript_status}
                  </div>
                </div>
                {v.transcript_status === 'fetched' && (
                  <Button
                    size="sm"
                    variant="tertiary"
                    onClick={() => setKnowledgeVideo(v)}
                    disabled={!knowledgeExtractionAvailable}
                    title={
                      knowledgeExtractionAvailable
                        ? 'Generate or view the AI knowledge report for this video.'
                        : FEATURE_UNAVAILABLE_MSG
                    }
                  >
                    Knowledge
                  </Button>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {showReportButton && (
        <Button onClick={openReportModal} style={{ alignSelf: 'flex-start' }}>
          View report
        </Button>
      )}

      {isReportModalOpen && showReportButton && (
        <ReportModal jobId={job.id} onClose={closeReportModal} />
      )}

      {job.status === 'completed' && <QASection jobId={job.id} />}

      {knowledgeVideo && (
        <VideoKnowledgeDrawer
          videoId={knowledgeVideo.video_id}
          videoTitle={knowledgeVideo.title}
          onClose={() => setKnowledgeVideo(null)}
        />
      )}
    </div>
  );
}

function SectionHeader({ title, description }: { title: ReactNode; description?: ReactNode }) {
  const c = useColors();
  return (
    <header style={{ marginBottom: space['4'] }}>
      <h3
        style={{
          margin: 0,
          fontFamily: fonts.display,
          fontSize: fontSize.lg,
          fontWeight: fontWeight.semibold,
          color: c.textPrimary,
          lineHeight: lineHeight.tight,
        }}
      >
        {title}
      </h3>
      {description && (
        <p
          style={{
            margin: `${space['1']} 0 0`,
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            color: c.textMuted,
          }}
        >
          {description}
        </p>
      )}
    </header>
  );
}

function jobHeaderTitle(job: Job): string {
  if (job.job_type === 'topic') return job.topic ?? 'Untitled topic';
  if (job.job_type === 'subscription') {
    const list = job.channel_list && job.channel_list.length > 0 ? job.channel_list.join(', ') : '';
    return `Subscription: ${list}`;
  }
  return 'Channel Collection';
}

function jobTypeLabel(type: Job['job_type']): string {
  if (type === 'topic') return 'Topic';
  if (type === 'channel') return 'Channel';
  return 'Subscription';
}

// Renders every non-empty submission parameter so the user can see exactly
// what this job was run with — supports the "view it entirely, duplicate,
// or tweak and re-run" workflow. Empty/null fields are omitted so the card
// doesn't bloat for minimal topic jobs.
function JobParamsCard({ job }: { job: Job }) {
  const c = useColors();
  const rows: Array<[string, ReactNode]> = [];

  rows.push([
    'Job ID',
    <code style={{ fontFamily: fonts.mono, fontSize: fontSize.xs, color: c.textSecondary }}>{job.id}</code>,
  ]);
  rows.push(['Type', <span style={{ textTransform: 'capitalize' }}>{job.job_type}</span>]);

  if (job.topic) rows.push(['Topic', job.topic]);
  if (job.search_instructions) {
    rows.push(['Search instructions', <span style={{ whiteSpace: 'pre-wrap' }}>{job.search_instructions}</span>]);
  }
  if (job.num_videos != null) rows.push(['Number of videos', String(job.num_videos)]);
  if (job.min_duration_minutes != null) rows.push(['Min duration', `${job.min_duration_minutes} min`]);
  if (job.max_duration_minutes != null) rows.push(['Max duration', `${job.max_duration_minutes} min`]);
  if (job.channel_type_filters && job.channel_type_filters.length > 0) {
    rows.push(['Channel type filters', job.channel_type_filters.join(', ')]);
  }
  if (job.preferred_channels && job.preferred_channels.length > 0) {
    rows.push(['Preferred channels', <span style={{ whiteSpace: 'pre-wrap' }}>{job.preferred_channels.join('\n')}</span>]);
  }
  if (job.channel_list && job.channel_list.length > 0) {
    rows.push([
      job.job_type === 'subscription' ? 'Subscribed channels' : 'Channels',
      <span style={{ whiteSpace: 'pre-wrap' }}>{job.channel_list.join('\n')}</span>,
    ]);
  }
  if (job.job_type === 'channel' && job.videos_per_channel != null) {
    rows.push(['Videos per channel', String(job.videos_per_channel)]);
  }

  return (
    <Card>
      <SectionHeader title="Job parameters" />
      <dl
        style={{
          margin: 0,
          display: 'grid',
          gridTemplateColumns: 'max-content 1fr',
          columnGap: space['4'],
          rowGap: space['2'],
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
        }}
      >
        {rows.map(([label, value], i) => (
          <div key={i} style={{ display: 'contents' }}>
            <dt style={{ color: c.textSecondary, fontWeight: fontWeight.medium }}>{label}</dt>
            <dd style={{ margin: 0, color: c.textPrimary, overflowWrap: 'anywhere' }}>{value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

interface SyncCounts {
  reused_count: number;
  newly_processed_count: number;
  total_count: number;
}

// Fields are published by the subscription ingestion pipeline; other job types
// never emit them, so counts stay null for topic/channel jobs.
function useSubscriptionSyncCounts(jobId: string | null): SyncCounts | null {
  const [counts, setCounts] = useState<SyncCounts | null>(null);

  useEffect(() => {
    setCounts(null);
    if (!jobId) return;
    return wsClient.subscribe(jobId, (msg) => {
      const data = msg.data;
      if (!data) return;
      const reused = data.reused_count;
      const newly = data.newly_processed_count;
      const total = data.total_count;
      if (typeof reused === 'number' && typeof newly === 'number' && typeof total === 'number') {
        setCounts({ reused_count: reused, newly_processed_count: newly, total_count: total });
      }
    });
  }, [jobId]);

  return counts;
}

function SubscriptionSyncCard({ counts }: { counts: SyncCounts }) {
  const c = useColors();
  const { reused_count, newly_processed_count, total_count } = counts;

  const Stat = ({ label, value }: { label: string; value: ReactNode }) => (
    <div>
      <div
        style={{
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          color: c.textMuted,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: fonts.display,
          fontSize: fontSize.lg,
          fontWeight: fontWeight.semibold,
          color: c.textPrimary,
        }}
      >
        {value}
      </div>
    </div>
  );

  return (
    <Card>
      <SectionHeader title="Sync progress" />
      <div style={{ display: 'flex', gap: space['6'], flexWrap: 'wrap' }}>
        <Stat label="Reused" value={`${reused_count} / ${total_count}`} />
        <Stat label="Newly processed" value={`${newly_processed_count} / ${total_count}`} />
      </div>
    </Card>
  );
}

type VideoSortKey = 'channel' | 'duration' | 'title';

function VideoApprovalSection({
  videos,
  jobId,
  onApprove,
}: {
  videos: Video[];
  jobId: string;
  onApprove: (args: { id: string; data: { approved_video_ids: string[] } }) => Promise<unknown>;
}) {
  const c = useColors();
  // Use YouTube video_id (not internal UUID) so the approval payload matches
  // what the backend expects in approved_video_ids.
  const [selected, setSelected] = useState<Set<string>>(new Set(videos.map((v) => v.video_id)));
  const [sortKey, setSortKey] = useState<VideoSortKey>('channel');

  const sortedVideos = useMemo(() => {
    const copy = [...videos];
    copy.sort((a, b) => {
      if (sortKey === 'duration') return a.duration_seconds - b.duration_seconds;
      if (sortKey === 'title') return a.title.localeCompare(b.title);
      return a.channel_name.localeCompare(b.channel_name);
    });
    return copy;
  }, [videos, sortKey]);

  const toggleVideo = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const selectAll = () => setSelected(new Set(videos.map((v) => v.video_id)));
  const deselectAll = () => setSelected(new Set());

  const handleApprove = () => {
    onApprove({ id: jobId, data: { approved_video_ids: Array.from(selected) } });
  };

  const thumbPlaceholder: CSSProperties = {
    width: 96,
    height: 54,
    borderRadius: radius.sm,
    background: c.surfaceAlt,
    flexShrink: 0,
    cursor: 'pointer',
    objectFit: 'cover',
  };

  return (
    <Card>
      <SectionHeader
        title={`Review videos (${selected.size}/${videos.length} selected)`}
        description="Deselect any videos you don't want to include, then approve to continue."
      />

      <div
        style={{
          display: 'flex',
          gap: space['2'],
          alignItems: 'center',
          flexWrap: 'wrap',
          marginBottom: space['4'],
        }}
      >
        <Button size="sm" variant="tertiary" onClick={selectAll}>
          Select all
        </Button>
        <Button size="sm" variant="tertiary" onClick={deselectAll}>
          Deselect all
        </Button>
        <label
          style={{
            marginLeft: 'auto',
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            color: c.textSecondary,
            display: 'flex',
            alignItems: 'center',
            gap: space['2'],
          }}
        >
          <span>Sort by</span>
          <div style={{ minWidth: 140 }}>
            <Select value={sortKey} onChange={(e) => setSortKey(e.target.value as VideoSortKey)}>
              <option value="channel">Channel</option>
              <option value="duration">Duration</option>
              <option value="title">Title</option>
            </Select>
          </div>
        </label>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {sortedVideos.map((v, i) => (
          <div
            key={v.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: space['3'],
              padding: space['2'],
              borderBottom: i < sortedVideos.length - 1 ? `1px solid ${c.border}` : 'none',
            }}
          >
            <input
              type="checkbox"
              checked={selected.has(v.video_id)}
              onChange={() => toggleVideo(v.video_id)}
              style={{ cursor: 'pointer', accentColor: c.accent }}
            />
            {v.thumbnail_url ? (
              <img src={v.thumbnail_url} alt="" onClick={() => toggleVideo(v.video_id)} style={thumbPlaceholder} />
            ) : (
              <div onClick={() => toggleVideo(v.video_id)} style={thumbPlaceholder} />
            )}
            <div onClick={() => toggleVideo(v.video_id)} style={{ flex: 1, minWidth: 0, cursor: 'pointer' }}>
              <div
                style={{
                  fontFamily: fonts.ui,
                  fontSize: fontSize.sm,
                  fontWeight: fontWeight.medium,
                  color: c.textPrimary,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {v.title}
              </div>
              <div
                style={{
                  fontFamily: fonts.ui,
                  fontSize: fontSize.xs,
                  color: c.textMuted,
                  marginTop: 2,
                }}
              >
                {v.channel_name} · {formatDuration(v.duration_seconds)}
              </div>
            </div>
            <a
              href={v.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: c.accent,
                textDecoration: 'none',
                fontFamily: fonts.ui,
                fontSize: fontSize.xs,
                fontWeight: fontWeight.semibold,
                border: `1px solid ${c.accent}`,
                padding: `${space['1']} ${space['2']}`,
                borderRadius: radius.sm,
                flexShrink: 0,
              }}
            >
              Watch
            </a>
          </div>
        ))}
      </div>

      <div style={{ marginTop: space['4'] }}>
        <Button onClick={handleApprove} leadingIcon={<span aria-hidden>✓</span>}>
          Approve &amp; continue ({selected.size} videos)
        </Button>
      </div>
    </Card>
  );
}

function ReportModal({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  // The /report endpoint is protected by JWT. An <iframe src> (and window.open
  // via target="_blank") is a plain browser navigation that cannot carry the
  // Authorization header our axios interceptor adds, so we thread the token
  // through a scoped ?token= query param that the backend accepts only on this
  // single read-only route.
  const { token } = useAuth();
  const c = useColors();
  const s = useShadows();
  const reportUrl = token
    ? `/api/v1/jobs/${jobId}/report?token=${encodeURIComponent(token)}`
    : `/api/v1/jobs/${jobId}/report`;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(20, 17, 14, 0.55)',
        zIndex: z.modal,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: '92vw',
          height: '92vh',
          background: c.surface,
          borderRadius: radius.lg,
          border: `1px solid ${c.border}`,
          boxShadow: s.floating,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: `${space['3']} ${space['4']}`,
            borderBottom: `1px solid ${c.border}`,
            gap: space['3'],
            background: c.surfaceAlt,
          }}
        >
          <h3
            style={{
              margin: 0,
              fontFamily: fonts.display,
              fontSize: fontSize.md,
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
            }}
          >
            Research report
          </h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: space['2'] }}>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => window.open(reportUrl, '_blank', 'noopener,noreferrer')}
            >
              Open in new tab
            </Button>
            <Button size="sm" variant="tertiary" onClick={onClose}>
              Close
            </Button>
          </div>
        </div>
        <iframe src={reportUrl} style={{ width: '100%', flex: 1, border: 'none' }} title="Research Report" />
      </div>
    </div>
  );
}

function QASection({ jobId }: { jobId: string }) {
  const c = useColors();
  const { data: history } = useQAHistory(jobId);
  const askQuestion = useAskQuestion(jobId);
  const clarifyQuestion = useClarifyQuestion(jobId);
  const qaAvailable = useFeatureAvailable('qa');

  const [question, setQuestion] = useState('');
  const [step, setStep] = useState<'ask' | 'clarify'>('ask');
  const [interpretation, setInterpretation] = useState('');
  const [clarifications, setClarifications] = useState<string[]>([]);
  const [clarificationAnswers, setClarificationAnswers] = useState<string[]>([]);

  const askInputDisabled = clarifyQuestion.isPending || !qaAvailable;
  const askButtonDisabled = askInputDisabled || !question.trim();
  const clarifyButtonsDisabled = askQuestion.isPending || !qaAvailable;

  const resetToAsk = () => {
    setStep('ask');
    setInterpretation('');
    setClarifications([]);
    setClarificationAnswers([]);
  };

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || !qaAvailable) return;
    const result = await clarifyQuestion.mutateAsync({ question });
    setInterpretation(result.interpretation);
    setClarifications(result.clarifications);
    setClarificationAnswers(new Array(result.clarifications.length).fill(''));
    setStep('clarify');
  };

  const handleConfirmSearch = async () => {
    if (!qaAvailable) return;
    const answeredParts = clarifications
      .map((q, i) => (clarificationAnswers[i]?.trim() ? `${q}\n${clarificationAnswers[i].trim()}` : null))
      .filter(Boolean) as string[];

    const context = [`My interpretation: ${interpretation}`, ...answeredParts].join('\n\n');

    await askQuestion.mutateAsync({ question, context });
    setQuestion('');
    resetToAsk();
  };

  const handleSkipAndAsk = async () => {
    if (!qaAvailable) return;
    await askQuestion.mutateAsync({ question });
    setQuestion('');
    resetToAsk();
  };

  return (
    <Card>
      <SectionHeader title="Ask questions" description="Citation-grounded answers drawn from this job's transcripts and report." />

      {step === 'ask' && (
        <>
          {!qaAvailable && (
            <p
              style={{
                color: c.warn,
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                margin: `0 0 ${space['3']}`,
              }}
            >
              {FEATURE_UNAVAILABLE_MSG}.
            </p>
          )}
          <form onSubmit={handleAsk} style={{ display: 'flex', gap: space['2'], marginBottom: space['3'] }}>
            <div style={{ flex: 1 }}>
              <Input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder={qaAvailable ? 'Ask a question about the research…' : FEATURE_UNAVAILABLE_MSG}
                disabled={askInputDisabled}
                title={!qaAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
              />
            </div>
            <Button
              type="submit"
              disabled={askButtonDisabled}
              loading={clarifyQuestion.isPending}
              title={!qaAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
            >
              Ask
            </Button>
          </form>
          {clarifyQuestion.isPending && <InfoStripe text="Generating clarifying questions…" />}
        </>
      )}

      {step === 'clarify' && (
        <div
          style={{
            marginBottom: space['5'],
            padding: space['4'],
            background: c.surfaceAlt,
            borderRadius: radius.md,
            border: `1px solid ${c.border}`,
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'flex-start',
              marginBottom: space['3'],
              gap: space['4'],
            }}
          >
            <p
              style={{
                margin: 0,
                fontFamily: fonts.ui,
                fontSize: fontSize.xs,
                color: c.textMuted,
                fontWeight: fontWeight.medium,
              }}
            >
              Your question:{' '}
              <em style={{ color: c.textSecondary, fontStyle: 'italic' }}>{question}</em>
            </p>
            <Button size="sm" variant="tertiary" onClick={resetToAsk} leadingIcon={<span aria-hidden>←</span>}>
              Edit question
            </Button>
          </div>

          <div
            style={{
              marginBottom: space['4'],
              padding: space['3'],
              background: c.accentSubtle,
              borderRadius: radius.sm,
              borderLeft: `3px solid ${c.accent}`,
            }}
          >
            <p
              style={{
                margin: 0,
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                fontWeight: fontWeight.semibold,
                color: c.accent,
                marginBottom: space['1'],
              }}
            >
              Here's how I understand your question:
            </p>
            <p
              style={{
                margin: 0,
                fontFamily: fonts.body,
                fontSize: fontSize.base,
                color: c.textPrimary,
                lineHeight: lineHeight.snug,
              }}
            >
              {interpretation}
            </p>
          </div>

          {clarifications.length > 0 && (
            <div style={{ marginBottom: space['4'] }}>
              <p
                style={{
                  margin: `0 0 ${space['2']}`,
                  fontFamily: fonts.ui,
                  fontSize: fontSize.sm,
                  fontWeight: fontWeight.semibold,
                  color: c.textSecondary,
                }}
              >
                A few clarifying questions (optional — answer any that are useful):
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
                {clarifications.map((q, i) => (
                  <FormField key={i} label={q}>
                    {(id) => (
                      <Input
                        id={id}
                        value={clarificationAnswers[i] ?? ''}
                        onChange={(e) => {
                          const next = [...clarificationAnswers];
                          next[i] = e.target.value;
                          setClarificationAnswers(next);
                        }}
                        placeholder="Your answer (optional)"
                        disabled={askQuestion.isPending}
                      />
                    )}
                  </FormField>
                ))}
              </div>
            </div>
          )}

          {askQuestion.isPending && <InfoStripe text="Analyzing transcripts and composing answer…" />}

          <div style={{ display: 'flex', gap: space['2'], marginTop: space['3'] }}>
            <Button
              onClick={handleConfirmSearch}
              disabled={clarifyButtonsDisabled}
              loading={askQuestion.isPending}
              title={!qaAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
            >
              Confirm &amp; search
            </Button>
            <Button
              variant="tertiary"
              onClick={handleSkipAndAsk}
              disabled={clarifyButtonsDisabled}
              title={!qaAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
            >
              Skip clarifications
            </Button>
          </div>
        </div>
      )}

      {history && history.length > 0 && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: space['3'],
            marginTop: step === 'clarify' ? 0 : space['3'],
          }}
        >
          {history.map((qa) => (
            <QAExchangeCard key={qa.id} qa={qa} />
          ))}
        </div>
      )}
    </Card>
  );
}

function InfoStripe({ text }: { text: string }) {
  const c = useColors();
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: space['3'],
        marginBottom: space['3'],
        padding: space['3'],
        background: c.accentSubtle,
        borderRadius: radius.sm,
      }}
    >
      <Spinner size={16} />
      <span
        style={{
          color: c.accent,
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
          fontWeight: fontWeight.medium,
        }}
      >
        {text}
      </span>
    </div>
  );
}

function QAExchangeCard({ qa }: { qa: QAExchange }) {
  const c = useColors();
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(qa.answer);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable (e.g. insecure context) — leave button state unchanged
    }
  };

  return (
    <div
      style={{
        padding: space['4'],
        background: c.surfaceAlt,
        borderRadius: radius.md,
        border: `1px solid ${c.border}`,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: space['3'],
          marginBottom: space['2'],
        }}
      >
        <p
          style={{
            fontFamily: fonts.display,
            fontWeight: fontWeight.semibold,
            fontSize: fontSize.base,
            color: c.textPrimary,
            margin: 0,
            flex: 1,
            lineHeight: lineHeight.snug,
          }}
        >
          Q: {qa.question}
        </p>
        {copied ? (
          <Badge tone="success" size="sm">Copied</Badge>
        ) : (
          <Button size="sm" variant="tertiary" onClick={handleCopy}>
            Copy answer
          </Button>
        )}
      </div>
      <div
        className="reading"
        style={{
          color: c.textPrimary,
          fontSize: fontSize.base,
          maxWidth: 'none',
        }}
      >
        <ReactMarkdown>{qa.answer}</ReactMarkdown>
      </div>
      {qa.references.length > 0 && (
        <div
          style={{
            marginTop: space['3'],
            borderTop: `1px solid ${c.border}`,
            paddingTop: space['2'],
          }}
        >
          <span
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.xs,
              fontWeight: fontWeight.semibold,
              color: c.textSecondary,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
            }}
          >
            References
          </span>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: space['1'] }}>
            {qa.references.map((ref, i) => (
              <a
                key={i}
                href={ref.youtube_link}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  color: c.accent,
                  textDecoration: 'none',
                  fontFamily: fonts.ui,
                  fontSize: fontSize.xs,
                }}
              >
                {ref.video_title} · {ref.channel_name} · {ref.timestamp_display}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
