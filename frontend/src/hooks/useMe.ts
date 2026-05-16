import { useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';
import { useAuth } from '../contexts/AuthContext';

export type Tier = 'free' | 'pro' | 'studio';

export interface MeResponse {
  id: string;
  email: string;
  created_at: string;
  tier: Tier;
}

const ME_QUERY_KEY = ['auth', 'me'] as const;

/**
 * Fetch the current user from `/auth/me`. Returns the same shape the
 * backend ships, including `tier`. Cached for 30s; invalidate via
 * `useInvalidateMe()` after any mutation that affects tier (e.g.
 * subscription page upgrade).
 */
export function useMe() {
  const { isAuthenticated } = useAuth();
  return useQuery<MeResponse>({
    queryKey: ME_QUERY_KEY,
    queryFn: async () => {
      const { data } = await api.get<MeResponse>('/auth/me');
      return data;
    },
    enabled: isAuthenticated,
    staleTime: 30_000,
  });
}

export function useInvalidateMe() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ME_QUERY_KEY });
}
