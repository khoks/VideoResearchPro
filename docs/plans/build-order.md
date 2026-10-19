# Build order — recommended sequence across I-3, I-6 and I-8

**Status:** recommendation (2026-10-19). Covers every epic planned under [`docs/plans/`](README.md). The board ([`initiatives.md`](../initiatives.md)) carries status; this file carries the *order and why*. Re-sequence here when reality intervenes; never renumber IDs.

## The rules the order follows

1. **Existing commitments first, regardless.** They are in flight in other sessions and several later items depend on them.
2. **Enablers before the things they enable**, measured by what each item unlocks (the reader unlocks sharing, mobile and the book viewer; the scheduler unlocks saved searches, the newsletter and Echo syncs; shelves unlock the site picker and graph filters; templates unlock onboarding; notes unlock Echo's voice).
3. **Retrieval-touching work waits for `qa_agent.py` to settle.** The R3/R4 batch is rewriting it and E-7.1 lands the `distance / weight` re-rank that notes and shelf scopes reuse ([D-068](../decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18)).
4. **Cheap, high-value, low-risk before expensive or decision-gated.** Public sharing and reels wait on the user's answers; Echo's heavier connectors wait on verification and revenue.
5. **Parallel lanes only where files are disjoint.** The shared hot spots are listed at the end.

## Phase 0 — commitments already made (in other sessions)

| Item | Why first |
|---|---|
| R3 / R4 / R5 batch: [S-1.15.2](../initiatives.md#e-115--output-length-policy-r4), [S-1.16.1 remainder](../initiatives.md#e-116--linguistic-agnosticism-with-english-output-r5), [S-1.17.2](../initiatives.md#e-117--temporal--era-awareness-r3) | Rewrites the Q&A and report prompts; everything that touches `qa_agent.py` queues behind it. |
| R1 measurement: [S-1.18.3](../initiatives.md#s-1183--measure-whether-visual-annotations-improve-output) | Decides whether S-1.18.2 (frames in the UI) is worth doing; the reader's citation cards have a hook for it either way. |
| [E-7.1](../initiatives.md#e-71--trust-weighted-retrieval-v1) trust-weighted retrieval | Lands the re-rank that M5 notes and M1 shelf scopes reuse; its weight control needs the channel page M7 creates (see Phase 1). |
| Report quality: [S-1.14.6](../initiatives.md#e-114--model-tier-quality-evaluation-harness) intermediates, S-1.14.7 registry guidance, S-1.14.15 summary defects | Quality of the thing every output kind is built from. |
| [T-5.4.9](../initiatives.md#e-54--auth-hardening) replace `python-jose` | Small, security; found by this research (unfixed critical CVE, mitigated today by pinned algorithms). One PR. |

## Phase 1 — workbench foundations (four parallel lanes)

Everything here is schema plus UI with no retrieval changes. Each lane is one reviewer-sized PR at a time.

| Lane | Order | Unlocks | Size |
|---|---|---|---|
| **A · Reading** | [S-8.8.1](../initiatives.md#s-881--report-content-endpoint-and-sanitised-renderer) reader → [S-8.8.2](../initiatives.md#s-882--citation-hover-cards-and-footnotes) citation cards + print → [S-8.8.3](../initiatives.md#s-883--knowledge-artifacts-and-books-in-the-same-shell) shared shell → [S-8.12.1](../initiatives.md#s-8121--reading-pages-responsive-pass) mobile pass → [S-8.12.2](../initiatives.md#s-8122--web-app-manifest) manifest | M11 public page, M12, the Author output viewer, retiring the `?token=` route | 4–5 PRs, frontend-heavy, no LLM cost |
| **B · Organisation** | [S-8.7.1](../initiatives.md#s-871--channel-detail-page) channel page (E-7.1's weight control needs it) → [S-8.1.1](../initiatives.md#s-811--shelves-schema-service-and-rest) shelves schema → [S-8.1.2](../initiatives.md#s-812--shelves-ui) shelves UI → [S-8.1.3](../initiatives.md#s-813--document-tags-per-tenant) tags → [S-8.6.1](../initiatives.md#s-861--templates-schema-rest-and-submit-page-integration) templates (with the Duplicate fix) → [S-8.6.2](../initiatives.md#s-862--starter-templates) starters | Site picker (E-6.2), graph filters (M9), onboarding (M10) | 6 PRs, no LLM cost |
| **C · Infrastructure** | [S-8.3.1](../initiatives.md#s-831--scheduler-tick-shared-infrastructure) scheduler tick → [S-8.2.1](../initiatives.md#s-821--search-endpoint) search endpoint (FTS5 + fallback) → [S-6.1.1](../initiatives.md#s-611--source-picker-and-a-working-author-page) make the Author page work → [S-6.1.2](../initiatives.md#s-612--markdown-source-for-reports) Markdown source | Saved searches, newsletter, Echo syncs; the palette; every Author kind | 4 PRs; the scheduler adds one process to `start.ps1` |
| **D · Notes** | [S-8.5.1](../initiatives.md#s-851--notes-schema-rest-and-inline-ui) notes CRUD + inline UI → [S-8.5.3](../initiatives.md#s-853--your-notes-view-search-and-export) notes page + export | Echo voice capture (E-3.3); the retrieval story waits for Phase 2 | 2 PRs |

**After the lanes converge** (they touch `AppLayout.tsx` and `routes/index.tsx`, so these go one at a time): [S-8.2.2](../initiatives.md#s-822--palette-ui-and-shortcuts) palette + `useShortcuts` → [S-8.10.1](../initiatives.md#s-8101--wizard) onboarding wizard (needs templates and the reader) → [S-8.10.2](../initiatives.md#s-8102--empty-state-audit) empty states → [S-8.4.1](../initiatives.md#s-841--suggestion-endpoint) / [S-8.4.2](../initiatives.md#s-842--suggestion-cards) suggestions (first LLM-spend feature in I-8; about $0.0002 per batch on a nano model, cached).

## Phase 2 — retrieval-touching (after Phase 0's Q&A rewrite and E-7.1)

Sequential, because all of it edits `qa_agent.py` or its retrieval helpers:

1. [S-8.5.2](../initiatives.md#s-852--notes-in-retrieval-and-citations) notes in retrieval and citations (the D-068 re-rank at weight 1.5; measured before tuning).
2. [S-8.1.4](../initiatives.md#s-814--shelf-scoped-qa) shelf-scoped Q&A (only the `video_ids` set changes).
3. [S-8.3.2](../initiatives.md#s-832--saved-searches-schema-rest-and-pin-ui) saved searches → [S-8.3.3](../initiatives.md#s-833--re-run-change-detection-and-notification) re-run, change detection, notifications (introduces the `notifications` table and bell; LLM spend bounded by the "new documents since last run" gate and the tier cap).

## Phase 3 — Author Studio, books first

| Order | Item | Depends on | Cost notes |
|---|---|---|---|
| 1 | [S-6.7.1](../initiatives.md#s-671--celery-backed-generation-with-progress) async generation + progress | Phase 1 C | Reuses the job progress channel |
| 2 | [S-6.7.2](../initiatives.md#s-672--binary-artifacts-and-downloads) downloads, [S-6.7.3](../initiatives.md#s-673--output_citations) citations table | — | — |
| 3 | [S-6.1.4](../initiatives.md#s-614--endnote-citations) endnotes → [S-6.1.5](../initiatives.md#s-615--pdf-and-epub-downloads) PDF + EPUB | S-6.1.2, S-6.7.3 | WeasyPrint needs Pango on Windows dev machines; no LLM |
| 4 | [S-6.1.3](../initiatives.md#s-613--llm-cohesion-pass) LLM cohesion | S-6.7.1 | About $1–4 per ten-report book at list prices; judged blind against `none` before it becomes default |
| 5 | [S-6.3.1](../initiatives.md#s-631--deckoutputter) deck | S-6.7.x | A few cents per deck |
| 6 | [S-6.2.1](../initiatives.md#s-621--siteoutputter-zip-of-static-html) site | S-8.1.1 (shelf picker), S-6.1.2 | No LLM |
| 7 | [S-6.4.1](../initiatives.md#s-641--newsletteroutputter) → [S-6.4.2](../initiatives.md#s-642--subscription-and-delivery) newsletter | S-8.3.1 scheduler, S-8.3.3's notifications | A few cents per issue plus email |

## Phase 4 — insight

1. [S-8.7.2](../initiatives.md#s-872--intelligence-aggregate-endpoint) channel aggregates → [S-8.7.3](../initiatives.md#s-873--intelligence-tab-ui) tab (no new dependencies; value scales with knowledge-extraction coverage).
2. [S-8.9.1](../initiatives.md#s-891--graph-endpoint) graph endpoint → [S-8.9.2](../initiatives.md#s-892--graph-ui) graph UI (lazy route; accessibility table and keyboard model are part of the story, not after it). M7's concept panel reuses it.

## Phase 5 — Echo, in the roadmap's own order

| Order | Item | Depends on |
|---|---|---|
| 1 | [S-3.7.1](../initiatives.md#s-371--shares_inbox-quick-share-and-the-inbox-page) shares inbox + [S-3.10.1](../initiatives.md#s-3101--full-export) export + [S-3.10.2](../initiatives.md#s-3102--full-delete) delete (ship together: the first new Echo table arrives with its export and erasure) | — |
| 2 | [S-3.7.2](../initiatives.md#s-372--processing-pipeline) processing (OCR, Whisper, embedding) → [S-3.7.5](../initiatives.md#s-375--export-file-importers) importers (this is where most of the roadmap's connector list actually lives) → [S-3.7.3](../initiatives.md#s-373--drag-drop-and-browser-extension) drop zone + extension | 1 |
| 3 | [S-3.3.1](../initiatives.md#s-331--voice_signals-schema-crud-and-the-signals-panel) signals → [S-3.3.2](../initiatives.md#s-332--signal-extraction) extraction → [S-3.3.3](../initiatives.md#s-333--personal-retrieval-collection) collection → [S-3.3.4](../initiatives.md#s-334--voice-match-evaluation-harness) evaluation harness | Notes (Phase 1 D) for its richest input |
| 4 | [S-3.2.1](../initiatives.md#s-321--connector-runtime-and-activity_events) connector runtime → [S-3.2.4](../initiatives.md#s-324--github-connector) GitHub → [S-3.2.2](../initiatives.md#s-322--youtube-likes-and-subscriptions-connector) YouTube likes + [S-3.2.5](../initiatives.md#s-325--calendar-connector) Calendar (one Google review, separate OAuth client, after verification) | Scheduler (Phase 1 C) |
| 5 | [S-3.5.1](../initiatives.md#s-351--five-domain-readiness) five-domain readiness | 1–4 |
| 6 | [S-3.4.1](../initiatives.md#s-341--agent-and-endpoint) speak-as-me → [S-3.4.2](../initiatives.md#s-342--feedback-loop-and-limits) feedback + limits → [S-3.8.1](../initiatives.md#s-381--bubble-panel-and-shortcut) bubble → [S-3.8.2](../initiatives.md#s-382--anticipation-cards) cards | S-3.3.4 passed; the palette hook (S-8.2.2) |
| later | [S-3.2.3](../initiatives.md#s-323--spotify-live-tail-self-host-only) Spotify tail, [S-3.7.4](../initiatives.md#s-374--email-in-inbox) email-in, [S-3.7.6](../initiatives.md#s-376--os-share-target) share target, [E-3.9](../initiatives.md#e-39--mode-b-opt-in-per-user-fine-tuning) Mode B, [S-3.10.3](../initiatives.md#s-3103--zero-knowledge-mode-saas) zero-knowledge | User decisions and revenue (see plan) |

## Decision-gated and last

- [E-8.11](../initiatives.md#e-811--public-report-sharing-m11) public sharing: design complete; **the user decides** whether it launches before billing and takedown tooling. If yes, it slots after Phase 1 lane A (it reuses the reader) and costs 2 PRs.
- [E-6.5](../initiatives.md#e-65--video--reel-tts-narration--stills) reel: last of the Author kinds; needs the TTS provider decision and a Hindi listening test; no third-party footage by default.
- [S-8.9.3](../initiatives.md#s-893--topic-clusters) topic clusters, [S-8.2.3](../initiatives.md#s-823--semantic-group) semantic search group: only if the simpler versions prove insufficient.

## What can run in parallel (disjoint files)

| Runs together | Why safe |
|---|---|
| Lane A (reader) ∥ Lane B (shelves, templates) ∥ Lane C (scheduler, search, Author page) ∥ Lane D (notes) | Different models, routers, services and pages; only `routes/index.tsx` and `package.json` overlap, and those merge trivially. |
| S-6.1.5 PDF/EPUB ∥ S-6.3.1 deck ∥ S-6.2.1 site | Separate outputter modules once E-6.7 is in. |
| S-8.7.2 channel aggregates ∥ S-8.9.1 graph endpoint | Separate services; the graph UI then serves both. |
| S-3.7.5 importers ∥ S-3.3.1 signals | Separate packages. |

## Shared hot spots (serialise anything that touches these)

| File | Touched by |
|---|---|
| `backend/app/agents/qa_agent.py` and retrieval helpers | R3/R4 batch, E-7.1, S-8.5.2, S-8.1.4, S-8.3.3 (caller only), E-3.4 (reads, does not edit) |
| `frontend/src/layouts/AppLayout.tsx` | S-8.1.2 (shelves group), S-8.2.2 (palette mount), S-8.3.3 (bell), S-8.10.1 (reopen link), S-3.7.1 (quick-share), S-3.8.1 (bubble) |
| `backend/app/tasks/celery_app.py` | S-8.3.1 (beat schedule), S-6.7.1 and S-3.7.2 (autodiscover list) |
| `backend/app/services/llm_routing.py` registry | S-8.4.1, S-8.3.3, S-6.1.3, S-6.3.1, S-6.4.1, S-6.5.1, S-3.3.2, S-3.4.1 — additive entries, low conflict, but one at a time |
| `frontend/src/pages/JobDetailPage.tsx` | S-8.1.2, S-8.5.1, S-8.6.1, S-8.8.1, S-8.12.1, S-6.1.1, S-8.11.2 |
| `scripts/start.ps1` | S-8.3.1 (beat), S-6.1.5 (WeasyPrint check, optional) |

## Rough totals

| Group | PRs | LLM spend introduced |
|---|---|---|
| Phase 1 (lanes + convergence) | about 24 | Suggestions only (cached, nano tier) |
| Phase 2 | 4 | Saved-search re-runs, gated and capped |
| Phase 3 | 8–9 | Book cohesion ($1–4 per ten-report book), deck, newsletter featured section |
| Phase 4 | 4 | None (aggregates); knowledge extraction already metered |
| Phase 5 (through the bubble) | about 16 | Signal extraction (batched, economy tier), drafts (capped per day), OCR fallback (cents) |

The counts are PR-sized stories from the board, not estimates of days; the board is the source of truth and this file only orders it.
