import type { LibraryVideoResponse } from '../../services/libraryApi';
import { formatDate, formatDuration } from '../../utils/formatters';

interface Props {
  video: LibraryVideoResponse;
  onChannelClick?: (channelId: string, channelName: string) => void;
}

function transcriptBadgeColor(status: string): string {
  switch (status) {
    case 'fetched':
      return '#22c55e';
    case 'pending':
      return '#f59e0b';
    case 'unavailable':
      return '#ef4444';
    default:
      return '#94a3b8';
  }
}

export function VideoRow({ video, onChannelClick }: Props) {
  const badgeBg = transcriptBadgeColor(video.transcript_status);
  const jobTitlesTooltip = video.job_titles && video.job_titles.length > 0
    ? video.job_titles.join('\n')
    : 'Not used in any job yet';

  return (
    <div
      style={{
        background: '#fff',
        borderRadius: 12,
        padding: '1rem',
        boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
        border: '1px solid #e2e8f0',
        display: 'flex',
        gap: '1rem',
        alignItems: 'flex-start',
      }}
    >
      {video.thumbnail_url ? (
        <img
          src={video.thumbnail_url}
          alt={video.title}
          width={128}
          height={72}
          style={{ borderRadius: 8, objectFit: 'cover', flexShrink: 0, background: '#e2e8f0' }}
        />
      ) : (
        <div
          style={{
            width: 128,
            height: 72,
            borderRadius: 8,
            flexShrink: 0,
            background: '#e2e8f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#94a3b8',
            fontSize: '0.75rem',
          }}
        >
          No thumbnail
        </div>
      )}

      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
        <div
          style={{
            fontWeight: 600,
            color: '#1e293b',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={video.title}
        >
          {video.title}
        </div>

        <div style={{ fontSize: '0.85rem', color: '#64748b', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
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
              color: '#667eea',
              cursor: onChannelClick ? 'pointer' : 'default',
              fontSize: '0.85rem',
              fontWeight: 500,
              textDecoration: onChannelClick ? 'underline' : 'none',
            }}
          >
            {video.channel_name}
          </button>
          <span>·</span>
          <span>{formatDuration(video.duration_seconds)}</span>
          {video.published_at && (
            <>
              <span>·</span>
              <span>{formatDate(video.published_at)}</span>
            </>
          )}
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap', fontSize: '0.75rem' }}>
          <span
            style={{
              background: badgeBg,
              color: '#fff',
              padding: '2px 8px',
              borderRadius: 10,
              fontWeight: 600,
            }}
          >
            {video.transcript_status}
          </span>
          {video.transcript_language && (
            <span
              style={{
                background: '#e0e7ff',
                color: '#4338ca',
                padding: '2px 8px',
                borderRadius: 10,
                fontWeight: 600,
              }}
            >
              {video.transcript_language}
            </span>
          )}
          <span
            title={jobTitlesTooltip}
            style={{
              background: '#f1f5f9',
              color: '#475569',
              padding: '2px 8px',
              borderRadius: 10,
              fontWeight: 500,
              cursor: 'help',
            }}
          >
            Used in {video.job_count} {video.job_count === 1 ? 'job' : 'jobs'}
          </span>
          <a
            href={video.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            style={{
              color: '#667eea',
              textDecoration: 'none',
              marginLeft: 'auto',
              fontWeight: 600,
            }}
          >
            YouTube &rarr;
          </a>
        </div>
      </div>
    </div>
  );
}
