import type { Channel } from '../../services/channelsApi';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { formatDate } from '../../utils/formatters';

interface Props {
  channel: Channel;
  onOpenVideos: (channelId: string) => void;
  onToggleSubscribe: (channel: Channel) => void;
  onSync: (channelId: string) => void;
  subscribeBusy?: boolean;
  syncBusy?: boolean;
}

export function ChannelRow({
  channel,
  onOpenVideos,
  onToggleSubscribe,
  onSync,
  subscribeBusy,
  syncBusy,
}: Props) {
  const subscribed = channel.subscribed;

  return (
    <div
      onClick={() => onOpenVideos(channel.channel_id)}
      style={{
        background: '#fff',
        borderRadius: 12,
        padding: '1rem',
        boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
        border: '1px solid #e2e8f0',
        cursor: 'pointer',
        display: 'flex',
        gap: '1rem',
        alignItems: 'center',
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontWeight: 600,
            color: '#1e293b',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={channel.name}
        >
          {channel.name}
        </div>
        <div style={{ fontSize: '0.8rem', color: '#64748b', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          {channel.subscriber_count != null && (
            <>
              <span>{channel.subscriber_count.toLocaleString()} subscribers</span>
              <span>·</span>
            </>
          )}
          <span>{channel.video_count} {channel.video_count === 1 ? 'video' : 'videos'} in library</span>
          <span>·</span>
          <span>
            Last synced: {channel.last_synced_at ? formatDate(channel.last_synced_at) : 'never'}
          </span>
        </div>
      </div>

      <div
        style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexShrink: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={() => onToggleSubscribe(channel)}
          disabled={subscribeBusy}
          style={{
            background: subscribed ? '#22c55e' : 'transparent',
            color: subscribed ? '#fff' : '#22c55e',
            border: `1px solid #22c55e`,
            padding: '0.3rem 0.8rem',
            borderRadius: 8,
            fontSize: '0.8rem',
            fontWeight: 600,
            cursor: subscribeBusy ? 'wait' : 'pointer',
            opacity: subscribeBusy ? 0.6 : 1,
          }}
        >
          {subscribed ? 'Subscribed' : 'Subscribe'}
        </button>
        <button
          type="button"
          onClick={() => onSync(channel.id)}
          disabled={syncBusy}
          style={{
            background: 'transparent',
            color: '#667eea',
            border: '1px solid #667eea',
            padding: '0.3rem 0.8rem',
            borderRadius: 8,
            fontSize: '0.8rem',
            fontWeight: 600,
            cursor: syncBusy ? 'wait' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '0.4rem',
            opacity: syncBusy ? 0.7 : 1,
          }}
        >
          {syncBusy && <LoadingSpinner size={12} />}
          {syncBusy ? 'Syncing...' : 'Sync now'}
        </button>
      </div>
    </div>
  );
}
