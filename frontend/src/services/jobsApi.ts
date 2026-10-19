import api from './api';
import type { Job, JobCreate, VideoApproval } from '../types/job';
import type { Video } from '../types/video';
import type { ReportBody } from '../types/report';

export const jobsApi = {
  create: (data: JobCreate) => api.post<Job>('/jobs', data).then(r => r.data),
  list: (params?: { status?: string; limit?: number; offset?: number }) =>
    api.get<Job[]>('/jobs', { params }).then(r => r.data),
  get: (id: string) => api.get<Job>(`/jobs/${id}`).then(r => r.data),
  approve: (id: string, data: VideoApproval) => api.put<Job>(`/jobs/${id}/approve`, data).then(r => r.data),
  cancel: (id: string) => api.post<Job>(`/jobs/${id}/cancel`).then(r => r.data),
  delete: (id: string) => api.delete(`/jobs/${id}`),
  getVideos: (id: string) => api.get<Video[]>(`/jobs/${id}/videos`).then(r => r.data),
  getReport: (id: string) => api.get<string>(`/jobs/${id}/report`).then(r => r.data),
  /** S-8.8.1: reader payload `{title, html, statistics}` under header auth only. */
  getReportBody: (id: string) => api.get<ReportBody>(`/jobs/${id}/report/body`).then(r => r.data),
};
