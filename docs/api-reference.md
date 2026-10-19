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
  }
}
```

### `GET /api/v1/health/llm`
Per-use-case LLM probe detail. Returns the result of the startup smoke check (deduped by `(provider, model)`).

```json
{
  "use_cases": [
    {
      "name": "qa_formulate_answer",
      "provider": "openai",
      "model": "gpt-5",
      "reasoning": "medium",
      "ok": true,
      "latency_ms": 412,
      "error": null
    }
    // ... 19 entries total
  ]
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
List the videos selected for this job. Returns `list[VideoResponse]`. Each row includes the per-job `approved` flag.

---

## Per-job Q&A and reports

### `GET /api/v1/jobs/{job_id}/report`
Serve the generated HTML report. Content-type `text/html`. Returns 404 if no report has been generated yet (channel jobs always have a stats-only report; subscription jobs never have one). Auth: bearer header **or** `?token=` query string (iframe-friendly).

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
  "answer_language": "English" // optional; default "English"
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
Ask a question across the entire library (no `video_id` filter). Runs `run_library_qa_agent`.

```json
// request
{ "question": "...", "answer_language": "English" }
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
    "job_titles": ["DNS basics", "Networking 101"]
  }
]
```

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

## Channels

All `/channels` endpoints require auth.

### `GET /api/v1/channels`
List all known channels (subscribed and unsubscribed). Returns `list[ChannelResponse]`.

### `GET /api/v1/channels/{channel_id}`
Fetch a single channel. Returns `ChannelResponse` or 404.

### `POST /api/v1/channels/{channel_id}/subscribe`
Mark a channel as subscribed. Optionally dispatches a sync job. Returns `SubscribeResponse` (channel + sync_job_id if dispatched).

### `POST /api/v1/channels/{channel_id}/unsubscribe`
Mark a channel as unsubscribed. Returns updated `ChannelResponse`. Does not delete videos already in the library.

### `POST /api/v1/channels/{channel_id}/sync`
Trigger a fresh subscription sync for the channel. Returns `SubscribeResponse` (channel + sync_job_id).

### `GET /api/v1/channels/{channel_id}/videos`
List videos for a channel from the global library. Returns `list[VideoResponse]`.

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
Fetch the stored knowledge artifact. Returns 404 if not yet extracted.

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

---

## Author Studio

All `/author` endpoints require `require_feature("author_studio")` (Pro and above); a lower tier gets 403. Backend: `backend/app/routers/author.py` (I-6, PR #173). Page: [`AuthorPage`](ui-pages.md#authorpage--author-pro).

### `GET /api/v1/author/kinds`
`{ "available": ["book"], "supported": ["book", "deck", "newsletter", "reel", "site"] }`. `available` lists kinds with a registered outputter; `supported` is every kind the schema accepts. Create a kind that is supported but not available and you get 501.

### `POST /api/v1/author/outputs`
Create and generate in one synchronous call. Body `{ "kind": "book", "title": "…", "source_ids": ["<job_id>", …], "parameters": { "include_qa": true, "include_toc": true } }`. For `book`, `source_ids` are job IDs, one chapter per run (its report, and its Q&A if `include_qa`); a run without a report yields a placeholder chapter. Returns the `OutputItem` in `completed` or `failed` state (`error_message` populated on failure). 400 unknown kind or empty title; 501 kind without an outputter, which leaves a `pending` row behind.

```json
{ "id": "...", "kind": "book", "title": "...", "status": "completed", "source_ids": ["..."], "parameters": {}, "error_message": null, "created_at": "...", "updated_at": "...", "has_content": true }
```

### `GET /api/v1/author/outputs`
List the caller's outputs. Query params: `kind`, `status` (`pending` / `generating` / `completed` / `failed`).

### `GET /api/v1/author/outputs/{output_id}`
One output; 404 for another user's (existence-leak posture).

### `GET /api/v1/author/outputs/{output_id}/content`
The generated text as `text/markdown` for books, `text/plain` otherwise. 404 when the row has no content yet. Header-auth only, so a browser download goes through a fetch and a blob, not an `<a href>`.

### `DELETE /api/v1/author/outputs/{output_id}`
`{ "deleted": true }`; 404 if absent.

---

## Echo

All `/echo` endpoints require `require_feature("echo_personal_brain")` (Studio only). Backend: `backend/app/routers/echo.py` (I-3, PR #172). Page: [`EchoPage`](ui-pages.md#echopage--echo-studio).

### `GET /api/v1/echo/status`
Cold-start readiness: `{ "ready": false, "total_rows": 1, "distinct_sources": 1, "has_personality_trait": true, "threshold_total": 100, "threshold_sources": 3 }`. `ready` is the AND of the three gates.

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
