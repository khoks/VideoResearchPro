import api from './api';
import type { ClarifyRequest, ClarifyResponse, QAExchange, QARequest } from '../types/qa';

export const qaApi = {
  ask: (jobId: string, data: QARequest) =>
    api.post<QAExchange>(`/jobs/${jobId}/qa`, data).then(r => r.data),
  getHistory: (jobId: string) =>
    api.get<QAExchange[]>(`/jobs/${jobId}/qa`).then(r => r.data),
  clarify: (jobId: string, data: ClarifyRequest) =>
    api.post<ClarifyResponse>(`/jobs/${jobId}/qa/clarify`, data).then(r => r.data),
};
