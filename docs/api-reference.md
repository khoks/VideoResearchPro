# Pratidhvani — API Reference

**Status:** canonical (2026-04-24, last refreshed 2026-10-19). This is the **single source of truth** for the REST and WebSocket API. All other docs link here rather than duplicating endpoint lists.

The API is mounted under `/api/v1/` (except the WebSocket, which is mounted at the root). All HTTP responses are JSON (content-type `application/json`) unless explicitly noted otherwise (HTML for reports, NDJSON for dataset exports). Authentication is via `Authorization: Bearer <jwt>` for everything except `/auth/register`, `/auth/login`, and `/health` family endpoints. The HTML report endpoint additionally accepts a `?token=` query string fallback (because iframes can't set `Authorization` headers).

Every error follows FastAPI's default `{ "detail": "..." }` shape unless otherwise noted.

---

## Auth

### `POST /api/v1/auth/register`
Create a new user. **Public.** Returns 201 + `UserResponse`.

```json
// request
{ "email": "user@example.com", "password": "..." }
// response (201)
{ "id": "...", "email": "...", "created_at": "..." }
```

### `POST /api/v1/auth/login`
Issue a JWT. **Public.** Returns 200 + `TokenResponse`.

```json
// request
{ "email": "user@example.com", "password": "..." }
// response
{ "access_token": "...", "token_type": "bearer" }
```

### `GET /api/v1/auth/me`
Return the current user. Requires bearer token.

```json
// response
{ "id": "...", "email": "...", "created_at": "..." }
```

---

## Health

### `GET /api/v1/health`
Overall app status plus a summary of LLM probe results.

```json
{
  "status": "ok",
  "llm": {
    "status": "ok",            // ok | degraded | down | unknown
    "unavailable_features": [] // feature names that are non-functional
  },
  "search_backend": "fts5"     // fts5 | like — S-8.2.1; "like" when SQLite lacks FTS5
}
```

### `GET /api/v1/health/llm`
Per-use-case LLM probe detail: the result of the startup smoke check (probes deduped by `(provider, model, vision)`; each use case reports its own reasoning level). `use_cases` is keyed by use-case name and is empty until the first probe completes.

Since S-1.14.7 each entry also carries the registry's measured `guidance` (shape under [`GET /api/v1/settings/llm`](#get-apiv1settingsllm)) and `warnings`: measured verdicts that apply to the config **this process** resolved, env overrides included. An operator whose `LLM_USE_CASE_CONFIG` points frame description at `gpt-5.6-luna` sees D-073's verdict here. Warnings are advisory; nothing refuses the config.

```json
{
  "summary": { "status": "ok", "unavailable_features": [], "last_checked_at": 1792430870.05 },
  "use_cases": {
    "visual_describe_frame": {
      "provider": "openai",
      "model": "gpt-5.6-luna",
      "reasoning": "off",
      "ok": true,
      "latency_ms": 412,
      "error": null,
      "guidance": { "status": "measured", "decision_id": "D-073", "...": "..." },
      "warnings": [
        {
          "kind": "unacceptable",          // unacceptable | weaker | not_vision_capable
          "model": "gpt-5.6-luna",
          "why": "22 of 66 gradings unusable, ...",
          "decision_id": "D-073"           // null for not_vision_capable
        }
      ]
    }
    // ... one entry per registry use case (23)
  }
}
```

### `GET /api/v1/health/scheduler`
Scheduler status (S-8.3.1). Configuration, the kinds **this process** can dispatch (the worker's list is the one that matters; nothing registers until S-8.3.2 adds `saved_search`), and `scheduled_runs` row counts. `last_run_at` is the newest dispatch across all rows, the cheapest liveness signal for beat once anything is scheduled. Unauthenticated like the rest of `/health`; counts only.

```json
{
  "enabled": true,
  "tick_seconds": 300,
  "lease_seconds": 600,
  "grace_seconds": 30,
  "kinds": [],
  "rows": { "total": 0, "enabled": 0, "due": 0, "claimed": 0 },
  "last_run_at": null
}
```

### `GET /api/v1/health/quota`
YouTube API quota status (today's usage, soft cap, hard cap, time-to-reset).

```json
{
  "units_used_today": 7340,
  "soft_cap": 8000,
  "hard_cap": 10000,
  "resets_at": "..."
}
```

---

## AI model settings

Per-user overrides of the per-use-case LLM registry (E-1.13, [D-054](decisions.md#d-054--per-user-llm-overrides--cost-calculator-gpt-56-adaptive-reasoning-findings-2026-07-29)) plus the measured guidance behind each default (S-1.14.7). All endpoints require auth; an override applies only to the caller and takes precedence over `LLM_USE_CASE_CONFIG` and the registry default. UI: `/account/ai-models`.

### `GET /api/v1/settings/llm`
Every registry use case with its default, the caller's override (or `null`), the effective config, and the measured guidance; plus the selectable models per provider and the list of models known to accept images.

```json
{
  "use_cases": [
    {
      "use_case": "report_compose",
      "summary": "Compose the final HTML report ...",
      "group": "Report generation",
      "default":   { "provider": "anthropic", "model": "claude-opus-5", "reasoning": "medium" },
      "override":  null,
      "effective": { "provider": "anthropic", "model": "claude-opus-5", "reasoning": "medium" },
      "typical_input_tokens": 10000,
      "typical_output_tokens": 16000,
      "vision": false,                       // true when the call sends images
      "guidance": {
        "status": "measured",                // measured | unmeasured
        "decision_id": "D-062",              // null when unmeasured
        "decided_on": "2026-07-31",          // null when unmeasured
        "flagship_delta": "On claude-sonnet-5 the whole report scored 7.22 against 8.67 ...",
        "downgrade_risk": "On claude-sonnet-5 the report dropped about 8 debates ...",
        "measured_cost": "claude-opus-5 adds $4.55 per 200-video job ...",
        "model_verdicts": [
          {
            "model": "claude-sonnet-5",
            "verdict": "weaker",             // unacceptable | weaker
            "why": "Synthesis 6-7 vs 9 on identical input; ...",
            "decision_id": "D-062",
            "reasoning": []                  // levels covered; [] = every level
          }
        ],
        "related_decisions": ["D-061"],
        "note": ""                           // for unmeasured: what evidence exists
      }
    }
    // ... one per registry use case (23)
  ],
  "providers": { "openai": { "models": [ { "id": "gpt-5.5", "context_window": 922000, "input_per_m": 5.0, "output_per_m": 30.0, "pricing_note": "..." } ] } },
  "reasoning_levels": ["off", "minimal", "low", "medium", "high", "auto"],
  "pricing_as_of": "2026-07-30",
  "vision_capable_models": ["claude-opus-5", "gemini-3.1-flash-lite", "gpt-5.5", "..."]
}
```

`measured` means the use case's own output was graded; a use case that only sat inside a graded chain, or changed tier alongside one that was, is `unmeasured` with a `note` saying so. An `unmeasured` entry can still carry `model_verdicts` (for example `gpt-5.4-mini` with reasoning on returned empty output on the refine calls, D-052). A verdict matches a choice when the model id is equal (no prefix matching) and the reasoning level is in `reasoning`, or `reasoning` is empty. The settings page applies the same rule client-side, and additionally warns when a `vision` use case points at a non-`local` model missing from `vision_capable_models`. Warnings never block a save.

### `PUT /api/v1/settings/llm/{use_case}`
Set the caller's override. `404` for an unknown use case, `422` for an unknown provider or reasoning level. Measured verdicts are not enforced here.

```json
// request
{ "provider": "anthropic", "model": "claude-sonnet-5", "reasoning": "medium" }
// response
{ "saved": true }
```

### `DELETE /api/v1/settings/llm/{use_case}`
Clear the caller's override; the use case returns to its registry default. Response: `{ "cleared": true }` (`false` when there was nothing to clear).

### `POST /api/v1/settings/llm/estimate`
Cost of the 200-video benchmark job (job `0d4db8c3`) under the caller's effective configs, with optional hypothetical `overrides` that are previewed and not saved. Each row also prices the same workload on the registry default, so a client can show the delta. Use cases the benchmark does not exercise (visual, era extraction, channel reports, social classification, the retired reduce call) return `calls: 0` and cost `0`.

```json
// request
{ "overrides": { "report_compose": { "provider": "anthropic", "model": "claude-sonnet-5", "reasoning": "medium" } } }
// response
{
  "benchmark": { "label": "A job like your 200-video AI research run", "videos": 200, "...": "..." },
  "per_use_case": [
    {
      "use_case": "report_compose",
      "model": "claude-sonnet-5",
      "calls": 5,
      "input_tokens": 435000,
      "output_tokens": 216000,
      "cost_usd": 3.03,
      "pricing_known": true,
      "pricing_note": "...",
      "default_model": "claude-opus-5",
      "default_cost_usd": 7.575              // null when the default has no pricing
    }
  ],
  "totals": { "cost_usd": 7.65, "unknown_pricing_models": [] }
}
```

---

## Jobs

All `/jobs` endpoints require auth.

### `POST /api/v1/jobs`
Create a new job and dispatch its Celery task. The body discriminates on `job_type` (`topic`, `channel`, `subscription`).

```json
// topic
{
  "job_type": "topic",
  "topic": "AI agent frameworks",
  "search_instructions": "...",
  "preferred_channels": ["@channel1", "..."],
  "max_videos": 25
}

// channel
{
  "job_type": "channel",
  "channel_urls": ["https://youtube.com/@channel1"],
  "max_videos_per_channel": 50
}

// subscription
{
  "job_type": "subscription",
  "channel_urls": ["https://youtube.com/@channel1"]
}
```

Optional fields accepted on every job type:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `output_length` | `"auto"` \| `"brief"` \| `"standard"` \| `"deep"` | `"auto"` | R4 report-depth override. `auto` lets the corpus-size bracket decide. Scales a derived budget; never a hard cap ([D-064](decisions.md)) |
| `visual_analysis` | bool | `false` | R1 opt-in to frame capture + description. Requires the install-wide `VISUAL_ENABLED`; the job records the request either way, but no frames are captured when the install has it off ([D-067](decisions.md)) |

Returns 201 + `JobResponse`. Both fields are echoed back on `JobResponse`.

**From a template** (E-8.6): `POST /api/v1/jobs?template_id=<id>[&template_version=<n>]` records which template version the run started from; `template_version` defaults to the latest. The body is still a full `JobCreate`, validated as any submission. A foreign, deleted or unknown template or version is a 404; a body whose `job_type` differs from the template's is a 422. `JobResponse` carries `template_id` and `template_version` (null otherwise). `{{topic}}` in `search_instructions` is filled with the topic on every topic run, template or not.

### `GET /api/v1/jobs`
List the current user's jobs. Returns `list[JobResponse]`.

### `GET /api/v1/jobs/{job_id}`
Fetch a single job. Returns `JobResponse` or 404.

### `PUT /api/v1/jobs/{job_id}/approve`
Approve a subset of the searched videos and resume the job. Body: `{ "video_ids": ["...", "..."] }`. Dispatches `resume_job_after_approval`. Topic jobs only — channel and subscription jobs do not have an approval phase. Returns updated `JobResponse`.

### `POST /api/v1/jobs/{job_id}/cancel`
Cancel a running job. Revokes the active Celery task. Returns updated `JobResponse`.

### `DELETE /api/v1/jobs/{job_id}`
Delete a job. Drops `job_videos` rows (videos and chunks survive in the global library), deletes the report file if present, and clears the per-job Q&A exchanges. Returns 204.

### `GET /api/v1/jobs/{job_id}/videos`
List the documents selected for this job. Returns `list[VideoResponse]`. Each row includes the per-job `approved` flag and the polymorphic fields `document_id`, `source_type` (default `"video"`), `source_id`, `source_url`, `source_metadata` (parsed JSON object) and `classification`. `video_id`, `url`, `duration_seconds` and `channel_name` are nullable: they are NULL for non-video documents. Until S-8.8.2 (2026-10-19) the schema did not declare the polymorphic fields, so they were stripped from every response and a non-video document on a job failed serialisation.

---

## Per-job Q&A and reports

### `GET /api/v1/jobs/{job_id}/report`
Serve the generated HTML report. Content-type `text/html`. Returns 404 if no report has been generated yet (channel jobs always have a stats-only report; subscription jobs never have one). Auth: bearer header **or** `?token=` query string (iframe-friendly). Kept for the job page's quick-peek modal and "Open in new tab"; the reader uses the body route below. The query-token fallback is slated for removal (T-8.8.1.5) once the modal no longer needs it.

### `GET /api/v1/jobs/{job_id}/report/body`
The native reader's payload (S-8.8.1). Splits the stored report back into its parts so the frontend renders the chrome itself and only the written sections go through the sanitiser:

```json
{
  "job_id": "…",
  "job_type": "topic",
  "title": "Research Report: …",
  "html": "<section class=\"report\"><h2>Executive Summary</h2>…",
  "statistics": {
    "video_count": 11, "transcript_count": 11, "total_words": 55389, "total_minutes": 226,
    "channel_breakdown": [{ "channel_name": "…", "video_count": 3, "word_count": 12000, "minutes": 61 }]
  },
  "generated_at": "2026-10-19 07:14 UTC"
}
```

`html` is **not** sanitised server-side — it is the LLM-written markup with the template's header, statistics grid and stylesheet removed; the client runs it through DOMPurify before parsing. `statistics` is `null` when the grid is absent or unreadable; a report in an unrecognised shape comes back as the whole `<body>`. Auth: bearer header **only** — no `?token=` fallback, so no token ever appears in a URL. 404 when the job is not the caller's, has no report, or the file is missing.

### `GET /api/v1/jobs/{job_id}/report.md`
The report's Markdown source (S-6.1.2): the stored HTML converted deterministically (`report_service.report_markdown`), cached beside it at `<report_path>.md`. `text/markdown; charset=utf-8` with `Content-Disposition: inline; filename="report-<job_id>.md"`. Citation links keep their `&t=` timestamps; the statistics grid and per-channel breakdown are Markdown tables. 404 `Job not found` (missing or another tenant's), `Report not generated yet`, `Report file not found`. **Header-bearer auth only** — a `?token=` does not authenticate it (the S-8.8.1 posture for new report routes); browsers download it through a fetch and a blob. Backend: `routers/reports.py`.

### `POST /api/v1/jobs/{job_id}/qa/clarify`
Pre-answer clarification step. Asks the LLM to produce an interpretation and three follow-up clarifying questions. Used by the frontend before running the full Q&A.

```json
// request
{ "question": "what do they say about supply chains?" }
// response
{
  "interpretation": "...",
  "clarifications": ["...", "...", "..."]
}
```

### `POST /api/v1/jobs/{job_id}/qa`
Ask a question scoped to this job. Runs the Q&A agent (retrieve → refine → answer → extract references) and persists the exchange.

```json
// request
{
  "question": "...",
  "context": "...",          // optional; user-provided clarification
  "answer_language": "English", // optional; default "English"
  "output_length": "deep"    // optional; "auto" | "brief" | "standard" | "deep" — overrides the job's setting; omitted = job setting, else the corpus bracket decides (D-064 / D-072)
}
// response
{
  "id": "...",
  "question": "...",
  "answer": "...",
  "references": [
    { "video_id": "...", "title": "...", "url": "...", "timestamp": 145.3, "quote": "..." }
  ],
  "created_at": "..."
}
```

Returns 400 if the job is not yet `completed`.

### `GET /api/v1/jobs/{job_id}/qa`
Per-job Q&A history. Query params: `limit` (default 50), `offset` (default 0). Ordered ascending by `created_at`. Returns `list[QAResponse]`.

---

## Library-wide Q&A

All `/library` endpoints require auth.

### `POST /api/v1/library/qa/clarify`
Pre-answer clarification step for library-scoped questions. Same shape as the per-job clarify endpoint.

### `POST /api/v1/library/qa`
Ask a question across everything the tenant can see (D-063). Runs `run_library_qa_agent` with corpus statistics for the visible set, so answer length follows the corpus bracket (D-072).

```json
// request
{ "question": "...", "answer_language": "English", "output_length": "brief" }  // output_length optional: "auto" | "brief" | "standard" | "deep""
// response
{
  "id": "...",
  "question": "...",
  "answer": "...",
  "references": [
    { "video_id": "...", "title": "...", "url": "...", "timestamp": 145.3, "quote": "..." }
  ],
  "answer_language": "English",
  "created_at": "..."
}
```

### `GET /api/v1/library/qa`
Library Q&A history. Query params: `limit` (default 100), `offset` (default 0). Ordered ascending by `created_at`. Returns `list[LibraryQAResponse]`.

### `DELETE /api/v1/library/qa/{exchange_id}`
Delete a single library Q&A exchange. Returns 204. (The matching `qa_library_global` Chroma entry is left as orphan; cleanup is a maintenance task, not a request-time concern.)

### `GET /api/v1/library/videos`
Browse the global, deduplicated video library. Returns `list[LibraryVideoResponse]`. Each row aggregates `job_count` and `job_titles[]` across `job_videos → jobs` so the UI can show "appears in N research runs" without follow-up requests.

Query params:
- `search` — free-text match across video title and channel name (ILIKE).
- `language` — exact transcript language code (e.g. `en`, `hi`).
- `channel_id` — restrict to one channel.
- `transcript_status` — one of `fetched`, `pending`, `unavailable`.
- `tag` — a tag id; only documents carrying it (S-8.1.3). Another reader's tag id matches nothing.
- `sort` — `newest` (default), `oldest`, `longest`, `shortest`.
- `limit` (default 50, max 500), `offset` (default 0).

```json
[
  {
    "id": "vid001alpha",
    "video_id": "vid001alpha",
    "title": "Alpha Intro to DNS",
    "channel_id": "UCaaa...",
    "channel_name": "Alpha Channel",
    "url": "https://www.youtube.com/watch?v=vid001alpha",
    "thumbnail_url": null,
    "duration_seconds": 300,
    "published_at": "2026-01-02T00:00:00Z",
    "transcript_status": "fetched",
    "transcript_language": "en",
    "transcript_word_count": 900,
    "job_count": 2,
    "job_titles": ["DNS basics", "Networking 101"],
    "tags": [{ "id": "…", "name": "must read", "color": "red" }]
  }
]
```

`tags` is the caller's own tags on the document, A→Z (S-8.1.3).

`channel_id`, `channel_name`, `thumbnail_url` and `duration_seconds` are empty or null for PDFs and pasted pages. Until [D-070](decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19) lands, those documents do not appear in this listing at all (see the D-063 amendment).

### `POST /api/v1/library/upload-pdf`
Multipart upload, field `file`, `.pdf` only, at most `PDF_MAX_BYTES` (100 MB). Extracts text page by page, chunks and embeds synchronously, and grants the document to the caller. Returns 201.

```json
{ "document_id": "...", "source_id": "pdf:<first-64KB sha256>", "page_count": 12, "word_count": 4810, "deduped": false }
```

`deduped: true` means the same bytes were already on the shelf; the existing document is returned and the caller is granted visibility over it. Errors: 400 not a `.pdf` or empty; 413 over the size limit; 422 uploaded but no extractable text (image-only or corrupt; the document row is kept with `transcript_status=unavailable`).

### `POST /api/v1/library/paste-urls`
Body `{ "urls": ["https://…", …] }`, 1–100 entries. Each URL is resolved to a source type by host (`facebook.com` / `fb.com` → `fb_post`, `instagram.com` → `ig_post`, `linkedin.com` → `li_post`, `twitter.com` / `x.com` → `tweet`, anything else → `article`), fetched through the article-extraction primitives, and ingested. The batch never fails on one bad URL; each row carries its own status. Returns 201.

```json
{ "results": [
  { "url": "…", "document_id": "…", "source_id": "article:<sha>", "source_type": "article", "word_count": 1200, "status": "created", "deduped": false },
  { "url": "…", "document_id": "…", "source_id": "…", "source_type": "tweet", "word_count": 40, "status": "deduped", "deduped": true },
  { "url": "…", "source_type": "article", "status": "extraction_failed" },
  { "url": "", "status": "invalid_url" }
] }
```

400 when `urls` is missing, empty or longer than 100. `invalid_url` rows carry no `source_type`; `extraction_failed` rows carry no `document_id`.

### `GET /api/v1/library/pdf/{digest}.pdf`
Serves the uploaded bytes (`application/pdf`) for the document whose `source_id` is `pdf:<digest>`; 404 if the document or the file is missing. Citations deep-link here with `#page=N`. The route sits under the router-level bearer-auth dependency and does **not** accept `?token=`, so a plain link or a new tab 401s; the frontend fetches the bytes with the header and opens a blob URL. Adopting the `?token=` fallback the export routes use is an open follow-up.

---

## Search

### `GET /api/v1/search`
Grouped, tenant-scoped keyword search across jobs, documents, channels, Q&A exchanges and knowledge reports (S-8.2.1; the command palette of S-8.2.2 calls it). Backend: `backend/app/routers/search.py`, `services/search_service.py`.

Query params: `q` (1–200 chars; whitespace-separated tokens of three or more characters are AND-ed and matched as case-insensitive substrings), `types` (comma-separated subset of `jobs,documents,channels,qa,knowledge`; default all; 400 on an unknown type), `limit` (items per group, 1–25, default 5).

```json
{
  "q": "rate cuts",
  "backend": "fts5",
  "groups": [
    { "type": "jobs", "items": [
      { "id": "<job_id>", "title": "Rate cuts research", "subtitle": "topic · completed · 2026-10-19", "href": "/jobs/<job_id>", "score": 3.5 }
    ]},
    { "type": "documents", "items": [
      { "id": "<document_id>", "title": "Interest rate cuts explained", "subtitle": "Channel · 2026-09-01", "href": "/library?document=<document_id>", "score": 2.9 }
    ]},
    { "type": "channels", "items": [{ "id": "<channel_id>", "title": "…", "subtitle": "42 subscribers", "href": "/library/channels/<channel_id>", "score": 1.1 }] },
    { "type": "qa", "items": [{ "id": "<exchange_id>", "title": "What are rate cuts?", "subtitle": "Library Q&A · 2026-10-01", "href": "/library/qa?exchange=<exchange_id>", "score": 2.0 }] },
    { "type": "knowledge", "items": [{ "id": "<document_id>", "title": "…", "subtitle": "Knowledge report · Channel", "href": "/library?document=<document_id>&view=knowledge", "score": 0.8 }] }
  ]
}
```

Groups come back in that fixed order, only the requested ones, each possibly empty. Every group is scoped to the caller — jobs by `tenant_id`, documents and knowledge by `document_visibility` keyed on `document_id` (D-070), channels by subscription or a visible document, Q&A by `tenant_id` on each of the three exchange tables — so a tenant who has ingested nothing gets empty groups, never everything (D-063). `score` is higher-is-better (`-bm25`, title weighted over body, recency tie-break); on the `like` backend every score is `0.0` and items are ordered by recency. `backend` is the engine used for *this* query: `like` also when FTS5 is present but every token is shorter than three characters. Q&A hrefs carry `?exchange=<id>` on the originating page (`/jobs/<job_id>`, `/library/qa`, `/qa-history`); document and knowledge hrefs carry `?document=<document_id>` (and `&view=knowledge`) on `/library` — the canonical id, because most non-video documents have no `video_id`, which the palette PR teaches the library page to honour.

---

## Channels

All `/channels` endpoints require auth. The channel *record* is shared; subscription state (`subscribed`, `source_weight`, `last_synced_at`) is the caller's own ([D-065](decisions.md#d-065--channel-subscriptions-become-per-tenant-transliteration-reversed-2026-07-31)), and every count or listing covers only documents the caller can see ([D-063](decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)).

`ChannelResponse`:

```json
{
  "id": "UCaaa...",                 // mirrors channel_id; rows and mutations key on it
  "channel_id": "UCaaa...",
  "name": "Alpha Channel",
  "url": "https://www.youtube.com/channel/UCaaa...",   // null for creator types with no derivable page
  "subscribed": true,
  "source_weight": 1.0,             // the caller's trust weight; read-only until S-7.1.1 ships PUT /channels/{id}/weight (D-068)
  "subscriber_count": 12345,
  "uploads_playlist_id": "UUaaa...",
  "last_synced_at": "2026-10-19T08:00:00",
  "created_at": "2026-07-31T10:00:00",
  "video_count": 12                 // documents from this channel visible to the caller
}
```

### `GET /api/v1/channels`
Channels the caller can see: any they hold subscription state for, or that produced a document visible to them. Returns `list[ChannelResponse]` ordered by name.

### `GET /api/v1/channels/{channel_id}`
Fetch a single channel with the caller's state. Returns `ChannelResponse` or 404. Backs the channel page (`/library/channels/:channelId`).

### `POST /api/v1/channels/{channel_id}/subscribe`
Flip the caller's subscription on and dispatch a sync job. Returns `SubscribeResponse` (`channel_id`, `job_id`; `job_id` is null when dispatch failed — the state still flipped).

### `POST /api/v1/channels/{channel_id}/unsubscribe`
Flip the caller's subscription off; other tenants are unaffected. Returns the updated `ChannelResponse`. Does not remove documents already in the library.

### `POST /api/v1/channels/{channel_id}/sync`
Dispatch a fresh subscription sync for the channel. Returns `SubscribeResponse`.

### `GET /api/v1/channels/{channel_id}/intelligence`
What the channel says, over **the documents of it the caller can see** (S-8.7.2, [M7 plan](plans/m7-channel-intelligence.md); D-063 / D-070). Two readers following the same channel can get different figures; a reader who can see none of its documents gets an empty aggregate, never the channel's global one. 404 for an unknown channel.

`?refresh=true` forces a recompute. Otherwise the document-derived part is served from a per-(channel, reader) cache (`channel_intelligence_cache`) until its fingerprint changes: a new visible document, new knowledge on one, a new transcript. The `qa` part is always computed live. Computed in the request (about 1.6 s cold at 500 documents, about 15 ms cached), not in the solo Celery worker, which is often busy with ingest for hours.

```json
{
  "channel_id": "UC…", "computed_at": "…", "cached": true,
  "coverage": { "documents": 120, "with_knowledge": 30, "without_knowledge": 90, "ratio": 0.25, "with_transcript": 118 },
  "cadence": { "months": [{ "month": "2026-01", "count": 4 }, …], "undated": 2 },   // contiguous, zeros included
  "durations": { "buckets": [{ "label": "5–15 min", "min_minutes": 5, "max_minutes": 15, "count": 31 }, …], "unknown": 3, "median_minutes": 18.5 },
  "topics":   [{ "label": "Monetary policy", "documents": 12, "examples": [{ "id": "…", "title": "…" }] }],   // top 25, from knowledge artifacts
  "concepts": [ … ],
  "keywords": [{ "term": "inflation", "weight": 1.0, "documents": 40 }],   // top 60, TF-IDF over cached transcripts
  "stance": null,      // { stance: [{month, counts}], sentiment: [...], classified_documents } where social classification exists
  "notes": { "topics": "Built from 30 of 120 documents. Extract knowledge for 90 more to fill these in.", "stance": "…" },
  "qa": { "exchanges": 7, "most_cited": [ … ], "recent": [{ "id": "…", "kind": "library", "question": "…", "created_at": "…", "job_id": null }] }
}
```

`notes` explains, per panel, why it is empty or partial. Topics and concepts are merged case-insensitively and counted once per document. Keywords drop English function words and spoken filler (not scikit-learn's Glasgow stop list, which removes content words like "interest"); the newest 500 documents and 40,000 characters each are read. `qa` counts the caller's own job and library exchanges whose citations include a document of this channel that the caller can see.

### `GET /api/v1/channels/{channel_id}/videos`
The caller's visible documents from the channel, newest first (`limit`, `offset`). Returns `list[VideoResponse]`. The channel page lists documents through `GET /library/videos?channel_id=` instead, because those rows carry `job_count` / `job_titles`; both routes scope to the same visible set.

---

## Job templates

Named, reusable research recipes (E-8.6 / M6; plan: [`docs/plans/m6-job-templates.md`](plans/m6-job-templates.md)). A template freezes everything on `JobCreate` except the topic; a reader types a new topic each time. **Not tier-gated.** Built-ins (`builtin: true`, S-8.6.2) are listed for everyone and are read-only (403 on any write). Another reader's template is a 404.

`JobTemplateResponse`:

```json
{
  "id": "…",
  "name": "Weekly AI policy scan",
  "description": null,
  "job_type": "topic",
  "builtin": false,
  "builtin_key": null,
  "version": 3,
  "parameters": {
    "job_type": "topic",
    "search_instructions": "Long-form interviews about {{topic}}",
    "num_videos": 25, "min_duration_minutes": 10, "max_duration_minutes": null,
    "channel_type_filters": ["educational"], "preferred_channels": ["@lexfridman"],
    "output_length": "deep", "visual_analysis": false,
    "channel_list": null, "videos_per_channel": null
  },
  "problems": [],          // why the caller could not run it today, e.g. a tier cap below num_videos
  "created_at": "…",
  "updated_at": "…"
}
```

Parameters are validated the way a submission is (`JobCreate`, with a placeholder topic, and placeholder channels when a channel or subscription recipe leaves `channel_list` empty, meaning "add the channels each run"); a recipe that would fail is a **422**, and unknown fields are refused rather than dropped. Names are unique per reader among live templates, case-insensitively (409). `{{topic}}` in `search_instructions` is replaced by the run's topic at submission.

### `GET /api/v1/job-templates`
The caller's templates A→Z, then the built-ins A→Z. The five starters (S-8.6.2) have stable `builtin_key`s: `topic-scan`, `deep-dive`, `quick-brief`, `channel-deep-dive`, `subscription-follow`.

### `POST /api/v1/job-templates`
Body `{ "name", "description"?, "parameters" }`. 201.

### `GET /api/v1/job-templates/{template_id}`
One template with its latest parameters.

### `PUT /api/v1/job-templates/{template_id}`
Partial. `name` / `description` change in place; `parameters` that differ from the latest version create the **next version** (identical ones do not). A template cannot change its research type. The newest 20 versions are kept.

### `DELETE /api/v1/job-templates/{template_id}`
204. Soft delete: gone from every listing and lookup, but its versions stay so runs that started from it keep their provenance. The name becomes free again.

### `GET /api/v1/job-templates/{template_id}/versions`
`[{ "version", "parameters", "created_at" }]`, newest first.

### `POST /api/v1/jobs/{job_id}/save-as-template`
Body `{ "name", "description"? }`. Freezes the run's recipe (everything but the topic, including `output_length` and `visual_analysis`) as version 1 of a new template. 201 `JobTemplateResponse`; 409 on a name collision.

---

## Shelves

Named, per-tenant collections of jobs (E-8.1 / M1; plan: [`docs/plans/m1-shelves.md`](plans/m1-shelves.md)). All `/shelves` endpoints require auth. **Reads work on every tier; writes need the `shelves` capability (Pro, Studio)**, so a shelf outlives a downgrade read-only. A shelf or job that belongs to another tenant is a 404, never a 403.

`ShelfResponse`:

```json
{
  "id": "…",
  "name": "Macro",
  "description": null,
  "color": "green",          // one of: default gray brown orange yellow green blue purple pink red
  "job_count": 3,
  "job_ids": ["…", "…", "…"], // most recently added first; one cached listing answers "which shelves is this run on"
  "created_at": "…",
  "updated_at": "…"
}
```

Names are unique per tenant, case-insensitively (whitespace is collapsed); a collision is a **409** with a human-readable `detail`. `color` is a palette *name*, never a hex value; anything else is a 422.

### `GET /api/v1/shelves`
The caller's shelves, A→Z, each with its `job_count`. Any tier.

### `POST /api/v1/shelves`
Body `{ "name", "description"?, "color"? }`. Returns 201 `ShelfResponse`. Pro+.

### `GET /api/v1/shelves/{shelf_id}`
`ShelfDetailResponse`: the shelf plus `jobs: JobResponse[]`, most recently added first. Any tier.

### `GET /api/v1/shelves/{shelf_id}/documents`
The union of the documents selected by the shelf's jobs, each once, filtered through the caller's visibility (D-063). Takes the library listing's `search`, `language`, `channel_id`, `transcript_status`, `tag`, `sort`, `limit`, `offset` and returns the same `LibraryVideoResponse[]` rows (with `job_count` / `job_titles` across all the caller's runs). **An empty shelf returns `[]`, never the whole library.** Any tier.

### `PUT /api/v1/shelves/{shelf_id}`
Partial update: fields left out are untouched; `"description": null` clears it; renaming onto another shelf's name is a 409. Returns `ShelfResponse`. Pro+.

### `DELETE /api/v1/shelves/{shelf_id}`
204. Removes the shelf and its membership rows; **jobs are never deleted**. Pro+.

### `POST /api/v1/shelves/{shelf_id}/jobs/{job_id}`
Put a job on the shelf. Idempotent: 200 with the (unchanged) `ShelfResponse` when it was already there. The job must be the caller's (404 otherwise). Pro+.

### `DELETE /api/v1/shelves/{shelf_id}/jobs/{job_id}`
204; 404 when the job is not on the shelf. Pro+.

### `GET /api/v1/jobs/{job_id}/shelves`
Shelves the job sits on, A→Z. Any tier; the job must be the caller's.

Deleting a job removes it from every shelf (an ORM cascade on `Job`, because SQLite does not enforce `ON DELETE CASCADE` without a pragma this app never sets). Still to come: `POST /shelves/{id}/qa` (S-8.1.4).

---

## Tags

Per-tenant labels on documents (S-8.1.3, [M1 plan](plans/m1-shelves.md)). Tags are rows with stable ids, so a rename keeps every tagging and a merge is one update. They are private to the reader who made them: another reader's tags on the same shared document never appear (D-063). **Not tier-gated.** A foreign tag id is a 404 everywhere.

`TagResponse`:

```json
{ "id": "…", "name": "must read", "color": "red", "document_count": 4, "created_at": "…" }
```

`document_count` counts only documents the caller can still see. Names are unique per tenant case-insensitively (a functional index on `lower(name)`); a collision is a **409**. `color` is a label-palette name (the same ten as shelves); anything else is a 422.

### `GET /api/v1/tags`
The caller's tags, A→Z, with counts.

### `POST /api/v1/tags`
Body `{ "name", "color"? }`. 201 `TagResponse`.

### `PUT /api/v1/tags/{tag_id}`
Rename and / or recolour; the id is kept. 409 on a name collision.

### `DELETE /api/v1/tags/{tag_id}`
204. Removes the tag from every document; documents are untouched. **With `?into=<tag_id>` it merges instead**: every document carrying this tag gets the target (duplicates are dropped, not doubled), then this tag goes. Merging into itself is a 400.

### `PUT /api/v1/library/videos/{document_id}/tags/{tag_id}`
Tag a document the caller can see (`document_id` is the D-070 primary key, the row's `id`). Idempotent. Returns `TagSummary[]`, the caller's tags now on the document. A document the caller cannot see is a 404, even with their own tag.

### `DELETE /api/v1/library/videos/{document_id}/tags/{tag_id}`
204; 404 when the document does not carry the tag.

---

## Q&A History (meta-chat)

All `/qa-history` endpoints require auth.

### `POST /api/v1/qa-history/chat`
Ask a meta-question across all past Q&A exchanges. Runs `qa_history_agent` against the `qa_library_global` collection. References cite past exchange IDs that the frontend resolves to deep links.

```json
// request
{ "question": "summarize everything I've learned about tariffs" }
// response
{
  "id": "...",
  "question": "...",
  "answer": "...",
  "references": [
    { "exchange_id": "...", "source": "job", "job_id": "...", "preview": "..." },
    { "exchange_id": "...", "source": "library", "preview": "..." }
  ],
  "created_at": "..."
}
```

### `GET /api/v1/qa-history/exchanges`
List meta-chat history. Query params: `limit`, `offset`. Returns `list[QAHistoryResponse]`.

---

## Video knowledge

All `/videos/{video_id}/...` endpoints require auth.

### `POST /api/v1/videos/{video_id}/extract-knowledge`
Run the knowledge extraction agent for this video. Map-reduce over the cached transcript, producing structured `{topics, concepts, events, facts}` JSON and a synthesized Markdown report. Persists to `videos.extracted_knowledge_json`, `videos.knowledge_report_md`, and `videos.knowledge_extracted_at`.

Query param: `?force=true` to re-run if already extracted. Returns 409 if already extracted and `force` is omitted.

```json
// response
{
  "video_id": "...",
  "extracted_at": "...",
  "topics": [...],
  "concepts": [...],
  "events": [...],
  "facts": [...],
  "knowledge_report_md": "..."
}
```

### `GET /api/v1/videos/{video_id}/knowledge`
Fetch the stored knowledge artifact. Returns 404 if not yet extracted. The path segment may be the YouTube `video_id` or the `document_id`. Besides the four lists, `knowledge_report_md` and `knowledge_extracted_at`, the response names its source (S-8.8.3): `document_id`, `source_type`, `title`, `channel_name`, `url`, `published_at`. `video_id` is NULL for non-video documents; before S-8.8.3 it was declared non-nullable, so a PDF's artifact failed serialisation.

---

## Dataset exports

All `/exports` endpoints require auth. Each returns `application/x-ndjson` (one JSON object per line) via `StreamingResponse`. Memory stays constant for arbitrarily large exports.

### `GET /api/v1/exports/qa-dataset/openai.jsonl`
Q&A dataset in OpenAI chat-format. Unions `qa_exchanges` + `library_qa_exchanges` + `qa_history_exchanges` ordered by `created_at`.

```json
{"messages":[{"role":"system","content":"..."},{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
```

### `GET /api/v1/exports/qa-dataset/tuple.jsonl`
Same data as above, in plain-tuple shape.

```json
{"system":"...","user":"...","assistant":"..."}
```

### `GET /api/v1/exports/knowledge-dataset/openai.jsonl`
Knowledge artifacts in chat-format. One record per video that has a knowledge artifact.

### `GET /api/v1/exports/knowledge-dataset/tuple.jsonl`
Knowledge artifacts in tuple shape.

System prompts are baked into `services/dataset_service.py` as module constants — see [finetune_design.md](finetune_design.md) for prompt content.

### `GET /api/v1/exports/notes.jsonl`
The caller's notes as W3C Web Annotations, one JSON-LD object per line under the `http://www.w3.org/ns/anno.jsonld` context, oldest first (S-8.5.3). Withdrawn notes are included with their `deleted` timestamp; `?include_deleted=false` leaves them out. Lossless: `services/note_export_service.py::parse_note_jsonld` is the exact inverse. `?token=` accepted like the other exports.

```json
{"@context":"http://www.w3.org/ns/anno.jsonld","id":"urn:uuid:…","type":"Annotation","motivation":"highlighting",
 "created":"2026-10-01T09:01:00+00:00","modified":"…","generator":{"type":"Software","name":"Pratidhvani"},
 "body":{"type":"TextualBody","value":"…markdown…","format":"text/markdown"},
 "target":{"id":"urn:pratidhvani:document:<document_id>","type":"document","label":"…","selector":{"type":"TextQuoteSelector","exact":"…","start_seconds":83.5}},
 "deleted":null,"pratidhvani":{"version":1,"target_type":"document","target_id":"…","target_video_id":"…"}}
```

### `GET /api/v1/exports/notes.md`
The same notes as a Markdown document (`text/markdown`): `## <target type>` → `### <target label>` with the raw `type:id` key → `#### <date>` per note, body verbatim, every column in an HTML comment, withdrawn notes marked in the heading. Same `include_deleted` and `?token=` handling.

---

## Author Studio

All `/author` endpoints require `require_feature("author_studio")` (Pro and above); a lower tier gets 403. Backend: `backend/app/routers/author.py` (I-6, PR #173). Page: [`AuthorPage`](ui-pages.md#authorpage--author-pro).

### `GET /api/v1/author/kinds`
`{ "available": ["book"], "supported": ["book", "deck", "newsletter", "reel", "site"] }`. `available` lists kinds with a registered outputter; `supported` is every kind the schema accepts. Create a kind that is supported but not available and you get 501.

### `POST /api/v1/author/outputs`
Create the row and queue its generation in the worker (S-6.7.1). Body `{ "kind": "book", "title": "…", "source_ids": ["<job_id>", …], "parameters": { "include_qa": true, "include_toc": true } }`. For `book`, `source_ids` are job IDs **of the caller's own runs** (another tenant's id reads like a missing one), one chapter per run: its report's Markdown source (S-6.1.2) with headings demoted under the chapter heading, and its Q&A if `include_qa`; a run without a report, or whose file is missing, yields a disclosed placeholder chapter. An empty `source_ids` for `book` is 400 and writes no row. Returns the `OutputItem` at once in `pending` state with `celery_task_id` set; the worker (`author.generate_output`, on the owner's tier queue) publishes status changes and per-chapter progress on the `/ws/jobs` socket under the **output's id** (subscribe to it like a job id; the server checks the caller owns it). `?sync=true` generates inside the request and returns the finished row (`completed` or `failed`), the path tests and scripts use. If the broker is unreachable the row is returned `failed` with `Could not queue generation: …`. 400 unknown kind or empty title; 501 kind without an outputter, before any row is written.

```json
{ "id": "...", "kind": "book", "title": "...", "status": "pending", "source_ids": ["..."], "parameters": {}, "error_message": null, "created_at": "...", "updated_at": "...", "has_content": false, "word_count": null, "progress_pct": 0, "progress_message": "Queued", "celery_task_id": "...", "formats": [] }
```

### `GET /api/v1/author/outputs`
List the caller's outputs. Query params: `kind`, `status` (`pending` / `generating` / `completed` / `failed` / `cancelled`). A `pending` row with no `celery_task_id` predates S-6.7.1 and will never run.

### `POST /api/v1/author/outputs/{output_id}/cancel`
Cancel a `pending` or `generating` output (S-6.7.1), mirroring `/jobs/{id}/cancel`: revokes the task and marks the row `cancelled`, publishing the change on the socket. Generation also stops at the outputter's next progress report, because a solo-pool worker cannot be interrupted mid-task, and a cancel that lands after the last report still wins over `completed`. Returns the `OutputItem`. 404 for another user's output; 400 once it is `completed`, `failed` or `cancelled`.

### `GET /api/v1/author/outputs/{output_id}`
One output; 404 for another user's (existence-leak posture).

### `GET /api/v1/author/outputs/{output_id}/download`
The output as a file (S-6.7.2). `format` (optional, `[a-z0-9]{1,8}`) picks one of the row's `formats`; without it the first is served, which is the text (`md` for a book) when there is one. Text comes from `content_text`; binary artifacts (`pdf`, `epub`, `pptx`, `zip`, …) from `<OUTPUTS_DIR>/<user_id>/<output_id>/artifact.<format>`, always derived from the row's own ids. Media type by format; `Content-Disposition: attachment; filename="<ascii>"; filename*=UTF-8''<title-slug>.<format>`. 404 for another user's output, an output with no content, or a format it does not have (the detail lists what is available); 422 for a malformed `format`. **Header-bearer only** (D-079): a `?token=` does not authenticate it.

### `GET /api/v1/author/outputs/{output_id}/content`
The generated text as `text/markdown` for books, `text/plain` otherwise. 404 when the row has no content yet. Header-auth only, so a browser download goes through a fetch and a blob, not an `<a href>`.

### `DELETE /api/v1/author/outputs/{output_id}`
`{ "deleted": true }`; 404 if absent.

---

## Echo

All `/echo` endpoints require `require_feature("echo_personal_brain")` (Studio only). Backend: `backend/app/routers/echo.py` (I-3, PR #172). Page: [`EchoPage`](ui-pages.md#echopage--echo-studio).

### `GET /api/v1/echo/status`
Cold-start readiness: `{ "ready": false, "total_rows": 1, "distinct_sources": 1, "has_personality_trait": true, "threshold_total": 100, "threshold_sources": 3, "notes_total": 4, "notes_words": 120 }`. `ready` is the AND of the three gates. `notes_total` / `notes_words` (S-8.5.3) count the caller's live notes as the Domain 3 feeder; they are reported, not gated, until S-3.5.1 sets the voice floor. `shares_total` (S-3.7.1) counts the shares inbox as the Domain 5 feeder, reported the same way.

### `GET /api/v1/echo/context`
The caller's personal-context rows. Query params: `kind`, `source`, `include_expired` (default false). Rows: `{ id, kind, key, value, source, confidence, captured_at, expires_at }`. `kind` is closed to ten values (`location`, `interest`, `hobby`, `work`, `talent`, `skill`, `personality_trait`, `life_event`, `daily_routine`, `place`); anything else is 400.

### `POST /api/v1/echo/context`
Body `{ "kind": "...", "key": "...", "value": "...", "confidence": 1.0, "expires_at": null }`; `source` is fixed to `manual`. Upserts on `(kind, key)`: re-posting an existing pair updates `value`, `confidence`, `expires_at` and `captured_at` in place, so this is also the edit endpoint. Non-string values are JSON-encoded.

### `DELETE /api/v1/echo/context/{kind}/{key}`
Deletes one row; 404 if absent. The key is a path segment and Starlette decodes `%2F` before routing, so a key containing `/` cannot be addressed; the frontend refuses such keys at entry.

### `DELETE /api/v1/echo/sources/{source}`
Revoke a source: deletes every row attributed to it for the caller. `{ "deleted_count": n }`, idempotent.

### `GET /api/v1/echo/connectors`
`{ "connectors": [], "supported_kinds": [...] }`. The connector registry is empty until E-3.2 ships a concrete connector.

### Shares inbox (S-3.7.1)
Everything the user forwards to Echo, no approval step. Every share is `pending` until S-3.7.2's processing exists. **Context-only by default:** `author_is_tenant` is false unless the user says the words are theirs; such a share is never quoted and never enters a dataset or derived export.

Share shape: `{ id, received_at, updated_at, surface, content_type, kind: "url"|"text"|"file", url, text, file: {filename, mime, size} | null, user_annotation, author_is_tenant, processing_state, linked_document_id }`. Timestamps are UTC with an offset. A foreign id is the same 404 as a missing one.

- `POST /api/v1/echo/shares` — body `{ url | text, annotation?, content_type?, author_is_tenant? = false, surface? = "manual_quick_share" }`, exactly one of `url` (http/https only) or `text` (non-blank, at most `ECHO_SHARE_TEXT_MAX_CHARS`, 413 above). `content_type` is inferred when omitted (`youtube_video`, `youtube_short`, `instagram_reel`, `tweet`, `link`, `text_snippet`, ...) and must match `^[a-z][a-z0-9_]{0,63}$`. 201.
- `POST /api/v1/echo/shares/upload` — multipart `file` plus optional `annotation`, `content_type`, `author_is_tenant`, `surface`. Empty is 422; over `ECHO_SHARE_MAX_BYTES` (25 MB) is 413 and writes nothing. Stored as `ECHO_SHARES_DIR/<tenant>/<share id><ext>`; the client's filename is kept for display only. 201.
- `GET /api/v1/echo/shares` — `?state=pending|processed|skipped|failed&q=&limit=(1-500, 100)&offset=`; newest first; `q` matches text, annotation and payload (URL, filename). `{ items, total, limit, offset }`.
- `GET /api/v1/echo/shares/{id}`; `PATCH /api/v1/echo/shares/{id}` with any of `annotation` (`null` clears), `content_type`, `author_is_tenant`.
- `DELETE /api/v1/echo/shares/{id}` — removes the share's vector, file, derived facts and row. `{ deleted, vectors, files, derived_facts }`.
- `GET /api/v1/echo/shares/{id}/file` — the stored bytes, always `Content-Disposition: attachment` with `X-Content-Type-Options: nosniff`. A row whose path points outside its tenant directory is never followed (404).

### `GET /api/v1/echo/export`
The whole brain as one zip (S-3.10.1): `manifest.json` (format `pratidhvani-echo-archive`, version 1, export time, tenant, row counts per table, every file with size and SHA-256, any missing file), `personal_context.jsonl` and `shares_inbox.jsonl` (every column; datetimes ISO-8601 with offset), and `files/<stored path>`. Lossless: `services/echo_privacy_service.py::read_archive` is the exact inverse. Built in a temporary file and removed after sending. Audited (`echo_exported`, counts only). Notes and the library are not part of Echo; notes export at `/exports/notes.*`.

### `GET /api/v1/echo/brain/footprint`
What Echo holds for the caller in every store: `{ "rows": {"personal_context": n, "shares_inbox": n}, "files": n, "vectors": {"shares_global": n, "personal_context_global": n} }`.

### `DELETE /api/v1/echo/brain?confirm=delete-everything`
Deletes every Echo row, file and vector of the caller (S-3.10.2). Without the exact confirmation: 422 (missing) or 400 (wrong). Order: vectors, files, then rows in one commit; a failing store returns 500 naming it and leaves the rows that let a retry finish. Returns `{ deleted, removed: <footprint>, footprint_after: <footprint> }`; `footprint_after` is all zeros or the call fails. Audited (`echo_brain_deleted`, counts only). Irreversible; the library, notes, account and BYOK keys are untouched.

---

## Notes

All `/notes` endpoints require auth. Backend: `backend/app/routers/notes.py`, service `backend/app/services/note_service.py` (M5 / S-8.5.1). A note is the user's own Markdown on something they can see; it is private to its tenant from the first row. The plan is [`plans/m5-notes.md`](plans/m5-notes.md).

**Target types** (closed set, 422 otherwise): `document`, `job`, `qa_exchange`, `library_qa_exchange`, `qa_history_exchange`, `channel`, `knowledge_artifact`. **Motivations:** `commenting` (default), `highlighting`, `tagging`.

**Target checks.** Every write resolves the target through the tenant's visibility (documents, knowledge artifacts and channels, per D-063 / D-065) or ownership (jobs and the three exchange tables). A target the tenant cannot see and a target that does not exist both answer `404 {"detail": "Target not found"}`. A `knowledge_artifact` target additionally requires that extraction has run on the document.

**Document ids.** `document` and `knowledge_artifact` targets accept either the canonical `document_id` or the legacy YouTube `video_id`; the note is stored under `document_id`, so both forms address one note stream. Responses carry `target_video_id` for surfaces still keyed on the legacy id (goes away with D-070).

### Note shape
```json
{
  "id": "…", "target_type": "document", "target_id": "<document_id>",
  "body_md": "**Bold** claim.", "motivation": "commenting",
  "selector": {"type": "TextQuoteSelector", "exact": "…", "prefix": "…", "suffix": "…", "start_seconds": 83.5} | null,
  "created_at": "2026-10-19T11:24:45.598818Z", "updated_at": "…", "deleted_at": null,
  "target_label": "My video about tariffs", "target_video_id": "minevid0001",
  "target_parent_id": null
}
```
`selector` follows the W3C Web Annotation `TextQuoteSelector` plus `start_seconds` so a note can anchor to a transcript moment like a Q&A citation. Timestamps are UTC with an explicit offset. `target_label` is null once the target is gone (a deleted job); the note itself survives its target. `target_parent_id` is set for `qa_exchange` targets only (the job that holds the exchange).

### `GET /api/v1/notes`
Query params: `target` (`<target_type>:<id>`, scopes to one target; 404 when that target is not visible, 422 when malformed), `target_type`, `q` (substring filter on the body), `include_deleted` (default false), `limit` (default 500, max 2000), `offset`. Newest first. Returns `{ "items": [...], "total": n, "limit": l, "offset": o }`.

### `POST /api/v1/notes`
Body `{ "target_type", "target_id", "body_md", "motivation"?, "selector"? }`. `body_md` is non-blank and at most 20,000 characters. 201 with the note.

### `GET /api/v1/notes/{note_id}`
404 for a missing, deleted or foreign note alike.

### `PUT /api/v1/notes/{note_id}`
Partial update: any of `body_md`, `motivation`, `selector` (`null` clears it). `created_at` never changes; `updated_at` does.

### `DELETE /api/v1/notes/{note_id}`
Soft delete: sets `deleted_at` and returns `{ "deleted": true, "deleted_at": "…" }`. The row stays (exports carry deletions); it leaves every live read and list, so a second delete is 404.

---

## Admin

### `POST /api/v1/admin/restart`
Restart the running services (FastAPI, Celery, optionally Vite). Spawns a detached PowerShell trampoline that kills this process and relaunches it after a short delay so the 202 response can flush.

Query params:
- `skip_frontend` (bool, default `false`)
- `delay` (int, default `2`)

Returns 202 + `{ "status": "accepted", "message": "...", "skip_frontend": bool }`.

Returns 501 on non-Windows hosts (the trampoline is Windows-only today). Requires bearer token.

---

## WebSocket

### `WS /ws/jobs`
Multiplexed progress stream for jobs. The endpoint is mounted at the root, **not** under `/api/v1`.

After connecting, send subscribe/unsubscribe messages:

```json
// subscribe
{ "action": "subscribe", "job_id": "..." }
// unsubscribe
{ "action": "unsubscribe", "job_id": "..." }
```

The server publishes progress events for any subscribed job:

```json
{
  "job_id": "...",
  "type": "status_change" | "progress" | "log" | "completed" | "failed",
  "status": "extracting",          // when type == status_change
  "phase": "fetch_transcripts",    // when type == progress
  "completed": 12,                  // when type == progress
  "total": 25,                      // when type == progress
  "message": "..."                  // human-readable status
}
```

Heartbeats every 30 seconds (server pings, client pongs). Auth is enforced via the `?token=` query string at WS handshake (browsers cannot set `Authorization` headers on WebSocket connections).

---

## Conventions

- **Timestamps** are ISO 8601 UTC strings.
- **IDs** are UUIDs except `video_id` (YouTube native ID, 11 chars) and `channel_id` (YouTube channel ID, 24 chars).
- **Pagination** uses `limit` + `offset` (no cursor pagination today). Defaults vary per endpoint and are noted inline.
- **Empty lists** return `[]`, not `null`.
- **Errors** return `{ "detail": "..." }` with the appropriate HTTP status. 401 means missing/invalid token; 403 means valid token but insufficient privileges (rare today since all auth is binary); 404 means resource not found; 409 means conflict (e.g. knowledge already extracted); 422 is FastAPI's request-body validation error; 502 wraps a downstream LLM error; 429 is reserved for the YouTube quota hard-cap.

## Forward-compat

The shape above will evolve in three ways as the [feature-roadmap](feature-roadmap.md) lands:

1. **L1 Multi-source ingest.** Landed differently from this sketch: uploads and pasted URLs are library-scoped (`/library/upload-pdf`, `/library/paste-urls`) rather than new `job_type` values, per [D-069](decisions.md#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19). Still ahead: `VideoResponse` → `DocumentResponse` with `source_type`, and `video_id` path parameters becoming `document_id` (the legacy path stays as an alias for one release). See [source-types.md](source-types.md) and [D-070](decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19).
2. **L5 SaaS.** All resource paths gain an implicit `tenant_id` filter via the JWT claim. Public per-tenant aliases (e.g. `/t/{tenant_slug}/...`) appear for shared/published resources. See [saas-roadmap.md](saas-roadmap.md).
3. **L3 Personal Brain.** The context store, readiness gate and connector registry shipped under `/echo/*` (above), not `/brain/*`. Still ahead: activity stream, voice signals, and the "speak as me" agent. See [personal-brain.md](personal-brain.md).

---

## Cross-references

- Architecture & request lifecycles — [architecture.md](architecture.md)
- Frontend pages that consume these endpoints — [ui-pages.md](ui-pages.md)
- Vision and the trajectory the API will follow — [vision.md](vision.md)
- LLM use case registry behind the Q&A and knowledge endpoints — [CLAUDE.md](../CLAUDE.md) §LLM-configuration
