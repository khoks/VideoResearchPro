import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { authorApi, type CreateOutputPayload, type ListOutputsParams, type NewsletterSettings } from '../services/authorApi';

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

/** One output's metadata, for the reader at /author/outputs/:id (S-8.8.3). */
export function useAuthorOutput(id: string | null) {
  return useQuery({
    queryKey: ['author', 'output', id],
    queryFn: () => authorApi.getOutput(id!),
    enabled: !!id,
    retry: (count, err: unknown) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      return status !== 403 && status !== 404 && count < 1;
    },
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

/** S-6.1.3: the cost of generating with these settings, before it runs.
 * Keyed on what changes the price (runs and cohesion level), not the title. */
export function useOutputEstimate(payload: CreateOutputPayload, enabled: boolean) {
  const cohesion = String(payload.parameters?.cohesion ?? 'none');
  return useQuery({
    queryKey: ['author', 'estimate', payload.kind, [...payload.source_ids].sort(), cohesion],
    queryFn: () => authorApi.estimateOutput(payload),
    enabled,
    staleTime: 5 * 60_000,
  });
}

const NEWSLETTER_KEY = ['author', 'newsletter'] as const;

/** S-6.4.2: the reader's digest subscription (null when there is none). */
export function useNewsletter(enabled = true) {
  return useQuery({ queryKey: NEWSLETTER_KEY, queryFn: () => authorApi.getNewsletter(), enabled });
}

export function useSaveNewsletter() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings: NewsletterSettings) => authorApi.saveNewsletter(settings),
    onSuccess: (sub) => qc.setQueryData(NEWSLETTER_KEY, sub),
  });
}

export function useDeleteNewsletter() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => authorApi.deleteNewsletter(),
    onSuccess: () => qc.setQueryData(NEWSLETTER_KEY, null),
  });
}

export function useSendNewsletterNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => authorApi.sendNewsletterNow(),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: NEWSLETTER_KEY });
      qc.invalidateQueries({ queryKey: OUTPUTS_KEY });
    },
  });
}

export function useCreateOutput() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateOutputPayload) => authorApi.createOutput(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: OUTPUTS_KEY }),
    // S-6.7.1: a 501 no longer writes a row, but a queue failure records a
    // `failed` row, so refresh on error too.
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

/** S-6.7.1: stop a pending or generating output (mirrors cancelling a job). */
export function useCancelOutput() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => authorApi.cancelOutput(id),
    onSettled: (_data, _err, id) => {
      qc.invalidateQueries({ queryKey: OUTPUTS_KEY });
      qc.invalidateQueries({ queryKey: ['author', 'output', id] });
    },
  });
}
