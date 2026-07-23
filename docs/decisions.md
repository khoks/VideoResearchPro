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

---

## D-018 — Polymorphic `<ApprovalCard>` TypeScript shape — four sub-decisions (2026-04-26)

**Status:** accepted. Resolves [OQ-8](initiatives.md#open-questions-parking-lot).

**Context.** [D-016](#d-016--single-polymorphic-approval-card-driven-by-source_metadata-2026-04-26) settled *that* the approval surface is a single polymorphic component dispatched on `source_type` + `source_metadata`. [OQ-8](initiatives.md#open-questions-parking-lot) raised four interrelated implementation questions for the TypeScript shape: where `SourceMetadata` lives in code, how chips reference fields, how formatters work, and how filter chips relate to display chips. This ADR locks all four. The user's overarching framing was *"keep the system a bit open ended for future enhancements and not too strict"* — that bias informs each sub-decision.

**Decisions.**

**(a) `SourceMetadata` is hand-rolled in TypeScript and kept synced with backend Pydantic models by convention.** No build-step generator. PR review enforces drift correction.

**(b) Chip `field` references are `keyof T` — pure source-metadata.** Document-level fields (`title`, `published_at`, `source_url`) are not addressable by chips; they render through fixed slots in `<CardHeader>` (always `document.title`, `document.published_at`) and `<CardActions>` (always `document.source_url`). Only the per-source-unique data — the data that *justifies* a polymorphic component — flows through the chip mechanism.

**(c) Formatters are hybrid: registry by name, callback override.** A small registry of named formatters (`durationSeconds`, `relativeTime`, `signedNumber`, `numberWithCommas`, `truncate`) covers ~80% of cases. A `format?: (v) => string` callback on the chip overrides the registry for one-offs. Both fields optional; callback wins when both are present; default is `String(v)`.

**(d) Filter chips are a separate `FilterChip<T>` type from `MetaChip<T>`.** Each source-type config registers two arrays: `metaChips` (display) and `filterChips` (predicate). A source can register both for the same field, but each has its own type shape.

**Alternatives considered.**

- *(a) Build-step generation from Pydantic JSON schema.* Recommendation in OQ-8. Rejected for being too rigid for a system still finding its abstractions — the open-ended evolution path the user explicitly cited as the priority outweighs the structural drift-prevention benefit. Decision can be revisited when the schema is more stable (post-Mastodon / Bluesky landings) and a build step has higher payoff.
- *(b) Flat `keyof (Document & T)` (recommendation in OQ-8) or namespaced `'document.title' | 'metadata.subreddit'`.* Both rejected. Flat blurs the line between Document-stable fields and source-specific ones — the very distinction the polymorphism is *about*. Namespaced is verbose at every chip declaration and still requires deciding which fields can appear in which namespace. Pure-metadata is the cleanest separation: chips talk about *what's unique to this source*; everything else is a fixed slot in the card primitives.
- *(c) Pure per-chip callback* (no registry) — DRY-loss for the ~6 common cases, no shared idiom. *Pure typed-formatter registry by JS type* — too rigid; can't express "format `score` as signed number when subreddit is r/AskReddit" without a custom callback anyway.
- *(d) Shared `MetaChip<T>` with a `filterable: 'eq' | 'gte' | 'lt' | 'contains'` discriminator.* Recommendation in OQ-8. Rejected because display and filter have genuinely different shapes (display has icon + format; filter has predicate + comparison value), and union-typing them loses clarity. Two arrays of clean types beats one array of polluted types.

**Consequences.**

- TypeScript sketch in [source-types.md § Polymorphic ApprovalCard TypeScript shape](source-types.md#polymorphic-approvalcard-typescript-shape) updated in lockstep: `header` config drops `titleField` / `subtitleField` / `avatarField` (always `document.*`); `MetaChip<T>` adds `formatter?: FormatterName`; new `FilterChip<T>` type and `filterChips: FilterChip<T>[]` field on the config; `customSlot` signature gains a `document: Document` arg.
- `<ApprovalCard>` component signature: `(props: { document: Document; metadata: T; classification?: Classification; config: ApprovalCardConfig<T> })`. `<CardHeader>` and `<CardActions>` read directly from `document`; `<CardBody>` / `<CardMetaRow>` / filter UI read from `metadata` via the typed registry.
- Per-source config size shrinks (no Document-field declarations) and cross-source consistency increases (header layout is structurally identical across all source types).
- Pydantic ↔ TS drift becomes a PR-review concern. If review fatigue kicks in or a fourth or fifth source type lands and the drift count climbs, revisit (a) and consider promoting to a build-step generator.
- Revisit hook for (b): if a future source type genuinely needs chips referencing Document-level fields (e.g. "show chip with `published_at` on the meta row alongside source-specific data"), reopen and consider promoting to flat `View<T>`.
- T-1.5.4.1 (build polymorphic primitive) starts unblocked.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.4 / T-1.5.4.1. Builds on [D-016](#d-016--single-polymorphic-approval-card-driven-by-source_metadata-2026-04-26).

---

## D-019 — CODEOWNERS + branch-protection policy for autonomous-merge sessions (2026-04-26)

**Status:** accepted. Resolves [OQ-9](initiatives.md#open-questions-parking-lot).

**Context.** Mid-session 2026-04-26, master's `required_approving_review_count: 1` blocked autonomous squash-merge of PRs [#85](https://github.com/khoks/VideoResearchPro/pull/85) / [#86](https://github.com/khoks/VideoResearchPro/pull/86), forcing `gh pr merge --admin` to bypass. This conflicts with the user's [`feedback_pr_workflow.md`](https://github.com/khoks/VideoResearchPro) directive to merge autonomously without review pings. [OQ-9](initiatives.md#open-questions-parking-lot) surfaced three resolutions: (a) drop `required_approving_review_count`, (b) keep + accept `--admin` overrides, (c) configure a CODEOWNERS / `bypass_pull_request_allowances` exception. User picked (c).

**Decision.** Adopt a hybrid of (c) and (a) reflecting GitHub's actual capabilities on personal-account free-plan public repos:

1. **Add `.github/CODEOWNERS`** declaring `@khoks` as owner of every path (`* @khoks`). Documents ownership for future automation (auto-assign reviewers, CODEOWNERS-aware templating) and signals owner intent if additional contributors are onboarded.
2. **Drop `required_approving_review_count` to `0`** on master branch protection. The user-as-bypass model (option c proper) requires `bypass_pull_request_allowances` which **is not available** on personal-account free-plan repos — verified via PATCH that silently dropped the field (only org-owned repos and Pro/Team plans expose it). Dropping the count to 0 is the closest available approximation.
3. **Keep all other branch protection rules** unchanged — `enforce_admins: false`, `allow_force_pushes: false`, `dismiss_stale_reviews: false`, `require_last_push_approval: false`, `require_code_owner_reviews: false`.

**Net effect.** Autonomous squash-merge from `gh pr merge --squash --delete-branch` (no `--admin` flag) works again. Force-push to master is still blocked. Future contributors land on master through PRs but don't need approving reviews — review still possible if the user opts in but isn't required.

**Alternatives considered.**
- *(a) Drop the rule, no CODEOWNERS file.* The decision lands here mechanically (since (c) wasn't available) but the CODEOWNERS file adds documentation and forward-compat for free.
- *(b) Keep + `--admin` per merge.* Rejected: every merge produces an "admin override" audit row, which clutters the audit trail with what looks like policy-violations even though they're routine. Cleaner to have no rule than to bypass a rule constantly.
- *(c) `bypass_pull_request_allowances.users = ["khoks"]`.* User's first choice. Rejected as **not available on this plan** — verified via PATCH that silently dropped the field. Would require migrating the repo to an organization, upgrading to GitHub Pro, or switching to GitHub Rulesets (which expose `bypass_actors`). Path not pursued today; documented as a revisit hook below.
- *Use GitHub Rulesets with `bypass_actors`.* The new branch-protection model. Possibly viable on this plan — `GET /repos/.../rulesets` returned `[]` rather than 404, suggesting accessibility. Not pursued today: Rulesets need explicit numeric actor IDs, and the test cycle to validate "blocks contributors but bypasses owner" is more involved than dropping a count to 0. Revisit if a second contributor appears.

**Consequences.**
- `gh pr merge --squash --delete-branch` (no `--admin`) works on master immediately for `@khoks`.
- `feedback_pr_workflow.md` directive ("merge autonomously without review pings") is mechanically satisfied — no friction next session.
- If another contributor joins, their PRs also won't require approving review — that's the security cost of the simplification. Revisit the moment a second collaborator's commit appears.
- CODEOWNERS file at `.github/CODEOWNERS`. Future automation (auto-assign reviewers, etc.) reads from it.
- OQ-9 marked resolved with reference to this ADR.

**Revisit hooks.**
- Second human collaborator joins → re-enable `required_approving_review_count: 1` and configure Rulesets / `bypass_actors` for the autonomous account.
- Repo migrates to an organization or upgrades plan → switch to `bypass_pull_request_allowances.users` (the user-preferred path).

**Linked initiatives / PRs.** I-4 (persistence skills) / OQ-9. References `feedback_pr_workflow.md`.

---

## D-020 — File orchestrator dispatch as standalone Story S-1.5.11 (2026-04-26)

**Status:** accepted. Resolves [OQ-10](initiatives.md#open-questions-parking-lot).

**Context.** Reddit (S-1.5.1) and HN (S-1.5.2) connectors emit `Candidate` objects standalone but `app/tasks/job_tasks.py` does not yet route topic jobs through them. [OQ-10](initiatives.md#open-questions-parking-lot) surfaced this gap during the 2026-04-26 holistic backlog walkthrough. Two resolutions: (a) file as new **S-1.5.11 — Topic-job routing through new connectors**; (b) fold dispatch into T-1.5.1.4 + T-1.5.2.5 storage tasks.

**Decision.** Option (a). File **S-1.5.11** as its own Story under E-1.5, sequenced after S-1.5.5 and ahead of Mastodon / Bluesky. The dispatcher abstraction lives in either `app/tasks/job_tasks.py` directly or factored into a new `app/services/connector_dispatch.py` (implementation detail; punt to S-1.5.11 design).

**Alternatives considered.**
- *(b) Fold into T-1.5.1.4 + T-1.5.2.5.* Faster to MVP but duplicates the dispatch pattern across N future connectors (Mastodon, Bluesky, Mode B paste, podcasts, PDFs). Each connector landing would re-implement the routing wiring. Rejected.
- *Land dispatch invisibly inside the orchestrator core, no Story.* The work happens, but it's invisible to progress tracking, not enumerated in `initiatives.md`, and a future contributor would re-discover the gap. Rejected.

**Consequences.**
- The dispatch layer ships **once** with the first two consumers (Reddit + HN); reused unchanged by every future connector.
- T-1.5.1.4 / T-1.5.2.5 stay scoped to "insert candidates into `documents`"; they consume the dispatch layer rather than re-implementing it.
- S-1.5.11 acceptance includes: `dispatch_by_source_type(source_type, candidate)` mechanism, per-source-type rate-limit + retry config externalized so each connector declares its own constraints, fan-out semantics for jobs that mix `source_types=["video","reddit_post","hn_story"]` (round-robin vs parallel — punted to S-1.5.11 design), progress reporting parity with the existing YouTube path.
- E-1.10 (UUID PK) is still a hard prerequisite of T-1.5.1.4 / T-1.5.2.5 storage tasks; S-1.5.11 dispatch can begin building independently but its e2e tests need the storage tasks to land.
- OQ-10 marked resolved.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.11 (filed in lockstep). References T-1.5.1.4, T-1.5.2.5.

---

## D-021 — Topic relevance threshold = 0.50 (2026-04-26)

**Status:** accepted. Resolves [OQ-1](initiatives.md#open-questions-parking-lot).

**Context.** [D-007](#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25) introduced `social_classify_stance` returning `topic_relevance: float ∈ [0, 1]` alongside stance / sentiment / framing. [OQ-1](initiatives.md#open-questions-parking-lot) parked the question of *threshold* — at what score does a candidate get filtered vs surfaced as low-confidence? Without a threshold, every fetched candidate (including drift / off-topic / spam matches the search API surfaced incidentally) flows into the approval list, drowning the user in noise. With too aggressive a threshold, borderline-relevant items the user might want to see get hidden.

**Decision.** **`TOPIC_RELEVANCE_THRESHOLD = 0.50`**. Candidates with `topic_relevance < 0.50` are excluded from default approval-list rendering. The user can opt in to seeing them via a filter chip ("Show low-relevance candidates"). Filtered candidates are **not deleted** — they remain in `documents` with their classification intact, just hidden by default in the UI.

**Alternatives considered.**
- *Higher threshold (0.7 / 0.8).* Skips too many borderline-relevant items. The classifier is `gpt-4.1-mini`-grade (cheap-and-fast, not surgical); a conservative cutoff produces too many false negatives, especially for niche-vocabulary topics where the classifier under-confidence-penalizes legit matches.
- *Lower threshold (0.3).* Surfaces too much off-topic noise; defeats the filter's purpose. Reddit / HN topic searches notoriously include drift hits that score in the 0.2–0.4 band.
- *No threshold (surface all with confidence badge).* Punts the noise problem to user attention. Explicitly counter to the curation-as-product thesis. The user gets the badge information *and* the filter so they can drill into low-confidence items selectively but not by default.
- *Per-source-type thresholds.* Reddit / HN / Mastodon may have different noise profiles. Rejected for v1: introduces complexity without empirical evidence it matters; one threshold lets us measure noise empirically and add per-source overrides later if data warrants.
- *Adaptive threshold based on query specificity.* Overkill for v1; revisit only if data shows static cutoff misperforms.

**Consequences.**
- Threshold lives as a constant in the social-classify module (e.g. `app/services/social_classify.py::TOPIC_RELEVANCE_THRESHOLD = 0.50`). Easy to tune as data accumulates.
- The classifier prompt (T-1.5.3.6) instructs the LLM to rate `topic_relevance` ∈ [0, 1] using calibrated scoring (1.0 = unambiguously on-topic, 0.5 = adjacent, 0.0 = unrelated). Exemplars in the prompt include borderline cases at the 0.4–0.6 band so the threshold maps to a sensible cut.
- Approval UI default filter applies `topic_relevance >= 0.50`; "Show low-relevance candidates" filter chip toggles the cutoff to 0.0.
- S-1.5.3 acceptance updated to include the threshold + default-filter behavior; S-1.5.4 acceptance gains the "Show low-relevance candidates" filter chip.
- Re-evaluation hook: if observed precision is too low (lots of 0.5+ matches that turn out off-topic on inspection), bump to 0.60 globally; if observed recall is too low (genuine matches scored 0.4 / 0.45), drop to 0.40 globally. Per-source-type override is the next escalation.
- OQ-1 marked resolved.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.3 / S-1.5.4. Builds on [D-007](#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25), [D-014](#d-014--add-framing-axis-to-social_classify_stance-schema-2026-04-26).

---

## D-022 — Astro for the marketing landing page (2026-04-28)

**Status:** accepted.

**Context.** [E-2.5](initiatives.md#e-25-marketing-landing-page-warm-editorial) needed a static-site stack for the marketing landing page (hero / curation thesis / source-types matrix / how-it-works / install / SaaS waitlist). The site is **explicitly separate** from the React product app under `frontend/` — different audience, different deploy target, no shared runtime — so the choice is unconstrained by the existing React-Vite stack.

Four candidates: **Astro**, **Next.js**, **11ty**, **plain HTML+CSS**.

**Decision.** **Astro** (^5.0.0) under a new top-level `marketing/` directory with its own `node_modules`, `package.json`, and build pipeline. Scaffold landed in PR [#98](https://github.com/khoks/VideoResearchPro/pull/98).

**Alternatives considered.**
- *Next.js.* Overkill for a static marketing site. Biases the codebase toward React-first thinking even though the marketing copy has zero React state. Heavier bundle, more config, more dependencies. The interactivity Next is good for (server components, dynamic routes, ISR) is irrelevant here.
- *11ty.* Viable. Mature, fast static-site generator. Rejected because the file-as-component DX (`.eleventy.js` data layers + Nunjucks/Liquid templating) is more friction than Astro's `.astro` files where TypeScript + components + scoped CSS coexist in a single file. Personal-preference call; reasonable engineers could pick 11ty.
- *Plain HTML + CSS.* Considered for the scaffold-only stage. Rejected because future sections (source-types matrix, install instructions across platforms, recurring footer / nav) want layout / partial / content-collection abstractions. Hand-writing those without a static-site framework means reinventing the wheel.
- *Folding into `frontend/` as a separate Vite entry point.* Rejected because (i) the marketing site's deploy target (static-only host like Netlify / Vercel / GitHub Pages / Cloudflare Pages) differs from the product app (which needs the FastAPI backend); (ii) coupling dependency trees forces marketing-side upgrades to revalidate against the product app and vice versa; (iii) the conceptual separation ("marketing copy vs the product") is clearer when the directories live separately.

**Why Astro wins on this surface:**
- **Zero JS by default.** Marketing pages ship as plain HTML; JS only loads when an island opts in (e.g. the eventual SaaS waitlist signup form).
- **Components-as-files DX.** `.astro` files combine frontmatter (TypeScript / data fetching), template (HTML + components), and scoped `<style>` in one place.
- **First-class Markdown / MDX.** The "different from Wikipedia" thesis and "how it works" walkthroughs can live as `.md` files that page templates import — clean separation of copy from layout.
- **Static output to `dist/`** deployable anywhere without a Node runtime.
- **Multi-page abstractions** (layouts, content collections, automatic `<link rel="canonical">`, sitemap generation) work out-of-the-box.
- **TypeScript-strict tsconfig** in the scaffold (`extends: "astro/tsconfigs/strict"`).

**Consequences.**
- New top-level directory `marketing/` with its own dependency tree. Independent of `frontend/`.
- Warm-editorial tokens mirrored from `frontend/src/theme.ts` into `marketing/src/layouts/BaseLayout.astro` (canonical token table is `docs/branding.md`; both consumers read from there). PR review catches drift. A future T-2.5.x could export a shared `@pratidhvani/tokens` workspace package, but a workspace setup for two consumers is premature; revisit if a third consumer appears.
- Google Fonts (Fraunces / Source Serif 4 / Inter / Tiro Devanagari Hindi) load via CDN preconnect in BaseLayout; the product app uses the same fonts, so users see coherent typography across product + marketing.
- Deploy target: static-only host. The eventual SaaS landing page reuses this infrastructure as-is; SaaS-specific surfaces (login / billing portal / status page) become separate Astro routes or separate sub-sites.

**Revisit hooks.**
- If marketing acquires substantial dynamic surfaces (live stats counters, OAuth-gated demos, multi-step interactive walkthroughs), reconsider Next.js — Astro can do islands but at scale Next's server-component model becomes more idiomatic.
- If the product app's React stack needs to share rendered components with marketing (e.g. a live-embed of the approval card), introduce a shared package and decide whether marketing consumes React via Astro's `@astrojs/react` integration or whether the product moves to Astro+React itself.

**Linked initiatives / PRs.** I-2 / E-2.5 / T-2.5.1. PR [#98](https://github.com/khoks/VideoResearchPro/pull/98) (initial scaffold).

---

## D-023 — `social_classify_stance` invoked inline inside each connector (2026-04-28)

**Status:** accepted. Resolves [OQ-12](initiatives.md#open-questions-parking-lot).

**Context.** [D-007](#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25) introduced `social_classify_stance` to run at fetch time. [D-014](#d-014--add-framing-axis-to-social_classify_stance-schema-2026-04-26) added the `framing` axis. [D-021](#d-021--topic-relevance-threshold--050-2026-04-26) set the surfacing threshold to 0.50. None of these specified *where in the codebase* the classifier gets called. [OQ-12](initiatives.md#open-questions-parking-lot) surfaced two natural placements: **(a)** inline inside each connector's `fetch_text()` / `fetch_metadata()` so each connector classifies before returning Candidates; **(b)** as a separate orchestrator pipeline step that runs after the connector returns and before persistence.

**Decision.** Option (a) — inline inside each connector. Each `BaseConnector` subclass (`RedditConnector`, `HNConnector`, future `MastodonConnector` / `BlueskyConnector`) calls `social_classify` on the text it just fetched, before returning the `Candidate`. The classification result lands on `Candidate.classification` (or, equivalently, on `source_metadata.{stance,sentiment,framing,topic_relevance}` if Candidates pass `source_metadata` directly).

**Alternatives considered.**
- *(b) Orchestrator pipeline step.* Cleaner separation of concerns (connector fetches, orchestrator classifies, storage persists). Rejected because: (i) classification cost is per-Candidate and the per-source-type call counts vary widely (Reddit returns hundreds of comments per thread; HN returns a flat story), so connectors are the natural batching boundary; (ii) connectors know the *right text to classify* — Reddit might classify "OP + top-comment summary" while Mastodon-OP-only classifies just the post body, while HN classifies "story + top-comment" — that knowledge lives in connector code, not orchestrator code; (iii) orchestrator stays focused on its core concern (fan-out + progress reporting + retry); (iv) parallelizable across connectors when fan-out is parallel.
- *Hybrid* — connector returns un-classified Candidates, orchestrator classifies, but optionally a connector can pre-classify if it has a cheap path. Rejected as over-engineered for v1; if the layering matters later the inline path is trivially refactorable into a hybrid.

**Consequences.**
- Each connector imports and calls `social_classify` from `app/services/social_classify.py`. Cost is amortized inside the connector's per-Candidate loop.
- Connector tests grow to assert classification fields populate on returned Candidates (mocked classifier in unit tests).
- The classifier function itself stays connector-agnostic — same signature regardless of source type.
- T-1.5.3.3 acceptance updates: "Wire into the social-connector ingest path" → "Inline call inside `RedditConnector.fetch_text()` and `HNConnector.fetch_text()` (and future connectors). Each connector calls `social_classify(text, query)` and attaches the result to the returned Candidate."
- OQ-12 marked resolved.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.3 / T-1.5.3.3. Builds on [D-007](#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25), [D-014](#d-014--add-framing-axis-to-social_classify_stance-schema-2026-04-26), [D-021](#d-021--topic-relevance-threshold--050-2026-04-26).

---

## D-024 — Flip E-1.6 to 🔵 with primitives-only scope split (2026-04-28)

**Status:** accepted. Resolves [OQ-14](initiatives.md#open-questions-parking-lot). Amends [D-005](#d-005--social-media-ingest-before-article-ingest-2026-04-25).

**Context.** [D-005](#d-005--social-media-ingest-before-article-ingest-2026-04-25) deferred the article connector (E-1.6) behind E-1.5 (social-media connectors). At the time, the assumption was the article connector and the social work were independent enough that ordering them sequentially saved attention. The 2026-04-28 holistic-backlog review revealed the trafilatura + Playwright fallback **pipeline primitives** that E-1.6 builds are also on the dependency path of S-1.5.8 (Mode B paste mode for FB/IG/LI/X-without-paid-API): both surfaces hit arbitrary HTML pages, extract clean text with trafilatura, and fall back to Playwright when trafilatura fails on JS-heavy SPA platforms. Building those primitives twice (once in S-1.5.8, then again — or factored differently — in E-1.6) is wasteful.

**Decision.** Flip E-1.6 from 🔴 deferred to 🔵 accepted, with **scope split**: the *pipeline primitives* (trafilatura wrapper, Playwright fallback, hybrid extraction strategy, language detection, word-count gating) ship first as a lightweight foundation under `app/services/article_extraction/` (or similar). The full article-connector UX (job submission flow that takes `source_types=["article"]`, RSS feed ingestion, search via Brave / Kagi / Tavily, approval card variant for articles) stays deferred until after the Reddit + HN end-to-end MVP (M-1.5).

**Alternatives considered.**
- *(a) Keep 🔴 deferred (status quo).* The deferral was deliberate per D-005 to focus attention on social MVP. Rejected because the primitive-duplication cost is real — S-1.5.8 needs the same primitives, so they get built somewhere either way.
- *(c) Flip to 🔵 with full scope (article connector + Mode B share the primitives).* Rejected because the full article-connector UX (RSS, search, approval card variant) adds in-flight surface area that distracts from the M-1.5 critical path. Recommendation (b) — primitives only, defer UX — gets the durable foundation in place without committing to the user-facing surface yet.

**Consequences.**
- E-1.6 status flips 🔴 → 🔵 in initiatives.md. Sub-tasks split into "T-1.6.1 — pipeline primitives (high priority, in service of S-1.5.8)" and "T-1.6.2+ — full article connector UX (post-M-1.5)".
- S-1.5.8 (Manual-paste mode) acceptance updated to reference E-1.6 T-1.6.1 as the dependency rather than reusing-from-the-future.
- The primitives module is intentionally connector-agnostic — `extract_text(url) -> ExtractionResult` — so the article connector and Mode B paste consume the same code.
- The decision is reversible: if M-1.5 takes longer than expected, E-1.6's primitives-only scope can be put back on the shelf without touching S-1.5.8 (which can absorb the trafilatura/Playwright code inline temporarily).

**Linked initiatives / PRs.** I-1 / E-1.6 / S-1.5.8. Amends [D-005](#d-005--social-media-ingest-before-article-ingest-2026-04-25).

---

## D-025 — File MVP definition-of-done as Milestone M-1.5 (2026-04-28)

**Status:** accepted. Resolves [OQ-15](initiatives.md#open-questions-parking-lot).

**Context.** Six in-flight stories (E-1.10, S-1.5.3, S-1.5.4, S-1.5.5, S-1.5.11, plus T-1.5.1.4 / T-1.5.2.5 unblocked by E-1.10) form the critical path to "Reddit + HN end-to-end ingest." Without an explicit milestone the work-tracker has no single convergence target — each story can claim to be "ready" by its own acceptance, but there's no test of whether the *user-facing experience* is end-to-end working.

**Decision.** File **Milestone M-1.5 — Reddit + HN end-to-end ingest** under E-1.5 with the following definition-of-done:

> A user submits a topic job with `source_types=['reddit_post','hn_story']`, sees a curated approval list with **stance / sentiment / framing badges + filter chips** (including the `topic_relevance >= 0.50` default per [D-021](#d-021--topic-relevance-threshold--050-2026-04-26) and the "Show low-relevance candidates" toggle), approves a subset, and asks Q&A across the approved threads receiving **comment-anchored citations** (per the `permalink#comment-<id>` format defined in [D-006](#d-006--one-document-row-per-social-post-thread-not-per-comment-2026-04-25)).

**Component checks for M-1.5 closure:**
1. E-1.10 cutover landed (UUID `document_id` PK + `source_id text` columns).
2. S-1.5.11 dispatcher routes topic-job source-type lists through the connector registry.
3. T-1.5.1.4 + T-1.5.2.5 storage tasks land Reddit / HN Candidates as `documents` rows.
4. S-1.5.3 inline classifier (per [D-023](#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28)) populates stance / sentiment / framing / topic_relevance.
5. S-1.5.4 polymorphic `<ApprovalCard>` renders Reddit + HN config entries with badges + filter chips.
6. S-1.5.5 citation rendering produces Reddit / HN deep-links.
7. End-to-end pipeline test passes for `["reddit_post"]`, `["hn_story"]`, and mixed `["video","reddit_post","hn_story"]`.

**Alternatives considered.**
- *Keep critical-path informal.* Rejected: gives no convergence test; risks "all stories shipped, but the user experience is still broken."
- *Define M-1.5 narrower (just Reddit, defer HN).* Rejected: HN is essentially free once Reddit ships (Algolia API needs no auth, comment-tree shape mirrors Reddit per the existing connector code), and a milestone without HN doesn't capture the meaningful "two source types in parallel" threshold.
- *Define M-1.5 broader (include Mastodon / Bluesky).* Rejected: those need their own connectors which haven't shipped; folding them into M-1.5 inflates scope past where the trade-off is worth it.

**Consequences.**
- initiatives.md gains a "Milestones" section (or M-1.5 lives inline under E-1.5) tracking the 7 component checks above. Each component check links to the closing PR or shipped task.
- "M-1.5" becomes the shorthand for the convergence target; sub-stories can quote progress relative to M-1.5 ("3/7 component checks closed", etc.).
- Future milestones — M-1.7 (podcast end-to-end), M-1.8 (PDF end-to-end), M-2.5 (marketing landing page deployed) — follow the same template.
- OQ-15 marked resolved.

**Linked initiatives / PRs.** I-1 / E-1.5 / E-1.10 / S-1.5.3 / S-1.5.4 / S-1.5.5 / S-1.5.11 / T-1.5.1.4 / T-1.5.2.5.

---

## D-026 — Sequential fan-out for the connector dispatcher (2026-05-02)

**Status:** accepted. Resolves [T-1.5.11.3](initiatives.md#s-1511-topic-job-routing-through-new-connectors).

**Context.** T-1.5.11.3 ("Fan-out semantics for mixed-source jobs") was filed when [S-1.5.11](initiatives.md#s-1511-topic-job-routing-through-new-connectors) was scoped, with two candidate shapes for how `dispatch_search()` should iterate `source_types` when a topic job spans multiple connectors:

- **(a) Round-robin** — one source-type at a time, smaller bursts. Bounds peak load on any individual provider; adds slight bookkeeping.
- **(b) Parallel** — every source-type's `connector.search()` kicks off concurrently via `asyncio.gather` (or thread-pool). Total latency tracks the slowest source rather than the sum.

Initial OQ-15 plan recommendation was (b) parallel.

**Decision.** **Sequential** for v1: each `source_type`'s `connector.search()` runs in turn, with the next starting only after the previous returns or errors. This is what shipped in PR [#109](https://github.com/khoks/VideoResearchPro/pull/109)'s `dispatch_search()` implementation and PR [#116](https://github.com/khoks/VideoResearchPro/pull/116)'s `execute_topic_job` integration. Total latency = sum of per-source latencies.

**Alternatives considered.**
- *(b) Parallel via asyncio.gather.* Better latency at scale, but adds genuine complexity for v1: (i) async-context plumbing through `execute_topic_job` (currently a synchronous Celery task); (ii) per-connector exception isolation across simultaneous calls (we already have it sequentially via `try/except` per source — would need careful gather-with-return-exceptions); (iii) partial-result semantics (one connector finishing fast and another timing out — what does the user see?); (iv) rate-limit coordination across simultaneous outbound calls (RedditClient's 100 rpm budget shouldn't be split unevenly across parallel sources). At M-1.5 scale (3 source types × ~10 candidates each), expected latency saving is ~1-3 seconds; not worth the complexity.
- *(a) Round-robin.* No meaningful advantage over sequential at v1 scale. Round-robin shines when individual sources can return many candidates and you want fairness; with `limit_per_type=10` per source, sequential is essentially indistinguishable in user-visible behavior.
- *Hybrid (sequential per-job, parallel inside hot connectors).* Over-engineered for v1.

**Consequences.**
- Each per-source-type request runs in its own try-except so one connector's outage doesn't block the others (shipped in PR #109).
- Connector-internal rate limits (RedditClient's 100 rpm, HN Algolia's free tier) operate independently per source — sequential dispatch never causes rate-limit collisions.
- Total latency is bounded by `sum(per-source latencies)`. For Reddit (~1-2s search) + HN Algolia (~0.3-0.5s) + future Mastodon (~1s) + Bluesky (~1s), worst case is ~5s for a 4-source job. Acceptable for self-host; SaaS-tier may revisit when concurrent load matters.
- Initiatives.md task `T-1.5.11.3` flips ✅ closed with this decision recorded inline.

**Re-evaluation hooks.**
- Switch to **parallel** if/when:
  - More than 4 source types are routinely requested in a single topic job AND user-perceived latency exceeds ~5s for a normal search.
  - SaaS tier hosts concurrent users with overlapping multi-source queries (ratelimit-aware parallel becomes important for fairness).
  - We add a connector with materially slow search (e.g. paid Twitter API at ~3-5s/query) where its sequential cost dominates.
- Switch to **round-robin** only if a connector lifts its rate-limit cap and `limit_per_type` grows past ~50, where fairness across sources starts to matter.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.11 / T-1.5.11.3. PRs [#109](https://github.com/khoks/VideoResearchPro/pull/109), [#116](https://github.com/khoks/VideoResearchPro/pull/116).

---

## D-027 — Mastodon discovery uses the public hashtag timeline (no auth, single-hashtag normalisation) (2026-05-03)

**Status:** accepted. Resolves the discovery question for [S-1.5.6](initiatives.md#s-156-mastodon-connector) and shipped with PR [#128](https://github.com/khoks/VideoResearchPro/pull/128).

**Context.** Mastodon disables full-text search by default on most instances to honour user privacy. The original S-1.5.6 acceptance criterion ("ActivityPub search + thread fetch") didn't pin down which discovery surface to use. Three candidate paths existed:

1. **Public hashtag timeline** — `GET /api/v1/timelines/tag/<hashtag>` is open on every instance, federates across the network, requires no auth.
2. **Per-instance authenticated full-text search** — only available where the instance operator has explicitly enabled it; needs OAuth + per-instance credentials, fragmenting the connector.
3. **Profile-page HTML scraping** — fast to ship but brittle, against ToS, and the per-IP rate-limiter would catch it.

A topic-search query like *"climate change"* must reduce to a single hashtag because Mastodon hashtags don't accept spaces or punctuation.

**Decision.** Use **(1) the public hashtag timeline**. Topic queries are normalised to a single alphanumeric hashtag — lowercased, with everything outside Unicode `L*` (Letter), `N*` (Number), and `M*` (Mark) categories stripped. The default instance is `mastodon.social`; self-hosters can override via `MASTODON_INSTANCE_BASE`.

**Alternatives considered.**
- *(2) Per-instance authenticated full-text search.* Rejected — fragments the connector across instances; most public instances don't expose it; auth complicates the no-credentials promise that distinguishes Mastodon from Reddit/Twitter ingest.
- *(3) HTML scraping of `/explore/posts` or profile pages.* Rejected — brittle, ToS-violating, and doesn't add reach beyond what hashtag federation already provides.
- *Multi-hashtag splitting* — break "climate change" into `#climate` + `#change`, run two timelines, merge. Rejected because Mastodon hashtag conventions are single-token (`#climatechange`), so the multi-hashtag form returns posts about *change* unrelated to *climate*. The single-token concatenation reproduces user behaviour on the platform.

**Consequences.**
- Discovery is hashtag-only. A topic that doesn't survive normalisation (pure punctuation, empty after stripping) returns zero candidates rather than calling the timeline endpoint with a bad path. Caller treats that as "no results, skip this source" rather than an error.
- **Combining-mark support is load-bearing.** Devanagari `ि` / `्`, Arabic `ـ`, Thai vowel marks all fail `str.isalnum()` (which only checks `L` + `N` categories). The `unicodedata.category(ch)[0] in ("L", "N", "M")` rule preserves them, which is what Mastodon's own hashtag parser does. Without this, Hindi/Marathi/Bengali queries get mangled (`परिवर्तन` → `परवरतन`).
- No per-instance auth means no token plumbing, no 401-retry loops, no credential rotation. The connector lifecycle is dead-simple.
- The hashtag normalisation function (`_topic_to_hashtag`) is connector-local; future connectors with similar topic-to-tag mappings (Bluesky tags, `forum_post`-shaped sources) can copy or share it.

**Re-evaluation hooks.**
- If user feedback shows hashtag-only discovery misses important non-tagged posts (a real Mastodon failure mode), revisit (2) for instances where the operator has enabled full-text search — it can be added as a second discovery path that runs alongside hashtag-timeline rather than replacing it.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.6 / M-1.6. PR [#128](https://github.com/khoks/VideoResearchPro/pull/128).

---

## D-028 — Bluesky uses public unauthenticated AT-Proto XRPC (deviation from S-1.5.7 spec) (2026-05-03)

**Status:** accepted. Resolves the auth question for [S-1.5.7](initiatives.md#s-157-bluesky-connector) and shipped with PR [#129](https://github.com/khoks/VideoResearchPro/pull/129).

**Context.** S-1.5.7 was originally specced as *"AT-Protocol search + thread fetch. App password auth."* — under the assumption that Bluesky required an app password for ingest. While building the connector we verified that Bluesky exposes its public read endpoints (`searchPosts`, `getPostThread`, `getProfile`, `getAuthorFeed`) at `https://public.api.bsky.app/xrpc/` **without auth**. App-password auth is required only for *writes* (posting / liking / following) and for higher-throughput PDS-direct reads.

**Decision.** Ship the connector against the public unauthenticated XRPC base. Configure via `BLUESKY_XRPC_BASE` so operators running a private PDS or who later need higher throughput can swap to an authenticated endpoint by setting that var (and adding a token-fetching path in the client at that point).

**Alternatives considered.**
- *App-password auth from the start, as originally specced.* Rejected for v1 — adds key management (rotation, storage, leak handling), a 401-retry path, and per-user vs. per-app-password rate-limit accounting. None of this is needed for ingest of public posts. We'd be paying complexity for a feature we may never use.
- *Defer the connector until app-password auth is justified.* Rejected — it would have blocked M-1.6 closure and left the polymorphic-plumbing-validates-without-changes claim unproven. The session goal was to validate that claim across two connectors back-to-back; postponing one for a non-load-bearing auth concern would lose the validation event.

**Consequences.**
- No credentials to manage. Frees us to ship Bluesky on the same day as Mastodon without a credential-onboarding flow.
- If Bluesky tightens public-endpoint rate limits in the future, the migration path is one env-var swap + adding a token fetcher to `client.py`. The rest of the connector (search/list/metadata/text wiring, flatten, classifier integration) is unchanged.
- The doc trail (S-1.5.7 in `initiatives.md`) called out the deviation explicitly so future readers understand why the spec said one thing and the code did another.

**Re-evaluation hooks.**
- Switch to authenticated PDS endpoint if (a) public-endpoint rate limits start materially constraining ingest throughput, or (b) Bluesky deprecates the public unauthenticated read path.
- If we ever ingest *private* (auth-protected) posts — which is out of scope today and may stay out of scope per the curated-but-public-content thesis — auth becomes mandatory.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.7 / M-1.6. PR [#129](https://github.com/khoks/VideoResearchPro/pull/129).

---

## D-029 — Bluesky `source_id` is the AT-URI, not the bsky.app web URL (2026-05-03)

**Status:** accepted. Shipped with PR [#129](https://github.com/khoks/VideoResearchPro/pull/129).

**Context.** Every Bluesky post has two parallel identifiers:

- **AT-URI** — `at://did:plc:abc.../app.bsky.feed.post/<rkey>`. Built from the *DID* (a permanent, opaque identifier the user can't change) plus a stable record key.
- **bsky.app web URL** — `https://bsky.app/profile/<handle>/post/<rkey>`. Built from the user's *handle*, which is mutable: users rename, change domains, or migrate instances.

Both round-trip into `getPostThread` (the API accepts either form), so either could serve as the connector's `Candidate.source_id`. But the L1 schema's deduplication relies on `(source_type, source_id)` being **stable** — if a handle changes after we ingest a post, a web-URL-based `source_id` would silently de-duplicate wrong on a future re-ingest of the same post.

**Decision.** Use the **AT-URI** as `Candidate.source_id` (namespaced as `bluesky:at://did:plc:.../app.bsky.feed.post/<rkey>`). The bsky.app web URL goes into `Candidate.source_url` for browser-friendly citations.

**Alternatives considered.**
- *bsky.app web URL as `source_id`.* Rejected — handle renames silently break dedup, and the L1 unique-index promise (`(source_type, source_id)` is stable) would no longer hold for Bluesky rows.
- *Post `cid` (content hash) as `source_id`.* Rejected — `cid` is content-addressable, which means edited posts get a new `cid`. We want one Document row per post regardless of edit history; `cid` would create new rows on edit, defeating dedup.
- *Bare `<rkey>` as `source_id`.* Rejected — rkeys are scoped to the author's repo, so two different authors can have the same rkey. Without the DID prefix, the namespace collides.

**Consequences.**
- AT-URIs are opaque to users (a long string with `did:plc:` + base-32 rkey). The connector compensates by always populating `Candidate.source_url` with the human-readable web URL, and by building `source_url` deterministically from the post's `author.handle` + AT-URI's rkey rather than relying on whatever the post payload happens to ship.
- Per-reply `comment_id` carries the *reply's* AT-URI (not the OP's) and `comment_url` carries the *reply's* bsky.app web URL — consistent with the reply-anchor pattern we use elsewhere.
- If a user renames, future ingests of their posts will keep producing the same `source_id` for the same posts (dedup holds), but the citations that point at *old* posts may show outdated `source_url` web URLs (which Bluesky redirects from the old handle to the new). Acceptable — citation hygiene, not dedup correctness.

**Re-evaluation hooks.**
- If we add reverse-lookup features (citation → post-id roundtrip from clipboard or shared links), we may want a content-addressable index on `cid` alongside `source_id` to handle the shared-link case where users have only the web URL.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.7. PR [#129](https://github.com/khoks/VideoResearchPro/pull/129).

---

## D-030 — Backend reference enrichment ships per-document polymorphic Chroma metadata first; per-segment (`comment_id`/`comment_url`) deferred (2026-05-03)

**Status:** accepted. Shipped with PR [#131](https://github.com/khoks/VideoResearchPro/pull/131).

**Context.** After M-1.6 closed, the polymorphic citation pipeline had a producer/consumer mismatch in production:

- **Frontend (consumer)** was renderer-complete since [PR #117](https://github.com/khoks/VideoResearchPro/pull/117) and PRs [#127](https://github.com/khoks/VideoResearchPro/pull/127)/[#128](https://github.com/khoks/VideoResearchPro/pull/128)/[#129](https://github.com/khoks/VideoResearchPro/pull/129). `<CitationLink>` dispatches by `source_type` and reads `permalink`, `author`, `subreddit`, `instance`.
- **Backend (producer)** was still writing only YouTube-shaped metadata to Chroma. `chunk_transcript()` had hardcoded `video_id`/`video_title`/`channel_name`/`video_url`/etc., dropping every polymorphic field on the floor. So in production, `_chunk_to_reference` always saw a metadata block without `source_type` and fell through to the YouTube default branch — even for Reddit/HN/Mastodon/Bluesky chunks that *had* the right `source_type` on the Document row.

Two ways to close the gap:

1. **Per-document fields only** — thread `source_type`, `source_id`, `source_url`, `permalink`, `author`, `subreddit`, `instance` (lifted from `Document.source_metadata_json`) through `_build_video_metadata()` → `chunk_transcript()` → Chroma. Citations link to **OP-level** URLs (`https://www.reddit.com/r/sub/comments/abc`, `https://news.ycombinator.com/item?id=42000`, etc.).
2. **Per-document AND per-segment fields** — additionally preserve each segment's `extra` block (`comment_id`, `comment_url`) through sentence-expansion and greedy-pack so a chunk citing a *specific reply* deep-links to that reply (e.g. `#comment-<id>` for Reddit, the per-status URL for Mastodon/Bluesky, the per-item endpoint for HN).

**Decision.** Ship **(1) per-document only**. Per-segment propagation is filed as the highest-value M-1.5/M-1.6 polish-backlog item.

**Alternatives considered.**
- *(2) Both layers in a single PR.* Rejected for now. Per-segment requires a structural change to `chunk_transcript()`: today it strips segments to bare `(text, start, end)` 3-tuples at line ~94 (losing the `extra` dict), then runs sentence-expansion + greedy-packing on the tuples. To preserve per-segment metadata we'd need to keep `extra` alongside each tuple through expansion + packing, then collapse a chunk's segments down to a representative reply when assigning chunk-level metadata (dominant-segment heuristic, or first-segment, or empty when a chunk straddles multiple replies). That's a meaningful refactor on a hot path with timestamp-arithmetic invariants the existing tests pin. Worth shipping carefully on its own.
- *Defer the whole thing until per-segment is ready.* Rejected. Per-document fields alone deliver the 80% production win — every social-media citation now renders with proper labels and links to the OP page, which is what users actually see when they click a citation. Per-segment is a refinement (jump to specific reply) layered on top of working OP-level citations, not a prerequisite for them. Shipping (1) immediately means Reddit/HN/Mastodon/Bluesky citations stop rendering as YouTube fallback in production today, instead of waiting for the chunker rework.

**Consequences.**
- Production citations across all five source types (`video` / `reddit_post` / `hn_story` / `mastodon_post` / `bluesky_post`) now render via their dedicated `_chunk_to_reference` branches with correct labels and OP-level permalinks.
- Reply-anchor citations (Reddit `#comment-<id>`, HN per-item, Mastodon per-reply status URL, Bluesky per-reply web URL) **do not work yet** for chunks read out of Chroma. The connector flatten layer still emits `comment_id` and `comment_url` in each segment's `extra` block — that data is now wasted at the chunking boundary, where it's stripped. This is acceptable because the OP-level citation always lands the user on the right thread; the per-reply jump is convenience, not correctness.
- `_build_video_metadata()` is now the choke point for per-document polymorphic field lifting. New source types just need to populate the right keys in `Document.source_metadata_json`; the helper handles the rest. This locks in the contract for the upcoming M-1.7 podcast connector and any further social-media surfaces.
- Legacy chunks already in Chroma (written before this PR) keep working — `_chunk_to_reference` falls back to the YouTube branch when `source_type` is missing from metadata, which is the right behaviour for those legacy rows since they're all `source_type='video'`. No backfill needed.

**Re-evaluation hooks.**
- Ship per-segment when (a) we observe materially different reply quality across multiple replies of the same thread getting cited (so jumping to specific reply matters), or (b) a future connector emits content where the per-reply identity is the citable unit (e.g. forum threads with multiple long top-level posts, podcast chapter markers).
- The chunker rework is also the natural moment to revisit pseudo-timestamp synthesis ([D-013](#d-013--pseudo-timestamps-at-3-wps-as-a-shared-cross-source-constant-2026-04-26)) — they could be replaced with explicit per-segment indices once `extra` is preserved.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.5 (frontend half shipped earlier). PR [#131](https://github.com/khoks/VideoResearchPro/pull/131). M-1.5 polish backlog item *Backend reference enrichment* — per-document layer ✅; per-segment layer remains open as a follow-up.

---

## D-031 — Dominant-segment heuristic for chunk-metadata promotion (2026-05-03)

**Status:** accepted. Resolves [T-1.5.12.2](initiatives.md#s-1512-backend-reference-enrichment) and shipped with PR [#134](https://github.com/khoks/VideoResearchPro/pull/134).

**Context.** The per-segment chunker rework had to decide *which* segment's per-reply identity (`comment_id` / `comment_url` / `author` / `kind` / `depth`) to promote to chunk-level Chroma metadata when a chunk contains segments from multiple replies. This happens in two scenarios:

1. **Overlap stitching.** The greedy chunk-packer's overlap window deliberately stitches the tail of one chunk's segments onto the head of the next, so a chunk straddling a reply boundary is the *intended* outcome of the overlap mechanism. (Without overlap, retrieval continuity across chunk boundaries breaks down — that's why we have it.)
2. **End-of-buffer flush.** The final chunk before flush can include the last segment of one reply plus the first segment of the next.

When the chunk's segments come from a single reply, the choice is trivial — promote that reply's identity. When they come from multiple replies, four candidate strategies:

- **(a) First-segment.** Promote the first segment's identity. Simplest, but systematically mis-attributes citations to short top-line replies in a straddling chunk.
- **(b) Last-segment.** Symmetric to (a); same problem in reverse.
- **(c) Most-tokens (dominant).** Pick the segment in the chunk with the highest token count.
- **(d) Suppress (no promotion when straddling).** Empty out `comment_id` / `comment_url` for any chunk that straddles, falling back to OP-level citation.

**Decision.** Use **(c) most-tokens dominant-segment heuristic**. The segment in the chunk with the most tokens wins; its `comment_id` / `comment_url` / `author` / `kind` / `depth` are written to chunk metadata. Ties broken by first-occurrence (Python `max()` is stable and returns the first equal-key element).

**Alternatives considered.**
- *(a) First-segment.* Rejected — overlap windows often start with a short tail-fragment from the previous reply, so first-segment would systematically mis-attribute citations to whichever reply happened to end at the boundary.
- *(b) Last-segment.* Rejected — same systematic mis-attribution in reverse, and loses the natural reading-order intuition where citations point at the most-quoted content.
- *(d) Suppress when straddling.* Rejected — straddling chunks are common (overlap is the whole point of the mechanism), and suppressing reply-level identity in all of them would defeat T-1.5.12.2's whole purpose. We'd be back to OP-only citations on the chunks where reply-anchor matters most (long popular replies that span the chunk boundary).

**Consequences.**
- Per-reply citations work correctly when a chunk's content is dominated by a single reply, which is the common case.
- For chunks where two replies have similar token counts, the citation could go to either — but the citation still lands the user *on the right thread*, just possibly at the wrong reply within it. Acceptable, since the OP page or adjacent reply is one scroll away.
- The heuristic is testable in isolation: dropping a long reply alongside a short reply in the same chunk and asserting the long one wins. Fixture-driven, no LLM dependency. (Test: `test_dominant_segment_heuristic_picks_longest_when_chunk_straddles_replies` in `test_chunking.py`.)
- Implementation cost is one `max(items, key=lambda it: _count_tokens(it[0]))` call per chunk emit. Negligible against the existing per-segment `_count_tokens` calls in the packer.

**Re-evaluation hooks.**
- If we ever observe systematic mis-attribution in production (a citation points at reply A when the actual quoted text was from reply B), the fix is to reweight the heuristic — e.g. apply token count *only to segments whose text was actually retrieved by the RAG query* rather than all segments in the chunk. That's a refinement, not a different strategy.
- For text-based connectors that emit very different segment-size distributions (a future `forum_post` connector with both long-OP and very-short replies), revisit whether token-count is the right weight or whether we want some kind of relevance-weighted score.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.12 / T-1.5.12.2. PR [#134](https://github.com/khoks/VideoResearchPro/pull/134).

---

## D-032 — Operator-coordinated runbook (vs automatic startup migration) for data-bearing identifier renames (2026-05-03)

**Status:** accepted. Resolves [T-2.6.6](initiatives.md#e-26-code-identifier-rename-pass) and shipped with PR [#137](https://github.com/khoks/VideoResearchPro/pull/137). Sets a precedent for future data-bearing renames (e.g. [E-1.9 channels → creators](initiatives.md#e-19-rename-channels-creators-db-orm)).

**Context.** The brand-rename pass identified two production-data-mutating identifiers that needed renaming alongside the user-facing copy: `CHROMA_GLOBAL_COLLECTION_NAME` (default `videoresearchpro_global` → `pratidhvani_global`) and `DATABASE_URL` (default `sqlite:///./data/videoresearchpro.db` → `pratidhvani.db`). Brand copy moved immediately in PR #97 because it's pure cosmetic. The data-bearing renames sat deferred because changing them naively would orphan existing self-hosters' libraries:

- Renaming `CHROMA_GLOBAL_COLLECTION_NAME` without a backfill leaves all existing chunks under the legacy collection name. The new collection starts empty; Q&A silently returns "no relevant context" against a library the user spent days building.
- Renaming `DATABASE_URL` without copying the SQLite file orphans every job, channel, Q&A exchange, knowledge artifact.

Two ways to resolve:

- **(a) Automatic startup migration.** App detects the legacy names on first boot of the new release, transparently moves data, swaps env defaults. Operator does nothing.
- **(b) Operator-coordinated runbook.** App keeps the legacy defaults indefinitely. Ship a documented safe-execution procedure that operators run on their own schedule, with verification checkpoints and a rollback path.

**Decision.** **(b) Operator-coordinated runbook** at [`docs/migration-code-identifiers.md`](migration-code-identifiers.md). Three sections: §A Chroma collection rename with idempotent paginated backfill script, §B SQLite file rename with backup-and-rename, §C optional GitHub repo rename (outside-codebase). Each section includes pre-flight checklist, execution steps, post-migration verification, and a rollback procedure. The codebase keeps the legacy defaults so pulling master never causes surprise data motion.

**Alternatives considered.**
- *(a) Automatic startup migration.* Rejected for three independent reasons:
  1. **ChromaDB collection rename is not atomic.** A crash mid-rename would leave half the chunks under each name, with no clean recovery and no obvious way for the operator to know which chunks made it. The runbook approach makes the operation observable + interruptible — operator runs the script with the worker stopped, watches the count climb, knows when it's done.
  2. **Default-no-rename matches operator expectations.** Self-hosters who pull master expect the same env-var defaults to keep working unless they explicitly change them. An automatic migration violates that contract.
  3. **Some operators want side-by-side instances** during evaluation — comparing behaviour on `pratidhvani_global` vs `videoresearchpro_global` collections, or running both old and new versions of the app simultaneously against separate DBs. Auto-migration forecloses that workflow.
- *Hybrid (default-stay + opt-in env-var to enable auto-migration).* Considered but rejected — adds a code path that runs once and is gone, plus the testing burden of an "automatically migrating mode" that's only correct on the first run. The runbook is one-time-by-design without the code-path complexity.

**Consequences.**
- The codebase ships with legacy defaults. Operators who want the new names follow the runbook on their own schedule. Fresh installs use the new names from the start (just set them in `.env`).
- **This sets a precedent for E-1.9** (`channels` → `creators` rename). When that ships, the *table rename* (Alembic migration in code) is still automatic on first boot — that's how SQLAlchemy / Alembic always work. But any *additional* operator-side coordination (re-pointing FKs, copying data between schemas in a complex case) follows the same runbook pattern: ship docs, not auto-migration code.
- The runbook explicitly never destroys data. Every step is reversible up to the point the operator deletes the legacy backup. That promise is worth more than execution speed.
- Maintenance cost: when we add new data-bearing renames, we extend the runbook. The docs-as-code path stays manageable as long as the rename frequency stays low — which it should, because every entry in the runbook is a deliberate rename, not an accident.

**Re-evaluation hooks.**
- Switch to automatic startup migration if (a) the rename frequency climbs to multiple per quarter (the runbook becomes a maintenance burden then), or (b) the project decides to drop self-host support — at which point the runbook audience disappears and the migration becomes a SaaS-internal infra task.
- For SaaS deployment specifically, this decision will be revisited: SaaS infra controls the data layer end-to-end, and automatic migration is fine when the migrator is the operator. But that's a separate decision for [I-5](initiatives.md#i-5-saas-readiness-long-horizon-code-shippable-work-fully-closed-2026-05-05).

**Linked initiatives / PRs.** I-2 / E-2.6 / T-2.6.6. PR [#137](https://github.com/khoks/VideoResearchPro/pull/137). Precedent referenced from [E-1.9](initiatives.md#e-19-rename-channels-creators-db-orm) when that epic schedules.

---

## D-033 — Whisper-as-service for podcasts: reuse existing OpenAI Whisper path (resolves OQ-4) (2026-05-03)

**Status:** accepted. Resolves [OQ-4](initiatives.md#open-questions-parking-lot) and shipped with PR [#140](https://github.com/khoks/VideoResearchPro/pull/140).

**Context.** [E-1.7](initiatives.md#e-17-podcast-connector) podcast-end-to-end requires audio transcription for episodes that ship without an in-feed transcript. The architectural question (filed as OQ-4 when E-1.7 was scoped): do we run Whisper as a separate service (e.g. a `whisper-service` Docker container with its own queue), or reuse the existing OpenAI Whisper integration path (`youtube_service._transcribe_with_whisper`) that the YouTube connector uses as a fallback?

Three viable architectures:

1. **Reuse existing OpenAI Whisper path.** Same `_whisper_transcribe_with_retry` helper, same retry / error-classification, same `OPENAI_API_KEY` gate, same fail-soft contract. The podcast connector downloads the enclosure to a temp file and passes it through.
2. **Separate Whisper service** with its own message queue (Celery task `transcribe_audio` accepting any audio URL). Decouples connector code from the transcription implementation; scales horizontally.
3. **Local-Whisper-via-faster-whisper** as a third option for self-hosters who don't want OpenAI in the loop. Higher self-host complexity (CUDA / ROCm / CPU model variants) but eliminates the per-minute API cost.

**Decision.** **(1) Reuse the existing OpenAI Whisper path** for v1. The podcast connector calls `_whisper_transcribe_with_retry` from `app.services.youtube_service`, gated on `OPENAI_API_KEY` exactly like the YouTube fallback. Local-Whisper option (3) deferred as a future opt-in (parallel to the Playwright SPA opt-in pattern from [D-024](#d-024--flip-e-16-to--with-primitives-only-scope-split-2026-04-28)).

**Alternatives considered.**
- *(2) Separate Whisper service.* Rejected for v1 — adds infrastructure complexity (a new Celery task type, a worker pool dimensioning question, retry semantics across two queues) that doesn't pay off until podcast-ingest volume is high enough to justify horizontal scaling. The existing single-task path handles podcast loads identically to YouTube fallback. We can graduate to (2) later by changing one function call site without touching the connector.
- *(3) Local Whisper via `faster-whisper` or similar.* Rejected as the v1 default but documented as a follow-up — see "Re-evaluation hooks" below. Adding it as a separate code path *today* means (a) we'd ship two transcription paths simultaneously and have to test both, (b) we'd need an env-var to choose, (c) `faster-whisper` model files (~1-3GB depending on size) inflate the default install. The opt-in extras pattern (`pratidhvani[whisper]`) belongs alongside the orchestrator decision to use it; that's a separate PR.

**Consequences.**
- Podcast ingest works the same way YouTube ingest works — out of the box for operators with `OPENAI_API_KEY` set, fail-soft (`text_status=unavailable`) for those without.
- The OpenAI Whisper API has a 25MB upload limit (existing constraint from YouTube integration). Long podcast episodes (1-2 hour shows = 50-150MB MP3) exceed this. Today's podcast connector doesn't yet split-and-stitch; episodes over 25MB will fail Whisper. **Filed as a known limitation**; the in-feed `<podcast:transcript>` path (which we prefer when available) sidesteps this. A future PR can add audio-splitting + per-segment Whisper + re-stitching.
- Cost: OpenAI Whisper is $0.006/minute as of 2025-Q4. A 1-hour podcast = $0.36. For a self-hoster ingesting 100 hour/month, that's $36/month — meaningful but not prohibitive. Operators who hit this scale should evaluate (3) `faster-whisper`.
- Reusing the existing helper means any future improvements (better retry classification, structured-output support, prompt-priming for known speakers) automatically apply to both YouTube + podcast ingest.

**Re-evaluation hooks.**
- Switch to **(2) Separate Whisper service** if podcast-ingest queue depth becomes a bottleneck (a Celery worker stuck on a 1-hour Whisper call blocks unrelated jobs). The fix is to put transcription on a dedicated queue, not to change connectors.
- Add **(3) Local Whisper opt-in** when (a) operator demand surfaces (we hear from self-hosters who don't want OpenAI), or (b) a SaaS deployment wants to escape per-minute API cost at scale. Implementation pattern: new `requirements-whisper-local.txt` + `WHISPER_LOCAL_MODEL` env var + extends-the-existing-helper rather than parallel-path-replaces.
- Audio-split path for >25MB files: implement when we observe the size limit biting in practice. Most podcast episodes that have transcripts publish them in-feed (Apple, Spotify Originals, every NPR show); the Whisper fallback is mostly used for indie podcasts which run shorter.

**Linked initiatives / PRs.** I-1 / E-1.7 / S-1.7 / OQ-4. PR [#140](https://github.com/khoks/VideoResearchPro/pull/140).

---

## D-034 — PDF source-type identity uses first-64KB SHA-256 (not full-file hash) (2026-05-03)

**Status:** accepted. Shipped with PR [#142](https://github.com/khoks/VideoResearchPro/pull/142).

**Context.** [E-1.8](initiatives.md#e-18-pdf-e-book-connector) PDF connector needed a stable `Candidate.source_id` derived from upload bytes. Two requirements: (a) re-uploads of the same file must dedup at the `(source_type, source_id)` unique index, and (b) the hash function must be cheap enough that the upload endpoint doesn't stall on large files (academic books, technical manuals can run 50-200MB).

Three candidate hashing strategies:

1. **Full-file SHA-256.** Strongest collision resistance; slowest for large files (~1s for 100MB on commodity hardware). Most rigorous dedup — including catching files that differ only in trailing trailer bytes.
2. **First-64KB SHA-256.** Fast (~ms regardless of file size); enough collision resistance in practice because the PDF header + first object table fall within 64KB and are highly file-specific. Tolerates trailing-trailer variation (e.g. timestamp-based linearization markers added by some PDF post-processors).
3. **Filename-based.** No collision resistance (two different files with the same name would collide); rejected immediately.

**Decision.** **(2) First-64KB SHA-256**. Hash the first 64KB and use the hex digest as the bare `source_id` (namespaced as `pdf:<digest>`).

**Alternatives considered.**
- *(1) Full-file SHA-256.* Considered seriously — it's the textbook choice. Rejected because it'd add up to a second of latency on large uploads with no observable user benefit. The collision space within first-64KB SHA-256 is 2^256, and PDF headers + initial object tables are highly file-specific (they encode object offsets, the cross-reference table, document-info dict). In practice we're nowhere close to needing the full-file content's entropy for collision avoidance.
- *(3) Filename-based.* Rejected (no collision resistance).
- *Hybrid (full-file hash, but stored in a column we can re-compute lazily).* Considered for future-proofing — if we ever need stronger dedup, we can add a `full_sha256` column populated on first read and use it as a secondary unique constraint. Skipped for v1.

**Consequences.**
- **Speed**: hash time stays in milliseconds regardless of upload size. The 100MB cap from `PDF_MAX_BYTES` becomes the I/O bound, not the hashing.
- **Dedup tolerance to trailer-metadata variation**: two uploads that differ only in trailing PDF trailer bytes (some PDF renderers re-emit the trailer with a fresh timestamp on every save) hash the same. Treated as the same document — usually the intent.
- **Collision risk**: 2^256 effective space. A practical collision requires two PDFs whose first 64KB byte-for-byte matches; in a normal corpus this never happens. Worst-case we'd need to upgrade to (1) full-file hashing later, but that's a doc-table migration (rehash existing uploads), not a structural redesign.
- Re-extraction works because we store the raw bytes at `PDF_UPLOAD_DIR/<hash>.pdf` keyed by the same digest — fitting the "extract once, store, re-extract later when PyMuPDF improves" pattern that's foundational to the rest of the L1 multi-source storage model.

**Re-evaluation hooks.**
- Switch to full-file hashing if (a) we ever observe a collision in practice, or (b) we add SaaS-side audit / compliance requirements that mandate full-content hashes for tamper detection.

**Linked initiatives / PRs.** I-1 / E-1.8 / S-1.8. PR [#142](https://github.com/khoks/VideoResearchPro/pull/142).

---

## D-035 — Connectors with no discovery surface raise `NotImplementedError`, dispatcher treats as zero-candidates (2026-05-03)

**Status:** accepted. Validated and shipped with PR [#142](https://github.com/khoks/VideoResearchPro/pull/142). Resolves a long-standing latent ambiguity in the `BaseConnector` contract.

**Context.** Most source types ([video](initiatives.md#e-15-social-media-connectors), reddit_post, hn_story, mastodon_post, bluesky_post, podcast_episode) implement `search()` because they all have public discovery surfaces. The PDF connector is the **first source type with no discovery surface** — PDFs come from upload, not search. The question: how does the polymorphic plumbing handle `source_type='pdf'` if a topic job's `source_types` array happens to include it?

Two design options:

1. **Connector raises `NotImplementedError`** in `search()` and `list_creator_items()`. Dispatcher catches the exception, treats as zero-candidates for that source type, continues with other types. Caller sees no error, just no results from that source.
2. **Connector returns empty list** silently. Same caller-visible behaviour, but loses the explicit "this connector doesn't do search" signal in the type system.

The dispatcher (`app.services.connector_dispatch.dispatch_search`) was already structured to handle both — it has a `try/except NotImplementedError: continue` block from when E-1.8 was first scoped (the empty-discovery-surface case was anticipated even though no source type exercised it until now).

**Decision.** **(1) Connectors with no discovery surface raise `NotImplementedError`** from `search()` and `list_creator_items()`. The dispatcher's existing try-block handles them gracefully.

**Alternatives considered.**
- *(2) Silent empty-list return.* Rejected — loses the "this connector intentionally has no search" signal. A future contributor reading just `connector.search("query")` couldn't tell if they got `[]` because the search ran and found nothing or because the connector doesn't search at all. The exception-based form is self-documenting.

**Consequences.**
- The pattern is reusable for future connectors with no discovery surface — `note` (user-authored annotations as a source type, planned for [I-1](initiatives.md#i-1-multi-source-ingest-original-scope-closed-2026-05-03-reopened-2026-07-22-for-e-111-scale-resilience) future), maybe a `book` connector that takes only file uploads. They follow the PDF template: raise `NotImplementedError`, document why in the docstring, the dispatcher handles it.
- The `BaseConnector` contract's existing comment ("Connectors that do not support search (e.g. PDF, where the user uploads files directly) raise NotImplementedError") was prescient — D-035 just cements it as the shipped + tested pattern.
- Tests for these connectors lock in the contract: `test_search_raises_not_implemented` is a new convention that every no-discovery-surface connector should include.
- Frontend implication: when a user enables `source_types=["pdf"]` on a topic job with no search query, the dispatch yields zero candidates for that source. The UI either filters out PDF from the topic-job source-type chooser entirely (PDFs come from upload, not topic search), or shows a helpful "Use the upload page to add PDFs" empty-state. Today's frontend doesn't expose `pdf` in the topic-job source-type chooser at all, so the dispatcher behaviour is moot — but if it ever does, the empty-state is the right answer.

**Linked initiatives / PRs.** I-1 / E-1.8 / S-1.8 / [D-026](#d-026--sequential-fan-out-for-the-connector-dispatcher-2026-05-02) (the dispatcher's NotImplementedError handling was added there). PR [#142](https://github.com/khoks/VideoResearchPro/pull/142).

---

## D-036 — Paste-mode emits five distinct `source_type` discriminators (not a single `paste`) (2026-05-03)

**Status:** accepted. Shipped with PR [#144](https://github.com/khoks/VideoResearchPro/pull/144).

**Context.** S-1.5.8 added Mode B paste-mode for FB / IG / LI / X-without-paid + generic articles. All five paste connectors share identical extraction logic (delegate to `app.services.article_extraction.extract_text`), so collapsing them into a single `paste` source_type would have been simpler — fewer SOURCE_CONFIGS entries, fewer Reference type variants, fewer connectors registered. The choice: per-platform discriminators (`fb_post` / `ig_post` / `li_post` / `tweet` / `article`) vs. a single shared `paste` discriminator with platform info in `source_metadata.platform`.

**Decision.** Use **five distinct `source_type` discriminators** matching the existing source-types matrix (`fb_post` / `ig_post` / `li_post` / `tweet` / `article`). All five connectors share the `_PasteURLBaseConnector` superclass so the implementation cost is one base + five thin one-liner subclasses; the visible discriminators are still per-platform.

**Alternatives considered.**
- *Single `paste` source_type with `metadata.platform` discriminator.* Rejected for three reasons:
  1. **Citation rendering must differ per platform.** A "fb_post" cite renders with the FB glyph + "Facebook" label; a "tweet" cite renders with the X glyph + "X / Twitter" label. Polymorphic dispatch by source_type makes that uniform; runtime-branching on `metadata.platform` makes it ad-hoc.
  2. **Library filtering by source_type is meaningful.** Users want to browse "all my Facebook posts" without seeing "all my random news articles". The library-page filter UI already pivots on source_type — collapsing weakens that.
  3. **Forward-compat with per-platform metadata extractors.** A future PR adding FB-specific author parsing, X handle extraction, or LI activity-id parsing pivots cleanly on source_type. With a single `paste` discriminator we'd have to runtime-branch on the URL host every time.
- *Sub-types of `article` with `metadata.kind`.* Rejected for similar reasons — adds ad-hoc nesting on top of the polymorphic-by-source_type contract that's now validated 12 times.

**Consequences.**
- Five new SOURCE_CONFIGS entries, five new SourceMetadata variants, five new ReferenceSourceType strings. Compile-time enforced via the mapped-type registry; one new social-media connector slips through can't compile.
- The `_PasteURLBaseConnector` shared base means the implementation cost is *low* even though the surface is polymorphic. Five subclasses are 4 lines each.
- `app/sources/paste_url/` becomes the home for paste-only connectors. `article` is later re-registered (E-1.6 phase 2) with a search-having ArticleConnector subclass; the registry's last-write-wins semantics make this safe.
- 12 source types total in the connector registry now: `video` / `reddit_post` / `hn_story` / `mastodon_post` / `bluesky_post` / `podcast_episode` / `pdf` / `article` / `fb_post` / `ig_post` / `li_post` / `tweet`. Polymorphic plumbing claim validated 12 times.

**Re-evaluation hooks.**
- If maintenance cost of 5 near-identical SOURCE_CONFIGS entries climbs, consider a config-table generator that emits all 5 from a single source-of-truth platform-spec list. Today (5 entries × ~15 lines each = 75 lines) is below the threshold where that pays off.
- If Apple opens an iOS / macOS public-post API or Bluesky adds image-mode posts as a separate type, those would be additional source types layered on the same paste-mode base.

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.8. PR [#144](https://github.com/khoks/VideoResearchPro/pull/144).

---

## D-037 — Brave Search as the default article search-engine provider (2026-05-03)

**Status:** accepted. Shipped with PR [#145](https://github.com/khoks/VideoResearchPro/pull/145).

**Context.** E-1.6 T-1.6.2 specced "Article search-engine integration (Brave / Kagi / Tavily)". The implementation had to pick one provider as the default; the connector code is per-provider-pluggable so future PRs can add others, but v1 needs a concrete default that operators can opt into without significant onboarding friction.

Three candidate providers:

1. **Brave Search.** Free tier with generous quota (~2,000 queries/month). API key is self-service signup at search.brave.com — no credit card required. Simple GET with `X-Subscription-Token` header.
2. **Tavily.** Tuned for LLM-search workloads (returns context-aware snippets). Free tier exists but requires credit card on file. Slightly higher per-query latency.
3. **Kagi.** Premium-quality results, paid-only. Requires Kagi subscription ($10/month minimum). Highest result quality but highest barrier to operator adoption.

**Decision.** **Brave Search as the v1 default**, gated on `BRAVE_SEARCH_API_KEY`. When the key is unset, `ArticleConnector.search()` returns `[]` gracefully (rather than raising) so topic jobs that include `source_types=['article']` don't fail; they just yield zero candidates from search until the operator opts in.

**Alternatives considered.**
- *Tavily as default.* Rejected for v1 — credit-card requirement is friction. Future PR can add Tavily as an alternative provider behind `TAVILY_API_KEY`.
- *Kagi as default.* Rejected — paid-only adoption barrier is too high for self-host scenarios. Power users who want Kagi can opt in; not the right default.
- *Multi-provider with operator picking via env var.* Eventually yes, but for v1 the single-provider path keeps the implementation surface minimal. Adding a second provider is one additional file + a `if settings.X_API_KEY: use X else use Y` branch in `ArticleConnector.search()`.
- *No default; operator must explicitly configure search.* Rejected — having a working free-tier default makes the article connector feel complete out of the box.

**Consequences.**
- Operators who want article search-discovery sign up at search.brave.com (free), set `BRAVE_SEARCH_API_KEY=...` in `.env`, and the article connector starts returning search candidates immediately. No code changes.
- The graceful-empty `search()` (returns `[]` instead of raising NotImplementedError) means topic jobs with mixed `source_types` (e.g. `["video", "article"]`) work even when Brave isn't configured — they just won't discover articles via search until the key is set. Article ingest via paste-mode and RSS still works.
- Future Tavily / Kagi / Google CSE providers slot into the same `ArticleConnector.search()` method as a `if BRAVE: ... elif TAVILY: ... elif KAGI: ...` chain, or (at higher provider count) a registry-of-providers table. Today's single-provider impl is the minimum viable path.

**Re-evaluation hooks.**
- Switch defaults if (a) Brave's free-tier quota becomes restrictive in practice, (b) Brave changes the API in a breaking way, or (c) a clearly-better free alternative emerges.
- Add Tavily as a second provider when LLM-tuned search results materially improve Q&A relevance for article-heavy libraries (an empirical question — measure first).

**Linked initiatives / PRs.** I-1 / E-1.6 / T-1.6.2. PR [#145](https://github.com/khoks/VideoResearchPro/pull/145).

---

## D-038 — Tenancy retrofit ships in four phases (audit → additive → backfill+writes → reads → NOT NULL) (2026-05-04)

**Status:** accepted. Resolves [E-5.1](initiatives.md#e-51-tenantid-audit-retrofit) and shipped across PRs [#149](https://github.com/khoks/VideoResearchPro/pull/149) (phase 0 audit) → [#150](https://github.com/khoks/VideoResearchPro/pull/150) (phase 1 additive) → [#151](https://github.com/khoks/VideoResearchPro/pull/151) (phase 2a backfill+writes) → [#152](https://github.com/khoks/VideoResearchPro/pull/152) (phase 2b reads). Phase 2c (NOT NULL constraint) deferred to operator runbook per [D-032](#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03) precedent.

**Context.** [E-5.1 audit](saas-tenant-id-audit.md) discovered that, despite shipping JWT auth + email/password registration and four user-scoped tables (`jobs`, `qa_exchanges`, `library_qa_exchanges`, `qa_history_exchanges`), the codebase was **structurally single-tenant** — zero `tenant_id` columns, zero `WHERE user = ?` filters in routers. Any logged-in user could read any other user's jobs, Q&A history, library exchanges. The fix is conceptually simple ("add `tenant_id` everywhere, filter queries by it") but operationally risky: any single-step rollout has a window where existing rows are unattributed, the code is enforcing attribution, and joins crash. Need a phased rollout that's safe at each intermediate state.

**Two ways to resolve:**

- **(a) Single-PR retrofit.** One migration adds `tenant_id NOT NULL` with a default backfill, one PR threads `current_user.id` through writes + reads. Atomic from the operator's perspective. **Rejected.** Three independent failure modes: (i) deploy-vs-migrate ordering — if the app boots before the migration runs, every INSERT fails on the missing column; if the migration runs before the app deploys, every SELECT crashes on the new column being unrecognized by the old ORM. (ii) Testing surface — has to validate `tenant_id IS NULL` isn't reachable mid-migration *and* the backfill produces correct attribution *and* every router enforces the filter, all in one atomic step. (iii) No room for operator verification between additive and enforcing states.

- **(b) Four-phase split.** Each phase is non-breaking on its own; the column / writes / reads / constraint advance independently with operator-observable checkpoints. **Accepted.**

**Decision.** Four phases, each shippable as an independent PR:

1. **Phase 0 — Audit doc.** [`docs/saas-tenant-id-audit.md`](saas-tenant-id-audit.md). Names every table needing `tenant_id`, every router endpoint needing the filter, the threat model (404 not 403 for cross-tenant to avoid existence-leak), the deferred-to-operator phase 2c rationale.
2. **Phase 1 — Additive nullable column + index.** Alembic migration adds `tenant_id String(36) NULL` + index to each table. ORM model adds the typed-mapped column. Zero runtime behaviour change — every existing INSERT still works (column defaults to NULL), every existing SELECT still works (column doesn't appear in WHERE clauses).
3. **Phase 2a — Backfill + write-side stamping.** Alembic backfill migration sets `tenant_id = (SELECT id FROM users ORDER BY created_at LIMIT 1)` WHERE `tenant_id IS NULL` (idempotent first-user attribution; multi-user installs follow the runbook). Concurrently, every write-side router stamps `tenant_id=current_user.id` from `Depends(get_current_user)`. After this phase, **every row has a `tenant_id`** but no SELECT filters by it.
4. **Phase 2b — Read-side filtering.** Service-layer functions (`get_job(db, job_id, tenant_id=None)` etc.) accept an optional tenant filter — `None` preserves legacy/Celery-worker call paths; routers pass `current_user.id`. Cross-tenant reads return 404 (not 403) to avoid leaking existence. After this phase, the codebase is **fully tenant-isolated** in user-facing surfaces.
5. **Phase 2c — NOT NULL constraint (deferred to operator).** A future migration drops nullability after operators have verified zero-NULL on their data. Deferred per D-032: only the operator can prove their backfill ran cleanly, and SQLite's batch_alter_table for NOT NULL with existing data is a runbook-class operation.

**Critical sequencing**: backfill runs **before** the read-side filter so legacy rows never disappear from the user mid-deploy. Write-side stamping runs **with** the backfill (same PR) so newly-created rows are correctly attributed before reads start filtering. The two-PR gap between writes (phase 2a) and reads (phase 2b) is intentional — it gives operators a window to verify backfill correctness before reads start hiding rows.

**Alternatives considered.**

- *(a) Single-PR retrofit.* Rejected above.
- *Two-phase (additive+backfill, then writes+reads).* Rejected — collapsing writes and reads into one PR loses the operator-verification window. With the four-phase split, an operator running a multi-user install can pause between 2a and 2b, run a `SELECT tenant_id, count(*) FROM jobs GROUP BY tenant_id;` sanity check, decide whether to run a per-user re-attribution before reads start filtering.
- *Three-phase (additive, writes, backfill+reads together).* Rejected — backfill must precede the read-side filter; mixing them is the same trap.
- *NOT NULL in phase 1.* Rejected — every existing row would need `tenant_id` populated atomically with the column add. Either a default value (incorrect attribution; "system" / first-user is a hack) or a join-time fail. Standard advice for additive migrations is "nullable first, NOT NULL later".

**Consequences.**

- **Each phase ships independently.** Operators can pause at any phase boundary. Phase 2c deferral means the codebase ships indefinitely with `tenant_id NULL` allowed at the schema level even when the application logic now always populates it.
- **Service-layer signatures are forever-flexible.** `get_job(db, job_id, tenant_id=None)` keeps the legacy call path working for Celery workers (which don't have `current_user` context) and any future internal services that legitimately need cross-tenant access.
- **First-user backfill is opinionated.** Single-user self-host: correct. Multi-user self-host: legacy rows attribute to whoever registered first; operators with a real multi-user install follow the future T-5.1.3 re-attribution runbook. SaaS deployment: explicit per-user / per-workspace attribution from day one (no legacy NULL rows possible).
- **404 vs 403 for cross-tenant reads.** Distinguishes "not found" from "found-but-forbidden"; the latter would leak existence (a malicious user could enumerate IDs to discover other users' job IDs). 404 is uniform with truly-non-existent IDs.
- **Sets a precedent for I-3 Echo personal-brain attribution.** The Echo north-star adds 5+ new user-scoped tables (location history, watch history, email connectors, etc.). Each will follow this same four-phase shape. The cost of doing it well once was the audit doc + four PRs; the cost of doing it badly once would have been an existence-leak vulnerability in production.

**Re-evaluation hooks.**

- Phase 2c (NOT NULL) ships when operators have run the runbook AND a clean fresh-install path is verified to never produce NULL `tenant_id`. The runbook lands as a separate doc.
- Multi-workspace-per-user (T-5.1.3) — distinct from `tenant_id`. Phase 2a's first-user backfill assumes one tenant per user; future workspace work will introduce a separate `workspace_id` column or move `tenant_id` semantics to mean "workspace".
- Performance — the `tenant_id` index was added in phase 1. If query plans ever show non-index use under tenant filtering, revisit.

**Linked initiatives / PRs.** I-5 / E-5.1 / T-5.1.0 / T-5.1.1 / T-5.1.2. PRs [#149](https://github.com/khoks/VideoResearchPro/pull/149) / [#150](https://github.com/khoks/VideoResearchPro/pull/150) / [#151](https://github.com/khoks/VideoResearchPro/pull/151) / [#152](https://github.com/khoks/VideoResearchPro/pull/152).

---

## D-039 — In-memory rate-limit backend as the default (Redis-swap deferred to multi-worker SaaS) (2026-05-04)

**Status:** accepted. Resolves [E-5.5](initiatives.md#e-55-abuse-prevention) phase 1 and shipped with [PR #157](https://github.com/khoks/VideoResearchPro/pull/157).

**Context.** [E-5.5 abuse prevention](initiatives.md#e-55-abuse-prevention) needed a rate-limit backend. Redis is already in the stack (Celery broker + WebSocket pub/sub), so a Redis-backed bucket store is "free" infrastructurally. But the supported self-host configuration runs a single uvicorn worker — multi-worker is blocked by Celery's Windows `--pool=solo` requirement and the project's deliberately-simple deployment story. Single-worker = single-process = an in-memory dict suffices for correctness. So which to ship first: in-memory (simpler, but caps fire per-process on multi-worker) or Redis (more general, but introduces a network dep on a feature that didn't have one).

**Decision.** **In-memory dict + `threading.Lock`** is the default backend. The service-layer contract (`check_and_consume(key, limit) -> (allowed, count, retry_after)`) is identical to what a Redis implementation would expose, so swapping in a Redis-backed `check_and_consume` for SaaS multi-worker deployment is a one-function change tracked as [T-5.5.4](initiatives.md#e-55-abuse-prevention).

**Alternatives considered.**
- *Redis from the start.* Rejected for self-host: the in-memory implementation is roughly 50 lines vs ~150 for the Redis version (atomic INCR + EXPIRE + retry-after computation across the round-trip). For a feature that's optional in dev and uniform in single-worker prod, the simpler implementation wins. Swap is mechanical when SaaS lands.
- *External library (`slowapi`, `fastapi-limiter`, `limits`).* Rejected. `slowapi` couples to Flask-style decorators that don't compose with our middleware shape; `fastapi-limiter` requires Redis and lacks the per-route override pattern; `limits` is a primitives-only library that wouldn't save much over our 50 lines. The project's pattern (per [E-1.6](initiatives.md#e-16-article-connector), [E-5.4](initiatives.md#e-54-auth-hardening), etc.) is to write the small piece ourselves rather than carry the dep.
- *SQL-backed buckets.* Rejected: every rate-limit check would round-trip the DB, and the cleanup path (deleting expired buckets) would need a periodic vacuum task. Hot-path latency would jump from microseconds (in-memory) or milliseconds (Redis) to multi-millisecond.

**Consequences.**
- **Single-worker self-host:** correct + fast. The middleware adds microseconds per request.
- **Multi-worker SaaS:** caps will fire per-worker, so effective limits are `N × configured_limit` where N = workers. For Free-tier-style strict caps this would matter; the swap-to-Redis is gated by SaaS launch, not by self-host scale.
- **Test posture:** `RATE_LIMIT_ENABLED=False` set globally in `conftest.py`; individual rate-limit tests opt back in via `monkeypatch`. In-memory state is cleared between tests via `rate_limit_service.reset()` in the `db` fixture teardown.
- **Backward-compat invariant:** the `check_and_consume(key, limit) -> (allowed, count, retry_after)` signature must NOT change when the Redis backend lands. T-5.5.4 is a backend swap, not an API change.

**Re-evaluation hooks.**
- Switch to Redis-backed when (a) SaaS deployment with multi-worker uvicorn lands, OR (b) a self-hoster reports needing horizontal-scale workers (rare given the Windows constraint).
- If T-5.5.5 (quota runtime metering, currently overlapping with E-5.2 T-5.2.5) lands and shares the same backend, that's the moment to reconsider whether SQL-backed buckets are actually the right call after all (since quotas are billing-relevant and need to survive a process restart).

**Linked initiatives / PRs.** I-5 / E-5.5 / T-5.5.1 / T-5.5.2 / T-5.5.3. PR [#157](https://github.com/khoks/VideoResearchPro/pull/157).

---

## D-040 — Failed logins for unknown emails do NOT create User rows (lock-arbitrary-account defence) (2026-05-04)

**Status:** accepted. Resolves a critical-correctness invariant for [E-5.4 auth hardening](initiatives.md#e-54-auth-hardening) and shipped with [PR #156](https://github.com/khoks/VideoResearchPro/pull/156).

**Context.** [E-5.4 account lockout](initiatives.md#e-54-auth-hardening) tracks `failed_login_attempts` per User. The naive implementation would, on a failed `/auth/login`, look up (or create-then-update) a User row keyed on the submitted email. But the obvious "ensure-row-exists" path opens a critical attack: an attacker submitting `{"email": "<arbitrary-real-user@somewhere.com>", "password": "wrong"}` enough times would lock that user's account. Worse, an attacker iterating over plausible emails could mass-lock thousands of accounts they don't own.

**Decision.** **Unknown emails do NOT create User rows. The lockout system applies only to existing users; brute-force attempts against non-existent emails are still rate-limited (E-5.5 sensitive-endpoint bucket) but never persist state in the `users` table.** Concretely, `authenticate_user_v2` returns `(None, INVALID_CREDENTIALS)` for unknown emails, and the router emits a `LOGIN_FAILURE` audit row with `user_id=None` (capturing the attacker's email + IP for forensics).

**Alternatives considered.**
- *Create-on-first-failure.* Rejected — opens the lock-arbitrary-account vector above. There's no defensive value: the absence of a User row is itself the correct "credentials invalid" outcome.
- *Track failed-login state on a separate `(email, ip)` keyed table independent of `users`.* Considered as a future hardening (would let us rate-limit at the (email, IP) tuple level even before a User row exists). Rejected for v1 — the E-5.5 sensitive-endpoint bucket already provides per-IP brute-force defence on `/auth/login`. If credential-stuffing-style attacks (millions of distinct (email, password) pairs from leak databases) become a real-world threat, revisit.
- *Account lockout at the IP level (lock the *attacker's IP* on N failures, regardless of email).* Considered but rejected as the *primary* defence — IPs are easily rotated. Per-account lockout + per-IP rate-limit is the layered approach that survives both rotation and credential-stuffing.

**Consequences.**
- **Test invariant**: `test_unknown_email_returns_invalid_credentials_not_locked` enforces the contract — the test is the canonical place a future PR would notice if it accidentally re-introduced the row-creation path.
- **Audit log captures the attacker's email** in the `metadata_json` of the `LOGIN_FAILURE` row even when `user_id IS NULL`. Forensics work the same as the existing-user case; the only difference is that there's no per-user lockout to consult.
- **Constant-time decoy verify**: `authenticate_user_v2` runs a dummy bcrypt verify when the email doesn't exist (`_DUMMY_PWD_HASH` constant generated at import). This keeps response latency comparable to the real-user path so timing leaks don't reveal account existence.
- **The "User row absence" outcome serves double-duty** as both the email-existence check and the timing-leak surface. Future contributors who add fields to the `users` table that materialize on first-login (e.g. some "active" status flag) MUST keep this invariant.

**Re-evaluation hooks.**
- If credential-stuffing patterns surface in audit logs (millions of `LOGIN_FAILURE` rows with `user_id IS NULL` from one IP range), consider adding an `(email, ip)` rate-limit table as a second layer of defence.
- If a per-email-prefix abuse pattern emerges (attacker probing every `[a-z]@target.com`), consider domain-level rate-limit grouping.

**Linked initiatives / PRs.** I-5 / E-5.4 / T-5.4.2. PR [#156](https://github.com/khoks/VideoResearchPro/pull/156).

---

## D-041 — ContextVar plumbing (vs explicit kwargs) for cross-cutting per-user state (2026-05-05)

**Status:** accepted. Resolves a design question that surfaced while wiring [T-5.6.4 BYOK LLM resolution-path](initiatives.md#e-56-background-job-isolation) through the LLM call sites; shipped with [PR #162](https://github.com/khoks/VideoResearchPro/pull/162).

**Context.** [T-5.6.4](initiatives.md#e-56-background-job-isolation) needed a way to make every `get_llm_for(use_case)` call honour the requesting user's BYOK credential when one is stored. The codebase has **19 LLM call sites** across `app/agents/qa_agent.py`, `app/agents/qa_history_agent.py`, `app/agents/knowledge_agent.py`, `app/agents/search_agent.py`, `app/agents/report_agent.py`, etc. — many nested two or three layers deep inside LangGraph node functions that take a state-dict, not free function arguments. None of these layers currently carry user context.

The narrow problem (route a BYOK key through to the LLM client) is one instance of a broader pattern: **request-scoped state that's needed many layers below the entry point**. Other I-5 work has the same shape — quota counters (E-5.5 T-5.5.5), per-tenant Celery routing (E-5.6 T-5.6.5), per-tenant rate limiting at the LLM-call level. Whatever pattern we pick here will set the precedent.

**Decision.** **`ContextVar` set at every router / Celery entry-point boundary**, read by `get_llm_for` (and any other infrastructure layer that needs user context). Concretely: `llm_service.byok_context(tenant_id, db)` is a context manager that sets a `ContextVar[(str, Session)]` for the duration of a `with` block. `get_llm_for` reads the var when its explicit `tenant_id`/`db` kwargs aren't provided. Routers and Celery tasks wrap their request scope:

```python
with llm_service.byok_context(current_user.id, db):
    answer, refs = run_qa_agent(...)
```

**Alternatives considered.**

- *Thread `tenant_id` + `db` as explicit kwargs through every layer.* Rejected. The "tens of touch sites" cost is real — every LangGraph node, every helper function, every agent run-function would grow the same two parameters. Mechanical refactor work that produces test churn but no behavioural value once it's done. The functions that need user context are infrastructure-layer concerns (LLM client construction, future quota metering); the agent-layer code that sits between has no business knowing about user identity.

- *Pass a `RequestContext` dataclass through the agent layer.* Same downside as above (every layer grows a parameter), plus introduces a new abstraction the codebase doesn't have today (`RequestContext`, `with_context`, etc.).

- *Module-global mutable singleton.* Rejected — request isolation breaks under concurrent FastAPI requests. ContextVar is the standard library's purpose-built solution to this exact "per-request state needed deep in the stack" problem.

- *Stash on the `request: Request` object.* Works for sync FastAPI handlers, doesn't reach Celery workers (no `Request`), and the LangGraph nodes called from inside `run_qa_agent` are not aware of the request object. ContextVar covers both call paths uniformly.

**Consequences.**

- **Plumbing-free for new infrastructure-layer concerns.** Quota metering, per-tenant tracing, per-tenant rate-limiting at the LLM-call level — all can read from the same ContextVar at minimum cost. T-5.5.5 quota metering will reuse the pattern.
- **Tests can use either the ContextVar (more realistic) or explicit kwargs (more isolated).** The `get_llm_for` signature still accepts `tenant_id=` / `db=` for the latter case.
- **Nesting works correctly.** ContextVar tokens make `with byok_context(a, db1): with byok_context(b, db2): ...` restore `(a, db1)` after the inner block — useful for "admin acts as user" scenarios.
- **Resets on exception.** The `@contextmanager` `try`/`finally` ensures the ContextVar is reset even when the wrapped code raises, so a crashed request doesn't leave the wrong tenant in the context for the next one.
- **Async-safe** by design. Python's `ContextVar` is `asyncio`-aware: each task gets its own copy of the var on creation. Both sync and async LangGraph nodes work.
- **One-of-pair warning.** Calling `get_llm_for(tenant_id=X)` without `db=` (or vice versa) is a programming error. The function logs a warning and skips the BYOK lookup rather than crashing.

**Re-evaluation hooks.**

- If a future cross-cutting concern needs more than `(tenant_id, db)` — e.g., the SaaS-launch milestone adds `workspace_id` distinct from `tenant_id` (T-5.1.3) — the ContextVar's value type can grow without changing call sites.
- If we ever ship a non-Python execution path (e.g. a Rust ingest worker), the ContextVar pattern won't transfer; that's a SaaS-architecture concern outside the scope of E-5.6.

**Linked initiatives / PRs.** I-5 / E-5.6 / T-5.6.4. PR [#162](https://github.com/khoks/VideoResearchPro/pull/162).

---

## D-042 — OAuth first-login links to existing User by email (2026-05-05)

**Status:** accepted. Resolves a security-and-UX trade-off that came up while implementing [T-5.4.5 OAuth](initiatives.md#e-54-auth-hardening); shipped with [PR #166](https://github.com/khoks/VideoResearchPro/pull/166).

**Context.** When a user signs in with Google or GitHub for the first time, the OAuth callback resolves to a `(provider, provider_user_id, email)` triple. The Pratidhvani user table is keyed on email (registration creates a row keyed on email; login looks up by email). The OAuth provider returns an email that may or may not match an existing Pratidhvani user. The implementation has to decide:

- **Path A**: always create a fresh `User` row on first OAuth login, even if the email matches an existing password-registered user. Two accounts → user can't tell why their library is empty when logging in via Google having previously registered with email/password.
- **Path B**: if the email matches an existing User, link the OAuth identity to that user. Single account survives the password→OAuth migration.

Path B has a security implication: it trusts that the OAuth provider has verified the email belongs to the person at the keyboard. Otherwise a malicious user who knows a target's email could register an OAuth account with that email at a sloppy provider and "link" their identity to the existing Pratidhvani account, gaining access without ever knowing the password.

**Decision.** **Path B** — first OAuth login matching an existing email links the new identity to the existing user. We rely on the OAuth providers' email verification: Google's OIDC `email_verified` claim is `true` by construction (Google insists on email ownership before account creation); GitHub returns only verified primary emails on the `/user` endpoint when the email was added through GitHub's verification flow. For both providers in v1 (Google, GitHub), email is verified.

**Alternatives considered.**

- *(A) Always create a fresh User on OAuth first-login.* Rejected. Forces users to migrate manually (export from old account, import into new), which is operationally painful, and creates duplicate User rows for the same human.
- *(B') Link only if the OAuth provider explicitly asserts `email_verified=true` AND we cache that flag.* Considered. The shipped code doesn't currently inspect `email_verified` because both shipped providers (Google + GitHub) verify by construction at the API endpoint we use. **If a future provider doesn't (or doesn't reliably), we add the check then** — flagged in this ADR's "Re-evaluation hooks". The risk surface today is zero providers wide.
- *(C) Link only after a confirmation email round-trip.* Rejected as v1 — adds an extra step to a flow users expect to be one-click. Reasonable for SaaS phase 2 if we ever add a provider with weaker email verification.
- *(D) Require the user to log in via password first to "associate" OAuth.* Rejected — defeats the OAuth purpose for users who never knew their password (e.g. registered via OAuth originally, never set a password).

**Consequences.**

- **Single-account UX.** A user who registered with email/password and later clicks "Sign in with Google" lands in their existing account with their full library intact. No migration step.
- **Duplicate identity rows are still impossible.** The `(provider, provider_user_id)` UNIQUE constraint on `oauth_identities` prevents linking two Pratidhvani users to the same Google account.
- **Trust boundary moves to the OAuth provider's email-verification process.** Today both shipped providers verify by construction. **A future PR adding a provider must verify this property before adding it** — that's the runbook test (search for `email_verified` checks; if none, document why this provider's email is trustable).
- **No way to detach a linked identity yet.** A user who linked Google to a password-registered account can't currently un-link. T-5.4.5b (future) will add `DELETE /auth/oauth/identities/{id}`. Out of scope here because the "link" direction is the urgent UX; "unlink" is rare.
- **Audit log captures the link event** via `LOGIN_SUCCESS` with `metadata={"provider": "...", "via": "oauth"}` so a future security review can see when an OAuth identity was first attached to a user.

**Re-evaluation hooks.**

- Adding a provider whose email isn't verified by construction (e.g. some Mastodon servers, self-hosted Gitea instances, custom enterprise OIDC). Add an `email_verified` flag check at the linking step (returning a "this provider doesn't verify email; please log in with email/password to link" error if false).
- Switching to confirmation-email-round-trip linking if SaaS abuse signals emerge.
- T-5.4.5b unlink endpoint when a real user request surfaces.

**Linked initiatives / PRs.** I-5 / E-5.4 / T-5.4.5. PR [#166](https://github.com/khoks/VideoResearchPro/pull/166).

---

## D-043 — Single shared Fernet key for all encrypted-at-rest credentials (2026-05-05)

**Status:** accepted. Resolves an architectural choice surfaced when [T-5.4.6 MFA](initiatives.md#e-54-auth-hardening) needed somewhere to store the TOTP secret encrypted; shipped with [PR #165](https://github.com/khoks/VideoResearchPro/pull/165).

**Context.** Three different encrypted-at-rest credential types now exist in the codebase:

- **BYOK provider keys** (T-5.6.1, PR #158) — `user_credentials.encrypted_secret`. Holds the user's OpenAI / Anthropic / Google API key.
- **MFA TOTP secret** (T-5.4.6, this PR) — `mfa_secrets.secret_encrypted`. Holds the random base32 secret shared with the user's authenticator app.
- **Future**: per-tenant Twitter Bearer tokens (currently shared env var; movable to per-user later), per-tenant LLM endpoint URLs, per-tenant SMTP credentials when SaaS multi-tenant adds custom email domains.

Each encryption needs a key. Two options for managing those keys:

- **One key per credential type** (e.g. `BYOK_ENCRYPTION_KEY` for BYOK, `MFA_ENCRYPTION_KEY` for MFA secrets, future-`TWITTER_TOKEN_KEY` etc.). Rotation is per-type; a key compromise blast-radius is limited to one type.
- **One shared key for all encrypted-at-rest credentials** (i.e. MFA reuses `BYOK_ENCRYPTION_KEY`). Operational simplicity at the cost of larger blast radius on key compromise.

**Decision.** **Single shared key (`BYOK_ENCRYPTION_KEY`)** for all encrypted-at-rest credentials. Both BYOK and MFA encrypt via the same `byok_service._get_fernet()` cached instance. Future credential types reuse it.

**Alternatives considered.**

- *Per-credential-type keys.* Rejected for v1 because (a) the operator burden compounds — every new credential type adds a `<TYPE>_ENCRYPTION_KEY` env var; key rotation requires coordinating N rotations; lost-key recovery is a dance per type; (b) the threat model where "leaked one key but not the other" is contrived — keys live in the same `.env` / secrets manager and are exposed via the same surfaces (process memory, env-var dump, secrets-manager breach); (c) the key is read-only after process startup — the rotation story is already operator-coordinated regardless of key count.
- *Per-user key derivation* (e.g. derive a per-user key from a master + user_id, encrypt each user's credentials with their own derived key). Rejected as overengineering for v1 — adds a derivation step on every encrypt/decrypt and doesn't change the threat model meaningfully (the master key is the real secret; derived keys recoverable from it). Reasonable for SaaS phase 2 if a regulator requires per-user key isolation.
- *KMS-backed envelope encryption* (Fernet key itself encrypted by AWS/GCP KMS, decrypted on demand). Rejected for v1 — couples self-host to cloud KMS. Promising for SaaS infrastructure (E-5.8) where KMS is already in scope.

**Consequences.**

- **Single rotation story.** Generate a new key, decrypt-and-re-encrypt every row across `user_credentials` + `mfa_secrets` + future tables, replace the env var. The runbook shipped for BYOK (T-5.6.1) generalizes.
- **Single fail-soft fallback.** When `BYOK_ENCRYPTION_KEY` is unset on self-host, a process-local Fernet key is generated at startup with a warning. Stored credentials become unrecoverable on restart in that mode — same fallback applies to BYOK + MFA. Operators who skip the key configuration get the same loud warning regardless of which feature they enable first.
- **Key compromise = full credential exposure.** If `BYOK_ENCRYPTION_KEY` leaks, the attacker can decrypt every user's BYOK provider keys AND every user's TOTP seed. In practice, a key-leak scenario already implies a compromise where these are the lesser concerns (the attacker has env-var access → can also issue JWTs / bypass auth entirely). The blast-radius increase from "one type" to "all types" is small relative to "operator gets to manage one key vs N keys".
- **MFA key rotation tolerance** — `verify_at_login` returns False (not raises) when the stored MFA ciphertext can't be decrypted. Same posture as BYOK's `get_credential` (returns None on decrypt-fail). Operators rotating the key will see MFA "fail open" (users can't second-factor in) until they re-encrypt, which is the right safety direction for an authn boundary.

**Re-evaluation hooks.**

- Switch to per-type keys if a regulator (HIPAA, FedRAMP, etc.) requires it for SaaS deployment. The runbook would split: each type's table gets its own re-encrypt step.
- Switch to KMS envelope encryption when SaaS infra (E-5.8) lands and KMS is part of the deployment story.
- Add per-user derivation if a high-value tenant requests cryptographic isolation between users at rest.

**Linked initiatives / PRs.** I-5 / E-5.4 / E-5.6 / T-5.4.6 / T-5.6.1. PRs [#158](https://github.com/khoks/VideoResearchPro/pull/158) (introduced the key for BYOK), [#165](https://github.com/khoks/VideoResearchPro/pull/165) (extended its use to MFA).

---

## D-044 — Foundation-first then concrete-implementations-deferred for I-3 / I-6 (2026-05-05)

**Status:** accepted. Resolves the structuring question for [I-3 Echo personal-brain](initiatives.md#i-3-echo-personal-brain-l3) and [I-6 Author Studio](initiatives.md#i-6-author-studio-output-generation-l2) and shipped with PRs [#172](https://github.com/khoks/VideoResearchPro/pull/172) (Echo) and [#173](https://github.com/khoks/VideoResearchPro/pull/173) (Author Studio).

**Context.** Both I-3 (Echo) and I-6 (Author Studio) are large-scope initiatives with the same shape: a small set of cross-cutting infrastructure (schema + abstraction + REST + tier gate) that hosts a larger set of concrete implementations (six Echo connectors: YouTube watch / Spotify / email / calendar / browser / Apple Health; five Author kinds: book / site / deck / newsletter / reel). The structuring question came up: do we ship one connector / outputter together with the foundation in PR 1 (proof-of-concept fully integrated), or ship the foundation alone with zero concrete implementations and let each concrete piece be its own PR?

The trade-off is non-obvious because both shapes look reasonable from the outside:

- **One concrete + foundation in PR 1**: more "real" — the foundation is validated by an end-to-end working feature, not just by tests. Easier to demo the value. But couples the foundation's API surface to one implementation's needs (risk of leaking specifics into the abstraction).
- **Foundation-only PR + concrete-per-PR**: cleaner separation; the abstraction is forced to be general because no specific consumer exists when it ships. But the foundation's tests are necessarily lower-fidelity (mocked outputters / stub connectors).

**Decision.** **Foundation-first with one trivial concrete implementation** — Echo ships with zero connectors (the registry is empty in v1; concrete connectors are E-3.2.1 through E-3.2.6); Author Studio ships with one minimum-viable outputter (`BookMarkdownOutputter` — deterministic structural concatenation of existing job reports + Q&A, no LLM). The trivial implementation validates that the foundation's REST surface + lifecycle work end-to-end with real content; future PRs add LLM-driven cohesion (T-6.1.2) and the other kinds.

**Alternatives considered.**

- *Ship one full concrete in PR 1 (e.g. YouTube watch history connector + Echo foundation, or LLM-cohesive book + Author foundation).* Rejected. (i) The first concrete implementation is always the most negotiable — its API needs influence the abstraction more than later ones do. (ii) PR review surface bloats — reviewer has to understand both the foundation and the concrete simultaneously. (iii) Schema bake-in: if the first connector turns out to want fields the schema doesn't have, the schema change ships in the same PR and tests have to cover both states.
- *Foundation-only with NO concrete implementation.* Rejected. The Echo foundation went this way (registry ships empty); the Author Studio foundation didn't because (i) "outputs" with no outputter at all is harder to demonstrate end-to-end without doing tester gymnastics, and (ii) the Book v1 deterministic concatenation is genuinely useful as a baseline (users can compile their existing reports into a Markdown bundle today). The asymmetry is intentional: Echo's connectors all need OAuth flows / external API integration and benefit from being individually-scoped PRs; Author's outputters can have a deterministic v1 that doesn't.

**Consequences.**

- **Echo follow-ups are mechanical**: each of T-3.2.1 through T-3.2.6 is "implement `EchoConnector` interface for X, write OAuth flow tests, register on import". The Protocol contract is fixed; PR review focuses on the connector's own logic.
- **Author follow-ups split between two layers**: T-6.1.2 (LLM cohesion) extends the existing `BookMarkdownOutputter` and tightens its API contract; T-6.2/.3/.4/.5 each add a new outputter to the registry. Both shapes plug into the same Outputter Protocol — no foundation churn.
- **Foundation-validation cost**: tests for the Echo foundation use mocked outputters / a fake connector; tests for the Author foundation use the BookMarkdownOutputter as the integration test. If the abstraction turns out to be insufficient for a future connector / outputter, the schema change ships in that connector's PR alongside the new code (instead of being a foundation-amend that risks breaking the deterministic v1 outputter).
- **CHANGELOG / initiatives.md framing**: every foundation PR explicitly enumerates "what's in this PR" vs "what's NOT in this PR (deliberate)" so reviewers and future contributors don't expect concrete implementations they shouldn't.

**Re-evaluation hooks.**

- If a connector / outputter PR ends up requiring meaningful schema changes (new columns, breaking API shape), revisit whether the foundation was scoped too tightly.
- If multiple connectors / outputters duplicate non-trivial code, that's a signal the abstraction is missing something — extract into the service layer rather than each implementation.

**Linked initiatives / PRs.** I-3 / I-6 / E-3.1 / E-3.2 / E-3.5 / E-3.6 / E-6.1 / E-6.6. PRs [#172](https://github.com/khoks/VideoResearchPro/pull/172) (Echo foundation, registry empty), [#173](https://github.com/khoks/VideoResearchPro/pull/173) (Author foundation + Book v1).

---

## D-045 — Quota metering: enforce-before, record-after-success (2026-05-05)

**Status:** accepted. Resolves a sequencing question that surfaced while implementing [T-5.5.5 quota runtime metering](initiatives.md#e-55-abuse-prevention) and shipped with [PR #169](https://github.com/khoks/VideoResearchPro/pull/169).

**Context.** The quota metering service exposes two operations to the hot endpoints: `enforce_quota_or_raise` (raises HTTP 429 when over cap) and `record_usage` (increments the counter). Each Q&A / library-Q&A / history-chat / knowledge-extraction endpoint has to decide the order:

- (a) `enforce` then `record` then run the agent → over-cap users 429 cleanly, but a successful enforce + crashed record means we lost a unit of attribution.
- (b) `enforce` then run the agent then `record` → over-cap users 429 cleanly, AND failed agent runs (provider timeout, malformed response) don't burn quota.
- (c) Run the agent first, `record` if successful, no enforce → users can exceed their cap by a controllable amount but the metering is purely observational.

The implementation has to make a choice that's consistent across all four hot endpoints (otherwise users see weird behaviour across surfaces).

**Decision.** **(b) enforce-before, record-after-success.** `enforce_quota_or_raise(db, current_user, "<resource>")` runs first; if it raises 429 the agent never starts. After the agent completes successfully, `record_usage(db, current_user.id, "<resource>")` increments the counter. Failed agent runs (any exception bubbling up before the record line) do NOT consume quota.

**Alternatives considered.**

- *(a) enforce-then-record-then-run.* Rejected. A user who exhausts their quota by hitting an endpoint that crashes mid-agent (rare but real — provider 5xx, network blip, malformed response, OOM during context refinement) would still have their quota burned for the failed call. Specifically: a Free-tier user with 49/50 Q&As who hits a flaky LLM provider and gets a 500 has burned their last Q&A on a failure they didn't cause. Not the right UX.
- *(c) record-only, no enforce.* Rejected. The point of quota is to enforce a cap — observational tracking without enforcement is just analytics. A future "soft warn at 80%, hard block at 100%" UX is achievable on top of (b) by reading the counter to drive frontend warnings before issuing the API call; it doesn't require changing the enforcement direction.
- *enforce-then-run-then-record-with-decrement-on-failure.* Considered as a hybrid. Rejected for unnecessary complexity: the failure path would need a try/finally with a decrement, the state machine becomes "what happens if the decrement itself crashes?", and the observable behaviour is identical to (b).

**Consequences.**

- **Failed runs don't burn quota.** A Free-tier user can retry a Q&A that hit a provider error without losing a slot. Reasonable UX; matches what users expect from "I tried, it errored, let me try again."
- **Off-by-one on the limit boundary.** A user at 49/50 successfully completes their 50th Q&A, then their 51st request 429s. They got exactly the cap they paid for. Clean.
- **Race condition window.** Two concurrent Q&A requests by the same user when they're at 49/50 could both pass `enforce_quota_or_raise` and both succeed, leaving them at 51/50. **Acceptable.** Hard atomicity (SELECT FOR UPDATE / Redis SETNX-style lock) would slow every request for an edge case that buys nothing meaningful for a per-user quota. SaaS deployment with strict billing implications could revisit; self-host doesn't need it.
- **Non-record on success path crash.** If the agent completes but `record_usage` fails (DB error, etc.) the user got their answer for free. Mirror of (a)'s failure mode but inverted: we'd rather under-count than over-charge. Aligned with the "fail-safe direction" pattern used throughout the project (audit_service, quota_service, BYOK ciphertext-undecryptable).
- **Pattern is uniform across all four hot endpoints.** `routers/qa.py`, `routers/library.py`, `routers/qa_history.py`, `routers/knowledge.py` all follow the same enforce-then-run-then-record sequence. Future quota-bearing endpoints should match.

**Re-evaluation hooks.**

- If observed quota race-conditions cause real problems (rare but possible if a user runs concurrent retries), add `SELECT FOR UPDATE` or a Redis-based reservation token. The cost is a per-request DB lock.
- If providers start charging us for failed calls (LLM provider doesn't refund tokens for a 500), revisit whether we should burn quota on failure to match our actual cost. Today providers don't, so we don't either.

**Linked initiatives / PRs.** I-5 / E-5.2 / E-5.5 / T-5.2.5 / T-5.5.5. PR [#169](https://github.com/khoks/VideoResearchPro/pull/169).

---

## D-046 — Comment-tree depth: per-platform env knob, no per-job override (resolves OQ-2) (2026-05-06)

**Status:** accepted. Resolves [OQ-2](initiatives.md#open-questions-parking-lot). Confirms the shipped behavior in [S-1.5.1](initiatives.md#s-151-reddit-search-connector) (PR [#70](https://github.com/khoks/VideoResearchPro/pull/70)) and [S-1.5.2](initiatives.md#s-152-hacker-news-search-connector) (PR [#73](https://github.com/khoks/VideoResearchPro/pull/73)).

**Context.** The Reddit and HN connectors flatten the OP body plus the top-N comments by score (Reddit "score", HN "points") into a single text body. Top-N defaults to 50 across both. OQ-2 was filed when the connectors were first scoped: should the depth be configurable per-job (a UI surface on the topic-job form), per-platform (env knob differing for Reddit vs HN), or both? Filing was deferred to ship-time so the choice could be made against real usage rather than speculatively.

**Decision.** **Per-platform env knob, no per-job override.** `app/config.py` already exposes `REDDIT_COMMENT_DEPTH_DEFAULT` and `HN_COMMENT_DEPTH_DEFAULT` as independent settings (both default 50). The connectors read these directly at fetch time. No `jobs` schema column, no UI surface, no API parameter.

**Alternatives considered.**

- **Per-job override (UI field on topic-job form).** Rejected — speculative complexity. Adding the override means: schema column on `jobs`, validation, frontend form field, persistence through the orchestrator, doc, tests. None of M-1.5 (Reddit / HN end-to-end) or M-1.6 (Mastodon / Bluesky) usage has surfaced a "I want shallower comments for this specific job" need across 60+ shipped jobs.
- **Single global env knob (one number, applies to all platforms).** Rejected — comment shapes diverge between platforms. Reddit's nested replies are noisier per-comment; HN's flat top-level comments tend to be more substantive. Future tuning likely needs per-platform divergence (e.g. drop Reddit to 30, keep HN at 50). Per-platform separation is already in place; collapsing it would be a regression.
- **Per-job override AND per-platform default.** Rejected — would land both layers; not warranted.

**Consequences.**

- Per-platform tuning is a one-line env-var change for self-host operators; no code change required.
- Per-job tuning is not available — operators who want it must currently fork the connector or set the env at deploy time. Acceptable given zero observed demand.
- Future platforms (Mastodon's reply chains, Bluesky's threads) follow the same pattern — each gets its own `<PLATFORM>_COMMENT_DEPTH_DEFAULT` env var.
- The `# OQ-2` reference in `app/config.py:42` (next to `REDDIT_COMMENT_DEPTH_DEFAULT`) stays as a breadcrumb for future revisits.

**Re-evaluation hooks.**

- If a user files a real "I want different comment depth for THIS topic job" request, promote to per-job (Story under E-1.5).
- If the per-platform env-knob default needs to differ in production (e.g. HN should be 80, Reddit 30), that's a deployment-time tweak, not a code change.
- When Mastodon (S-1.5.6) and Bluesky (S-1.5.7) gain their own depth knobs, audit whether the `<PLATFORM>_COMMENT_DEPTH_DEFAULT` naming convention scales (vs a single keyed dict).

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.1 / S-1.5.2 / OQ-2. Confirmed by PRs [#70](https://github.com/khoks/VideoResearchPro/pull/70) (Reddit) + [#73](https://github.com/khoks/VideoResearchPro/pull/73) (HN); no implementation PR is required for this decision (it ratifies shipped behavior).

---

## D-047 — Sibling-PR coordination for `/knowledge-curator` + `/work-tracker`: keep separate PRs (resolves OQ-3) (2026-05-06)

**Status:** accepted. Resolves [OQ-3](initiatives.md#open-questions-parking-lot). Ratifies the shipped pattern documented in [`.claude/skills/work-tracker/SKILL.md`](../.claude/skills/work-tracker/SKILL.md) §"Coordination with /knowledge-curator".

**Context.** Two project skills run on session-end: `/knowledge-curator` opens a `docs/<topic>-<date>` PR for vision/architecture/decision content, and `/work-tracker` opens a `work/<topic>-<date>` PR for `docs/initiatives.md` updates. When both fire on the same session, two PRs land. OQ-3 asked: should they coordinate to share a single PR per session?

**Decision.** **Keep separate PRs as the default.** Each skill owns its own branch + PR; the second skill to fire mentions the sibling PR in its body via "Companion PR: #N" (already documented in SKILL.md line 178). Combining is explicitly **not** scheduled.

**Alternatives considered.**

- **Shared single PR per session** (second skill checks out first skill's branch + amends with a new commit). Rejected — combining couples two unrelated change scopes. A doc-curator PR is a `LGTM, merge` skim; a work-tracker PR has actual scope-change content worth reading independently. If one had an issue, the other would be blocked.
- **No coordination at all** (each skill ignores the other). Rejected — leaves the user without wayfinding when reading PR bodies. The "Companion PR: #N" cross-reference is cheap and avoids confusion.
- **First-skill-only mode** (work-tracker collapses into knowledge-curator). Rejected — the two have different ownership boundaries (`initiatives.md` vs everything else); collapsing weakens the discipline.

**Consequences.**

- Two PRs per substantive session; both are independently reviewable + mergeable in either order.
- Cross-references in body via "Companion PR: #N" provide enough wayfinding.
- Skill code stays simple; no shared-branch coordination logic to maintain.
- The "v2 enhancement" language in SKILL.md line 184 ("Combining is a v2 enhancement") is now formally **descoped** — combining is not on the roadmap.

**Re-evaluation hooks.**

- If a future session ever produces 5+ skill PRs in a single chain (today's typical: 0-2), revisit with a shared-branch model.
- If a session produces a doc curator PR that depends on an `initiatives.md` change in the same session (today's design: they're independent), revisit.

**Linked initiatives / PRs.** I-4 / E-4.1 / E-4.2 / E-4.6 / OQ-3. Ratifies behavior already documented in `.claude/skills/work-tracker/SKILL.md` and `.claude/skills/knowledge-curator/SKILL.md`.

---

## D-048 — PDF connector intake: file upload only for v1 (resolves OQ-5) (2026-05-06)

**Status:** accepted. Resolves [OQ-5](initiatives.md#open-questions-parking-lot). Ratifies the shipped scope of [E-1.8](initiatives.md#e-18-pdf-e-book-connector) (PR [#142](https://github.com/khoks/VideoResearchPro/pull/142)).

**Context.** The PDF connector was scoped with an open question: file upload only, URL only, or both? E-1.8 shipped 2026-05-03 with **file upload only** via `POST /api/v1/library/upload-pdf`. URL-fetch was not implemented. OQ-5 was left open in case post-ship usage demanded URL fetch. Three days post-ship, no demand has surfaced.

**Decision.** **File upload only for v1.** URL-fetch is filed as a future-deferred Story under E-1.8 (no Story number assigned today; create on demand).

**Alternatives considered.**

- **URL-fetch in v1.** Rejected — significant additional surface: SSRF protection, redirect-chain handling, size DoS protection, Content-Type validation, optional auth (paywalled academic PDFs), concurrent-download throttling. None of which is needed for the dominant use cases (academic papers, technical books, manuals — users typically download once, then upload).
- **Both file upload AND URL-fetch in v1.** Rejected — same as above; doubles the v1 attack surface for unmeasured benefit.

**Consequences.**

- Many privacy-sensitive PDFs (paywalled academic papers, internal company documents, gated educational materials) don't have a public URL the connector could fetch from anyway — file upload covers them inherently.
- Identity model from [D-034](#d-034--pdf-source-type-identity-uses-first-64kb-sha-256-not-full-file-hash-2026-05-03) (`source_id = pdf:{first_64kb_sha256}`) is bytes-derived, so adding URL-fetch later requires no schema migration: the same bytes hash to the same source_id whether they were uploaded or fetched.
- The "no discovery surface" pattern from [D-035](#d-035-connectors-with-no-discovery-surface-raise-notimplementederror-dispatcher-treats-as-zero-candidates-2026-05-03) is preserved — URL-fetch would be intake, not discovery.
- E-1.8 follow-up list in `initiatives.md` already mentions "Frontend file-upload UI" but not URL-fetch — this decision formalizes URL-fetch as deferred.

**Re-evaluation hooks.**

- File a Story under E-1.8 when a real use case for URL-fetch surfaces (e.g. a user wants to bulk-import a list of public arxiv URLs).
- When that Story lands, share the SSRF-protection model the Article connector ([E-1.6](initiatives.md#e-16-article-connector)) already uses for trafilatura URL fetching — same threat model, same mitigations.
- A second-tier follow-up: bulk import via a list of URLs (newsletter / RSS-style intake) — that's a separate Story, not part of the v1 URL-fetch one.

**Linked initiatives / PRs.** I-1 / E-1.8 / OQ-5 / D-034 / D-035. Ratifies PR [#142](https://github.com/khoks/VideoResearchPro/pull/142) shipped scope.

---

## D-049 — Echo cold-start readiness threshold: shipped triple is v1; personal-brain.md sub-table is forward-looking spec (resolves OQ-6) (2026-05-06)

**Status:** accepted. Resolves [OQ-6](initiatives.md#open-questions-parking-lot). Ratifies the shipped behavior in [E-3.5](initiatives.md#e-35-cold-start-readiness-threshold) (PR [#172](https://github.com/khoks/VideoResearchPro/pull/172)).

**Context.** The Echo "speak as me" agent should not fire on sparse data — output would be lazy-mimicry, breaking user trust. A cold-start gate is needed. OQ-6 asked: what are the quantitative criteria? `personal-brain.md` proposed a four-row sub-table (Domain 1: 30 facts × 3 categories; Domain 2: 90 days × 200 events; Domain 3: 50 signals × 4 types; Domain 5: 100 shares × 4 content types). PR #172 shipped a simpler three-criterion gate.

**Decision.** **The shipped triple is the authoritative v1.** Three criteria, all measured today:

1. **`total_threshold=100`** — at least 100 PersonalContext rows total across all kinds.
2. **`sources_threshold=3`** — at least 3 distinct values of `personal_context.source` (one of: `manual`, `youtube_watch_history`, `spotify_history`, `email`, etc.).
3. **`has_personality_trait=True`** — at least one row with `kind='personality_trait'`.

The personal-brain.md sub-table remains as the **forward-looking spec** for once Domains 2-5 connectors land, at which point `is_ready()` will gain domain-specific minima. Until then, the simpler triple holds.

**Alternatives considered.**

- **Adopt the personal-brain.md sub-table as v1.** Rejected — premature lock-in. Domain 2 (activity events: 90 days × 200 events) and Domain 5 (constant-stream shares: 100 × 4 types) assume connectors that don't exist (E-3.2 deferred). Hardcoding their thresholds before the connectors ship would just be a guess; the implementations themselves will inform reasonable minima.
- **Single threshold (just total rows).** Rejected — misses signal diversity. A user with 100 rows all of `kind='location'` from a single source isn't ready for "speak as me"; the breadth + personality dimensions matter.
- **Stricter v1 thresholds (e.g. 200 / 5 / multiple personality kinds).** Rejected — too aggressive for the bootstrapping phase. Operators want to test Echo behavior before they've accumulated months of context; a `sources_threshold=3` is enough breadth to validate the agent without forcing month-long warmup.

**Consequences.**

- v1 is a function with named arguments (`total_threshold=100, sources_threshold=3`) so operators can tune at call time without redeploy.
- `EchoReadiness` dataclass returns the diagnostics (`total_rows`, `distinct_sources`, `has_personality_trait`, `threshold_total`, `threshold_sources`) so the frontend can show a "you're 60% there" progress UI.
- `/api/v1/echo/status` exposes the diagnostics over REST.
- The personal-brain.md sub-table is left intact as the future-spec; its preamble ("Recommended initial threshold (subject to validation)") already flags it as proposed, not committed.
- When E-3.2 (activity-stream connectors) lands, expand `is_ready()` to include domain-specific minima per the sub-table; that's a separate PR with its own ADR.

**Re-evaluation hooks.**

- When E-3.2 (activity-stream) lands, evolve the threshold to include 90-day × 200-event criteria.
- When E-3.4 (speak-as-me agent) is wired to actually consume `is_ready()` as a gate, threshold mis-calibration becomes load-bearing — that's the trigger to validate against real users.
- If self-host operators report Echo "feels off" at the v1 thresholds, raise to 200/5/2-personality-kinds.
- Promote function args to env vars / a settings object once tuning has stabilized.

**Linked initiatives / PRs.** I-3 / E-3.5 / E-3.2 / E-3.4 / OQ-6. PR [#172](https://github.com/khoks/VideoResearchPro/pull/172) (Echo foundation, registry empty).

---

## D-050 — Self-service tier flip with mock payment until E-5.3 (Stripe) ships (2026-05-15)

**Status:** accepted.

**Context.** Self-host operators today must `UPDATE users SET tier = 'studio' WHERE email = '...'` directly in SQL to evaluate paid-tier features (BYOK, Author Studio, Echo). That's hostile UX — the user has to know the schema, find the DB path, write SQL — and it's an obstacle to "kick the tires on Pro before deciding". The cleanest fix is a self-service Subscription page inside the app + a public Pricing page that explains what each tier unlocks. But the project is pre-Stripe (E-5.3 deferred to SaaS launch per [D-038](#d-038--tenancy-retrofit-ships-in-four-phases-audit-additive-backfillwrites-reads-not-null-2026-05-04) sequencing), so a "real" payment flow isn't shippable today.

**Decision.** Ship a **self-service tier flip endpoint** (`PUT /api/v1/auth/me/tier`) that updates `users.tier` directly, gated on authentication only — no payment integration, no Stripe webhook. The frontend renders a Stripe-style payment modal pre-filled with test values (`4242 4242 4242 4242` etc.) and shows a prominent "DEMO MODE — no real payment will be processed" banner everywhere the upgrade flow is surfaced. The endpoint accepts an optional `mock_payment` field in the request body for forward-compat shape but **ignores it server-side**.

When E-5.3 (Stripe) ships, the same endpoint stays — its implementation flips from "trust the request body" to "verify the Stripe webhook payload + update tier on `checkout.session.completed`". The frontend UX is largely unchanged (real Stripe Checkout redirect replaces the mock modal). No new UI primitives are needed.

**Alternatives considered.**

- **Wait for Stripe to ship E-5.3 before adding any tier-flip UI.** Rejected — keeps the SQL-edit-the-DB friction in place indefinitely, and operators have no way to evaluate paid features before commit. The cost of building a mock flow now is much lower than the user friction of doing nothing.
- **Build a "request upgrade" form that emails the operator.** Rejected — doesn't actually unlock anything for self-host (the operator and the user are the same person 99% of the time), and adds an email-delivery dependency to a flow that's already trivially expressible.
- **Allow tier-flip via a one-off CLI script (`./scripts/set_tier.py`).** Rejected — same DB-editing problem in a slightly different shape; doesn't address the "discover paid features → try them" UX gap.
- **Build the Subscription page without the mock-payment modal (just a "Switch to Pro" button).** Rejected — the modal exists to validate UX shape **before** Stripe lands. Skipping the modal means the team can't catch payment-flow UX issues until E-5.3, when the cost of rework is much higher.

**Consequences.**

- **Operator UX.** Self-hosters can switch tiers in three clicks from `/account/subscription` — no SQL, no schema knowledge required.
- **Endpoint shape stays stable across the Stripe migration.** When E-5.3 ships, the route name + body schema + response shape don't change — only the implementation. Frontend code remains unchanged.
- **Auth check is the only gate.** Anyone with valid credentials can flip their own tier to anything they want. On self-host this is harmless (operator-owned account). On SaaS this is a non-starter — but on SaaS, this endpoint is replaced by a Stripe webhook handler, so the "anyone can flip" surface never exists in production.
- **Audit log.** Every tier change writes a `tier_changed` audit_log event with `{from_tier, to_tier, mock_payment_mode: true}`. SaaS operators investigating "how did this user get Studio" can see the demo-mode marker.
- **No Stripe-coupling today.** Backend has zero Stripe dependencies; the migration to E-5.3 is a localized swap.

**Re-evaluation hooks.**

- When E-5.3 lands: swap the endpoint's implementation to verify Stripe webhook signature → update tier on `checkout.session.completed`. Swap the frontend's `MockPaymentModal` for a Stripe Checkout redirect. The route + UI scaffolding stay.
- If self-host operators report confusion ("am I being charged?"), strengthen the demo-mode banners or add a one-time consent dialog on first upgrade.
- If a SaaS deployment ever ships *before* Stripe lands, the endpoint must be gated behind an environment flag (`ENABLE_SELF_SERVICE_TIER_FLIP=false` in SaaS) — explicitly documented as a deploy-time toggle when SaaS launches.

**Linked initiatives / PRs.** I-5 / E-5.2 / E-5.3 (deferred). PR TBD (this commit).

---

## D-051 — Transcript-pipeline resilience bundle: circuit breaker + segmented Whisper + yt-dlp client fallback (2026-07-22)

**Status:** accepted.

**Context.** The 2026-07-21/22 200-video deep-research test (job `0d4db8c3`, 30 preferred channels, ~96 min end-to-end, completed) triggered a YouTube transcript-API IP block after ~60 serial fetches — the fixed 0.5s pacing was insufficient at scale. From that point every remaining video fell through to the Whisper path, making Whisper the *primary* transcription path for 159/200 videos (80%). The cascade cost real data: 36 videos were lost to the 25MB Whisper upload cap — disproportionately long-form, high-value sources (conference talks, podcasts: exactly what a research corpus wants most) — and 27 more to yt-dlp HTTP 403 audio-download failures. Final tally: 137/200 fetched. The extraction loop had no throttle, no backoff, and no breaker; nothing detected the block, so the job burned Whisper dollars on every remaining video instead of waiting the block out.

**Decision.** Three coordinated parts, shipped as one bundle:

- **(a) Adaptive pacing + circuit breaker for transcript fetches.** Default pacing raised 0.5s → 3.0s with ±40% jitter. After 3 consecutive IP-block signals, a cooldown opens the breaker (120s, doubling to a 900s max) and pauses transcript attempts; a post-cooldown probe re-tests the transcript API before resuming. While the breaker is open, per-video behavior falls to Whisper only when the remaining wait exceeds a cap — otherwise the loop waits it out. Rationale: waiting is cheaper than Whisper dollars + data loss.
- **(b) Segmented Whisper for >25MB audio** (user-specified design). Split audio via ffmpeg stream-copy into ~20MB-target time chunks WITH overlap (default 15s), transcribe each chunk separately, then merge with timestamps offset by each chunk's position; overlap-zone segments are deduplicated by a midpoint-ownership rule. Falls back to smallest-audio-format re-download when ffmpeg is unavailable; only bails if the audio is still oversize after that.
- **(c) yt-dlp 403 recovery.** Escalating retry ladder across YouTube innertube player clients (default → android → ios) with cooldowns between attempts, plus preference for smaller audio formats.

**Alternatives considered.**

- **Proxy rotation for the IP block.** Deferred — external dependency, recurring cost, and ToS posture concerns. Re-enters consideration if blocks persist at pacing=3s (see re-evaluation hooks).
- **Pre-emptive audio-bitrate capping alone.** Insufficient — very long videos exceed 25MB at any usable bitrate; only segmentation generalizes.
- **Dropping >25MB videos (status quo).** Unacceptable — a systematic data-loss bias against long-form content, which is the highest-value material for a research tool.

**Consequences.**

- Extraction is slower-but-complete under blocking — the breaker trades wall-clock time for completeness and cost containment.
- Whisper cost is bounded by a new per-job budget knob (`WHISPER_MAX_PER_JOB`).
- Provenance is now recorded (`text_source='whisper'|'youtube'`) — fixes the bug where all transcripts were labeled `'youtube'` (the test run recorded 0 of ~96 Whisper transcripts as `'whisper'`), so operators can audit which transcripts cost money and dataset exports can distinguish caption quality.

**Re-evaluation hooks.**

- Proxy support if IP blocks persist even at pacing=3.0s.
- Local-whisper option for self-host Whisper cost elimination.

**Linked initiatives / PRs.** I-1 / [E-1.11](initiatives.md#e-111-transcript-pipeline-resilience-at-scale) (new). PR: this branch's PR.
