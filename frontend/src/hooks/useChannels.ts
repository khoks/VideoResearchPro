import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { channelsApi, type Channel } from '../services/channelsApi';

export function useChannels() {
  return useQuery({
    queryKey: ['channels'],
    queryFn: () => channelsApi.list(),
    staleTime: 30_000,
  });
}

export function useChannel(id: string | null) {
  return useQuery({
    queryKey: ['channel', id],
    queryFn: () => channelsApi.get(id!),
    enabled: !!id,
    // A 404 is the answer ("not on your shelf"), not a transient failure.
    retry: false,
  });
}

function patchChannelInList(queryClient: ReturnType<typeof useQueryClient>, updated: Channel) {
  queryClient.setQueryData<Channel[]>(['channels'], (prev) => {
    if (!prev) return prev;
    return prev.map(c => (c.channel_id === updated.channel_id ? updated : c));
  });
  queryClient.setQueryData(['channel', updated.channel_id], updated);
}

/**
 * Subscribe returns a `SubscribeResponse` (channel_id + the sync job it
 * dispatched), not the channel, so the caches are invalidated rather than
 * patched. Callers that want to watch the sync use `data.job_id`.
 */
export function useSubscribeChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => channelsApi.subscribe(id),
    onSuccess: (_resp, id) => {
      void queryClient.invalidateQueries({ queryKey: ['channels'] });
      void queryClient.invalidateQueries({ queryKey: ['channel', id] });
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}

export function useUnsubscribeChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => channelsApi.unsubscribe(id),
    onSuccess: (updated) => patchChannelInList(queryClient, updated),
  });
}

export function useSyncChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => channelsApi.sync(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['channels'] });
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}
