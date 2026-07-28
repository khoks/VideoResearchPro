# Pratidhvani — System Architecture

**Status:** current as of 2026-04-24. Brand-name forward; the codebase still ships under `videoresearchpro` package paths and Chroma collection names — see [feature-roadmap.md](feature-roadmap.md) §Rebrand-asset-rollout for the rename plan.

This document is the single source of truth for **how the running system is wired**. The vision (why it exists) lives in [vision.md](vision.md). The future shape (multi-source ingest, Author Studio, Personal Brain, SaaS) lives in [feature-roadmap.md](feature-roadmap.md), [source-types.md](source-types.md), [personal-brain.md](personal-brain.md), and [saas-roadmap.md](saas-roadmap.md). API endpoints live in [api-reference.md](api-reference.md). Page-level UI lives in [ui-pages.md](ui-pages.md). This file owns: process topology, data model, request lifecycles, agent pipelines, and the cross-cutting concerns that bind them.

---

## High-level topology

```
┌──────────────────────────────────────┐         ┌────────────────────────────────────────┐
│   Frontend (React + Vite)            │         │   Backend (FastAPI, Uvicorn)           │
│                                      │──REST──▶│   Routers → Services → SQLAlchemy      │
│   React Query ─── Zustand            │         │                                        │
│        ▲                             │◀──WS────│   WebSocket Manager (Redis sub)        │
│        │ cache update                │         │   LLM startup smoke (lifespan)         │
│   useJobProgress hook                │         └────────┬───────────────┬───────────────┘
│   wsClient with reconnect            │                  │ .delay()      │ read/write
└──────────────────────────────────────┘                  ▼               ▼
                                              ┌──────────────────┐  ┌──────────────────┐
                                              │ Celery Worker     │  │ SQLite           │
                                              │ (Redis broker)    │  │ (data/*.db)      │
                                              │ ┌───────────────┐ │  └──────────────────┘
                                              │ │ YouTube svc   │ │
                                              │ │ ChromaDB svc  │ │  ┌──────────────────┐
                                              │ │ LangGraph     │ │  │ ChromaDB         │
                                              │ │  ▸ Search     │◀┼─▶│  ▸ transcripts   │
                                              │ │  ▸ Report     │ │  │  ▸ qa_library    │
                                              │ │  ▸ Q&A        │ │  └──────────────────┘
                                              │ │  ▸ Knowledge  │ │
                                              │ │  ▸ Q&A History│ │  ┌──────────────────┐
                                              │ └───────────────┘ │  │ Redis            │
                                              │      │ publish     │  │  ▸ db0 pub/sub   │
                                              │      ▼             │  │  ▸ db1 broker   │
                                              │  Redis Pub/Sub     │◀─│  ▸ db2 results  │
                                              │  job_progress:*    │  └──────────────────┘
                                              └──────────────────┘
```

Three processes run side-by-side in development: the FastAPI app (`uvicorn`), the Celery worker (`celery -A app.tasks.celery_app worker --pool=solo`), and Redis (Windows service via winget). SQLite and ChromaDB are file-backed under `data/`. The frontend is a separate Vite dev server that proxies API calls to the backend.

Production targets the same shape, with SQLite swapped for Postgres and ChromaDB hosted (or pgvector); see [saas-roadmap.md](saas-roadmap.md).

---

## Process responsibilities

### FastAPI app (`uvicorn app.main:app`)

- Serves the REST API and the WebSocket endpoint.
- Holds the only SQLAlchemy engine that handles request-time queries.
- On startup (FastAPI lifespan):
  - Creates `data/` directories (DB, ChromaDB, reports).
  - Creates SQLAlchemy tables (idempotent; Alembic migrations are the source of truth, but `Base.metadata.create_all` is the dev fallback).
  - Runs `services/llm_smoke.run_startup_probes` — see "LLM smoke + fail-soft" below.
- On shutdown: flushes any pending Chroma writes, closes the embedding model, releases Redis connections.
- Does **not** run Celery tasks itself. It only `.delay()`-dispatches them.

### Celery worker (`celery -A app.tasks.celery_app worker --pool=solo`)

- Runs all long-running orchestration: search, transcript fetch, embedding, report generation, knowledge extraction.
- Has its own SQLAlchemy session factory (created per task) so request-side and worker-side don't share connections.
- Publishes progress events to Redis pub/sub (`job_progress:{job_id}`) at every phase boundary.
- On Windows, **must use `--pool=solo`** because the multiprocessing prefork pool doesn't work cleanly with our embedding model + ChromaDB locks.
- Does **not** run the LLM smoke check. Task-time LLM failures surface on the Jobs page via the worker's progress publisher.
- A backfill runs once per worker startup that idempotently upserts every existing row from `qa_exchanges`, `library_qa_exchanges`, and `qa_history_exchanges` into the `qa_library_global` Chroma collection.

### Redis

Three logical databases on the same instance:

- **db0** — Pub/sub channel for progress events (`job_progress:{job_id}`).
- **db1** — Celery broker (queue of pending tasks).
- **db2** — Celery result backend (task return values).

### SQLite

`data/videoresearchpro.db` (env `DATABASE_URL`). All structured state: users, jobs, documents (formerly `videos`; renamed in L1 PR 4), channels, transcript cache, Q&A exchanges, knowledge artifact metadata. Alembic migrations under `backend/alembic/`.

### ChromaDB

`data/chroma/` (env-overridable). Two collections:

- **`videoresearchpro_global`** — chunked transcripts of every ingested video. Single collection across all jobs. Per-job scoping is a metadata filter at query time.
- **`qa_library_global`** — every Q&A exchange (job-scoped, library-scoped, history-chat) as a single concatenated `question + answer` document — not chunked.

Chunks use the multilingual embedder `paraphrase-multilingual-MiniLM-L12-v2` (SentenceTransformer, CPU). No paid embedding API.

---

## Backend layout

```
backend/
├── app/
│   ├── main.py                  # FastAPI app, CORS, lifespan (tables, dirs, LLM smoke)
│   ├── config.py                # Pydantic Settings (reads .env)
│   ├── database.py              # SQLAlchemy engine + SessionLocal
│   ├── dependencies.py          # DI: get_db, get_redis, get_current_user
│   ├── routers/
│   │   ├── auth.py              # /auth: register, login, me
│   │   ├── jobs.py              # /jobs: CRUD + approve + cancel + delete
│   │   ├── qa.py                # /jobs/{id}/qa, /jobs/{id}/report, clarify
│   │   ├── library.py           # /library/qa, /library/videos
│   │   ├── channels.py          # /channels CRUD + subscribe + sync
│   │   ├── knowledge.py         # /videos/{id}/extract-knowledge, /knowledge
│   │   ├── qa_history.py        # /qa-history/chat, /qa-history/exchanges
│   │   ├── exports.py           # /exports/qa-dataset, /exports/knowledge-dataset
│   │   ├── admin.py             # /admin/* — power-user endpoints behind auth
│   │   ├── health.py            # /health (overall + LLM detail)
│   │   └── ws.py                # /ws/jobs (multiplexed progress)
│   ├── models/
│   │   ├── user.py              # User (email, hashed_password, created_at)
│   │   ├── job.py               # Job (UUID PK, status, type, JSON fields)
│   │   ├── document.py          # Document (global, deduped — renamed from video.py in L1 PR 4)
│   │   ├── job_video.py         # job ↔ document join with approval flag
│   │   ├── channel.py           # Channels (subscribed, last_synced_at)
│   │   ├── transcript_cache.py  # cached raw transcript, PK = document_id (E-1.10)
│   │   ├── qa_exchange.py       # job-scoped Q&A
│   │   ├── library_qa_exchange.py  # library-wide Q&A
│   │   ├── qa_history_exchange.py  # meta-chat across all Q&A
│   │   └── api_quota_log.py     # YouTube + LLM call accounting
│   ├── schemas/                 # Pydantic models for every router
│   ├── services/
│   │   ├── auth_service.py      # JWT issue/verify, password hashing (bcrypt)
│   │   ├── job_service.py       # CRUD + concurrent-job-limit enforcement
│   │   ├── youtube_service.py   # YouTube Data API v3, transcripts, Whisper fallback, rate limiting
│   │   ├── chroma_service.py    # PersistentClient singleton, collection CRUD
│   │   ├── embedding_service.py # paraphrase-multilingual-MiniLM-L12-v2
│   │   ├── progress_service.py  # Redis pub/sub publisher
│   │   ├── report_service.py    # HTML report file I/O
│   │   ├── dataset_service.py   # streaming JSONL exports for fine-tune
│   │   ├── quota_service.py     # YouTube API quota tracking + soft cap
│   │   ├── llm_routing.py       # USE_CASE_REGISTRY + resolve_config
│   │   ├── llm_service.py       # get_llm(use_case) factory
│   │   └── llm_smoke.py         # startup probes + LLMStatus singleton
│   ├── agents/
│   │   ├── state.py             # TypedDict states per agent
│   │   ├── search_agent.py      # topic → query plan → searches → ranked list
│   │   ├── report_agent.py      # transcripts → map-reduce → HTML
│   │   ├── qa_agent.py          # question → retrieve → refine → answer + citations
│   │   ├── qa_history_agent.py  # meta-chat across qa_library_global
│   │   ├── knowledge_agent.py   # transcript → batched extract → synthesized MD
│   │   ├── prompts/             # prompt templates per agent
│   │   └── tools/               # @tool functions (youtube_search, rag_search)
│   ├── tasks/
│   │   ├── celery_app.py        # Celery config; autodiscover related_name="job_tasks"
│   │   └── job_tasks.py         # execute_topic_job, execute_channel_job,
│   │                            #   execute_subscription_job, resume_after_approval
│   ├── websocket/
│   │   └── manager.py           # ConnectionManager + Redis listener task
│   └── utils/
│       ├── chunking.py          # 512-token chunks with timestamp mapping
│       ├── html_builder.py      # Jinja2 env + custom number_format filter
│       └── ...
├── tests/                       # 168 tests, mostly pytest + httpx test client
├── alembic/                     # Alembic migrations
└── scripts/
    ├── stress_test_llm.py       # canonical LLM stress harness
    └── stress_test_local_llm.py # thin shim → stress_test_llm.py
```

---

## Frontend layout

```
frontend/
├── src/
│   ├── main.tsx                 # router root + React Query client + auth guard
│   ├── routes.tsx               # route table (10 pages)
│   ├── layouts/
│   │   └── AppLayout.tsx        # top-tab nav + content slot (today)
│   ├── pages/
│   │   ├── LoginPage.tsx
│   │   ├── RegisterPage.tsx
│   │   ├── JobsListPage.tsx     # all jobs the user owns
│   │   ├── SubmitJobPage.tsx    # tabbed form: Topic / Channels / Subscribe
│   │   ├── JobDetailPage.tsx    # status, approval, report, Q&A panel
│   │   ├── LibraryPage.tsx      # global video library browse + filters
│   │   ├── LibraryQAPage.tsx    # ask across the entire library
│   │   ├── QAHistoryChatPage.tsx# meta-chat across all past Q&A
│   │   ├── VideoKnowledgePage.tsx # knowledge artifact for one video
│   │   └── ExportsPage.tsx      # dataset export endpoints + downloads
│   ├── hooks/
│   │   ├── useJobProgress.ts    # WS subscribe → React Query cache invalidation
│   │   ├── useAuth.ts           # JWT in Zustand + axios interceptor
│   │   └── ...
│   ├── services/
│   │   ├── apiClient.ts         # axios instance, token attach, error normalization
│   │   ├── wsClient.ts          # /ws/jobs WS with reconnect + heartbeat
│   │   └── api/                 # one file per resource (jobs.ts, library.ts, etc.)
│   ├── stores/
│   │   ├── authStore.ts         # Zustand: token, user, hydration
│   │   └── uiStore.ts           # Zustand: sidebar collapse, theme, modals
│   └── styles/
│       ├── index.css            # global resets + CSS variables (legacy palette)
│       └── theme.ts             # design tokens (post-rebrand)  ← per branding.md
└── vite.config.ts               # dev server, proxy /api to localhost:8000
```

State split: **server state in React Query**, **UI state in Zustand**. No Redux. No styled-components — every component uses inline `style={{}}` objects today; the rebrand introduces a primitive set in `components/primitives/` that reads from design tokens.

---

## Data model

### Authoritative entities

```
User ──┬──< Job ──< JobVideo >── Document ──> Channel
       │           │
       │           ├──< QAExchange
       │           ├── ReportFile (filesystem, not a DB row)
       │           └── status, type, parameters (JSON)
       │
       ├──< LibraryQAExchange
       └──< QAHistoryExchange

Document ──< KnowledgeArtifact (columns on Document, not a separate table)
Document ──< TranscriptCache (1:1 by document_id; FK ON DELETE CASCADE)

ApiQuotaLog (append-only ledger of YouTube + LLM calls)
```

> **Schema state (post-E-1.10, 2026-05-02).** The primary key on `documents` is now `document_id` (UUID4, str(36)). The legacy `video_id` column survives as a NULLABLE back-compat reading column populated for `source_type='video'` rows (NULL for Reddit / HN / other source types). The join table is renamed to `job_documents` (Python class still `JobVideo` for import back-compat) with composite PK `(job_id, document_id)`. `transcript_cache` PK is also now `document_id` with FK to `documents.document_id`. See [D-017](decisions.md#d-017-e-110-hard-cutover-single-migration-uuid-pk-promotion-2026-04-26) for the cutover rationale and [PR #112](https://github.com/khoks/VideoResearchPro/pull/112) for the migration.

### Key invariants

- **Documents are global.** One row per source. Canonical identity is `(source_type, source_id)` (unique-indexed); the PK is the synthetic `document_id` UUID. Today's source types: `video` (YouTube), `reddit_post`, `hn_story`. The library is a single, deduplicated, shared corpus. `JobVideo` rows in `job_documents` tie a job to its documents. Deleting a job drops `JobVideo` rows; documents and chunks survive.
- **Channels are first-class.** Subscribing a channel pre-pulls every video on its uploads playlist into the global library via subscription jobs.
- **Transcripts are cached once.** Re-fetch is suppressed by `transcript_cache.document_id` lookup. Legacy `transcript_cache.video_id` column survives as nullable back-compat for video rows.
- **Embeddings happen exactly once per document.** `Document.embedded_in_chroma` flips to `true` after chunks land in `videoresearchpro_global`. Subsequent jobs referencing that document skip embedding.
- **Q&A exchanges have three flavors** that union into one Chroma collection:
  - `qa_exchanges` (job-scoped)
  - `library_qa_exchanges` (library-scoped)
  - `qa_history_exchanges` (meta-chat surface)

  All three are stored separately for SQL-level filtering but indexed together in `qa_library_global` so meta-chat retrieval crosses surfaces.
- **Knowledge artifacts live on the Document row.** Three nullable columns (`extracted_knowledge_json`, `knowledge_report_md`, `knowledge_extracted_at`). One artifact per document.
- **Jobs carry a status enum**: `pending → searching → awaiting_approval → extracting → building_rag → generating_report → completed`. Terminal: `completed`, `failed`, `cancelled`. Subscription jobs skip `awaiting_approval` and `generating_report`.

### Forward-compat columns (already present or planned next sprint)

Per [saas-roadmap.md](saas-roadmap.md) and [source-types.md](source-types.md):

- Every user-scoped table has — or will have, in the imminent migration — a `tenant_id` column. The single self-host instance has a single tenant.
- The `documents` table carries `source_type`, `source_id`, `source_url`, `source_metadata_json`, `language`, `word_count`, `user_provenance_json` (from L1 PR 1) plus `document_id` UUID PK (from E-1.10, PR #112). The legacy `video_id` column persists as nullable back-compat. The future `creator_id` foreign key for cross-source-type creators is the next planned column (E-1.9).
- The `channels` table grows into `creators` with `source_type`, `source_weight` (E-1.9). `source_type`, `creator_external_id`, and `source_weight` are already present from L1 PR 1.
- The classifier output (D-007 / D-014) lands at `documents.source_metadata_json["classification"]` per [D-023](decisions.md#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28); inserted via the source-type-agnostic `_upsert_candidate_and_link()` helper (PR [#113](https://github.com/khoks/VideoResearchPro/pull/113)).

Today's PRs respect both invariants even though only one tenant and one source type exist.

---

## Job lifecycle (the backbone)

```
┌─────────┐
│ pending │  ← created by POST /api/v1/jobs
└────┬────┘
     │ task picks up
     ▼
┌──────────┐    topic jobs only:    ┌──────────────────┐
│searching │ ───────────────────▶   │awaiting_approval │  ← user reviews, approves
└────┬─────┘    channel jobs:       └────────┬─────────┘
     │           skip directly to              │ approve API call
     │           extracting                    │ dispatches resume task
     │                                          ▼
     ▼                                   ┌──────────────┐
                                          │  extracting  │
                                          └──────┬───────┘
                                                 ▼
                                          ┌──────────────┐
                                          │ building_rag │
                                          └──────┬───────┘
                                                 │ topic + channel jobs
                                                 ▼
                                         ┌──────────────────┐
                                         │generating_report │ ← skipped by subscription
                                         └──────┬───────────┘
                                                ▼
                                         ┌─────────────┐
                                         │  completed  │
                                         └─────────────┘
```

### Multi-source dispatch (post-S-1.5.11, 2026-05-02)

Topic jobs carry a `source_types_json` column — a JSON-encoded array of `source_type` discriminators. NULL → `["video"]` for back-compat. `execute_topic_job` reads the column and branches:

- **`"video"`** → existing LangGraph search agent (richer ranking via `search_plan_queries` + `search_rank_and_curate` use cases).
- **Everything else (`"reddit_post"`, `"hn_story"`, future `"mastodon"` / `"bluesky"`)** → `app/services/connector_dispatch.py::dispatch_search()`, which iterates each non-video source_type **sequentially** (per [D-026](decisions.md#d-026-sequential-fan-out-for-the-connector-dispatcher-2026-05-02)) through `connector_for(source_type).search(query, instructions, limit)`. For each Candidate, the connector's own `fetch_text(query=...)` is called (which inline-classifies per [D-023](decisions.md#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28)); persistence is uniform across source types via `_upsert_candidate_and_link()`.

Both paths converge into the same `awaiting_approval` flow. The combined candidate count drives the user-visible "Found N candidates" message; an empty result across all sources fails the job with a clear "No candidates for source_types=[...]" error rather than dropping the user onto an empty approval list.

Per-source-type errors (connector raised, missing connector, NotImplementedError for PDF-style sources) are captured per source in `DispatchResult.errors_by_source_type` and logged; they don't fail the job — other source types' candidates still flow through.

### Approval pause mechanism

Topic jobs pause at `awaiting_approval`. The pause is **passive, not blocking**:

1. Celery task fetches search results, persists candidate documents (any source_type), sets `status='awaiting_approval'`, and **exits**. No worker is held waiting.
2. The user reviews and POSTs `/api/v1/jobs/{id}/approve` with a list of approved row IDs in `approved_video_ids`. Per S-1.5.4 (post-M-1.5), the field name is legacy — values can be either YouTube `video_id` strings (for `source_type='video'`) or `document_id` UUIDs (for non-video sources where `video_id` is NULL). The backend matches against both columns on each `JobVideo` row.
3. The router updates `JobVideo.approved=True` for the chosen rows, then dispatches a **new** Celery task (`resume_job_after_approval`) which picks up at the extraction phase.

This pattern means a job can sit in `awaiting_approval` for arbitrary time without consuming worker capacity.

#### Polymorphic approval response

`GET /api/v1/jobs/{id}/videos` returns one row per Document linked to the job. Post-S-1.5.4 (PR [#122](https://github.com/khoks/VideoResearchPro/pull/122)), the response carries:

- `id`, `video_id` (nullable for non-video), `document_id` (UUID, canonical PK)
- `source_type`, `source_id`, `source_url`
- `source_metadata` — parsed JSON dict (per-source-type shape — Reddit: `{subreddit, author, score, commentCount, permalink}`; HN: `{author, points, commentCount, url}`; video: `{channel, durationSec, viewCount}`)
- `classification` — lifted out of `source_metadata` for the frontend's `<ClassificationBadgeRow>` consumer; `{stance, sentiment, framing, topic_relevance}` per [D-007](decisions.md#d-007-sentiment-stance-classification-at-fetch-time-2026-04-25) / [D-014](decisions.md#d-014--add-framing-axis-to-social_classify_stance-schema-2026-04-26) / [D-021](decisions.md#d-021-topic-relevance-threshold-050-2026-04-26)
- The standard YouTube fields (`title`, `channel_name`, `duration_seconds`, `thumbnail_url`, `transcript_status`, etc.) — populated for video rows; nullable on non-video.

The frontend `<ApprovalCard>` polymorphic primitive (PR [#118](https://github.com/khoks/VideoResearchPro/pull/118)) consumes this shape via `videoToApprovalProps()` + `SOURCE_CONFIGS[source_type]`.

### Subscription jobs (no approval)

Subscription jobs ingest *everything* from each subscribed channel's uploads playlist into the global library:

- No `awaiting_approval`.
- No report generation.
- Whisper transcript fallback for videos lacking captions.
- Idempotent: re-running a subscription job over the same channel skips already-ingested videos.
- Transitions: `pending → extracting → building_rag → completed`.

### WebSocket progress

A single WebSocket endpoint at `/ws/jobs`. Clients send JSON `{action: "subscribe", job_id: "..."}` and `{action: "unsubscribe", job_id: "..."}` messages. The server-side `ConnectionManager`:

- Maintains a per-client subscription set in memory.
- Maintains a single Redis subscriber that listens on the pattern `job_progress:*`.
- On every progress event, fans the message out to every client subscribed to that job_id.
- Heartbeats every 30 seconds (server pings, client pongs).

The frontend's `useJobProgress` hook drives React Query cache invalidation off WS messages: a status change to `awaiting_approval` invalidates the `jobVideos` query so the approval list auto-populates without a manual reload.

---

## RAG pipeline

### Chunking

`utils/chunking.py` splits a YouTube transcript (a list of segments with `text`, `start`, `duration`) into ~512-token chunks with 50-token overlap. Each chunk preserves a `start_time` and `end_time` derived from the segments it spans. Multilingual scripts are tokenized via the embedder's tokenizer to keep chunk sizes aligned with the embedding context window.

### Embedding

`embedding_service.py` wraps a single `SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")` instance. Loaded once per process (FastAPI and Celery each load their own). CPU-only by default; the model is small enough for that to be fine on commodity hardware.

### ChromaDB

`chroma_service.py` is a singleton client (`PersistentClient(path=...)`). Collection access is via `get_or_create_collection`. Two collections in active use:

- **`videoresearchpro_global`** — chunked transcripts. Metadata per chunk: `{video_id, job_id, chunk_index, start_time, end_time, channel_id, ingested_at}`.
- **`qa_library_global`** — Q&A exchanges, single document each. Metadata: `{exchange_id, surface (job/library/history), job_id (nullable), question_preview, asked_at}`.

Chunk inserts are batched. Failures retry once and then surface as a `building_rag` failure on the job.

### Retrieval

- **Per-job Q&A** filters by `video_id ∈ approved_set`. Top-K = 15 by default (env `RAG_TOP_K`).
- **Library-wide Q&A** filters by nothing. Top-K = 15 by default.
- **Q&A history meta-chat** queries `qa_library_global` with no filter. Returns top-15 past exchanges.
- **Video knowledge extraction** doesn't use RAG — it works directly on the cached transcript (chunk-by-chunk via the knowledge agent's map-reduce).

---

## LangGraph agents

Each agent is a stateful graph with a `TypedDict` shared state in `agents/state.py`.

### Search Agent (`search_agent.py`)

Topic jobs only. Pipeline:

```
generate_search_queries → execute_searches → rank_and_curate
```

- **generate_search_queries** (`use_case=search_plan_queries`) plans 3-5 YouTube search queries from the user's topic + free-text instructions.
- **execute_searches** runs each query against YouTube Data API v3 in parallel (asyncio).
- **rank_and_curate** (`use_case=search_rank_and_curate`) deduplicates and ranks the results into the final candidate list — the largest reasoning-mode win in the codebase.

### Report Agent (`report_agent.py`)

Topic and channel jobs. Pipeline:

```
compute_statistics → map_chunks → reduce_summaries → compose_report
```

- **compute_statistics** runs SQL aggregations (video count, total duration, channel breakdown, date range).
- **map_chunks** (`use_case=report_map_chunks`) processes transcript chunks in batches, extracting per-batch facts. Highest-volume LLM call in the app.
- **reduce_summaries** (`use_case=report_reduce_summaries`) consolidates per-batch summaries into a unified summary.
- **compose_report** (`use_case=report_compose` for topic, `report_channel` + `report_compose_channel_section` for channel jobs) renders the final HTML.

Channel jobs skip `map_chunks`/`reduce_summaries` and go straight to a stats-only HTML report.

### Q&A Agent (`qa_agent.py`)

All three Q&A surfaces. Pipeline:

```
clarify (optional) → expand_sub_queries → retrieve_context → refine_context → formulate_answer → extract_references
```

- **clarify** (`use_case=qa_clarification` / `library_qa_clarification`) — short follow-up clarifier before answering, only when the question is too ambiguous.
- **expand_sub_queries** (`use_case=qa_sub_query_expansion`) rewrites the question into 2 sub-queries for broader RAG recall.
- **retrieve_context** queries ChromaDB with the original + sub-queries.
- **refine_context** (`use_case=qa_refine_context` / `library_qa_refine_context`) compacts ~45K raw RAG+report context into ~3K focused excerpts before the answer LLM sees it. This is the fix for "no relevant context" failures on large noisy inputs.
- **formulate_answer** (`use_case=qa_formulate_answer` / `library_qa_formulate_answer`) — final user-facing answer, temperature 0, accepts an `answer_language` parameter (default English).
- **extract_references** (`use_case=qa_extract_references`) parses the answer back into structured `(video_id, ts, quote)` so the frontend can render citation chips with `&t=` timestamp links.

Topic jobs use RAG + report. Channel jobs use RAG only. Subscription jobs are queryable only via library-wide Q&A.

### Knowledge Agent (`knowledge_agent.py`)

Per-video extraction. Pipeline:

```
batch_transcript → map_extract_per_batch → merge_with_dedupe → synthesize_report
```

- **batch_transcript** splits the cached transcript into token-budgeted batches (env `KNOWLEDGE_EXTRACT_BATCH_TOKENS=8000`, capped at `KNOWLEDGE_MAX_TRANSCRIPT_TOKENS=60000`).
- **map_extract_per_batch** (`use_case=knowledge_extract_batch`) returns structured `{topics, concepts, events, facts}` JSON per batch.
- **merge_with_dedupe** unions the per-batch outputs and deduplicates by case-insensitive equality.
- **synthesize_report** (`use_case=knowledge_synthesize_report`) renders a Markdown knowledge document.

Output written to `Document.extracted_knowledge_json` and `Document.knowledge_report_md`. Triggered by `POST /api/v1/videos/{id}/extract-knowledge`. Returns 409 if already extracted unless `?force=true`.

### Q&A History Agent (`qa_history_agent.py`)

Meta-chat across past exchanges. Pipeline:

```
retrieve_past_exchanges → refine_context → formulate_answer
```

- **retrieve_past_exchanges** queries `qa_library_global` for the top-K past Q&As similar to the meta-question.
- **refine_context** (`use_case=qa_history_refine_context`) compresses the retrieved exchanges.
- **formulate_answer** (`use_case=qa_history_formulate_answer`) synthesizes a meta-answer that cites past exchange IDs. The frontend turns those IDs into deep links to the originating job detail or library Q&A page.

---

## LLM routing

Every LLM call site in the codebase is a **named use case** with a default `(provider, model, reasoning)` triple registered in `app/services/llm_routing.py::USE_CASE_REGISTRY`. Nineteen entries today (full list in [CLAUDE.md](../CLAUDE.md) §LLM-configuration).

`resolve_config(use_case)` returns the effective config after applying `LLM_USE_CASE_CONFIG` overrides (highest precedence) and `LLM_ROUTE_OVERRIDES` (legacy fallback). `get_llm(use_case)` returns a configured LangChain client (`ChatOpenAI`, `ChatAnthropic`, `ChatGoogleGenerativeAI`, or local OpenAI-compatible).

### Reasoning levels

Normalized across providers:

- OpenAI — `reasoning_effort` (off/minimal/low/medium/high)
- Anthropic — `thinking.budget_tokens` (auto → medium)
- Google — `thinkingBudget` (auto → -1)

Unsupported levels degrade gracefully with a warning log; never fatal.

### LLM smoke + fail-soft

`services/llm_smoke.run_startup_probes` runs once from the FastAPI lifespan. It:

1. Resolves the effective `UseCaseConfig` for all 19 use cases.
2. Dedupes by `(provider, model)` — each unique pair probed once.
3. Fans a trivial one-token probe per unique config out via `asyncio.to_thread` (provider SDKs are synchronous).
4. Stores per-use-case results on a process-global `LLMStatus` singleton.

`GET /api/v1/health` returns `llm.status` (`ok` / `degraded` / `down` / `unknown`) and `unavailable_features` (a list of feature names whose required use cases failed). `GET /api/v1/health/llm` returns full per-use-case detail.

When a probe fails, the **app stays up**. The frontend shows a banner driven by the health response, and pages whose primary action depends on a failed feature disable that action (Ask question, Generate report, Extract knowledge). Non-LLM features stay fully interactive: viewing existing jobs, browsing the library, opening past reports, downloading dataset exports.

The Celery worker does not share this lifespan — task-time LLM failures surface on the Jobs page via the worker's progress publisher.

### Context-window & scale behavior (audited 2026-07-29)

A full call-site audit against a 200-video / 10.6M-token extreme corpus (real reference job 0d4db8c3: 200 videos, 947K words, 5,164 chunks, longest video 4.4 h). Three context strategies coexist, with very different maturity:

**Retrieval-bounded (all Q&A surfaces) — corpus-invariant by design.** Job Q&A, Library Q&A, and Q&A-history never see the corpus, only top-K retrieval: ≤3 queries × `RAG_TOP_K`(15) chunks, deduped, plus the report text hard-capped at 50,000 chars (`REPORT_CONTEXT_CHAR_CAP`, qa_agent.py). Worst-case refine input ≈ 37K tokens regardless of library size. Q&A-history additionally clips stored answers to 1,500 chars at prompt-assembly.

**Batch-bounded (knowledge agent) — per-video, capped, silently lossy.** Transcripts split into `KNOWLEDGE_EXTRACT_BATCH_TOKENS`(8K) batches under a `KNOWLEDGE_MAX_TRANSCRIPT_TOKENS`(60K) cap. The cap is a silent tail-truncation (no log/marker) — a 4.4 h video (~67K tokens) loses its tail. Synthesize re-sends the full (re-truncated) transcript plus the uncapped merged-extraction JSON: ~75K tokens worst-case in one call.

**Budget-batched (report pipeline) — the known scale hazard.** Map batches are sized to `0.6 × LLM_MAX_CONTEXT_TOKENS` (= 628K tokens against the global 1,047,576 constant) *regardless of which model the use case resolves to* — no per-model context-window table exists, and `min_context_recommended` in the registry is advisory metadata only. Reduce is single-level (one pairwise halving, no recursion, no final merge); reduce failure passes raw map outputs to compose. Failed map batches are silently dropped (`except → warn → continue`). The channel path truncates each channel at 314K tokens with no logging. `search_rank_and_curate` puts the whole candidate pool (cap `num_videos × 5`) in one prompt: ~130K tokens at target=200, ~300K at target=500. Only 4 of 20 registered call sites set `max_tokens`; no code path recognizes a context-length 400 specifically, and one-token startup probes cannot detect window mismatches.

**Remediated 2026-07-29** by [E-1.12](initiatives.md#e-112-llm-context-window-resilience-at-scale) (PRs #195/#196, [D-052](decisions.md#d-052-measured-context-windows-three-tier-model-stack-e-112-model-re-audit-2026-07-29)): batch budgets now derive from the RESOLVED model's empirically measured window (`llm_routing.MODEL_CONTEXT_WINDOWS` + `context_window_for()`, ×0.5 safety, 120K context-rot quality cap); reduce recurses pairwise to a single summary with token-truncated failure paths; failed map batches bisect-retry once and permanent drops render as a processing-note footer in the report itself; candidate ranking runs a batched tournament above 400 candidates; knowledge extraction batches full transcripts (500K sanity ceiling with a `_processing.truncated` marker) and synthesize sends a 20K grounding excerpt instead of the full transcript; all 20 call sites set `max_tokens`. The job-scope retrieval bug is fixed — the router passes approved video ids and retrieval filters on them (empty-approval jobs never fall back to global search). Mid-tier calls run on `gpt-5.4-mini` with reasoning OFF — on mini, reasoning consumes the visible completion budget (live-validation catch, PR #196).

---

## Auth and tenancy

### Today (self-host, single tenant)

- Email + password registration and login (`auth_service.py`, bcrypt).
- JWT issued on login; included in `Authorization: Bearer <token>` on every request.
- Token verification in a FastAPI dependency `get_current_user` that loads the user row.
- All user-scoped resources are FK-linked to `User.id` and filtered at query time.
- `tenant_id` is **not yet** materialized in the schema but is reserved for the imminent migration; today's `User.id` plays the role of an implicit tenant.

### Future (SaaS)

Per [saas-roadmap.md](saas-roadmap.md):

- Explicit `tenant_id` on every user-scoped table; tenant → workspace → user hierarchy.
- OAuth (Google, GitHub), MFA, session management, audit log.
- Per-tenant quota allocation (YouTube API, LLM tokens, document count).
- Per-tenant LLM keys (BYOK).
- Stripe subscription billing.

---

## Quotas and observability

### YouTube API

`quota_service.py` records every YouTube API call in `api_quota_log` with cost units (1 for search/playlistItems, etc.). A soft cap (default 10K daily units, the YouTube free quota) surfaces a banner on the frontend when usage crosses 80%. Hard cap rejects new searches with a 429 + a clear "quota exhausted" error.

### LLM calls

Per-call accounting is **not** in `api_quota_log` today (deferred to the SaaS phase). Cost observability for LLMs is through the provider dashboards.

### Logs

Structured logs via stdlib `logging` with a simple JSON formatter. Celery task logs include `job_id` in every record. Errors caught by FastAPI exception handlers are logged with the request path and user_id.

---

## Dataset exports

Four streaming JSONL endpoints (`routers/exports.py`):

- `/api/v1/exports/qa-dataset/openai.jsonl` — Q&A as OpenAI chat-format records.
- `/api/v1/exports/qa-dataset/tuple.jsonl` — Q&A as plain `(system, user, assistant)` tuples.
- `/api/v1/exports/knowledge-dataset/openai.jsonl` — knowledge artifacts in chat format.
- `/api/v1/exports/knowledge-dataset/tuple.jsonl` — knowledge artifacts in tuple format.

`StreamingResponse` over a SQL iterator. Memory stays constant for arbitrarily large exports. System prompts are baked into `services/dataset_service.py` as module constants. The Q&A dataset unions `qa_exchanges` + `library_qa_exchanges` + `qa_history_exchanges` ordered by `created_at`.

---

## Multilingual posture

- **Whisper** is invoked with `task="transcribe"` (not `translate`) so mixed-language audio (e.g. Hindi-English code-mixed) is preserved faithfully.
- The **embedding model** is multilingual (`paraphrase-multilingual-MiniLM-L12-v2`), so a Hindi transcript and an English question land in similar vector space.
- The **Q&A agent** accepts an `answer_language` parameter and is instructed to translate quoted non-English context into the target language while preserving proper nouns in their original script.

---

## Forward-looking notes

These sections describe the trajectory, not the current code:

- **Multi-source ingest** — the `videos` → `documents` table rename landed in L1 PR 4; the `SourceConnector` interface contract (PR 2/3) routes every YouTube call site through `connector_for("video")`. The Reddit (S-1.5.1) and HN (S-1.5.2) standalone connectors followed; **E-1.10 UUID PK promotion shipped 2026-05-02** ([PR #112](https://github.com/khoks/VideoResearchPro/pull/112)) collapsing storage tasks to trivial inserts. Reddit + HN end-to-end ingest converges on **Milestone M-1.5** (3 of 7 component checks closed; orchestrator wiring + frontend ApprovalCard primitive + citation rendering + e2e tests are the remaining work). Full trajectory in [source-types.md](source-types.md). L1 in the [feature-roadmap](feature-roadmap.md).
- **Personal Brain** — activity stream connectors, voice capture, "speak as me" agent are detailed in [personal-brain.md](personal-brain.md). Multi-quarter trajectory.
- **SaaS** — tenancy, billing, abuse prevention, hosting are detailed in [saas-roadmap.md](saas-roadmap.md). Today's PRs already respect the forward-compat invariants.
- **Author Studio** — derivative artifact generation (books, sites, decks, newsletters, reels) is L2 in the [feature-roadmap](feature-roadmap.md). Each output type plugs into the same library.
- **Curated source ranking** — source weights, disagreement detection, side-by-side narratives are L4. Source weights already have a column reservation on the `creators` table.

---

## Cross-references

- API endpoints — [api-reference.md](api-reference.md)
- Frontend pages — [ui-pages.md](ui-pages.md)
- UI design tokens & visual system — [ui-design.md](ui-design.md), [branding.md](branding.md)
- Functional & non-functional requirements — [requirements.md](requirements.md)
- Vision — [vision.md](vision.md)
- Roadmap — [feature-roadmap.md](feature-roadmap.md)
- LLM use case registry — [CLAUDE.md](../CLAUDE.md) §LLM-configuration and `backend/app/services/llm_routing.py::USE_CASE_REGISTRY`
- Testing — [testing.md](testing.md)
- Contributing — [contributing.md](contributing.md)
