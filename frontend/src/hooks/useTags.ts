import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ERRORS_SHOWN_HERE } from '../services/queryClient';
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

// The tag control on a source, the one caller of the next three, says a failure
// in its picker, so the global toast stands aside (T-3.4.1.22).
export function useCreateTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TagCreate) => tagsApi.create(body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: tagsKey }),
    meta: ERRORS_SHOWN_HERE,
  });
}

// The tags manager, the one caller of the next two, says a failure on the tag's
// own row, so the global toast stands aside (T-3.4.1.18). It stays open while
// one is in flight (`useIsMutating` on this key): closed, the row and its line
// would be gone, and the failure said nowhere.
export const tagEditsKey = ['tags', 'edits'] as const;

export function useUpdateTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationKey: tagEditsKey,
    mutationFn: ({ id, body }: { id: string; body: TagUpdate }) => tagsApi.update(id, body),
    onSuccess: () => refreshRows(qc),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useDeleteTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationKey: tagEditsKey,
    mutationFn: ({ id, into }: { id: string; into?: string }) => tagsApi.remove(id, into),
    onSuccess: () => refreshRows(qc),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useApplyTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ documentId, tagId }: { documentId: string; tagId: string }) =>
      tagsApi.apply(documentId, tagId),
    onSuccess: () => refreshRows(qc),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useUnapplyTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ documentId, tagId }: { documentId: string; tagId: string }) =>
      tagsApi.unapply(documentId, tagId),
    onSuccess: () => refreshRows(qc),
    meta: ERRORS_SHOWN_HERE,
  });
}
