import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { useKnowledge, useExtractKnowledge } from '../hooks/useKnowledge';
import { useFeatureAvailable } from '../hooks/useFeatureAvailable';
import { Badge, Button, Spinner, type BadgeTone } from '../components/primitives';
import { NotesPanel } from '../components/notes';
import { SuggestionCard } from '../components/qa/SuggestionCard';
import { VideoFramesPanel } from '../components/frames/VideoFramesPanel';
import { DepthSelect } from '../components/common/DepthSelect';
import { KnowledgeCutOffNote } from '../components/knowledge/KnowledgeCutOffNote';
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
import type { SourceScope } from '../types/qa';
import { depthLabel, depthOf, type Depth } from '../utils/depth';

const FEATURE_UNAVAILABLE_MSG = 'LLM-dependent feature is temporarily unavailable';

interface Props {
  /** The document's id: its `document_id`, or a video's legacy YouTube id. */
  videoId: string;
  videoTitle: string;
  /**
   * `documents.source_type`. Frames exist only for YouTube videos, so the
   * "On screen" panel is left out for any other type. Omitted means video.
   */
  sourceType?: string;
  /**
   * S-1.15.3: the depth the report control starts on — the preference the
   * surface already uses (a run's `output_length` on the job page). Omitted
   * or 'auto' starts on Auto, which sends no preference.
   */
  defaultDepth?: string | null;
  onClose: () => void;
}

/**
 * Right-side slide-in drawer showing the extracted knowledge artifact for a
 * single document — a video, a PDF, a pasted page, a thread.
 *
 * S-1.15.3: when nothing has been extracted yet the drawer offers the report
 * with a depth choice instead of starting it on open. A report is a metered,
 * minute-long run, and starting at the default made a reader who wanted
 * another depth pay for two. The choice starts on the surface's preference,
 * so accepting it is one click; Regenerate uses the same choice.
 */
export function VideoKnowledgeDrawer({ videoId, videoTitle, sourceType, defaultDepth, onClose }: Props) {
  const c = useColors();
  const s = useShadows();
  const navigate = useNavigate();
  const { data: artifact, isLoading: isLoadingCached, isError } = useKnowledge(videoId);
  const extract = useExtractKnowledge(videoId);
  const knowledgeExtractionAvailable = useFeatureAvailable('knowledge_extraction');
  const libraryQAAvailable = useFeatureAvailable('library_qa');
  const [depth, setDepth] = useState<Depth | null>(() => depthOf(defaultDepth));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const displayed: KnowledgeArtifact | null = artifact ?? extract.data ?? null;
  const source: SourceScope = { id: videoId, title: videoTitle };
  const isBusy = isLoadingCached || extract.isPending;
  const showUnavailableEmptyState =
    !knowledgeExtractionAvailable && !displayed && !isBusy;
  const showRunBar = knowledgeExtractionAvailable && !isLoadingCached;
  const writtenAt = depthOf(displayed?.output_length);
  const run = () => extract.mutate({ force: !!displayed, depth });
  const regenerateAt = (next: Depth) => {
    setDepth(next);
    extract.mutate({ force: true, depth: next });
  };

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
              // S-8.8.3: the drawer is the quick peek; the reading room has
              // the outline, measure and print.
              <Button size="sm" variant="primary" onClick={() => navigate(`/knowledge/${videoId}`)}>
                Open in reader
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
              Couldn't load the knowledge report. Try generating it again.
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

          {showRunBar && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: space['3'],
                marginBottom: space['4'],
              }}
            >
              <span
                style={{
                  fontFamily: fonts.ui,
                  fontSize: fontSize.sm,
                  color: displayed ? c.textMuted : c.textSecondary,
                }}
              >
                {!displayed
                  ? isError
                    ? null
                    : 'No knowledge report for this source yet.'
                  : writtenAt
                    ? `Written at ${depthLabel(writtenAt).toLowerCase()} depth.`
                    : null}
              </span>
              <div
                style={{
                  marginLeft: 'auto',
                  display: 'flex',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: space['2'],
                }}
              >
                <label
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: space['2'],
                    fontFamily: fonts.ui,
                    fontSize: fontSize.sm,
                    color: c.textSecondary,
                  }}
                >
                  Report depth
                  <DepthSelect
                    value={depth}
                    onChange={setDepth}
                    unsetLabel="Auto"
                    aria-label="Report depth"
                    title="Auto sizes the report to how much this source yields."
                    disabled={extract.isPending}
                  />
                </label>
                <Button
                  size="sm"
                  variant={displayed ? 'secondary' : 'primary'}
                  onClick={run}
                  loading={extract.isPending}
                  title={displayed ? 'Re-run extraction; overwrites the stored report.' : undefined}
                >
                  {displayed ? 'Regenerate' : 'Generate report'}
                </Button>
              </div>
            </div>
          )}

          {displayed?.report_cut_off && (
            <KnowledgeCutOffNote
              writtenAt={writtenAt}
              onRegenerate={knowledgeExtractionAvailable ? regenerateAt : undefined}
              busy={extract.isPending}
            />
          )}

          {displayed && <KnowledgeBody artifact={displayed} />}
          {/* S-1.18.2: frames are independent of the knowledge report, and
              only a YouTube video has any. */}
          {(!sourceType || sourceType === 'video') && <VideoFramesPanel videoId={videoId} />}
          {displayed && (
            // T-8.4.2.4: a suggestion is asked about this source alone, on
            // the library Q&A page (filled, or asked on Shift-click), which
            // says so beside its composer.
            <SuggestionCard
              context={`document:${videoId}`}
              enabled={libraryQAAvailable}
              note="Asked about this source only."
              onFill={(q) => navigate('/library/qa', { state: { question: q, source } })}
              onAsk={(q) => navigate('/library/qa', { state: { question: q, ask: true, source } })}
            />
          )}
          {displayed && (
            <div style={{ marginTop: space['5'] }}>
              <NotesPanel
                targetType="knowledge_artifact"
                targetId={videoId}
                variant="section"
                title="Your notes on this report"
              />
            </div>
          )}
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
