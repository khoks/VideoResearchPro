import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { channelsApi, type Channel } from '../services/channelsApi';
import { ERRORS_SHOWN_HERE, queryErrorsMeta, type QueryLineOptions } from '../services/queryClient';

/** The library's channels tab says a failed load, and only while it is the
 * tab on screen, so it passes `inlineErrors` (T-3.4.1.26). */
export function useChannels({ inlineErrors }: QueryLineOptions = {}) {
  return useQuery({
    queryKey: ['channels'],
    queryFn: () => channelsApi.list(),
    staleTime: 30_000,
    meta: queryErrorsMeta(inlineErrors),
  });
}

/** The channel page says a failed load; the graph explorer reads the name
 * alone and says nothing, so only the page passes `inlineErrors`. */
export function useChannel(id: string | null, { inlineErrors }: QueryLineOptions = {}) {
  return useQuery({
    queryKey: ['channel', id],
    queryFn: () => channelsApi.get(id!),
    enabled: !!id,
    // A 404 is the answer ("not on your shelf"), not a transient failure.
    retry: false,
    meta: queryErrorsMeta(inlineErrors),
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
 * patched. Callers that want to watch the sync use `data.job_id`; when it is
 * null no sync started, and they show `data.sync_note`.
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
    // Both callers, the channel page and the library's channel list, say a
    // failure under the buttons (T-3.4.1.22).
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useUnsubscribeChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => channelsApi.unsubscribe(id),
    onSuccess: (updated) => patchChannelInList(queryClient, updated),
  });
}

/** S-7.1.1: the server echoes the updated channel, so caches are patched in place. */
export function useSetChannelWeight() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, weight }: { id: string; weight: number }) => channelsApi.setWeight(id, weight),
    onSuccess: (updated) => patchChannelInList(queryClient, updated),
    // Its one caller, the channel page's trust weight, says a failure beside it
    // (T-3.4.1.22).
    meta: ERRORS_SHOWN_HERE,
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
    // As subscribe: both callers say a failure under the buttons.
    meta: ERRORS_SHOWN_HERE,
  });
}
