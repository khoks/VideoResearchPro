import { useState, type CSSProperties, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { LibrarySort, LibraryVideoResponse, ListVideosParams } from '../../services/libraryApi';
import { VideoRow } from './VideoRow';
import { Button, Card, EmptyState, Input, Select, Skeleton } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, radius, space } from '../../theme';

const PAGE_SIZE = 50;

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

export type DocumentsFetchParams = Pick<
  ListVideosParams,
  'search' | 'transcript_status' | 'sort' | 'limit' | 'offset'
>;

interface Props {
  /** Base React Query key; the filter state is appended. */
  queryKey: readonly unknown[];
  /** Fetches one page for the scope the caller owns (a channel, a shelf). */
  fetch: (params: DocumentsFetchParams) => Promise<LibraryVideoResponse[]>;
  heading?: string;
  /** Count shown beside the heading; omit when the scope has no cheap total. */
  total?: number | null;
  /** Passed to each `VideoRow`; the channel page passes `false`. */
  channelLink?: boolean;
  emptyTitle: ReactNode;
  emptyDescription: ReactNode;
  searchPlaceholder?: string;
  style?: CSSProperties;
}

/**
 * A scoped slice of the library with the library's own filters — search,
 * transcript status, sort — and paging. The caller supplies the fetcher so
 * the same browser serves the channel page (S-8.7.1) and the shelf page
 * (S-8.1.2) without duplicating the filter card, states and pager.
 */
export function DocumentsBrowser({
  queryKey,
  fetch,
  heading = 'Documents',
  total,
  channelLink = true,
  emptyTitle,
  emptyDescription,
  searchPlaceholder = 'Search titles…',
  style,
}: Props) {
  const c = useColors();
  const [search, setSearch] = useState('');
  const [transcriptStatus, setTranscriptStatus] = useState('');
  const [sort, setSort] = useState<LibrarySort>('newest');
  const [page, setPage] = useState(0);

  const params: DocumentsFetchParams = {
    search: search.trim() || undefined,
    transcript_status: transcriptStatus || undefined,
    sort,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  };
  const query = useQuery({
    queryKey: [...queryKey, params.search ?? null, params.transcript_status ?? null, sort, page],
    queryFn: () => fetch(params),
    staleTime: 30_000,
  });

  const videos = query.data ?? [];
  const hasNextPage = videos.length === PAGE_SIZE;
  const filtersActive = !!search.trim() || !!transcriptStatus;

  const clearFilters = () => {
    setSearch('');
    setTranscriptStatus('');
    setPage(0);
  };

  let body: ReactNode;
  if (query.isLoading && page === 0) {
    body = (
      <div aria-busy style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        <Skeleton variant="card" height={104} />
        <Skeleton variant="card" height={104} />
        <Skeleton variant="card" height={104} />
      </div>
    );
  } else if (query.isError) {
    body = (
      <EmptyState
        size="sm"
        title="Couldn't load these documents."
        description="Something blocked the library fetch."
        action={
          <Button size="sm" variant="secondary" onClick={() => void query.refetch()}>
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
        description="Loosen the search or the transcript filter to see more."
        action={
          <Button size="sm" variant="tertiary" onClick={clearFilters}>
            Clear filters
          </Button>
        }
      />
    );
  } else if (videos.length === 0) {
    body = <EmptyState size="sm" title={emptyTitle} description={emptyDescription} />;
  } else {
    body = (
      <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        {videos.map((video) => (
          <VideoRow key={video.id} video={video} channelLink={channelLink} />
        ))}
      </div>
    );
  }

  return (
    <section aria-label={heading} style={style}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: space['3'], marginBottom: space['3'] }}>
        <h2
          style={{
            fontFamily: fonts.display,
            fontSize: fontSize.lg,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            margin: 0,
          }}
        >
          {heading}
        </h2>
        {total !== undefined && total !== null && (
          <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>
            {total} on your shelf
          </span>
        )}
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
              placeholder={searchPlaceholder}
              aria-label={searchPlaceholder}
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

export function Pager({
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
