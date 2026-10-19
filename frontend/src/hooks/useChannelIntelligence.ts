import { useQuery, useQueryClient } from '@tanstack/react-query';
import { channelIntelligenceApi } from '../services/channelIntelligenceApi';
import { quotaApi } from '../services/quotaApi';

export const intelligenceKey = (channelId: string) => ['channelIntelligence', channelId] as const;

export function useChannelIntelligence(channelId: string) {
  return useQuery({
    queryKey: intelligenceKey(channelId),
    queryFn: () => channelIntelligenceApi.get(channelId),
    staleTime: 60_000,
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
