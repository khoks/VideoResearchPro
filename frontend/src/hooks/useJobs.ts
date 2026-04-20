import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { jobsApi } from '../services/jobsApi';
import type { JobCreate, VideoApproval } from '../types/job';

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

export function useCreateJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: JobCreate) => jobsApi.create(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  });
}

export function useApproveJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: VideoApproval }) => jobsApi.approve(id, data),
    onSuccess: (updatedJob, { id }) => {
      queryClient.setQueryData(['job', id], updatedJob);
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
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
