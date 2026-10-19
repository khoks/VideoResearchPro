import api from './api';

// Mirrors backend/app/routers/notes.py and backend/app/schemas/note.py
// (M5 / S-8.5.1). Notes are the user's own words on something they can see.

export type NoteTargetType =
  | 'document'
  | 'job'
  | 'qa_exchange'
  | 'library_qa_exchange'
  | 'qa_history_exchange'
  | 'channel'
  | 'knowledge_artifact';

export const NOTE_TARGET_TYPES: NoteTargetType[] = [
  'document',
  'job',
  'qa_exchange',
  'library_qa_exchange',
  'qa_history_exchange',
  'channel',
  'knowledge_artifact',
];

export type NoteMotivation = 'commenting' | 'highlighting' | 'tagging';

/** W3C Web Annotation `TextQuoteSelector` plus a media-time anchor. */
export interface NoteSelector {
  type?: 'TextQuoteSelector';
  exact: string;
  prefix?: string | null;
  suffix?: string | null;
  start_seconds?: number | null;
}

export interface Note {
  id: string;
  target_type: NoteTargetType;
  /** Canonical id: `document_id` for documents and knowledge artifacts. */
  target_id: string;
  body_md: string;
  motivation: NoteMotivation;
  selector: NoteSelector | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  /** Title of the target; null once the target is gone (a deleted job). */
  target_label: string | null;
  /** Documents and knowledge artifacts only: the legacy YouTube id, so a
   * surface still keyed on `video_id` can find notes stored under the
   * canonical `document_id`. */
  target_video_id: string | null;
  /** `qa_exchange` only: the job that holds the exchange. */
  target_parent_id?: string | null;
}

export interface NoteListResponse {
  items: Note[];
  total: number;
  limit: number;
  offset: number;
}

export interface NoteCreatePayload {
  target_type: NoteTargetType;
  /** Any id the server accepts for the type; documents take either id form. */
  target_id: string;
  body_md: string;
  motivation?: NoteMotivation;
  selector?: NoteSelector | null;
}

export interface NoteUpdatePayload {
  body_md?: string;
  motivation?: NoteMotivation;
  /** `null` clears the selector; omit to leave it. */
  selector?: NoteSelector | null;
}

export interface ListNotesParams {
  /** `<target_type>:<id>` — scope to one target. 404 when not visible. */
  target?: string;
  target_type?: NoteTargetType;
  q?: string;
  include_deleted?: boolean;
  limit?: number;
  offset?: number;
}

export const NOTE_BODY_MAX_CHARS = 20_000;

export const notesApi = {
  list: (params?: ListNotesParams) =>
    api.get<NoteListResponse>('/notes', { params }).then((r) => r.data),

  get: (id: string) => api.get<Note>(`/notes/${encodeURIComponent(id)}`).then((r) => r.data),

  create: (payload: NoteCreatePayload) => api.post<Note>('/notes', payload).then((r) => r.data),

  update: (id: string, payload: NoteUpdatePayload) =>
    api.put<Note>(`/notes/${encodeURIComponent(id)}`, payload).then((r) => r.data),

  remove: (id: string) =>
    api
      .delete<{ deleted: boolean; deleted_at: string }>(`/notes/${encodeURIComponent(id)}`)
      .then((r) => r.data),
};

/**
 * Where a note's target lives in the app, for the notes page. Sources have
 * no page of their own yet, so document and knowledge-report notes point
 * at the shelf; a Q&A answer points at its job page.
 */
export function noteTargetHref(
  note: Pick<Note, 'target_type' | 'target_id' | 'target_parent_id'>,
): string | null {
  switch (note.target_type) {
    case 'job':
      return `/jobs/${note.target_id}`;
    case 'qa_exchange':
      return note.target_parent_id ? `/jobs/${note.target_parent_id}` : null;
    case 'library_qa_exchange':
      return '/library/qa';
    case 'qa_history_exchange':
      return `/qa-history#exchange-${note.target_id}`;
    case 'channel':
      return `/library/channels/${encodeURIComponent(note.target_id)}`;
    case 'document':
    case 'knowledge_artifact':
      return '/library';
    default:
      return null;
  }
}

/** Human label for a target type, used by the notes page and the inline lists. */
export function noteTargetTypeLabel(type: NoteTargetType): string {
  switch (type) {
    case 'document':
      return 'Source';
    case 'job':
      return 'Research run';
    case 'qa_exchange':
      return 'Q&A answer';
    case 'library_qa_exchange':
      return 'Library Q&A answer';
    case 'qa_history_exchange':
      return 'Q&A history answer';
    case 'channel':
      return 'Channel';
    case 'knowledge_artifact':
      return 'Knowledge report';
    default:
      return type;
  }
}
