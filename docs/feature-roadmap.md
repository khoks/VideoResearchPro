# Pratidhvani — Feature Roadmap

**Status:** approved (2026-04-24). Living document; status of each item updates as work lands.

This is the canonical roadmap. Each entry has: motivation, sketch, schema/API impact, open questions, and status. The high-level phases live in [vision.md](vision.md).

---

## Status legend

| Marker | Meaning |
|--------|---------|
| 🟢 shipped | Feature is live and stable |
| 🟡 in-progress | Branch / PR open |
| 🔵 accepted | Approved, not yet started |
| ⚪ proposed | Idea documented; not yet approved |
| 🔴 deferred | Approved earlier, deprioritized for now |

---

## Large-scale features (L1-L5)

Multi-week each. Foundational. Each one reshapes the schema or adds a top-level surface.

---

### L1 — Multi-source ingest 🟢

**Motivation.** Today the only source-type is YouTube video. The user's vision (see [vision.md](vision.md) Ring 2) is a personal wiki built from podcasts, articles, threads, books, and forum posts in addition to videos — all flowing through the **same** search → approval → ingest → embed → query pipeline. The curation surface is the product, so it must generalize.

**Sketch.** Generalize the data model:

- Promote the `videos` table to `documents`. Add `source_type` enum: `video` / `podcast` / `article` / `tweet` / `forum_post` / `pdf`.
- Add `documents.source_url`, `documents.source_metadata` (JSON, source-specific shape), `documents.text_content` (extracted clean text, replacing `transcript_segments`).
- Rename `transcript_cache` to `text_cache`.
- Keep `videos` as a SQL view over `documents WHERE source_type = 'video'` for back-compat.
- Each new source type ships with a **connector** that implements a defined interface (search, fetch metadata, fetch content, post-process). Contract lives in [source-types.md](source-types.md).
- The single global Chroma collection (`videoresearchpro_global` → renamed `pratidhvani_global`) holds all source types; per-source filtering is a metadata predicate at query time, identical to today's per-job filter.

**Schema impact.**

- New columns on `documents`: `source_type`, `source_url`, `source_metadata`, `text_content`.
- New table `document_segments` replacing the YouTube-specific timestamp segments — generalized to `(start_offset, end_offset, segment_metadata)` where offset semantics depend on source type (seconds for video/podcast, character offsets for article/PDF).
- `job_videos` → `job_documents`.
- ChromaDB collection rename + metadata-key normalization.

**API impact.**

- `POST /api/v1/jobs` body grows a `source_types` array (defaults to `["video"]` for back-compat).
- `GET /api/v1/library/videos` joined by `GET /api/v1/library/documents` (new); old endpoint stays as a typed view.
- New endpoints per source type for connector-specific concerns (e.g. `POST /api/v1/sources/podcast/resolve` for an Apple podcast URL → RSS feed).

**Open questions.**

- How do PDFs get ingested? File upload (multipart) vs URL only. Recommend both, behind a feature flag.
- Whisper transcription for podcasts: same Whisper pipeline as YouTube fallback, or external API (Deepgram, AssemblyAI)? Recommend reuse of the existing local Whisper for self-host; SaaS tier can route to a service.
- How are forum threads chunked — by reply, by token-budget, or as a single doc with reply boundaries preserved? Recommend single doc with `segment_metadata.reply_index`.
- Source-type ordering when ingesting a mixed job: round-robin, sequential, or parallel? Recommend parallel with per-type rate limits.

**Status.** 🟢 **Closed 2026-05-03.** Twelve source types end-to-end (`video` / `reddit_post` / `hn_story` / `mastodon_post` / `bluesky_post` / `podcast_episode` / `pdf` / `article` / `fb_post` / `ig_post` / `li_post` / `tweet`). Polymorphic plumbing claim validated 12× across all axes of variation: discovery surface (search APIs / RSS / paste / no-discovery), storage (in-place / file upload / URL-only), citation (per-reply / per-timestamp / per-page / per-URL). Full chronological PR trace in [`initiatives.md` § I-1](initiatives.md#i-1-multi-source-ingest-original-scope-closed-2026-05-03-reopened-2026-07-22-for-e-111-scale-resilience).

- 🟢 **Foundation (PRs #63 / #65 / #66 / #67, shipped 2026-04-22 → 04-25).** Schema additive columns; `BaseConnector` interface; routed call sites; `videos` → `documents` table + ORM rename. See [`initiatives.md`](initiatives.md#i-1-multi-source-ingest-original-scope-closed-2026-05-03-reopened-2026-07-22-for-e-111-scale-resilience) for the full E-1.1 → E-1.4 trace.
- 🟢 **Reddit + HN candidate connectors shipped standalone (S-1.5.1 PR #70, S-1.5.2 PR #73).** Both emit `Candidate` objects with namespaced `source_id` (`reddit:abc`, `hn:42M`); pseudo-timestamp synthesis at 3 wps codified in [D-013](decisions.md#d-013-pseudo-timestamps-at-3-wps-for-text-based-connectors-2026-04-25).
- 🟢 **E-1.10 (UUID PK promotion) shipped 2026-05-02** ([PR #112](https://github.com/khoks/VideoResearchPro/pull/112)). Per [D-015](decisions.md#d-015-promote-e-110-uuid-pk-ahead-of-reddit-hn-orchestrator-wiring-2026-04-26) + [D-017](decisions.md#d-017-e-110-hard-cutover-single-migration-uuid-pk-promotion-2026-04-26) hard cutover. `documents.video_id` PK retired; `document_id` UUID PK + the existing `(source_type, source_id)` unique index now form the canonical identity. `job_videos` → `job_documents`; `transcript_cache` PK retargeted. Reddit + HN storage tasks (T-1.5.1.4 + T-1.5.2.5) shipped same-day on the new schema ([PR #113](https://github.com/khoks/VideoResearchPro/pull/113)) along with classifier persistence (T-1.5.3.4) into `Document.source_metadata_json["classification"]`.
- 🟢 **Milestone M-1.5 (Reddit + HN end-to-end) shipped 2026-05-03.** All 7 component checks closed: E-1.10 cutover, S-1.5.11 dispatcher + orchestrator wiring, T-1.5.1.4/T-1.5.2.5 storage, S-1.5.3 inline classifier persistence, S-1.5.4 polymorphic `<ApprovalCard>` + filter rail page integration, S-1.5.5 polymorphic citation rendering, e2e pipeline tests (Reddit-only / HN-only / mixed / partial-failure). Closing PRs cited inline in [`initiatives.md` § M-1.5](initiatives.md#m-15-milestone-reddit-hn-end-to-end-ingest-closed-2026-05-03). Polish deferred to follow-up: classifier golden tests (T-1.5.3.5), framing exemplars literally embedded in the LLM prompt (T-1.5.3.6), backend reference enrichment in `extract_references`, HTTP-level integration tests.
- 🟢 **Milestone M-1.6 (Mastodon + Bluesky end-to-end) shipped 2026-05-03.** Both connectors landed same-day on top of M-1.5: [S-1.5.6 PR #128](https://github.com/khoks/VideoResearchPro/pull/128) (Mastodon — public hashtag timeline, Unicode-tolerant hashtag normalisation, OP + top-N replies by favourites) and [S-1.5.7 PR #129](https://github.com/khoks/VideoResearchPro/pull/129) (Bluesky — public AT-Proto XRPC `searchPosts`, free-text search, OP + top-N replies by likes). Both ship the `comment_url` reply-anchor pattern so per-reply citations deep-link to the exact reply rather than the OP. **The structural promise of M-1.5 — that polymorphic plumbing generalises without core changes — held**: each connector was one entry in `SourceMetadata`, `SOURCE_CONFIGS`, `videoToApprovalProps`, `_chunk_to_reference`, and `<CitationLink>`'s dispatcher. Four social-media surfaces now battle-tested (Reddit / HN / Mastodon / Bluesky).
- 🟢 **Backend reference enrichment fully closed 2026-05-03.** Per-document polymorphic Chroma metadata in [PR #131](https://github.com/khoks/VideoResearchPro/pull/131); per-segment reply-anchor fields (`comment_id` / `comment_url`) and the polymorphic `extract_references` LLM-prompt update in [PR #134](https://github.com/khoks/VideoResearchPro/pull/134). The chunker now preserves segment-level `extra` through sentence-expansion + greedy-packing and applies a dominant-segment heuristic to promote per-reply identity to chunk metadata. **Production citations across all 5 source types now render polymorphically with per-reply deep-links** where the chunk originated from a specific reply.
- 🟢 **Article-extraction primitives shipped 2026-05-03** ([PR #135](https://github.com/khoks/VideoResearchPro/pull/135), T-1.6.1). `app/services/article_extraction/` — `ExtractionResult` + `extract_text(url)` hybrid orchestrator (httpx → trafilatura → Playwright fallback). 20 unit tests; backend suite 593 passing. **Unblocks S-1.5.8 Mode B paste-mode**.
- 🟢 **I-2 (Brand & visual identity rollout) closed 2026-05-03.** All 6 epics shipped: tokens layer, primitives library, page migration, sidebar nav (all earlier sessions); marketing landing page ([PR #136](https://github.com/khoks/VideoResearchPro/pull/136)); code-identifier-rename pass + safe-execution runbook ([PR #137](https://github.com/khoks/VideoResearchPro/pull/137)).
- 🟢 **Milestone M-1.7 (Podcast end-to-end) shipped 2026-05-03** ([PR #140](https://github.com/khoks/VideoResearchPro/pull/140)). Sixth source type. Two-tier discovery (iTunes Search → per-show RSS), in-feed `<podcast:transcript>` (SRT / VTT) preferred over Whisper fallback, per-segment `extra` carries `comment_url` with `#t=<sec>` fragment for podcast-player deep-linking. Whisper-as-service decision (OQ-4) resolved per [D-033](decisions.md#d-033-whisper-as-service-for-podcasts-reuse-existing-openai-whisper-path-resolves-oq-4-2026-05-03) — reuse existing OpenAI Whisper path; local-Whisper opt-in deferred to follow-up. 44 new tests; backend suite 637 passing.
- 🟢 **T-1.6.6 (Playwright fallback) shipped 2026-05-03** ([PR #141](https://github.com/khoks/VideoResearchPro/pull/141)). Closes E-1.6 primitives layer fully. Replaces T-1.6.1 stub with real headless-Chromium SPA extraction. Opt-in via `backend/requirements-spa.txt` + `ARTICLE_PLAYWRIGHT_ENABLED=True`. **Unblocks S-1.5.8 T-1.5.8.5** (FB / IG paste). 8 new tests; backend suite 645 passing.
- 🟢 **Milestone M-1.8 (PDF / e-book end-to-end) shipped 2026-05-03** ([PR #142](https://github.com/khoks/VideoResearchPro/pull/142)). Seventh source type — and the **first with no discovery surface** (PDFs come from upload, not search). `POST /api/v1/library/upload-pdf` accepts multipart, hashes via [D-034 first-64KB SHA-256](decisions.md#d-034-pdf-source-type-identity-uses-first-64kb-sha-256-not-full-file-hash-2026-05-03), persists raw bytes for re-extraction, runs PyMuPDF text + table extraction with per-page boundaries, embeds. `GET /api/v1/library/pdf/{digest}.pdf` serves bytes back so per-page `#page=<N>` deep-link citations work. Connector raises `NotImplementedError` on `search()` per [D-035](decisions.md#d-035-connectors-with-no-discovery-surface-raise-notimplementederror-dispatcher-treats-as-zero-candidates-2026-05-03). 19 new tests; backend suite 664 passing.
- 🟢 **S-1.5.8 Mode B paste-mode shipped 2026-05-03** ([PR #144](https://github.com/khoks/VideoResearchPro/pull/144)). Twelfth source type total — 5 paste-mode connectors (`article` / `fb_post` / `ig_post` / `li_post` / `tweet`) sharing a single `_PasteURLBaseConnector` extractor. URL→source_type host-based routing per [D-036](decisions.md#d-036--paste-mode-emits-five-distinct-source_type-discriminators-not-a-single-paste-2026-05-03). New `POST /api/v1/library/paste-urls` endpoint accepts up to 100 URLs/batch; per-URL result dicts let the frontend show per-URL state. 51 new tests; backend suite 715 passing.
- 🟢 **E-1.6 (Article connector) closed 2026-05-03** ([PR #145](https://github.com/khoks/VideoResearchPro/pull/145)). Full UX: T-1.6.2 Brave Search integration (per [D-037](decisions.md#d-037-brave-search-as-the-default-article-search-engine-provider-2026-05-03), free-tier-friendly default; gated on `BRAVE_SEARCH_API_KEY` opt-in), T-1.6.3 RSS feed iteration via `list_creator_items(feed_url)`, T-1.6.4 already shipped in PR #144's S-1.5.8 wave, T-1.6.5 covered by existing e2e + new connector tests. 19 new tests; backend suite 734 passing.
- 🟢 **E-1.9 (channels → creators rename) closed 2026-05-03** ([PR #146](https://github.com/khoks/VideoResearchPro/pull/146)). Python-level rename: `Creator` re-exported as alias for `Channel` from new module `app.models.creator`. SQL-level table rename deferred to operator-coordinated runbook at [`docs/migration-channels-to-creators.md`](migration-channels-to-creators.md) per the [D-032](decisions.md#d-032-operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03) precedent established by E-2.6.
- **I-1 🟢 — fully closed 2026-05-03.** Two of six top-level initiatives now shipped (I-1 + I-2). What's next: L2 Author Studio ([I-6](initiatives.md#i-6-author-studio-output-generation-l2)), L3 Echo personal brain ([I-3](initiatives.md#i-3-echo-personal-brain-l3)), L5 SaaS readiness ([I-5](initiatives.md#i-5-saas-readiness-long-horizon-code-shippable-work-fully-closed-2026-05-05)), or the optional S-1.5.9 / S-1.5.10 Twitter BYOK paths.
- 🟢 **S-1.5.9 + S-1.5.10 (BYOK Twitter / X) shipped 2026-05-04** ([PR #148](https://github.com/khoks/VideoResearchPro/pull/148)). Closes the explicitly-opt-in Twitter v2 path per [D-009](decisions.md#d-009-twitter-x-is-byok-opt-in-2026-04-25). New `TwitterClient` (bearer-auth, `/2/tweets/search/recent` with `expansions=author_id`) + `TwitterConnector` subclassing paste-mode `TweetConnector` (overrides `search()` / `list_creator_items()` / `resolve_creator_id()`; inherits paste-mode `fetch_text` so paste-only operators still work without a Bearer token). Re-registration pattern in `app/sources/__init__.py` makes registry's last-write-wins prefer search-having connector. `/api/v1/health` capability flags (`twitter_search_enabled` / `article_search_enabled` / `playwright_fallback_enabled` / `whisper_transcribe_enabled`) let frontend disable search surfaces without inspecting env. 28 new tests; backend suite 749 → 777.
- 🟢 **I-5 / E-5.1 SaaS tenancy retrofit fully closed 2026-05-04.** Five-phase rollout per [D-038](decisions.md#d-038-tenancy-retrofit-ships-in-four-phases-audit-additive-backfillwrites-reads-not-null-2026-05-04): [PR #149](https://github.com/khoks/VideoResearchPro/pull/149) phase 0 audit, [PR #150](https://github.com/khoks/VideoResearchPro/pull/150) phase 1 additive columns, [PR #151](https://github.com/khoks/VideoResearchPro/pull/151) phase 2a backfill+writes, [PR #152](https://github.com/khoks/VideoResearchPro/pull/152) phase 2b reads, plus phase 2c [`docs/migration-tenant-id-not-null.md`](migration-tenant-id-not-null.md) operator runbook + `e6f7a8b9c0d1` Alembic migration. Codebase moves from structurally single-tenant (zero `tenant_id` columns) to fully tenant-isolated.
- 🟡 **I-5 SaaS readiness — E-5.2 / E-5.4 / E-5.5 / E-5.6 foundations shipped 2026-05-04.** Four foundation PRs after E-5.1 closure: [PR #155](https://github.com/khoks/VideoResearchPro/pull/155) E-5.2 subscription tier enum + `require_tier` / `require_feature` dependencies (24 tests), [PR #156](https://github.com/khoks/VideoResearchPro/pull/156) E-5.4 audit log + account lockout + password reset (22 tests), [PR #157](https://github.com/khoks/VideoResearchPro/pull/157) E-5.5 rate-limit middleware with sensitive-endpoint + per-tier buckets (12 tests), [PR #158](https://github.com/khoks/VideoResearchPro/pull/158) E-5.6 per-user BYOK LLM credentials with Fernet encryption (20 tests). Backend suite 777 → 855. **Remaining I-5 work** — E-5.3 Stripe, E-5.7 Data residency, E-5.8 Hosting, E-5.9 Hosted UX — is design-complete and code-deferred to SaaS launch (none has meaningful code work for a self-host install).
- 🔵 **Remaining E-1.5 surfaces**: S-1.5.8 Mode B paste-mode (now unblocked by T-1.6.1), then BYOK Twitter API ([D-009](decisions.md#d-009-twitter-x-is-byok-opt-in-2026-04-25)). Discord and TikTok deferred ([D-010](decisions.md#d-010-defer-tiktok-and-per-server-discord-bot-indefinitely-2026-04-25)). All slot into the same polymorphic plumbing M-1.5 / M-1.6 validated.
- 🟡 **Article connector (E-1.6)**: primitives ✅, full UX deferred until after M-1.7.
- ⚪ Podcast (E-1.7), PDF/e-book (E-1.8), `channels` → `creators` rename (E-1.9).

Targeted Phase 2 (2026 Q3) for non-foundation source types. Detailed design in [source-types.md](source-types.md).

---

### L2 — Author Studio (output generation) ⚪

**Motivation.** The accumulated library is rich enough to produce **derivative artifacts** — books, websites, decks, newsletters, reels — not just answers. The user explicitly asked for this. Output generation closes the loop: ingest → understand → produce.

**Sketch.** A new top-level surface "Author" with five sub-surfaces:

- **Book** — long-form structured Markdown → typeset PDF / EPUB. Map-reduce over selected jobs / topics / Q&A history. Use the harness's `anthropic-skills:docx` for `.docx`, custom typeset for PDF, pandoc-style for EPUB. Citations rendered as endnotes with deep links.
- **Static site** — Astro (or 11ty) static build under `outputs/sites/<slug>/`. The user picks a subset of the library (shelves, jobs, knowledge artifacts), the system generates a personal-wiki site with reading-room typography, search, and citation links. Optionally publish to GitHub Pages or Netlify via a one-click integration.
- **Slides (PPTX)** — `anthropic-skills:pptx` produces a slide deck from a chosen topic. Each slide cites its source.
- **Newsletter / digest** — recurring scheduled output (weekly / monthly) emailed to the user, summarizing new content + new Q&As + a featured deep-dive.
- **Video / reel** — script + storyboard generated from knowledge artifacts; narration via TTS (ElevenLabs / OpenAI / local Coqui); optionally clip-stitch source videos for B-roll. Most ambitious sub-surface; ships last.

**Schema impact.**

- New table `outputs(id, output_type, title, source_selection_json, status, artifact_path, created_at, completed_at, owner_id)`.
- New `output_citations(output_id, document_id, segment_id, citation_text, position)`.
- Reuse existing job lifecycle (`pending → processing → completed/failed`) for outputs.

**API impact.** New top-level routes:
- `POST /api/v1/outputs` (create)
- `GET /api/v1/outputs` (list)
- `GET /api/v1/outputs/{id}` (status)
- `GET /api/v1/outputs/{id}/download` (artifact)

**Open questions.**

- Books: do we ship templates (academic, casual, journalistic) or a single editorial template? Recommend single + customization later.
- Sites: hosted preview vs download-only? Recommend download-only initially; hosted preview as a SaaS-tier feature.
- TTS provider: local-first (Coqui) for self-host, paid (ElevenLabs) for SaaS Pro.
- Reels: vertical 9:16 vs flexible aspect? Recommend vertical-only for v1.

**Status.** ⚪ proposed. Targeted Phase 3 (2026 Q4). Books first, reels last.

---

### L3 — Echo (the personal brain) ⚪

**Motivation.** The widest ring of the vision (see [vision.md](vision.md) Ring 3). Pratidhvani learns enough about the user — through opt-in life connectors *and* constant-stream sharing of liked videos / reels / memes / WhatsApp threads / Keep notes / quotes — that it can suggest questions before they ask, anticipate their needs, capture their personality, and eventually speak on their behalf.

The user-facing surface has a name: **Echo**, a proper-noun reuse of the brand's literal meaning (*Pratidhvani* = echo). Echo is **the** killer L3 feature; everything else in this entry is its supporting infrastructure. Per the user's 2026-04-24 framing (verbatim in [`notes/2026-04-24-echo-feature-vision.md`](notes/2026-04-24-echo-feature-vision.md)): *"behave just like the individual who is using it… their own perception, their own lens, their own apprehensions, their own methodology, their own style of talking."*

**Sketch.** Five components:

1. **Personal context store** — separate schema (`personal_facts` + `personal_context_global` Chroma collection) holding what the user has *told* or *connected* about themselves: location history, interests, hobbies, work, talents, skills, personality dimensions, life events, opinions, daily routine.
2. **Activity ingestion connectors (pull-mode)** — pluggable, opt-in, scoped, revocable. Each connector lands as its own PR. YouTube watch history → Spotify → Goodreads → calendar → Apple Health → GitHub → browser history → journal → email. See [personal-brain.md](personal-brain.md) for the connector contract.
3. **Personality capture & "speak as me" agent** — captures the user's writing samples, Q&A patterns, recurring framings, *plus* trusted conclusions, preferred solutions, recommendation lens, apprehensions, methodology, topic emphasis, perception lens. Drafts responses to incoming messages in the user's voice using their accumulated knowledge. Two modes: **A** prompt-time retrieval of personality signals (default), **B** opt-in per-user fine-tuning post-readiness, on curated dataset themes (problem-solution, recommendation lens, situational priority, opinion-formation, methodology) plus an agentic harness that consults the right substrate per turn.
4. **Constant-stream intake (push-mode sharing)** — `shares_inbox` table fed by OS share targets, browser extension, email-in inbox, drag-drop dropzone, manual quick-share. Friction-free intake of liked videos / reels / memes / WhatsApp threads / Keep notes / quotes / voice memos. Cross-feeds Domains 1 (facts), 2 (events), 3 (personality signals), and the source library. The single richest signal feeder for Echo readiness.
5. **Always-evokable Echo surface** — floating bubble present on every page (the "Jarvis" pattern). One-click expand into chat panel; keyboard `cmd+e` / `ctrl+e`. Cold-start readiness gating: Echo refuses (showing a progress meter) until the user crosses thresholds across all five domains.

**Schema impact.** Substantial new schema, isolated from the source library. New tables: `personal_facts`, `activity_events`, `voice_signals`, `shares_inbox`. New Chroma collections: `personal_context_global`, `activity_stream_global`, `shares_global`. See [personal-brain.md](personal-brain.md).

**API impact.** New top-level `/api/v1/me/*` endpoints for connectors, context store, personality agent. New `/api/v1/echo/*` endpoints for the always-evokable surface (chat, readiness status, fine-tune control). New `/api/v1/shares/*` for constant-stream intake (POST from share targets, browser ext, email-in webhook, drag-drop).

**Cold-start readiness threshold** (recommended initial — see [personal-brain.md](personal-brain.md) for sub-table):

| Signal | Minimum |
|--------|---------|
| Self-authored personal facts | 30 facts across ≥ 3 categories |
| Activity events (any connector) | 90 days, ≥ 200 events |
| Personality signals | ≥ 50 signals across ≥ 4 types |
| Constant-stream shares | ≥ 100 shares spanning ≥ 4 content types |

Below threshold: bubble dimmed, banner explains what's missing. Crossing threshold: bubble lights up, one-time onboarding moment.

**Open questions.** Many — see [personal-brain.md](personal-brain.md). Privacy model is the largest open design space; fine-tuning leverage and corpus thresholds are the second-largest.

**Status.** ⚪ proposed. Targeted Phase 6 (2027 Q3+). Components land in order:

1. Constant-stream intake first (Domain 5) — it's the highest-leverage, lowest-privacy-load entry point and starts feeding the readiness corpus immediately.
2. Personal context store + manual personality signals (Domains 1 + 3, retrieval mode only).
3. Activity connectors (Domain 2), one at a time, easiest first (YouTube watch history → Spotify → email → calendar).
4. "Speak as me" agent + Echo bubble (Domain 4) — once the corpus crosses readiness for any subset of users.
5. Mode B fine-tuning — opt-in, after Mode A is stable and readiness data shows the corpus warrants it.

---

### L4 — Curated source ranking ⚪

**Motivation.** The user explicitly framed Pratidhvani as a counter to mainstream-balanced encyclopedias. Today every source contributes equally to retrieval; tomorrow the user's curation must be a first-class signal everywhere — in retrieval ordering, in answer composition, in disagreement surfacing.

**Sketch.**

- **Source weights.** Per-channel / per-source explicit trust score (e.g. 0.0-2.0, default 1.0). User can boost trusted creators or de-rank ones they ingested but disagree with. Stored in `channels.trust_weight` (and `documents.author_trust_weight` for non-channel sources).
- **Weighted retrieval.** ChromaDB's similarity score is multiplied by source trust weight before re-ranking. The top-K result set thus skews to higher-weighted sources.
- **Source narratives.** When the user queries a topic, the answer optionally surfaces multiple perspectives side-by-side: "Mainstream view (low-weight sources): X. Your trusted creators: Y." Implemented as a new Q&A agent path that segments retrieval by weight bands.
- **Disagreement detection.** A pre-answer pass clusters retrieved fragments by stance (LLM judge). When clusters disagree materially, the answer preserves both views attributed to their sources.
- **User opinions / annotations.** See M5 (Notes). Notes are first-class searchable docs and contribute to retrieval just like any other source — user notes default to weight 1.5x.

**Schema impact.**

- `channels.trust_weight` (float, default 1.0)
- `documents.author_trust_weight` (float, nullable; falls back to channel weight)
- `notes` table (see M5)

**API impact.**

- `PUT /api/v1/channels/{id}/weight` — set trust weight
- `POST /api/v1/library/qa` body grows optional `surface_disagreement: bool`, `weight_strategy: "default" | "user_first" | "mainstream_first"`

**Open questions.**

- Should the user weight individual creators within a channel (e.g. one host vs another)? Recommend channel-only for v1.
- Disagreement surfacing — opt-in per query, or always-on for queries that retrieve from disparate-weighted sources? Recommend opt-in.
- How does weighting interact with subscriptions (auto-pulled content)? Recommend channel weight applies; user can override per-document.

**Status.** ⚪ proposed. Targeted Phase 4 (2027 Q1).

---

### L5 — SaaS-readiness layer 🟡

**Motivation.** Open-source self-host is the launch posture; public SaaS is the endgame. Today's PRs must not bake in assumptions that block the migration — single-tenant queries, hard-coded quotas, lack of tenancy columns, etc.

**Sketch.** This L5 is mostly **doc + light schema**, not heavy code. The full plan lives in [saas-roadmap.md](saas-roadmap.md). Concrete near-term work items:

1. Add `tenant_id` (UUID) to every user-scoped table from now on. Self-host installs always have one default tenant per user; SaaS will use it for true multi-tenancy.
2. Add `tier` enum (`free`, `pro`, `studio`) to `users`. Today everyone is `free`; the column exists so feature gates can read it.
3. Document quota allocations per tier (YouTube units / day, LLM tokens / day, document count cap, output count cap) in [saas-roadmap.md](saas-roadmap.md).
4. Document tenancy-isolation invariants every PR is checked against.

**Schema impact.** `tenant_id` column on `jobs`, `documents` (after L1), `qa_exchanges`, `library_qa_exchanges`, `qa_history_exchanges`, `notes` (after M5), `outputs` (after L2), `channels`. Default value = `users.tenant_id`. No production data migration needed since we have one tenant per user today.

**API impact.** None today. Future: `X-Tenant-ID` header for workspace-aware routes.

**Status.** 🟢 **code-shippable work fully closed 2026-05-05.** Five I-5 epics done end-to-end:
- ✅ **E-5.1** tenancy retrofit fully closed (4-phase rollout + operator runbook).
- ✅ **E-5.2** subscription tier enum + capability table + `require_tier` / `require_feature` dependencies + **runtime quota metering** (consume / enforce / display) shipped.
- ✅ **E-5.4** auth hardening — audit log + lockout + password reset + SMTP + sessions + MFA + OAuth (Google + GitHub PKCE).
- ✅ **E-5.5** rate-limit middleware + per-user quota enforcement at hot endpoints. Remaining tasks (Redis backend / content policy / fraud detection) are 🔴 deferred per [D-039](decisions.md#d-039-in-memory-rate-limit-backend-as-the-default-redis-swap-deferred-to-multi-worker-saas-2026-05-04) and dependency-on-M11 / production-traffic-needed reasoning.
- ✅ **E-5.6** BYOK LLM credentials foundation + LLM resolution-path integration + Chroma tenant filtering on `qa_library_global` + per-tenant Celery routing.

The remaining I-5 epics (**E-5.3 Stripe**, **E-5.7 Data residency**, **E-5.8 Hosting**, **E-5.9 Hosted UX**) are **design-complete and code-deferred to SaaS launch** — none has meaningful code work for a self-host install. Full design lives in [`saas-roadmap.md`](saas-roadmap.md).

---

## Medium-scale features (M1-M12)

Days each. Each one is shippable as a single PR or a small series.

---

### M1 — Shelves (collections / folders) ⚪

Group jobs into named projects. A job can belong to multiple shelves. Tag documents. Filter library views by shelf.

**Schema:** `shelves(id, name, description, color, owner_id, tenant_id, created_at)`, `shelf_jobs(shelf_id, job_id)`, `document_tags(document_id, tag)`.

**API:** `GET/POST/PUT/DELETE /api/v1/shelves/*`, `POST /api/v1/jobs/{id}/shelves`.

**UI:** New left-sidebar section "Shelves". Shelf detail page = filtered library view.

**Status.** ⚪ proposed. Targeted post-rebrand.

---

### M2 — Cmd-K global search ⚪

Command palette → search jobs, documents, channels, Q&As, knowledge artifacts in one. Powered by existing ChromaDB collections.

**Schema:** None.

**API:** `GET /api/v1/search?q=...` returns mixed result types.

**UI:** Cmd-K (Ctrl-K on Windows) opens a modal with fuzzy-search input and grouped results.

**Status.** ⚪ proposed.

---

### M3 — Saved searches & alerts ⚪

Save a Q&A query → re-run on a schedule → notify when new library content materially changes the answer.

**Schema:** `saved_searches(id, owner_id, query, answer_language, schedule_cron, last_run_at, last_answer_hash)`.

**API:** `GET/POST/DELETE /api/v1/saved-searches/*`.

**UI:** "Pin this question" button on Q&A answer cards.

**Status.** ⚪ proposed. Foundation for "research monitoring" / digest features.

---

### M4 — Question suggestions ⚪

Use the `qa_library_global` collection to suggest follow-up questions when the user opens a job, document, or knowledge artifact. Directly answers the user's "learn from past questions" ask.

**Schema:** None (read-only over existing Chroma data).

**API:** `GET /api/v1/suggestions?context=job:<id>` returns 3-5 suggested questions.

**UI:** "You might ask..." card below the Q&A input.

**Status.** ⚪ proposed.

---

### M5 — Notes (user annotations) ⚪

Attach a free-text "your take" / annotation to any document, job, Q&A exchange, channel, or knowledge artifact. Searchable, exportable, treated as citable content (weight 1.5x — see L4).

**Schema:** `notes(id, owner_id, tenant_id, target_type, target_id, body, created_at, updated_at)`.

**API:** `GET/POST/PUT/DELETE /api/v1/notes/*`, `GET /api/v1/notes?target=video:<id>`.

**UI:** "Add a note" button on every entity. Notes render inline below the entity. Aggregate "Your notes" view in the sidebar.

**Status.** ⚪ proposed. Foundational for L3 (voice capture relies on accumulated notes).

---

### M6 — Job templates / playbooks ⚪

Save a job's parameters as a template; one-click instantiate with fresh date ranges or a different topic.

**Schema:** `job_templates(id, owner_id, name, parameters_json, created_at)`.

**API:** `GET/POST/DELETE /api/v1/job-templates/*`.

**UI:** "Save as template" on submit page; "From template" picker.

**Status.** ⚪ proposed. Today's "Duplicate / re-run" already covers most of this; M6 generalizes from "duplicate one job" to "named reusable template".

---

### M7 — Channel intelligence dashboard ⚪

Per-channel analytics: word-cloud, recurring topics, evolving stance over time, knowledge-graph of frequent concepts.

**Schema:** None new (computed from existing knowledge artifacts).

**API:** `GET /api/v1/channels/{id}/intelligence` returns aggregated stats.

**UI:** New tab on the channel detail page.

**Status.** ⚪ proposed.

---

### M8 — Reading-room reader for reports ⚪

Replace iframe-modal HTML report with a native MDX-rendered reading view: typography, drop caps, inline references on hover, sticky outline, reading-progress, print-friendly.

**Schema:** None.

**API:** Reports already serve HTML; this is purely a frontend change. Optionally add `GET /api/v1/jobs/{id}/report.md` for the source Markdown.

**UI:** New `/reports/:id` route with full-page reading view; modal becomes a quick-peek alternative.

**Status.** ⚪ proposed.

---

### M9 — Citation graph / knowledge map ⚪

Visualize how Q&As cite documents, how documents relate to topics, how topics cluster. New library-overview page.

**Schema:** None new (computed from existing references / knowledge artifacts).

**API:** `GET /api/v1/library/graph` returns nodes + edges JSON.

**UI:** Force-directed graph (d3 / cytoscape); zoom, pan, click-to-detail.

**Status.** ⚪ proposed.

---

### M10 — Onboarding wizard + empty-state polish ⚪

First-run flow: pick 3-5 channels, run a first job, see the result. Today there's no onboarding.

**Schema:** None (or `users.onboarded_at`).

**API:** None.

**UI:** Multi-step wizard surfaced on first login; dismissible afterwards.

**Status.** ⚪ proposed. High-leverage for SaaS conversion later.

---

### M11 — Public report sharing ⚪

Signed URL for a single report → share with friends. Paves the way for SaaS sharing later.

**Schema:** `report_shares(id, report_id, signed_token, expires_at, created_at)`.

**API:** `POST /api/v1/jobs/{id}/share` returns signed URL; `GET /shared/reports/{token}` (no auth) renders read-only.

**UI:** "Share" button on report viewer.

**Status.** ⚪ proposed.

---

### M12 — Mobile reading mode ⚪

Today the layout collapses to stacked column at 640px. Improve specifically the *reading* experience (reports, Q&A answers, knowledge artifacts) for mobile — appropriate type sizes, tap targets, sticky controls.

**Schema:** None.

**API:** None.

**UI:** Responsive refinements across reading-heavy pages.

**Status.** ⚪ proposed.

---

## Rebrand asset rollout (parallel track) 🟡

Tracked separately because it's identity-system work, not a feature.

| Item | Status |
|------|--------|
| `docs/branding.md` | 🟢 shipped |
| `docs/vision.md` | 🟢 shipped |
| `docs/feature-roadmap.md` (this file) | 🟢 shipped |
| Documentation refresh (architecture, ui-design, requirements, etc.) | 🟡 in-progress |
| Frontend design tokens (`frontend/src/theme.ts`) | 🔵 accepted |
| Primitives library (`frontend/src/components/primitives/*`) | 🔵 accepted |
| Sidebar layout migration (top-tabs → sidebar) | 🔵 accepted |
| Per-page warm-editorial restyle | 🔵 accepted |
| Logo SVG + favicon | 🔵 accepted |
| Landing page (`marketing/`) | ⚪ proposed |
| Brand-name swap across all user-facing copy | 🔵 accepted (post-tokens) |

---

## Dropped / deferred ideas

For traceability — things considered and explicitly not pursued.

- **Generic "AI assistant" chat (no source grounding).** Rejected: violates the "every answer cites a voice" principle.
- **Auto-ingest the user's whole YouTube subscription list.** Rejected: violates the "user explicitly approves what enters the library" principle. Channel subscriptions are explicit per-channel.
- **Cross-user library sharing.** Deferred to SaaS phase; explicit signed-URL sharing only (M11).
- **Real-time collaborative research.** Deferred indefinitely; out of scope for personal-brain framing.
