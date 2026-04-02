# VideoResearchPro — System Architecture

## High-Level Overview

```
┌─────────────────────────────┐         ┌───────────────────────────────────────┐
│   Frontend (React + Vite)   │         │         Backend (FastAPI)             │
│                             │──REST──▶│  Routers → Services → Database       │
│  React Query ◄── Zustand    │         │                                      │
│       ▲                     │◀──WS────│  WebSocket Manager (Redis sub)       │
│       │ cache update        │         └──────────┬────────────────────────────┘
│  WebSocket Hook             │                    │ .delay()
└─────────────────────────────┘                    ▼
                                        ┌──────────────────────────────────────┐
                                        │       Celery Workers (Redis broker)  │
                                        │  ┌─────────────────────────────────┐ │
                                        │  │ YouTube Service (API + transcripts)│
                                        │  │ ChromaDB Service (vector store)   │
                                        │  │ LangGraph Agents (Search/Report/QA)│
                                        │  └─────────────────────────────────┘ │
                                        │         │ publish progress           │
                                        │         ▼                            │
                                        │    Redis Pub/Sub (job_progress:*)    │
                                        └──────────────────────────────────────┘
```

## Backend Architecture

### Layer Structure

```
Routers (HTTP/WS)  →  Services (business logic)  →  Models (ORM)  →  SQLite DB
                   →  Tasks (Celery)              →  Agents (LangGraph)
                   →  WebSocket Manager           →  Redis pub/sub
```

### Directory Layout

```
backend/
├── app/
│   ├── main.py                  # FastAPI app, CORS, lifespan (creates tables + dirs)
│   ├── config.py                # Pydantic Settings (reads .env)
│   ├── database.py              # SQLAlchemy engine + SessionLocal
│   ├── dependencies.py          # DI: get_db(), get_redis()
│   ├── routers/
│   │   ├── jobs.py              # Job CRUD + approve + cancel + delete
│   │   ├── qa.py                # Report serving, Q&A ask + history
│   │   ├── ws.py                # WebSocket endpoint /ws/jobs
│   │   └── health.py            # GET /health
│   ├── models/
│   │   ├── job.py               # Job ORM (UUID PK, status enum, JSON fields)
│   │   ├── video.py             # Video ORM (FK to job, approval flag)
│   │   └── qa_exchange.py       # QAExchange ORM (references as JSON)
│   ├── schemas/
│   │   ├── job.py               # JobCreate (model_validator), JobResponse, VideoApproval
│   │   ├── video.py             # VideoResponse
│   │   └── qa.py                # Reference, QARequest, QAResponse
│   ├── services/
│   │   ├── job_service.py       # CRUD + concurrent job limit enforcement
│   │   ├── youtube_service.py   # YouTube Data API v3 + transcript fetching (with language fallback)
│   │   ├── chroma_service.py    # ChromaDB singleton client, collection CRUD
│   │   ├── progress_service.py  # Redis pub/sub publisher
│   │   ├── report_service.py    # HTML report file I/O
│   │   └── llm_service.py       # get_llm() → ChatOpenAI(model="gpt-4.1")
│   ├── agents/
│   │   ├── state.py             # TypedDict states for all 3 agents
│   │   ├── search_agent.py      # LangGraph: topic → video discovery
│   │   ├── report_agent.py      # LangGraph: transcripts → HTML (map-reduce)
│   │   ├── qa_agent.py          # LangGraph: question → answer + citations
│   │   ├── prompts/             # Prompt templates per agent
│   │   └── tools/               # @tool functions (youtube_search, rag_search)
│   ├── tasks/
│   │   ├── celery_app.py        # Celery config (Redis broker/backend, JSON serializer)
│   │   └── job_tasks.py         # execute_topic_job, execute_channel_job, resume_job_after_approval
│   ├── websocket/
│   │   └── manager.py           # ConnectionManager: per-job subscriptions, Redis→WS fan-out
│   └── utils/
│       ├── chunking.py          # Transcript → 512-token chunks with timestamp mapping
│       ├── html_builder.py      # Jinja2 report template + save_report()
│       ├── youtube_helpers.py   # URL parsing, channel ID extraction, duration formatting
│       └── rate_limiter.py      # Thread-safe token bucket for YouTube API
├── tests/
│   ├── conftest.py              # In-memory SQLite, TestClient, mocked Celery tasks
│   ├── test_routers/            # test_health.py, test_jobs.py (11 tests)
│   ├── test_services/           # test_chroma_service.py (7 tests)
│   └── test_utils/              # test_chunking.py (6), test_youtube_helpers.py (11)
├── alembic/                     # Database migrations
├── data/                        # .gitignored: chroma/, reports/, SQLite DB
├── requirements.txt             # Production deps (>= constraints)
└── requirements-dev.txt         # pytest, ruff, httpx
```

### Database Schema (SQLite via SQLAlchemy)

**jobs**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID (String PK) | `uuid4()` default |
| job_type | String | `"topic"` or `"channel"` |
| status | String | Lifecycle enum (see below) |
| created_at, updated_at, completed_at | DateTime | Auto-managed |
| topic | String (nullable) | Topic jobs only |
| search_instructions | Text (nullable) | NL search guidance |
| num_videos | Integer | Default 10 |
| min_duration_minutes, max_duration_minutes | Float (nullable) | Duration filters |
| channel_type_filters | JSON (nullable) | E.g. `["educational"]` |
| channel_list | JSON (nullable) | Channel jobs only |
| videos_per_channel | Integer (nullable) | Channel jobs only |
| chroma_collection_name | String (nullable) | `job_{id}` |
| report_path | String (nullable) | Path to saved HTML |
| progress_pct | Integer | 0–100 |
| progress_message | String (nullable) | Human-readable status |
| error_message | Text (nullable) | On failure |
| celery_task_id | String (nullable) | For task revocation |

**videos**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID (String PK) | Internal ID |
| job_id | String FK → jobs.id | Cascade delete |
| video_id | String | YouTube video ID |
| title, channel_name, channel_id, url | String | Metadata |
| duration_seconds | Integer (nullable) | Video length |
| approved | Boolean | Default true, user can deselect |
| transcript_status | String | `"pending"`, `"fetched"`, `"failed"` |
| transcript_word_count | Integer (nullable) | After fetch |

**qa_exchanges**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID (String PK) | |
| job_id | String FK → jobs.id | Cascade delete |
| question | Text | User's question |
| answer | Text | Agent's answer |
| references | JSON | Array of `{video_title, channel_name, youtube_link, timestamp_display}` |
| prompt_tokens, completion_tokens | Integer (nullable) | Token tracking |
| created_at | DateTime | |

### Job Lifecycle State Machine

```
                 ┌──────────────────────────────┐
                 │          pending              │
                 └──────────┬───────────────────┘
                            │ Celery task starts
                            ▼
                 ┌──────────────────────────────┐
                 │         searching             │  ← Search agent (topic) or channel fetch
                 └──────────┬───────────────────┘
                            │ Videos found, task exits
                            ▼
                 ┌──────────────────────────────┐
                 │     awaiting_approval         │  ← User reviews video list
                 └──────────┬───────────────────┘
                            │ PUT /approve → new Celery task
                            ▼
                 ┌──────────────────────────────┐
                 │        extracting             │  ← Fetch transcripts
                 └──────────┬───────────────────┘
                            ▼
                 ┌──────────────────────────────┐
                 │       building_rag            │  ← Chunk + embed into ChromaDB
                 └──────────┬───────────────────┘
                            ▼
                 ┌──────────────────────────────┐
                 │    generating_report          │  ← Report agent (map-reduce)
                 └──────────┬───────────────────┘
                            ▼
                 ┌──────────────────────────────┐
                 │        completed              │  ← Q&A now available
                 └──────────────────────────────┘

  Any state ──cancel──▶ cancelled
  Any state ──error───▶ failed
```

### Celery Task Design

Three Celery tasks handle the full lifecycle:

1. **`execute_topic_job(job_id)`** — Runs the Search Agent to discover videos, saves them, sets `awaiting_approval`, exits.
2. **`execute_channel_job(job_id)`** — Fetches videos from channel playlists, saves them, sets `awaiting_approval`, exits.
3. **`resume_job_after_approval(job_id)`** — Fetches transcripts for approved videos → chunks and embeds into ChromaDB → runs Report Agent → saves HTML → sets `completed`.

Each task publishes progress to Redis pub/sub at every phase boundary and checks for cancellation between phases.

### WebSocket Protocol

**Connection**: `ws://localhost:8000/ws/jobs`

**Client → Server messages**:
```json
{"action": "subscribe", "job_id": "uuid"}
{"action": "unsubscribe", "job_id": "uuid"}
```

**Server → Client messages** (3 types):
```json
{"type": "job_progress", "job_id": "uuid", "progress_pct": 45, "message": "Fetching transcripts..."}
{"type": "job_status_change", "job_id": "uuid", "old_status": "extracting", "new_status": "building_rag"}
{"type": "job_error", "job_id": "uuid", "error": "YouTube API quota exceeded"}
```

### ChromaDB Design

- **One collection per job**: Named `job_{job_id}`
- **Document**: One transcript chunk (text)
- **Metadata per chunk**: `video_id`, `video_title`, `channel_name`, `video_url`, `timestamp_start`, `timestamp_end`, `chunk_index`, `language`, `word_count`
- **Embedding model**: `all-MiniLM-L6-v2` (sentence-transformers, runs locally)
- **Chunking**: 512 tokens, 50-token overlap, timestamps mapped from YouTube transcript segments using `tiktoken`
- **Batch insert**: 100 documents per batch to avoid ChromaDB limits
- **Cleanup**: Collection deleted when job is deleted

### LangGraph Agent Details

**Search Agent** (topic jobs only)
```
generate_search_queries → execute_searches → rank_and_curate → END
```
- Tools: `youtube_search`, `youtube_video_details`
- Input: topic, search instructions, num_videos, duration/channel filters
- Output: list of video candidates with metadata

**Report Agent** (map-reduce for scale)
```
compute_statistics → [map_chunks → reduce_summaries → compose_report] → END
```
- Channel jobs exit after `compute_statistics` (stats-only report)
- Map phase: batches transcript chunks to fit 60% of LLM context window
- Reduce phase: hierarchical reduction of batch summaries
- Output: statistics dict + HTML report body (rendered via Jinja2 template)

**Q&A Agent** (with context refinement)
```
retrieve_context → refine_context → formulate_answer → extract_references → END
```
- **retrieve_context**: Queries ChromaDB for top-15 RAG chunks + extracts clean text from HTML report (strips `<style>`/`<script>` blocks)
- **refine_context**: LLM-based compactor — takes ~45K chars of raw RAG chunks + report text and extracts only the relevant passages into ~2-4K chars of focused context. Prevents the answer LLM from being overwhelmed by irrelevant noise.
- **formulate_answer**: Answers the question using the refined context with source citations
- **extract_references**: Builds structured reference objects with YouTube timestamp links
- Topic jobs: retrieves from both RAG and HTML report sections
- Channel jobs: retrieves from RAG only
- Output: answer text + array of references with `youtube.com/watch?v=...&t=` links

---

## Frontend Architecture

### Directory Layout

```
frontend/
├── src/
│   ├── App.tsx                  # QueryClientProvider + RouterProvider
│   ├── main.tsx                 # Vite entry point
│   ├── index.css                # Global reset + base styles
│   ├── routes/
│   │   └── index.tsx            # Route definitions: /, /submit, /jobs, /jobs/:jobId
│   ├── layouts/
│   │   └── AppLayout.tsx        # App shell: gradient header, tab nav, <Outlet/>
│   ├── pages/
│   │   ├── SubmitJobPage.tsx    # Job creation form (topic/channel toggle)
│   │   ├── JobsListPage.tsx     # Job list with status cards, cancel/delete
│   │   └── JobDetailPage.tsx    # Detail view: approval, report modal, Q&A
│   ├── components/
│   │   └── common/
│   │       ├── StatusBadge.tsx  # Colored status pill
│   │       ├── ProgressBar.tsx  # Animated progress bar
│   │       └── LoadingSpinner.tsx
│   ├── hooks/
│   │   ├── useJobs.ts           # React Query: CRUD + approve + cancel + delete
│   │   ├── useJobProgress.ts    # WebSocket → React Query cache bridge
│   │   └── useQA.ts             # React Query: ask question + get history
│   ├── services/
│   │   ├── api.ts               # Axios instance (baseURL: http://localhost:8000/api/v1)
│   │   ├── jobsApi.ts           # Job REST API calls
│   │   ├── qaApi.ts             # Q&A REST API calls
│   │   └── wsClient.ts          # WSClient singleton: connect, subscribe, reconnect
│   ├── stores/
│   │   └── jobStore.ts          # Zustand: activeJobId, isReportModalOpen, activeTab
│   └── types/
│       ├── job.ts               # Job, JobCreate, VideoApproval interfaces
│       ├── video.ts             # Video interface
│       ├── qa.ts                # QAExchange, Reference interfaces
│       └── ws.ts                # WSProgressMessage interface
├── package.json
├── tsconfig.json
└── vite.config.ts
```

### State Management Strategy

| Concern | Tool | Why |
|---------|------|-----|
| Server data (jobs, videos, Q&A) | TanStack React Query | Caching, refetching, optimistic updates |
| Real-time progress | WebSocket → React Query cache | WS hook calls `queryClient.setQueryData` |
| UI state (active tab, modal open) | Zustand | Lightweight, no boilerplate |
| Route state | React Router v6 | URL-driven navigation |

### Real-Time Update Flow

```
Celery Worker
  → Redis pub/sub (job_progress:{job_id})
  → WebSocket Manager (fan-out to subscribed clients)
  → wsClient.ts (receives JSON message)
  → useJobProgress hook (parses message type)
  → queryClient.setQueryData (updates React Query cache for job)
  → queryClient.invalidateQueries on status changes:
      awaiting_approval → refetches jobVideos (populates approval list)
      completed/failed  → refetches job + jobs list + videos
  → Components re-render with new progress
```

### Routing

| Path | Component | Description |
|------|-----------|-------------|
| `/` | Redirect → `/submit` | Default landing |
| `/submit` | `SubmitJobPage` | Job creation form |
| `/jobs` | `JobsListPage` | All jobs list |
| `/jobs/:jobId` | `JobDetailPage` | Detail + approval + report + Q&A |

All routes are children of `AppLayout` which provides the header and tab navigation.
