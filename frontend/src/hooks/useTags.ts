import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { tagsApi, type TagCreate, type TagUpdate } from '../services/tagsApi';

export const tagsKey = ['tags'] as const;

export function useTags() {
  return useQuery({
    queryKey: tagsKey,
    queryFn: () => tagsApi.list(),
    staleTime: 30_000,
  });
}

type QC = ReturnType<typeof useQueryClient>;

/** Rows carry their tags, so every list of rows refreshes after a change:
 * the library, a channel's documents (keyed under `libraryVideos`) and a
 * shelf's documents. */
function refreshRows(qc: QC) {
  void qc.invalidateQueries({ queryKey: tagsKey });
  void qc.invalidateQueries({ queryKey: ['libraryVideos'] });
  void qc.invalidateQueries({ queryKey: ['shelfDocuments'] });
}

export function useCreateTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TagCreate) => tagsApi.create(body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: tagsKey }),
  });
}

export function useUpdateTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: TagUpdate }) => tagsApi.update(id, body),
    onSuccess: () => refreshRows(qc),
  });
}

export function useDeleteTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, into }: { id: string; into?: string }) => tagsApi.remove(id, into),
    onSuccess: () => refreshRows(qc),
  });
}

export function useApplyTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ documentId, tagId }: { documentId: string; tagId: string }) =>
      tagsApi.apply(documentId, tagId),
    onSuccess: () => refreshRows(qc),
  });
}

export function useUnapplyTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ documentId, tagId }: { documentId: string; tagId: string }) =>
      tagsApi.unapply(documentId, tagId),
    onSuccess: () => refreshRows(qc),
  });
}
