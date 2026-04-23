import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import { knowledgeApi, type KnowledgeArtifact } from '../services/knowledgeApi';

// 404 from GET /videos/{id}/knowledge is the documented "not yet extracted"
// signal — treat it as a null artifact rather than a query error so the UI
// can render the "Generate" affordance instead of an error state.
export function useKnowledge(videoId: string | null, enabled = true) {
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
  });
}

// Error toasts are handled globally by MutationCache.onError in App.tsx,
// so no local onError is needed.
export function useExtractKnowledge(videoId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (opts?: { force?: boolean }) => knowledgeApi.extract(videoId, opts?.force),
    onSuccess: (data) => {
      queryClient.setQueryData(['knowledge', videoId], data);
    },
  });
}
