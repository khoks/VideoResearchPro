import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  savedSearchesApi,
  type SavedSearchCreate,
  type SavedSearchUpdate,
} from '../services/savedSearchesApi';
import { useTierCapabilities } from './useTierCapabilities';

export const savedSearchesKey = ['savedSearches'] as const;

/** The reader's saved searches (S-8.3.2). Off for tiers without the feature. */
export function useSavedSearches() {
  const { has } = useTierCapabilities();
  return useQuery({
    queryKey: savedSearchesKey,
    queryFn: () => savedSearchesApi.list(),
    enabled: has('saved_searches'),
    staleTime: 15_000,
    // A queued "Run now" lands in a few seconds; poll gently while any row
    // has never run so its first result appears without a reload.
    refetchInterval: (q) => (q.state.data?.items.some((s) => s.enabled && !s.last_run_at) ? 10_000 : false),
  });
}

function useInvalidate() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: savedSearchesKey });
}

export function useCreateSavedSearch() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (body: SavedSearchCreate) => savedSearchesApi.create(body), onSuccess: invalidate });
}

export function useUpdateSavedSearch() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: SavedSearchUpdate }) => savedSearchesApi.update(id, body),
    onSuccess: invalidate,
  });
}

export function useDeleteSavedSearch() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (id: string) => savedSearchesApi.remove(id), onSuccess: invalidate });
}

export function useRunSavedSearchNow() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (id: string) => savedSearchesApi.runNow(id), onSuccess: invalidate });
}
