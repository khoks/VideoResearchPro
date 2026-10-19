import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
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
import { PdfUploadZone } from '../components/library/PdfUploadZone';
import { PasteUrlsForm } from '../components/library/PasteUrlsForm';
import { TagFilterBar } from '../components/tags';
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

type TabKey = 'videos' | 'channels' | 'ingest';

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
  const navigate = useNavigate();
  // `?tab=channels` lets the channel page's breadcrumb land on the right tab.
  // `?tag=<id>` is the tag filter (S-8.1.3), kept in the URL so a tag chip
  // anywhere in the app is a plain link.
  const [searchParams, setSearchParams] = useSearchParams();
  const tagFilter = searchParams.get('tag') ?? '';
  // `?document=<id>` is where a palette / search result for a source lands
  // (S-8.2.2): the list narrows to that one row until "Show all sources".
  const documentFilter = searchParams.get('document') ?? '';
  const [tab, setTab] = useState<TabKey>(() => {
    const requested = searchParams.get('tab');
    if (searchParams.get('document')) return 'videos';
    return requested === 'channels' || requested === 'ingest' ? requested : 'videos';
  });

  useEffect(() => {
    if (documentFilter) setTab('videos');
  }, [documentFilter]);

  const clearDocumentFilter = useCallback(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('document');
        return next;
      },
      { replace: true },
    );
  }, [setSearchParams]);

  const [search, setSearch] = useState('');
  const [language, setLanguage] = useState('');
  const [transcriptStatus, setTranscriptStatus] = useState('');
  const [channelFilter, setChannelFilter] = useState('');
  const [sort, setSort] = useState<LibrarySort>('newest');
  const [page, setPage] = useState(0);

  // A tag chip clicked elsewhere lands here with a new `?tag=`: start at page 1.
  useEffect(() => {
    setPage(0);
  }, [tagFilter]);

  const setTagFilter = useCallback(
    (tagId: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (tagId) next.set('tag', tagId);
          else next.delete('tag');
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

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
    tag: tagFilter || undefined,
    document_id: documentFilter || undefined,
    sort,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const resetPage = () => setPage(0);

  // Opening a channel goes to its page (S-8.7.1); the in-place channel
  // filter on the Sources tab remains available from the filter rail.
  const handleOpenChannel = (channelId: string) => {
    navigate(`/library/channels/${channelId}`);
  };

  const handleToggleSubscribe = (channel: Channel) => {
    if (channel.subscribed) {
      unsubscribeMut.mutate(channel.channel_id);
    } else {
      subscribeMut.mutate(channel.channel_id);
    }
  };

  const handleSync = (channelId: string) => {
    syncMut.mutate(channelId, {
      onSuccess: (resp) => {
        // `job_id` is null when the broker was unreachable; nothing to watch.
        const jobId = resp.job_id;
        if (!jobId) return;
        setSyncingChannels((prev) => ({ ...prev, [channelId]: jobId }));
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

  // After an ingest, show the newest volumes with no filter in the way.
  const handleViewShelf = useCallback(() => {
    setSearch('');
    setLanguage('');
    setTranscriptStatus('');
    setChannelFilter('');
    setTagFilter('');
    setSort('newest');
    setPage(0);
    setTab('videos');
  }, [setTagFilter]);

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
        <TabButton active={tab === 'ingest'} onClick={() => setTab('ingest')}>
          Add sources
        </TabButton>
      </div>

      {tab === 'ingest' ? (
        <IngestTab onViewShelf={handleViewShelf} />
      ) : tab === 'videos' ? (
        <>
        {documentFilter && <OneSourceBanner onShowAll={clearDocumentFilter} />}
        <TagFilterBar value={tagFilter} onChange={setTagFilter} />
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
        />
        </>
      ) : (
        <ChannelsTab
          channels={channelsQuery.data ?? []}
          isLoading={channelsQuery.isLoading}
          isError={channelsQuery.isError}
          onOpen={handleOpenChannel}
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

/**
 * "Add sources" — the two ingest paths that do not go through a research
 * run: PDF upload (E-1.8) and pasted URLs (S-1.5.8). Both endpoints are
 * library-scoped on the backend, so they live here rather than on the
 * Submit page. Each shelved document is granted to this tenant (D-063)
 * and immediately joins library-wide Q&A.
 */
function IngestTab({ onViewShelf }: { onViewShelf: () => void }) {
  const c = useColors();
  const sectionTitle: React.CSSProperties = {
    margin: 0,
    fontFamily: fonts.display,
    fontSize: fontSize.lg,
    fontWeight: fontWeight.semibold,
    color: c.textPrimary,
  };
  const sectionLede: React.CSSProperties = {
    margin: `${space['1']} 0 ${space['4']}`,
    fontFamily: fonts.body,
    fontSize: fontSize.sm,
    color: c.textSecondary,
    lineHeight: lineHeight.normal,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['5'] }}>
      <p
        style={{
          margin: 0,
          fontFamily: fonts.body,
          fontSize: fontSize.base,
          color: c.textSecondary,
          lineHeight: lineHeight.normal,
          maxWidth: measure.reading,
        }}
      >
        Not everything worth keeping arrives through a research run. Shelve your own PDFs and
        any page you can link to; they join the library at once and answer alongside everything
        else when you ask across it.
      </p>

      <Card>
        <h2 style={sectionTitle}>Upload PDFs</h2>
        <p style={sectionLede}>
          Papers, reports, book chapters. Citations later deep-link to the page they came from.
        </p>
        <PdfUploadZone onViewShelf={onViewShelf} />
      </Card>

      <Card>
        <h2 style={sectionTitle}>Paste URLs</h2>
        <p style={sectionLede}>
          Essays, blog posts, newsletters, and posts from Facebook, Instagram, LinkedIn or X.
        </p>
        <PasteUrlsForm onViewShelf={onViewShelf} />
      </Card>
    </div>
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
              data-page-search
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
                <option key={ch.channel_id} value={ch.channel_id}>
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
            <VideoRow key={video.id} video={video} />
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
  onOpen: (channelId: string) => void;
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
  onOpen,
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
          key={channel.channel_id}
          channel={channel}
          onOpen={onOpen}
          onToggleSubscribe={onToggleSubscribe}
          onSync={onSync}
          subscribeBusy={subscribeBusyId === channel.channel_id}
          syncJobId={syncingChannels[channel.channel_id]}
          onSyncFinished={onSyncFinished}
        />
      ))}
    </div>
  );
}

function ChannelRowWithSyncWatcher({
  channel,
  onOpen,
  onToggleSubscribe,
  onSync,
  subscribeBusy,
  syncJobId,
  onSyncFinished,
}: {
  channel: Channel;
  onOpen: (channelId: string) => void;
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
      onSyncFinished(channel.channel_id);
    }
  }, [jobStatus, channel.channel_id, onSyncFinished]);

  return (
    <ChannelRow
      channel={channel}
      onOpen={onOpen}
      onToggleSubscribe={onToggleSubscribe}
      onSync={onSync}
      subscribeBusy={subscribeBusy}
      syncBusy={!!syncJobId}
    />
  );
}

/** Shown while `?document=` narrows the list to the one source a search
 *  result pointed at (S-8.2.2). */
function OneSourceBanner({ onShowAll }: { onShowAll: () => void }) {
  const c = useColors();
  return (
    <div
      role="status"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: space['2'],
        margin: `0 0 ${space['3']}`,
        padding: `${space['2']} ${space['3']}`,
        background: c.accentSubtle,
        borderRadius: radius.md,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        color: c.textPrimary,
      }}
    >
      <span>Showing the one source you opened from search.</span>
      <Button size="sm" variant="secondary" onClick={onShowAll}>
        Show all sources
      </Button>
    </div>
  );
}
