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

### `GET /api/v1/channels/{channel_id}/videos`
The caller's visible documents from the channel, newest first (`limit`, `offset`). Returns `list[VideoResponse]`. The channel page lists documents through `GET /library/videos?channel_id=` instead, because those rows carry `job_count` / `job_titles`; both routes scope to the same visible set.

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
The union of the documents selected by the shelf's jobs, each once, filtered through the caller's visibility (D-063). Takes the library listing's `search`, `language`, `channel_id`, `transcript_status`, `sort`, `limit`, `offset` and returns the same `LibraryVideoResponse[]` rows (with `job_count` / `job_titles` across all the caller's runs). **An empty shelf returns `[]`, never the whole library.** Any tier.

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
Create and generate in one synchronous call. Body `{ "kind": "book", "title": "…", "source_ids": ["<job_id>", …], "parameters": { "include_qa": true, "include_toc": true } }`. For `book`, `source_ids` are job IDs **of the caller's own runs** (another tenant's id reads like a missing one), one chapter per run: its report's Markdown source (S-6.1.2) with headings demoted under the chapter heading, and its Q&A if `include_qa`; a run without a report, or whose file is missing, yields a disclosed placeholder chapter. An empty `source_ids` for `book` is 400 and writes no row. Returns the `OutputItem` in `completed` or `failed` state (`error_message` populated on failure). 400 unknown kind or empty title; 501 kind without an outputter, which leaves a `pending` row behind.

```json
{ "id": "...", "kind": "book", "title": "...", "status": "completed", "source_ids": ["..."], "parameters": {}, "error_message": null, "created_at": "...", "updated_at": "...", "has_content": true, "word_count": 4210 }
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
Cold-start readiness: `{ "ready": false, "total_rows": 1, "distinct_sources": 1, "has_personality_trait": true, "threshold_total": 100, "threshold_sources": 3, "notes_total": 4, "notes_words": 120 }`. `ready` is the AND of the three gates. `notes_total` / `notes_words` (S-8.5.3) count the caller's live notes as the Domain 3 feeder; they are reported, not gated, until S-3.5.1 sets the voice floor.

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
