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

### L1 — Multi-source ingest 🔵

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

**Status.** 🔵 accepted. Detailed design in [source-types.md](source-types.md). Targeted Phase 2 (2026 Q3).

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

### L3 — Personal Brain ⚪

**Motivation.** The widest ring of the vision (see [vision.md](vision.md) Ring 3). Pratidhvani learns enough about the user — through opt-in life connectors — that it can suggest questions before they ask, anticipate their needs, capture their voice, and eventually speak on their behalf.

**Sketch.** Three components:

1. **Personal context store** — separate schema (`user_context_*` tables) holding what the user has *told* or *connected* about themselves: location history, interests, hobbies, work, talents, skills, personality dimensions, life events, opinions, daily routine.
2. **Activity ingestion connectors** — pluggable, opt-in, scoped, revocable. Each connector lands as its own PR. See [personal-brain.md](personal-brain.md) for the connector contract.
3. **Voice & "speak as me" agent** — captures the user's writing samples, Q&A patterns, recurring framings; drafts responses to incoming messages in the user's voice using their accumulated knowledge.

**Schema impact.** Substantial new schema, isolated from the source library. See [personal-brain.md](personal-brain.md).

**API impact.** New top-level `/api/v1/me/*` endpoints for connectors, context store, and voice agent.

**Open questions.** Many — see [personal-brain.md](personal-brain.md). Privacy model is the largest open design space.

**Status.** ⚪ proposed. Targeted Phase 6 (2027 Q3+). Connectors land one at a time, easiest first (YouTube watch history → Spotify → email → calendar).

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

### L5 — SaaS-readiness layer 🔵

**Motivation.** Open-source self-host is the launch posture; public SaaS is the endgame. Today's PRs must not bake in assumptions that block the migration — single-tenant queries, hard-coded quotas, lack of tenancy columns, etc.

**Sketch.** This L5 is mostly **doc + light schema**, not heavy code. The full plan lives in [saas-roadmap.md](saas-roadmap.md). Concrete near-term work items:

1. Add `tenant_id` (UUID) to every user-scoped table from now on. Self-host installs always have one default tenant per user; SaaS will use it for true multi-tenancy.
2. Add `tier` enum (`free`, `pro`, `studio`) to `users`. Today everyone is `free`; the column exists so feature gates can read it.
3. Document quota allocations per tier (YouTube units / day, LLM tokens / day, document count cap, output count cap) in [saas-roadmap.md](saas-roadmap.md).
4. Document tenancy-isolation invariants every PR is checked against.

**Schema impact.** `tenant_id` column on `jobs`, `documents` (after L1), `qa_exchanges`, `library_qa_exchanges`, `qa_history_exchanges`, `notes` (after M5), `outputs` (after L2), `channels`. Default value = `users.tenant_id`. No production data migration needed since we have one tenant per user today.

**API impact.** None today. Future: `X-Tenant-ID` header for workspace-aware routes.

**Status.** 🔵 accepted. Land the schema columns alongside the doc refresh phase. Detailed in [saas-roadmap.md](saas-roadmap.md).

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
