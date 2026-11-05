import { useSearchParams } from 'react-router-dom';
import { DocumentsBrowser } from '../library/DocumentsBrowser';
import { libraryApi } from '../../services/libraryApi';
import type { Channel } from '../../services/channelsApi';
import { IntelligenceTab } from './IntelligenceTab';
import { Tab, Tabs } from '../primitives';

type TabKey = 'documents' | 'intelligence';

/**
 * Documents | Intelligence on the channel page (S-8.7.3). The tab lives in
 * `?tab=` so the Intelligence view can be linked to.
 */
export function ChannelTabs({ channel }: { channel: Channel }) {
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

  return (
    <>
      <Tabs label="Channel sections">
        <Tab active={tab === 'documents'} onClick={() => select('documents')} style={{ letterSpacing: 'normal' }}>
          Documents
        </Tab>
        <Tab active={tab === 'intelligence'} onClick={() => select('intelligence')} style={{ letterSpacing: 'normal' }}>
          Intelligence
        </Tab>
      </Tabs>
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
