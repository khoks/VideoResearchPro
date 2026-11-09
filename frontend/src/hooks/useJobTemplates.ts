import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  jobTemplatesApi,
  type JobTemplateCreate,
  type JobTemplateUpdate,
} from '../services/jobTemplatesApi';
import { ERRORS_SHOWN_HERE } from '../services/queryClient';

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
    // Its one caller, the submit form's "Save as template", says a failure in
    // the dialog (T-3.4.1.22).
    meta: ERRORS_SHOWN_HERE,
  });
}

/**
 * `inlineErrors`: the caller says every failure on the page, so the global toast
 * stands aside (T-3.4.1.22, D-153 point 2). The templates page's rename dialog
 * passes it; the submit form's "Save changes" shows no line and leaves it off.
 */
export function useUpdateTemplate({ inlineErrors = false }: { inlineErrors?: boolean } = {}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: JobTemplateUpdate }) =>
      jobTemplatesApi.update(id, body),
    onSuccess: (_t, { id }) => {
      void qc.invalidateQueries({ queryKey: templatesKey });
      void qc.invalidateQueries({ queryKey: ['jobTemplateVersions', id] });
    },
    meta: inlineErrors ? ERRORS_SHOWN_HERE : undefined,
  });
}

export function useDeleteTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => jobTemplatesApi.remove(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: templatesKey }),
    // Its one caller, the template's card, says a failure on the card (T-3.4.1.18).
    meta: ERRORS_SHOWN_HERE,
  });
}

export function useSaveJobAsTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, name, description }: { jobId: string; name: string; description?: string | null }) =>
      jobTemplatesApi.saveJobAsTemplate(jobId, { name, description }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: templatesKey }),
    // Its one caller, a run's "Save as template", says a failure in the dialog
    // (T-3.4.1.22).
    meta: ERRORS_SHOWN_HERE,
  });
}
