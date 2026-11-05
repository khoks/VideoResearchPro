import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { depthOf, type Depth } from '../utils/depth';

export type Tier = 'free' | 'pro' | 'studio';

export interface MeResponse {
  id: string;
  email: string;
  created_at: string;
  tier: Tier;
  /** S-8.10.1: set when the first-run wizard is finished. */
  onboarded_at?: string | null;
  /**
   * T-5.2.8 / D-111: whether this account operates the install (named in
   * ADMIN_EMAILS, or the first account registered when that is unset).
   * Only operators may switch tiers.
   */
  is_operator?: boolean;
  /** T-1.15.3.9: the depth this person's pages start from; null is Auto. */
  preferred_output_length?: string | null;
}

export const ME_QUERY_KEY = ['auth', 'me'] as const;

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

/**
 * T-1.15.3.9: the depth this person's pages start from, null for Auto.
 *
 * A subscriber to the `useMe` query, not a second fetch: `AppLayout` keeps that
 * query alive on every signed-in page, so this adds no request. Until it answers
 * the page is on Auto, and it moves to the preference if the reader has not
 * touched the control (`useDepthChoice`).
 */
export function usePreferredDepth(): Depth | null {
  const { data } = useQuery<MeResponse>({ queryKey: ME_QUERY_KEY, enabled: false });
  return depthOf(data?.preferred_output_length);
}

/** Save the default depth; null is Auto, which clears it. */
export function useSetPreferredDepth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (depth: Depth | null) => {
      const { data } = await api.patch<{ output_length: string | null }>('/auth/me/preferences', {
        output_length: depth ?? 'auto',
      });
      return data.output_length;
    },
    onSuccess: (saved) => {
      qc.setQueryData<MeResponse>(ME_QUERY_KEY, (me) => (me ? { ...me, preferred_output_length: saved } : me));
    },
  });
}

export function useInvalidateMe() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ME_QUERY_KEY });
}
