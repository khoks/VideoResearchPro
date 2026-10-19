import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  shelvesApi,
  type ShelfCreate,
  type ShelfDocumentsParams,
  type ShelfUpdate,
} from '../services/shelvesApi';

export const shelvesKeys = {
  all: ['shelves'] as const,
  detail: (id: string | null) => ['shelf', id] as const,
  forJob: (jobId: string | null) => ['jobShelves', jobId] as const,
  documents: (id: string | null) => ['shelfDocuments', id] as const,
};

export function useShelves() {
  return useQuery({
    queryKey: shelvesKeys.all,
    queryFn: () => shelvesApi.list(),
    staleTime: 30_000,
  });
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

export function useJobShelves(jobId: string | null) {
  return useQuery({
    queryKey: shelvesKeys.forJob(jobId),
    queryFn: () => shelvesApi.forJob(jobId!),
    enabled: !!jobId,
    staleTime: 30_000,
  });
}

export function useShelfDocuments(id: string | null, params?: ShelfDocumentsParams) {
  return useQuery({
    queryKey: [
      ...shelvesKeys.documents(id),
      params?.search ?? null,
      params?.language ?? null,
      params?.transcript_status ?? null,
      params?.sort ?? null,
      params?.limit ?? null,
      params?.offset ?? null,
    ],
    queryFn: () => shelvesApi.documents(id!, params),
    enabled: !!id,
    staleTime: 30_000,
  });
}

type QC = ReturnType<typeof useQueryClient>;

function touchShelf(qc: QC, shelfId: string, jobId?: string) {
  void qc.invalidateQueries({ queryKey: shelvesKeys.all });
  void qc.invalidateQueries({ queryKey: shelvesKeys.detail(shelfId) });
  void qc.invalidateQueries({ queryKey: shelvesKeys.documents(shelfId) });
  if (jobId) void qc.invalidateQueries({ queryKey: shelvesKeys.forJob(jobId) });
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
    onSuccess: (_updated, { id }) => {
      touchShelf(qc, id);
      // Chips on job pages show the name and colour; refresh them too.
      void qc.invalidateQueries({ queryKey: ['jobShelves'] });
    },
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
      void qc.invalidateQueries({ queryKey: ['jobShelves'] });
    },
  });
}

export function useAddJobToShelf() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ shelfId, jobId }: { shelfId: string; jobId: string }) =>
      shelvesApi.addJob(shelfId, jobId),
    onSuccess: (_shelf, { shelfId, jobId }) => touchShelf(qc, shelfId, jobId),
  });
}

export function useRemoveJobFromShelf() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ shelfId, jobId }: { shelfId: string; jobId: string }) =>
      shelvesApi.removeJob(shelfId, jobId),
    onSuccess: (_void, { shelfId, jobId }) => touchShelf(qc, shelfId, jobId),
  });
}
