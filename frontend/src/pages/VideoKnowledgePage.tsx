import { useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { useKnowledge, useExtractKnowledge } from '../hooks/useKnowledge';
import { useFeatureAvailable } from '../hooks/useFeatureAvailable';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import type { KnowledgeArtifact } from '../services/knowledgeApi';

const FEATURE_UNAVAILABLE_MSG = 'LLM-dependent feature is temporarily unavailable';

interface Props {
  videoId: string;
  videoTitle: string;
  onClose: () => void;
}

// Drawer idiom (right-side slide-in + backdrop) — modelled after the existing
// ReportModal pattern but anchored to the right edge so the user can still see
// the video row context behind it. Auto-fires extraction when no cached
// artifact exists so the first click "just works" with a spinner.
export function VideoKnowledgeDrawer({ videoId, videoTitle, onClose }: Props) {
  const { data: artifact, isLoading: isLoadingCached, isError } = useKnowledge(videoId);
  const extract = useExtractKnowledge(videoId);
  const knowledgeExtractionAvailable = useFeatureAvailable('knowledge_extraction');

  // When the GET resolves to null (never extracted) kick off the POST exactly
  // once. Guarded by pending/success so re-renders never retrigger. Also
  // short-circuits when LLM extraction is unavailable so we render an empty
  // state instead of firing a doomed request.
  useEffect(() => {
    if (isLoadingCached) return;
    if (artifact) return;
    if (!knowledgeExtractionAvailable) return;
    if (extract.isPending || extract.isSuccess || extract.isError) return;
    extract.mutate(undefined);
  }, [artifact, isLoadingCached, extract, knowledgeExtractionAvailable]);

  const displayed: KnowledgeArtifact | null = artifact ?? extract.data ?? null;
  const isBusy = isLoadingCached || extract.isPending;
  const showUnavailableEmptyState =
    !knowledgeExtractionAvailable && !displayed && !isBusy;
  const regenDisabled = extract.isPending || !knowledgeExtractionAvailable;

  return (
    <div
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        background: 'rgba(0,0,0,0.5)', zIndex: 1000,
        display: 'flex', justifyContent: 'flex-end',
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 'min(720px, 95vw)', height: '100vh', background: '#fff',
          display: 'flex', flexDirection: 'column', boxShadow: '-4px 0 12px rgba(0,0,0,0.15)',
        }}
      >
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0.75rem 1.25rem', borderBottom: '1px solid #e2e8f0', gap: '0.75rem',
          background: '#f8fafc', flexShrink: 0,
        }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 500 }}>
              Knowledge Report
            </div>
            <div style={{
              fontSize: '1rem', color: '#1e293b', fontWeight: 600,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }} title={videoTitle}>
              {videoTitle}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
            {displayed && !isBusy && (
              <button
                onClick={() => extract.mutate({ force: true })}
                disabled={regenDisabled}
                title={knowledgeExtractionAvailable
                  ? 'Re-run extraction; overwrites the stored report.'
                  : FEATURE_UNAVAILABLE_MSG}
                style={{
                  background: '#fff', color: '#667eea', border: '1px solid #667eea',
                  padding: '0.4rem 0.9rem', borderRadius: 6,
                  cursor: regenDisabled ? 'not-allowed' : 'pointer',
                  fontSize: '0.85rem', fontWeight: 500,
                  opacity: regenDisabled ? 0.6 : 1,
                }}
              >
                Regenerate
              </button>
            )}
            <button
              onClick={onClose}
              style={{
                background: '#fff', color: '#475569', border: '1px solid #cbd5e1',
                padding: '0.4rem 0.9rem', borderRadius: 6, cursor: 'pointer',
                fontSize: '0.85rem', fontWeight: 500,
              }}
            >
              Close
            </button>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '1.25rem' }}>
          {isBusy && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '0.75rem',
              padding: '1rem', background: '#f0f2ff', borderRadius: 8,
              marginBottom: '1rem',
            }}>
              <LoadingSpinner size={20} />
              <span style={{ color: '#667eea', fontSize: '0.9rem', fontWeight: 500 }}>
                {extract.isPending
                  ? 'Extracting topics and generating report...'
                  : 'Loading...'}
              </span>
            </div>
          )}

          {isError && !extract.isPending && !displayed && knowledgeExtractionAvailable && (
            <div style={{
              padding: '1rem', background: '#fef2f2', borderRadius: 8,
              border: '1px solid #fecaca', color: '#b91c1c', fontSize: '0.9rem',
              marginBottom: '1rem',
            }}>
              Failed to load knowledge report. Click Regenerate to try again.
            </div>
          )}

          {showUnavailableEmptyState && (
            <div style={{
              padding: '1rem', background: '#fffbeb', borderRadius: 8,
              border: '1px solid #fde68a', color: '#92400e', fontSize: '0.9rem',
            }}>
              {FEATURE_UNAVAILABLE_MSG}. Knowledge extraction will resume once the
              LLM service recovers — try again in a moment.
            </div>
          )}

          {displayed && <KnowledgeBody artifact={displayed} />}
        </div>
      </div>
    </div>
  );
}

function KnowledgeBody({ artifact }: { artifact: KnowledgeArtifact }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <ChipSection label="Topics" items={artifact.topics} tone="topic" />
      <ChipSection label="Concepts" items={artifact.concepts} tone="concept" />
      <ChipSection label="Events" items={artifact.events} tone="event" />
      <ChipSection label="Facts" items={artifact.facts} tone="fact" />

      {artifact.knowledge_report_md && (
        <div style={{
          background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8,
          padding: '1rem 1.25rem',
        }}>
          <div style={{
            fontSize: '0.8rem', fontWeight: 600, color: '#64748b',
            textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem',
          }}>
            Report
          </div>
          <div style={{ color: '#334155', lineHeight: 1.6, fontSize: '0.95rem' }}>
            <ReactMarkdown>{artifact.knowledge_report_md}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}

type ChipTone = 'topic' | 'concept' | 'event' | 'fact';

const TONE_COLORS: Record<ChipTone, { bg: string; color: string; border: string }> = {
  topic:   { bg: '#eef2ff', color: '#4338ca', border: '#c7d2fe' },
  concept: { bg: '#ecfeff', color: '#0e7490', border: '#a5f3fc' },
  event:   { bg: '#fef3c7', color: '#92400e', border: '#fde68a' },
  fact:    { bg: '#f1f5f9', color: '#334155', border: '#cbd5e1' },
};

function ChipSection({ label, items, tone }: { label: string; items: string[]; tone: ChipTone }) {
  if (!items || items.length === 0) return null;
  const c = TONE_COLORS[tone];
  return (
    <div>
      <div style={{
        fontSize: '0.8rem', fontWeight: 600, color: '#64748b',
        textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.4rem',
      }}>
        {label} ({items.length})
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
        {items.map((item, i) => (
          <span
            key={i}
            style={{
              background: c.bg, color: c.color, border: `1px solid ${c.border}`,
              padding: '3px 10px', borderRadius: 14, fontSize: '0.8rem', fontWeight: 500,
            }}
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}
