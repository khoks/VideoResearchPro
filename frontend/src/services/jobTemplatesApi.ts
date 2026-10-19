import api from './api';
import type { JobType, OutputLength } from '../types/job';

/** The frozen half of a `JobCreate` (everything but the topic). */
export interface TemplateParameters {
  job_type: JobType;
  /** May contain `{{topic}}`, filled with the run's topic at submission. */
  search_instructions: string | null;
  num_videos: number;
  min_duration_minutes: number | null;
  max_duration_minutes: number | null;
  channel_type_filters: string[] | null;
  preferred_channels: string[] | null;
  output_length: OutputLength | null;
  visual_analysis: boolean;
  channel_list: string[] | null;
  videos_per_channel: number | null;
}

/** `JobTemplateResponse` (S-8.6.1). Built-ins have `builtin: true` and are read-only. */
export interface JobTemplate {
  id: string;
  name: string;
  description: string | null;
  job_type: JobType;
  builtin: boolean;
  builtin_key: string | null;
  version: number;
  parameters: TemplateParameters;
  /** What would stop the caller using it today (e.g. a tier cap). */
  problems: string[];
  created_at: string;
  updated_at: string;
}

export interface JobTemplateVersion {
  version: number;
  parameters: TemplateParameters;
  created_at: string;
}

export interface JobTemplateCreate {
  name: string;
  description?: string | null;
  parameters: TemplateParameters;
}

export interface JobTemplateUpdate {
  name?: string;
  description?: string | null;
  /** Different from the latest version → a new version. */
  parameters?: TemplateParameters;
}

export const jobTemplatesApi = {
  list: () => api.get<JobTemplate[]>('/job-templates').then(r => r.data),
  get: (id: string) => api.get<JobTemplate>(`/job-templates/${id}`).then(r => r.data),
  create: (body: JobTemplateCreate) => api.post<JobTemplate>('/job-templates', body).then(r => r.data),
  update: (id: string, body: JobTemplateUpdate) =>
    api.put<JobTemplate>(`/job-templates/${id}`, body).then(r => r.data),
  remove: (id: string) => api.delete(`/job-templates/${id}`).then(() => undefined),
  versions: (id: string) =>
    api.get<JobTemplateVersion[]>(`/job-templates/${id}/versions`).then(r => r.data),
  saveJobAsTemplate: (jobId: string, body: { name: string; description?: string | null }) =>
    api.post<JobTemplate>(`/jobs/${jobId}/save-as-template`, body).then(r => r.data),
};
