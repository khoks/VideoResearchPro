import { useQuery } from '@tanstack/react-query';
import type { AxiosError } from 'axios';
import { jobsApi } from '../services/jobsApi';
import type { ReportBody } from '../types/report';
import { reportDocumentBlob } from '../utils/reportDocument';

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

/**
 * The stored HTML report for the quick peek (T-8.8.1.5): fetched with the
 * bearer header, scripts blocked (`utils/reportDocument`), as a Blob the
 * modal frames through a blob: URL. Until then the iframe's `src` carried
 * the JWT as `?token=`.
 */
export function useReportDocument(jobId: string | null) {
  return useQuery<Blob, AxiosError<{ detail?: string }>>({
    queryKey: ['reportDocument', jobId],
    queryFn: async () => reportDocumentBlob(await jobsApi.getReport(jobId!)),
    enabled: !!jobId,
    staleTime: 5 * 60 * 1000,
    retry: (count, err) => err.response?.status !== 404 && count < 1,
  });
}
