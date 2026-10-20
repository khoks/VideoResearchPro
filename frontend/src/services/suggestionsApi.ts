import api from './api';

/** `Suggestion` (S-8.4.1). `history` items were asked by this reader elsewhere. */
export interface Suggestion {
  question: string;
  rationale: string;
  source: 'generated' | 'history';
  origin: { source: string | null; exchange_id: string | null; job_id: string | null } | null;
}

export interface SuggestionsResponse {
  context: string;
  suggestions: Suggestion[];
  cached: boolean;
  generated: boolean;
}

/** `job:<id>`, `document:<id>` or `library`. */
export type SuggestionContext = `job:${string}` | `document:${string}` | 'library';

export const suggestionsApi = {
  get: (context: SuggestionContext, signal?: AbortSignal) =>
    api.get<SuggestionsResponse>('/suggestions', { params: { context }, signal }).then((r) => r.data),
  feedback: (body: { context: SuggestionContext; question: string; action: 'fill' | 'ask'; source?: Suggestion['source'] }) =>
    api.post('/suggestions/feedback', body).then(() => undefined),
};
