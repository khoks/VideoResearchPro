import type { AxiosProgressEvent } from 'axios';
import api from './api';

export type TranscriptStatus = 'fetched' | 'pending' | 'unavailable';

export type LibrarySort = 'newest' | 'oldest' | 'longest' | 'shortest';

export interface LibraryVideoResponse {
  /** `documents.document_id` — the primary key every source type has (D-070). */
  id: string;
  /** Legacy YouTube id; null for PDFs, pasted pages and every other non-video source. */
  video_id: string | null;
  title: string;
  /** Null for sources that have no channel (PDFs, pasted pages). */
  channel_id: string | null;
  /** Empty string when there is no channel. */
  channel_name: string;
  url: string;
  thumbnail_url: string | null;
  /** Null for text sources; the backend column is nullable. */
  duration_seconds: number | null;
  published_at: string | null;
  /** Sent by the backend since D-070; the row still falls back to sniffing `url` for older responses. */
  source_type?: string;
  transcript_status: TranscriptStatus | string;
  transcript_language: string | null;
  transcript_word_count: number | null;
  job_count: number;
  job_titles: string[];
}

export interface ListVideosParams {
  search?: string;
  language?: string;
  channel_id?: string;
  transcript_status?: string;
  sort?: LibrarySort;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------------------
// Ingest: PDF upload (E-1.8) + paste URLs (S-1.5.8)
// ---------------------------------------------------------------------------

/** `POST /library/upload-pdf` response. `deduped=true` means the same bytes
 * were already on the shelf; the existing document is returned instead. */
export interface UploadPdfResponse {
  document_id: string;
  /** `pdf:<digest>` — the digest is what `GET /library/pdf/{digest}.pdf` serves. */
  source_id: string;
  page_count: number | null;
  word_count: number | null;
  deduped: boolean;
}

export type PasteUrlStatus = 'created' | 'deduped' | 'extraction_failed' | 'invalid_url';

/** One row of the `POST /library/paste-urls` response. Fields other than
 * `url` and `status` are only present for some statuses — see
 * `utils/ingestResults.ts` for the per-status contract. */
export interface PasteUrlResult {
  url: string;
  status: PasteUrlStatus;
  document_id?: string;
  source_id?: string;
  source_type?: string;
  word_count?: number | null;
  deduped?: boolean;
}

export interface PasteUrlsResponse {
  results: PasteUrlResult[];
}

/** Server-side cap on one paste batch (router raises 400 above it). */
export const PASTE_URLS_MAX = 100;

const PDF_SOURCE_ID_PREFIX = 'pdf:';

/** Build the path the backend serves an uploaded PDF from, given its
 * `source_id` (`pdf:<digest>`). Relative to the API base URL. */
export function pdfServePath(sourceId: string): string {
  const digest = sourceId.startsWith(PDF_SOURCE_ID_PREFIX)
    ? sourceId.slice(PDF_SOURCE_ID_PREFIX.length)
    : sourceId;
  return `/library/pdf/${digest}.pdf`;
}

const API_PREFIX = '/api/v1';

/** Best-effort source type for a library row until the backend sends one. */
export function inferSourceType(row: Pick<LibraryVideoResponse, 'source_type' | 'url'>): string {
  if (row.source_type) return row.source_type;
  if (/\/library\/pdf\/[^/]+\.pdf$/i.test(row.url)) return 'pdf';
  if (/youtube\.com|youtu\.be/i.test(row.url)) return 'video';
  return 'article';
}

export const libraryApi = {
  // TODO: if backend adds a paginated wrapper ({items,total,...}), adjust the return type.
  listVideos: (params?: ListVideosParams) =>
    api.get<LibraryVideoResponse[]>('/library/videos', { params }).then(r => r.data),

  /**
   * Open an uploaded PDF in a new tab. The serve route sits behind the
   * router-level auth dependency, so a plain link 401s; fetch the bytes
   * with the bearer header and hand the browser a blob URL instead.
   * `url` is the document's stored URL (`/api/v1/library/pdf/<digest>.pdf`).
   */
  openPdf: async (url: string) => {
    const path = url.startsWith(API_PREFIX) ? url.slice(API_PREFIX.length) : url;
    const { data } = await api.get<Blob>(path, { responseType: 'blob' });
    const blobUrl = URL.createObjectURL(data);
    window.open(blobUrl, '_blank', 'noopener');
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
  },

  /**
   * Upload one PDF. The axios instance defaults to `application/json`, and
   * axios 1.x would serialise a FormData body to JSON under that header —
   * so the multipart content type is set explicitly here; the browser
   * then fills in the boundary.
   */
  uploadPdf: (file: File, onProgress?: (fraction: number) => void) => {
    const form = new FormData();
    form.append('file', file, file.name);
    return api
      .post<UploadPdfResponse>('/library/upload-pdf', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (evt: AxiosProgressEvent) => {
          if (!onProgress) return;
          const total = evt.total ?? file.size;
          if (total > 0) onProgress(Math.min(1, evt.loaded / total));
        },
      })
      .then(r => r.data);
  },

  pasteUrls: (urls: string[]) =>
    api.post<PasteUrlsResponse>('/library/paste-urls', { urls }).then(r => r.data),
};
