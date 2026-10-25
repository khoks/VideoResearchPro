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
  /** Domain 5 feeder (S-3.7.1): items in the shares inbox. */
  shares_total?: number;
  /** S-3.5.1: readiness v2. `ready` is every domain met; 0..1. */
  progress?: number;
  domains?: ReadinessDomain[];
}

export interface ReadinessCriterion {
  key: string;
  label: string;
  current: number;
  target: number;
  met: boolean;
  /** 0..1 */
  fraction: number;
}

export interface ReadinessSource {
  name: string;
  label: string;
  kind: 'connector' | 'import';
  /** connected | not_connected | imported */
  status: string;
  available: boolean;
  /** Why a source cannot be connected yet (not set up, waits on the Google connector OAuth client). */
  reason: string | null;
  events: number;
}

/** One of the five readiness domains (S-3.5.1), measured from its store. */
export interface ReadinessDomain {
  key: 'facts' | 'activity' | 'signals' | 'voice' | 'shares' | string;
  /** The personal-brain.md domain number. */
  domain: number;
  label: string;
  status: 'met' | 'in_progress' | 'not_started' | 'not_connected' | string;
  met: boolean;
  progress: number;
  criteria: ReadinessCriterion[];
  /** What is there, in words. */
  summary: string;
  /** What is missing, in words; null when met. */
  missing: string | null;
  details: {
    sources?: ReadinessSource[];
    per_script?: Record<string, { pieces: number; words: number }>;
    best_script?: string | null;
    stability?: { measured: boolean; spread: number | null; max: number; reason?: string; vectors?: number };
    voice_test?: { eligible: boolean; notes: number; notes_needed: number };
    [key: string]: unknown;
  };
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

export type PrivacyWeight = 'low' | 'medium' | 'high' | 'very_high';

/** A reader's grant for one connector (S-3.2.1). */
export interface ConnectorGrant {
  account_label: string | null;
  granted_at: string | null;
  consent_version: string;
  /** The disclosure changed since the user agreed to it. */
  consent_outdated: boolean;
  status: 'idle' | 'syncing' | 'error' | string;
  last_sync_at: string | null;
  backfilled_at: string | null;
  last_error: string | null;
  last_counts: { added: number; updated: number; facts: number } | null;
  events: number;
}

/** One connector this install offers, with what the consent screen shows. */
export interface ConnectorItem {
  name: string;
  display_name: string;
  privacy_weight: PrivacyWeight;
  consent_disclosure: string;
  consent_version: string;
  event_types: string[];
  /** The install has this connector's OAuth client. */
  configured: boolean;
  connected: boolean;
  grant: ConnectorGrant | null;
}

export interface ConnectorListResponse {
  connectors: string[];
  supported_kinds: string[];
  items: ConnectorItem[];
}

export interface ConnectorRevokeResult {
  connector: string;
  events: number;
  facts: number;
  provider_revoked: boolean;
}

export interface ActivityItem {
  id: string;
  connector: string;
  event_type: string;
  occurred_at: string;
  payload: Record<string, unknown>;
  text_content: string | null;
  linked_document_id: string | null;
}

export interface ActivityResponse {
  items: ActivityItem[];
  next_before: string | null;
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
  /** S-3.7.5: set on shares an export import wrote. */
  import_id?: string | null;
  /** When the message or note was written (imports); `received_at` otherwise. */
  occurred_at?: string | null;
  /** The importer's provenance: chat and sender, or note title and labels. */
  imported?: Record<string, unknown> | null;
  /** S-3.7.3: the page a quote or an image came from. */
  source?: { url?: string; title?: string } | null;
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
  /** S-3.7.5: `direct` (the default) | `import` | `all`. */
  origin?: 'direct' | 'import' | 'all';
  /** One import's shares, oldest first. */
  import_id?: string;
}

// S-3.7.5: export-file imports.
export type ImporterName = 'whatsapp' | 'google_keep' | string;
export type ImportStatus = 'importing' | 'embedding' | 'done' | 'failed' | 'deleting';

export interface ImportPreview {
  importer: ImporterName;
  label: string;
  summary: Record<string, unknown>;
  participants: { name: string; messages: number }[];
  options: Record<string, unknown>;
  warnings: string[];
}

export interface EchoImportItem {
  id: string;
  importer: ImporterName;
  filename: string;
  status: ImportStatus | string;
  options: Record<string, unknown>;
  counts: Record<string, number>;
  summary: Record<string, unknown>;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface ImportOptions {
  self_name?: string | null;
  redact_other_party?: boolean;
  timezone?: string | null;
  date_order?: 'dmy' | 'mdy' | 'ymd';
  own_words?: boolean;
  include_trashed?: boolean;
  /** Google Takeout: which parts to import. */
  include_keep?: boolean;
  include_youtube?: boolean;
  /** Apple Health: how many days the routine summaries cover. */
  window_days?: number;
}

export type ShareSurface = 'manual_quick_share' | 'drag_drop' | 'browser_ext' | 'email_in' | 'os_share';

export interface CreateSharePayload {
  url?: string;
  text?: string;
  annotation?: string | null;
  content_type?: string;
  author_is_tenant?: boolean;
  surface?: ShareSurface;
  source_url?: string;
  source_title?: string;
}

export interface UploadShareFields {
  annotation?: string | null;
  content_type?: string;
  author_is_tenant?: boolean;
  surface?: ShareSurface;
}

/** S-3.7.3: a token the browser extension adds shares with. */
export interface ShareToken {
  id: string;
  label: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
}

/** Returned once, when the token is made. */
export interface CreatedShareToken extends ShareToken {
  token: string;
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

/** S-3.4.1 "speak as me". Contract agreed with the Echo bubble (S-3.8.1). */
export interface DraftBlocker {
  code: 'install_off' | 'not_ready' | 'voice_test_required' | 'voice_test_failed' | 'daily_cap' | string;
  /** Written for the user; show it as is. */
  message: string;
}

export interface VoiceGate {
  status: 'not_run' | 'passed' | 'failed';
  run_at: string | null;
  pairs: number;
  picked_own_share: number | null;
  notes_total: number;
  notes_needed: number;
}

export interface DraftStatus {
  enabled: boolean;
  blockers: DraftBlocker[];
  readiness: Record<string, unknown>;
  voice_gate: VoiceGate;
  drafts_today: number;
  drafts_per_day: number;
  /** Summary fields for the bubble: the first blocker as a state, every
   * blocker's message, and the voice test's counts. */
  state: DraftGateState | string;
  reasons: string[];
  notes: number;
  notes_needed: number;
  pairs_judged: number;
  pairs_needed: number;
}

export interface DraftCitation {
  kind: 'source' | 'fact' | 'note' | 'qa' | 'share' | string;
  /** The draft's marker for it (S1, F2), unique within one draft. */
  ref?: string;
  label: string;
  /** A link outside the app (a source at its timestamp). */
  url?: string;
  /** A link inside the app, when there is one. */
  href?: string | null;
}

export interface EchoDraft {
  id: string;
  message: string;
  draft: string;
  language: string;
  register: string | null;
  audience: string | null;
  intent: string | null;
  voice_match_score: number;
  confidence: number;
  citations: DraftCitation[];
  deviation_notes: string[];
  flags: string[];
  disclosure: string;
  final_text: string | null;
  disclosure_kept: boolean | null;
  /** S-3.4.2: when the user saved their version, and what they changed. */
  feedback_at: string | null;
  edit: DraftEdit | null;
  created_at: string;
}

/** What the user changed in a draft. Only `written` (the words they typed)
 * teaches Echo their voice; the draft words they kept are the model's, and
 * `quoted` (stretches repeated from the incoming message) the sender's. */
export interface DraftEdit {
  written_words: number;
  removed_words: number;
  quoted_words: number;
  kept_words: number;
  written: string[];
  removed: string[];
  quoted: string[];
}

export interface DraftFeedbackPayload {
  /** The text the user used, without the disclosure line. */
  final_text: string;
  disclosure_kept: boolean;
}

export interface CreateDraftPayload {
  message: string;
  audience?: string;
  register?: 'intimate' | 'casual' | 'professional' | 'public';
  language?: 'en' | 'hi-Deva' | 'hi-Latn' | 'mixed';
  acknowledge_names?: string[];
}

export interface BrainDeleteResponse {
  deleted: boolean;
  removed: EchoFootprint;
  footprint_after: EchoFootprint;
}

/** The confirmation `DELETE /echo/brain` requires. */
export const BRAIN_DELETE_CONFIRMATION = 'delete-everything';

/** `filename="x.zip"` from a Content-Disposition header, or the fallback. */
function importForm(file: File, options: ImportOptions): FormData {
  const form = new FormData();
  form.append('file', file, file.name);
  const clean = Object.fromEntries(Object.entries(options).filter(([, v]) => v !== undefined));
  form.append('options', JSON.stringify(clean));
  return form;
}

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

/**
 * "Speak as me" (S-3.4.1, lane A) as the Echo panel reads it (S-3.8.1).
 * The gate is per user (D-100): the panel shows it in words rather than
 * hiding the feature. Until the endpoint exists the read is a 404, which the
 * panel reports as "not on this install yet".
 */
export type DraftGateState = 'not_ready' | 'voice_test_needed' | 'voice_test_failed' | 'enabled';

/** The bubble's view of ``GET /echo/draft/status``: the summary fields it
 * reads, all present on the server's ``DraftStatus``. */
export type DraftGate = Partial<DraftStatus> & { enabled: boolean; state: DraftGateState | string };

export type DraftRequest = CreateDraftPayload;

/** The bubble's view of a draft: the fields it renders, all on ``EchoDraft``. */
export type DraftResponse = Pick<EchoDraft, 'id' | 'draft'> & Partial<EchoDraft>;

/** An anticipation card in the Echo panel (S-3.8.2). */
export type CardKind = 'saved_search' | 'shares' | 'questions';

export interface EchoCard {
  key: string;
  kind: CardKind | string;
  title: string;
  body?: string | null;
  href?: string | null;
  action_label?: string | null;
  /** A questions card: the suggestions context to fetch. */
  context?: string | null;
}

export interface EchoCardsResponse {
  cards: EchoCard[];
  muted_kinds: string[];
  notice?: string | null;
  notice_kind?: string | null;
}

export const echoApi = {
  cards: (context?: string) =>
    api.get<EchoCardsResponse>('/echo/cards', { params: context ? { context } : undefined }).then(r => r.data),
  dismissCard: (key: string) =>
    api.post<{ muted_kind: string | null }>('/echo/cards/dismiss', null, { params: { key } }).then(r => r.data),
  actOnCard: (key: string) => api.post('/echo/cards/act', null, { params: { key } }).then(() => undefined),
  cardShown: (key: string) => api.post('/echo/cards/shown', null, { params: { key } }).then(() => undefined),
  cardSettings: () => api.get<{ kinds: Record<string, boolean> }>('/echo/cards/settings').then(r => r.data),
  setCardSettings: (kinds: Record<string, boolean>) =>
    api.put<{ kinds: Record<string, boolean> }>('/echo/cards/settings', { kinds }).then(r => r.data),
  sharesSeen: () => api.post('/echo/cards/seen/shares').then(() => undefined),
  status: () => api.get<EchoStatus>('/echo/status').then(r => r.data),
  draftStatus: () => api.get<DraftStatus>('/echo/draft/status').then(r => r.data),
  draft: (payload: DraftRequest) => api.post<DraftResponse>('/echo/draft', payload).then(r => r.data),

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

  /** Start connecting (S-3.2.1): the provider's sign-in URL for the browser
   * to open. `consentVersion` is the disclosure the consent screen showed. */
  authorizeConnector: (name: string, consentVersion: string) =>
    api
      .post<{ authorize_url: string }>(`/echo/connectors/${encodeURIComponent(name)}/authorize`, {
        consent_version: consentVersion,
      })
      .then(r => r.data),

  /** Finish connecting with the code the provider sent back. */
  completeConnector: (name: string, body: { code: string; state: string }) =>
    api.post<ConnectorItem>(`/echo/connectors/${encodeURIComponent(name)}/callback`, body).then(r => r.data),

  syncConnector: (name: string) =>
    api
      .post<{ dispatched: string; connector: ConnectorItem }>(`/echo/connectors/${encodeURIComponent(name)}/sync`)
      .then(r => r.data),

  /** Disconnect and delete everything the connector brought in. */
  revokeConnector: (name: string) =>
    api.delete<ConnectorRevokeResult>(`/echo/connectors/${encodeURIComponent(name)}`).then(r => r.data),

  listActivity: (params?: { connector?: string; before?: string; limit?: number }) =>
    api.get<ActivityResponse>('/echo/activity', { params }).then(r => r.data),

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
    if (fields.surface) form.append('surface', fields.surface);
    return api
      .post<Share>('/echo/shares/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then(r => r.data);
  },

  /** S-3.7.3: share tokens for the browser extension. */
  listShareTokens: () =>
    api.get<{ items: ShareToken[]; max: number }>('/echo/share-tokens').then(r => r.data),

  createShareToken: (label: string) =>
    api.post<CreatedShareToken>('/echo/share-tokens', { label }).then(r => r.data),

  revokeShareToken: (id: string) =>
    api.delete<{ revoked: boolean }>(`/echo/share-tokens/${encodeURIComponent(id)}`).then(r => r.data),

  /** S-3.7.5: what importing this file would produce. Writes nothing. */
  previewImport: (file: File, options: ImportOptions = {}) =>
    api
      .post<ImportPreview>('/echo/import/preview', importForm(file, options), {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then(r => r.data),

  runImport: (file: File, options: ImportOptions = {}) =>
    api
      .post<EchoImportItem>('/echo/import', importForm(file, options), {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 0,
      })
      .then(r => r.data),

  listImports: () => api.get<{ items: EchoImportItem[] }>('/echo/imports').then(r => r.data),

  retryImportEmbedding: (id: string) =>
    api.post<EchoImportItem>(`/echo/imports/${encodeURIComponent(id)}/embed`).then(r => r.data),

  deleteImport: (id: string) =>
    api
      .delete<{ deleted: boolean; shares: number; vectors: number; facts: number }>(
        `/echo/imports/${encodeURIComponent(id)}`,
      )
      .then(r => r.data),

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

  createDraft: (payload: CreateDraftPayload) => api.post<EchoDraft>('/echo/draft', payload).then(r => r.data),

  listDrafts: (limit = 5) => api.get<{ items: EchoDraft[] }>('/echo/drafts', { params: { limit } }).then(r => r.data),

  deleteDraft: (id: string) => api.delete(`/echo/drafts/${encodeURIComponent(id)}`).then(() => undefined),

  /** S-3.4.2: the version the user used; the words they typed teach Echo. */
  draftFeedback: (id: string, payload: DraftFeedbackPayload) =>
    api.post<EchoDraft>(`/echo/drafts/${encodeURIComponent(id)}/feedback`, payload).then(r => r.data),

  footprint: () => api.get<EchoFootprint>('/echo/brain/footprint').then(r => r.data),

  deleteBrain: () =>
    api
      .delete<BrainDeleteResponse>('/echo/brain', { params: { confirm: BRAIN_DELETE_CONFIRMATION } })
      .then(r => r.data),
};
