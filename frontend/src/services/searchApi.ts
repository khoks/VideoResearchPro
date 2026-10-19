import api from './api';

// Mirrors backend/app/schemas/search.py (S-8.2.1).

export type SearchType = 'jobs' | 'documents' | 'channels' | 'qa' | 'knowledge';

export interface SearchItem {
  id: string;
  title: string;
  subtitle: string;
  /** A frontend route; the palette navigates to it as-is. */
  href: string;
  score: number;
}

export interface SearchGroup {
  type: SearchType;
  items: SearchItem[];
}

export interface SearchResponse {
  q: string;
  backend: 'fts5' | 'like';
  groups: SearchGroup[];
}

export const searchApi = {
  /** `signal` lets React Query cancel a superseded request (T-8.2.2.3). */
  search: (q: string, signal?: AbortSignal, limit = 5) =>
    api.get<SearchResponse>('/search', { params: { q, limit }, signal }).then((r) => r.data),
};
