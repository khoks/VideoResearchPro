import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../contexts/AuthContext';
import { onboardingApi, type Onboarding, type OnboardingPatch } from '../services/onboardingApi';
import { ERRORS_SHOWN_HERE, queryErrorsMeta, type QueryLineOptions } from '../services/queryClient';

export const onboardingKey = ['auth', 'me', 'onboarding'] as const;

/** The first-run wizard's state (S-8.10.1). The wizard says a failed read;
 * the gate, the checklist, the submit form and the exports page say nothing,
 * so only the wizard passes `inlineErrors` (T-3.4.1.26). */
export function useOnboarding({ inlineErrors }: QueryLineOptions = {}) {
  const { isAuthenticated } = useAuth();
  return useQuery<Onboarding>({
    queryKey: onboardingKey,
    queryFn: () => onboardingApi.get(),
    enabled: isAuthenticated,
    staleTime: 30_000,
    meta: queryErrorsMeta(inlineErrors),
  });
}

/**
 * PATCH the state; the response is the fresh payload, so it replaces the cache.
 *
 * `inlineErrors`: the caller says every failure on the page, so the global toast
 * stands aside (T-3.4.1.22, D-153 point 2). The wizard passes it for the two
 * saves it says under their buttons, saving the channels and recording the
 * first run. Its other saves (a step, Skip, finishing) and the jobs page's
 * checklist show no line and leave it off.
 */
export function useUpdateOnboarding({ inlineErrors = false }: { inlineErrors?: boolean } = {}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: OnboardingPatch) => onboardingApi.patch(body),
    onSuccess: (data) => {
      qc.setQueryData(onboardingKey, data);
      if (data.onboarded_at) void qc.invalidateQueries({ queryKey: ['auth', 'me'], exact: true });
    },
    meta: inlineErrors ? ERRORS_SHOWN_HERE : undefined,
  });
}

/** The sidebar's "Getting started" link: while the wizard is unfinished and not skipped. */
export function useShowGettingStarted(): boolean {
  const { data } = useOnboarding();
  return !!data?.should_onboard;
}
