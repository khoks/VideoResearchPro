import { useMemo } from 'react';
import { Button, Spinner } from '../primitives';
import { useExtractFrames, useFrameImages, useVideoFrames } from '../../hooks/useVideoFrames';
import { useFeatureAvailable } from '../../hooks/useFeatureAvailable';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import { usableFrames } from '../../utils/frames';
import { featureFlags } from '../../config/features';

interface Props {
  videoId: string;
}

function errorText(err: unknown): string {
  const e = err as { response?: { status?: number; data?: { detail?: string } }; message?: string } | null;
  const status = e?.response?.status;
  const detail = e?.response?.data?.detail;
  if (status === 429) return 'You have used this month\'s frame captures. They reset at the start of next month.';
  return detail ?? e?.message ?? 'The capture could not be started.';
}

/**
 * S-1.18.2 (T-1.18.2.4): what was on screen in one video, and a way to
 * capture it on demand. Frames are computed once per document and shared by
 * every run that uses it (D-067), so a capture here also shows up in later
 * reports' citation cards.
 */
export function VideoFramesPanel({ videoId }: Props) {
  const c = useColors();
  const { data, isLoading } = useVideoFrames(videoId);
  const extract = useExtractFrames(videoId);
  const modelsAvailable = useFeatureAvailable('visual_analysis');

  const frames = useMemo(() => usableFrames(data?.frames ?? []), [data]);
  const wanted = useMemo(() => frames.map((f) => ({ videoId, frameId: f.frame_id })), [frames, videoId]);
  const urls = useFrameImages(wanted);

  const running = !!data?.in_progress || extract.isPending;
  const canCapture = !!data?.visual_enabled && modelsAvailable && !running;
  const disabledReason = !data?.visual_enabled
    ? 'Visual analysis is turned off on this install (VISUAL_ENABLED).'
    : !modelsAvailable
      ? 'The vision models failed their startup check.'
      : running
        ? 'A capture is already running.'
        : undefined;
  const ytId = data?.video_id ?? null;
  // D-105: capture starts visual analysis, so it hides with the opt-in; the
  // stills of frames that already exist still show.
  const captureShown = featureFlags.visualAnalysis;

  if (isLoading) return null;
  if (!data) return null;
  if (!frames.length && (!captureShown || (!data.visual_enabled && !running))) return null; // nothing to show, nothing to do

  return (
    <section
      aria-label="What was on screen"
      data-testid="video-frames-panel"
      style={{ marginTop: space['5'], fontFamily: fonts.ui }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], marginBottom: space['3'] }}>
        <h3 style={{ margin: 0, fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.textPrimary, flex: 1 }}>
          On screen {frames.length ? <span style={{ color: c.textSecondary, fontWeight: fontWeight.regular }}>· {frames.length}</span> : null}
        </h3>
        {captureShown && (<Button
          size="sm"
          variant="secondary"
          disabled={!canCapture}
          title={disabledReason ?? (frames.length ? 'Capture the key frames again; replaces the stored ones.' : 'Capture and describe the frames where something is being shown.')}
          onClick={() => extract.mutate(frames.length > 0)}
        >
          {frames.length ? 'Recapture frames' : 'Capture key frames'}
        </Button>)}
      </div>

      {captureShown && running && (
        <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], color: c.textSecondary, fontSize: fontSize.sm, marginBottom: space['3'] }}>
          <Spinner size={14} /> Capturing frames. This downloads the video once and takes a few minutes.
        </div>
      )}
      {captureShown && extract.isError && (
        <div role="alert" style={{ color: c.error, fontSize: fontSize.sm, marginBottom: space['3'] }}>
          {errorText(extract.error)}
        </div>
      )}
      {captureShown && !frames.length && !running && (
        <p style={{ margin: 0, color: c.textSecondary, fontSize: fontSize.sm, lineHeight: lineHeight.snug }}>
          No frames yet. Capturing picks the moments where the transcript suggests something is being shown and
          describes each still, so reports can say what was on screen and when.
        </p>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: space['3'] }}>
        {frames.map((f) => (
          <figure key={f.frame_id} style={{ margin: 0, background: c.surfaceAlt, borderRadius: radius.md, overflow: 'hidden' }}>
            <div style={{ aspectRatio: '16 / 9', background: c.border }}>
              {urls[f.frame_id] && (
                <img
                  src={urls[f.frame_id]}
                  alt={f.description ?? `Frame at ${f.timestamp_display}`}
                  style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                />
              )}
            </div>
            <figcaption style={{ padding: space['2'], fontSize: fontSize.xs, lineHeight: lineHeight.snug, color: c.textSecondary }}>
              {ytId ? (
                <a
                  href={`https://www.youtube.com/watch?v=${ytId}&t=${Math.floor(f.timestamp_seconds)}s`}
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: c.accent, fontWeight: fontWeight.medium }}
                >
                  {f.timestamp_display}
                </a>
              ) : (
                <strong>{f.timestamp_display}</strong>
              )}
              {f.description ? ` — ${f.description}` : ''}
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}
