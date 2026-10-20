# Pratidhvani — System Architecture

**Status:** current as of 2026-04-24; sections amended through 2026-10-19 (latest: Author Studio outputs, D-093). Brand-name forward; the codebase still ships under `videoresearchpro` package paths and Chroma collection names — see [feature-roadmap.md](feature-roadmap.md) §Rebrand-asset-rollout for the rename plan.

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

Four processes run side-by-side in development: the FastAPI app (`uvicorn`), the Celery worker (`celery -A app.tasks.celery_app worker --pool=solo`), exactly one Celery beat (`celery -A app.tasks.celery_app beat`, the scheduler tick added by S-8.3.1), and Redis (Windows service via winget). SQLite and ChromaDB are file-backed under `data/`. The frontend is a separate Vite dev server that proxies API calls to the backend.

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
  - Ensures the search index (S-8.2.1, [D-078](decisions.md#d-078--search-index-one-trigram-fts5-table-per-entity-copies-not-external-content-like-fallback-2026-10-19)): `services/search_service.ensure_index_for_url` probes SQLite for FTS5 with the trigram tokenizer, creates any missing `fts_*` virtual tables and their `AFTER INSERT / UPDATE / DELETE` triggers, rebuilds the ones just created from their base tables, and records the backend (`fts5` or `like`) that `GET /health` reports as `search_backend`. Migration `a9f3c1e7b5d2` does the same conditionally, so a fresh install is indexed before the first request; the lifespan re-probe is what picks up a Python upgrade that gains FTS5 later. Never blocks startup. The worker needs nothing: the triggers live in the database, so ingest writes from any process are indexed.
- On shutdown: flushes any pending Chroma writes, closes the embedding model, releases Redis connections.
- Does **not** run Celery tasks itself. It only `.delay()`-dispatches them.

### Celery worker (`celery -A app.tasks.celery_app worker --pool=solo`)

- Runs all long-running orchestration: search, transcript fetch, embedding, report generation, knowledge extraction, and Author Studio generation (`author.generate_output`, S-6.7.1). A book's EPUB is built in-process; its PDF is printed by WeasyPrint or headless Chromium, both optional installs probed once per process (`AUTHOR_PDF_ENGINE`, S-6.1.5) and both cut off from the network.
- Has its own SQLAlchemy session factory (created per task) so request-side and worker-side don't share connections.
- Publishes progress events to Redis pub/sub (`job_progress:{job_id}`) at every phase boundary. Author outputs publish on the same channel under the output's id; `routers/ws.py` lets a socket subscribe to any job or output its user owns. Output cancellation is cooperative: `output_service.report_progress` raises once the row is `cancelled`, because `revoke(terminate=True)` cannot stop a task on the solo pool.
- On Windows, **must use `--pool=solo`** because the multiprocessing prefork pool doesn't work cleanly with our embedding model + ChromaDB locks.
- Does **not** run the LLM smoke check. Task-time LLM failures surface on the Jobs page via the worker's progress publisher.
- A backfill runs once per worker startup that idempotently upserts every existing row from `qa_exchanges`, `library_qa_exchanges`, and `qa_history_exchanges` into the `qa_library_global` Chroma collection.

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

- **db0** — Pub/sub channel for progress events (`job_progress:{job_id}`).
- **db1** — Celery broker (queue of pending tasks).
- **db2** — Celery result backend (task return values).

### SQLite

`data/videoresearchpro.db` (env `DATABASE_URL`). Author Studio's binary artifacts sit beside it under `data/outputs/<user_id>/<output_id>/artifact.<format>` (env `OUTPUTS_DIR`, S-6.7.2); `outputs.content_path` is stored relative to that root, deleting an output removes its directory, and `scripts/sweep_output_artifacts.py` finds directories left without a row. All structured state: users, jobs, documents (formerly `videos`; renamed in L1 PR 4), channels, transcript cache, Q&A exchanges, knowledge artifact metadata, scheduled runs. Alembic migrations under `backend/alembic/`. Beside the ORM tables sit the S-8.2.1 search index's FTS5 virtual tables (`fts_documents`, `fts_jobs`, `fts_channels`, `fts_qa`, `fts_knowledge`, plus SQLite's `fts_*_data` / `_idx` / `_content` / `_docsize` / `_config` shadow tables): one trigram-tokenised table per entity, each row carrying the entity id as an `UNINDEXED` column and a copy of the indexed text, kept current by triggers. They have no ORM model and `schema_init_service` ignores the `fts_` prefix when comparing the live schema to the ORM. External-content mode was rejected because it maps on rowid and every base table has a string primary key, whose rowids are not stable across `VACUUM`.

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
│   │   ├── channel.py           # Channels (shared facts; per-tenant state in channel_subscription.py)
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
│   │   ├── visual_agent.py      # select moments → capture stills → describe → persist
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
       ├──< QAHistoryExchange
       ├──< Note ──> (document | knowledge_artifact | job | qa_exchange |
       │              library_qa_exchange | qa_history_exchange | channel)
       ├──< PersonalContext                                 (Echo facts, per tenant)
       ├──< Share ──> file under ECHO_SHARES_DIR/<tenant>/  (Echo shares inbox, per tenant)
       ├──< Shelf ──< ShelfJob >── Job                      (M1, per tenant)
       ├──< Tag ──< Tagging ──> Document                    (M1, per tenant)
       └──< JobTemplate ──< JobTemplateVersion              (M6; tenant NULL = built-in)
                 ▲
                 └── Job.template_id + template_version (provenance, no FK)

Document ──< KnowledgeArtifact (columns on Document, not a separate table)
Document ──  DiscussedEra (column `discussed_era_json` on Document — R3, see below)
Document ──< TranscriptCache (1:1 by document_id; FK ON DELETE CASCADE)
Document ──< VisualFrame (0:N by (document, timestamp); FK ON DELETE CASCADE)

ApiQuotaLog (append-only ledger of YouTube + LLM calls)
```

> **Schema state (post-E-1.10, 2026-05-02).** The primary key on `documents` is now `document_id` (UUID4, str(36)). The legacy `video_id` column survives as a NULLABLE back-compat reading column populated for `source_type='video'` rows (NULL for Reddit / HN / other source types). The join table is renamed to `job_documents` (Python class still `JobVideo` for import back-compat) with composite PK `(job_id, document_id)`. `transcript_cache` PK is also now `document_id` with FK to `documents.document_id`. See [D-017](decisions.md#d-017--e-110-hard-cutover-single-migration-uuid-pk-promotion-2026-04-26) for the cutover rationale and [PR #112](https://github.com/khoks/VideoResearchPro/pull/112) for the migration.

> **Two dates per source (R3, 2026-10-19).** `documents.published_at` is when a source was POSTED; `documents.discussed_era_json` is the period it is ABOUT — `{era_start, era_end, era_confidence, is_retrospective, era_label}`, integer years (negative = BCE), extracted once per document by the `temporal_scope_extract` use case the first time any job chunks it (`job_tasks._ensure_era`, fail-soft, failures not persisted), then reused by every later job like transcripts and embeddings. NULL means not yet extracted; null years mean undatable. Both read as UNKNOWN downstream, never as "discusses now". See [D-072](decisions.md#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19).

### Key invariants

- **Documents are global.** One row per source. Canonical identity is `(source_type, source_id)` (unique-indexed); the PK is the synthetic `document_id` UUID. Today's source types: `video` (YouTube), `reddit_post`, `hn_story`. The library is a single, deduplicated, shared corpus. `JobVideo` rows in `job_documents` tie a job to its documents. Deleting a job drops `JobVideo` rows; documents and chunks survive.
- **Channels are first-class.** Subscribing a channel pre-pulls every video on its uploads playlist into the global library via subscription jobs.
- **Transcripts are cached once.** Re-fetch is suppressed by `transcript_cache.document_id` lookup. Legacy `transcript_cache.video_id` column survives as nullable back-compat for video rows.
- **Embeddings happen exactly once per document.** `Document.embedded_in_chroma` flips to `true` after chunks land in `videoresearchpro_global`. Subsequent jobs referencing that document skip embedding.
- **Q&A exchanges have three flavors** that union into one Chroma collection:
  - `qa_exchanges` (job-scoped)
  - `library_qa_exchanges` (library-scoped; `scope_json` narrows a question to a shelf, documents and the asker's notes alike, or records that a saved search asked it, null = the whole visible library and every note: [D-095](decisions.md#d-095--scoped-library-questions-one-history-table-with-a-scope_json-object-narrowing-and-provenance-keys-unknown-keys-refused-2026-10-19))
  - `qa_history_exchanges` (meta-chat surface)

  All three are stored separately for SQL-level filtering but indexed together in `qa_library_global` so meta-chat retrieval crosses surfaces.
- **Echo's data is a registered set of stores, per tenant** (I-3). `personal_context` (facts), `shares_inbox` (everything the user forwards; files under `ECHO_SHARES_DIR/<tenant>/`), `activity_events` (what the user did, from connectors and the `internal` share event; unique per tenant, connector and external id) and `echo_connector_grants` are listed in `echo_privacy_service.ECHO_TABLES`; connector tokens (`echo_connector_credentials`, Fernet) and in-flight OAuth state (`echo_connector_oauth_states`) are in `ECHO_SECRET_TABLES`, erased with the rest but never exported ([D-097](decisions.md#d-097--echo-connectors-events-unique-per-reader-tokens-in-a-secret-store-that-is-erased-with-the-brain-but-never-exported-2026-10-19)). Connectors and archive importers implement `app/connectors/base.py` and register in `app/connectors/registry.py`; and Echo's Chroma collections (`shares_global`, `personal_context_global`) in `echo_vectors.echo_collection_names()`. `GET /echo/export` writes all of it into one lossless archive; `DELETE /echo/brain` removes vectors, then files, then rows, and re-counts every store. A share is context-only unless the user marks it as their own words. See [D-089](decisions.md#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19).
- **Notes are the user's own text, private per tenant** (M5). `notes(id, tenant_id, target_type, target_id, selector_json, body_md, motivation, created_at, updated_at, deleted_at)`. The target set is closed; the target is checked through visibility or ownership on every write; a document note is stored under `document_id`, so one document has one note stream. Delete is soft, and the JSON-LD export carries withdrawals losslessly. Notes are not in Chroma until S-8.5.2. See [D-074](decisions.md#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19).
- **Shelves, tags and templates are per tenant** (M1, M6). `shelves` + `shelf_jobs` group runs (a run on many shelves; deleting either side removes only memberships, through ORM cascades because SQLite here never enforces FK cascades). `tags` + `taggings` label documents per reader, even on shared documents; every count and filter re-applies visibility. `job_templates` + immutable `job_template_versions` hold reusable recipes; runs record `(template_id, template_version)` and templates are soft-deleted so that provenance survives. See [D-082](decisions.md#d-082--job-templates-identity-plus-immutable-versions-provenance-without-a-foreign-key-starters-in-a-self-contained-data-migration-2026-10-19) and [D-083](decisions.md#d-083--organisation-features-access-and-scope-defaults-on-the-plans-open-questions-2026-10-19).
- **Derived views are computed on read, per tenant** (M7, M9). `channel_intelligence_cache(channel_id, tenant_id, fingerprint, computed_at, payload_json)` caches a channel's aggregates for one reader and recomputes when the fingerprint of its inputs (visible document set, knowledge times, transcripts, payload version) changes. The library graph (`services/graph_service.py`) has no table: nodes and edges are built per request from the reader's visible documents, about 0.07 s at 2,000 documents. Both start from `visibility_service.visible_document_ids`, so an empty visible set is an empty result. See [D-091](decisions.md#d-091--channel-intelligence-aggregates-computed-on-read-and-cached-per-reader-behind-an-input-fingerprint-derived-links-resolved-at-read-time-2026-10-19) and [D-092](decisions.md#d-092--library-graph-computed-per-request-sigma-used-directly-as-a-lazy-chunk-three-group-colours-the-accessibility-layer-inside-the-story-2026-10-19).
- **Knowledge artifacts live on the Document row.** Three nullable columns (`extracted_knowledge_json`, `knowledge_report_md`, `knowledge_extracted_at`). One artifact per document.
- **Jobs carry a status enum**: `pending → searching → awaiting_approval → extracting → building_rag → generating_report → completed`. Terminal: `completed`, `failed`, `cancelled`. Subscription jobs skip `awaiting_approval` and `generating_report`.

### Forward-compat columns (already present or planned next sprint)

Per [saas-roadmap.md](saas-roadmap.md) and [source-types.md](source-types.md):

- Every user-scoped table has — or will have, in the imminent migration — a `tenant_id` column. The single self-host instance has a single tenant.
- The `documents` table carries `source_type`, `source_id`, `source_url`, `source_metadata_json`, `language`, `word_count`, `user_provenance_json` (from L1 PR 1) plus `document_id` UUID PK (from E-1.10, PR #112). The legacy `video_id` column persists as nullable back-compat and is NULL for every non-video source — never key anything on it. The future `creator_id` foreign key for cross-source-type creators is the next planned column (E-1.9).
- **Document visibility.** `document_visibility(document_id, tenant_id, source)` is the per-tenant grant over the shared cache ([D-063](decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)), re-keyed on the primary key by [D-070](decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19) after the original `video_id` key silently dropped every PDF and pasted page. Every ingest path calls `visibility_service.grant(db, document_ids, tenant_id, source)`, including on dedup hits; every user-facing read of `documents` filters through `visibility_service.visible_document_ids(db, tenant_id)`; library Q&A hands the same set to Chroma.
- The `channels` table grows into `creators` with `source_type`, `source_weight` (E-1.9). `source_type`, `creator_external_id`, and `source_weight` are already present from L1 PR 1. Per-user state, including `source_weight`, moved to `channel_subscriptions` in [D-065](decisions.md#d-065--channel-subscriptions-become-per-tenant-transliteration-reversed-2026-07-31). **Nothing reads `source_weight` yet** (verified 2026-10-18), so retrieval is unweighted: every approved source counts equally until [L4](feature-roadmap.md#l4--curated-source-ranking-) lands.
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
- **Everything else (`"reddit_post"`, `"hn_story"`, future `"mastodon"` / `"bluesky"`)** → `app/services/connector_dispatch.py::dispatch_search()`, which iterates each non-video source_type **sequentially** (per [D-026](decisions.md#d-026--sequential-fan-out-for-the-connector-dispatcher-2026-05-02)) through `connector_for(source_type).search(query, instructions, limit)`. For each Candidate, the connector's own `fetch_text(query=...)` is called (which inline-classifies per [D-023](decisions.md#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28)); persistence is uniform across source types via `_upsert_candidate_and_link()`.

Both paths converge into the same `awaiting_approval` flow. The combined candidate count drives the user-visible "Found N candidates" message; an empty result across all sources fails the job with a clear "No candidates for source_types=[...]" error rather than dropping the user onto an empty approval list.

Per-source-type errors (connector raised, missing connector, NotImplementedError for PDF-style sources) are captured per source in `DispatchResult.errors_by_source_type` and logged; they don't fail the job — other source types' candidates still flow through.

> **Unreachable from the API (found 2026-10-19).** `JobCreate` has no `source_types` field and nothing writes `jobs.source_types_json`, so every topic run created through `POST /jobs` takes the `["video"]` default and the non-video branch above never runs. The worker side is intact; the missing link is the request schema, persistence, response and a submit-form picker. Found while building job templates ([D-082](decisions.md#d-082--job-templates-identity-plus-immutable-versions-provenance-without-a-foreign-key-starters-in-a-self-contained-data-migration-2026-10-19)).

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
- `classification` — lifted out of `source_metadata` for the frontend's `<ClassificationBadgeRow>` consumer; `{stance, sentiment, framing, topic_relevance}` per [D-007](decisions.md#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25) / [D-014](decisions.md#d-014--add-framing-axis-to-social_classify_stance-schema-2026-04-26) / [D-021](decisions.md#d-021--topic-relevance-threshold--050-2026-04-26)
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

Since 2026-10-19 each chunk also carries its source's two dates as flat scalars — `published_at` (ISO string, legacy) plus numeric `published_ts` / `published_year`, and `era_start` / `era_end` / `era_confidence` / `is_retrospective` from the document's discussed era. **Unknown values are omitted, never written as sentinels**, so a Chroma range filter such as `{"published_ts": {"$gte": ...}}` excludes undated chunks instead of matching them against 1970. Chunks embedded before that date carry none of these and read as unknown; there is no backfill (D-072).

Also since 2026-10-19, a non-English source's chunks carry its measured language mix
(R5 / [N-002](inventions.md#n-002--proportion-driven-rendering-policy-for-code-mixed-speech-2026-07-31),
[D-080](decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19)). `chunk_transcript`
profiles the whole transcript once (`code_mixing_service.profile_transcript`, a free per-word tagger) and writes
`code_mix_primary` / `_script` / `_share` / `_matrix_share` / `_quote` on every chunk, plus per-chunk
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

`chroma_service.py` is a singleton client (`PersistentClient(path=...)`). Collection access is via `get_or_create_collection`. Two collections in active use:

- **`videoresearchpro_global`** — chunked transcripts. Metadata per chunk: `{document_id, video_id, source_type, source_id, chunk_index, timestamp_start, timestamp_end, channel_id, language, published_ts, era_*, ...}`. `document_id` ([D-070](decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19)) is the field every scoped query filters on; `video_id` is empty for non-video sources. Chunk ids are `{video_id}:{index}` for YouTube documents and `{document_id}:{index}` for every other source — a storage key for in-place upsert, never read by retrieval. Chunks embedded before 2026-10-19 carry no `document_id`; `chroma_service.backfill_chunk_document_ids` stamps it at API startup (metadata-only, no re-embedding, idempotent).
- **`qa_library_global`** — Q&A exchanges, single document each. Metadata: `{exchange_id, surface (job/library/history), job_id (nullable), question_preview, asked_at}`.

Chunk inserts are batched. Failures retry once and then surface as a `building_rag` failure on the job.

### Retrieval

- **Per-job Q&A** filters by `document_id ∈ the job's approved set` (`JobVideo.document_id`, so a job's Reddit / HN / PDF documents are in scope). Top-K = 15 by default (env `RAG_TOP_K`).
- **Library-wide Q&A** filters by `document_id ∈ the tenant's visible set` (D-063, keyed per D-070). Top-K = 15 by default. **An empty set retrieves nothing:** `query_collection(document_ids=[])` returns `[]`; only `None` is unrestricted, and no user-facing caller passes it.
- **Trust-weighted re-rank** ([D-068](decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18), S-7.1.1). Both Q&A routers resolve the asker's non-neutral weights with `subscription_service.channel_weights(db, tenant_id)` at request time and pass them to the agent; `qa_agent._scoped_query` then draws 3 × top-K, drops anything over `RAG_DISTANCE_THRESHOLD` on the **raw** distance, sorts by `distance / weight` (weight clamped to 0.05–2.0, 1.0 for chunks with no `channel_id`) and keeps top-K, and the merged context follows the same score. With no weights set it is one top-K query, exactly as before. Weights are per tenant and chunks are shared, so a weight never lives in chunk metadata and is never a filter. Measured on the 200-video reference job: strong weights move promoted channels from about a quarter of the context to more than half and cut the distinct channels per answer by a third, at a small relevance cost on library Q&A ([measurement](notes/2026-10-19-e71-trust-weighting-measurement.md)).
- **Corpus statistics come from SQLite, not from the hits.** Retrieval returns a handful of chunks, which say nothing about the corpus they came from, so `services/corpus_stats_service.py` computes `{video_count, total_words, earliest/latest/median published, videos_by_year, era span}` for the approved (job) or visible (library) document set in the router and passes them, with the length preference, into the Q&A agent. The output-length policy and the temporal note are dead code without them — which is exactly how R4's Q&A half shipped unwired from 2026-07-31 to 2026-10-18 (D-066 amendment, D-072).
- **The asker's own notes** (S-8.5.2) live in a private `notes_global` collection, one vector per live note with `tenant_id` and `target_key` metadata, written on every note write and backfilled at startup. Job Q&A draws notes on the job's own material (the job, its documents and their knowledge reports, its answers, its documents' channels); library Q&A draws every note of the asker, so an empty library can still answer from a note. Notes pass the same raw threshold, then join the D-068 re-rank at `NOTE_RETRIEVAL_WEIGHT` (1.5, measured). They skip the refine step, which compresses and was found dropping them, and reach the answer step verbatim under `[NOTE by you, <date>]` with `NOTE_ANNOTATION_CONTRACT` in the system prompt. A cited note becomes a `note` reference.
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

- **generate_search_queries** (`use_case=search_plan_queries`) plans 3-5 YouTube search queries from the user's topic + free-text instructions, and since 2026-10-19 a `temporal_profile` — a deliberate per-topic decision on how time should weigh in ranking (`recency_weight` of `dominant` / `secondary` / `minimal`, an optional `target_era`, a rationale).
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
- **formulate_answer** (`use_case=qa_formulate_answer` / `library_qa_formulate_answer`) — final user-facing answer, temperature 0, accepts an `answer_language` parameter (default English). Both sites share `_answer_policy`: the completion budget and the brief follow the corpus bracket (D-064) from the router-supplied statistics, with an optional per-request `output_length`; the prompt carries a CORPUS note (publication span, discussed-era span, "say so when sources disagree along a time axis") and allowed-source lines of the form `"Title" by Channel | published <date> | discusses <era>`.
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

### Visual Agent (`visual_agent.py`)

Per-document visual understanding (R1, [D-067](decisions.md#d-067--visual-understanding-separate-frames-table-marker-in-text-annotation-opt-in-per-job-2026-07-31)). Pipeline:

```
select_moments → capture_frames → describe_frames → persist
```

- **select_moments** (`use_case=visual_select_moments`, text-only) reads the timestamped transcript and returns `[{timestamp_seconds, reason, expected_content}]` for moments where the picture carries information the words do not — deictic language ("as you can see here"), figures read aloud, demonstrations, slides, screen shares. Zero is a valid answer. Spacing (`VISUAL_MIN_GAP_SECONDS`) and the per-video cap are re-enforced in code afterwards, because the prompt asks and the code guarantees.
- **capture_frames** (`services/frame_service.py`) downloads the video **once** with `worstvideo[height>=360]` and runs `ffmpeg -ss T -frames:v 1` per timestamp against the local file. One download rather than N is the whole design: N downloads is how the transcript pipeline got IP-blocked in [D-051](decisions.md#d-051--transcript-pipeline-resilience-bundle-circuit-breaker--segmented-whisper--yt-dlp-client-fallback-2026-07-22).
- **describe_frames** (`use_case=visual_describe_frame`) is the app's **only multimodal call site**. Each still goes to the model together with the speech within ±30s, answering one question: what does the picture add that the words do not? Returns `{informative, description, reads_as, legibility}`; frames the model judges uninformative or unreadable are stored but never merged.
- **persist** writes `visual_frames` rows. A failed commit rolls back explicitly — the session is shared with the extraction loop, and leaving it poisoned would turn one bad persist into a dead job.

Merging happens later and elsewhere: `services/visual_service.annotate_segments` is a pure function producing a NEW segment list, called at chunk time. It never touches `transcript_cache`, which is globally shared across jobs and tenants.

**Annotations are marked in the chunk TEXT**, as `[VISUAL @ mm:ss — …]`, not only in metadata. Chunking splits, merges, overlaps and re-packs segments, and the dominant-segment heuristic promotes exactly one segment's metadata to chunk level — a 12-token annotation beside 240 tokens of speech loses that vote every time. Text physically inside the chunk arrives regardless. Two chunking rules support this: `extra["atomic"]` exempts annotations from sentence-splitting, and visual presence is aggregated across all segments rather than voted on (annotations are excluded from the vote so they cannot steal a social chunk's reply attribution).

The reader-side half is `prompts/shared.py::VISUAL_ANNOTATION_CONTRACT`, injected into every prompt family that reads transcript text. It states that these spans were never spoken, must not be attributed to the speaker, must be cited as "on screen at mm:ss", and lose to the words where the two conflict. **Any new prompt that reads transcript text must include it**, or the model reads machine-written description as something a human said.

**Modality provenance** (S-1.18.8, [D-075](decisions.md#d-075--r1-after-three-runs-the-modality-boundary-needs-provenance-not-prompt-rules-2026-10-19)). Whether a fact was said or shown is decided at the report's map stage, where the model reads one chunk of native-language speech at a time: every extracted item carries `modality` (`said` / `shown` / `both`, or `unknown`), and code forces `said` for any source without a visual annotation. The lossless reduce keeps the label (two extractions of one item with different evidence become `both`), and compose renders it as an `[SAID]` / `[SHOWN]` / `[SAID+SHOWN]` / `[UNLABELLED]` tag the composer attributes from — only when the corpus has a shown item. The labels are in the persisted map records (`job_report_intermediates`), so a report can be checked against item provenance after the run.

Gated by `VISUAL_ENABLED` (install) AND `jobs.visual_analysis` (per job); both must be true. Off by default — it is the only multimodal spend and the only path that downloads video rather than audio.

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

Every LLM call site in the codebase is a **named use case** with a default `(provider, model, reasoning)` triple registered in `app/services/llm_routing.py::USE_CASE_REGISTRY`. Twenty-four entries today (full list in [CLAUDE.md](../CLAUDE.md) §LLM-configuration).

`resolve_config(use_case)` returns the effective config after applying, highest first: the caller's per-user override (`user_llm_overrides`, loaded into a ContextVar by `llm_service.byok_context`, E-1.13), `LLM_USE_CASE_CONFIG`, and `LLM_ROUTE_OVERRIDES` (legacy fallback). `get_llm(use_case)` returns a configured LangChain client (`ChatOpenAI`, `ChatAnthropic`, `ChatGoogleGenerativeAI`, or local OpenAI-compatible).

### Measured guidance

Each registry entry also carries `guidance`, which records what the E-1.14 measurements found for that use case. Eight entries are `measured` and cite a decision, the gap to the flagship tier and what fails on a downgrade. The other fifteen are `unmeasured`, with a note on what evidence exists. Each entry can also list per-model verdicts (`unacceptable` / `weaker`), scoped to reasoning levels where needed.

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

1. Resolves the effective `UseCaseConfig` for all 24 use cases.
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

**Budget-batched (report pipeline) — the known scale hazard.** Map batches are sized to `0.6 × LLM_MAX_CONTEXT_TOKENS` (= 628K tokens against the global 1,047,576 constant) *regardless of which model the use case resolves to* — no per-model context-window table exists, and `min_context_recommended` in the registry is advisory metadata only. Reduce is single-level (one pairwise halving, no recursion, no final merge); reduce failure passes raw map outputs to compose. Failed map batches are silently dropped (`except → warn → continue`). The channel path truncates each channel at 314K tokens with no logging. `search_rank_and_curate` puts the whole candidate pool (cap `num_videos × 5`) in one prompt: ~130K tokens at target=200, ~300K at target=500. Only 4 of 20 registered call sites set `max_tokens`; no code path recognizes a context-length 400 specifically, and one-token startup probes cannot detect window mismatches.

**Remediated 2026-07-29** by [E-1.12](initiatives.md#e-112--llm-context-window-resilience-at-scale) (PRs #195/#196, [D-052](decisions.md#d-052--measured-context-windows--three-tier-model-stack-e-112-model-re-audit-2026-07-29)): batch budgets now derive from the RESOLVED model's empirically measured window (`llm_routing.MODEL_CONTEXT_WINDOWS` + `context_window_for()`, ×0.5 safety, 120K context-rot quality cap); reduce recurses pairwise to a single summary with token-truncated failure paths; failed map batches bisect-retry once and permanent drops render as a processing-note footer in the report itself; candidate ranking runs a batched tournament above 400 candidates; knowledge extraction batches full transcripts (500K sanity ceiling with a `_processing.truncated` marker) and synthesize sends a 20K grounding excerpt instead of the full transcript; all 20 call sites set `max_tokens`. The job-scope retrieval bug is fixed — the router passes approved video ids and retrieval filters on them (empty-approval jobs never fall back to global search). Mid-tier calls run on `gpt-5.4-mini` with reasoning OFF — on mini, reasoning consumes the visible completion budget (live-validation catch, PR #196).

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
| `deck` | the user's runs | `author_deck_outline`, one call | `pptx`, plus `md` text |
| `site` | `shelf:` and `job:` ids | none | `zip`, plus a Markdown contents page |

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

Four streaming JSONL endpoints (`routers/exports.py`):

- `/api/v1/exports/qa-dataset/openai.jsonl` — Q&A as OpenAI chat-format records.
- `/api/v1/exports/qa-dataset/tuple.jsonl` — Q&A as plain `(system, user, assistant)` tuples.
- `/api/v1/exports/knowledge-dataset/openai.jsonl` — knowledge artifacts in chat format.
- `/api/v1/exports/knowledge-dataset/tuple.jsonl` — knowledge artifacts in tuple format.

`StreamingResponse` over a SQL iterator. Memory stays constant for arbitrarily large exports. System prompts are baked into `services/dataset_service.py` as module constants. The Q&A dataset unions `qa_exchanges` + `library_qa_exchanges` + `qa_history_exchanges` ordered by `created_at`.

---

## Multilingual posture

- **Whisper** is invoked with `task="transcribe"` (not `translate`) so mixed-language audio (e.g. Hindi-English code-mixed) is preserved faithfully.
- The **embedding model** is multilingual (`paraphrase-multilingual-MiniLM-L12-v2`), so a Hindi transcript and an English question land in similar vector space — passably for Devanagari, badly for romanised Hindi. Non-English chunks are therefore embedded as an English rendering (see [Embedding](#embedding), D-084).
- **Code-mixed speech** ([N-002](inventions.md#n-002--proportion-driven-rendering-policy-for-code-mixed-speech-2026-07-31), S-1.16.2). `language_service` profiles scripts exactly and is blind to Hindi in Latin letters by design. `code_mixing_service` answers the other question, which language each word is in, and runs on Latin and Devanagari alike. It works in four steps: a lexicon + character n-gram + Viterbi tagger; a matrix-language vote over system morphemes, which tells "Hindi grammar with English nouns" from "English with a Hindi clause"; a proportion-to-quote-form policy (`CODE_MIX_DOMINANT_SHARE` 0.6, `CODE_MIX_BORROWING_MAX_SHARE` 0.2); and one primary language per source, so a report never switches script for one speaker. The analysis path reads English (every prompt carries the English contract and the source's `speech:` note). Quotation keeps the original: report map items may carry `original` beside English `content`, and compose attaches the source's `quote_form`. Every kept `original` is verified in code before anything is composed: `app/services/quote_fidelity.py` (the same rule the R1 quote-fidelity audit uses) drops wording that is not verbatim or 80%-aligned with its own source's speech, mixes two scripts in one word, or is in a script other than the source's; the drop is disclosed in the report's processing note. After composing, the same rule checks the report itself (`quote_fidelity.scrub_report`): a native-script passage found in no source's speech (titles and channel names admitted) is removed with its transliteration, its English kept, and the removal counted in `processing_notes.report_quotes_removed` and disclosed. A source typed in Latin letters is quoted in Latin letters. Method and measurements: [the detection note](notes/2026-10-19-code-mixing-detection.md).
- **Caption-track choice is the known weak point.** `_fetch_transcript_once` falls back to the first listed track, so an auto-dubbed track can be ingested instead of the original audio. In the S-1.16.2 study, 2 of 13 Hindi-speech videos arrived this way. An English dub cannot be detected downstream. Tracked as S-1.11.11.
- The **Q&A agent** accepts an `answer_language` parameter and is instructed to translate quoted non-English context into the target language while preserving proper nouns in their original script.
- **Visual annotations are always written in English**, whatever the spoken language, because they are our text rather than the speaker's. `visual_service.strip_annotations` exists so that speech-only surfaces — dataset exports, word counts, and the language profiler — measure the source and not our own commentary.

---

## Forward-looking notes

These sections describe the trajectory, not the current code:

- **Multi-source ingest** — the `videos` → `documents` table rename landed in L1 PR 4; the `SourceConnector` interface contract (PR 2/3) routes every YouTube call site through `connector_for("video")`. The Reddit (S-1.5.1) and HN (S-1.5.2) standalone connectors followed; **E-1.10 UUID PK promotion shipped 2026-05-02** ([PR #112](https://github.com/khoks/VideoResearchPro/pull/112)) collapsing storage tasks to trivial inserts. Reddit + HN end-to-end ingest converges on **Milestone M-1.5** (3 of 7 component checks closed; orchestrator wiring + frontend ApprovalCard primitive + citation rendering + e2e tests are the remaining work). Full trajectory in [source-types.md](source-types.md). L1 in the [feature-roadmap](feature-roadmap.md).
- **Personal Brain** — activity stream connectors, voice capture, "speak as me" agent are detailed in [personal-brain.md](personal-brain.md). Multi-quarter trajectory.
- **SaaS** — tenancy, billing, abuse prevention, hosting are detailed in [saas-roadmap.md](saas-roadmap.md). Today's PRs already respect the forward-compat invariants.
- **Author Studio** — derivative artifact generation (books, sites, decks, newsletters, reels) is L2 in the [feature-roadmap](feature-roadmap.md). Books, decks and sites ship (see [Author Studio outputs](#author-studio-outputs)); newsletters and reels remain.
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
