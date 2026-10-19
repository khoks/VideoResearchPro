import api from './api';

// Mirrors backend/app/routers/author.py (I-6 foundation, PR #173).

export type OutputStatus = 'pending' | 'generating' | 'completed' | 'failed';

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

  /** Create + generate synchronously. Returns the row in `completed` or
   * `failed` state; a kind without an outputter returns HTTP 501. */
  createOutput: (payload: CreateOutputPayload) =>
    api.post<OutputItem>('/author/outputs', payload).then(r => r.data),

  deleteOutput: (id: string) =>
    api.delete<{ deleted: boolean }>(`/author/outputs/${id}`).then(r => r.data),
};
