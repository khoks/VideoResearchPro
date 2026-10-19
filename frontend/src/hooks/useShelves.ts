import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  shelvesApi,
  type Shelf,
  type ShelfCreate,
  type ShelfDocumentsParams,
  type ShelfUpdate,
} from '../services/shelvesApi';

export const shelvesKeys = {
  all: ['shelves'] as const,
  detail: (id: string | null) => ['shelf', id] as const,
  documents: (id: string | null) => ['shelfDocuments', id] as const,
};

/**
 * The caller's shelves with their `job_ids`. The sidebar, every "Add to
 * shelf" picker and every chip row read this one cached list, so a page of
 * twenty job cards costs one request, not twenty.
 */
export function useShelves() {
  return useQuery({
    queryKey: shelvesKeys.all,
    queryFn: () => shelvesApi.list(),
    staleTime: 30_000,
  });
}

/** Shelves a run sits on, derived from the cached listing. */
export function useJobShelves(jobId: string): { shelves: Shelf[]; isLoading: boolean } {
  const { data, isLoading } = useShelves();
  const shelves = useMemo(
    () => (data ?? []).filter((s) => s.job_ids.includes(jobId)),
    [data, jobId],
  );
  return { shelves, isLoading };
}

export function useShelf(id: string | null) {
  return useQuery({
    queryKey: shelvesKeys.detail(id),
    queryFn: () => shelvesApi.get(id!),
    enabled: !!id,
    // A 404 is the answer (not yours, or gone), not a transient failure.
    retry: false,
  });
}

export function useShelfDocumentsFetcher(id: string) {
  return (params: ShelfDocumentsParams) => shelvesApi.documents(id, params);
}

type QC = ReturnType<typeof useQueryClient>;

function touchShelf(qc: QC, shelfId: string) {
  void qc.invalidateQueries({ queryKey: shelvesKeys.all });
  void qc.invalidateQueries({ queryKey: shelvesKeys.detail(shelfId) });
  void qc.invalidateQueries({ queryKey: shelvesKeys.documents(shelfId) });
}

export function useCreateShelf() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ShelfCreate) => shelvesApi.create(body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: shelvesKeys.all }),
  });
}

export function useUpdateShelf() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ShelfUpdate }) => shelvesApi.update(id, body),
    onSuccess: (_updated, { id }) => touchShelf(qc, id),
  });
}

export function useDeleteShelf() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => shelvesApi.remove(id),
    onSuccess: (_void, id) => {
      qc.removeQueries({ queryKey: shelvesKeys.detail(id) });
      qc.removeQueries({ queryKey: shelvesKeys.documents(id) });
      void qc.invalidateQueries({ queryKey: shelvesKeys.all });
    },
  });
}

export function useAddJobToShelf() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ shelfId, jobId }: { shelfId: string; jobId: string }) =>
      shelvesApi.addJob(shelfId, jobId),
    onSuccess: (_shelf, { shelfId }) => touchShelf(qc, shelfId),
  });
}

export function useRemoveJobFromShelf() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ shelfId, jobId }: { shelfId: string; jobId: string }) =>
      shelvesApi.removeJob(shelfId, jobId),
    onSuccess: (_void, { shelfId }) => touchShelf(qc, shelfId),
  });
}
