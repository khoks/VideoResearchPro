# Pratidhvani — Initiatives, Epics, Stories & Tasks

**Status:** living doc (last refreshed 2026-04-25). Owner: [`/work-tracker`](../.claude/skills/work-tracker/SKILL.md) skill.

This file is the project's **work-state board**. Every piece of work — shipped, in-progress, accepted, proposed, deferred, blocked — lives here. The hierarchy mirrors a Jira-style Initiative → Epic → Story → Task tree. The high-level *why* of each Initiative is in [`feature-roadmap.md`](feature-roadmap.md) / [`vision.md`](vision.md); this file is the *what / where it is right now*.

## Status legend

| Marker | Status | Meaning |
|---|---|---|
| 🟢 | shipped | merged to master, live |
| 🟡 | in-progress | branch / PR open, or actively coded |
| 🔵 | accepted | scoped + agreed, not yet started |
| ⚪ | proposed | idea filed; awaiting approval |
| 🔴 | deferred | approved earlier, deprioritized |
| ⚫ | blocked | waiting on external dependency or decision |
| ✖ | cancelled | abandoned (kept for history) |

## ID format

`I-N` (initiative) → `E-N.M` (epic) → `S-N.M.K` (story) → `T-N.M.K.J` (task). IDs are **monotonic and never renumbered** — closed items keep their ID forever.

---

## I-1 🟡 Multi-source ingest

**Why it exists.** Generalize the data model from YouTube-only to all source types — podcasts, articles, threads, books, forum posts, social-media posts. Same search → approval → ingest → embed → query pipeline for every type.
**North-star doc:** [feature-roadmap.md L1](feature-roadmap.md#l1--multi-source-ingest) · [source-types.md](source-types.md)
**Decision links:** [D-004](decisions.md#d-004--l1-multi-source-ingest-as-the-next-large-initiative-2026-04-24), [D-005](decisions.md#d-005--social-media-ingest-before-article-ingest-2026-04-25), [D-006](decisions.md#d-006--one-document-row-per-social-post-thread-not-per-comment-2026-04-25), [D-007](decisions.md#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25), [D-008](decisions.md#d-008--no-scraping-of-search-result-pages-on-fb--ig--linkedin-2026-04-25), [D-009](decisions.md#d-009--twitter--x-is-byok--opt-in-2026-04-25), [D-010](decisions.md#d-010--defer-tiktok-and-per-server-discord-bot-indefinitely-2026-04-25)

### E-1.1 🟢 Schema additive

**Scope.** Add `source_type`, `source_url`, `source_metadata` columns alongside existing `videos` shape. No call-site changes. Pure additive migration so the rest of the L1 series can land safely.
**Shipped:** 2026-04-22 — PR [#63](https://github.com/khoks/VideoResearchPro/pull/63)

### E-1.2 🟢 Connector abstraction

**Scope.** Introduce `BaseConnector` interface (`search()`, `list_creator_items()`, `fetch_text()`, `fetch_metadata()`, `fetch_creator()`, `resolve_creator_id()`). Wire `YouTubeConnector` as the first concrete implementation.
**Shipped:** 2026-04-23 — PR [#65](https://github.com/khoks/VideoResearchPro/pull/65)

### E-1.3 🟢 Route remaining call sites

**Scope.** Replace direct YouTube service calls in agents / job tasks / services with `BaseConnector` calls so the system is connector-agnostic at the boundary.
**Shipped:** 2026-04-24 — PR [#66](https://github.com/khoks/VideoResearchPro/pull/66)

### E-1.4 🟢 Rename `videos` → `documents` (table + ORM)

**Scope.** SQLite table rename, ORM class `Video` → `Document`, model file move (`video.py` → `document.py`), 14 importers propagated, no behavioral change. PK column intentionally still `video_id` until UUID promotion (E-1.10).
**Shipped:** 2026-04-25 — PR [#67](https://github.com/khoks/VideoResearchPro/pull/67) (squash-merged as `cfa0406`)

### E-1.5 🟡 Social-media connectors

**Scope.** Add Reddit + HN search connectors first; Mastodon + Bluesky next; manual-paste mode for FB/IG/LI/X-without-paid-API; paid Twitter as a BYOK opt-in; defer Discord and TikTok (D-010). One `Document` per thread (D-006); fetch-time stance/sentiment classification (D-007); no search-page scraping (D-008).
**Linked decisions.** [D-005](decisions.md#d-005--social-media-ingest-before-article-ingest-2026-04-25), [D-006](decisions.md#d-006--one-document-row-per-social-post-thread-not-per-comment-2026-04-25), [D-007](decisions.md#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25), [D-008](decisions.md#d-008--no-scraping-of-search-result-pages-on-fb--ig--linkedin-2026-04-25), [D-009](decisions.md#d-009--twitter--x-is-byok--opt-in-2026-04-25), [D-010](decisions.md#d-010--defer-tiktok-and-per-server-discord-bot-indefinitely-2026-04-25)

#### S-1.5.1 🟢 Reddit search connector

**Shipped:** 2026-04-26 — PR [#70](https://github.com/khoks/VideoResearchPro/pull/70) (squash-merged as `faaed18`)
**Acceptance.** A topic job with `source_types=["reddit_post"]` searches Reddit (`/search.json` + per-sub fallback), presents threads at approval, ingests into the global library. Q&A returns Reddit citations with permalink + `#comment-<id>` deep-links.
**Scope-changed 2026-04-25:** Connector module (search / list / fetch_metadata / fetch_text) + OAuth client with rate limit + comment-tree flatten + 29 unit tests landed in PR #70. Storage-layer wiring (T-1.5.1.4 row insertion), end-to-end pipeline test (second half of T-1.5.1.6), Reddit approval-UI card (T-1.5.1.7), and citation rendering (S-1.5.5) are deferred to follow-up stories that wire Reddit through the job orchestrator. The `f"reddit:{post_id}"` namespace convention is enforced at the connector layer (`Candidate.source_id`); persistence into the `documents.video_id` PK column lands when the orchestrator dispatches Reddit jobs.
**Tasks**
- [x] T-1.5.1.1 Implement `RedditConnector(BaseConnector)` against `/search.json` + per-sub `/r/<sub>/search.json`
- [x] T-1.5.1.2 OAuth app registration + token refresh; respect 100 req/min rate limit
- [x] T-1.5.1.3 Flatten OP + top-50 comments (sorted by score) into single text body with reply markers
- [ ] T-1.5.1.4 Store new `source_type='reddit_post'` rows; PK column = `f"reddit:{post_id}"`
- [x] T-1.5.1.5 Comment-tree depth configurable (default top 50 by score)
- [ ] T-1.5.1.6 Connector unit tests + end-to-end pipeline test *(unit tests landed in PR #70; e2e test pending orchestrator wiring)*
- [ ] T-1.5.1.7 Approval-UI card variant for Reddit (handle, score, comment count, snippet, sentiment hint)

#### S-1.5.2 🟡 Hacker News search connector

**PR:** [#73](https://github.com/khoks/VideoResearchPro/pull/73) (open as of 2026-04-26)
**Acceptance.** Topic job with `source_types=["hn_story"]` returns HN stories with comment trees; uses Algolia HN search API (free, no auth).
**In-progress 2026-04-26:** Connector module (search via `/search?tags=story`, `list_creator_items` via `/search_by_date`, `fetch_metadata` + `fetch_text` via `/items/<id>`), HTML-scrub flatten with `↳` depth markers mirroring Reddit's segment shape, 31 unit tests, and a small refactor extracting `_WORDS_PER_SECOND` + `_segment_for_text` into `app/sources/_text_utils.py` so both text-based connectors share the D-013 constant. Date-range filtering (T-1.5.2.2) is deferred — Algolia exposes it via `numericFilters=created_at_i>...,<...`, but the in-scope acceptance is plain topic search; date scoping waits until the topic-job UI has a date-range field.
**Tasks**
- [x] T-1.5.2.1 Implement `HNConnector(BaseConnector)` against `https://hn.algolia.com/api/v1/search`
- [ ] T-1.5.2.2 Date-range filter via `numericFilters=created_at_i>...,<...` *(deferred — see In-progress note)*
- [x] T-1.5.2.3 Comment tree fetch via item endpoint, flatten same as Reddit
- [x] T-1.5.2.4 Tests

#### S-1.5.3 🔵 `social_classify_stance` LLM use case

**PR:** TBD
**Acceptance.** New named entry in `app/services/llm_routing.py::USE_CASE_REGISTRY` with default `provider=openai, model=gpt-4.1-mini, reasoning=off`. Returns structured `{stance, sentiment, topic_relevance}` for a candidate document. Same use case classifies each comment.
**Tasks**
- [ ] T-1.5.3.1 Define schema (Pydantic)
- [ ] T-1.5.3.2 Add to registry with token-budget recommendation
- [ ] T-1.5.3.3 Wire into the social-connector ingest path so each candidate is classified at fetch time
- [ ] T-1.5.3.4 Persist results into `Document.source_metadata` and `source_metadata.comments[]`
- [ ] T-1.5.3.5 Tests with golden short-text examples (sarcasm, sincere praise, in-favor, against)

#### S-1.5.4 🔵 Approval-UI variant for social posts

**PR:** TBD
**Acceptance.** Approval list rendered for social-post candidates shows: author handle, follower/karma proxy, post date, platform icon, first ~200 chars, comment count, score/likes/RTs, stance + sentiment badges, "View on platform" link. Same checkboxes + Approve flow as YouTube.
**Tasks**
- [ ] T-1.5.4.1 Frontend card component (variant of existing video card)
- [ ] T-1.5.4.2 Sentiment / stance badge sub-component
- [ ] T-1.5.4.3 Filter chips ("show only against", "show only positive") that filter the in-memory candidate list (do not re-fetch / re-classify)

#### S-1.5.5 🔵 Citation rendering for social posts

**PR:** TBD
**Acceptance.** Q&A answer citations rendering for social `source_type` values shows author handle + post date + platform; clicks open the permalink with `#comment-<id>` anchor when the cite is from a reply.
**Tasks**
- [ ] T-1.5.5.1 Citation renderer dispatch by `source_type`
- [ ] T-1.5.5.2 Permalink + comment-anchor URL builder per platform

#### S-1.5.6 ⚪ Mastodon connector

**PR:** TBD
**Acceptance.** Same shape as Reddit/HN. ActivityPub search + thread fetch. No paid tier needed.
**Tasks** (initial)
- [ ] T-1.5.6.1 Mastodon instance discovery (user provides home instance URL or default to `mastodon.social`)
- [ ] T-1.5.6.2 Search + thread fetch implementation
- [ ] T-1.5.6.3 Tests

#### S-1.5.7 ⚪ Bluesky connector

**PR:** TBD
**Acceptance.** AT-Protocol search + thread fetch. App password auth.
**Tasks** (initial)
- [ ] T-1.5.7.1 AT-Proto API client integration
- [ ] T-1.5.7.2 Tests

#### S-1.5.8 🔵 Manual-paste mode (Mode B for FB/IG/LI/X-without-paid)

**PR:** TBD
**Acceptance.** User pastes 1–N post URLs from any supported platform; system fetches each via the article-connector machinery (trafilatura → Playwright fallback) and ingests as the right `source_type`. Honest UI: search disabled for these platforms, paste-only.
**Tasks**
- [ ] T-1.5.8.1 URL → `source_type` resolver (FB / IG / LI / X / generic)
- [ ] T-1.5.8.2 Reuse trafilatura + Playwright pipeline (article-connector primitives) — see also E-1.6
- [ ] T-1.5.8.3 Frontend "Paste URLs" surface in job submission
- [ ] T-1.5.8.4 Per-platform `source_metadata` extraction (author handle, date) where the page exposes it

#### S-1.5.9 ⚪ Pluggable Twitter Bearer token (BYOK)

**PR:** TBD
**Acceptance.** `TWITTER_BEARER_TOKEN` env var, when present, enables the Twitter Mode A (search) connector. Absent → Mode B (paste-only) is the only Twitter ingest available. Health check surfaces presence/validity in `/api/v1/health`.
**Tasks**
- [ ] T-1.5.9.1 Env-var detection in startup smoke check
- [ ] T-1.5.9.2 Capability flag `twitter_search_enabled` on `/api/v1/health`
- [ ] T-1.5.9.3 Frontend hides Mode-A Twitter UI when capability is false

#### S-1.5.10 ⚪ Twitter connector (paid API)

**PR:** TBD
**Acceptance.** With BYOK token (S-1.5.9), Mode A Twitter search lands tweets + self-thread + top-K replies; rate-limit aware.
**Tasks** (initial)
- [ ] T-1.5.10.1 v2 Recent Search endpoint integration
- [ ] T-1.5.10.2 Self-thread unrolling (author replies to own tweets)
- [ ] T-1.5.10.3 Reply fetch (top 50)
- [ ] T-1.5.10.4 Quota exhaustion fallback to Mode B

### E-1.6 🔴 Article connector

**Scope.** Generic article ingestion: trafilatura primary, Playwright fallback for SPAs, hybrid (try trafilatura → fall back if word_count<200). Two modes (Discovery via search-engine API or RSS, Direct via URL list / file upload). Deferred per [D-005](decisions.md#d-005--social-media-ingest-before-article-ingest-2026-04-25) until E-1.5 (social media) ships.
**Note.** Pipeline primitives built here are reused by S-1.5.8 (manual-paste mode), so even though the *connector* is deferred, the *fetch primitives* may land earlier as part of E-1.5.

### E-1.7 ⚪ Podcast connector

**Scope.** Spotify/Apple show URL or RSS feed → episode list → text from existing transcript or Whisper transcription. Each episode = one `Document` with `source_type='podcast'`.

### E-1.8 ⚪ PDF / e-book connector

**Scope.** File upload (multipart). PyMuPDF text extraction; per-page boundaries preserved as segment metadata.

### E-1.9 ⚪ Rename `channels` → `creators` (DB + ORM)

**Scope.** Generalizes the YouTube-channel concept to any creator (podcast host, blog author, Twitter handle). Pure rename PR; no behavioral change.
**Note.** Plays the same role for creators as E-1.4 played for documents.

### E-1.10 ⚪ Promote `video_id` PK to UUID `document_id`

**Scope.** Final L1 schema cleanup. Migrate the `videos.video_id` PK column to a `document_id` UUID; namespaced platform IDs (e.g. `reddit:abc123`) move to a `source_id` column; `job_videos` join table renamed to `job_documents`.
**Blocker.** Wait until at least 2-3 non-video source types are in the codebase so we have evidence the namespaced-string approach really is friction (not premature).

---

## I-2 🔵 Brand & visual identity rollout

**Why it exists.** Switch the running app from generic-AI-SaaS aesthetics (purple-blue gradient, default sans) to warm-editorial Pratidhvani identity (paper background, oxblood / forest-teal / vintage gold, Fraunces / Source Serif). Visual identity should match the personal-library / research-journal vision.
**North-star doc:** [branding.md](branding.md) · [ui-design.md](ui-design.md)
**Decision links:** [D-001](decisions.md#d-001--rebrand-to-pratidhvani-प्रतिध्वनि-2026-04-24), [D-002](decisions.md#d-002--warm-editorial-visual-identity-2026-04-24)

### E-2.1 ⚪ Tokens layer (`frontend/src/theme.ts`)

**Scope.** Single tokens file exporting `colors`, `space`, `radius`, `shadow`, `type`, `motion` for both light and dark modes. Mirrors `branding.md` palette.

### E-2.2 ⚪ Primitives library

**Scope.** `frontend/src/components/primitives/` — Button, Card, Input, Textarea, Select, Badge, Modal, Tooltip, Tabs, Spinner, Skeleton, EmptyState, Toast, IconButton. All read from `theme.ts`. No CSS framework; inline styles per project convention.

### E-2.3 ⚪ Page-by-page migration

**Scope.** Migrate the 10 existing pages off ad-hoc inline styles onto tokens + primitives. Order: Login → AppLayout → JobsList → JobDetail → Library → LibraryQA → SubmitJob → Exports → QAHistoryChat → VideoKnowledge.

### E-2.4 ⚪ Sidebar nav (replace top tabs)

**Scope.** Top-tab nav → slim left sidebar grouped by purpose (Library / Research / Knowledge / Author future).

### E-2.5 ⚪ Marketing landing page (warm-editorial)

**Scope.** Static landing page under `marketing/` describing the curated-personal-wiki pitch, screenshots, install instructions, SaaS waitlist.

### E-2.6 ⚪ Code identifier rename pass

**Scope.** Once visual rollout settles: `videoresearchpro_global` → `pratidhvani_global` Chroma collection (with migration), package paths, env-var aliases. Decoupled from D-001 because identifier renames need a deliberate migration; brand copy moved immediately.

---

## I-3 ⚪ Echo (personal-brain L3)

**Why it exists.** Long-horizon north star — an app that ingests the user's likes / WhatsApp / Google Keep / quotes / activity / location / interests over time and develops a personality matching them. Eventually capable of "speaking on the user's behalf".
**North-star doc:** [personal-brain.md](personal-brain.md) · [vision.md](vision.md) Ring 3
**Decision links:** [D-003](decisions.md#d-003--echo--personal-brain-as-the-long-horizon-north-star-2026-04-24)
**Status:** ⚪ proposed — schema decisions today must remain forward-compatible; no L3 code lands until L1 is mature.

### E-3.1 ⚪ Personal context store schema

**Scope.** Separate-from-sources table holding location, interests, hobbies, work, talents, skills, personality, life events. Designed for opt-in, scoped, revocable bundles.

### E-3.2 ⚪ Activity-stream connectors

**Scope.** Pluggable opt-in connectors. Recommended order (per [feature-roadmap.md L3](feature-roadmap.md#l3--echo-personal-brain)): YouTube watch history → Spotify history → email (read-only) → calendar → browser history → Apple Health.

### E-3.3 ⚪ Voice & style capture

**Scope.** Store user writing samples, Q&A patterns, opinion threads. Train fine-tune adapters on user-tagged content for persona.

### E-3.4 ⚪ "Speak as me" agent

**Scope.** Given an incoming message, draft a response in the user's voice using their accumulated knowledge + context. Privacy: self-host local; SaaS opt-in encrypted.

### E-3.5 ⚪ Cold-start readiness threshold

**Scope.** Quantify "enough data has been ingested to safely activate Echo features" and gate Ring 3 surface behind this threshold.

---

## I-4 🟡 Self-curating docs & work-state

**Why it exists.** Decisions, vision refinements, and new work items routinely surface in chat conversations and risk being lost in the transcript. Skills + Stop hook persist them automatically into the canonical docs and this initiatives file, so future-Claude (and future-me) can reconstruct project state without trawling chat history.
**Decision links:** [D-011](decisions.md#d-011--two-persistence-skills--auto-stop-hook-for-session-to-docs-flow-2026-04-25)

### E-4.1 🟡 `knowledge-curator` skill

**Scope.** Skill at `.claude/skills/knowledge-curator/SKILL.md` that scans session, routes content into the canonical docs (`feature-roadmap.md`, `architecture.md`, `requirements.md`, `source-types.md`, `branding.md`, `vision.md`, `personal-brain.md`, `saas-roadmap.md`, `decisions.md`), commits on a branch, opens PR.
**PR:** this PR (bootstrap)

### E-4.2 🟡 `work-tracker` skill

**Scope.** Skill at `.claude/skills/work-tracker/SKILL.md` that owns this file (`docs/initiatives.md`). Updates status / scope of existing items; creates new items for newly-discussed work; cross-links to decisions and PRs; commits on a branch, opens PR.
**PR:** this PR (bootstrap)

### E-4.3 🟡 Stop-hook auto-invocation

**Scope.** `.claude/settings.json` Stop hook nudges Claude once per session (via `stop_hook_active` guard) to invoke both skills before ending. Skills are no-op-safe.
**PR:** this PR (bootstrap)

### E-4.4 🟡 Decision log seed

**Scope.** Bootstrap [`decisions.md`](decisions.md) with the eleven decisions captured from project history (D-001 through D-011).
**PR:** this PR (bootstrap)

### E-4.5 🟡 Initiatives seed

**Scope.** Bootstrap this file with all known initiatives + epics + stories at the time of the bootstrap PR.
**PR:** this PR (bootstrap)

### E-4.6 ⚪ Coordinated PR composition (skills share a PR per session)

**Scope.** v2 enhancement: when both `/knowledge-curator` and `/work-tracker` fire on the same session, the second skill checks out the first's branch and adds a commit instead of opening a sibling PR. For now, sibling PRs with `Companion PR: #N` cross-references is the default.

### E-4.7 🟡 Inventions / novel-ideas log

**Scope.** New canonical doc [`inventions.md`](inventions.md) owned by `/knowledge-curator`. Captures novel mechanisms / non-obvious combinations / potentially-patentable concepts surfaced in conversation. Skill detection heuristic biased toward over-capture; verbatim user messages flagged as novel are also saved raw to `docs/notes/<YYYY-MM-DD-novel-<slug>.md`. Skill makes no legal patentability assessment.
**Linked decision:** [D-012](decisions.md#d-012--capture-novel--potentially-patentable-ideas-in-inventionsmd-2026-04-25)
**PR:** [#68](https://github.com/khoks/VideoResearchPro/pull/68) (follow-up commit on the bootstrap branch)

---

## I-5 ⚪ SaaS readiness (long-horizon)

**Why it exists.** Today's PRs must remain forward-compatible with a future public SaaS — multi-tenant, billed, abuse-resistant, hardened auth.
**North-star doc:** [saas-roadmap.md](saas-roadmap.md)

### E-5.1 ⚪ `tenant_id` audit + retrofit

**Scope.** Add `tenant_id` / `workspace_id` columns to every user-scoped table; convert today's implicit JWT scoping to an explicit column for future per-tenant rate limiting + multi-workspace.

### E-5.2 ⚪ Subscription tier gating

**Scope.** Free / Pro / Studio tiers with explicit YouTube quota allocation, LLM token budget, document-count cap, feature gating (Author Studio = Pro+).

### E-5.3 ⚪ Stripe integration

**Scope.** Subscription, metered overage, team billing.

### E-5.4 ⚪ Auth hardening

**Scope.** OAuth (Google / GitHub), MFA, session management, password reset, account lockout, audit log.

### E-5.5 ⚪ Abuse prevention

**Scope.** Rate limits, fraud detection, content policy, takedown process for shared reports.

### E-5.6 ⚪ Background-job isolation

**Scope.** Celery queues per tenant or per tier; per-tenant LLM keys (BYOK pattern, reuse from D-009); per-tenant ChromaDB tenancy.

### E-5.7 ⚪ Data residency

**Scope.** Region-selectable storage (EU / US / etc.).

### E-5.8 ⚪ Hosting / infra

**Scope.** Postgres for SQLite, Redis cluster, ChromaDB managed or pgvector, S3 for reports, CDN for static.

### E-5.9 ⚪ Hosted UX

**Scope.** Landing page, signup, billing portal, support, status page.

---

## I-6 ⚪ Author Studio (output generation L2)

**Why it exists.** The accumulated library is rich enough to produce books, sites, decks, newsletters, reels — not just answers. Closes the loop: ingest → understand → produce.
**North-star doc:** [feature-roadmap.md L2](feature-roadmap.md#l2--author-studio-output-generation-)

### E-6.1 ⚪ Books (long-form Markdown → PDF / EPUB)

### E-6.2 ⚪ Static personal-wiki site (Astro / 11ty under `outputs/sites/`)

### E-6.3 ⚪ Slides (PPTX via `anthropic-skills:pptx`)

### E-6.4 ⚪ Newsletter / digest (recurring scheduled output)

### E-6.5 ⚪ Video / reel (TTS narration + clip-stitched B-roll)

---

## Open questions parking lot

These are real questions raised in conversation that don't yet have a Story home. When one of them is answered the answer becomes a Decision (`D-NNN`) and the question is converted into one or more Stories.

- **OQ-1.** Sentiment classification confidence threshold — at what score do we surface a stance/sentiment badge as a hint vs hide it as too noisy? (Tied to [D-007](decisions.md#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25))
- **OQ-2.** Comment-tree default depth — top 50 by score is the proposed default; configurable per-job? Per-platform? (Tied to S-1.5.1, S-1.5.2)
- **OQ-3.** Sibling-PR coordination — should `/knowledge-curator` and `/work-tracker` share a single PR per session? (Tied to E-4.6)
- **OQ-4.** Whisper for podcast Mode A vs external service (Deepgram / AssemblyAI) for SaaS tier? (Tied to E-1.7)
- **OQ-5.** PDF connector: file upload only, URL only, or both? (Tied to E-1.8)
- **OQ-6.** Echo cold-start readiness threshold — quantitative criteria? (Tied to E-3.5)
