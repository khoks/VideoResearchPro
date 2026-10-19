import { useSearchParams } from 'react-router-dom';
import { DocumentsBrowser } from '../library/DocumentsBrowser';
import { libraryApi } from '../../services/libraryApi';
import type { Channel } from '../../services/channelsApi';
import { IntelligenceTab } from './IntelligenceTab';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, space } from '../../theme';

type TabKey = 'documents' | 'intelligence';

/**
 * Documents | Intelligence on the channel page (S-8.7.3). The tab lives in
 * `?tab=` so the Intelligence view can be linked to.
 */
export function ChannelTabs({ channel }: { channel: Channel }) {
  const c = useColors();
  const [params, setParams] = useSearchParams();
  const tab: TabKey = params.get('tab') === 'intelligence' ? 'intelligence' : 'documents';
  const select = (next: TabKey) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next === 'documents') p.delete('tab');
        else p.set('tab', next);
        return p;
      },
      { replace: true },
    );

  const tabStyle = (active: boolean) => ({
    background: 'transparent',
    color: active ? c.accent : c.textSecondary,
    border: 'none',
    borderBottom: `2px solid ${active ? c.accent : 'transparent'}`,
    padding: `${space['2']} ${space['4']}`,
    marginBottom: -1,
    cursor: 'pointer',
    fontFamily: fonts.ui,
    fontWeight: active ? fontWeight.semibold : fontWeight.medium,
    fontSize: fontSize.sm,
  });

  return (
    <>
      <div
        role="tablist"
        aria-label="Channel sections"
        style={{ display: 'flex', gap: space['1'], marginBottom: space['4'], borderBottom: `1px solid ${c.border}` }}
      >
        <button type="button" role="tab" aria-selected={tab === 'documents'} style={tabStyle(tab === 'documents')} onClick={() => select('documents')}>
          Documents
        </button>
        <button type="button" role="tab" aria-selected={tab === 'intelligence'} style={tabStyle(tab === 'intelligence')} onClick={() => select('intelligence')}>
          Intelligence
        </button>
      </div>
      {tab === 'documents' ? (
        <DocumentsBrowser
          queryKey={['libraryVideos', 'channel', channel.channel_id]}
          fetch={(params) => libraryApi.listVideos({ ...params, channel_id: channel.channel_id })}
          total={channel.video_count}
          channelLink={false}
          emptyTitle="Nothing from this channel on your shelf yet."
          emptyDescription="Subscribe and sync to shelve its uploads, or pick its videos in a research run; either way they appear here."
        />
      ) : (
        <IntelligenceTab channelId={channel.channel_id} />
      )}
    </>
  );
}
