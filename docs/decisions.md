# Pratidhvani — Decision Log

**Status:** living doc (last refreshed 2026-04-25). Owner: [`/knowledge-curator`](../.claude/skills/knowledge-curator/SKILL.md) skill.

This is the chronological record of every product / engineering decision made on this project that is **not** trivially recoverable from `git log`. Use it to recall *why* a path was chosen and what alternatives were rejected, so future-you doesn't relitigate settled questions.

---

## Conventions

- **Numbering** is monotonic (`D-001`, `D-002`, …). Never renumber. If a decision is reversed, add a new entry that supersedes the old one and update the old one's `Status:` line.
- **Status** values: `accepted` / `proposed` / `superseded by D-NNN` / `rejected`.
- Each entry has the same five sections so the log is skimmable: **Context**, **Decision**, **Alternatives considered**, **Consequences**, **Linked initiatives / PRs**.
- Date format is ISO `YYYY-MM-DD`.
- The `Linked initiatives / PRs` field uses IDs from [`initiatives.md`](initiatives.md) and PR numbers from GitHub.

---

## D-001 — Rebrand to `Pratidhvani` (प्रतिध्वनि) (2026-04-24)

**Status:** accepted.

**Context.** The product was prototyped as *VideoResearchPro*, a placeholder name carried from the first commit. As the vision broadened beyond YouTube into a curated, opinionated personal wiki, the placeholder name no longer described the product.

**Decision.** Rename to **`Pratidhvani`** (Devanagari `प्रतिध्वनि`, Sanskrit/Hindi for *echo*). User-facing copy uses the new name immediately; legacy code identifiers (`videoresearchpro_global` Chroma collection, package paths) stay until a deliberate cleanup pass.

**Alternatives considered.**
- *Folio / Lore / Marginalia* — generic-feeling, English-Latin SaaS-name energy.
- *Keep VideoResearchPro* — describes the prototype, not the product.

**Consequences.** Visual identity, marketing copy, and all docs lead with the new name. Legacy strings in env-var names (`CHROMA_GLOBAL_COLLECTION_NAME=videoresearchpro_global`) preserved for back-compat. No code rename in this decision — that's its own future PR.

**Linked initiatives / PRs.** I-2 (Brand & visual identity rollout) — see [`branding.md`](branding.md).

---

## D-002 — Warm-editorial visual identity (2026-04-24)

**Status:** accepted.

**Context.** Default purple-blue gradient (`#667eea → #764ba2`) reads as generic-AI-SaaS. Vision is a personal library / research journal, not a dashboard.

**Decision.** Adopt a warm-editorial palette (paper background, oxblood / forest-teal / vintage-gold accents) and serif typography (Fraunces display, Source Serif body, Inter for UI sans, JetBrains Mono for code). Concentric-arcs glyph for the favicon; full Devanagari + Latin lockup for masthead. Full token table in [`branding.md`](branding.md).

**Alternatives considered.**
- *Keep purple-blue* — wrong vibe for the product framing.
- *Pure brutalist / minimalist* — too cold for "personal library".
- *AI-cliché sparkles / neural-net iconography* — explicitly avoided.

**Consequences.** All page styling reads from `frontend/src/theme.ts` tokens going forward. Migrating the 10 existing pages page-by-page is its own initiative.

**Linked initiatives / PRs.** I-2 (Brand & visual identity rollout).

---

## D-003 — Echo / personal-brain as the long-horizon north-star (2026-04-24)

**Status:** accepted.

**Context.** User delivered a verbatim vision message (now preserved in [`docs/notes/2026-04-24-echo-feature-vision.md`](notes/2026-04-24-echo-feature-vision.md)) describing an app that ingests *liked videos, reels, memes, WhatsApp conversations, posts, Google Keep notes, quotes* and over time develops a personality matching the user — speaks in their voice, recommends from their lens, draws on their conclusions.

**Decision.** Adopt this as **L3 — Echo** (formerly "Personal Brain"). Architecturally: a fourth Domain (constant-stream intake) on top of the existing three (sources / Q&A history / activity), driving a personality model (Ring 3 surface) that becomes available once a cold-start readiness threshold is crossed.

**Alternatives considered.**
- *Treat as a parking-lot idea* — the user explicitly asked to capture and ingest.
- *Build now* — premature; depends on multi-source ingest (L1) and accumulated personal data first.

**Consequences.** Today's schema decisions must remain forward-compatible (e.g. `tenant_id` and a `user_provenance` JSON column placeholder on every user-scoped table). Echo itself is multi-quarter trajectory work, not next-PR work.

**Linked initiatives / PRs.** I-3 (Echo). [`personal-brain.md`](personal-brain.md), [`vision.md`](vision.md) Ring 3.

---

## D-004 — L1 multi-source ingest as the next large initiative (2026-04-24)

**Status:** accepted (in-progress).

**Context.** YouTube-only ingest is the prototype's defining limit. The vision (curated personal wiki) requires podcasts, articles, threads, books, and forum posts to all flow through the same search → approval → ingest → embed → query pipeline.

**Decision.** Generalize the data model: `videos` → `documents` with a `source_type` discriminator; introduce a `BaseConnector` interface every new source type implements; one ChromaDB collection holds all source types with metadata-filter scoping. Phased PR plan (additive cols → connector abstraction → route call sites → table rename → first non-video connectors).

**Alternatives considered.**
- *Per-source-type collections* — fragments retrieval and complicates the existing per-job filter.
- *Per-source-type tables* — duplicates schema and forces N-way joins everywhere.
- *Build the connectors first, generalize the model later* — locks in YouTube assumptions and forces a painful migration mid-flight.

**Consequences.** Schema migration runs before any non-video connector ships. Q&A, knowledge extraction, fine-tune dataset shapes all generalize for free once `Document` is the unit.

**Linked initiatives / PRs.** I-1 (Multi-source ingest). PRs [#63](https://github.com/khoks/VideoResearchPro/pull/63), [#65](https://github.com/khoks/VideoResearchPro/pull/65), [#66](https://github.com/khoks/VideoResearchPro/pull/66), [#67](https://github.com/khoks/VideoResearchPro/pull/67) shipped 2026-04-22 → 2026-04-25.

---

## D-005 — Social-media ingest before article ingest (2026-04-25)

**Status:** accepted.

**Context.** After L1 PRs 1–4 shipped, the question was which non-video connector to build first. Article-connector deep-dive was on deck (trafilatura + Playwright fallback). User redirected: groom social-media post ingest first (Twitter/X, Facebook, Instagram, Discord, LinkedIn, Reddit, HN), with the same search → approval → ingest → Q&A pipeline.

**Decision.** Defer article connector. Build social-media connectors as L1 Epic E-1.5 in this order: **Reddit + HN first**, then Mastodon + Bluesky, then a generic manual-paste mode covering FB/IG/LI/X-without-paid-API, then paid Twitter API as a self-host opt-in, then per-server Discord bot.

**Alternatives considered.**
- *Article connector first* — already groomed; technically easier but less aligned with user intent.
- *Twitter/X first* — user-iconic platform, but $200/mo Basic API tier makes it a poor day-one pick for self-host default.
- *Try to scrape FB/IG/LI search results* — explicit ToS violation, fragile, bannable. Rejected.

**Consequences.** Article connector deferred (kept as Epic E-1.6, status 🔴 deferred). Multiple new `source_type` enum values land in PR series E-1.5. Search availability differs by platform — UI must be honest about Mode A (search) vs Mode B (paste only).

**Linked initiatives / PRs.** I-1 / E-1.5. Stories pending.

---

## D-006 — One `Document` row per social-post thread, not per comment (2026-04-25)

**Status:** accepted.

**Context.** Social-media threads have an OP plus N replies / comments. Two natural shapes: (a) one row per OP plus separate child rows for each reply, or (b) one row whose text is the OP + flattened replies, with reply-level metadata stored alongside.

**Decision.** Shape (b). One `Document` per thread. Comment tree is flattened into the document's `text_cache` with markers like `\n[--- reply by @user (score 42) ---]\n`. Per-comment metadata (id, author, score, sentiment) lives in `source_metadata.comments[]`. Citations carry a `comment_id` (or equivalent) so the frontend can deep-link back to the specific reply.

**Alternatives considered.**
- *Row-per-comment* — N× row growth, scattered citation surface, fine-tune dataset balloons, more joins everywhere.
- *Row-per-OP, comments dropped* — loses the actually-interesting content (the discussion itself).

**Consequences.** RAG chunking happens over the whole flattened thread, so comments get cited alongside the OP — exactly the "what people actually say to each other" surface area the vision targets. No new tables. Approval UI shows one card per thread with comment-count + sentiment-mix preview.

**Linked initiatives / PRs.** I-1 / E-1.5.

---

## D-007 — Sentiment / stance classification at fetch time (2026-04-25)

**Status:** accepted.

**Context.** User wants to filter discovered threads by sentiment ("show only critical takes on X", "show threads in favor of Y"). Platform APIs do not expose sentiment; we need to classify ourselves.

**Decision.** Run a small LLM classifier when a candidate document is fetched. Store the result on `Document.source_metadata` as `{stance, sentiment, topic_relevance}`. Same classifier runs on each comment in the thread, with results aggregated under `source_metadata.comments[].sentiment`. New use case `social_classify_stance` in `USE_CASE_REGISTRY` with cheap default (`provider=openai, model=gpt-4.1-mini, reasoning=off`). Approval UI surfaces classification as a hint, never as an automatic filter that hides candidates.

**Alternatives considered.**
- *Query-time classification* — runs the classifier every approval-list view, wasteful and slow.
- *No classification* — user has to read every snippet to filter. Doesn't scale to 200 candidates.
- *Use platform-provided sentiment (e.g. Reddit upvote ratio)* — too coarse and platform-specific.

**Consequences.** One-shot LLM cost per candidate at ingest time (cheap model, but real money on big Reddit pulls). Classifier output is stored once and reused forever. Sarcasm / dog-whistles / in-group code remain noisy — surface as hint, not gate.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.3.

---

## D-008 — No scraping of search-result pages on FB / IG / LinkedIn (2026-04-25)

**Status:** accepted.

**Context.** Facebook, Instagram, and LinkedIn have effectively **no public-search APIs** for non-owned content (FB Graph API since 2018, IG Graph requires Business + scope review, LinkedIn Marketing API is gated). Scraping search-result pages is the only way to do "search topic X on Facebook".

**Decision.** Do not scrape search-result pages on any platform. Do not store cookies / session tokens to pull from logged-in pages on the user's behalf (in self-host today). Only support Mode B (manual paste of post URLs) for these platforms; the UI is honest that search isn't available.

**Alternatives considered.**
- *Scrape search results* — explicit ToS violation, IPs get banned, fragile against any HTML change, legally murky for a SaaS future.
- *Use third-party scraping APIs (e.g. Apify, ScrapingBee)* — outsources the same ToS violation to a vendor we'd be paying.
- *Paid Twitter Basic API as the only "real" social search* — accepted as a self-host opt-in (BYOK), separate decision under D-009.

**Consequences.** The "social search" feature is platform-asymmetric: rich on Reddit/HN/Mastodon/Bluesky, paid-opt-in on Twitter, paste-only on FB/IG/LI. UI must clearly differentiate Mode A platforms from Mode B platforms.

**Linked initiatives / PRs.** I-1 / E-1.5.

---

## D-009 — Twitter / X is BYOK + opt-in (2026-04-25)

**Status:** accepted.

**Context.** Twitter has a usable search API but it's paid: Basic tier $200/mo for 15K read / month, Pro $5K/mo for 1M reads. Self-host default cannot assume the user has paid for it.

**Decision.** Twitter connector is **opt-in**: user provides a `TWITTER_BEARER_TOKEN` env var (BYOK — bring-your-own-key), connector is enabled if and only if the token is present. Without the token, the UI shows Twitter as Mode B (paste post URL) only. Future SaaS Pro tier may bundle a shared Twitter quota.

**Alternatives considered.**
- *Default-on with a project-funded API token* — burns money on every self-host install for free.
- *Default-off and paste-only forever* — leaves a major source-of-discussion surface unsearchable for users willing to pay.
- *Free-tier limited-search* — Twitter's free tier is no longer real for this use.

**Consequences.** No code default for the Twitter API token. Documentation calls out the cost up front. The same pattern (BYOK env var) is the SaaS "Pro tier" hook later.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.10 (Twitter connector — pending).

---

## D-010 — Defer TikTok and per-server Discord bot indefinitely (2026-04-25)

**Status:** accepted.

**Context.** TikTok's Research API is US-academic-gated; the Display API has no search. Discord has no global search — a bot can only see servers it is invited to.

**Decision.** Both deferred indefinitely. TikTok is too gated to support a generic personal-wiki use case. Discord is a niche surface (only useful when the user controls/joins a server) and a bot-per-server install model is heavy for marginal value.

**Alternatives considered.**
- *Build TikTok via display-page scraping* — same ToS objection as D-008.
- *Build Discord bot for self-host* — possible, but defer until at least one user explicitly asks for it.

**Consequences.** Roadmap calls out these as deferred so a future contributor doesn't accidentally pick them up before they're worth doing. Per-server Discord may unfreeze if a clear use case emerges.

**Linked initiatives / PRs.** I-1 / E-1.5 (deferred sub-items).

---

## D-011 — Two persistence skills + auto-Stop-hook for session-to-docs flow (2026-04-25)

**Status:** accepted.

**Context.** Conversations between Claude and the user routinely produce decisions, vision refinements, architecture choices, and new work items that risk being lost in the chat transcript. Manually remembering to update `feature-roadmap.md` / `architecture.md` / `decisions.md` / a Jira board after every session is unreliable.

**Decision.** Two named skills live in the repo: [`/knowledge-curator`](../.claude/skills/knowledge-curator/SKILL.md) (owns the canonical docs + this decision log) and [`/work-tracker`](../.claude/skills/work-tracker/SKILL.md) (owns [`initiatives.md`](initiatives.md), the Initiative → Epic → Story → Task hierarchy). Both auto-invoke at session-end via a project `Stop` hook (`.claude/settings.json`) that nudges Claude once per session (`stop_hook_active` guards against recursion). Both commit on a fresh branch and open a PR to master — never push directly.

**Alternatives considered.**
- *One mega-skill* — conflates two different audiences (docs vs work-state); harder to invoke partially.
- *No auto-invocation, manual `/curate` only* — unreliable; the whole point is to not depend on remembering.
- *Hard-block via Stop hook with no `stop_hook_active` guard* — infinite loop.
- *External Jira / Linear* — out-of-repo, requires API keys, drifts from code, breaks the "doc-first repo" stance.

**Consequences.** Every substantive session produces 0–2 PRs (one for docs, one for work-state) at end. Skills are allowed to be no-ops on tactical sessions. New contributors / future-Claude can read `decisions.md` + `initiatives.md` and reconstruct project state without trawling chat history.

**Linked initiatives / PRs.** I-4 (Self-curating docs & work-state) — bootstrap PR pending (this commit).

---

## D-012 — Capture novel / potentially-patentable ideas in `inventions.md` (2026-04-25)

**Status:** accepted.

**Context.** Conversations regularly surface specific mechanisms or non-obvious combinations that may be defensible IP. The decision log (`decisions.md`) captures *which path* we picked among known options; it does not capture *new mechanisms* invented during the session. Without a dedicated home, a novel idea can be lost in a Slack-shaped chat history with no preserved chronology, which would also undermine any future prior-art claim.

**Decision.** Add a third canonical doc — [`inventions.md`](inventions.md) — owned by [`/knowledge-curator`](../.claude/skills/knowledge-curator/SKILL.md). The skill applies a detection heuristic (explicit user signal *or* a specific mechanism Claude doesn't recognize from public literature *or* a non-obvious combination producing measurable advantage *or* a unusual product shape). Each entry has Status / Source / Summary / Mechanism / Why-novel / Prior-art / Commercial implications / Linked-decisions-initiatives-PRs / Verbatim-source. Verbatim user messages flagged as novel are also preserved raw under `docs/notes/<YYYY-MM-DD-novel-<slug>.md`. The skill **does not** make legal patentability assessments — only captures and preserves chronology.

**Alternatives considered.**
- *Fold novel-ideas into `decisions.md`* — conflates "we chose path A over path B" with "we invented mechanism X". They have different audiences (engineers + lawyers), different update cadences (decisions resolve once; inventions accrue prior-art notes), and different legal weight (chronology is load-bearing for inventions).
- *No dedicated capture; rely on chat history* — chat is not durable, lacks chronological certification, and is searched poorly. Loses provenance the moment context clears.
- *Have the skill auto-classify patentability* — out of scope. Patentability is a legal question; the skill captures, the user (with counsel) decides.

**Consequences.** A new doc to maintain. The curator skill biases toward over-capture (a false positive costs nothing — mark `superseded by prior art`; a false negative loses chronology forever). Verbatim source preservation extends the existing safekeeping pattern at `docs/notes/`. Future SaaS commercialization gets a defensive-disclosure paper trail.

**Linked initiatives / PRs.** I-4 / E-4.7. PR [#68](https://github.com/khoks/VideoResearchPro/pull/68) (same bootstrap PR, follow-up commit).

---

## D-013 — Pseudo-timestamps at 3 wps for text-based connectors (2026-04-25)

**Status:** accepted.

**Context.** The chunker in `app/utils/chunking.py` was designed around YouTube transcripts whose segments carry natural `(start_time, end_time)` pairs. It threads those values onto every chunk's metadata so per-chunk citations can build `&t=NNs` deep-links. Text-based sources (Reddit threads, HN comment trees, articles, tweets, future Mastodon / Bluesky) have no native time axis but must still satisfy the chunker's segment contract; otherwise we fragment the chunker into per-source-type variants.

**Decision.** Text-based connectors synthesize pseudo-timestamps at **3 words/second** (~180 wpm — a normal reading cadence). Each segment's `start` is the running word-count cursor up to that segment divided by 3.0; `end` is `start + (segment_words / 3.0)`. The first segment starts at `0.0`. The synthetic values flow through chunk metadata but are never displayed to the user — text-source citations use `permalink` / `#comment-<id>` / page-anchor deep-links instead of `&t=`. Codified in `app/sources/reddit/flatten.py::_segment_for_text` via the constant `_WORDS_PER_SECOND = 3.0`.

**Alternatives considered.**
- *Make `Segment.start` / `.end` `Optional[float]` and branch the chunker on `None`* — fans out a `None` check across every code path that reads chunk metadata; the chunker becomes source-type-aware.
- *Special-case the chunker by `source_type`* — moves source-type knowledge into a layer that should stay generic; same coupling problem.
- *Propagate `word_index` instead of `time`* — requires a parallel metadata field everywhere `start_time` / `end_time` is read (search / Q&A / citation builders), and the chunker contract still wouldn't accept it.
- *Pick a different rate (e.g. 2 or 4 wps)* — 3 wps is a coarse but defensible reading-speed estimate; the rate is a one-line constant if a future connector needs to tune.

**Consequences.** Every future text-based connector (HN, Mastodon, Bluesky, articles, tweets) reuses the same constant — no per-source chunker branches. The synthetic time values are meaningless to users but make all downstream tooling uniform. If 3 wps proves a poor proxy (e.g. messes up chunk-size estimation), revisit by tuning the constant in one place rather than re-architecting the contract.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.1. PR [#70](https://github.com/khoks/VideoResearchPro/pull/70) (initial implementation in Reddit connector).

---

## D-014 — Add `framing` axis to `social_classify_stance` schema (2026-04-26)

**Status:** accepted.

**Context.** [D-007](#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25) defined the `social_classify_stance` use case to emit `{stance, sentiment, topic_relevance}` per fetched social post (and per comment). This handles **polarity** ("for / against / neutral") and **tone** ("positive / negative / mixed"), but not **register** — the lens through which someone is engaging with the topic. Two posts can both be `against` a policy while one cites economic data ("the math doesn't work because...") and the other cites lived experience ("when this passed in 2019 my industry collapsed"). For L4 source-weighting and contradiction detection — and for the user's "show me the *kinds* of perspectives, not just the polarity split" use case — collapsing both into `against / negative` flattens out the genuinely different ways people argue.

**Decision.** Add a fourth axis `framing` to the classification schema with four primary values:

- **`technical`** — argues from data, citations, mechanism, system-level reasoning ("the math doesn't work because…", "the latency would be unacceptable")
- **`political`** — argues from ideology, party-line, group-identity ("conservatives / progressives think…", "this is what the establishment wants")
- **`emotional`** — argues from affect, outrage, joy, fear ("this is terrifying / amazing / disgusting"; tone-driven without reasoning chain)
- **`experiential`** — argues from first-person lived experience ("when I tried this…", "in my industry…", "as a parent of three…")

The classifier picks **one primary** framing. The values are not mutually exclusive in reality, but a flat single-label keeps the prompt cheap and the badges legible. A future `framing_secondary` slot is deferred until single-label proves lossy.

**Alternatives considered.**
- *Don't add framing* — keeps the schema small but L4 perspective-clustering becomes hard; you can only see polarity, not register, and the `experiential` voice (which the user explicitly values) drowns under generic `against / negative` aggregation.
- *Free-text `framing` label* — maximally flexible but unrankable / unfilterable in the UI; no consistent vocabulary across the corpus, defeats the point of structured classification.
- *Larger taxonomy* (academic / journalistic / activist / personal / humorous / sarcastic) — more granular but each value gets fewer examples in any reasonable batch and classifier accuracy on a `gpt-4.1-mini`-class model degrades fast as the cardinality grows. Four values is coarse enough to rate consistently.
- *Multi-label (return all framings present, ranked)* — better fidelity but doubles classification cost and complicates UI rendering; defer to a phase-2 ADR if data shows single-primary is too lossy.

**Consequences.**
- Schema becomes `{stance, sentiment, framing, topic_relevance}`. Pydantic model adds the `framing: Literal["technical", "political", "emotional", "experiential"]` enum.
- LLM prompt grows by ~80 tokens (one rule + four exemplars). Negligible on `gpt-4.1-mini`.
- Approval-UI badges (S-1.5.4) gain a fourth chip; filter chips can pick "show only experiential" or "show only technical".
- L4 retrieval re-ranker can boost / dampen by framing per user preference (e.g. weight `experiential` higher when researching "how do people *feel* about X", weight `technical` higher when researching "how does X actually work").
- Source-types.md classification schema and S-1.5.3 acceptance + tasks updated in lockstep.
- Future ADR may add `framing_secondary` if data shows single-label is too lossy in production.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.3. Builds on [D-007](#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25).

---

## D-015 — Promote E-1.10 (UUID PK) ahead of Reddit / HN orchestrator wiring (2026-04-26)

**Status:** accepted.

**Context.** The Reddit and HN connectors (S-1.5.1, S-1.5.2 — both shipped) emit `Candidate.source_id` as namespaced strings: `"reddit:abc123"`, `"hn:42000000"`. T-1.5.1.4 (Reddit storage wiring) was originally scoped to land these into `documents.video_id` as-is, leveraging the existing PK column with a string namespace prefix. E-1.10 (UUID promotion: `video_id` → `document_id` UUID + a separate `source_id` text column) was filed but ⚪ proposed with the explicit blocker note: *"Wait until at least 2-3 non-video source types are in the codebase so we have evidence the namespaced-string approach really is friction (not premature)."* Two non-video connectors are now on master.

**Decision.** Promote E-1.10 ahead of the Reddit / HN orchestrator wiring. Sequence:

1. **E-1.10 ships first** — UUID `document_id` PK + a separate `source_id text` column with a `(source_type, source_id)` unique index. `job_videos` → `job_documents` (FK target updated). `transcript_cache` PK retargeted.
2. **T-1.5.1.4 (Reddit storage) and T-1.5.2.5 (HN storage — to be filed) follow** — both write into the new schema natively. No prefixed-string PK transitional state ever exists.
3. **Approval / Q&A / citation surfaces (S-1.5.3 / S-1.5.4 / S-1.5.5) build on the clean foundation.**

**Alternatives considered.**
- *Land prefixed strings into `video_id` now, promote PK later* — works in principle but creates two waves of migration. Every Reddit / HN row inserted with `video_id="reddit:abc"` later needs `source_id="abc"` backfilled and a `document_id` UUID assigned. Every JOIN site touched twice (once on insert, once on cutover). Risk of inconsistent intermediate state in production.
- *Hard-rename the PK column without UUID* (i.e. `video_id` → `document_id`, keep string type) — cosmetic only. Doesn't solve the underlying typing problem of a single PK column trying to be `YT11`, `reddit:abc`, `hn:123`, future `pdf:sha256-hex` simultaneously, with no schema-level guarantee of namespace uniqueness across types.
- *Keep namespaced strings forever, declare it the design* — the original E-1.10 blocker note suspected this might prove fine. Two reasons it doesn't: (a) UUID is the standard for shared multi-source primary keys, especially once SaaS adds tenancy; (b) `documents.video_id="reddit:abc"` makes legacy YouTube assumptions in code (column name reads as YouTube-only) much harder to audit and root out.

**Consequences.**
- E-1.5 (social-media connectors) initiative effectively pauses on **storage wiring** until E-1.10 ships. Connector code on master continues to work standalone — it emits Candidates; the orchestrator just doesn't dispatch them yet, which has no user-facing impact today.
- E-1.10 status moves from ⚪ proposed to 🔵 accepted with explicit "next" sequencing.
- T-1.5.1.4 and the to-be-filed T-1.5.2.5 (HN storage) become trivial: drop a row into a generic table, no namespace-prefix design needed.
- Migration shape (sketched): add `document_id UUID NOT NULL DEFAULT gen_random_uuid()` (Postgres) / `BLOB(16)` populated via Python (SQLite), populate for existing 912 rows, add `source_id TEXT` (backfill from `video_id`), drop `video_id` PK constraint, add `(source_type, source_id)` unique constraint, retarget FK targets in `job_videos` and `transcript_cache`. Reversible — rollback drops the new columns; the legacy PK is reinstated.
- The plus side of the reorder: T-1.5.1.4 / T-1.5.2.5 design pressure goes from *"how do we make namespaced strings work as a PK"* to *"insert a row"*.

**Linked initiatives / PRs.** I-1 / E-1.10. Updates the blocker note on E-1.10 (initiatives.md). Re-sequences E-1.5 storage tasks.

---

## D-016 — Single polymorphic approval card driven by `source_metadata` (2026-04-26)

**Status:** accepted.

**Context.** Today the approval UI renders YouTube videos with thumbnail / title / channel / duration / view-count / publish-date as a bespoke component. S-1.5.4 was originally scoped as a "social-post card variant" alongside the existing video card. With more source types on the L1 roadmap (Reddit, HN, Mastodon, Bluesky, paste-mode FB/IG/LI/X, articles, podcasts, PDFs, tweets), the variant approach implies N variants for N source types — duplicated card layout code, drift in spacing / density / dark-mode / focus-ring affordances between types, and a JS bundle that grows linearly with source-type count.

**Decision.** Render approvals through a **single polymorphic card** that reads the `source_type` discriminator and the `source_metadata` shape, not per-type card components. Composition is built from a small primitive set:

- `<CardHeader>` — author / handle / channel avatar + display name + platform glyph (always present; field mapping varies by source)
- `<CardBody>` — title or excerpt (always present)
- `<CardMetaRow>` — flexible row of `(icon, label, value)` chips: views, score, likes, RTs, points, comment count, duration, word count, published date — only the chips relevant to the source-type render
- `<CardBadgeRow>` — stance / sentiment / framing badges (post-[D-014](#d-014--add-framing-axis-to-social_classify_stance-schema-2026-04-26))
- `<CardActions>` — checkbox + "View on platform" link

Each source-type registers a small config: which meta chips to show, what the platform glyph is, which `source_metadata` fields map to `<CardHeader>`. Adding a source type = a new entry in a config map, not a new component file.

**Alternatives considered.**
- *Per-source-type card components (the original S-1.5.4 plan)* — clearer for any single type read in isolation, but every cross-cutting UI affordance change (focus ring, dark-mode contrast, mobile collapse, density toggle, accessibility tweaks) requires editing N components. Drift between types is inevitable; it's the path the existing 10-page inline-style codebase already learned the hard way.
- *Headless card primitive + per-type visual variants* — splits styling from logic but you still ship N visual files. Half the duplication, none of the savings on cross-cutting concerns.
- *Render-prop / slot-based composition* — pure flexibility but every source type composes its own card from scratch; the consistency-by-construction the polymorphic config gives you is lost. Slot APIs also tend to leak implementation details into the consumer.
- *Markdown-based template with a renderer* — overkill for this surface; the dynamic shape is small enough to live in a TS config object.

**Consequences.**
- One `<ApprovalCard>` component file. New source type = ~30-line config entry + a glyph asset (~+1 day of work over per-variant for the *first* source type, then –2 days per additional source type after that).
- Stance / sentiment / framing badges (D-014) become a sub-component reused across every card automatically — no per-variant duplication.
- Filter-chip behavior (e.g. "only experiential framing", "only score > 50") generalizes across types since the data shape is uniform: chips filter `source_metadata.<field>` regardless of `source_type`.
- Frontend test surface shrinks: one `<ApprovalCard>` component test parametrized over a fixture per source type, instead of N component tests.
- Risk: a future source type genuinely needs UI not expressible in the primitive set (e.g. a podcast card wants an inline audio scrubber). Mitigation: the per-source config can include a `customSlot` render override for the rare case; the default path stays uniform. We accept this escape hatch only if and when it's needed.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.4. Updates S-1.5.4 acceptance and tasks.

---

## D-017 — E-1.10 hard cutover (single-migration UUID PK promotion) (2026-04-26)

**Status:** accepted. Resolves [OQ-7](initiatives.md#open-questions-parking-lot).

**Context.** [D-015](#d-015--promote-e-110-uuid-pk-ahead-of-reddit--hn-orchestrator-wiring-2026-04-26) promoted E-1.10 ahead of Reddit / HN orchestrator wiring with an 8-task migration breakdown but did not specify the *cadence*. Two viable shapes were on the table (filed as OQ-7): **(a) hard cutover** — drop the legacy `video_id` PK and add the new `(source_type, source_id)` unique constraint in a single Alembic migration, single PR; **(b) additive-then-cutover** — ship `document_id` UUID + `source_id text` alongside the legacy `video_id` for one release with dual-write / dual-read at every reader site, then drop `video_id` in a follow-up PR. Recommendation in OQ-7 was (b) on reversibility grounds (project ships SQLite — no `pg_dump`-and-restore parachute — and 14 importers touch the legacy column).

**Decision.** Hard cutover. E-1.10 ships as a single Alembic migration that adds `document_id` UUID + `source_id text`, backfills both, drops the legacy `video_id` PK, adds the `(source_type, source_id)` unique constraint, and retargets `job_videos` / `transcript_cache` FKs in one transaction. T-1.10.1 .. T-1.10.8 (as drafted in [E-1.10 in initiatives.md](initiatives.md#e-110--promote-video_id-pk-to-uuid-document_id)) stay shaped exactly as listed — they were already hard-cutover-shaped; this ADR just formalizes the cadence.

**Alternatives considered.**
- *Additive-then-cutover* — was the OQ-7 recommendation. Rejected because (i) the dual-write / dual-read transitional state has its own bug surface (every reader and writer needs a code path that handles "either column may be authoritative"), which is arguably *more* error-prone than a single audited cutover; (ii) two PRs of migration overhead for a foundation step that will see no production-traffic concurrency between PRs; (iii) the 168-test suite + a forward-and-rollback round-trip migration test (T-1.10.8) gives the same regression-catching property without dragging out the cutover; (iv) no SaaS / multi-tenant readers exist yet, so "missed call site discovered after release" is a self-host / dev-machine concern, not a customer-impacting one. Reversibility from a true cutover is preserved by the rollback half of T-1.10.8 — Alembic `downgrade` reinstates the legacy PK.
- *Keep prefixed strings forever* — already rejected in [D-015](#d-015--promote-e-110-uuid-pk-ahead-of-reddit--hn-orchestrator-wiring-2026-04-26).

**Consequences.**
- Single migration PR for E-1.10 — no transitional release.
- T-1.10.8 (round-trip migration test + 168-test suite + e2e smoke on a real existing job) is the safety net against missed call sites among the 14 importers. Treat T-1.10.8 as **gating** — the PR does not merge until both directions of the migration round-trip cleanly and the e2e smoke runs green.
- Pre-merge audit: every reference to `video_id` in `app/services/youtube_service.py`, `app/services/chroma_service.py`, the five LangGraph agents, the routers, the dataset exporters, and the test fixtures gets visited and updated in the same PR. No `video_id` reads survive.
- Database file backup as a manual pre-cutover step (`cp data/videoresearchpro.db data/videoresearchpro.db.pre-e110.bak`) documented in T-1.10.8's runbook so users who self-host can fall back if `downgrade` ever proves insufficient.
- OQ-7 marked resolved with reference to this ADR.

**Linked initiatives / PRs.** I-1 / E-1.10 / D-015 / OQ-7.
