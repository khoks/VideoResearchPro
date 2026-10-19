import { useQuery } from '@tanstack/react-query';
import type { AxiosError } from 'axios';
import { jobsApi } from '../services/jobsApi';
import type { ReportBody } from '../types/report';

/**
 * The report body for the native reader (S-8.8.1). Fetched with the bearer
 * header like every other API call — no `?token=` anywhere.
 *
 * A 404 means "no report for this run" and is final; everything else retries
 * once.
 */
export function useReportBody(jobId: string | null) {
  return useQuery<ReportBody, AxiosError<{ detail?: string }>>({
    queryKey: ['reportBody', jobId],
    queryFn: () => jobsApi.getReportBody(jobId!),
    enabled: !!jobId,
    staleTime: 5 * 60 * 1000,
    retry: (count, err) => err.response?.status !== 404 && count < 1,
  });
}
