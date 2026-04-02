# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**VideoResearchPro** — A full-stack web application for YouTube video research. Users submit jobs to fetch transcripts from YouTube videos (by topic search or channel list), build per-job vector DB RAGs with ChromaDB, generate comprehensive HTML reports using LangGraph agents (map-reduce pattern), and ask questions against the collected data with citation-backed answers.

## Tech Stack

- **Frontend**: React 18 + TypeScript + Vite + TanStack React Query + Zustand + React Router v6
- **Backend**: Python 3.12+ + FastAPI + SQLAlchemy 2.x (SQLite) + Alembic migrations
- **Task Queue**: Celery + Redis (broker on db1, results on db2, pub/sub on db0)
- **Vector DB**: ChromaDB with PersistentClient, sentence-transformers `all-MiniLM-L6-v2` embeddings
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
# All backend tests (36 tests)
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

### Two Job Types
- **Topic job**: User provides a topic + search instructions → Search Agent finds YouTube videos → user approves → transcripts fetched → RAG built → Report Agent generates full HTML report → Q&A enabled
- **Channel job**: User provides channel URLs → videos fetched from playlists → user approves → transcripts fetched → RAG built → stats-only HTML report → Q&A enabled

### Job Lifecycle
```
pending → searching → awaiting_approval → extracting → building_rag → generating_report → completed
                                                                                        → cancelled
                                                                                        → failed
```

### Approval Pause Mechanism
Celery task exits after the search/fetch phase, saving discovered videos and setting status to `awaiting_approval`. User reviews and approves via REST API. A **new** Celery task is dispatched to resume from the extraction phase. No worker is blocked waiting.

### WebSocket Progress
Single multiplexed WebSocket at `/ws/jobs`. Clients send `subscribe`/`unsubscribe` messages per job_id. Celery workers publish progress to Redis pub/sub (`job_progress:{job_id}`). The WebSocket manager listens on Redis and fans out to subscribed clients.

### RAG Pipeline
One ChromaDB collection per job (`job_{job_id}`). Transcripts are chunked at 512 tokens with 50-token overlap, preserving timestamp mappings from YouTube transcript segments. Embeddings via `all-MiniLM-L6-v2`.

### LangGraph Agents
- **Search Agent**: generate_search_queries → execute_searches → rank_and_curate (topic jobs only)
- **Report Agent**: compute_statistics → map_chunks → reduce_summaries → compose_report (map-reduce for large transcript sets; channel jobs skip to stats-only)
- **Q&A Agent**: retrieve_context → refine_context → formulate_answer → extract_references (LLM-based context refinement compacts ~45K raw RAG+report into ~3K focused extracts before answering; topic jobs use RAG + report; channel jobs use RAG only; citations include `&t=` timestamp links)

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
| `frontend/src/pages/JobDetailPage.tsx` | Job detail: approval, report modal, Q&A panel |
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
