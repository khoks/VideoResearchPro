import api from './api';

// Mirrors backend/app/routers/echo.py (I-3 foundation, PR #172).

export interface EchoStatus {
  ready: boolean;
  total_rows: number;
  distinct_sources: number;
  has_personality_trait: boolean;
  threshold_total: number;
  threshold_sources: number;
  /** Domain 3 feeder (S-8.5.3): live notes and their words. Reported, not a gate. */
  notes_total?: number;
  notes_words?: number;
  /** Domain 5 feeder (S-3.7.1): items in the shares inbox. Reported, not a gate. */
  shares_total?: number;
}

export interface PersonalContextItem {
  id: string;
  kind: string;
  key: string;
  /** Stored as text; non-string values are JSON-encoded by the service. */
  value: string;
  source: string;
  confidence: number;
  captured_at: string;
  expires_at: string | null;
}

/** `source` is fixed to `manual` by the endpoint. Re-posting an existing
 * (kind, key) updates that row in place (service-level upsert). */
export interface RecordContextPayload {
  kind: string;
  key: string;
  value: string;
  expires_at?: string | null;
  confidence?: number;
}

export interface ListContextParams {
  kind?: string;
  source?: string;
  include_expired?: boolean;
}

export interface ConnectorListResponse {
  connectors: string[];
  supported_kinds: string[];
}

// ---------------------------------------------------------------------------
// Shares inbox (S-3.7.1) and privacy (S-3.10.1 / S-3.10.2)
// ---------------------------------------------------------------------------

export type ShareKind = 'url' | 'text' | 'file';
export type ShareProcessingState = 'pending' | 'processed' | 'skipped' | 'failed';

export interface ShareFileInfo {
  filename: string;
  mime: string;
  size: number;
}

export interface Share {
  id: string;
  received_at: string;
  updated_at: string;
  surface: string;
  /** Open-ended: youtube_video, link, text_snippet, image, voice_memo, ... */
  content_type: string;
  kind: ShareKind | string;
  url: string | null;
  text: string | null;
  file: ShareFileInfo | null;
  user_annotation: string | null;
  /** False: someone else's words. Context-only: never quoted, never in a
   * dataset or derived export. True: the user's own words. */
  author_is_tenant: boolean;
  processing_state: ShareProcessingState | string;
  linked_document_id: string | null;
  /** S-3.7.2: extracted text for links and files (text shares carry `text`). */
  extracted_text?: string | null;
  /** S-3.7.2: what processing found; absent until it ran. */
  processing?: ShareProcessing | null;
}

export interface ShareProcessing {
  title?: string | null;
  author?: string | null;
  extractor?: string | null;
  /** Why processing failed, in words fit to show. */
  error?: string | null;
  /** Anything worth knowing about the reading: why a share was skipped,
   * that a reading had low confidence, that text was cut short. */
  note?: string | null;
  embedded?: boolean | null;
  processed_at?: string | null;
  library_offer?: { eligible: boolean; reason?: string | null; source_type?: string | null } | null;
  /** Part 2 (media): how a file was read. */
  ocr_confidence?: number | null;
  language?: string | null;
  duration_seconds?: number | null;
  page_count?: number | null;
  pages_with_text?: number | null;
  truncated?: boolean | null;
}

export interface ShareListResponse {
  items: Share[];
  total: number;
  limit: number;
  offset: number;
}

export interface ListSharesParams {
  state?: ShareProcessingState;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface CreateSharePayload {
  url?: string;
  text?: string;
  annotation?: string | null;
  content_type?: string;
  author_is_tenant?: boolean;
}

export interface UploadShareFields {
  annotation?: string | null;
  content_type?: string;
  author_is_tenant?: boolean;
}

export interface UpdateSharePayload {
  /** `null` clears it. */
  annotation?: string | null;
  content_type?: string;
  author_is_tenant?: boolean;
}

export interface EchoFootprint {
  rows: Record<string, number>;
  files: number;
  vectors: Record<string, number>;
}

/** One example of a signal in the user's own words (S-3.3.1). */
export interface SignalExample {
  text: string;
  /** `note:<id>`, `share:<id>`, `qa:<id>`, `library_qa:<id>`, `history_qa:<id>` or `user`. */
  source: string;
  at?: string | null;
}

export interface VoiceSignal {
  id: string;
  signal_type: string;
  layer: 'style' | 'personality';
  value: string;
  weight: number;
  examples: SignalExample[];
  language: string | null;
  register: string | null;
  derived_from: string[];
  /** `user` (typed on the panel), `llm` (extracted), `stylometry` (measured). */
  origin: string;
  consent_version: string;
  created_at: string;
  updated_at: string;
}

/** S-3.3.2: what extraction has read and what is waiting. */
export interface LearningState {
  /** `celery`, `inline` or `off` (this install never learns automatically). */
  mode: string;
  /** Live notes, questions and own-words shares Echo may learn from. */
  inputs: number;
  by_language: Record<string, number>;
  /** New, edited or deleted texts not read yet. */
  pending: number;
  /** A run starts on its own once this many are waiting. */
  threshold: number;
  last_learned_at: string | null;
}

export interface VoiceSignalList {
  items: VoiceSignal[];
  consent_version: string;
  learning?: LearningState | null;
}

export interface LearnResponse {
  status: 'queued' | 'ran' | 'waiting' | 'off' | 'not_entitled' | 'queue_failed';
  pending: number;
}

export interface CreateSignalPayload {
  signal_type: string;
  value: string;
  language?: string | null;
  register?: string | null;
}

export interface UpdateSignalPayload {
  value?: string;
  language?: string | null;
  register?: string | null;
  weight?: number;
}

export interface BrainDeleteResponse {
  deleted: boolean;
  removed: EchoFootprint;
  footprint_after: EchoFootprint;
}

/** The confirmation `DELETE /echo/brain` requires. */
export const BRAIN_DELETE_CONFIRMATION = 'delete-everything';

/** `filename="x.zip"` from a Content-Disposition header, or the fallback. */
export function filenameFromDisposition(header: string | undefined | null, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''));
    } catch {
      /* fall through to the plain form */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1].trim() : fallback;
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Authenticated download: the API needs the bearer header, which a plain
 * link cannot send, and the token stays out of the URL. */
async function downloadAuthenticated(path: string, fallbackName: string): Promise<void> {
  const resp = await api.get<Blob>(path, { responseType: 'blob' });
  const name = filenameFromDisposition(resp.headers['content-disposition'] as string | undefined, fallbackName);
  saveBlob(resp.data, name);
}

export const echoApi = {
  status: () => api.get<EchoStatus>('/echo/status').then(r => r.data),

  listContext: (params?: ListContextParams) =>
    api.get<PersonalContextItem[]>('/echo/context', { params }).then(r => r.data),

  recordContext: (payload: RecordContextPayload) =>
    api.post<PersonalContextItem>('/echo/context', payload).then(r => r.data),

  /** Path-param delete. Keys are URL-encoded; a key containing `/` cannot
   * be addressed this way (Starlette decodes before routing), so the form
   * refuses such keys up front. */
  deleteContext: (kind: string, key: string) =>
    api
      .delete<{ deleted: boolean }>(
        `/echo/context/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`,
      )
      .then(r => r.data),

  /** Deletes every row attributed to `source`. Idempotent. */
  revokeSource: (source: string) =>
    api
      .delete<{ deleted_count: number }>(`/echo/sources/${encodeURIComponent(source)}`)
      .then(r => r.data),

  listConnectors: () => api.get<ConnectorListResponse>('/echo/connectors').then(r => r.data),

  listShares: (params?: ListSharesParams) =>
    api.get<ShareListResponse>('/echo/shares', { params }).then(r => r.data),

  createShare: (payload: CreateSharePayload) =>
    api.post<Share>('/echo/shares', payload).then(r => r.data),

  /** Multipart: the axios instance defaults to JSON, so the content type is
   * set explicitly and the browser fills in the boundary. */
  uploadShare: (file: File, fields: UploadShareFields = {}) => {
    const form = new FormData();
    form.append('file', file, file.name);
    if (fields.annotation) form.append('annotation', fields.annotation);
    if (fields.content_type) form.append('content_type', fields.content_type);
    form.append('author_is_tenant', fields.author_is_tenant ? 'true' : 'false');
    return api
      .post<Share>('/echo/shares/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then(r => r.data);
  },

  updateShare: (id: string, payload: UpdateSharePayload) =>
    api.patch<Share>(`/echo/shares/${encodeURIComponent(id)}`, payload).then(r => r.data),

  /** S-3.7.2: queue processing again ("Retry"). */
  reprocessShare: (id: string) =>
    api.post<Share>(`/echo/shares/${encodeURIComponent(id)}/process`).then(r => r.data),

  /** S-3.7.2: the library offer; ingests the shared link for this reader only. */
  addShareToLibrary: (id: string) =>
    api.post<Share>(`/echo/shares/${encodeURIComponent(id)}/library`).then(r => r.data),

  deleteShare: (id: string) =>
    api
      .delete<{ deleted: boolean; vectors: number; files: number; derived_facts: number }>(
        `/echo/shares/${encodeURIComponent(id)}`,
      )
      .then(r => r.data),

  downloadShareFile: (share: Pick<Share, 'id' | 'file'>) =>
    downloadAuthenticated(`/echo/shares/${encodeURIComponent(share.id)}/file`, share.file?.filename ?? 'file'),

  /** The whole brain as one zip (manifest, JSONL per table, files). */
  exportBrain: () => downloadAuthenticated('/echo/export', 'echo-export.zip'),

  /** S-3.3.1: the signals panel. */
  listSignals: () => api.get<VoiceSignalList>('/echo/signals').then(r => r.data),

  createSignal: (payload: CreateSignalPayload) =>
    api.post<VoiceSignal>('/echo/signals', payload).then(r => r.data),

  updateSignal: (id: string, payload: UpdateSignalPayload) =>
    api.patch<VoiceSignal>(`/echo/signals/${encodeURIComponent(id)}`, payload).then(r => r.data),

  /** "That's not me": a tombstone; Echo never learns the signal again. */
  rejectSignal: (id: string) =>
    api.delete<VoiceSignal>(`/echo/signals/${encodeURIComponent(id)}`).then(r => r.data),

  exportSignals: () => downloadAuthenticated('/echo/signals/export', 'echo-voice-profile.json'),

  /** S-3.3.2 "Learn now": queue a run for whatever is waiting. */
  learnSignals: () => api.post<LearnResponse>('/echo/signals/learn').then(r => r.data),

  footprint: () => api.get<EchoFootprint>('/echo/brain/footprint').then(r => r.data),

  deleteBrain: () =>
    api
      .delete<BrainDeleteResponse>('/echo/brain', { params: { confirm: BRAIN_DELETE_CONFIRMATION } })
      .then(r => r.data),
};
