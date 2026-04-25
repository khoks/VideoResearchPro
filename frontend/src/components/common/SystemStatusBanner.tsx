import { useSystemStatusStore, type LLMStatus } from '../../stores/systemStatusStore';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import { Button } from '../primitives';

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
  const c = useColors();

  if (llmStatus === 'ok' || llmStatus === 'unknown') return null;

  const palette =
    llmStatus === 'down'
      ? { bg: c.errorSubtle, border: c.error, text: c.error }
      : llmStatus === 'degraded'
      ? { bg: c.warnSubtle, border: c.warn, text: c.warn }
      : { bg: c.surfaceAlt, border: c.border, text: c.textSecondary };

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        background: palette.bg,
        border: `1px solid ${palette.border}`,
        color: palette.text,
        padding: `${space['3']} ${space['4']}`,
        margin: `${space['4']} ${space['6']} 0`,
        borderRadius: radius.md,
        display: 'flex',
        alignItems: 'center',
        gap: space['4'],
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        lineHeight: lineHeight.snug,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: fontWeight.semibold }}>{STATUS_LABELS[llmStatus]}</div>
        {unavailableFeatures.length > 0 && (
          <div style={{ marginTop: 2, opacity: 0.85 }}>
            Temporarily unavailable: {unavailableFeatures.map(featureLabel).join(', ')}.
          </div>
        )}
      </div>
      <Button size="sm" variant="tertiary" onClick={onRetry}>
        Retry now
      </Button>
    </div>
  );
}
