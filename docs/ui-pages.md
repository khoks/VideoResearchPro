# Pratidhvani — UI Pages

**Status:** canonical (2026-04-24). This is the **single source of truth** for the frontend page inventory: every route, the page that renders it, what the user does there, and the empty / loading / error states. Visual system (colors, type, components) lives in [ui-design.md](ui-design.md). API endpoints these pages call live in [api-reference.md](api-reference.md).

The frontend is a single-page app under `frontend/src/`. Routing is `react-router-dom` v7 via `createBrowserRouter`. The route table lives at [`frontend/src/routes/index.tsx`](../frontend/src/routes/index.tsx).

---

## Route table (current)

| Path | Component | Auth | Purpose |
|------|-----------|------|---------|
| `/login` | `LoginPage` | public | Email + password login |
| `/register` | `RegisterPage` | public | Create a new account |
| `/` | `OnboardingGate` | protected | Default landing: `/welcome` while the server says the account should onboard, otherwise `/submit` |
| `/welcome` | `WelcomePage` | protected | First-run wizard: channels, a small first run, its report (S-8.10.1) |
| `/submit` | `SubmitJobPage` | protected | Start a new research run |
| `/jobs` | `JobsListPage` | protected | All jobs the user owns |
| `/jobs/:jobId` | `JobDetailPage` | protected | Single job: status, approval, report, Q&A |
| `/reports/:jobId` | `ReportReaderPage` | protected | Reading room: the run's report rendered natively with outline, drop cap, citations and progress |
| `/knowledge/:videoId` | `KnowledgeReaderPage` | protected | Reading room for a source's knowledge report (YouTube id or `document_id`) |
| `/author/outputs/:outputId` | `OutputReaderPage` | protected, Pro+ | Reading room for an Author Studio output (books today) |
| `/library` | `LibraryPage` | protected | Browse the global video library |
| `/library/qa` | `LibraryQAPage` | protected | Ask across the entire library |
| `/library/graph` | `GraphPage` (lazy) | protected | The library map: sources, channels, topics and your questions as a graph, or as a table |
| `/library/channels/:channelId` | `ChannelPage` | protected | One channel: header, subscribe / sync, trust-weight slot, its documents |
| `/shelves` | `ShelvesPage` | protected (writes Pro+) | The reader's shelves: create, edit, delete |
| `/shelves/:shelfId` | `ShelfPage` | protected (writes Pro+) | One shelf: its runs and the union of their sources |
| `/templates` | `TemplatesPage` | protected | Job templates: the reader's own (use, history, rename, delete) and the starters |
| `/saved-searches` | `SavedSearchesPage` | protected, Pro+ | Pinned library questions: schedule, next run, last answer; run now, pause, edit, delete (S-8.3.2) |
| `/qa-history` | `QAHistoryChatPage` | protected | Meta-chat across all past Q&A |
| `/exports` | `ExportsPage` | protected | Dataset export endpoints + downloads |
| `/notes` | `NotesPage` | protected | Every note the user wrote, grouped by target, searchable, exportable |
| `/author` | `AuthorPage` | protected, Pro+ | Author Studio: bind finished runs into a book; other kinds shown as coming later |
| `/echo` | `EchoPage` | protected, Studio | Echo: personal-context store, readiness meter, sources and connectors, export and delete |
| `/echo/inbox` | `EchoInboxPage` | protected, Studio | Echo's shares inbox: everything the user forwarded, with state and authorship |
| `/echo/import` | `EchoImportPage` | protected, Studio | Import an export from another service (WhatsApp, Google Takeout, Spotify, Goodreads, Letterboxd, Strava, Apple Health): preview, choose whose words are whose, import, undo |
| `/echo/connectors/:name/callback` | `EchoConnectorCallbackPage` | protected | Where a provider returns after the user approves a connector: posts the code back, then returns to `/echo?connected=<name>` |
| `/account/subscription` | `SubscriptionPage` | protected | Tier, upgrade / downgrade (demo billing) |
| `/account/ai-models` | `AIModelsPage` | protected | Per-use-case LLM overrides and BYOK keys |
| `*` | (redirect → `/`) | — | 404 → home |

Protected routes are wrapped in `<ProtectedRoute>` which redirects unauthenticated visitors to `/login`. Public-only routes (`/login`, `/register`) are wrapped in `<PublicOnlyRoute>` which redirects authenticated users to `/`, where the gate decides between the wizard and `/submit`.

`VideoKnowledgePage.tsx` exports `VideoKnowledgeDrawer` — used as an inline drawer inside `JobDetailPage` to show a video's knowledge artifact, not as its own route.

The protected routes share `<AppLayout>` (top-tabs nav today, sidebar after the redesign per [branding.md](branding.md) and [ui-design.md](ui-design.md)).

---

## Page-by-page

### `LoginPage` — `/login`
**Purpose.** Email + password login. Calls `POST /api/v1/auth/login`, stores the JWT in the auth context, redirects to `from.pathname` (or `/`, which the onboarding gate resolves).

| State | What renders |
|-------|--------------|
| Default | Email + password fields, "Sign in" button, link to `/register`. |
| Submitting | Button shows spinner, fields disabled. |
| Auth error | Inline error below the form ("Email or password is wrong."). |
| Network error | Toast via the global `ToastContainer`. |

### `RegisterPage` — `/register`
**Purpose.** Account creation. Calls `POST /api/v1/auth/register`, immediately follows with a login call to capture the JWT (the register response carries the user, not a token; until 2026-10-19 the context stored the missing token and every new account landed signed out on `/login`). Then goes to `/`, so a new account opens the wizard.

| State | What renders |
|-------|--------------|
| Default | Email + password + confirm-password, "Create account" button. |
| Validation error | Inline below the offending field. |
| Email exists | "An account with this email already exists. Sign in instead?" with link. |

### `WelcomePage` — `/welcome`
**Purpose.** The first-run wizard (S-8.10.1, plan [m10-onboarding](plans/m10-onboarding.md)): a task flow with real actions, not an overlay tour. Its state lives on the user row (`GET` / `PATCH /auth/me/onboarding`), so it resumes at the same step on any device. `/` sends an account here while `should_onboard` is true: no runs yet, or the wizard already started, and neither finished nor skipped. Accounts that had runs before the wizard shipped are not sent. **Skip for now** is always in the header (it records the dismissal and goes to `/submit`); after a skip or a finish it reads **Close** and the page stays reachable from the palette's **Getting started** action. A `Stepper` (ordered list, `aria-current="step"`) lets the reader go back to a finished step without losing what they entered.

| Step | What renders | Action |
|------|--------------|--------|
| 1. Choose channels | Channel link or @handle field (validated like the submit page's channel list), the chosen channels as removable chips, one to five | **Continue** saves the channels and the step, then shows step 2 |
| 2. Start a small run | The saved channels as radios (first chosen), what the run does, a "How long it takes" note (a few minutes; transcripts are throttled; captionless videos go through Whisper; the run pauses once for approval) | **Start the run** creates a channel run of five videos from the **Channel deep-dive** starter (`template_id` provenance), stores its id, shows step 3. A first run already under way offers **See its progress** instead; a failed one says so and offers another go |
| 3. Read the report | Live progress (`role="progressbar"`, polite status text, link to the run's page); at `awaiting_approval` the found titles with **Approve these N videos**; at `completed` **Read the report**; a failed or cancelled run shows its error with **Try again** | **Read the report** finishes the wizard (`onboarded_at`) and opens `/reports/:jobId`; a run that ended without a report offers **Open the run** |

| State | What renders |
|-------|--------------|
| Loading | Skeleton rows under the header (Skip already usable) |
| Error | `EmptyState` "Couldn't load your progress." with **Retry**; Skip still works |
| Finished earlier | A note with the date it was finished; the steps still work |

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
| First run | **Getting started** checklist card above the filters (S-8.10.2): *Start a research run*, *Read a report*, *Ask your sources a question*, each with the one link that completes it, "N of 3 done", and **Hide this** (kept on the server, `checklist_dismissed`). It disappears by itself once all three are done, so accounts that already work never see it. |
| Empty (no runs, nothing filtered) | "Nothing researched yet." with **New research** → `/submit`. |
| Empty (search or status filter returns nothing) | "Nothing matches these filters." with **Clear filters**. Until S-8.10.2 a status filter with no hits showed the first-run copy. |
| Loading | Skeletons in the shape of the header, filter card and two run cards. |
| Network error | "Couldn't load your runs." with **Retry**. |
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
| **Q&A panel** | status == `completed` | Question textarea, "Clarify first" optional toggle, language selector, "Ask" button. Below: list of past exchanges with citations rendered as chips that deep-link to `&t=` timestamps. Each exchange card carries the inline notes control (target `qa_exchange`). Under 640 px the composer moves below the thread and docks at the bottom of the screen while the panel is in view, above the keyboard (S-8.12.1). **You might ask** (S-8.4.2): under the composer, up to five suggested next questions from `GET /suggestions` (generated from the context, or the reader's own past questions, marked "You asked this before."). A click fills the composer; Shift-click asks at once, skipping the clarify step. Each use is logged through `POST /suggestions/feedback`. The card loads after the page, shows "Finding questions worth asking…" meanwhile, and renders nothing when there is nothing to suggest, when the request fails, or when the Q&A feature is down. Context `job:<id>`. |
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

**Small screens (S-8.12.1).** Below 1200 px the outline column and progress pill give way to a bottom reading toolbar: Contents (the outline as a bottom sheet, focus on the current section, Escape closes and returns focus), A− / A+ text size (five steps, kept per browser), theme, and the percentage. On touch, the first tap on a citation chip previews its card; a second tap, or the card's "Open at" link, opens the source; a tap elsewhere closes it. The same toolbar serves the knowledge and book readers.

### `LibraryPage` — `/library`
**Purpose.** Browse the caller's view of the global, deduplicated library and add sources that do not come through a research run. Three tabs: **Sources**, **Channels**, **Add sources**.

**One source** (`/library?document=<document_id>`, S-8.2.2): where a palette or search result for a source lands. The Sources tab shows only that row under a banner, "Showing the one source you opened from search", with **Show all sources**, which drops the parameter.

**Sources tab.** Filters: search text, language, channel, transcript status. Sort: newest / oldest / longest / shortest. Rows for PDFs and pasted pages carry a source-type pill instead of a channel, and no duration. Above the filters, a **Tag** bar (S-8.1.3): a tag select with counts, the active tag as a pill with **Clear**, and **Manage tags** (a dialog to rename, recolour, merge into another tag, or delete, with the source count). The tag lives in the URL (`/library?tag=<id>`), so every tag chip in the app is a plain link; the bar hides until the reader has a tag. Each row shows the reader's tag chips and a **+ Tag** control (checkbox per tag, saved on toggle; inline create applies the new tag). The same rows on a channel page and a shelf page carry the same control. Every row ends with the inline notes control ("N notes · + Add a note"); the channel rows on the **Channels** tab carry the same control, and typing in it never opens the channel.

| State | What renders |
|-------|--------------|
| Default | Row list. Each row: thumbnail (or source-type placeholder), title, channel or source type, duration where it applies, language pill, transcript-status pill, "referenced in N runs" footer, open link. |
| Filtering | Filter controls at the top; results update in place. |
| Empty (no sources, nothing filtered) | "Your library is empty." with **Add sources**, which opens the Add sources tab (S-8.10.2; it used to say "Nothing matches these filters." with no filter set). |
| Empty (filters return nothing) | "Nothing matches these filters." with **Clear filters**, which clears search, language, channel, transcript status, tag and the one-source filter. |
| Error | "Couldn't load your sources." with **Retry**. |
| Loading | Skeleton cards on the first page; later pages keep the list. |

**Channels tab.** Empty: "No channels yet." with **Start a channel run** (→ `/submit`); error: "Couldn't load channels." with **Retry**; loading: skeleton cards (S-8.10.2). One `ChannelRow` per channel this tenant can see ([D-065](decisions.md#d-065--channel-subscriptions-become-per-tenant-transliteration-reversed-2026-07-31)): name (a real link), subscribers, volumes on your shelf, last synced, Subscribe / Sync now. The row and the name open the channel's page (`/library/channels/:channelId`, below). `/library?tab=channels` (or `?tab=ingest`) opens the page on that tab; the channel page's breadcrumb uses it.

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
| **Trust weight** | Sunken card (`data-slot="trust-weight"`): a badge (`1.0 · neutral`, otherwise promoted / demoted), a 0.0–2.0 slider in steps of 0.1 that holds a draft, **Save** (`PUT /channels/{id}/weight`, disabled until the draft differs) and **Reset** to 1.0. A failed save shows an inline alert. The copy states the measured trade-off ([D-068](decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18), T-7.1.1.5): raising a weight also narrows answers toward the channel, and near 0 a channel appears only when little else matches. |
| **Documents** | Heading with the visible count, filter card (search titles, transcript status, sort), the rows (`channelLink={false}` so they do not link back to the page), pager at 50 per page. |
| **Documents / Intelligence tabs** | Below the trust-weight slot; the tab is in `?tab=intelligence` so it can be linked (S-8.7.3). **Documents** is the filtered list above. **Intelligence** reads `GET /channels/{id}/intelligence` over the documents of the channel the reader can see: a "Read … over N documents" line with **Refresh**; a **coverage** card (share of documents with a knowledge report, a meter, how many lack a transcript) with **Extract knowledge for N documents**; **Publishing** (monthly columns, keyboard-readable with ←/→, Show as table); **Length** (six duration buckets and the median); **Topics** and **Concepts** (ranked bars; each row opens to its example documents, linked to the source); **Words it keeps using** (a text keyword cloud, alphabetical, sized by weight); **Your questions about it** (the reader's job and library answers that cite the channel, linked); **Stance and sentiment** (stacked monthly columns with a legend where social classification exists, otherwise the reason); **Concept map** (S-8.9.2: **Show the concept map** loads the library map scoped to this channel, topics and questions only, in place; **Open in the library map** goes to `/library/graph?channel_id=`). Each panel shows the aggregate's `notes` when it is empty or partial. |
| **Extract knowledge for N documents** | Plans at most the reader's remaining monthly knowledge extractions (`GET /auth/quota`), confirms ("This makes N knowledge reports, one after another, about a minute each, and uses N of your … Keep this page open"), then runs the existing `POST /videos/{id}/extract-knowledge` one document at a time with a progress bar, the current title and **Stop after this one**. Stops at the first quota refusal; skips no-transcript / already-done; summarises made / skipped / failed; refreshes the aggregate. Disabled while the knowledge LLM is down. |

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
**Purpose.** One shelf as a filtered view of the library. Header: eyebrow with the colour dot, name, description, "N runs · updated …" (plus "read-only on your plan" when the tier lacks shelves), Edit / Delete for Pro+. **Runs**: one row per run (title link, status pill, type, sources · created), **Remove** for Pro+. **Sources**: the union of the runs' documents, each once, through `GET /shelves/{id}/documents` (visibility-scoped, D-063), with the library's search / transcript / sort filters and paging (`DocumentsBrowser`, shared with the channel page). **Ask this shelf** (S-8.1.4), between Runs and Sources: a question box, answer language and **Ask this shelf**, then the shelf's own history (`GET /shelves/{id}/qa`) as library exchange cards; answers draw only on the shelf's sources. On a shelf with no sources it says there is nothing to ask instead of showing the box.

| State | What renders |
|-------|--------------|
| Loading | Header skeleton. |
| 404 (foreign or deleted) | "This shelf isn't here." with **All shelves**. |
| No runs | "No runs on this shelf yet." with **Go to active runs**. |
| No sources | "No sources on this shelf yet." Ask this shelf: "This shelf has no sources yet, so there is nothing to ask." |
| Q&A down | Ask this shelf disabled, with the reason as its tooltip; the history still shows. |
| Deleted from here | Navigates to `/shelves`. |

### `TemplatesPage` — `/templates`
**Purpose.** The reader's job templates and the starters (S-8.6.1, [M6](plans/m6-job-templates.md)). Each card: name, type, `vN · updated …` (or a **starter** badge), description, a one-line summary of the recipe (videos, depth, preferred channels, durations, filters, visual analysis), the instructions in italics, and any **problems** (e.g. "Asks for 300 videos; the free plan allows 100"). Actions: **Use** (opens `/submit` with the template applied), **History** (when there is more than one version: each version with its date and summary), **Rename** (name and description), **Delete…** (two-step; says that runs keep pointing at the version they used). Starters have **Use** only. The five starters (S-8.6.2) are Topic scan, Deep dive, Quick brief, Channel deep-dive and Subscription follow; the channel ones read "you add the channels" in their summary, and on the submit form their banner says "Add the channels".

| State | What renders |
|-------|--------------|
| Loading | Two row skeletons. |
| No templates of your own | "No templates of your own yet." pointing at Save as template on a run or the submit form. |
| Error | Editorial error card with Retry. |

### `SavedSearchesPage` — `/saved-searches` (Pro+)
**Purpose.** Every library question the reader pinned (S-8.3.2, plan [M3](plans/m3-saved-searches-alerts.md)). Each card: the question, badges (**Paused**, the last run's status: **Answered**, **Last run failed**, **Skipped: monthly quota**, **Not in your plan**, **Shelf deleted**; **One shelf** when scoped), the schedule in words ("Weekly on Monday at 09:00", the zone named only when it is not the reader's), next run and last run in local time, whether it emails, the last run's reason when it did not answer, and the last answer clamped to four lines with **Read the full answer, with citations** (→ `/library/qa?exchange=<id>`). Actions: **Change schedule** (the same daily / weekly / monthly fields as the pin dialog), **Stop emails** / **Email me**, **Pause** / **Resume**, **Run now** (queues a run; "Queued. The answer appears here in a minute or so."), **Delete** (confirms; past answers stay in library Q&A). "N of M active" shows the tier's cap. The list polls every 10 s while a search has never run. The sidebar's Library group and the palette link here on tiers with the feature.

| State | What renders |
|-------|--------------|
| Loading (tier or list) | Skeleton cards; the plan message never shows before the tier is known. |
| Nothing pinned | "Nothing pinned yet." with **Ask the library**. |
| Error | "Couldn't load your saved searches." with **Retry**. |
| Tier without the feature | "Saved searches come with Pro." with **See plans**; nothing is fetched. |

**History** (S-8.3.3) opens a card's last runs: a badge per run (**Changed**, **No change**, **First answer**, **Nothing new to read** for the gate's skip, or the skip reason), when, whether it was scheduled or Run now, what changed ("Now cites 1 new source: …", or the judge's sentence), and links to **This answer** and, for a change, **The previous answer**. A notification lands here as `?search=<id>&run=<id>`: that card scrolls into view with its history open and the run outlined.

### `LibraryQAPage` — `/library/qa`
**Purpose.** Ask questions across the entire library, with no per-job filter. The history holds shelf questions too (S-8.1.4): a scoped exchange reads "Asked on shelf Rates" above its question (a link to the shelf, or "a shelf that no longer exists"), so it never passes for a library-wide answer.

Layout: question textarea + clarify-first toggle + language selector at the top; past exchanges below ordered ascending by `created_at`, each with citation chips that link to the source video at the cited timestamp and the inline notes control (target `library_qa_exchange`). A YouTube chip whose video the reader can see also names its channel as a link to `/library/channels/:id` (S-8.7.4); the same holds for the Q&A panel on a run's page. A chip for one of the reader's own notes (S-8.5.2) reads "You wrote this on <date> · on <target>", in italics, shows the note's opening on hover, and links inside the app to what the note is on (the run, the channel page, the shelf, or `/notes` when the target cannot be linked).

| State | What renders |
|-------|--------------|
| Default | Textarea + button + history list. Under 640 px the composer docks at the bottom below the history, as on the job page (S-8.12.1). **You might ask** (S-8.4.2): under the composer, up to five suggested next questions from `GET /suggestions` (generated from the context, or the reader's own past questions, marked "You asked this before."). A click fills the composer; Shift-click asks at once, skipping the clarify step. Each use is logged through `POST /suggestions/feedback`. The card loads after the page, shows "Finding questions worth asking…" meanwhile, and renders nothing when there is nothing to suggest, when the request fails, or when the Q&A feature is down. Context `library`. A question handed over from the knowledge drawer (route state) fills the composer, or is asked at once after a Shift-click. |
| Clarifying | Inline "Interpretation: ..." plus three suggested clarifying questions; user picks one or types their own context. |
| Pin (Pro+) | Each answer card carries **Pin this question** beside **Copy answer** (S-8.3.2). The dialog shows the question and asks only when: daily, weekly or monthly, the day, the hour in the reader's zone (weekly at 09:00 by default), and "Email me when the answer changes". **Pin it** creates the saved search; the button becomes a **Pinned** link to `/saved-searches`. Hidden on tiers without `saved_searches`. |
| Asking | Streaming answer area appears; citations populate as the agent extracts references. |
| Empty (no exchanges yet) | Composer and an empty thread. |
| Empty library | "Nothing to ask yet." with **Add sources** (→ `/library?tab=ingest`) in place of the composer, when the reader can see no source and has asked nothing (S-8.10.2). |
| LLM down | Banner + Ask disabled. |

### `GraphPage` — `/library/graph`
**Purpose.** The library map (S-8.9.2, [M9 plan](plans/m9-citation-graph.md)): the reader's sources, their channels and topics, and the questions they asked of them, from `GET /library/graph`. Loaded lazily, so sigma and the layout worker download only here and in a channel's concept map. Reached from the sidebar (**Library map**, under Library) and the channel page.

| Element | Behaviour |
|---------|-----------|
| **Filters** | One row: **Map / Table**; **Show** ▸ Channels, # Topics, ? Your questions; **Shelf**; **Single-link nodes** (off by default on the whole-library view, with the hidden count). Scope chips below: "Centred on …" with a 1–3 step **Depth** slider, "Channel: …", "Run: …", each removable. Everything is in the URL (`focus`, `depth`, `shelf_id`, `channel_id`, `job_id`, `types` (`none` = sources only), `leaves=1`, `view`); a new centre is a Back step, filter changes replace the entry. |
| **Summary and legend** | The server's one-paragraph summary, plus how many single-link nodes are hidden. The legend names the three largest groups (colour dot, size, main topics), then "Other groups" in grey, and the glyph key. |
| **Map** | A 560 px canvas (360 in the concept map). Size shows connections; colour shows the group; a glyph shows the kind. Hover shows a label; click opens the card and dims everything outside the node's neighbourhood; double-click re-centres. Nine buttons top right: zoom in / out, reset, pan in four directions. The layout animates once and freezes ("Arranging the map…" meanwhile); with reduced motion it is computed before the first frame. |
| **Keyboard** | The map is one tab stop. Arrows move to the nearest node that way (neighbours first); Enter opens the card, Escape closes it, Home returns to the most connected node (or the centre), + / − / 0 zoom, Shift + arrow pans. A ring marks the focused node and a live region reads "Topic: Housing. 5 connections. Group 2." The key help sits under the canvas. |
| **Detail card** | Name, kind, group, connections here and in the whole library, date or source count; links: **Open the source** (new tab), **Channel page**, **Open the answer** (`/library/qa?exchange=` or `/jobs/:id?exchange=`); **Centre the map here**; "Connected to" lists up to eight neighbours as buttons. |
| **Table** | The same nodes as the map, most connected first: name (opens the card), kind, group, links, connected to (four, then "and N more"); **Show all N connections** adds the edge table (from, relation, to). The default view under 640 px. |

| State | What renders |
|-------|--------------|
| Loading | A card skeleton; a filter change keeps the old map until the new one arrives ("Updating…"). |
| Empty library | "Nothing to map yet": the map draws your sources, their channels and topics, and your questions. |
| Empty scope | "None of your sources falls in this view." |
| All single-link | "Every node here has a single link" with **Show single-link nodes**. |
| Unknown centre | "The node you asked for is not on your map, so the whole library is shown." |
| Foreign shelf or run | "Not found": that shelf or run is not yours, or it no longer exists (the endpoint's 404). |

### `QAHistoryChatPage` — `/qa-history`
**Purpose.** Meta-chat across every Q&A the user has ever run, powered by `qa_library_global`.

Layout: chat-like — past meta-questions and meta-answers. Each meta-answer cites past *exchanges* (not videos directly), and each citation deep-links to the originating job-detail or library-Q&A page. Each card carries the inline notes control (target `qa_history_exchange`).

| State | What renders |
|-------|--------------|
| Default | Full chat scroll, latest at the bottom. New question textarea is sticky at the bottom. |
| Empty (no past exchanges anywhere) | "Once you've asked questions on a job or library page, they'll start echoing here." |
| Empty (past exchanges exist but no meta-questions yet) | "Ask anything across your past questions. e.g. 'What have I learned about supply chains?'" |
| Asking | Inline "thinking" indicator with skeleton paragraphs. |
| Loading | Skeleton cards (S-8.10.2). |
| Error | "Couldn't load your echoes." with **Retry**; the composer still works. |
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

Layout: one card per dataset (Q&A, knowledge, notes), each with its description and download buttons. There are no row counts.

| State | What renders |
|-------|--------------|
| Default | Three cards. |
| No questions yet | The Q&A card says both files download empty, from the onboarding `questions` milestone (S-8.10.2). The buttons still work. No count exists for the knowledge dataset, so it has no such note. |
| Downloading | A toast on start and on failure. |

### `AuthorPage` — `/author` (Pro+)
**Purpose.** Author Studio. Turn finished research runs into long-form output. Backend: `backend/app/routers/author.py`. Only `book` has a generator today; the page never offers a kind that would 501.

Sections: **What you can make** (one card per kind from `GET /author/kinds`: `available` kinds get a "New …" button, the rest read "Coming later · E-6.x"), **Your outputs** (kind / status filters, one row per output), a **create modal**, and a **delete confirmation**. Reading happens in the reading room at `/author/outputs/:outputId` (S-8.8.3), which replaced the page's own reader modal.

| State | What renders |
|-------|--------------|
| Below tier, or API 403 | Editorial lock: "Author Studio opens at Pro." with a "See plans" button → `/account/subscription?upgrade=pro`. |
| Kinds loading | Three skeleton cards. |
| Create (book) | Modal: title; chapter picker over the user's topic / channel runs (filterable; runs not completed or without a report are listed but disabled with the reason); "Include each run's Q&A" and "Table of contents" toggles. Generate runs synchronously; a `completed` result opens it in the reading room, a `failed` one toasts `error_message`. |
| Outputs empty | "Nothing authored yet." with a "New book" button; with filters active, "Nothing matches these filters." |
| Output row | Status pill (Ready / Failed / Generating / Pending), title, kind, source count, created date; **Read** (→ `/author/outputs/:id`) and **Download** when `has_content`; **Delete** always. Failed rows show `error_message` in full; pending rows explain they were created when their kind had no generator. |
| Delete | Confirmation modal; the runs the book was built from are untouched. |
| Digest by email (S-6.4.2) | Shown when `newsletter` is available. Off: "Turn on" with cadence (the saved-search schedule fields) and section toggles. On: the cadence in words and the next issue time, **Save changes**, **Send one now**, **Turn off** (keeps settings), **Unsubscribe** (removes them), and the latest sends ("Sent · read it", "Nothing new, not sent", "Made, but the email failed"). |

### `EchoPage` — `/echo` (Studio)
**Purpose.** Echo's personal-context store. Backend: `backend/app/routers/echo.py`. Honest about scope: it says so wherever a part is not built or not switched on. Since S-3.4.1 "speak as me" is built but off until two switches are on, and the page shows which are still off.

Sections: **Readiness**, **Connectors** (with **Sources on record**; S-3.2.1: one row per connector the install offers, with its privacy weight and status, **Connect** opening a consent dialog that shows the disclosure and what is recorded before any redirect, then **Sync now** and **Disconnect** (a confirmation saying how many events go); an auth failure offers **Reconnect**, a changed disclosure **Review and reconnect**; `?connected=<name>` after the callback shows a confirmation), **Activity** (S-3.2.1: the timeline, newest first, twenty at a time with **Show older**; events from an export import are labelled by service, such as Spotify or YouTube (Takeout), S-3.7.5), **What Echo knows** (grouped by the 10 kinds), **How you sound** (S-3.3.1), **Your Echo data** (S-3.10.1 / S-3.10.2), a **Not here yet** footer, and three modals (add / edit, forget, revoke). The subtitle links to the shares inbox.

| State | What renders |
|-------|--------------|
| Below tier, or API 403 | Editorial lock: "Echo opens at Studio." → `/account/subscription?upgrade=studio`. |
| Readiness | Since S-3.5.1 ([D-101](decisions.md#d-101--echo-readiness-v2-five-domains-measured-from-their-stores-blocked-reads-as-not-connected-the-voice-test-reported-not-gated-2026-10-20)): a large percentage, the mean of the five domains' progress and 100 only when the backend says `ready`, with "Five parts, all required." Then one row per domain (`components/echo/ReadinessDomains.tsx`): Facts about you, What you do, How you think, How you write, What you share. Each row has a status badge (Done, On the way, Not started, Not connected), a progress bar, the server's summary, and what is missing in words. The shares row links to the inbox. *What you do* lists each activity source with its status and event count; a connector the install cannot offer yet, such as YouTube likes or Google Calendar, reads "not connected" with its reason. *How you write* says when stability cannot be measured and how many notes remain before the user can take the voice test that switches on "speak as me" (D-100). An older backend without `domains` falls back to the three v1 gates. |
| Connectors empty | "No connectors yet." with the planned list. Sources on record lists each `source` with its row count and a **Revoke** button (confirm → `DELETE /echo/sources/{source}`; the toast reports `deleted_count`). |
| Context browser | Filters: kind, source, "Show expired" (`include_expired`). Every known kind renders as a card, empty or not, each with an **Add** shortcut preselecting that kind; rows show label, value, source pill, confidence, captured date, expiry (an **Expired** pill when past). **Edit** reopens the form with kind and label locked (the backend upserts on `(kind, key)`; renaming means forget + add). **Forget** confirms, then `DELETE /echo/context/{kind}/{key}`. |
| Add / edit modal | Kind, label (≤128 chars, no `/` because the key travels as a path segment; warns when the label already exists under that kind and would overwrite), the fact, confidence 0–1, optional expiry date (sent as end-of-day UTC). Source is always `manual`. |
| Loading | Skeleton rows / paragraphs per card. |
| Error | Inline retry line per card; the browser uses an editorial error state with Retry. |
| How you sound | `SignalsPanel` (S-3.3.1): what Echo learned about the user's style and personality, from `GET /echo/signals`. Two layers, **How you write** (style) and **What you think** (personality), each with an **Add** button; inside a layer, one block per signal type that has signals, in the vocabulary's order. A row shows the signal, its language and audience pills when set, where it came from ("You added this", "You corrected this", "Learned from your writing", "Measured from your writing") with the evidence in words ("from 2 × a note, a question you asked", "something you wrote elsewhere" for a connector's events, never a raw id), and a collapsible list of up to five verbatim examples. **Edit** corrects the wording, language or audience (the type is locked). **That's not me** confirms, then `DELETE /echo/signals/{id}`: a tombstone, so the signal leaves the list and is never learned again; re-adding it is refused with a toast that says so. An empty layer says signals appear as Echo reads notes and questions. **Export voice profile** downloads `GET /echo/signals/export`. Under the intro, the learning line (S-3.3.2) reads `learning`: "N texts are waiting to be read. Echo last learned on <date>. Echo starts on its own once 10 are waiting." with **Learn now** (`POST /echo/signals/learn`; the toast says whether a run was queued or nothing was waiting), "Up to date: Echo has read all N of your texts." when nothing is waiting, or, with no texts yet, that Echo learns from notes, questions and the user's own shares. When the install has learning off, the line says so and offers no button. The footer names the learning-terms version and that shares the user did not write never shape signals. Actions wrap under the signal at phone width. |
| Speak as me (S-3.4.1) | `SpeakAsMePanel`, mounted for tiers with `echo_speak_as_me` ([D-102](decisions.md#d-102--speak-as-me-two-switches-guards-in-code-the-reply-in-the-users-language-2026-10-20)). While any gate is shut: an **Off** badge and one line per blocker from `GET /echo/draft/status`, in the server's words, in order (install switch, readiness, voice test, daily cap), with no composer. Once on: a composer (the message, an optional audience, register and language) and **Draft**. A message naming a private person shows the names with **Draft anyway** and **Cancel**. The draft opens as an editable **Your version** (S-3.4.2), with the hint that Echo learns from the words the user types, never from its own. An **Add the disclosure line** checkbox ("Drafted with Echo, reviewed by …", on by default) decides what **Copy** puts on the clipboard. **Save my version** sends the version and the checkbox to `POST /echo/drafts/{id}/feedback`, then says "Saved. Echo learns your voice from the N words you wrote, never from the ones it drafted.", adding that words repeated from their message are left out when there were any. It is disabled until something changes again. The same `DraftEditor` is the bubble's draft view. Below: "Sounds like you: N% · grounded N%", citations (an external link for a source at its timestamp), deviation notes, and a note when a quoting sentence was removed. An opened recent draft shows the saved version. The daily cap reads in words. Below: recent drafts with **Delete**. Pure helpers in `frontend/src/utils/echoDrafts.ts`. |
| Add from your browser (S-3.7.3) | `ShareTokensCard`: explains the extension and how to load it, shows the **server address** to paste (the API's origin) with **Copy**, and **Make a share token** with a label. A new token is shown once in a highlighted box with **Copy token** and "it is not shown again". The list gives each active token's label, first characters, date made and last use ("Never used", "Used 3 days ago"), with **Revoke**. At the cap the button is disabled with a note. |
| Your Echo data | `EchoDataCard`: what the archive holds, then "Echo holds: N facts · N shares · N signals · N files · N search vectors" from `GET /echo/brain/footprint`. **Export everything** downloads the zip through an authenticated blob fetch (no token in the URL). **Delete everything Echo knows** opens a modal that restates the counts, says there is no undo, and enables **Delete permanently** only after the user types DELETE; the toast reports "Echo now holds nothing about you." when the server's after-count is zero. Both buttons are disabled when Echo holds nothing. |

Pure logic (gates, the readiness percentage, grouping, expiry, label validation) lives in `frontend/src/utils/echoReadiness.ts`; the signal vocabularies, grouping and evidence wording in `frontend/src/utils/echoSignals.ts`.

### `EchoInboxPage` — `/echo/inbox` (Studio)
**Purpose.** The shares inbox (S-3.7.1): everything the user handed to Echo, newest first, with no approval step. Same Studio lock as `EchoPage`. Header: back link to Echo and an **Add to Echo** button.

| State | What renders |
|-------|--------------|
| Default | Search (debounced; text, links, file names, annotations) and a state filter; then one card per share: content-type badge, **Your words** or **Context only** (tooltip explains the default), processing state ("Waiting for processing" until S-3.7.2 exists), shared date; the link, the text (scrollable block, gold rule for the user's own words) or the file name, size and **Download**; the "why" annotation. Actions: **Add why** / **Edit why** inline, **These are my words** / **Not my words**, **Delete** (confirm: the share, its file and anything derived are removed). |
| Processing (S-3.7.2) | A processed link shows its resolved title and author above the URL, and the opening of the extracted text below it. A processed file says how it was read: "Text read by local OCR", "Text read by a vision model", "Transcribed by Whisper · 0:13 · Hindi", "Text from 12 of 14 pages". A note, when there is one, follows in muted text (low confidence, text cut short, nothing found). A failed share shows the reason in red with **Retry**; a skipped share shows why it was not read, also with **Retry**. An eligible link shows **Add to library**; once added, **In your library →**. |
| Drop zone (S-3.7.3) | Not this page only: `EchoDropZone` is mounted in the app chrome for Studio. Dragging files, a link or text in from outside shows a full-window "Drop to add to Echo" overlay; drags that start inside the page and drops onto text fields are left alone. Files are uploaded (up to 10 per drop) and links and text are shared, all with `surface=drag_drop`, each confirmed by a toast. A dropped WhatsApp or Takeout export opens `/echo/import` with that file already previewed. |
| Sources (S-3.7.3) | A share with a source (a quote or image from the extension) shows "From <page title>" linking to the page. |
| Imports (S-3.7.5) | The header links to the import page. A third filter picks **Shared one at a time** (the default), **From imports** or **Everything**. `?import=<id>` shows one import oldest first, with a banner and **Back to the inbox**. An imported card shows where it came from ("WhatsApp chat with Asha · Asha" or "Keep · Tariff thoughts · Essays") with the time it was written, and says "Imported" rather than "Shared". |
| More than 100 | "Show N more" grows the page by 100. |
| Empty | "Nothing shared yet." pointing at Add to Echo; with filters, "Nothing matches." |
| Loading / error | Skeleton rows; editorial error with Retry. |

Pure logic (quick-share parsing, labels, sizes, footprint sums) lives in `frontend/src/utils/echoShares.ts`, unit-tested.

### `EchoImportPage` — `/echo/import` (Studio)
**Purpose.** Bring an export from another service into Echo (S-3.7.5). Same Studio lock as `EchoPage`. Linked from the Echo page and the inbox.

| State | What renders |
|-------|--------------|
| Pick a file | A file picker (`.txt`, `.zip`, `.json`). Choosing a file runs the preview at once; nothing is stored. |
| WhatsApp preview | The detected kind, then "with Asha: 6 messages from … to …, stored as 4 turns". **Which of these is you?** lists each participant with a message count, plus "None of them: keep it all as context". **Keep only my side of the chat** is enabled once a participant is chosen and explains what happens to the others' messages either way. When no date decides day-first or month-first, a select re-reads the dates. A line names the browser's time zone, used for the phone's local times. **Import** stays disabled until a participant is chosen. |
| Keep preview | Note counts and date span, warnings for other Takeout products in the archive, **These notes are my own words** (on by default) and **Include notes in the trash**. |
| Takeout preview | "N Keep notes, N watched videos and N searches from … to …. Ads are left out." **Keep notes** and **YouTube watch and search history** switches choose which parts to import; Keep's two switches show while notes are included. |
| Event previews | One line per service: Spotify plays, hours, span and top three artists ("Private-session plays are left out."); Goodreads books by shelf and how many carry your review; Letterboxd films watched, reviews and watchlist; Strava activities and how many carry your description ("Routes are not read."). |
| Apple Health preview | The three summaries it would store (hours asleep with typical bedtime and wake time, daily steps, workouts a week by type), a **Summarise the last** select (3 months, a year, 2 years) and "Only these summaries are kept." For exports past the upload cap, the header points to the command-line importer. |
| Your imports | One card per import: importer, status (Importing, Indexing with progress, Imported, Needs a retry, Undoing), filename, date, and a line such as "4 turns: 2 in your words, 2 context only · 4 of the other side's messages not stored" or "3 plays recorded · 2 already in Echo · 1 private-session play left out". **See what it stored →** opens the inbox on that import (share importers only). **Retry indexing** appears after a failure. **Undo import** asks first, then removes everything the import stored: shares, the events it added and the summaries it recorded. The list polls while an import is indexing. |

Pure logic (labels, count lines, provenance, the browser time zone) lives in `frontend/src/utils/echoImports.ts`, unit-tested.

### `KnowledgeReaderPage` — `/knowledge/:videoId`
**Purpose.** A source's knowledge report in the reading room (S-8.8.3). `GET /videos/{id}/knowledge` (YouTube id or `document_id`, resolved through the tenant's visibility grants) supplies the Markdown and, since S-8.8.3, the source's title, channel, kind, URL and dates. The Markdown's leading `# Title` becomes the page title and leaves the body; "From <source title> · <channel> · Extracted <date>" sits under it; tiles count topics, concepts, events and facts; toolbar: Back, Open the source, Print or save as PDF.

Rendering goes through `parseMarkdownDoc` (`components/reader/parseMarkdown.tsx`): remark-parse → remark-gfm → remark-rehype → one tree transform → hast-util-to-jsx-runtime, run once in a `useMemo` so the outline exists before the body renders. The transform assigns heading ids with the same slugger reports use, collects `h2`/`h3` into the outline, demotes stray `h1`s, wraps tables in a scroll region, marks the drop-cap paragraph, sends external links to a new tab, and repoints in-page links whose target was slugged differently. Raw HTML in the Markdown is dropped, never rendered, and link and image URLs pass react-markdown's `defaultUrlTransform`.

| State | What renders |
|-------|--------------|
| Loading | Spinner, "Opening the knowledge report…". |
| Not extracted (404) | `EmptyState` "No knowledge report for this source yet" + Back. |
| Error | `EmptyState` with the message + Back. |

### `OutputReaderPage` — `/author/outputs/:outputId` (Pro+)
**Purpose.** An Author Studio output in the reading room (S-8.8.3). Metadata from `GET /author/outputs/{id}`, Markdown from `/content`, rendered through `parseMarkdownDoc` like a knowledge report. The book's `# Title` is the page title; the outline is built from the two shallowest structural heading levels, so it lists each chapter (`##`) with its report's sections (`####` since S-6.1.2) beneath, while headings inside list items stay out of it; the outputter's table-of-contents links are written against its own slug of the bare chapter title (`#chapter-title`) while the heading reads "1. Chapter title", and the transform repoints them so every link lands. Tiles: sources, sections, words. Toolbar: back to Author Studio, Download (the loaded Markdown as a blob, same filename as the Author page), Print or save as PDF.

| State | What renders |
|-------|--------------|
| Loading | Spinner, "Opening the manuscript…". |
| 403 | `EmptyState` "Author Studio is not on your plan". |
| 404 | `EmptyState` "This output does not exist" (deleted, or another account's). |
| Not completed / no content | `EmptyState` with the status, or the failure message. |

### `VideoKnowledgeDrawer` (inside `JobDetailPage`)
**Purpose.** View or generate the per-video knowledge artifact. The drawer is the quick peek; "Open in reader" (primary, once an artifact exists) goes to `/knowledge/:videoId`.

Tabs: **Structured** (topics / concepts / events / facts) and **Report** (Markdown render).

| State | What renders |
|-------|--------------|
| Not yet extracted | "No knowledge report yet for this video." + "Generate" button. |
| Extracting | Progress indicator, disabled drawer-close (so user doesn't accidentally lose progress). |
| Extracted | Two tabs populated; "Regenerate" button at the bottom (calls the endpoint with `?force=true`). Under the report, **You might ask** for this source (context `document:<id>`, S-8.4.2), noted "Asked across your library.": there is no per-source Q&A, so a click opens library Q&A with the question filled in and a Shift-click asks it there; hidden while library Q&A is down. Below the report: "Your notes on this report" (section-variant notes panel, target `knowledge_artifact`; the target only exists once extraction has run). |
| LLM down | "Generate" disabled with a tooltip pointing at health status. |

---

## Cross-cutting page concerns

### Command palette (every protected page)
`components/palette/` (S-8.2.2), mounted once in `AppLayout`. **Mod-K** or **Ctrl-Alt-K** anywhere, or the sidebar's **Search…** button (a search icon in the mobile bar). An input with combobox / listbox semantics (focus stays in the input; arrows move `aria-activedescendant`; Enter opens; Escape closes and returns focus). With no query: **Recent** (the last six items opened from it, per browser) and **Go to and do** (every page in the nav, **Getting started** for the first-run wizard, export notes as Markdown or JSON-LD, switch theme, turn single-key shortcuts off / on). Typing filters the actions on the client and, after 180 ms, asks `GET /search` (superseded requests are cancelled), showing **Runs**, **Sources**, **Channels**, **Questions** and **Knowledge reports** groups; empty groups are hidden. States: "Searching…" while the debounce or request is pending, "Nothing in your library matches “…”", and "Search is unavailable" (actions still work); the result count is announced politely. The panel and `cmdk` load on first open (a 19.6 kB-gzip chunk).

Where results land: a run → `/jobs/<id>`; a question → its page with `?exchange=<id>`, which scrolls to the exchange card, focuses it and outlines it briefly (job page, library Q&A, Q&A history; the history page also keeps its `#exchange-<id>` links); a source → `/library?document=<id>`, the library narrowed to that row with "Show all sources"; a knowledge report → `/knowledge/<id>`; a channel → its page.

### Echo panel (every protected page, Studio)
`components/echo/EchoPanel.tsx` (S-3.8.1), mounted once in `AppLayout` behind `echo_personal_brain`.

**Openers.**
- Desktop: a floating **Echo** bubble at the bottom right.
- Under 960 px: a 44 px button in the mobile bar, so nothing floats over the docked Q&A composer.
- Everywhere: **Mod-Shift-E**, which also works from inside a text field.
- The palette's **Ask Echo**, which shows the shortcut.

**The panel** is a dialog role. On desktop it is non-modal, sits above the bubble and stays open across pages. Under 960 px it fills the screen and closes when a link inside it leads away. Escape closes it and focus returns to the opener; Tab wraps.

Top to bottom:
- **Echo**, an **AI** badge, and "You are talking to an AI. It answers from your library, notes and past questions, and can be wrong: check what it cites."
- Readiness in one line, with **What counts** linking to `/echo`. Since S-3.5.1 the line names the unmet domains, such as "24% ready. Still needs more facts about you and writing of your own." Against an older backend without `domains`, it names the v1 gates instead: "Still needs 60 more facts, 2 more sources and a personality trait."
- Two tabs, then the conversation, then the composer.

| Mode | What renders |
|------|--------------|
| Ask | **My library** / **My past questions**, a field (Enter asks, Shift-Enter breaks the line) and **Ask**. A library answer is Markdown with its sources (citation links) and "Saved in Library Q&A →". A past-questions answer lists the exchanges it drew on, each linking to where it was asked. Failures say why ("You have reached today’s limit for this…"). When the model for the chosen target is down, **Ask** is disabled and says so. |
| Draft as me | The per-user gate in words, never hidden: S-3.4.1's blockers, the first as the title. "Turned off on this install". "Echo is not ready yet", shortened to point at the readiness line above, with **See what is missing →**. "Your voice test comes first" with the notes the test still needs and **Write a note →**. "Your voice test has not passed yet". "That was today’s last draft". "Not on this install yet" if the endpoint is missing. Once on: a field for the message to answer and **Draft a reply**. A message naming someone who looks like a private person returns the server's warning with **Draft anyway**, which resends with those names acknowledged. Other refusals show the server's own words. The draft comes back with "Sounds like you: 82%" (S-3.4.1's 0 to 100 score), any flags, deviation notes, its sources (marker and label; a source at its timestamp opens in a new tab). Since S-3.4.2 the draft is the same `DraftEditor` as the Echo page card: an editable **Your version**, **Add the disclosure line** (on by default), **Copy** and **Save my version** through `POST /echo/drafts/{id}/feedback`. |

**Cards (S-3.8.2).** While the conversation is empty, up to three one-line cards sit above it:
- a saved search whose answer changed (**See what changed →**, which also marks the notice read);
- "New in your shares inbox" with what was read and what needs a retry (**Open the inbox →**);
- "You might ask" with up to three questions for the page in view. A question goes into the Ask field.

Each card has a × to dismiss it. **Card settings** turns each kind on or off. After a third dismissal of one kind within 30 days, a line says that kind is off, with **Turn back on**. The rules are [D-103](decisions.md#d-103--anticipation-cards-only-in-the-opened-panel-three-a-view-three-days-a-key-three-dismissals-turn-a-kind-off-2026-10-20). The shares inbox page tells the server when it opens.

The conversation lasts for the session: each answer is already saved where it was asked. **Clear** empties the panel. Pure logic (readiness wording, the gate in words, error wording) lives in `frontend/src/utils/echoPanel.ts`, unit-tested.

### Notification bell (every protected page)
`components/notifications/NotificationBell.tsx` (S-8.3.3), beside **Search…** in the sidebar and before the search icon in the mobile bar. The button names its unread count ("Notifications, 2 unread") and shows it as a badge. It opens a panel (dialog role) with the latest notices, newest first, unread ones tinted: title, body, how long ago. Opening one marks it read and goes to its `href`; **Mark all read** clears the count; Escape or a click outside closes it and focus returns to the bell. Empty: "Nothing new. A saved search tells you here when its answer changes." The list polls every minute and on focus; a WebSocket channel for it is a follow-up.

### Layout (`AppLayout`)
- Today: top horizontal tab bar with the protected pages.
- Post-redesign (per [branding.md](branding.md) §sidebar-mockup): slim left sidebar grouped by purpose (Library / Research / Knowledge / Author/future / Settings).
- Persistent global elements: top-right user avatar + sign-out, top-right LLM-status dot (green/yellow/red), `ToastContainer`.
- **Add to Echo** (S-3.7.1, tiers with `echo_personal_brain` only): a dashed button above the user chrome in the sidebar and the mobile drawer. It opens `QuickShare`'s dialog: one box (a single http(s) link becomes a link share; anything else is text), **Attach a file instead** (up to 25 MB), an optional "why", and **These are my own words** (off by default; the hint explains context-only). Shares go straight into the inbox.

While the wizard is unfinished and not skipped, a **Start here** group at the top of the sidebar holds **Getting started** (`/welcome`); it disappears on finish or skip (the palette action remains).

The **Library** group holds All sources, Ask the library and **Library map** (`/library/graph`, S-8.9.2; it navigates by path). The sidebar's **Shelves** group (after Library) lists the reader's shelves with a colour dot, the first eight then "Show all N", plus **Manage shelves** (or **Start a shelf** when there are none); it is hidden for a reader who has no shelves and no `shelves` capability. Shelf entries navigate by path because the `AppTab` union is fixed.

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

The S-8.10.2 audit (2026-10-19, NN/g and Atlassian empty-state guidance, plan [m10-onboarding](plans/m10-onboarding.md)) holds every list to four distinct states: **loading** (skeletons shaped like the content, never "nothing here" while loading), **error** (says the fetch failed and offers **Retry**), **zero data** (what the space is for and the one action that fills it), and **nothing matches** (a filter is set; offers **Clear filters**). Audited: runs, library sources and channels, library Q&A, Q&A history, exports; the author, Echo, Echo inbox, shelves, shelf, notes and templates pages already met it. There is no saved-searches page to audit. `pages/__tests__/emptyStates.test.tsx` pins the jobs page's three states, the checklist and the library Q&A empty state, and fails if a page uses generic copy ("No data", "No results", "Empty list", "Nothing here").

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
| `/brain/context` / `/brain/activity` / `/brain/voice` | L3; context and voice signals (S-3.3.1) live on `/echo` today, activity awaits E-3.2 | [personal-brain.md](personal-brain.md) |
| `/settings` | M (foundational) | [ui-design.md](ui-design.md) |
| `/billing` | L5 (SaaS) | [saas-roadmap.md](saas-roadmap.md) |

---

## Cross-references

- Visual system, components, design tokens — [ui-design.md](ui-design.md)
- Brand voice, color palette, typography — [branding.md](branding.md)
- Endpoints these pages call — [api-reference.md](api-reference.md)
- Architecture (WS, auth, lifecycle) — [architecture.md](architecture.md)
- Roadmap — [feature-roadmap.md](feature-roadmap.md)
