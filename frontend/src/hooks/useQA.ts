import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { qaApi } from '../services/qaApi';
import type { ClarifyRequest, QARequest } from '../types/qa';

export function useQAHistory(jobId: string | null) {
  return useQuery({
    queryKey: ['qaHistory', jobId],
    queryFn: () => qaApi.getHistory(jobId!),
    enabled: !!jobId,
  });
}

export function useAskQuestion(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: QARequest) => qaApi.ask(jobId, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['qaHistory', jobId] }),
  });
}

export function useClarifyQuestion(jobId: string) {
  return useMutation({
    mutationFn: (data: ClarifyRequest) => qaApi.clarify(jobId, data),
  });
}
