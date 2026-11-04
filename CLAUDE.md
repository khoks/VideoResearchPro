# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Pratidhvani (प्रतिध्वनि)** — Sanskrit for "echo". A full-stack personal research wiki. Users submit jobs to ingest sources (today: YouTube by topic search, channel list, or channel subscription; future: podcasts, articles, forum threads, PDFs — see [docs/source-types.md](docs/source-types.md)), contribute them to a **global, deduplicated document library**, generate comprehensive HTML reports via LangGraph agents (map-reduce pattern), and ask citation-backed questions either scoped to a single job, across the **entire library**, or across **every Q&A they've ever asked**. Transcripts, embeddings, and knowledge artifacts are computed once per document and reused across every job that references them.

> **Legacy name.** The project was previously called *VideoResearchPro*. The legacy string survives in the default database file (`DATABASE_URL`'s `sqlite:///./data/videoresearchpro.db`, which `backend/alembic.ini` repeats, grandfathered by [D-032](docs/decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03)), in the browser's `localStorage` keys `videoresearchpro.authToken` and `videoresearchpro.authUser` (renaming them signs every browser out), in the Celery app's internal name, and in the repository's URL. The Chroma default is **not** grandfathered: `CHROMA_GLOBAL_COLLECTION_NAME` defaults to `pratidhvani_global` since T-2.6.1 (PR #106). `videoresearchpro_global` exists only on an install that embedded before then and pins that name in its `.env` ([runbook](docs/migration-code-identifiers.md)). All user-facing copy now reads `Pratidhvani`.

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
- **Researched build plans for L2 / L3 / M1 to M12, and the build order:** [docs/plans/README.md](docs/plans/README.md), [docs/plans/build-order.md](docs/plans/build-order.md)
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
- **Vector DB**: ChromaDB with PersistentClient, sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2` embeddings (five global collections: `pratidhvani_global` for transcript chunks, `qa_library_global` for Q&A exchanges, and the tenant-filtered `notes_global`, `shares_global` and `personal_context_global`)
- **AI Agents**: 7 agents in `app/agents/`: 5 LangGraph graphs (Search, Report, Q&A, Knowledge, Echo) and 2 plain pipelines (Q&A-History, Visual), + per-use-case LLM config (OpenAI / Anthropic / Google / local OpenAI-compatible)
- **Auth**: JWT with revocable sessions, email+password, Google and GitHub OAuth (PKCE), two-step verification (TOTP + recovery codes), user-scoped jobs + Q&A history + knowledge artifacts
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
# All backend tests (3,700+; `pytest tests/ --collect-only -q` prints the count)
cd backend && ./venv/Scripts/python -m pytest tests/ -v

# Single test file
cd backend && ./venv/Scripts/python -m pytest tests/test_routers/test_jobs.py -v

# Single test
cd backend && ./venv/Scripts/python -m pytest tests/test_routers/test_jobs.py::test_create_topic_job -v

# Frontend type check
cd frontend && npm run build

# Browser extension's logic (S-3.7.3; Node's built-in runner, no install)
cd extension && npm test

# Markdown anchor links (T-4.8.5): a dry run by default, --check as in CI, --write to repair
cd backend && ./venv/Scripts/python scripts/fix_anchor_links.py --check
```

### One-shot launcher (recommended for dev)
```powershell
# Starts Redis (if needed), backend, Celery worker, ONE Celery beat (the
# scheduler tick), frontend; waits for health; opens browser; blocks until
# Ctrl+C, then tears everything down.
./scripts/start.ps1                # foreground; Ctrl+C stops everything
./scripts/start.ps1 -NoBrowser     # skip auto-open
./scripts/start.ps1 -NoFrontend    # backend + Celery only
```
Logs land in `.uvicorn.*.log` / `.celery.*.log` / `.celerybeat.*.log` / `.frontend.*.log` at the repo root (gitignored). For an in-place restart (kill + relaunch detached) use `./scripts/restart_services.ps1`. Both scripts are the single-beat guard: they kill any earlier beat before starting one (never run two).

### Infrastructure
```bash
# Redis is installed natively via: winget install Redis.Redis
# It runs as a Windows service automatically on port 6379
# Verify with:
redis-cli ping    # Should return PONG

# Start Celery worker (use --pool=solo on Windows)
cd backend && ./venv/Scripts/celery -A app.tasks.celery_app worker --loglevel=info --pool=solo

# Start the scheduler beat (S-8.3.1) — exactly ONE per install; no --pidfile
# (Celery's stale-pid probe terminates an unrelated process on Windows)
cd backend && ./venv/Scripts/celery -A app.tasks.celery_app beat --loglevel=info -s data/celerybeat-schedule
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
- `documents` (renamed from `videos` in L1 PR 4) is a shared, global, deduplicated table: one row per source, whatever its type (YouTube videos, threads, podcasts, articles, PDFs, pasted pages). The primary key is `document_id`, a UUID (E-1.10); the legacy `video_id` column survives, NULL for every non-video source. The ORM class is `Document` in `app/models/document.py`.
- `channels` stores the shared facts about YouTube channels (name, subscriber count, uploads playlist). Per-user state — `subscribed`, `source_weight`, `last_synced_at` — lives in `channel_subscriptions` and goes through `subscription_service` (D-065; the global columns were dropped in S-5.10.3). (`Creator` is already an alias of the `Channel` class; the table rename to `creators` waits on E-1.9.)
- `job_documents` is a many-to-many join linking jobs to the documents they selected (composite primary key `(job_id, document_id)`; the Python class is still `JobVideo`).
- Deleting a job drops its `job_documents` rows but leaves the documents and their chunks in the library — other jobs can still reference them.
- Transcripts are cached in `transcript_cache` (primary key `document_id`) and reused across jobs.

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
Single multiplexed WebSocket at `/ws/jobs`. Clients send `subscribe`/`unsubscribe` messages per job_id, or `topic: "notifications"` for the bell. Celery workers publish progress to Redis pub/sub (`job_progress:{job_id}`, `notifications:{tenant_id}`). The WebSocket manager listens on Redis and fans out to subscribed clients.

### RAG Pipeline
**Single global ChromaDB collection** named `pratidhvani_global` by default (`CHROMA_GLOBAL_COLLECTION_NAME`). Transcripts are chunked at 256 tokens with 32-token overlap (env `CHUNK_SIZE`/`CHUNK_OVERLAP`), preserving timestamp mappings from YouTube transcript segments. Embeddings are computed exactly once per video using the multilingual `paraphrase-multilingual-MiniLM-L12-v2`.

- Per-job Q&A filters by `document_id ∈ the job's approved set` at query time (`chroma_service.query_collection(..., document_ids=[...])`).
- Library-wide Q&A filters by `document_id ∈ the asking tenant's visible set` (D-063, keyed on the primary key per D-070). Chroma has no tenant concept, so the caller must pass the set — an **empty** list means "this tenant has ingested nothing" and retrieves nothing (enforced inside `query_collection`; only `None` is unrestricted, and no user-facing caller passes it).
- **Trust weights re-rank, never filter** ([D-068](docs/decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18)): job and library Q&A routers resolve the asker's weights with `subscription_service.channel_weights`; `qa_agent._scoped_query` draws 3 × top-K, applies `RAG_DISTANCE_THRESHOLD` to the RAW distance first, then sorts by `distance / weight`. Never store a weight on a chunk (chunks are shared across tenants). No weights set means one top-K query, identical to before.
- Every chunk carries a `document_id` metadata field, written by `_build_video_metadata` for every source type; chunks embedded before 2026-10-19 are stamped by `backfill_chunk_document_ids`, which runs in the API lifespan (`app/main.py`) and, since S-5.10.5, when a Celery worker starts, before it consumes any task (the `worker_ready` hook `run_startup_backfills` in `app/tasks/celery_app.py`), so a worker-only start stamps them too. The hook then closes the Chroma client and drops the model, because a prefork pool forks replacement children from that process. Chunk ids are `{video_id}:{index}` for YouTube documents and `{document_id}:{index}` for everything else — a storage key only.

### LangGraph Agents
- **Search Agent**: resolve_preferred_channels → plan_searches → execute_searches → rank_and_curate (topic jobs only)
- **Report Agent**: compute_statistics → map_chunks → reduce_summaries → compose_report (map-reduce for large transcript sets; channel jobs go straight to compose_channel_report, stats-only)
- **Knowledge Agent**: split_transcript → extract_per_batch → merge_extractions → synthesize_report (one document at a time; see Video Knowledge Artifacts below)
- **Echo Agent**: classify_intent → retrieve_relevant_knowledge → retrieve_voice_signals → retrieve_personal_context → draft → self_critique_against_voice → revise (back to the critique) or finalize ("speak as me", S-3.4.1)
- **Not graphs** (plain functions in `app/agents/`): the Q&A-History agent (retrieve → refine → formulate) and the Visual pipeline (select moments → capture → describe → persist)
- **Q&A Agent**: retrieve_context → refine_context → formulate_answer → extract_references (LLM-based context refinement compacts ~45K raw RAG+report into ~3K focused extracts before answering; topic jobs use RAG + report, channel jobs use RAG only, subscription jobs have no report and are only queried via library-wide Q&A; accepts an `answer_language` parameter; citations include `&t=` timestamp links). The routers pass `corpus_statistics` (from `corpus_stats_service`) and the length preference, so the answer budget and brief follow corpus size (R4) and the prompt sees the publication span, each source's date and discussed era (R3)

### Q&A Library RAG
One central ChromaDB collection (`qa_library_global`) indexes every Q&A exchange from all three surfaces (job-scoped, library-scoped, history-chat) as single documents — question and answer concatenated, not chunked. New Q&As are upserted post-commit on a best-effort basis (Chroma failures never break the Q&A response). `backfill_qa_library` idempotently upserts every existing row from `qa_exchanges`, `library_qa_exchanges`, and `qa_history_exchanges`; it runs inline in the API lifespan and, since S-5.10.5, as the `chroma.backfill_qa_library` task that the worker's `worker_ready` hook queues when a worker starts (queued, not inline, because it re-embeds every exchange on every run; before S-5.10.5 only the API ran it). This is the retrieval backbone for the Q&A History Chat page.

### Video Knowledge Artifacts
On-demand per-document knowledge extraction, for every source type. Every document row carries three nullable columns — `extracted_knowledge_json`, `knowledge_report_md`, `knowledge_extracted_at`. A "Knowledge report" button (job page rows, and every library row whose text has been read) triggers a map-reduce LangGraph agent (`knowledge_agent.py`) that splits the full text into token-budgeted batches, extracts structured `{topics, concepts, events, facts}` per batch, merges with dedupe, and synthesizes a report-style Markdown document. The text comes from `document_text_service.full_text`, keyed on `document_id`: the `transcript_cache` row for a YouTube video, otherwise the document's Chroma chunks reassembled in `chunk_index` order with the chunk overlap removed (PDFs, pasted pages, threads and podcast episodes keep their text nowhere else). The prompts name the source by its type (`knowledge_prompts.SOURCE_PROFILES`); a video's wording is the original. Returns 409 if already extracted unless `?force=true`.

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
| `backend/app/agents/qa_history_agent.py` | Linear agent for the meta-chat across past Q&A (no LangGraph) |
| `backend/app/agents/knowledge_agent.py` | Map-reduce LangGraph agent for per-document knowledge reports |
| `backend/app/utils/chunking.py` | Transcript chunking with timestamp mapping (+ atomic visual annotations) |
| `backend/app/agents/visual_agent.py` | R1 visual pipeline: select moments -> capture -> describe -> persist |
| `backend/app/services/frame_service.py` | yt-dlp video fetch + ffmpeg frame extraction |
| `backend/app/services/visual_service.py` | Pure merge of frame descriptions into transcript segments |
| `backend/app/services/temporal_service.py` | R3: discussed-era extraction (`temporal_scope_extract`), persistence, prompt/metadata rendering |
| `backend/app/services/code_mixing_service.py` | R5 / N-002: word-level language of code-mixed text (romanised Hindi included) — lexicon tagger in production, `code_mixing_detect` LLM as the reference (D-080) |
| `backend/app/services/corpus_stats_service.py` | Corpus figures for Q&A (approved / visible document set) that drive the length policy and temporal note |
| `backend/app/services/document_text_service.py` | A document's full text by `document_id`: transcript cache, else its Chroma chunks reassembled with the overlap removed (knowledge extraction) |
| `backend/scripts/regenerate_report.py` | Re-run a completed job's report phase from cached transcripts (before/after measurement) |
| `backend/scripts/judge_report_sections.py` | Split a report into sections and judge each in full — replaces the 180,000-char judging cap |
| `backend/scripts/audit_report_intermediates.py` | Read a job's persisted map/reduce intermediates back: batch statuses, item counts, reduce accounting |
| `backend/app/agents/echo_agent.py` | "Speak as me" LangGraph agent; the verbatim, citation and private-name guards live here in code (S-3.4.1) |
| `backend/app/services/echo_voice_test_service.py` | The D-100 "which of these did you write?" test, one procedure for the app (`/echo/voice-test`) and `scripts/voice_match_harness.py`: hold-out, prompts, pairs, score, and the rolled-back what-if that keeps the live database unchanged (T-3.4.1.8) |
| `backend/app/services/echo_draft_edits.py` | What the user changed in a draft: only the words they TYPED are theirs, minus 8-word stretches repeated from the incoming message (the provenance guard for S-3.4.2, D-104) |
| `backend/scripts/echo_import.py` | Import an export into a user's Echo from the command line (`--email`, `--file`, `--preview`): the `/echo/import` flow for exports past the upload cap, such as Apple Health (S-3.7.5) |
| `backend/app/websocket/manager.py` | Redis pub/sub → WebSocket fan-out; closes a socket when its session is revoked (T-5.4.19) |
| `backend/app/services/youtube_service.py` | YouTube API + transcript fetching with language fallback + rate limiting |
| `backend/app/services/chroma_service.py` | ChromaDB collection management (singleton client) |
| `backend/app/services/embedding_service.py` | Multilingual embedder (`paraphrase-multilingual-MiniLM-L12-v2`) |
| `backend/app/models/channel.py` | Channel model (shared facts only; per-tenant state in `channel_subscription.py`) |
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

Every route the app mounts, by area. A backend test keeps this list in step with the routers. Request and response shapes: [docs/api-reference.md](docs/api-reference.md).

```
# Health
GET    /api/v1/health
GET    /api/v1/health/llm
GET    /api/v1/health/scheduler
GET    /api/v1/health/quota              # The install's YouTube Data API units today

# Auth and account
POST   /api/v1/auth/register
POST   /api/v1/auth/login                # A token, or {requires_mfa, mfa_token} under two-step verification
POST   /api/v1/auth/login/mfa            # Second step: 5 codes per ticket, one session per ticket
POST   /api/v1/auth/logout               # Ends this session on the server
POST   /api/v1/auth/password-reset/request
POST   /api/v1/auth/password-reset/confirm  # Signs the account out everywhere
POST   /api/v1/auth/password/change      # Signed in: keeps this session, ends the others
GET    /api/v1/auth/me
PUT    /api/v1/auth/me/tier              # Operators only
GET/PATCH /api/v1/auth/me/onboarding
GET    /api/v1/auth/audit-log            # ?scope=account: account and security events only
GET    /api/v1/auth/quota                # Usage against tier limits, per resource
GET/DELETE /api/v1/auth/sessions         # DELETE ?keep_current=true signs out everywhere else
DELETE /api/v1/auth/sessions/{jti}
GET    /api/v1/auth/mfa/status
POST   /api/v1/auth/mfa/enroll
POST   /api/v1/auth/mfa/verify-enrollment  # Returns the recovery codes, once
DELETE /api/v1/auth/mfa
GET    /api/v1/auth/oauth/providers
GET    /api/v1/auth/oauth/{provider}/start
GET    /api/v1/auth/oauth/{provider}/callback
GET    /api/v1/auth/credentials          # BYOK keys (Studio): metadata, never the key
GET    /api/v1/auth/credentials/providers
PUT/DELETE /api/v1/auth/credentials/{provider}
GET    /api/v1/settings/llm              # The caller's model choices, guidance and BYOK key state
PUT/DELETE /api/v1/settings/llm/{use_case}
POST   /api/v1/settings/llm/estimate
GET    /api/v1/usage                     # The caller's own usage by feature, today + last 30 days (E-5.2); recorded, never limited
POST   /api/v1/admin/restart             # Operators only

# Jobs and reports
POST   /api/v1/jobs                      # Create job → dispatches Celery task
GET    /api/v1/jobs                      # The caller's jobs
GET    /api/v1/jobs/{job_id}             # Job detail
PUT    /api/v1/jobs/{job_id}/approve     # Approve videos → resumes job
POST   /api/v1/jobs/{job_id}/cancel      # Cancel + revoke Celery task
DELETE /api/v1/jobs/{job_id}             # Delete job + report; documents and chunks stay in the library
POST   /api/v1/jobs/{job_id}/save-as-template
GET    /api/v1/jobs/{job_id}/videos      # Documents for job
GET    /api/v1/jobs/{job_id}/report      # Serve HTML report
GET    /api/v1/jobs/{job_id}/report/body  # Sanitised body for the reading room
GET    /api/v1/jobs/{job_id}/report.md   # Markdown source
POST   /api/v1/jobs/{job_id}/qa/clarify
POST   /api/v1/jobs/{job_id}/qa          # Ask question (runs Q&A agent)
POST   /api/v1/jobs/{job_id}/qa/stream   # The same over server-sent events, with stage progress
GET    /api/v1/jobs/{job_id}/qa          # Q&A history
GET/POST /api/v1/job-templates
GET/PUT/DELETE /api/v1/job-templates/{template_id}
GET    /api/v1/job-templates/{template_id}/versions

# Library
POST   /api/v1/library/qa                # Library-wide Q&A ask; `document_id` narrows it to one source (T-8.4.2.4)
GET    /api/v1/library/qa                # Library-wide Q&A history
POST   /api/v1/library/qa/clarify        # Library-wide clarify step
DELETE /api/v1/library/qa/{exchange_id}  # Delete a library Q&A exchange
GET    /api/v1/library/videos            # Browse the caller's documents
GET    /api/v1/library/video-channels
GET    /api/v1/library/graph
POST   /api/v1/library/upload-pdf
POST   /api/v1/library/paste-urls
GET    /api/v1/library/pdf/{digest}.pdf
PUT/DELETE /api/v1/library/videos/{document_id}/tags/{tag_id}
GET/POST /api/v1/tags
PUT/DELETE /api/v1/tags/{tag_id}
GET/POST /api/v1/shelves
GET/PUT/DELETE /api/v1/shelves/{shelf_id}
GET    /api/v1/shelves/{shelf_id}/documents
GET/POST /api/v1/shelves/{shelf_id}/qa
POST/DELETE /api/v1/shelves/{shelf_id}/jobs/{job_id}
GET    /api/v1/search?q=&types=&limit=   # Grouped tenant-scoped keyword search (FTS5, LIKE fallback)
GET    /api/v1/suggestions?context=      # "You might ask…": job:<id> | document:<id> | library (S-8.4.1)
POST   /api/v1/suggestions/feedback      # A suggestion was used (fill | ask), for click-through
GET/POST /api/v1/notes
GET/PUT/DELETE /api/v1/notes/{note_id}

# Channels
GET    /api/v1/channels                  # List all channels
GET    /api/v1/channels/{channel_id}     # Single channel detail
GET    /api/v1/channels/{channel_id}/intelligence
POST   /api/v1/channels/{channel_id}/subscribe
POST   /api/v1/channels/{channel_id}/unsubscribe
POST   /api/v1/channels/{channel_id}/sync  # Trigger a fresh sync
PUT    /api/v1/channels/{channel_id}/weight  # Set the caller's trust weight 0.0-2.0 (D-068 re-rank)

# Saved searches and notifications
GET    /api/v1/saved-searches            # Pinned library questions (Pro+), S-8.3.2
POST   /api/v1/saved-searches            # Pin: {question, cadence, scope?, notify_email?}
GET/PATCH/DELETE /api/v1/saved-searches/{saved_search_id}
POST   /api/v1/saved-searches/{saved_search_id}/run-now  # Queue a run now (quota checked first)
GET    /api/v1/saved-searches/{saved_search_id}/runs     # Run history: change signals, diff (S-8.3.3)
GET    /api/v1/notifications             # The bell: {items, unread}
PATCH  /api/v1/notifications/{notification_id}  # {read}
POST   /api/v1/notifications/read-all

# Q&A history, knowledge, frames, exports
POST   /api/v1/qa-history/chat           # Ask meta-question across all Q&A history
GET    /api/v1/qa-history/exchanges      # List history chat exchanges
POST   /api/v1/videos/{video_id}/extract-knowledge  # Run knowledge extraction (409 if exists unless ?force; ?output_length=auto|brief|standard|deep)
GET    /api/v1/videos/{video_id}/knowledge  # Fetch stored knowledge artifact
GET    /api/v1/videos/{video_id}/frames  # Captured frames (R1, S-1.18.2)
GET    /api/v1/videos/{video_id}/frames/{frame_id}/image  # One still (JPEG), visibility-checked
POST   /api/v1/videos/{video_id}/extract-frames  # Capture frames on demand (202, worker task)
GET    /api/v1/exports/qa-dataset/openai.jsonl         # Q&A dataset, OpenAI chat format
GET    /api/v1/exports/qa-dataset/tuple.jsonl          # Q&A dataset, plain tuple format
GET    /api/v1/exports/knowledge-dataset/openai.jsonl  # Knowledge dataset, chat format
GET    /api/v1/exports/knowledge-dataset/tuple.jsonl   # Knowledge dataset, tuple format
GET    /api/v1/exports/notes.jsonl       # Notes as W3C JSON-LD, withdrawals included
GET    /api/v1/exports/notes.md

# Author Studio
GET    /api/v1/author/kinds
GET    /api/v1/author/knowledge-sources  # Documents a deck can be planned from (S-6.3.2)
GET/POST /api/v1/author/outputs
POST   /api/v1/author/outputs/estimate
GET/DELETE /api/v1/author/outputs/{output_id}
POST   /api/v1/author/outputs/{output_id}/cancel
GET    /api/v1/author/outputs/{output_id}/content
GET    /api/v1/author/outputs/{output_id}/download
GET    /api/v1/author/outputs/{output_id}/citations
GET/PUT/DELETE /api/v1/author/newsletter
POST   /api/v1/author/newsletter/send-now

# Echo
GET    /api/v1/echo/status
GET/POST /api/v1/echo/context
DELETE /api/v1/echo/context/{kind}/{key}
DELETE /api/v1/echo/sources/{source}
GET/POST /api/v1/echo/shares
POST   /api/v1/echo/shares/upload
GET/PATCH/DELETE /api/v1/echo/shares/{share_id}
POST   /api/v1/echo/shares/{share_id}/process
POST   /api/v1/echo/shares/{share_id}/library
GET    /api/v1/echo/shares/{share_id}/file
GET/POST /api/v1/echo/share-tokens
DELETE /api/v1/echo/share-tokens/{token_id}
GET    /api/v1/echo/share-tokens/check
GET    /api/v1/echo/connectors
POST   /api/v1/echo/connectors/{name}/authorize
POST   /api/v1/echo/connectors/{name}/callback
POST   /api/v1/echo/connectors/{name}/sync
DELETE /api/v1/echo/connectors/{name}
GET    /api/v1/echo/activity
GET    /api/v1/echo/fact-tombstones      # Deleted derived facts ("Kept deleted"), T-3.2.4.4
DELETE /api/v1/echo/fact-tombstones/{tombstone_id}  # "Allow again"
POST   /api/v1/echo/import/preview
POST   /api/v1/echo/import
GET    /api/v1/echo/imports
GET/DELETE /api/v1/echo/imports/{import_id}
POST   /api/v1/echo/imports/{import_id}/embed
GET/POST /api/v1/echo/signals
POST   /api/v1/echo/signals/learn
GET    /api/v1/echo/signals/export
GET    /api/v1/echo/signals/rejected     # "That's not me" rows, T-3.3.1.6
POST   /api/v1/echo/signals/{signal_id}/restore
PATCH/DELETE /api/v1/echo/signals/{signal_id}
GET    /api/v1/echo/draft/status
POST   /api/v1/echo/draft
GET    /api/v1/echo/drafts
GET/DELETE /api/v1/echo/drafts/{draft_id}
POST   /api/v1/echo/drafts/{draft_id}/feedback
GET/POST /api/v1/echo/voice-test         # The in-app voice test, T-3.4.1.8. POST spends about 40 model calls
GET    /api/v1/echo/voice-test/{test_id}
PUT    /api/v1/echo/voice-test/{test_id}/picks
POST   /api/v1/echo/voice-test/{test_id}/score
GET    /api/v1/echo/cards
POST   /api/v1/echo/cards/dismiss
POST   /api/v1/echo/cards/shown
POST   /api/v1/echo/cards/act
GET/PUT /api/v1/echo/cards/settings
POST   /api/v1/echo/cards/seen/shares
GET    /api/v1/echo/export
GET    /api/v1/echo/brain/footprint
DELETE /api/v1/echo/brain

WS     /ws/jobs                          # Multiplexed progress (subscribe/unsubscribe per job) and the bell
```

## Environment Variables

Copy `.env.example` to `backend/.env` and fill in required keys. The repository holds one template, at the root ([D-112](docs/decisions.md#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25)). It lists every `Settings` field in the groups below, and `backend/tests/test_ci/test_docs_match_code.py` fails when the template or this table drifts from `app/config.py`, so a new setting goes in all three.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| **App and infrastructure** | | | |
| `APP_NAME` | No | `Pratidhvani` | Title of the FastAPI app, shown on the API docs page |
| `DEBUG` | No | `False` | Logs every SQL statement (`echo` on the SQLAlchemy engine) |
| `DATABASE_URL` | No | `sqlite:///./data/videoresearchpro.db` | SQLAlchemy connection string |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis for pub/sub |
| `CELERY_BROKER_URL` | No | `redis://localhost:6379/1` | Celery broker |
| `CELERY_RESULT_BACKEND` | No | `redis://localhost:6379/2` | Celery result store |
| `APP_BASE_URL` | No | `http://localhost:5173` | Base of the links in emails (saved-search alerts) |
| **YouTube** | | | |
| `YOUTUBE_API_KEY` | Yes | (unset) | YouTube Data API v3 key |
| `YOUTUBE_DAILY_QUOTA` | No | `10000` | The install's daily YouTube Data API units: the limit `/health/quota` reports usage against |
| `YOUTUBE_SEARCH_MAX_PAGES` | No | `2` | Search pages per broad query (each page = 100 quota units, 50 results) |
| **Transcript-pipeline resilience (E-1.11 / D-051)** | | | |
| `YOUTUBE_TRANSCRIPT_RATE_LIMIT` | No | `3.0` | Min seconds between transcript fetches (0.5 triggered an IP block at ~60 videos) |
| `YOUTUBE_TRANSCRIPT_RATE_JITTER` | No | `0.4` | ± fraction of the base rate randomized per wait |
| `TRANSCRIPT_BREAKER_THRESHOLD` | No | `3` | Consecutive IP-block signals before the circuit breaker opens |
| `TRANSCRIPT_BREAKER_COOLDOWN_BASE` | No | `120.0` | First cooldown (s); doubles per re-trip |
| `TRANSCRIPT_BREAKER_COOLDOWN_MAX` | No | `900.0` | Cooldown ceiling (s) |
| `TRANSCRIPT_BREAKER_MAX_WAIT` | No | `300.0` | Max per-video wait (s) for an open breaker before falling to Whisper |
| `WHISPER_SEGMENT_TARGET_MB` | No | `20` | Target chunk size when splitting >25 MB audio for Whisper |
| `WHISPER_SEGMENT_OVERLAP_SECONDS` | No | `15.0` | Shared audio between neighbouring Whisper chunks |
| `WHISPER_MAX_PER_JOB` | No | `50` | Max Whisper transcriptions per job (`0` disables Whisper) — bounds OpenAI spend |
| `YOUTUBE_PROXY_URL` | No | (unset) | Proxy for transcript API + yt-dlp (`http://…` or `socks5://…`) — the D-051 escape hatch for IP blocks |
| `YTDLP_COOKIES_FROM_BROWSER` | No | (unset) | Opt-in: use the operator's logged-in browser session for yt-dlp (`chrome`, `firefox`, `chrome:Profile`) — passes YouTube's bot-wall; requests then carry the operator's account |
| `YTDLP_COOKIES_FILE` | No | (unset) | Netscape-format cookies.txt for yt-dlp (browser source wins when both set) |
| `YTDLP_DOWNLOAD_RATE_LIMIT` | No | `2.0` | Min seconds between yt-dlp download attempts (burst downloads escalate the bot-wall) |
| **Other sources** | | | |
| `REDDIT_CLIENT_ID` | No | (unset) | Reddit script-app client ID; required for the Reddit connector (S-1.5.1). Register at https://www.reddit.com/prefs/apps |
| `REDDIT_CLIENT_SECRET` | No | (unset) | Reddit script-app client secret |
| `REDDIT_USER_AGENT` | No | `pratidhvani/0.1 (by u/anonymous)` | Reddit-required UA string — bad/empty UAs are aggressively rate-limited |
| `REDDIT_RATE_LIMIT_RPM` | No | `100` | Requests/minute on Reddit's free OAuth tier; client spaces calls accordingly |
| `REDDIT_COMMENT_DEPTH_DEFAULT` | No | `50` | Top-N comments by score to flatten alongside the OP body |
| `HN_USER_AGENT` / `HN_RATE_LIMIT_RPM` / `HN_COMMENT_DEPTH_DEFAULT` | No | `pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani)` / `60` / `50` | Hacker News connector (Algolia API, no key): User-Agent, requests/minute, top-N comments flattened alongside a story |
| `MASTODON_INSTANCE_BASE` | No | `https://mastodon.social` | Instance searched when a job names none |
| `MASTODON_USER_AGENT` / `MASTODON_RATE_LIMIT_RPM` / `MASTODON_COMMENT_DEPTH_DEFAULT` | No | `pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani)` / `60` / `50` | Mastodon connector: User-Agent, requests/minute, top-N replies |
| `BLUESKY_XRPC_BASE` | No | `https://public.api.bsky.app` | Public AT-Protocol endpoint; a private PDS can replace it |
| `BLUESKY_USER_AGENT` / `BLUESKY_RATE_LIMIT_RPM` / `BLUESKY_COMMENT_DEPTH_DEFAULT` | No | `pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani)` / `60` / `50` | Bluesky connector: User-Agent, requests/minute, top-N replies |
| `PODCAST_USER_AGENT` / `PODCAST_RATE_LIMIT_RPM` | No | `pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani)` / `60` | Podcast connector: User-Agent and requests/minute (iTunes search, RSS feeds) |
| `PODCAST_EPISODES_PER_SHOW` / `PODCAST_SEARCH_TOP_N_SHOWS` | No | `5` / `3` | A topic search returns up to shows × episodes candidates |
| `PODCAST_AUDIO_FETCH_TIMEOUT_SEC` | No | `180` | Audio download budget for the Whisper path (episodes run 50-150 MB) |
| `BRAVE_SEARCH_API_KEY` | No | (unset) | Web-article search; unset, articles come by pasted URL only |
| `BRAVE_SEARCH_BASE` | No | `https://api.search.brave.com/res/v1/web/search` | Brave Search endpoint |
| `ARTICLE_USER_AGENT` / `ARTICLE_SEARCH_RATE_LIMIT_RPM` | No | `pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani)` / `60` | Article fetches: User-Agent and search requests/minute |
| `ARTICLE_PLAYWRIGHT_ENABLED` / `ARTICLE_PLAYWRIGHT_TIMEOUT_SEC` | No | `False` / `30` | Headless Chromium fallback for pages that need scripts (opt-in install, `backend/requirements-spa.txt`) and its per-page budget in seconds |
| `TWITTER_BEARER_TOKEN` | No | (unset) | X / Twitter API v2 (BYOK, D-009). Set, tweet search turns on and `/health` reports `twitter_search_enabled`; unset, tweets come by pasted URL only |
| `TWITTER_API_BASE` | No | `https://api.twitter.com/2` | X API endpoint |
| `TWITTER_USER_AGENT` / `TWITTER_RATE_LIMIT_RPM` | No | `pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani)` / `60` | X client: User-Agent and requests/minute |
| `TWITTER_REPLY_DEPTH_DEFAULT` | No | `50` | Not read by any code yet |
| `PDF_UPLOAD_DIR` / `PDF_MAX_BYTES` | No | `./data/uploads/pdf` / `104857600` | Where uploaded PDFs are kept, and the upload cap (100 MB) |
| **RAG and ChromaDB** | | | |
| `CHROMA_PERSIST_DIR` | No | `./data/chroma` | Where ChromaDB keeps its files |
| `CHROMA_GLOBAL_COLLECTION_NAME` | No | `pratidhvani_global` | The one global collection of transcript chunks. An install that embedded under the legacy default `videoresearchpro_global` pins that name here or migrates ([runbook](docs/migration-code-identifiers.md)) |
| `CHROMA_QA_COLLECTION_NAME` | No | `qa_library_global` | Central Q&A collection |
| `CHROMA_NOTES_COLLECTION_NAME` | No | `notes_global` | The asker's own notes, one vector per live note, tenant-filtered (S-8.5.2) |
| `CHROMA_SHARES_COLLECTION_NAME` / `CHROMA_PERSONAL_CONTEXT_COLLECTION_NAME` | No | `shares_global` / `personal_context_global` | Echo's private collections (tenant-filtered). The full Echo delete sweeps both |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | No | `256` / `32` | RAG chunk size and overlap, in tokens |
| `RAG_TOP_K` | No | `15` | Number of RAG results per query |
| `RAG_DISTANCE_THRESHOLD` | No | `0.6` | Relevance cut on the raw distance, applied before any D-068 re-rank |
| `EMBEDDING_MODEL_NAME` | No | `paraphrase-multilingual-MiniLM-L12-v2` | SentenceTransformer model |
| `NOTES_INDEX_ENABLED` | No | `True` | Notes in Q&A retrieval: index writes on every note write, startup backfill, queries. The test suite turns it off |
| `NOTE_RETRIEVAL_WEIGHT` | No | `1.5` | D-068 re-rank weight for notes, after the raw threshold. Measured before shipping (docs/notes/2026-10-19-s852-note-weight-measurement.md) |
| **Jobs, reports and knowledge** | | | |
| `MAX_CONCURRENT_JOBS` | No | `5` | Active jobs across the whole install, counted over every user; one more is refused |
| `MAX_VIDEOS_PER_JOB` | No | `100` | Not read by any code (tier limits apply instead) |
| `DEFAULT_TRANSCRIPT_LANGUAGE` | No | `en` | Language the YouTube connector asks for when nothing says what is spoken |
| `REPORTS_DIR` | No | `./data/reports` | Where report files live |
| `MAX_REPORT_WORDS` | No | `20000` | Not read by any code (the length policy applies instead) |
| `REPORT_INTERMEDIATES_ENABLED` | No | `True` | Persist the report pipeline's per-batch map extractions and reduced dataset to `job_report_intermediates` (S-1.14.6), about twice the reduced dataset's size per run. Audit with `backend/scripts/audit_report_intermediates.py` |
| `REPORT_MAP_BATCHING` / `REPORT_MAP_BATCH_TOKENS` | No | `packed` / `120000` | How report map batches are filled (S-1.14.19, D-094): `packed` fills them in source order up to the token cap, `source` never puts two sources in one call and doubles report length. The window of the resolved model also caps a batch |
| `REPORT_MAP_CONCURRENCY` | No | `4` | Map calls in flight at once; results stay in batch order |
| `REPORT_ATTRIBUTION_GUARD_ENABLED` | No | `True` | The deterministic attribution guard for on-screen details (S-1.18.9). A no-op without visual spans |
| `KNOWLEDGE_EXTRACT_BATCH_TOKENS` | No | `8000` | Max tokens per extract batch |
| `KNOWLEDGE_MAX_TRANSCRIPT_TOKENS` | No | `60000` | Max transcript size for knowledge extraction |
| **Author Studio** | | | |
| `OUTPUTS_DIR` | No | `./data/outputs` | Author Studio artifacts (PDF, EPUB, PPTX, site zips), one directory per output: `<OUTPUTS_DIR>/<user_id>/<output_id>/` (S-6.7.2) |
| `AUTHOR_PDF_ENGINE` | No | `auto` | Book PDF converter (S-6.1.5): `auto` tries WeasyPrint (needs Pango) then Chromium via Playwright; `weasyprint` / `chromium` pin one; `off` disables PDF. Both are optional (`backend/requirements-author.txt`); EPUB and Markdown need neither. Probed once per process, so restart after installing. Off for the test suite |
| `AUTHOR_PDF_TIMEOUT_SEC` | No | `180` | Wall-clock budget for Chromium to launch and lay out one book |
| **Saved searches, notifications and suggestions** | | | |
| `SAVED_SEARCH_JACCARD_THRESHOLD` | No | `0.5` | S-8.3.3: a run whose cited document set overlaps the previous one less than this votes "changed". Pre-registered prior (docs/notes/2026-10-19-saved-search-change-thresholds.md); calibration pending |
| `SAVED_SEARCH_EMBEDDING_THRESHOLD` | No | `0.15` | S-8.3.3: an answer whose embedding is further than this (cosine distance) from the previous one votes "changed". Pre-registered prior; calibration pending |
| `SAVED_SEARCH_GATE_ENABLED` | No | `True` | Skip a scheduled saved-search run whose scope resolves to the same document set as the last good run (no quota, no model). Run now always asks |
| `NOTIFICATIONS_PUSH_ENABLED` | No | `True` | T-8.3.3.8: publish each new notification on `notifications:{tenant_id}` so an open bell refetches at once over `/ws/jobs`; the one-minute poll is the fallback. Off for the test suite |
| `SUGGESTIONS_CACHE_TTL_MIN` | No | `60` | How long a context's question suggestions (S-8.4.1) are reused before recomputing; a new exchange, report or knowledge state invalidates sooner. `0` = never reuse |
| **Scheduler (S-8.3.1 / M3)** | | | |
| `SCHEDULER_ENABLED` | No | `True` | Registers the single beat entry `scheduler.tick`; off = no entry and a tick that still arrives no-ops. Beat is its own process (`celery -A app.tasks.celery_app beat`), started by `scripts/start.ps1`; run exactly one |
| `SCHEDULER_TICK_SECONDS` | No | `300` | Tick interval; also the tick's `expires`, so a backlog never replays after a restart |
| `SCHEDULER_LEASE_SECONDS` | No | `600` | A row claim older than this is stale and may be re-taken (the holder crashed between claim and advance) |
| `SCHEDULER_GRACE_SECONDS` | No | `30` | Rows due within this window count as due, so an early beat still runs them; `next_run_at` advances from the scheduled time, never twice |
| `SCHEDULER_BATCH_SIZE` | No | `50` | Max rows one tick claims (bounds the catch-up after downtime) |
| `SCHEDULER_MAX_RETRY_TICKS` | No | `3` | A failed dispatch is retried at the next tick this many times, then waits for its cadence |
| **Usage metering (E-5.2)** | | | |
| `USAGE_FLUSH_INTERVAL_SECONDS` | No | `60` | How often an open metering scope writes what it has counted, so a worker that dies mid-task loses about this much of its usage, not the whole run (T-5.2.13). `0` = only when the scope closes |
| **Visual understanding (R1 / E-1.18)** | | | |
| `VISUAL_ENABLED` | No | `False` | Install-wide switch for frame capture + description. AND-ed with the per-job `visual_analysis` opt-in — both must be true. Off by default: capture needs a *video* stream (more yt-dlp traffic than the audio path that caused the D-051 IP block) and it is the app's largest multimodal spend |
| `VISUAL_FRAMES_DIR` | No | `./data/frames` | Where extracted JPEGs live, keyed by document so they are computed once and reused |
| `VISUAL_MAX_FRAMES_PER_VIDEO` | No | `12` | Per-document frame cap |
| `VISUAL_MAX_FRAMES_PER_JOB` | No | `200` | Per-job ceiling across all documents; unused per-video allowance returns to the pool |
| `VISUAL_MIN_GAP_SECONDS` | No | `20.0` | Minimum spacing between selected moments — without it the selector clusters on one dense passage |
| `VISUAL_FRAME_MAX_WIDTH` | No | `1280` | Downscale width before the vision call (cost scales with pixel count) |
| `VISUAL_FRAME_JPEG_QUALITY` | No | `5` | ffmpeg `-q:v` for extracted stills (2 = near-lossless, 31 = worst) |
| `VISUAL_MAX_VIDEO_DOWNLOAD_MB` | No | `400` | Skip the document rather than pull more than this for a handful of JPEGs |
| `VISUAL_CAPTURE_TIMEOUT_SEC` | No | `900` | Per-document wall-clock budget for download + extraction |
| **Temporal awareness (R3 / E-1.17)** | | | |
| `TEMPORAL_SCOPE_ENABLED` | No | `True` | Per-document discussed-era extraction on first ingest (`temporal_scope_extract`, one economy-tier call per NEW document). Off = every era reads as unknown, which is also how a missing value is treated |
| `TEMPORAL_SCOPE_WINDOW_TOKENS` | No | `1500` | Size of each of the three transcript windows (opening / middle / close) sampled for the era call |
| **Code-mixed speech (R5 / N-002 / D-080)** | | | |
| `CODE_MIX_DOMINANT_SHARE` | No | `0.6` | A Hindi-grammar span with at least this Hindi share is quoted in Devanagari (with transliteration + translation). The threshold is the user's; a lower one is more robust to the tagger's Devanagari blind spot (open question in D-080) |
| `CODE_MIX_ENGLISH_RENDERING_ENABLED` | No | `True` | Embed non-English chunks as an English rendering (`code_mixing_render_english`, once per document) while the stored text stays the original. Off = embed as written (retrieval MRR 0.40–0.57 instead of 0.81, D-084). Off for the test suite |
| `CODE_MIX_BORROWING_MAX_SHARE` | No | `0.2` | An English-grammar span with at most this Hindi share is rendered as plain English; between the two thresholds, quotes stay in Roman script |
| **Echo: shares, connectors and imports** | | | |
| `ECHO_SHARES_DIR` | No | `./data/echo/shares` | Echo shares inbox files, one directory per tenant; removed by the full Echo delete |
| `ECHO_SHARE_MAX_BYTES` / `ECHO_SHARE_TEXT_MAX_CHARS` | No | `26214400` / `50000` | Caps on one quick-share file (25 MB) and one text share |
| `ECHO_CONNECTOR_SYNC` | No | `celery` | How a connector sync runs after connecting and on "Sync now" (S-3.2.1): `celery` (`echo.sync_connector`), `inline`, or `off` (the suite). Scheduled syncs always go through the scheduler tick (`echo_sync`) |
| `ECHO_SHARE_PROCESSING` | No | `celery` | How shares are processed after intake: `celery` (the `echo.process_share` task), `inline` (in the request, single-process dev) or `off` (the test suite) |
| `ECHO_SHARE_EMBED_MAX_CHARS` | No | `2000` | Text embedded per share in `shares_global`: annotation, title and the opening of the extracted text |
| `ECHO_IMPORT_MAX_BYTES` / `ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES` | No | `209715200` / `1073741824` | Caps on one export upload (S-3.7.5, 200 MB) and on what a zip may unpack to (1 GB, a zip-bomb guard). Parsing streams, so memory stays flat |
| `ECHO_SHARE_TOKENS_MAX` | No | `10` | Active share tokens per tenant (S-3.7.3): the browser extension's credential, accepted only by the share intake routes |
| `ECHO_FETCH_TIMEOUT_SEC` / `ECHO_FETCH_ALLOW_PRIVATE` | No | `20` / `False` | Fetching an image shared by its address. Hosts resolving to private, loopback or link-local addresses are refused unless allowed (a self-hosted LAN) |
| `ECHO_IMPORT_TURN_GAP_MIN` / `ECHO_IMPORT_TURN_MAX_CHARS` | No | `10` / `2000` | A WhatsApp chat is stored as turns: consecutive messages from one sender at most this many minutes apart, up to this many characters |
| `ECHO_REMOTE_MEDIA` | No | `True` | Whether a shared image (vision fallback) or recording (Whisper) may go to a remote provider. Off, or a local-only tenant: images use on-device OCR only, recordings are skipped with a note |
| `ECHO_OCR_MIN_CHARS` / `ECHO_OCR_MIN_CONFIDENCE` | No | `20` / `0.9` | When an on-device OCR reading is kept rather than sent to the vision fallback (measured: English 0.978+, Hindi and mixed 0.87 or less) |
| `ECHO_OCR_THREADS` | No | `4` | ONNX threads for on-device OCR; the all-cores default was four times slower on a 32-thread machine |
| `ECHO_OCR_VISION_MAX_SIDE` / `ECHO_OCR_VISION_MAX_TOKENS` | No | `2048` / `4000` | Image downscale before the vision fallback, and its completion cap |
| `ECHO_MEDIA_DECODE_TIMEOUT_SEC` | No | `300` | ffmpeg wall-clock cap when reducing a shared recording to speech audio |
| **Echo readiness (S-3.5.1)** | | | |
| `ECHO_READY_FACTS_MIN` / `ECHO_READY_FACT_KINDS_MIN` | No | `30` / `3` | Readiness domain 1 (S-3.5.1): facts the user wrote, and distinct kinds. Every `ECHO_READY_*` threshold set to `0` switches that check off |
| `ECHO_READY_EVENTS_MIN` / `ECHO_READY_EVENT_DAYS_MIN` | No | `200` / `90` | Domain 2: activity events from any connector or import, and days between the first and last |
| `ECHO_READY_SIGNALS_MIN` / `ECHO_READY_SIGNAL_TYPES_MIN` | No | `50` / `4` | Domain 3: live voice signals, and distinct types |
| `ECHO_READY_SHARES_MIN` / `ECHO_READY_SHARE_TYPES_MIN` | No | `100` / `4` | Domain 5: shares, and distinct content types |
| `ECHO_READY_VOICE_PIECES_MIN` / `ECHO_READY_VOICE_WORDS_MIN` | No | `30` / `2000` | Voice floor: own-writing pieces OR words in one script (notes plus own-words shares) |
| `ECHO_READY_VOICE_SPREAD_MAX` / `ECHO_READY_VOICE_MIN_VECTORS` | No | `0.05` / `10` | Voice stability: max bootstrap-centroid spread of the note vectors in `notes_global`, and the vectors needed to measure it. Untuned |
| `ECHO_VOICE_TEST_NOTES_MIN` | No | `40` | Live notes before readiness says the user can take the D-100 voice test (reported, not gated) |
| **Echo signal extraction (S-3.3.2 / D-099)** | | | |
| `ECHO_SIGNAL_EXTRACTION` | No | `celery` | `celery` queues one `echo.extract_signals` run per tenant; `inline` runs in the request; `off` never runs (the test suite) |
| `ECHO_SIGNALS_MIN_NEW_INPUTS` | No | `10` | New, edited or deleted texts waiting before a run starts on its own ("Learn now" runs below it) |
| `ECHO_SIGNALS_BATCH_TOKENS` | No | `6000` | User text per economy-tier call |
| `ECHO_SIGNALS_MAX_PER_BATCH` / `ECHO_SIGNALS_MAX_OUTPUT_TOKENS` | No | `12` / `2500` | Candidates per call and the output cap that bounds them (reasoning stays off) |
| `ECHO_SIGNALS_MAX_BATCHES_PER_RUN` | No | `20` | Cost bound per run; a larger backlog is read over several runs |
| `ECHO_SIGNALS_IMPORT_SAMPLE` / `ECHO_SIGNALS_MIN_PASSAGE_WORDS` | No | `300` / `4` | An export import is one input: stylometry reads every own-words turn; the model reads at most this many turns of at least this many words, spread over the chat's timeline (T-3.3.2.10) |
| **Speak as me (S-3.4.1 / D-102)** | | | |
| `ECHO_SPEAK_AS_ME_ENABLED` | No | `False` | The install switch. Each user also needs a passed voice test (`echo_voice_gates`, written by the Echo page's test or `scripts/voice_match_harness.py user-score --record`), readiness and the Studio tier |
| `ECHO_DRAFT_CRITIQUE_ROUNDS` / `ECHO_DRAFT_CRITIQUE_TARGET` | No | `2` / `4.0` | Critique-and-revise rounds per draft, and the mean voice score (1-5) at which they stop early |
| `ECHO_DRAFT_SOURCES` | No | `6` | Library chunks retrieved for one draft |
| `ECHO_VOICE_TEST_GENERATION` | No | `celery` | How the in-app voice test's pairs are written (T-3.4.1.8): `celery` (`echo.generate_voice_test`), `inline` or `off` (the suite) |
| `ECHO_VOICE_TESTS_PER_DAY` | No | `3` | Voice tests one user may start per UTC day; each makes about 40 calls on `echo_draft`. `0` = no limit |
| `ECHO_PERSONAL_INDEX_ENABLED` | No | `True` | S-3.3.3: keep `personal_context_global` (one vector per live fact and signal) in step on every write and at startup. Off for the test suite, like `NOTES_INDEX_ENABLED` |
| **LLM providers and routing** | | | |
| `OPENAI_API_KEY` | Yes* | (unset) | Required if any use case resolves to `openai` (most defaults do) |
| `ANTHROPIC_API_KEY` | No | (unset) | Required if any use case resolves to `anthropic` |
| `GOOGLE_API_KEY` | No | (unset) | Required if any use case resolves to `google` |
| `LLM_USE_CASE_CONFIG` | No | (unset) | Primary per-use-case override knob — see "LLM configuration" below |
| `LLM_LOCAL_BASE_URL` | No | (unset) | Base URL for the local OpenAI-compatible server (LM Studio, Ollama, vLLM, llama.cpp-server) used when a use case resolves to `provider=local` |
| `LLM_LOCAL_API_KEY` | No | (unset) | API key for the local endpoint; most servers ignore it but the OpenAI SDK needs a non-empty string, so unset falls back to `LLM_FAST_API_KEY` |
| **Legacy LLM knobs (deprecated)** | | | |
| `LLM_ROUTE_OVERRIDES` | No | (unset) | **Deprecated.** Binary `use_case=primary\|fast` knob. Honored as a lower-precedence fallback. New work should use `LLM_USE_CASE_CONFIG` |
| `LLM_PRIMARY_PROVIDER` / `LLM_PRIMARY_MODEL` | No | `openai` / (unset) | **Deprecated.** Provider and model of the legacy primary slot; a blank model falls back to `LLM_MODEL` |
| `LLM_MODEL` | No | `gpt-5` | **Deprecated.** Legacy primary-model name retained for back-compat; per-use-case defaults live in `app/services/llm_routing.py::USE_CASE_REGISTRY` |
| `LLM_FALLBACK_MODEL` | No | `gpt-4o` | **Deprecated.** Legacy fallback for the primary slot |
| `LLM_MAX_CONTEXT_TOKENS` | No | `1047576` | Not read by any code (report batches are budgeted from `llm_routing.MODEL_CONTEXT_WINDOWS`) |
| `LLM_FAST_MODEL` | No | `gpt-4.1-mini` | **Deprecated.** Legacy fast-slot model name; consulted only by `LLM_ROUTE_OVERRIDES=...=fast` fallback path |
| `LLM_FAST_BASE_URL` | No | (unset) | **Deprecated.** Legacy alias for `LLM_LOCAL_BASE_URL`; still honored when the canonical name is unset |
| `LLM_FAST_API_KEY` | No | `not-needed` | **Deprecated.** Legacy alias for `LLM_LOCAL_API_KEY` |
| **Auth** | | | |
| `JWT_SECRET` | **Yes (production)** | (insecure dev value) | Signs every token. Blank falls back to the insecure value with a warning at startup |
| `JWT_ALGORITHM` / `JWT_EXPIRY_HOURS` | No | `HS256` / `24` | Token signing algorithm and lifetime |
| `LOCKOUT_FAILURE_THRESHOLD` | No | `5` | Failed-login count before account locks. Set `0` to disable lockout (not recommended). |
| `LOCKOUT_DURATION_MIN` | No | `15` | How long an account stays locked (minutes). |
| `PASSWORD_RESET_TOKEN_TTL_MIN` | No | `30` | Password-reset token validity window (minutes). Single-use. |
| `MFA_ISSUER_NAME` | No | `Pratidhvani` | Issuer label shown by the user's authenticator app. |
| `ADMIN_EMAILS` | No | (empty) | The install's operators, comma-separated and case-insensitive (T-5.2.8 / D-111). Only operators may switch tiers (`PUT /auth/me/tier`) or restart the services (`POST /admin/restart`); anyone else gets 403. Empty: the earliest-registered account is the operator, so a single-user install needs nothing. A multi-user install should name its operators. **Register the account before listing it**: sign-up verifies no email, so password registration refuses a listed address (403); Google or GitHub sign-in with that address, verified by the provider, still works, and startup warns about every listed address with no account |
| **Email (SMTP)** | | | |
| `SMTP_HOST` | No | (unset) | SMTP server for password-reset emails. When unset, the reset email (with its code) goes to the server log for the operator to hand over out-of-band. The code is never in the API response: it was until 2026-11-03 (T-5.4.8's `debug_secret`), which let anyone reset any account by its address. |
| `SMTP_PORT` | No | `587` | SMTP port. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | No | (unset) / (unset) | SMTP auth. Both required, or both unset for anonymous relays. |
| `SMTP_FROM_ADDRESS` | No | (unset) | Sender envelope. |
| `SMTP_USE_SSL` | No | `False` | SMTPS-on-connect (port 465 typical). |
| `SMTP_USE_STARTTLS` | No | `True` | STARTTLS after connect (port 587 typical). |
| **OAuth** | | | |
| `OAUTH_GOOGLE_CLIENT_ID` / `OAUTH_GOOGLE_CLIENT_SECRET` | No | (unset) / (unset) | Google OAuth 2.0 + PKCE. Both must be set; endpoint returns 503 when unconfigured. |
| `OAUTH_GITHUB_CLIENT_ID` / `OAUTH_GITHUB_CLIENT_SECRET` | No | (unset) / (unset) | GitHub OAuth 2.0 + PKCE. |
| `OAUTH_GITHUB_CONNECTOR_CLIENT_ID` / `OAUTH_GITHUB_CONNECTOR_CLIENT_SECRET` | No | (unset) / (unset) | Echo's GitHub connector (S-3.2.4). Unset, it uses the sign-in app above, whose callback URL must then cover both redirects (register the frontend origin) |
| `OAUTH_GOOGLE_CONNECTOR_CLIENT_ID` / `OAUTH_GOOGLE_CONNECTOR_CLIENT_SECRET` | No | (unset) / (unset) | Reserved for the Google connectors (S-3.2.2, S-3.2.5), on their own client so a scope review never touches Google sign-in. Not read by any code yet |
| `OAUTH_REDIRECT_BASE_URL` | No | (unset) | Not read by any code yet: the redirect comes from the request's `redirect_uri` |
| **Rate limiting (E-5.5)** | | | |
| `RATE_LIMIT_ENABLED` | No | `True` | Kill switch. Set `False` for dev / under-test. |
| `RATE_LIMIT_PER_MIN_FREE` / `RATE_LIMIT_PER_MIN_PRO` / `RATE_LIMIT_PER_MIN_STUDIO` | No | `60` / `600` / `6000` | Per-user-tier caps for authenticated routes (req/min) |
| `RATE_LIMIT_PER_MIN_UNAUTH` | No | `100` | Per-IP cap for unauthenticated GETs. |
| `RATE_LIMIT_LOGIN_PER_MIN` | No | `10` | Per-IP credential-stuffing defence on `/auth/login`. |
| `RATE_LIMIT_RESET_PER_MIN` | No | `5` | Per-IP cap on `/auth/password-reset/{request,confirm}`. |
| `RATE_LIMIT_REGISTER_PER_MIN` | No | `5` | Per-IP cap on `/auth/register`. |
| `TRUSTED_PROXY_IPS` | No | (empty) | Reverse proxies whose `X-Forwarded-For` counts, comma-separated IPs or CIDRs (T-5.5.8). Empty: the header is ignored and the caller is the socket peer. **An install behind a proxy must set this**, or every user shares one address and one per-IP limit. Used by the rate limiter, the audit log and the address on a session (`app/utils/client_ip.py`). See README, "Running behind a reverse proxy" |
| **BYOK + MFA encryption (E-5.6 / E-5.4)** | | | |
| `BYOK_ENCRYPTION_KEY` | **Yes (production)** | (unset) | Fernet key (32 url-safe base64-encoded bytes; generate via `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`). Encrypts BYOK provider keys + MFA secrets. When unset, a process-local key is generated at startup with a loud warning — stored credentials become unrecoverable on restart in that mode. Single shared key per [D-043](docs/decisions.md#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05). |

\* One provider key is effectively mandatory: whichever provider your resolved use cases point at. Defaults ship pointing at `openai`, so `OPENAI_API_KEY` is required out of the box.

## Important Conventions

- **Backend always runs inside venv**: Use `./venv/Scripts/python` (Windows) or `./venv/bin/python` (Linux)
- **Version constraints**: `requirements.txt` uses `>=` (not `==`) to avoid pip resolution conflicts
- **Tests mock Celery**: `conftest.py` patches the Celery tasks the routers dispatch, so tests need no Redis
- **ChromaDB tests**: Use `EphemeralClient` monkeypatch instead of `PersistentClient`
- **Frontend inline styles**: Components use inline `style={{}}` objects rather than CSS modules or styled-components
- **State management split**: Server state in React Query, UI state in Zustand
- **Celery autodiscover**: `celery_app.py` makes one `autodiscover_tasks(..., related_name=...)` call per module in `app/tasks/`, since tasks live in `job_tasks.py` and its siblings, not `tasks.py`
- **Celery on Windows**: Must use `--pool=solo` flag
- **Transcript caption track**: `fetch_transcript()` takes the track in the language the video is spoken in, never an auto-dub; English-first is only the fallback when nothing says what is spoken ([D-117](docs/decisions.md#d-117--the-caption-track-is-the-one-in-the-spoken-language-auto-dubs-are-read-from-the-players-audio-tracks-2026-10-29))
- **Q&A context refinement**: Raw RAG+report context is compacted by an LLM before the answer LLM sees it — prevents "no relevant context" on large noisy inputs
- **HTML report rendering**: Uses `jinja2.Environment` with custom `number_format` filter (not `Template.globals`)
- **WebSocket cache invalidation**: `useJobProgress` invalidates the `jobVideos` query on `awaiting_approval` status change so the approval list auto-populates
- **Global document library — shared cache, private catalogue** ([D-063](docs/decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)): Documents are never job-owned, and `documents` remains a single global deduplicated store so transcripts, embeddings and knowledge artifacts are computed once and reused across every job and user. **But no user sees a document they did not ingest.** Visibility is an explicit per-tenant grant in `document_visibility(document_id, tenant_id, source)`, written by *every* ingest path — job selection, PDF upload, pasted URL, channel sync — including on dedup hits, because a cache hit means the bytes exist but this tenant may never have seen them. Ownership is **never** derived from `job_documents`: PDF uploads and pasted URLs create documents with no job, and deriving would make a user's own upload invisible to them. Any new user-facing read of `documents` must filter through `visibility_service.visible_document_ids(db, tenant_id)`, and any new ingest path must call `visibility_service.grant(db, [doc.document_id], tenant_id, source)`. The ORM class is `Document` (`app.models.document`); the table is `documents`. **Key everything on `document_id`** ([D-070](docs/decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19)): the legacy `video_id` column is NULL for every non-video source, and keying the grant on it made PDFs and pasted pages invisible to everyone from 2026-07-31 to 2026-10-19 — and keying the Chroma write on it meant their chunks were never embedded at all.
- **Two dates per source, both load-bearing** (R3, [D-072](docs/decisions.md#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19)): `documents.published_at` is when a source was POSTED; `documents.discussed_era_json` is the period it is ABOUT (`{era_start, era_end, era_confidence, is_retrospective}`, integer years, negative = BCE), extracted once per document by `temporal_scope_extract` the first time a job chunks it (`job_tasks._ensure_era`, fail-soft). Chunks carry both as flat scalars — `published_ts` / `published_year` and `era_start` / `era_end` / `era_confidence` / `is_retrospective` — **omitted when unknown, never sentinel-valued**, so a Chroma range filter excludes undated chunks instead of matching them against 1970. Chunks embedded before this shipped, or before their document's era was extracted, carry neither and read as unknown until the owner runs `scripts/backfill_chunk_temporal_fields.py --write` (S-1.17.3): a metadata-only update, no re-embedding, idempotent, so it can be re-run any time. In search ranking, time is a PREFERENCE decided once per topic by the planner's `temporal_profile`, never a filter (D-059's reasoning for language). Every prompt that reads transcript text carries `TEMPORAL_AWARENESS` or `TEMPORAL_EXTRACTION_NOTE` from `app/agents/prompts/shared.py`.
- **Code-mixed sources carry their language mix on every chunk** (R5 / N-002, [D-080](docs/decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19)): every chunking path profiles the whole transcript once (`language_mix_service.ensure`, which stores the profile on `documents.language_mix` and hands it to `chunk_transcript` as `language_profile=`, T-1.16.1.7; older documents are profiled by `scripts/backfill_language_mix.py` from their cached text, no LLM) and the chunker writes `code_mix_primary` / `_script` / `_share` / `_matrix_share` / `_quote` plus per-chunk `code_mix_chunk_share` / `_chunk_matrix`, **omitted entirely for English sources** (under 3% non-English words, `DOCUMENT_PRESENCE_SHARE`; English talks read 0.0–0.6%, comment threads under Hinglish videos 3–30%). Prompts read it through `code_mixing_service.source_note` (`speech: ... — quote in ...` on source headers). Report map items may carry `original` wording beside English `content`; compose attaches the source's `quote_form`. Such chunks are EMBEDDED as their English rendering (`text_en`, D-084) while the stored text stays the original. Any new prompt that shows sources to a model should carry the speech note.
- **Q&A reads the corpus from the database, not from its retrieval hits** (S-1.15.2): `routers/qa.py` and `routers/library.py` compute `corpus_stats_service` figures for the approved (job) or visible (library) document set and pass them, with the length preference, into the agents. The length policy and the publication-span note are dead code without them — exactly how R4's Q&A half shipped unwired from 2026-07-31 to 2026-10-18 — so `tests/test_routers/test_qa_length_policy.py` asserts at the production caller. Verify a feature at its caller, not at the function that implements it.
- **Visual annotations are marked in the TEXT, never only in metadata** ([D-067](docs/decisions.md#d-067--visual-understanding-separate-frames-table-marker-in-text-annotation-opt-in-per-job-2026-07-31)): frame descriptions are merged as `[VISUAL @ mm:ss - ...]` spans inside the chunk text. Chunking splits, merges and re-packs segments, and the dominant-segment heuristic promotes exactly one segment's metadata — so metadata alone is not a survivable channel. Any prompt that reads transcript text MUST include `VISUAL_ANNOTATION_CONTRACT` from `app/agents/prompts/shared.py`, or the model will read machine-written descriptions as things the speaker said. Frames live in `visual_frames` and are merged at chunk time; **never** annotate `transcript_cache`, which is globally shared. Since S-1.18.8 the report pipeline also carries each extracted item's `modality` (`said` / `shown` / `both` / `unknown`) from the map stage through reduce, and compose renders it as a tag the composer attributes from; code forces `said` for sources without annotations. A new extraction prompt that reads annotated text should emit the same field.
- **Single global Chroma collection**: All chunks live in `pratidhvani_global`. Per-job scoping is a metadata filter at query time. Deleting a job does NOT delete chunks.
- **Usage is metered per tenant, by feature, at the scope, not the call site** (E-5.2): `usage_service.metered(db, tenant_id)` names whose work it is; `llm_service.byok_context` opens one, `get_llm_for` attaches a meter to every client it builds, and `quota_service.record` charges each YouTube Data API request to the open scope (the install-wide `api_quota_log` is unchanged), and `youtube_service._whisper_transcribe_with_retry` charges each response's audio seconds (`whisper_seconds`, T-5.2.12; every hosted Whisper call passes through it, so a new one needs no meter of its own). The outermost scope writes `usage_records` (and the daily `quota_usage` totals) when it closes, through a session of its own: it never commits or rolls back the caller's session, and when the caller's transaction has already written (a flush, a DML statement, an open SQLite write transaction) the write waits for that transaction to end (commit, rollback or close). While it is open a scope also writes what it has counted, at most every `USAGE_FLUSH_INTERVAL_SECONDS` (T-5.2.13), by the same rules: it tries after each model call and each Whisper response (the chunks of a split recording are billed minutes apart inside one iteration), and a long loop calls `usage_service.checkpoint()` once it has committed, for YouTube units and for what a try was too early for or had to leave. Amounts leave the ledger before they are written, so a checkpoint and the close never write the same one, and a redelivered task starts with an empty ledger. A new user-triggered entry point that is not inside `byok_context` opens a scope; a new LLM use case needs a `USE_CASE_FEATURES` entry (a test enforces it); a pool thread needs the caller's context (`report_agent._map_in_context`), or BYOK, model overrides and the meter all miss it. Nothing is enforced from these numbers (D-111). Tests that patch `get_llm_for` bypass the meter; patch `llm_service._build_from_config` instead (`tests/usage_helpers.py`).
- **A caller's address has one reader** (T-5.5.8): `app/utils/client_ip.py`. `X-Forwarded-For` counts only from a proxy in `TRUSTED_PROXY_IPS`, read from the right. Nothing else reads the header or `request.client`; a test pins that. uvicorn's own proxy handling rewrites the peer for callers at 127.0.0.1, so the launchers pass `--no-proxy-headers`.
- **A session takes its sockets with it** (T-5.4.19): anything that sets `sessions.revoked_at` calls `auth_service._announce_revoked` after its commit, which publishes on `session_revoked:{tenant_id}` so whichever API process holds the socket closes it with 1008. The manager's one-minute look at the sessions table is the net when that message is lost, so a revocation never waits on Redis.
- **Per-use-case LLM config**: Call sites resolve their (provider, model, reasoning) triple via `app/services/llm_routing.py::resolve_config(use_case)`. Override per use case with `LLM_USE_CASE_CONFIG` (see "LLM configuration" below). The legacy `get_llm(..., purpose='fast')` / `LLM_ROUTE_OVERRIDES` knobs are still honored as deprecated fallbacks.

### Multilingual transcription

- Whisper is called with `task="transcribe"` (not `translate`), preserving the speaker's language(s). Mixed-language audio (e.g., Hindi-English code-mixed) is transcribed faithfully, with proper nouns in their original script.
- The multilingual embedding model (`paraphrase-multilingual-MiniLM-L12-v2`) ensures a Hindi transcript and its English question land in similar vector space.
- **Output is ALWAYS English** (D-066), whatever the source language. The contract is defined once in `app/agents/prompts/shared.py` and injected into every report, knowledge and Q&A prompt — enforced at the EXTRACTION boundary, because an item emitted in the source script propagates untouched to the final deliverable. Before D-066 no prompt instructed English output at all, so a Hindi corpus produced a Devanagari report.
- **Quotes keep three forms**: original script + transliteration + English translation, e.g. `अहिंसा परमो धर्मः (ahiṃsā paramo dharmaḥ) — "non-violence is the highest virtue"`. Reserved for material whose exact wording matters; ordinary speech is translated plainly.
- **Language detection is script-based** (`app/services/language_service.py`), exact for script mixing and explicitly NOT able to see romanised code-mixing (Hinglish in Latin letters). A test pins the gap; do not "fix" it by flipping the assertion. Romanised code-mixing is detected separately, per word, by `app/services/code_mixing_service.py` ([D-080](docs/decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19)): a lexicon tagger measured on a 300-unit hand-labelled set in `tests/fixtures/code_mixing/`. Do not tune it against that set's `test` split.
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

36 named call sites — full rationale, token budgets, and recommended minimum context live in the registry alongside each entry.

### Measured guidance (S-1.14.7)

Every `UseCaseInfo` carries a required `guidance: UseCaseGuidance`: `status` is `measured` (the use case's own output was graded; carries `decision_id`, `decided_on`, `flagship_delta`, `downgrade_risk`, optional `measured_cost`) or `unmeasured` (no decision id; `note` says what evidence exists). `model_verdicts` lists `ModelVerdict(model, verdict="unacceptable"|"weaker", why, decision_id, reasoning=())` — exact model-id match, scoped to reasoning levels when `reasoning` is non-empty. `assess_choice(use_case, cfg)` turns verdicts plus the `VISION_CAPABLE_MODELS` check into warnings; `/health/llm` reports them for the resolved config and `GET /settings/llm` ships the guidance to `/account/ai-models`, whose `assessChoice` mirrors the rule client-side. Advisory only: nothing refuses a config. Adding a use case means writing its guidance; promoting one to `measured` needs a decision entry, and `tests/test_services/test_llm_guidance.py` pins the measured set and checks every cited decision exists in `docs/decisions.md`.

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

**Visual understanding (`app/agents/visual_agent.py`):**
- `visual_select_moments` — read a timestamped transcript, decide where the picture carries information the words do not
- `visual_describe_frame` — **MULTIMODAL.** Describe one captured still in transcript context. Listed in `VISION_USE_CASES`; its model is **not freely swappable** (a text-only model does not fail helpfully — it describes the image from surrounding text)

**Discussed-era extraction (`app/services/temporal_service.py`, R3):**
- `temporal_scope_extract` — once per document on first ingest: which period the source DISCUSSES (`{era_start, era_end, era_confidence, is_retrospective}`), distinct from `published_at`. Persisted on `documents.discussed_era_json`, reused by every later job, flattened into chunk metadata. Reasoning OFF is mandatory (strict JSON under a 400-token cap). Fail-soft, so deliberately not a feature gate in `llm_smoke`

**Echo share processing (`app/services/echo_media.py`, S-3.7.2):**
- `echo_share_ocr` — **MULTIMODAL.** Copy out the text in a shared image when on-device OCR read too little or with low confidence (Devanagari always, since the default OCR models cannot read it). Original script kept: transcription, not a deliverable. Listed in `VISION_USE_CASES`. Runs only when `ECHO_REMOTE_MEDIA` is on and the tenant is not local-only, or when it resolves to a local model. Reasoning OFF, fail-soft, not a feature gate

**Echo voice and personality signals (`app/services/echo_signal_extraction.py`, S-3.3.2):**
- `echo_extract_signals` — a batch of the user's OWN words (notes, questions, own-words shares, the words they typed into a "speak as me" draft) → candidate style and personality signals with verbatim examples cited by passage id; code keeps an example only when found exactly in its passage (D-099). Economy tier, reasoning OFF, fail-soft, not a feature gate

**Speak as me (`app/agents/echo_agent.py`, S-3.4.1 / D-102):**
- `echo_classify_intent` — the incoming message's intent, topic, language and the people it names (by name only; "my uncle" is not a name), so private names are confirmed before drafting. Economy tier, reasoning OFF
- `echo_draft` — the draft in the user's voice and the reply's language (not D-066 English), from a trait card plus five style-diverse exemplars of the user's own writing (Mode A, D-100) and the cited knowledge; also the revision and the one-shot paraphrase of a third-party run the verbatim guard caught. Synthesis tier
- `echo_critique` — scores a draft's tone, vocabulary, structure and topicality 1-5 against the trait card; advisory (the best round is kept). Volume tier

**Author Studio (`app/services/outputters/`, S-6.1.3 / S-6.3.1):**
- `author_book_outline` — plan a book from chapter digests (order, parts, bridges, briefs, glossary terms); JSON. Opt-in per book (`cohesion=light|full`), fail-soft, not a feature gate
- `author_book_prose` — introduction, bridges, conclusion and glossary around the unchanged chapters; marked plain-text sections. `cohesion=full` only; `none` stays the default after two blind rounds (D-093)
- `author_deck_outline` — plan a slide deck from one or more reports or knowledge reports (S-6.3.2) whose citations arrive as `[S#]` markers; JSON. Not fail-soft: a failed call fails the deck. Slides citing nothing are dropped by the renderer
- `author_newsletter_compose` — a newsletter issue's featured deep-dive about one source, citing `[S#]` markers; plain prose. Opt-in per issue (D-097), fail-soft to the source's own summary

**Code-mixed speech (`app/services/code_mixing_service.py`, R5 / N-002):**
- `code_mixing_detect` — word-level language of 25 snippets per call: each snippet's Hindi runs verbatim plus its matrix (grammar) language. The evaluation reference, not on the ingest path: the lexicon tagger was more precise on romanised text at equal recall (D-080). Reasoning OFF, fail-soft, not a feature gate
- `code_mixing_render_english` — English rendering of a non-English chunk, used only as what the chunk is EMBEDDED as (stored text stays the original; rendering kept as metadata `text_en`). Six chunks per call, once per document, inside `chroma_service.insert_chunks`. Retrieval MRR 0.565 → 0.805 on Devanagari chunks, 0.402 → 0.805 romanised (D-084). Reasoning OFF, fail-soft, not a feature gate

**Saved-search change judge (`app/services/saved_search_change_service.py`, M3 / S-8.3.3):**
- `saved_search_judge` — called only when a saved search's two change signals disagree (cited-set Jaccard vs answer-embedding distance, pre-registered thresholds); strict JSON `{changed, what_changed}`, which becomes the notification text. Volume tier, reasoning OFF (400-token cap), fail-soft (the citation signal decides), not a feature gate

**Question suggestions (`app/services/suggestion_service.py`, M4 / S-8.4.1):**
- `qa_suggest_questions` — "You might ask…": seven next questions from a summary of a run, a source or the library plus what was already asked there; merged with the caller's nearest past questions, de-duplicated, MMR-diversified, cached per (tenant, context) in `suggestion_cache`. Volume tier, reasoning OFF (900-token cap), fail-soft (history only), not a feature gate. The first LLM spend in I-8; impressions and clicks go to `audit_log`

**Social ingest (`app/services/social_classify.py`):**
- `social_classify_stance` — one call per fetched post and top comment, inside each connector ([D-023](docs/decisions.md#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28)): `{stance, sentiment, framing, topic_relevance}` at fetch time, kept under `documents.source_metadata_json["classification"]`. Volume tier, reasoning OFF

**Report generation (`app/agents/report_agent.py`):**
- `report_map_chunks` — map phase; per-batch fact extraction (highest-volume call in the codebase)
- `report_reduce_summaries` — reduce phase; consolidate per-batch summaries
- `report_compose` — final HTML report composition (long user-facing output)
- `report_channel` — channel-report composition for channel jobs
- `report_compose_channel_section` — per-channel section composer inside the channel-report pipeline

## LLM startup smoke check + fail-soft

`run_startup_probes` in `app/services/llm_smoke.py` runs once from the FastAPI lifespan. It resolves the effective `UseCaseConfig` for all 36 entries, **dedupes by `(provider, model, vision)`** so each unique pair is probed exactly once, and fans a trivial one-token probe per unique config out via `asyncio.to_thread` (provider SDKs are synchronous). Results are stored on a process-global `LLMStatus` singleton.

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
