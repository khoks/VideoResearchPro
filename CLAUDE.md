# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Pratidhvani (प्रतिध्वनि)** — Sanskrit for "echo". A full-stack personal research wiki. Users submit jobs to ingest sources (today: YouTube by topic search, channel list, or channel subscription; future: podcasts, articles, forum threads, PDFs — see [docs/source-types.md](docs/source-types.md)), contribute them to a **global, deduplicated document library**, generate comprehensive HTML reports via LangGraph agents (map-reduce pattern), and ask citation-backed questions either scoped to a single job, across the **entire library**, or across **every Q&A they've ever asked**. Transcripts, embeddings, and knowledge artifacts are computed once per document and reused across every job that references them.

> **Legacy name.** The project was previously called *VideoResearchPro*. The legacy string survives in grandfathered environment-variable names (e.g. `CHROMA_GLOBAL_COLLECTION_NAME=videoresearchpro_global`) for back-compat only. All user-facing copy now reads `Pratidhvani`.

## Vision & Roadmap

The product is intentionally *curated, not balanced* — the opposite of Wikipedia. Long-term trajectory is a **personal brain** that learns the user's voice, opinions, and life. Canonical narrative docs:

- **Why the product exists:** [docs/vision.md](docs/vision.md)
- **What ships next:** [docs/feature-roadmap.md](docs/feature-roadmap.md)
- **Multi-source ingest (L1):** [docs/source-types.md](docs/source-types.md)
- **Personal brain (L3):** [docs/personal-brain.md](docs/personal-brain.md)
- **Path to SaaS:** [docs/saas-roadmap.md](docs/saas-roadmap.md)
- **Visual identity:** [docs/branding.md](docs/branding.md) and [docs/ui-design.md](docs/ui-design.md)
- **Decision log (ADRs):** [docs/decisions.md](docs/decisions.md)
- **Initiatives / epics / stories / tasks:** [docs/initiatives.md](docs/initiatives.md)
- **Inventions / novel-idea log:** [docs/inventions.md](docs/inventions.md)
- **Recent changes:** [CHANGELOG.md](CHANGELOG.md)

## Session-end persistence skills

Two project skills auto-invoke at session-end (via the `Stop` hook in [`.claude/settings.json`](.claude/settings.json), which fires once per session — `stop_hook_active` guards against recursion). Both are no-op-safe on tactical sessions and open PRs to master rather than pushing directly.

- [`/knowledge-curator`](.claude/skills/knowledge-curator/SKILL.md) — extracts vision / architecture / tech-stack / scaling / decision content from the conversation and routes it into the canonical docs (`docs/feature-roadmap.md`, `docs/architecture.md`, `docs/source-types.md`, `docs/decisions.md`, etc.). Also flags **novel mechanisms / potentially-patentable concepts** into [`docs/inventions.md`](docs/inventions.md). Owns both the [decision log](docs/decisions.md) and the [inventions log](docs/inventions.md).
- [`/work-tracker`](.claude/skills/work-tracker/SKILL.md) — owns [`docs/initiatives.md`](docs/initiatives.md) (Initiative → Epic → Story → Task hierarchy). Updates status / scope of existing items, creates new items for newly-discussed work, cross-links to decisions and PRs.

Both skills can be invoked manually any time. If a session was purely tactical (a one-off bug fix, a code question with no design content, a debugging exchange), let them no-op rather than forcing an empty PR.

## Tech Stack

- **Frontend**: React 19 + TypeScript + Vite + TanStack React Query + Zustand + React Router v7 (100% inline styles, tokens driven from `frontend/src/theme.ts`)
- **Backend**: Python 3.12+ + FastAPI + SQLAlchemy 2.x (SQLite) + Alembic migrations
- **Task Queue**: Celery + Redis (broker on db1, results on db2, pub/sub on db0)
- **Vector DB**: ChromaDB with PersistentClient, sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2` embeddings (two global collections: `videoresearchpro_global` for transcript chunks, `qa_library_global` for Q&A exchanges)
- **AI Agents**: LangGraph (5 agents: Search, Report, Q&A, Q&A-History, Knowledge) + per-use-case LLM config (OpenAI / Anthropic / Google / local OpenAI-compatible)
- **Auth**: JWT, email+password, user-scoped jobs + Q&A history + knowledge artifacts
- **YouTube**: YouTube Data API v3 + `youtube-transcript-api` + OpenAI Whisper fallback

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

### One-shot launcher (recommended for dev)
```powershell
# Starts Redis (if needed), backend, Celery, frontend; waits for health;
# opens browser; blocks until Ctrl+C, then tears everything down.
./scripts/start.ps1                # foreground; Ctrl+C stops everything
./scripts/start.ps1 -NoBrowser     # skip auto-open
./scripts/start.ps1 -NoFrontend    # backend + Celery only
```
Logs land in `.uvicorn.*.log` / `.celery.*.log` / `.frontend.*.log` at the repo root (gitignored). For an in-place restart (kill + relaunch detached) use `./scripts/restart_services.ps1`.

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

### Global Document Library
- `documents` (renamed from `videos` in L1 PR 4) is a shared, global, deduplicated table: one row per source — today only YouTube videos (`source_type='video'`, primary key column still named `video_id`), tomorrow podcasts / articles / threads / PDFs. The ORM class is `Document` in `app/models/document.py`.
- `channels` stores subscribed YouTube channels with `last_synced_at` for incremental re-sync. (Will generalize to `creators` in a later PR.)
- `job_videos` is a many-to-many join linking jobs to the documents they selected. (Will rename to `job_documents` once the PK column is promoted to UUID.)
- Deleting a job drops its `job_videos` rows but leaves the documents and their chunks in the library — other jobs can still reference them.
- Transcripts are cached in `transcript_cache` (by `video_id`) and reused across jobs. (Will generalize to `text_cache` keyed on `(source_type, source_id)` in a later PR.)

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

### Q&A Library RAG
One central ChromaDB collection (`qa_library_global`) indexes every Q&A exchange from all three surfaces (job-scoped, library-scoped, history-chat) as single documents — question and answer concatenated, not chunked. New Q&As are upserted post-commit on a best-effort basis (Chroma failures never break the Q&A response). A backfill runs on worker startup that idempotently upserts every existing row from `qa_exchanges`, `library_qa_exchanges`, and `qa_history_exchanges`. This is the retrieval backbone for the Q&A History Chat page.

### Video Knowledge Artifacts
On-demand per-video knowledge extraction. Every video row carries three nullable columns — `extracted_knowledge_json`, `knowledge_report_md`, `knowledge_extracted_at`. A "Generate knowledge report" button on each video triggers a map-reduce LangGraph agent (`knowledge_agent.py`) that splits the full transcript into token-budgeted batches, extracts structured `{topics, concepts, events, facts}` per batch, merges with dedupe, and synthesizes a report-style Markdown document. Returns 409 if already extracted unless `?force=true`.

### Dataset Exports
Four streaming JSONL endpoints feed an external fine-tune pipeline — two for Q&A (OpenAI chat format and plain tuple format), two for knowledge artifacts (same split). Endpoints use FastAPI `StreamingResponse` with SQL iterators so memory stays constant for arbitrarily large datasets. System prompts are baked into `services/dataset_service.py` as module constants; the Q&A dataset unions `qa_exchanges` + `library_qa_exchanges` + `qa_history_exchanges` ordered by `created_at`.

### Q&A History Chat
A dedicated page at `/qa-history` where the user asks meta-questions across every Q&A they have ever run ("summarize everything I've learned about tariffs"). Powered by the `qa_library_global` collection plus a synthesis LLM (`qa_history_agent.py`). References link back to the originating job detail page or the library Q&A page so the user can jump to the source exchange.

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
| `backend/app/models/document.py` | Document model (global library — formerly `Video`) |
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

POST   /api/v1/qa-history/chat               # Ask meta-question across all Q&A history
GET    /api/v1/qa-history/exchanges          # List history chat exchanges
POST   /api/v1/videos/{id}/extract-knowledge # Run knowledge extraction (409 if exists unless ?force)
GET    /api/v1/videos/{id}/knowledge         # Fetch stored knowledge artifact
GET    /api/v1/exports/qa-dataset/openai.jsonl         # Q&A dataset, OpenAI chat format
GET    /api/v1/exports/qa-dataset/tuple.jsonl          # Q&A dataset, plain tuple format
GET    /api/v1/exports/knowledge-dataset/openai.jsonl  # Knowledge dataset, chat format
GET    /api/v1/exports/knowledge-dataset/tuple.jsonl   # Knowledge dataset, tuple format

WS     /ws/jobs                        # Multiplexed progress (subscribe/unsubscribe per job)
```

## Environment Variables

Copy `.env.example` to `backend/.env` and fill in required keys:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `YOUTUBE_API_KEY` | Yes | — | YouTube Data API v3 key |
| `REDDIT_CLIENT_ID` | No | — | Reddit script-app client ID; required for the Reddit connector (S-1.5.1). Register at https://www.reddit.com/prefs/apps |
| `REDDIT_CLIENT_SECRET` | No | — | Reddit script-app client secret |
| `REDDIT_USER_AGENT` | No | `pratidhvani/0.1 (by u/anonymous)` | Reddit-required UA string — bad/empty UAs are aggressively rate-limited |
| `REDDIT_RATE_LIMIT_RPM` | No | `100` | Requests/minute on Reddit's free OAuth tier; client spaces calls accordingly |
| `REDDIT_COMMENT_DEPTH_DEFAULT` | No | `50` | Top-N comments by score to flatten alongside the OP body |
| `OPENAI_API_KEY` | Yes* | — | Required if any use case resolves to `openai` (most defaults do) |
| `ANTHROPIC_API_KEY` | No | — | Required if any use case resolves to `anthropic` |
| `GOOGLE_API_KEY` | No | — | Required if any use case resolves to `google` |
| `DATABASE_URL` | No | `sqlite:///./data/videoresearchpro.db` | SQLAlchemy connection string |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis for pub/sub |
| `CELERY_BROKER_URL` | No | `redis://localhost:6379/1` | Celery broker |
| `CHUNK_SIZE` | No | `512` | RAG chunk size in tokens |
| `RAG_TOP_K` | No | `15` | Number of RAG results per query |
| **Transcript-pipeline resilience (E-1.11 / D-051)** | | | |
| `YOUTUBE_TRANSCRIPT_RATE_LIMIT` | No | `3.0` | Min seconds between transcript fetches (0.5 triggered an IP block at ~60 videos) |
| `YOUTUBE_TRANSCRIPT_RATE_JITTER` | No | `0.4` | ± fraction of the base rate randomized per wait |
| `YOUTUBE_SEARCH_MAX_PAGES` | No | `2` | Search pages per broad query (each page = 100 quota units, 50 results) |
| `TRANSCRIPT_BREAKER_THRESHOLD` | No | `3` | Consecutive IP-block signals before the circuit breaker opens |
| `TRANSCRIPT_BREAKER_COOLDOWN_BASE` | No | `120` | First cooldown (s); doubles per re-trip |
| `TRANSCRIPT_BREAKER_COOLDOWN_MAX` | No | `900` | Cooldown ceiling (s) |
| `TRANSCRIPT_BREAKER_MAX_WAIT` | No | `300` | Max per-video wait (s) for an open breaker before falling to Whisper |
| `WHISPER_SEGMENT_TARGET_MB` | No | `20` | Target chunk size when splitting >25 MB audio for Whisper |
| `WHISPER_SEGMENT_OVERLAP_SECONDS` | No | `15` | Shared audio between neighbouring Whisper chunks |
| `WHISPER_MAX_PER_JOB` | No | `50` | Max Whisper transcriptions per job (`0` disables Whisper) — bounds OpenAI spend |
| `YOUTUBE_PROXY_URL` | No | (unset) | Proxy for transcript API + yt-dlp (`http://…` or `socks5://…`) — the D-051 escape hatch for IP blocks |
| `YTDLP_COOKIES_FROM_BROWSER` | No | (unset) | Opt-in: use the operator's logged-in browser session for yt-dlp (`chrome`, `firefox`, `chrome:Profile`) — passes YouTube's bot-wall; requests then carry the operator's account |
| `YTDLP_COOKIES_FILE` | No | (unset) | Netscape-format cookies.txt for yt-dlp (browser source wins when both set) |
| `YTDLP_DOWNLOAD_RATE_LIMIT` | No | `2.0` | Min seconds between yt-dlp download attempts (burst downloads escalate the bot-wall) |
| `EMBEDDING_MODEL_NAME` | No | `paraphrase-multilingual-MiniLM-L12-v2` | SentenceTransformer model |
| `CHROMA_GLOBAL_COLLECTION_NAME` | No | `videoresearchpro_global` | Name of the single global Chroma collection |
| `CHROMA_QA_COLLECTION_NAME` | No | `qa_library_global` | Central Q&A collection name |
| `KNOWLEDGE_EXTRACT_BATCH_TOKENS` | No | `8000` | Max tokens per extract batch |
| `KNOWLEDGE_MAX_TRANSCRIPT_TOKENS` | No | `60000` | Max transcript size for knowledge extraction |
| `LLM_USE_CASE_CONFIG` | No | (unset) | Primary per-use-case override knob — see "LLM configuration" below |
| `LLM_LOCAL_BASE_URL` | No | (unset) | Base URL for the local OpenAI-compatible server (LM Studio, Ollama, vLLM, llama.cpp-server) used when a use case resolves to `provider=local` |
| `LLM_LOCAL_API_KEY` | No | `not-needed` | API key for the local endpoint; most servers ignore this but the OpenAI SDK validator requires a non-empty string |
| `LLM_ROUTE_OVERRIDES` | No | (unset) | **Deprecated.** Binary `use_case=primary\|fast` knob. Honored as a lower-precedence fallback. New work should use `LLM_USE_CASE_CONFIG` |
| `LLM_FAST_MODEL` | No | `gpt-4.1-mini` | **Deprecated.** Legacy fast-slot model name; consulted only by `LLM_ROUTE_OVERRIDES=...=fast` fallback path |
| `LLM_FAST_BASE_URL` | No | (unset) | **Deprecated.** Legacy alias for `LLM_LOCAL_BASE_URL`; still honored when the canonical name is unset |
| `LLM_FAST_API_KEY` | No | `not-needed` | **Deprecated.** Legacy alias for `LLM_LOCAL_API_KEY` |
| `LLM_MODEL` | No | `gpt-5` | **Deprecated.** Legacy primary-model name retained for back-compat; per-use-case defaults live in `app/services/llm_routing.py::USE_CASE_REGISTRY` |
| **Auth hardening (E-5.4)** | | | |
| `LOCKOUT_FAILURE_THRESHOLD` | No | `5` | Failed-login count before account locks. Set `0` to disable lockout (not recommended). |
| `LOCKOUT_DURATION_MIN` | No | `15` | How long an account stays locked (minutes). |
| `PASSWORD_RESET_TOKEN_TTL_MIN` | No | `30` | Password-reset token validity window (minutes). Single-use. |
| `MFA_ISSUER_NAME` | No | `Pratidhvani` | Issuer label shown by the user's authenticator app. |
| `SMTP_HOST` | No | (unset) | SMTP server for password-reset emails. When unset, the secret is returned in the API response + logged so self-host operators can hand it off out-of-band (per T-5.4.8). |
| `SMTP_PORT` | No | `587` | SMTP port. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | No | (unset) | SMTP auth. Both required, or both unset for anonymous relays. |
| `SMTP_FROM_ADDRESS` | No | `no-reply@<SMTP_HOST>` | Sender envelope. |
| `SMTP_USE_SSL` | No | `False` | SMTPS-on-connect (port 465 typical). |
| `SMTP_USE_STARTTLS` | No | `True` | STARTTLS after connect (port 587 typical). |
| `OAUTH_GOOGLE_CLIENT_ID` / `OAUTH_GOOGLE_CLIENT_SECRET` | No | (unset) | Google OAuth 2.0 + PKCE. Both must be set; endpoint returns 503 when unconfigured. |
| `OAUTH_GITHUB_CLIENT_ID` / `OAUTH_GITHUB_CLIENT_SECRET` | No | (unset) | GitHub OAuth 2.0 + PKCE. |
| `OAUTH_REDIRECT_BASE_URL` | No | (unset) | Override the redirect base when frontend lives on a different origin. |
| **Rate limiting (E-5.5)** | | | |
| `RATE_LIMIT_ENABLED` | No | `True` | Kill switch. Set `False` for dev / under-test. |
| `RATE_LIMIT_PER_MIN_FREE` / `_PRO` / `_STUDIO` | No | `60` / `600` / `6000` | Per-user-tier caps for authenticated routes (req/min). |
| `RATE_LIMIT_PER_MIN_UNAUTH` | No | `100` | Per-IP cap for unauthenticated GETs. |
| `RATE_LIMIT_LOGIN_PER_MIN` | No | `10` | Per-IP credential-stuffing defence on `/auth/login`. |
| `RATE_LIMIT_RESET_PER_MIN` | No | `5` | Per-IP cap on `/auth/password-reset/{request,confirm}`. |
| `RATE_LIMIT_REGISTER_PER_MIN` | No | `5` | Per-IP cap on `/auth/register`. |
| **BYOK + MFA encryption (E-5.6 / E-5.4)** | | | |
| `BYOK_ENCRYPTION_KEY` | **Yes (production)** | (unset) | Fernet key (32 url-safe base64-encoded bytes; generate via `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`). Encrypts BYOK provider keys + MFA secrets. When unset, a process-local key is generated at startup with a loud warning — stored credentials become unrecoverable on restart in that mode. Single shared key per [D-043](docs/decisions.md#d-043). |

\* One provider key is effectively mandatory: whichever provider your resolved use cases point at. Defaults ship pointing at `openai`, so `OPENAI_API_KEY` is required out of the box.

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
- **Global document library**: Documents are never job-owned. Any job selects from the global library via `job_videos`. The ORM class is `Document` (`app.models.document`); the table is `documents`. Legacy column name `video_id` is preserved on the PK and FK until a future PR promotes it to a UUID.
- **Single global Chroma collection**: All chunks live in `videoresearchpro_global`. Per-job scoping is a metadata filter at query time. Deleting a job does NOT delete chunks.
- **Per-use-case LLM config**: Call sites resolve their (provider, model, reasoning) triple via `app/services/llm_routing.py::resolve_config(use_case)`. Override per use case with `LLM_USE_CASE_CONFIG` (see "LLM configuration" below). The legacy `get_llm(..., purpose='fast')` / `LLM_ROUTE_OVERRIDES` knobs are still honored as deprecated fallbacks.

### Multilingual transcription

- Whisper is called with `task="transcribe"` (not `translate`), preserving the speaker's language(s). Mixed-language audio (e.g., Hindi-English code-mixed) is transcribed faithfully, with proper nouns in their original script.
- The multilingual embedding model (`paraphrase-multilingual-MiniLM-L12-v2`) ensures a Hindi transcript and its English question land in similar vector space.
- The Q&A agent accepts an `answer_language` parameter (default English) and is instructed to translate quoted non-English context into English (preserving proper nouns) while responding in the requested language.

## LLM configuration

Every LLM call site in the codebase is a named **use case** with a default `(provider, model, reasoning)` triple registered in `app/services/llm_routing.py::USE_CASE_REGISTRY`. The registry is the source of truth; `LLM_USE_CASE_CONFIG` is the knob for overriding any entry without editing code.

### The primary knob: `LLM_USE_CASE_CONFIG`

Comma-separated entries. Each entry is `use_case=provider:model[:reasoning]`:

```
LLM_USE_CASE_CONFIG=qa_formulate_answer=openai:gpt-5.4:medium,qa_clarification=local:qwen/qwen3-9b:off,knowledge_synthesize_report=anthropic:claude-opus-4-5:medium
```

Missing use cases fall back to the registry `default_config`. Unknown names, unknown providers, and unknown reasoning levels are logged as warnings and ignored — **never fatal**, so a typo in your `.env` does not take down the app.

### Supported providers

| Provider | Client | Credentials |
|----------|--------|-------------|
| `openai` | `langchain_openai.ChatOpenAI` | `OPENAI_API_KEY` |
| `anthropic` | `langchain_anthropic.ChatAnthropic` | `ANTHROPIC_API_KEY` |
| `google` | `langchain_google_genai.ChatGoogleGenerativeAI` | `GOOGLE_API_KEY` |
| `local` | OpenAI-compatible endpoint (LM Studio, Ollama, vLLM, llama.cpp-server) | `LLM_LOCAL_BASE_URL` + `LLM_LOCAL_API_KEY` |

### Reasoning levels

Normalized across providers. Unsupported levels for a provider degrade gracefully.

| Provider | Accepted levels | Mapping |
|----------|-----------------|---------|
| OpenAI | `off`, `minimal`, `low`, `medium`, `high` | `reasoning_effort` |
| Anthropic | `off`, `low`, `medium`, `high`, `auto` | `thinking.budget_tokens` (auto → medium) |
| Google | `off`, `low`, `medium`, `high`, `auto` | `thinkingBudget` (auto → `-1`) |

### Precedence

From highest to lowest:

1. `LLM_USE_CASE_CONFIG` — inline per-use-case provider/model/reasoning
2. `LLM_ROUTE_OVERRIDES` — legacy binary `primary|fast` (route=fast flips the provider to `local`)
3. Registry `default_config` in `app/services/llm_routing.py`

### Registered use cases

Nineteen named call sites — full rationale, token budgets, and recommended minimum context live in the registry alongside each entry.

**Job Q&A (`app/agents/qa_agent.py`):**
- `qa_clarification` — short follow-up clarifier before answering
- `qa_sub_query_expansion` — rewrite the question into 2 sub-queries for broader RAG recall
- `qa_refine_context` — compress raw RAG + report context (p95 45K in) into a focused excerpt
- `qa_formulate_answer` — final user-facing answer with citations (temperature 0)
- `qa_extract_references` — parse the answer back into structured `(video_id, ts, quote)`

**Library-wide Q&A:**
- `library_qa_clarification` — clarifier variant for library-scoped questions
- `library_qa_refine_context` — library variant of context compression
- `library_qa_formulate_answer` — final library-scoped answer with citations

**Q&A History meta-chat (`app/agents/qa_history_agent.py`):**
- `qa_history_refine_context` — compact retrieved past exchanges before synthesis
- `qa_history_formulate_answer` — synthesize a meta-answer citing past exchange IDs

**Per-video Knowledge extraction (`app/agents/knowledge_agent.py`):**
- `knowledge_extract_batch` — map phase; structured `{topics, concepts, events, facts}` JSON per batch
- `knowledge_synthesize_report` — reduce phase; Markdown knowledge report

**Topic search (`app/agents/search_agent.py`):**
- `search_plan_queries` — plan 3-5 YouTube search queries from topic + instructions
- `search_rank_and_curate` — rank + dedup results into the final video list (biggest reasoning-mode win in the app)

**Report generation (`app/agents/report_agent.py`):**
- `report_map_chunks` — map phase; per-batch fact extraction (highest-volume call in the codebase)
- `report_reduce_summaries` — reduce phase; consolidate per-batch summaries
- `report_compose` — final HTML report composition (long user-facing output)
- `report_channel` — channel-report composition for channel jobs
- `report_compose_channel_section` — per-channel section composer inside the channel-report pipeline

## LLM startup smoke check + fail-soft

`run_startup_probes` in `app/services/llm_smoke.py` runs once from the FastAPI lifespan. It resolves the effective `UseCaseConfig` for all 19 entries, **dedupes by `(provider, model)`** so each unique pair is probed exactly once, and fans a trivial one-token probe per unique config out via `asyncio.to_thread` (provider SDKs are synchronous). Results are stored on a process-global `LLMStatus` singleton.

**Health endpoints:**
- `GET /api/v1/health` — overall status plus an `llm` field with `status` (`ok` / `degraded` / `down` / `unknown`) and `unavailable_features` (a list of feature names whose required use cases failed probing).
- `GET /api/v1/health/llm` — full per-use-case detail: `provider`, `model`, `reasoning`, `ok`, `latency_ms`, `error`.

**Failure mode.** When a probe fails, the app **stays up**. The frontend shows a banner driven by the health response, and pages whose primary action depends on a failed feature disable that action (Ask question, Generate report, Extract knowledge). Non-LLM features remain fully interactive: viewing existing jobs, browsing the library, opening past reports, and downloading dataset exports. The Celery worker does not share this lifespan; task-time LLM failures surface on the Jobs page as usual.

## LLM stress testing

`backend/scripts/stress_test_llm.py` is the canonical harness for measuring per-request latency (p50 / p95 / max), single-request throughput, and aggregate throughput across a sweep of concurrency levels. It accepts either `--use-case <name>` (reads provider/model/reasoning from the registry) or explicit `--provider / --model / --reasoning` flags so you can benchmark an ad-hoc combination before committing it to `LLM_USE_CASE_CONFIG`. `stress_test_local_llm.py` is now a thin shim that delegates to this script.

```bash
cd backend
./venv/Scripts/python scripts/stress_test_llm.py --use-case qa_formulate_answer
./venv/Scripts/python scripts/stress_test_llm.py --provider local --model qwen/qwen3-9b --concurrency 1 2 4 8
```

Note: embeddings are already local — we use SentenceTransformer (`paraphrase-multilingual-MiniLM-L12-v2`) on CPU. No embeddings API cost.
