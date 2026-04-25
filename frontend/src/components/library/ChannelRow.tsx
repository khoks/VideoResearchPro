import type { Channel } from '../../services/channelsApi';
import { formatDate } from '../../utils/formatters';
import { Button, Card, Spinner } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, space } from '../../theme';

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
  const c = useColors();
  const subscribed = channel.subscribed;

  return (
    <Card
      interactive
      onClick={() => onOpenVideos(channel.channel_id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpenVideos(channel.channel_id);
        }
      }}
    >
      <div
        style={{
          display: 'flex',
          gap: space['4'],
          alignItems: 'center',
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontFamily: fonts.display,
              fontWeight: fontWeight.semibold,
              fontSize: fontSize.md,
              color: c.textPrimary,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              marginBottom: space['1'],
            }}
            title={channel.name}
          >
            {channel.name}
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
            {channel.subscriber_count != null && (
              <>
                <span>{channel.subscriber_count.toLocaleString()} subscribers</span>
                <span aria-hidden style={{ color: c.textMuted }}>
                  ·
                </span>
              </>
            )}
            <span>
              {channel.video_count}{' '}
              {channel.video_count === 1 ? 'volume' : 'volumes'} on your shelf
            </span>
            <span aria-hidden style={{ color: c.textMuted }}>
              ·
            </span>
            <span style={{ color: c.textMuted }}>
              Last synced:{' '}
              {channel.last_synced_at ? formatDate(channel.last_synced_at) : 'never'}
            </span>
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            gap: space['2'],
            alignItems: 'center',
            flexShrink: 0,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <Button
            size="sm"
            variant={subscribed ? 'primary' : 'secondary'}
            onClick={() => onToggleSubscribe(channel)}
            disabled={subscribeBusy}
          >
            {subscribed ? 'Subscribed' : 'Subscribe'}
          </Button>
          <Button
            size="sm"
            variant="tertiary"
            onClick={() => onSync(channel.id)}
            disabled={syncBusy}
            leadingIcon={syncBusy ? <Spinner size={12} /> : undefined}
          >
            {syncBusy ? 'Syncing…' : 'Sync now'}
          </Button>
        </div>
      </div>
    </Card>
  );
}
