import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { accountSecurityApi } from '../services/accountSecurityApi';

/**
 * Reads for the account security page. Its writes (revoke, two-step setup)
 * call `accountSecurityApi` directly rather than through `useMutation`: the
 * app's mutation cache toasts every failure, and these forms say what went
 * wrong where the reader typed (a wrong code, an expired step).
 */

export const SESSIONS_KEY = ['auth', 'sessions'] as const;
export const MFA_KEY = ['auth', 'mfa'] as const;
export const ACTIVITY_KEY = ['auth', 'activity'] as const;

export function useSessions() {
  return useQuery({ queryKey: SESSIONS_KEY, queryFn: accountSecurityApi.sessions });
}

export function useAccountActivity(page: number) {
  return useQuery({
    queryKey: [...ACTIVITY_KEY, page],
    queryFn: () => accountSecurityApi.activity(page),
    placeholderData: keepPreviousData,
  });
}

export function useMfaStatus() {
  return useQuery({ queryKey: MFA_KEY, queryFn: accountSecurityApi.mfaStatus });
}

/** Re-read what a write changed. Every write here adds an activity row too. */
export function useRefreshSecurity() {
  const qc = useQueryClient();
  return (...keys: ReadonlyArray<readonly string[]>) =>
    Promise.all([...keys, ACTIVITY_KEY].map((queryKey) => qc.invalidateQueries({ queryKey })));
}
