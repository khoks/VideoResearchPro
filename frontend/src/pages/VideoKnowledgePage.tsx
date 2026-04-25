import { useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { useKnowledge, useExtractKnowledge } from '../hooks/useKnowledge';
import { useFeatureAvailable } from '../hooks/useFeatureAvailable';
import { Badge, Button, Spinner, type BadgeTone } from '../components/primitives';
import { useColors, useShadows } from '../hooks/useTheme';
import {
  fonts,
  fontSize,
  fontWeight,
  lineHeight,
  radius,
  space,
  z,
} from '../theme';
import type { KnowledgeArtifact } from '../services/knowledgeApi';

const FEATURE_UNAVAILABLE_MSG = 'LLM-dependent feature is temporarily unavailable';

interface Props {
  videoId: string;
  videoTitle: string;
  onClose: () => void;
}

/**
 * Right-side slide-in drawer showing the extracted knowledge artifact for a
 * single video. Auto-kicks extraction if no cached artifact exists so the first
 * click "just works" with a spinner.
 */
export function VideoKnowledgeDrawer({ videoId, videoTitle, onClose }: Props) {
  const c = useColors();
  const s = useShadows();
  const { data: artifact, isLoading: isLoadingCached, isError } = useKnowledge(videoId);
  const extract = useExtractKnowledge(videoId);
  const knowledgeExtractionAvailable = useFeatureAvailable('knowledge_extraction');

  useEffect(() => {
    if (isLoadingCached) return;
    if (artifact) return;
    if (!knowledgeExtractionAvailable) return;
    if (extract.isPending || extract.isSuccess || extract.isError) return;
    extract.mutate(undefined);
  }, [artifact, isLoadingCached, extract, knowledgeExtractionAvailable]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const displayed: KnowledgeArtifact | null = artifact ?? extract.data ?? null;
  const isBusy = isLoadingCached || extract.isPending;
  const showUnavailableEmptyState =
    !knowledgeExtractionAvailable && !displayed && !isBusy;
  const regenDisabled = extract.isPending || !knowledgeExtractionAvailable;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Knowledge report for ${videoTitle}`}
      onClick={onClose}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(20, 17, 14, 0.55)',
        zIndex: z.drawer,
        display: 'flex',
        justifyContent: 'flex-end',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 'min(720px, 95vw)',
          height: '100vh',
          background: c.surface,
          display: 'flex',
          flexDirection: 'column',
          boxShadow: s.floating,
          borderLeft: `1px solid ${c.border}`,
        }}
      >
        <header
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: `${space['3']} ${space['5']}`,
            borderBottom: `1px solid ${c.border}`,
            gap: space['3'],
            background: c.surfaceAlt,
            flexShrink: 0,
          }}
        >
          <div style={{ minWidth: 0, flex: 1 }}>
            <div
              style={{
                fontFamily: fonts.ui,
                fontSize: fontSize.xs,
                color: c.textMuted,
                fontWeight: fontWeight.medium,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
              }}
            >
              Knowledge report
            </div>
            <div
              style={{
                fontFamily: fonts.display,
                fontSize: fontSize.md,
                color: c.textPrimary,
                fontWeight: fontWeight.semibold,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                marginTop: 2,
              }}
              title={videoTitle}
            >
              {videoTitle}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexShrink: 0 }}>
            {displayed && !isBusy && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => extract.mutate({ force: true })}
                disabled={regenDisabled}
                title={
                  knowledgeExtractionAvailable
                    ? 'Re-run extraction; overwrites the stored report.'
                    : FEATURE_UNAVAILABLE_MSG
                }
              >
                Regenerate
              </Button>
            )}
            <Button size="sm" variant="tertiary" onClick={onClose}>
              Close
            </Button>
          </div>
        </header>

        <div style={{ flex: 1, overflowY: 'auto', padding: space['5'] }}>
          {isBusy && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: space['3'],
                padding: space['4'],
                background: c.accentSubtle,
                borderRadius: radius.md,
                marginBottom: space['4'],
              }}
            >
              <Spinner size={18} />
              <span
                style={{
                  fontFamily: fonts.ui,
                  fontSize: fontSize.sm,
                  color: c.accent,
                  fontWeight: fontWeight.medium,
                }}
              >
                {extract.isPending
                  ? 'Extracting topics and generating report…'
                  : 'Loading…'}
              </span>
            </div>
          )}

          {isError && !extract.isPending && !displayed && knowledgeExtractionAvailable && (
            <div
              role="alert"
              style={{
                padding: space['4'],
                background: c.errorSubtle,
                borderRadius: radius.md,
                border: `1px solid ${c.error}`,
                color: c.error,
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                marginBottom: space['4'],
              }}
            >
              Couldn't load the knowledge report. Click Regenerate to try again.
            </div>
          )}

          {showUnavailableEmptyState && (
            <div
              role="note"
              style={{
                padding: space['4'],
                background: c.warnSubtle,
                borderRadius: radius.md,
                border: `1px solid ${c.warn}`,
                color: c.warn,
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
              }}
            >
              {FEATURE_UNAVAILABLE_MSG}. Knowledge extraction will resume once the LLM service recovers — try again in a moment.
            </div>
          )}

          {displayed && <KnowledgeBody artifact={displayed} />}
        </div>
      </div>
    </div>
  );
}

function KnowledgeBody({ artifact }: { artifact: KnowledgeArtifact }) {
  const c = useColors();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
      <ChipSection label="Topics" items={artifact.topics} tone="accent" />
      <ChipSection label="Concepts" items={artifact.concepts} tone="info" />
      <ChipSection label="Events" items={artifact.events} tone="warn" />
      <ChipSection label="Facts" items={artifact.facts} tone="neutral" />

      {artifact.knowledge_report_md && (
        <div
          style={{
            background: c.surface,
            border: `1px solid ${c.border}`,
            borderRadius: radius.md,
            padding: `${space['4']} ${space['5']}`,
          }}
        >
          <div
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.xs,
              fontWeight: fontWeight.semibold,
              color: c.textSecondary,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: space['3'],
            }}
          >
            Report
          </div>
          <div
            className="reading"
            style={{
              color: c.textPrimary,
              fontFamily: fonts.body,
              fontSize: fontSize.base,
              lineHeight: lineHeight.loose,
            }}
          >
            <ReactMarkdown>{artifact.knowledge_report_md}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}

function ChipSection({
  label,
  items,
  tone,
}: {
  label: string;
  items: string[];
  tone: BadgeTone;
}) {
  const c = useColors();
  if (!items || items.length === 0) return null;
  return (
    <div>
      <div
        style={{
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          fontWeight: fontWeight.semibold,
          color: c.textSecondary,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          marginBottom: space['2'],
        }}
      >
        {label} ({items.length})
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['2'] }}>
        {items.map((item, i) => (
          <Badge key={i} tone={tone} size="sm">
            {item}
          </Badge>
        ))}
      </div>
    </div>
  );
}
