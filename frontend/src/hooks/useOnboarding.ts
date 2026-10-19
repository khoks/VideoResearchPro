import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../contexts/AuthContext';
import { onboardingApi, type Onboarding, type OnboardingPatch } from '../services/onboardingApi';

export const onboardingKey = ['auth', 'me', 'onboarding'] as const;

/** The first-run wizard's state (S-8.10.1). */
export function useOnboarding() {
  const { isAuthenticated } = useAuth();
  return useQuery<Onboarding>({
    queryKey: onboardingKey,
    queryFn: () => onboardingApi.get(),
    enabled: isAuthenticated,
    staleTime: 30_000,
  });
}

/** PATCH the state; the response is the fresh payload, so it replaces the cache. */
export function useUpdateOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: OnboardingPatch) => onboardingApi.patch(body),
    onSuccess: (data) => {
      qc.setQueryData(onboardingKey, data);
      if (data.onboarded_at) void qc.invalidateQueries({ queryKey: ['auth', 'me'], exact: true });
    },
  });
}

/** The sidebar's "Getting started" link: while the wizard is unfinished and not skipped. */
export function useShowGettingStarted(): boolean {
  const { data } = useOnboarding();
  return !!data?.should_onboard;
}
