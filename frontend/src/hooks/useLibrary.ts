import { useQuery } from '@tanstack/react-query';
import { libraryApi, type ListVideosParams } from '../services/libraryApi';
import { queryErrorsMeta, type QueryLineOptions } from '../services/queryClient';

/** The library's sources tab says a failed load while it is on screen; the
 * library Q&A page's one-row probe says nothing, so only the tab passes
 * `inlineErrors` (T-3.4.1.26). */
export function useLibraryVideos(params?: ListVideosParams, { inlineErrors }: QueryLineOptions = {}) {
  return useQuery({
    queryKey: [
      'libraryVideos',
      params?.search ?? null,
      params?.language ?? null,
      params?.channel_id ?? null,
      params?.transcript_status ?? null,
      params?.tag ?? null,
      params?.document_id ?? null,
      params?.sort ?? null,
      params?.limit ?? null,
      params?.offset ?? null,
    ],
    queryFn: () => libraryApi.listVideos(params),
    staleTime: 30_000,
    meta: queryErrorsMeta(inlineErrors),
  });
}
