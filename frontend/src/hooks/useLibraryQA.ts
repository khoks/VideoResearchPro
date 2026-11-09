import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { libraryQaApi } from '../services/libraryQaApi';
import { ERRORS_SHOWN_HERE } from '../services/queryClient';
import { rememberCutOff } from '../stores/qaCutOffStore';
import type { LibraryClarifyRequest, LibraryQARequest } from '../types/qa';

const LIBRARY_QA_HISTORY_KEY = ['libraryQaHistory'] as const;

export function useLibraryQAHistory() {
  return useQuery({
    queryKey: LIBRARY_QA_HISTORY_KEY,
    queryFn: () => libraryQaApi.getHistory(),
  });
}

/**
 * `inlineErrors`: the caller shows every failure where it was asked, so the
 * global toast stands aside (T-3.4.1.18, D-153 point 2). The Echo bubble's ask
 * turns pass it. The library Q&A page shows none of its own and leaves it off.
 */
export function useAskLibraryQA({ inlineErrors = false }: { inlineErrors?: boolean } = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: LibraryQARequest) => libraryQaApi.ask(data),
    onSuccess: (exchange, request) => {
      rememberCutOff(exchange, request);
      return queryClient.invalidateQueries({ queryKey: LIBRARY_QA_HISTORY_KEY });
    },
    meta: inlineErrors ? ERRORS_SHOWN_HERE : undefined,
  });
}

export function useClarifyLibraryQA() {
  return useMutation({
    mutationFn: (data: LibraryClarifyRequest) => libraryQaApi.clarify(data),
  });
}
