import type { LibraryVideoResponse } from '../../services/libraryApi';
import { formatDate, formatDuration } from '../../utils/formatters';
import { Badge, Card, type BadgeTone } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space } from '../../theme';

interface Props {
  video: LibraryVideoResponse;
  onChannelClick?: (channelId: string, channelName: string) => void;
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

export function VideoRow({ video, onChannelClick }: Props) {
  const c = useColors();
  const tone = transcriptBadgeTone(video.transcript_status);
  const jobTitlesTooltip =
    video.job_titles && video.job_titles.length > 0
      ? video.job_titles.join('\n')
      : 'Not used in any run yet';

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
              fontFamily: fonts.ui,
              fontSize: fontSize.xs,
            }}
          >
            No thumbnail
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
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onChannelClick?.(video.channel_id, video.channel_name);
              }}
              style={{
                background: 'transparent',
                border: 'none',
                padding: 0,
                color: c.accent,
                cursor: onChannelClick ? 'pointer' : 'default',
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                fontWeight: fontWeight.medium,
                textDecoration: onChannelClick ? 'underline' : 'none',
                textUnderlineOffset: '3px',
              }}
            >
              {video.channel_name}
            </button>
            <span aria-hidden style={{ color: c.textMuted }}>
              ·
            </span>
            <span>{formatDuration(video.duration_seconds)}</span>
            {video.published_at && (
              <>
                <span aria-hidden style={{ color: c.textMuted }}>
                  ·
                </span>
                <span>{formatDate(video.published_at)}</span>
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
            <a
              href={video.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              style={{
                marginLeft: 'auto',
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                fontWeight: fontWeight.semibold,
                color: c.accent,
                textDecoration: 'none',
                letterSpacing: '0.02em',
              }}
            >
              YouTube →
            </a>
          </div>
        </div>
      </div>
    </Card>
  );
}
