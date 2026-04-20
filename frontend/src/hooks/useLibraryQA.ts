import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { libraryQaApi } from '../services/libraryQaApi';
import type { LibraryClarifyRequest, LibraryQARequest } from '../types/qa';

const LIBRARY_QA_HISTORY_KEY = ['libraryQaHistory'] as const;

export function useLibraryQAHistory() {
  return useQuery({
    queryKey: LIBRARY_QA_HISTORY_KEY,
    queryFn: () => libraryQaApi.getHistory(),
  });
}

export function useAskLibraryQA() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: LibraryQARequest) => libraryQaApi.ask(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: LIBRARY_QA_HISTORY_KEY }),
  });
}

export function useClarifyLibraryQA() {
  return useMutation({
    mutationFn: (data: LibraryClarifyRequest) => libraryQaApi.clarify(data),
  });
}
