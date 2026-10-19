import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  jobTemplatesApi,
  type JobTemplateCreate,
  type JobTemplateUpdate,
} from '../services/jobTemplatesApi';

export const templatesKey = ['jobTemplates'] as const;

export function useJobTemplates() {
  return useQuery({
    queryKey: templatesKey,
    queryFn: () => jobTemplatesApi.list(),
    staleTime: 30_000,
  });
}

export function useTemplateVersions(id: string | null) {
  return useQuery({
    queryKey: ['jobTemplateVersions', id],
    queryFn: () => jobTemplatesApi.versions(id!),
    enabled: !!id,
  });
}

export function useCreateTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: JobTemplateCreate) => jobTemplatesApi.create(body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: templatesKey }),
  });
}

export function useUpdateTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: JobTemplateUpdate }) =>
      jobTemplatesApi.update(id, body),
    onSuccess: (_t, { id }) => {
      void qc.invalidateQueries({ queryKey: templatesKey });
      void qc.invalidateQueries({ queryKey: ['jobTemplateVersions', id] });
    },
  });
}

export function useDeleteTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => jobTemplatesApi.remove(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: templatesKey }),
  });
}

export function useSaveJobAsTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, name, description }: { jobId: string; name: string; description?: string | null }) =>
      jobTemplatesApi.saveJobAsTemplate(jobId, { name, description }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: templatesKey }),
  });
}
