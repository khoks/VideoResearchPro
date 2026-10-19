# M7 — Channel intelligence: plan

**Board:** [E-8.7](../initiatives.md#e-87--channel-intelligence-m7) · **Roadmap:** [M7](../feature-roadmap.md#m7--channel-intelligence-dashboard-) · **Research date:** 2026-10-19 · **Status:** recommendation.

## Problem

The user follows channels but cannot see what a channel *says* over time: its recurring topics, the concepts it keeps returning to, how often it publishes, what the user has asked about it. YouTube Studio and every analytics product measure audience, not content; that is the gap. The roadmap sketched word cloud, recurring topics, stance over time and a concept graph "as a new tab on the channel detail page".

## Verified current state (2026-10-18)

- **There is no channel detail page.** `/library` has a Channels tab rendering `ChannelRow`; the API has `GET /channels/{id}` and `GET /channels/{id}/videos` (tenant-scoped through `subscription_service` and visibility); nothing routes to a per-channel view. M7 must create one.
- Knowledge artifacts: `documents.extracted_knowledge_json` (`topics`, `concepts`, `events`, `facts`) and `knowledge_report_md`, present only where the user ran extraction (on demand, quota-metered: Free 10, Pro 200, Studio 2,000 per month).
- Stance / sentiment / framing: written to `source_metadata_json.classification` **only by social connectors** (`sources/{reddit,hn,mastodon,bluesky,podcast}` call `social_classify`); YouTube documents carry none. "Evolving stance over time" therefore has no data for the dominant source type.
- Transcripts: `transcript_cache` holds every document's segments; Chroma holds chunk embeddings retrievable with `collection.get(where={"video_id": {"$in": [...]}}, include=["embeddings"])`.
- `scikit-learn` is already installed: it is a core requirement of `sentence-transformers` 6.1.0, so TF-IDF and k-means cost no new dependency.
- Trust weight control: [S-7.1.1](../initiatives.md#s-711--make-source_weight-re-rank-retrieval) puts a weight control "on the channel page", which also does not exist yet; E-8.7's page is where it lands.

## Chosen approach

1. **Channel page** (S-8.7.1) at `/library/channels/:id`: header with subscribe and the E-7.1 weight control, the document list, and tabs (Documents, Intelligence). Links from `ChannelRow`, `VideoRow` and citation chips.
2. **Aggregate endpoint** (S-8.7.2) `GET /channels/{id}/intelligence` computed over the tenant's visible documents for the channel, materialised in `channel_intelligence_cache(channel_id, tenant_id, computed_at, payload_json)` by a Celery task on sync or on demand:
   - cadence per month and duration distribution from `published_at` and `duration_seconds`;
   - top topics and concepts with counts and the documents behind each, from `extracted_knowledge_json`; **coverage ratio** (documents with artifacts ÷ documents), and a call to action when coverage is low;
   - keyword cloud: TF-IDF over cached transcripts, top 60 terms (no library; `sklearn.feature_extraction.text.TfidfVectorizer`); YAKE is rejected (AGPL-3.0-or-later), BERTopic (MIT) drags hdbscan, umap, numba, pandas and plotly;
   - topic clusters: k-means or agglomerative clustering over the channel's chunk embeddings fetched from Chroma (no re-embedding), each cluster labelled by its top TF-IDF terms;
   - the user's Q&A exchanges that cite the channel (from stored references);
   - stance and sentiment timeline **only where classification exists**, bucketed by month or by a rolling window for sparse channels, otherwise omitted with an explanation.
3. **Tab UI** (S-8.7.3): cadence bars and the stance series as hand-rolled SVG (no chart library; the project's dataviz rules apply), the keyword cloud as inline-flex spans sized by `sqrt(count)` (real text, reflows, screen-reader friendly; `d3-cloud`, BSD-3-Clause, 2.9 kB gzipped, only if a spiral layout is wanted later), topic drill-down, an "Extract knowledge for all" batch action that respects the knowledge quota and shows the cost, and a concept graph panel reusing M9's component filtered to the channel.

## Alternatives rejected

| Option | Why not |
|---|---|
| `react-wordcloud` | Abandoned (2020, React 16 peer dependency). |
| BERTopic / HDBSCAN / UMAP | MIT and BSD but a heavy dependency tree for a per-channel summary; k-means over existing vectors is enough at this scale. |
| YAKE keyword extraction | AGPL-3.0-or-later (repository) / GPL (PyPI): copyleft either way. |
| Computing on every page view | Transcripts for 500 documents are megabytes; materialise. |
| Classifying stance for YouTube documents now | A new per-document LLM call across the whole library; out of scope here, filed as a question. |

## Schema deltas

`channel_intelligence_cache(channel_id, tenant_id, computed_at, payload_json)` with `UNIQUE(channel_id, tenant_id)`.

## API deltas

`GET /api/v1/channels/{id}/intelligence?refresh=`; `POST /api/v1/channels/{id}/extract-knowledge` (batch, quota-aware, returns a job-like progress handle on the existing WebSocket channel).

## Modules touched

`services/channel_intelligence_service.py` (new), `tasks/channel_tasks.py` (new), `models/channel_intelligence_cache.py`, `routers/channels.py`, `services/chroma_service.py` (embedding fetch helper), `frontend/src/pages/ChannelPage.tsx` (new), `routes/index.tsx`, `components/library/ChannelRow.tsx`, `VideoRow.tsx`, `components/citation/CitationLink.tsx`, `components/charts/*` (new SVG primitives), `services/channelsApi.ts`.

## Risks

- **Coverage.** The topic panels are only as good as knowledge-extraction coverage; the page must say so and offer the batch action rather than show an empty cloud.
- **Stance sparsity.** For YouTube channels the stance panel will be absent until a classification path exists for videos; do not fake it with sentiment over transcripts.
- **Tenant scoping.** Every aggregate runs over the tenant's visible documents; two users following the same channel can see different numbers, which is correct under [D-063](../decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31).
- **Compute time** on a 500-document channel (TF-IDF over tens of megabytes) belongs in the worker, never in the request.

## Test strategy

- Service: seeded documents with artifacts and classifications; counts, coverage ratio, cadence buckets, cloud terms, cluster labels; stance omitted when absent; isolation (visible-set scoping).
- Router: cache hit versus refresh; batch extraction respects quota (D-045) and dispatches through the mocked `.delay()`.
- Frontend: type-check; the page renders with and without artifacts; Playwright smoke.

## First PR (S-8.7.1)

The channel page itself with header, subscribe, documents list and links, plus the route. No aggregates. It is also where S-7.1.1's weight control lands, so it unblocks E-7.1's UI task.

## Open questions

1. Should stance classification be extended to YouTube documents (a per-document LLM call at ingest) so the timeline exists for the dominant source type? Cost scales with ingest; it is a separate decision.
2. Cache invalidation: on channel sync and on new knowledge artifacts (recommended), or only on demand?

## Sources (fetched 2026-10-19)

npm and Bundlephobia for `d3-cloud`, `react-wordcloud`, `wordcloud`; PyPI JSON for `sentence-transformers` 6.1.0 (`scikit-learn` in `requires_dist`), `keybert`, `yake` (and its repository LICENSE), `bertopic`, `hdbscan`, `umap-learn`; YouTube Studio analytics help. Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
