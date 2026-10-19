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
| `/reports/:jobId` | `ReportReaderPage` | protected | Reading room: the run's report rendered natively with outline, drop cap, citations and progress |
| `/library` | `LibraryPage` | protected | Browse the global video library |
| `/library/qa` | `LibraryQAPage` | protected | Ask across the entire library |
| `/library/channels/:channelId` | `ChannelPage` | protected | One channel: header, subscribe / sync, trust-weight slot, its documents |
| `/shelves` | `ShelvesPage` | protected (writes Pro+) | The reader's shelves: create, edit, delete |
| `/shelves/:shelfId` | `ShelfPage` | protected (writes Pro+) | One shelf: its runs and the union of their sources |
| `/templates` | `TemplatesPage` | protected | Job templates: the reader's own (use, history, rename, delete) and the starters |
| `/qa-history` | `QAHistoryChatPage` | protected | Meta-chat across all past Q&A |
| `/exports` | `ExportsPage` | protected | Dataset export endpoints + downloads |
| `/notes` | `NotesPage` | protected | Every note the user wrote, grouped by target, searchable, exportable |
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

**Templates** (S-8.6.1). Above the tabs, **Start from a template** lists the reader's templates and the starters, and links to **Manage templates →**. Choosing one fills every field but the topic (a topic already typed is kept) and shows a banner: "From template *Name* · vN. Type a topic; any other change applies to this run only." with **Save changes as vN+1** (own templates only) and **Detach**. The run is submitted with `?template_id=&template_version=`; switching the research type drops the provenance and says so. **Save as template** beside **Begin research** saves the form's recipe as a new template without running it. Arriving from `/templates` with **Use** applies that template.

**Duplicate** carries every parameter of the source run, including report depth and the visual-analysis flag (before S-8.6.1 it reset depth to Auto and dropped the flag). The form has **no** visual-analysis opt-in: that toggle is S-1.18.2, deferred by D-071 / D-075. When a duplicated run or a template carries the flag, an info box says so ("Visual analysis is on, carried from the run or template you started from…") with **Turn off**. The form's state and its conversions live in `utils/jobForm.ts` and are unit-tested (`npm test`).

### `JobsListPage` — `/jobs`
**Purpose.** Dashboard of every job the user owns. Real-time updates via the WS hook.

Columns: title, type icon, status pill, video count, created_at, last activity. Row hover reveals "Open" / "Cancel" / "Delete".

**Shelves** (S-8.1.2): each card carries an **Add to shelf** button ("On N shelves" once shelved) that opens a popover of checkboxes, one per shelf, saved on toggle, with an inline "New shelf…" field that creates and adds in one step; the shelves a run is on show as colour chips under the title, each linking to its shelf. Membership comes from the one cached `GET /shelves` (each shelf carries `job_ids`), so a page of cards costs one request. Readers without the `shelves` capability see the chips but no picker unless the run is already shelved.

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
| **Header** | always | Title, type, status pill, created_at, "Cancel" / "Delete" overflow menu. Shelf chips under the meta line and the **Add to shelf** picker beside the status pill (S-8.1.2). **Save as template** beside Duplicate (S-8.6.1) names the run's recipe as a reusable template. |
| **Progress** | status ∈ {searching, extracting, building_rag, generating_report} | Phase, progress bar (`completed / total`), message line, last-event timestamp. Driven by `useJobProgress`. |
| **Search results / Approval** | status == `awaiting_approval` (topic only) | Table of candidate videos with checkboxes, "Approve selected" button. Auto-populates when WS reports the status change. |
| **Your notes on this run** | always, once the job loads | Section-variant notes panel (M5 / S-8.5.1): the user's own Markdown on the run, newest first, with add / edit / delete. |
| **Approved videos** | status ∈ {extracting, building_rag, ...completed} | Read-only list of approved videos with per-video transcript status. Each row has a "Knowledge" button that opens the `VideoKnowledgeDrawer`, and an inline notes control: a note on a document shows on every surface that shows the document (the shelf, every job containing it). |
| **Report** | `job.report_path` is set | "Read report" (primary) → navigates to the reading room at `/reports/:jobId`; "Quick peek" (secondary) → the legacy HTML in an iframe modal, which also owns "Open in new tab". |
| **Q&A panel** | status == `completed` | Question textarea, "Clarify first" optional toggle, language selector, "Ask" button. Below: list of past exchanges with citations rendered as chips that deep-link to `&t=` timestamps. Each exchange card carries the inline notes control (target `qa_exchange`). |
| **Knowledge drawer** | user clicks the Knowledge button on a video row | Slides in from the right; shows the structured `{topics, concepts, events, facts}` + Markdown report; "Generate" button if not yet extracted. |

| State | What renders |
|-------|--------------|
| Default | Whichever sections apply per status. |
| WS reconnecting | Subtle dot indicator next to the status pill. |
| LLM down for `qa_formulate_answer` | Q&A panel banner: "Ask question is paused — `qa_formulate_answer` is unreachable." Ask button disabled. |
| LLM down for `knowledge_synthesize_report` | Knowledge drawer's "Generate" button disabled with a tooltip. |
| Job failed | Status pill in error color; banner with the failure message; offer to "Retry from extraction" if applicable. |
| Job cancelled | Status pill in muted color; the prior progress is shown frozen. |

### `ReportReaderPage` — `/reports/:jobId`
**Purpose.** The reading room (E-8.8, [plan](plans/m8-reading-room.md)). Replaces reading a report inside an iframe: the page fetches `GET /jobs/{id}/report/body` with the bearer header (no `?token=` in any URL), sanitises the HTML with DOMPurify, parses it into React with `html-react-parser`, and renders it through `ReaderShell` — the shell that knowledge artifacts and books will share (S-8.8.3).

What the reader does to the report's own markup:

| Element | Treatment |
|---------|-----------|
| `h2` / `h3` | Stable ids (unicode-aware slugs, deduped), collected into the sticky outline; `tabIndex=-1` so outline jumps move focus. A body `h1` is demoted to `h2` or dropped when it repeats the title. |
| `<a href="…&t=SECONDS">` | Citation chip (mono, pill) opening the source at the timestamp. Pre-S-1.14.9 reports carry bare `href="&t=123"` anchors with no video URL; those render as a non-link timestamp chip rather than a dead link. An anchor the browser repaired out of a truncated tag is never linked. |
| `<table>` | Wrapped in a horizontal scroll region (WCAG 1.4.10). |
| First substantial paragraph | Drop cap: `::first-letter` float everywhere, `initial-letter` where supported. |
| `<style>`, `<script>`, event handlers, `style=` attributes, embeds, forms, SVG, MathML | Removed by the sanitiser. |

Layout: 75ch serif measure, `text-wrap: pretty` on prose and `balance` on headings, statistics tiles under the title, a sticky `<nav aria-label="Outline">` on the right with `aria-current` tracking scroll (one IntersectionObserver), and a floating "Reading · n%" pill (decorative; the figure is repeated in the outline). The outline hides under 960px (the M12 pass refines the rest).

| State | What renders |
|-------|--------------|
| Loading | Spinner with "Opening the report…". |
| 404 (no report for this run) | `EmptyState` "No report for this run yet" + back link. |
| Other error | `EmptyState` with the API's `detail` + back link. |
| Report with no headings (e.g. "No transcript data available") | Body only; the outline nav is omitted. |

**Citation cards (S-8.8.2).** The page also fetches the run's documents (`GET /jobs/{id}/videos`) and resolves every citation to a source: by the YouTube id in the href, by the href against document URLs, or — for pre-S-1.14.9 reports whose anchors carry only `&t=` — by a known title, then a channel with exactly one document in the run, found in the text around the anchor. Recovered anchors become real links. One shared card (Popover API, top layer, placed from the chip's bounding rect; a fixed-position fallback where `showPopover` is missing) opens on hover after 120 ms and at once on keyboard focus; it shows the source kind and footnote number, title, the kind's facts (channel, date and length for a video; subreddit and author for a Reddit thread; pages for a PDF…), the timestamp and an "Open at" link, and says when the match came from the report text. The chip gets `aria-describedby` while its card is open; Escape closes the card and leaves focus on the chip; scrolling moves the card with its chip and closes it only once the chip leaves the viewport. A chip that cannot be tied to any source is a `<button>` with an explanatory card, so the keyboard still reaches it. A collapsed "Sources cited" list after the body numbers every distinct place cited (identical targets share a number and show "cited n×"). The card has a still slot for R1 frames that nothing feeds until S-1.18.2.

**Print (S-8.8.2).** "Print or save as PDF" in the toolbar, or Ctrl-P: app chrome, outline, progress pill, toolbar, card, health banner and toasts are hidden; text prints black on white whatever the theme; every `h2` after the first starts a page; tables, lists items, blockquotes and code avoid breaking; chips print as the writer's text plus a bracketed footnote number; the endnote list opens itself on `beforeprint` and prints each source's URL; other links print their URL after the text; `@page` margin 2 cm. The 102 kB R1 report prints to 37 A4 pages.

Not yet (later stories): knowledge artifacts and Author outputs in the same shell (S-8.8.3); the mobile pass (S-8.12.1), including a tap-to-preview pattern for chips on touch screens, where hover does not exist.

### `LibraryPage` — `/library`
**Purpose.** Browse the caller's view of the global, deduplicated library and add sources that do not come through a research run. Three tabs: **Sources**, **Channels**, **Add sources**.

**Sources tab.** Filters: search text, language, channel, transcript status. Sort: newest / oldest / longest / shortest. Rows for PDFs and pasted pages carry a source-type pill instead of a channel, and no duration. Above the filters, a **Tag** bar (S-8.1.3): a tag select with counts, the active tag as a pill with **Clear**, and **Manage tags** (a dialog to rename, recolour, merge into another tag, or delete, with the source count). The tag lives in the URL (`/library?tag=<id>`), so every tag chip in the app is a plain link; the bar hides until the reader has a tag. Each row shows the reader's tag chips and a **+ Tag** control (checkbox per tag, saved on toggle; inline create applies the new tag). The same rows on a channel page and a shelf page carry the same control. Every row ends with the inline notes control ("N notes · + Add a note"); the channel rows on the **Channels** tab carry the same control, and typing in it never opens the channel.

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

### `ShelvesPage` — `/shelves`
**Purpose.** Every shelf the reader owns (S-8.1.2, [M1](plans/m1-shelves.md)): name with its colour dot, description, run count, last update. Pro and Studio readers get **New shelf**, **Edit** (name, description, one of ten palette colours) and **Delete** (a confirmation that says the runs stay). A reader whose plan no longer includes shelves keeps the list read-only with an upgrade line; a Free reader with none sees "Shelves come with Pro."

| State | What renders |
|-------|--------------|
| Loading | Two row skeletons. |
| Empty (Pro+) | "No shelves yet." with **New shelf**. |
| Empty (Free) | "Shelves come with Pro." with **See plans**. |
| Error | Editorial error card with Retry. |
| Name collision | The form shows the server's 409 text inline ("You already have a shelf named …"). |

### `ShelfPage` — `/shelves/:shelfId`
**Purpose.** One shelf as a filtered view of the library. Header: eyebrow with the colour dot, name, description, "N runs · updated …" (plus "read-only on your plan" when the tier lacks shelves), Edit / Delete for Pro+. **Runs**: one row per run (title link, status pill, type, sources · created), **Remove** for Pro+. **Sources**: the union of the runs' documents, each once, through `GET /shelves/{id}/documents` (visibility-scoped, D-063), with the library's search / transcript / sort filters and paging (`DocumentsBrowser`, shared with the channel page). The shelf-scoped question box arrives with S-8.1.4.

| State | What renders |
|-------|--------------|
| Loading | Header skeleton. |
| 404 (foreign or deleted) | "This shelf isn't here." with **All shelves**. |
| No runs | "No runs on this shelf yet." with **Go to active runs**. |
| No sources | "No sources on this shelf yet." |
| Deleted from here | Navigates to `/shelves`. |

### `TemplatesPage` — `/templates`
**Purpose.** The reader's job templates and the starters (S-8.6.1, [M6](plans/m6-job-templates.md)). Each card: name, type, `vN · updated …` (or a **starter** badge), description, a one-line summary of the recipe (videos, depth, preferred channels, durations, filters, visual analysis), the instructions in italics, and any **problems** (e.g. "Asks for 300 videos; the free plan allows 100"). Actions: **Use** (opens `/submit` with the template applied), **History** (when there is more than one version: each version with its date and summary), **Rename** (name and description), **Delete…** (two-step; says that runs keep pointing at the version they used). Starters have **Use** only. The five starters (S-8.6.2) are Topic scan, Deep dive, Quick brief, Channel deep-dive and Subscription follow; the channel ones read "you add the channels" in their summary, and on the submit form their banner says "Add the channels".

| State | What renders |
|-------|--------------|
| Loading | Two row skeletons. |
| No templates of your own | "No templates of your own yet." pointing at Save as template on a run or the submit form. |
| Error | Editorial error card with Retry. |

### `LibraryQAPage` — `/library/qa`
**Purpose.** Ask questions across the entire library, with no per-job filter.

Layout: question textarea + clarify-first toggle + language selector at the top; past exchanges below ordered ascending by `created_at`, each with citation chips that link to the source video at the cited timestamp and the inline notes control (target `library_qa_exchange`).

| State | What renders |
|-------|--------------|
| Default | Textarea + button + history list. |
| Clarifying | Inline "Interpretation: ..." plus three suggested clarifying questions; user picks one or types their own context. |
| Asking | Streaming answer area appears; citations populate as the agent extracts references. |
| Empty | "No echoes yet. Ask your first question to begin." |
| LLM down | Banner + Ask disabled. |

### `QAHistoryChatPage` — `/qa-history`
**Purpose.** Meta-chat across every Q&A the user has ever run, powered by `qa_library_global`.

Layout: chat-like — past meta-questions and meta-answers. Each meta-answer cites past *exchanges* (not videos directly), and each citation deep-links to the originating job-detail or library-Q&A page. Each card carries the inline notes control (target `qa_history_exchange`).

| State | What renders |
|-------|--------------|
| Default | Full chat scroll, latest at the bottom. New question textarea is sticky at the bottom. |
| Empty (no past exchanges anywhere) | "Once you've asked questions on a job or library page, they'll start echoing here." |
| Empty (past exchanges exist but no meta-questions yet) | "Ask anything across your past questions. e.g. 'What have I learned about supply chains?'" |
| Asking | Inline "thinking" indicator with skeleton paragraphs. |
| LLM down for `qa_history_formulate_answer` | Banner + Ask disabled. |

### `NotesPage` — `/notes`
**Purpose.** "Your notes": everything the user has written on sources, runs, answers and channels (M5 / S-8.5.3). Sidebar entry under **Knowledge**.

Layout: header with **Export Markdown** / **Export JSON-LD**; a controls card (search box, debounced, server-side substring filter; type chips with counts, one at a time or All; a **Show withdrawn** toggle); then one section per target type in a fixed order (Sources, Knowledge reports, Research runs, Q&A answers, Library Q&A answers, Q&A history answers, Channels), notes newest first within each. Each note is a `NoteCard` with an "on <type>: <target>" line linking to the page the target lives on (run, channel page, library Q&A, history anchor; sources link to the shelf because they have no page of their own yet). Edit and delete inline; withdrawn notes render read-only with their withdrawal date.

| State | What renders |
|-------|--------------|
| Default | Grouped sections. The page fetches the newest 2000 (the server's page cap) and groups client-side so the chips carry counts. |
| More than 2000 | A line under the controls: "Showing the newest N of M. Narrow with a search to reach the rest; the export carries everything." |
| Empty (nothing written) | "Nothing written yet." with where notes come from. Export buttons disabled. |
| Empty (search) | "Nothing matches “…”." with a Clear search action. |
| Loading / error | Spinner; inline error with Retry. |

### `ExportsPage` — `/exports`
**Purpose.** Download dataset exports for fine-tuning, plus the user's own notes. Four dataset endpoints: Q&A in OpenAI chat format, Q&A in tuple format, Knowledge in OpenAI chat format, Knowledge in tuple format; and two notes exports, Markdown and JSON-LD (S-8.5.3).

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
| Readiness | Large percentage (mean of the three gates; 100 only when the backend says `ready`), then one meter per gate: facts recorded vs `threshold_total`, distinct sources vs `threshold_sources`, personality trait recorded / missing. The sources hint states plainly that the gate cannot be met while no connector exists. Below the meters, "Your voice so far: N notes · W words" from `notes_total` / `notes_words` (S-8.5.3), stated as a feeder, not a gate. |
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
| Extracted | Two tabs populated; "Regenerate" button at the bottom (calls the endpoint with `?force=true`). Below the report: "Your notes on this report" (section-variant notes panel, target `knowledge_artifact`; the target only exists once extraction has run). |
| LLM down | "Generate" disabled with a tooltip pointing at health status. |

---

## Cross-cutting page concerns

### Layout (`AppLayout`)
- Today: top horizontal tab bar with the protected pages.
- Post-redesign (per [branding.md](branding.md) §sidebar-mockup): slim left sidebar grouped by purpose (Library / Research / Knowledge / Author/future / Settings).
- Persistent global elements: top-right user avatar + sign-out, top-right LLM-status dot (green/yellow/red), `ToastContainer`.

The sidebar's **Shelves** group (after Library) lists the reader's shelves with a colour dot, the first eight then "Show all N", plus **Manage shelves** (or **Start a shelf** when there are none); it is hidden for a reader who has no shelves and no `shelves` capability. Shelf entries navigate by path because the `AppTab` union is fixed.

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

### Notes (inline, M5)
`frontend/src/components/notes/` — `NotesPanel` (two variants: `inline`, a one-line "N notes · + Add a note" control that expands inside a row or card; `section`, an always-open list with a heading for page-level cards), `NoteCard` ("You wrote this on <date>", Markdown body, edit / delete with an inline confirm) and `NoteEditor` (plain textarea with Write / Preview tabs through `react-markdown`; Ctrl+Enter saves, Escape cancels). Data: one `GET /notes?target_type=…` per type per page, shared by every panel on the page through React Query; each panel selects its own target's notes, matching on the canonical id or, for documents, the legacy `video_id`. The panel stops click and key events so it can live inside cards that open on click or Enter.

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
| `/shelves` | **built** (2026-10-19), see [`ShelvesPage`](#shelvespage--shelves) | [plans/m1-shelves.md](plans/m1-shelves.md) |
| `/shelves/:slug` | **built** (2026-10-19) as `/shelves/:shelfId` (ids, not slugs: names are renameable), see [`ShelfPage`](#shelfpage--shelvesshelfid) | [plans/m1-shelves.md](plans/m1-shelves.md) |
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
