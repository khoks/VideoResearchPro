import { useQuery } from '@tanstack/react-query';
import { usageApi } from '../services/usageApi';
import { ERRORS_SHOWN_HERE } from '../services/queryClient';

/** The signed-in user's usage today and over the last 30 days (E-5.2). Its
 * one caller says a failed load on the page (T-3.4.1.26). */
export function useUsageSummary() {
  return useQuery({
    queryKey: ['usageSummary'],
    queryFn: () => usageApi.get(),
    staleTime: 30_000,
    meta: ERRORS_SHOWN_HERE,
  });
}
