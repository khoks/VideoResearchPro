import api from './api';

export interface KnowledgeArtifact {
  topics: string[];
  concepts: string[];
  events: string[];
  facts: string[];
  knowledge_report_md: string;
}

export const knowledgeApi = {
  // GET returns 404 when the video has not been extracted yet. The caller
  // (useKnowledge hook) catches and surfaces that as "not yet extracted"
  // rather than a generic error toast.
  get: (videoId: string) =>
    api.get<KnowledgeArtifact>(`/videos/${videoId}/knowledge`).then(r => r.data),
  extract: (videoId: string, force = false) =>
    api
      .post<KnowledgeArtifact>(
        `/videos/${videoId}/extract-knowledge`,
        null,
        { params: force ? { force: true } : undefined },
      )
      .then(r => r.data),
};
