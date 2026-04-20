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
  });
}

function patchChannelInList(queryClient: ReturnType<typeof useQueryClient>, updated: Channel) {
  queryClient.setQueryData<Channel[]>(['channels'], (prev) => {
    if (!prev) return prev;
    return prev.map(c => (c.id === updated.id ? updated : c));
  });
  queryClient.setQueryData(['channel', updated.id], updated);
}

export function useSubscribeChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => channelsApi.subscribe(id),
    onSuccess: (updated) => patchChannelInList(queryClient, updated),
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
      queryClient.invalidateQueries({ queryKey: ['channels'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}
