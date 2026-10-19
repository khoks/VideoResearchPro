import api from './api';
import type { PaletteColor } from '../theme';

/** What a library row carries for each of the caller's tags on it. */
export interface TagSummary {
  id: string;
  name: string;
  /** A label-palette name; the API never sends a hex. */
  color: PaletteColor;
}

/** `TagResponse` — one of the caller's tags (S-8.1.3). Per tenant: another
 * reader's tags on a shared document never appear. */
export interface Tag extends TagSummary {
  /** Documents carrying the tag that the caller can still see. */
  document_count: number;
  created_at: string;
}

export interface TagCreate {
  name: string;
  color?: PaletteColor;
}

export interface TagUpdate {
  name?: string;
  color?: PaletteColor;
}

export const tagsApi = {
  list: () => api.get<Tag[]>('/tags').then(r => r.data),
  create: (body: TagCreate) => api.post<Tag>('/tags', body).then(r => r.data),
  update: (id: string, body: TagUpdate) => api.put<Tag>(`/tags/${id}`, body).then(r => r.data),
  /** Delete; with `into`, merge this tag into that one instead. */
  remove: (id: string, into?: string) =>
    api.delete(`/tags/${id}`, { params: into ? { into } : undefined }).then(() => undefined),
  /** Tag a document (idempotent). Returns the caller's tags now on it. */
  apply: (documentId: string, tagId: string) =>
    api.put<TagSummary[]>(`/library/videos/${documentId}/tags/${tagId}`).then(r => r.data),
  unapply: (documentId: string, tagId: string) =>
    api.delete(`/library/videos/${documentId}/tags/${tagId}`).then(() => undefined),
};
