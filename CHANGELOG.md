# Changelog

All notable changes to **Pratidhvani (प्रतिध्वनि)** — formerly *VideoResearchPro* — are recorded here.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Releases are not yet tagged; entries are ordered by PR merge date, newest first. Once the project cuts its first semver tag, this file will shift to dated release sections.

For the *why* behind any entry, follow the linked PR. For the active roadmap, see [docs/feature-roadmap.md](docs/feature-roadmap.md).

---

## Unreleased

### Branding & documentation refresh

- **Rebrand to Pratidhvani (प्रतिध्वनि).** Sanskrit for "echo" — captures both the *sources echoing into the library* and *past exchanges echoing into future ones*. Legacy `VideoResearchPro` name retained only in grandfathered env-var names like `CHROMA_GLOBAL_COLLECTION_NAME=videoresearchpro_global` for back-compat. See [docs/branding.md](docs/branding.md).
- **Warm-editorial visual language.** Retired the `#667eea → #764ba2` purple-blue gradient. New palette: paper-tone backgrounds, oxblood / forest-teal / vintage-gold accents, Fraunces + Source Serif Pro + Inter + JetBrains Mono typography. See [docs/ui-design.md](docs/ui-design.md).
- **Full docs refresh.** Split stale monoliths into canonical single-topic docs with an explicit ownership matrix:
  - New: [docs/vision.md](docs/vision.md), [docs/branding.md](docs/branding.md), [docs/feature-roadmap.md](docs/feature-roadmap.md), [docs/saas-roadmap.md](docs/saas-roadmap.md), [docs/personal-brain.md](docs/personal-brain.md), [docs/source-types.md](docs/source-types.md), [docs/api-reference.md](docs/api-reference.md), [docs/ui-pages.md](docs/ui-pages.md), [docs/contributing.md](docs/contributing.md), [docs/testing.md](docs/testing.md), [CHANGELOG.md](CHANGELOG.md) (this file).
  - Refreshed: [docs/architecture.md](docs/architecture.md), [docs/requirements.md](docs/requirements.md), [docs/ui-design.md](docs/ui-design.md).

*(No code changes shipped in this pass — documentation and identity only.)*

---

## Recently shipped

### Per-use-case LLM config + smoke-check + fail-soft UI · [#62](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/62)

- Every LLM call site in the codebase is now a named **use case** with a default `(provider, model, reasoning)` triple in `app/services/llm_routing.py::USE_CASE_REGISTRY`. Nineteen entries cover Q&A (job-scoped, library-scoped, history-chat), knowledge extraction, topic search, and report generation.
- New `LLM_USE_CASE_CONFIG` env var overrides any entry without editing code: `use_case=provider:model[:reasoning]`, comma-separated. Typos are warnings, never fatal.
- Providers supported: `openai`, `anthropic`, `google`, `local` (any OpenAI-compatible endpoint — LM Studio, Ollama, vLLM, llama.cpp-server).
- Reasoning normalized across providers (`off` / `minimal` / `low` / `medium` / `high` / `auto`), mapped to each SDK's native parameter.
- **Startup smoke check.** `run_startup_probes` fires a one-token probe per unique `(provider, model)` pair at boot; results land on a process-global `LLMStatus` singleton exposed via `GET /api/v1/health` and `GET /api/v1/health/llm`.
- **Fail-soft.** When a probe fails the app stays up; a frontend banner lists affected features and pages disable their primary action (Ask question, Generate report, Extract knowledge) while everything else stays interactive.

### Video-knowledge migration, Q&A history retrieval, LLM routing registry · [#47](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/47)

- Consolidated the formerly scattered LLM-provider selection logic into `llm_routing.py` as the single source of truth.
- Fixed Q&A History retrieval to pull from the central `qa_library_global` collection rather than per-job scopes.
- Merged the knowledge-report migration into the main Alembic chain so fresh installs don't need manual Unit-4 steps.

### Exports — drop Unit 2/4 fallback guards · [#46](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/46)

- Removed "does this column exist yet?" defensive guards from the exports service now that the `qa_library_global` and `video_knowledge` models have shipped.

### Dataset exports for fine-tuning · [#38](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/38) · [#42](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/42)

- Four streaming JSONL endpoints that dump your accumulated Q&A and knowledge artifacts as training-ready datasets:
  - `GET /api/v1/exports/qa-dataset/openai.jsonl` — OpenAI chat format
  - `GET /api/v1/exports/qa-dataset/tuple.jsonl` — plain `{system, user, assistant}` tuples
  - `GET /api/v1/exports/knowledge-dataset/openai.jsonl` — knowledge reports, chat format
  - `GET /api/v1/exports/knowledge-dataset/tuple.jsonl` — knowledge reports, tuple format
- Endpoints stream via `StreamingResponse` with SQL iterators so memory stays constant for arbitrarily large datasets.
- Q&A dataset unions `qa_exchanges` + `library_qa_exchanges` + `qa_history_exchanges` ordered by `created_at`.
- System prompts are baked into `services/dataset_service.py` as module constants.
- New Exports page in the frontend offers one-click downloads with row counts.

### Video knowledge artifacts (Unit 4 + Unit 5) · [#43](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/43) · [#40](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/40)

- Every `videos` row now carries three nullable columns — `extracted_knowledge_json`, `knowledge_report_md`, `knowledge_extracted_at`.
- New **Generate knowledge report** button on each video row triggers a map-reduce LangGraph agent (`knowledge_agent.py`) that splits the transcript into token-budgeted batches, extracts structured `{topics, concepts, events, facts}` per batch, merges with dedupe, and synthesizes a Wikipedia-paragraph-style Markdown document.
- New `POST /api/v1/videos/{id}/extract-knowledge` + `GET /api/v1/videos/{id}/knowledge` endpoints. 409 if already extracted unless `?force=true`.
- Frontend presents the artifact in a slide-in drawer.

### Q&A History chat (Unit 2 + Unit 3) · [#45](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/45) · [#39](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/39) · [#44](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/44)

- New central ChromaDB collection (`qa_library_global`) indexes every Q&A exchange — job-scoped, library-scoped, and history-chat — as single documents (question + answer concatenated, not chunked).
- Upserts run post-commit on a best-effort basis; Chroma failures never break the Q&A response.
- Worker-startup backfill idempotently upserts every existing row from `qa_exchanges`, `library_qa_exchanges`, and `qa_history_exchanges`.
- New `/qa-history` page lets you ask meta-questions across all past Q&A ("summarize everything I've learned about tariffs") with citations linking back to the source exchange.
- Powered by `qa_history_agent.py`: `retrieve_past_exchanges → refine_context → synthesize_answer`.

### Duplicate / re-run any job · [#38](https://github.com/RahulSinghKhokhar/VideoSearchDB/pull/38) (partial) and prior

- **Duplicate / Re-run** button on both the Jobs list and each Job Detail page navigates to the submit form with every parameter pre-filled from the original job.
- New **Job Parameters** card on the detail page surfaces the full submission payload in read-only form so you can see months later exactly what was asked for.
- Zero-backend-change feature — the frontend round-trips the existing `Job` response back into the form.

### Reliability & observability

- **Orphan-state backstop.** Every orchestrator task now runs a `finally`-clause safety net that fails any job stuck in a transient status (`pending` / `searching` / `extracting` / `building_rag` / `generating_report`) when the task returns, so a silent bug can't strand the UI at 5% forever.
- **Worker log capture.** `restart_services.ps1` now redirects every detached runtime's stdout and stderr to per-service `.out.log` / `.err.log` files at the repo root (uvicorn, Celery, Vite frontend).
- **Whisper retry.** Transient OpenAI errors now retry with backoff; a YouTube IP-block short-circuits the fallback chain so a single bad host doesn't poison an entire batch.
- **Extraction progress persistence.** The attempted-vs-fetched count is now written to the DB every iteration so the frontend progress bar reflects reality even mid-task.
- **Same-batch dedupe.** Prevents duplicate `Channel` / `Video` / `JobVideo` inserts within a single batch.

### Preferred channels on topic jobs · [`c48c7fb`](https://github.com/RahulSinghKhokhar/VideoSearchDB/commit/c48c7fb)

- Search Agent now takes a `preferred_channels` list alongside the topic and instructions. The LLM produces a structured plan (`broad_queries` + `channel_keywords`); preferred channels are resolved to IDs and their uploads playlists are walked directly, then keyword-filtered.
- No more creator names getting stuffed into raw YouTube query strings.

### One-click restart · [`c48c7fb`](https://github.com/RahulSinghKhokhar/VideoSearchDB/commit/c48c7fb)

- `scripts/restart_services.ps1` kills and relaunches all four runtimes (Redis, backend, Celery worker, frontend dev server) in one shot on Windows.
- `POST /api/v1/admin/restart` drives the same script from inside the running backend via a detached trampoline process. Returns `202 Accepted` immediately.
- Useful query params: `?skip_frontend=true`, `?delay=5`.

### Global video library · prior

- `videos` is now a shared, global, deduplicated table — one row per YouTube `video_id` ever.
- `channels` stores subscribed channels with `last_synced_at` for incremental re-sync.
- `job_videos` many-to-many join links jobs to videos.
- Deleting a job drops its `job_videos` rows but leaves the videos and chunks in the library so other jobs can still reference them.
- Single global ChromaDB collection `videoresearchpro_global`; per-job scoping is a metadata filter at query time.

### Channel subscriptions · prior

- New subscription job type: fire-and-forget ingestion of every video on a channel's uploads playlist — no approval step, no report. Subsequent jobs that reference the same videos skip re-fetch / re-transcribe / re-embed entirely.

### Library-wide Q&A · prior

- `POST /api/v1/library/qa` and the **/library/qa** page let you ask questions across every transcribed video in the library, not just one job.
- Citations link back to the source video with `&t=` timestamps.

### Multilingual transcription & answers · prior

- Whisper called with `task="transcribe"` (not `translate`) to preserve the speaker's language(s). Mixed-language audio (e.g., Hindi-English code-mixed) is transcribed faithfully.
- Embeddings use the multilingual `paraphrase-multilingual-MiniLM-L12-v2` so a Hindi transcript and an English question land in similar vector space.
- Q&A agent accepts an `answer_language` parameter (default English) and translates quoted non-English context into English (preserving proper nouns) while responding in the requested language.

### Authentication · prior

- Email + password JWT auth with user-scoped jobs, Q&A history, and knowledge artifacts. Channels and videos remain global (shared library), but every mutating endpoint is scoped to `current_user`.
