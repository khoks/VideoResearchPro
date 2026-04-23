import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { qaHistoryApi } from '../services/qaHistoryApi';
import type { QAHistoryChatRequest } from '../types/qa';

const QA_HISTORY_CHAT_KEY = ['qaHistoryChat'] as const;

export function useQAHistoryChatHistory() {
  return useQuery({
    queryKey: QA_HISTORY_CHAT_KEY,
    queryFn: () => qaHistoryApi.getExchanges(),
  });
}

export function useAskQAHistoryChat() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: QAHistoryChatRequest) => qaHistoryApi.postChat(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QA_HISTORY_CHAT_KEY }),
  });
}
