import { useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  notesApi,
  type ListNotesParams,
  type Note,
  type NoteCreatePayload,
  type NoteListResponse,
  type NoteTargetType,
  type NoteUpdatePayload,
} from '../services/notesApi';

const NOTES_KEY = ['notes'] as const;

// Inline surfaces (library shelf, job video list, answer cards) fetch the
// tenant's notes ONCE per target type per page and let each row select its
// own slice, rather than one request per row. Notes are few and small; the
// cap is the server's maximum page.
const BY_TYPE_LIMIT = 2000;

export function useNotesByType(targetType: NoteTargetType, enabled = true) {
  return useQuery({
    queryKey: [...NOTES_KEY, 'type', targetType],
    queryFn: () => notesApi.list({ target_type: targetType, limit: BY_TYPE_LIMIT }),
    staleTime: 30_000,
    enabled,
  });
}

/**
 * Notes on one target, selected from the per-type query. `ids` is every id
 * the caller has for the target (a document's `document_id` and legacy
 * `video_id`); a note matches on its canonical `target_id` or, for
 * document-backed targets, on `target_video_id`.
 */
export function useNotesForTarget(targetType: NoteTargetType, ids: Array<string | null | undefined>) {
  const wanted = ids.filter((x): x is string => !!x);
  const key = wanted.join('\u0000');
  const select = useCallback(
    (data: NoteListResponse): Note[] => {
      const set = new Set(key ? key.split('\u0000') : []);
      return data.items.filter(
        (n) => set.has(n.target_id) || (!!n.target_video_id && set.has(n.target_video_id)),
      );
    },
    [key],
  );
  return useQuery({
    queryKey: [...NOTES_KEY, 'type', targetType],
    queryFn: () => notesApi.list({ target_type: targetType, limit: BY_TYPE_LIMIT }),
    staleTime: 30_000,
    enabled: wanted.length > 0,
    select,
  });
}

/** The notes page: filtered, paged, newest first. */
export function useNotesList(params: ListNotesParams, enabled = true) {
  return useQuery({
    queryKey: [
      ...NOTES_KEY,
      'list',
      params.target ?? null,
      params.target_type ?? null,
      params.q ?? '',
      params.include_deleted ?? false,
      params.limit ?? null,
      params.offset ?? 0,
    ],
    queryFn: () => notesApi.list(params),
    staleTime: 15_000,
    enabled,
  });
}

function useInvalidateNotes() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: NOTES_KEY });
}

export function useCreateNote() {
  const invalidate = useInvalidateNotes();
  return useMutation({
    mutationFn: (payload: NoteCreatePayload) => notesApi.create(payload),
    onSuccess: invalidate,
  });
}

export function useUpdateNote() {
  const invalidate = useInvalidateNotes();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: NoteUpdatePayload }) =>
      notesApi.update(id, payload),
    onSuccess: invalidate,
  });
}

export function useDeleteNote() {
  const invalidate = useInvalidateNotes();
  return useMutation({
    mutationFn: (id: string) => notesApi.remove(id),
    onSuccess: invalidate,
  });
}
