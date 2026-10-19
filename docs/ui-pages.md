# Pratidhvani — UI Pages

**Status:** canonical (2026-04-24). This is the **single source of truth** for the frontend page inventory: every route, the page that renders it, what the user does there, and the empty / loading / error states. Visual system (colors, type, components) lives in [ui-design.md](ui-design.md). API endpoints these pages call live in [api-reference.md](api-reference.md).

The frontend is a single-page app under `frontend/src/`. Routing is `react-router-dom` v7 via `createBrowserRouter`. The route table lives at [`frontend/src/routes/index.tsx`](../frontend/src/routes/index.tsx).

---

## Route table (current)

| Path | Component | Auth | Purpose |
|------|-----------|------|---------|
| `/login` | `LoginPage` | public | Email + password login |
| `/register` | `RegisterPage` | public | Create a new account |
| `/` | (redirect → `/submit`) | protected | Default landing |
| `/submit` | `SubmitJobPage` | protected | Start a new research run |
| `/jobs` | `JobsListPage` | protected | All jobs the user owns |
| `/jobs/:jobId` | `JobDetailPage` | protected | Single job: status, approval, report, Q&A |
| `/library` | `LibraryPage` | protected | Browse the global video library |
| `/library/qa` | `LibraryQAPage` | protected | Ask across the entire library |
| `/library/channels/:channelId` | `ChannelPage` | protected | One channel: header, subscribe / sync, trust-weight slot, its documents |
| `/qa-history` | `QAHistoryChatPage` | protected | Meta-chat across all past Q&A |
| `/exports` | `ExportsPage` | protected | Dataset export endpoints + downloads |
| `/author` | `AuthorPage` | protected, Pro+ | Author Studio: bind finished runs into a book; other kinds shown as coming later |
| `/echo` | `EchoPage` | protected, Studio | Echo: personal-context store, readiness meter, sources and connectors |
| `/account/subscription` | `SubscriptionPage` | protected | Tier, upgrade / downgrade (demo billing) |
| `/account/ai-models` | `AIModelsPage` | protected | Per-use-case LLM overrides and BYOK keys |
| `*` | (redirect → `/`) | — | 404 → home |

Protected routes are wrapped in `<ProtectedRoute>` which redirects unauthenticated visitors to `/login`. Public-only routes (`/login`, `/register`) are wrapped in `<PublicOnlyRoute>` which redirects authenticated users to `/submit`.

`VideoKnowledgePage.tsx` exports `VideoKnowledgeDrawer` — used as an inline drawer inside `JobDetailPage` to show a video's knowledge artifact, not as its own route.

The protected routes share `<AppLayout>` (top-tabs nav today, sidebar after the redesign per [branding.md](branding.md) and [ui-design.md](ui-design.md)).

---

## Page-by-page

### `LoginPage` — `/login`
**Purpose.** Email + password login. Calls `POST /api/v1/auth/login`, stores the JWT in the auth context, redirects to `from.pathname` (or `/submit`).

| State | What renders |
|-------|--------------|
| Default | Email + password fields, "Sign in" button, link to `/register`. |
| Submitting | Button shows spinner, fields disabled. |
| Auth error | Inline error below the form ("Email or password is wrong."). |
| Network error | Toast via the global `ToastContainer`. |

### `RegisterPage` — `/register`
**Purpose.** Account creation. Calls `POST /api/v1/auth/register`, immediately follows with a login call to capture the JWT.

| State | What renders |
|-------|--------------|
| Default | Email + password + confirm-password, "Create account" button. |
| Validation error | Inline below the offending field. |
| Email exists | "An account with this email already exists. Sign in instead?" with link. |

### `SubmitJobPage` — `/submit`
**Purpose.** Start a research run. Three tabs: **Topic**, **Channels**, **Subscribe**.

| Tab | Inputs | Result |
|-----|--------|--------|
| Topic | topic, search instructions, preferred channels (multiselect from existing subscriptions), `max_videos` | `POST /api/v1/jobs` with `job_type=topic` |
| Channels | one or more channel URLs, `max_videos_per_channel` | `POST /api/v1/jobs` with `job_type=channel` |
| Subscribe | one or more channel URLs | `POST /api/v1/jobs` with `job_type=subscription`; channels become subscribed for auto-pull |

| State | What renders |
|-------|--------------|
| Default | Tabbed form with the active tab's inputs. |
| Submitting | Submit button shows spinner. |
| LLM down for `search_plan_queries` | Banner above the Topic tab: "Search planning is unavailable. Topic jobs are paused. Channel and Subscribe still work." Topic tab's submit button is disabled. |
| Quota near cap | Yellow banner: "YouTube quota at 86% — large jobs may fail." (Soft warning at 80% per `health/quota`.) |
| Quota exhausted | Red banner: "YouTube quota exhausted until {resets_at}." Submit blocked. |
| Success | Redirects to `/jobs/{id}` for the new job. |

### `JobsListPage` — `/jobs`
**Purpose.** Dashboard of every job the user owns. Real-time updates via the WS hook.

Columns: title, type icon, status pill, video count, created_at, last activity. Row hover reveals "Open" / "Cancel" / "Delete".

| State | What renders |
|-------|--------------|
| Default | Sortable table; default sort by `last activity` desc. |
| Empty | Editorial empty state: "No volumes on your shelf yet. Begin a research run to start building your library." with a primary CTA → `/submit`. |
| Loading | Skeleton rows matching the table column shape. |
| Network error | Toast + retry banner. |
| Background WS event | Status pill updates in place; if a job transitions to `awaiting_approval`, a small "review needed" badge appears. |

### `JobDetailPage` — `/jobs/:jobId`
**Purpose.** The most complex page. Status, approval, report viewing, Q&A panel. Drives the WS subscription for this `jobId`.

Sections (rendered conditionally on `job.status` and `job.job_type`):

| Section | When shown | Notes |
|---------|------------|-------|
| **Header** | always | Title, type, status pill, created_at, "Cancel" / "Delete" overflow menu. |
| **Progress** | status ∈ {searching, extracting, building_rag, generating_report} | Phase, progress bar (`completed / total`), message line, last-event timestamp. Driven by `useJobProgress`. |
| **Search results / Approval** | status == `awaiting_approval` (topic only) | Table of candidate videos with checkboxes, "Approve selected" button. Auto-populates when WS reports the status change. |
| **Approved videos** | status ∈ {extracting, building_rag, ...completed} | Read-only list of approved videos with per-video transcript status. Each row has a "Knowledge" button that opens the `VideoKnowledgeDrawer`. |
| **Report** | `job.report_path` is set | "Open report" button → opens the HTML in an iframe modal. |
| **Q&A panel** | status == `completed` | Question textarea, "Clarify first" optional toggle, language selector, "Ask" button. Below: list of past exchanges with citations rendered as chips that deep-link to `&t=` timestamps. |
| **Knowledge drawer** | user clicks the Knowledge button on a video row | Slides in from the right; shows the structured `{topics, concepts, events, facts}` + Markdown report; "Generate" button if not yet extracted. |

| State | What renders |
|-------|--------------|
| Default | Whichever sections apply per status. |
| WS reconnecting | Subtle dot indicator next to the status pill. |
| LLM down for `qa_formulate_answer` | Q&A panel banner: "Ask question is paused — `qa_formulate_answer` is unreachable." Ask button disabled. |
| LLM down for `knowledge_synthesize_report` | Knowledge drawer's "Generate" button disabled with a tooltip. |
| Job failed | Status pill in error color; banner with the failure message; offer to "Retry from extraction" if applicable. |
| Job cancelled | Status pill in muted color; the prior progress is shown frozen. |

### `LibraryPage` — `/library`
**Purpose.** Browse the caller's view of the global, deduplicated library and add sources that do not come through a research run. Three tabs: **Sources**, **Channels**, **Add sources**.

**Sources tab.** Filters: search text, language, channel, transcript status. Sort: newest / oldest / longest / shortest. Rows for PDFs and pasted pages carry a source-type pill instead of a channel, and no duration.

| State | What renders |
|-------|--------------|
| Default | Row list. Each row: thumbnail (or source-type placeholder), title, channel or source type, duration where it applies, language pill, transcript-status pill, "referenced in N runs" footer, open link. |
| Filtering | Filter controls at the top; results update in place. |
| Empty (no sources at all) | "Nothing matches these filters." (the shelf copy also points at the Add sources tab). |
| Empty (filters return nothing) | "Nothing matches these filters." with a "Clear" on the channel chip. |
| Loading | Spinner on first page; subsequent pages keep the list. |

**Channels tab.** One `ChannelRow` per channel this tenant can see ([D-065](decisions.md#d-065--channel-subscriptions-become-per-tenant-transliteration-reversed-2026-07-31)): name (a real link), subscribers, volumes on your shelf, last synced, Subscribe / Sync now. The row and the name open the channel's page (`/library/channels/:channelId`, below). `/library?tab=channels` (or `?tab=ingest`) opens the page on that tab; the channel page's breadcrumb uses it.

**Add sources tab** (shipped 2026-10-19). Why a tab and not the Submit page or a modal: both endpoints are library-scoped and start no job, the per-file / per-URL result tables need room and should outlive a dialog, and the page already uses tabs for its sections.

| Section | What it does |
|---------|--------------|
| **Upload PDFs** | Drop zone + "Choose PDFs" (multi-select, `.pdf` enforced client-side). Files upload one at a time to `POST /library/upload-pdf` with a per-file progress bar; at 100 % the row reads "Extracting" until the server returns. Result per file: **Added** (pages · words), **Already in library** (`deduped=true`), or **Failed** with the server's 400 / 413 / 422 detail. "See them on the shelf" clears filters and jumps to Sources; the list refreshes when the queue drains. |
| **Paste URLs** | Textarea, one URL per line. Client trims, drops blanks, de-duplicates and caps at the server's 100, and shows a live count of detected types (Facebook / Instagram / LinkedIn / X hosts → post types, everything else → article). Submit calls `POST /library/paste-urls`; the result table shows URL, server-detected type (a `?` marks rows where the server sent none and the type is the local guess), word count, and **Added** / **Already in library** / **Could not extract** / **Invalid URL** with a one-line explanation. A whole-batch 400 renders as an inline error above the table. |

Result-state logic is pure and lives in `frontend/src/utils/ingestResults.ts`; the components only render.

### `ChannelPage` — `/library/channels/:channelId`
**Purpose.** One channel as this reader sees it (S-8.7.1, the first PR of [M7](plans/m7-channel-intelligence.md)). Reads `GET /channels/{id}` for the header and `GET /library/videos?channel_id=` for the documents, so the rows are the same `VideoRow` as the library and carry "referenced in N runs". Reached from `ChannelRow` (title and row click), from the channel name on any `VideoRow`, and by URL.

| Section | Notes |
|---------|-------|
| **Breadcrumb** | "← Channels" → `/library?tab=channels`. |
| **Header** | Eyebrow "Channel", name, subscribers · volumes on your shelf · last synced. Actions: Subscribe / Subscribed (per tenant, [D-065](decisions.md#d-065--channel-subscriptions-become-per-tenant-transliteration-reversed-2026-07-31)), Sync now (the dispatched sync job is watched until it ends, then counts and the list refresh), "YouTube →" when the channel has a public URL. |
| **Trust weight** | Sunken card (`data-slot="trust-weight"`) showing the caller's `source_weight` as a badge (`1.0 · neutral`, otherwise promoted / demoted). Read-only: the write path and the retrieval re-rank are S-7.1.1 ([D-068](decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18)); the control lands in this slot. |
| **Documents** | Heading with the visible count, filter card (search titles, transcript status, sort), the rows (`channelLink={false}` so they do not link back to the page), pager at 50 per page. |
| **Intelligence** | Not yet: E-8.7's aggregate endpoint and tab attach here (S-8.7.2 / S-8.7.3). |

| State | What renders |
|-------|--------------|
| Loading | Header skeleton (eyebrow, title, meta), then three card skeletons for the rows. |
| 404 | "This channel isn't on your shelf." with a "Back to channels" button. Foreign channels are a 404, not a 403 (the existence-leak posture every router uses). |
| Fetch error | Editorial error card with Retry (header or documents, independently). |
| Empty (no documents) | "Nothing from this channel on your shelf yet." |
| Empty (filters) | "Nothing matches these filters." with "Clear filters". |
| Syncing | Sync button reads "Syncing…" with a spinner until the job completes, fails or is cancelled. |

### `LibraryQAPage` — `/library/qa`
**Purpose.** Ask questions across the entire library, with no per-job filter.

Layout: question textarea + clarify-first toggle + language selector at the top; past exchanges below ordered ascending by `created_at`, each with citation chips that link to the source video at the cited timestamp.

| State | What renders |
|-------|--------------|
| Default | Textarea + button + history list. |
| Clarifying | Inline "Interpretation: ..." plus three suggested clarifying questions; user picks one or types their own context. |
| Asking | Streaming answer area appears; citations populate as the agent extracts references. |
| Empty | "No echoes yet. Ask your first question to begin." |
| LLM down | Banner + Ask disabled. |

### `QAHistoryChatPage` — `/qa-history`
**Purpose.** Meta-chat across every Q&A the user has ever run, powered by `qa_library_global`.

Layout: chat-like — past meta-questions and meta-answers. Each meta-answer cites past *exchanges* (not videos directly), and each citation deep-links to the originating job-detail or library-Q&A page.

| State | What renders |
|-------|--------------|
| Default | Full chat scroll, latest at the bottom. New question textarea is sticky at the bottom. |
| Empty (no past exchanges anywhere) | "Once you've asked questions on a job or library page, they'll start echoing here." |
| Empty (past exchanges exist but no meta-questions yet) | "Ask anything across your past questions. e.g. 'What have I learned about supply chains?'" |
| Asking | Inline "thinking" indicator with skeleton paragraphs. |
| LLM down for `qa_history_formulate_answer` | Banner + Ask disabled. |

### `ExportsPage` — `/exports`
**Purpose.** Download dataset exports for fine-tuning. Four endpoints: Q&A in OpenAI chat format, Q&A in tuple format, Knowledge in OpenAI chat format, Knowledge in tuple format.

Layout: card grid, one card per dataset. Each card shows: dataset name, current row count, last-modified hint, "Download" button (initiates a streaming download), "Copy URL" button.

| State | What renders |
|-------|--------------|
| Default | Four cards. |
| Empty (zero rows for that dataset) | Card shows "0 records — no exchanges yet" and disables the Download button. |
| Downloading | Subtle progress indicator in the card. |

### `AuthorPage` — `/author` (Pro+)
**Purpose.** Author Studio. Turn finished research runs into long-form output. Backend: `backend/app/routers/author.py`. Only `book` has a generator today; the page never offers a kind that would 501.

Sections: **What you can make** (one card per kind from `GET /author/kinds`: `available` kinds get a "New …" button, the rest read "Coming later · E-6.x"), **Your outputs** (kind / status filters, one row per output), a **create modal**, a **reader modal**, and a **delete confirmation**.

| State | What renders |
|-------|--------------|
| Below tier, or API 403 | Editorial lock: "Author Studio opens at Pro." with a "See plans" button → `/account/subscription?upgrade=pro`. |
| Kinds loading | Three skeleton cards. |
| Create (book) | Modal: title; chapter picker over the user's topic / channel runs (filterable; runs not completed or without a report are listed but disabled with the reason); "Include each run's Q&A" and "Table of contents" toggles. Generate runs synchronously; a `completed` result opens the reader, a `failed` one toasts `error_message`. |
| Outputs empty | "Nothing authored yet." with a "New book" button; with filters active, "Nothing matches these filters." |
| Output row | Status pill (Ready / Failed / Generating / Pending), title, kind, source count, created date; **Read** and **Download** when `has_content`; **Delete** always. Failed rows show `error_message` in full; pending rows explain they were created when their kind had no generator. |
| Reader | Modal at reading measure rendering the Markdown from `GET /author/outputs/{id}/content`; footer Download (fetches with the bearer header, saves a blob as `<slug>.md`) and Close. |
| Delete | Confirmation modal; the runs the book was built from are untouched. |

### `EchoPage` — `/echo` (Studio)
**Purpose.** Echo's personal-context store. Backend: `backend/app/routers/echo.py`. Honest about scope: the store and readiness gates are real; connectors (E-3.2) and the "speak as me" agent (E-3.4) are not, and the page says so wherever it would otherwise imply them.

Sections: **Readiness**, **Connectors** (with **Sources on record**), **What Echo knows** (grouped by the 10 kinds), a **Not here yet** footer, and three modals (add / edit, forget, revoke).

| State | What renders |
|-------|--------------|
| Below tier, or API 403 | Editorial lock: "Echo opens at Studio." → `/account/subscription?upgrade=studio`. |
| Readiness | Large percentage (mean of the three gates; 100 only when the backend says `ready`), then one meter per gate: facts recorded vs `threshold_total`, distinct sources vs `threshold_sources`, personality trait recorded / missing. The sources hint states plainly that the gate cannot be met while no connector exists. |
| Connectors empty | "No connectors yet." with the planned list. Sources on record lists each `source` with its row count and a **Revoke** button (confirm → `DELETE /echo/sources/{source}`; the toast reports `deleted_count`). |
| Context browser | Filters: kind, source, "Show expired" (`include_expired`). Every known kind renders as a card, empty or not, each with an **Add** shortcut preselecting that kind; rows show label, value, source pill, confidence, captured date, expiry (an **Expired** pill when past). **Edit** reopens the form with kind and label locked (the backend upserts on `(kind, key)`; renaming means forget + add). **Forget** confirms, then `DELETE /echo/context/{kind}/{key}`. |
| Add / edit modal | Kind, label (≤128 chars, no `/` because the key travels as a path segment; warns when the label already exists under that kind and would overwrite), the fact, confidence 0–1, optional expiry date (sent as end-of-day UTC). Source is always `manual`. |
| Loading | Skeleton rows / paragraphs per card. |
| Error | Inline retry line per card; the browser uses an editorial error state with Retry. |

Pure logic (gates, grouping, expiry, label validation) lives in `frontend/src/utils/echoReadiness.ts`.

### `VideoKnowledgeDrawer` (inside `JobDetailPage`)
**Purpose.** View or generate the per-video knowledge artifact.

Tabs: **Structured** (topics / concepts / events / facts) and **Report** (Markdown render).

| State | What renders |
|-------|--------------|
| Not yet extracted | "No knowledge report yet for this video." + "Generate" button. |
| Extracting | Progress indicator, disabled drawer-close (so user doesn't accidentally lose progress). |
| Extracted | Two tabs populated; "Regenerate" button at the bottom (calls the endpoint with `?force=true`). |
| LLM down | "Generate" disabled with a tooltip pointing at health status. |

---

## Cross-cutting page concerns

### Layout (`AppLayout`)
- Today: top horizontal tab bar with the protected pages.
- Post-redesign (per [branding.md](branding.md) §sidebar-mockup): slim left sidebar grouped by purpose (Library / Research / Knowledge / Author/future / Settings).
- Persistent global elements: top-right user avatar + sign-out, top-right LLM-status dot (green/yellow/red), `ToastContainer`.

### Auth context
- `AuthContext` holds `{ token, user, isAuthenticated, login, logout }`. Token persists in `localStorage` under `pratidhvani_token` (was `vrp_token`; rename pending). Axios interceptor attaches it on every request and bounces 401 → `/login`.

### Real-time (WebSocket)
- The `/jobs` and `/jobs/:jobId` pages mount `useJobProgress(jobId)`, which subscribes via the multiplexed `/ws/jobs` connection and invalidates the relevant React Query caches on every event.
- Connection is shared across the app (singleton `wsClient`). Reconnect backoff is exponential, capped at 30 s, with a heartbeat at 30 s.

### Health-driven banners
- A small `useHealth()` hook polls `GET /api/v1/health` every 60 s.
- When `llm.status != 'ok'`, an editorial banner appears in `AppLayout` near the top: pull-quote style, citing the failed feature(s).
- When YouTube quota crosses 80%, a softer warning banner appears on `SubmitJobPage` only.
- When the backend is unreachable for >30 s, a "Reconnecting…" banner appears globally.

### Error boundaries
- Each page is wrapped in a route-level error boundary that renders an editorial error state with a "Reload" button. The toast queue surfaces transient errors (network blips, 500s) without nuking the page.

### Empty states (editorial voice)
Every page has at least one purposeful empty state. The voice is consistent (per [branding.md](branding.md) §voice): "library", "volumes", "echoes". No "No data." or "Empty list".

### Loading states
Skeletons match content shape. No bare spinners on data-bearing pages. Action buttons show inline spinners during their action.

### Accessibility (post-redesign target)
- Visible focus rings on every interactive element.
- ARIA labels on icon-only buttons.
- Keyboard nav: tab order, skip-to-content, focus trap in modals/drawers.
- Screen-reader announcements when streaming Q&A answers complete.

---

## Forward-looking pages (planned, not built)

These pages are defined ahead of time so today's components have a place to land:

| Path (proposed) | Status | Owner doc |
|-----------------|--------|-----------|
| `/shelves` | M1 | [feature-roadmap.md](feature-roadmap.md) |
| `/shelves/:slug` | M1 | [feature-roadmap.md](feature-roadmap.md) |
| `/notes` | M5 | [feature-roadmap.md](feature-roadmap.md) |
| `/author` | **built** (2026-10-19) as a single page, see [`AuthorPage`](#authorpage--author-pro) | [feature-roadmap.md](feature-roadmap.md) |
| `/author/books` / `/author/sites` / `/author/decks` | L2; per-kind sub-routes only if the single page outgrows its kind filter | [feature-roadmap.md](feature-roadmap.md) |
| `/brain` | **built** (2026-10-19) as `/echo`, see [`EchoPage`](#echopage--echo-studio) | [personal-brain.md](personal-brain.md) |
| `/brain/context` / `/brain/activity` / `/brain/voice` | L3; context lives on `/echo` today, activity and voice await E-3.2 / E-3.3 | [personal-brain.md](personal-brain.md) |
| `/settings` | M (foundational) | [ui-design.md](ui-design.md) |
| `/billing` | L5 (SaaS) | [saas-roadmap.md](saas-roadmap.md) |

---

## Cross-references

- Visual system, components, design tokens — [ui-design.md](ui-design.md)
- Brand voice, color palette, typography — [branding.md](branding.md)
- Endpoints these pages call — [api-reference.md](api-reference.md)
- Architecture (WS, auth, lifecycle) — [architecture.md](architecture.md)
- Roadmap — [feature-roadmap.md](feature-roadmap.md)
