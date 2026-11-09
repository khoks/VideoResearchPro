import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ERRORS_SHOWN_HERE } from '../services/queryClient';
import { rememberCutOff } from '../stores/qaCutOffStore';
import type { LibraryQARequest } from '../types/qa';
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
  questions: (id: string | null) => ['shelfQuestions', id] as const,
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
    // Both callers say a failure where it was asked: the new-shelf form, and the
    // "Add to shelf" picker's "New shelf…" field (T-3.4.1.22).
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useUpdateShelf() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ShelfUpdate }) => shelvesApi.update(id, body),
    onSuccess: (_updated, { id }) => touchShelf(qc, id),
    // Its callers, both through the shelf form, say a failure in the form.
    meta: ERRORS_SHOWN_HERE,
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
    // Its one caller, the delete modal, says a failure in the modal (T-3.4.1.18).
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useAddJobToShelf() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ shelfId, jobId }: { shelfId: string; jobId: string }) =>
      shelvesApi.addJob(shelfId, jobId),
    onSuccess: (_shelf, { shelfId }) => touchShelf(qc, shelfId),
    // Its one caller, the "Add to shelf" picker, says a failure in the picker.
    meta: ERRORS_SHOWN_HERE,
  });
}

/**
 * `inlineErrors`: the caller says every failure on the page, so the global toast
 * stands aside (T-3.4.1.22, D-153 point 2). The "Add to shelf" picker passes it;
 * a shelf page's own Remove shows no line and leaves it off.
 */
export function useRemoveJobFromShelf({ inlineErrors = false }: { inlineErrors?: boolean } = {}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ shelfId, jobId }: { shelfId: string; jobId: string }) =>
      shelvesApi.removeJob(shelfId, jobId),
    onSuccess: (_void, { shelfId }) => touchShelf(qc, shelfId),
    meta: inlineErrors ? ERRORS_SHOWN_HERE : undefined,
  });
}

/** Whether the shelf holds any source the caller can see (one-row probe).
 * Keyed under the shelf's documents, so adding or removing a run refreshes it. */
export function useShelfHasSources(id: string) {
  return useQuery({
    queryKey: [...shelvesKeys.documents(id), 'probe'] as const,
    queryFn: () => shelvesApi.documents(id, { limit: 1 }),
    select: (rows) => rows.length > 0,
    staleTime: 30_000,
  });
}

/** S-8.1.4: questions asked on this shelf. */
export function useShelfQuestions(id: string) {
  return useQuery({
    queryKey: shelvesKeys.questions(id),
    queryFn: () => shelvesApi.questions(id),
  });
}

/** Ask over the shelf; the answer also joins the library Q&A history. */
export function useAskShelf(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: LibraryQARequest) => shelvesApi.ask(id, body),
    onSuccess: (exchange, body) => {
      rememberCutOff(exchange, body);
      void qc.invalidateQueries({ queryKey: shelvesKeys.questions(id) });
      void qc.invalidateQueries({ queryKey: ['libraryQaHistory'] });
    },
  });
}
