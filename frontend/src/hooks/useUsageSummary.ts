import { useQuery } from '@tanstack/react-query';
import { usageApi } from '../services/usageApi';

/** The signed-in user's usage today and over the last 30 days (E-5.2). */
export function useUsageSummary() {
  return useQuery({
    queryKey: ['usageSummary'],
    queryFn: () => usageApi.get(),
    staleTime: 30_000,
  });
}
