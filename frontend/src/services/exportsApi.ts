// URL builders for the dataset export endpoints.
//
// These endpoints stream JSONL files for download. The browser can't attach
// the Authorization header when navigating (<a href>, window.open, etc.), so
// the backend also accepts a scoped `?token=<jwt>` query param on these
// download-only routes. See the report endpoint at
// backend/app/routers/qa.py:25-40 for the same pattern.

const BASE = '/api/v1/exports';

function withToken(path: string, token: string | null): string {
  if (!token) return path;
  return `${path}?token=${encodeURIComponent(token)}`;
}

export const exportsApi = {
  getQaOpenaiUrl: (token: string | null): string =>
    withToken(`${BASE}/qa-dataset/openai.jsonl`, token),

  getQaTupleUrl: (token: string | null): string =>
    withToken(`${BASE}/qa-dataset/tuple.jsonl`, token),

  getKnowledgeOpenaiUrl: (token: string | null): string =>
    withToken(`${BASE}/knowledge-dataset/openai.jsonl`, token),

  getKnowledgeTupleUrl: (token: string | null): string =>
    withToken(`${BASE}/knowledge-dataset/tuple.jsonl`, token),
};
