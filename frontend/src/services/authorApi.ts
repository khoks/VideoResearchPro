import api from './api';

// Mirrors backend/app/routers/author.py (I-6 foundation, PR #173).

export type OutputStatus = 'pending' | 'generating' | 'completed' | 'failed' | 'cancelled';

export interface OutputItem {
  id: string;
  kind: string;
  title: string;
  status: OutputStatus | string;
  /** For `book`, these are job IDs: one chapter per job. */
  source_ids: string[];
  parameters: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  has_content: boolean;
  /** Words in the generated text; null until there is content (S-6.1.1). */
  word_count?: number | null;
  /** S-6.7.1: what the worker last reported. A `pending` row with no task id
   * predates S-6.7.1 and was never queued. */
  progress_pct?: number;
  progress_message?: string | null;
  celery_task_id?: string | null;
  /** S-6.7.2: formats `download` can serve, text first (`md` for books). */
  formats?: string[];
}

/** `available` = kinds with a concrete outputter; `supported` = every kind
 * the schema accepts. A kind in `supported` but not `available` returns
 * 501 on create. */
export interface KindsResponse {
  available: string[];
  supported: string[];
}

export interface CreateOutputPayload {
  kind: string;
  title: string;
  source_ids: string[];
  parameters?: Record<string, unknown>;
}

export interface ListOutputsParams {
  kind?: string;
  status?: string;
}

export const authorApi = {
  listKinds: () => api.get<KindsResponse>('/author/kinds').then(r => r.data),

  listOutputs: (params?: ListOutputsParams) =>
    api.get<OutputItem[]>('/author/outputs', { params }).then(r => r.data),

  getOutput: (id: string) => api.get<OutputItem>(`/author/outputs/${id}`).then(r => r.data),

  /** Plain text (text/markdown for books). `transformResponse` is pinned to
   * identity so a manuscript that happens to parse as JSON is not parsed. */
  getContent: (id: string) =>
    api
      .get<string>(`/author/outputs/${id}/content`, {
        responseType: 'text',
        transformResponse: [(data: unknown) => data],
      })
      .then(r => r.data),

  /** Create the row and queue generation in the worker (S-6.7.1). Returns
   * the `pending` row at once; progress arrives over the job socket under
   * the output's id. A kind without an outputter is 501 (no row written). */
  createOutput: (payload: CreateOutputPayload) =>
    api.post<OutputItem>('/author/outputs', payload).then(r => r.data),

  /** S-6.7.2: the output as a file. Header auth, so the page saves a blob
   * rather than navigating (D-079). The server names the file. */
  download: (id: string, format?: string) =>
    api
      .get<Blob>(`/author/outputs/${id}/download`, { params: format ? { format } : undefined, responseType: 'blob' })
      .then((r) => ({ blob: r.data, disposition: String(r.headers['content-disposition'] ?? '') })),

  cancelOutput: (id: string) =>
    api.post<OutputItem>(`/author/outputs/${id}/cancel`).then(r => r.data),

  deleteOutput: (id: string) =>
    api.delete<{ deleted: boolean }>(`/author/outputs/${id}`).then(r => r.data),
};
