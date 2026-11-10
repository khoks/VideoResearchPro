import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { jobsApi } from '../services/jobsApi';
import { ERRORS_SHOWN_HERE, queryErrorsMeta, type QueryLineOptions } from '../services/queryClient';
import type { JobCreate, JobProvenance, VideoApproval } from '../types/job';

/** In flight, these hold the first-run wizard's Back, steps and Skip, which would
 * otherwise close the line that says their failure (T-3.4.1.22). */
export const createJobKey = ['jobs', 'create'] as const;
export const approveJobKey = ['jobs', 'approve'] as const;

/** The runs page says a failed read; the studio's create dialog says
 * nothing, so only the page passes `inlineErrors` (T-3.4.1.26). */
export function useJobs(params?: { status?: string; limit?: number; offset?: number }, { inlineErrors }: QueryLineOptions = {}) {
  return useQuery({
    queryKey: ['jobs', params?.status ?? null, params?.limit ?? null, params?.offset ?? null],
    queryFn: () => jobsApi.list(params),
    refetchInterval: 10000,
    meta: queryErrorsMeta(inlineErrors),
  });
}

/** The run page says a failed first read in place of the run (`'load'`); the
 * channel page, the library and the wizard read a run's status and say
 * nothing, so they leave `inlineErrors` off (T-3.4.1.26). */
export function useJob(id: string | null, { inlineErrors }: QueryLineOptions = {}) {
  return useQuery({
    queryKey: ['job', id],
    queryFn: () => jobsApi.get(id!),
    enabled: !!id,
    refetchInterval: 5000,
    meta: queryErrorsMeta(inlineErrors),
  });
}

export function useJobVideos(jobId: string | null) {
  return useQuery({
    queryKey: ['jobVideos', jobId],
    queryFn: () => jobsApi.getVideos(jobId!),
    enabled: !!jobId,
  });
}

/**
 * `inlineErrors`: the caller says every failure on the page, so the global toast
 * stands aside (T-3.4.1.22, D-153 point 2). The first-run wizard passes it. The
 * submit form says only a full library in the form and leaves it off, so the
 * global toast says the rest.
 */
export function useCreateJob({ inlineErrors = false }: { inlineErrors?: boolean } = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: createJobKey,
    mutationFn: ({ data, provenance }: { data: JobCreate; provenance?: JobProvenance }) =>
      jobsApi.create(data, provenance),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
    meta: inlineErrors ? ERRORS_SHOWN_HERE : undefined,
  });
}

export function useApproveJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: approveJobKey,
    mutationFn: ({ id, data }: { id: string; data: VideoApproval }) => jobsApi.approve(id, data),
    onSuccess: (updatedJob, { id }) => {
      queryClient.setQueryData(['job', id], updatedJob);
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    // Both callers say a failure where the approval was pressed: the run's
    // approval section and the first-run wizard (T-3.4.1.22).
    meta: ERRORS_SHOWN_HERE,
  });
}

/**
 * A run that ended before the cancel reached it answers 400 with what it ended
 * as, and keeps that end (T-5.2.22). The global toast says those words; the run
 * is fetched again so the page shows the end the toast names, not a Cancel
 * button for a run that is over.
 */
export function useCancelJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => jobsApi.cancel(id),
    onSuccess: (updatedJob, id) => {
      queryClient.setQueryData(['job', id], updatedJob);
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: (_error, id) => {
      queryClient.invalidateQueries({ queryKey: ['job', id] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
  });
}

export function useDeleteJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => jobsApi.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  });
}
