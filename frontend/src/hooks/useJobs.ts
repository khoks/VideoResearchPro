import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { jobsApi } from '../services/jobsApi';
import { ERRORS_SHOWN_HERE } from '../services/queryClient';
import type { JobCreate, JobProvenance, VideoApproval } from '../types/job';

/** In flight, these hold the first-run wizard's Back, steps and Skip, which would
 * otherwise close the line that says their failure (T-3.4.1.22). */
export const createJobKey = ['jobs', 'create'] as const;
export const approveJobKey = ['jobs', 'approve'] as const;

export function useJobs(params?: { status?: string; limit?: number; offset?: number }) {
  return useQuery({
    queryKey: ['jobs', params?.status ?? null, params?.limit ?? null, params?.offset ?? null],
    queryFn: () => jobsApi.list(params),
    refetchInterval: 10000,
  });
}

export function useJob(id: string | null) {
  return useQuery({
    queryKey: ['job', id],
    queryFn: () => jobsApi.get(id!),
    enabled: !!id,
    refetchInterval: 5000,
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

export function useCancelJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => jobsApi.cancel(id),
    onSuccess: (updatedJob, id) => {
      queryClient.setQueryData(['job', id], updatedJob);
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
