# Plans — researched, buildable designs for the larger roadmap items

**Status:** living index (created 2026-10-18). Each plan here backs an epic in [`initiatives.md`](../initiatives.md) and a section of [`feature-roadmap.md`](../feature-roadmap.md). The board tracks *status*; the roadmap holds the *why*; a plan holds the *how*: what exists in the code today (verified by reading it, not the docs), the chosen approach with the alternatives rejected, schema and API deltas, the modules touched, risks, a test strategy, the definition of the first PR, and the questions that are the user's call.

**Sequence across everything:** [`build-order.md`](build-order.md).

## Conventions

- A plan never claims something is shipped unless the file and line it lives in is named. Roadmap sketches were wrong often enough this week (`source_weight` "re-ranks retrieval" and was read by nothing; the Author page "exercises the shipped Book v1 outputter" and cannot produce a successful book) that every "already exists" below was checked with `grep`.
- Library choices name the SPDX licence. Copyleft dependencies (AGPL, GPL, LGPL) are rejected for anything imported into the server; separate optional binaries are acceptable only when auto-detected, never required. `pymupdf` (AGPL-3.0) is a pre-existing exception recorded in `requirements.txt`.
- Prices and limits carry the date they were fetched. They move; re-check before committing a registry entry.
- Open questions are the user's to answer. A plan recommends and says why, but does not decide on the user's behalf where the readings differ materially (public sharing before billing, zero-knowledge mode, TTS provider for self-host).
- When an approach in a plan is adopted, it becomes a `D-NNN` entry in [`decisions.md`](../decisions.md); the plan then links to it. Until then the plan's "Chosen approach" is a recommendation.
- Anchors are written by hand in GitHub's form (lowercase, punctuation dropped, every space a hyphen). `backend/scripts/fix_anchor_links.py` collapses the `--` that GitHub keeps and must not be run on these files (T-4.8.5).

## Index

| Plan | Roadmap | Board | One line |
|---|---|---|---|
| [l2-author-studio.md](l2-author-studio.md) | [L2](../feature-roadmap.md#l2--author-studio-output-generation-) | [I-6](../initiatives.md#i-6--author-studio-output-generation-l2) | Books (PDF/EPUB), static site, deck, newsletter, reel on the shipped Outputter registry; WeasyPrint, hand-rolled EPUB, Jinja2 site, python-pptx, beat tick, TTS abstraction |
| [l3-echo-personal-brain.md](l3-echo-personal-brain.md) | [L3](../feature-roadmap.md#l3--echo-the-personal-brain-) | [I-3](../initiatives.md#i-3--echo-personal-brain-l3) | Shares inbox first, then signals, connectors (several are export-file importers), speak-as-me with retrieval plus critique, readiness, privacy; fine-tuning deferred and provider-agnostic |
| [m1-shelves.md](m1-shelves.md) | [M1](../feature-roadmap.md#m1--shelves-collections--folders-) | [E-8.1](../initiatives.md#e-81--shelves--collections-tags-and-shelf-scoped-views-m1) | Many-to-many shelves, per-tenant tag rows, shelf-scoped Q&A on the existing `video_id` filter |
| [m2-command-palette.md](m2-command-palette.md) | [M2](../feature-roadmap.md#m2--cmd-k-global-search-) | [E-8.2](../initiatives.md#e-82--command-palette-and-global-search-m2) | `cmdk` palette over a tenant-scoped FTS5 search endpoint with a `LIKE` fallback; semantic group merged by rank fusion |
| [m3-saved-searches-alerts.md](m3-saved-searches-alerts.md) | [M3](../feature-roadmap.md#m3--saved-searches--alerts-) | [E-8.3](../initiatives.md#e-83--saved-searches-and-alerts-m3) | The project's first scheduler (one beat tick), human cadences, a "new documents since last run" gate, cited-set and embedding change detection, email plus in-app inbox |
| [m4-question-suggestions.md](m4-question-suggestions.md) | [M4](../feature-roadmap.md#m4--question-suggestions-) | [E-8.4](../initiatives.md#e-84--question-suggestions-m4) | Past questions from `qa_library_global` plus a cheap generation call, diversified and cached |
| [m5-notes.md](m5-notes.md) | [M5](../feature-roadmap.md#m5--notes-user-annotations-) | [E-8.5](../initiatives.md#e-85--notes--the-users-own-voice-in-the-library-m5) | W3C-shaped notes, a private `notes_global` collection merged into retrieval at weight 1.5 through the D-068 re-rank, cited as "you wrote this" |
| [m6-job-templates.md](m6-job-templates.md) | [M6](../feature-roadmap.md#m6--job-templates--playbooks-) | [E-8.6](../initiatives.md#e-86--job-templates-m6) | Server-side, versioned snapshots of the Duplicate flow's parameter set; starter templates for onboarding |
| [m7-channel-intelligence.md](m7-channel-intelligence.md) | [M7](../feature-roadmap.md#m7--channel-intelligence-dashboard-) | [E-8.7](../initiatives.md#e-87--channel-intelligence-m7) | A channel page that does not exist yet, plus cached aggregates over knowledge artifacts and transcripts with no new dependencies |
| [m8-reading-room.md](m8-reading-room.md) | [M8](../feature-roadmap.md#m8--reading-room-reader-for-reports-) | [E-8.8](../initiatives.md#e-88--reading-room--the-report-as-a-native-reading-view-m8) | Sanitised HTML rendered in React (no iframe, no token in the URL), outline, progress, citation cards, print |
| [m9-citation-graph.md](m9-citation-graph.md) | [M9](../feature-roadmap.md#m9--citation-graph--knowledge-map-) | [E-8.9](../initiatives.md#e-89--citation-graph-and-knowledge-map-m9) | Tenant-scoped graph endpoint, local-graph-first UI on sigma or react-force-graph, table view for accessibility |
| [m10-onboarding.md](m10-onboarding.md) | [M10](../feature-roadmap.md#m10--onboarding-wizard--empty-state-polish-) | [E-8.10](../initiatives.md#e-810--onboarding-wizard-and-empty-states-m10) | A task-flow wizard page (no tour library), server-side state, a deliberately tiny first job, empty-state audit |
| [m11-public-report-sharing.md](m11-public-report-sharing.md) | [M11](../feature-roadmap.md#m11--public-report-sharing-) | [E-8.11](../initiatives.md#e-811--public-report-sharing-m11) | Opaque hashed tokens, expiry and revocation, `noindex`, sandboxing CSP; the launch-before-billing question is the user's |
| [m12-mobile-reading.md](m12-mobile-reading.md) | [M12](../feature-roadmap.md#m12--mobile-reading-mode-) | [E-8.12](../initiatives.md#e-812--mobile-reading-mode-m12) | CSS-first reading pass, viewport-pinned composer, manifest, device-emulated screenshot tests |

**Raw research notes** with every URL and a per-claim verification tag (primary, secondary, unverified) are under [`research/`](research/): [`l2-author-studio.md`](research/l2-author-studio.md), [`l3-echo-connectors.md`](research/l3-echo-connectors.md), [`l3-echo-personality.md`](research/l3-echo-personality.md), [`m1-m6.md`](research/m1-m6.md), [`m7-m12.md`](research/m7-m12.md). They were produced on 2026-10-19 by five parallel research passes; prices, limits and licences are as of that date.

## Cross-cutting findings surfaced by the research

These came up while researching the items above and affect more than one plan. They are recorded here so they are not lost in a single plan.

- **`python-jose` has an unfixed critical vulnerability.** Version 3.5.0 (latest, 2025-05-28) carries CVE-2026-85394 (CVSS 9.3, published 2026-09-03, no fixed release): an algorithm-confusion flaw where a DER public key is accepted as an HMAC secret. The app's auth, MFA and rate-limit middleware all decode with it. Tracked as [T-5.4.9](../initiatives.md#e-54--auth-hardening). Public share tokens (M11) must never be JWTs.
- **Two harness skills named in the roadmap are not server libraries.** `anthropic-skills:docx` and `anthropic-skills:pptx` are Claude Code skills; the worker cannot call them. Book conversion uses WeasyPrint; decks use `python-pptx`.
- **Copyleft traps found and rejected:** `ebooklib` (AGPL-3.0-or-later), `html2text` (GPL-3.0-or-later), Pelican (AGPL-3.0-or-later), YAKE (AGPL-3.0-or-later), Shepherd.js ≥ 14 and Intro.js (AGPL-3.0), `python-crontab` (LGPL-3.0), Piper's successor and `espeak-ng` (GPL-3.0). `pandoc` (GPL-2.0-or-later) is acceptable only as an auto-detected optional binary, never bundled or required.
- **Several roadmap connectors have no permitted API.** YouTube watch history (Data API removed it in 2016; the Data Portability scope is restricted), Strava (API policy from 2026-06-01 forbids AI use), Goodreads (API closed 2020), Letterboxd (refuses LLM and personal projects), Apple Health (no web API), Spotify beyond a self-host single user (2026 developer-mode rules). They become export-file importers.
- **OpenAI's self-serve fine-tuning is winding down** (no new jobs after 2027-01-06; fine-tunable models retire 2027-01-14). Echo Mode B must be provider-agnostic; local LoRA on open weights is the only durable path and is documented to trade quality for style unless guarded.
- **The scheduler is shared.** M3 builds one Celery beat tick; the newsletter (E-6.4) and Echo connector syncs (S-3.2.1) run on it. Exactly one beat process; add it to `scripts/start.ps1`.
- **Reading view is shared.** M8's reader shell renders reports, knowledge artifacts, public shares (M11) and Author outputs (E-6.1). M12 refines it for phones.
- **Tenant rule for every new table:** per-user attributes of shared records live in per-tenant side tables (tags, notes, shares), and every new read of `documents` goes through `visibility_service.visible_video_ids` ([D-063](../decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)).
