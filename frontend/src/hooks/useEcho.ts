import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  echoApi,
  type CreateSharePayload,
  type ImportOptions,
  type CreateSignalPayload,
  type CreateDraftPayload,
  type DraftFeedbackPayload,
  type VoiceTest,
  type VoiceTestOverview,
  type VoiceTestSide,
  type ListContextParams,
  type ListSharesParams,
  type RecordContextPayload,
  type UpdateSharePayload,
  type UpdateSignalPayload,
  type UploadShareFields,
} from '../services/echoApi';
import { ERRORS_SHOWN_HERE, toastMutationError } from '../services/queryClient';
import { useJobStore } from '../stores/jobStore';
import { isSessionEnded } from '../utils/apiError';
import { draftErrorOf, isDraftStop } from '../utils/echoDrafts';

// A mutation below that names `toastMutationError` answers its own failures, in
// its own `onError`, so one failure is one toast, said even once the page that
// started it has gone (D-148 point 5, T-3.4.1.17). Each has one caller, whose
// own toast moved here. The two share hooks have two, and say theirs only when asked.

const STATUS_KEY = ['echo', 'status'] as const;
const CONTEXT_KEY = ['echo', 'context'] as const;

export function useEchoStatus(enabled = true) {
  return useQuery({
    queryKey: STATUS_KEY,
    queryFn: () => echoApi.status(),
    staleTime: 15_000,
    enabled,
  });
}

export function useEchoContext(params?: ListContextParams, enabled = true) {
  return useQuery({
    queryKey: [
      ...CONTEXT_KEY,
      params?.kind ?? null,
      params?.source ?? null,
      params?.include_expired ?? false,
    ],
    queryFn: () => echoApi.listContext(params),
    staleTime: 15_000,
    enabled,
  });
}

export function useEchoConnectors(enabled = true) {
  return useQuery({
    queryKey: ['echo', 'connectors'],
    queryFn: () => echoApi.listConnectors(),
    staleTime: 5 * 60_000,
    enabled,
  });
}

function useInvalidateEcho() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: CONTEXT_KEY });
    qc.invalidateQueries({ queryKey: STATUS_KEY });
    // Deleting a derived fact records a tombstone (T-3.2.4.4).
    qc.invalidateQueries({ queryKey: TOMBSTONES_KEY });
  };
}

// T-3.2.4.4: derived facts the user deleted, which syncs and re-imports skip.
const TOMBSTONES_KEY = ['echo', 'fact-tombstones'] as const;

export function useFactTombstones(enabled = true) {
  return useQuery({
    queryKey: TOMBSTONES_KEY,
    queryFn: () => echoApi.listFactTombstones(),
    staleTime: 15_000,
    enabled,
  });
}

export function useClearFactTombstone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => echoApi.clearFactTombstone(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TOMBSTONES_KEY });
      qc.invalidateQueries({ queryKey: ['echo', 'footprint'] });
    },
    onError: (err) => toastMutationError(err, 'Could not allow it again.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useRecordContext() {
  const invalidate = useInvalidateEcho();
  return useMutation({
    mutationFn: (payload: RecordContextPayload) => echoApi.recordContext(payload),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Could not save this entry.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useDeleteContext() {
  const invalidate = useInvalidateEcho();
  return useMutation({
    mutationFn: ({ kind, key }: { kind: string; key: string }) => echoApi.deleteContext(kind, key),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Delete failed. The entry may already be gone.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useRevokeSource() {
  const invalidate = useInvalidateEcho();
  return useMutation({
    mutationFn: (source: string) => echoApi.revokeSource(source),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Revoke failed.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

// ---------------------------------------------------------------------------
// Shares inbox and privacy
// ---------------------------------------------------------------------------

const SHARES_KEY = ['echo', 'shares'] as const;
const FOOTPRINT_KEY = ['echo', 'footprint'] as const;

export function useShares(params: ListSharesParams, enabled = true) {
  return useQuery({
    queryKey: [
      ...SHARES_KEY,
      params.state ?? null,
      params.q ?? '',
      params.limit ?? null,
      params.offset ?? 0,
      params.origin ?? 'direct',
      params.import_id ?? null,
    ],
    queryFn: () => echoApi.listShares(params),
    staleTime: 10_000,
    enabled,
  });
}

export function useEchoFootprint(enabled = true) {
  return useQuery({
    queryKey: FOOTPRINT_KEY,
    queryFn: () => echoApi.footprint(),
    staleTime: 10_000,
    enabled,
  });
}

function useInvalidateShares() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: SHARES_KEY });
    qc.invalidateQueries({ queryKey: FOOTPRINT_KEY });
    qc.invalidateQueries({ queryKey: STATUS_KEY });
  };
}

// S-3.7.3: share tokens for the browser extension.
const TOKENS_KEY = ['echo', 'share-tokens'] as const;

export function useShareTokens(enabled = true) {
  return useQuery({ queryKey: TOKENS_KEY, queryFn: () => echoApi.listShareTokens(), staleTime: 10_000, enabled });
}

export function useCreateShareToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (label: string) => echoApi.createShareToken(label),
    onSuccess: () => qc.invalidateQueries({ queryKey: TOKENS_KEY }),
    onError: (err) => toastMutationError(err, 'Could not make a token.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useRevokeShareToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => echoApi.revokeShareToken(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: TOKENS_KEY }),
    onError: (err) => toastMutationError(err, 'Could not revoke it.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

// S-3.7.5: export-file imports.
const IMPORTS_KEY = ['echo', 'imports'] as const;

export function useImports(enabled = true) {
  return useQuery({
    queryKey: IMPORTS_KEY,
    queryFn: () => echoApi.listImports(),
    staleTime: 5_000,
    enabled,
    // Embedding runs in the background; poll while any import is busy.
    refetchInterval: (q) =>
      q.state.data?.items.some(i => i.status === 'embedding' || i.status === 'deleting') ? 4_000 : false,
  });
}

export function usePreviewImport() {
  return useMutation({
    mutationFn: ({ file, options }: { file: File; options?: ImportOptions }) => echoApi.previewImport(file, options),
    // A date order means the file was read once already, and only the dates changed.
    onError: (err, { options }) =>
      toastMutationError(err, options?.date_order ? 'Could not re-read the dates.' : 'This file could not be read.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

function useInvalidateImports() {
  const qc = useQueryClient();
  const invalidateShares = useInvalidateShares();
  return () => {
    qc.invalidateQueries({ queryKey: IMPORTS_KEY });
    invalidateShares();
  };
}

export function useRunImport() {
  const invalidate = useInvalidateImports();
  return useMutation({
    mutationFn: ({ file, options }: { file: File; options?: ImportOptions }) => echoApi.runImport(file, options),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'The import failed.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useRetryImportEmbedding() {
  const invalidate = useInvalidateImports();
  return useMutation({
    mutationFn: (id: string) => echoApi.retryImportEmbedding(id),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Could not retry.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useDeleteImport() {
  const invalidate = useInvalidateImports();
  return useMutation({
    mutationFn: (id: string) => echoApi.deleteImport(id),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Undo failed.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

/**
 * `toastErrors`: the hook says each failure, naming what was being added. The
 * drop zone asks for it, since it can drop several files at once and a per-call
 * `onError` runs for the last one only. Quick share leaves it off: it shows the
 * failure in its dialog, and the global toast speaks as before.
 */
interface ShareErrorOptions {
  toastErrors?: boolean;
}

export function useCreateShare({ toastErrors = false }: ShareErrorOptions = {}) {
  const invalidate = useInvalidateShares();
  return useMutation({
    mutationFn: (payload: CreateSharePayload) => echoApi.createShare(payload),
    onSuccess: invalidate,
    onError: (err, payload) => {
      if (toastErrors) toastMutationError(err, payload.url ? 'Could not add the link.' : 'Could not add the text.');
    },
    meta: toastErrors ? ERRORS_SHOWN_HERE : undefined,
  });
}

export function useUploadShare({ toastErrors = false }: ShareErrorOptions = {}) {
  const invalidate = useInvalidateShares();
  return useMutation({
    mutationFn: ({ file, fields }: { file: File; fields?: UploadShareFields }) => echoApi.uploadShare(file, fields),
    onSuccess: invalidate,
    onError: (err, { file }) => {
      if (toastErrors) toastMutationError(err, `Could not add ${file.name}.`);
    },
    meta: toastErrors ? ERRORS_SHOWN_HERE : undefined,
  });
}

export function useUpdateShare() {
  const invalidate = useInvalidateShares();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateSharePayload }) => echoApi.updateShare(id, payload),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Could not save.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useReprocessShare() {
  const invalidate = useInvalidateShares();
  return useMutation({
    mutationFn: (id: string) => echoApi.reprocessShare(id),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Could not queue the retry.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useAddShareToLibrary() {
  const invalidate = useInvalidateShares();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => echoApi.addShareToLibrary(id),
    onSuccess: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ['library'] });
    },
    // A full library's refusal (T-5.2.10) is said here too, in the server's words:
    // the global toast leaves that one to the page.
    onError: (err) => toastMutationError(err, 'Could not add it to the library.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useDeleteShare() {
  const invalidate = useInvalidateShares();
  return useMutation({
    mutationFn: (id: string) => echoApi.deleteShare(id),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Delete failed. The share may already be gone.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

// ---------------------------------------------------------------------------
// Voice and personality signals (S-3.3.1)
// ---------------------------------------------------------------------------

const SIGNALS_KEY = ['echo', 'signals'] as const;

export function useVoiceSignals(enabled = true) {
  return useQuery({
    queryKey: SIGNALS_KEY,
    queryFn: () => echoApi.listSignals(),
    staleTime: 15_000,
    enabled,
  });
}

function useInvalidateSignals() {
  const qc = useQueryClient();
  return () => {
    // Prefix match: the rejected list (T-3.3.1.6) lives under it too.
    qc.invalidateQueries({ queryKey: SIGNALS_KEY });
    qc.invalidateQueries({ queryKey: FOOTPRINT_KEY });
  };
}

/** T-3.3.1.6: the "That's not me" rejections, for the panel's Rejected list. */
export function useRejectedSignals(enabled = true) {
  return useQuery({
    queryKey: [...SIGNALS_KEY, 'rejected'],
    queryFn: () => echoApi.listRejectedSignals(),
    staleTime: 15_000,
    enabled,
  });
}

export function useRestoreSignal() {
  const invalidate = useInvalidateSignals();
  return useMutation({
    mutationFn: (id: string) => echoApi.restoreSignal(id),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Could not restore the signal.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useCreateSignal() {
  const invalidate = useInvalidateSignals();
  return useMutation({
    mutationFn: (payload: CreateSignalPayload) => echoApi.createSignal(payload),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Could not add the signal.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useUpdateSignal() {
  const invalidate = useInvalidateSignals();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateSignalPayload }) => echoApi.updateSignal(id, payload),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Could not save the signal.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

// ---------------------------------------------------------------------------
// "Speak as me" (S-3.4.1)
// ---------------------------------------------------------------------------

const DRAFTS_KEY = ['echo', 'drafts'] as const;

export function useDraftStatus(enabled = true) {
  return useQuery({ queryKey: [...DRAFTS_KEY, 'status'], queryFn: () => echoApi.draftStatus(), staleTime: 15_000, enabled });
}

export function useRecentDrafts(enabled = true) {
  return useQuery({ queryKey: [...DRAFTS_KEY, 'recent'], queryFn: () => echoApi.listDrafts(5), staleTime: 15_000, enabled });
}

export function useCreateDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateDraftPayload) => echoApi.createDraft(payload),
    onSettled: () => qc.invalidateQueries({ queryKey: DRAFTS_KEY }),
    // Here, not on the panel's `mutate` call: TanStack drops a per-call callback
    // once its component has gone, and a draft runs long enough to be left behind.
    // These words beat the global toast's for a request that got no answer at all,
    // so that one stays quiet (T-3.4.1.15). The panel shows the stops itself.
    onError: (err) => {
      const e = draftErrorOf(err);
      if (!isDraftStop(e) && !isSessionEnded(err)) useJobStore.getState().pushToast('error', e.message);
    },
    meta: { errorsShownHere: true },
  });
}

export function useDeleteDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => echoApi.deleteDraft(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: DRAFTS_KEY });
      qc.invalidateQueries({ queryKey: FOOTPRINT_KEY });
    },
  });
}

/** Where a draft is edited: the Echo page's card, or a turn in the Echo bubble. */
export type DraftSurface = 'page' | 'bubble';

// The draft view, the one caller of `useDraftFeedback`, says a failed save on
// its own line, so the global toast stands aside (T-3.4.1.24). The surface it
// sits on holds still while a save made there is in flight (`useIsMutating` on
// this key): the bubble stays open, and the Echo page's card keeps the draft on
// screen. Otherwise the line would go before it is written, and the failure be
// said nowhere (D-156 point 2, D-159 point 2).
export const draftFeedbackKey = (surface: DraftSurface) => ['echo', 'draft-feedback', surface] as const;

export function useDraftFeedback(surface: DraftSurface) {
  const qc = useQueryClient();
  return useMutation({
    mutationKey: draftFeedbackKey(surface),
    mutationFn: ({ id, ...payload }: { id: string } & DraftFeedbackPayload) => echoApi.draftFeedback(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: DRAFTS_KEY });
      qc.invalidateQueries({ queryKey: ['echo', 'signals'] });
    },
    meta: ERRORS_SHOWN_HERE,
  });
}

// ---------------------------------------------------------------------------
// The voice test (T-3.4.1.8)
// ---------------------------------------------------------------------------

const VOICE_TEST_KEY = ['echo', 'voice-test'] as const;

export function useVoiceTest(enabled = true) {
  return useQuery({ queryKey: VOICE_TEST_KEY, queryFn: () => echoApi.voiceTest(), staleTime: 15_000, enabled });
}

/** Polls one test while it is being written. The overview re-reads readiness,
 * which is too much to ask of it every few seconds. */
export function useVoiceTestPoll(id: string | null, intervalMs = 3000) {
  return useQuery({
    queryKey: [...VOICE_TEST_KEY, 'poll', id],
    queryFn: () => echoApi.getVoiceTest(id as string),
    enabled: id !== null,
    refetchInterval: (query) => (query.state.data && query.state.data.status !== 'generating' ? false : intervalMs),
  });
}

export function useStartVoiceTest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => echoApi.startVoiceTest(),
    onSettled: () => qc.invalidateQueries({ queryKey: VOICE_TEST_KEY }),
    onError: (err) => toastMutationError(err, "Couldn't start the test. Try again."),
    meta: ERRORS_SHOWN_HERE,
  });
}

function storeTest(qc: ReturnType<typeof useQueryClient>, test: VoiceTest) {
  qc.setQueryData<VoiceTestOverview>(VOICE_TEST_KEY, (old) => (old ? { ...old, test } : old));
}

export function usePickVoiceTest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, pair, pick }: { id: string; pair: string; pick: VoiceTestSide }) => echoApi.pickVoiceTest(id, pair, pick),
    onSuccess: (test) => storeTest(qc, test),
    onError: (err) => toastMutationError(err, "Couldn't save that pick. Try again."),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useScoreVoiceTest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => echoApi.scoreVoiceTest(id),
    onSuccess: ({ test }) => {
      storeTest(qc, test);
      qc.invalidateQueries({ queryKey: VOICE_TEST_KEY });
      // The gate moved: the card's blockers and the bubble read it.
      qc.invalidateQueries({ queryKey: DRAFTS_KEY });
    },
    onError: (err) => toastMutationError(err, "Couldn't score the test. Try again."),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useLearnSignals() {
  const invalidate = useInvalidateSignals();
  return useMutation({
    mutationFn: () => echoApi.learnSignals(),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Could not start learning. Try again.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useRejectSignal() {
  const invalidate = useInvalidateSignals();
  return useMutation({
    mutationFn: (id: string) => echoApi.rejectSignal(id),
    onSuccess: invalidate,
    onError: (err) => toastMutationError(err, 'Could not remove the signal.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

/** Deletes every Echo row, file and vector. Invalidates everything Echo. */
export function useDeleteBrain() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => echoApi.deleteBrain(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['echo'] }),
    onError: (err) => toastMutationError(err, 'Delete failed. Nothing past the failing store was removed; try again.'),
    meta: ERRORS_SHOWN_HERE,
  });
}

// ---------------------------------------------------------------------------
// Connectors and the activity timeline (S-3.2.1)
// ---------------------------------------------------------------------------

const CONNECTORS_KEY = ['echo', 'connectors'] as const;
const ACTIVITY_KEY = ['echo', 'activity'] as const;

function useInvalidateConnectors() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: CONNECTORS_KEY });
    qc.invalidateQueries({ queryKey: ACTIVITY_KEY });
    qc.invalidateQueries({ queryKey: STATUS_KEY });
    qc.invalidateQueries({ queryKey: CONTEXT_KEY });
  };
}

export function useSyncConnector() {
  const invalidate = useInvalidateConnectors();
  return useMutation({
    mutationFn: (name: string) => echoApi.syncConnector(name),
    onSuccess: invalidate,
  });
}

export function useRevokeConnector() {
  const invalidate = useInvalidateConnectors();
  return useMutation({
    mutationFn: (name: string) => echoApi.revokeConnector(name),
    onSuccess: invalidate,
  });
}

export function useCompleteConnector() {
  const invalidate = useInvalidateConnectors();
  return useMutation({
    mutationFn: ({ name, code, state }: { name: string; code: string; state: string }) =>
      echoApi.completeConnector(name, { code, state }),
    onSuccess: invalidate,
    // Its one caller, the callback page, says a failure as the page itself (T-3.4.1.18).
    meta: ERRORS_SHOWN_HERE,
  });
}

/** The newest activity, a page at a time (`before` = the previous page's `next_before`). */
export function useEchoActivity(enabled = true, before?: string) {
  return useQuery({
    queryKey: [...ACTIVITY_KEY, before ?? null],
    queryFn: () => echoApi.listActivity({ limit: 20, before }),
    enabled,
  });
}
