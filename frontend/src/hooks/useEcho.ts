import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  echoApi,
  type CreateSharePayload,
  type ImportOptions,
  type ListContextParams,
  type ListSharesParams,
  type RecordContextPayload,
  type UpdateSharePayload,
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
  });
}

export function useRetryImportEmbedding() {
  const invalidate = useInvalidateImports();
  return useMutation({ mutationFn: (id: string) => echoApi.retryImportEmbedding(id), onSuccess: invalidate });
}

export function useDeleteImport() {
  const invalidate = useInvalidateImports();
  return useMutation({ mutationFn: (id: string) => echoApi.deleteImport(id), onSuccess: invalidate });
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

/** Deletes every Echo row, file and vector. Invalidates everything Echo. */
export function useDeleteBrain() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => echoApi.deleteBrain(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['echo'] }),
  });
}
