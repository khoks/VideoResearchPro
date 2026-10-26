# Pratidhvani — API Reference

**Status:** canonical (2026-04-24, last refreshed 2026-10-19). This is the **single source of truth** for the REST and WebSocket API. All other docs link here rather than duplicating endpoint lists.

The API is mounted under `/api/v1/` (except the WebSocket, which is mounted at the root). All HTTP responses are JSON (content-type `application/json`) unless explicitly noted otherwise (HTML for reports, NDJSON for dataset exports). Authentication is via `Authorization: Bearer <jwt>` for everything except `/auth/register`, `/auth/login`, and `/health` family endpoints. No HTTP route accepts the JWT as a `?token=` query string (retired 2026-10-25, T-8.8.1.5, [D-085 addendum](decisions.md#d-085--reading-room-reports-stay-html-sanitised-and-parsed-in-the-browser-one-shared-citation-card-fed-by-the-runs-documents-2026-10-19)): a browser fetches files with the header and opens or saves them from a blob: URL. The `/ws/jobs` WebSocket is the one exception, since a WebSocket handshake cannot carry headers.

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

409 when the address already has an account. 403 when the address is listed in `ADMIN_EMAILS` ([D-111](decisions.md#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)): a listed address makes its holder an operator and this route verifies no email, so the detail tells the operator to register the account before listing it. Google or GitHub sign-in with that address, verified by the provider, still creates it (`GET /auth/oauth/{provider}/callback`), and an unverified one is refused there with the usual 401.

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
{ "id": "...", "email": "...", "created_at": "...", "tier": "free", "onboarded_at": null, "is_operator": true }
```

`onboarded_at` (S-8.10.1) is set when the first-run wizard is finished. `is_operator` (T-5.2.8, [D-111](decisions.md#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)) says whether the caller operates this install: their email is in `ADMIN_EMAILS` (comma-separated, case-insensitive), or, when that is empty, theirs is the earliest-registered account. The Subscription page offers the tier switch only when it is true.

### `PUT /api/v1/auth/me/tier`
Switch the caller's tier (mock payment, [D-050](decisions.md#d-050--self-service-tier-flip-with-mock-payment-until-e-53-stripe-ships-2026-05-15)). **Operator only** since T-5.2.8 ([D-111](decisions.md#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)): any other account gets 403 `Only this install's operator can do this.` and nothing changes. Body `{ "tier": "free" | "pro" | "studio", "mock_payment"?: {...} }` (`mock_payment` is accepted and ignored); 422 for another tier. Returns `{ "tier", "message", "mock_payment_mode": true }` and writes a `tier_changed` audit event.

### `GET /api/v1/auth/me/onboarding`
The first-run wizard's state for the caller (S-8.10.1). `state` is the default when the wizard was never touched. Milestones are derived on read: `jobs` counts the caller's runs, `first_job` is the run the wizard started (else the oldest), `report_opened` is whether a `first_report_opened` audit event exists. `should_onboard` is what `/` uses: false once `onboarded_at` is set or the wizard was skipped; true once it was started; otherwise true only for an account with no runs.

```json
{
  "onboarded_at": null,
  "state": {
    "step": 2,
    "choices": { "channels": ["@3blue1brown"], "first_job_id": null },
    "dismissed": false,
    "started_at": "2026-10-19T20:31:02+00:00",
    "completed_at": null,
    "dismissed_at": null,
    "checklist_dismissed": false,
    "checklist_dismissed_at": null
  },
  "started": true,
  "milestones": { "jobs": 0, "first_job": null, "report_opened": false, "questions": 0 },
  "should_onboard": true
}
```

### `PATCH /api/v1/auth/me/onboarding`
Merge a change into the caller's state; returns the same shape as `GET`. Every field is optional and unknown fields are a 422. `step` is 1 to 3. `channels` replaces the list (at most five; trimmed, de-duplicated, blanks dropped). `first_job_id` must be one of the caller's runs, else 404. `completed: true` sets `onboarded_at`; `dismissed: true` records a skip; `checklist_dismissed: true` hides the jobs page's first-run checklist (S-8.10.2) and, unlike every other field, does not start the wizard. The first PATCH that touches the wizard writes `started_at`. `milestones.questions` counts the caller's questions on runs, the library and the history chat. Audit events, each once per account: `onboarding_started`, `onboarding_completed`, `onboarding_skipped`; `first_job_created` is written by `POST /jobs` and `first_report_opened` by `GET /jobs/{id}/report/body`.

```json
// request
{ "step": 3, "first_job_id": "..." }
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
Serve the generated HTML report. Content-type `text/html`. Returns 404 if no report has been generated yet (channel jobs always have a stats-only report; subscription jobs never have one). Auth: bearer header **only**. Kept for the job page's quick-peek modal and its "Open in new tab", which fetch it with the header and show it from a blob: URL (sandboxed iframe, scripts blocked by a CSP meta tag); the reader uses the body route below. Until T-8.8.1.5 (2026-10-25) it also took `?token=` for the iframe; a query token now gets 401.

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

**Reference shapes.** References are polymorphic by `source_type` (`video`, `reddit_post`, `hn_story`, `pdf`, `article`, ...) and every field the agent emits is returned; until S-8.5.2 the response schema kept only the YouTube fields. **Notes (S-8.5.2):** when the answer uses one of the asker's own notes, the reference is `{ "source_type": "note", "note_id", "note_target_type", "note_target_id", "note_target_label", "note_target_parent_id", "note_created_at", "quote", "video_title": "Your note of <date> on <target>", "channel_name": "you", ... }` with empty URL fields. Job Q&A draws notes on the job's own material; library Q&A (same reference shape) draws every note of the asker.

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
  "created_at": "...",
  "scope": null
}
```

`scope` (S-8.1.4, [D-095](decisions.md#d-095--scoped-library-questions-one-history-table-with-a-scope_json-object-narrowing-and-provenance-keys-unknown-keys-refused-2026-10-19)) is what the question was asked over: `null` for the whole library (this endpoint always), or an object such as `{"shelf_id": "…"}` for a question asked on a shelf. Narrowing keys (`shelf_id`) only ever restrict the reader's visible documents, and a scope with no documents retrieves nothing; provenance keys (`saved_search_id`, M3) record where an exchange came from. Unknown keys from newer builds may appear; clients keep them and do not interpret them. Shape: `backend/app/schemas/qa_scope.py`.

### `GET /api/v1/library/qa`
Library Q&A history. Query params: `limit` (default 100), `offset` (default 0). Ordered ascending by `created_at`. Returns `list[LibraryQAResponse]`, every exchange whatever its scope, each with its `scope` (a malformed stored value reads as `null`).

### `DELETE /api/v1/library/qa/{exchange_id}`
Delete a single library Q&A exchange. Returns 204. (The matching `qa_library_global` Chroma entry is left as orphan; cleanup is a maintenance task, not a request-time concern.)

### `GET /api/v1/library/graph`
The reader's library as a graph (S-8.9.1, [M9 plan](plans/m9-citation-graph.md)). Built from **the documents the caller can see** (D-063 / D-070): nothing of another reader's (a document, an answer, a channel, a topic) can appear, and an empty visible set is an empty graph.

Query: `focus` (a node id: its neighbourhood to `depth` hops, 1–3; an unknown id falls back to the global view) · `shelf_id` / `job_id` / `channel_id` (narrow the documents; a shelf or job that is not the caller's is a **404**; an empty shelf is an empty graph) · `types` (comma list of `channel`, `topic`, `exchange` besides documents) · `limit` (default 300, max 2,000).

```json
{
  "nodes": [{ "id": "document:…", "type": "document", "label": "…", "degree": 4,
              "meta": { "document_id": "…", "url": "…", "source_type": "video", "channel_id": "UC…", "published_at": "…" } },
            { "id": "channel:UC…", "type": "channel", "label": "…", "degree": 12, "meta": { "channel_id": "UC…" } },
            { "id": "topic:monetary policy", "type": "topic", "label": "Monetary policy", "degree": 9, "meta": { "documents": 8 } },
            { "id": "exchange:library:…", "type": "exchange", "label": "the question", "degree": 3, "meta": { "kind": "library", "exchange_id": "…", "job_id": null } }],
  "edges": [{ "source": "document:…", "target": "channel:UC…", "type": "published_by", "weight": 1 }],   // published_by | about | cites | co_occurs
  "truncated": true,
  "total": { "documents": 312, "channels": 6, "topics": 48, "exchanges": 20 },
  "shown": { "documents": 230, "channels": 6, "topics": 44, "exchanges": 20 },
  "summary": "Showing 230 documents, 44 topics, 6 channels and 20 of your answers. 300 of 386 nodes are shown, the most connected first. They form 3 connected groups; the largest holds 290 nodes, mostly about …",
  "focus": null
}
```

Ids are stable across requests. Topics come from knowledge reports and need at least two of the caller's documents; `co_occurs` links topics sharing at least two documents (the five strongest per topic). Answers are the caller's own job and library exchanges that cite at least one visible document. Under the cap, nodes are chosen by degree, then recency (the focus always first). `summary` is the textual alternative to the canvas. Computed per request: about 0.07 s at 2,000 documents and 500 answers.

An absent or empty `types` means every type, so a client that wants sources only sends `types=document` (the library map does, S-8.9.2). The map asks for `limit=300`.

### `GET /api/v1/library/video-channels`
`?video_ids=a,b,c` → `{ "<video_id>": { "channel_id": "UC…", "channel_name": "…" } }` (S-8.7.4). Maps cited YouTube videos to their channel so a citation chip can link to the channel page. Only videos the caller can see answer; unknown or invisible ids are simply absent (never an error, never a hint that another reader holds them). At most 200 distinct ids per call. Resolved at read time, so every existing answer gains the link without changing stored references. The frontend batches every chip on screen into one call.

### `GET /api/v1/library/videos`
Browse the global, deduplicated video library. Returns `list[LibraryVideoResponse]`. Each row aggregates `job_count` and `job_titles[]` across `job_videos → jobs` so the UI can show "appears in N research runs" without follow-up requests.

Query params:
- `search` — free-text match across video title and channel name (ILIKE).
- `language` — exact transcript language code (e.g. `en`, `hi`).
- `channel_id` — restrict to one channel.
- `transcript_status` — one of `fetched`, `pending`, `unavailable`.
- `tag` — a tag id; only documents carrying it (S-8.1.3). Another reader's tag id matches nothing.
- `document_id` — one document (S-8.2.2; where a search result for a source lands). Inside the visibility scope, so another tenant's id returns `[]`.
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
Serves the uploaded bytes (`application/pdf`) for the document whose `source_id` is `pdf:<digest>`; 404 if the document or the file is missing. Citations deep-link here with `#page=N`. The route sits under the router-level bearer-auth dependency and does **not** accept `?token=`, so a plain link or a new tab 401s; the frontend fetches the bytes with the header and opens a blob URL, keeping the `#page=N` fragment — from the Library row and, since T-8.8.1.5, from every PDF citation.

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
    { "type": "knowledge", "items": [{ "id": "<document_id>", "title": "…", "subtitle": "Knowledge report · Channel", "href": "/knowledge/<document_id>", "score": 0.8 }] }
  ]
}
```

Groups come back in that fixed order, only the requested ones, each possibly empty. Every group is scoped to the caller — jobs by `tenant_id`, documents and knowledge by `document_visibility` keyed on `document_id` (D-070), channels by subscription or a visible document, Q&A by `tenant_id` on each of the three exchange tables — so a tenant who has ingested nothing gets empty groups, never everything (D-063). `score` is higher-is-better (`-bm25`, title weighted over body, recency tie-break); on the `like` backend every score is `0.0` and items are ordered by recency. `backend` is the engine used for *this* query: `like` also when FTS5 is present but every token is shorter than three characters. Q&A hrefs carry `?exchange=<id>` on the originating page (`/jobs/<job_id>`, `/library/qa`, `/qa-history`), which scrolls to and focuses that exchange. Document hrefs carry `?document=<document_id>` on `/library` (the canonical id, because most non-video documents have no `video_id`), which narrows the list to that row through `GET /library/videos?document_id=`. Knowledge hrefs open the reader at `/knowledge/<document_id>` (S-8.8.3) since S-8.2.2.

---

## Question suggestions

### `GET /api/v1/suggestions?context=`
"You might ask…" for one context (S-8.4.1, plan [m4-question-suggestions](plans/m4-question-suggestions.md)). `context` is `job:<id>` (a completed run of the caller's), `document:<id>` (a source the caller can see; the YouTube id or `document_id`) or `library`. Returns up to five questions from two pools: **generated** from a summary of the context (report headings, knowledge topics, source titles) by `qa_suggest_questions`, and **history**, the caller's own nearest past questions from `qa_library_global` (tenant-filtered; exchanges on this same context are skipped). Both are de-duplicated against what was already asked on the context and against each other, then diversified with maximal marginal relevance. Cached per (caller, context) for `SUGGESTIONS_CACHE_TTL_MIN` minutes or until the context changes (a new exchange, report or knowledge state). When the generator's probe failed or the call fails, the response carries history items only, `generated: false`, and is not cached. A context with no sources (an empty library) returns an empty list without a model call. Every response records a `suggestion_shown` audit event. 422 for a malformed context, 404 for one the caller cannot see, 400 for a run that has not finished.

```json
{
  "context": "job:…",
  "suggestions": [
    { "question": "…", "rationale": "…", "source": "generated", "origin": null },
    { "question": "…", "rationale": "You asked this in another run; ask it here too.", "source": "history",
      "origin": { "source": "job", "exchange_id": "…", "job_id": "…" } }
  ],
  "cached": false,
  "generated": true
}
```

### `POST /api/v1/suggestions/feedback`
A suggestion was used. Body `{context, question, action: "fill" | "ask", source?}` (unknown fields 422); 204. Records `suggestion_clicked` with the context, action, source and question, for your own contexts only (404 otherwise).

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
  "source_weight": 1.0,             // the caller's trust weight, 0.0-2.0, 1.0 neutral; set with PUT /channels/{id}/weight (D-068)
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

### `PUT /api/v1/channels/{channel_id}/weight`
Set the caller's trust weight for the channel ([D-068](decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18), S-7.1.1). Body `{"weight": <0.0-2.0>}`; 1.0 is neutral. Returns the updated `ChannelResponse`; 422 outside the range, 404 for an unknown channel. Only the caller's `channel_subscriptions` row changes, so no other tenant's ranking moves.

The weight re-ranks the caller's **job and library Q&A** retrieval: 3 × top-K candidates, drop any over `RAG_DISTANCE_THRESHOLD` on the raw distance, sort by `distance / weight`, keep top-K. 0.0 is clamped to 0.05 at query time; sources without a channel weigh 1.0. It is never a filter and never stored on chunks. Measured effect and its relevance cost: [notes/2026-10-19-e71-trust-weighting-measurement.md](notes/2026-10-19-e71-trust-weighting-measurement.md).

### `POST /api/v1/channels/{channel_id}/sync`
Dispatch a fresh subscription sync for the channel. Returns `SubscribeResponse`.

### `GET /api/v1/channels/{channel_id}/intelligence`
What the channel says, over **the documents of it the caller can see** (S-8.7.2, [M7 plan](plans/m7-channel-intelligence.md); D-063 / D-070). Two readers following the same channel can get different figures; a reader who can see none of its documents gets an empty aggregate, never the channel's global one. 404 for an unknown channel.

`?refresh=true` forces a recompute. Otherwise the document-derived part is served from a per-(channel, reader) cache (`channel_intelligence_cache`) until its fingerprint changes: a new visible document, new knowledge on one, a new transcript. The `qa` part is always computed live. Computed in the request (about 1.6 s cold at 500 documents, about 15 ms cached), not in the solo Celery worker, which is often busy with ingest for hours.

```json
{
  "channel_id": "UC…", "computed_at": "…", "cached": true,
  "coverage": { "documents": 120, "with_knowledge": 30, "without_knowledge": 90, "ratio": 0.25, "with_transcript": 118,
                "extractable": [{ "id": "…", "title": "…", "url": "…" }] },   // no knowledge yet, transcript cached: what the batch action runs over
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

## Saved searches

Pinned library questions re-asked on a schedule (S-8.3.2, plan [m3-saved-searches-alerts](plans/m3-saved-searches-alerts.md)). Every route acts on the caller's own rows and needs the `saved_searches` tier feature (Pro and Studio; 403 otherwise). The schedule is a `scheduled_runs` row of kind `saved_search` (S-8.3.1) the service keeps in step: created, re-cadenced, paused and deleted with the saved search.

### `GET /api/v1/saved-searches`
`{items: [SavedSearch], active, cap}`: newest first; `active` counts enabled rows and `cap` is the tier's limit on them (`saved_searches_active_cap`: Pro 10, Studio 50, Free 0; `-1` = unlimited).

```json
{
  "id": "…",
  "question": "What do my sources say about rate cuts?",
  "answer_language": "en",
  "scope": null,
  "cadence": { "cadence": "weekly", "hour": 9, "minute": 0, "weekday": 0, "timezone": "Europe/London" },
  "next_run_at": "2026-10-26T08:00:00",
  "notify_email": true,
  "enabled": true,
  "created_at": "…",
  "last_run_at": "…",
  "last_status": "ok",
  "last_error": null,
  "last_success_at": "…",
  "last_exchange_id": "…",
  "last_answer": "…"
}
```

Times are naive UTC. `next_run_at` is null while paused. `last_status` is `ok`, `failed`, `quota_exceeded` (the month's library-question quota was used up, so the run was skipped before any spend, D-045), `feature_unavailable` (the tier no longer has the feature) or `scope_missing` (the shelf was deleted); every status but `ok` leaves the last answer in place.

### `POST /api/v1/saved-searches`
Body `{question, cadence, answer_language?, scope?, notify_email?}`, unknown fields 422; 201 with the saved search. `cadence` is `daily`, `weekly` (with `weekday`, 0 = Monday) or `monthly` (with `day_of_month` 1 to 28), an `hour`, optional `minute`, and an IANA `timezone` (default UTC); `every` is for system kinds and is refused. `scope` is null (the whole library) or `{"shelf_id"}` for one of the caller's shelves (404 otherwise): the library-question scope of S-8.1.4, resolved by `qa_scope_service`. 409 when the tier's active cap is reached.

### `GET` / `PATCH` / `DELETE /api/v1/saved-searches/{id}`
PATCH accepts any of the create fields plus `enabled`; a new cadence recomputes `next_run_at`; resuming checks the cap (409) and moves a slot that passed while paused to the next one. DELETE removes the schedule too; past answers stay in library Q&A. Another tenant's id is a 404.

### `POST /api/v1/saved-searches/{id}/run-now`
Queues one run on the caller's tier queue outside the schedule; 202 `{status: "queued"}`. The quota is checked here as well as in the run, so an exhausted month answers 429 at once. A run asks the library Q&A agent over the caller's visible set (narrowed to the shelf's runs' approved documents when scoped, never widened when that is empty), with corpus statistics and trust weights as `POST /library/qa` passes them, records the quota, stores a `library_qa_exchanges` row (indexed in `qa_library_global`, `scope_json` = the scope plus `saved_search_id`) and updates the saved search's baseline: answer hash, cited document set, last exchange.

### `GET /api/v1/saved-searches/{id}/runs`
The last 20 runs, newest first (S-8.3.3). Each: `ran_at`, `trigger` (`schedule` / `manual`), `status` (the saved-search statuses plus `no_new_sources`, the gate's skip), `exchange_id`, `previous_exchange_id`, `changed` (null on the first run, which sets the baseline, and on runs that did not answer), `jaccard` and `embedding_distance` (the two signals), `decided_by` (`none` / `agreed` / `judged` / `judge_failed`), `added_reference_ids`, `dropped_reference_ids`, `diff_summary`.

**How a run decides it changed** ([pre-registered thresholds](notes/2026-10-19-saved-search-change-thresholds.md)): (1) a scheduled run whose scope resolves to the same document set as the last good run is skipped (`no_new_sources`, no quota, no model); Run now always asks. (2) After answering, the cited-set Jaccard below `SAVED_SEARCH_JACCARD_THRESHOLD` (0.50) or the answer-embedding cosine distance above `SAVED_SEARCH_EMBEDDING_THRESHOLD` (0.15) votes "changed". (3) When exactly one votes, `saved_search_judge` decides and writes the sentence; if it fails, the citation vote decides. A change writes a notification (`saved_search_changed`, `href` `/saved-searches?search=<id>&run=<run_id>`) and, when `notify_email` is on, an email through `email_service` linking to `APP_BASE_URL` + that path.

---

## Notifications

In-app notices for the caller (S-8.3.3). No tier gate; today's only producer is a saved search whose answer changed.

### `GET /api/v1/notifications?unread_only=&limit=`
`{items: [{id, kind, title, body, href, read_at, created_at}], unread}`: newest first, `limit` 1 to 100 (default 30); `unread` counts every unread notice whatever the filter.

### `PATCH /api/v1/notifications/{id}`
Body `{read: true | false}`; another tenant's id is a 404.

### `POST /api/v1/notifications/read-all`
Marks every unread notice read; `{marked}`.

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

### `POST /api/v1/shelves/{shelf_id}/qa`
Ask the library agent over this shelf's documents only (S-8.1.4): the documents selected by the shelf's runs, within what the caller can see. Request and response are `POST /library/qa`'s; the response's `scope` is `{"shelf_id": "…"}` and the exchange joins the library Q&A history and the Q&A library index. **An empty shelf retrieves nothing**, never the whole library, and a citation outside the shelf is dropped from the answer. The asker's notes (S-8.5.2) follow the same scope: only notes on the shelf's runs, their documents, knowledge reports, answers and channels, and on the shelf's earlier answers. A shelf that is not the caller's is a **404** and runs nothing. Any tier; the library Q&A quota applies (429 when spent).

### `GET /api/v1/shelves/{shelf_id}/qa`
The caller's questions asked on this shelf (including saved-search runs scoped to it), oldest first, as `LibraryQAResponse[]`. `limit` (default 100, max 500), `offset`. 404 for a shelf that is not the caller's.

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

### Frames (S-1.18.2, R1)

A frame is as private as its document: each route resolves the document through the caller's visibility grants, and a document they cannot see 404s exactly like a missing one. The path segment may be the YouTube `video_id` or the `document_id`.

#### `GET /api/v1/videos/{video_id}/frames`
The document's captured frames in time order: `{document_id, video_id, visual_enabled, in_progress, frames: [{frame_id, timestamp_seconds, timestamp_display, description, informative, status, width, height, has_image}]}`. `visual_enabled` mirrors the install switch (`VISUAL_ENABLED`); stored frames are listed whatever it says. `in_progress` is true while an on-demand capture runs, so a client polls until it clears.

#### `GET /api/v1/videos/{video_id}/frames/{frame_id}/image`
One still as `image/jpeg` (`Cache-Control: private, max-age=86400`). 404 for a frame of another document, for a stored path outside `VISUAL_FRAMES_DIR` (traversal guard), and for a missing file. Report routes take no token in a URL (D-079), so the frontend fetches the bytes with the bearer header and shows them through an object URL.

#### `POST /api/v1/videos/{video_id}/extract-frames`
Queues select → capture → describe → persist for one document on the worker (`visual.extract_frames`) and returns **202** `{status: "queued", document_id}`. `?force=true` recaptures. Errors:
- 503: the install switch is off, or the vision models failed their startup probe;
- 422: not a YouTube video, or no transcript;
- 409: frames exist and `force` is omitted, or a capture is already running;
- 429: the monthly `visual_extractions` quota is spent (free 2, Pro 30, Studio 300; D-096). The quota is charged only when frames were actually captured.

---

## Dataset exports

All `/exports` endpoints require auth, bearer header only: until T-8.8.1.5 (2026-10-25) they also took `?token=` for plain download links; a query token now gets 401, and the frontend fetches each file with the header and saves it from a blob: URL. Each returns `application/x-ndjson` (one JSON object per line) via `StreamingResponse`. Memory stays constant on the server for arbitrarily large exports.

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
The caller's notes as W3C Web Annotations, one JSON-LD object per line under the `http://www.w3.org/ns/anno.jsonld` context, oldest first (S-8.5.3). Withdrawn notes are included with their `deleted` timestamp; `?include_deleted=false` leaves them out. Lossless: `services/note_export_service.py::parse_note_jsonld` is the exact inverse. Bearer header only, like the other exports.

```json
{"@context":"http://www.w3.org/ns/anno.jsonld","id":"urn:uuid:…","type":"Annotation","motivation":"highlighting",
 "created":"2026-10-01T09:01:00+00:00","modified":"…","generator":{"type":"Software","name":"Pratidhvani"},
 "body":{"type":"TextualBody","value":"…markdown…","format":"text/markdown"},
 "target":{"id":"urn:pratidhvani:document:<document_id>","type":"document","label":"…","selector":{"type":"TextQuoteSelector","exact":"…","start_seconds":83.5}},
 "deleted":null,"pratidhvani":{"version":1,"target_type":"document","target_id":"…","target_video_id":"…"}}
```

### `GET /api/v1/exports/notes.md`
The same notes as a Markdown document (`text/markdown`): `## <target type>` → `### <target label>` with the raw `type:id` key → `#### <date>` per note, body verbatim, every column in an HTML comment, withdrawn notes marked in the heading. Same `include_deleted` handling and header-only auth.

---

## Author Studio

All `/author` endpoints require `require_feature("author_studio")` (Pro and above); a lower tier gets 403. Backend: `backend/app/routers/author.py` (I-6, PR #173). Page: [`AuthorPage`](ui-pages.md#authorpage--author-pro).

### `GET /api/v1/author/kinds`
`{ "available": ["book", "deck", "newsletter", "site"], "supported": ["book", "deck", "newsletter", "reel", "site"], "formats": { "book": { "available": ["md", "epub"], "unavailable": { "pdf": "PDF export needs a converter on the server. Install one …" }, "pdf_engine": null } } }`. `available` lists kinds with a registered outputter; `supported` is every kind the schema accepts. Create a kind that is supported but not available and you get 501. `formats` (S-6.1.5) says, per available kind, which downloads this server can build and why any other cannot: a book's PDF needs WeasyPrint or Chromium (`backend/requirements-author.txt`), and `pdf_engine` names the one in use.

### `POST /api/v1/author/outputs`
Create the row and queue its generation in the worker (S-6.7.1). Body `{ "kind": "book", "title": "…", "source_ids": ["<job_id>", …], "parameters": { "include_qa": true, "include_toc": true } }`. For `book`, `source_ids` are job IDs **of the caller's own runs** (another tenant's id reads like a missing one), one chapter per run: its report's Markdown source (S-6.1.2) with headings demoted under the chapter heading, and its Q&A if `include_qa`; every citation becomes its working link plus a numbered GFM footnote, listed under `## Endnotes` with title, channel, timestamp and URL (S-6.1.4; footnote `n` is `GET …/citations` position `n`), and Q&A answers cite from their stored references; a run without a report, or whose file is missing, yields a disclosed placeholder chapter. An empty `source_ids` for `book` is 400 and writes no row. Returns the `OutputItem` at once in `pending` state with `celery_task_id` set; the worker (`author.generate_output`, on the owner's tier queue) publishes status changes and per-chapter progress on the `/ws/jobs` socket under the **output's id** (subscribe to it like a job id; the server checks the caller owns it). `?sync=true` generates inside the request and returns the finished row (`completed` or `failed`), the path tests and scripts use. If the broker is unreachable the row is returned `failed` with `Could not queue generation: …`. For `newsletter` (S-6.4.1), there are no `source_ids`; `parameters` take `since` and `until` (ISO 8601; `since` defaults to the caller's last issue, else seven days back) and `sections` (`featured`, `library`, `knowledge`, `questions`, `saved_searches`, `outputs`; `featured` is the only model-written part and is off by default, [D-097](decisions.md#d-097--newsletter-featured-section-ships-opt-in-the-rest-of-an-issue-is-listed-from-the-database-2026-10-19)). The output is the issue as Markdown and as a self-contained HTML email (`format=html`). An issue with nothing new in its enabled sections ends with status **`skipped`**, with the reason in `progress_message`. For `site` (S-6.2.1), `source_ids` name shelves and runs (`shelf:<id>`, `job:<id>`, or a bare run id), resolved inside the caller's library; the output is a zip of static pages (`format=zip`) that opens from disk, plus a Markdown contents page (`format=md`). No model is called. For `deck` (S-6.3.1), `source_ids` are the caller's own runs and there are no parameters: one `author_deck_outline` call plans 3 to 15 content slides from the reports, and the output carries a PPTX (`GET …/download?format=pptx`) and a Markdown rendering (`format=md`); every content slide cites at least one linked source (in its notes and on the closing sources slide), a slide citing none is left out and counted on the last slide, and `GET …/citations` lists one row per cited moment. A deck whose plan cites nothing, or whose call fails, is `failed` with the reason. A book's `parameters.cohesion` (S-6.1.3: `none` default, `light`, `full`) adds model-written framing around the unchanged chapters, disclosed in the front matter; the row's `usage` then carries each call's model, tokens and cost. A book's `parameters.formats` (S-6.1.5) picks the files built beside the Markdown, from `epub` and `pdf`; without it a book gets EPUB, plus PDF when the server has a converter. The resolved list is written back into `parameters` (`["md", "epub", "pdf"]`). 400 unknown kind, empty title or unknown format; 501 kind without an outputter, or `pdf` asked for on a server with no PDF converter (the detail says what to install), in both cases before any row is written.

```json
{ "id": "...", "kind": "book", "title": "...", "status": "pending", "source_ids": ["..."], "parameters": {}, "error_message": null, "created_at": "...", "updated_at": "...", "has_content": false, "word_count": null, "progress_pct": 0, "progress_message": "Queued", "celery_task_id": "...", "formats": [], "citation_count": 0 }
```

### `GET /api/v1/author/outputs`
List the caller's outputs. Query params: `kind`, `status` (`pending` / `generating` / `completed` / `failed` / `cancelled` / `skipped`; `skipped` is a newsletter with nothing new, S-6.4.1). A `pending` row with no `celery_task_id` predates S-6.7.1 and will never run.

### `POST /api/v1/author/outputs/estimate`
What generating an output would cost before it runs (S-6.1.3). Same body as create. Writes nothing. For a book with `parameters.cohesion` of `light` or `full`: `{ "cohesion": "full", "calls": [{ "use_case": "author_book_outline", "provider": "openai", "model": "gpt-5.5", "reasoning": "medium", "input_tokens": 3436, "output_tokens": 1800, "cost_usd": 0.069 }, …], "cost_usd": 0.12, "pricing_as_of": "…" }`; with `none` (the default), no calls and `cost_usd` 0. `cost_usd` is null when a resolved model has no published pricing. 400 for an unknown cohesion level; 501 for a kind with no outputter.

### `POST /api/v1/author/outputs/{output_id}/cancel`
Cancel a `pending` or `generating` output (S-6.7.1), mirroring `/jobs/{id}/cancel`: revokes the task and marks the row `cancelled`, publishing the change on the socket. Generation also stops at the outputter's next progress report, because a solo-pool worker cannot be interrupted mid-task, and a cancel that lands after the last report still wins over `completed`. Returns the `OutputItem`. 404 for another user's output; 400 once it is `completed`, `failed` or `cancelled`.

### `GET /api/v1/author/outputs/{output_id}`
One output; 404 for another user's (existence-leak posture).

### `GET /api/v1/author/outputs/{output_id}/download`
The output as a file (S-6.7.2). `format` (optional, `[a-z0-9]{1,8}`) picks one of the row's `formats`; without it the first is served, which is the text (`md` for a book) when there is one. Text comes from `content_text`; binary artifacts (`pdf`, `epub`, `pptx`, `zip`, …) from `<OUTPUTS_DIR>/<user_id>/<output_id>/artifact.<format>`, always derived from the row's own ids. Media type by format; `Content-Disposition: attachment; filename="<ascii>"; filename*=UTF-8''<title-slug>.<format>`. 404 for another user's output, an output with no content, or a format it does not have (the detail lists what is available); 422 for a malformed `format`. **Header-bearer only** (D-079): a `?token=` does not authenticate it.

### `GET /api/v1/author/outputs/{output_id}/citations`
Every source the output cites, in output order (S-6.7.3): `[{ "position": 1, "label": "0:00", "url": "https://www.youtube.com/watch?v=…&t=0", "seconds": 0, "document_id": "…", "source_type": "video", "source_id": "…", "resolved_by": "title", "title": "…", "channel_name": "…" }]`. `resolved_by` is `video_id`, `url`, `title` or `channel`, or null when no library document visible to the caller matched; an unmatched bare `&t=` anchor then has no `url`. 404 for another user's output. `OutputItem.citation_count` carries the count on every output response.

### `GET /api/v1/author/outputs/{output_id}/content`
The generated text as `text/markdown` for books, `text/plain` otherwise. 404 when the row has no content yet. Header-auth only, so a browser download goes through a fetch and a blob, not an `<a href>`.

### `DELETE /api/v1/author/outputs/{output_id}`
`{ "deleted": true }`; 404 if absent.

### `GET /api/v1/author/newsletter`
The caller's digest subscription (S-6.4.2), or `{ "subscription": null }`:

```json
{ "subscription": { "id": "...", "title": "Your library digest", "cadence": { "cadence": "weekly", "weekday": 0, "hour": 8, "minute": 0, "timezone": "UTC" }, "sections": { "featured": false, "library": true, "knowledge": true, "questions": true, "saved_searches": true, "outputs": true }, "enabled": true, "last_issue_at": null, "next_issue_at": "2026-10-26T08:00:00", "created_at": "...", "sends": [{ "period_key": "2026-W43", "status": "sent", "output_id": "...", "trigger": "schedule", "detail": null, "created_at": "...", "finished_at": "..." }] } }
```

`sends` is the latest ten periods. `status` is `started`, `sent`, `email_failed` (the issue is in the outputs list but the email failed), `skipped` (nothing new; nothing sent) or `failed`. `next_issue_at` is null while the digest is off.

### `PUT /api/v1/author/newsletter`
Create or update the subscription, and schedule it. Body fields are all optional: `{ "title": "…", "cadence": { … }, "sections": { … }, "enabled": true }`. `cadence` takes the scheduler's shape (`daily` / `weekly` / `monthly` with hour, minute, weekday or day of month, and an IANA timezone; default weekly, Monday 08:00 UTC). `sections` takes the newsletter's toggles, with `featured` off by default (D-097). 400 for a bad cadence, an unknown section or no section on. `enabled: false` keeps the settings and disables the schedule.

### `DELETE /api/v1/author/newsletter`
Unsubscribe: `{ "deleted": true }` (`false` when there was none). Removes the subscription, its send history and its schedule. Past issues stay in the outputs list.

### `POST /api/v1/author/newsletter/send-now`
Make and send an issue now, outside the schedule. It covers what is new since the last issue and counts as one. Returns `{ "status": "queued", "task_id": "…" }` (the worker runs it); `?sync=true` runs it in the request and returns `{ "status": "sent" | "skipped" | "email_failed" | "failed", "period_key": "manual:…", "output_id": "…" }`. 400 when there is no subscription or it is off.

---

## Echo

All `/echo` endpoints require `require_feature("echo_personal_brain")` (Studio only). Backend: `backend/app/routers/echo.py` (I-3, PR #172). Page: [`EchoPage`](ui-pages.md#echopage--echo-studio).

### `GET /api/v1/echo/status`
Cold-start readiness, v2 since S-3.5.1 ([D-101](decisions.md#d-101--echo-readiness-v2-five-domains-measured-from-their-stores-blocked-reads-as-not-connected-the-voice-test-reported-not-gated-2026-10-20)). `ready` is the AND of five domains, each measured from its store on every call: `facts`, `activity`, `signals`, `voice` and `shares`. `progress` is the mean of the domains' progress.

```json
{ "ready": false, "progress": 0.31,
  "domains": [{ "key": "facts", "domain": 1, "label": "Facts about you", "status": "in_progress", "met": false, "progress": 0.53,
                "criteria": [{ "key": "facts", "label": "Facts you wrote", "current": 12, "target": 30, "met": false, "fraction": 0.4 }, "…"],
                "summary": "12 facts you wrote, across 2 kinds.", "missing": "To finish: write 18 more facts …",
                "details": { "self_authored": 12, "inferred": 3 } }, "…"],
  "total_rows": 15, "distinct_sources": 2, "has_personality_trait": true, "threshold_total": 100, "threshold_sources": 3,
  "notes_total": 4, "notes_words": 120, "shares_total": 9 }
```

- **`status`** is one of four values:
  - `met`;
  - `in_progress`;
  - `not_started` (nothing yet);
  - `not_connected`, used only by activity, when there are no events and nothing is connected. It is not a failure.
- **`missing`** is null once the domain is met.
- **`details`** depends on the domain:
  - activity has `first_at`, `last_at` and `sources`. Each source has `name`, `label`, `kind` (`connector` | `import`), `status` (`connected` | `not_connected` | `imported`), `available`, `reason` and `events`. A connector this install cannot offer yet reads `not_connected` with its reason; YouTube likes and Google Calendar are listed this way until the install has a Google connector OAuth client (`OAUTH_GOOGLE_CONNECTOR_CLIENT_ID`).
  - voice has `per_script` (pieces and words per script), `best_script`, `stability` (`measured`, `spread`, `max`, `vectors`, `reason`) and `voice_test` (`eligible`, `notes`, `notes_needed`). The voice test is D-100's user-as-judge test, reported and not gated.
  - facts has `self_authored` and `inferred`; the facts Echo inferred are kept but not counted.
  - signals has `types`; shares has `content_types` (count per type).
- **Thresholds** are settings (`ECHO_READY_*`); a threshold of 0 switches that check off.
- **The v1 fields** (`total_rows`, `distinct_sources`, `has_personality_trait`, `threshold_*`) and the feeders (`notes_total`, `notes_words`, `shares_total`) are still returned. They are reported only.

### `GET /api/v1/echo/context`
The caller's personal-context rows. Query params: `kind`, `source`, `include_expired` (default false). Rows: `{ id, kind, key, value, source, confidence, captured_at, expires_at }`. `kind` is closed to ten values (`location`, `interest`, `hobby`, `work`, `talent`, `skill`, `personality_trait`, `life_event`, `daily_routine`, `place`); anything else is 400.

### `POST /api/v1/echo/context`
Body `{ "kind": "...", "key": "...", "value": "...", "confidence": 1.0, "expires_at": null }`; `source` is fixed to `manual`. Upserts on `(kind, key)`: re-posting an existing pair updates `value`, `confidence`, `expires_at` and `captured_at` in place, so this is also the edit endpoint. Non-string values are JSON-encoded.

### `DELETE /api/v1/echo/context/{kind}/{key}`
Deletes one row; 404 if absent. The key is a path segment and Starlette decodes `%2F` before routing, so a key containing `/` cannot be addressed; the frontend refuses such keys at entry.

### `DELETE /api/v1/echo/sources/{source}`
Revoke a source: deletes every row attributed to it for the caller. `{ "deleted_count": n }`, idempotent.

### `GET /api/v1/echo/connectors`
Every connector this install offers, with the caller's grant (S-3.2.1, [#336](https://github.com/khoks/VideoResearchPro/pull/336)). `connectors` (names) and `supported_kinds` are kept from v1.

```json
{ "connectors": ["github"], "supported_kinds": ["interest", "..."],
  "items": [{ "name": "github", "display_name": "GitHub", "privacy_weight": "low",
              "consent_disclosure": "…", "consent_version": "2026-10-19", "event_types": ["pushed_commit", "…"],
              "configured": true, "connected": true,
              "grant": { "account_label": "octocat", "granted_at": "…", "consent_version": "2026-10-19", "consent_outdated": false,
                         "status": "idle", "last_sync_at": "…", "backfilled_at": "…", "last_error": null,
                         "last_counts": { "added": 40, "updated": 2, "facts": 3 }, "events": 412 } }] }
```

Connectors on this build: `github` (S-3.2.4; public activity under `read:user`; event types `pushed`, `committed`, `opened_pull_request`, `merged_pull_request`, `reviewed_pull_request`, `opened_issue`, `commented`, `published_release`, `created_repository`, `starred`, `forked`; nightly).

### `POST /api/v1/echo/connectors/{name}/authorize`
Body `{ "consent_version": "…" }`: the disclosure version the consent screen showed. Returns `{ "authorize_url": "…" }` for the browser to open. Records a single-use OAuth state bound to the caller (PKCE, ten minutes); the redirect URI is `APP_BASE_URL` + `/echo/connectors/{name}/callback`, never taken from the client. 404 unknown connector, 409 the disclosure changed (show it again), 503 the install has no OAuth client for it.

### `POST /api/v1/echo/connectors/{name}/callback`
Body `{ "code": "…", "state": "…" }`, posted by the frontend route the provider redirects to, with the caller's token. The state must be the caller's, for this connector, and unexpired; it is consumed. Stores the tokens Fernet-encrypted, records the grant, schedules syncs (`echo_sync`) and queues the backfill. Returns the connector item. Any failure is one generic 400, never which step failed.

### `POST /api/v1/echo/connectors/{name}/sync`
Sync now. `{ "dispatched": "queued" | "ran" | "off" | "queue_failed", "connector": {…} }`. 404 when not connected. The first sync after connecting is a backfill; later ones are incremental from the last success. A provider failure is recorded on the grant (`status: "error"`, `last_error`, "Reconnect to sync: …" when the grant no longer works), never raised.

### `DELETE /api/v1/echo/connectors/{name}`
Disconnect. Revokes at the provider (best effort) and deletes, in one request, the grant, the tokens, any pending state, every event the connector wrote, the facts derived from them, and its schedule. `{ "connector": "github", "events": 412, "facts": 3, "provider_revoked": true }`.

### `GET /api/v1/echo/activity`
The caller's activity timeline, newest first: `connector` (filter), `before` (ISO time; pass the previous page's `next_before`), `limit` (default 50, max 200). `{ "items": [{ "id", "connector", "event_type", "occurred_at", "payload", "text_content", "linked_document_id" }], "next_before": "…" | null }`.

### Shares inbox (S-3.7.1)
Everything the user forwards to Echo, no approval step. Every share is `pending` until S-3.7.2's processing exists. **Context-only by default:** `author_is_tenant` is false unless the user says the words are theirs; such a share is never quoted and never enters a dataset or derived export.

Share shape: `{ id, received_at, updated_at, surface, content_type, kind: "url"|"text"|"file", url, text, file: {filename, mime, size} | null, user_annotation, author_is_tenant, processing_state, linked_document_id }`. Timestamps are UTC with an offset. A foreign id is the same 404 as a missing one.

- `POST /api/v1/echo/shares` — body `{ url | text, annotation?, content_type?, author_is_tenant? = false, surface? = "manual_quick_share" }`, exactly one of `url` (http/https only) or `text` (non-blank, at most `ECHO_SHARE_TEXT_MAX_CHARS`, 413 above). `content_type` is inferred when omitted (`youtube_video`, `youtube_short`, `instagram_reel`, `tweet`, `link`, `text_snippet`, ...) and must match `^[a-z][a-z0-9_]{0,63}$`. 201.
- `POST /api/v1/echo/shares/upload` — multipart `file` plus optional `annotation`, `content_type`, `author_is_tenant`, `surface`. Empty is 422; over `ECHO_SHARE_MAX_BYTES` (25 MB) is 413 and writes nothing. Stored as `ECHO_SHARES_DIR/<tenant>/<share id><ext>`; the client's filename is kept for display only. 201.
- `GET /api/v1/echo/shares` — `?state=pending|processed|skipped|failed&q=&limit=(1-500, 100)&offset=&origin=direct|import|all&import_id=`; newest first; `q` matches text, annotation and payload (URL, filename). `origin` defaults to `direct`, the shares handed over one at a time; `import_id` lists one import's shares oldest first. `{ items, total, limit, offset }`. Imported shares carry `import_id`, `occurred_at` and `imported` (the importer's provenance: chat and sender, or note title and labels).
- `GET /api/v1/echo/shares/{id}`; `PATCH /api/v1/echo/shares/{id}` with any of `annotation` (`null` clears), `content_type`, `author_is_tenant`.
- `DELETE /api/v1/echo/shares/{id}` — removes the share's vector, file, derived facts and row. `{ deleted, vectors, files, derived_facts }`.
- `GET /api/v1/echo/shares/{id}/file` — the stored bytes, always `Content-Disposition: attachment` with `X-Content-Type-Options: nosniff`. A row whose path points outside its tenant directory is never followed (404).
- **Processing (S-3.7.2).** Every created share is queued to `echo.process_share` (`ECHO_SHARE_PROCESSING`: `celery`, `inline` or `off`); a queue failure leaves it `pending`. The share shape gains `extracted_text` (links and files) and `processing`: `{ title, author, extractor, error, note, embedded, processed_at, library_offer: { eligible, reason, source_type }, ocr_confidence, language, duration_seconds, page_count, pages_with_text, truncated }`, absent until processing ran. `extractor` names the reader: `ocr_local` (on-device OCR), `ocr_vision` (a vision model), `whisper`, `pdf_text`, `text_file`, or the article extractor for links. `processing_state` is `skipped` when a share was deliberately not read (remote media off, a local-only tenant, no OpenAI key, a kind no reader handles), with `note` saying why; Retry reads it again.
- `POST /api/v1/echo/shares/{id}/process` — queue processing again (Retry). Idempotent: everything is re-derived from what arrived.
- `POST /api/v1/echo/shares/{id}/library` — the library offer. For a link processing marked eligible, ingests it through the same path as `POST /library/paste-urls` (deduplicated, visible to the sharer only) and sets `linked_document_id`; a second call returns the same document. 409 for anything not eligible (text, files, YouTube links, unprocessed links), 422 when the page cannot be extracted.

### Adding to Echo from outside the app (S-3.7.3)
- **Share tokens.** `POST /api/v1/echo/shares` and `POST /api/v1/echo/shares/upload` accept, besides a session, `Authorization: Bearer pec_…`, a share token. A token is refused everywhere else (401), including the token routes themselves, so it cannot read anything or mint another. The Studio check runs on every use. A revoked or unknown token is 401.
- `POST /api/v1/echo/share-tokens` — body `{ label }`; needs a session. 201 `{ id, label, prefix, created_at, last_used_at, token }`. The `token` is in this response only; only its SHA-256 hash is stored. 409 at `ECHO_SHARE_TOKENS_MAX` (10) active tokens.
- `GET /api/v1/echo/share-tokens` — `{ items: [{ id, label, prefix, created_at, last_used_at }], max }`, active tokens only.
- `DELETE /api/v1/echo/share-tokens/{id}` — `{ revoked: true }`; 404 for another tenant's or an already revoked token.
- `GET /api/v1/echo/share-tokens/check` — for the extension's settings: `{ ok, email, via: "share_token" | "session" }`.
- **Source.** `POST /api/v1/echo/shares` takes optional `source_url` (http/https, validated like a share URL) and `source_title`: the page a quote or an image came from. The share shape gains `source: { url, title }`.
- **Images by address.** A URL share with `content_type: "image"`, or a URL ending in an image extension, is fetched by processing into the tenant's share directory, then read like an uploaded image. Hosts that resolve to private, loopback, link-local or other non-global addresses are refused, and so is every redirect into one, unless `ECHO_FETCH_ALLOW_PRIVATE` is set. Only image content types are kept, up to `ECHO_SHARE_MAX_BYTES`. A refused fetch fails the share with a reason, and Retry runs it again.

### Echo anticipation cards (S-3.8.2)
Studio (`echo_personal_brain`). The Echo panel reads these when it opens; nothing here notifies. The cap and the dismissal rule are [D-103](decisions.md#d-103--anticipation-cards-only-in-the-opened-panel-three-a-view-three-days-a-key-three-dismissals-turn-a-kind-off-2026-10-20), pre-registered in [the note](notes/2026-10-20-anticipation-cards-preregistration.md).
- `GET /api/v1/echo/cards?context=library|job:<id>|document:<id>` → `{ cards: [{ key, kind: saved_search|shares|questions, title, body?, href?, action_label?, context? }], muted_kinds, notice?, notice_kind? }`.
  - At most three cards, one per kind, each shown on at most three distinct days.
  - Viewing counts a card once per day, except a questions card, which the panel reports itself (below).
  - `notice` is said once, after three dismissals turned a kind off.
  - A malformed context is 422.
  - A questions card carries no questions: the panel fetches `GET /suggestions?context=`.
- `POST /api/v1/echo/cards/dismiss?key=` → `{ muted_kind }`. Retires the key; the third dismissal of a kind within 30 days turns that kind off and returns it.
- `POST /api/v1/echo/cards/act?key=` → 204. Retires the key without counting as a dismissal. A saved-search card also marks its notification read; another tenant's notification is untouched.
- `POST /api/v1/echo/cards/shown?key=` → 204. A questions card was rendered with at least one question.
- `GET /api/v1/echo/cards/settings` and `PUT /api/v1/echo/cards/settings { kinds: { saved_search?, shares?, questions? } }` → `{ kinds }`. Turning a kind back on restarts its dismissal count; an unknown kind is 422.
- `POST /api/v1/echo/cards/seen/shares` → 204. Called by the shares inbox when it opens: what is there now is not news.
- Keys are `saved_search:<notification id>`, `shares:<newest share id>` or `questions:<context>`. Anything else is 422.

### Echo export-file imports (S-3.7.5)
Studio (`echo_personal_brain`). Uploads are multipart `file`, plus `importer` (optional; detected otherwise) and `options` (a JSON object). Over `ECHO_IMPORT_MAX_BYTES` (200 MB) is 413. An empty file, an unknown format, a zip unpacking past `ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES` or impossible options are 422. The upload is never stored.
- `POST /api/v1/echo/import/preview` — what an import would produce; writes nothing. `{ importer, label, summary, participants: [{ name, messages }], options, warnings }`. `whatsapp` options: `self_name`, `redact_other_party`, `timezone` (IANA), `date_order` (`dmy`, `mdy`, `ymd`; inferred, with a warning when nothing decides it). `google_keep` options: `own_words` (default true), `include_trashed`. `google_takeout` options: `include_keep`, `include_youtube` (both default true), plus Keep's `own_words` and `include_trashed`. `apple_health_export` options: `window_days` (30 to 3,650, default 365). The others take none.
- `POST /api/v1/echo/import` — runs it. A WhatsApp `self_name` must be a participant, and `redact_other_party` needs one. Writes one share per WhatsApp turn or Keep note, then queues embedding (`echo.embed_import`, or inline, or off, per `ECHO_SHARE_PROCESSING`). 201 with the import: `{ id, importer, filename, status: importing|embedding|done|failed|deleting, options, counts: { shares, own_words, context_only, embedded, events?, events_already_held?, facts?, redacted_turns?, redacted_messages?, skipped_trashed?, private_session_skipped?, ads_skipped?, ... }, summary, error, created_at, finished_at }`.
- **Event importers.** These write `activity_events` through S-3.2.1's writer, with `connector` set to the importer's name; they write no shares and need no embedding, so the import is `done` when it returns. Each event's payload carries `_import: <id>`. Only events not already held are written: `events` counts those, `events_already_held` the rest.

  | Importer | File | Events | Not read or not stored |
  |---|---|---|---|
  | `google_takeout` | `takeout-*.zip` | `watched_video` (title, video id, channel), `searched_youtube` (the query, as `text_content`); Keep notes as shares | ads; removed videos; HTML history (a warning asks for JSON) |
  | `spotify_export` | `my_spotify_data.zip`, `Streaming_History_*.json`, `StreamingHistory*.json`, `endsong_*.json` | `played_track`, `played_episode`, `played_audiobook` (title, artist or show, ms played, skipped) | private-session plays; IP address and country |
  | `goodreads_export` | `goodreads_library_export.csv` | `read_book`, `reading_book`, `want_to_read` (rating, shelves); the review and private notes are `text_content` | |
  | `letterboxd_export` | `letterboxd-*.zip` | `watched_film` (diary entries, plus watched films with no diary date, marked `undated_viewing`), `reviewed_film` (review as `text_content`), `want_to_watch` | |
  | `strava_export` | `export_<n>.zip` | `workout` (type, distance, elapsed and moving time; the description as `text_content`) | routes and GPS files |
  | `apple_health_export` | `export.zip`, `export.xml` | none; three `daily_routine` facts (`sleep`, `steps`, `workouts`) in `personal_context`, `source: "import:<id>"`, confidence 0.8 | the health records themselves |

  An export renamed on the way is still recognised by its contents. Exports past the upload cap go through `backend/scripts/echo_import.py --email … --file …` (`--preview`, `--options`, `--max-unpacked-mb`), the same flow from the command line.
- `GET /api/v1/echo/imports` and `GET /api/v1/echo/imports/{id}` — the caller's imports, newest first.
- `POST /api/v1/echo/imports/{id}/embed` — retry indexing after a failure; resumes where it stopped. 409 while importing or undoing.
- `DELETE /api/v1/echo/imports/{id}` — undo: every share the import wrote, their vectors and anything derived from them; the events it added (not ones it found already held, which belong to the import that added them); the facts it recorded that still carry its source (a fact restated since is kept), and their vectors in `personal_context_global`; then the import. `{ deleted, shares, vectors, facts, events }`.

### Voice and personality signals (S-3.3.1)
The signals panel's rows, the caller's own only (another tenant's id is a 404). Learned only from the user's own words: notes, questions, and shares marked `author_is_tenant`; never a context-only share ([D-089](decisions.md#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19)).

Signal shape: `{ id, signal_type, layer: "style"|"personality", value, weight, examples: [{text, source, at?}], language, register, derived_from: [source refs], origin: "user"|"llm"|"stylometry", consent_version, created_at, updated_at }`. `signal_type` is one of `vocabulary`, `cadence`, `framing`, `recurring_reference`, `formality_register`, `register_per_audience` (style) or `trusted_conclusion`, `preferred_solution`, `recommendation_lens`, `apprehension`, `methodology`, `topic_emphasis`, `perception_lens`, `interest` (personality). `language` ∈ `en`, `hi-Deva`, `hi-Latn`, `mixed`; `register` ∈ `intimate`, `casual`, `professional`, `public`; both nullable. Source refs are `note:<id>`, `share:<id>`, `qa:<id>`, `library_qa:<id>`, `history_qa:<id>` or `user`.

- `GET /api/v1/echo/signals` — `?signal_type=&language=`; live signals, style types first, each type by weight. `{ items, consent_version, learning }`. `learning` (S-3.3.2) is `{ mode: "celery"|"inline"|"off", inputs, by_language, pending, threshold, last_learned_at }`: how many of the user's own texts Echo may learn from, how many are new, edited or deleted since the last read, and the count at which a run starts on its own.
- `POST /api/v1/echo/signals/learn` — "Learn now" (S-3.3.2): queue a run for whatever is waiting, below the threshold too. 202 `{ status: "queued"|"ran"|"waiting"|"off"|"not_entitled"|"queue_failed", pending }`.
- `POST /api/v1/echo/signals` — body `{ signal_type, value (1-500 chars), language?, register? }`; a signal the user states (`origin: "user"`). 201. 422 for an unknown type, language or register, and for a signal the user already rejected (same type, language and `value` ignoring case, spacing and surrounding quotes or full stops).
- `PATCH /api/v1/echo/signals/{id}` — any of `value`, `language`, `register` (an explicit `null` clears; an absent field is kept), `weight` (0-100). The type is fixed.
- `DELETE /api/v1/echo/signals/{id}` — "That's not me". A tombstone, not a delete: the row is kept with `suppressed_reason: "user"` so extraction never writes the signal again; it leaves every list and the live profile. Returns the signal. `DELETE /echo/brain` removes tombstones too.
- `GET /api/v1/echo/signals/export` — the voice profile as a JSON download (`echo-voice-profile.json`): `{ format: "pratidhvani-voice-profile", version: 1, exported_at, consent_version, style: [...], personality: [...], rejected: [{signal_type, value, language}] }`. Every column of every row, tombstones included, is in the whole-brain archive below.

**Learning (S-3.3.2).** Signals with `origin: "llm"` come from one economy-tier call per batch of the user's own texts. Each example is checked against the passage it cites and stored only if found there exactly. Signals with `origin: "stylometry"` (type `cadence`) are measured without a model and recomputed on every run. A personality signal has `language: null`; a style signal's language is that of its examples' passages ([D-099](decisions.md#d-099--signal-extraction-verbatim-checked-examples-language-free-beliefs-stylometry-without-a-model-2026-10-19)). Deleting a note withdraws it from every signal at once. An export import (S-3.7.5) counts as one input in `learning`. So does each connector whose events carry the user's own words (`text_content`, T-3.3.2.8). Their examples cite `event:<id>`, and revoking the connector withdraws them at once. A "speak as me" draft the user edited and saved is an input too (S-3.4.2), made of the words they typed into it and nothing of the draft or of the incoming message (an 8-word stretch repeated from it is the sender's): its examples cite `draft_edit:<id>`, an edit under 4 typed words is not an input, and deleting the draft withdraws it. Its examples cite the individual turns, so undoing the import withdraws them.

**Retrieval (S-3.3.3).** Every live fact and signal also lives as one vector in `personal_context_global`, with `tenant_id` metadata. A rejected or source-deleted signal, or an expired or deleted fact, has none. Nothing in the API queries it yet; "speak as me" (E-3.4) and the voice-match harness (S-3.3.4) read it through `echo_personal_vectors.query_personal_context`, which fails closed without a tenant.

Deleting a share withdraws it as evidence: its examples and provenance leave the signals listed in its `derived_signal_ids_json`, and a signal with no source left is suppressed as `source_deleted` (unlike a rejection, new evidence may derive it again).

### Speak as me (S-3.4.1)
Backend: `backend/app/routers/echo_drafts.py`, service `services/echo_draft_service.py`, agent `agents/echo_agent.py` ([D-102](decisions.md#d-102--speak-as-me-two-switches-guards-in-code-the-reply-in-the-users-language-2026-10-20)). Every route needs the `echo_speak_as_me` feature (Studio); other tiers get 403. A draft is never sent anywhere.

- `GET /api/v1/echo/draft/status` — what stands between the caller and a draft. `{ enabled, blockers: [{code, message}], readiness, voice_gate: {status: "not_run"|"passed"|"failed", run_at, pairs, picked_own_share, notes_total, notes_needed}, drafts_today, drafts_per_day }`. Blocker codes, in order: `install_off` (`ECHO_SPEAK_AS_ME_ENABLED` is false, the default), `not_ready` (readiness v2; the message names each unmet domain), `voice_test_required` or `voice_test_failed`, `daily_cap`. The Echo bubble's summary fields ride along: `state` (`enabled`, or the first blocker's code, with `voice_test_required` reported as `voice_test_needed`), `reasons` (every blocker's message), `notes`, `notes_needed`, `pairs_judged`, `pairs_needed`.
- `POST /api/v1/echo/draft` — body `{ message (1-8000 chars), audience? (≤200), register?: "intimate"|"casual"|"professional"|"public", language?: "en"|"hi-Deva"|"hi-Latn"|"mixed", acknowledge_names?: [string] }`; unknown fields are refused. 201 with the draft: `{ id, message, draft, language, register, audience, intent, voice_match_score (0-100), confidence (0-1), citations: [{kind: "source"|"note"|"fact"|"qa"|"share", ref, label, url?}], deviation_notes, flags, disclosure, final_text, disclosure_kept, created_at }`. `ref` is the draft's marker for the item (S1, N2, F1); `url` is a link outside the app, such as a source at its timestamp. `flags` may hold `verbatim_removed` (a sentence quoting a third party was dropped) and `ungrounded`. Errors:
  - 409 `{code, message, status}` for a closed gate.
  - 409 `{code: "names_need_confirmation", names, message}` when the message names a private person. Send the request again with those names in `acknowledge_names`.
  - 429 `{code: "daily_cap"}`.

  A stopped draft is not counted against the cap.
- `GET /api/v1/echo/drafts?limit=` — the caller's drafts, newest first: `{ items }`.
- `GET /api/v1/echo/drafts/{id}` and `DELETE /api/v1/echo/drafts/{id}` (204) — the caller's own only; another tenant's id is a 404. Deleting a draft withdraws what its edit taught (below) at once.
- `POST /api/v1/echo/drafts/{id}/feedback` (S-3.4.2, [D-104](decisions.md#d-104--a-draft-edit-teaches-only-the-words-the-user-typed-2026-10-20)) — body `{ final_text (1-16000 chars), disclosure_kept: bool = true }`; unknown fields refused. The text the user used, sent again as often as they like (the newest wins). A trailing disclosure line is removed first. 200 with the draft, whose `final_text`, `disclosure_kept` and `feedback_at` are now set and whose `edit` is `{ written_words, removed_words, quoted_words, kept_words, written: [runs the user typed, verbatim], removed: [draft runs they cut], quoted: [typed stretches of 8+ words repeated from the incoming message] }` (`edit` is null before feedback). Only `written` teaches the user's voice. 404 for another tenant's draft; 422 for a text that is only the disclosure. Not counted against the daily cap; audited as `echo_draft_feedback` with counts only.

Each draft is metered as the daily quota resource `echo_drafts` (`echo_drafts_per_day`: Free 0, Pro 0, Studio 20) and audited as `echo_drafted` with counts only. Drafts and voice-test results (`echo_drafts`, `echo_voice_gates`) are part of the brain: exported and erased with it.

### `GET /api/v1/echo/export`
The whole brain as one zip (S-3.10.1): `manifest.json` (format `pratidhvani-echo-archive`, version 1, export time, tenant, row counts per table, every file with size and SHA-256, any missing file), `personal_context.jsonl`, `shares_inbox.jsonl`, `voice_signals.jsonl` and `voice_signal_inputs.jsonl` (every column; datetimes ISO-8601 with offset), and `files/<stored path>`. Lossless: `services/echo_privacy_service.py::read_archive` is the exact inverse. Built in a temporary file and removed after sending. Audited (`echo_exported`, counts only). Notes and the library are not part of Echo; notes export at `/exports/notes.*`.

### `GET /api/v1/echo/brain/footprint`
What Echo holds for the caller in every store: `{ "rows": {"personal_context": n, "shares_inbox": n, "voice_signals": n, "voice_signal_inputs": n}, "files": n, "vectors": {"shares_global": n, "personal_context_global": n} }`.

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

Returns 501 on non-Windows hosts (the trampoline is Windows-only today). **Operator only** (T-5.2.8, [D-111](decisions.md#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)): the bearer token must belong to an account `GET /auth/me` reports as `is_operator`; any other account gets 403 before anything is spawned.

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

Heartbeats every 30 seconds (server pings, client pongs). Auth is enforced via the `?token=` query string at WS handshake (browsers cannot set `Authorization` headers on WebSocket connections). Since T-8.8.1.5 this is the only route that reads a token from the URL.

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
3. **L3 Personal Brain.** The context store, the five-domain readiness gate, connectors, the activity stream, shares and voice signals shipped under `/echo/*` (above), not `/brain/*`. Still ahead: the "speak as me" agent. See [personal-brain.md](personal-brain.md).

---

## Cross-references

- Architecture & request lifecycles — [architecture.md](architecture.md)
- Frontend pages that consume these endpoints — [ui-pages.md](ui-pages.md)
- Vision and the trajectory the API will follow — [vision.md](vision.md)
- LLM use case registry behind the Q&A and knowledge endpoints — [CLAUDE.md](../CLAUDE.md) §LLM-configuration
