import { useCallback, useEffect, useMemo, useState } from 'react';
import { useJob } from '../hooks/useJobs';
import { useLibraryVideos } from '../hooks/useLibrary';
import {
  useChannels,
  useSubscribeChannel,
  useSyncChannel,
  useUnsubscribeChannel,
} from '../hooks/useChannels';
import { VideoRow } from '../components/library/VideoRow';
import { ChannelRow } from '../components/library/ChannelRow';
import {
  Button,
  Card,
  EmptyState,
  Input,
  Select,
  Spinner,
} from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import {
  fonts,
  fontSize,
  fontWeight,
  lineHeight,
  measure,
  radius,
  space,
} from '../theme';
import type { LibrarySort, LibraryVideoResponse } from '../services/libraryApi';
import type { Channel } from '../services/channelsApi';

type TabKey = 'videos' | 'channels';

const PAGE_SIZE = 50;

const LANGUAGE_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'All languages' },
  { value: 'en', label: 'English (en)' },
  { value: 'hi', label: 'Hindi (hi)' },
  { value: 'es', label: 'Spanish (es)' },
  { value: 'other', label: 'Other' },
];

const TRANSCRIPT_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'All transcripts' },
  { value: 'fetched', label: 'Fetched' },
  { value: 'pending', label: 'Pending' },
  { value: 'unavailable', label: 'Unavailable' },
];

const SORT_OPTIONS: { value: LibrarySort; label: string }[] = [
  { value: 'newest', label: 'Newest' },
  { value: 'oldest', label: 'Oldest' },
  { value: 'longest', label: 'Longest' },
  { value: 'shortest', label: 'Shortest' },
];

export function LibraryPage() {
  const c = useColors();
  const [tab, setTab] = useState<TabKey>('videos');

  const [search, setSearch] = useState('');
  const [language, setLanguage] = useState('');
  const [transcriptStatus, setTranscriptStatus] = useState('');
  const [channelFilter, setChannelFilter] = useState('');
  const [sort, setSort] = useState<LibrarySort>('newest');
  const [page, setPage] = useState(0);

  const [syncingChannels, setSyncingChannels] = useState<Record<string, string>>({});

  const channelsQuery = useChannels();
  const subscribeMut = useSubscribeChannel();
  const unsubscribeMut = useUnsubscribeChannel();
  const syncMut = useSyncChannel();

  const videosQuery = useLibraryVideos({
    search: search.trim() || undefined,
    language: language || undefined,
    channel_id: channelFilter || undefined,
    transcript_status: transcriptStatus || undefined,
    sort,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const resetPage = () => setPage(0);

  const handleChannelDrilldown = (channelId: string) => {
    setChannelFilter(channelId);
    setTab('videos');
    resetPage();
  };

  const handleToggleSubscribe = (channel: Channel) => {
    if (channel.subscribed) {
      unsubscribeMut.mutate(channel.id);
    } else {
      subscribeMut.mutate(channel.id);
    }
  };

  const handleSync = (channelId: string) => {
    syncMut.mutate(channelId, {
      onSuccess: (resp) => {
        setSyncingChannels((prev) => ({ ...prev, [channelId]: resp.job_id }));
      },
    });
  };

  const handleSyncFinished = useCallback((channelId: string) => {
    setSyncingChannels((prev) => {
      if (!(channelId in prev)) return prev;
      const next = { ...prev };
      delete next[channelId];
      return next;
    });
  }, []);

  const channelNameById = useMemo(() => {
    const map = new Map<string, string>();
    (channelsQuery.data ?? []).forEach((ch) => map.set(ch.channel_id, ch.name));
    return map;
  }, [channelsQuery.data]);

  const activeChannelFilterName = channelFilter
    ? channelNameById.get(channelFilter) ?? channelFilter
    : null;

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
      <header style={{ marginBottom: space['5'] }}>
        <h1
          style={{
            fontFamily: fonts.display,
            fontSize: fontSize['2xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            margin: 0,
            lineHeight: lineHeight.tight,
          }}
        >
          Your library
        </h1>
        <p
          style={{
            fontFamily: fonts.body,
            fontStyle: 'italic',
            fontSize: fontSize.sm,
            color: c.textMuted,
            margin: `${space['2']} 0 0`,
          }}
        >
          Every voice you've invited onto the shelves.
        </p>
      </header>

      <div
        role="tablist"
        aria-label="Library sections"
        style={{
          display: 'flex',
          gap: space['1'],
          marginBottom: space['4'],
          borderBottom: `1px solid ${c.border}`,
        }}
      >
        <TabButton active={tab === 'videos'} onClick={() => setTab('videos')}>
          Sources
        </TabButton>
        <TabButton active={tab === 'channels'} onClick={() => setTab('channels')}>
          Channels
        </TabButton>
      </div>

      {tab === 'videos' ? (
        <VideosTab
          search={search}
          onSearchChange={(v) => {
            setSearch(v);
            resetPage();
          }}
          language={language}
          onLanguageChange={(v) => {
            setLanguage(v);
            resetPage();
          }}
          transcriptStatus={transcriptStatus}
          onTranscriptStatusChange={(v) => {
            setTranscriptStatus(v);
            resetPage();
          }}
          channelFilter={channelFilter}
          channels={channelsQuery.data ?? []}
          onChannelFilterChange={(v) => {
            setChannelFilter(v);
            resetPage();
          }}
          activeChannelName={activeChannelFilterName}
          sort={sort}
          onSortChange={(v) => {
            setSort(v);
            resetPage();
          }}
          page={page}
          onPageChange={(next) => setPage(next)}
          videos={videosQuery.data ?? []}
          isLoading={videosQuery.isLoading}
          isError={videosQuery.isError}
          onPickChannel={(channelId) => {
            setChannelFilter(channelId);
            resetPage();
          }}
        />
      ) : (
        <ChannelsTab
          channels={channelsQuery.data ?? []}
          isLoading={channelsQuery.isLoading}
          isError={channelsQuery.isError}
          onOpenVideos={handleChannelDrilldown}
          onToggleSubscribe={handleToggleSubscribe}
          onSync={handleSync}
          subscribeBusyId={
            subscribeMut.isPending
              ? (subscribeMut.variables as string | undefined)
              : unsubscribeMut.isPending
                ? (unsubscribeMut.variables as string | undefined)
                : undefined
          }
          syncingChannels={syncingChannels}
          onSyncFinished={handleSyncFinished}
        />
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  const c = useColors();
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      style={{
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
        letterSpacing: '0.02em',
      }}
    >
      {children}
    </button>
  );
}

interface VideosTabProps {
  search: string;
  onSearchChange: (v: string) => void;
  language: string;
  onLanguageChange: (v: string) => void;
  transcriptStatus: string;
  onTranscriptStatusChange: (v: string) => void;
  channelFilter: string;
  channels: Channel[];
  onChannelFilterChange: (v: string) => void;
  activeChannelName: string | null;
  sort: LibrarySort;
  onSortChange: (v: LibrarySort) => void;
  page: number;
  onPageChange: (next: number) => void;
  videos: LibraryVideoResponse[];
  isLoading: boolean;
  isError: boolean;
  onPickChannel: (channelId: string) => void;
}

function VideosTab({
  search,
  onSearchChange,
  language,
  onLanguageChange,
  transcriptStatus,
  onTranscriptStatusChange,
  channelFilter,
  channels,
  onChannelFilterChange,
  activeChannelName,
  sort,
  onSortChange,
  page,
  onPageChange,
  videos,
  isLoading,
  isError,
  onPickChannel,
}: VideosTabProps) {
  const c = useColors();
  const hasNextPage = videos.length === PAGE_SIZE;

  return (
    <>
      <Card style={{ marginBottom: space['4'] }}>
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: space['3'],
            alignItems: 'center',
          }}
        >
          <div style={{ flex: '1 1 240px' }}>
            <Input
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Search title or channel…"
              aria-label="Search sources"
            />
          </div>
          <div style={{ flex: '0 0 170px' }}>
            <Select
              value={language}
              onChange={(e) => onLanguageChange(e.target.value)}
              aria-label="Filter by language"
            >
              {LANGUAGE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </Select>
          </div>
          <div style={{ flex: '0 0 170px' }}>
            <Select
              value={transcriptStatus}
              onChange={(e) => onTranscriptStatusChange(e.target.value)}
              aria-label="Filter by transcript status"
            >
              {TRANSCRIPT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </Select>
          </div>
          <div style={{ flex: '0 0 200px' }}>
            <Select
              value={channelFilter}
              onChange={(e) => onChannelFilterChange(e.target.value)}
              aria-label="Filter by channel"
            >
              <option value="">All channels</option>
              {channels.map((ch) => (
                <option key={ch.id} value={ch.channel_id}>
                  {ch.name}
                </option>
              ))}
            </Select>
          </div>
          <div style={{ flex: '0 0 140px' }}>
            <Select
              value={sort}
              onChange={(e) => onSortChange(e.target.value as LibrarySort)}
              aria-label="Sort order"
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </Card>

      {activeChannelName && (
        <div
          style={{
            marginBottom: space['3'],
            display: 'flex',
            alignItems: 'center',
            gap: space['3'],
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            color: c.textSecondary,
          }}
        >
          <span>
            Filtering by channel:{' '}
            <strong style={{ color: c.textPrimary, fontWeight: fontWeight.semibold }}>
              {activeChannelName}
            </strong>
          </span>
          <Button
            size="sm"
            variant="tertiary"
            onClick={() => onChannelFilterChange('')}
          >
            Clear
          </Button>
        </div>
      )}

      {isLoading && page === 0 ? (
        <div style={{ textAlign: 'center', padding: space['8'] }}>
          <Spinner size={32} />
        </div>
      ) : isError ? (
        <EmptyState
          size="sm"
          title="Couldn't load the shelves."
          description="Something blocked the library fetch. Try refreshing the page."
        />
      ) : videos.length === 0 ? (
        <EmptyState
          size="sm"
          title="Nothing matches these filters."
          description="Loosen the filters or clear the channel pick to see more volumes."
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          {videos.map((video) => (
            <VideoRow
              key={video.id}
              video={video}
              onChannelClick={(channelId) => onPickChannel(channelId)}
            />
          ))}
        </div>
      )}

      {(page > 0 || hasNextPage) && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            gap: space['4'],
            marginTop: space['6'],
          }}
        >
          <Button
            size="sm"
            variant="tertiary"
            disabled={page === 0}
            onClick={() => onPageChange(Math.max(0, page - 1))}
            leadingIcon={<span aria-hidden>←</span>}
          >
            Previous
          </Button>
          <span
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              color: c.textSecondary,
              padding: `${space['1']} ${space['3']}`,
              border: `1px solid ${c.border}`,
              borderRadius: radius.pill,
            }}
          >
            Page {page + 1}
          </span>
          <Button
            size="sm"
            variant="tertiary"
            disabled={!hasNextPage}
            onClick={() => onPageChange(page + 1)}
            trailingIcon={<span aria-hidden>→</span>}
          >
            Next
          </Button>
        </div>
      )}
    </>
  );
}

interface ChannelsTabProps {
  channels: Channel[];
  isLoading: boolean;
  isError: boolean;
  onOpenVideos: (channelId: string) => void;
  onToggleSubscribe: (channel: Channel) => void;
  onSync: (channelId: string) => void;
  subscribeBusyId: string | undefined;
  syncingChannels: Record<string, string>;
  onSyncFinished: (channelId: string) => void;
}

function ChannelsTab({
  channels,
  isLoading,
  isError,
  onOpenVideos,
  onToggleSubscribe,
  onSync,
  subscribeBusyId,
  syncingChannels,
  onSyncFinished,
}: ChannelsTabProps) {
  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: space['8'] }}>
        <Spinner size={32} />
      </div>
    );
  }
  if (isError) {
    return (
      <EmptyState
        size="sm"
        title="Couldn't load channels."
        description="Something blocked the channels fetch. Try refreshing the page."
      />
    );
  }
  if (channels.length === 0) {
    return (
      <EmptyState
        title="No channels on the shelf yet."
        description="Subscribe to a channel from a research run, or add them from the submit page."
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
      {channels.map((channel) => (
        <ChannelRowWithSyncWatcher
          key={channel.id}
          channel={channel}
          onOpenVideos={onOpenVideos}
          onToggleSubscribe={onToggleSubscribe}
          onSync={onSync}
          subscribeBusy={subscribeBusyId === channel.id}
          syncJobId={syncingChannels[channel.id]}
          onSyncFinished={onSyncFinished}
        />
      ))}
    </div>
  );
}

function ChannelRowWithSyncWatcher({
  channel,
  onOpenVideos,
  onToggleSubscribe,
  onSync,
  subscribeBusy,
  syncJobId,
  onSyncFinished,
}: {
  channel: Channel;
  onOpenVideos: (channelId: string) => void;
  onToggleSubscribe: (channel: Channel) => void;
  onSync: (channelId: string) => void;
  subscribeBusy: boolean;
  syncJobId: string | undefined;
  onSyncFinished: (channelId: string) => void;
}) {
  const { data: job } = useJob(syncJobId ?? null);
  const jobStatus = job?.status;

  useEffect(() => {
    if (jobStatus === 'completed' || jobStatus === 'failed' || jobStatus === 'cancelled') {
      onSyncFinished(channel.id);
    }
  }, [jobStatus, channel.id, onSyncFinished]);

  return (
    <ChannelRow
      channel={channel}
      onOpenVideos={onOpenVideos}
      onToggleSubscribe={onToggleSubscribe}
      onSync={onSync}
      subscribeBusy={subscribeBusy}
      syncBusy={!!syncJobId}
    />
  );
}

