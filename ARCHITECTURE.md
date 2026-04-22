# VideoResearchPro — Architecture & Design

> A reference document describing the features, architectural decisions, algorithmic choices, optimizations, and communication strategies of VideoResearchPro. Written to capture intent, not just the mechanics. When in doubt, this file is the canonical explanation; the code is the ground truth.

## 1. Overview

VideoResearchPro is a full-stack web application that turns a loose YouTube browsing workflow into a structured research pipeline. A user submits a **job** (topic search, channel list, or channel subscription); the system discovers videos, fetches transcripts, builds a retrieval index, generates HTML reports, and answers citation-backed questions — either scoped to one job or across the entire accumulated library.

Design priorities, in order:

1. **Idempotent work** — every expensive operation (transcript fetch, embedding, LLM call) should run at most once per video across the lifetime of the system.
2. **Honest citations** — every claim in a Q&A answer must point back to a specific `(video, timestamp)` the user can click through to.
3. **Responsive long-running jobs** — the UI should never sit in a blank loading state; it should stream phase-level progress from the worker.
4. **Graceful degradation** — when YouTube rate-limits, transcripts are missing, or IPs are blocked, the pipeline falls back rather than fails.
5. **Single-tenant simplicity first, multi-tenant ready** — the schema treats the library as shared, but auth is JWT so multi-user scoping is a future migration, not a rewrite.

## 2. Features

### 2.1 Three job types

| Type | Input | Pipeline | Output |
|---|---|---|---|
| **Topic** | Topic string + search instructions + duration/channel-type filters + optional **preferred channels** list | Search Agent (resolve preferred channels → LLM planner → broad YouTube searches + direct uploads-playlist walk → rank & curate) → user approval → transcript extraction → RAG index → Report Agent (map-reduce HTML) | Approved list, global index chunks, full HTML report, Q&A enabled |
| **Channel** | List of channel URLs | Resolve uploads playlists → user approval → extraction → RAG index → stats-only report | Same as topic but report is channel-statistics only |
| **Subscription** | List of channel URLs | Fire-and-forget: resolve channels, walk every upload page, extract transcripts (with Whisper fallback), embed into global index. No approval. No report. | Library growth; channel marked `subscribed=True` for future re-syncs |

### 2.2 Global video library

Videos are a first-class, **deduplicated** entity keyed by YouTube `video_id`. A video processed by one job is instantly reusable by every subsequent job — the transcript cache and the ChromaDB chunks are global.

- `Library → Channels` tab: list of every channel the library has touched, with subscribe toggle, sync button, and last-sync timestamp.
- `Library → Videos` tab: cross-job browse with filters (language, transcript status, channel) and sort (newest, longest, etc.).

### 2.3 Library-wide Q&A

A separate Q&A surface that queries the whole collection, not one job. Same LangGraph pipeline as job-scoped Q&A, with two tweaks: no `video_id` filter at retrieval, and a system prompt that explicitly handles mixed-language context (translate-when-quoting, answer in user-selected language).

### 2.4 Per-job Q&A with citation-backed answers

Each completed job exposes a Q&A panel. The agent retrieves top-k chunks scoped to the approved videos, compacts the raw RAG+report context via an LLM refinement step, and produces an answer where every claim cites `(video_title, timestamp)` with a clickable `&t=` YouTube deep link.

### 2.5 Multilingual transcription & retrieval

Whisper preserves the speaker's language(s); Hindi/Urdu/English code-mixed audio is transcribed faithfully rather than translated. The embedding model (`paraphrase-multilingual-MiniLM-L12-v2`) embeds all 50+ supported languages into a shared vector space, so an English question can match a Hindi transcript chunk. Q&A answers are rendered in the user-selected `answer_language` (default English).

### 2.6 Reports

Topic jobs: comprehensive HTML report with an intro, synthesized sections, a channel/statistics table, and per-video summaries. Built via map-reduce so transcript sets larger than the LLM context window are still summarizable. Channel jobs: stats-only variant. Reports are served from `/api/v1/jobs/{id}/report` as standalone HTML.

### 2.7 JWT authentication

Register → login → Bearer token. All non-health routes are protected. The WebSocket accepts the token as a query parameter (`?token=…`) since browsers can't attach headers to `new WebSocket(...)`.

### 2.8 One-click service restart

A single PowerShell script (`scripts/restart_services.ps1`) and a protected HTTP endpoint (`POST /api/v1/admin/restart`) kill and relaunch all four runtimes (Redis verified, backend, Celery worker, frontend dev server) in a single step. The endpoint uses a detached trampoline pattern so the backend can safely kill itself. See §7.5 for the mechanics.

## 3. System Architecture

### 3.1 Process topology

```
┌─────────────────┐          ┌─────────────────┐
│   Browser       │          │   Browser       │
│ (React + Vite)  │          │ (React + Vite)  │
└────────┬────────┘          └────────┬────────┘
         │  REST + WS                 │
         ▼                            ▼
  ┌──────────────────────────────────────────┐
  │   FastAPI app  (uvicorn, port 8000)     │
  │   • Routers (jobs, channels, library,   │
  │     auth, admin, ws)                    │
  │   • ConnectionManager: Redis pub/sub    │
  │     → WebSocket fan-out                 │
  └───────┬──────────────────────────┬──────┘
          │  enqueue via Celery      │  subscribes
          ▼                          │
  ┌──────────────────┐               │
  │   Redis          │ ◀─────────────┤
  │   db 0: pub/sub  │  publish      │
  │   db 1: broker   │◀─┐            │
  │   db 2: results  │  │            │
  └──────────────────┘  │            │
                        │            │
                        ▼            │
  ┌──────────────────────────────┐   │
  │ Celery worker (--pool=solo)  │   │
  │ • execute_topic_job          │   │
  │ • execute_channel_job        │   │
  │ • execute_subscription_job   │   │
  │ • resume_job_after_approval  │   │
  │ • sync_channel_job           │   │
  └────┬────────┬────────┬───────┘   │
       │        │        │           │
       ▼        ▼        ▼           │
  ┌────────┐┌───────┐┌────────┐      │
  │YouTube ││OpenAI ││Chroma  │      │
  │Data API││GPT-5  ││Persistent  ──┘
  │/ytt    ││Whisper││Client      │
  └────────┘└───────┘└────────┘
                      │
                      ▼
                  ┌───────┐
                  │SQLite │ (SQLAlchemy)
                  └───────┘
```

### 3.2 Data flow for a topic job

1. `POST /api/v1/jobs` → insert `Job` row (`status=pending`), dispatch `execute_topic_job.delay(job_id)`, return 202.
2. Celery worker picks up task, transitions `pending → searching`, runs **Search Agent** (LLM expands topic into search queries, calls YouTube Data API, ranks candidates).
3. Approved-candidate videos are upserted into the **global** `videos` table and linked via `job_videos` rows. Status → `awaiting_approval`. Task exits. No worker is blocked.
4. User reviews in the frontend, toggles approvals, `PUT /api/v1/jobs/{id}/approve`. Router dispatches `resume_job_after_approval.delay(job_id)`.
5. Resume task transitions `extracting → building_rag`. For each approved video: check `transcript_status` on the **global** `Video` row; skip entirely if `fetched`. Otherwise fetch transcript (with fallback chain below), chunk, upsert into the global Chroma collection.
6. Status `generating_report`: Report Agent runs map-reduce and writes HTML to `data/reports/{job_id}.html`.
7. Status `completed`. Q&A panel becomes active. Progress events published to Redis at every transition; the WebSocket manager fans them out to subscribed clients.

## 4. Data Model

All tables live in a single SQLite file (`data/videoresearchpro.db`) via SQLAlchemy 2.x (`Mapped` / `mapped_column` style) with Alembic migrations.

| Table | Primary key | Purpose | Notable columns |
|---|---|---|---|
| `users` | `id` (UUID) | Auth | `email` (unique), `password_hash` (bcrypt via passlib) |
| `jobs` | `id` (UUID) | One row per job | `job_type ∈ {topic, channel, subscription}`, `status`, `preferred_channels` (JSON — topic jobs only), `channel_list_resolved` (JSON), `search_queries_used` (JSON), `progress_pct`, `celery_task_id` |
| `videos` | `video_id` (YouTube ID) | **Global** deduplicated video registry | `channel_id` FK, `transcript_status`, `transcript_language`, `transcript_source ∈ {youtube, whisper}`, `embedded_in_chroma` |
| `channels` | `channel_id` | **Global** channel registry | `subscribed`, `uploads_playlist_id`, `last_synced_at` |
| `job_videos` | `(job_id, video_id)` composite | M:N join: which videos does a job reference | `approved`, `curated_at`, `selection_reason` |
| `transcript_cache` | `video_id` | Cache of raw transcript segments (pre-chunk) | `segments_json`, `language`, `fetched_at` |
| `qa_exchanges` | `id` (UUID) | Per-job Q&A history | `job_id` FK, `question`, `answer`, `references` (JSON) |
| `library_qa_exchanges` | `id` (UUID) | Library-wide Q&A history | `question`, `answer`, `references`, `answer_language` |
| `api_quota_log` | `id` | YouTube Data API quota tracking | `endpoint`, `cost`, `timestamp` |

### 4.1 Key schema decisions

- **`video_id` as primary key, not surrogate UUID.** YouTube's ID is already globally unique, stable, and 11 chars. Using it as PK makes deduplication free — any `INSERT` of a duplicate fails; any join-through-the-ID works without a lookup table. Migration from the old UUID-based schema hand-wrote a dedup step (`SELECT DISTINCT video_id ... INSERT INTO videos_new`).
- **`job_videos` as the unit of job scope.** Removing a job deletes its `job_videos` rows; the `videos` rows and their ChromaDB chunks stay in the library. This is a cornerstone of the "every expensive operation happens once" rule.
- **Channel FK is `SET NULL`** on delete, so a channel row can be garbage-collected without cascading through the video library.
- **Composite PK on `job_videos`** prevents accidental double-linking within a job; Alembic migration `c3d4e5f6a7b8_global_video_library.py` added explicit indices on both columns for the reverse lookups.

## 5. RAG Pipeline

### 5.1 Chunking (`backend/app/utils/chunking.py`)

- **Size / overlap**: 256 tokens, 32-token overlap, counted via `tiktoken`. Small chunks favor precise retrieval; the refinement step (§6.3) compensates for the narrower context.
- **Sentence-aware boundaries**: raw transcript segments are first expanded into sentence-aligned windows, so a chunk boundary never lands mid-sentence.
- **Timestamp interpolation**: each chunk carries `timestamp_start` / `timestamp_end` computed by the character-share within the source segments — good enough for `&t=123s` deep links without reparsing audio.
- **Metadata**: `video_id`, `video_title`, `channel_name`, `channel_id`, `video_url`, `published_at`, `duration_seconds`, `timestamp_start`, `timestamp_end`, `chunk_index`, `total_chunks`, `language`, `transcription_source ∈ {youtube, whisper}`, `word_count`. All flattened to scalars so ChromaDB accepts them.

### 5.2 Embeddings (`backend/app/services/embedding_service.py`)

- Model: `paraphrase-multilingual-MiniLM-L12-v2` (384-dim, 50+ languages). Swapped in from the English-only `all-MiniLM-L6-v2` once subscription ingest meant transcripts could be in any language.
- **Lazy, process-level singleton.** First call loads the model (~120 MB download on first run, a few seconds to warm up); subsequent calls hit the same instance.
- **Why not OpenAI embeddings?** Multilingual quality is comparable, sentence-transformers is free and offline, and a local model avoids a network round-trip per chunk during indexing.

### 5.3 Single global ChromaDB collection (`backend/app/services/chroma_service.py`)

- One collection, `videoresearchpro_global`. Chunk IDs are `f"{video_id}:{chunk_index}"` — stable and deterministic.
- **Inserts use `upsert`, not `add`.** Re-extracting the same video (e.g., after a schema change) overwrites in place rather than duplicating. Idempotency is a property of the ID scheme + upsert, not of the caller's discipline.
- **Scoping is a metadata filter.** Per-job queries pass `video_ids=[…]` → Chroma `where={"video_id": {"$in": [...]}}`. Library-wide queries pass `video_ids=None` and search the whole collection.
- **Distance threshold filter** at read time: results with `distance > settings.RAG_DISTANCE_THRESHOLD` (0.6) are dropped. Prevents low-similarity chunks from polluting the context window.
- **Backward-compat shims**: the old `create_collection(job_id)` / `get_collection(job_id)` / two-arg `insert_chunks(job_id, chunks)` / three-arg `query_collection(job_id, query, n)` signatures still work with a `DeprecationWarning` and ignored `job_id`. This is what allowed the 12-unit refactor to merge incrementally.
- **Legacy migration hook** (`migrate_legacy_per_job_collections`): on startup, iterates any surviving `job_*` collections, upserts their chunks into the global one, deletes the source. Idempotent — safe to run every boot.

### 5.4 Concurrency constraint

`PersistentClient` holds an exclusive SQLite handle on the Chroma persist directory. The Celery worker must run with `--pool=solo` on Windows (one worker = one process). Scaling to multiple workers requires switching to `HttpClient` against a dedicated `chroma-server` — noted in the module docstring.

## 6. LangGraph Agents

All three agents are built with `langgraph.StateGraph` over `TypedDict` states in `backend/app/agents/state.py`. Prompts are single-source-of-truth in `backend/app/agents/prompts/*.py`.

### 6.1 Search Agent (`agents/search_agent.py`)

```
resolve_preferred_channels → plan_searches → execute_searches → rank_and_curate → END
```

The 4-node design replaced an earlier naive `generate_search_queries → execute_searches → rank_and_curate` pipeline that stuffed creator names, handles, and URLs lifted from `search_instructions` directly into YouTube query strings. That produced brittle, over-specific queries that often returned zero results. The current agent separates *broad topical discovery* from *creator-specific fetches* and merges them at curation time.

- **`resolve_preferred_channels`**: the user's optional `preferred_channels` list (handles, URLs, `UC…`-IDs, or plain text) is resolved to canonical channel IDs via `youtube_service.resolve_channel_id`. Unresolvable entries are skipped with a warning so a single typo can't sink the whole job. Deduped. Output: `preferred_channel_ids: list[str]`.
- **`plan_searches`**: a single structured LLM call (`PLAN_SEARCHES_PROMPT`, temperature 0.3) produces JSON `{broad_queries: [...], channel_keywords: [...]}`:
  - `broad_queries` are clean, topic-only YouTube search strings. The prompt explicitly forbids including channel names, creator names, handles, URLs, or `@`-mentions.
  - `channel_keywords` are topic-salient terms used later to filter each preferred channel's uploads. If the LLM returns an empty list but preferred channels are present, a fallback derives keywords from the topic directly.
- **`execute_searches`** merges two streams of candidates, each tagged with a `source` field on its metadata:
  1. `source="search"` — `broad_queries` are sent through `youtube_service.search_videos`; results are fetched at ~3× the target pool and deduped by `video_id`.
  2. `source="preferred_channel"` — for each resolved channel ID, `_fetch_preferred_channel_uploads` walks the uploads playlist (bounded by `PREFERRED_CHANNEL_FETCH_LIMIT = 50` items per channel, one YouTube quota unit). Each upload is scored against `channel_keywords` by `_keyword_score`; videos with zero keyword matches are dropped.
- **`rank_and_curate`**: `RANK_AND_CURATE_PROMPT` (temperature 0.0) ranks the merged pool against the topic, duration/channel-type filters, and the user's `search_instructions`. The prompt is `source`-aware — the curator can prefer or penalize preferred-channel videos based on fit rather than trusting them blindly. Output: the final `num_videos`.

**Design rationale**: creator preferences are a *retrieval* signal, not a *query* signal. Walking uploads playlists directly gives the curator full access to a creator's back-catalog on the topic, even when that creator wouldn't rank organically in broad search results. Meanwhile the broad queries stay semantically clean, so recall isn't handicapped by accidentally appending "Andrew Berman" to every search string.

### 6.2 Report Agent (`agents/report_agent.py`) — map-reduce

```
compute_statistics → map_chunks → reduce_summaries → compose_report → END
```

- **`compute_statistics`**: counts videos, total words, total minutes, per-channel breakdown. Runs for both topic and channel jobs.
- **`map_chunks`** (topic jobs only): each transcript chunk is mapped to a structured extraction (`key_claims`, `entities`, `timestamped_quotes`) via the `MAP_CHUNK_PROMPT`. Parallelizable but currently serial.
- **`reduce_summaries`**: aggregates per-chunk extractions into per-video summaries and a global overview.
- **`compose_report`**: renders the final HTML via `html_builder.py` (Jinja2 template with a custom `number_format` filter) and writes to `data/reports/{job_id}.html`.
- **Why map-reduce?** A 20-video job can have >20k tokens of transcript, exceeding the useful attention window even on large models. Map-reduce turns it into a bounded per-chunk LLM call plus one synthesis call.
- Channel jobs skip `map_chunks`/`reduce_summaries` and compose a stats-only report directly from `compute_statistics`.

### 6.3 Q&A Agent (`agents/qa_agent.py`)

```
retrieve_context → refine_context → formulate_answer → extract_references → END
```

- **`retrieve_context`**: multi-query expansion. The original question + 2 LLM-generated sub-queries (via `SUB_QUERY_EXPANSION_PROMPT`, temperature 0.0) are each sent to ChromaDB. Top-k results per query are merged and deduped by `(video_id, chunk_index, timestamp_start)`, keeping the smallest distance.
- **Report context extraction**: topic jobs also load the job's HTML report, strip tags/scripts, cap at 50k characters. Channel jobs skip (no full report).
- **`refine_context`**: the ~50k-char raw RAG+report context is sent to an LLM (via `REFINE_CONTEXT_PROMPT`) that extracts only the passages relevant to the question — typically compressing down to ~3k tokens. This exists because early testing showed the answer LLM returning "no relevant context" when the raw context was noisy, even though relevant text was present. Refining first is cheaper than letting the answer LLM re-read 50k chars.
- **`formulate_answer`**: constructs the answer via `QA_ANSWER_PROMPT` + `QA_SYSTEM_PROMPT`. For library-wide Q&A, `LIBRARY_QA_*` prompts are used instead, which explicitly handle mixed-language context and accept an `answer_language` parameter.
- **`extract_references`**: deterministic post-hoc pass — scans the answer for video IDs and exact-title substrings, emits a structured references list the UI renders as clickable rows. No LLM in this step; avoids the LLM hallucinating citations.
- **Citation sanitizer**: references that don't map to a chunk actually used in the context are dropped, preventing phantom citations.

### 6.4 Prompt discipline

Every prompt lives in one of the three `prompts/*.py` files. No prompts inline in agent logic. The prompts are the user-facing behavior; keeping them centralized makes tuning a grep-and-edit operation.

## 7. Job Orchestration

### 7.1 Celery configuration (`backend/app/tasks/celery_app.py`)

- Broker: Redis db 1. Result backend: Redis db 2. Progress pub/sub: Redis db 0. Three separate DBs to keep broker traffic, results, and user-facing events from sharing queues.
- `task_acks_late=True`, `worker_prefetch_multiplier=1`: a task is only acknowledged after it completes, and the worker doesn't prefetch — so a killed worker never silently drops a job.
- `--pool=solo` on Windows. Forking pools (`prefork`) don't work on Windows; threads would fight ChromaDB's SQLite lock.

### 7.2 The approval pause pattern

The pipeline has two phases — discovery and extraction — separated by a user gate. A naive implementation would block a Celery worker waiting for the approval. Instead:

1. The discovery task finishes, persists `job_videos` rows (`approved=True` by default), sets `status=awaiting_approval`, and **exits**. The worker returns to the pool.
2. The user's `PUT /approve` request dispatches a **second** Celery task — `resume_job_after_approval` — that picks up where the first left off.

No persistent worker state. No timeout. Users can approve minutes, hours, or days later.

### 7.3 Subscription fan-out (`execute_subscription_job`)

Subscription jobs skip approval entirely:

1. Resolve each channel URL to a `channel_id`; upsert into `channels` with `subscribed=True` and store the uploads playlist ID.
2. Walk every page of the uploads playlist via `get_channel_videos_all` (bounded only by `nextPageToken`; no hard page limit).
3. Upsert each video into the global `videos` table. Create `job_videos` rows with `approved=True`.
4. Delegate to the same extraction logic the resume task uses, so transcripts, chunking, and embedding are unchanged code paths.
5. No report phase; status goes `extracting → building_rag → completed`.

### 7.4 `sync_channel_job`

Re-walks a subscribed channel, picks only videos newer than `last_synced_at`, creates a new "sync" Job row that represents the delta. This is the "Sync now" button in the Library → Channels tab.

### 7.5 Service lifecycle & self-restart (`scripts/restart_services.ps1`, `routers/admin.py`)

The app has four moving pieces — Redis, the uvicorn backend, a Celery worker, and the Vite frontend dev server. A reload-everything operation has to kill the backend (which is the process driving the reload), so we can't do it inline.

**The script** (`scripts/restart_services.ps1`) is the single source of truth for "what does a full restart look like":

1. Kill the backend by PID on `:8000` (`Get-NetTCPConnection -LocalPort 8000`).
2. Kill every Celery worker (matches `python.exe` with `celery` in its command line; also catches helper `celery.exe` processes left over from `--pool=solo`).
3. Kill the frontend by PID on `:5173`.
4. Verify the Redis Windows service is installed and `Running`; start it if it's stopped.
5. Relaunch backend (`venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`), Celery (`venv\Scripts\celery.exe -A app.tasks.celery_app worker --loglevel=info --pool=solo`), and frontend (`cmd /c npm run dev`) — each detached with `-WindowStyle Hidden`.

Flags: `-SkipFrontend` (backend + Celery only), `-KillOnly` (stop without restart), `-Delay <seconds>` (sleep before the kill phase — used by the HTTP endpoint below). Every step is mirrored to `restart_services.log` at the repo root, because when the script is spawned detached by the backend it has no console to write to.

**The endpoint** (`POST /api/v1/admin/restart`) is how the user triggers a restart from the running app. The challenge: a Python process on Windows cannot safely kill-and-respawn itself inline — the parent dies the moment you kill it, and any `Popen` it spawned would go with it unless explicitly detached. We use a *trampoline* pattern:

1. The HTTP handler validates auth, confirms the script exists, returns `202 Accepted` immediately.
2. A background daemon thread does a tiny `sleep(0.5)` (so the HTTP response can flush), then spawns `restart_services.ps1` with `subprocess.Popen`.
3. The child process inherits no handles: we use `creationflags = CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP` and `close_fds=True`. `DETACHED_PROCESS` is what you'd expect to use here, but in practice on Windows 10/11 it combined with `close_fds=True` causes PowerShell to exit before running the script — the new-console flag reliably works and is invisible in our scheduled-task infra.
4. The script sleeps for `-Delay 2`, then kills the backend's own uvicorn process and relaunches everything.

From the client's perspective: the 202 flies, the server goes quiet for ~5–10 s, then the new backend is up on the same port. Query params `skip_frontend` and `delay` are forwarded to the script. The route is protected with `Depends(get_current_user)` — only authenticated callers can restart the stack. Self-restart is wired up only for Windows hosts; the handler returns `501 Not Implemented` elsewhere.

### 7.6 Progress publishing (`services/progress_service.py`)

Every phase transition and progress update publishes a JSON event to Redis channel `job_progress:{job_id}`:

```json
{"type": "job_progress", "job_id": "...", "status": "extracting",
 "progress_pct": 42, "message": "Fetching transcript for dQw4w9WgXcQ",
 "data": {"reused_count": 12, "newly_processed_count": 3},
 "timestamp": "2026-04-20T06:16:04Z"}
```

The `data` payload is free-form per phase. Extraction, for example, includes `reused_count` and `newly_processed_count` so the UI can show "28 of 50 videos already in library" without another API call.

## 8. Transcript Acquisition

`backend/app/services/youtube_service.py` implements a fallback chain that is central to why the pipeline is resilient to YouTube's anti-bot posture:

1. **Cache lookup**: `transcript_cache.video_id = :id` → return cached segments immediately.
2. **youtube-transcript-api**: preferred for speed and fidelity (captions often include punctuation and speaker turns). Language preference order: [user_language, `{lang}-auto`, "en", "en-auto"]. Retried up to 3 times with exponential backoff [2s, 4s, 8s].
3. **yt-dlp audio download → OpenAI hosted Whisper** (`whisper-1`, `audio.transcriptions.create`, `response_format="verbose_json"`): used when step 2 exhausts all languages or when the IP is rate-limited/blocked. Audio files larger than 25 MB are split into 30-second pseudo-segments so Whisper's per-request limit isn't hit. The hosted API already preserves source language — explicitly calling it out because an earlier version mistakenly passed `task="transcribe"`, which is a local-whisper-library kwarg the hosted endpoint rejects.
4. **Store to cache**: the successful result (from either source) is written to `transcript_cache` before chunking, so a later job hits step 1.

### 8.1 Rate limiting

`utils/rate_limiter.py` defines `RateLimiter(rate: float)` where `rate` is minimum seconds between calls. Used in two places:

- `transcript_limiter = RateLimiter(rate=settings.YOUTUBE_TRANSCRIPT_RATE_LIMIT)` (default 0.5s) — throttles youtube-transcript-api calls.
- Equivalent throttling on YouTube Data API calls keeps us under the daily quota (10k units/day by default; tracked in `api_quota_log`).

### 8.2 `transcript_source` metadata

Every chunk carries a `transcription_source ∈ {youtube, whisper}` field. Downstream, this is used for quality signalling — Whisper transcripts are more likely to contain artefacts (filler words, ASR errors) than caption-derived transcripts.

## 9. Communication Architecture

### 9.1 Why REST + WebSocket, not just REST polling

Jobs can take minutes to hours. Polling `GET /jobs/{id}` once a second would produce a lot of empty requests and still feel laggy. Instead:

- **REST** drives all commands: create, approve, cancel, delete, ask, etc.
- **WebSocket** (`/ws/jobs`) carries progress events only — no commands, no state mutations.

### 9.2 Single multiplexed WebSocket

All jobs in a browser session share one WebSocket connection. Clients send JSON control frames:

```json
{"action": "subscribe", "job_id": "abc-123"}
{"action": "unsubscribe", "job_id": "abc-123"}
```

The `ConnectionManager` (`app/websocket/manager.py`) tracks per-connection subscriptions as a `dict[WebSocket, set[str]]`. This is preferable to one-WS-per-job because browsers cap concurrent WebSockets per origin (typically 30–50).

### 9.3 Redis pub/sub → WebSocket fan-out

When the manager starts, it subscribes to the Redis pattern `job_progress:*`. Every incoming event is decoded, and for every connection whose subscription set contains the event's `job_id`, the JSON is forwarded to that socket. One Redis subscription; O(connections) fan-out per event.

### 9.4 Authentication on the WebSocket

The browser WebSocket API cannot set Authorization headers. We accept the JWT as a query parameter (`?token=…`) on the initial upgrade request, validate it with `auth_service.decode_token`, and reject the handshake on failure. After acceptance, the ping/pong keepalive (every 30s from the client; heartbeat-only strings "ping" / "pong") keeps the connection alive through proxies.

### 9.5 Client reconnection

`frontend/src/services/wsClient.ts`: exponential backoff starting at 1s, doubling up to 30s, up to 10 attempts. On reconnect, all active subscriptions are replayed. This is why closing a laptop lid and reopening later doesn't lose the Q&A panel state.

### 9.6 React Query cache bridge

`useJobProgress` listens for `job_progress` events and invalidates the relevant React Query keys (`['job', jobId]`, `['jobVideos', jobId]`, `['jobQA', jobId]`). The mutation-centric components (approval, ask question) use `useMutation` and call `queryClient.invalidateQueries` on success, so the UI converges by a single pattern: server state is always the source of truth, and cache invalidation is the sync primitive.

Special case: transitioning to `awaiting_approval` invalidates `['jobVideos', jobId]` so the approval list auto-populates without a separate event.

### 9.7 JWT on REST

Axios interceptor at `frontend/src/services/api.ts` attaches `Authorization: Bearer ${token}` from `localStorage`. 401 responses clear the token and redirect to `/login`.

## 10. Authentication & Authorization

- **Library**: `python-jose`, HS256, 24h expiry (`settings.JWT_EXPIRY_HOURS`).
- **Passwords**: bcrypt via `passlib.context.CryptContext`.
- **Token payload**: `{sub: user_id, iat, exp}`.
- **Dependency**: `Depends(get_current_user)` on protected routers; unauthenticated requests 401.
- **No account creation on behalf of users.** Users register themselves — this is a hard rule inherited from the platform's safety policy.

The library is currently single-tenant (everyone sees the same catalog); jobs are not user-scoped. The schema is ready for a per-user scope in the future — add `owner_id` to `jobs` and filter by `current_user.id` at the router layer.

## 11. Optimizations & Algorithmic Choices

Consolidated list of the non-obvious decisions and the reason behind each:

| Decision | Why |
|---|---|
| Global ChromaDB collection instead of per-job | One video = one set of embeddings, forever. Cuts embedding compute and Chroma storage by a factor equal to the cross-job video overlap. |
| `f"{video_id}:{chunk_index}"` chunk IDs + `upsert` | Re-extraction is idempotent without a dedup step in the caller. |
| `TranscriptCache` keyed by `video_id` (separate from `videos.transcript_status`) | Caches the raw segments pre-chunk, so if the chunking algorithm changes we can re-chunk without re-fetching. |
| Multi-query expansion at Q&A retrieval | Short user questions under-match on verbose transcripts. Two LLM-generated rephrasings widen recall without much precision cost. Dedupe preserves precision. |
| LLM-based context refinement before the answer LLM | Empirically the answer LLM returned "no relevant context" on 50k-char raw inputs that contained the answer. Refining first is a cheap LLM call that dramatically improves answer quality. |
| Chunk size 256 / overlap 32, not 512 / 50 | Smaller chunks improve retrieval precision on timestamped claims. The refinement step covers the context-narrowness cost. |
| Distance threshold 0.6 | Empirical cutoff — below this, chunks rarely contained relevant answers. Filtering at retrieve time reduces noise to the refinement LLM. |
| Map-reduce for the Report Agent | Enables reports over video sets whose combined transcripts exceed the LLM context window. |
| Approval pause as two separate Celery tasks | No worker is blocked waiting on a human. Users can approve at their leisure. |
| Subscription ingest skips approval and report | Fire-and-forget semantics match user expectation ("subscribe means everything"). Skipping the report saves an expensive LLM pass that nobody asked for. |
| `task_acks_late=True` + `worker_prefetch_multiplier=1` | Kill-resilience: a dying worker's job goes back to the broker, and no worker hoards tasks it can't process. |
| `--pool=solo` on Windows | ChromaDB's SQLite lock is process-level and not thread-safe in the default PersistentClient. Prefork isn't an option on Windows. Scaling past one worker means switching to `HttpClient` + dedicated chroma-server. |
| Exponential backoff on youtube-transcript-api [2s, 4s, 8s] | YouTube's transcript endpoint rate-limits by IP. Three retries with back-off handle transient 429s; Whisper covers persistent blocks. |
| Rate limiter for YouTube at 0.5 s between calls | Stays well under the per-second cap. Quota is tracked separately in `api_quota_log`. |
| Deterministic post-hoc citation extraction | The answer LLM is not asked to format citations. A regex/string pass reads the answer and emits references, so citations can't hallucinate. |
| Citation sanitizer (drop refs not in context) | Backstop for the above — if a reference doesn't map to a chunk used in `retrieve_context`, it's dropped. |
| Lazy, process-level embedding singleton | The SentenceTransformer load is expensive (seconds + 120 MB); loading once per process is fine for the topology (one Celery worker = one process). |
| Channel and video metadata upsert before extraction | Makes the extraction step a pure transcript operation; if we fail mid-way the library still has a consistent set of `videos`/`channels` rows to retry from. |

## 12. Multilingual Strategy

- **Whisper is called without a language hint** and with the default `task` (transcribe, not translate). This preserves the speaker's language(s). For Hindi-English code-mixed audio, each segment stays in its own script. Proper nouns in Devanagari/Cyrillic/Perso-Arabic/etc. are not transliterated.
- **Embedding model is multilingual.** A Hindi transcript chunk and an English question land in the same region of vector space at comparable quality to an English-only pair.
- **Q&A answer language is a user choice.** The request body carries `answer_language` (default English). The system prompt tells the LLM to translate quoted non-English excerpts into the answer language while preserving proper nouns in their original script.
- **Per-chunk `language` metadata**: stored so the Library → Videos tab can filter by transcript language.

## 13. Frontend Architecture

- **Routing**: React Router v6. Six protected routes (`/submit`, `/jobs`, `/jobs/:id`, `/library`, `/library/qa`, `/login`/`/register` public). Layout is a single `AppLayout` with a four-tab nav (Submit Job, Jobs, Library, Global Q&A).
- **State split**: server state in React Query (with invalidation driven by WebSocket events), UI state (active tab, theme, form drafts) in Zustand. No Redux, no Context-as-store.
- **Styles**: inline `style={{}}` objects on every component. No CSS-in-JS library, no CSS modules. Trade-off: fewer abstractions to learn; cost: no theme tokens beyond CSS custom properties.
- **Forms**: `localStorage` persistence for the submit form so a refresh doesn't lose a half-filled job.
- **Toasts, loaders, badges**: single set of components reused across pages (`components/common/*`).
- **Report viewer**: reports are served as standalone HTML and embedded in an iframe. JWT is forwarded via a cookie-bridge endpoint so the iframe can load the protected report without a public URL.

## 14. Testing Philosophy

- **Unit tests mock external services**: `conftest.py` patches Celery task `.delay()` so tests don't need Redis. ChromaDB tests use `EphemeralClient` instead of `PersistentClient`.
- **Integration tests exercise the agents end-to-end with mocked LLM responses** — the real value is the StateGraph wiring, not the LLM.
- **Live-pipeline verification is run manually** (see `.claude/plans/zippy-dancing-castle.md`). Unit tests catch regressions; the live run validates that mocks match real service behavior.

## 15. Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `YOUTUBE_API_KEY` | Yes | — | YouTube Data API v3 key |
| `OPENAI_API_KEY` | Yes | — | For GPT model + Whisper |
| `LLM_MODEL` | No | `gpt-5` | Primary LLM |
| `LLM_FALLBACK_MODEL` | No | `gpt-4o` | Fallback when primary errors |
| `DATABASE_URL` | No | `sqlite:///./data/videoresearchpro.db` | SQLAlchemy connection string |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Pub/sub |
| `CELERY_BROKER_URL` | No | `redis://localhost:6379/1` | Broker |
| `CELERY_RESULT_BACKEND` | No | `redis://localhost:6379/2` | Result backend |
| `EMBEDDING_MODEL_NAME` | No | `paraphrase-multilingual-MiniLM-L12-v2` | SentenceTransformer model |
| `CHROMA_GLOBAL_COLLECTION_NAME` | No | `videoresearchpro_global` | Single global collection name |
| `CHUNK_SIZE` | No | `256` | Tokens per chunk |
| `CHUNK_OVERLAP` | No | `32` | Token overlap |
| `RAG_TOP_K` | No | `15` | Chunks per retrieval |
| `RAG_DISTANCE_THRESHOLD` | No | `0.6` | Upper bound on retained distance |
| `JWT_SECRET` | Yes in prod | `dev-insecure-…` | HMAC secret |
| `JWT_EXPIRY_HOURS` | No | `24` | Token lifetime |
| `YOUTUBE_TRANSCRIPT_RATE_LIMIT` | No | `0.5` | Min seconds between transcript fetches |

## 16. Known gaps / future work

- **`GET /api/v1/library/videos`** — the frontend Library → Videos tab expects a paginated cross-library video listing; the backend currently only exposes `GET /api/v1/channels/{channel_id}/videos`. Channels tab works; Videos tab shows an error. Needs a new router endpoint.
- **Chroma concurrency** — only one Celery worker allowed because of the `PersistentClient` SQLite lock. Horizontal scale requires `HttpClient` + a dedicated chroma-server process.
- **`migrate_legacy_per_job_collections`** is implemented but not wired into `app/main.py` lifespan. Safe to run manually; will be auto-run on startup in a future commit.
- **Per-user library scoping** — the schema is single-tenant. Adding `owner_id` to `jobs` and a router-level filter is straightforward but not yet done.
- **Report regeneration** — if a report goes stale (new chunks added to the library for an existing job's videos), there's no automatic re-report. User deletes and re-creates the job as a workaround.
- **Rate limit for OpenAI** — currently no application-level throttle; relies on OpenAI's API to return 429 and retry naturally. A limiter similar to `transcript_limiter` would smooth spikes.

## 17. Glossary

- **Chunk**: a ~256-token slice of a transcript, with its start/end timestamps and source metadata, stored as a single row in ChromaDB.
- **Global collection**: the single ChromaDB collection where every chunk lives, regardless of which job added it.
- **JobVideo**: the many-to-many join between a job and the videos it selected; the vehicle for per-job approval state without owning the video.
- **Library-wide Q&A**: a Q&A query with `video_ids=None` — searches the whole collection instead of a job's subset.
- **Map-reduce report**: per-chunk LLM extraction (`map_chunks`) → per-video / global aggregation (`reduce_summaries`) → final HTML synthesis (`compose_report`). Handles transcript sets larger than the LLM context window.
- **Refinement step**: an LLM pass between retrieval and answering that compresses noisy 50k-char raw context down to the ~3k-token distilled context the answer LLM actually sees.
- **Transcript cache**: `transcript_cache` table, keyed by `video_id`, holding raw segments. Lets us re-chunk without re-fetching if the chunking algorithm changes.
- **Approval pause**: the two-task Celery pattern that separates discovery from extraction across a user gate without blocking a worker.

---

*Last updated: 2026-04-20. This document should be kept in sync as architecture evolves. When a new feature introduces a new data flow, a new algorithm, or a new communication channel, update the relevant section here.*
