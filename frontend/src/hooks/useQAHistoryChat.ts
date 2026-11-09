import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { qaHistoryApi } from '../services/qaHistoryApi';
import { ERRORS_SHOWN_HERE } from '../services/queryClient';
import type { QAHistoryChatRequest } from '../types/qa';

const QA_HISTORY_CHAT_KEY = ['qaHistoryChat'] as const;

export function useQAHistoryChatHistory() {
  return useQuery({
    queryKey: QA_HISTORY_CHAT_KEY,
    queryFn: () => qaHistoryApi.getExchanges(),
  });
}

/**
 * `inlineErrors`: the caller shows every failure where it was asked, so the
 * global toast stands aside (T-3.4.1.18, D-153 point 2). The Echo bubble's ask
 * turns pass it. The Q&A history page shows none of its own and leaves it off.
 */
export function useAskQAHistoryChat({ inlineErrors = false }: { inlineErrors?: boolean } = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: QAHistoryChatRequest) => qaHistoryApi.postChat(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QA_HISTORY_CHAT_KEY }),
    meta: inlineErrors ? ERRORS_SHOWN_HERE : undefined,
  });
}
