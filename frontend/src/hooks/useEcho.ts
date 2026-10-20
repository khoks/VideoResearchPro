import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  echoApi,
  type CreateSharePayload,
  type CreateSignalPayload,
  type ListContextParams,
  type ListSharesParams,
  type RecordContextPayload,
  type UpdateSharePayload,
  type UpdateSignalPayload,
  type UploadShareFields,
} from '../services/echoApi';

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
  };
}

export function useRecordContext() {
  const invalidate = useInvalidateEcho();
  return useMutation({
    mutationFn: (payload: RecordContextPayload) => echoApi.recordContext(payload),
    onSuccess: invalidate,
  });
}

export function useDeleteContext() {
  const invalidate = useInvalidateEcho();
  return useMutation({
    mutationFn: ({ kind, key }: { kind: string; key: string }) => echoApi.deleteContext(kind, key),
    onSuccess: invalidate,
  });
}

export function useRevokeSource() {
  const invalidate = useInvalidateEcho();
  return useMutation({
    mutationFn: (source: string) => echoApi.revokeSource(source),
    onSuccess: invalidate,
  });
}

// ---------------------------------------------------------------------------
// Shares inbox and privacy
// ---------------------------------------------------------------------------

const SHARES_KEY = ['echo', 'shares'] as const;
const FOOTPRINT_KEY = ['echo', 'footprint'] as const;

export function useShares(params: ListSharesParams, enabled = true) {
  return useQuery({
    queryKey: [...SHARES_KEY, params.state ?? null, params.q ?? '', params.limit ?? null, params.offset ?? 0],
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

export function useCreateShare() {
  const invalidate = useInvalidateShares();
  return useMutation({
    mutationFn: (payload: CreateSharePayload) => echoApi.createShare(payload),
    onSuccess: invalidate,
  });
}

export function useUploadShare() {
  const invalidate = useInvalidateShares();
  return useMutation({
    mutationFn: ({ file, fields }: { file: File; fields?: UploadShareFields }) => echoApi.uploadShare(file, fields),
    onSuccess: invalidate,
  });
}

export function useUpdateShare() {
  const invalidate = useInvalidateShares();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateSharePayload }) => echoApi.updateShare(id, payload),
    onSuccess: invalidate,
  });
}

export function useReprocessShare() {
  const invalidate = useInvalidateShares();
  return useMutation({
    mutationFn: (id: string) => echoApi.reprocessShare(id),
    onSuccess: invalidate,
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
  });
}

export function useDeleteShare() {
  const invalidate = useInvalidateShares();
  return useMutation({
    mutationFn: (id: string) => echoApi.deleteShare(id),
    onSuccess: invalidate,
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
    qc.invalidateQueries({ queryKey: SIGNALS_KEY });
    qc.invalidateQueries({ queryKey: FOOTPRINT_KEY });
  };
}

export function useCreateSignal() {
  const invalidate = useInvalidateSignals();
  return useMutation({
    mutationFn: (payload: CreateSignalPayload) => echoApi.createSignal(payload),
    onSuccess: invalidate,
  });
}

export function useUpdateSignal() {
  const invalidate = useInvalidateSignals();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateSignalPayload }) => echoApi.updateSignal(id, payload),
    onSuccess: invalidate,
  });
}

export function useLearnSignals() {
  const invalidate = useInvalidateSignals();
  return useMutation({
    mutationFn: () => echoApi.learnSignals(),
    onSuccess: invalidate,
  });
}

export function useRejectSignal() {
  const invalidate = useInvalidateSignals();
  return useMutation({
    mutationFn: (id: string) => echoApi.rejectSignal(id),
    onSuccess: invalidate,
  });
}

/** Deletes every Echo row, file and vector. Invalidates everything Echo. */
export function useDeleteBrain() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => echoApi.deleteBrain(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['echo'] }),
  });
}
