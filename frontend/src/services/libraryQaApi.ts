import api from './api';
import type {
  ClarifyResponse,
  LibraryClarifyRequest,
  LibraryQAExchange,
  LibraryQARequest,
} from '../types/qa';

export const libraryQaApi = {
  getHistory: () =>
    api.get<LibraryQAExchange[]>('/library/qa').then(r => r.data),
  ask: (data: LibraryQARequest) =>
    api.post<LibraryQAExchange>('/library/qa', data).then(r => r.data),
  clarify: (data: LibraryClarifyRequest) =>
    api.post<ClarifyResponse>('/library/qa/clarify', data).then(r => r.data),
};
