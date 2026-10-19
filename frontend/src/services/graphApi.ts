import api from './api';

/** `GET /library/graph` (S-8.9.1). Built from the documents this reader can
 * see (D-063): nothing of another reader's appears, and an empty library is
 * an empty graph. Ids are stable across requests. */
export type GraphNodeType = 'document' | 'channel' | 'topic' | 'exchange';
export type GraphEdgeType = 'published_by' | 'about' | 'cites' | 'co_occurs';

export interface GraphNode {
  /** `document:<id>`, `channel:<id>`, `topic:<lowercased label>`, `exchange:<job|library>:<id>`. */
  id: string;
  type: GraphNodeType;
  label: string;
  /** Degree in the whole graph, before the cap. */
  degree: number;
  meta: {
    document_id?: string;
    url?: string | null;
    source_type?: string | null;
    channel_id?: string | null;
    published_at?: string | null;
    documents?: number;
    kind?: 'job' | 'library';
    exchange_id?: string;
    job_id?: string | null;
  };
}

export interface GraphEdge {
  source: string;
  target: string;
  type: GraphEdgeType;
  weight: number;
}

export interface GraphCounts {
  documents: number;
  channels: number;
  topics: number;
  exchanges: number;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  total: GraphCounts;
  shown: GraphCounts;
  /** One paragraph describing the graph: the textual alternative to the canvas. */
  summary: string;
  focus: string | null;
}

/** Node types besides documents, which are always included. */
export type GraphExtraType = 'channel' | 'topic' | 'exchange';
export const GRAPH_EXTRA_TYPES: GraphExtraType[] = ['channel', 'topic', 'exchange'];

export interface GraphParams {
  focus?: string | null;
  depth?: number;
  shelfId?: string | null;
  channelId?: string | null;
  jobId?: string | null;
  /** Omitted means every type. */
  types?: GraphExtraType[] | null;
  limit?: number;
}

export const graphApi = {
  get: (p: GraphParams) =>
    api
      .get<GraphResponse>('/library/graph', {
        params: {
          focus: p.focus || undefined,
          depth: p.focus ? p.depth : undefined,
          shelf_id: p.shelfId || undefined,
          channel_id: p.channelId || undefined,
          job_id: p.jobId || undefined,
          // An empty list would read as "every type" server-side; ask for sources only.
          types: p.types ? (p.types.length ? p.types.join(',') : 'document') : undefined,
          limit: p.limit,
        },
      })
      .then(r => r.data),
};
