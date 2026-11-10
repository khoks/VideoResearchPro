import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import { knowledgeApi, type KnowledgeArtifact } from '../services/knowledgeApi';
import type { Depth } from '../utils/depth';
import { queryErrorsMeta, type QueryLineOptions } from '../services/queryClient';

// 404 from GET /videos/{id}/knowledge is the documented "not yet extracted"
// signal — treat it as a null artifact rather than a query error so the UI
// can render the "Generate" affordance instead of an error state.
//
// The reader says any other failure on its page; the drawer says it only in
// place of a report, and only while extraction is on. Each passes
// `inlineErrors` for what it shows (T-3.4.1.26).
export function useKnowledge(videoId: string | null, enabled = true, { inlineErrors }: QueryLineOptions = {}) {
  return useQuery<KnowledgeArtifact | null>({
    queryKey: ['knowledge', videoId],
    queryFn: async () => {
      try {
        return await knowledgeApi.get(videoId!);
      } catch (err) {
        if (axios.isAxiosError(err) && err.response?.status === 404) return null;
        throw err;
      }
    },
    enabled: !!videoId && enabled,
    staleTime: 60_000,
    meta: queryErrorsMeta(inlineErrors),
  });
}

// Error toasts are handled globally by MutationCache.onError in App.tsx,
// so no local onError is needed.
export function useExtractKnowledge(videoId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (opts?: { force?: boolean; depth?: Depth | null }) =>
      knowledgeApi.extract(videoId, opts?.force, opts?.depth ?? null),
    onSuccess: (data) => {
      queryClient.setQueryData(['knowledge', videoId], data);
    },
  });
}
