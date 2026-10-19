import { useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import {
  useChannel,
  useSubscribeChannel,
  useSyncChannel,
  useUnsubscribeChannel,
} from '../hooks/useChannels';
import { useLibraryVideos } from '../hooks/useLibrary';
import { useJob } from '../hooks/useJobs';
import { VideoRow } from '../components/library/VideoRow';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Select,
  Skeleton,
  Spinner,
} from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../theme';
import { formatDate } from '../utils/formatters';
import type { Channel } from '../services/channelsApi';
import type { LibrarySort } from '../services/libraryApi';

const PAGE_SIZE = 50;
const CHANNELS_TAB_HREF = '/library?tab=channels';

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

/**
 * One channel, as this reader sees it (S-8.7.1 / M7).
 *
 * Header: the shared channel facts plus the caller's own subscription state
 * (D-065); actions subscribe, sync and open the public page. Below it the
 * trust-weight slot (read-only until S-7.1.1 ships the write path and the
 * retrieval re-rank, D-068) and the documents this tenant can see from the
 * channel (D-063), listed through the library endpoint so the rows carry
 * "referenced in N runs" like everywhere else. The Intelligence tab (E-8.7)
 * attaches here once its aggregate endpoint exists.
 */
export function ChannelPage() {
  const { channelId } = useParams<{ channelId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const c = useColors();

  const channelQuery = useChannel(channelId ?? null);
  const subscribeMut = useSubscribeChannel();
  const unsubscribeMut = useUnsubscribeChannel();
  const syncMut = useSyncChannel();

  // A subscribe or sync dispatches a subscription job; watch it so the
  // button reads "Syncing…" until the worker is done, then refresh counts.
  const [syncJobId, setSyncJobId] = useState<string | null>(null);
  const { data: syncJob } = useJob(syncJobId);
  const syncStatus = syncJob?.status;

  useEffect(() => {
    if (!syncJobId) return;
    if (syncStatus === 'completed' || syncStatus === 'failed' || syncStatus === 'cancelled') {
      setSyncJobId(null);
      void queryClient.invalidateQueries({ queryKey: ['channel', channelId] });
      void queryClient.invalidateQueries({ queryKey: ['channels'] });
      void queryClient.invalidateQueries({ queryKey: ['libraryVideos'] });
    }
  }, [syncJobId, syncStatus, channelId, queryClient]);

  const channel = channelQuery.data;
  const notFound =
    channelQuery.isError &&
    isAxiosError(channelQuery.error) &&
    channelQuery.error.response?.status === 404;

  const handleToggleSubscribe = (ch: Channel) => {
    if (ch.subscribed) {
      unsubscribeMut.mutate(ch.channel_id);
    } else {
      subscribeMut.mutate(ch.channel_id, {
        onSuccess: (resp) => {
          if (resp.job_id) setSyncJobId(resp.job_id);
        },
      });
    }
  };

  const handleSync = (ch: Channel) => {
    syncMut.mutate(ch.channel_id, {
      onSuccess: (resp) => {
        if (resp.job_id) setSyncJobId(resp.job_id);
      },
    });
  };

  const subscribeBusy = subscribeMut.isPending || unsubscribeMut.isPending;
  const syncBusy = syncMut.isPending || !!syncJobId;

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
      <nav aria-label="Breadcrumb" style={{ marginBottom: space['3'] }}>
        <Link
          to={CHANNELS_TAB_HREF}
          style={{
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            fontWeight: fontWeight.medium,
            color: c.textSecondary,
            textDecoration: 'none',
          }}
        >
          ← Channels
        </Link>
      </nav>

      {channelQuery.isLoading ? (
        <HeaderSkeleton />
      ) : notFound ? (
        <EmptyState
          title="This channel isn't on your shelf."
          description="Nothing you have ingested comes from it, or the link is stale. Channels appear here once one of their videos joins your library."
          action={
            <Button variant="secondary" onClick={() => navigate(CHANNELS_TAB_HREF)}>
              Back to channels
            </Button>
          }
        />
      ) : channelQuery.isError || !channel ? (
        <EmptyState
          title="Couldn't load this channel."
          description="Something blocked the fetch. Try again in a moment."
          action={
            <Button variant="secondary" onClick={() => void channelQuery.refetch()}>
              Retry
            </Button>
          }
        />
      ) : (
        <>
          <ChannelHeader
            channel={channel}
            subscribeBusy={subscribeBusy}
            syncBusy={syncBusy}
            onToggleSubscribe={() => handleToggleSubscribe(channel)}
            onSync={() => handleSync(channel)}
          />
          <TrustWeightSlot weight={channel.source_weight} />
          <DocumentsSection channelId={channel.channel_id} total={channel.video_count} />
        </>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Header

function ChannelHeader({
  channel,
  subscribeBusy,
  syncBusy,
  onToggleSubscribe,
  onSync,
}: {
  channel: Channel;
  subscribeBusy: boolean;
  syncBusy: boolean;
  onToggleSubscribe: () => void;
  onSync: () => void;
}) {
  const c = useColors();
  const dot = (
    <span aria-hidden style={{ color: c.textMuted }}>
      ·
    </span>
  );

  return (
    <header style={{ marginBottom: space['5'] }}>
      <div
        style={{
          display: 'flex',
          gap: space['4'],
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <p
            style={{
              margin: `0 0 ${space['1']}`,
              fontFamily: fonts.ui,
              fontSize: fontSize.xs,
              fontWeight: fontWeight.semibold,
              color: c.textMuted,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
            }}
          >
            Channel
          </p>
          <h1
            style={{
              fontFamily: fonts.display,
              fontSize: fontSize['2xl'],
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
              margin: 0,
              lineHeight: lineHeight.tight,
              overflowWrap: 'anywhere',
            }}
          >
            {channel.name}
          </h1>
          <p
            style={{
              margin: `${space['2']} 0 0`,
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
                {dot}
              </>
            )}
            <span>
              {channel.video_count} {channel.video_count === 1 ? 'volume' : 'volumes'} on your
              shelf
            </span>
            {dot}
            <span style={{ color: c.textMuted }}>
              Last synced: {channel.last_synced_at ? formatDate(channel.last_synced_at) : 'never'}
            </span>
          </p>
        </div>

        <div
          style={{
            display: 'flex',
            gap: space['2'],
            alignItems: 'center',
            flexWrap: 'wrap',
            flexShrink: 0,
          }}
        >
          <Button
            size="sm"
            variant={channel.subscribed ? 'primary' : 'secondary'}
            onClick={onToggleSubscribe}
            disabled={subscribeBusy}
            aria-pressed={channel.subscribed}
          >
            {channel.subscribed ? 'Subscribed' : 'Subscribe'}
          </Button>
          <Button
            size="sm"
            variant="tertiary"
            onClick={onSync}
            disabled={syncBusy}
            leadingIcon={syncBusy ? <Spinner size={12} /> : undefined}
          >
            {syncBusy ? 'Syncing…' : 'Sync now'}
          </Button>
          {channel.url && (
            <a
              href={channel.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                fontWeight: fontWeight.medium,
                color: c.accent,
                textDecoration: 'none',
                padding: `${space['1']} ${space['3']}`,
                border: `1px solid transparent`,
                borderRadius: radius.md,
                whiteSpace: 'nowrap',
              }}
            >
              YouTube →
            </a>
          )}
        </div>
      </div>
    </header>
  );
}

function HeaderSkeleton() {
  return (
    <div
      aria-busy
      style={{ display: 'flex', flexDirection: 'column', gap: space['3'], marginBottom: space['5'] }}
    >
      <Skeleton width={72} height={12} />
      <Skeleton width="48%" height={32} />
      <Skeleton width="36%" height={14} />
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Trust weight — the slot S-7.1.1's control lands in

/**
 * Shows this reader's trust weight for the channel. The number is already
 * per tenant (`channel_subscriptions.source_weight`, D-065) and the formula
 * that will use it is pre-registered in D-068 (`distance / weight` after
 * the relevance threshold). Until E-7.1 ships `PUT /channels/{id}/weight`
 * and the re-rank, the slot is read-only; a control here that saved a
 * number nothing reads would mislead.
 */
function TrustWeightSlot({ weight }: { weight: number }) {
  const c = useColors();
  const neutral = Math.abs(weight - 1) < 1e-9;
  const standing = neutral ? 'neutral' : weight > 1 ? 'promoted' : 'demoted';

  return (
    <Card sunken data-slot="trust-weight" style={{ marginBottom: space['5'], padding: `${space['3']} ${space['4']}` }}>
      <div
        style={{
          display: 'flex',
          gap: space['3'],
          alignItems: 'center',
          flexWrap: 'wrap',
        }}
      >
        <span
          style={{
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
          }}
        >
          Trust weight
        </span>
        <Badge tone={neutral ? 'neutral' : 'accent'} size="md">
          {weight.toFixed(1)} · {standing}
        </Badge>
        <span
          style={{
            fontFamily: fonts.body,
            fontSize: fontSize.sm,
            color: c.textMuted,
            lineHeight: lineHeight.snug,
            flex: '1 1 320px',
          }}
        >
          Raising it lets this channel's passages outrank others in your answers; lowering it
          lets them sink. The control arrives with trust-weighted retrieval; until then the
          weight is shown, not set.
        </span>
      </div>
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────
// Documents

function DocumentsSection({ channelId, total }: { channelId: string; total: number }) {
  const c = useColors();
  const [search, setSearch] = useState('');
  const [transcriptStatus, setTranscriptStatus] = useState('');
  const [sort, setSort] = useState<LibrarySort>('newest');
  const [page, setPage] = useState(0);

  const videosQuery = useLibraryVideos({
    channel_id: channelId,
    search: search.trim() || undefined,
    transcript_status: transcriptStatus || undefined,
    sort,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const videos = videosQuery.data ?? [];
  const hasNextPage = videos.length === PAGE_SIZE;
  const filtersActive = !!search.trim() || !!transcriptStatus;

  const clearFilters = () => {
    setSearch('');
    setTranscriptStatus('');
    setPage(0);
  };

  let body: ReactNode;
  if (videosQuery.isLoading && page === 0) {
    body = (
      <div aria-busy style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        <Skeleton variant="card" height={104} />
        <Skeleton variant="card" height={104} />
        <Skeleton variant="card" height={104} />
      </div>
    );
  } else if (videosQuery.isError) {
    body = (
      <EmptyState
        size="sm"
        title="Couldn't load this channel's documents."
        description="Something blocked the library fetch."
        action={
          <Button size="sm" variant="secondary" onClick={() => void videosQuery.refetch()}>
            Retry
          </Button>
        }
      />
    );
  } else if (videos.length === 0 && filtersActive) {
    body = (
      <EmptyState
        size="sm"
        title="Nothing matches these filters."
        description="Loosen the search or the transcript filter to see more of this channel."
        action={
          <Button size="sm" variant="tertiary" onClick={clearFilters}>
            Clear filters
          </Button>
        }
      />
    );
  } else if (videos.length === 0) {
    body = (
      <EmptyState
        size="sm"
        title="Nothing from this channel on your shelf yet."
        description="Subscribe and sync to shelve its uploads, or pick its videos in a research run; either way they appear here."
      />
    );
  } else {
    body = (
      <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        {videos.map((video) => (
          <VideoRow key={video.id} video={video} channelLink={false} />
        ))}
      </div>
    );
  }

  return (
    <section aria-labelledby="channel-documents-heading">
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: space['3'],
          marginBottom: space['3'],
        }}
      >
        <h2
          id="channel-documents-heading"
          style={{
            fontFamily: fonts.display,
            fontSize: fontSize.lg,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            margin: 0,
          }}
        >
          Documents
        </h2>
        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>
          {total} on your shelf
        </span>
      </div>

      <Card style={{ marginBottom: space['4'] }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['3'], alignItems: 'center' }}>
          <div style={{ flex: '1 1 240px' }}>
            <Input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(0);
              }}
              placeholder="Search titles…"
              aria-label="Search this channel's documents"
            />
          </div>
          <div style={{ flex: '0 0 170px' }}>
            <Select
              value={transcriptStatus}
              onChange={(e) => {
                setTranscriptStatus(e.target.value);
                setPage(0);
              }}
              aria-label="Filter by transcript status"
            >
              {TRANSCRIPT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </Select>
          </div>
          <div style={{ flex: '0 0 140px' }}>
            <Select
              value={sort}
              onChange={(e) => {
                setSort(e.target.value as LibrarySort);
                setPage(0);
              }}
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

      {body}

      {(page > 0 || hasNextPage) && (
        <Pager page={page} hasNextPage={hasNextPage} onPageChange={setPage} />
      )}
    </section>
  );
}

function Pager({
  page,
  hasNextPage,
  onPageChange,
}: {
  page: number;
  hasNextPage: boolean;
  onPageChange: (next: number) => void;
}) {
  const c = useColors();
  const pill: CSSProperties = {
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    color: c.textSecondary,
    padding: `${space['1']} ${space['3']}`,
    border: `1px solid ${c.border}`,
    borderRadius: radius.pill,
  };
  return (
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
      <span style={pill}>Page {page + 1}</span>
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
  );
}
