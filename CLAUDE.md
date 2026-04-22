# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**VideoResearchPro** — A full-stack web application for YouTube video research. Users submit jobs to fetch transcripts from YouTube videos (by topic search, channel list, or channel subscription), contribute them to a **global, deduplicated video library**, generate comprehensive HTML reports using LangGraph agents (map-reduce pattern), and ask citation-backed questions either scoped to a single job or across the **entire library**. Videos, transcripts, and embeddings are computed once and reused across every job that references them.

## Tech Stack

- **Frontend**: React 18 + TypeScript + Vite + TanStack React Query + Zustand + React Router v6
- **Backend**: Python 3.12+ + FastAPI + SQLAlchemy 2.x (SQLite) + Alembic migrations
- **Task Queue**: Celery + Redis (broker on db1, results on db2, pub/sub on db0)
- **Vector DB**: ChromaDB with PersistentClient, sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2` embeddings (single global collection)
- **AI Agents**: LangGraph (3 agents: Search, Report, Q&A) + OpenAI GPT-4.1 via `langchain-openai`
- **YouTube**: YouTube Data API v3 + `youtube-transcript-api`

## Build & Run Commands

### Backend
```bash
cd backend
./venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm run dev          # Dev server at http://localhost:5173
npm run build        # Production build + type check
```

### Tests
```bash
# All backend tests (168 tests)
cd backend && ./venv/Scripts/python -m pytest tests/ -v

# Single test file
cd backend && ./venv/Scripts/python -m pytest tests/test_routers/test_jobs.py -v

# Single test
cd backend && ./venv/Scripts/python -m pytest tests/test_routers/test_jobs.py::test_create_topic_job -v

# Frontend type check
cd frontend && npm run build
```

### Infrastructure
```bash
# Redis is installed natively via: winget install Redis.Redis
# It runs as a Windows service automatically on port 6379
# Verify with:
redis-cli ping    # Should return PONG

# Start Celery worker (use --pool=solo on Windows)
cd backend && ./venv/Scripts/celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
```

### Setup (first time)
```bash
# Redis
winget install Redis.Redis    # Installs and starts as Windows service on port 6379

# Backend
cd backend
python -m venv venv
./venv/Scripts/pip install -r requirements.txt
./venv/Scripts/pip install -r requirements-dev.txt
cp ../.env.example .env   # Fill in YOUTUBE_API_KEY and OPENAI_API_KEY

# Frontend
cd frontend
npm install
```

## Architecture Summary

### Three Job Types
- **Topic job**: User provides a topic + search instructions → Search Agent finds YouTube videos → user approves → transcripts fetched → RAG built → Report Agent generates full HTML report → Q&A enabled
- **Channel job**: User provides channel URLs → videos fetched from playlists → user approves → transcripts fetched → RAG built → stats-only HTML report → Q&A enabled
- **Subscription job**: User provides channel URLs → every video from each channel's uploads playlist is ingested into the global library → no approval step (fire-and-forget) → transcripts fetched (with Whisper fallback) → chunks added to the global Chroma collection → no report. Subsequent jobs that reference the same videos skip re-fetch / re-transcribe / re-embed entirely.

### Global Video Library
- `videos` is a shared, global, deduplicated table: one row per YouTube `video_id`, ever.
- `channels` stores subscribed channels with `last_synced_at` for incremental re-sync.
- `job_videos` is a many-to-many join linking jobs to the videos they selected.
- Deleting a job drops its `job_videos` rows but leaves the videos and their chunks in the library — other jobs can still reference them.
- Transcripts are cached in `transcript_cache` (by video_id) and reused across jobs.

### Job Lifecycle
```
pending → searching → awaiting_approval → extracting → building_rag → generating_report → completed
                                                                                        → cancelled
                                                                                        → failed
```
Subscription jobs skip `awaiting_approval` and `generating_report` — they fan out to ingest every video on the channel's uploads playlist and complete once embeddings are added to the global collection.

### Approval Pause Mechanism
Celery task exits after the search/fetch phase, saving discovered videos and setting status to `awaiting_approval`. User reviews and approves via REST API. A **new** Celery task is dispatched to resume from the extraction phase. No worker is blocked waiting.

### WebSocket Progress
Single multiplexed WebSocket at `/ws/jobs`. Clients send `subscribe`/`unsubscribe` messages per job_id. Celery workers publish progress to Redis pub/sub (`job_progress:{job_id}`). The WebSocket manager listens on Redis and fans out to subscribed clients.

### RAG Pipeline
**Single global ChromaDB collection** named `videoresearchpro_global`. Transcripts are chunked at 512 tokens with 50-token overlap, preserving timestamp mappings from YouTube transcript segments. Embeddings are computed exactly once per video using the multilingual `paraphrase-multilingual-MiniLM-L12-v2`.

- Per-job Q&A filters by `video_id ∈ approved_set` at query time.
- Library-wide Q&A queries the whole collection with no filter.

### LangGraph Agents
- **Search Agent**: generate_search_queries → execute_searches → rank_and_curate (topic jobs only)
- **Report Agent**: compute_statistics → map_chunks → reduce_summaries → compose_report (map-reduce for large transcript sets; channel jobs skip to stats-only)
- **Q&A Agent**: retrieve_context → refine_context → formulate_answer → extract_references (LLM-based context refinement compacts ~45K raw RAG+report into ~3K focused extracts before answering; topic jobs use RAG + report, channel jobs use RAG only, subscription jobs have no report and are only queried via library-wide Q&A; accepts an `answer_language` parameter; citations include `&t=` timestamp links)

### Data Flow
```
REST API → FastAPI Router → Service Layer → Celery Task dispatch
Celery Worker → YouTube Service → ChromaDB Service → LangGraph Agents → Progress via Redis pub/sub
Redis pub/sub → WebSocket Manager → Frontend React Query cache update
```

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/tasks/job_tasks.py` | Celery orchestrator — the backbone of job execution |
| `backend/app/agents/report_agent.py` | Map-reduce LangGraph agent for HTML reports |
| `backend/app/agents/search_agent.py` | LangGraph agent for YouTube video discovery |
| `backend/app/agents/qa_agent.py` | LangGraph agent for Q&A with context refinement + citations |
| `backend/app/utils/chunking.py` | Transcript chunking with timestamp mapping |
| `backend/app/websocket/manager.py` | Redis pub/sub → WebSocket fan-out |
| `backend/app/services/youtube_service.py` | YouTube API + transcript fetching with language fallback + rate limiting |
| `backend/app/services/chroma_service.py` | ChromaDB collection management (singleton client) |
| `backend/app/services/embedding_service.py` | Multilingual embedder (`paraphrase-multilingual-MiniLM-L12-v2`) |
| `backend/app/models/channel.py` | Channel model (subscriptions, `last_synced_at`) |
| `backend/app/models/job_video.py` | JobVideo join table (global library ↔ jobs) |
| `backend/app/models/library_qa_exchange.py` | Library-wide Q&A history |
| `backend/app/routers/channels.py` | Channels management API |
| `backend/app/routers/library.py` | Library-wide Q&A API |
| `frontend/src/pages/JobDetailPage.tsx` | Job detail: approval, report modal, Q&A panel |
| `frontend/src/pages/LibraryPage.tsx` | Browse the global video library |
| `frontend/src/pages/LibraryQAPage.tsx` | Ask questions across the entire library |
| `frontend/src/hooks/useJobProgress.ts` | WebSocket → React Query cache bridge |
| `frontend/src/services/wsClient.ts` | WebSocket client with reconnection + ping/pong |

## API Endpoints

```
GET    /api/v1/health
POST   /api/v1/jobs                    # Create job → dispatches Celery task
GET    /api/v1/jobs                    # List all jobs
GET    /api/v1/jobs/{id}               # Job detail
PUT    /api/v1/jobs/{id}/approve       # Approve videos → resumes job
POST   /api/v1/jobs/{id}/cancel        # Cancel + revoke Celery task
DELETE /api/v1/jobs/{id}               # Delete job + ChromaDB collection + report
GET    /api/v1/jobs/{id}/videos        # Video list for job
GET    /api/v1/jobs/{id}/report        # Serve HTML report
POST   /api/v1/jobs/{id}/qa            # Ask question (runs Q&A agent)
GET    /api/v1/jobs/{id}/qa            # Q&A history

POST   /api/v1/library/qa              # Library-wide Q&A ask
GET    /api/v1/library/qa              # Library-wide Q&A history
POST   /api/v1/library/qa/clarify      # Library-wide clarify step
DELETE /api/v1/library/qa/{id}         # Delete a library Q&A exchange (optional)
GET    /api/v1/library/videos          # Browse global video library

GET    /api/v1/channels                # List all channels
GET    /api/v1/channels/{id}           # Single channel detail
POST   /api/v1/channels/{id}/subscribe
POST   /api/v1/channels/{id}/unsubscribe
POST   /api/v1/channels/{id}/sync      # Trigger a fresh sync
GET    /api/v1/channels/{id}/videos

WS     /ws/jobs                        # Multiplexed progress (subscribe/unsubscribe per job)
```

## Environment Variables

Copy `.env.example` to `backend/.env` and fill in required keys:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `YOUTUBE_API_KEY` | Yes | — | YouTube Data API v3 key |
| `OPENAI_API_KEY` | Yes | — | OpenAI API key for GPT-4.1 |
| `DATABASE_URL` | No | `sqlite:///./data/videoresearchpro.db` | SQLAlchemy connection string |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis for pub/sub |
| `CELERY_BROKER_URL` | No | `redis://localhost:6379/1` | Celery broker |
| `LLM_MODEL` | No | `gpt-4.1` | OpenAI model name |
| `CHUNK_SIZE` | No | `512` | RAG chunk size in tokens |
| `RAG_TOP_K` | No | `15` | Number of RAG results per query |
| `EMBEDDING_MODEL_NAME` | No | `paraphrase-multilingual-MiniLM-L12-v2` | SentenceTransformer model |
| `CHROMA_GLOBAL_COLLECTION_NAME` | No | `videoresearchpro_global` | Name of the single global Chroma collection |

## Important Conventions

- **Backend always runs inside venv**: Use `./venv/Scripts/python` (Windows) or `./venv/bin/python` (Linux)
- **Version constraints**: `requirements.txt` uses `>=` (not `==`) to avoid pip resolution conflicts
- **Tests mock Celery**: `conftest.py` patches all three Celery task `.delay()` methods to avoid Redis dependency in tests
- **ChromaDB tests**: Use `EphemeralClient` monkeypatch instead of `PersistentClient`
- **Frontend inline styles**: Components use inline `style={{}}` objects rather than CSS modules or styled-components
- **State management split**: Server state in React Query, UI state in Zustand
- **Celery autodiscover**: Uses `related_name="job_tasks"` since tasks live in `job_tasks.py`, not `tasks.py`
- **Celery on Windows**: Must use `--pool=solo` flag
- **Transcript language fallback**: `fetch_transcript()` tries English first, falls back to any available language
- **Q&A context refinement**: Raw RAG+report context is compacted by an LLM before the answer LLM sees it — prevents "no relevant context" on large noisy inputs
- **HTML report rendering**: Uses `jinja2.Environment` with custom `number_format` filter (not `Template.globals`)
- **WebSocket cache invalidation**: `useJobProgress` invalidates the `jobVideos` query on `awaiting_approval` status change so the approval list auto-populates
- **Global video library**: Videos are never job-owned. Any job selects from the global library via `job_videos`.
- **Single global Chroma collection**: All chunks live in `videoresearchpro_global`. Per-job scoping is a metadata filter at query time. Deleting a job does NOT delete chunks.

### Multilingual transcription

- Whisper is called with `task="transcribe"` (not `translate`), preserving the speaker's language(s). Mixed-language audio (e.g., Hindi-English code-mixed) is transcribed faithfully, with proper nouns in their original script.
- The multilingual embedding model (`paraphrase-multilingual-MiniLM-L12-v2`) ensures a Hindi transcript and its English question land in similar vector space.
- The Q&A agent accepts an `answer_language` parameter (default English) and is instructed to translate quoted non-English context into English (preserving proper nouns) while responding in the requested language.
