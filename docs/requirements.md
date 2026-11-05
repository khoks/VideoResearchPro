# Pratidhvani — Requirements

**Status:** written 2026-04-24; NFR-4 amended 2026-10-19; FR-19 amended 2026-10-25; re-audited against the code 2026-11-04 (T-4.11.1.5). Functional requirements describe what the running system does; non-functional requirements describe the quality bars it must meet. Forward-looking requirements (multi-source, Author Studio, Personal Brain, SaaS) live in their owning docs and are not duplicated here — see [feature-roadmap.md](feature-roadmap.md).

---

## Functional requirements

### FR-1 — Job submission

- **FR-1.1.** Users can create **topic-based** jobs by providing:
  - `topic` (required)
  - `search_instructions` (optional free-text steering for the Search Agent)
  - `preferred_channels` (optional list of channel handles to prefer)
  - `num_videos` (default 10; the plan sets the cap)
  - `source_types`, `output_length`, duration bounds, `channel_type_filters` and `published_after_days` (all optional)
- **FR-1.2.** Users can create **channel-based** jobs by providing:
  - `channel_list` (1+ YouTube channel URLs, handles or UC ids)
  - `videos_per_channel` (default 10, at most 50)
- **FR-1.3.** Users can create **subscription-based** jobs by providing:
  - `channel_list` (1+ YouTube channel URLs, handles or UC ids)
  - The channels become *subscribed* for that user.
- **FR-1.4.** The install runs at most `MAX_CONCURRENT_JOBS` (default 5) active jobs at once, counted over every user. One more is refused.
- **FR-1.5.** Jobs are user-scoped: each job belongs to the user who created it; users do not see one another's jobs. The `documents` table is one global cache, but a user sees only the documents they ingested ([D-063](decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)).

### FR-2 — Video discovery

- **FR-2.1.** **Topic jobs** run a LangGraph Search Agent that:
  - Plans 3-5 search queries via `search_plan_queries` (LLM use case)
  - Executes them in parallel against YouTube Data API v3
  - Ranks and deduplicates via `search_rank_and_curate` (LLM use case)
  - Returns a curated candidate list
- **FR-2.2.** **Channel jobs** resolve channel handles → channel IDs → uploads playlist → recent videos.
- **FR-2.3.** **Subscription jobs** walk every video on each channel's uploads playlist. Videos already in the library skip the fetch, transcription and embedding.

### FR-3 — Video approval (topic and channel jobs)

- **FR-3.1.** Topic and channel jobs pause at `awaiting_approval` after discovery.
- **FR-3.2.** Users see a list of discovered videos with thumbnails, channel, duration, published date.
- **FR-3.3.** Users select a subset and `PUT` it to `/jobs/{id}/approve` with the approved IDs.
- **FR-3.4.** Approval is **passive**: the worker that ran search has already exited. A new Celery task is dispatched to resume from extraction.
- **FR-3.5.** Subscription jobs skip approval entirely.

### FR-4 — Transcript extraction

- **FR-4.1.** Transcripts are fetched via `youtube-transcript-api` per video.
- **FR-4.2.** **Multilingual.** The track taken is the one in the language the video is spoken in, never an auto-dub; English first applies only when nothing says what is spoken ([D-117](decisions.md#d-117--the-caption-track-is-the-one-in-the-spoken-language-auto-dubs-are-read-from-the-players-audio-tracks-2026-10-29)). The transcript's language is stored.
- **FR-4.3.** When no caption track exists at all, the system falls back to **Whisper transcription** via `yt-dlp + whisper`. Whisper is invoked with `task="transcribe"` (not `translate`) so mixed-language audio is preserved.
- **FR-4.4.** Failed transcripts mark the video `transcript_status='unavailable'` without blocking other videos in the job.
- **FR-4.5.** **Cached.** A `transcript_cache` row keyed by `document_id` ensures we never re-fetch.
- **FR-4.6.** Rate-limited (default 3 s between requests, with jitter; `YOUTUBE_TRANSCRIPT_RATE_LIMIT`). The pace of 0.5 s triggered an IP block at about 60 videos.

### FR-5 — RAG construction

- **FR-5.1.** Transcripts are chunked at 256 tokens with 32-token overlap (`CHUNK_SIZE` / `CHUNK_OVERLAP`).
- **FR-5.2.** Each chunk preserves `start_time` / `end_time` derived from the source segments.
- **FR-5.3.** Chunks are embedded with `paraphrase-multilingual-MiniLM-L12-v2` (CPU SentenceTransformer; no embedding API). A chunk of a non-English source is embedded as its English rendering, while its stored text stays the original ([D-084](decisions.md#d-084--code-mixed-retrieval-embed-an-english-rendering-keep-the-original-as-the-stored-text-2026-10-19)).
- **FR-5.4.** Chunks live in **a single global ChromaDB collection** (`pratidhvani_global` by default, `CHROMA_GLOBAL_COLLECTION_NAME`). Per-job scoping is a metadata filter at query time.
- **FR-5.5.** Chunk metadata carries `document_id` for every source type, the source fields (`source_type`, `source_id`, `source_url`, `channel_id` and the like), `chunk_index`, the time span, and the temporal and language fields, which are omitted when unknown.
- **FR-5.6.** **One-time embedding.** Each document's `Document.embedded_in_chroma` flips to `true` after first chunking. Subsequent jobs referencing that video skip embedding.

### FR-6 — Report generation

- **FR-6.1.** **Topic jobs** generate a full HTML report via the LangGraph Report Agent:
  - **map_chunks** (`report_map_chunks`) — per-batch fact extraction
  - **reduce_summaries** (`report_reduce_summaries`) — consolidation
  - **compose_report** (`report_compose`) — final composition
- **FR-6.2.** **Channel jobs** generate a stats-only HTML report via the channel-report pipeline (`report_channel`, `report_compose_channel_section`).
- **FR-6.3.** **Subscription jobs** generate **no report**.
- **FR-6.4.** Reports include: key facts, perspectives, conclusions, references with `&t=` timestamp links, speaker attribution where identifiable, statistics (video count, total duration, word count, channel breakdown).
- **FR-6.5.** Reports are saved as standalone HTML files under `data/reports/` and served via `GET /jobs/{id}/report`.
- **FR-6.6.** The report endpoint takes the bearer header only. The job page's quick-peek modal fetches the HTML with the header and frames it from a blob: URL; the `?token=` query-string fallback it used was retired by T-8.8.1.5 (2026-10-25), on this route and on the `/exports/*` downloads.
- **FR-6.7.** Reports are read natively at `/reports/:jobId` from `GET /jobs/{id}/report/body` (header-bearer only), sanitised and parsed in the browser, with an outline, citation cards, endnotes and a print stylesheet; knowledge reports and Author Studio books read in the same shell ([D-085](decisions.md#d-085--reading-room-reports-stay-html-sanitised-and-parsed-in-the-browser-one-shared-citation-card-fed-by-the-runs-documents-2026-10-19), [D-086](decisions.md#d-086--markdown-readers-react-markdowns-own-pipeline-run-once-with-a-tree-transform-the-outline-is-the-two-shallowest-structural-heading-levels-2026-10-19)).

### FR-7 — Per-job Q&A

- **FR-7.1.** Completed topic and channel jobs expose a Q&A surface.
- **FR-7.2.** **Optional clarify step** (`qa_clarification`) — the LLM produces an interpretation and three follow-up clarifying questions before the answer.
- **FR-7.3.** Q&A pipeline: `qa_sub_query_expansion → retrieve_context → qa_refine_context → qa_formulate_answer → qa_extract_references`.
- **FR-7.4.** **Context refinement** is mandatory: raw RAG + report context (~45K tokens p95) is compressed to ~3K focused excerpts before the answer LLM sees it.
- **FR-7.5.** Topic jobs use RAG + the generated report. Channel jobs use RAG only.
- **FR-7.6.** Q&A accepts an `answer_language` parameter (default English). Quoted non-English context is translated into the target language while preserving proper nouns.
- **FR-7.7.** Answers cite sources with `(video_id, timestamp, quote)` triples; the frontend turns them into chips with `&t=` timestamp deep-links.
- **FR-7.8.** Per-job Q&A history is persisted to `qa_exchanges` and indexed into `qa_library_global` post-commit (best-effort; Chroma failures never break the response).

### FR-8 — Library-wide Q&A

- **FR-8.1.** Authenticated users can ask questions across the library they can see, at `/library/qa`, or about one source (`document_id`).
- **FR-8.2.** No per-job filter. Retrieval is limited to `document_id ∈` the asker's visible set; an empty set retrieves nothing ([D-063](decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)).
- **FR-8.3.** Same clarify / sub-query / refine / answer / extract pipeline as FR-7, with use cases prefixed `library_qa_*`.
- **FR-8.4.** Library Q&A history persists to `library_qa_exchanges` and is indexed into `qa_library_global`.
- **FR-8.5.** A user can delete a library Q&A exchange (`DELETE /library/qa/{exchange_id}`).

### FR-9 — Channel management & subscriptions

- **FR-9.1.** Users can list, view, and subscribe / unsubscribe channels.
- **FR-9.2.** Subscribing a channel optionally dispatches an immediate sync job that ingests every video on its uploads playlist.
- **FR-9.3.** Subscriptions are per user (`channel_subscriptions`, [D-065](decisions.md#d-065--channel-subscriptions-become-per-tenant-transliteration-reversed-2026-07-31)). `last_synced_at` records the last sync and is shown; a sync walks the whole playlist and relies on the library's dedup.
- **FR-9.4.** Manual sync (`POST /channels/{id}/sync`) is supported.
- **FR-9.5.** Unsubscribing leaves already-ingested videos in the global library; cleanup is intentional, not implicit.

### FR-10 — Q&A History meta-chat

- **FR-10.1.** Users can ask **meta-questions** across every Q&A they have ever run, at `/qa-history`.
- **FR-10.2.** Powered by the `qa_library_global` Chroma collection, which unions `qa_exchanges` + `library_qa_exchanges` + `qa_history_exchanges`.
- **FR-10.3.** Pipeline: `retrieve_past_exchanges → qa_history_refine_context → qa_history_formulate_answer`.
- **FR-10.4.** References cite past exchange IDs; the frontend resolves them to deep links to the originating job-detail or library-Q&A page.
- **FR-10.5.** An idempotent backfill upserts every existing row from the three Q&A tables into `qa_library_global`, in the API's startup and as a task queued when a worker starts.

### FR-11 — Per-document knowledge artifacts

- **FR-11.1.** Every document, of any source type, can have a structured knowledge artifact extracted on demand, via `POST /videos/{id}/extract-knowledge`.
- **FR-11.2.** The Knowledge Agent splits the document's full text into token-budgeted batches (`KNOWLEDGE_EXTRACT_BATCH_TOKENS`, default 8000). The whole text is read, up to a 500,000-token sanity ceiling that marks a truncated result.
- **FR-11.3.** **Map phase** (`knowledge_extract_batch`) returns structured `{topics, concepts, events, facts}` JSON per batch.
- **FR-11.4.** **Merge phase** unions and deduplicates the per-batch outputs.
- **FR-11.5.** **Synthesize phase** (`knowledge_synthesize_report`) renders a Markdown knowledge document.
- **FR-11.6.** Output is persisted to `documents.extracted_knowledge_json`, `documents.knowledge_report_md`, `documents.knowledge_extracted_at`.
- **FR-11.7.** Returns 409 if already extracted unless `?force=true`.

### FR-12 — Dataset exports

- **FR-12.1.** Four streaming JSONL endpoints expose the corpus for fine-tuning:
  - `/exports/qa-dataset/openai.jsonl` — Q&A in OpenAI chat format
  - `/exports/qa-dataset/tuple.jsonl` — Q&A in tuple format
  - `/exports/knowledge-dataset/openai.jsonl` — knowledge artifacts in chat format
  - `/exports/knowledge-dataset/tuple.jsonl` — knowledge artifacts in tuple format
- **FR-12.2.** All endpoints use FastAPI `StreamingResponse` over a SQL iterator. **Memory stays constant** for arbitrarily large exports.
- **FR-12.3.** The Q&A dataset unions `qa_exchanges` + `library_qa_exchanges` + `qa_history_exchanges` ordered by `created_at`.
- **FR-12.4.** System prompts are baked into `services/dataset_service.py` as module constants.

### FR-13 — Auth & multi-user

- **FR-13.1.** Email + password registration and login (`/auth/register`, `/auth/login`), Google and GitHub OAuth with PKCE, and two-step verification (TOTP + recovery codes).
- **FR-13.2.** Passwords hashed with bcrypt.
- **FR-13.3.** Login issues a JWT tied to a session the server can revoke; included as `Authorization: Bearer <token>` on every authenticated request.
- **FR-13.4.** Protected endpoints fail with 401 on missing/invalid token.
- **FR-13.5.** Resources are filtered by user ownership at query time. The global document store is a shared cache, read through each user's visibility grants ([D-063](decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)).

### FR-14 — LLM smoke + fail-soft

- **FR-14.1.** On FastAPI startup, `services/llm_smoke.run_startup_probes` resolves the effective `(provider, model, reasoning)` triple for every registered LLM use case.
- **FR-14.2.** Probes are deduped by `(provider, model, vision)` — each unique config is probed exactly once with a trivial one-token call.
- **FR-14.3.** Results are stored on a process-global `LLMStatus` singleton.
- **FR-14.4.** `GET /health` returns overall status plus an `llm` object: `status` (`ok` / `degraded` / `down` / `unknown`) and `unavailable_features` (list of feature names whose required use cases failed).
- **FR-14.5.** `GET /health/llm` returns full per-use-case detail: `provider`, `model`, `reasoning`, `ok`, `latency_ms`, `error`.
- **FR-14.6.** **Fail-soft:** when a probe fails, the app stays up. The frontend shows a banner; pages whose primary action depends on a failed feature disable that action. Non-LLM features remain interactive (browse library, view past reports, download dataset exports).

### FR-15 — LLM routing

- **FR-15.1.** Every LLM call site is a **named use case** with a default `(provider, model, reasoning)` registered in `app/services/llm_routing.py::USE_CASE_REGISTRY`.
- **FR-15.2.** Thirty-six use cases ship today (full list in [CLAUDE.md](../CLAUDE.md) §LLM-configuration).
- **FR-15.3.** `LLM_USE_CASE_CONFIG` env var overrides any use case at runtime: `use_case=provider:model[:reasoning]`, comma-separated.
- **FR-15.4.** Unknown use case names, providers, or reasoning levels are logged as warnings and ignored — never fatal.
- **FR-15.5.** Supported providers: OpenAI, Anthropic, Google, local (OpenAI-compatible).
- **FR-15.6.** Reasoning levels are normalized across providers (off / minimal / low / medium / high / auto), with provider-specific mapping.

### FR-16 — Real-time progress

- **FR-16.1.** A single multiplexed WebSocket at `/ws/jobs` streams progress for any subscribed job.
- **FR-16.2.** Clients subscribe and unsubscribe per `job_id` via JSON action messages.
- **FR-16.3.** Celery workers publish progress to Redis pub/sub channel `job_progress:{job_id}` at every phase boundary.
- **FR-16.4.** WS authenticates via `?token=` query string (browsers cannot set Authorization headers on WS).
- **FR-16.5.** Heartbeats every 30 seconds.
- **FR-16.6.** The frontend's `useJobProgress` hook drives React Query cache updates off WS messages.

### FR-17 — Quota observability

- **FR-17.1.** Every YouTube API call is logged in `api_quota_log` with cost units.
- **FR-17.2.** Each request also counts against the user's own usage, by feature ([E-5.2](initiatives.md#e-52--subscription-tier-gating)).
- **FR-17.3.** `YOUTUBE_DAILY_QUOTA` (default 10,000 units) is what usage is reported against. Nothing in the app refuses a search at that figure: YouTube's own 403 ends the search phase, and `QuotaExceededError` carries it.
- **FR-17.4.** `GET /health/quota` returns today's date, units used, the daily limit and what remains.

### FR-18 — Admin & operations

- **FR-18.1.** `POST /admin/restart` (Windows-only today) restarts the running services via a detached PowerShell trampoline. Returns 202; the actual restart happens out of band.
- **FR-18.2.** Optional `skip_frontend` query param leaves Vite alone if only backend code changed.
- **FR-18.3.** The restart and the tier switch (`PUT /auth/me/tier`) are operator-only (T-5.2.8, D-111): the accounts in `ADMIN_EMAILS`, or the earliest-registered account when it is empty. Any other account gets 403.

---

## Non-functional requirements

### NFR-1 — Performance

- **NFR-1.1.** First search result returned within 30 s of `pending` for topic jobs (assuming healthy YouTube API).
- **NFR-1.2.** Per-video transcript fetch median ≤ 2 s (`youtube-transcript-api` path); Whisper fallback can take O(audio length) and is acknowledged as variable.
- **NFR-1.3.** Per-job Q&A end-to-end median ≤ 12 s on the default LLM routing.
- **NFR-1.4.** Library-wide Q&A end-to-end median ≤ 18 s.
- **NFR-1.5.** Dataset export memory footprint stays constant regardless of dataset size (verified by streaming response over SQL iterator).

### NFR-2 — Reliability

- **NFR-2.1.** Job lifecycle is deterministic: every state transition is an atomic DB write paired with a single Celery task dispatch.
- **NFR-2.2.** Approval-pause does not block worker capacity. A job can sit in `awaiting_approval` for arbitrary time.
- **NFR-2.3.** A failed chunk insert fails the job at `building_rag`; nothing retries it.
- **NFR-2.4.** Q&A library upserts are best-effort; Chroma failures never break the Q&A response.
- **NFR-2.5.** Worker startup runs an idempotent backfill of `qa_library_global` from the three Q&A tables.

### NFR-3 — Fail-soft

- **NFR-3.1.** When any LLM use case fails its smoke probe, the app stays up. Affected actions are disabled; everything else stays interactive.
- **NFR-3.2.** When YouTube quota is exhausted, the user can still **read** their accumulated library — only **new ingestion** is blocked.
- **NFR-3.3.** When ChromaDB is unreachable, the user can still browse SQL-backed views (Library page, Jobs list).

### NFR-4 — Multilingual

- **NFR-4.1.** Embedding model is multilingual; Hindi transcripts and English questions land in similar vector space.
- **NFR-4.2.** Whisper transcribes (does not translate); mixed-language audio is preserved faithfully with proper nouns in their original script.
- **NFR-4.3.** The Q&A agent translates quoted non-English context into the requested `answer_language` while preserving proper nouns.
- **NFR-4.4.** Code-mixed and romanised speech is recognised as non-English, per word, in Latin and Devanagari script alike (held-out romanised text: token precision 0.93, recall 0.89; 17 of 18 Hindi-bearing unseen comments). Every source's quotes use one quote form chosen from its measured language mix: Devanagari + transliteration + translation, Roman script + translation, or plain English ([N-002](inventions.md#n-002--proportion-driven-rendering-policy-for-code-mixed-speech-2026-07-31), [D-080](decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19)).

### NFR-5 — Observability

- **NFR-5.1.** Logs go through stdlib `logging`, as plain text.
- **NFR-5.2.** Celery task logs include `job_id` in every record.
- **NFR-5.3.** YouTube API calls are tracked in `api_quota_log` with cost units.
- **NFR-5.4.** LLM startup probes record `latency_ms` per `(provider, model)` pair on the `LLMStatus` singleton.

### NFR-6 — Cost / quota observability

- **NFR-6.1.** YouTube API quota status is surfaced via `GET /health/quota`.
- **NFR-6.2.** `/account/system` shows today's usage against the daily limit; the submit form shows an estimate of the one run. There is no banner.
- **NFR-6.3.** LLM tokens, calls, YouTube units and Whisper audio are recorded per user and feature (`usage_records`, `GET /usage`). Nothing is enforced from those figures ([D-111](decisions.md#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)).

### NFR-7 — Forward-compatibility with multi-tenancy

- **NFR-7.1.** Every user-scoped table has a `tenant_id` column. Each user is one tenant.
- **NFR-7.2.** User-scoped queries filter on `tenant_id` where they run; there is no central helper. Reads of `documents` go through `visibility_service.visible_document_ids`.
- **NFR-7.3.** Tier quotas are enforced per tenant (`quota_metering_service`, HTTP 429 over the limit).

### NFR-8 — Security

- **NFR-8.1.** Passwords hashed with bcrypt (work factor ≥ 12).
- **NFR-8.2.** JWTs signed with HS256; secret in `.env`.
- **NFR-8.3.** Bearer token validated on every protected request.
- **NFR-8.4.** No user input ever passed unsanitized to the LLM prompt — the agent prompts are templated.
- **NFR-8.5.** A report is untrusted HTML. The job page frames it from a blob: URL in a sandboxed iframe with scripts blocked, and the reading room sanitises it with DOMPurify. The server sends no `Content-Security-Policy` header of its own.
- **NFR-8.6.** ChromaDB queries use parameterized metadata filters; no raw query injection surface.

### NFR-9 — Privacy

- **NFR-9.1.** Self-host stores all data locally under `data/`.
- **NFR-9.2.** No telemetry pings third-party services.
- **NFR-9.3.** YouTube transcripts are public content; we cite, never rehost video.
- **NFR-9.4.** Echo follows the privacy model in [personal-brain.md](personal-brain.md): each connector is opt-in, and export and full delete cover every store.

### NFR-10 — Maintainability

- **NFR-10.1.** Backend tests run against in-memory SQLite, mocked Celery, ephemeral ChromaDB. No external service dependency.
- **NFR-10.2.** Frontend type-checks via `npm run build` (Vite + tsc).
- **NFR-10.3.** Alembic owns schema migrations: startup brings the database to head (`schema_init_service`), and nothing calls `Base.metadata.create_all`.
- **NFR-10.4.** Code style enforced by ruff (Python) and the TS compiler (frontend); see [contributing.md](contributing.md).

---

## Out of scope

Things that are intentionally **not** requirements today:

- Video hosting / re-encoding / streaming.
- A creator-facing analytics surface.
- Public sharing of reports beyond the in-app reader (M11, decision-gated).
- Realtime collaborative editing of Q&A or notes.
- Multi-tenant data sharing between workspaces (each tenant is isolated by default).
- Anything requiring a paid embedding API (we use local SentenceTransformer).

---

## Cross-references

- Architecture & request lifecycles — [architecture.md](architecture.md)
- API endpoints these requirements expose — [api-reference.md](api-reference.md)
- Pages that consume them — [ui-pages.md](ui-pages.md)
- Roadmap (what's next) — [feature-roadmap.md](feature-roadmap.md)
- SaaS forward-compat — [saas-roadmap.md](saas-roadmap.md)
- Personal Brain forward-compat — [personal-brain.md](personal-brain.md)
- Multi-source forward-compat — [source-types.md](source-types.md)

### FR-19 — Visual understanding (opt-in)

A job may request visual analysis at submission (`visual_analysis: true`). When the install also enables it (`VISUAL_ENABLED`), each ingested video is analysed for moments where on-screen content carries information the speech does not; stills are captured at those moments, described by a multimodal model in the context of the surrounding speech, and merged into the transcript as `[VISUAL @ mm:ss — …]` annotations.

- Frames are keyed on the document and reused by every job referencing it, like transcripts and embeddings.
- Per-video and per-job frame caps bound cost; unused allowance returns to the job pool, and reused frames cost nothing.
- Annotations are marked in chunk text so they survive chunking, and every prompt reading transcript text is instructed to treat them as on-screen evidence rather than speech.
- For a source whose speech is English in Latin script, a report does not leave a detail found only in an annotation inside a sentence credited to a speaker. The attribution guard marks it in place as "on screen at mm:ss" and corrects speech presented as on screen. It never claims a detail went unsaid. It discloses each change in the processing note, and names how many sources it could not check. It never deletes a detail ([D-106](decisions.md#d-106--the-deterministic-attribution-guard-ships-in-the-report-pipeline-r1-stays-hidden-after-run-9-2026-10-24), [D-108](decisions.md#d-108--the-attribution-guard-never-infers-that-a-detail-went-unsaid-it-checks-only-english-speech-in-latin-script-2026-10-25)).
- Failure is isolated: a blocked download, an unusable selection, or a failed description never prevents a job from completing.
- Off by default. See [D-067](decisions.md#d-067--visual-understanding-separate-frames-table-marker-in-text-annotation-opt-in-per-job-2026-07-31).
