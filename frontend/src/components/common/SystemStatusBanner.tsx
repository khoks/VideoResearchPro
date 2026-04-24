import { useSystemStatusStore, type LLMStatus } from '../../stores/systemStatusStore';

// Human-readable names for the per-use-case feature identifiers the backend
// reports in `unavailable_features`. Keys must match the names used by
// useFeatureAvailable callers.
const FEATURE_LABELS: Record<string, string> = {
  topic_job: 'Topic research jobs',
  qa: 'Job Q&A',
  library_qa: 'Global library Q&A',
  qa_history: 'Q&A history chat',
  knowledge_extraction: 'Knowledge extraction',
};

function featureLabel(feature: string): string {
  return FEATURE_LABELS[feature] ?? feature;
}

const STATUS_COLORS: Record<LLMStatus, { bg: string; border: string; text: string }> = {
  ok:       { bg: '#ecfdf5', border: '#a7f3d0', text: '#065f46' },
  degraded: { bg: '#fffbeb', border: '#fde68a', text: '#92400e' },
  down:     { bg: '#fef2f2', border: '#fecaca', text: '#991b1b' },
  unknown:  { bg: '#f1f5f9', border: '#cbd5e1', text: '#475569' },
};

const STATUS_LABELS: Record<LLMStatus, string> = {
  ok: 'All systems operational',
  degraded: 'LLM services are degraded',
  down: 'LLM services are unavailable',
  unknown: 'LLM status unknown',
};

interface Props {
  onRetry: () => void;
}

export function SystemStatusBanner({ onRetry }: Props) {
  const llmStatus = useSystemStatusStore((s) => s.llmStatus);
  const unavailableFeatures = useSystemStatusStore((s) => s.unavailableFeatures);

  if (llmStatus === 'ok' || llmStatus === 'unknown') return null;

  const c = STATUS_COLORS[llmStatus];

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        background: c.bg,
        border: `1px solid ${c.border}`,
        color: c.text,
        padding: '0.7rem 1rem',
        margin: '0.75rem 1.5rem 0',
        borderRadius: 8,
        display: 'flex',
        alignItems: 'center',
        gap: '0.75rem',
        fontSize: '0.875rem',
        lineHeight: 1.4,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600 }}>{STATUS_LABELS[llmStatus]}</div>
        {unavailableFeatures.length > 0 && (
          <div style={{ marginTop: '0.2rem', opacity: 0.9 }}>
            Temporarily unavailable: {unavailableFeatures.map(featureLabel).join(', ')}.
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={onRetry}
        style={{
          background: 'transparent',
          color: c.text,
          border: `1px solid ${c.border}`,
          padding: '0.35rem 0.8rem',
          borderRadius: 6,
          cursor: 'pointer',
          fontWeight: 600,
          fontSize: '0.8rem',
          flexShrink: 0,
        }}
      >
        Retry now
      </button>
    </div>
  );
}
