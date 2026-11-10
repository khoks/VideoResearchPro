import { useQuery, useQueryClient } from '@tanstack/react-query';
import { channelIntelligenceApi } from '../services/channelIntelligenceApi';
import { quotaApi } from '../services/quotaApi';
import { ERRORS_SHOWN_HERE } from '../services/queryClient';

export const intelligenceKey = (channelId: string) => ['channelIntelligence', channelId] as const;

/** Its one caller, the Intelligence tab, says a failed read in place of the
 * panels (T-3.4.1.26). */
export function useChannelIntelligence(channelId: string) {
  return useQuery({
    queryKey: intelligenceKey(channelId),
    queryFn: () => channelIntelligenceApi.get(channelId),
    staleTime: 60_000,
    meta: ERRORS_SHOWN_HERE,
  });
}

/** Forces a recompute and writes the fresh aggregate into the cache. */
export function useRefreshChannelIntelligence(channelId: string) {
  const qc = useQueryClient();
  return async () => {
    const fresh = await channelIntelligenceApi.get(channelId, true);
    qc.setQueryData(intelligenceKey(channelId), fresh);
    return fresh;
  };
}

export function useQuota() {
  return useQuery({
    queryKey: ['authQuota'],
    queryFn: () => quotaApi.get(),
    staleTime: 30_000,
  });
}
