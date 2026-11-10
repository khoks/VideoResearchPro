import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { graphApi, type GraphParams } from '../services/graphApi';
import { LOAD_ERRORS_SHOWN_HERE } from '../services/queryClient';

export const libraryGraphKey = (p: GraphParams) =>
  [
    'libraryGraph',
    p.focus ?? null,
    p.focus ? (p.depth ?? 1) : null,
    p.shelfId ?? null,
    p.channelId ?? null,
    p.jobId ?? null,
    p.types ? [...p.types].sort().join(',') : 'all',
    p.limit ?? null,
  ] as const;

/** The reader's library as nodes and edges (S-8.9.1). Keeps the previous
 * graph on screen while a filter change loads, so the map does not blank. Its
 * one caller, the explorer, says a failed load in place of the map, and keeps
 * a map already drawn when a refresh fails, so that failure keeps its toast
 * (T-3.4.1.26). */
export function useLibraryGraph(params: GraphParams, enabled = true) {
  return useQuery({
    queryKey: libraryGraphKey(params),
    queryFn: () => graphApi.get(params),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
    enabled,
    meta: LOAD_ERRORS_SHOWN_HERE,
  });
}
