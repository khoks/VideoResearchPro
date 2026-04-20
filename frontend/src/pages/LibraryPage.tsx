import { useCallback, useEffect, useMemo, useState } from 'react';
import { useJob } from '../hooks/useJobs';
import { useLibraryVideos } from '../hooks/useLibrary';
import {
  useChannels,
  useSubscribeChannel,
  useSyncChannel,
  useUnsubscribeChannel,
} from '../hooks/useChannels';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { VideoRow } from '../components/library/VideoRow';
import { ChannelRow } from '../components/library/ChannelRow';
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

const inputStyle: React.CSSProperties = {
  padding: '0.5rem 0.75rem',
  borderRadius: 8,
  border: '1px solid var(--color-border)',
  fontSize: '0.9rem',
  background: 'var(--color-surface)',
  color: 'var(--color-text)',
};

export function LibraryPage() {
  const [tab, setTab] = useState<TabKey>('videos');

  // Videos tab state
  const [search, setSearch] = useState('');
  const [language, setLanguage] = useState('');
  const [transcriptStatus, setTranscriptStatus] = useState('');
  const [channelFilter, setChannelFilter] = useState('');
  const [sort, setSort] = useState<LibrarySort>('newest');
  const [page, setPage] = useState(0);

  // Track the sync job kicked off from the channels tab so we can show a spinner
  // until it reaches completed/failed.
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
    (channelsQuery.data ?? []).forEach((c) => map.set(c.channel_id, c.name));
    return map;
  }, [channelsQuery.data]);

  const activeChannelFilterName = channelFilter
    ? channelNameById.get(channelFilter) ?? channelFilter
    : null;

  return (
    <div>
      <h2 style={{ marginBottom: '1rem', color: 'var(--color-text)' }}>Library</h2>

      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
        <TabButton active={tab === 'videos'} onClick={() => setTab('videos')}>
          Videos
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
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: active ? '#667eea' : 'transparent',
        color: active ? '#fff' : '#667eea',
        border: '1px solid #667eea',
        padding: '0.4rem 1.2rem',
        borderRadius: 8,
        cursor: 'pointer',
        fontWeight: 600,
        fontSize: '0.9rem',
      }}
    >
      {children}
    </button>
  );
}

// ---------------------------- Videos tab ----------------------------

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
  const hasNextPage = videos.length === PAGE_SIZE;

  return (
    <>
      <div
        style={{
          background: 'var(--color-surface)',
          borderRadius: 12,
          padding: '1rem',
          marginBottom: '1rem',
          boxShadow: 'var(--shadow-card)',
          display: 'flex',
          flexWrap: 'wrap',
          gap: '0.75rem',
          alignItems: 'center',
        }}
      >
        <input
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search title or channel..."
          style={{ ...inputStyle, flex: '1 1 240px' }}
        />
        <select
          value={language}
          onChange={(e) => onLanguageChange(e.target.value)}
          style={inputStyle}
        >
          {LANGUAGE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <select
          value={transcriptStatus}
          onChange={(e) => onTranscriptStatusChange(e.target.value)}
          style={inputStyle}
        >
          {TRANSCRIPT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <select
          value={channelFilter}
          onChange={(e) => onChannelFilterChange(e.target.value)}
          style={inputStyle}
        >
          <option value="">All channels</option>
          {channels.map((c) => (
            <option key={c.id} value={c.channel_id}>
              {c.name}
            </option>
          ))}
        </select>
        <select
          value={sort}
          onChange={(e) => onSortChange(e.target.value as LibrarySort)}
          style={inputStyle}
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {activeChannelName && (
        <div
          style={{
            marginBottom: '0.75rem',
            fontSize: '0.85rem',
            color: '#64748b',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <span>
            Filtering by channel: <strong style={{ color: '#1e293b' }}>{activeChannelName}</strong>
          </span>
          <button
            type="button"
            onClick={() => onChannelFilterChange('')}
            style={{
              background: 'transparent',
              border: '1px solid #cbd5e1',
              padding: '0.2rem 0.6rem',
              borderRadius: 6,
              cursor: 'pointer',
              fontSize: '0.75rem',
              color: '#475569',
            }}
          >
            Clear
          </button>
        </div>
      )}

      {isLoading && page === 0 ? (
        <div style={{ textAlign: 'center', padding: '3rem' }}>
          <LoadingSpinner size={40} />
        </div>
      ) : isError ? (
        <div style={{ textAlign: 'center', padding: '2rem', color: '#ef4444' }}>
          Failed to load library videos.
        </div>
      ) : videos.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '2rem', color: '#64748b' }}>
          No videos match the current filters.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
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
            gap: '1rem',
            marginTop: '1.5rem',
          }}
        >
          <button
            onClick={() => onPageChange(Math.max(0, page - 1))}
            disabled={page === 0}
            style={{
              background: '#fff',
              color: '#667eea',
              border: '1px solid #e2e8f0',
              padding: '0.5rem 1rem',
              borderRadius: 8,
              cursor: page === 0 ? 'not-allowed' : 'pointer',
              opacity: page === 0 ? 0.5 : 1,
              fontWeight: 600,
              fontSize: '0.85rem',
            }}
          >
            &larr; Previous
          </button>
          <span style={{ fontSize: '0.85rem', color: '#64748b' }}>Page {page + 1}</span>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={!hasNextPage}
            style={{
              background: '#fff',
              color: '#667eea',
              border: '1px solid #e2e8f0',
              padding: '0.5rem 1rem',
              borderRadius: 8,
              cursor: !hasNextPage ? 'not-allowed' : 'pointer',
              opacity: !hasNextPage ? 0.5 : 1,
              fontWeight: 600,
              fontSize: '0.85rem',
            }}
          >
            Next &rarr;
          </button>
        </div>
      )}
    </>
  );
}

// ---------------------------- Channels tab ----------------------------

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
      <div style={{ textAlign: 'center', padding: '3rem' }}>
        <LoadingSpinner size={40} />
      </div>
    );
  }
  if (isError) {
    return (
      <div style={{ textAlign: 'center', padding: '2rem', color: '#ef4444' }}>
        Failed to load channels.
      </div>
    );
  }
  if (channels.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '2rem', color: '#64748b' }}>
        No channels yet. Subscribe to channels from a job or add them here.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
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

/**
 * Wraps ChannelRow and watches the returned sync-job until it terminates, so the
 * "Sync now" button keeps a spinner until the server confirms completion.
 */
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
