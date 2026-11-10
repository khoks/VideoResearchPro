import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { accountSecurityApi } from '../services/accountSecurityApi';
import { ERRORS_SHOWN_HERE, queryErrorsMeta, type QueryLineOptions } from '../services/queryClient';

/**
 * Reads for the account security page. Its writes (revoke, two-step setup)
 * call `accountSecurityApi` directly rather than through `useMutation`: the
 * app's mutation cache toasts every failure, and these forms say what went
 * wrong where the reader typed (a wrong code, an expired step).
 */

export const SESSIONS_KEY = ['auth', 'sessions'] as const;
export const MFA_KEY = ['auth', 'mfa'] as const;
export const ACTIVITY_KEY = ['auth', 'activity'] as const;

// Each card says its read's failure in place of what it would show, so the
// toast stands aside (T-3.4.1.26). The two-step card shows its line only when
// no setup step is open, so it says when.

export function useSessions() {
  return useQuery({ queryKey: SESSIONS_KEY, queryFn: accountSecurityApi.sessions, meta: ERRORS_SHOWN_HERE });
}

export function useAccountActivity(page: number) {
  return useQuery({
    queryKey: [...ACTIVITY_KEY, page],
    queryFn: () => accountSecurityApi.activity(page),
    placeholderData: keepPreviousData,
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useMfaStatus({ inlineErrors }: QueryLineOptions = {}) {
  return useQuery({ queryKey: MFA_KEY, queryFn: accountSecurityApi.mfaStatus, meta: queryErrorsMeta(inlineErrors) });
}

/** Re-read what a write changed. Every write here adds an activity row too. */
export function useRefreshSecurity() {
  const qc = useQueryClient();
  return (...keys: ReadonlyArray<readonly string[]>) =>
    Promise.all([...keys, ACTIVITY_KEY].map((queryKey) => qc.invalidateQueries({ queryKey })));
}
