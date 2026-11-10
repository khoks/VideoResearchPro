# Pratidhvani — System Architecture

**Status:** current as of 2026-04-24; sections amended through 2026-11-04 (latest: the whole page re-read against the code after batch 4 of 2026-11-03). Brand-name forward; the one default that keeps the legacy name is the SQLite file `data/videoresearchpro.db` — see [migration-code-identifiers.md](migration-code-identifiers.md).

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
                                              │ │ Agents        │ │  │ ChromaDB         │
                                              │ │  ▸ Search     │◀┼─▶│  ▸ transcripts   │
                                              │ │  ▸ Report     │ │  │  ▸ qa_library    │
                                              │ │  ▸ Q&A        │ │  │  ▸ notes         │
                                              │ │  ▸ Knowledge  │ │  │  ▸ shares        │
                                              │ │  ▸ Q&A History│ │  │  ▸ personal ctx  │
                                              │ │  ▸ Visual     │ │  └──────────────────┘
                                              │ │  ▸ Echo       │ │  ┌──────────────────┐
                                              │ └───────────────┘ │  │ Redis            │
                                              │      │ publish     │  │  ▸ db0 pub/sub   │
                                              │      ▼             │  │  ▸ db1 broker   │
                                              │  Redis Pub/Sub     │◀─│  ▸ db2 results  │
                                              │  job_progress:*    │  └──────────────────┘
                                              └──────────────────┘
```

Four processes run side-by-side in development: the FastAPI app (`uvicorn`), the Celery worker (`celery -A app.tasks.celery_app worker --pool=solo`), exactly one Celery beat (`celery -A app.tasks.celery_app beat`, the scheduler tick added by S-8.3.1), and Redis (Windows service via winget). SQLite and ChromaDB are file-backed under `data/`. The frontend is a separate Vite dev server that proxies API calls to the backend.

Production targets the same shape, with SQLite swapped for Postgres and ChromaDB hosted (or pgvector); see [saas-roadmap.md](saas-roadmap.md).

---

## Process responsibilities

### FastAPI app (`uvicorn app.main:app`)

- Serves the REST API and the WebSocket endpoint.
- Holds the only SQLAlchemy engine that handles request-time queries.
- On startup (FastAPI lifespan):
  - Creates `data/` directories (DB, ChromaDB, reports).
  - Brings the schema to Alembic head (`schema_init_service.ensure_schema_at_head`, E-4.10): an empty database is migrated, one at head is left alone, and a pre-E-4.10 database whose tables match the ORM is stamped.
  - Runs `services/llm_smoke.run_startup_probes` — see "LLM smoke + fail-soft" below.
  - Runs the idempotent Chroma backfills, each fail-soft (a failure is logged and startup continues): `chroma_service.backfill_qa_library` (every Q&A exchange into `qa_library_global`), `chroma_service.backfill_chunk_document_ids` (stamps `document_id` on chunks embedded before 2026-10-19, [D-070](decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19)), `note_index.backfill` (S-8.5.2) and `echo_personal_vectors.backfill` (S-3.3.3). The first two also run when a Celery worker starts (below), the Q&A one as a queued task.
  - Ensures the search index (S-8.2.1, [D-078](decisions.md#d-078--search-index-one-trigram-fts5-table-per-entity-copies-not-external-content-like-fallback-2026-10-19)): `services/search_service.ensure_index_for_url` probes SQLite for FTS5 with the trigram tokenizer, creates any missing `fts_*` virtual tables and their `AFTER INSERT / UPDATE / DELETE` triggers, rebuilds the ones just created from their base tables, and records the backend (`fts5` or `like`) that `GET /health` reports as `search_backend`. Migration `a9f3c1e7b5d2` does the same conditionally, so a fresh install is indexed before the first request; the lifespan re-probe is what picks up a Python upgrade that gains FTS5 later. Never blocks startup. The worker needs nothing: the triggers live in the database, so ingest writes from any process are indexed.
- On shutdown: flushes any pending Chroma writes, closes the embedding model, releases Redis connections.
- Does **not** run Celery tasks itself. It only `.delay()`-dispatches them.

### Celery worker (`celery -A app.tasks.celery_app worker --pool=solo`)

- Runs all long-running orchestration: search, transcript fetch, embedding, report generation, saved-search runs, newsletters, frame capture, Echo's share processing, signal extraction, connector syncs and voice-test writing, and Author Studio generation (`author.generate_output`, S-6.7.1). Task modules: `app/tasks/*_tasks.py`. Knowledge extraction is the exception that runs inside its request. A book's EPUB is built in-process; its PDF is printed by WeasyPrint or headless Chromium, both optional installs probed once per process (`AUTHOR_PDF_ENGINE`, S-6.1.5) and both cut off from the network.
- Has its own SQLAlchemy session factory (created per task) so request-side and worker-side don't share connections.
- Publishes progress events to Redis pub/sub (`job_progress:{job_id}`) at every phase boundary. Author outputs publish on the same channel under the output's id; `routers/ws.py` lets a socket subscribe to any job or output its user owns. Output cancellation is cooperative: `output_service.report_progress` raises once the row is `cancelled`, because `revoke(terminate=True)` cannot stop a task on the solo pool. An ended output stays ended as a run does (T-5.2.34): every output status and progress write is one conditional `UPDATE` that refuses a row in `TERMINAL_STATUSES` (`output_service._write_unless_ended`), with the run's pending content in the same transaction, and its event is published only once it has committed, so the cancel route never writes over a finished output and a run never writes `completed` or `failed` over a cancel. An output that ends other than `completed` keeps no text, citations or files, though a book commits its manuscript with its EPUB and PDF progress reports: the cancel's write and the run's own `failed` or `skipped` write clear the text and citations in the same transaction, and a run that finds its output ended by someone else clears them and removes the folder. A second live delivery of the task can still replace a completed output's files with its own until its next progress write stops it (T-5.2.29). Job cancellation is too (T-5.2.20): each job task returns at once when its row is already `cancelled`, `failed` or `completed` (`job_tasks._already_stopped`), stops at its next check when the row becomes so (`_is_stopped`), and makes every status and progress write a single conditional `UPDATE ... WHERE status NOT IN ('failed', 'cancelled', 'completed')` (`_write_unless_stopped`), so no run turns a stopped row back into an active or completed one. A progress event goes out only after its write (T-5.2.21), so a stopped run publishes nothing more. `completed` counts as over since T-5.2.23: tasks ack late, so a worker that died between writing it and the ack had the task delivered again, and the run ran twice; the topic and channel first phases also leave alone a row at `awaiting_approval` or past it, which the resume owns. The cancel route's own write is conditional on the run not having ended (T-5.2.22), and once it has committed the route publishes the change to `cancelled` on the run's channel, so every open page hears of it at once (T-5.2.30). Only the cancel whose own write took publishes: a second cancel that raced it reads the row count (`job_service.write_job_status`) and stays silent (T-5.2.32).
- On Windows, **must use `--pool=solo`** because the multiprocessing prefork pool doesn't work cleanly with our embedding model + ChromaDB locks.
- Does **not** run the LLM smoke check. Task-time LLM failures surface on the Jobs page via the worker's progress publisher.
- On worker start (S-5.10.5), the `worker_ready` hook `run_startup_backfills` in `app/tasks/celery_app.py` runs the API lifespan's two retrieval backfills, both fail-soft (a failure is logged and the worker continues). The worker retrieves too (a saved-search run is a library Q&A), so a worker-only start after an upgrade must not leave pre-2026-10-19 chunks unretrievable until the API boots.
  - `backfill_chunk_document_ids` (D-070) runs inline. Celery sends `worker_ready` just before the consumer loop, so no task runs before the chunks are stamped. It is a metadata scan; nothing is re-embedded.
  - `backfill_qa_library` (idempotently upserts every row from `qa_exchanges`, `library_qa_exchanges` and `qa_history_exchanges` into `qa_library_global`) is queued as the `chroma.backfill_qa_library` task on the `default` queue. It re-embeds every exchange on every run and nothing waits on it, so it does not hold the consumer loop. On the solo pool it runs after whatever was already queued; on a prefork pool it runs in a child.
  - Then the hook closes the Chroma client and drops the embedding model that the chunk backfill opened (`chroma_service.close_client`). A prefork pool forks every replacement child (after a revoke with `terminate`, a crash, an OOM kill) from this process, and neither a Chroma client nor the model survives a fork. As a guard, a `worker_process_init` receiver makes each prefork child drop anything it inherited anyway (`chroma_service.forget_inherited_client`). On the solo pool the first task that needs them opens them again.
  - Before S-5.10.5 the worker ran no backfill at all, although this page said it ran the Q&A one. The notes and Echo personal-context backfills still run only in the API lifespan.

### Celery beat (`celery -A app.tasks.celery_app beat -s data/celerybeat-schedule`)

Added 2026-10-19 (S-8.3.1, the scheduler the saved searches, newsletter and Echo syncs run on; plan in [plans/m3-saved-searches-alerts.md](plans/m3-saved-searches-alerts.md)). Decision [D-077](decisions.md#d-077--scheduler-one-static-beat-entry-over-table-rows-beat-is-its-own-process-with-no-pidfile-2026-10-19).

- **One static entry.** Beat fires exactly one task, `scheduler.tick` (`app/tasks/scheduler_tasks.py`), every `SCHEDULER_TICK_SECONDS` (default 300) on the `default` queue with `expires` set to the same interval, so ticks that sat unconsumed while the worker was down are dropped rather than replayed. Nothing else is ever a beat entry: everything that runs on a schedule is a **row** in `scheduled_runs`, which keeps the schedule inside the SQLite backup and needs no Redis-backed beat store (RedBeat and friends were rejected in the plan).
- **The tick** (`app/services/scheduler_service.run_tick`) selects enabled rows with `next_run_at` within `SCHEDULER_GRACE_SECONDS` of now, claims each with a single `UPDATE … WHERE claimed_at IS NULL OR claimed_at < now − SCHEDULER_LEASE_SECONDS` (so a second tick, or a second beat, claims nothing), dispatches the row's kind through `task_routing_service.dispatch_for_tenant_id` (tier queues apply), computes the next slot from `max(now, next_run_at)` and releases the claim. A failed dispatch is retried at the next tick up to `SCHEDULER_MAX_RETRY_TICKS` times, then waits for its cadence; an unknown kind is recorded as `no_handler` and advanced.
- **Cadences are human, never cron**: `daily` / `weekly` / `monthly` with hour, minute, weekday or day-of-month (1–28) and an IANA zone, or `every` N seconds. `next_run_at` is computed by Celery's own `crontab.remaining_delta` on the row's local wall clock and converted back to UTC, so a 09:00 local run stays 09:00 local across DST. Every datetime in the table is naive UTC (SQLite drops tzinfo).
- **Kinds register themselves** from the task module that defines their Celery task (`scheduler_service.register_kind("saved_search", run_saved_search)`); `celery_app.autodiscover_tasks` must import that module. The API process and the worker may know different kinds; only the worker dispatches.
- **Exactly one beat.** Celery's embedded `worker -B` is unverified with `--pool=solo` and discouraged for production, so beat is its own process started by `scripts/start.ps1` and `scripts/restart_services.ps1`, which kill any earlier beat before starting one. `--pidfile` is deliberately not used: Celery's stale-pidfile probe is `os.kill(pid, 0)`, which on Windows terminates whatever process now owns that pid.
- `GET /api/v1/health/scheduler` reports the configuration, the kinds this process can dispatch and row counts (total / enabled / due / claimed) plus the newest `last_run_at`. `SCHEDULER_ENABLED=false` registers no beat entry, and a tick that still arrives no-ops.

### Redis

Three logical databases on the same instance:

- **db0** — Pub/sub channels for progress events (`job_progress:{job_id}`) and the notification doorbell (`notifications:{tenant_id}`).
- **db1** — Celery broker (queue of pending tasks).
- **db2** — Celery result backend (task return values).

### SQLite

`data/videoresearchpro.db` (env `DATABASE_URL`). Author Studio's binary artifacts sit beside it under `data/outputs/<user_id>/<output_id>/artifact.<format>` (env `OUTPUTS_DIR`, S-6.7.2); `outputs.content_path` is stored relative to that root, deleting an output removes its directory, and `scripts/sweep_output_artifacts.py` finds directories left without a row. All structured state: users, jobs, documents (formerly `videos`; renamed in L1 PR 4), channels, transcript cache, Q&A exchanges, knowledge artifact metadata, scheduled runs. Alembic migrations under `backend/alembic/`. Beside the ORM tables sit the S-8.2.1 search index's FTS5 virtual tables (`fts_documents`, `fts_jobs`, `fts_channels`, `fts_qa`, `fts_knowledge`, plus SQLite's `fts_*_data` / `_idx` / `_content` / `_docsize` / `_config` shadow tables): one trigram-tokenised table per entity, each row carrying the entity id as an `UNINDEXED` column and a copy of the indexed text, kept current by triggers. They have no ORM model and `schema_init_service` ignores the `fts_` prefix when comparing the live schema to the ORM. External-content mode was rejected because it maps on rowid and every base table has a string primary key, whose rowids are not stable across `VACUUM`.

### ChromaDB

`data/chroma/` (env-overridable). Five collections:

- **`pratidhvani_global`** (`CHROMA_GLOBAL_COLLECTION_NAME`) — chunked text of every ingested document. Single collection across all jobs. Per-job scoping is a metadata filter at query time. An install that embedded before T-2.6.1 keeps its chunks under `videoresearchpro_global` by pinning that name, or migrates ([runbook](migration-code-identifiers.md)).
- **`qa_library_global`** — every Q&A exchange (job-scoped, library-scoped, history-chat) as a single concatenated `question + answer` document — not chunked.
- **`notes_global`** — the user's own notes, one vector per live note.
- **`shares_global`** and **`personal_context_global`** — Echo's collections, one vector per share and per live fact or signal.

The last three are private: every query carries a fail-closed tenant filter.

Chunks use the multilingual embedder `paraphrase-multilingual-MiniLM-L12-v2` (SentenceTransformer, CPU). No paid embedding API.

---

## Backend layout

```
backend/
├── app/
│   ├── main.py                  # FastAPI app, CORS, lifespan (schema, dirs, LLM smoke, backfills)
│   ├── config.py                # Pydantic Settings (reads .env)
│   ├── database.py              # SQLAlchemy engine + SessionLocal
│   ├── dependencies.py          # DI: get_db, get_redis, get_current_user, require_operator
│   ├── middleware/
│   │   ├── cors.py              # CORS on the app's one origin list (T-4.11.3.3)
│   │   └── rate_limit.py        # per-route + per-tier limits (E-5.5)
│   ├── routers/                 # one file per API area; every route is in api-reference.md
│   │   ├── auth.py              # /auth: register, login, password reset + change, me, audit log
│   │   ├── sessions.py, mfa.py, oauth.py, credentials.py, onboarding.py  # the rest of /auth
│   │   ├── jobs.py, job_templates.py  # /jobs CRUD + approve + cancel, /job-templates
│   │   ├── qa.py, reports.py    # /jobs/{id}/qa, /jobs/{id}/report*
│   │   ├── library.py           # /library: qa, videos, graph, upload-pdf, paste-urls
│   │   ├── channels.py, shelves.py, tags.py, notes.py, search.py, suggestions.py
│   │   ├── saved_searches.py, notifications.py
│   │   ├── knowledge.py, frames.py  # /videos/{id}/...
│   │   ├── qa_history.py        # /qa-history/chat, /qa-history/exchanges
│   │   ├── author.py            # /author: outputs, newsletter
│   │   ├── echo.py, echo_cards.py, echo_connectors.py, echo_drafts.py,
│   │   │   echo_signals.py, echo_voice_test.py  # /echo
│   │   ├── exports.py           # /exports: Q&A + knowledge datasets, notes
│   │   ├── usage.py, llm_settings.py  # /usage, /settings/llm
│   │   ├── admin.py             # /admin/restart, operators only
│   │   ├── health.py            # /health (overall, LLM, scheduler, quota)
│   │   └── ws.py                # /ws/jobs (multiplexed progress, the bell)
│   ├── models/                  # one file per table: user, job, document (global, deduped),
│   │                            #   job_video (job ↔ document), document_visibility, channel,
│   │                            #   channel_subscription, transcript_cache, the Q&A exchanges,
│   │                            #   notes, shelves, tags, outputs, saved searches, Echo's stores,
│   │                            #   sessions, MFA, credentials, usage_record, quota_usage, ...
│   ├── schemas/                 # Pydantic models for the routers
│   ├── services/                # the business logic; the ones that recur below:
│   │   ├── auth_service.py      # JWT issue/verify, sessions, password hashing (bcrypt)
│   │   ├── job_service.py       # job CRUD + the concurrent-job limit
│   │   ├── visibility_service.py  # who sees which document (D-063, D-070)
│   │   ├── usage_service.py     # per-tenant usage metering (E-5.2)
│   │   ├── document_cap_service.py  # the tier's document cap (D-115)
│   │   ├── youtube_service.py   # YouTube Data API v3, transcripts, Whisper fallback, rate limiting
│   │   ├── chroma_service.py    # PersistentClient singleton, collection CRUD, backfills
│   │   ├── document_text_service.py  # a document's full text by document_id (D-113)
│   │   ├── embedding_service.py # paraphrase-multilingual-MiniLM-L12-v2
│   │   ├── progress_service.py  # Redis pub/sub publisher
│   │   ├── report_service.py    # HTML report file I/O
│   │   ├── dataset_service.py   # streaming JSONL exports for fine-tune
│   │   ├── quota_service.py     # YouTube API quota tracking
│   │   ├── llm_routing.py       # USE_CASE_REGISTRY + resolve_config
│   │   ├── llm_service.py       # get_llm_for(use_case) factory, byok_context
│   │   ├── llm_smoke.py         # startup probes + LLMStatus singleton
│   │   └── outputters/          # one per Author Studio kind
│   ├── sources/                 # ingest connectors, one package per source type
│   ├── connectors/              # Echo connectors and export importers
│   ├── agents/
│   │   ├── state.py             # TypedDict states per agent
│   │   ├── search_agent.py      # topic → query plan → searches → ranked list
│   │   ├── report_agent.py      # transcripts → map-reduce → HTML
│   │   ├── qa_agent.py          # question → retrieve → refine → answer + citations
│   │   ├── qa_history_agent.py  # meta-chat across qa_library_global
│   │   ├── knowledge_agent.py   # full text → batched extract → synthesized MD
│   │   ├── visual_agent.py      # select moments → capture stills → describe → persist
│   │   ├── echo_agent.py        # "speak as me": classify → retrieve → draft → critique
│   │   ├── prompts/             # prompt templates per agent
│   │   └── tools/               # @tool functions (youtube_search, rag_search)
│   ├── tasks/
│   │   ├── celery_app.py        # Celery config; one autodiscover call per task module
│   │   ├── job_tasks.py         # execute_topic_job, execute_channel_job,
│   │   │                        #   execute_subscription_job, resume_job_after_approval
│   │   └── scheduler_tasks.py, output_tasks.py, saved_search_tasks.py, newsletter_tasks.py,
│   │       echo_tasks.py, echo_connector_tasks.py, visual_tasks.py
│   ├── websocket/
│   │   └── manager.py           # ConnectionManager + Redis listener task
│   └── utils/
│       ├── app_origins.py       # the origins CORS answers and sign-in returns to (T-4.11.3.3)
│       ├── chunking.py          # 256-token chunks (32 overlap) with timestamp mapping
│       ├── html_builder.py      # Jinja2 env + custom number_format filter
│       ├── tiktoken_cache.py    # tiktoken's encoding in TIKTOKEN_ENCODINGS_DIR (T-8.8.6.5)
│       └── ...
├── tests/                       # 6,000+ tests, mostly pytest + httpx test client
├── alembic/                     # Alembic migrations
└── scripts/                     # measurement harnesses, backfills (dry run unless --write), and
    ├── fix_anchor_links.py      # the Markdown anchor checker CI runs
    ├── stress_test_llm.py       # canonical LLM stress harness
    └── stress_test_local_llm.py # thin shim → stress_test_llm.py
```

---

## Frontend layout

```
frontend/
├── src/
│   ├── main.tsx                 # entry point
│   ├── App.tsx                  # providers + router
│   ├── routes/index.tsx         # route table, auth guards, lazy pages
│   ├── layouts/AppLayout.tsx    # the signed-in shell: navigation, the bell, the Echo panel
│   ├── pages/                   # one file per page, listed in ui-pages.md
│   ├── components/              # by feature (reader, qa, echo, author, security, ...), plus
│   │                            #   primitives/ for the shared design-system pieces
│   ├── hooks/                   # React Query hooks per resource, and:
│   │   └── useJobProgress.ts    # WS subscribe → React Query cache invalidation
│   ├── contexts/AuthContext.tsx # the signed-in user + token
│   ├── services/
│   │   ├── api.ts               # axios instance, token attach, error normalization
│   │   ├── apiFiles.ts          # file downloads with the bearer header, opened from blob: URLs
│   │   ├── wsClient.ts          # /ws/jobs WS with reconnect + heartbeat
│   │   ├── sessionExpiry.ts     # what a 401 does: ends the session, keeps the page
│   │   ├── queryClient.ts       # the app's one query client, with the global error toast
│   │   └── *Api.ts              # one file per resource (jobsApi.ts, libraryApi.ts, etc.)
│   ├── stores/                  # Zustand: UI state only (Echo panel, palette, reader, ...)
│   ├── config/features.ts       # UI switches decided by the owner (visual analysis is off)
│   ├── theme.ts                 # design tokens ← per branding.md
│   └── index.css                # global resets + CSS variables
└── vite.config.ts               # dev server, proxy /api and /ws to localhost:8000
```

State split: **server state in React Query**, **UI state in Zustand**. No Redux. No styled-components — every component uses inline `style={{}}` objects, with tokens from `theme.ts`; `components/primitives/` holds the shared pieces.

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
       ├──< QAHistoryExchange
       ├──< Note ──> (document | knowledge_artifact | job | qa_exchange |
       │              library_qa_exchange | qa_history_exchange | channel)
       ├──< PersonalContext                                 (Echo facts, per tenant)
       ├──< Share ──> file under ECHO_SHARES_DIR/<tenant>/  (Echo shares inbox, per tenant)
       ├──< Shelf ──< ShelfJob >── Job                      (M1, per tenant)
       ├──< Tag ──< Tagging ──> Document                    (M1, per tenant)
       ├──< Session, MfaSecret, UserCredential, OAuthIdentity  (the account)
       ├──< UsageRecord                                     (E-5.2, per tenant, day and feature)
       └──< JobTemplate ──< JobTemplateVersion              (M6; tenant NULL = built-in)
                 ▲
                 └── Job.template_id + template_version (provenance, no FK)

Document ──< KnowledgeArtifact (columns on Document, not a separate table)
Document ──  DiscussedEra (column `discussed_era_json` on Document — R3, see below)
Document ──< TranscriptCache (1:1 by document_id; FK ON DELETE CASCADE)
Document ──< VisualFrame (0:N by (document, timestamp); FK ON DELETE CASCADE)

ApiQuotaLog (append-only ledger of YouTube Data API calls, install-wide)
```

> **Schema state (post-E-1.10, 2026-05-02).** The primary key on `documents` is now `document_id` (UUID4, str(36)). The legacy `video_id` column survives as a NULLABLE back-compat reading column populated for `source_type='video'` rows (NULL for Reddit / HN / other source types). The join table is renamed to `job_documents` (Python class still `JobVideo` for import back-compat) with composite PK `(job_id, document_id)`. `transcript_cache` PK is also now `document_id` with FK to `documents.document_id`. See [D-017](decisions.md#d-017--e-110-hard-cutover-single-migration-uuid-pk-promotion-2026-04-26) for the cutover rationale and [PR #112](https://github.com/khoks/VideoResearchPro/pull/112) for the migration.

> **Two dates per source (R3, 2026-10-19).** `documents.published_at` is when a source was POSTED; `documents.discussed_era_json` is the period it is ABOUT — `{era_start, era_end, era_confidence, is_retrospective, era_label}`, integer years (negative = BCE), extracted once per document by the `temporal_scope_extract` use case the first time any job chunks it (`job_tasks._ensure_era`, fail-soft, failures not persisted), then reused by every later job like transcripts and embeddings. NULL means not yet extracted; null years mean undatable. Both read as UNKNOWN downstream, never as "discusses now". See [D-072](decisions.md#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19).

### Key invariants

- **Documents are global.** One row per source. Canonical identity is `(source_type, source_id)` (unique-indexed); the PK is the synthetic `document_id` UUID. Source types: `video` (YouTube), `reddit_post`, `hn_story`, `mastodon_post`, `bluesky_post`, `podcast_episode`, `article`, `tweet`, `pdf`, and the pasted `fb_post`, `ig_post` and `li_post`. The library is a single, deduplicated, shared corpus. `JobVideo` rows in `job_documents` tie a job to its documents. Deleting a job drops `JobVideo` rows; documents and chunks survive.
- **Channels are first-class.** Subscribing a channel pre-pulls every video on its uploads playlist into the global library via subscription jobs.
- **Transcripts are cached once.** Re-fetch is suppressed by `transcript_cache.document_id` lookup. Legacy `transcript_cache.video_id` column survives as nullable back-compat for video rows.
- **Embeddings happen exactly once per document.** `Document.embedded_in_chroma` flips to `true` after chunks land in the global collection. Subsequent jobs referencing that document skip embedding. Since PR #440 the flag is set only once `insert_chunks` has returned; documents an earlier run left flagged with no chunks are found by `backend/scripts/check_embedded_flags.py`, whose `--write` clears the flag so the next job that selects one embeds it (T-5.2.24). It reads the configured collection alone, so it refuses while any other collection in the store holds chunks of this database's documents (T-5.2.26).
- **Q&A exchanges have three flavors** that union into one Chroma collection:
  - `qa_exchanges` (job-scoped)
  - `library_qa_exchanges` (library-scoped; `scope_json` narrows a question to a shelf or to one source, documents and the asker's notes alike, or records that a saved search asked it, null = the whole visible library and every note: [D-095](decisions.md#d-095--scoped-library-questions-one-history-table-with-a-scope_json-object-narrowing-and-provenance-keys-unknown-keys-refused-2026-10-19))
  - `qa_history_exchanges` (meta-chat surface)

  All three are stored separately for SQL-level filtering but indexed together in `qa_library_global` so meta-chat retrieval crosses surfaces. Each carries a nullable `answer_cut_off` (T-1.15.4.8): what the check found when the answer was written, NULL on a row from before it, which is unknown and never "not cut". A saved search's cut answer never becomes its baseline (T-1.15.4.9).
- **Echo's data is a registered set of stores, per tenant** (I-3). `personal_context` (facts), `shares_inbox` (everything the user forwards; files under `ECHO_SHARES_DIR/<tenant>/`), `voice_signals` (style and personality signals with their examples, tombstones included; S-3.3.1), `voice_signal_inputs` (which of the user's texts extraction read, with stylometric profiles; S-3.3.2), `activity_events` (what the user did, from connectors and the `internal` share event; unique per tenant, connector and external id; S-3.2.1), `echo_connector_grants`, `echo_drafts` ("speak as me" drafts with their citations and scores, and the user's saved version, whose typed words alone feed signal extraction as `draft_edit:<id>`; S-3.4.2) `echo_voice_gates` (each user's voice-test result, the per-user switch; S-3.4.1), `echo_voice_tests` (each in-app voice test: its pairs, picks and score; T-3.4.1.8) and `echo_fact_tombstones` (derived facts the user deleted, per connector, which syncs and re-imports skip; T-3.2.4.4, [D-122](decisions.md#d-122--a-deleted-derived-fact-stays-deleted-per-connector-only-a-refused-refresh-asks-for-a-reconnect-restore-re-checks-the-evidence-2026-11-04)) are listed in `echo_privacy_service.ECHO_TABLES`, and Echo's Chroma collections (`shares_global`, `personal_context_global`) in `echo_vectors.echo_collection_names()`. `personal_context_global` holds one vector per live fact and signal. It is kept in step by `echo_personal_vectors.sync_tenant`, a content-hash diff that every write path runs after its commit and the startup backfill runs per tenant, so a tombstone's vector is gone as soon as the tombstone exists (S-3.3.3). Connector tokens (`echo_connector_credentials`, Fernet) and in-flight OAuth state (`echo_connector_oauth_states`) are in `ECHO_SECRET_TABLES`: erased with the rest but never exported ([D-098](decisions.md#d-098--echo-connectors-events-unique-per-reader-tokens-in-a-secret-store-that-is-erased-with-the-brain-but-never-exported-2026-10-19)). Connectors and archive importers implement `app/connectors/base.py` and register in `app/connectors/registry.py`. `GET /echo/export` writes the brain into one lossless archive; `DELETE /echo/brain` removes vectors, then files, then rows, and re-counts every store. A share is context-only unless the user marks it as their own words. See [D-089](decisions.md#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19).
- **Notes are the user's own text, private per tenant** (M5). `notes(id, tenant_id, target_type, target_id, selector_json, body_md, motivation, created_at, updated_at, deleted_at)`. The target set is closed; the target is checked through visibility or ownership on every write; a document note is stored under `document_id`, so one document has one note stream. Delete is soft, and the JSON-LD export carries withdrawals losslessly. Each live note has one vector in `notes_global` (S-8.5.2). See [D-074](decisions.md#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19).
- **Shelves, tags and templates are per tenant** (M1, M6). `shelves` + `shelf_jobs` group runs (a run on many shelves; deleting either side removes only memberships, through ORM cascades because SQLite here never enforces FK cascades). `tags` + `taggings` label documents per reader, even on shared documents; every count and filter re-applies visibility. `job_templates` + immutable `job_template_versions` hold reusable recipes; runs record `(template_id, template_version)` and templates are soft-deleted so that provenance survives. See [D-082](decisions.md#d-082--job-templates-identity-plus-immutable-versions-provenance-without-a-foreign-key-starters-in-a-self-contained-data-migration-2026-10-19) and [D-083](decisions.md#d-083--organisation-features-access-and-scope-defaults-on-the-plans-open-questions-2026-10-19).
- **Derived views are computed on read, per tenant** (M7, M9). `channel_intelligence_cache(channel_id, tenant_id, fingerprint, computed_at, payload_json)` caches a channel's aggregates for one reader and recomputes when the fingerprint of its inputs (visible document set, knowledge times, transcripts, payload version) changes. The library graph (`services/graph_service.py`) has no table: nodes and edges are built per request from the reader's visible documents, about 0.07 s at 2,000 documents. Both start from `visibility_service.visible_document_ids`, so an empty visible set is an empty result. See [D-091](decisions.md#d-091--channel-intelligence-aggregates-computed-on-read-and-cached-per-reader-behind-an-input-fingerprint-derived-links-resolved-at-read-time-2026-10-19) and [D-092](decisions.md#d-092--library-graph-computed-per-request-sigma-used-directly-as-a-lazy-chunk-three-group-colours-the-accessibility-layer-inside-the-story-2026-10-19).
- **Knowledge artifacts live on the Document row.** Three nullable columns (`extracted_knowledge_json`, `knowledge_report_md`, `knowledge_extracted_at`). One artifact per document.
- **Jobs carry a status enum**: `pending → searching → awaiting_approval → extracting → building_rag → generating_report → completed`. Terminal: `completed`, `failed`, `cancelled`. Subscription jobs skip `awaiting_approval` and `generating_report`.

### Forward-compat columns

Per [saas-roadmap.md](saas-roadmap.md) and [source-types.md](source-types.md):

- Most user-scoped tables carry `tenant_id`, and every read of them filters on it. `outputs`, `quota_usage`, `user_llm_overrides`, `user_credentials`, `oauth_identities`, `sessions`, `mfa_secrets`, `mfa_step_tickets` and `password_reset_tokens` key on `user_id` instead. Today a tenant is one user, so both equal `User.id`. On `jobs` and the three Q&A tables `tenant_id` stays nullable until the operator runs [the NOT NULL migration](migration-tenant-id-not-null.md).
- The `documents` table carries `source_type`, `source_id`, `source_url`, `source_metadata_json`, `language`, `word_count`, `user_provenance_json` (from L1 PR 1) plus `document_id` UUID PK (from E-1.10, PR #112). The legacy `video_id` column persists as nullable back-compat and is NULL for every non-video source — never key anything on it. The future `creator_id` foreign key for cross-source-type creators is the next planned column (E-1.9).
- **Document visibility.** `document_visibility(document_id, tenant_id, source)` is the per-tenant grant over the shared cache ([D-063](decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)), re-keyed on the primary key by [D-070](decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19) after the original `video_id` key silently dropped every PDF and pasted page. Every ingest path calls `visibility_service.grant(db, document_ids, tenant_id, source)`, including on dedup hits; every user-facing read of `documents` filters through `visibility_service.visible_document_ids(db, tenant_id)`; library Q&A hands the same set to Chroma.
- The `channels` table grows into `creators` with `source_type`, `source_weight` (E-1.9). `source_type`, `creator_external_id`, and `source_weight` are already present from L1 PR 1. Per-user state, including `source_weight`, moved to `channel_subscriptions` in [D-065](decisions.md#d-065--channel-subscriptions-become-per-tenant-transliteration-reversed-2026-07-31). Q&A retrieval reads it as a re-rank since S-7.1.1 ([D-068](decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18)).
- The classifier output (D-007 / D-014) lands at `documents.source_metadata_json["classification"]` per [D-023](decisions.md#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28); inserted via the source-type-agnostic `_upsert_candidate_and_link()` helper (PR [#113](https://github.com/khoks/VideoResearchPro/pull/113)).

New tables and columns keep both invariants.

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

Topic jobs carry a `source_types_json` column — a JSON-encoded array of `source_type` discriminators, set from the optional `source_types` of `POST /api/v1/jobs` (S-1.5.13, [D-114](decisions.md#d-114--which-sources-a-topic-run-searches-settings-decide-one-budget-for-the-run-no-whisper-before-approval-2026-10-29)). NULL → `["video"]`, which is also what a request that names none gets. `app/services/job_source_types.py` decides what a run may search: a source that is unknown, library-only or not set up on this install is refused with a message naming the missing setting. `execute_topic_job` reads the column and branches:

- **`"video"`** → existing LangGraph search agent (richer ranking via `search_plan_queries` + `search_rank_and_curate` use cases).
- **Everything else (`"reddit_post"`, `"hn_story"`, `"mastodon_post"`, `"bluesky_post"`, `"podcast_episode"`, `"article"`, `"tweet"`)** → `app/services/connector_dispatch.py::dispatch_search()`, which iterates each non-video source_type **sequentially** (per [D-026](decisions.md#d-026--sequential-fan-out-for-the-connector-dispatcher-2026-05-02)) through `connector_for(source_type).search(query, instructions, limit)`. For each Candidate, the connector's own `fetch_text(query=...)` is called (which inline-classifies per [D-023](decisions.md#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28)); persistence is uniform across source types via `_upsert_candidate_and_link()`.

Both paths converge into the same `awaiting_approval` flow. The combined candidate count drives the user-visible "Found N candidates" message; an empty result across all sources fails the job with a clear "No candidates for source_types=[...]" error rather than dropping the user onto an empty approval list.

Per-source-type errors (connector raised, missing connector) are captured per source in `DispatchResult.errors_by_source_type` and `failures_by_source_type`; they don't fail the job — other source types' candidates still flow through. A connector's `search()` raises when the service failed, because an empty list means "nothing found", and the run says which it was (`run_notes`, S-1.5.14). A 401 or 403 also holds the source off the submit form (`source_refusal_service`). `NotImplementedError` from a PDF-style source counts as zero candidates.

The non-video sources search before YouTube, without fetching text, so what they have decides the shares: `job_source_types.redistribute` gives a share a source cannot fill to the sources that can use it, and YouTube takes its part as a bigger target on its one search, within `YOUTUBE_DAILY_QUOTA`. Text is fetched afterwards, for what the run keeps.

The number of results is the whole run's budget, shared across its sources, so the tier cap bounds the run. Nothing goes to Whisper before approval: a podcast episode with no transcript in its feed is transcribed only after it is approved, and counts against `WHISPER_MAX_PER_JOB`. Each approved document is fetched once, because the text found during the search is reused at extraction.

### Approval pause mechanism

Topic jobs pause at `awaiting_approval`. The pause is **passive, not blocking**:

1. Celery task fetches search results, persists candidate documents (any source_type), sets `status='awaiting_approval'`, and **exits**. No worker is held waiting.
2. The user reviews and POSTs `/api/v1/jobs/{id}/approve` with a list of approved row IDs in `approved_video_ids`. Per S-1.5.4 (post-M-1.5), the field name is legacy — values can be either YouTube `video_id` strings (for `source_type='video'`) or `document_id` UUIDs (for non-video sources where `video_id` is NULL). The backend matches against both columns on each `JobVideo` row.
3. The router updates `JobVideo.approved=True` for the chosen rows, then dispatches a **new** Celery task (`resume_job_after_approval`) which picks up at the extraction phase.

This pattern means a job can sit in `awaiting_approval` for arbitrary time without consuming worker capacity.

**Document caps** (T-5.2.10, [D-115](decisions.md#d-115--the-document-cap-counts-visible-documents-a-request-that-names-its-documents-is-all-or-nothing-and-nothing-is-granted-before-approval-2026-10-29)). `document_cap_service` holds a tenant's library to its tier's cap (Free 500, Pro 5,000, Studio unlimited), counting visible documents: one the tenant already has never counts again, and one only someone else added counts as new. Approval, a PDF upload and pasted URLs are all or nothing. Subscribing to or syncing a channel is refused only when the library is already full; otherwise the sync stops at the cap, newest uploads first, and says how many it left out. Visibility is granted at approval, and only for the approved documents, so a deselected candidate never reaches the library.

#### Polymorphic approval response

`GET /api/v1/jobs/{id}/videos` returns one row per Document linked to the job. Post-S-1.5.4 (PR [#122](https://github.com/khoks/VideoResearchPro/pull/122)), the response carries:

- `id`, `video_id` (nullable for non-video), `document_id` (UUID, canonical PK)
- `source_type`, `source_id`, `source_url`
- `source_metadata` — parsed JSON dict (per-source-type shape — Reddit: `{subreddit, author, score, commentCount, permalink}`; HN: `{author, points, commentCount, url}`; video: `{channel, durationSec, viewCount}`)
- `classification` — lifted out of `source_metadata` for the frontend's `<ClassificationBadgeRow>` consumer; `{stance, sentiment, framing, topic_relevance}` per [D-007](decisions.md#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25) / [D-014](decisions.md#d-014--add-framing-axis-to-social_classify_stance-schema-2026-04-26) / [D-021](decisions.md#d-021--topic-relevance-threshold--050-2026-04-26)
- The standard YouTube fields (`title`, `channel_name`, `duration_seconds`, `thumbnail_url`, `transcript_status`, etc.) — populated for video rows; nullable on non-video.

The frontend `<ApprovalCard>` polymorphic primitive (PR [#118](https://github.com/khoks/VideoResearchPro/pull/118)) consumes this shape via `videoToApprovalProps()` + `SOURCE_CONFIGS[source_type]`.

### Subscription jobs (no approval)

Subscription jobs ingest *everything* from each subscribed channel's uploads playlist into the global library:

- No `awaiting_approval`.
- No report generation.
- Whisper transcript fallback for videos lacking captions, on the user's own OpenAI key when they brought one, else the install's (T-5.6.13). Podcast audio and Echo recordings follow the same rule, `llm_service.whisper_api_key`.
- Idempotent: re-running a subscription job over the same channel skips already-ingested videos.
- Transitions: `pending → extracting → building_rag → completed`.

### WebSocket progress

A single WebSocket endpoint at `/ws/jobs`. Clients send JSON `{action: "subscribe", job_id: "..."}` and `{action: "unsubscribe", job_id: "..."}` messages. The server-side `ConnectionManager`:

- Maintains a per-client subscription set in memory.
- Maintains a single Redis subscriber that listens on the pattern `job_progress:*`.
- On every progress event, fans the message out to every client subscribed to that job_id.
- Heartbeats every 30 seconds (server pings, client pongs).

The same socket carries the notification bell (T-8.3.3.8). `notification_service.create` publishes `{type, id, kind}` on `notifications:{tenant_id}` after its commit, so it works from the Celery worker; the listener also holds the pattern `notifications:*` and routes each message by its **channel**, never its payload, to the sockets that sent `{action: "subscribe", topic: "notifications"}`. A socket joins only as the user its token names. The event is a doorbell: `useLiveNotifications` (mounted once in `AppLayout`) refetches `GET /notifications`, and the one-minute poll stays as the fallback for a dropped socket or a down Redis. `AuthProvider` closes the socket when the token goes away, on a sign-out in this tab or another, and `wsClient` remembers the token a socket was opened with and replaces the socket when the stored token changes, so a tab never keeps the first identity. The handshake makes the same check as an HTTP request (`auth_service.authenticate_access_token`, T-5.4.15, failing closed), so a revoked token cannot open a socket.

A socket already open ends with its session (T-5.4.19). The manager holds each socket with the session that opened it. Every path that revokes (`revoke_session`, `revoke_all_sessions`, `confirm_password_reset`, `change_password`) calls `auth_service._announce_revoked` after its commit, which publishes the `jti`s on `session_revoked:{tenant_id}`. The listener holds that pattern too, on every API process, and each process closes the sockets it holds on those sessions of that user with code 1008. Like a notification, the message is routed by its channel, so a payload cannot reach another user's sockets. The publish is fail-soft: a revocation never waits on Redis. The net under it is `close_revoked_sessions`, which reads the sessions table once a minute while any socket is open, so with Redis down, or a message lost between two subscriptions, the socket closes within a minute. The web client does not reconnect after a 1008: its token would be refused, and the page's next HTTP call gets a 401 and signs out. A token with no `jti` predates sessions, so nothing can revoke it.

It also ends with its token (T-5.4.21). The manager holds each socket with the token's `exp`, and the same once-a-minute tick closes one past it with 1008 and the reason `Session expired`. That compares a number held in memory, so it needs neither the table nor Redis, and a token with no `jti` expires like any other.

The frontend's `useJobProgress` hook drives React Query cache invalidation off WS messages: a status change to `completed`, `failed` or `cancelled` refetches the run and the jobs lists. The `jobVideos` query follows the run's cached status instead: it is refetched when that status moves to `awaiting_approval`, so the approval list auto-populates without a manual reload, or to an end, whatever moved it (an event, the 5-second poll, the cancel's answer), so an event the hook drops or the socket lost still refreshes the videos. It folds each event into the run's query and into every cached jobs list (`useAllJobsProgress` does the latter for the jobs page). A run the cache holds as ended takes no more events (T-5.2.28): a worker commits a progress write and then publishes it, so a cancel that commits in between is followed by one event that would show the run going again. An ended status reaches the cache only on the server's word (a fetch, the cancel's answer, or an event published after the write that ended the row), so dropping events after it hides nothing, and a refetch still sets the cache either way. A `job_error` refetches the run and the lists as an ending status change does (T-5.2.35). A refetch already in flight when the run ends read the row before the end, so it must not land after it (T-5.2.33): the ending event's own refetch cancels it (React Query's `cancelRefetch`), and the cancel's and the approval's answers cancel it before they are stored, since an answer that arrives before its event leaves the event dropped. `useOutputsProgress` drops events for an output a cached copy holds as `completed`, `failed`, `cancelled` or `skipped`, and an event every copy drops refetches nothing (T-5.2.34).

---

## RAG pipeline

### Chunking

`utils/chunking.py` splits a transcript (a list of segments with `text`, `start`, `duration`) into 256-token chunks with 32-token overlap (`CHUNK_SIZE`, `CHUNK_OVERLAP`). Each chunk preserves a `start_time` and `end_time` derived from the segments it spans. Multilingual scripts are tokenized via the embedder's tokenizer to keep chunk sizes aligned with the embedding context window.

Since 2026-10-19 each chunk also carries its source's two dates as flat scalars — `published_at` (ISO string, legacy) plus numeric `published_ts` / `published_year`, and `era_start` / `era_end` / `era_confidence` / `is_retrospective` from the document's discussed era. **Unknown values are omitted, never written as sentinels**, so a Chroma range filter such as `{"published_ts": {"$gte": ...}}` excludes undated chunks instead of matching them against 1970. Chunks embedded before that date read as unknown until the owner runs `scripts/backfill_chunk_temporal_fields.py --write`, a metadata-only pass with no re-embedding (S-1.17.3, [D-120](decisions.md#d-120--older-chunks-gain-their-era-and-publish-fields-by-a-metadata-only-pass-amends-d-072-the-language-profile-is-stored-on-the-document-2026-11-04), amending D-072).

Also since 2026-10-19, a non-English source's chunks carry its measured language mix
(R5 / [N-002](inventions.md#n-002--proportion-driven-rendering-policy-for-code-mixed-speech-2026-07-31),
[D-080](decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19)). Every chunking path
profiles the whole transcript once (`language_mix_service.ensure`, a free per-word tagger, T-1.16.1.7), stores the profile on
`documents.language_mix` and hands it to `chunk_transcript`, which writes
`code_mix_primary` / `_script` / `_share` / `_matrix_share` / `_quote` / `_named_share` on every chunk, plus per-chunk
`code_mix_chunk_share` / `_chunk_matrix`. Sources under 3% non-English words get none of these fields, so English
chunks are unchanged. Prompts read the fields through `code_mixing_service.source_note` as a `speech: … — quote in …`
fragment on each source header.

### Embedding

`embedding_service.py` wraps a single `SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")` instance. Loaded once per process (FastAPI and Celery each load their own). CPU-only by default; the model is small enough for that to be fine on commodity hardware.

**Non-English chunks are embedded as an English rendering**
([D-084](decisions.md#d-084--code-mixed-retrieval-embed-an-english-rendering-keep-the-original-as-the-stored-text-2026-10-19)).
`chroma_service.insert_chunks`, the one write path every ingest uses, first calls
`code_mixing_service.ensure_english_renderings`. A chunk whose own Hindi share exceeds the borrowing threshold, or
whose grammar is Hindi, gets an English rendering (`code_mixing_render_english`, six chunks per call, once per
document) stored as metadata `text_en`. The vector is computed from that rendering with the collection's own
embedding function; the stored document text stays the original, which is what Q&A shows and quotes. Measured on
132 real chunks with independent English questions: MRR 0.565 for Devanagari originals, 0.402 for the same text
romanised, 0.805 for the rendering. Fail-soft (a failed batch embeds as written), switchable with
`CODE_MIX_ENGLISH_RENDERING_ENABLED`, off for the test suite. There is no backfill.

### ChromaDB

`chroma_service.py` is a singleton client (`PersistentClient(path=...)`). Collection access is via `get_or_create_collection`. The two collections every Q&A surface reads (the private ones are described under Retrieval and in the Echo invariant):

- **`pratidhvani_global`** — chunked transcripts. Metadata per chunk: `{document_id, video_id, source_type, source_id, chunk_index, timestamp_start, timestamp_end, channel_id, language, published_ts, era_*, ...}`. `document_id` ([D-070](decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19)) is the field every scoped query filters on; `video_id` is empty for non-video sources. Chunk ids are `{video_id}:{index}` for YouTube documents and `{document_id}:{index}` for every other source — a storage key for in-place upsert, never read by retrieval. Chunks embedded before 2026-10-19 carry no `document_id`; `chroma_service.backfill_chunk_document_ids` stamps it at API startup and on every Celery worker start, before the worker consumes (metadata-only, no re-embedding, idempotent).
- **`qa_library_global`** — Q&A exchanges, single document each. Metadata: `{exchange_id, surface (job/library/history), job_id (nullable), question_preview, asked_at}`.

Chunk inserts are batched. Failures retry once and then surface as a `building_rag` failure on the job.

### Retrieval

- **Per-job Q&A** filters by `document_id ∈ the job's approved set` (`JobVideo.document_id`, so a job's Reddit / HN / PDF documents are in scope). Top-K = 15 by default (env `RAG_TOP_K`).
- **Library-wide Q&A** filters by `document_id ∈ the tenant's visible set` (D-063, keyed per D-070). Top-K = 15 by default. **An empty set retrieves nothing:** `query_collection(document_ids=[])` returns `[]`; only `None` is unrestricted, and no user-facing caller passes it. A question on a shelf narrows the set to the shelf; a question about one source (`document_id`, T-8.4.2.4) narrows it to that document, and the asker's notes to the ones on it. An invisible or missing document is a 404 before any quota is spent.
- **Trust-weighted re-rank** ([D-068](decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18), S-7.1.1). Both Q&A routers resolve the asker's non-neutral weights with `subscription_service.channel_weights(db, tenant_id)` at request time and pass them to the agent; `qa_agent._scoped_query` then draws 3 × top-K, drops anything over `RAG_DISTANCE_THRESHOLD` on the **raw** distance, sorts by `distance / weight` (weight clamped to 0.05–2.0, 1.0 for chunks with no `channel_id`) and keeps top-K, and the merged context follows the same score. With no weights set it is one top-K query, exactly as before. Weights are per tenant and chunks are shared, so a weight never lives in chunk metadata and is never a filter. Measured on the 200-video reference job: strong weights move promoted channels from about a quarter of the context to more than half and cut the distinct channels per answer by a third, at a small relevance cost on library Q&A ([measurement](notes/2026-10-19-e71-trust-weighting-measurement.md)).
- **Corpus statistics come from SQLite, not from the hits.** Retrieval returns a handful of chunks, which say nothing about the corpus they came from, so `services/corpus_stats_service.py` computes `{video_count, total_words, earliest/latest/median published, videos_by_year, era span}` for the approved (job) or visible (library) document set in the router and passes them, with the length preference, into the Q&A agent. The output-length policy and the temporal note are dead code without them — which is exactly how R4's Q&A half shipped unwired from 2026-07-31 to 2026-10-18 (D-066 amendment, D-072).
- **The asker's own notes** (S-8.5.2) live in a private `notes_global` collection, one vector per live note with `tenant_id` and `target_key` metadata, written on every note write and backfilled at startup. Job Q&A draws notes on the job's own material (the job, its documents and their knowledge reports, its answers, its documents' channels); library Q&A draws every note of the asker, so an empty library can still answer from a note. Notes pass the same raw threshold, then join the D-068 re-rank at `NOTE_RETRIEVAL_WEIGHT` (1.5, measured). They skip the refine step, which compresses and was found dropping them, and reach the answer step verbatim under `[NOTE by you, <date>]` with `NOTE_ANNOTATION_CONTRACT` in the system prompt. A cited note becomes a `note` reference.
- **Q&A history meta-chat** queries `qa_library_global` filtered to the asker's tenant (T-5.6.6), top-K = `RAG_TOP_K`.
- **Knowledge extraction** doesn't use RAG — it works on the document's full text (`document_text_service.full_text`, [D-113](decisions.md#d-113--knowledge-text-for-any-source-the-transcript-cache-else-the-documents-chunks-put-back-together-2026-10-29)), through the knowledge agent's map-reduce.

---

## Agents

Search, Report, Q&A, Knowledge and Echo are LangGraph graphs with a `TypedDict` shared state (`agents/state.py`, or the agent's own file). Q&A History and Visual are plain functions, because their flows are linear.

### Search Agent (`search_agent.py`)

Topic jobs only. Pipeline:

```
resolve_preferred_channels → plan_searches → execute_searches → rank_and_curate
```

- **resolve_preferred_channels** turns the channels named on the job into ids.
- **plan_searches** (`use_case=search_plan_queries`) plans 3-5 YouTube search queries from the user's topic + free-text instructions, and since 2026-10-19 a `temporal_profile` — a deliberate per-topic decision on how time should weigh in ranking (`recency_weight` of `dominant` / `secondary` / `minimal`, an optional `target_era`, a rationale). A run's `published_after_days` (S-8.6.3) never reaches this node: it is added at ranking, as a preference that leads this profile where the two disagree, and the date is worked out then, so a template stays relative.
- **execute_searches** runs each query against YouTube Data API v3 in parallel (asyncio).
- **rank_and_curate** (`use_case=search_rank_and_curate`) deduplicates and ranks the results into the final candidate list — the largest reasoning-mode win in the codebase. The prompt receives the temporal profile, each candidate's publish date and (when the library has already dated it) its discussed era, a `Script:` hint for non-Latin titles, and an English preference. All of these are ranking PREFERENCES; no candidate is ever excluded for its date or language (D-059, D-072).

### Report Agent (`report_agent.py`)

Topic and channel jobs. Pipeline:

```
compute_statistics → map_chunks → reduce_summaries → compose_report
```

- **compute_statistics** runs SQL aggregations (video count, total duration, channel breakdown, date range).
- **map_chunks** (`use_case=report_map_chunks`) processes transcript chunks in batches, extracting per-batch facts. Highest-volume LLM call in the app.
- **reduce_summaries** (`use_case=report_reduce_summaries`) consolidates per-batch summaries into a unified summary.
- **compose_report** (`use_case=report_compose` for topic, `report_channel` + `report_compose_channel_section` for channel jobs) renders the final HTML.
  - **Words are counted once per document** (`compute_statistics`): `chunk_transcript` stamps every chunk with `document_word_count`, the words of the document's full text with `[VISUAL @ ...]` spans removed. Summing the chunks' own `word_count` counted every `CHUNK_OVERLAP` region twice (the 200-video reference job said 1,057,331 words for 947,239) and, on a visual run, the descriptions too. Chunks without the stamp are rebuilt in order without their overlap (`quote_fidelity.merge_chunk_texts`) and counted.
  - **Every section's HTML must be finished** (S-1.14.17). Sections are concatenated, so one that stops inside a tag or attribute folds the next section's headings into it. `utils/html_balance.check` scans each topic-report section, the executive summary and a channel job's narrative (whose end the template's closing tags follow) for an unfinished tag, attribute or comment and for elements left open. A `/` ending an unquoted attribute value belongs to the value, as in the HTML tokenizer, so `<a href=/x/>` counts as an open link. An unfinished answer is composed once more with twice the completion budget (clamped to the model's ceiling). If it is still unfinished, `html_balance.repair` cuts the longer attempt before the unfinished tag, closes what is open, and the processing note names the section as cut off on both attempts. If the retry call fails or comes back empty, the first attempt is closed instead and the note says the section could not be composed again. The note carries `class="processing-note"`, which is how the reading room finds and shows it.

Channel jobs skip `map_chunks`/`reduce_summaries` and go straight to `compose_channel_report`, a stats-only HTML report.

### Q&A Agent (`qa_agent.py`)

Job, library and shelf Q&A. The graph:

```
retrieve_context → refine_context → formulate_answer → extract_references
```

- **Clarify** (`use_case=qa_clarification` / `library_qa_clarification`) is not a node: the `/qa/clarify` routes ask a short follow-up before the question is sent, only when it is too ambiguous, and the answers reach the agent as `context`.
- **retrieve_context** rewrites the question into 2 sub-queries for broader RAG recall (`use_case=qa_sub_query_expansion`), then queries ChromaDB with the original + sub-queries.
- **refine_context** (`use_case=qa_refine_context` / `library_qa_refine_context`) compacts ~45K raw RAG+report context into ~3K focused excerpts before the answer LLM sees it. This is the fix for "no relevant context" failures on large noisy inputs.
- **formulate_answer** (`use_case=qa_formulate_answer` / `library_qa_formulate_answer`) — final user-facing answer, temperature 0, accepts an `answer_language` parameter (default English). Both sites share `_answer_policy`: the completion budget and the brief follow the corpus bracket (D-064) from the router-supplied statistics, with an optional per-request `output_length` (the composers offer it per ask since S-1.15.3); the prompt carries a CORPUS note (publication span, discussed-era span, "say so when sources disagree along a time axis") and allowed-source lines of the form `"Title" by Channel | published <date> | discusses <era>`.
- **extract_references** (`use_case=qa_extract_references`) parses the answer back into structured `(video_id, ts, quote)` so the frontend can render citation chips with `&t=` timestamp links.

Topic jobs use RAG + report. Channel jobs use RAG only. Subscription jobs are queryable only via library-wide Q&A.

### Knowledge Agent (`knowledge_agent.py`)

Per-document extraction, for every source type. Runs inside the request, not on the worker. Pipeline:

```
split_transcript → extract_per_batch → merge_extractions → synthesize_report
```

- **split_transcript** splits the document's full text into token-budgeted batches (env `KNOWLEDGE_EXTRACT_BATCH_TOKENS=8000`), with a 500,000-token sanity ceiling that marks a truncated result; `KNOWLEDGE_MAX_TRANSCRIPT_TOKENS` (default 20,000) is the size of the synthesis prompt's opening excerpt and bounds nothing else. The text comes from `document_text_service.full_text`, keyed on `document_id`: the `transcript_cache` row for a YouTube video, otherwise the document's chunks put back together in order with the overlap removed ([D-113](decisions.md#d-113--knowledge-text-for-any-source-the-transcript-cache-else-the-documents-chunks-put-back-together-2026-10-29)). PDFs, pasted pages, threads and podcast episodes keep their text nowhere else. The prompts name the source by its type (`knowledge_prompts.SOURCE_PROFILES`).
- **extract_per_batch** (`use_case=knowledge_extract_batch`) returns structured `{topics, concepts, events, facts}` JSON per batch.
- **merge_extractions** unions the per-batch outputs and deduplicates by case-insensitive equality.
- **synthesize_report** (`use_case=knowledge_synthesize_report`) renders a Markdown knowledge document. The budget follows the document's size (S-1.14.8). An optional `?output_length=brief|standard|deep` multiplies it by D-064's user multiplier and adds that depth's brief (S-1.15.3); unset or `auto` is exactly 1.0 with no brief, and extraction never changes.

Output written to `Document.extracted_knowledge_json` and `Document.knowledge_report_md`. Triggered by `POST /api/v1/videos/{id}/extract-knowledge`. Returns 409 if already extracted unless `?force=true`.

### Visual Agent (`visual_agent.py`)

Per-document visual understanding (R1, [D-067](decisions.md#d-067--visual-understanding-separate-frames-table-marker-in-text-annotation-opt-in-per-job-2026-07-31)). Pipeline:

```
select_moments → capture_frames → describe_frames → persist
```

- **select_moments** (`use_case=visual_select_moments`, text-only) reads the timestamped transcript and returns `[{timestamp_seconds, reason, expected_content}]` for moments where the picture carries information the words do not — deictic language ("as you can see here"), figures read aloud, demonstrations, slides, screen shares. Zero is a valid answer. Spacing (`VISUAL_MIN_GAP_SECONDS`) and the per-video cap are re-enforced in code afterwards, because the prompt asks and the code guarantees.
- **capture_frames** (`services/frame_service.py`) downloads the video **once** with `worstvideo[height>=360]` and runs `ffmpeg -ss T -frames:v 1` per timestamp against the local file. One download rather than N is the whole design: N downloads is how the transcript pipeline got IP-blocked in [D-051](decisions.md#d-051--transcript-pipeline-resilience-bundle-circuit-breaker--segmented-whisper--yt-dlp-client-fallback-2026-07-22).
- **describe_frames** (`use_case=visual_describe_frame`) is one of the app's two **multimodal call sites** (the other is `echo_share_ocr`). Each still goes to the model together with the speech within ±30s, answering one question: what does the picture add that the words do not? Returns `{informative, description, reads_as, legibility}`; frames the model judges uninformative or unreadable are stored but never merged.
- **persist** writes `visual_frames` rows. A failed commit rolls back explicitly — the session is shared with the extraction loop, and leaving it poisoned would turn one bad persist into a dead job.

Merging happens later and elsewhere: `services/visual_service.annotate_segments` is a pure function producing a NEW segment list, called at chunk time. It never touches `transcript_cache`, which is globally shared across jobs and tenants.

**Annotations are marked in the chunk TEXT**, as `[VISUAL @ mm:ss — …]`, not only in metadata. Chunking splits, merges, overlaps and re-packs segments, and the dominant-segment heuristic promotes exactly one segment's metadata to chunk level — a 12-token annotation beside 240 tokens of speech loses that vote every time. Text physically inside the chunk arrives regardless. Two chunking rules support this: `extra["atomic"]` exempts annotations from sentence-splitting, and visual presence is aggregated across all segments rather than voted on (annotations are excluded from the vote so they cannot steal a social chunk's reply attribution).

The reader-side half is `prompts/shared.py::VISUAL_ANNOTATION_CONTRACT`, injected into every prompt family that reads transcript text. It states that these spans were never spoken, must not be attributed to the speaker, must be cited as "on screen at mm:ss", and lose to the words where the two conflict. **Any new prompt that reads transcript text must include it**, or the model reads machine-written description as something a human said.

**Modality provenance** (S-1.18.8, [D-075](decisions.md#d-075--r1-after-three-runs-the-modality-boundary-needs-provenance-not-prompt-rules-2026-10-19)). Whether a fact was said or shown is decided at the report's map stage, where the model reads one chunk of native-language speech at a time: every extracted item carries `modality` (`said` / `shown` / `both`, or `unknown`), and code forces `said` for any source without a visual annotation. The lossless reduce keeps the label (two extractions of one item with different evidence become `both`), and compose renders it as an `[SAID]` / `[SHOWN]` / `[SAID+SHOWN]` / `[UNLABELLED]` tag the composer attributes from — only when the corpus has a shown item. The labels are in the persisted map records (`job_report_intermediates`), so a report can be checked against item provenance after the run.

**Attribution guard** (S-1.18.9, [D-106](decisions.md#d-106--the-deterministic-attribution-guard-ships-in-the-report-pipeline-r1-stays-hidden-after-run-9-2026-10-24)). `services/attribution_guard.py` checks provenance in code, at two points, against evidence built once from the report's own chunks: each source's speech (spans stripped) and its spans with their timestamps.
- *Map stage* (`label_items`, after the model's labels). A specific detail is a number, an identifier, a quoted string, a visual descriptor pair or a list of names. A detail is screen-only when it is found in a span of the item's own source near its moment and not in the speech around that moment. Screen-only details are named in the compose tag (`[SAID+SHOWN; shown on screen: …]`). An item is never relabelled `shown` or split, because that would say its details went unsaid.
- *Compose* (`guard_report`). A screen-only detail in a part of a sentence credited to a speaker (a speech verb with a speaker before it, a possessive such as "his examples", or a clause ending "— Name (mm:ss)") is marked in place, "(on screen at mm:ss)", with the span's own timestamp. A lone two-digit figure counts only inside a list whose other figures the speaker said around that moment. Quotations, including a quote's transliteration and translation, are never marked. Speech presented as screen is marked as said. An "also visible on screen" with no span of the cited source behind it is removed; one that a span supports is left as written. The sections are guarded before the executive summary reads them, then the summary.

The guard acts only on a detail it finds in a span, so every mark is true by construction. It never claims that a detail went unsaid ([D-108](decisions.md#d-108--the-attribution-guard-never-infers-that-a-detail-went-unsaid-it-checks-only-english-speech-in-latin-script-2026-10-25)): in R1 run 10, every such inference came from speech it could not fully read. It examines only sources whose speech is English in Latin script (`Source.readable`). Devanagari, Bengali and romanised Hinglish sources are left as written, and the processing note says how many were not checked. It never deletes a detail. The guard is fail-soft, counted in `processing_notes` (`map_attribution_guard`, `report_attribution_*`, `report_screen_*`), disclosed in the processing note, and listed in the run's intermediates. The note says what was matched, never "only on screen", because the guard cannot read Devanagari or Bengali speech or a garbled caption. `REPORT_ATTRIBUTION_GUARD_ENABLED` switches it off. It is a no-op when no source has a span. It realizes invention [N-003](inventions.md#n-003--true-by-construction-modality-marks-for-reports-written-from-speech-plus-machine-described-screens-2026-10-24).

Gated by `VISUAL_ENABLED` (install) AND `jobs.visual_analysis` (per job); both must be true. Off by default — it is the largest multimodal spend and the only path that downloads video rather than audio. R1 is parked ([D-109](decisions.md#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25)): the UI hides everything that starts it.

### Echo Agent (`echo_agent.py`)

"Speak as me" (S-3.4.1, [D-102](decisions.md#d-102--speak-as-me-two-switches-guards-in-code-the-reply-in-the-users-language-2026-10-20)). Pipeline:

```
classify_intent → retrieve_relevant_knowledge → retrieve_voice_signals → retrieve_personal_context → draft → self_critique_against_voice → (revise → critique again) → finalize
```

- **classify_intent** (`use_case=echo_classify_intent`) reads the message's intent, topic, language and the people it names. A private name stops the run until the user confirms it.
- **draft** and **revise** (`use_case=echo_draft`) write in the user's voice and the reply's language (not D-066 English), from a trait card, five style-diverse exemplars of the user's own writing and the cited knowledge.
- **self_critique_against_voice** (`use_case=echo_critique`) scores tone, vocabulary, structure and topicality from 1 to 5. It is advisory: the best round is kept. `ECHO_DRAFT_CRITIQUE_ROUNDS` bounds the loop, and `ECHO_DRAFT_CRITIQUE_TARGET` stops it early.
- **finalize** applies the verbatim and citation guards. Like the private-name stop, they live in code, not in the prompt.

Two switches gate it: the install's `ECHO_SPEAK_AS_ME_ENABLED`, and a passed voice test for each user (`echo_voice_gates`). Since T-3.4.1.8 the user takes that test in the app: `echo.generate_voice_test` writes 20 blinded pairs on the worker, about 40 `echo_draft` calls that run only when the user asks for them. `scripts/voice_match_harness.py user-score --record` remains the operator's route. A draft is never sent.

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

Every LLM call site in the codebase is a **named use case** with a default `(provider, model, reasoning)` triple registered in `app/services/llm_routing.py::USE_CASE_REGISTRY`. 36 entries today (full list in [CLAUDE.md](../CLAUDE.md#registered-use-cases)).

`resolve_config(use_case)` returns the effective config after applying, highest first: the caller's per-user override (`user_llm_overrides`, loaded into a ContextVar by `llm_service.byok_context`, E-1.13), `LLM_USE_CASE_CONFIG`, and `LLM_ROUTE_OVERRIDES` (legacy fallback). `get_llm_for(use_case)` returns a configured LangChain client (`ChatOpenAI`, `ChatAnthropic`, `ChatGoogleGenerativeAI`, or local OpenAI-compatible).

### Measured guidance

Each registry entry also carries `guidance`, which records what the E-1.14 measurements found for that use case. Ten entries are `measured` and cite a decision, the gap to the flagship tier and what fails on a downgrade. The other twenty-six are `unmeasured`, with a note on what evidence exists. Each entry can also list per-model verdicts (`unacceptable` / `weaker`), scoped to reasoning levels where needed.

`assess_choice(use_case, cfg)` turns those verdicts, plus the `VISION_CAPABLE_MODELS` check, into warnings. The warnings appear in three places:
- `/health/llm`, for the config this process resolved;
- `/settings/llm`, as the data behind the `/account/ai-models` page;
- the page itself, which re-applies the rule client-side.

Warnings are advisory: no layer refuses a config (see [D-076](decisions.md#d-076--model-guidance-measured-means-the-use-cases-own-output-was-graded-verdicts-warn-never-block-2026-10-19)).

### Reasoning levels

Normalized across providers:

- OpenAI — `reasoning_effort` (off/minimal/low/medium/high)
- Anthropic — `thinking.budget_tokens` (auto → medium)
- Google — `thinkingBudget` (auto → -1)

Unsupported levels degrade gracefully with a warning log; never fatal.

### LLM smoke + fail-soft

`services/llm_smoke.run_startup_probes` runs once from the FastAPI lifespan. It:

1. Resolves the effective `UseCaseConfig` for all 36 use cases.
2. Dedupes by `(provider, model, vision)` — each unique pair probed once. `temporal_scope_extract` is probed but gates no feature: a failure leaves each document's era unknown and the job completes.
3. Fans a trivial one-token probe per unique config out via `asyncio.to_thread` (provider SDKs are synchronous).
4. Stores per-use-case results on a process-global `LLMStatus` singleton.

`GET /api/v1/health` returns `llm.status` (`ok` / `degraded` / `down` / `unknown`) and `unavailable_features` (a list of feature names whose required use cases failed). `GET /api/v1/health/llm` returns full per-use-case detail.

When a probe fails, the **app stays up**. The frontend shows a banner driven by the health response, and pages whose primary action depends on a failed feature disable that action (Ask question, Generate report, Extract knowledge). Non-LLM features stay fully interactive: viewing existing jobs, browsing the library, opening past reports, downloading dataset exports.

The Celery worker does not share this lifespan — task-time LLM failures surface on the Jobs page via the worker's progress publisher.

### Context-window & scale behavior (audited 2026-07-29)

A full call-site audit against a 200-video / 10.6M-token extreme corpus (real reference job 0d4db8c3: 200 videos, 947K words, 5,164 chunks, longest video 4.4 h). Three context strategies coexist, with very different maturity:

**Retrieval-bounded (all Q&A surfaces) — corpus-invariant by design.** Job Q&A, Library Q&A, and Q&A-history never see the corpus, only top-K retrieval: ≤3 queries × `RAG_TOP_K`(15) chunks, deduped, plus the report text hard-capped at 50,000 chars (`REPORT_CONTEXT_CHAR_CAP`, qa_agent.py). Worst-case refine input ≈ 37K tokens regardless of library size. Q&A-history additionally clips stored answers to 1,500 chars at prompt-assembly.

**Batch-bounded (knowledge agent) — per-video, capped, silently lossy.** Transcripts split into `KNOWLEDGE_EXTRACT_BATCH_TOKENS`(8K) batches under a `KNOWLEDGE_MAX_TRANSCRIPT_TOKENS`(60K) cap. The cap is a silent tail-truncation (no log/marker) — a 4.4 h video (~67K tokens) loses its tail. Synthesize re-sends the full (re-truncated) transcript plus the uncapped merged-extraction JSON: ~75K tokens worst-case in one call.

**Budget-batched (report pipeline) — the known scale hazard.** Map batches are sized to `0.6 × LLM_MAX_CONTEXT_TOKENS`, a setting removed on 2026-11-04 (T-4.11.1.4) (= 628K tokens against the global 1,047,576 constant) *regardless of which model the use case resolves to* — no per-model context-window table exists, and `min_context_recommended` in the registry is advisory metadata only. Reduce is single-level (one pairwise halving, no recursion, no final merge); reduce failure passes raw map outputs to compose. Failed map batches are silently dropped (`except → warn → continue`). The channel path truncates each channel at 314K tokens with no logging. `search_rank_and_curate` puts the whole candidate pool (cap `num_videos × 5`) in one prompt: ~130K tokens at target=200, ~300K at target=500. Only 4 of 20 registered call sites set `max_tokens`; no code path recognizes a context-length 400 specifically, and one-token startup probes cannot detect window mismatches.

**Remediated 2026-07-29** by [E-1.12](initiatives.md#e-112--llm-context-window-resilience-at-scale) (PRs #195/#196, [D-052](decisions.md#d-052--measured-context-windows--three-tier-model-stack-e-112-model-re-audit-2026-07-29)): batch budgets now derive from the RESOLVED model's empirically measured window (`llm_routing.MODEL_CONTEXT_WINDOWS` + `context_window_for()`, ×0.5 safety, 120K context-rot quality cap); reduce recurses pairwise to a single summary with token-truncated failure paths; failed map batches bisect-retry once and permanent drops render as a processing-note footer in the report itself; candidate ranking runs a batched tournament above 400 candidates; knowledge extraction batches full transcripts (500K sanity ceiling with a `_processing.truncated` marker) and synthesize sends a 20K grounding excerpt instead of the full transcript; all 20 call sites set `max_tokens`. The job-scope retrieval bug is fixed — the router passes approved video ids and retrieval filters on them (empty-approval jobs never fall back to global search). Mid-tier calls run on `gpt-5.4-mini` with reasoning OFF — on mini, reasoning consumes the visible completion budget (live-validation catch, PR #196).

---

## Auth and tenancy

### Today (self-host; each user is a tenant)

- **Sign-in.** Email + password (`auth_service.py`, bcrypt), and Google or GitHub OAuth 2.0 with PKCE, which links or creates an account only from a provider-verified email ([D-116](decisions.md#d-116--oauth-links-or-creates-an-account-only-from-a-provider-verified-email-and-the-link-records-it-2026-10-29)). `LOCKOUT_FAILURE_THRESHOLD` failed passwords lock an account for `LOCKOUT_DURATION_MIN` minutes.
- **Tokens.** A JWT sent as `Authorization: Bearer <token>` on every HTTP request; no route reads a token from the URL (T-8.8.1.5, T-5.4.23). A browser cannot set a header on the WebSocket handshake, so it offers the token as a subprotocol (`bearer`, then the token), and the handshake makes the same check as an HTTP request (`auth_service.authenticate_access_token`, T-5.4.15, failing closed). Tokens say what they are: an access token has `typ: access`, so the second-factor ticket (`typ: mfa_step`) is not a sign-in token ([D-121](decisions.md#d-121--reset-codes-never-appear-in-a-response-two-step-verification-guards-every-sign-in-and-tokens-say-what-they-are-2026-11-04)).
- **Sessions.** Every access token has a `jti` and a row in `sessions`, so `POST /auth/logout`, `DELETE /auth/sessions/{jti}` and `DELETE /auth/sessions` revoke it on the server. A row is never deleted; `active` on `GET /auth/sessions` says whether it still works. Revoking a session also closes any socket open on it, at once over Redis or within a minute without it (T-5.4.19; see the WebSocket section).
- **Two-step verification.** A TOTP authenticator or recovery codes, on password and OAuth sign-ins alike. The password step returns a five-minute ticket. Each code checked counts against the ticket's `jti` in `mfa_step_tickets`, never against the caller's address; the fifth miss kills it, even for the right code, and a ticket buys one session (T-5.4.13). Turning it off takes a code too, capped at five per user per 15 minutes (T-5.4.16).
- **Passwords.** A reset code goes by email, or to the server log when `SMTP_HOST` is unset, and never into a response. Confirming a reset revokes every session in the same commit (T-5.4.12). `POST /auth/password/change` needs the current password, counts a wrong one toward the lockout, and keeps only the session that asked (T-5.4.14).
- **Encryption at rest.** Stored provider keys, authenticator secrets and connector tokens share one Fernet key, `BYOK_ENCRYPTION_KEY` ([D-043](decisions.md#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05)). Unset, each process generates its own and what it stores is unreadable after a restart. Malformed, or well formed but unable to read a stored authenticator secret because the key changed, the routes that need it answer 503 naming the cause, never the key (T-5.6.9, T-5.6.11); `GET /settings/llm` reports the state ([D-118](decisions.md#d-118--a-provider-key-is-stored-only-for-a-provider-a-call-reads-it-for-the-settings-report-the-encryption-keys-state-never-the-key-2026-11-04)).
- **Your own keys.** Studio users can store their own OpenAI, Anthropic and Google keys and choose per-use-case models, loaded into a ContextVar by `llm_service.byok_context`.
- **Operators.** Only the accounts in `ADMIN_EMAILS`, or with none set the first registered, may switch tiers or restart the install ([D-111](decisions.md#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)).
- **Tenancy.** `get_current_user` loads the user row. Every user-scoped row carries `tenant_id` or `user_id`, today both equal to `User.id`, and a read of someone else's row is a 404, the same as a row that does not exist. `document_visibility` is the grant over the shared documents (D-063).
- **Limits and records.** Per-route and per-tier rate limits (`middleware/rate_limit.py`, E-5.5), per-user quotas (`quota_metering_service`, HTTP 429), the document caps above, and an audit log (`GET /auth/audit-log`).
- **Who is calling.** `app/utils/client_ip.py` is the one reader of `X-Forwarded-For`, used by the per-IP limits, the audit log and the address on a session. The header counts only when the socket peer is a proxy named in `TRUSTED_PROXY_IPS`, and it is read from the right, so what a client wrote changes nothing (T-5.5.8). Unset, the caller is the peer, so an install behind a proxy has to set it: README, "Running behind a reverse proxy". The limits count an IPv6 caller by its /64 (T-5.5.9); everything else keeps the full address.
- **Browser policy.** `middleware/content_security_policy.py` puts a `Content-Security-Policy` on every response. JSON gets `default-src 'none'; frame-ancestors 'none'`, and any other response that no entry names gets that plus `sandbox`, so a new route starts locked. The stored report may keep its inline styles and runs nothing; Swagger's one inline script is allowed by a hash taken from the page as sent. The app's own policy is the host's: README, "Content-Security-Policy for the app".
- **The app's origins.** One list, `app/utils/app_origins.py`: the origin of `APP_BASE_URL` plus each of `OAUTH_ALLOWED_REDIRECT_ORIGINS`, compared by scheme, host and port, with any wildcard refused (T-4.11.3.3). CORS answers a page on it (`middleware/cors.py`), and `GET /auth/oauth/{provider}/start` accepts a `redirect_uri` only on it, before anything is stored (T-4.11.2.4), so a page the API answers is one sign-in can return to. Both read the settings when they run. The Echo connector routes take no redirect: `echo_connector_service.redirect_uri` builds it from `APP_BASE_URL`.

### Future (SaaS)

Per [saas-roadmap.md](saas-roadmap.md):

- A tenant → workspace → user hierarchy, with teams.
- Stripe subscription billing; tier changes are a mock, operator-only flip until then (D-050).
- Per-tenant allocation of the install's YouTube quota, and enforcement of the usage now recorded.

---

## Quotas and observability

### YouTube API

`quota_service.py` records every YouTube Data API call in `api_quota_log` with its cost in units and mirrors the day's total in Redis. `GET /health/quota` reports it against `YOUTUBE_DAILY_QUOTA` (default 10K, the YouTube free quota), and the system status page shows it. The log's `operation` is the kind of call, so the lazy audio-language lookup is `videos_audio_language`, not `videos` (T-1.11.11.5); rows older than that still read `videos`. Nothing refuses a call at that figure: `QuotaExceededError` comes from YouTube's own 403.

### Usage per tenant

Usage is metered per tenant and by feature, at a scope rather than at each call site (E-5.2, [D-119](decisions.md#d-119--usage-is-metered-at-a-scope-that-names-the-tenant-and-written-in-a-session-of-its-own-2026-11-04)). `usage_service.metered(db, tenant_id)` names whose work it is. `llm_service.byok_context` opens one, `get_llm_for` attaches a meter to every client it builds, `quota_service.record` charges each YouTube request to the open scope, and `youtube_service._whisper_transcribe_with_retry` charges each Whisper response's audio seconds as `whisper_seconds` (T-5.2.12). Every hosted Whisper call goes through that one, whichever key pays for it, so a transcription that fails part-way has its billed chunks recorded. The outermost scope writes `usage_records` (per UTC day, feature and metric) and the daily `quota_usage` totals when it closes, through a session of its own, so it never commits or rolls back the caller's. It also writes what it has counted while it is open, at most every `USAGE_FLUSH_INTERVAL_SECONDS` (T-5.2.13), so a worker that dies part-way through a long task loses about that much, not the whole run. `GET /api/v1/usage` returns the caller's own figures, and `GET /auth/quota` reports them against the tier's limits. Nothing is enforced from these numbers (D-111): the per-run Whisper limits (`WHISPER_MAX_PER_JOB`, `WHISPER_MAX_MINUTES_PER_JOB`) count inside the task. Not recorded yet: tokens from local models that do not report them, whose calls count with no tokens.

### Logs

Structured logs via stdlib `logging` with a simple JSON formatter. Celery task logs include `job_id` in every record. Errors caught by FastAPI exception handlers are logged with the request path and user_id.

Credentials stay out by two nets (`app/utils/log_redaction.py`), both set up when `app` is imported. A filter on `uvicorn.error` and `uvicorn.access` redacts a credential query parameter and any JWT from what those loggers are handed, for a client that still sends one (T-5.4.23). A record factory works on every record in every process: a model SDK's refusal of a key, or anything it caused, is named by its type alone, any other text has the shapes of a key taken out, and a traceback is rendered and scrubbed the same way, because a formatter renders it long after a filter on the message has run (T-5.6.16). Neither reaches `print`, or a row or a response that holds an exception's text. A link a user gave us is logged by its host alone, `app/utils/shared_url_log.py` (T-3.7.2.9, T-1.7.1.6).

### Agent-intermediate retention gap (identified 2026-07-29)

Two classes of agent state were **discarded** once a job completed, and their absence blocked retrospective quality auditing. Both are now closed (2026-07-30 and 2026-10-19):

- **Map/reduce intermediates. Closed 2026-10-19 (S-1.14.6, [D-088](decisions.md#d-088--report-intermediates-persisted-per-run-on-by-default-frozen-at-the-stage-that-produced-them-2026-10-19)).** `report_map_chunks` output (per-batch extraction JSON) and the reduced summary used to live only in LangGraph state, so a regression in map quality was invisible unless it degraded the finished report. They are now written to `job_report_intermediates` — one row per map call (bisected halves and failed batches included) plus one reduce row, grouped by `run_id` — through `run_report_agent(..., intermediates_out=)` and `job_tasks._persist_report_intermediates`, behind `REPORT_INTERMEDIATES_ENABLED` (default on). Payloads are serialised when each stage produces them. `backend/scripts/audit_report_intermediates.py` reads a run back.
- **Rejected search candidates. Closed 2026-07-30 (S-1.14.6, PR [#205](https://github.com/khoks/VideoResearchPro/pull/205)).** `search_rank_and_curate` ranks a candidate pool (417 candidates on job `0d4db8c3`) down to the approved set. Previously only the winners were persisted, via `job_documents`. The whole pool is now written to `job_search_candidates` with a `selected` flag (`tasks/job_tasks.py`), so a ranking decision can be replayed against a different model or prompt. Rejected candidates never enter the global `documents` library.

Consequence, established empirically by the [D-055](decisions.md#d-055--intelligence-delta-evaluation-methodology-production-input-replay--blind-ab-judging-2026-07-29) evaluation: intermediate-stage quality can only be measured by *replaying* the original inputs (rebuildable, because transcripts and chunking are deterministic) rather than by inspecting what the run actually produced. Persisting these artifacts — even sampled or behind a debug flag — is the prerequisite for continuous per-use-case quality monitoring, and is tracked as follow-up work under [E-1.14](initiatives.md#e-114--model-tier-quality-evaluation-harness).

---

## Author Studio outputs

An output is one row in `outputs`, generated by the outputter registered for its `kind` (`app/services/outputters/`), in the Celery task `author.generate_output` on the owner's tier queue (S-6.7.1). Progress goes out on `job_progress:{output_id}` like a job's, and a cancel takes effect at the next progress step. Text goes in `content_text` (Markdown), files go under `OUTPUTS_DIR` (`content_path` points at the primary one), every citation the output makes is a row in `output_citations`, and the model calls generation made, with tokens and cost, are in `usage_json`.

| Kind | Sources | Model calls | Files |
|---|---|---|---|
| `book` | the user's runs, one chapter each | none by default; `cohesion=light` / `full` adds `author_book_outline` / `author_book_prose` (opt-in, [D-093](decisions.md#d-093--book-cohesion-pass-ships-opt-in-none-stays-the-default-after-two-blind-rounds-2026-10-19)) | `md` text, `epub` always, `pdf` with a converter |
| `deck` | the user's runs, and `document:<id>` for a document in their library with a knowledge report (S-6.3.2) | `author_deck_outline`, one call | `pptx`, plus `md` text |
| `site` | `shelf:` and `job:` ids | none | `zip`, plus a Markdown contents page |
| `newsletter` | none: a window `(since, until]` over the reader's own library | none by default; `featured` adds `author_newsletter_compose`, one call (opt-in, [D-097](decisions.md#d-097--newsletter-featured-section-ships-opt-in-the-rest-of-an-issue-is-listed-from-the-database-2026-10-19)) | `html` (the email), plus `md` text; an empty window ends `skipped` |

**Newsletter delivery** (S-6.4.2). A reader has at most one `newsletter_subscriptions` row, scheduled as a `scheduled_runs` row of kind `newsletter` (registered by `app/tasks/newsletter_tasks.py`). For each due slot `newsletter_service.deliver`:
1. Claims the period in `newsletter_sends`, unique on `(subscription_id, period_key)`, before anything is made. The key is the slot's ISO week, date or month in the subscription's timezone, so a retried tick finds the claim and does nothing.
2. Re-checks the plan, then makes the issue over `(last_issue_at, now]` through the outputter.
3. Emails a completed issue through `email_service` (HTML with a plain-text part and a `Message-ID` derived from the period), and posts a `newsletter_issue` notification. A skipped issue sends nothing. `last_issue_at` advances either way.

What every outputter keeps true:
- **The model never rewrites source text.**
  - Book chapters are the reports' own Markdown. The cohesion calls see digests and write framing only, which is cleaned of links, footnote markers, headings and HTML before it is spliced in.
  - A deck's model sees each report with its citations as source markers, and only resolvable sources get a marker.
  - A slide that cites nothing is dropped, and the deck says how many were.
- **Every citation resolves or says it did not.**
  - Citations are matched to the run's documents the user can see (D-063) by `output_citation_service`.
  - An unresolved one keeps its label, loses its link, and is disclosed.
- **Framing and planning are disclosed.** A framed book's front matter and a deck's title slide name the models that wrote them.
- **Nothing reaches the network while rendering.**
  - The Markdown parser has raw HTML off, and images become their alt text.
  - The PDF engines refuse every fetch.
  - A site's search index is a script, so the zip works from `file://`, and its only absolute links go to sources.

## Dataset exports

Six export routes (`routers/exports.py`), all read with the Authorization header, never a token in the URL (T-8.8.1.5). The four fine-tune datasets stream JSONL:

- `/api/v1/exports/qa-dataset/openai.jsonl` — Q&A as OpenAI chat-format records.
- `/api/v1/exports/qa-dataset/tuple.jsonl` — Q&A as plain `(system, user, assistant)` tuples.
- `/api/v1/exports/knowledge-dataset/openai.jsonl` — knowledge artifacts in chat format.
- `/api/v1/exports/knowledge-dataset/tuple.jsonl` — knowledge artifacts in tuple format.

`/api/v1/exports/notes.jsonl` and `/api/v1/exports/notes.md` are the user's notes, not training data.

`StreamingResponse` over a SQL iterator. Memory stays constant for arbitrarily large exports. System prompts are baked into `services/dataset_service.py` as module constants. The Q&A dataset unions `qa_exchanges` + `library_qa_exchanges` + `qa_history_exchanges` ordered by `created_at`. Both datasets are the caller's only: Q&A rows filter on `tenant_id`, and the knowledge dataset exports the documents in `visibility_service.visible_document_ids` that carry a knowledge report (S-5.10.5, keyed on `document_id` per D-070), the same set the library lists. It used to derive ownership from the caller's jobs joined on the legacy `video_id`, which dropped documents with no job, documents whose job was deleted, and every non-video document. It also broke on its first record until then: it loaded `Document` entities through `execution_options(yield_per=...)`, the legacy `Query` uniquifies entity rows unless `Query.yield_per()` set its load option, and SQLAlchemy refuses `yield_per` with `unique()`. It now selects the three columns it needs, with `Query.yield_per()`.

---

## Multilingual posture

- **Whisper** is invoked with `task="transcribe"` (not `translate`) so mixed-language audio (e.g. Hindi-English code-mixed) is preserved faithfully.
- The **embedding model** is multilingual (`paraphrase-multilingual-MiniLM-L12-v2`), so a Hindi transcript and an English question land in similar vector space — passably for Devanagari, badly for romanised Hindi. Non-English chunks are therefore embedded as an English rendering (see [Embedding](#embedding), D-084).
- **Code-mixed speech** ([N-002](inventions.md#n-002--proportion-driven-rendering-policy-for-code-mixed-speech-2026-07-31), S-1.16.2). `language_service` profiles scripts exactly and is blind to Hindi in Latin letters by design. `code_mixing_service` answers the other question, which language each word is in, and runs on Latin and Devanagari alike. It knows English and Hindi only: Latin text with no Hindi evidence is abstained on (`primary_language: other`, still non-English for every share and rendering decision), and English written in Devanagari comes from an offline lexicon. It works in four steps: a lexicon + character n-gram + Viterbi tagger; a matrix-language vote over system morphemes, which tells "Hindi grammar with English nouns" from "English with a Hindi clause"; a proportion-to-quote-form policy (`CODE_MIX_DOMINANT_SHARE` 0.6, `CODE_MIX_BORROWING_MAX_SHARE` 0.2); and one primary language per source, so a report never switches script for one speaker. The analysis path reads English (every prompt carries the English contract and the source's `speech:` note). Quotation keeps the original: report map items may carry `original` beside English `content`, and compose attaches the source's `quote_form`. Every kept `original` is verified in code before anything is composed: `app/services/quote_fidelity.py` (the same rule the R1 quote-fidelity audit uses) drops wording that is not verbatim or 80%-aligned with its own source's speech, mixes two scripts in one word, or is in a script other than the source's; the drop is disclosed in the report's processing note. After composing, the same rule checks the report itself (`quote_fidelity.scrub_report`): a native-script passage found in no source's speech (titles and channel names admitted) is removed with its transliteration, its English kept, and the removal counted in `processing_notes.report_quotes_removed` and disclosed. A source typed in Latin letters is quoted in Latin letters. Method and measurements: [the detection note](notes/2026-10-19-code-mixing-detection.md).
- **Caption tracks** (S-1.11.11, [D-117](decisions.md#d-117--the-caption-track-is-the-one-in-the-spoken-language-auto-dubs-are-read-from-the-players-audio-tracks-2026-10-29)). The fetch takes the track in the language the video is spoken in. Auto-dubs, which YouTube lists beside the original's captions, are recognised from the player's audio tracks and skipped, a creator's manual track beats the automatic one, and English-first is only the fallback when nothing says what language is spoken. A video whose every track is a dub goes to Whisper. The chosen track, and why, is recorded on the document. `scripts/refetch_dubbed_transcripts.py` finds transcripts that came from a dub before this.
- The **Q&A agent** accepts an `answer_language` parameter and is instructed to translate quoted non-English context into the target language while preserving proper nouns in their original script.
- **Visual annotations are always written in English**, whatever the spoken language, because they are our text rather than the speaker's. `visual_service.strip_annotations` exists so that speech-only surfaces — dataset exports, word counts, and the language profiler — measure the source and not our own commentary.

---

## Forward-looking notes

These sections describe the trajectory, not the current code:

- **Multi-source ingest** — the `videos` → `documents` table rename landed in L1 PR 4; the `SourceConnector` interface contract (PR 2/3) routes every YouTube call site through `connector_for("video")`. The Reddit (S-1.5.1) and HN (S-1.5.2) standalone connectors followed; **E-1.10 UUID PK promotion shipped 2026-05-02** ([PR #112](https://github.com/khoks/VideoResearchPro/pull/112)) collapsing storage tasks to trivial inserts. Reddit, Hacker News, Mastodon, Bluesky, podcasts, web articles and X now run end to end, and a topic run chooses among them (S-1.5.13). Full trajectory in [source-types.md](source-types.md). L1 in the [feature-roadmap](feature-roadmap.md).
- **Personal Brain** — activity stream connectors, voice capture and the "speak as me" agent have shipped behind their gates; what remains is in [personal-brain.md](personal-brain.md). Multi-quarter trajectory.
- **SaaS** — tenancy, billing, abuse prevention, hosting are detailed in [saas-roadmap.md](saas-roadmap.md).
- **Author Studio** — derivative artifact generation (books, sites, decks, newsletters, reels) is L2 in the [feature-roadmap](feature-roadmap.md). Books, decks, sites and the newsletter ship (see [Author Studio outputs](#author-studio-outputs)); reels remain.
- **Curated source ranking** — the per-tenant trust weight shipped (S-7.1.1); disagreement detection and side-by-side narratives remain in L4.

---

## Cross-references

- API endpoints — [api-reference.md](api-reference.md)
- Frontend pages — [ui-pages.md](ui-pages.md)
- UI design tokens & visual system — [ui-design.md](ui-design.md), [branding.md](branding.md)
- Functional & non-functional requirements — [requirements.md](requirements.md)
- Vision — [vision.md](vision.md)
- Roadmap — [feature-roadmap.md](feature-roadmap.md)
- LLM use case registry — [CLAUDE.md](../CLAUDE.md#llm-configuration) and `backend/app/services/llm_routing.py::USE_CASE_REGISTRY`
- Testing — [testing.md](testing.md)
- Contributing — [contributing.md](contributing.md)
