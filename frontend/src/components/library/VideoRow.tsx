import { useState } from 'react';
import { Link } from 'react-router-dom';
import { inferSourceType, libraryApi, type LibraryVideoResponse } from '../../services/libraryApi';
import { TabBlockedError } from '../../services/apiFiles';
import { TAB_BLOCKED_MESSAGE } from '../citation/citedFile';
import { formatDate, formatDuration } from '../../utils/formatters';
import { sourceTypeLabel } from '../../utils/ingestResults';
import { useJobStore } from '../../stores/jobStore';
import { Badge, Card, type BadgeTone } from '../primitives';
import { NotesPanel } from '../notes';
import { DocumentTags } from '../tags/DocumentTags';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space } from '../../theme';

interface Props {
  video: LibraryVideoResponse;
  /**
   * Render the channel name as a link to its page (`/library/channels/:id`,
   * S-8.7.1). The channel page passes `false` so rows do not link back to
   * the page they are on.
   */
  channelLink?: boolean;
}

function transcriptBadgeTone(status: string): BadgeTone {
  switch (status) {
    case 'fetched':
      return 'success';
    case 'pending':
      return 'warn';
    case 'unavailable':
      return 'error';
    default:
      return 'neutral';
  }
}

/**
 * One shelf row. Built for YouTube videos; tolerant of PDFs and pasted
 * pages, which have no channel, duration or thumbnail (see D-063 and the
 * Add sources tab).
 */
export function VideoRow({ video, channelLink = true }: Props) {
  const c = useColors();
  const pushToast = useJobStore((s) => s.pushToast);
  const [opening, setOpening] = useState(false);
  const tone = transcriptBadgeTone(video.transcript_status);
  const sourceType = inferSourceType(video);
  const isVideo = sourceType === 'video';
  const hasChannel = !!video.channel_id && !!video.channel_name;
  const jobTitlesTooltip =
    video.job_titles && video.job_titles.length > 0
      ? video.job_titles.join('\n')
      : 'Not used in any run yet';

  const linkStyle: React.CSSProperties = {
    marginLeft: 'auto',
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    fontWeight: fontWeight.semibold,
    color: c.accent,
    textDecoration: 'none',
    letterSpacing: '0.02em',
    background: 'transparent',
    border: 'none',
    padding: 0,
    cursor: 'pointer',
  };

  const openPdf = async () => {
    setOpening(true);
    try {
      await libraryApi.openPdf(video.url);
    } catch (err) {
      pushToast(
        'error',
        err instanceof TabBlockedError
          ? TAB_BLOCKED_MESSAGE
          : 'Could not fetch the PDF. It may have been removed from the upload directory.',
      );
    } finally {
      setOpening(false);
    }
  };

  return (
    <Card flush>
      <div
        style={{
          padding: space['4'],
          display: 'flex',
          gap: space['4'],
          alignItems: 'flex-start',
        }}
      >
        {video.thumbnail_url ? (
          <img
            src={video.thumbnail_url}
            alt=""
            width={128}
            height={72}
            style={{
              borderRadius: radius.md,
              objectFit: 'cover',
              flexShrink: 0,
              background: c.surfaceAlt,
              border: `1px solid ${c.border}`,
            }}
          />
        ) : (
          <div
            style={{
              width: 128,
              height: 72,
              borderRadius: radius.md,
              flexShrink: 0,
              background: c.surfaceAlt,
              border: `1px solid ${c.border}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: c.textMuted,
              fontFamily: isVideo ? fonts.ui : fonts.display,
              fontSize: isVideo ? fontSize.xs : fontSize.sm,
              fontWeight: isVideo ? fontWeight.regular : fontWeight.semibold,
              textAlign: 'center',
              padding: space['2'],
            }}
          >
            {isVideo ? 'No thumbnail' : sourceTypeLabel(sourceType)}
          </div>
        )}

        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: space['2'],
          }}
        >
          <div
            style={{
              fontFamily: fonts.display,
              fontWeight: fontWeight.semibold,
              fontSize: fontSize.md,
              color: c.textPrimary,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={video.title}
          >
            {video.title}
          </div>

          <div
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              color: c.textSecondary,
              display: 'flex',
              gap: space['2'],
              flexWrap: 'wrap',
              alignItems: 'center',
            }}
          >
            {hasChannel && channelLink ? (
              <Link
                to={`/library/channels/${video.channel_id}`}
                onClick={(e) => e.stopPropagation()}
                title={`Open ${video.channel_name}`}
                style={{
                  color: c.accent,
                  fontFamily: fonts.ui,
                  fontSize: fontSize.sm,
                  fontWeight: fontWeight.medium,
                  textDecoration: 'underline',
                  textUnderlineOffset: '3px',
                }}
              >
                {video.channel_name}
              </Link>
            ) : hasChannel ? (
              <span style={{ fontWeight: fontWeight.medium }}>{video.channel_name}</span>
            ) : (
              <span style={{ fontWeight: fontWeight.medium }}>{sourceTypeLabel(sourceType)}</span>
            )}
            {video.duration_seconds !== null && video.duration_seconds !== undefined && (
              <>
                <span aria-hidden style={{ color: c.textMuted }}>
                  ·
                </span>
                <span>{formatDuration(video.duration_seconds)}</span>
              </>
            )}
            {video.published_at && (
              <>
                <span aria-hidden style={{ color: c.textMuted }}>
                  ·
                </span>
                <span>{formatDate(video.published_at)}</span>
              </>
            )}
            {!isVideo && video.transcript_word_count !== null && (
              <>
                <span aria-hidden style={{ color: c.textMuted }}>
                  ·
                </span>
                <span>{video.transcript_word_count.toLocaleString()} words</span>
              </>
            )}
          </div>

          <div
            style={{
              display: 'flex',
              gap: space['2'],
              alignItems: 'center',
              flexWrap: 'wrap',
            }}
          >
            <Badge tone={tone} size="sm">
              {video.transcript_status}
            </Badge>
            {video.transcript_language && (
              <Badge tone="info" size="sm">
                {video.transcript_language}
              </Badge>
            )}
            <span
              title={jobTitlesTooltip}
              style={{
                fontFamily: fonts.ui,
                fontSize: fontSize.xs,
                color: c.textMuted,
                cursor: 'help',
                letterSpacing: '0.02em',
              }}
            >
              Referenced in {video.job_count}{' '}
              {video.job_count === 1 ? 'run' : 'runs'}
            </span>
            {sourceType === 'pdf' ? (
              <button type="button" onClick={openPdf} disabled={opening} style={{ ...linkStyle, opacity: opening ? 0.6 : 1 }}>
                {opening ? 'Opening…' : 'Open PDF →'}
              </button>
            ) : (
              <a
                href={video.url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                style={linkStyle}
              >
                {isVideo ? 'YouTube →' : 'Open →'}
              </a>
            )}
          </div>
          <DocumentTags documentId={video.id} tags={video.tags ?? []} />
          <NotesPanel
            targetType="document"
            targetId={video.video_id || video.id}
            matchIds={[video.id, video.video_id]}
          />
        </div>
      </div>
    </Card>
  );
}
