import { useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { useJob, useJobVideos, useApproveJob, useCancelJob, useDeleteJob } from '../hooks/useJobs';
import { useJobProgress } from '../hooks/useJobProgress';
import { useQAHistory, useAskQuestion, useClarifyQuestion } from '../hooks/useQA';
import { StatusBadge } from '../components/common/StatusBadge';
import { ProgressBar } from '../components/common/ProgressBar';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { formatDuration, formatDate, statusColor } from '../utils/formatters';
import { useJobStore } from '../stores/jobStore';
import type { Video } from '../types/video';
import type { QAExchange } from '../types/qa';

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { data: job, isLoading } = useJob(jobId || null);
  const { data: videos } = useJobVideos(jobId || null);
  const approveJob = useApproveJob();
  const cancelJob = useCancelJob();
  const deleteJob = useDeleteJob();
  const { isReportModalOpen, openReportModal, closeReportModal } = useJobStore();

  useJobProgress(jobId || null);

  if (isLoading) return <div style={{ textAlign: 'center', padding: '3rem' }}><LoadingSpinner size={40} /></div>;
  if (!job) return <p>Job not found.</p>;

  return (
    <div>
      <button onClick={() => navigate('/jobs')} style={{
        background: 'none', border: 'none', color: '#667eea', cursor: 'pointer',
        fontSize: '0.9rem', marginBottom: '1rem', padding: 0,
      }}>
        &larr; Back to Jobs
      </button>

      <div style={{ background: '#fff', borderRadius: 12, padding: '1.5rem',
                     boxShadow: '0 1px 3px rgba(0,0,0,0.08)', marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <div>
            <h2 style={{ margin: 0, color: '#1e293b' }}>
              {job.job_type === 'topic' ? job.topic : 'Channel Collection'}
            </h2>
            <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}>
              Created {formatDate(job.created_at)} | {job.job_type} job
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <StatusBadge status={job.status} />
            {!['completed', 'cancelled', 'failed'].includes(job.status) && (
              <button onClick={() => cancelJob.mutate(job.id)} style={{
                background: '#ef4444', color: '#fff', border: 'none', padding: '0.4rem 1rem',
                borderRadius: 6, cursor: 'pointer', fontSize: '0.85rem',
              }}>Cancel</button>
            )}
            {['completed', 'cancelled', 'failed'].includes(job.status) && (
              <button onClick={() => { deleteJob.mutate(job.id); navigate('/jobs'); }} style={{
                background: '#ef4444', color: '#fff', border: 'none', padding: '0.4rem 1rem',
                borderRadius: 6, cursor: 'pointer', fontSize: '0.85rem',
              }}>Delete</button>
            )}
          </div>
        </div>
        <ProgressBar value={job.progress_pct} color={statusColor(job.status)} />
        <p style={{ margin: '0.5rem 0 0', fontSize: '0.85rem', color: '#64748b' }}>
          {job.progress_message} ({job.progress_pct}%)
        </p>
        {job.error_message && (
          <p style={{ color: '#ef4444', margin: '0.5rem 0 0', fontSize: '0.85rem' }}>
            Error: {job.error_message}
          </p>
        )}
      </div>

      {/* Video Approval */}
      {job.status === 'awaiting_approval' && videos && (
        <VideoApprovalSection videos={videos} jobId={job.id} onApprove={approveJob.mutateAsync} />
      )}

      {/* Video List (non-approval states) */}
      {job.status !== 'awaiting_approval' && videos && videos.length > 0 && (
        <div style={{ background: '#fff', borderRadius: 12, padding: '1.5rem',
                       boxShadow: '0 1px 3px rgba(0,0,0,0.08)', marginBottom: '1rem' }}>
          <h3 style={{ margin: '0 0 1rem', color: '#1e293b' }}>Videos ({videos.length})</h3>
          {videos.map(v => (
            <div key={v.id} style={{ display: 'flex', justifyContent: 'space-between',
                                     padding: '0.5rem 0', borderBottom: '1px solid #f1f5f9' }}>
              <div>
                <a href={v.url} target="_blank" rel="noopener noreferrer"
                   style={{ color: '#667eea', textDecoration: 'none', fontWeight: 500 }}>{v.title}</a>
                <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                  {v.channel_name} | {formatDuration(v.duration_seconds)} | {v.transcript_status}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Report Button */}
      {job.has_report && (
        <div style={{ marginBottom: '1rem' }}>
          <button onClick={openReportModal} style={{
            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            color: '#fff', border: 'none', padding: '0.7rem 1.5rem',
            borderRadius: 8, cursor: 'pointer', fontWeight: 600, fontSize: '0.95rem',
          }}>
            View Report
          </button>
        </div>
      )}

      {/* Report Modal */}
      {isReportModalOpen && (
        <ReportModal jobId={job.id} onClose={closeReportModal} />
      )}

      {/* Q&A Panel */}
      {job.status === 'completed' && <QASection jobId={job.id} />}
    </div>
  );
}

type VideoSortKey = 'channel' | 'duration' | 'title';

function VideoApprovalSection({ videos, jobId, onApprove }: {
  videos: Video[]; jobId: string;
  onApprove: (args: { id: string; data: { approved_video_ids: string[] } }) => Promise<unknown>;
}) {
  // Use YouTube video_id (not internal UUID) so the approval payload matches
  // what the backend expects in approved_video_ids.
  const [selected, setSelected] = useState<Set<string>>(new Set(videos.map(v => v.video_id)));
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
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const selectAll = () => setSelected(new Set(videos.map(v => v.video_id)));
  const deselectAll = () => setSelected(new Set());

  const handleApprove = () => {
    onApprove({ id: jobId, data: { approved_video_ids: Array.from(selected) } });
  };

  return (
    <div style={{ background: '#fff', borderRadius: 12, padding: '1.5rem',
                   boxShadow: '0 1px 3px rgba(0,0,0,0.08)', marginBottom: '1rem' }}>
      <h3 style={{ margin: '0 0 0.5rem', color: '#1e293b' }}>Review Videos ({selected.size}/{videos.length} selected)</h3>
      <p style={{ color: '#64748b', fontSize: '0.85rem', marginBottom: '1rem' }}>
        Deselect any videos you don't want to include, then approve to continue.
      </p>

      <div style={{
        display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap',
        marginBottom: '1rem',
      }}>
        <button onClick={selectAll} style={{
          background: 'transparent', color: '#667eea', border: '1px solid #667eea',
          padding: '0.3rem 0.75rem', borderRadius: 6, cursor: 'pointer',
          fontSize: '0.8rem', fontWeight: 600,
        }}>Select All</button>
        <button onClick={deselectAll} style={{
          background: 'transparent', color: '#64748b', border: '1px solid #cbd5e1',
          padding: '0.3rem 0.75rem', borderRadius: 6, cursor: 'pointer',
          fontSize: '0.8rem', fontWeight: 600,
        }}>Deselect All</button>
        <label style={{ fontSize: '0.8rem', color: '#64748b', marginLeft: 'auto' }}>
          Sort by:{' '}
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as VideoSortKey)}
            style={{
              padding: '0.3rem 0.5rem', borderRadius: 6, border: '1px solid #e2e8f0',
              fontSize: '0.8rem', background: '#fff',
            }}
          >
            <option value="channel">Channel</option>
            <option value="duration">Duration</option>
            <option value="title">Title</option>
          </select>
        </label>
      </div>

      {sortedVideos.map(v => (
        <div key={v.id} style={{
          display: 'flex', alignItems: 'center', gap: '0.75rem',
          padding: '0.5rem', borderBottom: '1px solid #f1f5f9',
        }}>
          <input
            type="checkbox"
            checked={selected.has(v.video_id)}
            onChange={() => toggleVideo(v.video_id)}
            style={{ cursor: 'pointer' }}
          />
          {v.thumbnail_url ? (
            <img
              src={v.thumbnail_url}
              alt=""
              onClick={() => toggleVideo(v.video_id)}
              style={{
                width: 96, height: 54, borderRadius: 4, objectFit: 'cover',
                flexShrink: 0, background: '#f1f5f9', cursor: 'pointer',
              }}
            />
          ) : (
            <div
              onClick={() => toggleVideo(v.video_id)}
              style={{
                width: 96, height: 54, borderRadius: 4, background: '#f1f5f9',
                flexShrink: 0, cursor: 'pointer',
              }}
            />
          )}
          <div
            onClick={() => toggleVideo(v.video_id)}
            style={{ flex: 1, minWidth: 0, cursor: 'pointer' }}
          >
            <div style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis' }}>{v.title}</div>
            <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
              {v.channel_name} | {formatDuration(v.duration_seconds)}
            </div>
          </div>
          <a
            href={v.url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: '#667eea', textDecoration: 'none', fontSize: '0.8rem',
              fontWeight: 600, border: '1px solid #667eea', padding: '0.3rem 0.75rem',
              borderRadius: 6, flexShrink: 0,
            }}
          >
            Watch
          </a>
        </div>
      ))}
      <button onClick={handleApprove} style={{
        background: '#22c55e', color: '#fff', border: 'none', padding: '0.6rem 1.5rem',
        borderRadius: 8, cursor: 'pointer', fontWeight: 600, marginTop: '1rem',
      }}>
        Approve & Continue ({selected.size} videos)
      </button>
    </div>
  );
}

function ReportModal({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const reportUrl = `/api/v1/jobs/${jobId}/report`;

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex',
      alignItems: 'center', justifyContent: 'center',
    }} onClick={onClose}>
      <div style={{
        width: '90vw', height: '90vh', background: '#fff', borderRadius: 12,
        overflow: 'hidden', position: 'relative', display: 'flex', flexDirection: 'column',
      }} onClick={(e) => e.stopPropagation()}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0.75rem 1rem', borderBottom: '1px solid #e2e8f0', gap: '0.75rem',
          background: '#f8fafc',
        }}>
          <h3 style={{ margin: 0, fontSize: '1rem', color: '#1e293b' }}>Research Report</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <a href={reportUrl} target="_blank" rel="noopener noreferrer" style={{
              background: '#667eea', color: '#fff', padding: '0.4rem 0.9rem',
              borderRadius: 6, fontSize: '0.85rem', fontWeight: 500, textDecoration: 'none',
            }}>
              Open in new tab
            </a>
            <button onClick={onClose} style={{
              background: '#fff', color: '#475569', border: '1px solid #cbd5e1',
              padding: '0.4rem 0.9rem', borderRadius: 6, cursor: 'pointer',
              fontSize: '0.85rem', fontWeight: 500,
            }}>
              Close
            </button>
          </div>
        </div>
        <iframe
          src={reportUrl}
          style={{ width: '100%', flex: 1, border: 'none' }}
          title="Research Report"
        />
      </div>
    </div>
  );
}

function QASection({ jobId }: { jobId: string }) {
  const { data: history } = useQAHistory(jobId);
  const askQuestion = useAskQuestion(jobId);
  const clarifyQuestion = useClarifyQuestion(jobId);

  const [question, setQuestion] = useState('');
  const [step, setStep] = useState<'ask' | 'clarify'>('ask');
  const [interpretation, setInterpretation] = useState('');
  const [clarifications, setClarifications] = useState<string[]>([]);
  const [clarificationAnswers, setClarificationAnswers] = useState<string[]>([]);

  const resetToAsk = () => {
    setStep('ask');
    setInterpretation('');
    setClarifications([]);
    setClarificationAnswers([]);
  };

  // Step 1: call /qa/clarify and move to clarify step
  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    const result = await clarifyQuestion.mutateAsync({ question });
    setInterpretation(result.interpretation);
    setClarifications(result.clarifications);
    setClarificationAnswers(new Array(result.clarifications.length).fill(''));
    setStep('clarify');
  };

  // Step 2a: combine original question + interpretation + answers, fire /qa
  const handleConfirmSearch = async () => {
    const answeredParts = clarifications
      .map((q, i) => (clarificationAnswers[i]?.trim() ? `${q}\n${clarificationAnswers[i].trim()}` : null))
      .filter(Boolean) as string[];

    const context = [
      `My interpretation: ${interpretation}`,
      ...answeredParts,
    ].join('\n\n');

    await askQuestion.mutateAsync({ question, context });
    setQuestion('');
    resetToAsk();
  };

  // Step 2b: skip clarifications and fire /qa directly (fallback)
  const handleSkipAndAsk = async () => {
    await askQuestion.mutateAsync({ question });
    setQuestion('');
    resetToAsk();
  };

  return (
    <div style={{ background: '#fff', borderRadius: 12, padding: '1.5rem',
                   boxShadow: '0 1px 3px rgba(0,0,0,0.08)' }}>
      <h3 style={{ margin: '0 0 1rem', color: '#1e293b' }}>Ask Questions</h3>

      {/* ── Step 1: question input ── */}
      {step === 'ask' && (
        <>
          <form onSubmit={handleAsk} style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask a question about the research..."
              disabled={clarifyQuestion.isPending}
              style={{
                flex: 1, padding: '0.6rem 1rem', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: '0.95rem',
                opacity: clarifyQuestion.isPending ? 0.6 : 1,
                background: clarifyQuestion.isPending ? '#f1f5f9' : '#fff',
              }}
            />
            <button type="submit" disabled={clarifyQuestion.isPending || !question.trim()} style={{
              background: '#667eea', color: '#fff', border: 'none', padding: '0.6rem 1.5rem',
              borderRadius: 8, cursor: clarifyQuestion.isPending || !question.trim() ? 'not-allowed' : 'pointer',
              fontWeight: 600, opacity: clarifyQuestion.isPending || !question.trim() ? 0.5 : 1,
            }}>
              {clarifyQuestion.isPending ? '...' : 'Ask'}
            </button>
          </form>
          {clarifyQuestion.isPending && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem',
                          padding: '1rem', background: '#f0f2ff', borderRadius: 8 }}>
              <LoadingSpinner size={20} />
              <span style={{ color: '#667eea', fontSize: '0.9rem', fontWeight: 500 }}>
                Generating clarifying questions...
              </span>
            </div>
          )}
        </>
      )}

      {/* ── Step 2: clarification panel ── */}
      {step === 'clarify' && (
        <div style={{ marginBottom: '1.5rem', padding: '1.25rem', background: '#f8fafc',
                      borderRadius: 10, border: '1px solid #e2e8f0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                        marginBottom: '0.75rem' }}>
            <p style={{ margin: 0, fontSize: '0.8rem', color: '#94a3b8', fontWeight: 500 }}>
              Your question: <em style={{ color: '#64748b' }}>{question}</em>
            </p>
            <button onClick={resetToAsk} style={{
              background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer',
              fontSize: '0.8rem', padding: 0, flexShrink: 0, marginLeft: '1rem',
            }}>
              ← Edit question
            </button>
          </div>

          <div style={{ marginBottom: '1rem', padding: '0.75rem', background: '#eef2ff',
                        borderRadius: 8, borderLeft: '3px solid #667eea' }}>
            <p style={{ margin: 0, fontSize: '0.85rem', fontWeight: 600, color: '#4338ca',
                        marginBottom: '0.25rem' }}>Here's how I understand your question:</p>
            <p style={{ margin: 0, fontSize: '0.9rem', color: '#334155', lineHeight: 1.5 }}>
              {interpretation}
            </p>
          </div>

          {clarifications.length > 0 && (
            <div style={{ marginBottom: '1rem' }}>
              <p style={{ margin: '0 0 0.5rem', fontSize: '0.85rem', fontWeight: 600, color: '#475569' }}>
                A few clarifying questions (optional — answer any that are useful):
              </p>
              {clarifications.map((q, i) => (
                <div key={i} style={{ marginBottom: '0.75rem' }}>
                  <label style={{ display: 'block', fontSize: '0.85rem', color: '#475569',
                                   marginBottom: '0.25rem' }}>
                    {q}
                  </label>
                  <input
                    value={clarificationAnswers[i] ?? ''}
                    onChange={(e) => {
                      const next = [...clarificationAnswers];
                      next[i] = e.target.value;
                      setClarificationAnswers(next);
                    }}
                    placeholder="Your answer (optional)"
                    disabled={askQuestion.isPending}
                    style={{
                      width: '100%', padding: '0.5rem 0.75rem', borderRadius: 6,
                      border: '1px solid #e2e8f0', fontSize: '0.875rem', boxSizing: 'border-box',
                      background: askQuestion.isPending ? '#f1f5f9' : '#fff',
                    }}
                  />
                </div>
              ))}
            </div>
          )}

          {askQuestion.isPending && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem',
                          padding: '0.75rem', background: '#f0f2ff', borderRadius: 8 }}>
              <LoadingSpinner size={18} />
              <span style={{ color: '#667eea', fontSize: '0.9rem', fontWeight: 500 }}>
                Analyzing transcripts and generating answer...
              </span>
            </div>
          )}

          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button onClick={handleConfirmSearch} disabled={askQuestion.isPending} style={{
              background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
              color: '#fff', border: 'none', padding: '0.6rem 1.25rem',
              borderRadius: 8, cursor: askQuestion.isPending ? 'not-allowed' : 'pointer',
              fontWeight: 600, fontSize: '0.9rem', opacity: askQuestion.isPending ? 0.6 : 1,
            }}>
              {askQuestion.isPending ? '...' : 'Confirm & Search'}
            </button>
            <button onClick={handleSkipAndAsk} disabled={askQuestion.isPending} style={{
              background: 'none', color: '#667eea', border: '1px solid #667eea',
              padding: '0.6rem 1.25rem', borderRadius: 8,
              cursor: askQuestion.isPending ? 'not-allowed' : 'pointer',
              fontWeight: 500, fontSize: '0.9rem', opacity: askQuestion.isPending ? 0.4 : 1,
            }}>
              Skip clarifications
            </button>
          </div>
        </div>
      )}

      {/* ── Q&A history ── */}
      {history && history.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem',
                      marginTop: step === 'clarify' ? 0 : '1rem' }}>
          {history.map(qa => (
            <QAExchangeCard key={qa.id} qa={qa} />
          ))}
        </div>
      )}
    </div>
  );
}

function QAExchangeCard({ qa }: { qa: QAExchange }) {
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
    <div style={{ padding: '1rem', background: '#f8fafc', borderRadius: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                    gap: '0.75rem', marginBottom: '0.5rem' }}>
        <p style={{ fontWeight: 600, color: '#1e293b', margin: 0, flex: 1 }}>Q: {qa.question}</p>
        <button onClick={handleCopy} style={{
          background: copied ? '#22c55e' : '#fff', color: copied ? '#fff' : '#475569',
          border: '1px solid #cbd5e1', padding: '0.25rem 0.6rem', borderRadius: 6,
          cursor: 'pointer', fontSize: '0.75rem', fontWeight: 500, flexShrink: 0,
        }}>
          {copied ? 'Copied' : 'Copy answer'}
        </button>
      </div>
      <div style={{ color: '#334155', lineHeight: 1.6 }}>
        <ReactMarkdown>{qa.answer}</ReactMarkdown>
      </div>
      {qa.references.length > 0 && (
        <div style={{ marginTop: '0.75rem', borderTop: '1px solid #e2e8f0', paddingTop: '0.5rem' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#64748b' }}>References:</span>
          {qa.references.map((ref, i) => (
            <div key={i} style={{ fontSize: '0.8rem', color: '#667eea', marginTop: '0.25rem' }}>
              <a href={ref.youtube_link} target="_blank" rel="noopener noreferrer"
                 style={{ color: '#667eea', textDecoration: 'none' }}>
                {ref.video_title} by {ref.channel_name} at {ref.timestamp_display}
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
