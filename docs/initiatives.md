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

- **M-1.6** 🟡 (Mastodon + Bluesky end-to-end) — same pattern, two more connectors. **S-1.5.6 (Mastodon) shipped 2026-05-03** on `feat/s-1-5-6-mastodon-connector-2026-05-03` (this branch); S-1.5.7 (Bluesky) still ⚪ open as the second discovery surface. Storage + classifier + polymorphic approval / citation rendering reused from the M-1.5 plumbing without changes.
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
- [ ] T-1.5.1.6 Connector unit tests + end-to-end pipeline test *(unit tests landed in PR #70; e2e test pending orchestrator wiring)*
- [ ] T-1.5.1.7 Approval-UI card variant for Reddit (handle, score, comment count, snippet, sentiment hint)

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
- [ ] T-1.5.4.2 Stance / sentiment / **framing** badge sub-component (consumed by `<CardBadgeRow>`); tooltip-on-hover with full classification breakdown.
- [ ] T-1.5.4.3 Filter chips ("show only against", "show only positive", "show only experiential framing", "show only score ≥ N", **"Show low-relevance candidates" toggle** per [D-021](decisions.md#d-021--topic-relevance-threshold--050-2026-04-26)) — filter `source_metadata.<field>` regardless of `source_type`. Default approval list applies `topic_relevance >= 0.50`; the toggle drops the cutoff to 0.0 to surface hidden candidates. Filter state lives client-side; chips do not re-fetch / re-classify.
- [ ] T-1.5.4.4 Migrate existing YouTube approval card to `<ApprovalCard>` as the first config-entry consumer; verify visual + interaction parity vs. today's bespoke component before any social-post type is wired.
- [x] T-1.5.4.5 Reddit + HN config entries — *shipped 2026-05-02 PR [#118](https://github.com/khoks/VideoResearchPro/pull/118). `SOURCE_CONFIGS` mapped-type registry with three entries (video / reddit_post / hn_story); each carries platform glyph + chip layout + formatter selections. Mapped type forces compile-time exhaustiveness — adding Mastodon / Bluesky / podcast = one entry each.*

#### S-1.5.5 🟢 Citation rendering for social posts

**PR:** TBD
**Acceptance.** Q&A answer citations rendering for social `source_type` values shows author handle + post date + platform; clicks open the permalink with `#comment-<id>` anchor when the cite is from a reply.
**Tasks**
- [x] T-1.5.5.1 + T-1.5.5.2 Citation renderer dispatch + per-platform URL builders — *shipped 2026-05-02 PR [#117](https://github.com/khoks/VideoResearchPro/pull/117). `<CitationLink>` polymorphic component dispatches by `Reference.source_type`; `renderCitation(ref) → {href, label}` is the pure dispatcher (testable). Per-source labels: video → "title · channel · timestamp", reddit_post → "r/sub · u/author · title", hn_story → "HN · author · title". JobDetailPage + LibraryQAPage migrated. Backend QA-agent reference enrichment (emit source_type / permalink / author per source) is the post-MVP follow-up*

#### S-1.5.6 🟢 Mastodon connector

**PR:** TBD (this branch — `feat/s-1-5-6-mastodon-connector-2026-05-03`)
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
- [ ] T-1.5.8.2 Reuse `app/services/article_extraction/` (E-1.6 T-1.6.1 primitives) — depends on T-1.6.1 landing first per [D-024](decisions.md#d-024--flip-e-16-to--with-primitives-only-scope-split-2026-04-28)
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

#### S-1.5.11 🟢 Topic-job routing through new connectors

**PR:** TBD
**Filed 2026-04-26** per [D-020](decisions.md#d-020--file-orchestrator-dispatch-as-standalone-story-s-1511-2026-04-26) (resolves [OQ-10](#open-questions-parking-lot)). The Reddit (S-1.5.1) and HN (S-1.5.2) connectors emit `Candidate` objects standalone, but `app/tasks/job_tasks.py` does not route topic jobs through them yet. T-1.5.1.4 / T-1.5.2.5 (storage wiring, blocked on E-1.10) implicitly assume an orchestrator step that this Story owns.

**Acceptance.** Topic jobs with `source_types=["reddit_post","hn_story",...]` route through the connector registry via a `dispatch_by_source_type(source_type, ...)` mechanism. The dispatcher reads the connector registry and routes each `source_type` to its `BaseConnector` implementation (search → list → fetch_metadata → fetch_text). Per-source-type rate-limit + retry config externalized so each connector declares its own constraints. Progress reporting parity with the existing YouTube path (Redis pub/sub events match shape + cadence). End-to-end pipeline tests cover Reddit-only, HN-only, and mixed `["video","reddit_post","hn_story"]` jobs.

**Tasks**
- [x] T-1.5.11.1 Search-phase dispatcher in `app/services/connector_dispatch.py` — *shipped 2026-04-28 PR [#109](https://github.com/khoks/VideoResearchPro/pull/109). Exposes `dispatch_search(source_types, query, instructions, limit_per_type) -> DispatchResult` with per-source-type candidates + captured errors. Fail-isolated: missing connector / connector exception / `NotImplementedError` (PDF-style) all handled per-source. Sequential today; T-1.5.11.3 decides parallel/round-robin. 8 unit tests covering happy path, error isolation, and edge cases.*
- [ ] T-1.5.11.2 Per-source-type rate-limit + retry config in `BaseConnector` subclasses — *deferred polish; current sequential dispatch with each connector's internal rate-limit (e.g. RedditClient's 100 req/min) is sufficient for v1*
- [x] T-1.5.11.3 Fan-out semantics — *resolved as **sequential** for v1 in PR [#116](https://github.com/khoks/VideoResearchPro/pull/116). Parallel is the right answer for high-fanout multi-source jobs; deferred until we see concurrency pressure*
- [x] T-1.5.11.4 Progress-reporting parity — *shipped 2026-05-02 PR [#116](https://github.com/khoks/VideoResearchPro/pull/116). `execute_topic_job` reports combined candidate count via existing `publish_progress` / `publish_status_change` channels; UI WebSocket handler doesn't need source-type-specific branches.*
- [ ] T-1.5.11.5 End-to-end pipeline test: submit topic job with `source_types=["reddit_post"]` — *✅ shipped via integration test in PR [#116](https://github.com/khoks/VideoResearchPro/pull/116) (`test_execute_topic_job_reddit_only_goes_through_dispatch_path`). HTTP-level e2e via routers still pending*
- [ ] T-1.5.11.6 Same e2e test for `hn_story` — *pending; same pattern as T-1.5.11.5*
- [ ] T-1.5.11.7 Same e2e test for mixed `["video","reddit_post","hn_story"]` — *pending; needs LangGraph + dispatcher concurrent path*
**Dependencies.** Was independent of E-1.10 for build; e2e tests now run against the post-E-1.10 schema with storage tasks shipped.

### E-1.6 🔵 Article connector

**Status updated 2026-04-28** per [D-024](decisions.md#d-024--flip-e-16-to--with-primitives-only-scope-split-2026-04-28). Flipped 🔴 → 🔵 with **scope split**: pipeline primitives ship now in service of S-1.5.8; full article-connector UX stays deferred until after M-1.5.

**Scope (primitives, near-term).** Connector-agnostic text-extraction module under `app/services/article_extraction/`: trafilatura primary, Playwright fallback for SPAs, hybrid strategy (try trafilatura → fall back if `word_count<200` or extraction fails). Single API: `extract_text(url) -> ExtractionResult` returning `{text, title, author, published_at, language, word_count, source}`. Reused by S-1.5.8 Mode B paste.

**Scope (full UX, post-M-1.5).** Discovery flow (search-engine API like Brave / Kagi / Tavily, or RSS feed ingestion); Direct flow (URL list, file upload); approval card variant for articles with title + author + excerpt + source-domain.

**Tasks**
- [ ] T-1.6.1 🔵 Build `app/services/article_extraction/` module — trafilatura wrapper + Playwright fallback + hybrid strategy + `ExtractionResult` dataclass + tests against fixture HTML.
- [ ] T-1.6.2 ⚪ Article search-engine integration (Brave / Kagi / Tavily) — *deferred until post-M-1.5*.
- [ ] T-1.6.3 ⚪ RSS feed ingestion path — *deferred until post-M-1.5*.
- [ ] T-1.6.4 ⚪ Article approval card variant + Q&A citation rendering — *deferred until post-M-1.5*.
- [ ] T-1.6.5 ⚪ End-to-end article-job pipeline test — *deferred until post-M-1.5*.

### E-1.7 ⚪ Podcast connector

**Scope.** Spotify/Apple show URL or RSS feed → episode list → text from existing transcript or Whisper transcription. Each episode = one `Document` with `source_type='podcast'`.

### E-1.8 ⚪ PDF / e-book connector

**Scope.** File upload (multipart). PyMuPDF text extraction; per-page boundaries preserved as segment metadata.

### E-1.9 ⚪ Rename `channels` → `creators` (DB + ORM)

**Scope.** Generalizes the YouTube-channel concept to any creator (podcast host, blog author, Twitter handle). Pure rename PR; no behavioral change.
**Note.** Plays the same role for creators as E-1.4 played for documents.

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

---

## I-2 🟡 Brand & visual identity rollout

**Status reconciliation 2026-04-26.** A backlog audit on 2026-04-26 revealed I-2 is **substantially shipped** — 4 of 6 epics are 🟢 (tokens, primitives library, page migration, sidebar nav). The earlier characterization in feature-roadmap.md ("documented but zero code shifted") was inaccurate; the warm-editorial migration largely landed in earlier sessions and was not reflected here. Remaining I-2 work: E-2.5 (marketing landing page) ⚪ and E-2.6 (code identifier rename) 🟡 partial. I-2 stays 🟡 (in-progress) until both ship.

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

### E-2.5 🟡 Marketing landing page (warm-editorial)

**Scope.** Static landing page under `marketing/` describing the curated-personal-wiki pitch, screenshots, install instructions, SaaS waitlist. Folder does not yet exist (verified 2026-04-26 — no `marketing/` directory in repo).

**Tasks** (initial)
- [x] T-2.5.1 Astro project scaffold under `marketing/` *(shipped 2026-04-28 — PR [#98](https://github.com/khoks/VideoResearchPro/pull/98); Astro ^5.0.0 chosen per [D-022](decisions.md#d-022--astro-for-the-marketing-landing-page-2026-04-28). `package.json` / `astro.config.mjs` / `tsconfig.json` (extends `astro/tsconfigs/strict`) / `.gitignore` / `README.md` + `BaseLayout.astro` mirroring `frontend/src/theme.ts` tokens + `index.astro` placeholder hero with brand lockup)*
- [ ] T-2.5.2 Hero with the personal-wiki pitch + tagline ("Your sources, echoed back" or similar from branding.md).
- [ ] T-2.5.3 "How it differs from Wikipedia" section (curation thesis).
- [ ] T-2.5.4 Source-types matrix (videos / podcasts / articles / etc.) reflecting current support.
- [ ] T-2.5.5 "How it works" walkthrough (search → approve → embed → ask).
- [ ] T-2.5.6 Install instructions (open-source self-host).
- [ ] T-2.5.7 SaaS waitlist hook (future-only — disabled call-to-action today).
- [ ] T-2.5.8 Footer: GitHub, docs, license.

### E-2.6 🟡 Code identifier rename pass

**Status partial 2026-04-26.** User-facing brand copy moved to `Pratidhvani` (CLAUDE.md, README, page strings, doc headers — all migrated). Legacy code identifiers remain in env-var defaults, package paths, the SQLite filename, and the Chroma collection name. Audit on 2026-04-26 found 73 occurrences of `videoresearchpro` / `VideoResearchPro` across 30 files; many are intentional grandfathered env-var defaults but a meaningful subset is rename-eligible.

**Remaining identifiers (high-level inventory).**
- [ ] T-2.6.1 `CHROMA_GLOBAL_COLLECTION_NAME` default `videoresearchpro_global` → `pratidhvani_global`. **Requires migration** — existing collections need to be copied/renamed via a one-time backfill script, not just an env default change. Risk-rate: high (lose embeddings = lose Q&A retrieval).
- [ ] T-2.6.2 `DATABASE_URL` default `sqlite:///./data/videoresearchpro.db` → `pratidhvani.db`. Requires data migration or symlink for existing self-hosters.
- [ ] T-2.6.3 Backend package paths — currently `app.*` (already neutral); no rename needed unless a top-level rename is wanted (e.g. directory `backend/` → `backend/` no change).
- [ ] T-2.6.4 GitHub repo rename `khoks/VideoResearchPro` → `khoks/pratidhvani` (or similar). Outside-codebase action; redirects auto-handled by GitHub but old PR / issue URLs depend on the redirect.
- [x] T-2.6.5 Audit + fix any remaining strings in tests, scripts, docstrings that aren't grandfathered env-var references. *(shipped 2026-04-28 — PR [#97](https://github.com/khoks/VideoResearchPro/pull/97); 9 files updated: `APP_NAME` default, `/api/v1/health` response, startup log, `POST /restart` docstring, two service module docstrings, env template header, paired test, restart-services.ps1. Intentional non-changes for future migration tasks documented in PR body)*
- [ ] T-2.6.6 Migration runbook covering data preservation for self-hosters running the legacy names.

**Sequencing.** T-2.6.1 / T-2.6.2 are gated by a thoughtful migration story (they're production-data-mutating). T-2.6.5 is purely cosmetic and can ship anytime. T-2.6.4 can ship anytime but is outside the codebase. Decoupled from D-001 because identifier renames need a deliberate migration; brand copy moved immediately.

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

- **OQ-1.** ✅ **Resolved 2026-04-26 by [D-021](decisions.md#d-021--topic-relevance-threshold--050-2026-04-26): `TOPIC_RELEVANCE_THRESHOLD = 0.50`.** Candidates below 0.50 hidden from default approval list but kept in the database; "Show low-relevance candidates" filter chip toggles cutoff to 0.0. Calibrated scoring (1.0 unambiguous / 0.5 adjacent / 0.0 unrelated) baked into the prompt with borderline 0.4–0.6 exemplars. Re-evaluation hooks documented (precision low → bump 0.60; recall low → drop 0.40; per-source-type override is the next escalation).
- **OQ-2.** Comment-tree default depth — top 50 by score is the proposed default; configurable per-job? Per-platform? (Tied to S-1.5.1, S-1.5.2)
- **OQ-3.** Sibling-PR coordination — should `/knowledge-curator` and `/work-tracker` share a single PR per session? (Tied to E-4.6)
- **OQ-4.** Whisper for podcast Mode A vs external service (Deepgram / AssemblyAI) for SaaS tier? (Tied to E-1.7)
- **OQ-5.** PDF connector: file upload only, URL only, or both? (Tied to E-1.8)
- **OQ-6.** Echo cold-start readiness threshold — quantitative criteria? (Tied to E-3.5)
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
