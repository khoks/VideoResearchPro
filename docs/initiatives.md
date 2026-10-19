# Pratidhvani — Initiatives, Epics, Stories & Tasks

**Status:** living doc (last refreshed 2026-10-18). Owner: [`/work-tracker`](../.claude/skills/work-tracker/SKILL.md) skill.

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

## I-1 🟡 Multi-source ingest — original scope closed 2026-05-03; reopened 2026-07-22 for E-1.11 (scale resilience)

**Filing fix 2026-10-18:** E-1.15 to E-1.18 (the R1/R3/R4/R5 epics filed 2026-07-31) had landed under the I-2 heading. They now sit at the end of I-1. IDs unchanged, same as the 2026-07-29 fix for E-1.13.

**Scope-changed 2026-10-19:** the PDF upload and paste-URL surfaces shipped (T-1.5.8.3, E-1.8 follow-up, PR [#224](https://github.com/khoks/VideoResearchPro/pull/224)), and building them exposed that the "12 source types end-to-end" closure below is true of ingest but not of retrieval: since [D-063](decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31) every non-video document is ingested without a visibility grant and is therefore never listed or retrieved. Tracked under E-5.10 as [S-5.10.4](#s-5104--key-document-visibility-on-document_id) ([D-070](decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19)), shipped 2026-10-19 in PR [#241](https://github.com/khoks/VideoResearchPro/pull/241) — which also found that no non-video chunk had ever reached Chroma. I-1 stays 🟡 for the E-1.11 scale track, not for this.

**Scope-changed 2026-10-19 (II):** building job templates (S-8.6.1) found that `JobCreate` has no `source_types` field and nothing writes `jobs.source_types_json`, so every topic run created through the API searches YouTube only; S-1.5.11's worker dispatch is intact but unreachable (its HTTP-level end-to-end test was the one variant never written). Ingest by paste, upload and channel sync is unaffected. Filed as [S-1.5.13](#s-1513--accept-source_types-on-job-creation).

**Scope-changed 2026-07-29 (II):** the reopened scale/quality track now also carries [E-1.13](#e-113-per-user-llm-overrides-cost-calculator) (per-user model overrides + cost calculator, 🟢) and [E-1.14](#e-114-model-tier-quality-evaluation-harness) (model-tier quality evaluation, 🟡). Trajectory of the reopening: E-1.11 made ingest survive scale → E-1.12 made the agents survive scale → E-1.13 made model choice configurable and costed → E-1.14 measures whether the chosen models are good enough. Linked decisions: [D-054](decisions.md#d-054--per-user-llm-overrides--cost-calculator-gpt-56-adaptive-reasoning-findings-2026-07-29), [D-055](decisions.md#d-055--intelligence-delta-evaluation-methodology-production-input-replay--blind-ab-judging-2026-07-29).

**Scope-changed 2026-07-22:** reopened for [E-1.11](#e-111-transcript-pipeline-resilience-at-scale) — the 200-video deep-research test (job `0d4db8c3`, 2026-07-21/22) surfaced transcript-pipeline failures at scale: an IP-block cascade made Whisper the primary path for 80% of videos, and 63/200 videos were lost (25MB Whisper cap + yt-dlp 403s). The original multi-source scope stays closed; E-1.11 is the scale-resilience follow-on. Linked decision: [D-051](decisions.md#d-051--transcript-pipeline-resilience-bundle-circuit-breaker--segmented-whisper--yt-dlp-client-fallback-2026-07-22).

**Closure 2026-05-03 (evening).** I-1 is **fully closed**. The polymorphic plumbing claim is validated **12 times** end-to-end across every dimension of variation:

- **Discovery surfaces**: search APIs (YouTube / Reddit / HN / Bluesky / Brave for articles), RSS feeds (Mastodon hashtag / Podcast iTunes+RSS / Article RSS), paste-only (FB / IG / LI / Tweet), no-discovery (PDF, exercises the `NotImplementedError` dispatcher path).
- **Storage variants**: in-place rows (videos / social posts), file upload (PDF), URL-only (paste-mode 5 source types).
- **Citation variants**: per-reply deep-links (Reddit `#comment-<id>`, HN per-item, Mastodon / Bluesky per-status), per-timestamp (video / podcast `#t=<sec>`), per-page (PDF `#page=<N>`), per-URL (paste).

**Twelve source types in the connector registry**: `video` / `reddit_post` / `hn_story` / `mastodon_post` / `bluesky_post` / `podcast_episode` / `pdf` / `article` / `fb_post` / `ig_post` / `li_post` / `tweet`. Every one slotted into the same `BaseConnector` / polymorphic `<ApprovalCard>` / `_chunk_to_reference` / `<CitationLink>` plumbing without changes to the core contracts.

**Closing PRs (chronological):**

| Phase | PRs |
|-------|-----|
| Foundation (E-1.1–E-1.4, E-1.10) | [#63](https://github.com/khoks/VideoResearchPro/pull/63) – [#67](https://github.com/khoks/VideoResearchPro/pull/67), [#112](https://github.com/khoks/VideoResearchPro/pull/112) |
| Reddit + HN end-to-end (M-1.5) | through [#123](https://github.com/khoks/VideoResearchPro/pull/123) |
| Mastodon + Bluesky (M-1.6) | [#128](https://github.com/khoks/VideoResearchPro/pull/128), [#129](https://github.com/khoks/VideoResearchPro/pull/129) |
| Backend reference enrichment (S-1.5.12) | [#131](https://github.com/khoks/VideoResearchPro/pull/131), [#134](https://github.com/khoks/VideoResearchPro/pull/134) |
| Podcast (M-1.7) | [#140](https://github.com/khoks/VideoResearchPro/pull/140) |
| Playwright fallback (T-1.6.6) | [#141](https://github.com/khoks/VideoResearchPro/pull/141) |
| PDF (M-1.8) | [#142](https://github.com/khoks/VideoResearchPro/pull/142) |
| Mode B paste (S-1.5.8) | [#144](https://github.com/khoks/VideoResearchPro/pull/144) |
| Article full UX (E-1.6 close: T-1.6.2 / .3 / .5) | [#145](https://github.com/khoks/VideoResearchPro/pull/145) |
| Channels → creators (E-1.9 close) | [#146](https://github.com/khoks/VideoResearchPro/pull/146) |

**What's still operator-side (not codebase work):**

- **E-1.9 SQL-level rename** — Phase 2 awaits operators running the runbook in `docs/migration-channels-to-creators.md`. The Python-level rename (Creator alias) shipped in PR #146 per the same D-032 pattern E-2.6 established for brand identifier renames.
- **E-2.6 SQL-level rename** — same status. The Python-level rename shipped earlier; the SQL rename of `videoresearchpro_global` → `pratidhvani_global` etc. waits for operator opt-in via `docs/migration-code-identifiers.md`.

**Backend tests at I-1 closure:** 745 (was 503 at the start of the multi-session push; net +242 over the trajectory).

**What's next** (post-I-1):

- **S-1.5.9 / S-1.5.10** (BYOK Twitter env detection + paid Twitter connector) — explicitly opt-in per [D-009](decisions.md#d-009--twitter--x-is-byok--opt-in-2026-04-25); not on the critical path for I-1 closure but the natural follow-up if a user supplies a token.
- **L2 Author Studio** ([I-6](initiatives.md#i-6--author-studio-output-generation-l2)) — output generation for the accumulated library: books, sites, decks, newsletters, reels.
- **L3 Echo / personal brain** ([I-3](initiatives.md#i-3--echo-personal-brain-l3)) — the long-horizon north star.
- **L5 SaaS readiness** ([I-5](initiatives.md#i-5--saas-readiness-long-horizon--code-shippable-work-fully-closed-2026-05-05)) — multi-tenancy + billing + abuse prevention + auth hardening + hosting.

**Companion initiative I-2 closed 2026-05-03 morning** alongside the E-2.5 + E-2.6 work. With I-1 closing this evening, **two of six top-level initiatives are now fully shipped**.

**Why it exists.** Generalize the data model from YouTube-only to all source types — podcasts, articles, threads, books, forum posts, social-media posts. Same search → approval → ingest → embed → query pipeline for every type.
**North-star doc:** [feature-roadmap.md L1](feature-roadmap.md#l1--multi-source-ingest-) · [source-types.md](source-types.md)
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

### E-1.5 🟢 Social-media connectors

**Scope.** Add Reddit + HN search connectors first; Mastodon + Bluesky next; manual-paste mode for FB/IG/LI/X-without-paid-API; paid Twitter as a BYOK opt-in; defer Discord and TikTok (D-010). One `Document` per thread (D-006); fetch-time stance/sentiment classification (D-007) inline per connector (D-023); no search-page scraping (D-008).
**Linked decisions.** [D-005](decisions.md#d-005--social-media-ingest-before-article-ingest-2026-04-25), [D-006](decisions.md#d-006--one-document-row-per-social-post-thread-not-per-comment-2026-04-25), [D-007](decisions.md#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25), [D-008](decisions.md#d-008--no-scraping-of-search-result-pages-on-fb--ig--linkedin-2026-04-25), [D-009](decisions.md#d-009--twitter--x-is-byok--opt-in-2026-04-25), [D-010](decisions.md#d-010--defer-tiktok-and-per-server-discord-bot-indefinitely-2026-04-25), [D-023](decisions.md#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28), [D-025](decisions.md#d-025--file-mvp-definition-of-done-as-milestone-m-15-2026-04-28)

#### M-1.5 🟢 Milestone — Reddit + HN end-to-end ingest **CLOSED 2026-05-03**

**Filed 2026-04-28** per [D-025](decisions.md#d-025--file-mvp-definition-of-done-as-milestone-m-15-2026-04-28). The convergence target for E-1.5 work — six in-flight stories close into a single user-visible experience.

**Definition of done.** A user submits a topic job with `source_types=['reddit_post','hn_story']`, sees a curated approval list with **stance / sentiment / framing badges + filter chips** (including the `topic_relevance >= 0.50` default per [D-021](decisions.md#d-021--topic-relevance-threshold--050-2026-04-26) and the "Show low-relevance candidates" toggle), approves a subset, and asks Q&A across the approved threads receiving **comment-anchored citations** (per the `permalink#comment-<id>` format defined in [D-006](decisions.md#d-006--one-document-row-per-social-post-thread-not-per-comment-2026-04-25)).

**Component checks** (7 total — flip to ✅ as each closes; "🟡 partial" marks substantive progress short of full closure):
- [x] **C1. ✅** E-1.10 cutover landed (UUID `document_id` PK + `source_id text` columns) — *T-1.10.1 ✅ (PR [#96](https://github.com/khoks/VideoResearchPro/pull/96)) + T-1.10.2-.8 cutover ✅ shipped 2026-05-02 PR [#112](https://github.com/khoks/VideoResearchPro/pull/112). Documents PK swapped, job_videos→job_documents, transcript_cache PK retargeted, ORM + 14-importer audit clean, 415/415 tests green*
- [x] **C2. ✅** S-1.5.11 dispatcher routes topic-job source-type lists through the connector registry — *T-1.5.11.1 ✅ ([#109](https://github.com/khoks/VideoResearchPro/pull/109)) + orchestrator wiring + T-1.5.11.4 progress-reporting parity ✅ shipped 2026-05-02 PR [#116](https://github.com/khoks/VideoResearchPro/pull/116). `Job.source_types_json` column added; `execute_topic_job` reads it and branches on video (LangGraph search agent) vs non-video (`dispatch_search` → `connector.fetch_text` → `_upsert_candidate_and_link`). 11 new tests covering helper logic + Reddit-only integration. T-1.5.11.2 (per-source rate-limit/retry config) + T-1.5.11.3 (fan-out semantics — sequential is the v1 answer) deferred as polish; e2e tests are C7's scope*
- [x] **C3. ✅** T-1.5.1.4 + T-1.5.2.5 storage tasks land Reddit / HN Candidates as `documents` rows — *Shipped 2026-05-02 PR [#113](https://github.com/khoks/VideoResearchPro/pull/113). `_upsert_candidate_and_link()` generalizes the YouTube path to handle any source_type via canonical (source_type, source_id) lookup; 9 new tests cover Reddit + HN happy paths, idempotent dedup, cross-job sharing, classification persistence, ExtractedText state recording.*
- [x] **C4. ✅** S-1.5.3 inline classifier (per [D-023](decisions.md#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28)) populates stance / sentiment / framing / topic_relevance — *T-1.5.3.1/.2/.3 ✅ (PRs [#94](https://github.com/khoks/VideoResearchPro/pull/94), [#107](https://github.com/khoks/VideoResearchPro/pull/107)) + T-1.5.3.4 ✅ shipped 2026-05-02 PR [#113](https://github.com/khoks/VideoResearchPro/pull/113). Classifier dict round-trips into `source_metadata_json["classification"]` via `_upsert_candidate_and_link(..., classification=...)`. T-1.5.3.5 (golden tests with sarcasm / sincere / for / against examples) + T-1.5.3.6 (framing exemplars embedded in the prompt — already locked in source-types.md, just needs the prompt-level baking) remain as polish*
- [x] **C5. ✅** S-1.5.4 polymorphic `<ApprovalCard>` renders Reddit + HN config entries with badges + filter chips — *Fully closed 2026-05-03 PR [#122](https://github.com/khoks/VideoResearchPro/pull/122). All four sub-tasks done across PRs #99 (TS shape), #108 (badge row), #118 (polymorphic primitive + Reddit/HN configs), #122 (page migration + filter rail). T-1.5.4.4 swaps JobDetailPage's inline approval markup for `<ApprovalCard config={SOURCE_CONFIGS[source_type]}>`; T-1.5.4.3 ships the "Show low-relevance candidates" toggle per D-021. Backend `job_videos_response` extended with source_type/source_metadata/classification; approve_job accepts both video_id + document_id keys.*
- [x] **C6. ✅** S-1.5.5 citation rendering produces Reddit / HN deep-links — *Shipped 2026-05-02 PR [#117](https://github.com/khoks/VideoResearchPro/pull/117). Polymorphic `<CitationLink>` dispatches by `Reference.source_type`; per-source URL + label format for video / reddit_post / hn_story; back-compat fallback to YouTube for legacy rows lacking source_type. JobDetailPage + LibraryQAPage migrated. Backend QA agent `extract_references` → emit source_type/permalink fields is a follow-up but the rendering contract is established*
- [x] **C7. ✅** End-to-end pipeline test passes for `["reddit_post"]`, `["hn_story"]`, and mixed `["video","reddit_post","hn_story"]` — *Closed 2026-05-03 PR [#121](https://github.com/khoks/VideoResearchPro/pull/121). Reddit-only test prior (#116). PR #121 added HN-only, mixed-three-source-types, and partial-failure-isolation tests. All four orchestrator-integration tests pass; total backend suite at 438/438*

**Final progress 2026-05-03 — M-1.5 ✅ FULLY CLOSED.** All 7 component checks closed across 11 days of focused work (D-024 filed 2026-04-26 → DoD met 2026-05-03). End-to-end Reddit + HN ingest now functional: a topic job with `source_types=["reddit_post","hn_story"]` searches via the dispatcher, classifies each candidate inline at fetch time, persists with `source_metadata.classification`, surfaces in the polymorphic ` <ApprovalCard>` approval list with stance / sentiment / framing badges + low-relevance filter, and produces source-aware citations in Q&A answers.

**Polish items deferred to follow-up (not blocking M-1.5 acceptance):**

1. **T-1.5.3.5 classifier golden tests** — sarcasm / sincere praise / in-favor / against fixtures with golden classifications. Improves classifier confidence in production.
2. **T-1.5.3.6 framing exemplars baked into the LLM prompt** — exemplars locked in source-types.md; the actual prompt body needs to embed them literally rather than via the current stub.
3. **Backend reference enrichment** — teach the `extract_references` LLM use case to emit `source_type` + `permalink` + `author` per source so Reddit / HN citations render with proper labels in production. Frontend rendering contract is in place (PR #117); the backend producer is the missing half.
4. **HTTP-level integration tests** — current e2e tests drive `execute_topic_job.run()` directly. A future `test_e2e_topic_job_via_api.py` would POST to `/api/v1/jobs` and walk the approve flow through HTTP. Higher-fidelity but slower.

**Next milestones (post-M-1.5):**

- **M-1.6** 🟢 (Mastodon + Bluesky end-to-end) — **shipped 2026-05-03**. S-1.5.6 (Mastodon) + S-1.5.7 (Bluesky) both closed. Two new connectors slotted into the M-1.5 BaseConnector / polymorphic ApprovalCard / classifier / citation plumbing without changes — that's the structural validation we wanted from this milestone. The pattern is now battle-tested across four social-media surfaces (Reddit / HN / Mastodon / Bluesky).
- **M-1.7** (podcast end-to-end) — E-1.7 connector + Whisper-as-service decision (OQ-4).
- **M-2.5** (marketing landing page deployed) — E-2.5 + a hosting decision.

#### S-1.5.1 🟢 Reddit search connector

**Shipped:** 2026-04-26 — PR [#70](https://github.com/khoks/VideoResearchPro/pull/70) (squash-merged as `faaed18`)
**Acceptance.** A topic job with `source_types=["reddit_post"]` searches Reddit (`/search.json` + per-sub fallback), presents threads at approval, ingests into the global library. Q&A returns Reddit citations with permalink + `#comment-<id>` deep-links.
**Scope-changed 2026-04-25:** Connector module (search / list / fetch_metadata / fetch_text) + OAuth client with rate limit + comment-tree flatten + 29 unit tests landed in PR #70. Storage-layer wiring (T-1.5.1.4 row insertion), end-to-end pipeline test (second half of T-1.5.1.6), Reddit approval-UI card (T-1.5.1.7), and citation rendering (S-1.5.5) are deferred to follow-up stories that wire Reddit through the job orchestrator. The `f"reddit:{post_id}"` namespace convention is enforced at the connector layer (`Candidate.source_id`); persistence into the `documents.video_id` PK column lands when the orchestrator dispatches Reddit jobs.
**Tasks**
- [x] T-1.5.1.1 Implement `RedditConnector(BaseConnector)` against `/search.json` + per-sub `/r/<sub>/search.json`
- [x] T-1.5.1.2 OAuth app registration + token refresh; respect 100 req/min rate limit
- [x] T-1.5.1.3 Flatten OP + top-50 comments (sorted by score) into single text body with reply markers
- [x] T-1.5.1.4 Store new `source_type='reddit_post'` rows — *shipped 2026-05-02 PR [#113](https://github.com/khoks/VideoResearchPro/pull/113). `_upsert_candidate_and_link(db, job_id, candidate, classification=..., extracted_text=...)` resolves existing rows by canonical `(source_type, source_id)`, mirrors `source_id` into `video_id` only for video rows (NULL otherwise), creates JobVideo (job_documents) link with UUID document_id. 9 dedicated unit tests including cross-job sharing.*
- [x] T-1.5.1.5 Comment-tree depth configurable (default top 50 by score)
- [x] T-1.5.1.6 Connector unit tests + end-to-end pipeline test *(unit tests landed in PR #70; Reddit-only e2e shipped in PR [#116](https://github.com/khoks/VideoResearchPro/pull/116), see T-1.5.11.5. Checkbox reconciled 2026-10-18)*
- [x] T-1.5.1.7 Approval-UI card variant for Reddit (handle, score, comment count, snippet, sentiment hint) *(shipped as the `SOURCE_CONFIGS['reddit_post']` entry of the polymorphic `<ApprovalCard>` in PRs [#118](https://github.com/khoks/VideoResearchPro/pull/118) / [#122](https://github.com/khoks/VideoResearchPro/pull/122). Checkbox reconciled 2026-10-18)*

#### S-1.5.2 🟢 Hacker News search connector

**Shipped:** 2026-04-26 — PR [#73](https://github.com/khoks/VideoResearchPro/pull/73) (squash-merged as `3615d81`)
**Acceptance.** Topic job with `source_types=["hn_story"]` returns HN stories with comment trees; uses Algolia HN search API (free, no auth).
**Shipped scope 2026-04-26:** Connector module (search via `/search?tags=story`, `list_creator_items` via `/search_by_date`, `fetch_metadata` + `fetch_text` via `/items/<id>`), HTML-scrub flatten with `↳` depth markers mirroring Reddit's segment shape, 31 unit tests, and a small refactor extracting `_WORDS_PER_SECOND` + `_segment_for_text` into `app/sources/_text_utils.py` so both text-based connectors share the D-013 constant. Date-range filtering (T-1.5.2.2) is deferred — Algolia exposes it via `numericFilters=created_at_i>...,<...`, but the in-scope acceptance is plain topic search; date scoping waits until the topic-job UI has a date-range field. Storage-layer wiring into `documents` (T-1.5.2.5 candidate, not yet filed) is the same blocker as the Reddit connector — both wait on the orchestrator dispatch path.
**Tasks**
- [x] T-1.5.2.1 Implement `HNConnector(BaseConnector)` against `https://hn.algolia.com/api/v1/search`
- [ ] T-1.5.2.2 Date-range filter via `numericFilters=created_at_i>...,<...` *(deferred — see Shipped scope note)*
- [x] T-1.5.2.3 Comment tree fetch via item endpoint, flatten same as Reddit
- [x] T-1.5.2.4 Tests
- [x] T-1.5.2.5 Store new `source_type='hn_story'` rows — *shipped 2026-05-02 PR [#113](https://github.com/khoks/VideoResearchPro/pull/113). Same `_upsert_candidate_and_link()` path as Reddit; HN candidates flow through identically since the function is source-type-agnostic.*

#### S-1.5.3 🟢 `social_classify_stance` LLM use case

**PR:** TBD
**Acceptance.** New named entry in `app/services/llm_routing.py::USE_CASE_REGISTRY` with default `provider=openai, model=gpt-4.1-mini, reasoning=off`. Returns structured `{stance, sentiment, framing, topic_relevance}` for a candidate document — schema extended with the `framing` axis per [D-014](decisions.md#d-014--add-framing-axis-to-social_classify_stance-schema-2026-04-26). Same use case classifies each comment. Module exports `TOPIC_RELEVANCE_THRESHOLD = 0.50` per [D-021](decisions.md#d-021--topic-relevance-threshold--050-2026-04-26); the prompt instructs the LLM to use calibrated scoring (1.0 unambiguous / 0.5 adjacent / 0.0 unrelated) with borderline 0.4–0.6 exemplars baked in alongside framing exemplars.
**Tasks**
- [x] T-1.5.3.1 Define schema (Pydantic) — `stance` ∈ {for, against, neutral, unclear}; `sentiment` ∈ {positive, negative, mixed, neutral}; `framing` ∈ {technical, political, emotional, experiential}; `topic_relevance` ∈ [0, 1] *(shipped 2026-04-28 — PR [#94](https://github.com/khoks/VideoResearchPro/pull/94); module `backend/app/services/social_classify.py` exports `StanceClassification` + `TOPIC_RELEVANCE_THRESHOLD = 0.50`)*
- [x] T-1.5.3.2 Add to registry with token-budget recommendation *(shipped 2026-04-28 — PR [#94](https://github.com/khoks/VideoResearchPro/pull/94); `social_classify_stance` registered with default `UseCaseConfig("openai", "gpt-4.1-mini", "off")`, `default_route="fast"`, full token-budget metadata)*
- [x] T-1.5.3.3 Inline call inside each connector's `fetch_text()` per [D-023](decisions.md#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28) — *shipped 2026-04-28 PR [#107](https://github.com/khoks/VideoResearchPro/pull/107). Adds `classify(text, query)` to `app/services/social_classify.py`, wires inline into `RedditConnector.fetch_text` and `HNConnector.fetch_text`, populates `ExtractedText.extra["classification"]`. Fail-soft on every error path. 12 classifier unit tests + 2 connector tests. `BaseConnector.fetch_text` signature gains `query: str = ""` kwarg; `job_tasks.py` call sites pass `query=job.topic or ""`.*
- [x] T-1.5.3.4 Persist classification into `Document.source_metadata_json["classification"]` — *shipped 2026-05-02 PR [#113](https://github.com/khoks/VideoResearchPro/pull/113). Document-level classification persisted via the `classification=` kwarg on `_upsert_candidate_and_link`. Sibling source_metadata keys preserved on re-upsert. Per-comment classification under `source_metadata.comments[]` deferred to follow-up — today's classifier classifies the document-level OP+top-comment text per D-023, not per-comment*
- [ ] T-1.5.3.5 Tests with golden short-text examples (sarcasm, sincere praise, in-favor, against)
- [ ] T-1.5.3.6 Framing prompt exemplars — **two short canonical examples per framing value** (technical, political, emotional, experiential) baked into the prompt; topical diversity (tech / policy / generic-life) so classifier learns *register*, not topic. Locked exemplars in [`source-types.md` § Framing prompt exemplars](source-types.md#framing-prompt-exemplars-for-t-1536). Golden tests cover at least one example from each set (paired with T-1.5.3.5).

#### S-1.5.4 🟢 Single polymorphic `<ApprovalCard>` (per [D-016](decisions.md#d-016--single-polymorphic-approval-card-driven-by-source_metadata-2026-04-26))

**PR:** TBD
**Acceptance.** Approval list rendered through a **single `<ApprovalCard>` component** dispatched on `source_type` + `source_metadata`, not per-source-type card variants. Composition primitives: `<CardHeader>` (avatar / display name / platform glyph), `<CardBody>` (title or excerpt), `<CardMetaRow>` (variable `(icon, label, value)` chips: views / score / likes / RTs / points / comment count / duration / word count / published date), `<CardBadgeRow>` (stance / sentiment / framing badges per [D-014](decisions.md#d-014--add-framing-axis-to-social_classify_stance-schema-2026-04-26)), `<CardActions>` (checkbox + "View on platform"). Each source-type registers a config entry (~30 lines) declaring which chips to show, the platform glyph, and the header field mapping. New source type = new config entry, not a new component file. Filter chips operate on `source_metadata.<field>` regardless of `source_type`.
**Tasks**
- [x] T-1.5.4.1 Build `<ApprovalCard>` polymorphic primitive + sub-components — *shipped 2026-05-02 PR [#118](https://github.com/khoks/VideoResearchPro/pull/118). Components: `<CardHeader>` / `<CardActions>` / `<CardBody>` / `<CardMetaRow>` (uses formatter dispatch) / `<CardBadgeRow>` (consumes existing `<ClassificationBadgeRow>`). FORMATTERS hybrid registry: durationSeconds / relativeTime / signedNumber / numberWithCommas / truncate. customSlot escape hatch wired with signature per D-016/D-018. TypeScript build green (337 modules)*
  - **Types subset shipped 2026-04-28** — PR [#95](https://github.com/khoks/VideoResearchPro/pull/95). `frontend/src/components/approval/types.ts` exports the full D-018 shape (`SourceMetadata` discriminated union, `MetadataFor<K>`, `FormatterName`, `MetaChip<T>`, `FilterChip<T>`, `ApprovalCardConfig<T>`, mapped-type `SourceConfigRegistry`, `ApprovalCardProps<T>`, classification mirror, `ApprovalDocument` fixed-slot type). React component build + formatters.ts impl + YouTube migration + Reddit/HN config entries are remaining sub-work.
- [x] T-1.5.4.2 *(shipped PR [#108](https://github.com/khoks/VideoResearchPro/pull/108), badge row; checkbox reconciled 2026-10-18 per M-1.5 C5)* Stance / sentiment / **framing** badge sub-component (consumed by `<CardBadgeRow>`); tooltip-on-hover with full classification breakdown.
- [x] T-1.5.4.3 *(shipped PR [#122](https://github.com/khoks/VideoResearchPro/pull/122); checkbox reconciled 2026-10-18 per M-1.5 C5)* Filter chips ("show only against", "show only positive", "show only experiential framing", "show only score ≥ N", **"Show low-relevance candidates" toggle** per [D-021](decisions.md#d-021--topic-relevance-threshold--050-2026-04-26)) — filter `source_metadata.<field>` regardless of `source_type`. Default approval list applies `topic_relevance >= 0.50`; the toggle drops the cutoff to 0.0 to surface hidden candidates. Filter state lives client-side; chips do not re-fetch / re-classify.
- [x] T-1.5.4.4 *(shipped PR [#122](https://github.com/khoks/VideoResearchPro/pull/122); checkbox reconciled 2026-10-18 per M-1.5 C5)* Migrate existing YouTube approval card to `<ApprovalCard>` as the first config-entry consumer; verify visual + interaction parity vs. today's bespoke component before any social-post type is wired.
- [x] T-1.5.4.5 Reddit + HN config entries — *shipped 2026-05-02 PR [#118](https://github.com/khoks/VideoResearchPro/pull/118). `SOURCE_CONFIGS` mapped-type registry with three entries (video / reddit_post / hn_story); each carries platform glyph + chip layout + formatter selections. Mapped type forces compile-time exhaustiveness — adding Mastodon / Bluesky / podcast = one entry each.*

#### S-1.5.5 🟢 Citation rendering for social posts

**Shipped:** 2026-05-02 — PR [#117](https://github.com/khoks/VideoResearchPro/pull/117) (frontend) + 2026-05-03 — PR [#127](https://github.com/khoks/VideoResearchPro/pull/127) (qa_agent backend dispatch)
**Acceptance.** Q&A answer citations rendering for social `source_type` values shows author handle + post date + platform; clicks open the permalink with `#comment-<id>` anchor when the cite is from a reply.
**Follow-up Story:** [S-1.5.12 — Backend reference enrichment](#s-1512--backend-reference-enrichment) covers the missing producer half — propagating `source_type` / `permalink` / `author` / `subreddit` / `instance` from `Document.source_metadata_json` through the chunking pipeline into Chroma metadata so `_chunk_to_reference` can dispatch correctly in production.
**Tasks**
- [x] T-1.5.5.1 + T-1.5.5.2 Citation renderer dispatch + per-platform URL builders — *shipped 2026-05-02 PR [#117](https://github.com/khoks/VideoResearchPro/pull/117). `<CitationLink>` polymorphic component dispatches by `Reference.source_type`; `renderCitation(ref) → {href, label}` is the pure dispatcher (testable). Per-source labels: video → "title · channel · timestamp", reddit_post → "r/sub · u/author · title", hn_story → "HN · author · title", mastodon_post → "@user@instance · title", bluesky_post → "@handle.bsky.social · title". JobDetailPage + LibraryQAPage migrated.*
- [x] T-1.5.5.3 Backend `_chunk_to_reference` polymorphic dispatch — *shipped 2026-05-03 PR [#127](https://github.com/khoks/VideoResearchPro/pull/127); extended for Mastodon in [#128](https://github.com/khoks/VideoResearchPro/pull/128) and Bluesky in [#129](https://github.com/khoks/VideoResearchPro/pull/129). Reads `source_type` from chunk metadata and emits the right field set per source. The producer side (chunker writing `source_type` to Chroma in the first place) ships in [S-1.5.12](#s-1512--backend-reference-enrichment).*

#### S-1.5.6 🟢 Mastodon connector

**Shipped:** 2026-05-03 — PR [#128](https://github.com/khoks/VideoResearchPro/pull/128)
**Linked decision:** [D-027 — Mastodon discovery uses the public hashtag timeline (no auth, single-hashtag normalisation)](decisions.md#d-027--mastodon-discovery-uses-the-public-hashtag-timeline-no-auth-single-hashtag-normalisation-2026-05-03)
**Acceptance.** Same shape as Reddit/HN. ActivityPub-based discovery via the public hashtag timeline (`/api/v1/timelines/tag/<hashtag>`); thread fetch via `/api/v1/statuses/<id>` + `/api/v1/statuses/<id>/context`. No auth required. No paid tier needed.
**Tasks**
- [x] T-1.5.6.1 Mastodon instance config (`MASTODON_INSTANCE_BASE`, default `https://mastodon.social`; per-job override is a follow-up to S-1.5.6 once the submit-research form gains the `mastodon_instance` source_metadata input)
- [x] T-1.5.6.2 Search + thread fetch implementation — `app/sources/mastodon/{client,connector,flatten}.py` (hashtag-timeline discovery, status + context flatten, top-N replies by favourites with depth markers, inline classifier per D-023)
- [x] T-1.5.6.3 Tests — `backend/tests/test_sources/test_mastodon_connector.py` (~40 tests covering hashtag normalisation, search/list-creator/metadata/text wiring, classifier integration, fail-soft on get_context errors, depth-marker rendering, HTML strip)
- [x] T-1.5.6.4 Frontend `SOURCE_CONFIGS['mastodon_post']` + `SourceMetadata` discriminator + `videoToApprovalProps` mapper extension (compile-time-enforced via mapped-type registry)
- [x] T-1.5.6.5 Polymorphic `_chunk_to_reference` (backend) + `<CitationLink>` (frontend) extension for `mastodon_post` — author + instance + reply-aware permalink

**Implementation notes.**
- Discovery uses Mastodon's public hashtag timeline because most instances disable global keyword search to honour user privacy. Topic queries are normalised to a single alphanumeric hashtag (lowercased, punctuation stripped, Unicode letters preserved).
- Replies arrive flat with `in_reply_to_id` pointers; depth is reconstructed from the parent chain so the depth marker (`↳`) matches threading even after favourites-sorting.
- Status `language` flows through to `ExtractedText.language` so multilingual indexing knows what it's storing — Mastodon is genuinely multilingual.
- Federated reach: `mastodon.social` (the default) federates with most public instances, so a single connection point gives broad discovery without per-instance auth. Self-hosters can override with `MASTODON_INSTANCE_BASE`.
- Per-source rate-limit / retry config (T-1.5.11.2 from the M-1.5 polish backlog) still applies to Mastodon when it lands; the unauth ceiling is 300 req/5min ≈ 60 rpm and the client throttles defensively to that.

#### S-1.5.7 🟢 Bluesky connector

**Shipped:** 2026-05-03 — PR [#129](https://github.com/khoks/VideoResearchPro/pull/129)
**Linked decisions:** [D-028 — Bluesky uses public unauthenticated AT-Proto XRPC](decisions.md#d-028--bluesky-uses-public-unauthenticated-at-proto-xrpc-deviation-from-s-157-spec-2026-05-03), [D-029 — Bluesky `source_id` is the AT-URI, not the bsky.app web URL](decisions.md#d-029--bluesky-source_id-is-the-at-uri-not-the-bskyapp-web-url-2026-05-03)
**Acceptance.** AT-Protocol search + thread fetch via the public XRPC API at `https://public.api.bsky.app/xrpc/`. **No auth required for ingest** — the original spec called for app-password auth, but Bluesky's public read endpoints (`searchPosts`, `getPostThread`, `getProfile`, `getAuthorFeed`) are open and that's what we use. If Bluesky tightens rate limits later, swapping to an authenticated PDS endpoint is a matter of adding a token-fetching path and toggling `BLUESKY_XRPC_BASE`.
**Tasks**
- [x] T-1.5.7.1 AT-Proto XRPC client integration — `app/sources/bluesky/client.py` with rate-limited `searchPosts`, `getPostThread`, `getProfile`, `getAuthorFeed` wrappers; `app/sources/bluesky/connector.py` implementing the BaseConnector contract; `app/sources/bluesky/flatten.py` for OP + top-N replies (by likes) with depth markers reconstructed by walking the recursive `replies` tree.
- [x] T-1.5.7.2 Tests — `backend/tests/test_sources/test_bluesky_connector.py` (~50 tests covering search/list/metadata/text wiring, classifier integration, AT-URI validation, comment_url emission, blocked-post / repost skipping, language extraction from `record.langs`).
- [x] T-1.5.7.3 Frontend `SOURCE_CONFIGS['bluesky_post']` + `SourceMetadata` discriminator + `videoToApprovalProps` mapper extension (compile-time-enforced via mapped-type registry).
- [x] T-1.5.7.4 Polymorphic `_chunk_to_reference` (backend) + `<CitationLink>` (frontend) extension for `bluesky_post` — author + reply-aware permalink (same `comment_url` reply-anchor pattern as Mastodon).

**Implementation notes.**
- Identity: `Candidate.source_id = f"bluesky:{at_uri}"`. AT-URIs are stable across handle renames (DIDs are permanent); the bsky.app web URL goes into `Candidate.source_url` for browser-friendly citations.
- Discovery: `searchPosts` returns posts ranked by Bluesky's relevance scoring (keyword + recency + engagement weighting). No query normalisation needed — AT-Proto search accepts free text.
- Creator-feed: `getAuthorFeed` accepts both handles and DIDs as `actor`. Reposts (entries with `reason.$type === '...#reasonRepost'`) are filtered out — parity with how Mastodon excludes reblogs.
- Reply tree: `getPostThread` returns recursive `{post, replies}` shape. Depth-first walk yields absolute depth per reply; we sort by `likeCount` and trim to top-N.
- Each reply segment carries its own `comment_url` (the reply's bsky.app web URL) so the reference enricher can deep-link to that exact reply when chunks of its body get cited — same reply-anchor pattern as Mastodon.
- Language: `record.langs[0]` flows through to `ExtractedText.language` for multilingual indexing.
- Blocked / not-found posts (`#blockedPost`, `#notFoundPost` thread nodes) are skipped during walking; their visible children (if any) still render.

**Closes M-1.6** ✅ — Mastodon (S-1.5.6) + Bluesky (S-1.5.7) shipped same day. The polymorphic-connector / approval / citation pattern is now validated across four social-media surfaces (Reddit / HN / Mastodon / Bluesky); future connectors slot into the same shape.

#### S-1.5.8 🟢 Manual-paste mode (Mode B for FB/IG/LI/X-without-paid)

**Shipped:** 2026-05-03 — PR [#144](https://github.com/khoks/VideoResearchPro/pull/144). Twelve source types in the connector registry now (5 paste-mode source types added on top of the prior 7).

**Acceptance.** User pastes 1–N post URLs from any supported platform; system fetches each via the article-connector machinery (trafilatura → Playwright fallback) and ingests as the right `source_type`. Honest UI: search disabled for these platforms, paste-only.

**Tasks**
- [x] T-1.5.8.1 URL → `source_type` resolver — *shipped PR #144. `app/services/paste_url_resolver.py::resolve_source_type(url)` host-based router. facebook.com / fb.com → fb_post; instagram.com → ig_post; linkedin.com → li_post; twitter.com / x.com → tweet; else → article.*
- [x] T-1.5.8.2 Reuse `app/services/article_extraction/` (E-1.6 T-1.6.1 primitives) — *✅ T-1.6.1 shipped 2026-05-03 PR [#135](https://github.com/khoks/VideoResearchPro/pull/135). All five paste connectors delegate to extract_text in their fetch_text method.*
- [x] T-1.5.8.3 🟢 Frontend "Paste URLs" surface on the Library page — *shipped 2026-10-19 PR [#224](https://github.com/khoks/VideoResearchPro/pull/224). Lives on the new **Add sources** tab of `/library` (not on job submission: the endpoint is library-scoped and starts no job). One-URL-per-line textarea with client-side trim / dedupe / cap at the server's 100, a live count of detected source types (mirror of `resolve_source_type`), and a per-URL result table showing the server's `source_type`, word count and `created` / `deduped` / `extraction_failed` / `invalid_url`. Pure result-state logic lives in `frontend/src/utils/ingestResults.ts`. The same PR fixed a backend defect the first caller exposed: `_ingest_single_paste_url` read `current_user` from a scope that did not have it, so every non-blank URL raised `NameError`; now threaded through, pinned by `tests/test_routers/test_library_paste_urls.py`. Linked decision: [D-069](decisions.md#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19). Caveat resolved 2026-10-19: [S-5.10.4](#s-5104--key-document-visibility-on-document_id) (PR [#241](https://github.com/khoks/VideoResearchPro/pull/241)) keyed visibility and the Chroma write on `document_id`, so a pasted page is listed, searchable and retrievable by its owner and nobody else.*
- [ ] T-1.5.8.4 ⚪ Per-platform `source_metadata` extraction (author handle, date) — *current default uses trafilatura's metadata pass which works for blogs/articles but is mediocre for FB/IG/LI/X-specific fields. A future PR adding per-platform extractors (parse FB post author from meta tags, X handle from URL, etc.) sharpens the metadata. Not blocking I-1.*
- [x] T-1.5.8.5 FB / IG paste support — *unblocked + shipped via the combination of T-1.6.6 (Playwright fallback) + S-1.5.8 paste connectors. Operators with `ARTICLE_PLAYWRIGHT_ENABLED=True` get working SPA extraction; FB / IG URLs route to fb_post / ig_post connectors which delegate through the Playwright path.*

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

#### S-1.5.11 🟢 Topic-job routing through new connectors

**PR:** TBD
**Filed 2026-04-26** per [D-020](decisions.md#d-020--file-orchestrator-dispatch-as-standalone-story-s-1511-2026-04-26) (resolves [OQ-10](#open-questions-parking-lot)). The Reddit (S-1.5.1) and HN (S-1.5.2) connectors emit `Candidate` objects standalone, but `app/tasks/job_tasks.py` does not route topic jobs through them yet. T-1.5.1.4 / T-1.5.2.5 (storage wiring, blocked on E-1.10) implicitly assume an orchestrator step that this Story owns.

**Acceptance.** Topic jobs with `source_types=["reddit_post","hn_story",...]` route through the connector registry via a `dispatch_by_source_type(source_type, ...)` mechanism. The dispatcher reads the connector registry and routes each `source_type` to its `BaseConnector` implementation (search → list → fetch_metadata → fetch_text). Per-source-type rate-limit + retry config externalized so each connector declares its own constraints. Progress reporting parity with the existing YouTube path (Redis pub/sub events match shape + cadence). End-to-end pipeline tests cover Reddit-only, HN-only, and mixed `["video","reddit_post","hn_story"]` jobs.

**Tasks**
- [x] T-1.5.11.1 Search-phase dispatcher in `app/services/connector_dispatch.py` — *shipped 2026-04-28 PR [#109](https://github.com/khoks/VideoResearchPro/pull/109). Exposes `dispatch_search(source_types, query, instructions, limit_per_type) -> DispatchResult` with per-source-type candidates + captured errors. Fail-isolated: missing connector / connector exception / `NotImplementedError` (PDF-style) all handled per-source. Sequential today; T-1.5.11.3 decides parallel/round-robin. 8 unit tests covering happy path, error isolation, and edge cases.*
- [ ] T-1.5.11.2 Per-source-type rate-limit + retry config in `BaseConnector` subclasses — *deferred polish; current sequential dispatch with each connector's internal rate-limit (e.g. RedditClient's 100 req/min) is sufficient for v1*
- [x] T-1.5.11.3 Fan-out semantics — *resolved as **sequential** for v1 in PR [#116](https://github.com/khoks/VideoResearchPro/pull/116). Parallel is the right answer for high-fanout multi-source jobs; deferred until we see concurrency pressure*
- [x] T-1.5.11.4 Progress-reporting parity — *shipped 2026-05-02 PR [#116](https://github.com/khoks/VideoResearchPro/pull/116). `execute_topic_job` reports combined candidate count via existing `publish_progress` / `publish_status_change` channels; UI WebSocket handler doesn't need source-type-specific branches.*
- [x] T-1.5.11.5 End-to-end pipeline test: submit topic job with `source_types=["reddit_post"]` — *✅ shipped via integration test in PR [#116](https://github.com/khoks/VideoResearchPro/pull/116) (`test_execute_topic_job_reddit_only_goes_through_dispatch_path`). HTTP-level e2e via routers is the only remaining variant and tracked in §M-1.5 polish backlog.*
- [x] T-1.5.11.6 Same e2e test for `hn_story` — *✅ shipped in PR [#121](https://github.com/khoks/VideoResearchPro/pull/121) (`test_execute_topic_job_hn_only_goes_through_dispatch_path`); covered the same fail-isolation + dispatch-path verification as the Reddit variant.*
- [x] T-1.5.11.7 Same e2e test for mixed `["video","reddit_post","hn_story"]` — *✅ shipped in PR [#121](https://github.com/khoks/VideoResearchPro/pull/121) (`test_execute_topic_job_mixed_video_reddit_hn_combines_both_paths` + `test_execute_topic_job_isolates_one_source_failure`). Mixed path verified to combine YouTube + dispatcher candidates and to isolate per-source failures.*
**Dependencies.** Was independent of E-1.10 for build; e2e tests now run against the post-E-1.10 schema with storage tasks shipped.

#### S-1.5.12 🟢 Backend reference enrichment

**Closed 2026-05-03.** Filed and shipped same day as the producer-side completion of [S-1.5.5](#s-155--citation-rendering-for-social-posts) (frontend rendering). Per-document layer shipped in PR [#131](https://github.com/khoks/VideoResearchPro/pull/131); per-segment + LLM-prompt layers shipped in PR [#134](https://github.com/khoks/VideoResearchPro/pull/134).

**Linked decision:** [D-030 — Backend reference enrichment ships per-document polymorphic Chroma metadata first; per-segment deferred](decisions.md#d-030--backend-reference-enrichment-ships-per-document-polymorphic-chroma-metadata-first-per-segment-comment_idcomment_url-deferred-2026-05-03)

**Context.** After M-1.6 closed, the polymorphic citation pipeline had a producer/consumer mismatch. Frontend `<CitationLink>` and backend `_chunk_to_reference` both dispatched correctly by `source_type`, but `chunk_transcript()` was still writing only YouTube-shaped fields to Chroma. So in production every social-media chunk fell through to the YouTube default branch — even though the source row carried the right `source_type`.

**Acceptance ✅ met.** Production Q&A citations across all five source types (`video` / `reddit_post` / `hn_story` / `mastodon_post` / `bluesky_post`) render with their dedicated `_chunk_to_reference` branches, with correct labels, platform-canonical URLs, AND per-reply deep-links (where applicable) when the chunk originated from a specific reply.

**Tasks**
- [x] T-1.5.12.1 Per-document polymorphic Chroma metadata — *shipped 2026-05-03 PR [#131](https://github.com/khoks/VideoResearchPro/pull/131). Threaded `source_type` / `source_id` / `source_url` / `permalink` / `author` / `subreddit` / `instance` from `Document.source_metadata_json` through `_build_video_metadata()` → `chunk_transcript()` → `chroma_service.insert_chunks()`. 17 new tests; backend suite 549 → 566.*
- [x] T-1.5.12.2 Per-segment reply-anchor fields (`comment_id` / `comment_url`) — *shipped 2026-05-03 PR [#134](https://github.com/khoks/VideoResearchPro/pull/134). `_Seg` tuple shape changed from `(text, start, end)` to `(text, start, end, extra)`; sentence-expansion propagates parent `extra` to every sub-segment; new `_emit_chunk` helper applies a **dominant-segment heuristic** (most-tokens segment in chunk wins; see [D-031](decisions.md#d-031--dominant-segment-heuristic-for-chunk-metadata-promotion-2026-05-03)) to promote `comment_id` / `comment_url` / `author` / `kind` / `depth` to chunk-level metadata. The Q&A agent's existing per-source `_chunk_to_reference` branches already read these fields and prefer them when present, so the citation now jumps to the specific reply rather than the OP. 7 new chunking tests (single-reply propagation, video transcript empty defaults, dominant-segment heuristic across straddling replies, sentence-expansion preserving extra, malformed-extra defensive handling, OP-dominates-chunk fallback). Backend suite 566 → 573.*
- [x] T-1.5.12.3 `extract_references` LLM-prompt update for polymorphic shape — *shipped 2026-05-03 PR [#134](https://github.com/khoks/VideoResearchPro/pull/134). `USED_SOURCES_PROMPT` rewritten — was YouTube-only ("whose video was actually cited"), now refers to "source" generically and lists all 5 source types so the auditor knows the variety it might see. Chunk-listing format changed from `index | video_id | video_title` to `index | [source_type] | source_id | title` with per-source prefixes (`[reddit_post]` / `[hn_story]` / `[mastodon_post]` / `[bluesky_post]` / `[video]`).*

**Implementation notes (T-1.5.12.1, shipped).**
- `_build_video_metadata()` is the choke point for per-document polymorphic field lifting. It reads `source_metadata_json` defensively (None / non-dict / missing keys all handled) and emits a flat dict the chunker can pass through to Chroma.
- `chunk_transcript()` writes the polymorphic block alongside the legacy YouTube-shaped fields. Legacy chunks already in Chroma keep working because `_chunk_to_reference` falls back to the YouTube branch when `source_type` is missing — the right behaviour for legacy rows since they're all `source_type='video'` anyway.
- New source types (the upcoming M-1.7 podcast connector, future `article` / `pdf`) just need to populate the right keys in `Document.source_metadata_json`; the chunker passes them through unchanged.

**Re-evaluation hooks (T-1.5.12.2, deferred).**
- Ship per-segment when (a) we observe materially different reply quality across multiple replies of the same thread getting cited (so jumping to specific reply matters), or (b) a future connector emits content where the per-reply identity is the citable unit (forum threads with multiple long top-level posts, podcast chapter markers, etc.).
- The chunker rework is also the natural moment to revisit pseudo-timestamp synthesis ([D-013](decisions.md#d-013--pseudo-timestamps-at-3-wps-for-text-based-connectors-2026-04-25)) — they could be replaced with explicit per-segment indices once `extra` is preserved end-to-end.

#### S-1.5.13 ⚪ Accept `source_types` on job creation
**PR:** TBD
**Filed 2026-10-19** from the S-8.6.1 finding (see I-1 *Scope-changed 2026-10-19 (II)*; [D-082](decisions.md#d-082--job-templates-identity-plus-immutable-versions-provenance-without-a-foreign-key-starters-in-a-self-contained-data-migration-2026-10-19)). Proposed as its own session; awaiting the user.
**Acceptance.** `POST /api/v1/jobs` with `source_types=["video","reddit_post"]` persists them, `_resolve_source_types` reads them back, and the run goes through `connector_dispatch` for the non-video types; the submit form offers the choice; Duplicate and templates carry it.
- [ ] T-1.5.13.1 `JobCreate.source_types` limited to the types `connector_dispatch` supports (default None → video); persist in `job_service.create_job`; return on `JobResponse`
- [ ] T-1.5.13.2 Add the field to `TemplateParameters` and `parameters_from_job` (the S-8.6.1 pinning test fails until this is done) and to `frontend/src/utils/jobForm.ts`
- [ ] T-1.5.13.3 Source-type picker on the Topic tab of `SubmitJobPage`
- [ ] T-1.5.13.4 HTTP-level test at the caller (the variant S-1.5.11 never wrote); a live connector check needs credentials, say what was not verified

### E-1.6 🟢 Article connector

**Closed 2026-05-03.** Full UX shipped across PRs [#135](https://github.com/khoks/VideoResearchPro/pull/135) (T-1.6.1 primitives), [#141](https://github.com/khoks/VideoResearchPro/pull/141) (T-1.6.6 Playwright fallback), [#144](https://github.com/khoks/VideoResearchPro/pull/144) (S-1.5.8 paste mode wired the article connector and citation rendering for it = T-1.6.4), [#145](https://github.com/khoks/VideoResearchPro/pull/145) (T-1.6.2 search-engine integration via Brave + T-1.6.3 RSS feed ingestion + T-1.6.5 e2e test wiring).

**Scope (primitives).** Connector-agnostic text-extraction module under `app/services/article_extraction/`: trafilatura primary, Playwright fallback for SPAs, hybrid strategy. Single API: `extract_text(url) -> ExtractionResult`. Reused by S-1.5.8 Mode B paste.

**Scope (full UX).** Search-engine integration (Brave Search default; opt-in BRAVE_SEARCH_API_KEY) + RSS feed iteration via `list_creator_items(feed_url)` + approval-card variant + paste-mode citation rendering.

**Tasks**
- [x] T-1.6.1 Build `app/services/article_extraction/` module — *shipped 2026-05-03 PR [#135](https://github.com/khoks/VideoResearchPro/pull/135). `ExtractionResult` dataclass + `extract_text(url)` hybrid orchestrator. 20 unit tests; backend suite 573 → 593. Unblocks S-1.5.8.*
- [x] T-1.6.2 Article search-engine integration — *shipped 2026-05-03 PR [#145](https://github.com/khoks/VideoResearchPro/pull/145). Brave Search via X-Subscription-Token; gated on BRAVE_SEARCH_API_KEY (operator opt-in). Returns [] gracefully when unset. Future PRs can add Tavily / Kagi as alt providers.*
- [x] T-1.6.3 RSS feed ingestion path — *shipped 2026-05-03 PR [#145](https://github.com/khoks/VideoResearchPro/pull/145). `list_creator_items(feed_url)` parses via feedparser; yields one Candidate per entry. Same shape as podcast RSS pattern.*
- [x] T-1.6.4 Article approval card variant + Q&A citation rendering — *shipped 2026-05-03 PR [#144](https://github.com/khoks/VideoResearchPro/pull/144) as part of the S-1.5.8 wave. SOURCE_CONFIGS entry, ArticleGlyph SVG, videoToApprovalProps mapper, `<CitationLink>` renderCitation case all landed in that PR.*
- [x] T-1.6.5 E2E article-job pipeline test — *covered by the existing test_orchestrator_multisource e2e suite (Reddit-only / HN-only / mixed) plus the per-connector tests for article search + RSS in PR [#145](https://github.com/khoks/VideoResearchPro/pull/145). HTTP-level e2e via routers is the M-1.5 polish-backlog item shared with all source types.*
- [x] T-1.6.6 Playwright fallback implementation — *shipped 2026-05-03 PR [#141](https://github.com/khoks/VideoResearchPro/pull/141). Real headless-Chromium SPA extraction. Gated on `ARTICLE_PLAYWRIGHT_ENABLED` (default False); opt-in via `backend/requirements-spa.txt`. 8 new tests; backend suite 637 → 645. Unblocks S-1.5.8 T-1.5.8.5 (FB / IG paste).*

### E-1.7 🟢 Podcast connector

**Shipped:** 2026-05-03 — PR [#140](https://github.com/khoks/VideoResearchPro/pull/140). Closes Milestone **M-1.7** (Podcast end-to-end).

**Linked decision:** [D-033 — Whisper-as-service for podcasts: reuse existing OpenAI Whisper path (resolves OQ-4)](decisions.md#d-033--whisper-as-service-for-podcasts-reuse-existing-openai-whisper-path-resolves-oq-4-2026-05-03)

**Scope.** Spotify / Apple show URL or RSS feed → episode list → text from existing transcript (Podcast Index 2.0 `<podcast:transcript>` SRT/VTT extension) or Whisper transcription (reused OpenAI Whisper path from `youtube_service`). Each episode = one `Document` with `source_type='podcast_episode'`.

**Implementation notes.**
- Discovery is two-tier: iTunes Search API for shows + per-show RSS for episodes. Topic search yields up to `PODCAST_SEARCH_TOP_N_SHOWS × PODCAST_EPISODES_PER_SHOW` candidates.
- Identity: `source_id = f"podcast:{episode_guid}"`. GUIDs are required by RSS-2.0 and stable across CDN URL rotations.
- Per-segment `extra` carries `comment_url = episode_url + #t=<sec>` so podcast players that honour the fragment (Overcast, Pocket Casts, Apple Podcasts iOS 17+) deep-link citations to the cited timestamp.
- Whisper API gated on `OPENAI_API_KEY`; fail-soft to None when unset (same pattern as YouTube fallback). Known limitation: 25MB upload cap means episodes >~20 min require either an in-feed transcript or a future audio-split path; in-feed transcripts are common enough that this isn't blocking for v1.
- 44 unit tests covering discovery, transcript parsing (SRT / VTT / Whisper), failure modes, identity, registration.

### E-1.8 🟢 PDF / e-book connector

**Shipped:** 2026-05-03 — PR [#142](https://github.com/khoks/VideoResearchPro/pull/142). Closes Milestone **M-1.8** (PDF end-to-end).

**Linked decisions:** [D-034 — PDF source-type identity uses first-64KB SHA-256](decisions.md#d-034--pdf-source-type-identity-uses-first-64kb-sha-256-not-full-file-hash-2026-05-03), [D-035 — Connectors with no discovery surface raise `NotImplementedError`](decisions.md#d-035--connectors-with-no-discovery-surface-raise-notimplementederror-dispatcher-treats-as-zero-candidates-2026-05-03)

**Scope.** File upload (multipart) via `POST /api/v1/library/upload-pdf`. PyMuPDF text extraction; per-page boundaries preserved as segment metadata. Page-anchored citations via `permalink#page=<N>` deep-link fragments that standard PDF viewers (Chrome built-in, Firefox, Adobe) honour.

**Implementation notes.**
- First source type with no discovery surface — `search()` + `list_creator_items()` raise `NotImplementedError` per D-035; the dispatcher's `dispatch_search` already handles that gracefully per [D-026](decisions.md#d-026--sequential-fan-out-for-the-connector-dispatcher-2026-05-02).
- Identity: `source_id = f"pdf:{first_64kb_sha256}"` per D-034. Fast for very large PDFs; dedup-stable across trailer-metadata variation; idempotent re-upload.
- Raw bytes persist at `PDF_UPLOAD_DIR/<hash>.pdf` so future PRs can re-extract (e.g. when PyMuPDF improves table extraction) without re-uploading.
- `GET /api/v1/library/pdf/{digest}.pdf` serves bytes back so per-page deep-link citations work.
- Tables extracted via PyMuPDF's `find_tables()` and rendered inline with `[TABLE]` markers (future enhancement: emit as separate segments for better retrieval).
- 19 unit tests using real PyMuPDF (in-memory PDFs built via `fitz`'s writer; no fixture binaries).

**E-1.8 follow-ups.**
- [x] Frontend file-upload UI — *shipped 2026-10-19 PR [#224](https://github.com/khoks/VideoResearchPro/pull/224). Drop zone + file picker on the **Add sources** tab of `/library`; `.pdf` is enforced client-side before any byte leaves the browser. Files upload one at a time (the endpoint extracts and embeds synchronously, so parallel uploads only pile CPU on the API process) with a per-file progress bar, an "Extracting" phase once bytes are in, and a per-file result: Added / Already in library (`deduped=true`) / Failed with the 400 / 413 / 422 detail. The Sources list refreshes when the queue drains. Linked decision: [D-069](decisions.md#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19). Caveat resolved 2026-10-19: [S-5.10.4](#s-5104--key-document-visibility-on-document_id) (PR [#241](https://github.com/khoks/VideoResearchPro/pull/241)) keyed visibility and the Chroma write on `document_id`, so an uploaded PDF is listed, searchable and retrievable by its owner and nobody else.*
- Serving uploaded PDFs to a browser tab: `GET /library/pdf/{digest}.pdf` sits under the router-level `get_current_user` dependency, so a plain link or a citation's `#page=N` deep-link 401s from a new tab. The Library row fetches the bytes with the bearer header and opens a blob URL instead; the deep-link path needs the `?token=` pattern the export routes use.
- OCR for image-only PDFs (Tesseract or cloud-OCR fallback gated like Playwright).
- Per-page Q&A reranking (chunk-level page filter on retrieval).

### E-1.9 🟢 Rename `channels` → `creators` (DB + ORM)

**Closed 2026-05-03 — PR [#146](https://github.com/khoks/VideoResearchPro/pull/146).** Closes I-1.

**Linked decision:** [D-032 — Operator-coordinated runbook for data-bearing identifier renames](decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03)

**Scope.** Generalizes the YouTube-channel concept to any creator (podcast host, blog author, Twitter handle). Pure rename; no behavioral change. Two-phase per the D-032 precedent established by E-2.6:

- **Phase 1 (shipped, PR #146):** Python-level rename — `Creator` re-exported from new module `app.models.creator` as alias for `Channel`. Both names resolve to the same SQLAlchemy class. New code uses `Creator`; existing code using `Channel` keeps working. No DB changes.
- **Phase 2 (operator-coordinated runbook, deferred):** SQL-level rename — `channels` → `creators` table + `documents.channel_id` → `documents.creator_id` FK column via Alembic batch_alter_table. Documented in [`docs/migration-channels-to-creators.md`](migration-channels-to-creators.md). Self-hosters run the runbook on their own schedule; SaaS deployment runs it once for all tenants in a coordinated maintenance window when L5 ships.

**Why the same operator-coordinated split.** SQLite RENAME COLUMN with FK chain is non-atomic; default-keep-old-name matches operator expectations on `git pull master`; operators want side-by-side instances during evaluation. Same three reasons that drove D-032 originally.

**Note.** Plays the same role for creators as E-1.4 played for documents — and the same two-phase split E-2.6 used for brand identifier renames.

### E-1.10 🟢 Promote `video_id` PK to UUID `document_id`

**Promoted 2026-04-26** ahead of E-1.5 storage wiring per [D-015](decisions.md#d-015--promote-e-110-uuid-pk-ahead-of-reddit--hn-orchestrator-wiring-2026-04-26). Reddit (S-1.5.1) and HN (S-1.5.2) connectors are on master and emit namespaced `Candidate.source_id` strings (`reddit:<id>`, `hn:<id>`); landing E-1.10 first means their storage tasks (T-1.5.1.4, T-1.5.2.5) become trivial inserts on the new schema rather than a transitional namespaced-string PK that would need a second migration pass.

**Cadence: hard cutover** ([D-017](decisions.md#d-017--e-110-hard-cutover-single-migration-uuid-pk-promotion-2026-04-26), resolves OQ-7). Single Alembic migration, single PR — no transitional release. T-1.10.8 (round-trip migration test) is **gating** — the PR does not merge until both forward and rollback round-trip cleanly and the e2e smoke runs green on a real existing job. Every reader of `video_id` (14 importers across `youtube_service`, `chroma_service`, the five LangGraph agents, routers, and dataset exporters) gets visited and updated in the same PR; no `video_id` reads survive.

**Scheduling: four parallel tracks (2026-04-26).** Per user direction, four tracks proceed in parallel; each ships its own PR series and shares no files with the others:

- **Backend A — E-1.10** (this initiative): backend Alembic + ORM + FK retargeting.
- **Backend B — S-1.5.3**: `social_classify_stance` LLM use case + framing axis + threshold.
- **Frontend — T-1.5.4.1 / S-1.5.4**: polymorphic `<ApprovalCard>` primitive build.
- **I-2 remainder — E-2.5 (marketing site) and E-2.6 (code identifier rename)**: per the 2026-04-26 audit, E-2.1 / E-2.2 / E-2.3 / E-2.4 are already 🟢 (theme.ts + primitives + page migration + sidebar nav all shipped); the remaining I-2 work is the marketing landing page and the code-identifier cleanup with its data migration story.

Any can start first; none block the other. E-1.10 still gates Reddit / HN orchestrator wiring (D-015) and the e2e tests in S-1.5.11 (D-020); T-1.5.4.1 still gates Reddit / HN approval-UI rendering. S-1.5.11 (orchestrator dispatch) builds independently of E-1.10 but its e2e tests need E-1.10 + storage tasks to land.

**Scope.** Migrate `documents.video_id` PK column → `documents.document_id UUID` + a separate `documents.source_id text` column with `(source_type, source_id)` unique index. Cascade FK retargeting into `job_videos` (rename → `job_documents`) and `transcript_cache` (PK retargeted; rename → `text_cache` deferred unless trivial).

**Migration shape.**
- Add `document_id UUID NOT NULL DEFAULT gen_random_uuid()` (Postgres) / `BLOB(16)` populated via Python (SQLite) — the project ships SQLite today.
- Backfill `document_id` for all ~912 existing rows.
- Add `source_id TEXT` populated from existing `video_id` (since `source_type='video'` everywhere today, the existing `video_id` *is* the YouTube ID — no namespace prefix).
- Drop `video_id` PK constraint; add `(source_type, source_id)` unique constraint.
- Retarget FK targets in `job_videos` → `job_documents.document_id`; in `transcript_cache` → `document_id`.
- Reversible: rollback drops the new columns, reinstates the legacy PK.

**Tasks**
- [x] T-1.10.1 Alembic migration adding `document_id` + `source_id` columns; backfill from `video_id`; populate UUIDs for all rows. *(shipped 2026-04-28 — PR [#96](https://github.com/khoks/VideoResearchPro/pull/96); `source_id` was already in place from L1 PR-1, so this PR adds `document_id VARCHAR(36)` only, backfills with UUID4 per row, alters to NOT NULL, creates a unique index. Doubles as a **merge node** joining the two parallel migration heads `01c5b6dae736` (rename) and `b8c9d0e1f2a3` (multi-source columns) that had been silently parallel since L1 PR-1. Drive-by fix: `alembic/env.py` stale `Video` import → `Document`)*
- [x] T-1.10.2 Drop legacy `video_id` PK + add `(source_type, source_id)` unique constraint *(landed in PR [#112](https://github.com/khoks/VideoResearchPro/pull/112) via explicit table-rebuild on documents — SQLite's anonymous PK constraint forced a manual CREATE NEW + INSERT FROM OLD + DROP + RENAME pattern rather than batch_alter_table)*
- [x] T-1.10.3 ORM updates (`Document.document_id` PK; relationships re-pointed) *(PR [#112](https://github.com/khoks/VideoResearchPro/pull/112). Document gets eager UUID4 factory at `__init__` time so callers reading `doc.document_id` pre-flush see a populated value)*
- [x] T-1.10.4 Rename `job_videos` → `job_documents` *(PR [#112](https://github.com/khoks/VideoResearchPro/pull/112). Table + ORM `__tablename__` updated; class name kept as JobVideo for back-compat with existing imports; before_insert event listener resolves document_id from video_id for legacy fixtures)*
- [x] T-1.10.5 Retarget `transcript_cache` PK to `document_id` *(PR [#112](https://github.com/khoks/VideoResearchPro/pull/112). Same before_insert resolver pattern as JobVideo)*
- [x] T-1.10.6 Chroma chunk metadata migration — *no-op since OQ-11 wiped Chroma; new chunks naturally key on document_id via the new ORM. Documented in the migration's docstring*
- [x] T-1.10.7 Update reading sites for the new PK shape *(PR [#112](https://github.com/khoks/VideoResearchPro/pull/112). Surgical updates: `db.get(Document, video_id)` patterns swapped for `db.query(Document).filter(Document.video_id == video_id).first()` in routers/knowledge.py and tasks/job_tasks.py. The 50+ readers that just print/log/return `video.video_id` for the YouTube native ID still work via the back-compat column — full elimination is an E-2.6 follow-on)*
- [x] T-1.10.8 Tests: round-trip migration + 415-test suite passes + e2e smoke *(PR [#112](https://github.com/khoks/VideoResearchPro/pull/112). `alembic upgrade head` + `alembic downgrade -1` cycle round-trips cleanly; full backend suite 415/415 green; FastAPI app imports cleanly with 42 routes)*

**Status: 🟢 shipped 2026-05-02** — PR [#112](https://github.com/khoks/VideoResearchPro/pull/112). All 8 sub-tasks closed.

**Unblocked downstream:** T-1.5.1.4 + T-1.5.2.5 (Reddit/HN storage — shipped 2026-05-02 PR [#113](https://github.com/khoks/VideoResearchPro/pull/113)). T-1.5.3.4 (classifier persistence — also PR #113). M-1.5 e2e tests (still pending orchestrator wiring).

### E-1.11 🟡 Transcript-pipeline resilience at scale

**Shipped:** 2026-07-22 — PR [#189](https://github.com/khoks/VideoResearchPro/pull/189). Recovery fully validated live on job 0d4db8c3 across three waves: 31/63 recovered 2026-07-22 (segmented Whisper + yt-dlp client ladder while the IP block was active), and the final 32 recovered 2026-07-24 after the block lifted (fast caption path, paced by the new limiter). **Final corpus: 200/200 videos — 162 youtube (591,843 words) + 38 whisper (355,396 words) = 947,239 transcript words.** The wait-out-the-block strategy from D-051 proved correct; cookies/proxy knobs (S-1.11.10) remain available for blocks that persist.

**Filed 2026-07-22** from the 200-video deep-research test (job `0d4db8c3`, 2026-07-21/22, ~96 min end-to-end, completed): **137/200 fetched, 63 lost** — 36 to the 25MB Whisper cap (disproportionately long-form conference talks / podcasts), 27 to yt-dlp HTTP 403s. A YouTube transcript-API IP block after ~60 serial fetches made Whisper the primary path for 80% of videos (159/200 attempts). All stories below ship together in this branch's PR.
**Linked decision:** [D-051](decisions.md#d-051--transcript-pipeline-resilience-bundle-circuit-breaker--segmented-whisper--yt-dlp-client-fallback-2026-07-22)

#### S-1.11.1 🟢 Transcript throttle + IP-block circuit breaker

**Scope.** Adaptive pacing + circuit breaker for transcript fetches. Config: `YOUTUBE_TRANSCRIPT_RATE_LIMIT` default raised 0.5s → 3.0s with ±40% jitter; breaker opens after 3 consecutive IP-block signals; cooldown 120s doubling to 900s max; post-cooldown probe re-tests before resuming. While open, a video falls to Whisper only when the remaining wait exceeds a cap — otherwise the loop waits it out.

#### S-1.11.2 🟢 Segmented Whisper for >25MB audio

**Scope.** ffmpeg stream-copy chunking into ~20MB-target time chunks with 15s overlap; per-chunk transcription; merge with timestamps offset by each chunk's position; overlap-zone segments deduplicated by midpoint-ownership rule. `worstaudio` (smallest-audio-format) re-download fallback when ffmpeg is unavailable; only bails if still oversize. Design per [D-051](decisions.md#d-051--transcript-pipeline-resilience-bundle-circuit-breaker--segmented-whisper--yt-dlp-client-fallback-2026-07-22) part (b).

#### S-1.11.3 🟢 yt-dlp 403 hardening

**Scope.** Escalating retry ladder across YouTube innertube player clients (default → android → ios) with cooldowns between attempts; smaller-audio-format preference.

#### S-1.11.4 🟢 Transcript provenance fix

**Scope.** `fetch_transcript` returns its source; `transcript_cache` gains a `source` column via Alembic; `documents.transcript_source` is now honest — was hardcoded `'youtube'` (the 200-video run recorded 0 of ~96 Whisper transcripts as `'whisper'`).

#### S-1.11.5 🟢 Paginated YouTube search

**Scope.** `pageToken` loop in `search_videos`; `YOUTUBE_SEARCH_MAX_PAGES` default 2. Quota note: each page costs 100 units.

#### S-1.11.6 🟢 Unresolved-handle surfacing

**Scope.** Topic jobs store `{"resolved": [], "unresolved": []}` in `channel_list_resolved`; approval UI warns when channel handles failed to resolve (previously each failed handle silently burned a 100-unit search fallback with no user-facing signal).

#### S-1.11.7 🟢 Per-job Whisper budget

**Scope.** `WHISPER_MAX_PER_JOB` env var, default 50; videos beyond the budget are marked unavailable with a reason. Per-job UI control ⚪ deferred follow-up.

#### S-1.11.8 🟢 Extraction ETA + search-phase sub-progress

**Scope.** Extraction ETA in progress messages driven by rolling per-path pacing (transcript-API vs Whisper rates differ ~10×); search phase emits sub-progress stages (was a static 5% for the whole ~3.7 min phase).

#### S-1.11.9 🟢 Recovery tooling

**Scope.** `scripts/retry_unavailable_transcripts.py` re-fetches a job's unavailable documents, then chunks + embeds them into the global collection. Validated on job `0d4db8c3`'s 63 lost videos.

#### S-1.11.11 ⚪ Caption-track choice prefers the spoken language over auto-dubs
**Proposed for its own session 2026-10-19** (from S-1.16.2), with a brief covering T-1.11.11.1–3 and a measurement step first (list caption tracks and `defaultAudioLanguage` for the ~30 Hindi/Hinglish videos in the dev library).

**Raised in priority 2026-10-19 by the S-1.16.2 held-out evaluation: 2 of 13 Hindi-speech videos in that study arrived as machine-dubbed tracks (one Bengali, one English: `v6CuYULP3tM` lists `en-US(auto)` and `hi(auto)`), and an English dub is undetectable downstream — every quote from it is words the speaker never said.** **Filed 2026-10-19** from the S-1.16.2 corpus build ([D-080](decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19)). `_fetch_transcript_once` tries `en` / `en-auto` and then takes the FIRST listed track. Video `1v3_AQ26jZ0` (a Hindi lecture) lists `bn(auto)`, `en-US(auto)`, `hi(auto)`: `en-US` matched nothing, so the library now holds a machine-dubbed Bengali transcript of a Hindi lecture.
- [ ] T-1.11.11.1 Match regional English codes (`en-US`, `en-GB`) as English, but only when the track is the video's original audio language
- [ ] T-1.11.11.2 When English is unavailable, prefer the original-audio track over auto-dubbed ones; take the default audio language from the Data API (`snippet.defaultAudioLanguage`) when present
- [ ] T-1.11.11.3 Re-fetch documents whose stored transcript language differs from their default audio language (one-off script, reporting counts)

---

### E-1.12 🟢 LLM context-window resilience at scale

**Filed 2026-07-29** from the context-scale audit (five parallel readers + adversarial verification over every agentic call site, sized against a 200-video / 10.6M-token extreme corpus; reference job 0d4db8c3). Findings summarized in [architecture.md § Context-window & scale behavior](architecture.md#context-window--scale-behavior-audited-2026-07-29). **Shipped 2026-07-29** — PRs [#195](https://github.com/khoks/VideoResearchPro/pull/195) + [#196](https://github.com/khoks/VideoResearchPro/pull/196) (all 9 stories) plus the D-052 model re-audit: context windows measured empirically (nano/mini 272K, 5.4/5.5/5.6 922K, 4.1-mini 1,047,576), three-tier model stack restored (nano / 5.4-mini / 5.5), four use cases stepped down a price tier. Report batches now derive from the resolved model with a 120K quality cap; reduce recurses to a single summary; map failures bisect-retry then surface as a processing note in the report itself.

**Why it exists.** The report pipeline sizes batches to one global constant (`LLM_MAX_CONTEXT_TOKENS` = 1,047,576) blind to the resolved model; reduce is single-level; failed batches and channel-path overflow are silently dropped; `rank_and_curate` sends the whole pool in one prompt (~300K tokens at the new target=500 cap). Q&A surfaces are corpus-invariant (top-K bounded) and need no work.

**Stories**
- S-1.12.1 🟢 **Fix job-scoped Q&A retrieval** — qa_agent.py:111 uses the deprecated `query_collection` signature; job filter ignored → every job Q&A searches the whole global library (CLAUDE.md's scoping claim currently false). One-line fix + regression test. *Correctness bug, not scale.*
- S-1.12.2 🟢 Per-model `context_window` in `USE_CASE_REGISTRY`; derive report/channel batch budgets from the resolved model with a safety margin (replaces the global constant).
- S-1.12.3 🟢 Recursive reduce: loop pairwise until under budget + final merge; on reduce failure degrade to truncated summaries, never raw pass-through to compose.
- S-1.12.4 🟢 Loud accounting for dropped content: failed map batches, channel-path truncation, knowledge 60K tail-chop → progress message + report footnote ("N sources partially processed").
- S-1.12.5 🟢 Batch/tournament ranking in `rank_and_curate`; cap map batches ~120K tokens for extraction quality (context-rot mitigation independent of window fit).
- S-1.12.6 🟢 Catch context-length 400s → bisect batch and retry (adaptive splitting).
- S-1.12.7 🟢 Wire `max_tokens` from registry `typ_out` at all 20 call sites (4 set it today).
- S-1.12.8 🟢 Knowledge agent: windowed extraction above 60K instead of silent truncation; synthesize from extraction JSON without re-sending the full transcript.
- S-1.12.9 🟢 Doc drift: CLAUDE.md says CHUNK_SIZE 512/50 but config ships 256/32; registry holds 20 use cases, docs say 19.

### E-1.13 🟢 Per-user LLM overrides + cost calculator

**Filed 2026-07-29. Shipped 2026-07-29** — PRs [#199](https://github.com/khoks/VideoResearchPro/pull/199) + [#200](https://github.com/khoks/VideoResearchPro/pull/200). Linked decision: [D-054](decisions.md#d-054--per-user-llm-overrides--cost-calculator-gpt-56-adaptive-reasoning-findings-2026-07-29).
**Filing-error fixed 2026-07-29:** this epic was originally written under the I-2 heading (brand identity) by mistake; moved here under I-1 where it belongs. ID unchanged.

**Scope.** Expose all 20 per-use-case LLM settings (provider/model/reasoning) in user settings with DB-backed overrides that dynamically supersede registry defaults (ContextVar layer inside `byok_context` per D-041), plus a cost calculator benchmarked on the real 200-video job with researched cross-provider pricing (OpenAI / Anthropic / Google, source-cited, `as_of` stamped).

**Stories**
- S-1.13.1 🟢 `user_llm_overrides` schema + Alembic + top-precedence resolve layer — **Shipped:** 2026-07-29 — PR [#199](https://github.com/khoks/VideoResearchPro/pull/199)
- S-1.13.2 🟢 Settings REST surface (GET/PUT/DELETE + POST estimate) — **Shipped:** 2026-07-29 — PR [#199](https://github.com/khoks/VideoResearchPro/pull/199)
- S-1.13.3 🟢 `model_pricing.py` (researched 2026-07-29) + `cost_estimator.py` (benchmark = job 0d4db8c3 actuals; formulas mirror shipped pipeline mechanics) — **Shipped:** 2026-07-29 — PR [#199](https://github.com/khoks/VideoResearchPro/pull/199)
- S-1.13.4 🟢 `/account/ai-models` settings panel + live cost calculator UI — **Shipped:** 2026-07-29 — PR [#199](https://github.com/khoks/VideoResearchPro/pull/199)
- S-1.13.5 🟢 OpenAI adapter fixes from the D-054 research (`off`→explicit `none` on gpt-5.x; `minimal`→`low`) — **Shipped:** 2026-07-29 — PR [#199](https://github.com/khoks/VideoResearchPro/pull/199)
- S-1.13.6 ⚪ Responses-API path for guaranteed `max` reasoning on `search_rank_and_curate` (follow-up)
- S-1.13.7 🟢 Gemini integration — **Shipped:** 2026-07-29 — PRs [#199](https://github.com/khoks/VideoResearchPro/pull/199) (windows, pricing, `thinking_level` adapter) + [#200](https://github.com/khoks/VideoResearchPro/pull/200) (paid Tier-1 validation). *Scope-changed 2026-07-29:* started as a free-tier bench, expanded when paid billing was activated — 1M window verified end-to-end (API-stated 1,048,576), quota lift proven (295K/475K single requests), gemini-3.1-pro benched and verified live through the app, generation-aware `off` mapping per the measured 3.x thinking matrix, plus the launcher env-shadow fix (OS-level `GOOGLE_API_KEY`/`OPENAI_API_KEY` were overriding `backend/.env`). See D-054 amendments I + II.

### E-1.14 🟡 Model-tier quality evaluation harness

**Filed 2026-07-29.** Linked decision: [D-055](decisions.md#d-055--intelligence-delta-evaluation-methodology-production-input-replay--blind-ab-judging-2026-07-29). Realizes invention [N-001](inventions.md#n-001--production-replay-blind-delta-harness-for-per-call-site-model-tier-selection-2026-07-29). Docs PR: [#201](https://github.com/khoks/VideoResearchPro/pull/201).

**Why it exists.** Every model-tier decision through D-052/D-053/D-054 rested on proxy evidence — latency, context windows, JSON discipline, task-shape reasoning. None of it measured the thing that matters: **how much answer quality the cheap tiers actually give up on our corpus.** E-1.14 answers that empirically, per use case, and the verdicts feed back into `USE_CASE_REGISTRY` defaults and the E-1.13 override guidance.

**Method** (D-055): rebuild a completed job's exact per-call-site inputs from stored state using the app's own deterministic transforms, replay them through frontier models at maximum thinking, blind A/B judge against what production stored, with judges verifying claims against the live corpus rather than scoring prose.

**Reference run.** Job `0d4db8c3` — 200 videos, 1,057,331 transcript words, 5,149 chunks, 12 map batches at ≤120K tokens.

**Stories**
- S-1.14.1 🟢 Deterministic input-replay prep — rebuild chunks/batches/stats/retrieval from stored job state via the app's own chunker + batch budgeting; dump stored artifacts (report, Q&A, knowledge) for pairing. *Verified: reproduced 5,149 chunks / 12 batches.*
- S-1.14.2 🟢 Challenger replication at max effort across the pipeline — map ×12 (5,861 items, 200/200 videos), reduce, compose, full Q&A chain ×2, knowledge chain ×2, query planning. *Mixed provenance: Q&A + knowledge on Fable 5, report chain on Opus 5 after a subscription-limit switch — labelled per artifact, not averaged.*
- S-1.14.3 🟢 Blind pairing + rubric judging with retrieval-grounded verification. **Result: max-effort won all 6 comparisons** — report severe, knowledge ×2 / Q&A-context / query-plan moderate, Q&A-patterns minor. Scores in [D-055 Results](decisions.md#d-055--intelligence-delta-evaluation-methodology-production-input-replay--blind-ab-judging-2026-07-29).
- S-1.14.4 🟢 Loss attribution for unpersisted stages. **Result: 60 of 60 sampled facts from two batches absent from the shipped report (100% loss).** Root cause is the map/reduce token funnel, not model IQ — see S-1.14.8.
- S-1.14.5 🟢 Selection-criteria audit standing in for `search_rank_and_curate` (true re-rank impossible — rejected pool not persisted). *Finding: default selection graded 6.5/10 — ~20-24 questionable picks, IBM Technology at 10% of corpus despite not being a preferred channel, 12 of 30 preferred channels absent, zero flagship model-release coverage despite instructions naming GPT-5.x / Claude / Gemini.*
- **S-1.14.6 🟢 Persist agent intermediates + rejected candidate pool — shipped 2026-10-19** so quality is continuously monitorable instead of replay-only — see [architecture.md § Agent-intermediate retention gap](architecture.md#agent-intermediate-retention-gap-identified-2026-07-29). **Candidate-pool half shipped 2026-07-30**, PR [#205](https://github.com/khoks/VideoResearchPro/pull/205): `job_search_candidates` stores the whole pool with a `selected` flag. **Map/reduce half shipped 2026-10-19**, PR [#273](https://github.com/khoks/VideoResearchPro/pull/273), linked decision [D-088](decisions.md#d-088--report-intermediates-persisted-per-run-on-by-default-frozen-at-the-stage-that-produced-them-2026-10-19).
  - [x] T-1.14.6.1 `job_report_intermediates` (migration `a3b4c5d6e7f9`): one row per map call — bisected halves and failed batches included, with error and covered videos — plus one reduce row with its processing notes, grouped by `run_id`
  - [x] T-1.14.6.2 Captured through `run_report_agent(..., intermediates_out=)` (the search agent's `candidates_out` pattern); payloads serialised when each stage produces them, so compose's later item mutations never reach the record
  - [x] T-1.14.6.3 Persisted best-effort by the job task before the HTML is built, behind `REPORT_INTERMEDIATES_ENABLED` (default on, ~3 MB per 200-video run); `scripts/regenerate_report.py --persist-intermediates` adds a run next to the original
  - [x] T-1.14.6.4 `scripts/audit_report_intermediates.py` reads a run back: map calls by status, items by category, dropped chunks, and the reduce identity (in − duplicates − trimmed = out)
  - [x] T-1.14.6.5 Tests (`test_report_intermediates.py`): rows written and lossless on the real graph with fake LLMs, failed / unparsed batches recorded as rows, records frozen before compose mutates items, one `run_id` per run, setting-off path writes nothing, best-effort on a failing session, channel jobs write nothing, the job task's wiring, and the audit script
  *Status reconciled 2026-10-18; it had been left at ⚪.*
- **S-1.14.7 🟢 Measured verdicts as registry guidance, shown in `/account/ai-models` — shipped 2026-10-19**, PR [#251](https://github.com/khoks/VideoResearchPro/pull/251). The defaults half was already done decision by decision (D-057, D-062, D-073); this story moved the evidence behind them out of `decisions.md` and in front of the person choosing an override. No `default_config` changed. Evidence folded in: [D-052](decisions.md#d-052--measured-context-windows--three-tier-model-stack-e-112-model-re-audit-2026-07-29), [D-055](decisions.md#d-055--intelligence-delta-evaluation-methodology-production-input-replay--blind-ab-judging-2026-07-29), [D-056](decisions.md#d-056--report-pipeline-budgets-derived-from-work-lossless-reduce-sectioned-compose-2026-07-30), [D-057](decisions.md#d-057--volume-tier-moves-to-gpt-56-luna-selection-is-now-measurable-2026-07-30), [D-060](decisions.md#d-060--extraction-ratio-raised-020---040-2026-07-30), [D-061](decisions.md#d-061--s-11410-re-judge-the-intelligence-gap-after-the-fixes-2026-07-31), [D-062](decisions.md#d-062--report_compose-upgraded-to-claude-opus-5-2026-07-31), [D-072](decisions.md#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19), [D-073](decisions.md#d-073--frame-description-moves-to-gemini-31-flash-lite-on-image-grounded-grading-selection-stays-on-gpt-55-2026-10-19).
  - [x] T-1.14.7.1 `UseCaseInfo.guidance` (required): `measured` entries carry decision id, date, the gap to the flagship tier, what fails on a downgrade and the measured cost; `unmeasured` entries carry a note on what evidence exists. **8 measured** (`qa_formulate_answer`, `knowledge_synthesize_report`, `search_plan_queries`, `report_map_chunks`, `report_reduce_summaries`, `report_compose`, `visual_select_moments`, `visual_describe_frame`), **15 unmeasured**
  - [x] T-1.14.7.2 `ModelVerdict` per use case, scoped to reasoning levels: unacceptable — luna for frame description (22/66 unusable), nano for map (unparseable JSON on 1 of 2 batches), luna with reasoning on for map and era extraction, gpt-5.4-mini with reasoning on for the three mini sites; weaker — sonnet-5 for compose, mini and flash-lite for frame selection
  - [x] T-1.14.7.3 `assess_choice()` (verdicts + `VISION_CAPABLE_MODELS`); `/health/llm` reports guidance and warnings for the resolved config; `GET /settings/llm` ships guidance, a `vision` flag and `vision_capable_models`; the estimate prices each row on the default too
  - [x] T-1.14.7.4 Page: evidence badge, warning callouts, warning markers on model options before one is picked, benchmark cost against the default, collapsible evidence panel. Verified live on a scratch stack: compose on sonnet-5 shows `$3.03 against $7.58 (−$4.54)`, total $7.65 vs $12.20, matching D-062
  - [x] T-1.14.7.5 Tests: every use case measured-with-decision or unmeasured; every cited decision exists in `decisions.md`; verdict models are real ids; no default trips a warning; endpoint and `/health/llm` tests
  - [x] T-1.14.7.6 In passing: `qa_history_*` rows were grouped under "Job Q&A" (prefix order); two tests still iterated probe targets as bare names after #240
  - **Design choices made here, open to revision** (recorded as [D-076](decisions.md#d-076--model-guidance-measured-means-the-use-cases-own-output-was-graded-verdicts-warn-never-block-2026-10-19), not decided by the user):
    1. `measured` means this use case's own output was graded. The refine, extract and library-answer steps sat inside graded chains or moved tier alongside graded ones, and are `unmeasured` with a note rather than borrowing a sibling's verdict.
    2. "Unacceptable" on n=2 for nano on map batches (D-057 itself acted on n=2). "Weaker" for frame selection rests on agreement with the default's picks, which D-073 says is not quality; the copy says so.
    3. Warnings advise and never block a save, matching the fail-soft rule for the vision allowlist ([D-067](decisions.md#d-067--visual-understanding-separate-frames-table-marker-in-text-annotation-opt-in-per-job-2026-07-31)). A hard block for `unacceptable` would be one line in the PUT handler — see OQ-16.
- **S-1.14.8 🟢 Fix the report information funnel — shipped 2026-07-30.** Linked decision: [D-056](decisions.md#d-056--report-pipeline-budgets-derived-from-work-lossless-reduce-sectioned-compose-2026-07-30). Validated on job `0d4db8c3`: reduce now loses **0.00%** (5,861 items in / out, 200 videos + 92 channels retained, vs 91.2% of items and 46% of videos lost before).
  - [x] T-1.14.8.1 `report_map_chunks` completion budget derived from batch size (3,000 → ~24,000); registry `p95_input` corrected 32,000 → 120,000; new measured `MODEL_MAX_OUTPUT_TOKENS` (128K / 64K haiku)
  - [x] T-1.14.8.2 Reduce rewritten deterministic + lossless; even per-video compression past a 1M-token cost guard so no video is dropped wholesale
  - [x] T-1.14.8.3 Compose sectioned — one call per section, split further as material requires, so report length scales with corpus; Statistics rendered in code
  - [x] T-1.14.8.4 Reduce trims / failed sections / map drops disclosed as an in-report processing note
  - [x] T-1.14.8.5 Re-validated end to end (see D-056 Validation); isolating residual *model* delta needs a fresh full-corpus judging run — tracked as S-1.14.10

- **S-1.14.9 🟢 Two corpus traps — shipped 2026-07-30.** (a) Every extracted item carried an empty `video_url` because the map chunk header never supplied one, so **every timestamp citation in every report was a dead link** (`href="&t=123"`); the header now carries the URL and composed HTML unwraps any non-URL anchor. Validated: 104/104 links working, 6/6 videos correct, 0 fabricated. (b) `_item_video()` keys on `video_url` rather than title, so the two pairs of distinct videos whose titles differ only in letter case no longer merge.
- **S-1.14.10 🟢 E-1.14 harness re-run after the fixes — closed 2026-07-31.** Linked decision: [D-061](decisions.md#d-061--s-11410-re-judge-the-intelligence-gap-after-the-fixes-2026-07-31). Three independent blind judges on the regenerated production report vs the max-effort control, same corpus: **gap SEVERE → MODERATE**, mean **3.5 → 6.94** against the control's 8.72. Zero fabrications in either report. Production now exceeds the control on words (30,864 vs 26,631) and citations (1,489 vs 946); trails on video coverage (185 vs 200) and quantitative density.
- **S-1.14.14 🟢 Residual compose defects closed — shipped 2026-07-31** — PR [#209](https://github.com/khoks/VideoResearchPro/pull/209). Linked decision: [D-062](decisions.md#d-062--report_compose-upgraded-to-claude-opus-5-2026-07-31).
  - [x] T-1.14.14.1 Source in the VISIBLE citation text. Measured: citations with a source named nearby **30% → 63%**; attribution score **6 → 9**, now ahead of the control's 7
  - [x] T-1.14.14.2 Theme-first structure. Measured: sub-sections named after a channel **16% → 7%**; corpus titles mentioned **3 → 139** of 200. Did NOT move the insight score
  - [x] T-1.14.14.3 `_invoke_with_retry` with an error classifier — 7 sections, 0 failed, where a `529` had cost one
  - [x] T-1.14.14.4 Statistics marked computed-not-estimated — **partially effective**; residual defects carried to S-1.14.15
  - [x] T-1.14.14.5 Re-judged; overall **6.94 → 7.22**, coverage gap moderate → minor, synthesis unchanged at 6.33 → tier upgrade justified per the pre-registered rule
- **S-1.14.16 🟢 `report_compose` → claude-opus-5 — shipped 2026-07-31.** [D-062](decisions.md#d-062--report_compose-upgraded-to-claude-opus-5-2026-07-31). Head-to-head on identical input: synthesis 9 vs 6-7, tension-handling 9 vs 6, specificity 9-10 vs 5.5-6. The length prior was tested and refuted — opus is 2.6x longer AND ~1.4x denser (3.42 vs 2.42 claims/100w), so ~3.5x payload. sonnet dropped ~8 corpus debates, named 18 tools vs 47, contradicted itself on a consensus claim, and invented two host names. Cost $7.65 → $12.20 per benchmark job.
- **S-1.14.15 🟢 Executive-summary factual defects (T-1.14.14.4 residue) — shipped 2026-10-19**, PR [#227](https://github.com/khoks/VideoResearchPro/pull/227), batched with S-1.17.2 (same prompt files). Linked decision: [D-072](decisions.md#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19).
  - [x] T-1.14.15.1 Summary mis-dates the corpus — the statistics arrived as a raw JSON dump whose 92-entry channel breakdown buried the dates. Every compose call now receives a compact `_corpus_facts` block (count, words, publication span, per-year histogram, discussed-era span) and is told to quote it exactly
  - [x] T-1.14.15.2 Pipeline metadata leaks into prose — the summary only ever received section titles with item counts ("Key Facts, part 1 of 2: 1,128 items"), so counts were all it could summarise. It now reads a plain-text rendering of the written sections (`_section_text_digest`, 60K-token bound) and is told never to mention counts, parts or batches
  - [x] T-1.14.15.3 "well over 150 distinct videos" — the same verified facts block goes to every section prompt, not just the summary; pinned by a test that captures every compose prompt
  - [x] T-1.14.15.4 Judging harness — `backend/scripts/judge_report_sections.py` splits a report on `<h2>` and judges each section in full; no document-level cap remains
- **S-1.14.11 🟢 Reasoning-model response shape — shipped 2026-07-30.** Anthropic returns `[thinking_block, text_block]` instead of a string once the model actually thinks, so `response.content` yielded a list exactly on the hardest prompts. Latent in production since D-053 moved these sites to claude-sonnet-5. Fixed centrally via `llm_service.response_text()` at all 18 response-reading call sites, with regression tests.

- S-1.14.17 ⚪ A composed section can end mid-tag. Found 2026-10-19 by S-8.8.1's parser fixtures: the stored report for job `419e691d…` (the R1 measurement run) has a `<a href="https://www.youtube.com/watch?v=5` cut off where one section ends and the next begins, so every HTML parser folds the next section's `<h2>` and `<h3>` into that attribute value and two headings vanish from the outline, the iframe and the reader alike. Likely a completion-budget cut in `report_compose`; the compose step should detect an unbalanced tail (unterminated tag or attribute) and either retry the section or close it cleanly, and disclose it in the processing note like the other drops. Not a reader concern — the reader refuses to link the garbage href and nothing more can be recovered client-side.

- S-1.14.18 ⚪ Refresh the guidance that S-1.14.7 shows as stale or unmeasured. Filed 2026-10-19. Linked decision: [D-076](decisions.md#d-076--model-guidance-measured-means-the-use-cases-own-output-was-graded-verdicts-warn-never-block-2026-10-19). Several `measured` entries show users numbers taken on a tier the slot no longer runs, and some of the busiest slots are unmeasured. Each task below is a D-055-style replay on the reference job. A changed verdict is a registry edit plus a decision entry.
  - [ ] T-1.14.18.1 `qa_formulate_answer` at medium reasoning (graded at low in D-055; moved by D-056)
  - [ ] T-1.14.18.2 `search_plan_queries` on gpt-5.6-luna (graded on gpt-5.4-nano)
  - [ ] T-1.14.18.3 `knowledge_synthesize_report` on claude-sonnet-5 (graded against whatever produced the stored artifact)
  - [ ] T-1.14.18.4 Isolate `qa_refine_context` from the D-055 chain (it is now the only unmeasured step between retrieval and a graded answer)
  - [ ] T-1.14.18.5 `search_rank_and_curate` head-to-head on the persisted candidate pool (S-1.14.6). This makes the slot replayable for the first time
  - [ ] T-1.14.18.6 Luna on frame selection with captured alternative frames, so agreement can be replaced by graded quality (shares the run with T-1.18.5.5)

**Open questions**
- OQ-7: does the harness generalize to a scheduled regression check (re-run on every model-lineup shift), or stay a manual audit? Depends on S-1.14.6 landing.
- OQ-8: judging currently uses a single model family; is a multi-judge panel needed to control for self-preference bias when the challenger shares that family?
- OQ-16 (from S-1.14.7): should a model measured `unacceptable` for a use case be refused at `PUT /settings/llm`, or stay a warning? Today it is a warning everywhere. Refusing protects users from known-bad output; warning keeps the override knob a knob, and the verdicts carry small samples (n=2 on map batches).

### E-1.15 🟢 Output length policy (R4) — closed 2026-10-19

**Why it exists.** User requirement: output length should follow the corpus size bracket, with per-bracket defaults and an optional non-obstructive user override at submission time.
**Linked decision:** [D-064](decisions.md#d-064--output-length-corpus-brackets-with-an-optional-user-override-2026-07-31)

#### S-1.15.1 🟢 Report-side brackets + user override
**Shipped:** 2026-07-31
- [x] T-1.15.1.1 `output_length.py` — brackets, per-bracket defaults, user multipliers, prose guidance
- [x] T-1.15.1.2 `jobs.output_length` column + migration `e5f6a7b8c9d1`; `auto` normalised to NULL
- [x] T-1.15.1.3 Threaded through `JobCreate` -> `job_service` -> `run_report_agent` -> `compose_report`
- [x] T-1.15.1.4 "Report depth" selector on the submit form, defaults to Auto, only sent when chosen
- [x] T-1.15.1.5 10 tests incl. the ANTI-CAP invariant (deep-on-small < brief-on-large), unknown-value fallback, and that the `deep` brief forbids padding

#### S-1.15.2 🟢 Q&A length policy — agent side shipped 2026-07-31 (D-066); wired into the routers 2026-10-19 (PR [#227](https://github.com/khoks/VideoResearchPro/pull/227))
Q&A was corpus-blind: `formulate_answer` had a fixed 4,500-token budget and never received video/word counts. Deferred into the R3+R5 batch because all three rewrite the same Q&A prompt files.
**Scope-changed 2026-10-18: reopened.** This story was marked shipped with "R4 now complete", but a code audit found the policy unreachable in production. `run_qa_agent` accepts `corpus_statistics` / `output_length`, but its only caller (`routers/qa.py`) passes neither. `corpus_bracket({})` therefore returns `small`, so every job answer gets the small-corpus 1.25× budget and brief, and no publication span, even on the 200-video corpus. No test references `corpus_statistics`. See the [D-066 amendment](decisions.md#d-066--language-contract-temporal-awareness-and-corpus-aware-qa-length-2026-07-31).
- [x] T-1.15.2.1 Pass corpus statistics into the job and library Q&A agents — `corpus_stats_service` computes them from the approved (job) / visible (library) document set in the routers; both the sync and SSE job endpoints pass them
- [x] T-1.15.2.2 Same scale-plus-guidance policy on both answer sites via `qa_agent._answer_policy`; the library call's fixed `max_tokens=4500` is gone
- [x] T-1.15.2.3 Per-request `output_length` on `QARequest` and `LibraryQARequest`; the request override beats `job.output_length`, NULL everywhere lets the bracket decide
- [x] ~~T-1.15.2.4~~ moved to S-1.15.3 — the knowledge endpoint has no preference input, so "honours a preference" has nothing to test yet
- [x] T-1.15.2.5 `tests/test_routers/test_qa_length_policy.py` asserts at the production caller: the 200K-words-per-document fixture must classify `xlarge`, the rejected document must not count, the override must win, and the library set must follow visibility grants

#### S-1.15.3 ⚪ Length preference for knowledge synthesis
Knowledge synthesis already scales its budget with extraction size (S-1.14.8) but has no user preference input. Add an optional `output_length` to `POST /videos/{id}/extract-knowledge`, apply the D-064 multiplier and brief in `synthesize_report`, and test it at the router.

### E-1.16 🟡 Linguistic agnosticism with English output (R5)

**Why it exists.** Search should favour English, but topics like Hindu/Indian subjects legitimately surface Hindi sources. Every intermediate and final output must nonetheless be English, with quotes preserved in original script + transliteration + translation.
**Linked decisions:** [D-065](decisions.md#d-065--channel-subscriptions-become-per-tenant-transliteration-reversed-2026-07-31), [D-066](decisions.md#d-066--language-contract-temporal-awareness-and-corpus-aware-qa-length-2026-07-31), [D-080](decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19), [D-084](decisions.md#d-084--code-mixed-retrieval-embed-an-english-rendering-keep-the-original-as-the-stored-text-2026-10-19)

#### S-1.16.1 🟢 Language contract + script profiling — shipped 2026-07-31
- [x] T-1.16.1.1 `prompts/shared.py` — one definition of the English contract, quote rules and code-mixing note, injected per stage (map gets no quote rules: it emits JSON)
- [x] T-1.16.1.2 English contract added to report + job-Q&A prompts. The audit found NONE existed — a Hindi corpus produced a Devanagari report
- [x] T-1.16.1.3 `language_service.py` — Unicode script profiling, `switch_points`, `needs_translation`. Combining-mark bug fixed (Devanagari was undercounted ~40%, hiding language switches)
- [x] T-1.16.1.4 Anti-transliteration instruction reversed to the three-part form (D-065)
- [x] T-1.16.1.5 12 tests, including one asserting the romanised-Hinglish gap PERSISTS by design
- [x] T-1.16.1.6 Wire `language_service.describe_for_prompt` into the per-job prompt path — shipped 2026-10-19 (PR [#227](https://github.com/khoks/VideoResearchPro/pull/227)): per-batch profile into every map call, corpus-level profile (stored as `statistics.language_profile`) into every compose section and the summary. Empty for plain English, so the common case costs no tokens
- [ ] T-1.16.1.7 Persist the per-document language profile (`documents.language_mix`) so the per-video label stops being the only signal
  - Scope-changed 2026-10-19: S-1.16.2 now computes a per-document language profile at chunk time (`code_mixing_service.profile_transcript`) and carries it on every chunk as `code_mix_*` metadata, so prompts and retrieval no longer depend on the per-video label. What remains is a `documents` column holding the same profile, so the library, the job page and the reading room can show a source's language without reading Chroma, and older documents can be profiled without re-chunking
- [x] T-1.16.1.8 English-preference in `search_rank_and_curate` ranking — shipped 2026-10-19 (PR [#227](https://github.com/khoks/VideoResearchPro/pull/227)). A `LANGUAGE (a preference, never a filter)` block in the ranking prompt plus a `Script:` hint on titles not in Latin script (exact via `language_service.dominant_script`; the model infers the language). A test confirms a Devanagari-titled pick survives untouched

#### S-1.16.2 🟢 Proportion-driven rendering for code-mixed speech — implements [N-002](inventions.md#n-002--proportion-driven-rendering-policy-for-code-mixed-speech-2026-07-31)
The shipped script profiler is exact for script mixing and **blind to romanised code-mixing** — the user's own example ("...taaki baadme koi kasar koi zarra na reh jaye...") is entirely Latin and reads as English today. This story closes that gap.
**Shipped:** 2026-10-19 — PRs [#258](https://github.com/khoks/VideoResearchPro/pull/258), [#260](https://github.com/khoks/VideoResearchPro/pull/260), [#262](https://github.com/khoks/VideoResearchPro/pull/262), [#264](https://github.com/khoks/VideoResearchPro/pull/264), [#268](https://github.com/khoks/VideoResearchPro/pull/268), [#271](https://github.com/khoks/VideoResearchPro/pull/271), [#276](https://github.com/khoks/VideoResearchPro/pull/276); architecture/requirements docs in [#278](https://github.com/khoks/VideoResearchPro/pull/278). T-1.16.2.1–6 are done; T-1.16.2.7–9 are follow-ups that stay open, along with the user's two open questions in D-080 (what the 60% threshold rests on, and Devanagari words in Roman-mode quotes).
**Linked decisions:** [D-080](decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19), [D-084](decisions.md#d-084--code-mixed-retrieval-embed-an-english-rendering-keep-the-original-as-the-stored-text-2026-10-19)
- [x] T-1.16.2.1 Detect romanised non-English spans — shipped 2026-10-19 (PR [#258](https://github.com/khoks/VideoResearchPro/pull/258), [D-080](decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19)). Measured a lexicon + n-gram + Viterbi tagger against a `gpt-5.6-luna` pass on 300 hand-labelled units: real comments and captions from three Hinglish jobs, split DEV/TEST. On held-out romanised text the lexicon tagger is more precise at equal recall (token P 0.929 vs 0.803, R 0.890 vs 0.895), free, and runs at chunk time; the LLM is better only on English written in Devanagari (F1 0.965 vs 0.868) and stays registered as the reference `code_mixing_detect`. First finding: YouTube captions Hinglish speech in Devanagari, not romanised; romanised Hinglish arrives through comments and text sources. [Method and results](notes/2026-10-19-code-mixing-detection.md)
- [x] T-1.16.2.2 Estimate matrix vs embedded language per span — shipped 2026-10-19 (PR [#260](https://github.com/khoks/VideoResearchPro/pull/260), [D-080 addendum](decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19)). `analyse_span` returns `{hi_share, matrix, embedded}`; the matrix comes from a Matrix Language Frame vote of system morphemes (auxiliaries, light verbs, postpositions), so content words never decide it. Held-out mixed units: 0.952 vs 0.855 for word majority (LLM reference 0.968). Every baseline miss was Hindi grammar with mostly English words — 11% of all mixed units in the labelled set. A closed list of English function words in Devanagari (इज, टू, द) now tags English, so an English-matrix sentence in Devanagari is recognisable
- [x] T-1.16.2.3 Proportion thresholds as a RENDERING policy — shipped 2026-10-19 (PR [#262](https://github.com/khoks/VideoResearchPro/pull/262)). `rendering_mode(analysis)` → `native_script` (Hindi grammar, Hindi share ≥ `CODE_MIX_DOMINANT_SHARE` 0.6) / `plain_english` (English grammar, ≤ `CODE_MIX_BORROWING_MAX_SHARE` 0.2) / `roman` between; the matrix gates both ends. Defaults = centres of the DEV plateaus where detector and gold decisions agree; TEST agreement 0.970 Latin, 0.823 mixed. **Open question for the user** (D-080): what the 60% rests on — robustness favours 50% (Devanagari agreement 0.912 vs 0.824) while the tagger cannot see English nouns in Devanagari
- [x] T-1.16.2.4 Transcript-level "primary language of communication" — shipped 2026-10-19 (PR [#264](https://github.com/khoks/VideoResearchPro/pull/264)). `profile_transcript` → `{primary_language, native_script, hi_share, matrix_hi_share, quote_mode, flicker_unresolved}`; primary = the language framing ≥ half the speech; `resolve_quote_mode` lets a span decide only whether it is English, the source decides the script. Removes 25 script changes across 7 Devanagari Hinglish transcripts and 128 across 11 romanised comment threads. **Found and fixed:** only Devanagari/Arabic/Gurmukhi had counted as non-English — two Bengali and two Kannada transcripts in the library measured 0% non-English
- [x] T-1.16.2.5 Bidirectional split: analysis/extraction/ranking run on the English rendering; quotation retains original + transliteration + translation — shipped 2026-10-19 in two PRs
  - [x] Part A, quotation — shipped 2026-10-19 (PR [#268](https://github.com/khoks/VideoResearchPro/pull/268)). `code_mix_*` chunk metadata (none for English); `speech: <language> — <quote form>` on every non-English source header in the report map, job and library Q&A; map items carry `original` wording beside English `content`, compose attaches the source's `quote_form`; knowledge extraction gets a measured `SOURCE LANGUAGE` line. The report pipeline previously kept no original wording at all
  - [x] Part B, ranking on English — shipped 2026-10-19 (PR [#271](https://github.com/khoks/VideoResearchPro/pull/271), [D-084](decisions.md#d-084--code-mixed-retrieval-embed-an-english-rendering-keep-the-original-as-the-stored-text-2026-10-19)). Non-English chunks are embedded as an English rendering (`code_mixing_render_english`, metadata `text_en`) inside `chroma_service.insert_chunks`; stored text stays the original. Measured first: MRR 0.565 Devanagari / 0.402 romanised / 0.805 English rendering (55 independent questions, 132 real chunks). No backfill
- [x] T-1.16.2.6 Evaluate on real code-mixed transcripts before claiming it works — shipped 2026-10-19 (PR [#276](https://github.com/khoks/VideoResearchPro/pull/276)). Held-out sources only: 80 unseen comments (17/18 Hindi-bearing caught), the map stage before/after on a held-out lecture and two comment threads (**0 Hinglish passed through in six runs, with or without N-002**; originals kept 0 → 25 on the lecture), the production composer (8/8 three-part quotes), retrieval through the production renderer (MRR 0.554 → 0.762). The predicted failure happened at FETCH instead: 2 of 13 Hindi videos arrived as auto-dubbed tracks (S-1.11.11). Two fixes forced: a 3% presence floor so English-primary sources with real Hindi carry the profile, and per-item quote resolution in compose. [Section 11](notes/2026-10-19-code-mixing-detection.md#11-end-to-end-evaluation-on-held-out-sources-t-11626)
- [x] T-1.16.2.10 Verify kept `original` wording in code — fixed 2026-10-19 (PR [#294](https://github.com/khoks/VideoResearchPro/pull/294)). Regression from #268 found in R1 run 5: Hindi speakers quoted in Bengali script, strings in no transcript. Map originals are now checked against their own source with `quote_fidelity` (the run-6 gate's rule): mixed-script words, wrong script and unaligned wording are dropped, the English point kept, the drop disclosed. Drops exactly what the audit fails on run 5 (4/37 off, 12/51 on). Compose material no longer JSON-escapes non-Latin text. [Section 12](notes/2026-10-19-code-mixing-detection.md#12-regression-invented-original-wording-and-the-fix-2026-10-19)
- [ ] T-1.16.2.7 Native-speaker spot check of the labelled set (42 Hindi-bearing Latin units + 10 Devanagari units, ~30 min) before its numbers compare future detectors (D-080 open question 1)
- [ ] T-1.16.2.8 English CONTENT words in Devanagari (मशीन लर्निंग) — the tagger's measured blind spot; a hybrid (LLM on Devanagari) or a transliteration lexicon. Would also make a 50% dominant threshold unnecessary (D-080 open question 3)
- [ ] T-1.16.2.9 Measure a stronger multilingual embedder (E5/BGE-M3) on the D-084 pool before the library grows; it would replace or complement the English rendering
- [ ] T-1.16.2.11 Reconcile the native-script quote form with the quote-fidelity audit for ROMANISED Hindi-dominant sources. N-002 says such a source is quoted in Devanagari with its romanised original as the transliteration, but the R1 report-level audit (`audit_quote_fidelity.py --check`) looks every Devanagari run up in the corpus and would fail a re-scripted quote as `absent`. Either the audit learns that a Devanagari quote may stand for a romanised original (transliterate before matching), or the quote form keeps Roman for romanised sources. Raised 2026-10-19 with the fix in #294; not hit by job 419e691d, which has no romanised sources

### E-1.18 🟡 Visual understanding (R1)

**Scope.** Work out where something visually important happens in a video, capture stills there, describe them in transcript context, and merge the descriptions back as clearly-marked annotations that downstream prompts read as visual aid and never as speech.
**Linked decision:** [D-067](decisions.md#d-067--visual-understanding-separate-frames-table-marker-in-text-annotation-opt-in-per-job-2026-07-31)
**Roadmap:** [L6 — Visual understanding](feature-roadmap.md#l6--visual-understanding-)
**Architecture:** [Visual Agent](architecture.md#visual-agent-visual_agentpy) · **Requirement:** FR-19

#### S-1.18.1 🟢 Backend pipeline — select, capture, describe, merge — shipped 2026-07-31
- [x] T-1.18.1.1 `visual_frames` table + `jobs.visual_analysis` (migration `a7b8c9d1e2f3`)
- [x] T-1.18.1.2 `frame_service` — one yt-dlp download, N ffmpeg seeks; `worstvideo[height>=360]`; size cap, wall-clock budget, path-traversal guard
- [x] T-1.18.1.3 `visual_select_moments` + `visual_describe_frame` use cases; `VISION_USE_CASES`, `warn_if_not_vision_capable`, vision-aware smoke probe
- [x] T-1.18.1.4 `visual_agent` — select then capture then describe then persist, fail-soft at every level
- [x] T-1.18.1.5 `visual_service.annotate_segments` — pure merge, never mutates the shared transcript
- [x] T-1.18.1.6 Chunking: `atomic` segments exempt from sentence-splitting; visual presence aggregated rather than promoted by the dominance vote
- [x] T-1.18.1.7 `VISUAL_ANNOTATION_CONTRACT` into report map/section/summary, Q&A system prompt, knowledge extraction
- [x] T-1.18.1.8 Per-job frame budget with unused-allowance return and once-only exhaustion warning
- [x] T-1.18.1.9 Tests: 101 across annotation survival, budget accounting, vision routing, real-ffmpeg extraction, prompt-placeholder binding
- [ ] T-1.18.1.10 🔵 **Annotations never reach Chroma for a video that was already embedded** (found 2026-10-18 while designing the R1 measurement). `job_tasks.py` re-chunks a reused video through `_with_visuals` so the *report* sees the spans, but the RAG phase skips "already-embedded chunks", so Q&A retrieval over a previously ingested video never sees a `[VISUAL @ …]` span. Visual analysis therefore only helps Q&A on videos new to the library. Fix options: re-embed a document's chunks when frames exist and its stored chunks carry no visual markers, or store annotated chunks under distinct ids. Decide after S-1.18.3 says whether annotations help at all.
- [ ] T-1.18.1.11 🔵 **Knowledge extraction never sees annotations either.** `routers/knowledge.py` builds its transcript straight from `transcript_cache.segments_json`, so the `VISUAL_ANNOTATION_CONTRACT` injected into `knowledge_agent.py` describes spans the model will never receive. Same decision point as T-1.18.1.10.
- [x] T-1.18.1.12 🟢 *Fixed 2026-10-19: `{visual_annotations}` in `CHANNEL_MAP_PROMPT`, passed at the call site, and added to both parametrised lists plus a stubbed-LLM test that a span reaches the channel map prompt with the rule in force.* **The channel-report map prompt carries no visual contract** (found 2026-10-19 while landing S-1.18.6, PR [#234](https://github.com/khoks/VideoResearchPro/pull/234); [D-067](decisions.md#d-067--visual-understanding-separate-frames-table-marker-in-text-annotation-opt-in-per-job-2026-07-31) amended the same day). `_with_visuals` in `job_tasks.py` gates frame capture on `VISUAL_ENABLED`, `jobs.visual_analysis` and `source_type == "video"`, never on job type, so a channel job that opts in gets annotated chunks and `CHANNEL_MAP_PROMPT` formats them with no `{visual_annotations}` placeholder (T-1.18.1.7 never listed the channel-report family). Fix: placeholder + call-site kwarg in `report_agent.py`, and add `CHANNEL_MAP_PROMPT` to both parametrised lists in `tests/test_agents/test_prompt_contracts.py`.
- [x] T-1.18.1.13 🟢 *Fixed 2026-10-19, ahead of T-1.18.1.10 because the gap is live today for videos new to the library: both refine prompts take `REFINE_VISUAL_RULES` (the contract plus `VISUAL_SPAN_EXTRACT_RULE`, which tells the extractor to copy a span whole, marker included, and never fold it into a speech extract). Pinned by the call-site, rule-once and stubbed-LLM tests; mutation-checked.* **The two Q&A refine prompts carry no visual contract.** `REFINE_CONTEXT_PROMPT` and `LIBRARY_REFINE_CONTEXT_PROMPT` rewrite raw chunks into extracts before the answer prompt sees them, so a span can be paraphrased into plain prose before the answer-stage contract applies. Masked today by T-1.18.1.10 (spans rarely reach Chroma for an already-embedded video); land together with it.

#### S-1.18.2 🔵 Surfacing frames to the user
The backend produces frames and descriptions; nothing shows them yet. *Verified 2026-10-18: no frontend reference to `visual_analysis` and no frame-serving route.*
- [ ] T-1.18.2.1 Job-creation UI: the opt-in toggle, disabled when `/health` reports the `visual_analysis` feature down
- [ ] T-1.18.2.2 Serve frame images (auth + `document_visibility` check — a frame is as private as its document)
- [ ] T-1.18.2.3 Show the frame inline where a report or answer cites "on screen at mm:ss"
- [ ] T-1.18.2.4 On-demand per-document extraction endpoint, mirroring `/videos/{id}/extract-knowledge`

#### S-1.18.3 🟢 Measure whether visual annotations improve output — measured 2026-10-19
Protocol and results: [docs/notes/2026-10-18-r1-visual-measurement.md](notes/2026-10-18-r1-visual-measurement.md). Decision: [D-071](decisions.md#d-071--r1-verdict-annotations-win-on-substance-fail-on-attribution-and-cost-ui-deferred-2026-10-19). Sequenced before S-1.18.2 on 2026-10-18, by the user's instruction to test before building.
- [x] T-1.18.3.1 Same corpus, visual on vs off, blind-judged. Deterministic replay of job `419e691d` (11 videos, 120 frames) via `backend/scripts/replay_visual_ab.py`; three judge families via `backend/scripts/judge_pair.py`; 87-agent adversarial verification. **ON preferred on substance 3 of 3 (8.33 vs 7.00); 2 attribution errors in ON found by the sweep that every judge missed; ON 0 confirmed fabrications vs OFF 5.**
- [x] T-1.18.3.2 `informative` rate: 119/120 flagged; hand check of 7 frames found 6 exact, 1 minor misread at 360p, 1 borderline. No outright wrong description in the sample.
- [x] T-1.18.3.3 Cost: **$0.198 per video** at the gpt-5.5 defaults, double the pre-registered $0.10 ceiling → S-1.18.5.

#### S-1.18.6 🟢 Fix the speaker-attribution gap in the visual contract, then re-run — rule and tests landed 2026-10-19
Both confirmed errors bundle a screen-only detail into a sentence credited to a named speaker. `VISUAL_ANNOTATION_CONTRACT` forbade reading spans as speech but said nothing about mixing the two inside one attributed clause. **Sequenced after PR #227**, which rewrote `prompts/shared.py`.
**Rule landed 2026-10-19 (PR [#234](https://github.com/khoks/VideoResearchPro/pull/234)).** One `ATTRIBUTION BOUNDARY` bullet inside `VISUAL_ANNOTATION_CONTRACT`: a sentence credited to a speaker ("X says / notes / explains", quoted speech, "— Name (mm:ss)") may contain only what that speaker said; a detail that exists only in an annotation goes in a separate clause marked as shown on screen; a spoken figure noted as "also visible on screen" stays correct, since the sweep judged that pattern right every time. Stated once in `prompts/shared.py`, so the six transcript-reading prompts (report map / section / summary, both Q&A system prompts, knowledge extraction) inherit it with no call-site change; the D-066 language fragments and the D-072 temporal fragments are untouched. Still open: T-1.18.6.3, the protocol re-run.
- [x] T-1.18.6.1 Contract rule: a sentence attributed to a speaker ("X says", "— Name (mm:ss)") may contain only what was spoken; screen-only details go in a separate clause marked as shown — 2026-10-19, PR [#234](https://github.com/khoks/VideoResearchPro/pull/234)
- [x] T-1.18.6.2 Pin it with a prompt-level test on a synthetic transcript where the span and the speech disagree — 2026-10-19, PR [#234](https://github.com/khoks/VideoResearchPro/pull/234). `tests/test_agents/test_prompt_contracts.py`: the rule appears exactly once in each of the six composed prompts; and a two-segment transcript whose span alone carries "shaded 95 percent confidence band" runs through `annotate_segments` → `chunk_transcript` → `map_chunks` with a stubbed LLM, asserting the prompt the model receives holds the speech, the span intact, the rule, and the screen-only detail nowhere outside the span
- [x] T-1.18.6.3 Re-run the S-1.18.3 protocol unchanged; the rule needs zero confirmed attribution errors after the sweep. **Ran 2026-10-19: failed.** Run 2 (Flash-Lite descriptions) had 1 confirmed error and won 1/3 judges; run 3 (gpt-5.5 descriptions) won 3/3 at matched length but had 2 confirmed errors, now in the opposite direction (spoken details presented as on screen). The rule moved the error rather than removing it. See [D-075](decisions.md#d-075--r1-after-three-runs-the-modality-boundary-needs-provenance-not-prompt-rules-2026-10-19) and the protocol note.

#### S-1.18.7 🟢 Deterministic modality check — measured 2026-10-19, not shipped
`backend/scripts/modality_check.py` checks a report's "on screen" claims and speaker-attributed details against timestamped speech and frame descriptions. `eval_modality_check.py` scores it against the verified labels from runs 1–3. Best setting: **2 of 5 confirmed errors caught, about 8 other flags per report**, mostly false positives. Three causes: four of the eleven videos are spoken in Hindi or Bengali, ASR renders identifiers differently from the screen, and the composer cites every sentence "— Source (mm:ss)". It stays a research tool; [D-075](decisions.md#d-075--r1-after-three-runs-the-modality-boundary-needs-provenance-not-prompt-rules-2026-10-19) explains why it is not a gate.

#### S-1.18.8 🟡 Modality provenance through the map/reduce pipeline — T-1 to T-3 shipped 2026-10-19 (PR [#277](https://github.com/khoks/VideoResearchPro/pull/277)); T-4 open
Decided by [D-075](decisions.md#d-075--r1-after-three-runs-the-modality-boundary-needs-provenance-not-prompt-rules-2026-10-19): the composer currently infers whether a fact was said or shown from interleaved text, and prompt rules have not stopped it mixing the two. **Sequenced after S-1.14.6** (persisted map items make the labels auditable) and after the R5 session's prompt changes.
*Evidence added 2026-10-19:* four of the five confirmed attribution errors after the S-1.18.6 rule are in the one Bengali-language video (1 of 11). The composer misjudges modality where it cannot read the speech; the map stage reads each chunk's native speech, so that is where the label must be fixed. This ties S-1.18.8 to R5 (E-1.16).
- [x] T-1.18.8.1 Map stage: every extracted item carries `modality: said | shown | both`, decided from whether its evidence sits in speech, in a `[VISUAL @]` span, or both. The rule (`MODALITY_FIELD_RULE`, `prompts/shared.py`) tells the model to read the speech in its own language — a figure spoken in Bengali, native digits included, is `said`. Code then fixes what code can know: an item from a source with no visual annotation is `said` whatever the model wrote (the model's value kept as `modality_model`); a missing or unusable label is `unknown`, never a guess. Per-run counts land in `processing_notes.map_modality`
- [x] T-1.18.8.2 Reduce preserves the label (D-056); when the same item arrives twice with different evidence (overlapping chunks), the union is `both`. Compose renders each item as `[SAID]` / `[SHOWN]` / `[SAID+SHOWN]` / `[UNLABELLED]` with `MODALITY_TAGS_NOTE` telling the composer to attribute from the tag and never print it. Tags appear only when the corpus has a shown or both item, so a corpus without visual evidence pays nothing
- [x] T-1.18.8.3 Converse rule added once to `VISUAL_ANNOTATION_CONTRACT`: "on screen" only where an annotation shows it or the item is tagged shown; a spoken detail is never "on screen", in any language. A ride-along, not relied on
- Tests: `test_modality_provenance.py` (15, stub LLMs) — a Bengali chunk with a version number spoken in native digits and a ValueError visible only on screen, labelled said / shown / both at map; forced to said without frames; synonyms and missing labels; reduce keeps and unions labels; compose carries the tags, the note, and no raw keys; no tags without shown items; prompt bindings; labels in the persisted S-1.14.6 record and the audit. Mutation-checked: removing map labelling, the tags, or the union each fails a test
- [ ] T-1.18.8.4 Check the composed report against item provenance (deterministic, now that the provenance exists), then re-run the S-1.18.3 protocol with the multilingual-verification rule from D-075
  - *Run 5, 2026-10-19:* **0 confirmed attribution errors** in the annotated report, the first run of five. Substance judging was confounded by an R5 regression (#268's map-stage `original` quotes, fabricated in the wrong script) and by a Gemini Pro quota fallback. Run 6 follows the R5 fix. See the protocol note.

#### S-1.18.5 🔵 Re-tier the two vision use cases, then re-measure cost
Filed 2026-10-19 from the S-1.18.3 run: at the registry defaults (`visual_select_moments` gpt-5.5 medium, `visual_describe_frame` gpt-5.5 low) the estimated vision spend was **$0.198 per video** (11 videos, 120 frames at 640×360; selection ≈ 75K input tokens, description ≈ 159K input tokens), double the $0.10 ceiling the protocol fixed in advance. Both cheaper candidates are already on `VISION_CAPABLE_MODELS`.
- [x] T-1.18.5.1 `visual_select_moments` **stays on gpt-5.5, reasoning medium → low** (measured 2026-10-19, `scripts/retier_vision.py`). Agreement with the stored picks within 20 s: gpt-5.5 medium against itself 85% (the noise floor), gpt-5.5 low 76%, gpt-5.5 off 76%, gpt-5.6-luna 59%, gpt-5.4-mini 24%, gemini-3.1-flash-lite 23%. Real cost per video: medium $0.097, low $0.067, off $0.064, luna $0.002. No cheaper model is close; low keeps the model and most of its picks.
- [x] T-1.18.5.2 `visual_describe_frame` → **gemini-3.1-flash-lite** ([D-073](decisions.md#d-073--frame-description-moves-to-gemini-31-flash-lite-on-image-grounded-grading-selection-stays-on-gpt-55-2026-10-19)). Same 120 frames re-described by each model; 33 frames × 2 graders looked at the image, blind: gpt-5.5 mean 4.52/5, best in 54 of 66, 3 unusable; flash-lite 4.21, 5 unusable; luna 3.97, **22 unusable** (misread dates, axis values, mistook a code cell for output). Real cost $0.133 → $0.008 per video.
- [x] T-1.18.5.3 Measured total for the visual pass: **$0.075 per video** (select $0.067 + describe $0.008) against $0.230 before, under the $0.10 ceiling; pinned by `tests/test_services/test_vision_tier.py` at the measured token counts. The first pass of these numbers divided by 12 approved videos instead of the 11 that produced calls and understated everything by 8%; the test caught it.
- [ ] T-1.18.5.4 Revisit the S-1.18.2 UI decision after S-1.18.6's re-run (T-1.18.6.3) passes the attribution criterion with these tiers. *2026-10-19: the re-run failed (D-075); now waits on S-1.18.8.*
- [x] T-1.18.5.6 🟢 **Describer chosen at report level, not per frame** — *closed 2026-10-19: the user chose gpt-5.5 (D-081), visual pass about $0.20 per video; ceiling pinned by `test_vision_tier.py`.* (D-075). Flash-Lite graded only 0.3 below gpt-5.5 per frame, yet the report-level benefit disappeared (run 2: 1/3 vs run 3: 3/3). Grade three mid-priced describers per frame (gpt-5.4-mini $0.018/video measured, claude-haiku-4-5, gemini-3.5-flash), then confirm the best one with a report-level run before changing the D-073 default. **Measured 2026-10-19:** per frame, gemini-3.5-flash 4.70 (0/62 unusable) > gpt-5.5 4.54 > gpt-5.4-mini 4.37 >> claude-haiku-4-5 2.39 (55/62 unusable). Report level (run 4, Flash descriptions): 2/3 judges, substance level, 2 attribution errors. The report-level ranking follows how often graders picked a description as most useful, not its accuracy. The default awaits the user's spend-vs-quality call in [D-081](decisions.md#d-081--frame-describer-default-spend-against-report-level-quality-2026-10-19).
- [ ] T-1.18.5.5 🔵 Frame resolution: every model misread small text at 640×360 (`worstvideo[height>=360]`); graders had to upscale to read labels. Try `height>=720` on the same 11 videos, re-grade, and weigh download size (D-051 bot-wall traffic) against the accuracy gain.

#### S-1.18.4 🔵 Beyond YouTube
- [ ] T-1.18.4.1 PDFs: page images are already available without any download
- [ ] T-1.18.4.2 Articles: figures and charts referenced by the text

### E-1.17 🟢 Temporal / era awareness (R3) — closed 2026-10-19

**Why it exists.** A corpus spans time. A claim made in 2024 is not the same claim in 2026; relevance and meaning shift with publication date.
**Linked decisions:** [D-066](decisions.md#d-066--language-contract-temporal-awareness-and-corpus-aware-qa-length-2026-07-31), [D-072](decisions.md#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19)

**Closed 2026-10-19 (PR [#227](https://github.com/khoks/VideoResearchPro/pull/227)).** Both halves of R3 now exist: publication date (S-1.17.1, 2026-07-31) and the era a source DISCUSSES (S-1.17.2), in knowledge extraction, search ranking, Q&A and the report. Chunks embedded before 2026-10-19 carry no era and no numeric publish fields; they read as unknown by design (no backfill — D-072).

**SCOPE CORRECTION 2026-07-31.** The requirement has TWO dimensions and only one was built. The user's words: *"the time when the videos were posted, AND which era/timeperiod they are talking about"*, affecting *"knowledge extraction, search ranking, qna, reporting"*. Publication date is done. **The era a video DISCUSSES is not**, and **search ranking received no temporal signal at all**. E-1.17 stays 🟡 until S-1.17.2 lands; describing R3 as "core shipped" was an overstatement.

**Correction 2026-10-18.** The claim above that "search ranking received no temporal signal at all" was itself wrong. Since PR #2 (2026-04-19), the ranking prompt has shown each candidate's publish date with a generic hint: "more recent is usually better unless the topic calls for foundational content". What ranking still lacks is the discussed era and a deliberate per-topic recency decision. Separately, the Q&A piece below (T-1.17.1.4) turned out to be unwired; see S-1.15.2.

#### S-1.17.1 🟢 Publication date reaches the prompts — shipped 2026-07-31; last three tasks 2026-10-19
- [x] T-1.17.1.1 `compute_statistics` derives earliest/latest/median publish date + per-year counts
- [x] T-1.17.1.2 Map chunk headers carry `published <date>`
- [x] T-1.17.1.3 `TEMPORAL_AWARENESS` / `TEMPORAL_EXTRACTION_NOTE` fragments; guardrail conflict resolved by SUPPLYING verified dates rather than relaxing D-062's anti-invention rule
- [x] T-1.17.1.4 Q&A receives publication span and weights recency for time-sensitive questions — live since 2026-10-19, when the routers started passing corpus statistics (S-1.15.2). The CORPUS note also carries the discussed-era span
- [x] T-1.17.1.5 Date into the Q&A allowed-sources list — `- "Title" by Channel | published 2025-03-12 | discusses 2019–2021 (retrospective)`, for job and library Q&A; the raw-context headers the refiner reads carry the same, and the system prompts say the suffix is never part of a citation. Pinned against the citation sanitizer
- [x] T-1.17.1.6 `published_ts` / `published_year` (ints) in chunk metadata, omitted when the date is unknown so a `$gte` filter excludes undated chunks rather than matching 1970. Pre-existing chunks are not backfilled
- [x] ~~T-1.17.1.7 Optional `temporal_scope_extract`~~ — promoted out of "optional" into S-1.17.2; it is half the requirement, not a nice-to-have

#### S-1.17.2 🟢 The era a source DISCUSSES, and temporal signal in ranking — shipped 2026-10-19 (PR [#227](https://github.com/khoks/VideoResearchPro/pull/227))
A 2026 video about a 2019 paper is a 2026 source about a 2019 event. Linked decision: [D-072](decisions.md#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19).
- [x] T-1.17.2.1 `temporal_scope_extract` use case (registry entry 23; `gpt-5.6-luna`, reasoning OFF, 400-token cap). Prompt in `prompts/temporal_prompts.py`; title + description + publish date + three sampled transcript windows → `{era_start, era_end, era_confidence, is_retrospective, era_label}`, integer years, negative = BCE. `temporal_service.parse_era_payload` tolerates fences, swaps reversed bounds, forces zero confidence on null years
- [x] T-1.17.2.2 Persisted as `documents.discussed_era_json` (migration `b1a2c3d4e5f8`), extracted by `job_tasks._ensure_era` before every `chunk_transcript` site in both ingest loops (a source-level test counts the sites), once per document and reused. Flattened into chunk metadata as `era_start` / `era_end` / `era_confidence` / `is_retrospective`, omitted when unknown. `TEMPORAL_SCOPE_ENABLED` kill switch
- [x] T-1.17.2.3 Temporal signal in ranking — the planner now emits a `temporal_profile` (`recency_weight` dominant / secondary / minimal, `target_era`, rationale) decided ONCE per topic; the ranking prompt receives the matching guidance block, each candidate's `Era:` when the library has dated it, and the explicit rule that no candidate is excluded for its date. Default when the planner is silent: secondary (relevance leads, date breaks ties) — the strength of "dominant" is the open design question recorded in D-072
- [x] T-1.17.2.4 Knowledge extraction anchors relative time to the publish date (`_temporal_note` in both knowledge prompts; "keep relative phrases verbatim" when the date is unknown); synthesis writes time-sensitive claims "as of <date>"
- [x] T-1.17.2.5 Report: `TEMPORAL_AWARENESS` now distinguishes "true AS OF <date>" from "true now" and requires supersession to be named; map headers carry `discusses <era>`; the corpus-facts block carries the discussed-era span
- [x] T-1.17.2.6 Q&A: the CORPUS note tells the answer model to weight recency for time-sensitive questions, the discussed era for period questions, and to say so with dates when sources disagree along a time axis; the refiner is told to keep dates with extracts so the answer step can see the axis

#### S-1.17.3 ⚪ Backfill era + numeric publish fields into pre-R3 Chroma chunks
Deferred by [D-072](decisions.md#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19): chunks embedded before 2026-10-19 carry no `era_*` / `published_ts` metadata and read as unknown. A document gains its era the next time a job re-chunks it, but its OLD chunks in Chroma do not. Worth doing only once something reads the fields at retrieval time (recency-weighted retrieval, era filters). Chroma supports metadata updates without re-embedding, so this is a metadata-only pass, not a re-index.
- [ ] T-1.17.3.1 Script: for every document with `discussed_era_json` or `published_at`, update the metadata of its existing chunks in `videoresearchpro_global` (no re-embedding)
- [ ] T-1.17.3.2 Idempotent and resumable; logs how many chunks gained each field

#### S-1.17.4 ⚪ Measure the temporal ranking signal
The planner's `temporal_profile` and the per-candidate `Era:` line are reasoned preferences, not measured ones. Replay the D-057 reference pool (S-1.14.6 persisted the rejected candidates) with and without the temporal guidance and judge the selections blind, the E-1.14 way. Also decides OQ-9.
- [ ] T-1.17.4.1 Re-rank the persisted candidate pool of job `0d4db8c3` with `temporal_profile` forced to each of `dominant` / `secondary` / `minimal`; diff the selections
- [ ] T-1.17.4.2 Blind-judge the three selections for topical fit and vintage balance

**Open questions**
- OQ-9: how strongly should `dominant` recency outweigh relevance for a fast-moving topic? Today: "strongly prefer the most recent among on-topic candidates; keep an older one only when clearly foundational". Stricter behaves like a filter; looser collapses into `secondary`. Raised in [D-072](decisions.md#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19); for the user to decide, ideally after S-1.17.4.

## I-2 🟢 Brand & visual identity rollout

**Closed 2026-05-03.** All 6 epics now 🟢: E-2.1 tokens layer, E-2.2 primitives library, E-2.3 page migration, E-2.4 sidebar nav (all shipped earlier — verified 2026-04-26), E-2.5 marketing landing page (PR [#136](https://github.com/khoks/VideoResearchPro/pull/136), 2026-05-03), E-2.6 code identifier rename (this session — runbook in `docs/migration-code-identifiers.md` covers the operator-coordinated data-bearing renames).

**Status reconciliation 2026-04-26 (historical).** A backlog audit on 2026-04-26 revealed I-2 was substantially shipped — 4 of 6 epics were already 🟢. The earlier characterization in feature-roadmap.md ("documented but zero code shifted") was inaccurate; the warm-editorial migration largely landed in earlier sessions and was not reflected here. After E-2.5 + E-2.6 closed on 2026-05-03, I-2 is fully closed.

**Why it exists.** Switch the running app from generic-AI-SaaS aesthetics (purple-blue gradient, default sans) to warm-editorial Pratidhvani identity (paper background, oxblood / forest-teal / vintage gold, Fraunces / Source Serif). Visual identity should match the personal-library / research-journal vision.
**North-star doc:** [branding.md](branding.md) · [ui-design.md](ui-design.md)
**Decision links:** [D-001](decisions.md#d-001--rebrand-to-pratidhvani-प्रतिध्वनि-2026-04-24), [D-002](decisions.md#d-002--warm-editorial-visual-identity-2026-04-24)

### E-2.1 🟢 Tokens layer (`frontend/src/theme.ts`)

**Shipped** in an earlier session (verified live on master 2026-04-26). `frontend/src/theme.ts` exports `colors` (warm-editorial light + dark), `fonts` (Fraunces / Source Serif / Inter / Tiro Devanagari / JetBrains Mono), `fontSize` (modular scale), `lineHeight`, `fontWeight`, `space` (4px scale), `radius`, `shadow`, `motion`, `z`, `breakpoints`, `measure`. Helpers `pickColor(token, mode)`, `transitionAll(d)`, `focusRing(mode)`. CSS-var mirror in `frontend/src/index.css` (`--color-*` etc.) so native pseudo-elements (`::placeholder`, scrollbar) share the palette.

### E-2.2 🟢 Primitives library

**Shipped** core set (verified live on master 2026-04-26). `frontend/src/components/primitives/`: `Button`, `Card`, `Input` / `Textarea` / `Select`, `FormField`, `Badge` + `StatusPill`, `Modal`, `Spinner` + `Skeleton`, `EmptyState`. All consume tokens via `useColors()` hook. The original feature-roadmap "primitives" list also called for `Tooltip` / `Tabs` / `Toast` / `IconButton`; those are not yet in `primitives/index.ts` (Toast lives in `components/common/Toast.tsx`; Tooltip / Tabs / IconButton not yet built).

**Remaining (low-priority within E-2.2).**
- [ ] T-2.2.1 `Tooltip` primitive (currently inline)
- [ ] T-2.2.2 `Tabs` primitive (currently inline where needed)
- [ ] T-2.2.3 `IconButton` primitive (currently `<Button>` with icon-only content)
- [ ] T-2.2.4 Move `Toast` from `components/common/` → `primitives/` for index parity

### E-2.3 🟢 Page-by-page migration

**Shipped** for all 10 pages (verified live on master 2026-04-26). All pages import from `../theme` and consume primitives from `../components/primitives`. Pages migrated: `LoginPage`, `RegisterPage`, `JobsListPage`, `JobDetailPage`, `LibraryPage`, `LibraryQAPage`, `SubmitJobPage`, `ExportsPage`, `QAHistoryChatPage`, `VideoKnowledgePage`. 26 files in total import from `theme`.

### E-2.4 🟢 Sidebar nav (replace top tabs)

**Shipped** (verified live on master 2026-04-26). `AppLayout.tsx` now renders an editorial sidebar (240px desktop, drawer on mobile<960px) with the Devanagari + Latin brand lockup at the top and user chrome (email / theme toggle / logout) at the bottom. NavContent groups Submit / Jobs / Library / Library Q&A / Q&A History / Exports.

### E-2.5 🟢 Marketing landing page (warm-editorial)

**Scope.** Static landing page under `marketing/` describing the curated-personal-wiki pitch, screenshots, install instructions, SaaS waitlist. Folder does not yet exist (verified 2026-04-26 — no `marketing/` directory in repo).
**Shipped:** 2026-05-03 — PR [#136](https://github.com/khoks/VideoResearchPro/pull/136). *Status reconciled 2026-10-18. The I-2 closure note already recorded this, but this heading and its tasks were never flipped. `marketing/src/pages/index.astro` has the hero, the Wikipedia contrast, how-it-works, install, waitlist and footer sections.*

**Tasks** (initial)
- [x] T-2.5.1 Astro project scaffold under `marketing/` *(shipped 2026-04-28 — PR [#98](https://github.com/khoks/VideoResearchPro/pull/98); Astro ^5.0.0 chosen per [D-022](decisions.md#d-022--astro-for-the-marketing-landing-page-2026-04-28). `package.json` / `astro.config.mjs` / `tsconfig.json` (extends `astro/tsconfigs/strict`) / `.gitignore` / `README.md` + `BaseLayout.astro` mirroring `frontend/src/theme.ts` tokens + `index.astro` placeholder hero with brand lockup)*
- [x] T-2.5.2 Hero with the personal-wiki pitch + tagline ("Your sources, echoed back" or similar from branding.md).
- [x] T-2.5.3 "How it differs from Wikipedia" section (curation thesis).
- [x] T-2.5.4 Source-types matrix (videos / podcasts / articles / etc.) reflecting current support.
- [x] T-2.5.5 "How it works" walkthrough (search → approve → embed → ask).
- [x] T-2.5.6 Install instructions (open-source self-host).
- [x] T-2.5.7 SaaS waitlist hook (future-only — disabled call-to-action today).
- [x] T-2.5.8 Footer: GitHub, docs, license.

### E-2.6 🟢 Code identifier rename pass

**Closed 2026-05-03.** User-facing brand copy migrated in earlier sessions (PRs #97, brand work). The data-bearing identifiers (`CHROMA_GLOBAL_COLLECTION_NAME`, `DATABASE_URL`) are operator-coordinated migrations — not codebase changes — with a safe-execution runbook now landed at [`docs/migration-code-identifiers.md`](migration-code-identifiers.md). The GitHub repo rename (T-2.6.4) is genuinely outside-codebase and listed in the runbook for completeness. All codebase-side work is done.

**Linked decision:** [D-032 — Operator-coordinated runbook (vs automatic startup migration) for data-bearing identifier renames](decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03)

**Tasks**
- [x] T-2.6.1 `CHROMA_GLOBAL_COLLECTION_NAME` default `videoresearchpro_global` → `pratidhvani_global`. *Operator-coordinated; safe-execution procedure in [migration-code-identifiers.md §A](migration-code-identifiers.md#a--migrating-the-chroma-collection). The default itself stays at `videoresearchpro_global` so existing self-hosters who pull master don't get surprise data motion; operators flip the env var after running the backfill script described in the runbook.*
- [x] T-2.6.2 `DATABASE_URL` default `sqlite:///./data/videoresearchpro.db` → `pratidhvani.db`. *Same pattern — runbook in [migration-code-identifiers.md §B](migration-code-identifiers.md#b--migrating-the-sqlite-database-file). File-rename + env-var flip, fully reversible.*
- [x] T-2.6.3 Backend package paths — already neutral (`app.*`); no rename needed. ✅ *Confirmed during the 2026-04-26 audit.*
- [x] T-2.6.4 GitHub repo rename `khoks/VideoResearchPro` → `khoks/pratidhvani` (or similar). *Outside-codebase action; GitHub auto-redirects so old PR / issue URLs keep working. Listed in [migration-code-identifiers.md §C](migration-code-identifiers.md#c--optional-github-repo-rename) for completeness.*
- [x] T-2.6.5 Audit + fix any remaining strings in tests, scripts, docstrings that aren't grandfathered env-var references. *(shipped 2026-04-28 — PR [#97](https://github.com/khoks/VideoResearchPro/pull/97); 9 files updated: `APP_NAME` default, `/api/v1/health` response, startup log, `POST /restart` docstring, two service module docstrings, env template header, paired test, restart-services.ps1. Intentional non-changes for future migration tasks documented in PR body)*
- [x] T-2.6.6 Migration runbook covering data preservation for self-hosters running the legacy names. *(shipped 2026-05-03 — `docs/migration-code-identifiers.md`. Three sections — Chroma collection rename, SQLite file rename, optional GitHub repo rename — with pre-flight checklist, idempotent backfill script, post-migration verification, and rollback procedure for each. Promise: never destroys data, every step is reversible.)*

**Sequencing rationale (closed).** Brand copy moved immediately in PR #97 because it's pure cosmetic with no data-motion risk. Data-bearing identifier renames stayed deferred because they're production-data-mutating and need operator coordination. The runbook closes that gap by giving operators a safe-execution checklist; the codebase keeps the legacy defaults so pulling master never causes surprise motion. Operators who want the new names follow the runbook on their own schedule.

### E-2.7 🟢 Research-flow UX polish (from 200-video test)

**Filed 2026-07-22** from the same 200-video deep-research test that produced [E-1.11](#e-111-transcript-pipeline-resilience-at-scale) (job `0d4db8c3`). UX findings at 200-row scale; all stories shipping in the same branch's PR. Linked decision: [D-051](decisions.md#d-051--transcript-pipeline-resilience-bundle-circuit-breaker--segmented-whisper--yt-dlp-client-fallback-2026-07-22) (context only — the UX work carries no ADR of its own).

#### S-2.7.1 🟢 Approval-list UX at scale

**Scope.** Default-select-all on the approval list (was 0/200 selected while the helper copy said "Deselect any candidates you don't want" — contradictory); copy made consistent with the default; `content-visibility` virtualization so 200+ row lists stay responsive (500 would strain the current flat render).

#### S-2.7.2 🟢 Q&A streaming

**Scope.** SSE stage events on the Q&A path — `retrieving` / `refining` / `formulating` / `extracting_references` — so the user sees pipeline progress instead of a spinner. Token-level answer streaming ⚪ deferred.

#### S-2.7.3 🟢 Per-tier `num_videos` ceilings

**Scope.** Per-tier ceilings for topic-job `num_videos`: free 100 / pro 250 / studio 500. Schema absolute cap raised to 500 per PR [#188](https://github.com/khoks/VideoResearchPro/pull/188) (was `le=100` backend + `max={100}` frontend, which silently clamped a 200-video request).

### E-2.8 ⚪ Brand asset remainder (branding.md §8)

**Filed 2026-10-19.** S-8.12.2 shipped part of the [asset inventory](branding.md#8-asset-inventory) — an interim rendering of the §3 echo mark as `logo-mark.svg`, the favicon, the app icons and the Apple touch icon, plus the manifest and the page title ([D-087](decisions.md#d-087--mobile-reading-and-install-a-reading-toolbar-below-1200-px-a-docked-composer-lifted-by-visualviewport-hermetic-device-tests-a-manifest-without-a-service-worker-2026-10-19)). What remains is design work, so it is proposed rather than accepted.
- [ ] T-2.8.1 A designed glyph mark to replace the interim echo-mark rendering (keep `frontend/public/logo-mark.svg` as the master; `npm run icons` re-renders every PNG from it)
- [ ] T-2.8.2 Full lockup `logo-full.svg` (Devanagari + Latin wordmark, outlined so it does not depend on installed fonts)
- [ ] T-2.8.3 Open Graph image `og.png` (1200 × 630, masthead lockup over the paper background); needed before M11 public sharing produces links worth previewing
- [ ] T-2.8.4 Marketing-side logo set (`marketing/public/logo-*.svg`)

---

## I-3 🟡 Echo (personal-brain L3)

**Why it exists.** Long-horizon north star — an app that ingests the user's likes / WhatsApp / Google Keep / quotes / activity / location / interests over time and develops a personality matching them. Eventually capable of "speaking on the user's behalf".
**North-star doc:** [personal-brain.md](personal-brain.md) · [vision.md](vision.md) Ring 3 · **Plan:** [`docs/plans/l3-echo-personal-brain.md`](plans/l3-echo-personal-brain.md) · **Sequence:** [`docs/plans/build-order.md`](plans/build-order.md)
**Decision links:** [D-003](decisions.md#d-003--echo--personal-brain-as-the-long-horizon-north-star-2026-04-24), [D-049](decisions.md#d-049--echo-cold-start-readiness-threshold-shipped-triple-is-v1-personal-brainmd-sub-table-is-forward-looking-spec-resolves-oq-6-2026-05-06), [D-069](decisions.md#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19)
**Status:** 🟡 foundation shipped 2026-05-05; **frontend Echo surface shipped 2026-10-19** (PR [#224](https://github.com/khoks/VideoResearchPro/pull/224)). Schema + service-layer + cold-start gate + REST surface all live, and `/echo` now exercises all of it: a readiness meter ("you're N% there", the mean of the three gates with each gate shown against its threshold, and an honest line that the sources gate cannot be met while the connector registry is empty), a context browser grouped by the 10 kinds with add / edit (edit = upsert on the same `(kind, key)`; labels cannot be renamed) / forget, a sources-on-record list with revoke (`DELETE /echo/sources/{source}`, confirm first), and an empty-state connectors card. Pure logic in `frontend/src/utils/echoReadiness.ts`. Concrete activity-stream connectors (YouTube watch / Spotify / email / etc.) and the "speak as me" agent are E-3.2 / E-3.4 follow-ups. Per [D-044](decisions.md#d-044--foundation-first-then-concrete-implementations-deferred-for-i-3--i-6-2026-05-05), the foundation ships **without** any concrete connector — the registry is empty in v1 — so each connector PR is independently scoped. Known edge: `DELETE /echo/context/{kind}/{key}` takes the key as a path segment, so a key containing `/` cannot be deleted; the form refuses such labels. Linked decision: [D-069](decisions.md#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19).

**Planned 2026-10-18.** The roadmap's five components now map onto epics in the roadmap's own order: constant-stream intake (new E-3.7) → manual personality signals and retrieval (E-3.3) → activity connectors (E-3.2) → "speak as me" plus the always-evokable surface (E-3.4, new E-3.8) → opt-in fine-tuning (new E-3.9), with the privacy model as its own epic (new E-3.10). Findings from the code audit that change the plan:
- The foundation stores everything in `personal_context(user_id, kind, key, value, source, confidence, captured_at, expires_at)` with a unique `(user_id, kind, key)`. That shape fits *facts*; it cannot hold *events* (many rows per kind) or *shares*. The `activity_events`, `shares_inbox` and `voice_signals` tables from `personal-brain.md` do not exist and are not derivable from the foundation; each lands with its epic.
- `personal_context` carries `user_id` only, not the `tenant_id` + `user_id` pair `personal-brain.md` §"What this means for today's PRs" asks for. Today `tenant_id == user.id` everywhere (E-5.1), so nothing breaks; the pair is added when the first new Echo table lands (S-3.7.1) and backfilled on `personal_context` in the same revision.
- No Chroma collection exists for personal context; `is_ready` counts rows, sources and one `personality_trait` only (the D-049 v1 triple).
- No `backend/app/connectors/` package exists; the `EchoConnector` Protocol lives in `echo_service.py` with `authorize_url / revoke / sync / supported_kinds`, which is narrower than the `personal-brain.md` contract (no `initial_backfill`, `incremental_sync`, `consent_disclosure`, `privacy_weight`). S-3.2.1 widens it before the first connector.
- **YouTube watch history is not obtainable through the YouTube Data API**; only liked videos, subscriptions and playlists are. Watch history arrives only as a Google Takeout export. T-3.2.1 is therefore split into an API connector (likes, subscriptions) and a Takeout importer (S-3.7.5).
- **Several connectors in the roadmap list are export-file imports, not APIs.** Spotify's 2026 developer-mode rules (Premium owner, five allow-listed users, 250k-MAU business for more) make it a self-host-only live tail, with the lifetime streaming-history export as the real source; Strava's 2026 API policy forbids feeding API data to any AI application; Goodreads' API is gone and Letterboxd's refuses LLM and personal projects; Apple Health has no web API. The plan records sources. Consequence: the connector registry gains a second kind, the export-archive importer (`accepts(filename) / parse(stream)`), and S-3.7.5 carries most of the roadmap's Domain 2 catalogue.
- **Google verification is per project.** Adding `youtube.readonly` and `calendar.readonly` (both *sensitive*, reviewed in days, no security assessment) to the login client puts the whole consent screen under review, and unverified sensitive-scope apps carry an irreversible 100-user lifetime cap. Gmail read-only is *restricted* (annual CASA assessment) and stays deferred.
- The `/echo` page (PR #224) is the context store, the readiness meter and the sources list; there is no floating bubble, no shortcut and no chat — that is E-3.8.

### E-3.1 🟢 Personal context store schema

**Scope.** Separate-from-sources table holding location, interests, hobbies, work, talents, skills, personality, life events. Designed for opt-in, scoped, revocable bundles.
**Shipped 2026-05-05** in PR #172. New `personal_context` table (Alembic `a4b5c6d7e8f9_personal_context_table.py`) — `(user_id, kind, key)` unique, value JSON-or-string in TEXT, source attribution, confidence 0-1, optional expires_at for stale-aware data ("current employer" expires after N months without re-confirmation). Service layer in `backend/app/services/echo_service.py`: `record_context` (upsert), `get_context`, `list_context` (kind/source filter; expired-by-default hidden), `delete_context`, `revoke_source` (deletes everything from a connector — opt-out path).

10 supported kinds: `location` / `interest` / `hobby` / `work` / `talent` / `skill` / `personality_trait` / `life_event` / `daily_routine` / `place`. Set is closed at the API layer (unknown kinds → 400); extend by editing `SUPPORTED_KINDS` + adding a test.

### E-3.2 🟡 Activity-stream connectors (Domain 2)

**Scope.** Pluggable opt-in connectors. Recommended order (per [feature-roadmap.md L3](feature-roadmap.md#l3--echo-the-personal-brain-)): YouTube watch history → Spotify history → email (read-only) → calendar → browser history → Apple Health.

**Foundation shipped 2026-05-05** in PR #172. `EchoConnector` Protocol + `register_connector` / `get_connector` / `list_connectors` registry in `echo_service.py`. Each connector implements `authorize_url` / `revoke` / `sync` / `supported_kinds`. Concrete connectors are future PRs:

- [ ] T-3.2.1 ⚪ YouTube watch history connector. *Split 2026-10-18: likes + subscriptions via the Data API (S-3.2.2); watch history only via Takeout import (S-3.7.5).*
- [ ] T-3.2.2 ⚪ Spotify history connector. *Now S-3.2.3.*
- [ ] T-3.2.3 ⚪ Email (read-only OAuth) connector. *Deferred: highest privacy weight and Google's restricted-scope assessment; see plan.*
- [ ] T-3.2.4 ⚪ Calendar connector. *Now S-3.2.5.*
- [ ] T-3.2.5 ⚪ Browser history connector. *Deferred to the browser extension in S-3.7.3.*
- [ ] T-3.2.6 ⚪ Apple Health connector. *Deferred: export-file import only; no web API exists.*

**Scope-changed 2026-10-18:** connectors ship as stories below on a widened contract with two kinds, OAuth pull connectors and export-archive importers; the ordering follows the plan's privacy-weight-first rule (cheapest, lowest-sensitivity signals first): GitHub → YouTube likes + Calendar (one Google review) → Spotify live tail (self-host only). Email, browser history and health are deferred rather than scheduled; Strava, Goodreads, Letterboxd and Apple Health are importers under S-3.7.5 because no permitted API exists.
**Acceptance.** A user connects an account from the Echo page, sees exactly what will be ingested before consenting, watches a first sync land events, sees them in a timeline, and revokes with every row from that connector deleted within the same request.

#### S-3.2.1 🔵 Connector runtime and `activity_events`
**PR:** TBD. Lands before any concrete connector.
- [ ] T-3.2.1.1 `activity_events(id, tenant_id, user_id, connector, event_type, occurred_at, ingested_at, payload_json, text_content, linked_document_id, embedding_id)` with index `(user_id, connector, occurred_at)`; `(connector, external_id)` unique for idempotent re-sync
- [ ] T-3.2.1.2 Widen `EchoConnector` to the `personal-brain.md` contract: `name`, `privacy_weight`, `consent_disclosure`, `authorize_url`, `handle_callback`, `revoke`, `initial_backfill`, `incremental_sync`, `event_types`; connectors live under `backend/app/connectors/<name>/`
- [ ] T-3.2.1.3 OAuth tokens stored through the existing Fernet credential store (`byok_service` pattern, [D-043](decisions.md#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05)); `GET /echo/connectors/{name}/authorize`, `GET /echo/connectors/{name}/callback`, `POST /echo/connectors/{name}/sync`, `DELETE /echo/connectors/{name}` (revoke deletes events and tokens). Google connectors use a **separate OAuth client** (`OAUTH_GOOGLE_CONNECTOR_CLIENT_ID/SECRET`) so a rejected sensitive-scope review never breaks sign-in
- [ ] T-3.2.1.7 Second registry kind for export-archive importers (`name`, `accepts(filename)`, `parse(stream) -> events | shares | facts`), used by S-3.7.5; file importers never fake `authorize_url`
- [ ] T-3.2.1.4 `sync_echo_connector` Celery task; scheduler kind `echo_sync` on the S-8.3.1 tick for incremental syncs
- [ ] T-3.2.1.5 Consent screen component showing `consent_disclosure` and the event types before the OAuth redirect
- [ ] T-3.2.1.6 Tests with a fake connector: backfill, idempotent incremental, revoke cascade, isolation
- [ ] T-3.2.1.8 Register `activity_events` and the connector-grant table for export and erasure (`echo_privacy_service.ECHO_TABLES`, `echo_vectors.echo_collection_names()`; [D-089](decisions.md#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19) item 2). The full delete must also revoke and remove stored OAuth tokens: the first Echo credential store, which T-3.10.2.1 already names

#### S-3.2.2 🔵 YouTube likes and subscriptions connector
**PR:** TBD
- [ ] T-3.2.2.1 Google OAuth with `youtube.readonly` (reusing the OAuth client from E-5.4); events `liked`, `subscribed`, `playlist_added`
- [ ] T-3.2.2.2 Liked videos already in the library get `linked_document_id`; others are offered as paste-ingest candidates (never auto-ingested, per the vision's approval principle)
- [ ] T-3.2.2.3 Derived facts: top channels → `interest` rows with confidence from frequency
- [ ] T-3.2.2.4 Tests on recorded API fixtures

#### S-3.2.3 ⚪ Spotify live tail (self-host only)
**Status.** ⚪ proposed, self-host only. Since 2026-02-11 a development-mode Spotify app needs a Premium-subscribed owner and allows five users; extended quota needs a registered business with 250k monthly users. Not a SaaS feature. The lifetime "Extended streaming history" export (S-3.7.5) is the bootstrap and the only complete source.
- [ ] T-3.2.3.1 OAuth; recently-played (API returns only the latest ~50 plays, so sync frequency matters), saved shows and episodes; events `played_episode`, `played_track`, `saved`; disabled gracefully when the owner's Premium lapses
- [ ] T-3.2.3.2 Podcast episodes already in the library linked by RSS GUID where the show matches
- [ ] T-3.2.3.3 Tests on fixtures

#### S-3.2.4 🔵 GitHub connector
**PR:** TBD
- [ ] T-3.2.4.1 OAuth (reusing the GitHub client from E-5.4) with `read:user` and events read; the events feed holds only 300 events / 30 days, so a nightly scheduled sync is required and older commits are walked per repository; commit messages and PR descriptions as `text_content` (voice signal feeder for E-3.3)
- [ ] T-3.2.4.2 Derived `skill` facts from languages

#### S-3.2.5 🔵 Calendar connector
**PR:** TBD
- [ ] T-3.2.5.1 Google Calendar read-only; events `event_attended` with titles only by default (attendees and descriptions opt-in); derived `daily_routine` facts
- [ ] T-3.2.5.2 Tests on fixtures

### E-3.3 🔵 Voice & personality capture (Domain 3)

**Scope.** Store user writing samples, Q&A patterns, opinion threads. Train fine-tune adapters on user-tagged content for persona.

**Scope-changed 2026-10-18.** Mode A only in this epic: `voice_signals` as inspectable, editable, exportable, revocable rows, extracted by an LLM pass over the user's own text (notes from E-8.5, questions, journal entries, shares, outgoing messages from connectors), embedded with the personal facts for retrieval. Fine-tuning moves to E-3.9.
**Acceptance.** After a user has written twenty notes and asked fifty questions, the Echo page shows a signals panel listing style and personality signals with the verbatim examples they were learned from; the user deletes one and it never returns; the user exports the profile as JSON; the "speak as me" agent (E-3.4) retrieves these signals and a blind judge prefers drafts with them over drafts without.

#### S-3.3.1 🔵 `voice_signals` schema, CRUD and the signals panel
**PR:** TBD
- [ ] T-3.3.1.1 `voice_signals(id, tenant_id, user_id, signal_type, value, weight, examples_json, language, register, derived_from, consent_version, created_at, updated_at, suppressed_at)`; `signal_type` closed set covering the style and personality layers in `personal-brain.md` Domain 3; `language` ∈ {en, hi-Deva, hi-Latn, mixed} and `register` ∈ {intimate, casual, professional, public} because bilingual users measurably shift voice per language (see plan)
- [ ] T-3.3.1.2 `GET/POST/PATCH/DELETE /echo/signals`, `GET /echo/signals/export`; suppression is a tombstone so re-extraction cannot resurrect a deleted signal
- [ ] T-3.3.1.3 Signals panel on the Echo page grouped by type, with examples and a one-click "that's not me"
- [ ] T-3.3.1.4 Isolation and tombstone tests
- [ ] T-3.3.1.5 Register `voice_signals` for export and erasure (`echo_privacy_service.ECHO_TABLES`, `echo_vectors.echo_collection_names()`; [D-089](decisions.md#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19) item 2); `echo_intake_service.delete_share` tombstones the signals listed in `derived_signal_ids_json`; signals derive only from the user's own words (`author_is_tenant`), never from context-only shares

#### S-3.3.2 🔵 Signal extraction
**PR:** TBD. Depends on E-8.5 (notes) for its richest input. That input exists since 2026-10-19 (S-8.5.1 / S-8.5.3): read live notes through `note_service.iter_notes(include_deleted=False)` and treat a withdrawn note as a reason to suppress any signal derived from it, not as a missing row ([D-074](decisions.md#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19)).
- [ ] T-3.3.2.1 `echo_extract_signals` use case (economy tier, structured JSON): given a batch of the user's own text with provenance, emit candidate signals with examples; merged by `(signal_type, value)` with weight accumulation
- [ ] T-3.3.2.2 Cheap stylometric baseline computed without an LLM (function-word profile, sentence-length distribution, punctuation habits, character n-grams; language-agnostic) plus one open author-embedding per note on the existing CPU embedding worker (Apache-2.0 or MIT model, named in the plan; English-trained, so the embedding is English-only until validated), stored as `cadence` signals and a per-language style centroid
- [ ] T-3.3.2.3 Inputs: notes, Q&A questions, shares with `user_annotation`, connector `text_content` where the user is the author; incoming content is never a voice input
- [ ] T-3.3.2.4 Runs as a Celery task after each batch of N new inputs; `language` set from `language_service`
- [ ] T-3.3.2.5 Tests with the LLM patched; the stylometric baseline on fixtures

#### S-3.3.3 🔵 Personal retrieval collection
**PR:** TBD
- [ ] T-3.3.3.1 `personal_context_global` Chroma collection (same embedder) holding facts and signals with `tenant_id` metadata; `query_personal_context(tenant_id, text)` with the fail-closed tenant filter the Q&A collection uses
- [ ] T-3.3.3.2 Upsert on write, delete on tombstone, backfill on worker start (the `backfill_qa_library` pattern)
- [ ] T-3.3.3.3 Tests: isolation; tombstoned signals absent
- [ ] T-3.3.3.4 Write vectors with `tenant_id` metadata only into `CHROMA_PERSONAL_CONTEXT_COLLECTION_NAME`, which the full delete already sweeps; add a `test_echo_privacy` case that a fact's vector is gone after `DELETE /echo/brain`

#### S-3.3.4 🔵 Voice-match evaluation harness
**PR:** TBD. The gate for E-3.4; the [D-055](decisions.md#d-055--intelligence-delta-evaluation-methodology-production-input-replay--blind-ab-judging-2026-07-29) method applied to voice.
- [ ] T-3.3.4.1 Three tiers, per the plan: (i) an automatic authorship-verification score against the user's held-out texts per language, (ii) an LLM judge that may abstain, used only for the in-UI voice-match number, (iii) a blinded "which of these did you write?" pairwise test with the user as judge, the only credible product gate
- [ ] T-3.3.4.2 Pre-registered pass rule before the first run; a quality guard (preference against a neutral draft) so a style win never ships unreadable text

### E-3.4 🔵 "Speak as me" agent (Domain 4)

**Scope.** Given an incoming message, draft a response in the user's voice using their accumulated knowledge + context. Privacy: self-host local; SaaS opt-in encrypted. Will use `echo_service.is_ready(user)` as the cold-start gate before activating.

**Scope-changed 2026-10-18.** Pipeline fixed as `classify_intent → retrieve_relevant_knowledge → retrieve_voice_signals → retrieve_personal_context → draft → self_critique_against_voice → finalize`; drafts only, never sends; every draft carries citations, a voice-match score, deviation notes and a disclosure footer.
**Acceptance.** A ready user pastes an incoming message, gets a draft with citations to sources, facts and past Q&As, a voice-match score and deviation notes; editing the draft records the diff as a new signal; a not-ready user gets the readiness meter instead; the daily draft cap holds.

#### S-3.4.1 🔵 Agent and endpoint
**PR:** TBD. Depends on S-3.3.3 and S-3.3.4.
- [ ] T-3.4.1.1 `echo_agent.py` LangGraph graph with the seven nodes; `echo_classify_intent`, `echo_draft`, `echo_critique` use cases registered (`echo_draft` on the synthesis tier). Retrieval picks about five exemplars chosen for *style diversity within the target language and register*, not topical similarity (topical matching measurably hurt attribution in the literature); the critic scores tone, vocabulary, sentence structure and topicality against the trait card for two to three rounds with knockout
- [ ] T-3.4.1.2 `POST /echo/draft {message, audience?, register?}` → `{draft, confidence, voice_match_score, citations, deviation_notes}`; 409 with readiness diagnostics when not ready; gated on `echo_speak_as_me`
- [ ] T-3.4.1.3 Guardrails from `personal-brain.md`: no claims outside ingested sources and facts; names of non-public people flagged before drafting
- [ ] T-3.4.1.4 Tests with the LLM patched; readiness gate; citation grounding
- [ ] T-3.4.1.5 Context-only shares may ground a draft but are never quoted verbatim in it ([D-089](decisions.md#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19) item 1); `echo_drafts` is registered for export and erasure; test both

#### S-3.4.2 🔵 Feedback loop and limits
**PR:** TBD
- [ ] T-3.4.2.1 `POST /echo/draft/{id}/feedback {final_text}` stores the diff as a `voice_signals` candidate with `derived_from=draft_edit`
- [ ] T-3.4.2.2 `ECHO_DRAFTS_PER_DAY` quota key through `quota_metering_service`; a visible, user-removable disclosure line ("Drafted with Echo, reviewed by <user>") on by default, the "reviewed by" clause being what the EU AI Act Art. 50(4) editorial-responsibility exception keys on if a draft is ever published; `audit_log` event per draft; the provenance guard (only the tenant's own authored text feeds a voice) enforced in code, which makes impersonating anyone else structurally impossible
- [ ] T-3.4.2.3 Tests: quota; feedback creates a signal

### E-3.5 🟡 Cold-start readiness threshold

**Scope.** Quantify "enough data has been ingested to safely activate Echo features" and gate Ring 3 surface behind this threshold.
**Shipped 2026-05-05** in PR #172. `echo_service.is_ready(db, user_id, total_threshold=100, sources_threshold=3)` returns an `EchoReadiness` dataclass: `(ready, total_rows, distinct_sources, has_personality_trait, threshold_total, threshold_sources)`. Default thresholds are conservative (100 rows / 3 sources / ≥1 personality_trait); operators tune via the function args. Endpoint `GET /api/v1/echo/status` exposes the readiness diagnostics so the frontend can show "you're 60% there" progress UI. *Built 2026-10-19 on `/echo` (PR #224): the percentage is the mean of the three gates, capped at 99 until `ready`, each gate drawn against its threshold ([D-069](decisions.md#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19)).*

**Scope-changed 2026-10-18:** 🟢 → 🟡. [D-049](decisions.md#d-049--echo-cold-start-readiness-threshold-shipped-triple-is-v1-personal-brainmd-sub-table-is-forward-looking-spec-resolves-oq-6-2026-05-06) named the four-domain table in `personal-brain.md` as the forward-looking spec; once shares, events and signals exist (E-3.7, E-3.2, E-3.3) the v1 triple is no longer the right gate.

#### S-3.5.1 🔵 Five-domain readiness
**PR:** TBD. After S-3.7.1, S-3.2.1 and S-3.3.1 exist.
- [ ] T-3.5.1.1 `is_ready` v2 scoring facts, events (count and span), signals (count and types), shares (count and content types) and notes against the `personal-brain.md` minima, plus a per-language voice floor (the plan suggests about 30 notes or 2,000 words per language, to be tuned) and centroid stability; per-domain progress in `EchoReadiness`. No comparable product publishes a numeric threshold; the literature's anchors are about five exemplars for prompt-time voice and 32 to 100 examples for fine-tuning
- [ ] T-3.5.1.2 `GET /echo/status` returns per-domain progress; the meter shows what is missing in words
- [ ] T-3.5.1.3 Thresholds in settings; tests per domain and for the all-domains gate
Scope-changed 2026-10-19: the notes input already exists. `GET /echo/status` reports `notes_total` and `notes_words` (live notes) since S-8.5.3 (PR [#246](https://github.com/khoks/VideoResearchPro/pull/246)), counted by `note_service.voice_stats`. This story turns them into a per-language gate; until then they are reported only ([D-074](decisions.md#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19) item 4).

### E-3.6 🟢 Tier gating (Studio-only initially)

**Shipped 2026-05-05** in PR #172. Two new feature flags: `echo_personal_brain` (gates the entire `/echo/*` surface) + `echo_speak_as_me` (gates the future "speak as me" agent — E-3.4). Both are Studio-tier-only at the `TIER_CAPABILITIES` level. Frontend shows the Echo surface only when `has_feature("echo_personal_brain")` returns true.

### E-3.7 🟡 Constant-stream intake (Domain 5)

**Progress 2026-10-19.** S-3.7.1 shipped with the privacy pair S-3.10.1 / S-3.10.2 ([#286](https://github.com/khoks/VideoResearchPro/pull/286)). Processing (S-3.7.2) is next.
**Linked decision:** [D-089](decisions.md#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19) (context-only by default, the brain as a registry, the whole archive, delete order).

**Filed 2026-10-18.** The roadmap's first-to-ship Echo component: the user forwards liked videos, reels, memes, WhatsApp threads, Keep notes, quotes, bookmarks and voice memos all day with no approval step, because the act of sharing is the curation. Everything lands in one `shares_inbox`, is processed into text, embedded, and cross-feeds facts (E-3.1), signals (E-3.3), events (E-3.2) and, when the share is an ingestible source, the library through the normal ingest path.
**Plan:** [`docs/plans/l3-echo-personal-brain.md`](plans/l3-echo-personal-brain.md) § Domain 5
**Acceptance.** A user pastes a YouTube URL, drops a screenshot of a meme, and uploads a WhatsApp export; within a minute each appears in the inbox with extracted text, the video is offered to the library, the meme's text is searchable, the WhatsApp thread shows a "redact the other party" option; readiness moves; deleting a share removes its derived signals.

#### S-3.7.1 🟢 `shares_inbox`, quick-share and the inbox page
**PR:** [#286](https://github.com/khoks/VideoResearchPro/pull/286) — merged 2026-10-19, together with S-3.10.1 and S-3.10.2 so the first new Echo table arrived with its export and erasure.
**Calls made in the PR.** (1) **Third-party content is context-only by default**, the plan's recommendation for its open question 2: `author_is_tenant` is false unless the user ticks "These are my own words"; a context-only share may be retrieved as context once S-3.7.2 embeds it, but is never quoted and never enters a dataset or derived export. Marking one's own words is authorship, not an override; the per-thread override the open question asks about was not built. (2) Every share starts `pending`, text included: its words are stored as `extracted_text` at once, but embedding and signals are S-3.7.2's. (3) The stored file name is the share id plus a sanitised extension, never the client's name; downloads are attachments with `nosniff`; a row whose path points outside its tenant directory is never followed. (4) `linked_document_id` instead of the sketch's `linked_source_id` (documents are the library's unit), and `updated_at` added.
- [x] T-3.7.1.1 `shares_inbox(id, tenant_id, user_id, received_at, surface, content_type, raw_payload_json, file_path, extracted_text, user_annotation, processing_state, derived_fact_ids_json, derived_signal_ids_json, linked_document_id, embedding_id)`; same revision adds `tenant_id` to `personal_context` with backfill `= user_id`
- [x] T-3.7.1.2 `POST /echo/shares` (URL, text or file; `surface=manual_quick_share`), `GET /echo/shares`, `PATCH /echo/shares/{id}` (annotation, content_type), `DELETE /echo/shares/{id}` (cascades to derived rows); gated on `echo_personal_brain`
- [x] T-3.7.1.3 "Add to Echo" quick-share in the sidebar chrome and an `/echo/inbox` page with state, text preview and actions
- [x] T-3.7.1.4 Files stored under `ECHO_SHARES_DIR/<tenant>/` with the frame-service traversal guard; size cap
- [x] T-3.7.1.5 Isolation and cascade tests (`tests/test_routers/test_echo_shares.py`: gating, every content type, traversal and size cap, a tampered path, two tenants on every verb, the per-share cascade to file, vector and derived facts)

#### S-3.7.2 🔵 Processing pipeline
**PR:** TBD
- [ ] T-3.7.2.1 `process_share` Celery task: URL → `paste_url_resolver` / article extraction / YouTube metadata; image → local OCR first (Apache-2.0 engine with a Devanagari model, chosen in the plan) with a vision-LLM fallback for stylised text that is off when the tenant's LLM is local-only; audio → the existing Whisper path; text → as is
- [ ] T-3.7.2.2 Embedding into a `shares_global` collection with `tenant_id`; shares resolving to a source are offered to the library (one-click ingest through the paste path, visibility granted to the sharer only)
- [ ] T-3.7.2.3 Share → activity event (`connector=internal`, `event_type=shared_to_pratidhvani`) and → signal-extraction queue (S-3.3.2)
- [ ] T-3.7.2.4 Fail-soft: a share whose processing fails stays browsable with the failure shown
- [ ] T-3.7.2.5 Tests per content type with external calls patched
- [ ] T-3.7.2.6 Embed each share under `echo_vectors.share_vector_id(id)` with `tenant_id` metadata in `CHROMA_SHARES_COLLECTION_NAME`, and set `embedding_id`. The per-share delete and the full delete (S-3.10.2) find vectors only by that id and that metadata
- [ ] T-3.7.2.7 A context-only share (`author_is_tenant` false) feeds context retrieval but never voice-signal extraction as the user's own words; the user's own words (`author_is_tenant` true) do

#### S-3.7.3 🔵 Drag-drop and browser extension
**PR:** TBD
- [ ] T-3.7.3.1 Drop zone on every page (files, URLs, text) posting to `/echo/shares` with `surface=drag_drop`
- [ ] T-3.7.3.2 Manifest V3 extension (`extension/`): context-menu "Share to Pratidhvani" on page, link, selection and image; token pasted from the app's sessions page; posts with `surface=browser_ext`
- [ ] T-3.7.3.3 Optional history capture in the extension (per-domain allow-list, never incognito) lands as `activity_events` through the connector runtime; opt-in per category

#### S-3.7.4 ⚪ Email-in inbox
- [ ] T-3.7.4.1 Self-host: IMAP poller for a dedicated mailbox (settings `ECHO_IMAP_*`), each message a share with `surface=email_in`
- [ ] T-3.7.4.2 SaaS: inbound-webhook provider (choice in the plan), per-user address, signature verification

#### S-3.7.5 🔵 Export-file importers
**PR:** TBD. The only route to several high-value signals.
- [ ] T-3.7.5.1 WhatsApp `.txt` export parser (date / sender / message lines, media placeholders), with "redact other party" producing a sender-only copy before storage
- [ ] T-3.7.5.2 Google Takeout: YouTube watch and search history JSON → `activity_events` (`connector=youtube_takeout`); Keep notes JSON → shares
- [ ] T-3.7.5.3 Spotify "Extended streaming history" JSON → events (the complete source; the API is a 50-item tail); Goodreads and Letterboxd CSV → `read` / `watched` events; Strava bulk export → workout events (user-owned data outside Strava's API policy; confirm with counsel per the plan); Apple Health `export.xml` → `daily_routine` facts via a streaming parser (exports run to gigabytes)
- [ ] T-3.7.5.6 `author_is_tenant` flag on every imported message: third-party text (the other side of a WhatsApp thread) is retrievable as context, never quoted verbatim in outputs and excluded from dataset exports
- [ ] T-3.7.5.4 Upload endpoint with format detection; streaming parse so a 100 MB export does not load into memory
- [ ] T-3.7.5.5 Tests on fixture exports for every format

#### S-3.7.6 ⚪ OS share target
- [ ] T-3.7.6.1 Web-app manifest `share_target` (depends on S-8.12.2) so Android shares land in the inbox; iOS via a Shortcut that posts to `/echo/shares`

### E-3.8 🔵 Always-evokable Echo surface

**Filed 2026-10-18.** The floating bubble on every page: one click or `Ctrl-E` expands a chat panel; below readiness it shows the meter and what is missing; above it, it answers *as the user* by routing to the E-3.4 agent for drafts and to the library / history agents for questions, and surfaces anticipation cards (unread saved items, suggested questions from E-8.4).
**Acceptance.** The bubble is present for Studio users on every authenticated page, opens with its shortcut, shows readiness progress in words, and once ready holds a conversation whose answers cite sources, facts and past Q&As; it never covers the Q&A composer on mobile.

#### S-3.8.1 🔵 Bubble, panel and shortcut
**PR:** TBD. Depends on the `useShortcuts` hook from S-8.2.2.
- [ ] T-3.8.1.1 `EchoBubble` mounted in `AppLayout` behind `has('echo_personal_brain')`; panel with readiness state and chat, labelled as AI (EU AI Act Art. 50(1) applies to a conversational surface from 2026-08-02). Shortcut: **not** `Cmd-E` as the roadmap sketched (it is macOS's system-wide "Use Selection for Find" and clashes in Safari and Chrome); the plan proposes `Ctrl/Cmd-Shift-E` plus an "Ask Echo" entry in the `Ctrl-K` palette
- [ ] T-3.8.1.2 `POST /echo/chat` routing by intent to draft, library Q&A or history Q&A; exchanges stored as `qa_history_exchanges` with `source=echo` so they enter the Q&A library index
- [ ] T-3.8.1.3 Mobile placement above the docked composer (S-8.12.1)

#### S-3.8.2 🔵 Anticipation cards
**PR:** TBD
- [ ] T-3.8.2.1 Cards in the panel: suggested questions for the current page (E-8.4), shares not yet read, saved searches that changed (E-8.3)

### E-3.9 ⚪ Mode B: opt-in per-user fine-tuning

**Filed 2026-10-18.** After Mode A is stable and the readiness data shows the corpus warrants it: curate per-theme datasets (problem-solution, recommendation lens, situational priority, opinion-formation, methodology) from the user's signals and exchanges, train an adapter, and route `echo_draft` to it with retrieval still augmenting. Provider and cost model are open questions in the plan.
**Status.** ⚪ proposed. Not scheduled until S-3.3.4 shows Mode A plateauing. **Research 2026-10-19:** OpenAI is winding down its self-serve fine-tuning platform (no new jobs after 2027-01-06; the fine-tunable models retire 2027-01-14), Anthropic fine-tuning exists only for Claude 3 Haiku on Bedrock in one region, and the one head-to-head study found direct LoRA style tuning raises style accuracy while collapsing preferred quality. Mode B therefore has to be provider-agnostic from the first line, with local LoRA on open weights as the durable path and a quality guard before any adapter is served.

#### S-3.9.1 ⚪ Theme datasets
- [ ] T-3.9.1.1 `dataset_service` gains per-theme Echo exports built from exchanges, drafts the user accepted and signals with examples, in the OpenAI chat JSONL already shipped (byte-compatible with Hugging Face TRL's `messages` format) plus thin Bedrock-Claude and Vertex variants, every example tagged with `language`, `register`, `source_id` and `consent_version` so themes can be curated and revoked
#### S-3.9.2 ⚪ Training adapter
- [ ] T-3.9.2.1 Provider abstraction: local LoRA on an open-weights model (Apache-2.0 tooling; about 6 GB VRAM floor for an 8B QLoRA, 12 to 16 GB realistic) first, hosted supervised fine-tune where a provider still offers it; job tracking, cost shown beforehand; persona-vector style regression prompts and a preference-rate quality guard before serving
#### S-3.9.3 ⚪ Routing
- [ ] T-3.9.3.1 Per-user override of the `echo_draft` use case to the tuned model through the E-1.13 override mechanism; delete weights on revoke

### E-3.10 🟡 Privacy model: export, delete, zero-knowledge

**Linked decision:** [D-089](decisions.md#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19).
**Open question (the user's):** should context-only share text stay in the whole-brain archive (built, D-089 item 3), or move to a separate flagged section? Not omitted either way, or the archive stops being lossless.
**Progress 2026-10-19.** Export and delete shipped with the first new Echo table ([#286](https://github.com/khoks/VideoResearchPro/pull/286)). **Rule for every later Echo story:** a new Echo table goes into `echo_privacy_service.ECHO_TABLES`, a new Echo Chroma collection into `echo_vectors.echo_collection_names()`, and a new Echo file store under the tenant directory, or the export misses it and the delete leaves it behind. The connector-grant table (E-3.2) is the first credential store this applies to.

**Filed 2026-10-18.** The hard constraint from `personal-brain.md`: self-host data is local; every connector is opt-in, scoped and revocable; the whole brain is exportable and deletable; SaaS offers a zero-knowledge mode.
**Acceptance.** A user downloads one archive containing facts, events, signals, shares and drafts; a full delete leaves no row, file, token or Chroma vector attributed to them; every connector's consent text is shown before activation and stored with the grant.

#### S-3.10.1 🟢 Full export
**PR:** [#286](https://github.com/khoks/VideoResearchPro/pull/286) — merged 2026-10-19.
- [x] T-3.10.1.1 `GET /echo/export` streaming a zip of JSONL per table plus files; audit event. Built in a temporary file (constant memory) and removed after sending. `manifest.json` carries row counts, every file with size and SHA-256, and any file a row points at that was missing. `echo_privacy_service.read_archive` is the exact inverse, and `test_echo_privacy.py` holds every column of every row and every file's bytes to it. The archive includes context-only share content: it is the user's own copy of what they handed over (Article 20). The audit event carries counts only
#### S-3.10.2 🟢 Full delete
**PR:** [#286](https://github.com/khoks/VideoResearchPro/pull/286) — merged 2026-10-19.
- [x] T-3.10.2.1 `DELETE /echo/brain?confirm=delete-everything` cascading across every Echo table, file directory, credential and Chroma collection; verified by a test that counts zero rows afterwards. The test looks in each store directly (rows, the tenant directory, both Echo collections) for both tenants: the deleting tenant's footprint is zero and the other tenant's is unchanged. Order is vectors, files, then rows in one commit, so a failing store stops the delete before the rows that would let a retry find what is left (tested). The service re-counts every store afterwards and fails rather than report success with data left. No Echo credential exists yet; the library, notes, account and BYOK keys are outside Echo and untouched. `GET /echo/brain/footprint` shows the same counts
#### S-3.10.3 ⚪ Zero-knowledge mode (SaaS)
- [ ] T-3.10.3.1 Design only: client-side encryption of share payloads and signals with a user-held key; the plan records that server-side embedding and extraction cannot run on ciphertext, so this mode disables them. Decision deferred to SaaS launch.

---

## I-4 🟡 Self-curating docs & work-state

**Why it exists.** Decisions, vision refinements, and new work items routinely surface in chat conversations and risk being lost in the transcript. Skills + Stop hook persist them automatically into the canonical docs and this initiatives file, so future-Claude (and future-me) can reconstruct project state without trawling chat history.
**Decision links:** [D-011](decisions.md#d-011--two-persistence-skills--auto-stop-hook-for-session-to-docs-flow-2026-04-25)

### E-4.1 🟢 `knowledge-curator` skill

**Scope.** Skill at `.claude/skills/knowledge-curator/SKILL.md` that scans session, routes content into the canonical docs (`feature-roadmap.md`, `architecture.md`, `requirements.md`, `source-types.md`, `branding.md`, `vision.md`, `personal-brain.md`, `saas-roadmap.md`, `decisions.md`), commits on a branch, opens PR.
**Status verified 2026-04-28** — skill has been invoked dozens of times across the multi-session L1 rollout, has correctly opened curator PRs (e.g. PRs #94, #97, #98, #101), correctly no-ops on tactical sessions (PR-merge sessions, status-only sessions), and reliably routes ADRs / source-types / feature-roadmap edits into the right files.

### E-4.2 🟢 `work-tracker` skill

**Scope.** Skill at `.claude/skills/work-tracker/SKILL.md` that owns this file (`docs/initiatives.md`). Updates status / scope of existing items; creates new items for newly-discussed work; cross-links to decisions and PRs; commits on a branch, opens PR.
**Status verified 2026-04-28** — skill has filed S-1.5.11 (D-020), S-1.5.3 / S-1.5.4 framing/polymorphic updates (D-014/016/018), I-2 audit (PR #93), OQ-1 through OQ-11 lifecycle tracking, and the I-4 audit captured in this PR. Sibling-PR pattern with curator works reliably.

### E-4.3 🟢 Stop-hook auto-invocation

**Scope.** `.claude/settings.json` Stop hook nudges Claude once per session (via `stop_hook_active` guard) to invoke both skills before ending. Skills are no-op-safe.
**Status verified 2026-04-28** — Stop hook fired 8+ times across the 2026-04-26 → 2026-04-28 sessions; recursion-guard works; both skills triggered or correctly no-op'd as appropriate. Per-session reliability has been 100%.

### E-4.4 🟢 Decision log seed

**Scope.** Bootstrap [`decisions.md`](decisions.md) with the eleven decisions captured from project history (D-001 through D-011).
**Shipped** in the bootstrap PR. The log has since grown organically to D-022 through curator-driven adds — the seed serves its purpose.

### E-4.5 🟢 Initiatives seed

**Scope.** Bootstrap this file with all known initiatives + epics + stories at the time of the bootstrap PR.
**Shipped** in the bootstrap PR. File has since grown to 6 initiatives (I-1 through I-6) and 11 OQs through work-tracker maintenance.

### E-4.6 🟢 Coordinated PR composition (skills share a PR per session)

**Closed 2026-05-04.** The "second skill checks out the first's branch + adds a commit" pattern is now both **documented in `SKILL.md`** (under the "Coordination with /knowledge-curator" section in `work-tracker/SKILL.md`) **and practiced in production** across multiple sessions: combined PRs include [#139](https://github.com/khoks/VideoResearchPro/pull/139) (D-031/D-032 + T-1.6.6 follow-up), [#143](https://github.com/khoks/VideoResearchPro/pull/143) (M-1.7/T-1.6.6/M-1.8 reconciliation), [#147](https://github.com/khoks/VideoResearchPro/pull/147) (I-1 closure).

Sibling-PR fallback is still acceptable when timing or branch-state makes a shared branch awkward — the convention is "shared by default, sibling when easier", with a `Companion PR: #N` cross-reference in either case.

### E-4.7 🟢 Inventions / novel-ideas log

**Closed 2026-05-04.** [`inventions.md`](inventions.md) ships as a canonical doc with the full template + conventions. The `/knowledge-curator` skill includes the detection heuristic for filing `N-NNN` entries.

**Status (2026-05-04 inventory).** Zero `N-NNN` entries filed to date. The project's work has been **engineering with established patterns** — polymorphic dispatch, factory base classes, opt-in extras, two-phase migrations — none of which qualify as novel mechanisms. The infrastructure (template + skill heuristic + doc location) is ready when a genuine novel concept surfaces. False-negative bias is the expensive failure mode per the doc's own conventions, so the bar stays "we'd file even something borderline" — there's just been nothing borderline yet.

**Scope.** Canonical doc [`inventions.md`](inventions.md) owned by `/knowledge-curator`. Captures novel mechanisms / non-obvious combinations / potentially-patentable concepts surfaced in conversation. Skill detection heuristic biased toward over-capture; verbatim user messages flagged as novel are also saved raw to `docs/notes/<YYYY-MM-DD-novel-<slug>.md`. Skill makes no legal patentability assessment.
**Linked decision:** [D-012](decisions.md#d-012--capture-novel--potentially-patentable-ideas-in-inventionsmd-2026-04-25)
**PR:** [#68](https://github.com/khoks/VideoResearchPro/pull/68) (follow-up commit on the bootstrap branch)

### E-4.8 🟢 Cross-doc anchor-link convention fix

**Bulk-fix shipped 2026-05-06** in [PR #179](https://github.com/khoks/VideoResearchPro/pull/179). `backend/scripts/fix_anchor_links.py` walks every cross-doc link, attempts to collapse `-+ → -` per GitHub's slug rule, and rewrites if the candidate matches a real heading. **132 links rewritten** across `docs/decisions.md` (25), `docs/initiatives.md` (69), `docs/feature-roadmap.md` (16), `docs/saas-roadmap.md` (6), `docs/source-types.md` (12), `docs/architecture.md` (4). Idempotent — re-running on already-fixed docs is a no-op. **13 residual heading-rename casualties resolved 2026-05-06** in the follow-up branch — every cross-doc anchor now resolves cleanly.

**Tasks**
- [x] T-4.8.1 Bulk-fix script — *shipped 2026-05-06*.
- [x] T-4.8.2 Run + diff review — *shipped 2026-05-06*.
- [x] T-4.8.3 Manual click-through (post-merge) — pending.
- [x] T-4.8.4 🟢 **Heading-rename casualties resolved 2026-05-06** in this branch's follow-up. All 13 residual cross-doc anchors hand-mapped to their renamed-target heading slugs (e.g. `i-5--saas-readiness-long-horizon` → `i-5-saas-readiness-long-horizon-code-shippable-work-fully-closed-2026-05-05`; `oq-4` rerouted to its parent heading `open-questions-parking-lot` since OQ-* lives in bullet form, not headings). `fix_anchor_links.py --report` now reports zero residual broken links across the doc set.
- [ ] T-4.8.5 🔵 **`fix_anchor_links.py` collapses hyphen runs; GitHub does not.** Found 2026-10-18 while reconciling this file. The script rewrote `#d-063--per-user-...` to `#d-063-per-user-...`, but GitHub's rendered HTML (contents API, `html` media type) gives `id="user-content-d-063--per-user-..."`, and `e-510--per-user-isolation-r2` for an emoji heading: every dropped em dash or emoji leaves two hyphens. So the 132 rewrites in PR #179 need re-checking against rendered anchors, and the script's oracle should be GitHub's output rather than its own slug function. It also has no dry-run flag; `--report` is ignored and files are rewritten. The 2026-10-18 reconciliation reverted its rewrites and kept the `--` forms.
  - [x] Script rewritten to match github-slugger, `--check` mode, 8 slugs pinned against rendered ids — PR [#229](https://github.com/khoks/VideoResearchPro/pull/229), 2026-10-19. `--check` on master: 183 repairable links, 6 needing hand fixes.
  - [ ] Run the repair across the docs and hand-fix the 6 (`#d-051`, `#d-043`, `#e-51-tenantid-audit-retrofit`, the D-009 anchor in CHANGELOG, the `n-NNN` template link). Waits for the in-flight R3/R4 and roadmap-planning doc branches to merge, so the rewrite does not conflict with them.

### E-4.10 🟢 Replace `Base.metadata.create_all` lifespan with Alembic-managed schema

**Closed 2026-05-06** in [PR #179](https://github.com/khoks/VideoResearchPro/pull/179). New `app/services/schema_init_service.py` with `ensure_schema_at_head(db_url, orm_metadata)` handles four cases cleanly:
- `fresh_install` — empty DB → `alembic upgrade head`.
- `already_at_head` — no-op.
- `upgraded` — DB at intermediate revision → normal upgrade.
- `stamped_recovery` — tables exist (via pre-E-4.10 `create_all`) but `alembic_version` is stale → upgrade fails with "already exists" → service detects schema-matches-ORM bidirectionally → auto-stamp head. **Closes the operator upgrade-path bug** for anyone who installed before this session's migrations.

Strict bidirectional schema-match check (every ORM table in DB AND every DB table in ORM) prevents silent papering-over of real drift; mismatches raise with a clear "manual operator intervention required" message pointing at `alembic stamp <revision>`.

**Tasks**
- [x] T-4.10.1 Remove `Base.metadata.create_all` from lifespan — *shipped*.
- [x] T-4.10.2 Replace with `ensure_schema_at_head` — *shipped*.
- [x] T-4.10.3 Recovery path is the auto-stamp branch above; no separate runbook needed since it's automatic + observable via the lifespan log line. Operators with drifted schemas hit the manual-intervention error message which carries the exact `stamp` command — *shipped*.
- [x] T-4.10.4 conftest.py keeps using `Base.metadata.create_all` directly against in-memory SQLite for tests (independent of production lifespan; intentional) — *unchanged*.
- [x] T-4.10.5 End-to-end test in `tests/test_services/test_schema_init.py::test_real_alembic_recovers_from_create_all_conflict` reproduces the conflict + verifies recovery — *shipped*.
- [x] T-4.10.6 🟢 **Column-drift detection + auto-recovery shipped 2026-05-06** in this branch's follow-up. `_attempt_recovery` now checks bidirectional **table** match → detects **column** drift via `_column_drift` (compares live `inspect(eng).get_columns(t)` against `orm_metadata.tables[t].columns`) → if drift is purely additive (`missing_in_db` only), runs `ALTER TABLE ADD COLUMN` for each missing column then stamps head; refuses with a clear "non-additive drift" error if the DB has columns the ORM doesn't (destructive direction is a manual operator call). 3 new tests cover (a) additive recovery, (b) destructive-drift refusal, (c) end-to-end against the real ORM with `users.failed_login_attempts` / `users.locked_until` reconstructed. Operators no longer need to `rm data/<db>` after pulling new migrations against pre-E-4.10 schemas.

- [x] T-4.10.7 🟢 **In-process migrations were silencing all application logging — fixed 2026-07-31** ([PR #219](https://github.com/khoks/VideoResearchPro/pull/219)). Moving schema init *into the process* (the whole point of this epic) had a side effect nobody looked for: `alembic/env.py` calls `fileConfig(...)`, whose `disable_existing_loggers` defaults to `True`, setting `.disabled` on every logger not named in `alembic.ini` — the whole `app.*` tree. On a fresh install the app lost its entire log for the process lifetime, starting with the `logger.info(f"schema_init: {result}")` on the next line. Standalone `alembic upgrade` was unaffected, which is why it survived from 2026-05-06 to 2026-07-31. Fixed with `disable_existing_loggers=False`; pinned by `test_startup_migration_does_not_disable_app_loggers`, which asserts the migration actually ran so it cannot pass vacuously. Surfaced from an unrelated flaky R1 test — see [docs/testing.md](testing.md) §3.5.

13 schema_init tests; all paths covered. End-to-end against the project's real ORM + migrations. Live boot post-fix: `lifespan: schema-init result=stamped_recovery` (when applicable) followed by clean `/api/v1/health` `ok`.

### E-4.9 🟢 LLM smoke-probe `gpt-5.4` config audit

**Closed 2026-05-06** in [PR #179](https://github.com/khoks/VideoResearchPro/pull/179). Audit found `gpt-5.4` and `gpt-5.4-mini` (the registry's defaults) are NOT in the configured OpenAI account's available models — the available `gpt-5.x` family is `gpt-5.4-nano`, `gpt-5.4-pro`, `gpt-5.5`, `gpt-5.5-pro`. Updated `USE_CASE_REGISTRY` (`app/services/llm_routing.py`):
- `gpt-5.4-mini` → `gpt-5.4-nano` (small / fast tier)
- `gpt-5.4` → `gpt-5.5` (flagship tier)

Verified post-fix boot: `/api/v1/health` reports `llm.status: ok`, `unavailable_features: []`. All 3 unique configs (`openai:gpt-5.4-nano:off`, `openai:gpt-5.5:low`, `openai:gpt-4.1-mini:off`) probe successfully.

**Tasks**
- [x] T-4.9.1 List OpenAI models — *done via openai-python `models.list()`*.
- [x] T-4.9.2 Registry rewrite — *shipped*.
- [x] T-4.9.3 Boot smoke green — *verified*.
- [x] T-4.9.4 🟢 **Registry-revalidation CLI shipped 2026-05-06** in this branch's follow-up. New `backend/scripts/validate_llm_registry.py` walks unique `(provider, model)` pairs in `USE_CASE_REGISTRY` (post-`resolve_config`, so env overrides apply), calls `client.models.list()` per provider, and reports drift. `--strict` exits 1 on any miss for CI use. Suggests near-matches when a model isn't found. OpenAI is the only provider exercised today; Anthropic / Google get a `?` line + skipped count. Verified live: 3 unique pairs all `OK`. Schedule manually or via Windows Task Scheduler.
- [x] T-4.9.5 🟢 **Probe budget fix shipped 2026-05-06** in this branch's follow-up. Picked option (a) — `probe_config()` now uses `max_tokens=256` when `cfg.reasoning != "off"`, keeps the minimal 16-token budget for non-reasoning configs. Reasoning models burn budget on internal thinking before any visible output, so 256 covers the typical `low` / `medium` budget overhead while still being cheap. Verified live: `/api/v1/health` returns `llm.status: ok`, `unavailable: []` against `gpt-5.5:low`.

---


## I-5 🟡 SaaS readiness (long-horizon) — code-shippable work fully closed 2026-05-05

**Scope-changed 2026-10-18:** status 🟢 → 🟡 to follow the parent-is-loosest-child rule. [E-5.10](#e-510--per-user-isolation-r2) (R2 per-user isolation, filed 2026-07-31) reopened code-shippable work here: S-5.10.3 and T-5.10.2.5 are still open. The heading's "fully closed 2026-05-05" refers to the original scope.

**Why it exists.** Today's PRs must remain forward-compatible with a future public SaaS — multi-tenant, billed, abuse-resistant, hardened auth.
**North-star doc:** [saas-roadmap.md](saas-roadmap.md)

**Status (2026-05-05).** **All code-shippable I-5 work has now landed.** The remaining ⚪ items are correctly deferred to SaaS launch — none has a self-host code path that buys anything today.

- ✅ **E-5.1** Tenancy retrofit — fully closed (4 phases + operator NOT NULL runbook).
- ✅ **E-5.4** Auth hardening — fully closed. 8 tasks across PRs [#156](https://github.com/khoks/VideoResearchPro/pull/156) / [#163](https://github.com/khoks/VideoResearchPro/pull/163) / [#164](https://github.com/khoks/VideoResearchPro/pull/164) / [#165](https://github.com/khoks/VideoResearchPro/pull/165) / [#166](https://github.com/khoks/VideoResearchPro/pull/166).
- ✅ **E-5.2** Subscription tiers — fully closed. Schema (#155) + utility (#155) + quota enforcement at hot endpoints (#169) shipped. T-5.2.4 (wire `require_tier` into actual endpoints) is **partial-permanent** — `require_feature("byok_llm_keys")` already gates the BYOK router; future Author Studio (I-6) and Echo (I-3) endpoints will gate when those land.
- ✅ **E-5.5** Abuse prevention — code-shippable parts closed. Rate-limit middleware (#157) + quota metering enforcement (#169) shipped. Remaining: T-5.5.4 Redis backend (🔴 per [D-039](decisions.md#d-039--in-memory-rate-limit-backend-as-the-default-redis-swap-deferred-to-multi-worker-saas-2026-05-04) — gated on multi-worker SaaS), T-5.5.6 content policy / takedown (🔴 — needs M11 public sharing first), T-5.5.7 fraud detection (🔴 — needs production traffic + abuse signal data first).
- ✅ **E-5.6** Background-job isolation — code-shippable parts closed. BYOK foundation (#158), BYOK LLM resolution-path (#162 via ContextVar / [D-041](decisions.md#d-041--contextvar-plumbing-vs-explicit-kwargs-for-cross-cutting-per-user-state-2026-05-05)), Chroma tenant filtering (#161), per-tenant Celery routing (#170). All shipped.

**Remaining design-complete, code-deferred to SaaS launch:**
- **E-5.3** Stripe — pure SaaS; no value for self-host (every user already at "Studio" effectively).
- **E-5.7** Data residency — single-machine install has data in one place by definition.
- **E-5.8** Hosting / infra — operations work (Postgres / Redis Cluster / S3 / CDN provisioning), executed at SaaS launch.
- **E-5.9** Hosted UX — gated on E-5.3.
- **T-5.1.3** Multi-user-per-workspace (`tenants` + `tenant_users` tables) — Team SaaS tier only.
- **T-5.5.4** Redis-backed rate-limit bucket store — gated on multi-worker SaaS deployment per D-039.
- **T-5.5.6** Content policy + takedown workflow — gated on M11 public report sharing.
- **T-5.5.7** Fraud detection / anomalous-pattern alerting — gated on real production traffic.

Full design for each in [`saas-roadmap.md`](saas-roadmap.md); each epic's entry below cross-links the relevant section.

**Decisions captured 2026-05-04 / 2026-05-05:**
- [D-038](decisions.md#d-038--tenancy-retrofit-ships-in-four-phases-audit--additive--backfillwrites--reads--not-null-2026-05-04) — Tenancy retrofit ships in four phases (E-5.1).
- [D-039](decisions.md#d-039--in-memory-rate-limit-backend-as-the-default-redis-swap-deferred-to-multi-worker-saas-2026-05-04) — In-memory rate-limit backend as the default; Redis-swap deferred.
- [D-040](decisions.md#d-040--failed-logins-for-unknown-emails-do-not-create-user-rows-lock-arbitrary-account-defence-2026-05-04) — Failed logins for unknown emails do NOT create User rows.
- [D-041](decisions.md#d-041--contextvar-plumbing-vs-explicit-kwargs-for-cross-cutting-per-user-state-2026-05-05) — ContextVar plumbing for cross-cutting per-user state.
- [D-042](decisions.md#d-042--oauth-first-login-links-to-existing-user-by-email-2026-05-05) — OAuth first-login email-based linking.
- [D-043](decisions.md#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05) — Single shared Fernet key for all encrypted-at-rest credentials.


### E-5.10 🟡 Per-user isolation (R2)

**Why it exists.** The user's requirement: work done by one user must not be visible to another in any section. An audit found five live leak classes and, underneath them, a missing ownership model — `documents` is a shared cache with no tenant, and three ingest paths create documents with no job either.
**Linked decision:** [D-063](decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-070](decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19) (fix for the gap below, shipped 2026-10-19)

#### S-5.10.1 🟢 Close the five leak classes + document_visibility
**Shipped:** 2026-07-31
**Audit 2026-10-19:** the grants only ever work for `source_type='video'`. `document_visibility.video_id` references the legacy, nullable `documents.video_id`, and `grant()` drops falsy ids, so PDFs, pasted pages and every other non-video document are ingested but never granted, and never listed or retrieved. Found by the first frontend caller (PR [#224](https://github.com/khoks/VideoResearchPro/pull/224)); pinned by a strict xfail; fixed by [S-5.10.4](#s-5104--key-document-visibility-on-document_id) on 2026-10-19 (PR [#241](https://github.com/khoks/VideoResearchPro/pull/241)), which also found that `insert_chunks` had never written a non-video chunk and that an empty visible set searched the whole library. The "0 orphans" below held only because no non-video document existed on that instance.
- [x] T-5.10.1.1 `document_visibility` model + migration `d4e5f6a7b8c0` with backfill (203 grants, 0 orphans)
- [x] T-5.10.1.2 Grants wired at every ingest path incl. PDF/paste **dedup hits**; job path grants over the whole link set at 3 phase boundaries. *2026-10-19: the PDF and paste calls pass `doc.video_id`, which is NULL for those sources, so the wiring is present and the grant is a no-op — see the audit note above.*
- [x] T-5.10.1.3 Library browse scoped; job-topic and job-count joins tenant-filtered
- [x] T-5.10.1.4 Cross-tenant delete closed — tenant is part of the lookup, so a foreign id 404s indistinguishably
- [x] T-5.10.1.5 Dataset exports scoped; signature change makes a missed call site a hard error, not a silent leak
- [x] T-5.10.1.6 WebSocket job-ownership check, fails closed, injectable session
- [x] T-5.10.1.7 Vector retrieval scoped to the visible set; empty list stays empty. *2026-10-19: the agent passed `[]` but `query_collection` turned it into an unrestricted search — the test checked the caller, not the service. Closed under T-5.10.4.8.*
- [x] T-5.10.1.8 11 regression tests asserting absence of foreign data

#### S-5.10.2 🟢 Channels per-tenant — shipped 2026-07-31
Linked decision: [D-065](decisions.md#d-065--channel-subscriptions-become-per-tenant-transliteration-reversed-2026-07-31). User decision: channels become per-tenant.
- [x] T-5.10.2.1 `channel_subscriptions` model + migration `f6a7b8c9d1e2` with backfill (95 rows, 92/3 split matching document visibility)
- [x] T-5.10.2.2 `source_weight` moved per-tenant — it was a documented *user-set* trust score stored globally, so one user re-weighted everyone's retrieval ranking
- [x] T-5.10.2.3 `subscription_service` as the single accessor; channel list, detail, subscribe/unsubscribe/sync and video listing all scoped
- [x] T-5.10.2.4 8 isolation tests: subscribe/weight/sync-timestamp do not cross tenants; video counts show only visible documents
- [ ] T-5.10.2.5 `api_quota_log` unscoped (low sensitivity — leaks usage volume only). *Verified 2026-10-18: its columns are id / timestamp / operation / units, with no user or tenant*
- [x] T-5.10.2.6 Q&A-history Chroma collection — verify tenant filtering matches the transcript collection. *Verified 2026-10-18: `query_qa_collection` restricts to `tenant_id` metadata (T-5.6.6), the counterpart of the transcript collection's visible-set filter*
- [ ] T-5.10.2.7 Re-run the D-055 harness: library Q&A now answers from a per-user corpus

#### S-5.10.3 🔵 Drop the legacy global columns on `channels`
`subscribed`, `source_weight`, `last_synced_at` are retained on `channels` so a partial rollout stays recoverable. Remove once nothing reads them.
- [ ] T-5.10.3.1 Audit remaining readers of the legacy columns (subscription sync task, any scripts). *2026-10-18 findings: still written in `tasks/job_tasks.py` (`channel.subscribed = True` in the subscription path, `channel.last_synced_at` in the sync path). Routers read through `subscription_service`. `source_weight` has no reader anywhere (see I-7)*
- [ ] T-5.10.3.2 Migration to drop them, with a downgrade that restores from `channel_subscriptions`

#### S-5.10.4 🟢 Key document visibility on `document_id` — shipped 2026-10-19
**PR:** [#241](https://github.com/khoks/VideoResearchPro/pull/241). Proposed as a side-session card on 2026-10-19; landed after the R3/R4 batch (PR #227) because both touch `qa_agent.py` and the library Q&A route.
**Linked decision:** [D-070](decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19) (accepted; records the transition choice and six defects found while shipping)
**Acceptance (met).** An uploaded PDF and a pasted page appear in `GET /library/videos`, are found by its `search=`, and are in the set library Q&A retrieves from — for the tenant who ingested them and for nobody else (`tests/test_routers/test_library_visibility_isolation.py`, two tenants). The strict xfail in `tests/test_routers/test_library_paste_urls.py` is un-marked and passes. Non-video chunks are proven to reach a real in-memory Chroma collection and to be scoped by `document_id` (`tests/test_services/test_chroma_document_scope.py`). 1,454 backend tests pass; `npm run build` passes.
**Tasks**
- [x] T-5.10.4.1 Migration `3653e565c1fc` (on top of S-8.1.1's `d8e9f0a1b2c3`; two earlier drafts had taken `c7d8e9f0a1b2` and `d8e9f0a1b2c3`, which S-8.3.1 and S-8.1.1 also took the same day — ids are random now): `document_visibility.document_id` (FK `documents.document_id`, cascade), backfill by joining `documents` on `video_id`, orphans dropped with a logged count, unique moved to `(document_id, tenant_id)`, `video_id` retired via SQLite batch rebuild. Downgrade restores `video_id` and drops the grants the old schema cannot hold. Round trip pinned by `tests/test_migrations/test_visibility_document_id_migration.py`
- [x] T-5.10.4.2 `grant()` takes document ids; the five call sites pass `document_id` (the job path reads `JobVideo.document_id`, which also covers channel sync); `visible_video_ids()` → `visible_document_ids()` with no shim — no reader needs YouTube ids
- [x] T-5.10.4.3 Listing, both `channels.py` readers, `subscription_service.visible_channel_ids` and `corpus_stats_service` filter on `document_id`; `query_collection(document_ids=...)` filters Chroma on the `document_id` metadata field, which `_build_video_metadata` and the chunker now write for every source type
- [x] T-5.10.4.4 Transition decided and recorded in D-070: metadata-only backfill at API startup (`backfill_chunk_document_ids`, idempotent, no re-embedding), a single retrieval path rather than a dual filter. Chroma ids stay `{video_id}:{index}` for videos and are `{document_id}:{index}` for everything else
- [x] T-5.10.4.5 `LibraryVideoResponse.id = document_id`, `video_id` and `duration_seconds` nullable, `source_type` added; `libraryApi.ts` type widened to match
- [x] T-5.10.4.6 Tests: xfail un-marked and sharpened; `test_library_upload_pdf.py` (four tests, none existed); two-tenant isolation over a pasted page and a PDF (listing, search, Q&A scope, empty scope); `test_visibility_service.py`; chunker and metadata-helper tests for `document_id`
- [x] T-5.10.4.7 *(found)* `insert_chunks` skipped every chunk without a `video_id`, so no non-video document had ever been embedded. Keyed on `_chunk_storage_key` now
- [x] T-5.10.4.8 *(found)* `query_collection` turned an empty scope into an unrestricted search; `document_ids=[]` returns nothing, pinned at the service
- [x] T-5.10.4.9 *(found)* Job Q&A filtered on `JobVideo.video_id`; now passes the approved `document_id` set so a topic job's Reddit / HN / PDF documents are retrievable (`run_qa_agent(document_ids=...)`)

#### S-5.10.5 ⚪ Remaining readers keyed on the legacy `video_id`
**PR:** TBD. Filed 2026-10-19 while shipping S-5.10.4 (PR [#241](https://github.com/khoks/VideoResearchPro/pull/241)); listed there as follow-ups rather than widened into that PR.
**Linked decision:** [D-070](decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19)
**Scope.** Two readers still key on `documents.video_id`, which is NULL for every non-video source, so they silently omit PDFs, pasted pages, Reddit and HN documents; and the D-070 chunk backfill only runs where the API lifespan runs.
**Tasks**
- [ ] T-5.10.5.1 `services/dataset_service.py` derives knowledge-export ownership from `JobVideo.video_id` (pre-D-063 shape): non-video documents never export, and nor does any PDF or pasted page, which has no job. Filter through `visibility_service.visible_document_ids` instead; add a test with a PDF that carries a knowledge report
- [ ] T-5.10.5.2 Run `chroma_service.backfill_chunk_document_ids` on Celery worker startup as well as in the API lifespan: a worker-only start after the upgrade leaves pre-2026-10-19 chunks unretrievable until the API boots once
- [ ] T-5.10.5.3 `temporal_service.known_eras_for` is keyed on YouTube ids by design (search candidates are not documents yet) — confirm and note it in the function docstring so the next audit does not re-flag it

#### S-5.10.6 🟢 Close three cross-tenant reads S-5.10.1 missed — shipped 2026-10-19
**PR:** [#248](https://github.com/khoks/VideoResearchPro/pull/248). Found by auditing every `documents` reader on master after S-5.10.4 merged, at the request of the session driving the backlog.
**Linked decision:** [D-063](decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31) (amended 2026-10-19 (II))
**Acceptance (met).** Each read below 404s for a tenant who did not ingest the document or own the job, indistinguishably from a missing id, and the owner's access is unchanged. Each fix has a two-tenant test that fails on the unfixed code.
**Tasks**
- [x] T-5.10.6.1 `GET /videos/{id}/knowledge` and `POST /videos/{id}/extract-knowledge` looked the document up by `video_id` with no tenant check: any signed-in user could read another tenant's knowledge report, or spend an extraction on a document only another tenant had ingested. Both now resolve through the new `visibility_service.visible_document`, which also accepts the `document_id`
- [x] T-5.10.6.2 `GET /library/pdf/{digest}.pdf` checked only that the PDF existed: anyone holding the digest got another tenant's file. Now filtered on the caller's visible set
- [x] T-5.10.6.3 The Author Studio book outputter loaded each source job by id alone, so a book listing another user's job id compiled that user's topic and report. The tenant is now part of the lookup
- [x] T-5.10.6.4 `note_service._visible_document` delegates to the shared helper instead of carrying its own copy

### E-5.1 🟢 `tenant_id` audit + retrofit

**Scope.** Add `tenant_id` / `workspace_id` columns to every user-scoped table; convert today's implicit JWT scoping to an explicit column for future per-tenant rate limiting + multi-workspace.

**Closed 2026-05-04.** Five PRs ship the four-phase tenancy retrofit per the [D-038](decisions.md#d-038--tenancy-retrofit-ships-in-four-phases-audit--additive--backfillwrites--reads--not-null-2026-05-04) sequencing:

- **Phase 0** ([PR #149](https://github.com/khoks/VideoResearchPro/pull/149)) — [`docs/saas-tenant-id-audit.md`](saas-tenant-id-audit.md). Headline finding: codebase is structurally single-tenant despite JWT auth.
- **Phase 1** ([PR #150](https://github.com/khoks/VideoResearchPro/pull/150)) — Alembic migration `d5e6f7a8b9c0_add_tenant_id_columns.py` adds NULLABLE `tenant_id String(36)` + index to `jobs` / `qa_exchanges` / `library_qa_exchanges` / `qa_history_exchanges`. ORM models updated. Purely additive — no behaviour change.
- **Phase 2a** ([PR #151](https://github.com/khoks/VideoResearchPro/pull/151)) — Backfill migration `b2c3d4e5f6a7_backfill_tenant_id.py` sets `tenant_id = first-user.id` WHERE NULL. Every write-side router stamps `tenant_id=current_user.id` from `Depends(get_current_user)`. After this PR, every existing row is attributed AND every new row is correctly attributed.
- **Phase 2b** ([PR #152](https://github.com/khoks/VideoResearchPro/pull/152)) — `get_job(db, job_id, tenant_id=None)` + `get_jobs(...)` accept the optional filter. Routers thread `tenant_id=current_user.id`. Cross-tenant reads return 404 (not 403) to avoid existence-leak. Codebase is now fully tenant-isolated on user-facing surfaces.
- **Phase 2c** (this PR) — Operator-coordinated runbook [`docs/migration-tenant-id-not-null.md`](migration-tenant-id-not-null.md) + Alembic migration `e6f7a8b9c0d1_tenant_id_not_null.py`. Per [D-032](decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03) precedent, the migration ships in the codebase but is not auto-applied — operators run `alembic upgrade head` after running the runbook's pre-flight (verify zero NULL rows / backup / stop writers). Optional ORM-tightening (`Mapped[str | None]` → `Mapped[str]`) deferred to a calm follow-up PR.

**Tasks**
- [x] T-5.1.0 Audit doc — *shipped 2026-05-04 in `docs/saas-tenant-id-audit.md`.*
- [x] T-5.1.1 Phase 1 additive columns + indexes — *shipped 2026-05-04 in [PR #150](https://github.com/khoks/VideoResearchPro/pull/150).*
- [x] T-5.1.2 Phase 2a/2b — backfill + write-side stamping + read-side filter — *shipped 2026-05-04 in [PR #151](https://github.com/khoks/VideoResearchPro/pull/151) + [PR #152](https://github.com/khoks/VideoResearchPro/pull/152).*
- [x] T-5.1.2c Phase 2c — NOT NULL constraint runbook + migration — *shipped 2026-05-04. Operator-coordinated per D-032 precedent; the codebase delivers the safe-execution path, the operator owns the timing.*
- [ ] T-5.1.3 🔴 Phase 3 (deferred) — `tenants` + `tenant_users` tables for multi-user-per-workspace. Only needed for team SaaS tier.

**Linked decision:** [D-038](decisions.md#d-038--tenancy-retrofit-ships-in-four-phases-audit--additive--backfillwrites--reads--not-null-2026-05-04)

### E-5.2 🟡 Subscription tier gating

**Scope.** Free / Pro / Studio tiers with explicit YouTube quota allocation, LLM token budget, document-count cap, feature gating (Author Studio = Pro+).

**Foundation shipped 2026-05-04.** `users.tier String(16)` column with `server_default='free'` (Alembic `f7a8b9c0d1e2`); `Tier` enum + `TIER_CAPABILITIES` table + `require_tier(min_tier)` / `require_feature(name)` FastAPI dependencies in `backend/app/services/tier_service.py`. 24 new tests; backend suite 777 → 801. **Quota enforcement (runtime metering + 429 on exceeded) deferred to E-5.5** since rate limiting and quota enforcement share infrastructure.

**Tasks**
- [x] T-5.2.1 Add `tier` column to `users` table — *shipped 2026-05-04*.
- [x] T-5.2.2 `Tier` enum + capability table + FastAPI dependency factories — *shipped 2026-05-04*.
- [x] T-5.2.3 Document tier capabilities in `saas-roadmap.md` — *shipped 2026-05-04*.
- [x] T-5.2.4 Partial-permanent. *`require_feature("byok_llm_keys")` already gates the BYOK credentials router (PR #158). Remaining wires happen as L2 (Author Studio, I-6) and L3 (Echo personal-brain, I-3) endpoints land — every new tier-gated endpoint adds a `Depends(require_tier(...))` or `Depends(require_feature(...))` at definition time, so this task closes incrementally rather than as one PR.*
- [x] T-5.2.5 Quota runtime metering — *shipped 2026-05-05 (combined with T-5.5.5). New `quota_usage` table + `app/services/quota_metering_service.py` with `record_usage`, `get_usage`, `get_all_usage`, `check_quota`, `enforce_quota_or_raise`. Resource keys: `qa_exchanges` (monthly), `library_qa_exchanges` (monthly), `qa_history_chats` (monthly), `knowledge_extractions` (monthly), `documents` (lifetime), `llm_tokens_in/out` (daily), `youtube_units` (daily). New `qa_exchanges_per_month` + `knowledge_extractions_per_month` keys added to `TIER_CAPABILITIES` (Free 50 / Pro 1000 / Studio unlimited; Free 10 / Pro 200 / Studio 2000 respectively). Wired enforcement at the four hot endpoints: `/jobs/{id}/qa`, `/library/qa`, `/qa-history/chat`, `/videos/{id}/extract-knowledge`. New `GET /auth/quota` endpoint returns the user's full usage snapshot. 20 new tests; backend suite 929 → 949. **Linked decision:** [D-045](decisions.md#d-045--quota-metering-enforce-before-record-after-success-2026-05-05) — enforce-before / record-after-success sequencing.*
- [x] T-5.2.6 🟢 **Tier-visibility UI + self-service tier flip shipped 2026-05-15.** Public marketing pages (`/landing`, `/pricing`) accessible to anyone; in-app `/account/subscription` page with current-tier highlight + mock-payment modal for upgrades + downgrade-confirmation modal listing features lost. New backend endpoint `PUT /api/v1/auth/me/tier` flips `users.tier` immediately (mock-payment-mode) and writes a `tier_changed` audit_log event. New stub frontend pages for Echo (`/echo` — Studio-only, exercises shipped CRUD on `personal_context`) and Author Studio (`/author` — Pro+, exercises shipped Book v1 outputter). Sidebar nav reveals Author / Echo links based on `useTierCapabilities()` mirror of `TIER_CAPABILITIES`; "Subscription" link in Account group shows current tier as a pill badge. 9 new backend tests + frontend type-check clean. **Linked decision:** [D-050](decisions.md#d-050--self-service-tier-flip-with-mock-payment-until-e-53-stripe-ships-2026-05-15) — mock payment + endpoint stability across the future Stripe migration.
- [x] T-5.2.7 🟢 LLM token accounting — *shipped 2026-07-22, PR [#189](https://github.com/khoks/VideoResearchPro/pull/189) (checkbox reconciled 2026-10-18). `qa_exchanges.prompt_tokens` / `completion_tokens` now populated; per-user `llm_tokens_in` / `llm_tokens_out` metering recorded on the Q&A path (feeds the existing daily quota keys from T-5.2.5). Per-JOB LLM spend ⚪ deferred — needs a `jobs` schema column.*

### E-5.3 ⚪ Stripe integration

**Scope.** Subscription, metered overage, team billing.

**Design-complete 2026-05-04.** Full design lives in [`docs/saas-roadmap.md` §3](saas-roadmap.md#3-billing) — provider, customer / subscription objects, webhook endpoint shape, metered-overage rules, self-host kill switch (`BILLING_ENABLED=false`). **Code deferred until SaaS launch is funded** — self-host has no use for billing (everyone's tier is operator-controlled), so shipping Stripe today buys nothing while costing maintenance. Schema fields (`tenants.billing_customer_id`, `tenants.billing_subscription_id`) will land alongside the `tenants` table when T-5.1.3 ships.

**Tasks**
- [ ] T-5.3.1 ⚪ **Replace mock-payment with Stripe Checkout (resolves D-050).** When SaaS launches, swap `PUT /api/v1/auth/me/tier`'s implementation from "trust the request" to "verify Stripe webhook signature on `checkout.session.completed` → update tier". Frontend swaps the `MockPaymentModal` for a Stripe Checkout redirect; the rest of the in-app `/account/subscription` UI is unchanged (TierCard grid, downgrade modal, capability-aware nav). Self-host operators retain the existing mock-payment path via `ENABLE_SELF_SERVICE_TIER_FLIP=true` flag (default in SaaS: `false`). Blocked-on the rest of E-5.3 landing first (Stripe customer/subscription objects, webhook endpoint, kill switch).

### E-5.4 🟡 Auth hardening

**Scope-changed 2026-10-19:** 🟢 → 🟡. Research for M11 found that `python-jose` 3.5.0 (the latest release, 2025-05-28) carries CVE-2026-85394 (CVSS 9.3, published 2026-09-03, no fixed version): a DER-encoded public key is accepted as an HMAC secret, an incomplete fix of CVE-2024-33663. The app decodes JWTs with it in `auth_service.py`, `mfa_service.py` and `middleware/rate_limit.py`. All three sites pin `algorithms=[settings.JWT_ALGORITHM]`, which neutralises the known confusion path, but the dependency is unfixed and effectively unmaintained.
- [x] T-5.4.9 🟢 **Shipped 2026-10-19 — PR [#232](https://github.com/khoks/VideoResearchPro/pull/232).** Found on the way: the dev `.env` had `JWT_SECRET=` blank and python-jose had been signing every token with an empty HMAC key; PyJWT refuses, and a config validator now maps blank to the dev default with a loud warning. Replace `python-jose` with `PyJWT` (MIT, actively released) at the three call sites, keep `algorithms` pinned, keep the `jti` session semantics; one PR, tests unchanged. M11 share tokens must never be JWTs regardless

**Scope.** OAuth (Google / GitHub), MFA, session management, password reset, account lockout, audit log.

**Phase 1 shipped 2026-05-04.** The defensive primitives — credential-stuffing defence (lockout), self-service recovery (password reset), and observability (audit log) — ship in one PR. Remaining auth-hardening work is OAuth and MFA, deferred to dedicated PRs since each has substantial provider-specific complexity.

- **Audit log** — new `audit_log` table + `app/services/audit_service.py` with the canonical `Event` enum (USER_REGISTERED / LOGIN_SUCCESS / LOGIN_FAILURE / LOGIN_LOCKED_OUT / ACCOUNT_LOCKED / PASSWORD_RESET_REQUESTED / PASSWORD_RESET_COMPLETED / PASSWORD_RESET_INVALID_TOKEN). Recorded on every auth event with IP, user-agent, structured metadata. `GET /api/v1/auth/audit-log` returns the current user's events (newest first; capped at 500/page).
- **Account lockout** — `users.failed_login_attempts INT NOT NULL DEFAULT 0` + `users.locked_until DATETIME NULL`. After `LOCKOUT_FAILURE_THRESHOLD` (default 5) failures, the account is locked for `LOCKOUT_DURATION_MIN` (default 15) minutes. Successful login resets both columns. **Unknown emails do NOT create User rows** (a critical-correctness check — otherwise an attacker could lock arbitrary accounts by trying any email). `authenticate_user_v2` returns a structured `AuthOutcome` so the router can audit lockouts separately from invalid creds while still serving a generic 401.
- **Password reset** — new `password_reset_tokens` table (single-use, SHA-256 hashed; raw secret never stored). `POST /api/v1/auth/password-reset/request` returns 200 unconditionally (never leaks whether the email exists); on self-host the secret is returned in `debug_secret` and logged so operators can hand it off out-of-band when SMTP isn't configured. `POST /api/v1/auth/password-reset/confirm` rotates the password + clears any active lockout. Tokens expire after `PASSWORD_RESET_TOKEN_TTL_MIN` (default 30) minutes.

22 new tests; backend suite 801 → 823.

**Tasks**
- [x] T-5.4.1 Audit log table + service — *shipped 2026-05-04*.
- [x] T-5.4.2 Account lockout (`failed_login_attempts` + `locked_until` + threshold) — *shipped 2026-05-04. See [D-040](decisions.md#d-040--failed-logins-for-unknown-emails-do-not-create-user-rows-lock-arbitrary-account-defence-2026-05-04) for the lock-arbitrary-account defence invariant.*
- [x] T-5.4.3 Password reset flow (request + confirm + token table) — *shipped 2026-05-04*.
- [x] T-5.4.4 `GET /auth/audit-log` per-user read endpoint — *shipped 2026-05-04*.
- [x] T-5.4.5 OAuth (Google + GitHub) — *shipped 2026-05-05. OAuth 2.0 + PKCE flow with two configured providers (config-driven, adding a third is ~30 lines). New tables `oauth_states` (10 min TTL, single-use, S256 PKCE verifier persisted) + `oauth_identities` (`(provider, provider_user_id)` unique). New endpoints: `GET /auth/oauth/providers`, `GET /auth/oauth/{provider}/start`, `GET /auth/oauth/{provider}/callback`. First OAuth login finds-or-creates the User by email; existing-email users get the identity linked to their existing account (no duplicates). All callback failures return generic 401 (don't leak which step failed). 14 new tests with mocked provider responses; backend suite 915 → 929. **E-5.4 fully closed** — all 8 tasks done. **Linked decision:** [D-042](decisions.md#d-042--oauth-first-login-links-to-existing-user-by-email-2026-05-05) — email-based linking trade-off + provider verification expectations.*
- [x] T-5.4.6 MFA (TOTP) — *shipped 2026-05-05. RFC 6238 TOTP via `pyotp`. New `mfa_secrets` table (encrypted secret + JSON-hashed recovery codes; Alembic `d1e2f3a4b5c6_mfa_secrets_table.py`). Endpoints: `POST /auth/mfa/enroll` (returns `secret` + `provisioning_uri` for QR rendering), `POST /auth/mfa/verify-enrollment` (validates first TOTP code → enabled=True; returns 10 single-use recovery codes ONCE), `GET /auth/mfa/status`, `DELETE /auth/mfa` (requires valid TOTP / recovery code), `POST /auth/login/mfa` (second-step using short-lived 5-min mfa_token from /auth/login). Login flow change: when MFA is enabled, `/auth/login` returns `MfaRequiredResponse` instead of `TokenResponse`; client must call `/auth/login/mfa` with the returned mfa_token + a code to receive the real access token. ±1 TOTP window for clock skew. Encryption reuses BYOK Fernet key (see [D-043](decisions.md#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05) for the single-shared-key rationale). 13 new tests; backend suite 902 → 915.*
- [x] T-5.4.7 Session management (revoke individual sessions, list active sessions, logout everywhere) — *shipped 2026-05-05. New `sessions` table keyed on JWT `jti` claim (Alembic `c0d1e2f3a4b5_sessions_table.py`); login writes a row + captures IP/User-Agent; `dependencies.get_current_user` validates the row is not revoked on every authenticated request. New endpoints: `GET /auth/sessions`, `DELETE /auth/sessions/{jti}` (404 on cross-user — existence-leak posture), `DELETE /auth/sessions?keep_current=true|false` (logout everywhere with the "keep current" UX), `POST /auth/logout`. Revocation is via `revoked_at` timestamp (audit trail preserved). Pre-T-5.4.7 tokens (no jti claim, no session row) keep working until they expire — back-compat. 12 new tests; backend suite 890 → 902.*
- [x] T-5.4.8 SMTP integration (deliver password-reset secrets via email) — *shipped 2026-05-05. New `app/services/email_service.py` with pluggable SMTP backend (host / port / username / password / SSL / STARTTLS / from-address config) + log-fallback when `SMTP_HOST` unset. Password-reset endpoint now: (a) renders email via `render_password_reset_email`, (b) sends via `email_service.send_email` (SMTP when configured, log otherwise), (c) returns `debug_secret` ONLY when SMTP is unconfigured (self-host operator handoff). On SaaS / SMTP-configured deployments, the secret is never in the response — email is the only delivery channel. 11 new tests; backend suite 879 → 890.*

### E-5.5 🟢 Abuse prevention

**Scope.** Rate limits, fraud detection, content policy, takedown process for shared reports.

**Phase 1 shipped 2026-05-04.** Rate-limit middleware enforces per-route + per-tier caps via an in-memory sliding-window counter. Fraud detection / content policy / takedown remain ⚪ (each is a SaaS-launch concern).

- **`backend/app/services/rate_limit_service.py`** — sliding-window counter with `RateLimit(requests, window_sec)` config + `check_and_consume(key, limit) -> (allowed, count, retry_after_sec)`. Thread-safe via `threading.Lock`; auto-prunes expired buckets. In-memory by design (single-process self-host); Redis-backed swap is one-function for SaaS multi-worker deployment per the docstring.
- **`backend/app/middleware/rate_limit.py`** — FastAPI middleware applied early. Three-tier strategy: (1) sensitive endpoints (`/auth/login`, `/auth/password-reset/{request,confirm}`, `/auth/register`) get tight per-IP buckets that fire BEFORE auth so they defend against credential-stuffing / brute-force / mass-reset attacks; (2) authenticated routes consume from per-user buckets sized by tier (Free/Pro/Studio scale 60/600/6000 req/min); (3) unauthenticated GETs use a per-IP fallback. Returns `429` with `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`. Disabled in tests via `RATE_LIMIT_ENABLED=False` (set in conftest); individual tests opt back in.
- **JWT pre-parse for bucket key** — middleware decodes the bearer token to extract user_id without a DB lookup; stable bucket key without slowing the request path.
- **Config knobs** — `RATE_LIMIT_ENABLED`, `RATE_LIMIT_PER_MIN_FREE/PRO/STUDIO`, `RATE_LIMIT_PER_MIN_UNAUTH`, `RATE_LIMIT_LOGIN_PER_MIN`, `RATE_LIMIT_RESET_PER_MIN`, `RATE_LIMIT_REGISTER_PER_MIN`.

12 new tests; backend suite 823 → 835.

**Tasks**
- [x] T-5.5.1 In-memory sliding-window rate-limit service — *shipped 2026-05-04. See [D-039](decisions.md#d-039--in-memory-rate-limit-backend-as-the-default-redis-swap-deferred-to-multi-worker-saas-2026-05-04) for the in-memory-vs-Redis design decision.*
- [x] T-5.5.2 FastAPI middleware with per-route + per-tier strategy — *shipped 2026-05-04*.
- [x] T-5.5.3 Sensitive-endpoint hardening (login / reset / register) — *shipped 2026-05-04*.
- [ ] T-5.5.4 🔴 Redis-backed bucket store for multi-worker SaaS deployment — *deferred per [D-039](decisions.md#d-039--in-memory-rate-limit-backend-as-the-default-redis-swap-deferred-to-multi-worker-saas-2026-05-04) until multi-worker SaaS lands. In-memory backend is correct for single-worker self-host; swapping to Redis prematurely is gold-plating without a consumer.*
- [x] T-5.5.5 Quota enforcement — *shipped 2026-05-05 (combined with T-5.2.5; see that entry for full detail). 429 with `Retry-After` header + structured `detail` body (`{error, resource, consumed, limit, retry_after_sec, retry_at}`) on cap-exceeded. enforce_quota_or_raise runs BEFORE the expensive agent at every hot endpoint.*
- [ ] T-5.5.6 🔴 Content policy + takedown workflow for shared reports — *deferred. Blocks on [M11 public report sharing](feature-roadmap.md#m11--public-report-sharing-) — there's no shared-report surface to apply takedown logic to until M11 ships.*
- [ ] T-5.5.7 🔴 Fraud detection (anomalous-pattern alerting) — *deferred. Needs real production traffic + accumulated abuse signal data before pattern definitions are useful. Premature without it.*

### E-5.6 🟢 Background-job isolation

**Scope.** Celery queues per tenant or per tier; per-tenant LLM keys (BYOK pattern, reuse from D-009); per-tenant ChromaDB tenancy.

**BYOK foundation shipped 2026-05-04.** Per-user, per-provider API keys with encryption-at-rest. Power users on the Studio tier can route their LLM calls to their own provider account.

- **`backend/app/models/user_credential.py`** — `(user_id, provider)` unique; `encrypted_secret Text` (Fernet ciphertext, plaintext never persisted); `label`, `created_at`, `updated_at`.
- **`backend/app/services/byok_service.py`** — `cryptography.fernet.Fernet`-based encrypt/decrypt keyed off `BYOK_ENCRYPTION_KEY`. CRUD: `set_credential`, `get_credential`, `list_for_user`, `delete_credential`. Provider validation against `SUPPORTED_PROVIDERS` (`openai` / `anthropic` / `google` / `local` — matches `llm_routing.py` provider table). Encryption-key rotation tolerance: `get_credential` returns `None` (with warning) when ciphertext is undecryptable so the consumer falls back to install-wide env-var keys.
- **`backend/app/routers/credentials.py`** — REST endpoints under `/api/v1/auth/credentials/*`, gated on `require_feature("byok_llm_keys")` (Studio-tier only). PUT for upsert; GET for list (metadata only — never the plaintext); DELETE for removal; `/providers` for the supported set.
- **20 new tests** covering encryption round-trip + non-determinism, CRUD upsert semantics, cross-user isolation, provider validation, key-rotation tolerance, auth + tier gating on every endpoint, plaintext-not-leaked invariant.

Backend suite 835 → 855.

**Tasks**
- [x] T-5.6.1 BYOK schema + service layer (encryption + CRUD) — *shipped 2026-05-04*.
- [x] T-5.6.2 Credentials REST router (Studio-gated) — *shipped 2026-05-04*.
- [x] T-5.6.3 Provider validation + encryption-rotation tolerance — *shipped 2026-05-04*.
- [x] T-5.6.4 LLM resolution-path integration — *shipped 2026-05-05. `llm_service.byok_context(tenant_id, db)` ContextVar set at every router/Celery boundary; `get_llm_for(...)` reads from the context (or explicit kwargs in tests) and threads the BYOK key into the resolved provider client. Tier-gated to Studio (Free / Pro tiers ignore stored credentials — defense-in-depth on tier downgrades). Local provider ignored (install-wide infrastructure). Encryption-rotation tolerant (decrypt-fail returns None → env-var fallback). Wired at: `routers/qa.py`, `routers/library.py`, `routers/qa_history.py`, `routers/knowledge.py`, plus Celery search-agent + report-agent paths in `tasks/job_tasks.py` (using `job.tenant_id` from E-5.1 phase 2a stamping). 15 new tests; backend suite 864 → 879. **Linked decision:** [D-041](decisions.md#d-041--contextvar-plumbing-vs-explicit-kwargs-for-cross-cutting-per-user-state-2026-05-05) — ContextVar pattern for cross-cutting per-user state.*
- [x] T-5.6.5 Per-tenant Celery queue routing — *shipped 2026-05-05. New `app/services/task_routing_service.py` with `queue_for_user(user)`, `queue_for_tier(tier)`, `queue_for_tenant_id(db, tenant_id)`, `dispatch_for_user(task, user, *args, **kw)`, `dispatch_for_tenant_id(task, db, tenant_id, *args, **kw)`. Three tier queues (`tier_free`, `tier_pro`, `tier_studio`) plus a `default` fallback for system tasks. Wired at every Celery dispatch site in `routers/jobs.py` (topic / channel / subscription / resume) + `routers/channels.py` (subscribe / sync). Self-host: one worker handles all queues. SaaS-launch posture: split worker pools per queue for Studio-tier-latency-isolation. 10 new tests; backend suite 949 → 959.*
- [x] T-5.6.6 Per-tenant ChromaDB tenancy on `qa_library_global` — *shipped 2026-05-05. Closes a real cross-tenant leak in the Q&A History meta-chat: PR #152 filtered SQL reads by tenant_id but the Chroma similarity search bypassed that filter, so a meta-chat question could surface other users' Q&A. Fixed via `metadata.tenant_id` propagation in upsert + `tenant_id` filter on every `query_qa_collection` call. The global document collection (`videoresearchpro_global`) stays unfiltered by design — that's the deduplicated library, not user-scoped data.*

### E-5.7 ⚪ Data residency

**Scope.** Region-selectable storage (EU / US / etc.).

**Design-complete 2026-05-04.** Full design in [`docs/saas-roadmap.md` §6 → Data residency](saas-roadmap.md#data-residency). Pure-SaaS-launch concern — a single-machine self-host install has its data in exactly one place by definition. The `tenants.region` column lands with T-5.1.3; region-specific stack provisioning is operations work, not code work. **No code change today.**

### E-5.8 ⚪ Hosting / infra

**Scope.** Postgres for SQLite, Redis cluster, ChromaDB managed or pgvector, S3 for reports, CDN for static.

**Design-complete 2026-05-04.** Full target topology in [`docs/saas-roadmap.md` §6 → SaaS (target)](saas-roadmap.md#saas-target). The matrix is the *target*; every row is a swap from the self-host equivalent. None of these swaps make sense for a single-machine self-host install. **The few code touches that ARE forward-looking** (e.g. Postgres compatibility on the SQLAlchemy layer, S3-not-local-disk for outputs) **are tracked under their respective L1/L2 epics**, not E-5.8. The scope of E-5.8 itself is *operations work* (Cloud SQL provisioning, Redis Cluster setup, CDN config), executed at SaaS launch time, not code work.

### E-5.9 ⚪ Hosted UX

**Scope.** Landing page, signup, billing portal, support, status page.

**Design-complete 2026-05-04.** Full design in [`docs/saas-roadmap.md` §7](saas-roadmap.md#7-hosted-ux). The marketing landing page already ships ([E-2.5](#e-25--marketing-landing-page-warm-editorial)) — the only piece of "hosted UX" with code today. The signup flow / billing portal / status page / docs site are all SaaS-launch-time work, gated on E-5.3 (billing) and SaaS infrastructure (E-5.8). **No code change today.**

---

## I-6 🟡 Author Studio (output generation L2)

**Why it exists.** The accumulated library is rich enough to produce books, sites, decks, newsletters, reels — not just answers. Closes the loop: ingest → understand → produce.
**North-star doc:** [feature-roadmap.md L2](feature-roadmap.md#l2--author-studio-output-generation-) · **Plan:** [`docs/plans/l2-author-studio.md`](plans/l2-author-studio.md) · **Sequence:** [`docs/plans/build-order.md`](plans/build-order.md)
**Decision links:** [D-044](decisions.md#d-044--foundation-first-then-concrete-implementations-deferred-for-i-3--i-6-2026-05-05), [D-069](decisions.md#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19)
**Status:** 🟡 foundation shipped 2026-05-05. Schema + Outputter Protocol + lifecycle + REST surface + tier gating + first concrete outputter (Book v1 Markdown) all live. Sites / decks / newsletters / reels are E-6.2/.3/.4/.5 follow-ups that plug into the same registry. Per [D-044](decisions.md#d-044--foundation-first-then-concrete-implementations-deferred-for-i-3--i-6-2026-05-05), the foundation ships with one minimum-viable outputter (deterministic Book v1) so the abstraction is validated end-to-end with real content; LLM cohesion + the other kinds are individually-scoped follow-ups.

**Planned 2026-10-18.** Every epic below now carries a scope, an acceptance statement and PR-sized stories; the research behind the choices (PDF and EPUB toolchains, site generation without Node, python-pptx, scheduler, TTS providers, the B-roll licensing risk) is in the plan. Two corrections from the code audit:
- The stub `/author` page of 2026-10-18 **could not produce a successful book**: it posted `{kind, title}` with no `source_ids`, and `BookMarkdownOutputter.generate` raises `OutputError` on an empty list, so every output created from the UI landed as `failed`. PR [#224](https://github.com/khoks/VideoResearchPro/pull/224) replaced it on 2026-10-19 with a chapter picker ([D-069](decisions.md#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19)); S-6.1.1 now carries only the remainder.
- The roadmap's `output_citations` table and `GET /outputs/{id}/download` were never built; `outputs` has `content_text` / `content_path` only, generation is synchronous inside the request, and there is no Celery task for outputs. Carried by E-6.7.

### E-6.1 🟡 Books (long-form Markdown → PDF / EPUB)

**v1 shipped 2026-05-05** in PR #173. `BookMarkdownOutputter` performs deterministic structural concatenation of selected job reports + per-job Q&A history into a Markdown manuscript with TOC. No LLM in v1 — that's the point: validate the schema + lifecycle + REST surface end-to-end before adding cohesion.

**Scope (2026-10-18).** Make the book real: a source picker, a true Markdown source for reports, an LLM cohesion pass, endnote citations with deep links, and PDF / EPUB downloads. Books are the first Author kind to finish because every other kind reuses its pieces (Markdown source, citation contract, async generation).
**Acceptance.** A user picks three completed jobs, titles the book, and gets a manuscript with an LLM-written introduction, ordered chapters with transitions, a glossary, numbered endnotes that deep-link to timestamps, and a downloadable PDF and EPUB; generation runs in the worker with progress; a failed chapter is disclosed in the manuscript rather than silently dropped (the D-056 posture).

**Tasks (epic-level, pre-2026-10-18 numbering kept)**
- [x] T-6.1.1 v1 deterministic Markdown bundle — *shipped 2026-05-05*.
- [ ] T-6.1.2 ⚪ LLM-driven cohesion (chapter ordering, transition prose, auto-generated introductions, glossary extraction). *Now S-6.1.3.*
- [ ] T-6.1.3 ⚪ PDF conversion. *Now S-6.1.5 (the plan rejects `anthropic-skills:docx` and `pypandoc` as the primary path; see plan).*
- [ ] T-6.1.4 ⚪ EPUB conversion. *Now S-6.1.5.*
- [x] T-6.1.5 🟢 Frontend "Author Studio" surface — *shipped 2026-10-19 PR [#224](https://github.com/khoks/VideoResearchPro/pull/224). Scope moved from "a Pro+ button on a job page" to the full `/author` page, because a book spans several runs. Kinds come from `GET /author/kinds`: `available` kinds get a create flow, the rest render as "Coming later · E-6.x" with no button (a 501 is never offered). The create modal names the book, picks chapters from the user's finished topic / channel runs (runs without a report or not yet completed are listed but disabled, so the 501 / empty-chapter paths are unreachable from the UI), and toggles `include_qa` / `include_toc`. Outputs list with kind / status filters, failed rows show `error_message` in full, pending rows explain they were created when their kind had no generator. Reader modal renders the Markdown at reading measure; Download fetches `/content` with the bearer header and saves a blob (`<a href>` cannot carry the token); Delete confirms first. Tier-locked state when `has('author_studio')` is false or the API 403s. Linked decision: [D-069](decisions.md#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19). What remains of the original scope: the job-page shortcut and the server-side guard (S-6.1.1) and reading outputs in the shared reader shell (S-8.8.3).*

#### S-6.1.1 🟢 Source picker and a working Author page
**Scope-changed 2026-10-19:** the picker shipped in PR [#224](https://github.com/khoks/VideoResearchPro/pull/224) a day after this story was filed; what remains is below.
- [x] T-6.1.1.1 `AuthorPage` job picker sending `source_ids`; runs without a report are listed but disabled — *shipped 2026-10-19, PR #224*
- [x] T-6.1.1.2 "Add to a book" on `JobDetailPage` (completed runs with a report, `author_studio` tier) opens `/author?new=book&job=<id>`, which opens the create modal with that run pre-selected — *shipped 2026-10-19, PR [#255](https://github.com/khoks/VideoResearchPro/pull/255)*
- [x] T-6.1.1.3 Output row shows chapter count and word count (`OutputItem.word_count`, computed from the content); the page's reader renders the manuscript's GFM tables through `remark-gfm` — *shipped 2026-10-19, PR [#255](https://github.com/khoks/VideoResearchPro/pull/255)*. The moved "View opens the shared reader shell" part shipped with S-8.8.3 (PR [#261](https://github.com/khoks/VideoResearchPro/pull/261)): Read and a freshly generated book open `/author/outputs/:id`, and the page's own reader modal is gone.
- [x] T-6.1.1.4 The router rejects `kind=book` with an empty `source_ids` as 400 before any row is written (test asserts zero rows); frontend type-check and vitest pass — *shipped 2026-10-19, PR [#255](https://github.com/khoks/VideoResearchPro/pull/255)*

#### S-6.1.2 🟢 Markdown source for reports
**PR:** [#255](https://github.com/khoks/VideoResearchPro/pull/255) — *shipped 2026-10-19.* Shared enabler for the book, the reading room (E-8.8) and public sharing (E-8.11). Converter: `markdownify` (MIT) through a `ReportMarkdownConverter` subclass; html2text rejected as GPL-3.0. The tenant-scoped job lookup S-5.10.6 added to the outputter is kept. Linked decision: [D-079](decisions.md#d-079--report-markdown-source-on-markdownify-new-report-routes-are-header-bearer-only-2026-10-19).
- [x] T-6.1.2.1 `report_service.report_markdown(job)` / `html_to_markdown(html)`: drops the document head and stylesheet, ATX headings, hyphen bullets, no `*`/`_` escaping, no autolinks (a citation stays `[text](href)` with its `&t=`), the statistics grid as a one-row table, `[VISUAL @ …]` spans verbatim; cached at `<report_path>.md`, rewritten when older than the HTML; an unwritable cache degrades to converting every time; `delete_report` removes the cache too — *shipped 2026-10-19*
- [x] T-6.1.2.2 `BookMarkdownOutputter` reads it; the report's H1 (which repeats the chapter title) is dropped and its headings demoted two levels under the chapter's H2; a missing report or file is disclosed in the manuscript; `_strip_html_to_markdownish` retired — *shipped 2026-10-19*
- [x] T-6.1.2.3 `GET /api/v1/jobs/{id}/report.md` in `routers/reports.py`, `text/markdown`, tenant-scoped 404s. **Auth deviates from the story text:** header-bearer only, no `?token=`, following the posture S-8.8.1 (merged first) set for every new report route to keep tokens out of URLs; a test pins that a query token alone gets 401 — *shipped 2026-10-19*
- [x] T-6.1.2.4 Round-trip tests on three stored real reports (`backend/tests/fixtures/reports/`: a three-video run with 30 citations, a run with 83, a run with no transcripts) plus one synthetic report built by the production template: every H1–H3 present as ATX, every `&t=` href preserved, one table per HTML table plus the grid, no stylesheet or tag text — *shipped 2026-10-19*

#### S-6.1.3 🔵 LLM cohesion pass
**PR:** TBD. Absorbs T-6.1.2.
- [ ] T-6.1.3.1 `author_book_outline` use case: given chapter summaries, return order, part grouping, one-paragraph transitions, introduction and conclusion briefs (structured JSON)
- [ ] T-6.1.3.2 `author_book_prose` use case: write introduction, transitions, conclusion and glossary from the outline plus source excerpts; `VISUAL_ANNOTATION_CONTRACT` and the English-output contract injected ([D-066](decisions.md#d-066--language-contract-temporal-awareness-and-corpus-aware-qa-length-2026-07-31))
- [ ] T-6.1.3.3 Chapter bodies stay the report Markdown (never rewritten by the LLM, so citations cannot be invented); an in-manuscript processing note discloses any failed call
- [ ] T-6.1.3.4 `parameters_json` gains `cohesion: "none" | "light" | "full"`; `none` is the shipped v1 path
- [ ] T-6.1.3.5 Cost estimate per book surfaced before generation via `cost_estimator`
- [ ] T-6.1.3.6 Tests with the LLM factory patched; golden manuscript on a two-job fixture

#### S-6.1.4 🟢 Endnote citations
**PR:** [#PR_S614](https://github.com/khoks/VideoResearchPro/pull/PR_S614) — *shipped 2026-10-19.* Endnotes are GFM footnotes (`[^n]`), which the reading room (remark-gfm), GitHub and the EPUB/PDF converters all render as linked superscripts with back-links; endnote `n` is always `output_citations` position `n`. Found while testing: a tight list (items without blank lines) let a later item's bare anchor borrow an earlier item's title; citation context is now the list item, as the reader's `<li>`.
- [x] T-6.1.4.1 `cite_markdown` rewrites every citation in a chapter as its working link plus `[^n]` (a resolved bare `&t=` anchor gets its rebuilt URL; an unresolved one keeps its label and loses the dead link), numbered across chapters in reading order; `endnote_definitions` writes `[^n]: *Title* — Channel, m:ss. <url>` under `## Endnotes`, or `Source not identified (cited as …)` — *shipped 2026-10-19*
- [x] T-6.1.4.2 `cite_references` cites each answer from its stored `references` (`Sources: [1:35](url)[^31], …`); links in the answer prose are reduced to text; a reference resolves to a document only if it is among the run's visible documents, otherwise it keeps its own link, title and channel — *shipped 2026-10-19*
- [x] T-6.1.4.3 Tests: on two real-report chapters, references run 1..60 in reading order, one definition each, matching `output_citations` positions, with title, channel, timestamp and URL; every link in the manuscript is absolute or an in-page anchor to an existing heading; unresolved citations disclosed; Q&A cited from references; tight and loose list contexts; a vitest renders a book through the reading room's own parser and finds every footnote and TOC target — *shipped 2026-10-19*
- [x] T-6.1.4.4 *Shipped 2026-10-19: the TOC links to `heading_slug("n. Title")`, a port of the reader's slug, so `#1-first-topic` (and Devanagari ids) exist in the reader, on GitHub and in the EPUB/PDF HTML.* Table-of-contents links resolve: today the TOC links `#first-topic` while the chapter heading is `## 1. First Topic`, whose generated id differs; fold into the no-dead-links test. Filed 2026-10-19 by S-6.1.2; [D-079](decisions.md#d-079--report-markdown-source-on-markdownify-new-report-routes-are-header-bearer-only-2026-10-19)

#### S-6.1.5 🔵 PDF and EPUB downloads
**PR:** TBD. Absorbs T-6.1.3 and T-6.1.4.
- [ ] T-6.1.5.1 Markdown → HTML (typographic stylesheet shared with the reader) → PDF through the converter chosen in the plan; `content_path` set; served by E-6.7's download endpoint
- [ ] T-6.1.5.2 EPUB 3 from the same HTML (converter chosen in the plan; licence recorded in `requirements.txt` comments as for PyMuPDF)
- [ ] T-6.1.5.3 Optional install: both converters live in `requirements-author.txt`; the outputter reports 501 with install instructions when missing (the Playwright precedent)
- [ ] T-6.1.5.4 Tests: generated files open (PDF page count, EPUB container validity); a Devanagari quote renders (font embedding)

### E-6.2 🔵 Static personal-wiki site

Outputter scaffolded by I-6 foundation; the schema's `kind="site"` is supported and the route returns 501 until an outputter ships.

**Scope (2026-10-18).** A downloadable static site built from a shelf or a set of jobs: one page per report (reader typography), one per knowledge artifact, an index, tag pages, client-side search, citation links out to sources. Built by the backend with Jinja2 templates, **not** by Astro or 11ty: the plan rejects a Node toolchain inside the Python worker. Hosting integrations are a later story.
**Acceptance.** A user picks a shelf, generates a site, downloads a zip, opens `index.html` from disk and can read every report, search by title, and follow citations; the site has no app chrome and makes no network calls except to sources.

#### S-6.2.1 🔵 `SiteOutputter` (zip of static HTML)
**PR:** TBD. Depends on S-6.1.2 (Markdown source) and S-8.1.1 (shelves) for the picker.
- [ ] T-6.2.1.1 `source_ids` accepts `shelf:<id>` and `job:<id>`; resolves to visible documents and the tenant's exchanges only
- [ ] T-6.2.1.2 Jinja2 templates under `app/templates/site/` (index, report, knowledge, tag, about) with the reader stylesheet inlined
- [ ] T-6.2.1.3 Client-side search index (prebuilt JSON + a small vanilla script; no CDN)
- [ ] T-6.2.1.4 Zip written to `content_path`; download through E-6.7
- [ ] T-6.2.1.5 Tests: every link inside the zip resolves; no absolute app URLs

#### S-6.2.2 ⚪ Publish integrations
- [ ] T-6.2.2.1 GitHub Pages push (user-supplied token through the BYOK credential store) and Netlify drop; design only until S-6.2.1 is used

### E-6.3 🔵 Slides (PPTX)

`kind="deck"` reserved; outputter pending.

**Scope (2026-10-18).** A deck from one job or a knowledge artifact: an LLM-planned outline (8 to 15 slides), each slide carrying its citations in the notes and a sources slide at the end, rendered with `python-pptx` (the `anthropic-skills:pptx` skill named in the roadmap is a harness skill, not a library the worker can call).
**Acceptance.** A user picks a job, gets a `.pptx` whose every content slide has at least one citation in its notes, and the sources slide lists every cited source with a link.

#### S-6.3.1 🔵 `DeckOutputter`
**PR:** TBD
- [ ] T-6.3.1.1 `author_deck_outline` use case (structured JSON: title, slides[{heading, bullets, speaker_notes, citations}])
- [ ] T-6.3.1.2 `python-pptx` renderer with one editorial template (title, section, bullets, quote, sources); brand tokens from `docs/branding.md`
- [ ] T-6.3.1.3 Citations copied into slide notes and the sources slide; `output_citations` rows
- [ ] T-6.3.1.4 Tests: slide count within bounds, notes non-empty, file opens

### E-6.4 🔵 Newsletter / digest (recurring scheduled output)

`kind="newsletter"` reserved; outputter pending.

**Scope (2026-10-18).** A periodic email digest: what entered the library since the last issue, new Q&As, a featured deep-dive (one report section or knowledge artifact), and pinned saved-search changes (E-8.3). Runs on the scheduler E-8.3 builds (S-8.3.1); sends through the existing `email_service`.
**Acceptance.** A user enables a weekly digest; an issue is generated and emailed every week with only material newer than the previous issue; an issue with nothing new is skipped and says so in the outputs list; the digest is also readable in-app as an output.

#### S-6.4.1 🔵 `NewsletterOutputter`
**PR:** TBD. Depends on S-8.3.1.
- [ ] T-6.4.1.1 `parameters_json` carries `since` (last issue timestamp) and section toggles; content from documents, exchanges and outputs newer than `since`, visible to the tenant
- [ ] T-6.4.1.2 `author_newsletter_compose` use case for the featured section only; the rest is deterministic
- [ ] T-6.4.1.3 Plain-HTML email template (no external CSS, inlined styles) plus a Markdown `content_text` for in-app reading
- [ ] T-6.4.1.4 Tests: `since` boundary, empty issue skipped

#### S-6.4.2 🔵 Subscription and delivery
**PR:** TBD
- [ ] T-6.4.2.1 `newsletter_subscriptions(id, tenant_id, cadence, sections_json, last_issue_at, enabled)` + REST + a toggle on the Author page
- [ ] T-6.4.2.2 Scheduler kind `newsletter` → generate output → `email_service.send_email` → in-app notification; idempotent per `(subscription, period)`
- [ ] T-6.4.2.3 Tests: one send per period; unsubscribe stops the next run
- [ ] T-6.4.2.4 Register the `newsletter` scheduler kind from its own task module and add the module to `celery_app.autodiscover_tasks`, as T-8.3.2.5 does for saved searches. Filed 2026-10-19 by S-8.3.1; [D-077](decisions.md#d-077--scheduler-one-static-beat-entry-over-table-rows-beat-is-its-own-process-with-no-pidfile-2026-10-19)

### E-6.5 ⚪ Video / reel (TTS narration + stills)

`kind="reel"` reserved; outputter pending. Heaviest of the kinds — requires a TTS provider + an ffmpeg pipeline.

**Scope (2026-10-18).** A short vertical video: an LLM-written script from a knowledge artifact or report section, narrated by TTS, over **stills the app already owns** (R1 `visual_frames` captured by E-1.18, generated title cards, and source thumbnails) with captions burned in. The roadmap's "clip-stitched B-roll from source videos" is **not** in v1: re-publishing downloaded YouTube video is a Terms-of-Service risk the plan records, and the stills path needs no new downloads.
**Status.** ⚪ proposed. Ships last; the TTS provider choice (local model for self-host, paid API for SaaS) is an open question in the plan.
**Acceptance.** A user picks a knowledge artifact, gets a 60 to 90 second 1080×1920 MP4 with narration, captions and a sources end-card; generation cost is shown beforehand; a missing TTS provider yields 501 with setup instructions.

#### S-6.5.1 ⚪ Script and storyboard
- [ ] T-6.5.1.1 `author_reel_script` use case: scenes[{narration, on_screen_text, source_ref, frame_hint}] within a duration budget
#### S-6.5.2 ⚪ Narration
- [ ] T-6.5.2.1 `tts_service` provider abstraction (`openai` / `local`), per-use-case config like `llm_routing`, cached audio per scene
#### S-6.5.3 ⚪ Assembly
- [ ] T-6.5.3.1 ffmpeg pipeline: stills + Ken Burns pan, captions, narration mix, end-card; `content_path` MP4; download through E-6.7
- [ ] T-6.5.3.2 Tests: duration within budget; file probes as valid MP4

### E-6.6 🟢 Foundation (schema + outputter Protocol + lifecycle + tier gate)

**Shipped 2026-05-05** in PR #173. New `outputs` table (Alembic `b5c6d7e8f9a0`) with status state machine (`pending` → `generating` → `completed` | `failed`); `Outputter` Protocol + `register_outputter` / `get_outputter` / `list_outputters` registry; `run_generation` driver that handles status transitions + error capture; `OutputKind` enum (`book` / `site` / `deck` / `newsletter` / `reel`). REST surface under `/api/v1/author/*` — `GET /kinds`, `POST /outputs` (creates + generates synchronously for v1; 501 when no outputter for the kind), `GET /outputs` (kind/status filters), `GET /outputs/{id}`, `GET /outputs/{id}/content` (PlainTextResponse with media-type), `DELETE /outputs/{id}`. All gated on `require_feature("author_studio")` (Pro+).

### E-6.7 🟢 Generation runtime (async, progress, downloads, citations)

**Filed 2026-10-18.** Cross-cutting pieces every kind needs that the foundation deliberately left out ([D-044](decisions.md#d-044--foundation-first-then-concrete-implementations-deferred-for-i-3--i-6-2026-05-05)).
**Scope.** Move generation into the Celery worker with WebSocket progress, add binary artifact storage and a download endpoint, and add the `output_citations` table the roadmap sketched so every kind cites the same way.
**Acceptance.** Creating an output returns immediately with `pending`; the Author page shows live progress over the existing `/ws/jobs` channel; a completed binary output downloads with the right media type; every output lists its citations through `GET /outputs/{id}/citations`.

#### S-6.7.1 🟢 Celery-backed generation with progress
**PR:** [#281](https://github.com/khoks/VideoResearchPro/pull/281) — *shipped 2026-10-19.* Cancellation is cooperative as well as a revoke: the solo-pool Windows worker cannot be interrupted mid-task, so `output_service.report_progress` (called by outputters between units of work) raises `OutputCancelled` once the row is cancelled, and a cancel that lands after the last report still wins over `completed`. The socket's ownership check (`routers/ws.py::_owns_job`) accepts an output id the caller owns, since outputs share the job channel.
- [x] T-6.7.1.1 `author.generate_output` Celery task (`tasks/output_tasks.py`, autodiscovered) dispatched through `task_routing_service.dispatch_for_user`; `outputs.celery_task_id`, `progress_pct`, `progress_message` (migration `72d7e46ef057`); `POST /outputs` returns `pending` at once and `?sync=true` generates inline; a broker failure is recorded on the row as `failed` — *shipped 2026-10-19*
- [x] T-6.7.1.2 Every status change and per-chapter progress published on `job_progress:{output_id}`; `useOutputsProgress` folds them into the outputs list and the reader; the Author page shows a progress bar and opens the book it just queued when it finishes; the reader at `/author/outputs/:id` follows a book still being written — *shipped 2026-10-19*
- [x] T-6.7.1.3 `POST /author/outputs/{id}/cancel`: 404 for another user's output, 400 once finished, revokes the task, new `cancelled` status; Cancel button on active rows — *shipped 2026-10-19*
- [x] T-6.7.1.4 `conftest.py` mocks `app.routers.author.generate_output` like the job tasks; tests cover dispatch to the tier queue, sync path, broker failure, cancel (revoke, publish, 404, 400), socket ownership of outputs, cancel mid-generation ending `cancelled` with no content, per-chapter progress, and the task body against the test engine — *shipped 2026-10-19*
- [x] T-6.7.1.5 *Shipped 2026-10-19; the test asserts zero rows.* Refuse a kind with no outputter before writing the row: today `POST /author/outputs` creates a `pending` row and then returns 501 (the UI never offers such kinds, so only API callers hit it). Filed 2026-10-19 by S-6.1.1
- [x] T-6.7.1.6 *Shipped 2026-10-19: a connecting socket is reused, handlers talk to their own socket, a replaced socket's close never reconnects; vitest with a fake WebSocket that throws like the browser.* Fix `wsClient.ts`'s dev-mode `InvalidStateError: Still in CONNECTING state` (its `onopen` sends on a socket that a second connect has replaced) before AuthorPage subscribes to progress. Seen in the S-6.1.2 live check, 2026-10-19. Also seen on `JobDetailPage` in the lane A live checks (S-8.8.2, S-8.12.1), where it surfaces as an uncaught page error, so it is not Author-specific

#### S-6.7.2 🟢 Binary artifacts and downloads
**PR:** [#284](https://github.com/khoks/VideoResearchPro/pull/284) — *shipped 2026-10-19.* `services/output_artifacts.py`: one directory per output so a book can carry Markdown, PDF and EPUB side by side; formats come from a whitelist with their media types; downloads are always derived from the row's own ids, never from the stored `content_path`, so a tampered column cannot read another file.
- [x] T-6.7.2.1 `OUTPUTS_DIR` (default `./data/outputs`); `<OUTPUTS_DIR>/<user_id>/<output_id>/artifact.<format>`, written atomically by `write_artifact`; `content_path` stored relative to the root (the worker writes, the API serves); ids must match `[A-Za-z0-9_-]` (rejected, never sanitised into a colliding name) and every resolved path must stay inside the root — *shipped 2026-10-19*
- [x] T-6.7.2.2 `GET /api/v1/author/outputs/{id}/download?format=` serves the text (`md` for books) or any artifact present, with its media type and an RFC 6266 `Content-Disposition` (UTF-8 `filename*` so Devanagari titles survive, ASCII fallback); `OutputItem.formats` lists what is available. **Deviates from the story text:** header-bearer only, no `?token=`, per [D-079](decisions.md#d-079--report-markdown-source-on-markdownify-new-report-routes-are-header-bearer-only-2026-10-19); the page fetches and saves a blob — *shipped 2026-10-19*
- [x] T-6.7.2.3 Deleting an output removes its directory (and an emptied user directory); a cancelled or failed run discards its partial files; `scripts/sweep_output_artifacts.py` lists directories with no row or under the wrong owner, `--apply` deletes them — *shipped 2026-10-19*
- [x] T-6.7.2.4 Tests: binary and text downloads with media types and names, extra format beside the text, missing format 404 and malformed format 422, cross-user 404, query token 401, tampered `content_path` never served, unsafe ids rejected, delete and cancel/failure leave no files, orphan sweep dry run then apply, Devanagari file names. Frontend: one download button per format, Read only for text outputs, vitest for the helpers — *shipped 2026-10-19*

#### S-6.7.3 🟢 `output_citations`
**PR:** [#293](https://github.com/khoks/VideoResearchPro/pull/293) — *shipped 2026-10-19.* The resolver is a port of the reading room's (`frontend/src/components/reader/citations.ts`, S-8.8.2), so a link resolves to the same source in the reader and in a book. Without it most rows would be dead: both stored real reports carry only bare `&t=` anchors (written before S-1.14.9). Schema adds `seconds` and `resolved_by` to the plan's columns, so endnotes can print the timestamp and say honestly when a citation found no source.
- [x] T-6.7.3.1 `output_citations(id, output_id, position, label, url, seconds, document_id NULL, source_type, source_id, resolved_by, created_at)` (migration `c5ee7a568ef8`); written through `output_citation_service.record_citations` (replace-all, no commit of its own, so a failed or cancelled run leaves no rows); `extract_markdown_citations` resolves a link by YouTube id, then URL, then a known title or sole channel in the text around it, against the chapter run's documents **visible to the tenant**; an unmatched bare anchor gets no URL rather than an invented one; deleted with the output — *shipped 2026-10-19*
- [x] T-6.7.3.2 `GET /api/v1/author/outputs/{id}/citations` (ordered, with the document's title and channel; 404 for another user's output); `OutputItem.citation_count` on create, get and the list (one grouped query); the Author row and the reader's stat tiles show it — *shipped 2026-10-19*
- [x] T-6.7.3.3 Tests: the reader's resolver cases ported (YouTube id, URL ignoring `t` and `www`, title, title within the list item, longest title, hashtag stem, sole channel, shared channel not enough, unresolved, unmatched absolute, anchors/images/relative skipped, garbage href); the stored smoke-test report against its three real sources gives **30 rows for 30 anchors, all resolved**, with rebuilt `watch?v=…&t=…` URLs; the same run without visibility grants resolves nothing; a failed run writes no rows; REST counts, ordering and isolation — *shipped 2026-10-19*

---

## I-7 ⚪ Curated source ranking (L4)

**Filed 2026-10-18** from a "what's remaining" code audit.
**Why it exists.** The product is meant to be *curated, not balanced*: the user's trust in a source should shape retrieval ordering, answer composition and disagreement surfacing. Today curation stops at approval, and every approved source counts equally after that.
**North-star doc:** [feature-roadmap.md L4](feature-roadmap.md#l4--curated-source-ranking-) · [vision.md](vision.md)
**Decision links:** [D-065](decisions.md#d-065--channel-subscriptions-become-per-tenant-transliteration-reversed-2026-07-31) (amended 2026-10-18)

**Current state.** Only a seed exists: `channel_subscriptions.source_weight` (per-tenant, default 1.0, moved there by D-065). Nothing reads it, no endpoint sets it, and no UI exposes it. `channel_subscription.py` nonetheless documents it as "the trust score that re-ranks retrieval".

### E-7.1 🔵 Trust-weighted retrieval (v1)

**Decided 2026-10-18 by [D-068](decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18):** weighted retrieval first, as a pure re-rank (`distance / weight` after the raw relevance threshold, over a 3× pool), weights resolved per tenant at query time and never stored on chunks or used as a filter. Perspective banding is E-7.2. **Sequenced after the R3/R4 batch**, which is rewriting `qa_agent.py`.

#### S-7.1.1 ⚪ Make `source_weight` re-rank retrieval
**PR:** TBD
**Acceptance.** A user who raises one channel's weight sees that channel's chunks rank higher in their own job and library Q&A, and no other tenant's ranking changes.
- [ ] T-7.1.1.1 `PUT /api/v1/channels/{id}/weight` writing `channel_subscriptions.source_weight` through `subscription_service`
- [ ] T-7.1.1.2 Apply the weight when re-ranking job and library retrieval. Weights are per-tenant and chunks are global ([D-063](decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)), so resolve them at query time and never store them in chunk metadata
- [ ] T-7.1.1.3 Weight control on the channel page — *the page and a read-only `TrustWeightSlot` (`data-slot="trust-weight"`) shipped in S-8.7.1, PR [#237](https://github.com/khoks/VideoResearchPro/pull/237); replace the slot with the control ([D-083](decisions.md#d-083--organisation-features-access-and-scope-defaults-on-the-plans-open-questions-2026-10-19))*
- [ ] T-7.1.1.4 Make the `channel_subscription.py` docstring true, or correct it
- [ ] T-7.1.1.5 Measure: the same questions with and without weighting, judged blind (E-1.14 harness)

### E-7.2 ⚪ Perspective banding in answers

**Scope.** Segment retrieval by trust band and let the answer surface "your trusted creators say X; others say Y", with disagreement detection between bands. Deferred by D-068 until user-set weights exist and E-7.1's measurement is in.

## I-8 🟡 Research workbench features (M1 to M12)

**Filed 2026-10-18** under the user's directive to turn the larger roadmap items into tracked, researched, buildable plans. One epic per medium-scale roadmap item; every epic links to a research plan under [`docs/plans/`](plans/README.md) that records the chosen approach, the alternatives rejected, schema and API deltas, the modules touched, risks, the test strategy and the first PR. Recommended sequence across I-3 / I-6 / I-8: [`docs/plans/build-order.md`](plans/build-order.md).

**Why it exists.** Ring 1 of the vision is a personal wiki that *reads like a research journal*. Ingest, reports and Q&A are shipped; what is missing is the workbench around them: ways to organise (shelves, tags, templates), find (command palette, suggestions), annotate (notes), monitor (saved searches), read (reading room, mobile), see the shape of the library (channel intelligence, citation graph), start (onboarding) and share (public reports). Several of these are also feeders for later initiatives: notes feed Echo's voice capture (I-3), shelves scope site output (I-6), the scheduler built for saved searches runs the newsletter (I-6).
**North-star doc:** [feature-roadmap.md M1 to M12](feature-roadmap.md#medium-scale-features-m1-m12) · [vision.md Ring 1](vision.md)
**Decision links:** [D-063](decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31) (every new user-facing read of shared tables goes through visibility; every new per-user attribute on a shared record lives in a per-tenant side table), [D-068](decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18) (the `distance / weight` re-rank that M5's note weight reuses), [D-050](decisions.md#d-050--self-service-tier-flip-with-mock-payment-until-e-53-stripe-ships-2026-05-15) (tier gates exist for `shelves`, `saved_searches`, `public_report_sharing` with no feature behind them yet).

**Verified state 2026-10-18 (what the code audit found before planning):**
- No `shelves`, `notes`, `saved_searches`, `job_templates`, `report_shares` or `document_tags` table exists; no Alembic revision references them. `TIER_CAPABILITIES` already lists `shelves`, `saved_searches` and `public_report_sharing` as Pro+ features and `useTierCapabilities.ts` mirrors them: gates with nothing behind them.
- No `/api/v1/search` endpoint. The only free-text search is `GET /library/videos?search=` (SQL `ILIKE` on title and channel name).
- No keyboard-shortcut hook: `ui-design.md` §2.1 says `g + r` shortcuts exist "via a global `useShortcuts` hook"; no such hook is in `frontend/src`. The only key handlers are the Modal's Escape and one in `VideoKnowledgePage`.
- Reports are LLM-written semantic-HTML bodies wrapped by `utils/html_builder.py` and stored as files at `jobs.report_path`; there is no Markdown source. They render in an `<iframe>` modal whose URL carries the JWT as `?token=` (`routers/qa.py` `get_report`).
- A "Duplicate" flow exists (`JobsListPage` → `/submit` with `cloneFrom` state; `SubmitJobPage` persists a draft in `localStorage`). There is no named template concept.
- Celery has no beat scheduler configured (`tasks/celery_app.py`); channel sync is manual (`POST /channels/{id}/sync`).
- Stance / sentiment / framing classification exists only for social sources (`sources/{reddit,hn,mastodon,bluesky,podcast}` call `social_classify`); YouTube documents carry none, so "stance over time" per channel has no data for the dominant source type.
- Per-video knowledge artifacts are `{topics, concepts, events, facts}` lists plus Markdown, on the `documents` row; extraction is on demand and quota-metered, so channel-level aggregation depends on coverage.
- Q&A references carry `source_type`, source id, timestamp and quote (`qa_agent._chunk_to_reference`); every exchange is also embedded in `qa_library_global` with `tenant_id`, `source`, `exchange_id` and `job_id` metadata, the substrate for suggestions (M4) and the graph (M9).
- There is no channel detail page: `/library` has a Channels tab (`ChannelRow`), the API has `GET /channels/{id}`, nothing routes to a per-channel view.
- Responsive handling is two CSS media rules in `index.css` (sidebar collapse under 960px, `.form-row` stacking under 640px); no reading-specific mobile work exists.
- `users` has no `onboarded_at`; there is no first-run flow.

### E-8.1 🟡 Shelves — collections, tags and shelf-scoped views (M1)

**Scope.** Named collections of jobs (many-to-many), per-tenant tags on documents, a shelf detail page that is a filtered library view, and Q&A scoped to a shelf. Tags are a per-tenant side table because `documents` is a shared cache ([D-063](decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)): a tag is private to the user who applied it.
**Plan:** [`docs/plans/m1-shelves.md`](plans/m1-shelves.md)
**Linked decision:** [D-083](decisions.md#d-083--organisation-features-access-and-scope-defaults-on-the-plans-open-questions-2026-10-19) (defaults taken on the plan's open questions)
**Acceptance.** A user creates a shelf, adds jobs to it from the jobs list and job page, opens the shelf and sees only those jobs and their documents, asks a question scoped to the shelf and gets citations only from documents on it. Another tenant sees none of it.

#### S-8.1.1 🟢 Shelves schema, service and REST
**PR:** [#242](https://github.com/khoks/VideoResearchPro/pull/242) (merged 2026-10-19)
- [x] T-8.1.1.1 `shelves(id, tenant_id, name, description, color, created_at, updated_at)` + `shelf_jobs(shelf_id, job_id, added_at)`, Alembic revision `d8e9f0a1b2c3`; unique `(tenant_id, name)` plus a case-insensitive check in the service; `color` is one of the ten palette names, validated server-side
- [x] T-8.1.1.2 `shelf_service` as the single accessor (tenant is part of every lookup; foreign ids 404)
- [x] T-8.1.1.3 `GET/POST/PUT/DELETE /api/v1/shelves`, `POST/DELETE /api/v1/shelves/{id}/jobs/{job_id}`, `GET /api/v1/jobs/{id}/shelves`. Writes gated on `require_feature("shelves")`; **reads open to every tier** so a shelf outlives a downgrade read-only (plan open question 1, recommended default taken)
- [x] T-8.1.1.4 Deleting a job removes its `shelf_jobs` rows; deleting a shelf never deletes jobs. The cascade is an ORM relationship on `Job`, not DB-level: SQLite here never enforces `ON DELETE CASCADE` (no `PRAGMA foreign_keys`)
- [x] T-8.1.1.5 Router + service + isolation tests (every endpoint against a second real tenant: all 404); a parametrised Alembic upgrade → downgrade → upgrade round-trip test (`tests/test_models/test_migrations_round_trip.py`) that later lane migrations add a row to

#### S-8.1.2 🟢 Shelves UI
**PR:** [#250](https://github.com/khoks/VideoResearchPro/pull/250) (merged 2026-10-19)
- [x] T-8.1.2.1 Sidebar "Shelves" group listing the user's shelves (first eight, then "Show all N"; "Manage shelves" link to a new `/shelves` page with create / edit / delete)
- [x] T-8.1.2.2 "Add to shelf" control on `JobsListPage` cards and `JobDetailPage` header (checkbox per shelf, saved on toggle; inline "New shelf…" creates and adds). Shelf chips show where a run sits. `GET /shelves` now carries each shelf's `job_ids` so a page of cards costs one request, not one per card
- [x] T-8.1.2.3 `/shelves/:id` page: header, its runs (remove for Pro+), the union of their documents through a new `GET /shelves/{id}/documents` (visibility-scoped, deduplicated, library filters; an empty shelf lists nothing). The library listing became a reusable `query_library_documents`, and the filter / pager UI a shared `DocumentsBrowser` used by the channel page too
- [x] T-8.1.2.4 Type-check clean. **No Playwright runner exists in the frontend**, so the create → add → open smoke ran live instead: worktree backend on 8001 against a scratch SQLite, Vite on 3000, driven in the browser pane (create inline, tick a second run, open the shelf, recolour, chip on the job page, delete with runs intact). A checked-in Playwright suite is still open
- [x] Label palette: ten named colours in `theme.ts` with light / dark pairs at ≥ 4.5:1, documented in `ui-design.md` §1.1

#### S-8.1.3 🟢 Document tags (per tenant)
**PR:** [#257](https://github.com/khoks/VideoResearchPro/pull/257) (merged 2026-10-19)
**Scope-changed 2026-10-19:** built to the [M1 plan](plans/m1-shelves.md)'s *tags as rows* design rather than the free-string `document_tags` table this story first listed. Rows give a stable id (rename keeps every tagging), merge as one update, and first-class colour and counts; the plan rejected free strings for exactly those reasons.
- [x] T-8.1.3.1 `tags(id, tenant_id, name, color, created_at)` unique per tenant on `lower(name)` (functional index) + polymorphic `taggings(id, tag_id, tenant_id, target_type, target_id, created_at)`, unique `(tag_id, target_type, target_id)`, index `(tenant_id, target_type, target_id)`. Migration `e9f0a1b2c3d4`. `target_type` accepts only `document` in v1 (plan open question 2: documents-only until asked; jobs and channels need no schema change)
- [x] T-8.1.3.2 `GET/POST /api/v1/tags`, `PUT /tags/{id}` (rename / recolour), `DELETE /tags/{id}[?into=]` (delete or merge), `PUT/DELETE /library/videos/{document_id}/tags/{tag_id}`; `?tag=` on the library listing and on shelf documents, joined through the visibility set; rows carry the caller's `tags`
- [x] T-8.1.3.3 Tag chips on every library row with a "+ Tag" picker (checkbox per tag, inline create); a Tag bar on the Library page (select with counts, active-tag pill, "Manage tags" dialog for rename / recolour / merge / delete). The tag lives in the URL so chips are links. Shared pieces: `LabelPill` primitive, `PaletteField`, `LabelPicker` (now also behind "Add to shelf")
- [x] T-8.1.3.4 Tests: tags never cross tenants (every endpoint against a second real reader, including their tag on a shared document); the filter and counts respect visibility; merge drops duplicates; migration round trip. Live smoke in the browser pane: create and apply, filter by chip, merge through the dialog, shelf picker regression
- [x] Found on the way: list popovers were painted under the next card (each `Card` is its own stacking context through `transform`); `LabelPicker` now portals to `<body>` with fixed coordinates and listens for outside clicks and Escape in the capture phase
- **Decision taken (flagged):** tags are **not tier-gated**. They cost the operator nothing (the M6 plan's reasoning), the `shelves` capability is about grouping runs, and `frontend/src/data/tiers.ts` does not advertise tags. One `require_feature` line per write route if the user wants them Pro

#### S-8.1.4 🔵 Shelf-scoped Q&A
**PR:** TBD
- [ ] T-8.1.4.1 `POST /api/v1/shelves/{id}/qa` resolving the shelf's job set to a document set and calling the library Q&A agent with that `video_ids` filter (an empty shelf retrieves nothing)
- [ ] T-8.1.4.2 Exchanges stored as `library_qa_exchanges` with a `scope_json` column (`{"shelf_id": …}`) so history and the Q&A library index keep working
- [ ] T-8.1.4.3 Q&A panel on the shelf page reusing the library Q&A components
- [ ] T-8.1.4.4 Tests: scope restricts citations; empty scope never widens

### E-8.2 🟡 Command palette and global search (M2)

**Scope.** `Cmd-K` / `Ctrl-K` palette with navigation actions and grouped search across jobs, documents, channels, Q&A exchanges, knowledge artifacts, shelves and notes, backed by one tenant-scoped search endpoint. Keyword search first; semantic results as a second, clearly labelled group.
**Plan:** [`docs/plans/m2-command-palette.md`](plans/m2-command-palette.md)
**Acceptance.** From any page, `Ctrl-K` opens the palette; typing three characters returns grouped results within 300 ms on a 5,000-document library; Enter navigates; arrow keys and Escape work; a screen reader announces the result count. No result from another tenant ever appears.

#### S-8.2.1 🟢 Search endpoint
**PR:** [#245](https://github.com/khoks/VideoResearchPro/pull/245) — *shipped 2026-10-19.* Two deviations from the plan's sketch, both recorded in `services/search_service.py`: (1) **one trigram FTS5 table per entity** instead of a `unicode61` table plus a trigram table — the trigram tokenizer alone covers word-prefix and mid-word substring matching, case folding, diacritics folding (SQLite ≥ 3.45) and Devanagari, so the second table bought nothing at this scale; queries whose tokens are all under three characters take the `LIKE` path even with FTS5 present; (2) **not external-content tables** — FTS5's `content=` mode maps on rowid and every base table has a string primary key, whose rowids are not stable across `VACUUM`, so each FTS row carries the entity id as an `UNINDEXED` column and duplicates the indexed text. `GET /health` gains `search_backend`. Visibility joins are on `document_id` (D-070, merged first), through `visibility_service.visible_document_ids` and `subscription_service.visible_channel_ids` on the ORM paths; a test pins that a PDF with no `video_id` is found by its owner only. No palette yet (S-8.2.2); document and knowledge hrefs use `/library?document=<document_id>` (`&view=knowledge`), a contract the palette PR teaches the library page. Linked decision: [D-078](decisions.md#d-078--search-index-one-trigram-fts5-table-per-entity-copies-not-external-content-like-fallback-2026-10-19).
- [x] T-8.2.1.1 `GET /api/v1/search?q=&types=&limit=` returning `{q, backend, groups: [{type, items: [{id, title, subtitle, href, score}]}]}`; tenant scoping is applied to the FTS hit list by joining each entity's anchor (`jobs.tenant_id`, `document_visibility`, `channel_subscriptions` ∪ visible documents' channels, `*_qa_exchanges.tenant_id`), never by a tenant column inside the index; a tenant with nothing visible gets empty groups — *shipped 2026-10-19*
- [x] T-8.2.1.2 FTS5 tables `fts_documents`, `fts_jobs`, `fts_channels`, `fts_qa` (three Q&A tables, `surface` column), `fts_knowledge` with `AFTER INSERT / UPDATE OF <cols> / DELETE` triggers; created conditionally by migration `a9f3c1e7b5d2` **and** re-ensured by the lifespan (`search_service.ensure_index`), so a Python upgrade that gains FTS5 later still gets the tables; the probe tries `trigram remove_diacritics 1` then `trigram`, and falls back to `LIKE` with a logged warning; `schema_init_service` ignores the `fts_` prefix when comparing the live DB to the ORM — *shipped 2026-10-19*
- [x] T-8.2.1.3 Substring (and therefore prefix) matching from three characters; `bm25()` with the title column weighted 5:1 over the body, recency tie-break, over-fetch ×4 before the cut, per-group cap (`limit` 1–25, default 5) — *shipped 2026-10-19*
- [x] T-8.2.1.4 Tests on both paths through one parametrised fixture: every group scoped to the asking tenant (same words in both tenants' rows), empty for a tenant with nothing visible, caps, `LIKE` metacharacters literal; FTS-only: title outranks body, substring / case / Devanagari, triggers track update and delete and ignore unindexed columns, knowledge indexed only with a report, short query falls back, recency tie-break, channels visible through documents; probe failure creates nothing and warns; migration round-trip; latency under 300 ms on 5,000 documents + 2,000 exchanges on both paths; router: 401, 422, 400 on unknown type, two-tenant isolation through the endpoint — *shipped 2026-10-19*

#### S-8.2.2 🟢 Palette UI and shortcuts
**PR:** [#282](https://github.com/khoks/VideoResearchPro/pull/282) — shipped 2026-10-19. The plan's two open questions: (1) **no `<style>` block** was needed — the overlay is the app's own (cmdk's Dialog takes only class names) and each row reads its selected state through `useCommandState`, so the inline-only convention holds; (2) **`/` is bound**, as the story specifies, focusing the page's own search box (`data-page-search` on the library, runs and notes pages) or opening the palette, never inside a field, and the palette's "Turn single-key shortcuts off" switches it and the `g` chords off per browser (WCAG 2.1.4) since no settings page exists yet. Two things found on the way: cmdk does not reselect when async results replace the list (nothing active, Enter does nothing), so the selection is controlled; and in that mode it never writes `aria-activedescendant`, so the panel mirrors the active option's id onto the combobox and listbox. The panel and `cmdk` load on first open (19.6 kB gzip), so the main bundle grows by the shortcut hook only.
- [x] T-8.2.2.1 `useShortcuts` hook (the one `ui-design.md` already describes): `Ctrl/Cmd-K` palette with `Ctrl-Alt-K` as the alternate chord (Chrome and Firefox bind `Ctrl-K` to the address bar; a page handler that calls `preventDefault` wins once the page has focus), `Escape` close, `/` focuses page search only when no input is focused and can be disabled in settings (WCAG 2.1.4 character-key shortcuts); ignores typing inside inputs
- [x] T-8.2.2.2 Palette on `cmdk` (MIT, about 15 kB gzipped, unstyled, React 19 peer dependency, `shouldFilter={false}` for server results) with ARIA combobox/listbox semantics, inline styles plus at most one scoped `<style>` block for its data-attribute states, grouped results, recent items (localStorage), navigation actions ("New research", "Open library Q&A", "Toggle theme")
- [x] T-8.2.2.3 Debounced query, request cancellation, empty and loading states — *180 ms debounce (a query still settling counts as searching, so "Nothing matches" never flashes first); React Query cancels the superseded request through its `signal`*
- [x] T-8.2.2.4 Remove the stale `ui-design.md` claim or make it true (`g + r` style chords) in the same PR — *made true: `g r` / `g l` / `g k` / `g a`*
- [x] T-8.2.2.5 Notes group in the palette: "Your notes" (`/notes`), "Export notes as Markdown" and "Export notes as JSON-LD" (`/exports/notes.md` / `.jsonl`). Moved here from T-8.5.3.2, which shipped before the palette existed
- [x] T-8.2.2.6 The library page honours the search hrefs `?document=<document_id>` and `&view=knowledge` (open the document row, or its knowledge report), so palette results land on the item rather than the unfiltered list. Filed 2026-10-19 by S-8.2.1; [D-078](decisions.md#d-078--search-index-one-trigram-fts5-table-per-entity-copies-not-external-content-like-fallback-2026-10-19) — *`?document=` narrows the list to that row through a new `document_id` filter on `GET /library/videos` (inside the visibility scope); knowledge results now open the reader at `/knowledge/<id>` instead of `&view=knowledge`; Q&A results' `?exchange=` scrolls to and focuses the exchange on the job, library Q&A and Q&A history pages*

#### S-8.2.3 ⚪ Semantic group
- [ ] T-8.2.3.1 `semantic=true` adds a group from `qa_library_global` and the transcript collection (visible set only), merged with the keyword results by reciprocal rank fusion (rank-only, so FTS5 scores and Chroma distances need no calibration); labelled separately in the palette

### E-8.3 🟡 Saved searches and alerts (M3)

**Scope.** Pin a library question, re-run it on a schedule, detect whether new library content materially changed the answer, and notify by email and in-app. Carries the project's first scheduler, which [E-6.4](#e-64--newsletter--digest-recurring-scheduled-output) reuses.
**Plan:** [`docs/plans/m3-saved-searches-alerts.md`](plans/m3-saved-searches-alerts.md)
**Acceptance.** A user pins a question with a weekly schedule; a week later the question re-runs without anyone online; if the cited document set or the answer changed beyond the threshold they receive an email and an in-app notification linking to the diff; re-runs count against the user's monthly library Q&A quota; a paused search never runs.

#### S-8.3.1 🟢 Scheduler tick (shared infrastructure)
**PR:** [#238](https://github.com/khoks/VideoResearchPro/pull/238) — *shipped 2026-10-19.* Beat is a separate process (`celery -A app.tasks.celery_app beat`) started by both launcher scripts, never the embedded `worker -B` form; the launchers are the single-beat guard because Celery's `--pidfile` stale check is `os.kill(pid, 0)`, which on Windows terminates whatever process holds that pid. Cadences are human (`daily` / `weekly` / `monthly` with hour, minute, weekday or day-of-month 1–28, IANA timezone; `every` N seconds for system kinds), stored as `cadence_json`; `next_run_at` is computed by Celery's own `crontab` on the row's local wall clock, so 09:00 local stays 09:00 local across DST. Kinds register from the task module that defines their task (`scheduler_service.register_kind`); nothing registers yet — `saved_search` arrives with S-8.3.2. `GET /api/v1/health/scheduler` reports config, registered kinds and row counts. Linked decision: [D-077](decisions.md#d-077--scheduler-one-static-beat-entry-over-table-rows-beat-is-its-own-process-with-no-pidfile-2026-10-19).
- [x] T-8.3.1.1 Celery beat entry `scheduler.tick` every `SCHEDULER_TICK_SECONDS` (default 300) on the `default` queue with `expires` so a backlog of ticks never replays after a restart; `SCHEDULER_ENABLED` (off = no beat entry and the tick no-ops); beat process in `scripts/start.ps1` and `scripts/restart_services.ps1` — *shipped 2026-10-19*
- [x] T-8.3.1.2 `scheduled_runs(id, tenant_id, kind, target_id, cadence_json, next_run_at, last_run_at, last_status, last_error, claimed_at, consecutive_failures, enabled)` (migration `c7d8e9f0a1b2`); the tick claims each due row with one `UPDATE … WHERE claimed_at IS NULL OR claimed_at < now − SCHEDULER_LEASE_SECONDS`, so a duplicate tick claims nothing and a crashed holder's lease expires — *shipped 2026-10-19*
- [x] T-8.3.1.3 Per-kind dispatch through `task_routing_service.dispatch_for_tenant_id` (tier queues apply; `tenant_id` NULL → `default`); an unknown kind is recorded as `no_handler` and advanced by its cadence, a failed dispatch (broker down) is retried at the next tick up to `SCHEDULER_MAX_RETRY_TICKS` times, then waits for its cadence — *shipped 2026-10-19*
- [x] T-8.3.1.4 Tests: due selection, disabled rows, fresh vs stale lease, duplicate tick, batch limit, clock skew (a tick inside `SCHEDULER_GRACE_SECONDS` runs the row and advances from the *scheduled* time, so nothing runs twice), DST spring-forward and fall-back, per-tier queue, no-handler, retry budget, corrupt cadence; plus the wiring tests (beat entry names the task, task registered, task calls the service) — *shipped 2026-10-19*

#### S-8.3.2 🔵 Saved searches schema, REST and pin UI
**PR:** TBD
- [ ] T-8.3.2.1 `saved_searches(id, tenant_id, question, answer_language, scope_json, schedule, last_run_at, last_answer_hash, last_reference_ids_json, last_answer_embedding_id, notify_email, enabled)`; schedules are human presets (`daily` / `weekly` / `monthly`), not cron
- [ ] T-8.3.2.2 `GET/POST/PATCH/DELETE /api/v1/saved-searches`, `POST /api/v1/saved-searches/{id}/run-now`; gated on `require_feature("saved_searches")`
- [ ] T-8.3.2.3 "Pin this question" on library Q&A answer cards; `/saved-searches` list page with last result and next run
- [ ] T-8.3.2.4 Isolation tests; quota enforced before each run ([D-045](decisions.md#d-045--quota-metering-enforce-before-record-after-success-2026-05-05)); a per-tier cap on active saved searches in `TIER_CAPABILITIES` (comparable products cap at 3 to 15)
- [ ] T-8.3.2.5 Register the `saved_search` kind (`scheduler_service.register_kind`) from `tasks/saved_search_tasks.py` and add that module to `celery_app.autodiscover_tasks`; without the import the worker records `no_handler` and the search never runs. Filed 2026-10-19 by S-8.3.1; [D-077](decisions.md#d-077--scheduler-one-static-beat-entry-over-table-rows-beat-is-its-own-process-with-no-pidfile-2026-10-19)

#### S-8.3.3 🔵 Re-run, change detection and notification
**PR:** TBD
- [ ] T-8.3.3.1 Celery task runs the library Q&A agent with the saved scope and stores a `saved_search_runs` row (answer, references, embedding, changed flag, diff summary)
- [ ] T-8.3.3.2 Change detector in three stages: skip the re-run entirely when no document visible to the tenant has been granted since the last run (cost then scales with ingest, not with the number of saved searches); otherwise cited-document-set Jaccard below a threshold OR answer-embedding distance above a threshold → "changed"; an LLM judge (cheap tier) only when those two disagree, and it writes the notification text; thresholds in settings, pre-registered before tuning and calibrated on the app's own Q&A history
- [ ] T-8.3.3.3 Email via `email_service.send_email` (already fail-soft when SMTP is unset) and an in-app `notifications` row
- [ ] T-8.3.3.4 `notifications(id, tenant_id, kind, title, body, href, read_at, created_at)` + `GET /api/v1/notifications`, bell in the sidebar chrome
- [ ] T-8.3.3.5 Tests: unchanged answers do not notify; a run that fails leaves the previous result intact

### E-8.4 🔵 Question suggestions (M4)

**Scope.** "You might ask…" suggestions on the job page, the library Q&A page and the knowledge page, generated from the user's own past questions (nearest neighbours in `qa_library_global`) plus the current context, deduplicated and cached. Directly answers the user's "learn from past questions" ask and is the first piece of Echo's *anticipation* capability.
**Plan:** [`docs/plans/m4-question-suggestions.md`](plans/m4-question-suggestions.md)
**Acceptance.** Opening a completed job shows three to five suggested questions within two seconds; clicking one fills the composer; suggestions never repeat a question already asked on that job; a user with no history still gets context-derived suggestions; a second open within the cache window makes no LLM call.

#### S-8.4.1 🔵 Suggestion endpoint
**PR:** TBD
- [ ] T-8.4.1.1 `GET /api/v1/suggestions?context=job:<id>|document:<id>|library` → `{suggestions: [{question, rationale, source}]}`; tenant-scoped retrieval of past questions, context summary from report sections or knowledge topics
- [ ] T-8.4.1.2 `qa_suggest_questions` use case in `USE_CASE_REGISTRY` (economy tier, structured JSON, low reasoning); diversity pass so the five differ
- [ ] T-8.4.1.3 Cache per `(tenant, context)` for a configurable window; invalidated when a new exchange lands on that context
- [ ] T-8.4.1.4 Tests with the LLM patched at the factory boundary; no-history and cache-hit paths

#### S-8.4.2 🔵 Suggestion cards
**PR:** TBD
- [ ] T-8.4.2.1 Card below the composer on `JobDetailPage`, `LibraryQAPage`, `VideoKnowledgePage`; click fills, Shift-click asks immediately
- [ ] T-8.4.2.2 Click-through recorded as an `audit_log` event so the feature can be measured
- [ ] T-8.4.2.3 Hidden when `/health` reports the Q&A feature down

### E-8.5 🟡 Notes — the user's own voice in the library (M5)

**Progress 2026-10-19.** S-8.5.1 and S-8.5.3 shipped (Phase 1, lane D). S-8.5.2 remains and is sequenced after E-7.1.
**Linked decision:** [D-074](decisions.md#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19) (one note stream per document, soft delete only, lossless JSON-LD export, Echo feeder reported not gated).

**Scope.** Free-text Markdown notes on any entity (document, job, Q&A exchange, channel, knowledge artifact), private to the author, searchable, exportable, and **citable**: a note is retrieved alongside transcripts and cited as "you wrote this on <date>" with a 1.5× retrieval weight applied through the [D-068](decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18) re-rank. Foundational for [E-3.3](#e-33--voice--personality-capture-domain-3): notes are the highest-density personality signal.
**Plan:** [`docs/plans/m5-notes.md`](plans/m5-notes.md)
**Acceptance.** A user adds a note to a document; the note appears inline under it and in the "Your notes" view; a library question whose answer the note bears on cites the note with its date and ranks it above an equally relevant transcript chunk; another tenant never sees or retrieves it; the user exports all notes as Markdown.

#### S-8.5.1 🟢 Notes schema, REST and inline UI
**PR:** [#243](https://github.com/khoks/VideoResearchPro/pull/243) — merged 2026-10-19.
**Shipped as planned, with four calls made in the PR (not in the plan):** (1) a document note is keyed on the canonical `document_id` whichever id the caller sends — the shelf still carries the legacy `video_id`, the job page carries `document_id`, and both must be ONE note stream (the plan's open question 2, taken at its recommended default: a note on a document shows on every surface that shows the document); the response carries `target_video_id` so pre-[D-070](decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19) surfaces can match. (2) A target the tenant cannot see and a target that does not exist are the same 404, like the library Q&A delete. (3) `DELETE` is a soft delete only — the row stays with `deleted_at` so S-8.5.3's export can carry deletions and Echo keeps a signal the user wrote and withdrew; a hard purge is not offered. (4) Inline surfaces fetch the tenant's notes once per target type per page (`GET /notes?target_type=…`, capped at the server's 2000-row page) and each row selects its slice, rather than one request per row. No embedding and no `NOTE_RETRIEVAL_WEIGHT` yet (S-8.5.2); open question 1 (1.5 vs 1.0) is untouched.
- [x] T-8.5.1.1 `notes(id, tenant_id, target_type, target_id, selector_json, body_md, motivation, created_at, updated_at, deleted_at)` with index `(tenant_id, target_type, target_id)`; `target_type` closed set validated at the API layer; `selector_json` follows the W3C Web Annotation shape (`TextQuoteSelector` plus `start_seconds`) so a note can cite a transcript span with a `&t=` link exactly like a Q&A citation; `deleted_at` so exports can carry deletions
- [x] T-8.5.1.2 `GET/POST/PUT/DELETE /api/v1/notes`, `GET /api/v1/notes?target=document:<id>`; target existence checked through the tenant's visibility / ownership
- [x] T-8.5.1.3 "Add a note" control and inline note list on `VideoRow`, `JobDetailPage`, Q&A answer cards, `ChannelRow`, `VideoKnowledgePage`; plain textarea with Markdown preview (react-markdown is already a dependency)
- [x] T-8.5.1.4 Isolation tests; a note on a document the tenant cannot see is rejected (`tests/test_routers/test_notes.py`: every target type mine-vs-theirs, two-tenant isolation on every verb, soft delete, one note stream per document)

#### S-8.5.2 🔵 Notes in retrieval and citations
**PR:** TBD. **Sequenced after [E-7.1](#e-71--trust-weighted-retrieval-v1)**, which lands the `distance / weight` re-rank this story reuses, and after the R3/R4 batch that is rewriting `qa_agent.py`.
- [ ] T-8.5.2.1 A separate `notes_global` Chroma collection (same embedder, one document per note, `tenant_id` / `target_type` / `target_id` / `note_id` metadata, queried with the fail-closed tenant filter the Q&A collection uses) rather than mixing private notes into the shared transcript collection; the job and library retrieval paths query both and merge by raw distance
- [ ] T-8.5.2.2 Weight `1.5` for notes in the D-068 re-rank (setting `NOTE_RETRIEVAL_WEIGHT`), applied after the raw relevance threshold like channel weights. The collections use Chroma's default squared-L2 space (the app never sets `hnsw:space`), so `distance / 1.5` is monotone but not a 1.5× cosine boost; keep the formula for consistency with channel weights and measure with the E-1.14 method before tuning
- [ ] T-8.5.2.6 Prompts that read note text carry a marker contract like D-067's (`[NOTE by you, YYYY-MM-DD]`) so the model never attributes the user's words to a speaker
- [ ] T-8.5.2.3 `_chunk_to_reference` emits a `note` reference `{note_id, target, created_at, quote}`; `<CitationLink>` renders "you wrote this on YYYY-MM-DD" and links to the note's target
- [ ] T-8.5.2.4 Re-embed on edit, delete chunks on delete; backfill script for existing notes
- [ ] T-8.5.2.5 Tests: note cited; weight ordering; absent for other tenants; empty visible set still returns the tenant's notes only when they match
- [ ] T-8.5.2.7 Withdrawn notes (`deleted_at` set) never enter `notes_global`, and soft-deleting a note removes its vector ([D-074](decisions.md#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19) item 2); test both
- [ ] T-8.5.2.8 A `document` note is retrievable from job-scoped Q&A on EVERY job that contains the document, not only the one it was written from (D-074 item 1): match note `target_id` against the job's approved `document_id` set
- [ ] T-8.5.2.9 The citation reuses the shipped `NoteCard` phrasing ("You wrote this on <date>") so the inline list, the notes page and the answer read the same
Linked decision: D-074.

#### S-8.5.3 🟢 "Your notes" view, search and export
**PR:** [#246](https://github.com/khoks/VideoResearchPro/pull/246) — merged 2026-10-19. Lane D of Phase 1 is complete; S-8.5.2 (retrieval and citations) waits for E-7.1 in Phase 2.
- [x] T-8.5.3.1 `/notes` page: all notes newest first, grouped by target type, filter by target, full-text filter. Fetches the newest 2000 (the server's page cap) and groups client-side so the type chips carry counts; says so when more exist. A "Show withdrawn" toggle lists soft-deleted notes read-only. Each note links to the page its target lives on (run, channel page, library Q&A, history anchor); sources have no page of their own yet, so those link to the shelf
- [x] T-8.5.3.2 `GET /api/v1/exports/notes.jsonl` (W3C Web Annotation JSON-LD under the `anno.jsonld` context, one per line, oldest first, withdrawn notes included with `deleted`; `note_export_service.parse_note_jsonld` is the exact inverse and the round-trip test holds every column to it) and `GET /api/v1/exports/notes.md` (grouped by target type and target, every column in an HTML comment per note). Both stream like the dataset exports and accept `?token=`. On the Exports page and the notes page. **Not in the command palette**: E-8.2's palette UI (S-8.2.2) does not exist yet; add the group there when it lands (filed as [T-8.2.2.5](#s-822--palette-ui-and-shortcuts))
- [x] T-8.5.3.3 `GET /echo/status` reports `notes_total` and `notes_words` (live notes) as the Domain 3 feeder; the Echo readiness panel shows them. **Reported, not gated**: the per-language voice floor is S-3.5.1's to set, so `ready` does not move

### E-8.6 🟡 Job templates (M6)

**Scope.** Save a job's parameters as a named template; instantiate with a new topic and run. Generalises the shipped "Duplicate" flow from "copy one job" to "named reusable recipe", and seeds the starter templates the onboarding wizard (E-8.10) offers.
**Plan:** [`docs/plans/m6-job-templates.md`](plans/m6-job-templates.md)
**Linked decisions:** [D-082](decisions.md#d-082--job-templates-identity-plus-immutable-versions-provenance-without-a-foreign-key-starters-in-a-self-contained-data-migration-2026-10-19) (schema, starters, visual flag carried), [D-083](decisions.md#d-083--organisation-features-access-and-scope-defaults-on-the-plans-open-questions-2026-10-19) (not tier-gated)
**Acceptance.** A user saves a completed topic job as "Weekly AI policy scan", later picks it from the submit page, changes only the topic, and the new job runs with the saved instructions, filters, preferred channels, source types, depth and visual flag; built-in starter templates appear for every user and cannot be edited.

#### S-8.6.1 🟢 Templates schema, REST and submit-page integration
**PR:** [#263](https://github.com/khoks/VideoResearchPro/pull/263) (merged 2026-10-19)
- [x] T-8.6.1.0 Duplicate fixed: `jobToFormState` (now in `frontend/src/utils/jobForm.ts`, unit-tested with vitest) carries `output_length` and `visual_analysis`. **No visual-analysis opt-in was added to the form**: that toggle is T-1.18.2.1, deferred by D-071 / D-075. A carried flag shows as an info box with "Turn off"
- [x] T-8.6.1.1 Schema (migration `f0a1b2c3d4e5`): `job_templates(id, tenant_id NULL for built-ins, builtin_key UNIQUE, name, description, job_type, latest_version, created_at, updated_at, deleted_at)` + `job_template_versions(template_id, version, parameters_json, created_at)`, immutable rows per saved change, newest 20 kept; `jobs.template_id` + `jobs.template_version` for provenance. Split from the plan's single table so a template's id survives a rename; soft delete so provenance keeps resolving
- [x] ~~T-8.6.1.6 Relative publish window~~ — *moved to [S-8.6.3](#s-863--relative-publish-window) on 2026-10-19: it needs the search agent's ranking prompt, which this lane could not edit. Variable fields today: `topic` (and channels when a recipe leaves them open); `{{topic}}` in instructions is filled at submission*
- [x] T-8.6.1.2 `GET/POST /api/v1/job-templates`, `GET/PUT/DELETE /job-templates/{id}` (PUT with new parameters → next version), `GET /job-templates/{id}/versions`, `POST /api/v1/jobs/{id}/save-as-template`, `POST /jobs?template_id=&template_version=` (provenance); built-ins 403 on write
- [x] T-8.6.1.3 "Save as template" on `JobDetailPage`; "Start from a template" picker, origin banner with "Save changes as vN+1", and "Save as template" on `SubmitJobPage`; a `/templates` page (use, history, rename, delete)
- [x] T-8.6.1.4 Parameters are validated through `JobCreate` on every save (422 otherwise; unknown fields refused), the submission is a full `JobCreate` again, and each listing reports `problems` for the caller (a tier cap below the recipe's `num_videos`). A test pins that frozen ∪ variable fields = `JobCreate`'s fields, so a new field forces a decision
- [x] T-8.6.1.5 Tests incl. isolation (every endpoint against a second reader) and built-in immutability; live check in the browser pane (save a deep visual run as a template, Duplicate keeps depth and the flag, pick the template, save v2 from the form, history, Use)
- **Finding, not fixed (outside this lane):** `JobCreate` has **no `source_types` field** and nothing writes `jobs.source_types_json`, so every topic run searches video only. The worker's multi-source dispatch (`job_tasks._resolve_source_types` → `connector_dispatch`) is unreachable from the API. The plan listed `source_types` as a frozen template field on the assumption it existed; templates freeze what `JobCreate` really accepts. Starter templates that need it (podcast digest, mixed-source debate) wait for that wiring (S-8.6.2)

#### S-8.6.2 🟢 Starter templates
**PR:** [#265](https://github.com/khoks/VideoResearchPro/pull/265) (merged 2026-10-19)
- [x] T-8.6.2.1 Five built-ins seeded by migration `f1a2b3c4d5e6`, keyed by `builtin_key`, read-only, listed for every reader under "Starters": **Topic scan** (20 videos), **Deep dive** (60 long-form videos, deep report), **Quick brief** (8 short videos, brief report), **Channel deep-dive** (25 per channel), **Subscription follow**. The upsert is idempotent and versioned (identical → no-op, changed parameters → next version); a later revision copies it into a new migration. **Plan open question 2 (which five) answered by substitution:** podcast digest and mixed-source debate need `source_types`, which `JobCreate` does not accept (S-8.6.1 finding), so Deep dive and Quick brief stand in until that field is wired. No starter turns on visual analysis (its opt-in is deferred, D-071 / D-075)
- [x] Channel and subscription recipes may leave the channel list empty, meaning "add the channels each run" (as topic recipes leave the topic); validation fills a placeholder for the check, submission still requires channels, and the submit banner says "Add the channels"
- [x] ~~T-8.6.2.2 Used by the onboarding wizard (E-8.10) as the first-job step~~ — *moved 2026-10-19: it is the wizard's work and already lives in [S-8.10.1](#s-8101--wizard) T-8.10.1.2 ("a first job … from a starter template"); the wizard picks a starter by `builtin_key` from `GET /api/v1/job-templates`*

#### S-8.6.3 ⚪ Relative publish window
**PR:** TBD
**Filed 2026-10-19** from T-8.6.1.6. **The user's call** (M6 plan open question 1): is a relative window wanted now? It changes the ranking prompt.
- [ ] T-8.6.3.1 `JobCreate.published_after_days` (and `jobs.published_after_days`), resolved at run time; a template field (extend `TemplateParameters`)
- [ ] T-8.6.3.2 Thread it into `search_agent` ranking as a **preference**, never a filter ([D-059](decisions.md#d-059--selection-quotas-preferred-channel-guarantee--concentration-cap-2026-07-30) posture), coordinated with S-1.17.2's `temporal_profile`
- [ ] T-8.6.3.3 Submit-form control and template round trip; tests at the caller
**Blocked-on:** the user's answer; serialise with other `backend/app/agents` work.

#### S-8.6.4 ⚫ Source-type starters (podcast digest, mixed-source debate)
**PR:** TBD
**Filed 2026-10-19.** The two starters the M6 plan proposed that S-8.6.2 could not ship ([D-082](decisions.md#d-082--job-templates-identity-plus-immutable-versions-provenance-without-a-foreign-key-starters-in-a-self-contained-data-migration-2026-10-19)).
- [ ] T-8.6.4.1 A new data migration that copies `STARTERS` / `_upsert` from `f1a2b3c4d5e6_starter_templates.py` (never edit that file) and adds `podcast-digest` and `mixed-source-debate`
**Blocked-on:** [S-1.5.13](#s-1513--accept-source_types-on-job-creation).

### E-8.7 🟡 Channel intelligence (M7)

**Scope.** A per-channel view with analytics computed from what the library already holds: publishing cadence, top topics and concepts aggregated from knowledge artifacts, a keyword cloud from transcripts, the user's own Q&A activity against the channel, and a concept graph. Stance over time is scoped to sources that carry classification (social connectors); YouTube has none today, so that panel is explicitly data-dependent.
**Plan:** [`docs/plans/m7-channel-intelligence.md`](plans/m7-channel-intelligence.md)
**Linked decision:** [D-083](decisions.md#d-083--organisation-features-access-and-scope-defaults-on-the-plans-open-questions-2026-10-19) (read-only trust-weight slot)
**Acceptance.** Opening a channel the user follows shows cadence, top topics (with the videos behind each), a keyword cloud and the user's questions about it; panels whose inputs are missing say what to do ("Extract knowledge for 12 more videos to populate topics") instead of showing nothing; a channel with 500 documents renders within two seconds from a cached aggregate.

#### S-8.7.1 🟢 Channel detail page
**PR:** [#237](https://github.com/khoks/VideoResearchPro/pull/237) (merged 2026-10-19)
- [x] T-8.7.1.1 `/library/channels/:id` route and page: header, per-tenant subscribe / sync, a read-only **trust-weight slot** showing the caller's `source_weight` (the control itself stays with [S-7.1.1](#s-711--make-source_weight-re-rank-retrieval): a control that saved a number nothing reads yet would mislead), documents through `GET /library/videos?channel_id=` (same visible set as `GET /channels/{id}/videos`; the rows need `job_count` / `job_titles`)
- [x] T-8.7.1.2 Links from `ChannelRow` and `VideoRow`. Citation chips are **not** linked: `Reference` has no `channel_id`, and adding it edits `qa_agent._chunk_to_reference` (a shared hot spot); one line there plus a `Link` in `CitationLink` when that file is free
- [x] Found and fixed on the way: the Channels tab keyed Subscribe / Sync on a `channel.id` the API never sent (`/channels/undefined/...`); `ChannelResponse` now carries `id`, `url`, `source_weight`, `created_at`

#### S-8.7.2 🟢 Intelligence aggregate endpoint
**PR:** [#280](https://github.com/khoks/VideoResearchPro/pull/280) (merged 2026-10-19)
- [x] T-8.7.2.1 `GET /api/v1/channels/{id}/intelligence` over the tenant's visible documents of the channel: contiguous monthly cadence, duration buckets and median, top-25 topics / concepts (merged case-insensitively, per document, with example documents), top-60 keyword cloud (TF-IDF over cached transcripts with a function-word + spoken-filler stop list; scikit-learn's Glasgow list dropped words like "interest"), coverage, the caller's job and library exchanges citing the channel (live), and per-panel `notes` saying why a panel is empty
- [x] T-8.7.2.2 Stance / sentiment monthly series from `source_metadata_json.classification` where present; `null` plus a note otherwise
- [x] T-8.7.2.3 `channel_intelligence_cache(channel_id, tenant_id, fingerprint, computed_at, payload_json)` (migration `b4c5d6e7f8a0`). Recomputed when a fingerprint of the inputs changes (visible document set, knowledge times, transcripts) or on `?refresh=true`: this answers M7 open question 2 ("invalidate on sync and on new knowledge") without hooks in either path. **Computed in the request, not a Celery task**: the solo worker is routinely busy for hours with ingest. Measured 1.6 s cold and 13 ms cached on a synthetic 500-document channel
- [x] T-8.7.2.4 Tests: seeded artifacts and transcripts, two readers on one channel (counts, topics, keywords and Q&A never cross; caches separate), an empty visible set is empty, cache hit then recompute on new knowledge, stance series, 404
- **Not built (plan item outside the board's tasks):** topic clusters by k-means over Chroma chunk embeddings. Needs a new Chroma read helper while E-7.1 is editing retrieval, and overlaps the gated S-8.9.3
- `scikit-learn` is now declared in `requirements.txt` (it was only a transitive dependency of sentence-transformers)

#### S-8.7.3 🟢 Intelligence tab UI
**PR:** [#285](https://github.com/khoks/VideoResearchPro/pull/285) (merged 2026-10-19)
- [x] T-8.7.3.1 Documents / Intelligence tabs on the channel page (`?tab=intelligence`). Cadence columns, duration bars, topic and concept lists with drill-down to linked example documents, a text keyword cloud (inline words sized by √weight; no library), the reader's citing questions, a stance / sentiment panel where classification exists, per-panel notes, and a coverage card with **Extract knowledge for N documents**. The batch runs the existing per-document endpoint one at a time from the page (visibility and quota enforced per call), plans no more than the remaining monthly quota from `GET /auth/quota`, stops at the first quota refusal and refreshes the aggregate. **Deviation from the plan:** not a server-side batch with WebSocket progress; that needs a new Celery task (the `celery_app` hot spot), and the solo worker would queue it behind ingest. Cost is shown as quota, not dollars
- [x] Charts follow the dataviz method: validated `chartColors` per mode, thin marks, surface gaps, a legend only for ≥2 series, hover + keyboard readouts, a table view on every chart. New primitives: `ColumnChart`, `BarList`, `ChartTable`
- [x] Tests: `utils/batchExtract.ts` unit tests (quota cap, outcome classes, stop on quota, stop on request); aggregate gains `coverage.extractable` and example URLs (router test). The cache fingerprint now carries a payload version so rows written by older code recompute
- [ ] ~~T-8.7.3.2 Concept graph panel reusing the E-8.9 graph component filtered to the channel~~ — *moved 2026-10-19 to [S-8.9.2](#s-892--graph-ui): the graph component does not exist until that story; it adds the channel-filtered view*

#### S-8.7.4 🟢 Citation chips link to the channel page
**PR:** [#291](https://github.com/khoks/VideoResearchPro/pull/291) (merged 2026-10-19)
**Filed 2026-10-19:** the part of T-8.7.1.2 that S-8.7.1 could not do. `Reference` has no `channel_id`, and adding it edits `qa_agent._chunk_to_reference`, a shared hot spot.
**Scope-changed 2026-10-19:** built without touching `qa_agent.py` or `routers/qa.py` (E-7.1 is working there): the link is resolved at read time instead of stored on references.
- [x] ~~T-8.7.4.1 Add `channel_id` to video references in `_chunk_to_reference`~~ — *replaced by `GET /api/v1/library/video-channels?video_ids=` (visibility-scoped, absent for unknown or invisible ids, ≤ 200 per call). Every existing answer gains the link; nothing stored changes*
- [x] T-8.7.4.2 `CitationLink` names the channel of a visible YouTube citation as a link to `/library/channels/:id`; the video id comes from `video_id` or the URL; one batched request per screen (`utils/batchLoader.ts`, unit-tested). Live: three citations resolved in one call, two linked, the unknown one kept its plain label

### E-8.8 🟡 Reading room — the report as a native reading view (M8)

**Status 2026-10-19.** S-8.8.1, S-8.8.2 and S-8.8.3 shipped (PRs [#244](https://github.com/khoks/VideoResearchPro/pull/244), [#254](https://github.com/khoks/VideoResearchPro/pull/254), [#261](https://github.com/khoks/VideoResearchPro/pull/261)); the epic stays 🟡 for T-8.8.1.5 (retire the `?token=` fallback, which needs `routers/qa.py`) and the proposed follow-ups in S-8.8.4. Linked decisions: [D-085](decisions.md#d-085--reading-room-reports-stay-html-sanitised-and-parsed-in-the-browser-one-shared-citation-card-fed-by-the-runs-documents-2026-10-19), [D-086](decisions.md#d-086--markdown-readers-react-markdowns-own-pipeline-run-once-with-a-tree-transform-the-outline-is-the-two-shallowest-structural-heading-levels-2026-10-19).

**Scope.** Replace the iframe modal with a full-page reader at `/reports/:jobId`: sanitised report HTML rendered in React with the app's typography, drop cap, sticky outline built from the report's own headings, reading progress, citation hover cards, print stylesheet. The modal stays as a quick peek. The same reader shell renders knowledge artifacts and, later, public shares (E-8.11) and books (E-6.1).
**Plan:** [`docs/plans/m8-reading-room.md`](plans/m8-reading-room.md)
**Acceptance.** A report opens at `/reports/:jobId` with no iframe and no token in the URL; the outline tracks scroll; hovering a citation shows source title, channel and timestamp; Ctrl-P produces a clean document with citations as footnotes; keyboard navigation reaches every citation; the page holds 75ch measure at desktop and reflows at 640px.

#### S-8.8.1 🟢 Report content endpoint and sanitised renderer
**PR:** [#244](https://github.com/khoks/VideoResearchPro/pull/244) — shipped 2026-10-19. The body route lives in a new `routers/reports.py` (the Q&A router is a shared hot spot and was left untouched); the plan's open question 1 was taken at its recommended default (retire `?token=` later, T-8.8.1.5 stays open) and question 2 likewise (the modal survives as "Quick peek"). A vitest + jsdom runner (`npm test`) arrived with this story — the frontend had none.
- [x] T-8.8.1.1 The reader fetches the report body through the authenticated API (Authorization header, no `?token=` in any URL) as `{title, html, statistics}`; the legacy HTML route stays for "Open in new tab"
- [x] T-8.8.1.2 Client-side pipeline: DOMPurify (dual MPL-2.0 / Apache-2.0, elect Apache-2.0; about 12 kB gzipped; forbid `style` and `script`) then `html-react-parser` (MIT, about 11 kB) with a `replace` hook that turns `&t=` anchors into `<CitationLink>`, assigns heading ids and collects the outline, and wraps tables in a scroll container; reports stay HTML (converting them to Markdown is lossy) — *shipped as `components/reader/{sanitize,parseReport}`; the chip is `ReaderCitation` (the existing `CitationLink` takes a Q&A `Reference`, which a report anchor cannot supply). Bare pre-S-1.14.9 `href="&t=123"` anchors render as non-link chips; an href the browser repaired out of a truncated tag is never linked.*
- [ ] T-8.8.1.5 Retire the query-string JWT fallback on the report route (`get_user_from_query_or_header`) once the iframe is gone; it is a log-leak surface — *open: needs an edit to `routers/qa.py` (a serialised hot spot) and the quick-peek modal still uses the fallback*
- [x] T-8.8.1.3 `/reports/:jobId` route, `ReaderShell` layout (65 to 75ch measure, drop cap via `::first-letter` with `initial-letter` under `@supports` because Firefox still lacks it, IntersectionObserver outline, reading-progress bar, `text-wrap: pretty` as enhancement), `JobDetailPage` "Read" button; modal kept as quick peek
- [x] T-8.8.1.4 Tests: parser on three stored real reports; sanitiser rejects script / event handlers; type-check — *the three fixtures are committed under `components/reader/__fixtures__`; one of them (`419e691d…`) was cut mid-tag by the writer so the browser folds two of its headings into an attribute value — the reader cannot recover them, the compose step should refuse to emit a truncated section (filed as a note under E-1.14)*

#### S-8.8.2 🟢 Citation hover cards and footnotes
**PR:** [#254](https://github.com/khoks/VideoResearchPro/pull/254) — shipped 2026-10-19. Found and fixed on the way: `GET /jobs/{id}/videos` declared none of the polymorphic fields its builder returned, so `source_type` / `document_id` / `source_metadata` were stripped from every response (the job page's approval cards always fell back to the YouTube shape) and a non-video document on a job failed serialisation; the schema now declares them.
- [x] T-8.8.2.1 Citation anchors (`&t=` links) upgraded to superscript chips with hover / focus cards (Popover API, positioned with `getBoundingClientRect` since CSS anchor positioning is still partial) showing title, channel, timestamp, quote where available; polymorphic by `source_type` — *one shared card for all chips (a report carries up to 277); sources resolved by YouTube id, by URL, or for pre-S-1.14.9 bare anchors by the title or sole channel written beside them (30 of 30 recovered in the stored smoke-test report, 20 by title and 10 by channel because the writer reworded one Kannada title); per-kind facts in `sourceLabels.ts`. On screen the chip keeps the writer's timestamp text, since it is part of the sentence, and the footnote number appears in print. Report anchors carry no quote; the card has no quote line until a citation shape that carries one reaches it.*
- [x] T-8.8.2.2 Print stylesheet: outline removed, citations rendered as numbered footnotes, page breaks before `h2` — *plus a "Sources cited" endnote list that opens itself on `beforeprint`, monochrome output in either theme, the health banner and toasts hidden; verified with Chromium print emulation and a 37-page A4 PDF of the R1 report*
- [x] T-8.8.2.3 Hook for R1 frames: when [S-1.18.2](#s-1182--surfacing-frames-to-the-user) ships, the popover shows the still — *the slot ships (`CitationCardProvider`'s `resolveStill`, tested with a stub); no data until S-1.18.2 serves `visual_frames`*

#### S-8.8.3 🟢 Knowledge artifacts and books in the same shell
**PR:** [#261](https://github.com/khoks/VideoResearchPro/pull/261) — shipped 2026-10-19.
- [x] T-8.8.3.1 `/knowledge/:videoId` route rendering the Markdown knowledge report through `ReaderShell` (react-markdown + heading ids) — *react-markdown's own pipeline (remark-parse → remark-gfm → remark-rehype → hast-util-to-jsx-runtime) run once with a tree transform between, instead of `<ReactMarkdown>` plus `rehype-slug`: the shell needs the outline before the body renders, and two passes that must agree on every heading id drift. Same slugger as reports, so no `rehype-slug` dependency. The knowledge response now names its source (title, channel, kind, URL, dates) and `video_id` became nullable (a PDF's artifact failed serialisation). The drawer stays as the quick peek with "Open in reader".*
- [x] T-8.8.3.2 Author Studio outputs (`/author/outputs/:id`) read in the same shell — *manuscripts carry GFM tables since S-6.1.2 and render through the same `remark-gfm` path; the Author page's reader modal is gone; Read and a fresh `completed` output both navigate here. The book outputter's table-of-contents anchors are written against its own slug of the bare chapter title while the heading reads "1. Title"; the transform repoints them (checked on a real 81 kB manuscript built by `BookMarkdownOutputter` from two stored runs).*

#### S-8.8.4 ⚪ Reader follow-ups surfaced while building E-8.8
**Filed 2026-10-19** by the lane A session; proposed, not yet agreed. Linked decisions: [D-085](decisions.md#d-085--reading-room-reports-stay-html-sanitised-and-parsed-in-the-browser-one-shared-citation-card-fed-by-the-runs-documents-2026-10-19), [D-086](decisions.md#d-086--markdown-readers-react-markdowns-own-pipeline-run-once-with-a-tree-transform-the-outline-is-the-two-shallowest-structural-heading-levels-2026-10-19).
- [ ] T-8.8.4.1 Lazy-load the three reader routes (`ReportReaderPage`, `KnowledgeReaderPage`, `OutputReaderPage`) with `React.lazy` + `Suspense` so DOMPurify, html-react-parser and the unified / remark-gfm stack leave the first paint. Measured: the app is one 262 kB-gzip chunk after the lane (229 kB before it, +32 kB over three PRs), against the plan's 170 kB critical-path budget. Touches `routes/index.tsx` beyond an additive line, so it goes one at a time with the other lanes' route work
- [ ] T-8.8.4.2 Make the book outputter's table-of-contents anchors match the heading ids it writes: `book_markdown._slugify(title)` gives `#chapter-title` for a heading that reads `## 1. Chapter title`, so every TOC link was dead in the old Author modal. The reader repoints them (D-086); any other consumer of the manuscript (the S-6.1.5 PDF / EPUB export, the site outputter) will not
- [ ] T-8.8.4.3 Run the frontend suites in CI: `npm test` (vitest) and `npm run test:mobile` (Playwright, needs `npx playwright install --with-deps chromium webkit` in the runner). Today CI runs pytest, ruff and the frontend build only ([testing.md §5.4](testing.md#54-ci))
- [ ] T-8.8.4.4 Report the compose step's truncated section ([S-1.14.17](#e-114--model-tier-quality-evaluation-harness)) in the reader when it happens again: the reader cannot repair it, but it could show the processing note instead of silently losing two headings. Only after S-1.14.17 decides how the compose step discloses it

### E-8.9 🔵 Citation graph and knowledge map (M9)

**Scope.** A library-overview graph: documents, channels, Q&A exchanges and knowledge topics as nodes; citations, authorship and shared topics as edges; tenant-scoped; filterable by shelf, channel or job; a "local graph" around any node. Useful rather than a hairball: size caps, degree-based sizing, clustering by channel or topic, and a focused mode by default.
**Plan:** [`docs/plans/m9-citation-graph.md`](plans/m9-citation-graph.md)
**Acceptance.** `/library/graph` renders the user's library in under three seconds at 2,000 nodes; clicking a document shows its neighbours and a detail card; filtering by shelf narrows the graph; nothing from another tenant appears; the graph degrades to a list on narrow screens.

#### S-8.9.1 🟢 Graph endpoint
**PR:** [#297](https://github.com/khoks/VideoResearchPro/pull/297) (merged 2026-10-19)
- [x] T-8.9.1.1 `GET /api/v1/library/graph?focus=&depth=&shelf_id=&job_id=&channel_id=&types=&limit=` → `{nodes, edges, truncated, total, shown, summary, focus}`. Nodes: visible documents, their channels (channels with no visible document would be isolated, so they are left out), the tenant's job and library exchanges that cite a visible document (references matched by video id or URL), and topics from knowledge artifacts on at least two visible documents. Edges `published_by`, `about`, `cites`, and derived `co_occurs` (topics sharing at least two documents, five strongest per topic). A foreign shelf or job is a 404
- [x] T-8.9.1.2 Degree then recency pick nodes under the cap (focus first); ids are stable (`document:`, `channel:`, `topic:<lowercased>`, `exchange:<kind>:`); a one-paragraph `summary` (counts, "N of M shown", connected groups and the largest group's main topics) as the textual alternative. Computed per request: about 0.07 s at 2,000 documents and 500 answers, so no edge table
- [x] T-8.9.1.3 Tests: two-reader isolation (nothing of theirs in the payload, their topic absent, my answer citing only their document has no node), an empty visible set is an empty graph, cap and truncation with degree order, focus at depth 1 and 2, channel / job / shelf filters (foreign → 404, empty shelf → empty), types filter, job exchanges
- Found on the way: a topic label's display spelling depended on row order when casings tied; both this and the channel aggregate now break ties toward the capitalised spelling

#### S-8.9.2 🔵 Graph UI
**PR:** TBD
- [ ] T-8.9.2.1 Lazy-loaded graph route on `sigma` + `graphology` + `@react-sigma/core` with the ForceAtlas2 web-worker layout and Louvain communities (all MIT, about 113 kB gzipped; `react-force-graph-2d`, MIT, 60 kB, is the smaller alternative), inline-styled chrome, zoom / pan, hover labels, click → detail card with links to the document, job or exchange; layout frozen after convergence
- [ ] T-8.9.2.2 Filters (shelf, channel, type), local-graph mode, legend, reduced-motion respect
- [ ] T-8.9.2.4 The channel page's concept graph (moved from T-8.7.3.2): the graph filtered to the channel, reachable from the Intelligence tab
- [ ] T-8.9.2.3 Accessibility, which is real work for a canvas: an equivalent node / edge table view, keyboard focus over nodes with a drawn focus ring, button alternatives to drag and pan (WCAG 2.5.7), a one-paragraph textual summary; the table doubles as the narrow-screen fallback

#### S-8.9.3 ⚪ Topic clusters
- [ ] T-8.9.3.1 Cluster documents by embedding centroid (k-means over stored chunk means) and colour the graph by cluster; only if S-8.9.2's topic edges prove too sparse

### E-8.10 🔵 Onboarding wizard and empty states (M10)

**Scope.** A first-run flow: pick channels → start a first job from a starter template → watch it run → open the report in the reader; dismissible, resumable, recorded server-side so it survives devices. Plus an audit of every empty state against the editorial voice and a first-run checklist. High leverage for SaaS conversion later, useful for self-hosters now.
**Plan:** [`docs/plans/m10-onboarding.md`](plans/m10-onboarding.md)
**Acceptance.** A new account lands on `/welcome`, completes three steps in under five minutes to a running job, can skip at any point and reopen from the sidebar; `users.onboarded_at` is set on completion; activation events are logged; every list page has an empty state with one primary action.

#### S-8.10.1 🔵 Wizard
**PR:** TBD
- [ ] T-8.10.1.1 `users.onboarded_at` + `onboarding_state_json` (step, choices); `PATCH /api/v1/auth/me/onboarding`
- [ ] T-8.10.1.2 `/welcome` route as a plain stepper page (no tour library: Shepherd.js ≥ 14 and Intro.js are AGPL-3.0, and overlay walkthroughs underperform task-flow wizards) with three steps: channels via existing search + subscribe, a deliberately tiny first job (3 to 5 videos from one channel, so the transcript throttle does not make "see the result" take half an hour) from a starter template, progress + "read it"; redirect from `/` while incomplete, skip link always visible
- [ ] T-8.10.1.3 Activation events in `audit_log` (`onboarding_started`, `first_job_created`, `first_report_opened`)
- [ ] T-8.10.1.4 Tests: redirect logic, resumability, skip

#### S-8.10.2 🔵 Empty-state audit
**PR:** TBD
- [ ] T-8.10.2.1 Every page's zero-data state uses the `EmptyState` primitive with editorial copy and one action (jobs, library, channels, Q&A history, exports, author, echo, shelves, notes, saved searches)
- [ ] T-8.10.2.2 First-run checklist card on the jobs page until three milestones are hit

### E-8.11 ⚪ Public report sharing (M11)

**Scope.** A signed, expiring, revocable URL for a single report, rendered read-only on a public route through the E-8.8 reader with `noindex` and a sandboxing CSP, with view counts, a manage-shares list and takedown hooks. Tier gate `public_report_sharing` already exists.
**Plan:** [`docs/plans/m11-public-report-sharing.md`](plans/m11-public-report-sharing.md)
**Status.** ⚪ proposed, not accepted: whether sharing launches before billing and the abuse-prevention items it depends on (T-5.5.6 content policy and takedown) is the user's call and is recorded as the plan's first open question. Design is complete so the decision can be taken on a concrete proposal.
**Acceptance.** The owner creates a share with an expiry, copies a URL, and a logged-out visitor reads the report in the reader with no app chrome, no Q&A, no links into the app; the owner revokes it and the next visit returns 404; search engines are told not to index; the public route is rate-limited per IP; takedowns are logged.

#### S-8.11.1 ⚪ Share tokens and public route
- [ ] T-8.11.1.1 `report_shares(id, tenant_id, job_id, token_hash, expires_at, revoked_at, view_count, created_at)`; opaque `secrets.token_urlsafe(32)` tokens (256 bits) stored as SHA-256, never JWTs (the app's JWT library carries an unfixed critical CVE, see T-5.4.9); default expiry 30 days with an explicit "no expiry" choice; per-tenant cap on active shares; `SHARING_ENABLED` kill switch
- [ ] T-8.11.1.2 `POST /api/v1/jobs/{id}/share`, `GET /api/v1/jobs/{id}/shares`, `DELETE /api/v1/shares/{id}`; public `GET /s/{token}` JSON for the reader and a raw-HTML variant under `Content-Security-Policy: sandbox; default-src 'none'` (header, not meta); `X-Robots-Tag: noindex, nofollow` plus the meta tag (and the path must stay crawlable or the noindex is never seen), `Referrer-Policy: no-referrer`, `Cache-Control: private, no-store`; per-IP rate limit; a separate origin for shares is the plan's recommendation for SaaS
- [ ] T-8.11.1.3 Public reader route in the frontend (`/s/:token`) using `ReaderShell` with chrome stripped
- [ ] T-8.11.1.4 Tests: expiry, revocation, hashed storage, headers, no leakage of job metadata beyond the report

#### S-8.11.2 ⚪ Share UI and takedown hooks
- [ ] T-8.11.2.1 "Share" on the reader and job page; manage list with view counts and revoke
- [ ] T-8.11.2.2 `audit_log` events `share_created` / `share_revoked` / `takedown`; an operator endpoint to revoke by token (T-5.5.6)

### E-8.12 🟢 Mobile reading mode (M12)

**Shipped 2026-10-19** — PRs [#269](https://github.com/khoks/VideoResearchPro/pull/269) (S-8.12.1) and [#272](https://github.com/khoks/VideoResearchPro/pull/272) (S-8.12.2), emulation only; the real-device pass is S-8.12.3, proposed and the user's call. Linked decision: [D-087](decisions.md#d-087--mobile-reading-and-install-a-reading-toolbar-below-1200-px-a-docked-composer-lifted-by-visualviewport-hermetic-device-tests-a-manifest-without-a-service-worker-2026-10-19).

**Scope.** Reading-first responsive refinements for reports, Q&A answers and knowledge artifacts: type scale, touch targets, safe areas, dynamic viewport height, a bottom-docked Q&A composer, and device-emulated screenshot tests. Builds on the E-8.8 reader; not a general mobile redesign.
**Plan:** [`docs/plans/m12-mobile-reading.md`](plans/m12-mobile-reading.md)
**Acceptance.** On a 375px-wide viewport the reader, the job Q&A thread and a knowledge artifact are readable without horizontal scroll, every control meets the 44px target, the composer stays reachable while the keyboard is open, and Playwright device-emulation screenshots are checked in for the three pages.

#### S-8.12.1 🟢 Reading pages responsive pass
**PR:** [#269](https://github.com/khoks/VideoResearchPro/pull/269) — shipped 2026-10-19, emulation only. **Not done: a pass on a real iPhone and a real Android phone.** The plan's risks section calls that part of "done", and its open question 1 asks whether it is part of acceptance; that is the user's call. Emulation has no real keyboard and no Safari chrome, so the VisualViewport lift in particular is unverified on a device.
- [x] T-8.12.1.1 Fluid type scale and measure tokens in `theme.ts`; reader drops the outline under 960px and keeps drop cap and citations (per `ui-design.md` §2.4) — *`fluidType`, `readerScale`, `target` tokens. The outline already hid under 1200 px (S-8.8.1, because the sidebar takes 240 px); below that a bottom reading toolbar with a Contents sheet, text size and theme replaces it, so phones and small tablets keep a way to navigate*
- [x] T-8.12.1.2 Touch targets ≥ 24px everywhere (WCAG 2.2 SC 2.5.8) and ≥ 44px on primary controls (Apple HIG; inline citation chips are exempt); `env(safe-area-inset-*)` with `viewport-fit=cover`; `100dvh` / `svh` for docked panels; inputs at ≥ 16px to stop iOS zoom and never `maximum-scale=1` (ignored by iOS and a WCAG 1.4.4 failure); 320px reflow (WCAG 1.4.10) — *the toolbar, sheet links, reader actions, hamburger, drawer items, composer field and Ask are 44 px. On touch, a chip's first tap previews its card. Phone page padding follows ui-design §2.2. `dvh` is used for the outline column and the sheet*
- [x] T-8.12.1.3 Bottom-docked Q&A composer on `JobDetailPage` and `LibraryQAPage` under 640px, pinned above the keyboard with the VisualViewport API (rAF-throttled) — *`components/qa/Composer.tsx`: `QADock` / `QAThread` / `DockedComposer` and `useKeyboardInset`, which ignores pinch-zoom. The composer moves under the thread (the API returns it oldest first) and sticks to the bottom while the card is on screen. Nine lines change in each page*
- [x] T-8.12.1.4 Playwright device-emulation screenshot tests (iPhone and Pixel profiles) for the three reading pages — *`npm run test:mobile`: iPhone 13 (WebKit), Pixel 7 and a 320 px phone (Chromium), each in light and dark, giving 18 baselines in `frontend/tests/__screenshots__`. Hermetic: API fixtures with a synthetic Q&A thread, and the WebSocket and proxy are cut off. The tests also assert no horizontal scroll, 44 px controls, the composer in view after a shorter viewport, and 16 px fields*

#### S-8.12.2 🟢 Web-app manifest
**Linked decision:** [D-087](decisions.md#d-087--mobile-reading-and-install-a-reading-toolbar-below-1200-px-a-docked-composer-lifted-by-visualviewport-hermetic-device-tests-a-manifest-without-a-service-worker-2026-10-19)
**PR:** [#272](https://github.com/khoks/VideoResearchPro/pull/272) — shipped 2026-10-19. Unblocks T-3.7.6.1 (`share_target`).
- [x] T-8.12.2.1 `manifest.webmanifest` (`display: standalone`, icons, `theme_color`; about 30 lines; Safari 26 opens any Home-Screen site as a web app with or without one) and an icon that depends on the logo work in the rebrand table; a service worker is deferred because it complicates JWT-gated fetches and report invalidation and offline reading is not a stated requirement — *the plan left the icon open, so it renders the mark `branding.md` §3 already recommends (three concentric arcs fading inward, oxblood on paper) and uses the §8 inventory's `theme_color: #7a2c1a` and page title. That is an interim rendering of a documented recommendation, not a new logo: the rebrand's logo work stays open, and `npm run icons` re-renders every PNG from `public/logo-mark.svg` when it lands. Ships `logo-mark.svg`, a light / dark `favicon.svg` (replacing Vite's bolt), 192 / 512 / maskable-512 PNGs and a 180 px `apple-touch-icon.png`. Tests: the icons' real sizes and opaque backgrounds, the page's links, and Chromium's own installability check over CDP (no errors, no service worker needed). No service worker*

#### S-8.12.3 ⚪ Real-device pass
**Blocked-on:** the user's call — the [M12 plan](plans/m12-mobile-reading.md)'s open question 1 asks whether a pass on real phones is part of acceptance; its risks section says it should be. Filed 2026-10-19.
- [ ] T-8.12.3.1 One iPhone (Safari) and one Android phone (Chrome): open a report, the job Q&A thread and a knowledge report; check reflow, the bottom reading toolbar and Contents sheet, text size, the theme toggle
- [ ] T-8.12.3.2 With the on-screen keyboard open, the docked composer stays above it on both (the VisualViewport lift, which emulation cannot exercise); the field does not trigger iOS zoom
- [ ] T-8.12.3.3 Tap-to-preview on citation chips (first tap previews, second opens), the card's 44 px link, and the safe-area padding in landscape on a notched phone
- [ ] T-8.12.3.4 Add to Home Screen on both: the echo-mark icon, the paper splash, standalone launch at `/`, and back-gesture behaviour in standalone mode (unverified per the plan's risks)

---

## Open questions parking lot

These are real questions raised in conversation that don't yet have a Story home. When one of them is answered the answer becomes a Decision (`D-NNN`) and the question is converted into one or more Stories.

**Planning questions filed 2026-10-19 (the user's call; each lives in its plan, listed here so they are findable):** public sharing before billing and takedown tooling ([m11](plans/m11-public-report-sharing.md)); self-host TTS default and whether clip-stitched B-roll ever exists ([l2](plans/l2-author-studio.md)); private-by-key versus nothing for SaaS Echo, third-party-content default, the bubble shortcut, whether Gmail or Mode B are pursued at all ([l3](plans/l3-echo-personal-brain.md)); per-tier caps on saved searches ([m3](plans/m3-saved-searches-alerts.md)); the note weight's starting value ([m5](plans/m5-notes.md)); a relative publish window in templates ([m6](plans/m6-job-templates.md)); stance classification for YouTube documents ([m7](plans/m7-channel-intelligence.md)); graph library and whether a global view ships ([m9](plans/m9-citation-graph.md)); channel or topic job for the first run ([m10](plans/m10-onboarding.md)); the scoped `<style>` block for the palette ([m2](plans/m2-command-palette.md)).

- **OQ-1.** ✅ **Resolved 2026-04-26 by [D-021](decisions.md#d-021--topic-relevance-threshold--050-2026-04-26): `TOPIC_RELEVANCE_THRESHOLD = 0.50`.** Candidates below 0.50 hidden from default approval list but kept in the database; "Show low-relevance candidates" filter chip toggles cutoff to 0.0. Calibrated scoring (1.0 unambiguous / 0.5 adjacent / 0.0 unrelated) baked into the prompt with borderline 0.4–0.6 exemplars. Re-evaluation hooks documented (precision low → bump 0.60; recall low → drop 0.40; per-source-type override is the next escalation).
- **OQ-2.** ✅ **Resolved 2026-05-06 by [D-046](decisions.md#d-046--comment-tree-depth-per-platform-env-knob-no-per-job-override-resolves-oq-2-2026-05-06): per-platform env knob, no per-job override.** `app/config.py` exposes `REDDIT_COMMENT_DEPTH_DEFAULT` and `HN_COMMENT_DEPTH_DEFAULT` as independent settings (both default 50). No `jobs` schema column, no UI surface, no API parameter. Future platforms follow the same pattern (`<PLATFORM>_COMMENT_DEPTH_DEFAULT`). Per-job override revisits if real demand surfaces; per-platform tuning is a one-line env-var change.
- **OQ-3.** ✅ **Resolved 2026-05-06 by [D-047](decisions.md#d-047--sibling-pr-coordination-for-knowledge-curator--work-tracker-keep-separate-prs-resolves-oq-3-2026-05-06): keep separate PRs as the default.** Each skill owns its own branch + PR; the second-to-fire mentions the sibling via "Companion PR: #N" (already in SKILL.md). Combining is formally **descoped** — the v2 enhancement language in SKILL.md is no longer scheduled. Decoupling avoids one PR blocking the other and keeps each independently reviewable.
- **OQ-4.** Whisper for podcast Mode A vs external service (Deepgram / AssemblyAI) for SaaS tier? (Tied to E-1.7)
- **OQ-5.** ✅ **Resolved 2026-05-06 by [D-048](decisions.md#d-048--pdf-connector-intake-file-upload-only-for-v1-resolves-oq-5-2026-05-06): file upload only for v1.** Ratifies E-1.8 shipped scope (PR [#142](https://github.com/khoks/VideoResearchPro/pull/142)). URL-fetch deferred to a future Story under E-1.8; identity model (D-034 first-64KB SHA-256) is bytes-derived so URL-fetch lands without schema change. SSRF-protection model from E-1.6 trafilatura URL fetching can be reused when the URL-fetch Story ships.
- **OQ-6.** ✅ **Resolved 2026-05-06 by [D-049](decisions.md#d-049--echo-cold-start-readiness-threshold-shipped-triple-is-v1-personal-brainmd-sub-table-is-forward-looking-spec-resolves-oq-6-2026-05-06): shipped triple is v1.** Three criteria: `total_threshold=100` rows, `sources_threshold=3` distinct sources, `has_personality_trait=True`. The personal-brain.md four-row sub-table (Domains 1/2/3/5 minima) remains the forward-looking spec for once Domain 2 (activity stream) connectors land. Re-evaluation hook: when E-3.4 (speak-as-me agent) consumes `is_ready()` as a gate, mis-calibration becomes load-bearing — validate against real users at that point.
- **OQ-7.** ✅ **Resolved 2026-04-26 by [D-017](decisions.md#d-017--e-110-hard-cutover-single-migration-uuid-pk-promotion-2026-04-26): hard cutover.** Single Alembic migration adds `document_id UUID` + `source_id text`, backfills both, drops legacy `video_id` PK, adds `(source_type, source_id)` unique constraint, retargets `job_videos` + `transcript_cache` FKs in one transaction. T-1.10.8 (round-trip migration test + 168-test suite + e2e smoke) is gating. Pre-cutover backup `cp data/videoresearchpro.db data/videoresearchpro.db.pre-e110.bak` documented as a self-host fallback.
- **OQ-8.** ✅ **Resolved 2026-04-26 by [D-018](decisions.md#d-018--polymorphic-approvalcard-typescript-shape--four-sub-decisions-2026-04-26).** Locked-in shape lives in [source-types.md § Polymorphic ApprovalCard TypeScript shape](source-types.md#polymorphic-approvalcard-typescript-shape). User's overarching framing: *"keep the system a bit open ended for future enhancements and not too strict"*.
  - **(a)** ` SourceMetadata` hand-rolled in TS, kept synced with backend Pydantic by convention. Drift is a PR-review concern. Revisit if drift count climbs.
  - **(b)** Chip ` field` is ` keyof T` — pure source-metadata. Document-level fields render through fixed slots in ` <CardHeader>` and ` <CardActions>`, not chips.
  - **(c)** Hybrid formatters — named registry (` durationSeconds`, ` relativeTime`, ` signedNumber`, ` numberWithCommas`, ` truncate`) + optional ` format?: (v) => string` callback override.
  - **(d)** Separate ` FilterChip<T>` type. Source configs register two distinct arrays: ` metaChips` (display) and ` filterChips` (predicate).
  - T-1.5.4.1 unblocked. PR-review-driven drift correction documented as a revisit hook on (a); promotion to flat ` View<T>` documented as a revisit hook on (b) if a future source type wants Document-level chips.
- **OQ-9.** ✅ **Resolved 2026-04-26 by [D-019](decisions.md#d-019--codeowners--branch-protection-policy-for-autonomous-merge-sessions-2026-04-26).** User picked option (c) bypass list, but `bypass_pull_request_allowances` is not exposed on personal-account free-plan public repos (verified via PATCH that silently dropped the field). Pragmatic landing: `.github/CODEOWNERS` declares `@khoks` as owner of every path, and `required_approving_review_count` dropped to `0`. Net: `gh pr merge --squash --delete-branch` (no `--admin`) works on master immediately. Force-push still blocked. Two revisit hooks documented (second collaborator joins → Rulesets `bypass_actors`; org migration → `bypass_pull_request_allowances.users`).
- **OQ-10.** ✅ **Resolved 2026-04-26 by [D-020](decisions.md#d-020--file-orchestrator-dispatch-as-standalone-story-s-1511-2026-04-26): file as standalone S-1.5.11.** Dispatch layer ships once with the first two consumers (Reddit + HN) and is reused by every future connector. Folding into per-source storage tasks would duplicate the dispatch pattern N times. See [S-1.5.11](#s-1511--topic-job-routing-through-new-connectors) for the task breakdown.
- **OQ-12.** ✅ **Resolved 2026-04-28 by [D-023](decisions.md#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28): option (a) inline.** Each `BaseConnector` subclass calls `social_classify` from `app/services/social_classify.py` on its fetched text before returning Candidates. T-1.5.3.3 acceptance updated to "Inline call inside `RedditConnector.fetch_text()` and `HNConnector.fetch_text()` (and future connectors)."
- **OQ-13.** ✅ **Resolved 2026-04-28 — ship now as a tiny PR.** User approved. Post-OQ-11 dev wipe collapsed the rename from a high-risk migration to a one-line env default change. T-2.6.1 ships in this work cycle; T-2.6.6 documents the production-data migration path separately for self-hosters with accumulated embeddings.
- **OQ-14.** ✅ **Resolved 2026-04-28 by [D-024](decisions.md#d-024--flip-e-16-to--with-primitives-only-scope-split-2026-04-28): option (b) primitives-only split.** E-1.6 flips 🔴 → 🔵. trafilatura + Playwright primitives ship now as `app/services/article_extraction/` in service of S-1.5.8 Mode B paste. Full article-connector UX (RSS / search / approval card variant) stays deferred until after M-1.5. D-005 amended.
- **OQ-15.** ✅ **Resolved 2026-04-28 by [D-025](decisions.md#d-025--file-mvp-definition-of-done-as-milestone-m-15-2026-04-28).** Milestone M-1.5 — Reddit + HN end-to-end ingest filed under E-1.5 with 7 component checks: (1) E-1.10 cutover landed; (2) S-1.5.11 dispatcher; (3) T-1.5.1.4 + T-1.5.2.5 storage; (4) S-1.5.3 inline classifier per D-023; (5) S-1.5.4 polymorphic ApprovalCard with badges + filters; (6) S-1.5.5 citation rendering; (7) e2e pipeline tests for Reddit-only / HN-only / mixed source types.
- **OQ-11.** ✅ **Resolved 2026-04-28 — option (b) cleanest-reset chosen.** User authorized full data wipe ("I don't care about existing data and jobs"). Executed in this session:
  - Moved `data/videoresearchpro.db` (3.4 MB, 912 legacy `videos` rows + the empty post-rename `documents` table + all jobs / channels / Q&A history / transcript cache) to `data/.pre-cleanup-2026-04-28/`.
  - Moved `data/chroma/` (22 MB embedding store) to `data/.pre-cleanup-2026-04-28/` so dangling chunk metadata referencing wiped video_ids doesn't surface in Q&A retrieval.
  - Removed leftover test DBs (`data/test-e110-t1101.db`, `data/test-trace.db`).
  - Ran `alembic upgrade head` against an empty DB. **Full migration chain runs cleanly end-to-end**, including PR [#96](https://github.com/khoks/VideoResearchPro/pull/96)'s merge-node + my T-1.10.1 `document_id` UUID column.
  - Final state verified: `alembic_version = d12345678901` (single head, no parallel branches), all 11 tables present (`alembic_version`, `api_quota_log`, `channels`, `documents`, `job_videos`, `jobs`, `library_qa_exchanges`, `qa_exchanges`, `qa_history_exchanges`, `transcript_cache`, `users`), `documents.document_id VARCHAR(36) NOT NULL` exists with `ix_documents_document_id` unique index. FastAPI app imports cleanly (42 routes registered, title `Pratidhvani`).
  - The pre-cleanup snapshot is preserved in `data/.pre-cleanup-2026-04-28/` for paranoia; can be deleted whenever.
  - Side discovery: two pre-existing `test_llm_routing.py` tests were failing on master since `LLM_PRIMARY_MODEL` was added to `app/config.py` — they monkeypatch only `LLM_MODEL` but `_resolve_primary_model()` prefers `LLM_PRIMARY_MODEL`. Drive-by fixed alongside this cleanup.
- S-1.11.10 🟢 IP-block workarounds (D-051 hooks exercised 2026-07-22): `YOUTUBE_PROXY_URL` routes both the transcript API (GenericProxyConfig) and yt-dlp through an operator-supplied proxy; `YTDLP_COOKIES_FROM_BROWSER` / `YTDLP_COOKIES_FILE` (explicit opt-in) pass YouTube's "confirm you're not a bot" wall using the operator's own session; `YTDLP_DOWNLOAD_RATE_LIMIT` paces download attempts (the 60-video recovery sweep's ~180 burst downloads escalated the block). Diagnosis that motivated this: all 32 residual unavailable videos are public+live, failing only on fetch (transcript API `RequestBlocked` + yt-dlp bot-wall on all three player clients).
