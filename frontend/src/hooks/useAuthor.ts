import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { authorApi, type CreateOutputPayload, type ListOutputsParams } from '../services/authorApi';

const OUTPUTS_KEY = ['author', 'outputs'] as const;

export function useAuthorKinds(enabled = true) {
  return useQuery({
    queryKey: ['author', 'kinds'],
    queryFn: () => authorApi.listKinds(),
    staleTime: 5 * 60_000,
    enabled,
  });
}

export function useAuthorOutputs(params?: ListOutputsParams, enabled = true) {
  return useQuery({
    queryKey: [...OUTPUTS_KEY, params?.kind ?? null, params?.status ?? null],
    queryFn: () => authorApi.listOutputs(params),
    staleTime: 15_000,
    enabled,
  });
}

export function useAuthorOutputContent(id: string | null) {
  return useQuery({
    queryKey: ['author', 'content', id],
    queryFn: () => authorApi.getContent(id!),
    enabled: !!id,
    staleTime: 5 * 60_000,
  });
}

export function useCreateOutput() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateOutputPayload) => authorApi.createOutput(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: OUTPUTS_KEY }),
    // A 501 (no outputter yet) still leaves a pending row behind on the
    // server, so refresh the list on error too.
    onError: () => qc.invalidateQueries({ queryKey: OUTPUTS_KEY }),
  });
}

export function useDeleteOutput() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => authorApi.deleteOutput(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: OUTPUTS_KEY });
      qc.removeQueries({ queryKey: ['author', 'content', id] });
    },
  });
}
