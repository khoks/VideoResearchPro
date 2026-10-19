import api from './api';
import type { Job } from '../types/job';
import type { LibraryVideoResponse, ListVideosParams } from './libraryApi';
import { PALETTE_COLORS, type PaletteColor } from '../theme';

/** A shelf's colour is one of the ten palette NAMES (never a hex). */
export type ShelfColor = PaletteColor;
export const SHELF_COLORS: readonly ShelfColor[] = PALETTE_COLORS;

/** `ShelfResponse` — a named, per-tenant collection of jobs (E-8.1). */
export interface Shelf {
  id: string;
  name: string;
  description: string | null;
  color: ShelfColor;
  job_count: number;
  /** The shelf's job ids, most recently added first. */
  job_ids: string[];
  created_at: string;
  updated_at: string;
}

/** `ShelfDetailResponse` — the shelf plus its jobs, most recently added first. */
export interface ShelfDetail extends Shelf {
  jobs: Job[];
}

export interface ShelfCreate {
  name: string;
  description?: string | null;
  color?: ShelfColor;
}

/** Fields left out are untouched; `description: null` clears it. */
export interface ShelfUpdate {
  name?: string;
  description?: string | null;
  color?: ShelfColor;
}

/** The library listing params minus `channel_id` (a shelf spans channels). */
export type ShelfDocumentsParams = Omit<ListVideosParams, 'channel_id'>;

export const shelvesApi = {
  list: () => api.get<Shelf[]>('/shelves').then(r => r.data),
  get: (id: string) => api.get<ShelfDetail>(`/shelves/${id}`).then(r => r.data),
  create: (body: ShelfCreate) => api.post<Shelf>('/shelves', body).then(r => r.data),
  update: (id: string, body: ShelfUpdate) =>
    api.put<Shelf>(`/shelves/${id}`, body).then(r => r.data),
  remove: (id: string) => api.delete(`/shelves/${id}`).then(() => undefined),
  addJob: (id: string, jobId: string) =>
    api.post<Shelf>(`/shelves/${id}/jobs/${jobId}`).then(r => r.data),
  removeJob: (id: string, jobId: string) =>
    api.delete(`/shelves/${id}/jobs/${jobId}`).then(() => undefined),
  documents: (id: string, params?: ShelfDocumentsParams) =>
    api.get<LibraryVideoResponse[]>(`/shelves/${id}/documents`, { params }).then(r => r.data),
};
