import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { echoApi, type ListContextParams, type RecordContextPayload } from '../services/echoApi';

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
