# L3 — Echo, the personal brain: plan

**Board:** [I-3](../initiatives.md#i-3--echo-personal-brain-l3) · **Roadmap:** [L3](../feature-roadmap.md#l3--echo-the-personal-brain-) · **Design doc:** [personal-brain.md](../personal-brain.md) · **Research date:** 2026-10-19 · **Status:** recommendation; adopt by filing decisions per epic.

## Problem

Echo is the Ring 3 north star: an app that learns the user's facts, consumption, voice and opinions and can speak as them, never unilaterally. The foundation shipped on 2026-05-05 (PR #172): a `personal_context` facts table, an empty connector registry, a readiness gate on three counters, and a Studio-tier gate. The roadmap lists five components; none beyond the facts store exists. This plan turns the sketch into six epics in the roadmap's own order and corrects the sketch where the research found it wrong.

## Verified current state (2026-10-18)

| Claim | Where | Finding |
|---|---|---|
| Personal context store | `backend/app/models/personal_context.py`, revision `a4b5c6d7e8f9` | `(user_id, kind, key)` unique; `value`, `source`, `confidence`, `captured_at`, `expires_at`. **Facts only**: one row per key, so events and shares cannot live here. No `tenant_id` column (`personal-brain.md` asks for both; today `tenant_id == user.id`). |
| Service | `backend/app/services/echo_service.py` | CRUD, `revoke_source`, `EchoConnector` Protocol (`authorize_url / revoke / sync / supported_kinds`), registry (empty), `is_ready` (100 rows, 3 sources, one `personality_trait`). |
| REST | `backend/app/routers/echo.py` | `/echo/status`, `/echo/context` CRUD, `/echo/sources/{source}` revoke, `/echo/connectors`. Gated on `echo_personal_brain`. |
| Page | `frontend/src/pages/EchoPage.tsx` | Manual facts form and the readiness meter. No bubble, no chat, no shortcut. |
| Tables from the design doc (`activity_events`, `voice_signals`, `shares_inbox`) | — | None exist; no Alembic revision references them. |
| Chroma collections for personal data | — | None. |
| `backend/app/connectors/` | — | Does not exist. |
| Reusable pieces | `services/byok_service.py` (Fernet credential store, [D-043](../decisions.md#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05)), `routers/oauth.py` (Google and GitHub PKCE login), `services/paste_url_resolver.py` and `article_extraction/`, Whisper path in `youtube_service.py`, `dataset_service.py` (OpenAI chat JSONL), `language_service.py` (script-based, blind to romanised Hindi) | All present and reusable. |

## Chosen approach

### Order

1. **E-3.7 Constant-stream intake (Domain 5)** — manual quick-share, drag-drop, export-file importers, then extension, email-in, share target.
2. **E-3.3 Voice and personality capture (Domain 3)** — signals as rows, cheap stylometry, batched LLM traits, a personal retrieval collection, an evaluation harness.
3. **E-3.2 Activity connectors (Domain 2)** — the connector runtime, then GitHub, YouTube likes plus Calendar, Spotify live tail for self-host.
4. **E-3.4 Speak-as-me + E-3.8 the bubble (Domain 4)** — retrieval plus critique, gated by five-domain readiness (S-3.5.1).
5. **E-3.9 Mode B fine-tuning** — deferred, provider-agnostic.
6. **E-3.10 Privacy** — export and delete ship alongside the first new table; zero-knowledge stays a design.

### Domain 5 — shares inbox (E-3.7)

One `shares_inbox` table (schema in `personal-brain.md`, plus `author_is_tenant` on every imported message) fed by every surface, processed by a Celery task per share: URLs through `paste_url_resolver` and article extraction; YouTube links through metadata lookup and an *offer* to ingest (never automatic: the vision's approval principle holds even here); images through **local OCR first** (RapidOCR, Tesseract, EasyOCR and PaddleOCR are all Apache-2.0 and all have Devanagari models; RapidOCR is the lightest, ONNX-only) with a vision-LLM fallback for stylised text ($0.0001–0.005 per megapixel image at current prices) that is **off when the tenant's LLM is local-only**; audio through the existing Whisper path. Text is embedded into a `shares_global` Chroma collection with `tenant_id` metadata (the `qa_library_global` pattern). Each share also writes an `activity_events` row (`connector=internal`) and queues signal extraction.

**Export-file importers carry most of the roadmap's connector list**, because the APIs are gone or forbidden (next section): WhatsApp `.txt`/`.zip` (iOS `[dd.mm.yy, hh:mm:ss] Name:` and Android `dd.mm.yy, hh:mm - Name:` patterns, media placeholders, continuation lines, Unicode normalisation), Google Takeout (YouTube `history/watch-history.json` with `title`, `titleUrl`, `subtitles[]`, `time`; `subscriptions.csv`; Keep notes JSON with `textContent`, `listContent[]`, `labels[]`), Spotify "Extended streaming history" JSON (`ts`, `ms_played`, track and episode URIs), Goodreads and Letterboxd CSV, Strava bulk export, Apple Health `export.xml` (1–2 GB for multi-year users; `iterparse`, chunked upload). Importers are a second registry kind (`accepts(filename) / parse(stream)`), never a fake `authorize_url`. Third-party text in a WhatsApp export is stored as context, never quoted verbatim in outputs and excluded from dataset exports, with a "redact the other party" option before storage; no comparable product (Limitless, Mem, Reflect, Obsidian) does better than pushing that burden onto the user through terms of service.

Surfaces: a sidebar quick-share and drop zone on every page; a Manifest V3 extension using `contextMenus` plus `activeTab` (no `history` permission, so no install warning and a lighter store review; Chrome Web Store's tightened Limited Use rule is enforced from 2026-08-01); a Web Share Target in the manifest for Android (installed PWA; iOS Safari still cannot be a share target, so ship an iOS Shortcut that POSTs to the intake endpoint); email-in as IMAP polling for self-host (IMAPClient, BSD-3-Clause) and an inbound-webhook provider for SaaS (Mailgun's free route or Cloudflare Email Routing plus a Worker are $0 entry points; Postmark needs Pro).

### Domain 2 — connectors (E-3.2)

What the research found changes the roadmap's list:

| Connector | Reality (sources in research notes) | Plan |
|---|---|---|
| YouTube watch history | **Not in the Data API** since 2016 (placeholder playlists, error "cannot be retrieved using the API"); the only programmatic path is the Data Portability API's `dataportability.myactivity.youtube`, a *restricted* scope with annual CASA assessment. | Takeout importer. Live connector covers liked videos (`videos.list?myRating=like`, capped at 1,000), subscriptions and playlists under `youtube.readonly` (*sensitive*: days of review, no assessment). |
| Spotify | Since 2026-02-11 a development-mode app needs a Premium-subscribed owner and allows five users; extended quota needs a registered business with 250k monthly users; recently-played is a ~50-item window. | Export importer is the source; live tail is self-host only. |
| Gmail | `gmail.readonly` is *restricted* → CASA Tier 2 every twelve months ($540–1,800 at the Google-negotiated lab, up to $40k elsewhere); OAuth IMAP is equally restricted; basic-auth IMAP died 2025-03-14 except app passwords. | Deferred. Self-host path: app password plus IMAP, or a BYO Google Cloud project in testing mode. |
| Calendar | `calendar.readonly` is *sensitive*, not restricted. | Ship with YouTube likes under one Google review, on a **separate OAuth client** so a rejection never breaks sign-in; unverified sensitive-scope apps carry an irreversible 100-user lifetime cap, so never expose to beta users before verification. |
| GitHub | `GET /users/{username}/events` with fine-grained events read; 5,000 requests per hour; **only 300 events / 30 days**; 30 s–6 h latency. | Cheapest pull connector; nightly scheduled sync; older commits walked per repository. |
| Strava | API policy effective 2026-06-01 §5.3 forbids use "in connection with the development, training, evaluation, or operation of any AI Application", including "ingestion into a context window"; Standard tier needs a paid subscription. | Bulk-export importer only (user-owned data outside the API agreement; confirm with counsel). |
| Goodreads / Letterboxd | Goodreads API closed December 2020; Letterboxd's beta refuses "LLM or GPT-related use" and "private or personal projects". | CSV importers. |
| Apple Health | No web API; HealthKit is on-device. | `export.xml` importer. |
| Browser history | Chrome `history` permission shows "Read and change your browsing history on all signed-in devices"; Firefox desktop only. | Deferred; the extension's explicit capture covers the useful case. |

The `EchoConnector` contract widens to the `personal-brain.md` shape (`privacy_weight`, `consent_disclosure`, `initial_backfill`, `incremental_sync`, `event_types`), connectors live under `backend/app/connectors/<name>/`, tokens go through the Fernet credential store, syncs run on the M3 scheduler tick, and a consent screen shows the disclosure before any redirect. `activity_events` is a new table; derived facts (`interest` from top channels, `skill` from languages, `daily_routine` from calendar) are written with sub-1.0 confidence.

### Domain 3 — voice and personality (E-3.3)

Signals are **rows, not prompt blobs**: `voice_signals(tenant_id, user_id, signal_type, value, weight, examples_json, language, register, derived_from, consent_version, suppressed_at, …)`. Two dimensions the roadmap lacked and the evidence demands: `language` (en, hi-Deva, hi-Latn, mixed) and `register` (intimate, casual, professional, public). Hindi–English users measurably shift voice per language (430k-tweet study: Hindi preferred for negative opinion and swearing, English for positive and professional content; Big-Five self-reports shift with language), so exemplars and centroids are bucketed per language and register. The script-based `language_service` cannot see romanised Hindi (a documented gap), so signal tagging needs a token-level language id for Latin-script Hindi before the Hinglish bucket is trustworthy.

Extraction in three cheap layers: (1) language-agnostic stylometry per note (function words, sentence-length distribution, punctuation, character n-grams; `faststylometry` for Burrows' Delta, MIT); (2) one open author embedding per note on the existing CPU embedding worker (`LUAR-MUD`, Apache-2.0, 82.5M parameters, 512-d; or `StyleDistance`, MIT) — both English-trained, so the embedding score is English-only until validated; (3) batched LLM trait extraction (`echo_extract_signals`, economy tier, the knowledge-agent map-reduce shape) emitting trusted conclusions, preferred solutions, recommendation lens, apprehensions, methodology and topic emphasis with verbatim examples, merged by `(signal_type, value)`. LIWC-22 (commercial) and Wegmann's `Style-Embedding` (no licence declared) are rejected. Inputs are only the user's own text: notes (M5), questions, shares with annotations, connector `text_content` where the user is the author; incoming content is a consumption signal, never a voice signal.

A `personal_context_global` collection embeds facts and signals for retrieval with the fail-closed tenant filter.

**Evaluation (S-3.3.4), the gate for the agent.** No automatic metric is credible alone: an LLM-as-personalised-judge has "low and inconsistent agreement" with humans unless it abstains on uncertain items; style metrics are content-entangled; human evaluations are routinely under-powered. Three tiers: (i) an automatic authorship-verification score from the open embedding against the user's held-out texts per language, as a regression gate; (ii) an uncertainty-aware LLM judge for the in-UI voice-match number, never as the product gate; (iii) a blinded pairwise "which of these did you write?" test with the user as judge, the one credible anchor, since Echo uniquely has the true author on hand. Plus a quality guard (preference against a neutral draft), because direct style optimisation is documented to collapse readability.

### Domain 4 — speak as me (E-3.4) and the surface (E-3.8)

**Retrieval plus critique, not fine-tuning.** The best 2025–26 evidence: about five exemplars capture most of the prompt-time style gain with little return beyond; content-matched exemplar selection *hurt* attribution, so exemplars are chosen for style diversity within the target language and register; direct LoRA raised style accuracy but collapsed preference rate (97.9 % → 38.1 %); a profile-conditioned critic scoring tone, vocabulary, sentence structure and topicality improved personalisation by 8.5–12 % over retrieval alone across three to five iterations (no human evaluation in that study). Pipeline as in `personal-brain.md`: classify intent → retrieve knowledge → retrieve signals → retrieve facts → draft → critique against the trait card with knockout, two or three rounds → finalise with citations, voice-match score, deviation notes. Drafts only, never sent. The feedback loop stores the user's edit diff as a signal candidate.

**Disclosure and safety.** A visible, user-removable line "Drafted with Echo, reviewed by <user>", on by default: the "reviewed by" clause is what the EU AI Act Article 50(4) editorial-responsibility exception keys on if a draft is ever published; Article 50(1) applies to the conversational bubble from 2026-08-02 (marking duties for existing systems deferred to 2026-12-02; the Code of Practice exempts text under about 200 tokens from watermarking). India's February 2026 rules cover audio and visual synthetic content only. Provider policies bar impersonating *others*; the provenance guard (only the tenant's own authored text feeds a voice) is enforced in code, not advised. A daily draft cap through `quota_metering_service`, an audit event per draft, and a flag before drafting anything that names a non-public person.

**Bubble.** Mounted in `AppLayout` for Studio users; dialog semantics (focus in and out, Escape, Tab wrap, `aria-modal` only if truly modal); shows per-domain readiness in words below the gate. **Not `Cmd-E`** as the roadmap sketched: it is macOS's system-wide "Use Selection for Find" and clashes in Safari and Chrome; `Ctrl-J` opens Chrome downloads. Proposed: `Ctrl/Cmd-Shift-E` plus an "Ask Echo" command in the M2 palette. Anticipation cards (suggested questions from M4, unread shares, changed saved searches from M3) live in the panel.

**Readiness (S-3.5.1).** No comparable product publishes a numeric threshold; NotebookLM, Gemini Personal Intelligence, ChatGPT memory and Grammarly's voice profile all accumulate passively from the first item. The literature's anchors are about five exemplars for prompt-time voice and 32 (Bedrock minimum) to 100 (Vertex recommendation) examples for fine-tuning. Proposed gate: the `personal-brain.md` per-domain minima **plus** a per-language voice floor (about 30 notes or 2,000 words, to be tuned), centroid stability (bootstrap variance below a threshold), and one passed blinded user-as-judge session. [D-049](../decisions.md#d-049--echo-cold-start-readiness-threshold-shipped-triple-is-v1-personal-brainmd-sub-table-is-forward-looking-spec-resolves-oq-6-2026-05-06) already named the four-domain table as the forward spec.

### Mode B — fine-tuning (E-3.9), deferred

OpenAI is **winding down self-serve fine-tuning**: no new jobs for anyone after 2027-01-06, and gpt-4.1, gpt-4.1-mini and gpt-4o with their fine-tunes retire 2027-01-14; the successors are not listed as fine-tunable. Anthropic offers fine-tuning only for Claude 3 Haiku on Bedrock in us-west-2 with provisioned throughput. Vertex supports Gemini 3.5 Flash, 3.1 Flash-Lite and the retiring 2.5 line. Local LoRA on open weights (Unsloth core, Axolotl, PEFT, all Apache-2.0; about 6 GB VRAM floor for an 8B QLoRA, 12–16 GB realistic) is the only durable path, and narrow fine-tunes are documented to shift broad traits (emergent misalignment, persona-vector sycophancy) and to trade quality for style. Therefore: provider-agnostic from the first line; export theme datasets now in OpenAI chat JSONL (byte-compatible with Hugging Face TRL's `messages` format) plus thin Bedrock-Claude and Vertex variants, every example tagged with `language`, `register`, `source_id`, `consent_version`; train only with a preference-rate quality guard and persona-vector style regression prompts; route through the E-1.13 per-user override.

### Privacy (E-3.10)

Export (one archive, JSONL per table plus files) and full delete (cascading across tables, files, credentials and Chroma collections, verified by a zero-row test) ship with the first new table. GDPR Article 20 portability drives the export (India's DPDP Act has no portability right; its substantive rules apply from about May 2027). **Zero-knowledge mode cannot coexist with the server-side pipeline**: sentence-transformers and Chroma need plaintext, and embeddings cannot be computed on ciphertext. The honest options are client-side embeddings in the browser (vectors are themselves a lossy leak and must be treated as personal data), a "private-by-key" mode (at-rest encryption with a tenant key, operator can read, say so plainly), or local-only. Only the second fits the current LangGraph and Chroma pipeline; the decision is deferred to SaaS launch and recorded as an open question.

## Alternatives rejected

| Option | Why not |
|---|---|
| Storing events and shares in `personal_context` | Unique per `(kind, key)`; a watch history has thousands of rows per kind. |
| YouTube watch history via the Data API | Removed in 2016; the Data Portability scope is restricted and needs annual CASA plus billing. |
| Spotify as a SaaS connector | Five users per development-mode app since 2026-02-11; extended quota needs a 250k-MAU business. |
| Gmail connector now | Restricted scope, annual security assessment cost; highest privacy weight; last in the design doc's own order anyway. |
| Strava, Letterboxd, Goodreads APIs | Forbidden for AI use, refused for LLM projects, closed. |
| Fine-tuning first (Mode B before Mode A) | Provider shutdowns above; quality collapse in the one head-to-head; five exemplars already deliver most of the gain. |
| LLM-as-judge as the readiness or quality gate | Low and inconsistent agreement with humans unless it abstains. |
| `Cmd-E` for the bubble | macOS system shortcut; clashes in Safari and Chrome. |
| Browser history connector now | Heavy install warning, tightened store policy, desktop-only on Firefox; explicit capture via the extension covers the need. |
| True zero-knowledge mode | Incompatible with server-side embeddings and the Q&A pipeline without a rewrite. |

## Schema deltas

- `personal_context`: add `tenant_id` (backfilled `= user_id`).
- New `shares_inbox` (per `personal-brain.md` plus `author_is_tenant`, `file_path`), `activity_events` (plus `external_id` unique per connector), `voice_signals` (plus `language`, `register`, `consent_version`, `suppressed_at`), `echo_connector_grants(tenant_id, connector, consent_version, granted_at, revoked_at)`, `echo_drafts(id, tenant_id, input, draft, score, citations_json, created_at)`.
- Chroma: `shares_global`, `personal_context_global`, both with `tenant_id` metadata and fail-closed filters.

## API deltas

`/echo/shares` CRUD and upload; `/echo/import` (archive upload with format detection); `/echo/signals` CRUD and export; `/echo/connectors/{name}/authorize|callback|sync` and `DELETE`; `/echo/draft`, `/echo/draft/{id}/feedback`; `/echo/chat`; `/echo/export`, `DELETE /echo/brain`; `/echo/status` returns per-domain progress. New registry use cases: `echo_extract_signals`, `echo_classify_intent`, `echo_draft`, `echo_critique`. New settings: `ECHO_SHARES_DIR`, `ECHO_DRAFTS_PER_DAY`, `ECHO_IMAP_*`, `OAUTH_GOOGLE_CONNECTOR_CLIENT_ID/SECRET`, readiness thresholds.

## Modules touched

`models/{shares_inbox,activity_event,voice_signal,echo_connector_grant,echo_draft}.py` (new), `services/echo_service.py` (widened contract, readiness v2), `services/echo_intake_service.py`, `services/echo_signal_service.py`, `services/echo_importers/*` and `backend/app/connectors/*` (new packages), `agents/echo_agent.py` and `agents/prompts/echo_prompts.py` (new), `services/chroma_service.py` (two collections), `services/dataset_service.py` (theme exports), `routers/echo.py`, `tasks/echo_tasks.py` (new), `frontend/src/pages/EchoPage.tsx`, `frontend/src/components/echo/*` (bubble, inbox, signals panel), `frontend/src/layouts/AppLayout.tsx`, `extension/` (new top-level directory), `scripts/start.ps1` (beat, via M3).

## Risks

- Google verification is per project; the 100-user cap on unverified sensitive-scope apps is irreversible; the "7-day refresh-token expiry in testing mode" claim is unconfirmed.
- Export schemas (Instagram, TikTok, Goodreads, Letterboxd) are undocumented and change silently; keep parsers tolerant and ship fixtures.
- Apple Health exports exceed any web upload limit; needs chunked upload or a CLI importer.
- Vision-LLM OCR sends third-party images to a provider; must follow the BYOK and local-only controls ([D-043](../decisions.md#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05)).
- Every open style embedding is English-trained; a Hinglish voice score is not trustworthy until a multilingual model is validated.
- Measurement risk is structural: user-as-judge tests cost user time, and automatic metrics are content-entangled.
- CASA is a recurring line item the moment Gmail or Data Portability is added.
- WhatsApp exports are other people's personal data; a SaaS operator is a processor and the DPA must say so.

## Test strategy

- Importers: fixture exports for every format (iOS and Android WhatsApp, Takeout JSON, Keep JSON, Spotify JSON, Goodreads and Letterboxd CSV, a truncated Health XML) with streaming assertions; `author_is_tenant` set correctly.
- Intake: each content type with external calls patched; failure leaves the share browsable; delete cascades to derived rows; isolation (two tenants, foreign ids 404).
- Connectors: a fake connector exercising backfill, idempotent incremental sync and revoke cascade; recorded API fixtures for GitHub, YouTube and Calendar; OAuth state and PKCE reuse from the login tests.
- Signals: stylometry on fixtures; LLM patched; tombstones never resurrect.
- Agent: LLM patched; readiness gate returns 409 with diagnostics; citation grounding; draft cap; the critic loop terminates.
- Readiness: per-domain thresholds and the all-domains gate.
- Privacy: export archive round-trips; delete leaves zero rows, files, credentials and vectors.
- Quality: the S-3.3.4 harness run before E-3.4 is enabled for anyone.

## First PR (S-3.7.1)

`shares_inbox` table and the `tenant_id` backfill on `personal_context` in one revision; `POST/GET/PATCH/DELETE /echo/shares` for URL, text and file shares with `surface=manual_quick_share`; files under `ECHO_SHARES_DIR/<tenant>/` with the traversal guard and a size cap; the "Add to Echo" quick-share in the sidebar and an `/echo/inbox` page; isolation and cascade tests. No processing yet (S-3.7.2 follows), no LLM, no OAuth. It is the first row of Domain 5 and moves the readiness counter from the first share.

## Open questions (the user's call)

1. **Private-by-key or nothing for SaaS.** True zero-knowledge is incompatible with the pipeline; is server-readable, tenant-key-encrypted at rest an acceptable promise if labelled honestly?
2. **Third-party content default.** Context-only (retrievable, never quoted, never exported) is the recommendation; should the user be able to override it for a specific thread?
3. **The bubble's shortcut.** `Ctrl/Cmd-Shift-E` is proposed; the roadmap said `Cmd-E`, which conflicts.
4. **Spotify live tail.** Worth building at all given it is self-host-only, or export import only?
5. **When Gmail.** Only with revenue to fund the annual assessment, or never, with IMAP plus app password as the self-host answer?
6. **Mode B at all.** Given the provider shutdowns and the quality trade-off, is local LoRA worth pursuing, or does retrieval plus critique remain the product?

## Sources (fetched 2026-10-19)

YouTube Data API revision history, `videos.list`, `subscriptions.list`, quota and scope pages; Google Data Portability scopes and user guide; Google My Activity schema; Google OAuth sensitive and restricted scope verification pages, restricted-scopes list, user-cap page; Gmail scopes; Google app passwords and LSA shutdown notice; Spotify recently-played reference, quota modes, February 2026 migration guide, July 2026 quota blog, data-export help; Strava API policy and press release; Goodreads API shutdown coverage; Letterboxd API beta page; Apple Health export community docs; GitHub events and rate-limit docs; Chrome history API, permissions list, Web Store user-data and 2026 policy pages; MDN history and Web Share Target; WebKit and vendor pages on iOS share targets; Postmark, Mailgun, Cloudflare Email Routing pricing; IMAPClient docs; WhatsR parsers; Keep Takeout gists; TikTok and Instagram export guides; Tesseract, EasyOCR, PaddleOCR, RapidOCR repositories; OpenAI, Anthropic and Google vision pricing; GDPR Articles 12, 17, 20; DPDP rules coverage; Limitless, Reflect, Obsidian, Mem privacy pages; libsodium, PyNaCl, age, pyrage, Transformers.js; LaMP, PersonaLLM, "Catch Me If You Can? Not Yet" (Findings EMNLP 2025), "Predicting Steering Vectors and Adapter Weights" (2610.03163), "Can LLM be a Personalized Judge?", PerFine (2510.24469), Emergent Misalignment (2502.17424), Persona Vectors (2507.21509), Rudra et al. EMNLP 2016, Ramírez-Esparza 2006; LUAR-MUD, StyleDistance, Style-Embedding model cards; faststylometry, TextDescriptives, Empath; OpenAI fine-tuning guide, pricing and deprecations; Bedrock and Vertex fine-tuning docs; Unsloth, Axolotl, PEFT; EU AI Act Article 50 pages and Code of Practice; India IT Rules 2026 amendment coverage; OpenAI usage policies; WAI-ARIA dialog pattern; Apple developer forum on Command-E. Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/): [`l3-echo-connectors.md`](research/l3-echo-connectors.md) and [`l3-echo-personality.md`](research/l3-echo-personality.md).
