import api from './api';
import type { Depth } from '../utils/depth';

export interface KnowledgeArtifact {
  topics: string[];
  concepts: string[];
  events: string[];
  facts: string[];
  knowledge_report_md: string;
  knowledge_extracted_at?: string | null;
  // S-8.8.3: the source the artifact is about (absent from older backends).
  video_id?: string | null;
  document_id?: string | null;
  source_type?: string;
  title?: string | null;
  channel_name?: string | null;
  url?: string | null;
  published_at?: string | null;
  /** S-1.15.3: the depth the report was written at; null when none was asked for. */
  output_length?: Depth | null;
  /** T-1.15.3.8: the report stopped at its token budget. False or absent otherwise. */
  report_cut_off?: boolean;
}

export const knowledgeApi = {
  // GET returns 404 when the video has not been extracted yet. The caller
  // (useKnowledge hook) catches and surfaces that as "not yet extracted"
  // rather than a generic error toast.
  get: (videoId: string) =>
    api.get<KnowledgeArtifact>(`/videos/${videoId}/knowledge`).then(r => r.data),
  // S-1.15.3: `depth` goes as `output_length` only when one was chosen, so a
  // report with no preference is the same request as before.
  extract: (videoId: string, force = false, depth: Depth | null = null) => {
    const params: Record<string, string | boolean> = {};
    if (force) params.force = true;
    if (depth) params.output_length = depth;
    return api
      .post<KnowledgeArtifact>(
        `/videos/${videoId}/extract-knowledge`,
        null,
        { params: Object.keys(params).length > 0 ? params : undefined },
      )
      .then(r => r.data);
  },
};
