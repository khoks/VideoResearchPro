import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import {
  useChannel,
  useSetChannelWeight,
  useSubscribeChannel,
  useSyncChannel,
  useUnsubscribeChannel,
} from '../hooks/useChannels';
import { useJob } from '../hooks/useJobs';
import { ChannelTabs } from '../components/channel/ChannelTabs';
import { Badge, Button, Card, EmptyState, Skeleton, Spinner } from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../theme';
import { formatDate } from '../utils/formatters';
import type { Channel } from '../services/channelsApi';

const CHANNELS_TAB_HREF = '/library?tab=channels';


/**
 * One channel, as this reader sees it (S-8.7.1 / M7).
 *
 * Header: the shared channel facts plus the caller's own subscription state
 * (D-065); actions subscribe, sync and open the public page. Below it the
 * trust-weight control (S-7.1.1, D-068) and the documents this tenant can see from the
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
          <TrustWeightControl channelId={channel.channel_id} weight={channel.source_weight} />
          <ChannelTabs channel={channel} />
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
// Trust weight — S-7.1.1

const WEIGHT_MIN = 0;
const WEIGHT_MAX = 2;
const WEIGHT_STEP = 0.1;

/**
 * This reader's trust weight for the channel, 0.0 to 2.0 (1.0 neutral),
 * stored per tenant (`channel_subscriptions.source_weight`, D-065). The
 * server re-ranks this reader's job and library Q&A as `distance / weight`
 * after the relevance threshold (D-068): a higher weight lets the channel's
 * relevant passages outrank others, a lower one lets them sink, and no
 * weight ever brings in an off-topic passage. Measured (T-7.1.1.5): strong
 * weights narrow answers toward the promoted channels, and near 0 a channel
 * effectively drops out on a broad corpus, so the copy says both.
 * The slider holds a draft; Save sends it, Reset returns to neutral.
 */
function TrustWeightControl({ channelId, weight }: { channelId: string; weight: number }) {
  const c = useColors();
  const setWeight = useSetChannelWeight();
  const [draft, setDraft] = useState(weight);
  useEffect(() => setDraft(weight), [weight]);

  const neutral = Math.abs(draft - 1) < 1e-9;
  const standing = neutral ? 'neutral' : draft > 1 ? 'promoted' : 'demoted';
  const dirty = Math.abs(draft - weight) > 1e-9;
  const save = (value: number) => setWeight.mutate({ id: channelId, weight: value });

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
          {draft.toFixed(1)} · {standing}
        </Badge>
        <input
          type="range"
          min={WEIGHT_MIN}
          max={WEIGHT_MAX}
          step={WEIGHT_STEP}
          value={draft}
          onChange={(e) => setDraft(Number(e.target.value))}
          disabled={setWeight.isPending}
          aria-label="Trust weight for this channel"
          aria-valuetext={`${draft.toFixed(1)}, ${standing}`}
          style={{ flex: '0 1 200px', accentColor: c.accent }}
        />
        <Button size="sm" onClick={() => save(draft)} disabled={!dirty || setWeight.isPending}>
          {setWeight.isPending ? 'Saving…' : 'Save'}
        </Button>
        <Button
          size="sm"
          variant="tertiary"
          onClick={() => {
            setDraft(1);
            save(1);
          }}
          disabled={(neutral && !dirty) || setWeight.isPending}
        >
          Reset
        </Button>
        <span
          style={{
            fontFamily: fonts.body,
            fontSize: fontSize.sm,
            color: c.textMuted,
            lineHeight: lineHeight.snug,
            flex: '1 1 320px',
          }}
        >
          Raising it lets this channel's relevant passages outrank others in your answers, which
          also narrows them toward this channel. Lowering it lets them sink; near 0 they appear
          only when little else matches. It never pulls in an off-topic passage, and only your
          answers change.
          {setWeight.isError && (
            <span role="alert" style={{ color: c.error, marginLeft: space['2'] }}>
              Could not save the weight. Try again.
            </span>
          )}
        </span>
      </div>
    </Card>
  );
}
