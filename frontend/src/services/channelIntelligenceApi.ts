import api from './api';

/** `GET /channels/{id}/intelligence` (S-8.7.2). Every figure is over the
 * documents of the channel this reader can see (D-063). */
export interface DocumentRef {
  id: string;
  title: string;
  url: string | null;
}

export interface LabelCount {
  label: string;
  documents: number;
  examples: DocumentRef[];
}

export interface MonthCounts {
  month: string;
  counts: Record<string, number>;
}

export interface ChannelIntelligence {
  channel_id: string;
  computed_at: string;
  cached: boolean;
  coverage: {
    documents: number;
    with_knowledge: number;
    without_knowledge: number;
    ratio: number;
    with_transcript: number;
    /** No knowledge report yet, transcript cached: what the batch runs over. */
    extractable: DocumentRef[];
  };
  cadence: { months: { month: string; count: number }[]; undated: number };
  durations: {
    buckets: { label: string; min_minutes: number; max_minutes: number | null; count: number }[];
    unknown: number;
    median_minutes: number | null;
  };
  topics: LabelCount[];
  concepts: LabelCount[];
  keywords: { term: string; weight: number; documents: number }[];
  stance: { stance: MonthCounts[]; sentiment: MonthCounts[]; classified_documents: number } | null;
  /** Why a panel is empty or partial, keyed by panel. */
  notes: Record<string, string>;
  qa: {
    exchanges: number;
    most_cited: LabelCount[];
    recent: { id: string; kind: 'job' | 'library'; question: string; created_at: string | null; job_id: string | null }[];
  };
}

export const channelIntelligenceApi = {
  get: (channelId: string, refresh = false) =>
    api
      .get<ChannelIntelligence>(`/channels/${channelId}/intelligence`, {
        params: refresh ? { refresh: true } : undefined,
      })
      .then(r => r.data),
};
