# Pratidhvani — Decision Log

**Status:** living doc (last refreshed 2026-10-25). Owner: [`/knowledge-curator`](../.claude/skills/knowledge-curator/SKILL.md) skill.

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

**Context.** [E-2.5](initiatives.md#e-25--marketing-landing-page-warm-editorial) needed a static-site stack for the marketing landing page (hero / curation thesis / source-types matrix / how-it-works / install / SaaS waitlist). The site is **explicitly separate** from the React product app under `frontend/` — different audience, different deploy target, no shared runtime — so the choice is unconstrained by the existing React-Vite stack.

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

**Status:** accepted. Resolves [T-1.5.11.3](initiatives.md#s-1511--topic-job-routing-through-new-connectors).

**Context.** T-1.5.11.3 ("Fan-out semantics for mixed-source jobs") was filed when [S-1.5.11](initiatives.md#s-1511--topic-job-routing-through-new-connectors) was scoped, with two candidate shapes for how `dispatch_search()` should iterate `source_types` when a topic job spans multiple connectors:

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

**Status:** accepted. Resolves the discovery question for [S-1.5.6](initiatives.md#s-156--mastodon-connector) and shipped with PR [#128](https://github.com/khoks/VideoResearchPro/pull/128).

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

**Status:** accepted. Resolves the auth question for [S-1.5.7](initiatives.md#s-157--bluesky-connector) and shipped with PR [#129](https://github.com/khoks/VideoResearchPro/pull/129).

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

**Status:** accepted. Resolves [T-1.5.12.2](initiatives.md#s-1512--backend-reference-enrichment) and shipped with PR [#134](https://github.com/khoks/VideoResearchPro/pull/134).

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

**Status:** accepted. Resolves [T-2.6.6](initiatives.md#e-26--code-identifier-rename-pass) and shipped with PR [#137](https://github.com/khoks/VideoResearchPro/pull/137). Sets a precedent for future data-bearing renames (e.g. [E-1.9 channels → creators](initiatives.md#e-19--rename-channels--creators-db--orm)).

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
- For SaaS deployment specifically, this decision will be revisited: SaaS infra controls the data layer end-to-end, and automatic migration is fine when the migrator is the operator. But that's a separate decision for [I-5](initiatives.md#i-5--saas-readiness-long-horizon--code-shippable-work-fully-closed-2026-05-05).

**Linked initiatives / PRs.** I-2 / E-2.6 / T-2.6.6. PR [#137](https://github.com/khoks/VideoResearchPro/pull/137). Precedent referenced from [E-1.9](initiatives.md#e-19--rename-channels--creators-db--orm) when that epic schedules.

---

## D-033 — Whisper-as-service for podcasts: reuse existing OpenAI Whisper path (resolves OQ-4) (2026-05-03)

**Status:** accepted. Resolves [OQ-4](initiatives.md#open-questions-parking-lot) and shipped with PR [#140](https://github.com/khoks/VideoResearchPro/pull/140).

**Context.** [E-1.7](initiatives.md#e-17--podcast-connector) podcast-end-to-end requires audio transcription for episodes that ship without an in-feed transcript. The architectural question (filed as OQ-4 when E-1.7 was scoped): do we run Whisper as a separate service (e.g. a `whisper-service` Docker container with its own queue), or reuse the existing OpenAI Whisper integration path (`youtube_service._transcribe_with_whisper`) that the YouTube connector uses as a fallback?

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

**Context.** [E-1.8](initiatives.md#e-18--pdf--e-book-connector) PDF connector needed a stable `Candidate.source_id` derived from upload bytes. Two requirements: (a) re-uploads of the same file must dedup at the `(source_type, source_id)` unique index, and (b) the hash function must be cheap enough that the upload endpoint doesn't stall on large files (academic books, technical manuals can run 50-200MB).

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

**Context.** Most source types ([video](initiatives.md#e-15--social-media-connectors), reddit_post, hn_story, mastodon_post, bluesky_post, podcast_episode) implement `search()` because they all have public discovery surfaces. The PDF connector is the **first source type with no discovery surface** — PDFs come from upload, not search. The question: how does the polymorphic plumbing handle `source_type='pdf'` if a topic job's `source_types` array happens to include it?

Two design options:

1. **Connector raises `NotImplementedError`** in `search()` and `list_creator_items()`. Dispatcher catches the exception, treats as zero-candidates for that source type, continues with other types. Caller sees no error, just no results from that source.
2. **Connector returns empty list** silently. Same caller-visible behaviour, but loses the explicit "this connector doesn't do search" signal in the type system.

The dispatcher (`app.services.connector_dispatch.dispatch_search`) was already structured to handle both — it has a `try/except NotImplementedError: continue` block from when E-1.8 was first scoped (the empty-discovery-surface case was anticipated even though no source type exercised it until now).

**Decision.** **(1) Connectors with no discovery surface raise `NotImplementedError`** from `search()` and `list_creator_items()`. The dispatcher's existing try-block handles them gracefully.

**Alternatives considered.**
- *(2) Silent empty-list return.* Rejected — loses the "this connector intentionally has no search" signal. A future contributor reading just `connector.search("query")` couldn't tell if they got `[]` because the search ran and found nothing or because the connector doesn't search at all. The exception-based form is self-documenting.

**Consequences.**
- The pattern is reusable for future connectors with no discovery surface — `note` (user-authored annotations as a source type, planned for [I-1](initiatives.md#i-1--multi-source-ingest--original-scope-closed-2026-05-03-reopened-2026-07-22-for-e-111-scale-resilience) future), maybe a `book` connector that takes only file uploads. They follow the PDF template: raise `NotImplementedError`, document why in the docstring, the dispatcher handles it.
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

**Status:** accepted. Resolves [E-5.1](initiatives.md#e-51--tenant_id-audit--retrofit) and shipped across PRs [#149](https://github.com/khoks/VideoResearchPro/pull/149) (phase 0 audit) → [#150](https://github.com/khoks/VideoResearchPro/pull/150) (phase 1 additive) → [#151](https://github.com/khoks/VideoResearchPro/pull/151) (phase 2a backfill+writes) → [#152](https://github.com/khoks/VideoResearchPro/pull/152) (phase 2b reads). Phase 2c (NOT NULL constraint) deferred to operator runbook per [D-032](#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03) precedent.

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

**Status:** accepted. Resolves [E-5.5](initiatives.md#e-55--abuse-prevention) phase 1 and shipped with [PR #157](https://github.com/khoks/VideoResearchPro/pull/157).

**Context.** [E-5.5 abuse prevention](initiatives.md#e-55--abuse-prevention) needed a rate-limit backend. Redis is already in the stack (Celery broker + WebSocket pub/sub), so a Redis-backed bucket store is "free" infrastructurally. But the supported self-host configuration runs a single uvicorn worker — multi-worker is blocked by Celery's Windows `--pool=solo` requirement and the project's deliberately-simple deployment story. Single-worker = single-process = an in-memory dict suffices for correctness. So which to ship first: in-memory (simpler, but caps fire per-process on multi-worker) or Redis (more general, but introduces a network dep on a feature that didn't have one).

**Decision.** **In-memory dict + `threading.Lock`** is the default backend. The service-layer contract (`check_and_consume(key, limit) -> (allowed, count, retry_after)`) is identical to what a Redis implementation would expose, so swapping in a Redis-backed `check_and_consume` for SaaS multi-worker deployment is a one-function change tracked as [T-5.5.4](initiatives.md#e-55--abuse-prevention).

**Alternatives considered.**
- *Redis from the start.* Rejected for self-host: the in-memory implementation is roughly 50 lines vs ~150 for the Redis version (atomic INCR + EXPIRE + retry-after computation across the round-trip). For a feature that's optional in dev and uniform in single-worker prod, the simpler implementation wins. Swap is mechanical when SaaS lands.
- *External library (`slowapi`, `fastapi-limiter`, `limits`).* Rejected. `slowapi` couples to Flask-style decorators that don't compose with our middleware shape; `fastapi-limiter` requires Redis and lacks the per-route override pattern; `limits` is a primitives-only library that wouldn't save much over our 50 lines. The project's pattern (per [E-1.6](initiatives.md#e-16--article-connector), [E-5.4](initiatives.md#e-54--auth-hardening), etc.) is to write the small piece ourselves rather than carry the dep.
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

**Status:** accepted. Resolves a critical-correctness invariant for [E-5.4 auth hardening](initiatives.md#e-54--auth-hardening) and shipped with [PR #156](https://github.com/khoks/VideoResearchPro/pull/156).

**Context.** [E-5.4 account lockout](initiatives.md#e-54--auth-hardening) tracks `failed_login_attempts` per User. The naive implementation would, on a failed `/auth/login`, look up (or create-then-update) a User row keyed on the submitted email. But the obvious "ensure-row-exists" path opens a critical attack: an attacker submitting `{"email": "<arbitrary-real-user@somewhere.com>", "password": "wrong"}` enough times would lock that user's account. Worse, an attacker iterating over plausible emails could mass-lock thousands of accounts they don't own.

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

**Status:** accepted. Resolves a design question that surfaced while wiring [T-5.6.4 BYOK LLM resolution-path](initiatives.md#e-56--background-job-isolation) through the LLM call sites; shipped with [PR #162](https://github.com/khoks/VideoResearchPro/pull/162).

**Context.** [T-5.6.4](initiatives.md#e-56--background-job-isolation) needed a way to make every `get_llm_for(use_case)` call honour the requesting user's BYOK credential when one is stored. The codebase has **19 LLM call sites** across `app/agents/qa_agent.py`, `app/agents/qa_history_agent.py`, `app/agents/knowledge_agent.py`, `app/agents/search_agent.py`, `app/agents/report_agent.py`, etc. — many nested two or three layers deep inside LangGraph node functions that take a state-dict, not free function arguments. None of these layers currently carry user context.

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

**Status:** accepted. Resolves a security-and-UX trade-off that came up while implementing [T-5.4.5 OAuth](initiatives.md#e-54--auth-hardening); shipped with [PR #166](https://github.com/khoks/VideoResearchPro/pull/166).

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

**Status:** accepted. Resolves an architectural choice surfaced when [T-5.4.6 MFA](initiatives.md#e-54--auth-hardening) needed somewhere to store the TOTP secret encrypted; shipped with [PR #165](https://github.com/khoks/VideoResearchPro/pull/165).

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

**Status:** accepted. Resolves the structuring question for [I-3 Echo personal-brain](initiatives.md#i-3--echo-personal-brain-l3) and [I-6 Author Studio](initiatives.md#i-6--author-studio-output-generation-l2) and shipped with PRs [#172](https://github.com/khoks/VideoResearchPro/pull/172) (Echo) and [#173](https://github.com/khoks/VideoResearchPro/pull/173) (Author Studio).

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

**Status:** accepted. Resolves a sequencing question that surfaced while implementing [T-5.5.5 quota runtime metering](initiatives.md#e-55--abuse-prevention) and shipped with [PR #169](https://github.com/khoks/VideoResearchPro/pull/169).

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

**Status:** accepted. Resolves [OQ-2](initiatives.md#open-questions-parking-lot). Confirms the shipped behavior in [S-1.5.1](initiatives.md#s-151--reddit-search-connector) (PR [#70](https://github.com/khoks/VideoResearchPro/pull/70)) and [S-1.5.2](initiatives.md#s-152--hacker-news-search-connector) (PR [#73](https://github.com/khoks/VideoResearchPro/pull/73)).

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

**Status:** accepted. Resolves [OQ-5](initiatives.md#open-questions-parking-lot). Ratifies the shipped scope of [E-1.8](initiatives.md#e-18--pdf--e-book-connector) (PR [#142](https://github.com/khoks/VideoResearchPro/pull/142)).

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
- When that Story lands, share the SSRF-protection model the Article connector ([E-1.6](initiatives.md#e-16--article-connector)) already uses for trafilatura URL fetching — same threat model, same mitigations.
- A second-tier follow-up: bulk import via a list of URLs (newsletter / RSS-style intake) — that's a separate Story, not part of the v1 URL-fetch one.

**Linked initiatives / PRs.** I-1 / E-1.8 / OQ-5 / D-034 / D-035. Ratifies PR [#142](https://github.com/khoks/VideoResearchPro/pull/142) shipped scope.

---

## D-049 — Echo cold-start readiness threshold: shipped triple is v1; personal-brain.md sub-table is forward-looking spec (resolves OQ-6) (2026-05-06)

**Status:** superseded by [D-101](#d-101--echo-readiness-v2-five-domains-measured-from-their-stores-blocked-reads-as-not-connected-the-voice-test-reported-not-gated-2026-10-20) (2026-10-20). Resolves [OQ-6](initiatives.md#open-questions-parking-lot). Ratifies the shipped behavior in [E-3.5](initiatives.md#e-35--cold-start-readiness-threshold) (PR [#172](https://github.com/khoks/VideoResearchPro/pull/172)).

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

**Status-changed 2026-10-25:** amended by [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25) — the tier switch (and `POST /admin/restart`) is operator-only: the accounts in `ADMIN_EMAILS`, else the earliest-registered account.

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

**Linked initiatives / PRs.** I-1 / [E-1.11](initiatives.md#e-111--transcript-pipeline-resilience-at-scale) (new). PR: this branch's PR.

---

## D-052 — Measured context windows + three-tier model stack (E-1.12 model re-audit) (2026-07-29)

**Status:** accepted.

**Context.** The E-1.12 context-scale audit found report batching sized by one global constant (`LLM_MAX_CONTEXT_TOKENS` = 1,047,576, GPT-4.1's window) regardless of the resolved model. The registry documented no window per model, and the OpenAI lineup had shifted again since the E-4.9 audit: `gpt-5.4` / `gpt-5.4-mini` returned to the account (absent in May), and an undated `gpt-5.6-luna/sol/terra` trio appeared. The user asked for a model re-analysis alongside the resilience work. `ANTHROPIC_API_KEY` is not configured, so Claude models cannot be defaults today.

**Decision.** Three coordinated parts:

(a) **Measure, don't guess.** Context windows are now empirically measured by sending each model an oversized prompt and parsing the API's own 400 message ("Input tokens exceed the configured limit of N tokens") — rejected requests are unbilled, so re-measuring after every lineup shift is free. Measured 2026-07-29: `gpt-5.4-nano` / `gpt-5.4-mini` = **272,000** input tokens; `gpt-5.4` / `gpt-5.5` / `gpt-5.5-pro` / `gpt-5.6-*` = **922,000**; `gpt-4.1-mini` = **1,047,576**. Stored in `llm_routing.MODEL_CONTEXT_WINDOWS` with `context_window_for()` prefix matching and a conservative 128K default for unknown models. Batch budgets derive from the RESOLVED model (`report_agent._batch_budget`), capped additionally at a 120K quality ceiling (context-rot guard).

(b) **Three-tier stack** now that `gpt-5.4-mini` is back: nano (272K) for high-volume mechanical calls (map, extract, classify, clarify, expansion, references, plan); **5.4-mini (272K) for mid-tier synthesis** — `qa_refine_context`, `library_qa_refine_context`, `report_reduce_summaries`, `report_channel` (all previously on 5.5 or nano); 5.5 (922K) for flagship user-facing output (formulate ×3, compose, rank, knowledge synthesize). `social_classify_stance` moves `gpt-4.1-mini` → `gpt-5.4-nano` (consistent stack). Net effect: four use cases step DOWN a price tier with no window risk (their inputs are ≤37K vs 272K available).

(c) **Deliberate non-adoptions.** `gpt-5.6-luna/sol/terra`: live, 922K windows, but undated and unprofiled — watch-list, not defaults; re-evaluate when dated snapshots appear. Claude 5 family (`claude-sonnet-5` suits long-context refine/compose; `claude-haiku-4-5` suits map/classify volume): recommended alternates documented in the registry header, adoptable per-use-case via `LLM_USE_CASE_CONFIG` the day `ANTHROPIC_API_KEY` is configured.

**Alternatives considered.** Keeping the global constant (rejected — the measured data proves gpt-5.4-nano's 272K window made every 628K map batch a silent 400; the reference job's report was likely built from a fraction of its corpus). Hardcoding vendor-published windows (rejected — post-cutoff models have no reliable published numbers in-repo; measurement is free and exact). Adopting gpt-5.6 immediately (rejected — no dated snapshot, no track record).

**Consequences.** Batch sizing is now model-truthful; swapping any use case to a smaller-window model automatically shrinks its batches instead of silently dropping content. The measurement probe is rerunnable (documented in the registry header). Registry model drift remains monitorable via `scripts/validate_llm_registry.py --strict`.

**Re-evaluation hooks.** Re-measure + re-tier when gpt-5.6 gets dated snapshots; revisit Claude adoption when the key lands; if 5.4-mini quality on refine/reduce disappoints, the una-tantum bump back to 5.5 is one env line.

**Linked initiatives / PRs.** I-1 / E-1.12 (S-1.12.2 + model re-audit). PRs [#195](https://github.com/khoks/VideoResearchPro/pull/195), [#196](https://github.com/khoks/VideoResearchPro/pull/196).

**Status-changed 2026-07-29:** amended same-day after live validation — `gpt-5.4-mini` with reasoning `low` consumes the visible completion budget (refine returned empty output; same failure class as T-4.9.5). All four mini call sites run reasoning **off**; part (b)'s tier table stands otherwise. Re-validated live on job 0d4db8c3: 11.8K-char grounded answer, 10 citations, 52s vs the 127s pre-audit baseline.

---

## D-053 — Claude 5 adoption for user-facing synthesis + gpt-5.6 empirical profile (2026-07-29)

**Status:** accepted.

**Context.** `ANTHROPIC_API_KEY` was configured (the D-052 precondition), and the user asked for an in-depth gpt-5.6 analysis. All candidates were profiled empirically: measured context windows (oversized-prompt 400s), generation latency/throughput, JSON discipline (rank-style), compression fidelity (refine-style, 3 planted facts), and reasoning behavior.

**Measurements (2026-07-29).** Windows: `claude-sonnet-5` / `claude-opus-5` / `claude-fable-5` = 1,000,000 input tokens; `claude-haiku-4-5` = 200,000. Throughput/latency on a fixed 180-word generation: `gpt-5.6-luna` 120.6 tok/s (5.7s), `gpt-5.4-mini` 88.1 (2.7s), `claude-sonnet-5` 78.7 (5.8s), `gpt-5.5` 78.7 (13.0s), `claude-haiku-4-5` 66.1 (3.8s), `gpt-5.6-sol` 59.9 (12.1s), `gpt-5.6-terra` 15.8 (59.8s), `claude-opus-5` (26.7s, thinking-on default). Every model passed the JSON-rank and 3/3 compression probes — quality separation at this trivial tier is nil; the differentiators are speed, window, reasoning capability, and provenance.

**Decision.**

1. **`claude-sonnet-5` owns the four user-facing synthesis sites**: `qa_formulate_answer` (low), `library_qa_formulate_answer` (low), `report_compose` (medium), `knowledge_synthesize_report` (medium). Rationale: flagship-class output at ~2× gpt-5.5's measured latency, a 1M window that removes compose-input pressure entirely, and citation-faithful long-form synthesis is the family's traditional strength.
2. **gpt-5.6 trio: profiled, still not adopted.** All three accept `reasoning_effort` but emit ZERO reasoning tokens — they are non-reasoning speed tiers (luna=fast/120 tok/s, sol=mid, terra=slow-heavy). That disqualifies them for `search_rank_and_curate` (the app's biggest reasoning win) and makes them lateral moves elsewhere. luna is the future volume-tier candidate — revisit when dated snapshots + published pricing appear.
3. **Everything else unchanged**: nano volume tier, 5.4-mini (reasoning off) mid tier, gpt-5.5 keeps rank (`high`) and `qa_history_formulate_answer` (medium) pending a dedicated quality pass; `claude-haiku-4-5` (200K, 66 tok/s) offers no edge over the OpenAI volume tier; `claude-opus-5`/`claude-fable-5` are premium thinking tiers reserved for future Echo "speak as me" quality work.

**Two provider-quirk fixes shipped alongside (live-probe catches):** (a) Anthropic requires `temperature=1` when thinking is enabled — the builder now forces it; (b) Claude 5-generation models reject `thinking.type=enabled`/`budget_tokens` and require `thinking.type=adaptive` + `output_config.effort` — the reasoning mapping is now generation-aware (legacy budget shape retained for Claude ≤4.x).

**Alternatives considered.** Adopting sonnet-5 for refine/reduce too (rejected — 5.4-mini at 88 tok/s reasoning-off is faster and cheaper for mechanical compression, and was just stabilized in PR #196); adopting gpt-5.6-luna for map/classify now (rejected — undated preview, unknown pricing, no track record); opus-5 for rank (rejected — thinking-on default costs 26.7s/call latency where rank runs mid-pipeline).

**Consequences.** The app is now genuinely multi-provider in production defaults (OpenAI volume/mid + Anthropic user-facing synthesis). BYOK Studio users' Anthropic keys now cover the highest-value calls. Rollback of any single site is one `LLM_USE_CASE_CONFIG` env line.

**Re-evaluation hooks.** Re-run the bench battery when gpt-5.6 gets dated snapshots; A/B `qa_history_formulate_answer` on sonnet-5; consider `claude-fable-5`/`claude-opus-5` for E-3.4 "speak as me" when it ships.

**Linked initiatives / PRs.** I-1 / E-1.12 follow-on / D-052. PR: this branch's PR.

---

## D-054 — Per-user LLM overrides + cost calculator; gpt-5.6 adaptive-reasoning findings (2026-07-29)

**Status:** accepted.

**Context.** The user asked to expose per-use-case model settings (provider/model/reasoning) in user settings with DB-backed overrides that dynamically supersede registry defaults, plus a cost calculator benchmarked on the real 200-video job with current cross-provider pricing; and to investigate why gpt-5.6 emitted no reasoning tokens in the D-053 bench.

**Decision.**

1. **Override architecture:** new `user_llm_overrides` table (one row per user x use case, Alembic `b2c3d4e5f6a8`); `resolve_config` gains a top-precedence per-user layer via a ContextVar populated inside `llm_service.byok_context` — piggybacking on the D-041 pattern means every user-scoped LLM entry point (routers + Celery tasks) gets override coverage with zero new call-site changes. Load failures degrade to defaults. REST surface: `GET/PUT/DELETE /api/v1/settings/llm[...]` + `POST /api/v1/settings/llm/estimate`; UI at `/account/ai-models`.
2. **Cost calculator:** `model_pricing.py` (researched 2026-07-29 from the three official pricing pages, source URLs inline; includes OpenAI >272K long-context tiers, sonnet-5 intro-pricing note, Gemini 200K tiering) + `cost_estimator.py` whose workload formulas mirror the SHIPPED pipeline mechanics (model-window-derived map batches, tournament rank rounds, measured QA token actuals) against the job-0d4db8c3 benchmark (200 videos / 947,239 words) plus assumed interactive usage. Unknown-pricing models are flagged, never guessed.
3. **gpt-5.6 verdict (research + 40 probes): the adapter was NOT broken — the 5.6 family reasons ADAPTIVELY.** `reasoning_effort` is a ceiling; an internal router decides per request (easy prompts → 0 tokens at any effort; hard prompts → real reasoning on both API surfaces). Public record: three-tier family launched 2026-07-09 (sol flagship, terra =5.5-at-half-price, luna fast/cheap); new `xhigh`/`max` levels, `max` being Responses-API-only and the only forced-reasoning level. Zero-reasoning-tokens must not be used as an adapter-health signal.
4. **Adapter fixes from the findings:** (a) `off` now sends explicit `reasoning_effort="none"` on gpt-5.x — an OMITTED param defaults to medium adaptive (measured 89 hidden reasoning tokens on a trivial gpt-5.5 prompt), so our volume tier was silently paying thinking tokens; (b) `minimal` remaps to `low` (removed from the 5.5/5.6 enum — was a hard 400 for operators); (c) a Responses-API path for guaranteed `max` reasoning on rank is filed as follow-up, not shipped.

**Consequences.** Users self-serve model choice per function with immediate effect and cost preview; the registry stays the default layer; SaaS BYOK users can point expensive use cases at their own keys/models. Pricing is a static researched table with an `as_of` stamp — staleness is visible and re-research is cheap.

**Re-evaluation hooks.** Refresh `model_pricing.py` when sonnet-5 intro pricing lapses (2026-09-01) or any provider reprices; consider gpt-5.6-luna ($1/$6, fastest measured) for the volume tier after a dated snapshot lands; Responses-API `max` for `search_rank_and_curate`; Gemini adoption per the bench (windows to be recorded when the bench lands).

**Linked initiatives / PRs.** E-1.13 (new). PR: this branch's PR.

**Amended 2026-07-29 — Gemini bench landed (S-1.13.7).** Findings from the live models.list + bench run on our key:

1. **The key is FREE TIER, and since April 2026 all Gemini Pro models are paid-only** — every Pro probe (3.1-pro-preview, 3-pro-preview, 2.5-pro) returned 429 with `limit: 0` RPM/RPD. Free-tier flash quota observed: 250K input tokens/min/model, which also makes the advertised 1M window unverifiable end-to-end (a 1.1M-token probe was quota-rejected before reaching the context validator). Practical free-tier per-request ceiling: ~250K input tokens.
2. **Windows recorded** (models.list metadata): all current flash/pro text models report 1,048,576 in / 65,536 out. Added to `MODEL_CONTEXT_WINDOWS` with the free-tier caveat inline.
3. **Bench (4 usable models):** `gemini-3.5-flash-lite` / `gemini-3.1-flash-lite` are excellent volume-tier fits — ~1.3 s round-trips, 147–169 tok/s, flawless bare-JSON discipline, 3/3 planted-fact recall, no thinking by default. `gemini-3.6-flash` thinks by default and burned 2,397 thought tokens to emit 99 (24×) — usable for mid-synthesis only with effort pinned low. `gemini-3.5-flash` similar but thinking is fully disableable.
4. **Adapter fix:** Gemini 3.x replaced integer `thinking_budget` with `thinking_level` (low/medium/high); the two can't be combined, and `thinking_budget=0` is a hard 400 on 3.6-flash and 3.5-flash-lite. `_google_reasoning_kwargs` is now generation-aware: 3.x → `thinking_level` (or omit entirely for `off`); 2.x → legacy `thinking_budget`. Construction falls back without reasoning kwargs if the installed langchain-google-genai predates `thinking_level`.
5. **Adoption stance:** flash-lite is approved for user-override volume use cases now (free today, $0.30/$2.50 paid); flagship-tier Gemini (3.1-pro) is blocked until a paid billing account exists; do not route p95-45K-input use cases at free-tier Gemini at concurrency (250K/min quota).

**Amended 2026-07-29 (II) — paid Tier 1 activated and validated.** Billing landed on project `my-project-7282026` (Tier 1 Prepay); the first key placed was from the old free-tier project — diagnosed via AI Studio's per-key billing column. Two systemic findings and the paid-tier profile:

1. **Machine-level env vars shadow `backend/.env`** (pydantic-settings precedence): Windows-level `GOOGLE_API_KEY` (old free key) and `OPENAI_API_KEY` (a different account than `.env`'s!) were silently overriding the project's keys — all prior OpenAI spend went to the OS-level key's account. Fix: `start.ps1` / `restart_services.ps1` now clear any inherited env var that `backend/.env` defines before spawning services; `.env` is authoritative for the app. Standalone scripts must load keys via `dotenv_values`, not `os.environ`.
2. **Window verified end-to-end:** a 1,119,838-token prompt to gemini-3.1-pro was rejected with the API naming the exact limit **1,048,576** (unbilled). Paid quota lift confirmed: a single 295K-token request to 3.6-flash processed in 3.8s (this exact size 429'd on free tier), and 475K tokens to 3.5-flash-lite in 2.95s — both with correct end-planted-fact recall. Long-context ingest latency is a non-issue on the flash family.
3. **gemini-3.1-pro bench:** 32 visible tok/s long-form (103 incl. thoughts) — ~half of claude-sonnet-5; perfect JSON discipline and 3/3 needle recall; thinking is **mandatory** (`thinking_budget=0` → 400 "This model only works in thinking mode"; `minimal` → 400; `low` is the floor) and **thoughts deduct from `max_output_tokens`** (a 200-token cap died mid-array after 193 thought tokens — size caps as answer + 200–1600 thoughts headroom). Omitting `thinking_config` triggers dynamic thinking that spent MORE than explicit `high` (628 vs 473 thoughts) — always pin the level; the adapter now maps `off` per-model (Pro/3.6-flash → `low` floor, 3.5-flash → `budget=0`, lite → omit).
4. **Verdict:** 3.1-pro is a reasoning-shaped short-output engine, not a flagship synthesis model — the ~1.5K mandatory thought tokens on a 600-word answer add latency and ~2.2× billed output on every user-facing call, so claude-sonnet-5 keeps user-facing synthesis (D-053). Best trial fit: `search_rank_and_curate` (always-on thinking suits ranking; `thinking_level=high`) and possibly `qa_refine_context` at `low`.
5. **Tier-1 rate limits are dashboard-only:** Google removed per-model tables from the docs — [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit) is the only authority (unofficial prior-generation references: Pro-class ~150 RPM / ~1M input TPM, Flash-class ~300 RPM / ~2M TPM). Check the dashboard before committing Gemini to a high-concurrency use case.

---

## D-055 — Intelligence-delta evaluation methodology: production-input replay + blind A/B judging (2026-07-29)

**Status:** accepted (methodology). Results in flight — see [E-1.14](initiatives.md#e-114--model-tier-quality-evaluation-harness).

**Context.** The app routes 20 named use cases across a deliberately mixed model stack (`gpt-5.4-nano` for volume, `gpt-5.4-mini` for mid-tier, `gpt-5.5` for ranking, `claude-sonnet-5` for user-facing synthesis — D-052/D-053), and E-1.13 now lets users override every one of them. But every tier decision to date rested on *proxy* evidence: latency benches, context-window measurements, JSON-discipline probes, and reasoning about task shape. Nothing measured the thing that actually matters — **how much answer quality the cheap tiers give up on our real corpus**. The user asked for exactly that: run the same functions over the same data with a maximum-capability model and quantify the delta.

**Decision.** Measure per-use-case intelligence delta by **replaying a real completed job's exact LLM inputs** through frontier models at maximum thinking, then **blind A/B judging** the results against the outputs production actually stored.

Four properties make the comparison honest:

1. **Exact-input replay, not re-execution.** Inputs are rebuilt deterministically from stored job state using the app's own code paths — same chunker and settings, same `[title | channel | timestamp]` formatting, same model-derived batch budget, same job-scoped retrieval collection. For job `0d4db8c3` this reproduced 5,149 chunks across 12 batches of ≤120K tokens. The challenger sees byte-comparable input, so the only variable is the model.
2. **Verbatim prompt templates.** Challenger agents read the app's real prompt templates out of `app/agents/prompts/*.py` and apply them unchanged, including the output-format contract. They are instructed to emit only what the model would emit — no meta-commentary — so artifacts are directly comparable.
3. **Blind judging with hidden orientation.** A blinding step coin-flips each pair into `A`/`B` copies and writes the mapping to a file the judges never read. Judges are told explicitly not to guess provenance and to discount verbosity and confident tone.
4. **Grounded verification, not vibes.** Judges verify claims against ground truth rather than scoring impressions: Q&A judges re-query the live corpus through the same retrieval path and check whether cited videos actually support sampled claims; knowledge judges verify claims against the raw transcript and hunt fabrications; a non-blind map-fidelity auditor scores extraction against source batches and then lists specific facts the max-effort extraction captured that are **absent from the production report** — direct evidence of pipeline loss.

**Execution note.** The challenger fleet runs as **Claude Code subagents on the interactive subscription**, deliberately not through `ANTHROPIC_API_KEY`. This keeps a large-fleet evaluation off the metered API budget. The trade-off is real: subscription rate limits interrupt long runs (this experiment was cut twice), so the harness must be **restart-safe** — artifacts are written to disk per agent, disk state is inspected before any resume, and judging is ordered *before* expensive replication so partial runs still yield the answer. A corollary discovered the hard way: a killed agent may leave a **truncated JSON file**, so every replayed artifact must be parse-validated before use, never trusted by existence.

**Alternatives considered.**

- *Re-run the whole job through the app with overrides pointed at a frontier model.* Rejected: costs a full ingest, and non-determinism in search/approval means the corpus would differ, confounding model delta with corpus delta.
- *Synthetic benchmark suites (HELM-style, lm-eval-harness).* Rejected: they measure general capability, not fit for these prompts on this corpus. The whole question is domain- and pipeline-specific.
- *Human evaluation.* Rejected for now: not scalable to 20 use cases, and the artifacts (a 62KB report, 15KB cited answers) are too long for quick human A/B.
- *Judge with the same model family that produced one side.* Avoided where possible; the judging model is held constant across every comparison so any residual self-preference bias applies uniformly rather than favoring one artifact.

**Consequences.** Establishes a repeatable way to answer "is this use case under-modeled?" with evidence instead of intuition, and the per-use-case verdicts feed directly into `USE_CASE_REGISTRY` defaults and the E-1.13 override guidance. It also surfaced a structural blocker: **the app discards map/reduce intermediates and rejected search candidates**, so intermediate-stage quality is only measurable by replay, and selection quality cannot be re-scored at all (see [architecture.md §Agent-intermediate retention gap](architecture.md#agent-intermediate-retention-gap-identified-2026-07-29)). Persisting those artifacts is the prerequisite for continuous monitoring rather than one-off audits.

**Caveats to carry into any conclusion drawn from this run.** (a) Challenger artifacts are mixed-provenance — Q&A and knowledge replication ran on Claude Fable 5, the report chain on Claude Opus 5 after a limit switch; both are frontier-tier at max effort, but per-artifact provenance must be labelled, not averaged away. (b) Q&A replay consumes the *production-generated* report as context exactly as production does, which mildly favors the defaults. (c) `search_rank_and_curate` cannot be replayed at all (rejected pool not persisted), so it is assessed as a criteria-conformance audit of the 200 surviving picks rather than a head-to-head.

**Linked initiatives / PRs.** [E-1.14](initiatives.md#e-114--model-tier-quality-evaluation-harness); realizes invention [N-001](inventions.md#n-001--production-replay-blind-delta-harness-for-per-call-site-model-tier-selection-2026-07-29). Feeds D-052 / D-053 / D-054 re-evaluation.

**Results — 2026-07-29 (E-1.14 first run complete).** Six blind comparisons on job `0d4db8c3`; the max-effort challenger won all six (gaps: 1 severe, 4 moderate, 1 minor). Mean judge scores, app → challenger: report **3.5 → 8.5**, knowledge-short 5.8 → 9.0, knowledge-long 7.0 → 8.4, Q&A-context-engineering 5.8 → 8.5, Q&A-patterns 7.2 → 7.7, query-plan 5.6 → 7.8.

**The headline is structural, not intelligence.** The shipped report for that job cites **2 distinct channels** (Sam Witteveen 73×, Cole Medin 66×) across all 139 attributions, and only **4 of 200** corpus video titles appear anywhere in it — while its own executive summary claims to synthesize 137 videos. The map-fidelity audit found **60 of 60** checkable facts from two sampled batches absent from the report (100% loss). Independently verified, not judge-reported.

Root cause is an unsized information funnel, and it is model-independent:

| Stage | Cap | Effect on job `0d4db8c3` |
|---|---|---|
| map | `max_tokens=3000` × 12 batches | ≤36K tokens emitted from 1,393,656 tokens of transcript — **5.9%** of what max-effort extraction produced (608,718 tokens / 5,861 items) |
| reduce | `max_tokens=6000` per merge, every round | collapses to ≤6K tokens |
| compose | reads ≤6K, writes ≤16K | **0.43%** of source tokens reach the writer |

Two compounding defects: (a) `report_map_chunks` is registered with `p95_input=32,000` but E-1.12 raised real batches to ~116,000 — **3.6× the sizing assumption** — while `max_tokens=3000` never moved, so the context-window fix pushed *more* information through an unchanged aperture; (b) a control experiment over all 12 batches found **zero duplicates** within `(category, video)` — no exact, substring, or Jaccard≥0.90 matches — so on this corpus *any* item-count reduction in reduce is pure content loss, not deduplication. The cheap default's loss was also non-uniform: it dropped whole videos (46% of videos vanished in the 7-batch control) rather than compressing evenly.

A perfect lossless consolidation measures 369,801 tokens against `compose`'s effective budget of 120,000 (`_QUALITY_BATCH_CAP`), so the architecture genuinely requires ~3× compression — but the shipped pipeline performed ~11×. Note `compose` resolves to `claude-sonnet-5` (1M window); the 120K cap is the only binding constraint and is self-imposed.

**Where model tier genuinely matters** (independent of the funnel): signal density in knowledge synthesis (9 vs 5 and 9 vs 4 — the challenger identified speakers and preserved quantitative findings the default dropped) and synthesis-vs-enumeration in Q&A (a judge characterized the default's answer as "an annotated bibliography"; on one question the default scored 4/10 on completeness by answering half the question). **Where the default is better:** citation hygiene — it scored 8 vs 6 on one Q&A pair because every citation resolved to a real seekable timestamp while the challenger degraded three into unlinkable report references.

**Method caveats that bound these numbers.** (a) The production report was generated when only 137/200 videos had transcripts (495,847 words) while the replay used the recovered 200-video corpus (1,057,331 words) — the report margin is inflated by roughly 2× more material, though the 2-channel collapse is independent of corpus size. (b) Q&A replay is mildly challenger-favored for the same reason (retrieval now spans 200 videos). (c) Knowledge extraction and query planning used identical inputs and are clean comparisons. (d) The full-corpus `reduce` was executed **deterministically over the corpus rather than free-running token emission** — hand-emitting 5,861 items would itself have introduced the silent truncation under measurement — so the report comparison measures *ideal pipeline vs shipped pipeline*, not *big model vs small model*. (e) Challenger provenance is mixed: Q&A and knowledge on Claude Fable 5, report chain on Claude Opus 5 after a subscription-limit switch.

**Two corpus traps found in passing.** All 5,861 map items carried an **empty `video_url`** (chunk headers don't include URLs), so timestamp citations cannot link without a downstream join against `documents`. And the corpus holds two pairs of distinct videos whose titles differ only in letter case (`The Best LOCAL…` / `The Best Local…`, `Context Engineering…` / `Context engineering…`) — any step keying identity on `video_title` case-insensitively undercounts by 2.

## D-056 — Report pipeline: budgets derived from work, lossless reduce, sectioned compose (2026-07-30)

**Status:** accepted.

**Context.** [D-055](#d-055--intelligence-delta-evaluation-methodology-production-input-replay-blind-ab-judging-2026-07-29) measured the report pipeline losing ~99.6% of its source material: a 200-video job produced a report citing 2 channels out of 92 and 4 videos out of 200, with zero quantitative claims, while asserting it synthesized 137 videos. Blind judging scored it 3.5/10 against a max-effort control at 8.5. The user approved fixing the funnel first (it is model-independent and cheaper than a tier upgrade), and added a requirement: **report size should scale with the amount of information the corpus actually yielded**, comparable to the depth seen in per-video knowledge extraction.

**Decision.**

1. **Completion budgets derive from the work, not constants.** New `MODEL_MAX_OUTPUT_TOKENS` in the registry (measured 2026-07-30 with the same free oversized-request technique as the input windows: **128,000** for gpt-5.4-*/5.5 and claude-sonnet-5/opus-5/fable-5; 64,000 for claude-haiku-4-5). `report_map_chunks` now requests `batch_tokens x 0.20` clamped to that ceiling — ~24,000 for a 120K batch, versus the hardcoded 3,000 that discarded ~94% of extractable content. `knowledge_synthesize_report` scales with its merged extraction instead of a flat 8,000.
2. **Reduce is deterministic and lossless.** The recursive pairwise LLM merge is gone. D-055's control found **zero duplicates** in map output — no exact, substring, or Jaccard>=0.90 matches — so "merge and deduplicate" could only destroy content while a flat 6,000-token cap applied every round. Reduce now performs a structural union collapsing only byte-identical items; the same claim from a different source is distinct attribution and is kept. Compression runs only past a 1,000,000-token cost guard, and then **per-video evenly** so no video is dropped wholesale (the old path lost 46% of videos outright).
3. **Compose is sectioned.** One call per report section, each split further into as many calls as its material needs, so total report length tracks corpus size instead of being clipped by a single completion cap. The Statistics section is rendered **deterministically in code** — the LLM-written version undercounted the corpus by 31.5% and dropped ~20 channels. The executive summary is composed last, from what was actually written, and is instructed not to claim breadth the body lacks.
4. **Accounting.** Reduce trimming, failed sections, and map drops all surface as a processing note in the report itself, not only in worker logs.
5. **Reasoning raised low->medium** on `qa_formulate_answer` and `library_qa_formulate_answer`. D-055 scored these 4/10 on completeness and synthesis ("an annotated bibliography"); measured output stayed under the old 4,500-token cap, so the gap was synthesis depth, not budget.

**Two live bugs found and fixed while validating.**

- **Reasoning models return content BLOCKS, not a string.** With thinking enabled, Anthropic returns `[{"type":"thinking",...},{"type":"text",...}]` — but only once the model actually thinks, so the shape flips per request and trivial prompts still return a string. Every call site read `response.content` directly, so composition would have written a stringified Python list into the report and the JSON call sites would have failed to parse — silently, and specifically on the hardest prompts. D-053 moved these sites to claude-sonnet-5 and no report had run since, so this was latent in production. Fixed centrally with `llm_service.response_text()`, applied at all 18 response-reading call sites.
- **Every timestamp citation in every report was a dead link.** `MAP_CHUNK_PROMPT` asks each extracted item for a `video_url`, but the chunk header passed only `[title | channel | timestamp]` — no URL was ever supplied, so citations rendered as `href="&t=123"`. The header now carries the URL (~12 tokens/chunk), and composed HTML is post-processed to unwrap any anchor whose href is not a real URL, preserving the timestamp label as text.

**Consequences.** Report cost rises with corpus size by design — map emits ~8x more per batch and compose makes ~9 calls instead of 1 for a 200-video job. That is the point: the previous cost was low because the pipeline was discarding the corpus. `report_reduce_summaries` remains in the registry (so existing overrides keep resolving) but no longer performs an LLM call on topic jobs; its rationale records this.

**Validation.** Reduce over the real 12 map extractions of job `0d4db8c3`: **5,861 items in, 5,861 out, 0.00% loss, all 200 videos and 92 channels retained** (previously 91.2% of items and 46% of videos lost), zero LLM calls. A real compose call over a cross-corpus sample of 190 facts produced 6,903 words naming 34 distinct channels — versus 3,848 words and 2 channels for the entire shipped report. Full production chain end-to-end on 6 videos: **104 timestamp links, 104 working, 0 dead, 6/6 videos correctly linked, 0 fabricated**. Backend suite 1,132 passing.

**Linked initiatives / PRs.** S-1.14.8, S-1.14.9; supersedes the reduce mechanics of S-1.12.3.

## D-057 — Volume tier moves to gpt-5.6-luna; selection is now measurable (2026-07-30)

**Status:** accepted.

**Context.** On 2026-07-30 OpenAI cut gpt-5.6-luna by 80% and terra by 20%. Verified on the official pricing page (not the announcement): **luna $0.20 / $1.20**, terra $2.00 / $12.00, both with >272K long-context tiers. Luna therefore *matches* `gpt-5.4-nano` on input ($0.20) and *undercuts* it on output ($1.20 vs $1.25) — our economy tier could get strictly better at no cost. Vendor benchmarks measure generic intelligence, so we tested on the job we actually give it.

**Decision.** All nine `gpt-5.4-nano` sites move to `gpt-5.6-luna` at the same reasoning level. The default stack is now three tiers: **luna** (volume) / **gpt-5.4-mini** (mid) / **gpt-5.5** + **claude-sonnet-5** (flagship).

**Evidence** — head-to-head on two real 120K-token map batches, same prompt and completion budget:

| Batch (true videos) | Model | Items | Distinct titles | JSON | Time | Cost |
|---|---|---|---|---|---|---|
| batch_03 (25) | gpt-5.4-nano `off` | 133 | **52** | ok | 100s | $0.0420 |
| batch_03 (25) | **luna `off`** | **212** | **25** | ok | 78s | $0.0418 |
| batch_03 (25) | luna `high` | 0 | — | **FAILED** | 129s | $0.0523 |
| batch_07 (17) | gpt-5.4-nano `off` | 0 | — | **FAILED** | 127s | $0.0460 |
| batch_07 (17) | **luna `off`** | **284** | 15 | ok | 109s | $0.0487 |
| batch_07 (17) | luna `high` | 246 | 16 | ok | 107s | $0.0476 |

Three findings drove the call: (a) luna extracts **1.6-2x more items** at parity cost and lower latency; (b) its **attribution is exact** — 25 distinct titles for a 25-video batch, where nano emitted **52 title variants of the same 25 videos**, fragmenting citation grouping (neither model fabricated: 0% of titles were outside the corpus); (c) **nano returned unparseable JSON on one of two batches**, which in production triggers bisect-retry — double cost and possible content loss.

**Luna must stay at `reasoning=off` for extraction.** At `high` it spent all 24,000 completion tokens thinking and emitted nothing (batch_03) — the OpenAI gotcha where `max_completion_tokens` includes reasoning tokens, which has now bitten three times (T-4.9.5, PR #196, here).

Measured `MODEL_MAX_OUTPUT_TOKENS` for the 5.6 family (128,000 each). Without this luna fell through to the conservative 4,096 default and would have silently clamped the map budget.

**Cost calculator corrected.** It still modelled the pre-D-056 pipeline (2,000 output tokens/batch, one compose call). Updated to the shipped behaviour: map output derives from the batch, reduce is $0 (deterministic), compose is sectioned. The benchmark job moves **$4.36 → $5.88** — reports cost more because they no longer discard the corpus.

**Consequences.** Caveat: n=2 batches. The signals (a hard JSON failure, 2x attribution variance, 1.6-2x yield at equal price) are strong enough to act on, and any user can revert per use case from `/account/ai-models`. Re-measure when the next model lands.

**Linked initiatives / PRs.** S-1.14.6, S-1.14.12; follows D-056.

## D-058 — Report pipeline fix validated on the reference job (2026-07-30)

**Status:** accepted.

**Context.** [D-056](#d-056--report-pipeline-budgets-derived-from-work-lossless-reduce-sectioned-compose-2026-07-30) fixed the report funnel but was validated only at component level. The report for job `0d4db8c3` was regenerated through the production path (same 200 videos, same 5,149 chunks, same criteria) for a direct A/B against the 2026-07-22 report.

**Result** — 41.5 minutes, 7 section calls, 0 failed:

| Measure | Before | After |
|---|---|---|
| Body words | 5,610 | **25,692** (4.6x) |
| Videos linked | **0** | **125** |
| Corpus titles mentioned | 4 | 38 |
| Channels named | 67 | **92 / 92** |
| Timestamp links | 143, **all dead** | 1,058, **0 dead** |
| Quantitative claims | **0** | **130** |
| Sub-sections (h3) | 9 | 82 |

Reduce logged `lossless merge fits (217,115 tokens); 1,451 items across 119 videos, 0 LLM calls` — the stage that previously squeezed everything through a flat 6,000-token cap.

**Residual gap.** Coverage is 125/200 videos, not 200 — because *map extraction* covered only 119 videos. That run used gpt-5.4-nano; per [D-057](#d-057--volume-tier-moves-to-gpt-56-luna-selection-is-now-measurable-2026-07-30) luna extracts 1.6-2x more items with exact attribution, so the next run should improve further. The binding constraint has moved from the pipeline to the extraction model, which is the correct place for it to be.

**Linked initiatives / PRs.** S-1.14.10 (partially answered), S-1.14.8.


## D-059 — Selection quotas: preferred-channel guarantee + concentration cap (2026-07-30)

**Status:** accepted.

**Context.** S-1.14.6 made selection measurable for the first time by persisting the rejected candidate pool. A fresh search on the reference criteria captured **651 candidates -> 200 selected / 451 rejected**, and the rejects indicted the ranker: only **12 of 29** resolvable preferred channels reached the corpus, while **14 of the 18 missing ones had candidates sitting in the rejected pool** (@fireship 7, @matthew_berman 7, @theprimetimeagen 7, @openai 6, @dwarkeshpatel 5 ...). Meanwhile **IBM Technology - not a preferred channel - took 10.5%** of the 200 picks. This was not a discovery failure: the videos were found, then discarded.

Critically, `RANK_AND_CURATE_PROMPT` *already* instructs the model to prefer preferred-channel videos. It does not comply reliably. A prompt cannot make a guarantee.

**Decision.** Enforce two selection invariants deterministically, after ranking:

1. **Preferred-channel guarantee** - every preferred channel with at least one candidate gets a slot, taking that channel's best-ranked video. Quotas draw from the FULL pool, not the post-tournament survivors, because a preferred channel can be eliminated in an early round.
2. **Concentration cap** - no channel exceeds `max(3, 8% of target)`. If too few channels exist to fill the target under the cap, it relaxes rather than under-delivering.

Merit ordering remains the model's; quotas only reserve slots and cap crowding. `rank_and_curate` now also preserves the model's returned ORDER (the previous code returned pool order, silently discarding the ranking signal).

**Measured effect on the real 651-candidate pool:**

| | Before | After |
|---|---|---|
| Preferred channels covered | 12 / 29 | **29 / 29** |
| Largest channel share | 21 (10.5%) | **16 (8.0%)** |
| Distinct channels | 86 | **103** |

**Shorts filter - scoped down by measurement.** Sub-120s clips are pruned when the user set no duration floor of their own, because they survive ranking on engagement signals and carry a few seconds of transcript. **Preferred channels are exempt**: applying the floor to them too cost **6 of 29** preferred channels their only candidates in exchange for ~6% more corpus minutes. An explicit "include this creator" outranks an inferred "prefer substantive".

**Rejected: the non-English title filter** originally scoped in T-1.14.13.4. It contradicts the product's deliberate multilingual design (multilingual embeddings, `task="transcribe"` preserving the speaker's language, an `answer_language` parameter). Filtering non-English candidates at search time would silently undo that.

**Consequences.** Selection is now measurable *and* enforced. Three existing ranking tests asserted byte-equality with the model's returned ids; they encoded the pre-quota contract and were updated (their fixture puts 1,000 videos on 7 channels, so the cap necessarily reshuffles).

**Linked initiatives / PRs.** S-1.14.13; enabled by S-1.14.6.

## D-060 — Extraction ratio raised 0.20 -> 0.40 (2026-07-30)

**Status:** accepted.

**Context.** D-056 replaced hardcoded completion caps with budgets derived from the work, using `_MAP_EXTRACTION_RATIO = 0.20` - deliberately below the E-1.14 max-effort control's measured 44%. Reviewing the full picture after D-057, that choice was itself a ceiling: 0.20 caps a 200-video run at **288,000 extraction tokens against the control's 608,718**, so even a perfect model could emit less than half of what the corpus supports. That is the same class of defect D-056 set out to remove, re-introduced one layer up.

It was invisible while `gpt-5.4-nano` was the volume model (it produced ~217K, under even its 288K allowance - model-limited, not budget-limited). Moving to `gpt-5.6-luna`, which measured 1.6-2x nano's yield, would have made the ratio the binding constraint immediately.

**Decision.** Raise to **0.40** - run ceiling 576,000 tokens, effectively matching the control. Still below 0.44 so we are not paying for exhaustive restatement. At Luna's $1.20/M output this costs ~**$0.34** on the 200-video benchmark; the full benchmark estimate moves **$5.88 -> $7.65**.

**Consequences.** Extraction should no longer be budget-bound; the remaining delta versus the max-effort control is model quality alone. That is the correct place for the constraint, and it makes the pending S-1.14.10 re-judge interpretable - any residual quality gap can now be attributed to the model rather than to plumbing.

**Linked initiatives / PRs.** S-1.14.13, S-1.14.10; amends D-056.


## D-061 — S-1.14.10 re-judge: the intelligence gap after the fixes (2026-07-31)

**Status:** accepted.

**Context.** [D-055](#d-055--intelligence-delta-evaluation-methodology-production-input-replay-blind-ab-judging-2026-07-29) measured the production report at **3.5/10 against a max-effort control at 8.5/10, gap SEVERE**. Every structural cause of that verdict has since changed (D-056 funnel fix, D-057 Luna volume tier, D-060 extraction ratio), so the verdict was re-run on the same 200-video corpus with the same blind method.

**Method.** Production report regenerated end-to-end through the shipped pipeline (48.8 min, `gpt-5.6-luna` @ ratio 0.40, sectioned compose). Blind-paired against the max-effort control, both normalised to plain text and capped at 180,000 chars so neither wins on medium or length. **Three independent judges** on different lenses (coverage/breadth, factual rigour with live retrieval, synthesis/insight) plus a mechanical citation-integrity audit. Orientation hidden from all four.

**Result — the gap narrowed from SEVERE to MODERATE, unanimously.**

| Lens | Production | Max-effort |
|---|---|---|
| Coverage / breadth | 7.33 | 9.00 |
| Factual rigour | 7.17 | 8.50 |
| Synthesis / insight | 6.33 | 8.67 |
| **Mean** | **6.94** | **8.72** |

Versus D-055's 3.5 vs 8.5. All three judges picked max-effort, all three classified the gap as `moderate` (was `severe`).

**Pipeline metrics across the four variants** (same corpus throughout):

| Variant | Words | Videos linked | Citations | Dead links |
|---|---|---|---|---|
| Shipped 2026-07-22 (starved) | 5,610 | 0 | 143 | 143 |
| Fixed pipeline + nano | 25,692 | 125 | 1,058 | 0 |
| **Fixed + luna @0.40 (current)** | **30,864** | **185** | **1,489** | 0 |
| Max-effort control | 26,631 | 200 | 946 | 0 |

Extraction went 1,451 items / 119 videos → **3,233 items / 189 videos** from the Luna swap plus lifting our own 0.20 ceiling — roughly 55% of the control's 5,861, up from 25%. Production now exceeds the control on words and citations; it trails on coverage (185 vs 200 videos) and on quantitative density (179 vs 229 percentage claims).

**Zero fabrications in either report.** The audit resolved every title-bearing citation in both against the 200-video corpus; the only near-misses were inexact renderings of real titles.

**What actually remains — three fixable defects, none of them model capability:**

1. **Inline attribution (6 vs 9).** 75% of production's citations render as a bare `( 12:34 )` with no source named in the visible text. NOTE: this is not broken citation — all 1,489 anchors carry a correct video URL, and the control's anchors are *also* 100% bare timestamps; the control simply writes `Title — Channel · mm:ss` in the prose beside each one. Production even names more distinct channels overall (92/92 vs 91/92). This is a `COMPOSE_SECTION_PROMPT` wording fix.
2. **Source-by-source digest instead of cross-source synthesis (5 vs 9 on insight).** Production's Key Facts are organised per channel ("Cole Medin's workflow", "IndyDevDan: ..."), which preserves fidelity but leaves cross-video comparison to the reader. The control organises into themes and then into named debates with each side given its strongest cited voice. Also a prompt fix.
3. **No retry on transient provider errors.** The Speaker Contributions section was lost to an Anthropic `529 Overloaded`. The accounting worked — the failure was logged and disclosed in the report footer rather than shipping a silently short report — but compose should retry 5xx with backoff before giving up.

A judge also flagged that production mis-states the corpus size and vintage in its framing, and garbles several proper names in its reference section.

**Consequences.** The claim "the defaults are far behind a premium model" is no longer supported: on identical input the measured mean is 6.94 vs 8.72, and the three remaining defects are prompt/retry work rather than model tier. Whether to close the rest by prompt work or by moving `report_compose` up a tier should be decided AFTER the prompt fixes, since two of the three gaps are addressable for free.

**Linked initiatives / PRs.** S-1.14.10 (closed), S-1.14.14 (new); follows D-056 / D-057 / D-060.


## D-062 — `report_compose` upgraded to claude-opus-5 (2026-07-31)

**Status:** accepted.

**Context.** [D-061](#d-061--s-11410-re-judge-the-intelligence-gap-after-the-fixes-2026-07-31) left three residual defects, all judged prompt/retry rather than model capability. S-1.14.14 shipped fixes for all three and the report was regenerated and re-judged on the same corpus.

**What the prompt fixes moved — and what they did not.**

| Lens | v2 | v3 (after fixes) | Control | Gap |
|---|---|---|---|---|
| Coverage | 7.33 | **8.00** | 8.67 | moderate → **minor** |
| Rigour | 7.17 | 7.33 | 8.67 | moderate |
| Synthesis / insight | 6.33 | **6.33** | 8.67 | moderate |
| Overall | 6.94 | **7.22** | 8.67 | |

Attribution flipped outright: **6 → 9, now ahead of the control's 7** — a judge who had called production untraceable now preferred it for chasing a claim back to its video. Mechanically: citations with a source named nearby went 30% → 63%, sub-sections named after a channel 16% → 7%, corpus titles mentioned 3 → 139 of 200. The retry fix held (7 sections, 0 failed, where a `529` had previously eaten one).

**Synthesis did not move at all — 6.33 in both rounds.** That is the diagnostic result. The v2 round predates the new citation formatting, so verbosity cannot explain it, and theme-first structuring did not shift it either. Prompt work moved everything it could; this was the residue.

**Decision.** `report_compose` moves `claude-sonnet-5` → `claude-opus-5` (reasoning medium), per the rule recorded in S-1.14.14 **before** results were seen.

**Evidence — head-to-head, identical section input (340 comment items, 36K tokens), two blind judges:**

| Dimension | sonnet-5 | opus-5 |
|---|---|---|
| Synthesis | 6-7 | **9** |
| Tension handling | 6 | **9** |
| Signal density | 6-6.5 | **9** |
| Specificity | 5.5-6 | **9-10** |
| Grounding | 7 | **8.5-9** |
| Readability | **7.5-8** | 7 |

**The length hypothesis was tested and REJECTED.** Opus ran 2.6x longer, and the prior that this was padding is the obvious objection — so both judges were instructed to suspect it and to count claims per unit length. Both found opus *denser*: hand-counted propositions across three matched sections gave 3.42 vs 2.42 per 100 words; an independent proxy (citation anchors per 1,000 words) gave 21.2 vs 17.7. Roughly **3.5x total informational payload**, not 2.6x the words.

Concrete failures that decided it: sonnet named **18 distinct tools/models vs opus's 47** and 4 numeric specifics vs 11; dropped roughly **8 debates present in the corpus**; **contradicted itself** — declaring "a near-consensus emerges that context engineering has displaced prompt engineering" while itself holding the rebuttal quote (Zen van Riel calling the terms "largely gimmicks") filed two sections earlier under the wrong argument; and **invented two unverifiable host names** where opus correctly hedged to "the Google Cloud Tech hosts".

**Cost.** `report_compose` $3.03 → $7.58; benchmark total **$7.65 → $12.20** (+$4.55 per 200-video job). This is the most expensive single change available in the stack, which is why it was made last and only on measurement.

**Consequences.** sonnet-5's one win is readability (8 vs 7) — a real trade, accepted because a 3-point synthesis gap on the flagship deliverable outweighs it. Any user can revert per use case from `/account/ai-models`. Note the ordering that made this decision cheap and correct: the funnel fix, volume-tier swap, extraction ceiling and prompt fixes all landed FIRST, so the tier premium buys only what nothing else could.

**Open, deliberately not fixed here.** The executive summary still mis-dates the corpus ("2024-2025-era" when the bulk is 2026), leaks pipeline metadata into prose, and contradicts its own video count in Conclusions — T-1.14.14.4 did not fully land. Filed as S-1.14.15 rather than bundled, so the tier decision is not confounded by a simultaneous prompt change.

**Linked initiatives / PRs.** S-1.14.14 (closed), S-1.14.15 (new); follows D-061.


## D-063 — Per-user isolation: shared cache, private catalogue (2026-07-31)

**Status:** accepted.

**Context.** Requirement: work done by one user must not be visible to another user in any section of the app. An audit found this was not true, and the gap was not a missing `WHERE` clause — it was a missing ownership model.

`documents`, `transcript_cache`, `job_documents`, `channels` and `job_search_candidates` carry **no tenant column at all**, by design: CLAUDE.md states documents are *never job-owned*, one global deduplicated library with two global Chroma collections, so transcripts, embeddings and knowledge artifacts are computed once and reused across every job and user. That is what makes the economics work — and it is directly incompatible with "no user sees another user's work".

**Five leak classes were live and reproducible against real data.** Demonstrated on the running instance: user `5c2b8dda` browsing the library saw user `d6cdfa65`'s 200-video corpus **and the job topic** `"new AI enhancements around LLM models…"`.

| Leak | Site | Impact |
|---|---|---|
| Library browse | `library.py` `list_library_videos` | Every tenant's documents **plus their job topics** — the topic string being the more sensitive half |
| Cross-tenant delete | `library.py:209` | `db.get(pk)` then delete: any user could **destroy** any other user's Q&A exchange |
| Dataset exports | `routers/exports.py` | Zero `current_user` references; streamed **every** tenant's Q&A and knowledge as fine-tune data |
| WebSocket | `ws.py:52` | Subscribed to any `job_id` sent — another tenant's progress, status and error text |
| **Vector retrieval** | `chroma_service.query_collection` | Library Q&A searched **every tenant's transcripts**; Chroma has no tenant concept so nothing in the query layer could catch it |

**Decision. Shared cache, private catalogue** (option 3 of three offered; the user chose it over full partitioning and over shared-corpus-private-activity).

`documents` remains the global deduplicated store. Visibility is recorded **explicitly** in a new `document_visibility(video_id, tenant_id, source)` table — one grant per (document, tenant). Two users ingesting the same video share the cached transcript and embeddings, each hold their own grant, and neither can see that the other has one.

**Why explicit rather than derived.** The first implementation derived ownership from `job_documents → jobs.tenant_id`, which reads correctly and is wrong: `upload_pdf`, `paste_urls` and channel sync all create documents with **no job**. Job-derived ownership would have made a user's own uploaded PDF invisible to them — trading a privacy leak for data loss. A failing test asserting `job_count == 0` is what surfaced it. Under the explicit model that assertion is now *meaningful*: "I ingested this, no job used it."

`source` (`job` / `pdf_upload` / `paste_url` / `channel_sync`) is recorded per grant so a forgotten ingest path is greppable rather than invisible.

**Implementation notes.**

- Grants are wired at **every** ingest path, including the **dedup hit** on PDF and paste — a cache hit means the bytes exist but *this* tenant may never have seen them.
- The job path grants over the job's **whole current link set** at three phase boundaries rather than at each `JobVideo` insertion: there are two insertion sites today and more will be added per source type, and a missed one silently hides results. Idempotent, so repeated calls are free.
- Retrieval scoping passes the visible set from the router into `run_library_qa_agent`. An **empty** list means "this tenant has ingested nothing" and correctly retrieves nothing — it must never degrade into an unrestricted search, which is the obvious way this would silently regress. There is a test for exactly that.
- The WebSocket ownership check **fails closed** and takes an injectable session factory: it runs in the socket loop with no `Depends(get_db)`, and was otherwise querying the *dev* database during tests.

**Migration.** `d4e5f6a7b8c0` creates the table and **backfills from existing job ownership**: 203 grants written, **0 documents left ungranted**, nobody loses access on deploy. Documents belonging to no job could not be attributed retroactively and would have been left invisible — none existed, but the migration says so explicitly so a different deployment knows to re-grant.

**Consequences.** The library is no longer a shared browsing surface; each user sees only what they ingested. Dedup economics are untouched. Two behavioural changes worth noting: library Q&A now answers from a smaller corpus per user, which may change answer quality on small accounts (worth re-running the D-055 harness later), and `channels` remains unscoped — subscriptions are still global, filed as follow-up.

**Tests.** 11 regression tests asserting the **absence** of foreign data — the only direction that would have caught any of these. Two of them found real bugs in the fix itself: `session_factory()` outside the `try` (a DB blip would have crashed the socket loop rather than denying) and the test-database issue above.

**Linked initiatives / PRs.** E-5.10 / S-5.10.1. Supersedes the library-is-global assumption in CLAUDE.md, which is updated in the same change.

**Amended 2026-10-19: the explicit model never covered non-video sources.** The first frontend caller of `upload-pdf` and `paste-urls` (PR [#224](https://github.com/khoks/VideoResearchPro/pull/224)) found that `document_visibility.video_id` is a foreign key to `documents.video_id`, the legacy YouTube-id column, which is NULL for every `source_type` other than `video`. `visibility_service.grant()` drops falsy ids, so the grants this entry says are "wired at every ingest path, including the dedup hit on PDF and paste" are silently never written for a PDF or a pasted page, and every reader filters on the same column. The migration's "0 documents left ungranted" was true only because no non-video document existed on that instance. In effect the model protected against leaks but delivered the data-loss outcome this entry set out to avoid, for exactly the ingest paths it named. A strict `xfail` pins it; the fix is [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19).

**Amended 2026-10-19 (II): three reads the five leak classes did not list.** Auditing every `documents` reader after D-070 merged found reads that never checked the tenant at all: both knowledge endpoints (read the shared artifact, or spend an extraction, on any document by id), the PDF serve route (the digest was the only gate), and the book outputter (any job id compiled into a book). Fixed in PR [#248](https://github.com/khoks/VideoResearchPro/pull/248) (S-5.10.6) with a shared `visibility_service.visible_document(db, tenant_id, id)` for single-document lookups. The lesson is the one D-070 already drew: an invariant written as "every read goes through the visibility service" holds only as far as someone has listed the reads, so new routes that take a document or job id in the path are where to look first.


## D-064 — Output length: corpus brackets with an optional user override (2026-07-31)

**Status:** accepted.

**Context.** Requirement (R4): report/Q&A/knowledge length should depend on the size bracket of the corpus, with defaults per bracket and an optional user override chosen at job submission, presented non-obstructively.

Grounding the requirement first showed **most of it already shipped**: since [D-056](#d-056--report-pipeline-budgets-derived-from-work-lossless-reduce-sectioned-compose-2026-07-30) report length scales *continuously* with corpus — `_completion_budget` derives from the work in front of each call and compose splits each section across as many calls as its material needs. What was missing was an explicit bracket concept and any user control.

**The trap.** Implementing "bracket" as a **cap** would re-introduce exactly the defect D-055/D-056 removed: hardcoded `max_tokens=3000` on map and `6000` on reduce, which made a 200-video job produce a report citing 2 channels out of 92. [D-062](#d-062--report_compose-upgraded-to-claude-opus-5-2026-07-31) then showed length intuitions here were wrong twice — opus ran 2.6x longer *and* ~1.4x denser, so the extra length carried extra information rather than padding.

**Decision.** Brackets are **not caps**. `app/services/output_length.py` does two things:

1. **Scales the derived budget** by a multiplier. The budget still tracks corpus size continuously; the multiplier only shifts where on that curve the report sits. "Deep" on a small corpus therefore never exceeds what the corpus supports, because the derived figure remains the base — there is a test asserting deep-on-small < brief-on-large.
2. **Changes the composer's brief.** D-062 measured that a model writes to the brief it is given far more than to the token ceiling it is handed, so each preference carries prose guidance. The `deep` brief explicitly forbids padding ("length must be earned by content — never pad, restate, or inflate"), pinned by a test.

**Brackets** (from the statistics the report agent already computes): `xlarge` (>=120 videos or >=500K words), `large` (>=40 / >=150K), `medium` (>=10 / >=30K), `small`. Defaults are *inverse* to size — small corpora are written up more fully per source (little material, so treat it properly); xlarge is already large at 1.0 and needs no inflation.

**User override:** `brief` 0.45 / `standard` 1.0 / `deep` 1.6, applied instead of the bracket default. `jobs.output_length` (migration `e5f6a7b8c9d1`), NULL == "no preference expressed" — `auto` is normalised to NULL at creation so the column means exactly one thing. Existing jobs keep today's behaviour untouched.

**Extraction is deliberately NOT scaled.** Fidelity of what we pull out of the corpus is not a user preference; only how much of it gets written up is. `_MAP_EXTRACTION_RATIO` stays at 0.40 regardless.

**UI.** A "Report depth" select beside "Number of videos", defaulting to *Auto (recommended)*, sent only when the user actively picks something. Additive and ignorable, per the requirement that it be non-obstructive.

**Robustness.** An unknown value (stale row, hand-edited DB) falls back to the bracket default rather than raising — an odd string must never fail a job. Tested.

**Consequences / incomplete.** This covers the **report** surface only. **Q&A remains corpus-blind**: `formulate_answer` still gets a fixed 4,500-token budget and never sees video/word counts. The requirement explicitly covers Q&A, so R4 is not fully satisfied — the remainder is deliberately deferred into the R3+R5 work because all three touch the same Q&A prompt files and doing it now would churn prompts hardened against measured defects twice. Tracked as S-1.15.2.

**Linked initiatives / PRs.** E-1.15 / S-1.15.1; constrained by D-055, D-056, D-062.


## D-065 — Channel subscriptions become per-tenant; transliteration reversed (2026-07-31)

**Status:** accepted. Both decisions made explicitly by the user on 2026-07-31.

### Part 1 — channel subscription state is per-tenant

**Context.** [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31) closed five leak classes but left `channels` unscoped, filed as S-5.10.2. The user's decision: channels become per-tenant.

Splitting the table showed the more interesting problem was **not** `subscribed`. `channels.source_weight` is documented in the model itself as *"user-set trust score that drives retrieval re-ranking"* — a per-user preference by definition — yet it was stored globally. **One user re-weighting a source silently re-ranked every other user's retrieval.** That would never have surfaced as a privacy complaint; it would have looked like unexplained ranking drift.

**Decision.** Same shape as D-063: the record is shared, the state is private.

| Field | Home | Why |
|---|---|---|
| name, subscriber_count, uploads_playlist_id | `channels` (shared) | Public facts, identical for everyone, worth deduplicating |
| `subscribed` | `channel_subscriptions` | One user following a channel must not enroll others |
| `source_weight` | `channel_subscriptions` | Per-user by intent; was globally mutable |
| `last_synced_at` | `channel_subscriptions` | Two tenants subscribing at different times must not skip each other's backlog |

`subscription_service` is the single accessor, mirroring `visibility_service`, so a new surface cannot accidentally read the legacy global columns. `visible_channel_ids` resolves to channels the tenant holds subscription state for OR that produced a document visible to them. Channel video counts are scoped through document visibility — a global count leaks how much others ingested.

**Migration `f6a7b8c9d1e2`** backfills by attributing each channel's state to every tenant with visibility on one of its documents: 95 subscriptions written, 92 to one tenant and 3 to the other, matching the document split exactly.

**Legacy columns are deliberately NOT dropped** in this revision. Unmigrated code paths still read `channels.subscribed`, and dropping them here would make a partial rollout unrecoverable. Removal is a follow-up once nothing reads them (S-5.10.3).

**Amended 2026-10-18: `source_weight` drives nothing.** The premise above came from the model docstring and was never checked against callers. Nothing reads `source_weight`. No retrieval or ranking code uses it, no endpoint sets it, and no UI exposes it (verified by searching `backend/app` and `frontend/src`). The "one user silently re-ranked everyone" harm was therefore hypothetical, not live. The decision still stands, since a per-user preference belongs in per-user state. But trust-weighted retrieval ([L4](feature-roadmap.md#l4--curated-source-ranking-)) does not exist: the column is a seed, not a mechanism. The docstring in `channel_subscription.py` still says it "re-ranks retrieval".

### Part 2 — reverse the anti-transliteration instruction

**Context.** `knowledge_prompts.py` instructed the model *"Do not transliterate them"* and *"keep the original-script names intact rather than transliterating or translating them"* — in both the extract and synthesis phases. That was a deliberate earlier choice to preserve authenticity, and it directly contradicts requirement R5, which asks for quotes to be transliterated **and** translated **and** kept in the original script. Reversing a deliberate instruction warrants a record rather than a silent edit; the user confirmed the three-part form.

**Decision.** Non-English material now renders in three parts:

- **Proper nouns**: original script + romanisation, plus a gloss where the name carries meaning the reader needs — `महाभारत (Mahābhārata)`.
- **Quotes, verses, historically significant speech**: all three — `अहिंसा परमो धर्मः (ahiṃsā paramo dharmaḥ) — "non-violence is the highest virtue"`. The original preserves authenticity and impact, the transliteration makes it pronounceable, the translation makes it usable. None may be dropped for a quote that matters.

**An English-output contract was added to both knowledge prompts at the same time.** The audit found *no* prompt in `report_prompts.py` or `knowledge_prompts.py` instructed English output, so a Hindi corpus produced a Devanagari report. The extract phase is where that starts: an item emitted in Devanagari there propagates untouched to the final output, so the contract belongs at the extraction boundary, not only at composition.

**Consequences.** This covers the knowledge prompts only. R5 still needs: the English contract across the seven report prompts, per-segment language detection (the per-video label is wrong for code-mixed speech — Hinglish and Arabic/Persian/Urdu mixing inside one sentence), and a `quote_render` use case. Those land with R3, since both rewrite the same files.

**Linked initiatives / PRs.** S-5.10.2 (closed), S-5.10.3 (new), E-1.16 (R5, in progress). Follows D-063.


## D-066 — Language contract, temporal awareness, and corpus-aware Q&A length (2026-07-31)

**Status:** accepted; amended 2026-10-18 (Part 3 was never wired; see the amendment at the end). Covers R5 (linguistics), R3 (time) and the deferred Q&A half of R4, batched because all three rewrite the same prompt files and those prompts are hardened against measured defects — churning them once beats three times.

### Part 1 — R5: English output, with authenticity preserved

**The finding that set the shape.** The audit checked CLAUDE.md's three multilingual claims and found **one false**: no prompt in `report_prompts.py` or `knowledge_prompts.py` instructed English output at all. A Hindi corpus produced a Devanagari report end to end. Multilingual *embeddings* were real; multilingual *output handling* did not exist.

**Decision.** One definition, injected — `app/agents/prompts/shared.py` holds `ENGLISH_OUTPUT_CONTRACT`, `QUOTE_RENDERING_RULES`, `CODE_MIXING_NOTE`, `TEMPORAL_AWARENESS` and `TEMPORAL_EXTRACTION_NOTE`, composed into each prompt at its call site. Nine hand-maintained copies of a rule drift; one definition does not. Fragments are applied selectively — the map stage gets the English contract and code-mixing note but **not** quote-rendering rules, because it emits structured JSON and cannot act on them; sending them would be tokens spent on an unusable instruction.

The contract is enforced at the **extraction** boundary, not only at composition: an item emitted in Devanagari during map propagates untouched into the final deliverable, so translation has to happen there.

**Language detection: exact where possible, honest where not.** `language_service.py` profiles Unicode scripts rather than calling a detection library, because the requirement decomposes into two problems with different answers:

1. **Script mixing** (Devanagari+Latin, Arabic+Latin) — solved exactly. No model, no dependency, no confidence threshold. This is the case that actually threatens the pipeline.
2. **Romanised code-mixing** — Hinglish in Latin letters ("mujhe ye samajh nahi aaya") is invisible to script analysis, and statistical detectors are at their *weakest* here: short text, Hindi grammar, Latin characters. Adding `lingua` would buy a heavy dependency and false confidence on the one case it handles worst. Handled at the prompt layer instead, where the model reads the actual text. **A test asserts this gap persists**, with a note instructing a future maintainer to update this ADR rather than flip the assertion.

`profile_segments` also emits `switch_points` — the indices where a transcript's dominant script changes. A per-video language label is a lie for a 2-hour lecture that switches at minute 40; this is the thing that label cannot express.

**Bug found while building it.** Indic and Arabic scripts carry much of their content in combining marks (Mn/Mc), for which `isalpha()` is False. Counting only "letters" undercounted Devanagari by ~40% in a realistic code-mixed sentence — enough to flip the dominant script from Devanagari to Latin and hide a language switch entirely. Marks now count toward their script.

**Also reversed** (see D-065): `knowledge_prompts.py`'s explicit "Do not transliterate them", replaced with the three-part rendering — original script, transliteration, English translation — for quotes whose exact wording is part of their value. Ordinary conversational speech is translated plainly; the three-part form is reserved rather than applied indiscriminately.

**Search stays a preference, not a filter.** R5 asks that search favour English sources. [D-059](#d-059--selection-quotas-preferred-channel-guarantee--concentration-cap-2026-07-30) explicitly rejected a non-English *filter* as contradicting the multilingual design, and that reasoning holds: a Hindu-topics job legitimately surfaces Hindi content. English preference belongs in ranking, not exclusion.

### Part 2 — R3: publication date and era

**Context.** `documents.published_at` was captured and stored, and reached Chroma chunk metadata — but reached **no prompt**. Nothing in the pipeline knew when anything was published.

**Decision.** `compute_statistics` now derives `earliest_published`, `latest_published`, `median_published`, `videos_by_year` and `dated_video_count`; map chunk headers carry `| published <date>`.

**The guardrail conflict, resolved by supplying data rather than relaxing rules.** D-062 added an instruction *forbidding* the summary from describing corpus vintage beyond verified figures — precisely because the v3 report invented "2024-2025-era" when the bulk was 2026. R3 asks for exactly that commentary. Relaxing the guardrail would reinstate the hallucination; instead the verified span is now computed and supplied, so the model quotes rather than guesses.

`TEMPORAL_AWARENESS` instructs that a claim about "the latest model" is a claim about the world *at that date*, that date-tracking disagreements be stated as trajectories rather than silently resolved, and — critically — that no date be inferred that was not given. That last clause is what keeps it compatible with the Q&A grounding rule ("do not draw on general knowledge").

### Part 3 — S-1.15.2: Q&A stops being corpus-blind

Q&A had a fixed 4,500-token budget and no idea whether it was answering from 3 videos or 200. It now receives corpus statistics and publication span, scaling through the same D-064 policy as the report: multiply a derived budget, change the brief, never impose a cap.

**Consequences.** R4 is now complete across report and Q&A. R5 and R3 are complete at the prompt and data layers. Not yet done: `quote_render` as a separate use case was **deliberately not added** — the R5 investigator's own note was that a separate translate pass doubles cost on `report_map_chunks`, the highest-volume site, and loses source-attribution binding. The prompt contract does the work at zero extra calls.

**A caught failure worth recording.** Mid-implementation, a prompt-binding edit silently failed to apply, so `MAP_CHUNK_PROMPT.format()` raised `KeyError` for every batch. The S-1.12.6 bisect-retry caught it, logged a warning, and continued — producing an empty extraction with a polite processing note. The accounting behaved exactly as designed, and the run would have looked green. Unit tests caught it. The lesson for future work here: a swallowed exception plus a fallback path can hide total failure, so map/reduce stages need a test that asserts a *non-empty* result, not merely that the pipeline completed.

**Amended 2026-10-18: corrections from a code audit.**

- **Part 3 never went live.** `run_qa_agent` gained `corpus_statistics` and `output_length` parameters, but its only production caller (`routers/qa.py`) passes neither. With empty statistics, `output_length.corpus_bracket()` returns `small`. Every job answer, including on the 200-video corpus, therefore gets the small-corpus 1.25× budget and the brief "the corpus is small, so treat each source thoroughly", and never sees the publication span. Library Q&A still runs a fixed 4,500-token budget. No test referenced `corpus_statistics`, which is how the gap went unnoticed. R4 is **not** complete across Q&A, and S-1.15.2 is reopened.
- **Part 2's context overstated the gap.** `published_at` did reach one prompt. Since PR #2 (2026-04-19), the search ranking prompt has shown each candidate's publish date with the hint "more recent is usually better unless the topic calls for foundational content". What ranking still lacks for R3 is the era a source *discusses* and a deliberate per-topic recency decision. Chunk metadata stores `published_at` only as an ISO string, which Chroma cannot range-filter or weight.
- The lesson matches the swallowed `KeyError` above: check a feature at its production caller, not only at the function that implements it.

**Linked initiatives / PRs.** E-1.16 (R5), E-1.17 (R3), S-1.15.2 (reopened 2026-10-18). Follows D-059, D-062, D-064, D-065.

### D-067 — Visual understanding: separate frames table, marker-in-text annotation, opt-in per job (2026-07-31)

**Status:** accepted; amended 2026-10-19 (contract coverage overstated; see the amendment at the end)

**Context.** R1 asks the app to work out where something visually important happens in a video, capture screenshots there, describe them *in transcript context*, and attach the descriptions back to the transcript **clearly annotated** so downstream prompts read them as visual aid, never as spoken words. Three sub-decisions had real alternatives.

**Decision.**

1. **Frames live in their own `visual_frames` table, merged into the transcript at chunk time — never by rewriting `transcript_cache`.**
2. **The annotation marker travels inside the chunk TEXT** (`[VISUAL @ mm:ss — ...]`), not only in metadata.
3. **Opt-in per job (`jobs.visual_analysis`) AND-ed with an install-wide `VISUAL_ENABLED`.** Both must be true.

**Alternatives considered.**

- *Annotate `transcript_cache` in place.* Simplest merge — and wrong. That table is the globally-shared compute-once layer: one row per video, reused by every job and every tenant (D-063). One job's opt-in feature would rewrite everyone else's source text, re-annotation would be destructive, and a transcript that was never annotated would be indistinguishable from one where the selector legitimately found nothing.
- *Carry the visual marker in chunk metadata only.* Cleaner separation, but chunking splits, merges, overlaps and re-packs segments, and the dominant-segment heuristic (D-031) promotes exactly one segment's metadata to chunk level. A 12-token annotation beside 240 tokens of speech loses that vote every time. Text physically inside the chunk reaches the model regardless of which chunk it lands in.
- *Default visual analysis on.* Rejected on two grounds. Frame capture needs a **video** stream, strictly more yt-dlp traffic than the audio-only path that already triggered a YouTube IP block costing 63 videos mid-job (D-051). And it is the app's only multimodal spend — a 200-video corpus at 12 frames each is 2,400 vision calls.

**Consequences.**

- Two chunking changes were required and are load-bearing. `extra["atomic"]` exempts annotations from sentence-splitting, which would otherwise leave the opening marker on one fragment and the closing bracket on another, with the middle sentences reading as speech. Visual presence is aggregated across all segments in a chunk rather than promoted by the dominance vote, and annotations are excluded from that vote so they cannot steal a social chunk's reply attribution.
- `visual_describe_frame` is the app's **first multimodal use case**, and the first registry entry whose model is not freely swappable. `VISION_USE_CASES` marks it; `warn_if_not_vision_capable` advises without blocking (same fail-soft rule as the rest of `llm_routing`); the smoke check's dedupe key gained a `vision` dimension, because a text-only probe against a text-only model *succeeds* — a misconfigured vision use case would otherwise report healthy at startup and fail on the first real frame.
- Every prompt family that reads transcript text now carries `VISUAL_ANNOTATION_CONTRACT`, which states that these spans were never spoken, must not be attributed to the speaker, must be cited as "on screen at mm:ss", and lose to the words where the two conflict. Since 2026-10-19 (S-1.18.6, PR [#234](https://github.com/khoks/VideoResearchPro/pull/234)) it also draws the attribution boundary the [D-071](#d-071--r1-verdict-annotations-win-on-substance-fail-on-attribution-and-cost-ui-deferred-2026-10-19) sweep found missing: a sentence credited to a speaker may contain only what that speaker said; a detail that exists only in an annotation goes in a separate clause marked as shown on screen; a spoken figure noted as "also visible on screen" remains correct use. The rule lives in the one shared fragment, so no prompt file re-states it.
- The `informative` flag is a model judgement biased toward inclusion. Explicit calibration in the prompt catches descriptions that describe an *absence* of content, but borderline frames still pass. This is deliberate: the structural guarantees (marked, never read as speech) are enforced in code; content quality is not, and is measured separately in S-1.18.3.

**Measured, not assumed.** A 200-second video downloaded at 1.9 MB with the `worstvideo[height>=360]` selector, and the describer read a model name off a code slide, a Pydantic class definition with its pass/fail literal field, and a session UUID from a UI — none of which appear in the transcript.

**A bug this caught.** The first version of the vision probe's embedded PNG was written from memory: plausible-looking, malformed, and rejected by OpenAI with `image_parse_error`. Every vision probe would have reported the model unreachable — a startup banner blaming the provider for our own broken bytes. The constant is now generated, verified with an independent decoder, and pinned by a test that walks the chunk CRCs.

**Linked initiatives / PRs.** E-1.18 (R1). Follows D-031 (dominant-segment heuristic), D-051 (bot-wall), D-063 (shared cache, private catalogue).

**Amended 2026-10-19: "every prompt family that reads transcript text" overstates the coverage.** Implementing S-1.18.6 (PR [#234](https://github.com/khoks/VideoResearchPro/pull/234)) found two families that read transcript text without `VISUAL_ANNOTATION_CONTRACT`. First, `_with_visuals` in `job_tasks.py` gates frame capture on `VISUAL_ENABLED`, `jobs.visual_analysis` and `source_type == "video"`, never on job type, so a channel job that opts in gets annotated chunks, and `CHANNEL_MAP_PROMPT` formats those chunks with no `{visual_annotations}` placeholder; T-1.18.1.7 never listed the channel-report family. Second, the two Q&A refine prompts (`REFINE_CONTEXT_PROMPT`, `LIBRARY_REFINE_CONTEXT_PROMPT`) rewrite raw chunks into extracts before the answer prompt sees them, so the answer-stage contract applies to prose from which the marker may already have been paraphrased away. The second gap is masked today by T-1.18.1.10 (spans rarely reach Chroma for an already-embedded video) and becomes live the moment that lands. The consequence above is accurate for the topic-report, Q&A-answer and knowledge families. Tracked as T-1.18.1.12 and T-1.18.1.13 under S-1.18.1.


## D-068 — Curated source ranking v1: per-tenant trust weight re-ranks retrieval; perspective banding deferred (2026-10-18)

**Status:** accepted; v1 shipped 2026-10-19 in PR [#287](https://github.com/khoks/VideoResearchPro/pull/287) and measured (T-7.1.1.5). Two of the four pre-registered clauses failed (relevance narrowly; faithfulness, on counts both arms inflate), so the formula is reopened as S-7.1.2 — see the amendment at the end of this entry. Taken by Claude under the user's 2026-10-18 directive to "take a wise decision around L4 and document its rationale"; the user set the goal, not the shape.

**Context.** The product thesis is *curated, not balanced*, yet curation stops at approval: every approved source counts equally in retrieval. The audit of 2026-10-18 found that `channel_subscriptions.source_weight` (per-tenant since [D-065](#d-065--channel-subscriptions-become-per-tenant-transliteration-reversed-2026-07-31)) is read by nothing, despite its docstring calling it "the trust score that re-ranks retrieval". Two shapes were on the table for [L4](feature-roadmap.md#l4--curated-source-ranking-): weighted retrieval, or perspective banding in the answer ("your trusted creators say X; others say Y").

**Decision.** Ship weighted retrieval first, as a pure re-rank, and defer banding.

1. **Weights are a ranking input resolved at query time, never stored on chunks and never a filter.** Chunks are shared across tenants ([D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)), so a per-tenant number cannot live in Chroma metadata. The weight is looked up per `channel_id` from the asking tenant's subscriptions and applied after retrieval.
2. **Formula, pre-registered so the measurement cannot be tuned afterwards:** retrieve `3 × top_k` candidates, drop those failing `RAG_DISTANCE_THRESHOLD` on the *raw* distance, then sort by `distance / weight` and keep `top_k`. Weight range 0.0–2.0, default 1.0; a weight of 0 is clamped to 0.05 so the source sinks to the bottom but can still surface when nothing else matches. Weighting after the threshold means a trusted source cannot pull an off-topic chunk into the answer; it only reorders what is relevant.
3. **Weights become settable:** `PUT /api/v1/channels/{id}/weight` through `subscription_service`, plus a control on the channel page. Sources without a channel (Reddit, HN, PDFs) stay at 1.0 until creators generalise (E-1.9 Phase 2).
4. **Scope:** job-scoped and library Q&A. The report has no retrieval step (it maps every approved chunk), so weights do not apply there yet.
5. **Measured before being called done:** the same question set with weights on and off, judged blind with the E-1.14 method.

**Alternatives considered.**

- *Perspective banding first.* Rejected for now: there are no user-set weights yet to band on, so it would be built on defaults; it reshapes `qa_agent.py`, which the R3/R4 batch is rewriting; and its value is unmeasurable until weights exist. Filed as E-7.2.
- *Weight as a filter* (drop low-trust sources). Rejected: [D-059](#d-059--selection-quotas-preferred-channel-guarantee--concentration-cap-2026-07-30) and [D-066](#d-066--language-contract-temporal-awareness-and-corpus-aware-qa-length-2026-07-31) established "preference, never filter"; exclusion already happens at approval.
- *Boost before the relevance threshold.* Rejected: it would let a trusted but off-topic chunk displace a relevant one.
- *Per-document `author_trust_weight`.* Deferred: channel-level first, per the roadmap's own recommendation.

**Consequences.** E-7.1 is sequenced after the R3/R4 batch lands, because both touch `qa_agent.py`. The `channel_subscription.py` docstring becomes true rather than being rewritten. Retrieval pool size triples for weighted queries; the cost is one Chroma call either way.

**Linked initiatives / PRs.** I-7 / E-7.1 / S-7.1.1 (PR [#287](https://github.com/khoks/VideoResearchPro/pull/287)), S-7.1.2. Follows D-059, D-063, D-065.

**Status-changed 2026-10-25:** kept by [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) — a weight near 0 keeps today's behaviour (the channel drops out on a broad corpus), and the slider text that promised otherwise is corrected (T-7.1.2.2, T-7.1.1.6); perspective banding (E-7.2) waits until the owner has weighted channels for real.

**Amended 2026-10-19: measured, and it costs relevance at strong weights.** The formula above shipped unchanged in PR [#287](https://github.com/khoks/VideoResearchPro/pull/287) and was measured with the protocol pre-registered in [notes/2026-10-19-e71-trust-weighting-measurement.md](notes/2026-10-19-e71-trust-weighting-measurement.md): 10 questions, job and library Q&A, weights 2.0 on three channels and 0 on three others of the reference job's ten largest, three blind judges, three-lens claim verification.

- **The mechanism works as specified.** Promoted channels went from 23% to 57% of the retrieved context, demoted ones from 10% to 0%, and no weighted chunk failed the raw threshold.
- **It costs breadth, and judges noticed.** Distinct channels per answer fell from about 20 to 13. Mean relevance stayed level (8.53 vs 8.58), but 61% of non-tie verdicts preferred the unweighted answer against a 60% limit, almost all of it on library Q&A (21 to 7). Job Q&A, which also reads the report, slightly preferred weighting (15 to 13). Confirmed unsupported claims: ON 110, OFF 95, which also fails the faithfulness clause (ON ≤ OFF + 2); both counts are inflated by date claims the judges' excerpts could not show, so the gap is suggestive rather than conclusive.
- **A weight of 0 excludes in practice.** Point 2's "can still surface when nothing else matches" did not happen once in 20 weighted answers: a 3× pool always holds enough other relevant chunks.

Per the rule written before the run, the mechanism stays (it changes nothing until a user sets a weight), the result is recorded here, and the formula is reopened as **S-7.1.2** rather than tuned to pass: candidates are a per-channel share cap in the spirit of D-059's concentration cap, a softened transform (`distance / weight^α`, α < 1), and a true last-resort rule for low weights. Each is to be compared on the same questions and weights. E-7.2 (banding) stays deferred; this measurement is the evidence it was waiting for, and it says concentration, not ordering, is the problem to solve first.

**Re-judged 2026-10-19 with dated excerpts (PR [#330](https://github.com/khoks/VideoResearchPro/pull/330)).** The judging above showed judges and verifiers excerpts without the publication dates the answers cite (found by T-5.10.2.7), so correctly cited dates read as unsupported. The same answers were re-judged under the same four clauses, unchanged, with dates visible. Both readings are kept:

| Clause | Undated (as recorded) | Dated re-judge |
|---|---|---|
| 1. Mechanism (promoted share up, demoted down, 7+ of 10 job questions) | met | met (retrieval, unchanged) |
| 2. No weighted chunk over the raw threshold | met | met (retrieval, unchanged) |
| 3. Relevance: mean ON ≥ OFF − 0.5 **and** ≤ 60% of non-tie verdicts favour OFF | **not met** — 8.53 vs 8.58; OFF 60.7% | met — 8.73 vs 8.82; OFF 59.3% |
| 3, two unchanged judges only (GPT-5.5, Sonnet 5) | met — 8.28 vs 8.45; OFF 57.5% | met — 8.40 vs 8.47; OFF 55.0% |
| 4. Confirmed unsupported claims ON ≤ OFF + 2 | **not met** — 110 vs 95 | met — 11 vs 26 |

Verdicts ON / OFF / tie: undated 22 / 34 / 4, dated 24 / 35 / 1. By surface (dated): job 16 / 14 / 0, library 8 / 21 / 1; mean faithfulness ON / OFF undated 7.07 / 7.23, dated 8.82 / 8.57.

**Outcome, per the rule fixed before the re-judge:** the dated reading meets clauses 3 and 4, so **S-7.1.2 closes as "artifact, no rework"** and weighting stays as shipped. The two clauses moved for different reasons, and the difference matters. **Clause 4's failure was the artifact:** with dates visible, weighted answers carry fewer confirmed unsupported claims than unweighted ones (11 vs 26, against 110 vs 95). **Clause 3 crossed its line by less than a point** (60.7% → 59.3% of non-tie verdicts favouring OFF; limit 60%), which is within run-to-run noise. The two judges common to both readings (GPT-5.5, Claude Sonnet 5) meet clause 3 in both, at 57.5% and 55.0%; the recorded failure came from Gemini 3.1 Pro, 69% of whose non-tie verdicts favoured OFF. **Library Q&A's preference for unweighted answers is not an artifact:** it held with dates visible (OFF 21 to ON 8, against 21 to 7 undated), while job Q&A stays even. So strong weights do narrow library answers in a way judges dislike; it is a real cost of the setting, recorded rather than reworked, and the channel-page copy already warns that raising a weight narrows answers. The weight-0 finding also stands, because it comes from retrieval: no demoted chunk reached any weighted answer.


## D-069 — Shipped-backend surfaces: ingest as a Library tab, Author Studio as one page, readiness as a gate mean (2026-10-19)

**Status:** accepted. Three UX choices taken by Claude while building PR [#224](https://github.com/khoks/VideoResearchPro/pull/224) under the user's instruction to pick what matches [ui-design.md](ui-design.md) and record why; the user asked for the surfaces, not their shape.

**Context.** The 2026-10-18 audit found four backend capabilities with no frontend caller: `POST /library/upload-pdf`, `POST /library/paste-urls`, and the Author Studio and Echo routers behind stub pages. Each needed a home and a shape, and the original tracking items implied shapes that no longer fit the backend as shipped.

**Decision.**

1. **Ingest controls live on an "Add sources" tab of `/library`, not on the Submit page and not in a modal.** Both endpoints are library-scoped by design (their docstrings say so: a PDF joins the global library and library-wide Q&A regardless of any job) and start no job, so the research-run form is the wrong home. The per-file and per-URL result tables need room and should outlive a dialog. The page already uses tabs for its sections, and [ui-design.md §2.1](ui-design.md) groups the Library sidebar as Shelves / All sources / Channels, where a third tab sits naturally.
2. **Author Studio is a single `/author` page, not "a Pro+ button on a job page" (T-6.1.5's original wording) and not a per-kind route tree.** A book spans several runs, so a per-job button would hide the only input that matters. Kinds come from `GET /author/kinds`: only `available` kinds get a create flow; the rest render as "coming later" with no button, so a 501 is never offered. Per-kind sub-routes (`/author/books`, …) wait until the kind filter is not enough.
3. **Echo readiness is shown as the mean of the three cold-start gates, capped at 99 % until the backend says `ready`, with each gate drawn against its own threshold.** The gates are AND-ed server-side, so no single number is exact; a mean tells the user how far along they are without claiming more than the backend does, and the per-gate meters keep it honest. The sources gate carries an explicit line that it cannot be met while the connector registry is empty.

**Alternatives considered.**

- *Ingest on the Submit page as new job types.* Rejected: no job is created, and the roadmap's old `url_list` / `upload` job-type idea ([api-reference.md § Forward-compat](api-reference.md#forward-compat)) was superseded when the endpoints shipped library-scoped.
- *Ingest in a modal from a header button.* Rejected: results vanish on close, and a 100-URL batch takes minutes.
- *Author create button on `JobDetailPage`.* Rejected as above; a job page could later offer "add this run to a book" as a shortcut into the same flow.
- *Readiness as "N of 3 gates met".* Rejected: it reads 0 of 3 for a user with 90 facts recorded, which is discouraging and wrong in spirit.

**Consequences.** `/author` and `/echo` are real pages with their own state matrices in [ui-pages.md](ui-pages.md); `/brain/*` from the forward-looking table is realised as `/echo`. The frontend gained React-free result-state modules (`utils/ingestResults.ts`, `utils/authorOutputs.ts`, `utils/echoReadiness.ts`) that are test-ready; there is still no frontend unit-test runner, which [testing.md](testing.md) lists as open work. Two backend contract gaps the UI works around are recorded in [api-reference.md](api-reference.md): the PDF serve route is header-auth only, and an Echo key containing `/` cannot be deleted.

**Linked initiatives / PRs.** T-1.5.8.3, E-1.8 follow-up, T-6.1.5, I-3 status / PR #224.


## D-070 — Document visibility keyed on `document_id`, not the legacy `video_id` (2026-10-19)

**Status:** accepted. Diagnosed in PR [#224](https://github.com/khoks/VideoResearchPro/pull/224); shipped 2026-10-19 in PR [#241](https://github.com/khoks/VideoResearchPro/pull/241), sequenced after the R3/R4 batch ([#227](https://github.com/khoks/VideoResearchPro/pull/227)) that was editing `qa_agent.py` and the library Q&A route.

**Context.** See the 2026-10-19 amendment to [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31). `document_visibility(video_id, tenant_id, source)` references `documents.video_id`, which the E-1.10 cutover ([D-017](#d-017--e-110-hard-cutover-single-migration-uuid-pk-promotion-2026-04-26)) made a nullable back-compat column that is NULL for every non-video source. `grant()` drops falsy ids, the listing (`library.py`), library Q&A (`library.py` → `qa_agent._query_library`) and `channels.py` all filter on that column, and `LibraryVideoResponse` still declares `id`, `video_id` and `duration_seconds` non-nullable. Uploaded PDFs, pasted pages, Reddit, HN and podcast documents are therefore invisible and unretrievable for every tenant, and have been since D-063 landed. The "twelve source types end-to-end" claim in the roadmap is true of ingest and false of retrieval for the eight non-video types.

**Decision.** Key visibility on `documents.document_id` end to end:

1. Migration: add `document_visibility.document_id` (FK `documents.document_id`, cascade), backfill by joining `documents` on `video_id`, move the unique constraint to `(document_id, tenant_id)`, retire the `video_id` column (SQLite batch mode).
2. `grant()` takes document ids; its five call sites (`library.py` ×4, `job_tasks.py` ×1) pass `document_id`. `visible_video_ids()` becomes `visible_document_ids()`.
3. Readers filter `Document.document_id`. Retrieval filters Chroma on a `document_id` metadata field; `_build_video_metadata` writes it for every source type, and legacy chunks that carry only `video_id` are stamped by a metadata-only backfill at API startup (`chroma_service.backfill_chunk_document_ids`) — the transition choice is recorded below.
4. `LibraryVideoResponse.id = document_id`, `duration_seconds` nullable, `source_type` added. The frontend already tolerates this ([D-069](#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19)).
5. The strict `xfail` in `tests/test_routers/test_library_paste_urls.py` is un-marked, an equivalent upload-PDF router test is added, and a two-tenant isolation test proves user B cannot see user A's pasted page.

**Alternatives considered.**

- *Backfill a synthetic `video_id` for non-video rows.* Rejected: it reverses D-017 and makes a 20-character YouTube-id column carry UUIDs.
- *Derive visibility from `job_documents` for the gap cases.* Rejected by D-063 itself: PDFs and pasted pages have no job.
- *Keep `video_id` grants for videos and add a parallel table for other sources.* Rejected: two code paths for one invariant is how the first gap went unnoticed.

**Consequences.** One migration touching a table with live grants; the retrieval filter changes shape, so it must land after, not alongside, the in-flight `qa_agent.py` work. Once merged, the D-063 "0 documents left ungranted" guarantee is re-established for every source type and the roadmap's L1 end-to-end claim becomes true again.

**Transition for legacy chunks (T-5.10.4.4): metadata backfill, single filter.** Chunks embedded before 2026-10-19 carry `video_id` and no `document_id`. *Rejected:* filtering on either field during a transition window. It is two retrieval paths for one invariant — the shape of the original gap — it makes every caller carry two id sets, and it never ends, because nothing tells the operator when the window may close. *Chosen:* `chroma_service.backfill_chunk_document_ids` runs on every API startup next to the Q&A library backfill. It pages the global collection's metadata, resolves each un-stamped chunk through `documents` (by `video_id`, then by `(source_type, source_id)`) and updates the metadata in place. Chroma keeps the stored embedding on a metadata-only update, so nothing is re-embedded; D-072's "no backfill" reasoning was about re-embedding the library for a ranking signal and does not apply. Idempotent, and a chunk whose document is gone stays un-stamped and unretrievable, which is the right state for it. The cost is one metadata scan per startup; a completion marker is the escape hatch if that ever matters, and was not added because a marker can lie after a Chroma restore.

**Chroma storage keys.** Chunk ids stay `{video_id}:{index}` for YouTube documents — a video's id never changes, and moving them to the UUID would orphan every existing chunk — and are `{document_id}:{index}` for every other source. The id is a storage key for in-place upsert; retrieval reads only the `document_id` metadata field, which is one path, not two.

**Found while shipping, fixed in the same PR.**

1. `chroma_service.insert_chunks` keyed every chunk on `video_id` and *skipped* chunks without one. No PDF, pasted page, Reddit or HN document had ever been embedded: the loss was one layer deeper than this entry described — not "granted to nobody" but "never written". Both routers' Chroma writes were mocked in their tests; `tests/test_services/test_chroma_document_scope.py` now writes through a real in-memory collection.
2. `query_collection` built its filter with `if video_ids`, so an **empty** visible set — a new user who has ingested nothing — fell through to an unrestricted search of every tenant's transcripts. T-5.10.1.7's test asserted that the agent passed `[]`, not what the service did with it. `document_ids=[]` now returns no results, pinned at the service.
3. Job Q&A had the same shape: `routers/qa.py` read `JobVideo.video_id`, so a topic job's Reddit / HN / PDF documents were never retrieved. It now passes the job's approved `document_id` set (`run_qa_agent(document_ids=...)`, state key `document_ids`), and `corpus_stats_service` counts those documents too.
4. `LibraryVideoResponse` declared `id`, `video_id` and `duration_seconds` non-nullable; a PDF row would have failed validation the moment it became visible.
5. `qa_agent._dedupe_chunks` keyed on `video_id` + `chunk_index`, which collapses chunk N of every non-video document into one entry. Keyed on `document_id` now.
6. `_flatten_metadata` wrote `None` as the string `"None"`; the key is omitted instead (D-072's rule for unknowns).

**Not kept.** No `visible_video_ids()` shim: no caller needs YouTube ids. `corpus_stats_service.corpus_statistics_for_video_ids` became `corpus_statistics_for_document_ids`, `approved_video_ids_for_job` became `approved_document_ids_for_job`.

**Downgrade.** `alembic downgrade -1` restores `video_id` from `documents` and deletes grants over non-video documents, which the old schema cannot hold — exactly the pre-D-070 state, logged with a count. Revision `3653e565c1fc` (a random id: two earlier drafts took `c7d8e9f0a1b2` and `d8e9f0a1b2c3`, which S-8.3.1 and S-8.1.1 also took the same day), on top of S-8.1.1's `d8e9f0a1b2c3`. The round trip is pinned by `tests/test_migrations/test_visibility_document_id_migration.py`.

**Linked initiatives / PRs.** S-5.10.4 (this fix, PR [#241](https://github.com/khoks/VideoResearchPro/pull/241)), S-5.10.1 (reopened by this gap, closed again), E-1.8, S-1.5.8 / PR #224 (diagnosis). Follows D-017, D-063, D-072.

## D-071 — R1 verdict: annotations win on substance, fail on attribution and cost; UI deferred (2026-10-19)

**Status:** accepted. Outcome of the pre-registered protocol in [docs/notes/2026-10-18-r1-visual-measurement.md](notes/2026-10-18-r1-visual-measurement.md), run under the user's instruction to test R1 before building its UI.

**Context.** D-067 shipped the visual pipeline with the value question open. The protocol fixed three criteria before any result existed: 2 of 3 blind judges prefer the annotated report on substance; zero attribution errors in it; vision spend under $0.10 per video.

**What was measured.** One visual-on job (11 videos, 120 frames), then a deterministic replay of its own chunks into two reports that differ only by the `[VISUAL @]` spans. Three judges from three model families, blind with independent coin flips; then 87 verifier agents: three lenses per claimed error, three independent sweeps of the annotated report, three refuters per sweep candidate.

**Decision.**

1. **Annotations stay in the pipeline and stay opt-in; the UI (S-1.18.2) is not built yet.** Criterion 1 was met decisively (3 of 3; 8.33 vs 7.00; zero confirmed fabrications against five in the unannotated arm). Criteria 2 and 3 failed: two attribution errors, and $0.198 per video.
2. **The contract gains a rule before the next run:** a sentence attributed to a speaker may contain only what was spoken; screen-only details go in a separate clause marked as shown (S-1.18.6; landed 2026-10-19, PR [#234](https://github.com/khoks/VideoResearchPro/pull/234)). Both confirmed errors had exactly that shape, and none of the "(values also visible on screen)" sentences was an error, so the fix is narrow.
3. **Both vision use cases move to a cheaper tier and the cost is re-measured** (S-1.18.5); `gpt-5.6-luna` and `gemini-3.1-flash-lite` are already on the vision allowlist at roughly 1/25 of gpt-5.5's input price.
4. **A sweep with independent refuters is part of the method from now on.** All three judges returned zero attribution errors; the sweep found two. Judges alone are not evidence of absence.

**Alternatives considered.**

- *Build the UI anyway, since quality won.* Rejected: the rule was written down first precisely so a favourable headline could not override the other two criteria.
- *Relax the zero-error criterion to "no more than the unannotated arm".* Rejected: the unannotated arm cannot commit this error class at all, and the contract fix is cheap.
- *Count the judges' "fabrications" as reported.* Rejected after verification: none of the seven in the annotated arm survived; four were pipeline metadata leaking into prose (S-1.14.15), three restated supplied statistics.

**Consequences.** S-1.18.2 stays deferred behind S-1.18.5 and S-1.18.6. The judge scripts (`replay_visual_ab.py`, `judge_pair.py`) and the verification workflow are reusable for T-7.1.1.5 and S-1.16.2. Known limits stand: one topic, report only; Q&A cannot be compared until T-1.18.1.10 lands.

**Linked initiatives / PRs.** S-1.18.3 (closed), S-1.18.5, S-1.18.6, S-1.18.2 (deferred). Follows D-055, D-067.

## D-072 — Two dates per source; era at ingest; time as a ranking preference; Q&A statistics from the database (2026-10-19)

**Status:** accepted

**Context.** R3 asks the app to know both *when a source was posted* and *which period it talks about*, and to use both in knowledge extraction, search ranking, Q&A and reporting. D-066 shipped the first date. An audit on 2026-10-18 found the second never started, the Q&A half of R4 built as agent plumbing no router fed (so every answer on the 200-video corpus was classified `small`), and three executive-summary defects (S-1.14.15) that were themselves temporal. All of it edits the same hardened prompt files, so it shipped as one batch.

**Decision.**

1. **A second date column, extracted once at ingest.** `documents.discussed_era_json` holds `{era_start, era_end, era_confidence, is_retrospective, era_label}` — integer years, negative for BCE — written by the new `temporal_scope_extract` use case the first time a job chunks the document (`job_tasks._ensure_era`), then reused forever, like transcripts and embeddings (D-063). Economy tier, reasoning OFF, 400-token cap, ~5K tokens in. Fail-soft: a failed call leaves the era unknown and the job continues; failures are not persisted, so a transient outage is retried by the next job rather than frozen.
2. **Unknown is a first-class value and is never a sentinel.** Chunks carry `published_ts` / `published_year` and the four era scalars only when known. A Chroma range filter therefore excludes undated chunks instead of matching them against 1970. Chunks embedded before 2026-10-19 carry none of these; they read as unknown, and there is **no backfill**.
3. **Time in ranking is a preference decided once per topic.** The planner's JSON gained `temporal_profile` — `recency_weight` of `dominant` / `secondary` / `minimal`, an optional `target_era`, a rationale — and the ranking prompt receives the matching guidance, each candidate's discussed era when the library has dated it, and the explicit rule that no candidate is excluded for its date. This builds on the generic publish-date hint the prompt has carried since PR #2 rather than duplicating it. Default when the planner is silent: `secondary`. Same reasoning as D-059 rejected a language filter.
4. **Q&A reads its corpus from the database.** `corpus_stats_service` computes the figures for the approved (job) or visible (library) set in the routers and passes them, with the length preference, into the agents. Both answer sites share `qa_agent._answer_policy`; the library's fixed 4,500 is gone; both request schemas gained an optional `output_length`. Tests assert at the production caller.
5. **Every compose call gets the same verified corpus facts, and the summary reads the written sections.** `_corpus_facts` replaces the raw statistics JSON (whose 92-entry channel breakdown buried the dates) and goes to every section, so no section can contradict the Statistics table. The summary receives a plain-text rendering of the sections (60K-token bound) instead of titles with item counts, and is told never to mention pipeline mechanics.
6. **Judging is section by section.** `scripts/judge_report_sections.py` splits on `<h2>` and judges each in full; the 180,000-character document cap is gone.

**Alternatives considered.**

- *Extract the era during knowledge extraction instead of ingest.* Cheaper in aggregate (knowledge extraction is on demand) but the era would reach neither chunk metadata nor the report's map headers, which is where ranking and extraction need it. Ingest is the one place every document passes through.
- *Backfill the existing Chroma collection.* Would re-embed the whole library for a metadata field only ranking and filtering read. Unknown is the honest value for a chunk nobody has dated; a document gains its era the next time a job re-chunks it.
- *Date candidates at ranking time with a per-candidate LLM call.* Hundreds of calls per search for a signal that is unavailable for most candidates anyway (no transcript yet). The library lookup covers candidates the app has seen; the ranker infers the rest from title and description, which it reads regardless.
- *A separate recency-scoring function applied after the model's ranking.* A numeric re-rank would be a filter in disguise and would override the model's relevance judgement with a formula nobody has measured. The decision stays with the model, made explicit rather than implicit.
- *Keep feeding the summary a digest of item counts.* It had nothing else to summarise, which is why counts leaked into prose. The cost of reading the sections (~60K tokens on the largest reports) buys a summary that can say what the report found.

**Consequences.**

- One more LLM call per NEW document at ingest (~$0.001 on `gpt-5.6-luna`); a 200-video job of unseen documents adds roughly $0.20. Re-running a job over a processed corpus costs nothing extra.
- The registry has 23 use cases. `temporal_scope_extract` is probed at startup but gates no feature.
- The CORPUS note Q&A answers now carry — publication span, discussed-era span, and the instruction to name dates when sources disagree — is only as good as the statistics the router computes. A new Q&A surface must compute and pass them, or it inherits the 2026-07-31 defect.
- **Open design question, deliberately left to the user:** how strongly should recency outweigh relevance for a fast-moving topic? `dominant` currently means "strongly prefer the most recent among on-topic candidates; keep an older one only when clearly foundational". A stricter reading (an explicit cutoff, or a numeric re-rank) would start to behave like a filter; a looser one collapses into `secondary`. The planner's choice is logged per job so the decision can be inspected before it is tuned.

**Linked initiatives / PRs.** E-1.17 (R3, closed), E-1.15 (R4, closed), S-1.15.2, S-1.14.15, T-1.16.1.6, T-1.16.1.8. Follows D-059, D-064, D-066. PR [#227](https://github.com/khoks/VideoResearchPro/pull/227).

**Status-changed 2026-10-25:** kept by [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) — the `dominant` wording stays until S-1.17.4 measures it (OQ-9), and S-1.17.3 may reverse the no-backfill rule with its own amendment.

## D-073 — Frame description moves to gemini-3.1-flash-lite on image-grounded grading; selection stays on gpt-5.5 (2026-10-19)

**Status:** accepted. Follows the cost branch of [D-071](#d-071--r1-verdict-annotations-win-on-substance-fail-on-attribution-and-cost-ui-deferred-2026-10-19).

**Context.** The R1 protocol fixed $0.10 per video as the ceiling for the visual pass; the gpt-5.5 defaults cost $0.230 per video when measured with real token counts (select $0.097, describe $0.133; 11 videos produced calls). Two cheaper vision-capable candidates were on the allowlist. Cost alone could not decide: a cheaper describer that misreads a chart is worse than no annotation.

**What was measured** (`backend/scripts/retier_vision.py`, results in [the protocol note](notes/2026-10-18-r1-visual-measurement.md#re-tier-s-1185-appended-2026-10-19)). The same 120 frames re-described by gpt-5.5, gpt-5.6-luna and gemini-3.1-flash-lite; 33 frames graded blind by two independent graders each, who opened the image. Selection re-run on the same 11 transcripts by four models, scored by agreement with the stored picks against gpt-5.5's own re-run as the noise floor.

**Decision.**
1. `visual_describe_frame` → `google:gemini-3.1-flash-lite:off`. Accuracy 4.21/5 with 5 of 66 gradings unusable, against gpt-5.5's 4.52 and 3; cost $0.008 per video against $0.133.
2. `visual_select_moments` stays on gpt-5.5 but drops from `medium` to `low` reasoning. The same model at low agreed with the medium picks 76% of the time (medium against itself: 85%) for $0.067 instead of $0.097; luna agreed 59%, mini 24%, flash-lite 23%. Selection quality cannot be graded without capturing the alternative frames, so the measured model keeps the slot and only its reasoning budget moves.
3. Total $0.075 per video, pinned by a test at the measured token counts so a pricing or registry change that breaks the ceiling fails CI. A first pass of these figures divided by the 12 approved videos rather than the 11 that produced calls and put the total at $0.097 with selection still on medium; the pinned test rejected it at $0.105.

**Alternatives considered.**
- *Luna for both* ($0.006). Rejected on quality: 22 of 66 gradings unusable, with substantive misreads (axis dates, a code cell reported as output).
- *Select on luna* to widen the margin ($0.002). Rejected for now: 59% agreement is not evidence of bad selections, but it is not evidence of good ones either; T-1.18.5.5's higher-resolution run is the moment to capture and grade alternative selections.
- *Select on gpt-5.5 off* ($0.064, also 76%). Not chosen over low: the $0.003 difference is noise and selection is a judgement call, not a JSON extraction, so the light reasoning budget stays.
- *Keep gpt-5.5 for describe and accept $0.230.* Rejected: the ceiling was set before the data, and flash-lite's quality gap is small and mostly 360p label misreads that gpt-5.5 also makes.

**Consequences.** The smoke probe now exercises the Google provider at startup, which is why `langchain-google-genai` had to become a declared dependency (PR #231). Frame resolution is the next lever (T-1.18.5.5). The S-1.18.2 UI decision waits for the protocol re-run after S-1.18.6.

**Linked initiatives / PRs.** S-1.18.5 (closed except .4/.5), S-1.18.6, D-071.


## D-074 — Notes: one stream per document, soft delete only, lossless W3C JSON-LD export, Echo feeder reported not gated (2026-10-19)

**Status:** accepted. Item 1 takes the [M5 plan](plans/m5-notes.md#open-questions)'s open question 2 at its recommended default; the user may revisit it.

**Context.** Notes (M5, [E-8.5](initiatives.md#e-85--notes--the-users-own-voice-in-the-library-m5)) are the first text in the system written BY the user rather than ingested FOR them, and the richest input Echo's voice capture (E-3.3) will have. Building S-8.5.1 and S-8.5.3 forced four choices the plan left open or did not name. At the time, the library shelf still addressed a document by its legacy YouTube `video_id` while the job page used `document_id`. Deletion semantics would decide whether an export can carry a withdrawn note. "Exportable" had to name a format. The plan said notes feed Echo readiness, but readiness's per-language voice floor belongs to S-3.5.1.

**Decision.**
1. **One note stream per document.** A `document` or `knowledge_artifact` note accepts either id and is stored under the canonical `document_id`. It therefore shows on every surface that shows the document, including every job that contains it. A note meant for one run is a `job` note. Responses carry `target_video_id` for surfaces still keyed on the legacy id.
2. **Soft delete only.** `DELETE /notes/{id}` sets `deleted_at`. The row leaves every live read and list but stays for exports and for Echo. No purge endpoint exists yet.
3. **The lossless export is W3C Web Annotation JSON-LD.** `GET /exports/notes.jsonl` writes one annotation per line under the `anno.jsonld` context, with withdrawn notes carrying a `deleted` timestamp. `note_export_service.parse_note_jsonld` is the exact inverse, and a test holds every stored column of every row to it. The Markdown export is for reading. This is also the GDPR Article 20 copy of user-provided data.
4. **Echo feeder, reported not gated.** `GET /echo/status` reports `notes_total` and `notes_words`, and the readiness panel shows them. `ready` does not change until S-3.5.1 sets the voice floor.
5. **Missing and foreign are the same 404**, for both note ids and targets, as the library Q&A delete already does.

**Alternatives considered.**
- *Scope document notes to the job they were written from.* Rejected for v1. A note on a document is about the document, the plan recommended this, and a run-scoped thought already has the `job` target type.
- *Store whichever id the caller sent.* Rejected. One document would get two note streams that never meet, and D-070 has since made `document_id` the only visibility key.
- *Hard delete.* Rejected. It loses the user's own words from the export and from Echo, and a withdrawal is itself a signal. A purge for erasure requests can come with the SaaS erasure flow.
- *A bespoke JSON export.* Rejected. The W3C shape is portable to Hypothes.is-style tools at no extra cost, and the round-trip test makes it lossless anyway.
- *Gate readiness on notes now with a provisional floor.* Deferred to S-3.5.1, which owns the per-language minima and the evidence behind them.

**Consequences.** S-8.5.2 must exclude withdrawn notes from the `notes_global` collection, and a document note must reach every job that contains the document, not only the one it was written from. Inline panels fetch one list per target type per page, capped at 2,000 rows, so a heavy user sees only the newest 2,000 of a type inline while the `/notes` page and the export see everything. A purge endpoint is owed before SaaS (see [saas-roadmap.md](saas-roadmap.md)).

**Linked initiatives / PRs.** [S-8.5.1](initiatives.md#s-851--notes-schema-rest-and-inline-ui) (PR [#243](https://github.com/khoks/VideoResearchPro/pull/243)), [S-8.5.3](initiatives.md#s-853--your-notes-view-search-and-export) (PR [#246](https://github.com/khoks/VideoResearchPro/pull/246)), S-8.5.2, S-3.5.1, [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19).

**Status-changed 2026-10-25:** ratified by [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) — the owner adopted these defaults, item 1 included.

## D-075 — R1 after three runs: the modality boundary needs provenance, not prompt rules (2026-10-19)

**Status:** accepted. Follows [D-071](#d-071--r1-verdict-annotations-win-on-substance-fail-on-attribution-and-cost-ui-deferred-2026-10-19) and [D-073](#d-073--frame-description-moves-to-gemini-31-flash-lite-on-image-grounded-grading-selection-stays-on-gpt-55-2026-10-19); the measurements are in [the protocol note](notes/2026-10-18-r1-visual-measurement.md#re-runs-after-the-contract-fix-t-11863-appended-2026-10-19).

**Context.** S-1.18.6 added an attribution-boundary rule to `VISUAL_ANNOTATION_CONTRACT`, and D-073 moved frame description to gemini-3.1-flash-lite to meet the cost ceiling. Two re-runs on the same job then tested each change on its own: run 2 with Flash-Lite descriptions, run 3 with gpt-5.5 descriptions, both under the new rule, both judged blind by three model families and adversarially verified.

**Findings.**

1. The substance gain is real, but only with a strong describer: run 3 won 3/3 at matched length; run 2 tied (1/3). A cheap describer that grades only 0.3 points lower per frame erased the benefit at report level.
2. The rule changed the direction of attribution errors, not their number. Every run had one or two confirmed errors per ~10,000-word report. Before the rule, screen details were credited to speakers; after it, spoken details were credited to the screen.
3. A deterministic post-check cannot enforce the boundary on this corpus. It recalled 2 of 5 confirmed errors, flooded reports with false positives, and is structurally blind to Hindi and Bengali speech.

**Decision.**

- **The UI (S-1.18.2) stays deferred.** No configuration has yet met all three pre-registered criteria.
- **Fix the cause, not the wording.** At the map stage, each extracted fact is labelled with its modality, `said`, `shown` or `both`, taken from the chunk it came from. The label travels through the lossless reduce (D-056) and is rendered for the composer. The composer then attributes from labels instead of inferring modality from interleaved text, and a check can compare the report against item provenance rather than raw transcripts. Filed as S-1.18.8, sequenced after S-1.14.6, which persists map items so their labels can be audited.
- **The describer is chosen at report level, not per frame.** Per-frame grading did not predict the report-level loss, so the next tier change needs a report-level run. Three mid-priced describers (gpt-5.4-mini, claude-haiku-4-5, gemini-3.5-flash) are graded per frame first to pick a candidate (S-1.18.5).
- **Multilingual verification rule.** A claim is not called fabricated until the non-Latin speech has been checked, native digits included. Judges and checkers that read only Latin script inflate fabrication counts on this corpus.

**Alternatives considered.**

- *Tighten the prompt again with the converse rule ("say 'on screen' only where a span exists").* Rejected as the primary fix: the last prompt rule moved the error rather than removing it, and a third rule may move it again. It is cheap, so it can ride along with S-1.18.8, but it is not relied on.
- *Ship the deterministic check as a warning in the processing note.* Rejected: about eight false flags per report would teach readers to ignore the note.
- *An LLM audit pass after compose.* Viable (the sweep found what the judges missed). It is deferred, not rejected: provenance makes errors less likely at the source, and an audit would then have less to catch. It is reconsidered after the S-1.18.8 measurement.

**Consequences.** The visual feature stays opt-in and off by default, now with measured quality and known failure modes. S-1.18.8 touches the map and compose prompts and the item schema, so it is serialised after the R5 session's prompt work and after S-1.14.6.

**Implemented 2026-10-19 (S-1.18.8 T-1 to T-3, PR [#277](https://github.com/khoks/VideoResearchPro/pull/277)).** Choices made inside this decision, open to revision:

- *Code overrides the model where code can know.* An item from a source with no visual annotation is `said`, whatever the model labelled it; the model's value is kept as `modality_model` in the persisted map record (S-1.14.6) so its labelling can still be audited.
- *Unknown is a label, not a default.* A missing or unusable label becomes `unknown` and renders as `[UNLABELLED]`, which sends the composer back to the contract's own rules. Defaulting to `said` would recreate the error this decision exists to remove.
- *The same item with different evidence is `both`.* Overlapping chunks can extract one item from the speech and again from a span; the lossless reduce keeps the union rather than whichever came first.
- *Tags only when they can matter.* Compose renders tags, and the instruction for them, only when the corpus has a shown or both item. A corpus without visual evidence would otherwise get `[SAID]` on every item.
- T-1.18.8.4 (check the composed report against item provenance, then re-run the S-1.18.3 protocol) is not part of this change.

**Linked initiatives / PRs.** S-1.18.2 (deferred), S-1.18.5, S-1.18.6 (T-3 done), S-1.18.7 (measured), S-1.18.8 (T-1 to T-3 shipped), S-1.14.6.

**Status-changed 2026-10-25:** kept by [D-109](#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25): the post-compose LLM audit deferred here is way back (e), taken only if the owner asks and checked offline on runs 1 to 10 first; the S-1.18.8 re-run that was to trigger it (T-1.18.8.4) is deferred with R1.

## D-076 — Model guidance: "measured" means the use case's own output was graded; verdicts warn, never block (2026-10-19)

**Status:** accepted. Item 3 is open to the user as OQ-16 in [E-1.14](initiatives.md#e-114--model-tier-quality-evaluation-harness).

**Context.** E-1.14 measured tier quality per use case (D-055 to D-062, D-073), but the verdicts lived only in this log. The `/account/ai-models` override page therefore offered a raw model picker, and nothing warned an operator whose `LLM_USE_CASE_CONFIG` pointed frame description at a model graded unusable. S-1.14.7 moved the evidence into `USE_CASE_REGISTRY`, which forced three choices the decisions themselves never made.

**Decision.**
1. **A use case is `measured` only when its own output was graded.** That gives 8 measured entries. The other 15 are `unmeasured`, each with a note on what evidence exists. Three kinds of evidence do not count:
   - sitting inside a graded chain (refine, knowledge extraction);
   - sharing a prompt contract with a graded site (the library answer);
   - moving tier alongside a graded site (the eight volume-tier sites that followed `report_map_chunks` to luna in D-057).
2. **Verdicts are per model and scoped to reasoning levels, in two strengths.**
   - `unacceptable`: the measurement produced unusable output. Examples: luna on frames (22 of 66 gradings), claude-haiku-4-5 on frames (55 of 62, although it accepts images), nano on map batches (unparseable JSON on 1 of 2), luna or gpt-5.4-mini with reasoning on (empty output).
   - `weaker`: measurably below the default on the decision's own grading, but usable. Examples: sonnet-5 on compose; mini and flash-lite on frame selection, judged by agreement with the default's picks, which D-073 itself says is not a quality measure.

   Model ids match exactly, as on `VISION_CAPABLE_MODELS`, so `gpt-5.5` cannot catch `gpt-5.5-pro`.
3. **Warnings advise; nothing refuses a config.** This applies at the PUT, at resolve time and at startup. It is the same fail-soft rule [D-067](#d-067--visual-understanding-separate-frames-table-marker-in-text-annotation-opt-in-per-job-2026-07-31) set for the vision allowlist.

**Alternatives considered.**
- *Mark a use case measured when its chain was graded.* Rejected: it would put a sibling's numbers behind a choice nobody measured. That would be a guidance version of the defect D-055 found, where the registry described a call by numbers that no longer applied to it.
- *A single severity.* Rejected: sonnet-5 on compose reads better (8 vs 7) and is a defensible trade, while luna on frames produced 22 unusable gradings out of 66. One warning colour for both would teach users to ignore it.
- *Refuse `unacceptable` choices at `PUT /settings/llm`.* Not taken for now. The verdicts rest on small samples (n=2 on map batches), the vision list always lags new releases, and the override page exists so that users can choose differently. The block would be one line in the PUT handler; recorded as OQ-16.
- *Keep guidance in a separate table keyed by use case.* Rejected: a required field on `UseCaseInfo` means a new call site cannot ship without stating its evidence, and the registry test enforces that.

**Consequences.**
- Promoting a use case to `measured` now requires a decision entry. `tests/test_services/test_llm_guidance.py` pins the measured set and fails on any cited decision id missing from this log.
- `assess_choice()` on the server and `assessChoice` on the page must change together.
- A re-measurement that changes a verdict is a registry edit plus a decision, not just a decision.

**Linked initiatives / PRs.** [S-1.14.7](initiatives.md#e-114--model-tier-quality-evaluation-harness), PR [#251](https://github.com/khoks/VideoResearchPro/pull/251). Follows D-052, D-055, D-056, D-057, D-062, D-072, D-073.

**Status-changed 2026-10-25:** kept by [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) — item 3 stands: a model measured `unacceptable` is warned about, not refused (OQ-16), since the verdicts rest on n=2.

## D-077 — Scheduler: one static beat entry over table rows; beat is its own process with no pidfile (2026-10-19)

**Status:** accepted.

**Context.** Nothing in the app ran on a schedule. Saved searches (E-8.3), the newsletter (E-6.4) and Echo connector syncs (S-3.2.1) all need "run X for tenant T at cadence C", and the [M3 plan](plans/m3-saved-searches-alerts.md) chose a shape: one static Celery beat entry plus rows in SQLite. Building S-8.3.1 on Windows forced two choices the plan did not name: how to guarantee a single beat process, and how cadences compute across time zones.

**Decision.**
1. **Beat fires one task, `scheduler.tick`; the schedule is rows in `scheduled_runs`.** The tick claims each due row with one conditional `UPDATE … WHERE claimed_at IS NULL OR claimed_at < now − lease`, dispatches it on the owning tenant's tier queue, and advances from `max(now, next_run_at)`, so a duplicate or early tick never runs a row twice.
2. **Beat is a separate process started by `scripts/start.ps1` and `scripts/restart_services.ps1`, which kill any earlier beat first. No `--pidfile`.** Celery's stale-pidfile probe is `os.kill(pid, 0)`, which on Windows terminates whatever process now owns that pid.
3. **Cadences are human, never cron**, and `next_run_at` is computed by Celery's own `crontab` on the row's local wall clock, then converted to UTC, so 09:00 local stays 09:00 local across DST.
4. **Kinds register from the task module that defines their task.** A worker that lacks the module records `no_handler` and advances the row rather than retrying it every tick.

**Alternatives considered.**
- *Embedded `worker -B`.* Rejected. Celery calls it unsuitable for production, and it is unverified with `--pool=solo` on Windows.
- *`--pidfile` as the singleton guard.* Rejected for the Windows reason above.
- *RedBeat or another dynamic beat store.* Rejected by the plan: rows keep the schedule inside the SQLite backup; RedBeat stays the upgrade path for highly available beat.
- *Cron strings or `croniter`.* Rejected: users never see cron, and `crontab` already covers daily, weekly and monthly.
- *Retry a failed dispatch only at the next cadence slot.* Rejected: a broker blip would delay a weekly run by a week. Failed dispatches retry at the next tick up to `SCHEDULER_MAX_RETRY_TICKS` times.

**Consequences.** Exactly one beat per install is now an operator rule, enforced only by the launchers; a hand-started second beat doubles the tick load, though the lease still prevents double dispatch. `day_of_month` is capped at 28, so there is no "last day of month" cadence. S-8.3.2 registers `saved_search` and S-6.4.2 registers `newsletter` from their own task modules, and each must add its module to `celery_app.autodiscover_tasks`.

**Linked initiatives / PRs.** [S-8.3.1](initiatives.md#s-831--scheduler-tick-shared-infrastructure) (PR [#238](https://github.com/khoks/VideoResearchPro/pull/238)), S-8.3.2, S-6.4.2, S-3.2.1.

## D-078 — Search index: one trigram FTS5 table per entity, copies not external content, LIKE fallback (2026-10-19)

**Status:** accepted. Deviates from the [M2 plan](plans/m2-command-palette.md)'s sketch in two places, both recorded here.

**Context.** S-8.2.1 adds `GET /api/v1/search` over jobs, documents, channels, Q&A exchanges and knowledge reports. The plan sketched FTS5 external-content tables with a `unicode61` table plus a `trigram` table per entity, and a `LIKE` fallback where FTS5 is missing. It also required that a tenant with nothing visible gets nothing, never everything (D-063).

**Decision.**
1. **One `trigram`-tokenised FTS5 table per entity** (`fts_documents`, `fts_jobs`, `fts_channels`, `fts_qa`, `fts_knowledge`), tokenizer `trigram remove_diacritics 1` where SQLite ≥ 3.45 supports it, else plain `trigram`.
2. **Each FTS row carries the entity id as an `UNINDEXED` column and a copy of the indexed text**, kept current by `AFTER INSERT / UPDATE OF <indexed columns> / DELETE` triggers. Not external-content tables.
3. **Tenant scoping joins each entity's anchor onto the FTS hit list**, never a tenant column inside the index: `jobs.tenant_id`, `document_visibility` on `document_id` (D-070), subscriptions ∪ visible documents' channels (D-065), and `*_qa_exchanges.tenant_id`.
4. **The tables are created conditionally** by migration `a9f3c1e7b5d2` and re-ensured at every boot, so a Python upgrade that gains FTS5 later still gets them. Without FTS5, and for queries whose tokens are all shorter than three characters, search scans with `LIKE`. `GET /health` reports `search_backend`.
5. **Document hrefs key on `document_id`** (`/library?document=<id>`), because most non-video documents have no `video_id`.

**Alternatives considered.**
- *`unicode61` plus `trigram` per entity (the plan).* Rejected. The trigram tokenizer alone covers word prefixes, mid-word substrings, case and diacritics folding, and Devanagari, so the second table doubled the triggers for no gain at this scale.
- *External-content tables (the plan).* Rejected. `content=` mode maps on rowid, and every base table here has a string primary key whose rowid is not stable across `VACUUM`. The copied text is small except the knowledge Markdown.
- *A tenant column inside the FTS table.* Rejected. It would duplicate the visibility model and drift from it; joining the canonical anchors keeps one source of truth.
- *`LIKE` only.* Rejected: no ranking, and full scans of description and knowledge text.

**Consequences.** `schema_init_service` ignores the `fts_` prefix when comparing the live schema to the ORM; any future non-ORM table needs the same treatment. The index costs disk roughly equal to the indexed text. Linux distro Pythons without FTS5 get working but unranked search. A query of only one- and two-character words never uses the index. The palette (S-8.2.2) owns teaching the library page to read `?document=`.

**Linked initiatives / PRs.** [S-8.2.1](initiatives.md#s-821--search-endpoint) (PR [#245](https://github.com/khoks/VideoResearchPro/pull/245)), S-8.2.2, S-8.2.3, [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19).

## D-079 — Report Markdown source on markdownify; new report routes are header-bearer only (2026-10-19)

**Status:** accepted. Item 2 deviates from the S-6.1.2 story text; the user may revisit it.

**Context.** S-6.1.2 gives every report a Markdown source that the book, the site index, the newsletter's plain-text part and `GET /jobs/{id}/report.md` read. The [L2 plan](plans/l2-author-studio.md) chose `markdownify`. The story asked for the `.md` route to use "the HTML route's auth", which accepts a `?token=` query parameter because iframes cannot send headers. S-8.8.1, merged first, had already made the reader's body route header-only to keep tokens out of URLs and logs.

**Decision.**
1. **`report_service.report_markdown(job)` converts the stored HTML with a `markdownify` subclass** and caches the result at `<report_path>.md`. It drops the document head and stylesheet, uses ATX headings, never autolinks (a citation stays `[text](href)` with its `&t=`), and turns the statistics grid into a table. Book chapters use it with the report's H1 dropped and its headings demoted under the chapter heading.
2. **Every new report route is header-bearer only.** `GET /jobs/{id}/report.md` does not accept `?token=`; browsers fetch it with the header and save a blob, as Author downloads already do. The legacy HTML route keeps its query-token fallback until T-8.8.1.5 retires it.

**Alternatives considered.**
- *`html2text`.* Rejected: GPL-3.0.
- *trafilatura's Markdown mode.* Rejected: a boilerplate stripper that drops report content.
- *Reuse S-8.8.1's `extract_report_body` for the Markdown.* Not adopted. The reader needs the template's parts; the Markdown needs the whole document, and only the statistics grid is template-specific in the converter.
- *`?token=` on the `.md` route, as the story said.* Rejected: it would reopen the URL and log leak S-8.8.1 closed, for a file that is always fetched by script.

**Consequences.** New dependencies `markdownify` (backend) and `remark-gfm` (frontend, so the Author reader renders the manuscript's tables). Any future link that opens a report file in a new tab must fetch with the header first. The cache is a second file per report; `delete_report` removes both.

**Linked initiatives / PRs.** [S-6.1.2](initiatives.md#s-612--markdown-source-for-reports), [S-6.1.1](initiatives.md#s-611--source-picker-and-a-working-author-page) (PR [#255](https://github.com/khoks/VideoResearchPro/pull/255)), S-8.8.1, T-8.8.1.5, S-6.1.4.

**Status-changed 2026-10-25:** ratified by [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) — both items, the header-bearer-only deviation from the S-6.1.2 story text included.

## D-080 — Code-mixing detection: a lexicon tagger, not an LLM pass (2026-10-19)

**Status:** accepted. Implements T-1.16.2.1 of [N-002](inventions.md#n-002--proportion-driven-rendering-policy-for-code-mixed-speech-2026-07-31); extends [D-066](#d-066--language-contract-temporal-awareness-and-corpus-aware-qa-length-2026-07-31). Method and numbers: [the detection note](notes/2026-10-19-code-mixing-detection.md).

**Context.** `language_service` profiles scripts exactly and cannot see Hindi written in Latin letters, which is the case N-002 targets. The task was to measure at least two ways of finding romanised Hindi before choosing one. Three Hinglish topic jobs on the dev backend gave the first finding: YouTube captions Hindi speech in Devanagari, English words included ("इट इज नॉट बीइंग एक्सप्लीसिटली प्रोग्राम"), and its English captions of Indian podcasts are English-dominant. Romanised Hinglish appears in the comments under those videos, and in the Reddit, chat and social sources the roadmap adds. The 300-unit labelled set therefore combines 180 real comments with 120 caption windows (Latin Indian English, Devanagari Hinglish, English tech talk), labelled per token and split one third DEV, two thirds TEST.

**Measurements (held-out TEST, 168 Latin and 34 Devanagari units).**

| | Latin token P | Latin token R | Latin F1 | Devanagari F1 | Cost |
|---|---|---|---|---|---|
| Lexicon + n-gram + Viterbi | 0.929 [0.88, 0.96] | 0.890 | 0.909 | 0.868 | none, ~1 ms per unit |
| `gpt-5.6-luna`, reasoning off | 0.803 [0.74, 0.85] | 0.895 | 0.847 | 0.965 | ~24K in + 12K out tokens per hour of speech |

Both caught 28–29 of the 30 Hindi-bearing Latin units. The lexicon tagger flagged one word in each of 4 of 138 English units; the LLM flagged none. The LLM also named the matrix language correctly on 60 of 62 mixed units.

**Decision.** The lexicon tagger (`code_mixing_service.tag_tokens`) is the production detector. It is more precise on romanised text at the same recall, with non-overlapping intervals on precision; it is deterministic, so a chunk's profile never changes between runs; and it is cheap enough to run on every chunk of every transcript at chunk time, with no ingest step, no persistence and no backfill. The LLM detector stays registered as `code_mixing_detect`. It is the evaluation harness's reference and the better instrument for English written in Devanagari, but it is not on the ingest path.

**Alternatives considered.**

- *LLM pass at ingest.* Rejected as the primary detector. It is less precise on romanised text, because it returns whole clauses as "Hindi runs" and swallows the English nouns inside them, which is exactly the insertional pattern N-002 measures. It would also add an ingest step and a persisted profile per document, and its output format drifted between batches (see the next point).
- *Strict span matching of the LLM's output.* Rejected after measurement. On some Devanagari batches the model returned all of a snippet's Hindi words as one span with the English words dropped; matched literally, Devanagari recall fell to 0.48. The mapper now matches spans as in-order subsequences with bounded gaps, which keeps the skipped words English and never reads the labels.
- *An off-the-shelf language-ID library* (lingua, fastText lid.176, CLD3). Not evaluated: none ship a romanised-Hindi class, and the venv has none installed. They label documents, not tokens, and the task was to measure rather than assume a library solves the problem.
- *Hybrid: lexicon for Latin text, LLM for Devanagari text.* Deferred. The lexicon tagger's Devanagari blind spot changes the Hindi share (MAE 0.236) but not the N-002 rendering decision on this data: all 50 labelled Devanagari units are Hindi-matrix and Hindi-dominant either way. It becomes worth building if the end-to-end evaluation (T-1.16.2.6) finds English-matrix speech in Devanagari changing a decision.

**Open questions (recorded, not decided).**

1. *Labeller.* The labels are Claude's (Opus 5.5), not a native speaker's. A native spot check of the 42 Hindi-bearing Latin units and 10 Devanagari units would take about half an hour, and should come before the numbers are used to compare future detectors.
2. *Where romanised Hinglish enters in volume.* Not YouTube captions, on this evidence. Whisper on Hinglish audio could not be tested (yt-dlp is bot-walled). Whether Whisper romanises, writes Devanagari or silently translates Hinglish decides how much of the problem the podcast and Whisper paths carry.

**Consequences.**

- `code_mixing_service` (tokenizer, lexicon tagger, LLM detector, span mapper) and `code_mixing_eval` (gold parsing, scoring). The lexicon files live in `app/services/lexicons/`, and DEV-derived additions sit in marked sections.
- Registry entry 24, `code_mixing_detect`: volume tier, reasoning off, fail-soft, not a feature gate.
- `tests/fixtures/code_mixing/` holds the labelled set and the LLM's cached answers. The test suite scores both detectors without calling a provider and fails if the lexicon tagger drops below its measured held-out precision and recall.
- Found in passing, not fixed: `_fetch_transcript_once` falls back to the first listed caption track, which ingested a machine-dubbed Bengali transcript of a Hindi lecture (`1v3_AQ26jZ0`).

**Addendum (2026-10-19): matrix language, T-1.16.2.2.** The matrix
language comes from a vote of system morphemes (Matrix Language Frame), not
from word counts and not from the LLM. On 62 held-out mixed units the vote
named the grammar's language in 0.952 of cases, word majority in 0.855, and
the LLM in 0.968. All nine of word majority's misses were Hindi-grammar
sentences with mostly English words, which is the case N-002 exists for. The
vote is free and deterministic and reuses the tagger's output, so it ships.
The 0.016 gap to the LLM (one unit) does not justify a model call per span.
A 29-word closed list of English function words as Hindi ASR spells them
(इज, टू, द) is now tagged English, which lets an English-matrix sentence
written in Devanagari be recognised as one. Details in [the detection
note](notes/2026-10-19-code-mixing-detection.md#7-matrix-and-embedded-language-t-11622).

**Addendum (2026-10-19): rendering policy, T-1.16.2.3.** The rendering
policy is `rendering_mode(analysis)`. It gives native script for
Hindi-grammar spans with Hindi share ≥ `CODE_MIX_DOMINANT_SHARE` (0.6),
plain English for English-grammar spans with Hindi share ≤
`CODE_MIX_BORROWING_MAX_SHARE` (0.2), and Roman script throughout for
everything between. Defaults were chosen on DEV as the centres of the
plateaus where the detector's decision matches the gold decision; on TEST
they agree on 0.970 of Latin units and 0.823 of mixed units. D-066's
three-part rule is unchanged. In Roman mode the original is already
romanised, so original and transliteration are written once. **Open
question 3 (the user's call):** what the dominant threshold should rest on.
Reader preference cannot be measured here. Robustness can: Devanagari
decisions agree with gold 0.912 of the time at 0.5, 0.824 at 0.6 and 0.647
at 0.8, because the tagger overstates the Hindi share of Devanagari
Hinglish. The default stays at the user's 60%; the measurement favours 50%
until English nouns in Devanagari are visible to the tagger. **Open
question 4:** whether Roman-mode quotes should also carry the Hindi words in
Devanagari, as the user's original message proposed ("Hindi/Urdu words in
their scripts"). N-002's own rule for heavy interleaving is "one script
throughout", so this is not done. Details in [the detection
note](notes/2026-10-19-code-mixing-detection.md#8-proportion-thresholds-as-a-rendering-policy-t-11623).

**Addendum (2026-10-19): one primary language per transcript,
T-1.16.2.4.** `profile_transcript` resolves a source's primary language from
the grammar of its sentence-sized windows, not from word counts, and applies
the policy once. A span decides only whether it is English, and the source
decides the script. On the library this removes 25 script changes across
seven Devanagari Hinglish transcripts and 128 across eleven romanised comment
threads. Measuring it exposed a silent failure: only Devanagari, Arabic and
Gurmukhi words had counted as non-English, so two Bengali and two Kannada
transcripts read as 0% non-English. Every non-Latin script now counts, and
the profile records which one (`native_script`). Details in [the detection
note](notes/2026-10-19-code-mixing-detection.md#9-transcript-level-primary-language-t-11624).

**Addendum (2026-10-19): the quotation half of the bidirectional split,
T-1.16.2.5 part A.** The measured profile travels as `code_mix_*` chunk
metadata, absent for English sources. Source headers in the report map and
in Q&A name each non-English source's language and quote form. Map items may
carry the speaker's `original` wording beside the English `content`, and
compose attaches the source's quote form to it from metadata. Before this,
the report pipeline translated at the map stage and kept no original wording
for D-066's three-part rule to quote. Library Q&A gets recognition but not
the English quote forms, because it answers in a requested language. The
retrieval half (embedding an English rendering) was measured first: MRR 0.565
for Devanagari chunks, 0.402 romanised, 0.805 English. It is decided
separately. Details in [the detection
note](notes/2026-10-19-code-mixing-detection.md#10-the-bidirectional-split-t-11625).

**Addendum (2026-10-19): held-out evaluation, T-1.16.2.6.** The evaluation
ran on sources nothing was tuned on and forced two changes. (1) An
English-primary source whose Hindi share is at least 3%
(`DOCUMENT_PRESENCE_SHARE`) now carries the profile. English talks read
0.0–0.6% and none of the library's 214 crosses the line. Comment threads
under Hinglish videos read 3.3–30%, and with 13–17% Hindi they had been given
no metadata at all. (2) Compose resolves quote form per item: the source
chooses the script, and the span still decides whether it is English. On
held-out data there was no Hinglish passed through at extraction in six runs,
either with N-002 or without it; the failure occurred at fetch instead
(S-1.11.11). Details in [the detection
note](notes/2026-10-19-code-mixing-detection.md#11-end-to-end-evaluation-on-held-out-sources-t-11626).

**Addendum (2026-10-19): kept wording is verified in code.** The R1
run-5 replay showed the prompt-only "copy EXACTLY" failing: Hindi speakers
were quoted in Bengali script in strings found in no transcript. Every map
`original` is now checked against its OWN source's speech by
`app/services/quote_fidelity.py`, the same rule the run-6 gate audits with.
It requires no mixed-script words, the source's own script, and verbatim or
≥ 80% aligned fragments. A failing original is dropped, the English point is
kept, and the drop is disclosed. The tolerance is deliberate: an
exact-substring check dropped near-verbatim quotes where the model had only
regularised caption spelling. On run 5 the check drops exactly what the
audit fails (4 of 37 and 12 of 51). Details in [section 12 of the detection
note](notes/2026-10-19-code-mixing-detection.md#12-regression-invented-original-wording-and-the-fix-2026-10-19).

**Addendum (2026-10-19): the composed report is checked too, and romanised
sources are quoted in Roman.** R1 run 7's composer translated an item's
English back into Devanagari ("वेरी इंपॉर्टेंट लाइब्रेरी (very important
library)") beside a verbatim `original`, so a map-level check alone cannot
guarantee that non-English text in a report is speech. After composing,
`quote_fidelity.scrub_report` looks every native-script run in the prose up
in the corpus by the gate's rule. It removes each failing run and its
transliteration, keeps the English, and counts and discloses the removal.
Titles and channel names are admitted. On runs 5–7 it removes exactly what
the gate fails (2, 8, 0, 0, 1, 0 per report) and leaves none failing. The
same reasoning decides T-1.16.2.11: a source typed in Latin letters is
quoted in Latin letters even when it is Hindi-dominant. N-002 had said
Devanagari, but that means re-scripting the speaker's words, which this
check would remove as unspoken. The rejected alternative was to transliterate
before matching: no exact Devanagari-to-Roman transliterator exists here,
and the reader would still see a script the speaker did not use. Details in
[section 12 of the detection
note](notes/2026-10-19-code-mixing-detection.md#12-regression-invented-original-wording-and-the-fix-2026-10-19).

**Linked initiatives / PRs.** S-1.16.2 (T-1.16.2.1 to T-1.16.2.6, T-1.16.2.10 to T-1.16.2.13), E-1.16, N-002, T-1.18.8.4.

**Status-changed 2026-10-25:** kept by [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) — the dominant threshold stays at 0.6 until the native-reader spot check (T-1.16.2.7), since the 0.912 against 0.824 figures rest on Claude's labels.

## D-081 — Frame describer default: spend against report-level quality (2026-10-19)

**Status:** accepted 2026-10-19 — **the user chose option 2, gpt-5.5**, "for the strongest report-level result", accepting about $0.20 per video for the visual pass. Supersedes D-073's describer choice; D-073's selection tier (gpt-5.5 at low reasoning) stands. Claude had recommended option 1; the recommendation is kept below for the record.

**Context.** [D-073](#d-073--frame-description-moves-to-gemini-31-flash-lite-on-image-grounded-grading-selection-stays-on-gpt-55-2026-10-19) moved frame description to gemini-3.1-flash-lite to meet a $0.10-per-video ceiling. [D-075](#d-075--r1-after-three-runs-the-modality-boundary-needs-provenance-not-prompt-rules-2026-10-19) found that the report-level benefit disappeared with that describer, and that the describer must be chosen at report level. Four report-level runs and two per-frame gradings now exist ([protocol note](notes/2026-10-18-r1-visual-measurement.md)).

| Describer | Per-frame accuracy (unusable) | Judges prefer annotated report | Substance ON vs OFF | Visual pass $/video (select gpt-5.5 low + describe) |
|---|---|---|---|---|
| gpt-5.5 | 4.54 (5/62) | **3/3** | **8.67 vs 7.67** | **$0.200** |
| gemini-3.5-flash | **4.70 (0/62)** | 2/3 | 7.67 vs 8.00 | $0.118 |
| gemini-3.1-flash-lite (current) | 4.21 (5/66) | 1/3 | 7.67 vs 7.67 | $0.075 |

Every configuration still has one or two attribution errors per report, so the UI stays deferred whichever is chosen (S-1.18.8 addresses that).

**Options.**

1. **gemini-3.5-flash, ceiling raised to about $0.12 (recommended).** It is the most accurate describer, and the only one with no unusable description, which matters most for a research tool: a misleading frame description is worse than a less complete one. It keeps most of the report-level gain at 60% of gpt-5.5's cost. A 200-video job adds about $24, against about $12 for the report itself.
2. **gpt-5.5, ceiling raised to about $0.20.** It gives the strongest report-level result, from one run. A 200-video job adds about $40.
3. **Keep gemini-3.1-flash-lite at $0.075.** It meets the original ceiling but delivered no measurable report-level benefit.

All single-run evidence. The S-1.18.8 protocol re-run should carry both of the first two describers as arms, so the default can be revisited on two runs each.

**Linked initiatives / PRs.** T-1.18.5.6, S-1.18.8. Follows D-073, D-075.


## D-082 — Job templates: identity plus immutable versions, provenance without a foreign key, starters in a self-contained data migration (2026-10-19)

**Status:** accepted. Taken by Claude while building [E-8.6](initiatives.md#e-86--job-templates-m6) (S-8.6.1, S-8.6.2) under the lane brief to follow the [M6 plan](plans/m6-job-templates.md) and take its recommended defaults.

**Context.** The plan chose Grafana-style versioned templates and sketched one table, `job_templates(..., version, parameters_json, is_latest)` unique on `(tenant_id, name, version)`, with `jobs.template_id` + `jobs.template_version` for provenance. In that shape a template's identity is its name, so a rename either breaks the chain or rewrites history. Building it also surfaced three gaps the plan assumed away: the Duplicate flow it builds on dropped fields; `JobCreate` has no `source_types` (nothing writes `jobs.source_types_json`), although the plan froze it into templates and two proposed starters needed it; and channel-type starters cannot know a reader's channels.

**Decision.** Two tables: `job_templates` holds identity and editable metadata (name, description, `builtin_key`, soft-delete `deleted_at`), and `job_template_versions` holds immutable parameter rows (newest 20 kept). A run records `(template_id, template_version)` with **no foreign key**, so provenance outlives a soft delete. Template parameters are exactly `JobCreate` minus the run-time fields. A test pins `frozen ∪ variable = JobCreate fields`, so a new field must be classified rather than silently dropped by every template. Every save is validated as a submission would be.

1. **Run-time fields:** the topic always; channels only when a channel or subscription recipe leaves `channel_list` empty ("add them each run"). `{topic}` in instructions is filled server-side at submission for every topic run.
2. **Starters** are seeded by a data migration (`f1a2b3c4d5e6`) that carries its own frozen copy of the definitions and an idempotent, versioned upsert: identical is a no-op, changed parameters become the next version. A revision is a new migration that copies them; app code never feeds a migration.
3. **Starter set.** Topic scan, Deep dive, Quick brief, Channel deep-dive and Subscription follow. The plan's podcast digest and mixed-source debate wait for `source_types` on job creation.
4. **The visual-analysis flag is carried, never offered.** Duplicate and templates keep a run's `visual_analysis`; the submit form shows it with "Turn off" but has no opt-in, because that toggle is T-1.18.2.1, deferred by [D-071](#d-071--r1-verdict-annotations-win-on-substance-fail-on-attribution-and-cost-ui-deferred-2026-10-19) and [D-075](#d-075--r1-after-three-runs-the-modality-boundary-needs-provenance-not-prompt-rules-2026-10-19). No starter turns it on.
5. **The relative publish window (`published_after_days`) is split out:** it must reach the search agent's ranking prompt as a preference, which the lane could not edit.

**Alternatives considered.**
- *The plan's single table.* Rejected: identity keyed on the name breaks under rename, for no gain over a version table.
- *A foreign key from `jobs.template_id`.* Rejected: with a hard delete it would null provenance; with soft delete it adds a constraint SQLite here does not enforce anyway.
- *Starter definitions in app code, read by the migration.* Rejected: an old revision would change meaning whenever the module changed.
- *A visual-analysis checkbox on the form* (the Duplicate story's literal ask). Rejected: it is the deferred R1 opt-in by another name.
- *Shipping the two source-type starters anyway.* Rejected: `JobCreate` would ignore `source_types`, so they would silently run video-only.

**Consequences.** Templates survive renames and deletes without breaking provenance, and a stale template cannot create an invalid run. Whoever wires `source_types` must extend `TemplateParameters` (the pinning test fails until they do) and may then add the two starters in a new data migration. The publish window and the wizard's starter step (T-8.6.2.2) remain open.

**Linked initiatives / PRs.** E-8.6 / S-8.6.1 / S-8.6.2, PRs [#263](https://github.com/khoks/VideoResearchPro/pull/263), [#265](https://github.com/khoks/VideoResearchPro/pull/265). Follows D-059 (preference, never filter), D-071, D-075.

**Status-changed 2026-10-25:** item 5's relative window is accepted by [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) (S-8.6.3), built after S-1.5.13.

## D-083 — Organisation features: access and scope defaults on the plans' open questions (2026-10-19)

**Status:** accepted as defaults. The questions were the user's call per the [M1](plans/m1-shelves.md) and [M6](plans/m6-job-templates.md) plans; the lane brief said to take each plan's recommended default and say so. Each is a one-line change if the user wants otherwise.

**Context.** Shelves, tags, templates and the channel page (E-8.1, E-8.6, E-8.7) shipped as PRs [#237](https://github.com/khoks/VideoResearchPro/pull/237), [#242](https://github.com/khoks/VideoResearchPro/pull/242), [#250](https://github.com/khoks/VideoResearchPro/pull/250), [#257](https://github.com/khoks/VideoResearchPro/pull/257), [#263](https://github.com/khoks/VideoResearchPro/pull/263) and [#265](https://github.com/khoks/VideoResearchPro/pull/265). Each plan left open questions; building them also forced a few shape choices the plans did not cover.

**Decision.**
1. **Shelves are readable on every tier; writing them needs the `shelves` capability** (Pro, Studio). A downgraded reader keeps their shelves read-only (M1 open question 1, the plan's recommendation).
2. **Tags and templates are not tier-gated.** They cost the operator nothing, the `shelves` capability is about grouping runs, and the pricing page advertises neither.
3. **Tags are rows** (`tags` + polymorphic `taggings`), as the M1 plan chose, not the free-string `document_tags` the board first listed. Rename keeps the id, merge is one update, and names are unique per reader on `lower(name)`. `taggings.target_type` accepts only `document` in v1 (M1 open question 2); jobs and channels need no schema change.
4. **Colour is one of ten named palette tokens** (Notion's set) stored by name, every pair at least 4.5:1 in both modes, never colour alone.
5. **Membership is embedded in the shelves listing** (`job_ids` on each shelf), so one cached `GET /shelves` answers "which shelves is this run on" for a page of cards instead of one request per card.
6. **The channel page shows the trust weight read-only** in the slot where [D-068](#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18)'s control will go. A control that saved a number nothing reads would mislead.
7. **Shelf URLs use ids, not slugs**, because names are renameable.

**Alternatives considered.** Hide shelves after a downgrade (loses the reader's organisation over a billing change). Gate tags as Pro (annoys without saving cost). Free-string tags (rejected by the M1 plan: leaks across tenants on a shared table, rename is a mass update). One membership request per job card (twenty requests per page). A writable weight control before E-7.1 (writes a value nothing reads).

**Consequences.** S-8.1.4 shelf-scoped Q&A resolves its set through `query_library_documents(..., job_ids=)` and inherits the empty-set rule (an empty shelf retrieves nothing). E-7.1 replaces the read-only weight slot with its control. If shelves move to read-and-write for all, or tags and templates become paid, it is one `require_feature` change per route plus the frontend mirror.

**Linked initiatives / PRs.** E-8.1 / E-8.6 / E-8.7, the PRs above. Follows D-063, D-065, D-068.

**Status-changed 2026-10-25:** ratified by [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) — every item stands except 6, which D-068's control replaced when S-7.1.1 shipped the weight slider.

## D-084 — Code-mixed retrieval: embed an English rendering, keep the original as the stored text (2026-10-19)

**Status:** accepted. Completes T-1.16.2.5 of [N-002](inventions.md#n-002--proportion-driven-rendering-policy-for-code-mixed-speech-2026-07-31) with [D-080](#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19)'s quotation half. Measurement: [the detection note](notes/2026-10-19-code-mixing-detection.md#10-the-bidirectional-split-t-11625).

**Context.** N-002 asks for analysis on an English rendering and quotation from the original. Every analysis stage is an LLM call that now knows each source's language (D-080 addendum) and translates as it reads. Retrieval is the one stage with no model in the loop: an English question is compared with chunk embeddings from `paraphrase-multilingual-MiniLM-L12-v2`. A content-controlled test used 132 real chunks from three Hindi-ASR lectures, with the same text in Devanagari, in romanised Hinglish, and in English, and 55 English questions written by a different model from the Devanagari alone.

| Pool written in | recall@5 | recall@15 (production depth) | MRR |
|---|---|---|---|
| Devanagari (as ingested today) | 0.727 | 0.818 | 0.565 |
| Romanised Hindi | 0.582 | 0.745 | 0.402 |
| English rendering | 0.891 | 0.927 | 0.805 |

**Decision.** A chunk of a non-English source is embedded as its English rendering when its own Hindi share exceeds the borrowing threshold or its grammar is Hindi. Its stored text, which is what Q&A shows and quotes, stays the original. The rendering is stored as chunk metadata `text_en`. It is produced once per document by a new volume-tier use case, `code_mixing_render_english` (`gpt-5.6-luna`, reasoning off, six chunks per call), inside `chroma_service.insert_chunks`, the one place every ingest path writes chunks. Embeddings for the batch come from the collection's own embedding function, so rendered and unrendered chunks share one vector space. The step is fail-soft (a failed batch embeds as written) and switchable (`CODE_MIX_ENGLISH_RENDERING_ENABLED`). It is off for the test suite, so no test reaches a provider.

**Alternatives considered.**

- *Keep embedding the original.* Rejected on the measurement. Romanised text, the case N-002 targets, loses about a third of its MRR against the same words in Devanagari.
- *Store the English rendering as the chunk text.* Rejected. Quotation needs the original (D-066's three-part form), and Q&A shows stored text to the answer model.
- *Two vectors per chunk (original and English).* Deferred. It doubles index size and needs result de-duplication, and the English vector alone already beats both originals.
- *A stronger multilingual embedder* (e.g. a larger E5 or BGE-M3 model). Not evaluated. It means re-embedding the whole library and a much heavier CPU model, and whether it reads romanised Hindi well is itself unmeasured. It would be worth measuring against this same pool before the library grows. Recorded as an open question.
- *Translate the question into Hindi instead.* Rejected. It does not help romanised text, and it puts translation on the latency path of every question rather than once per document.

**Cost.** The rendering used about 1.5 input and 1.0 output tokens per word of transcript, plus ~300 prompt tokens per call. That is roughly 11K input and 7K output tokens for an hour of Hindi speech, once per document, and nothing for English sources.

**Consequences.**

- Chunks embedded before this ship have no rendering and keep their original vectors. There is no backfill; re-ingesting a document re-embeds it.
- Questions retrieve Hindi and Hinglish sources by meaning, while quotes still come from the original wording.
- Registry entry 25, `code_mixing_render_english`, has measured guidance citing this decision.

**Linked initiatives / PRs.** S-1.16.2 (T-1.16.2.5), E-1.16, N-002.

## D-085 — Reading room: reports stay HTML, sanitised and parsed in the browser; one shared citation card fed by the run's documents (2026-10-19)

**Status:** accepted. Both open questions in the [M8 plan](plans/m8-reading-room.md) were taken at its recommended defaults: retire `?token=` later (T-8.8.1.5 stays open), and keep the iframe modal as a quick peek.

**Context.** Reports are LLM-written HTML documents, one file per job, read until now in an `<iframe>` whose `src` carried the JWT as `?token=`. The reader (E-8.8) had to render them inside the app's own DOM with the app's typography, an outline and citation cards. Four of the six stored reports predate S-1.14.9, so their timestamp anchors are a bare `href="&t=123"` with no video URL. A report can carry 277 citations.

**Decision.**
1. **Reports stay HTML; the browser sanitises, then parses.** `GET /jobs/{id}/report/body` (new `routers/reports.py`, so the serialised `routers/qa.py` stays untouched) returns `{title, html, statistics, generated_at}` under header-bearer auth only. `report_service.extract_report_body` splits the template's parts back out. The client runs **DOMPurify** first (dual MPL-2.0 / Apache-2.0; **Apache-2.0 elected**), forbidding `style`, `script`, embeds, forms, SVG and MathML and dropping `style=` attributes. It then runs `html-react-parser`, whose one `replace` hook assigns heading ids, collects the outline, turns `&t=` anchors into citation chips, wraps tables in a scroll region and marks the drop cap. The parser is never fed unsanitised input.
2. **One citation card for all chips**, using the Popover API (top layer) and positioned from the chip's `getBoundingClientRect`, with a fixed-position fallback. The context value changes only with the citation index, so hovering never re-renders the chips, and `aria-describedby` is set on the active chip imperatively.
3. **Sources come from the run's own document list.** A citation resolves by the YouTube id in its href, then the href against document URLs. For bare anchors it tries the longest known title (or its hashtag-free stem) in the enclosing paragraph or list item, then a channel that has exactly one document in the run. An absolute href never resolves to a different document by title. Identical targets share one footnote number, so the endnote list dedupes (277 chips → 181 notes).
4. **Print** is a stylesheet plus an endnote list that opens itself on `beforeprint`. Chips print as the writer's text plus `[n]`.

**Alternatives considered.**
- *Convert reports to Markdown and render with react-markdown.* Rejected in the plan as lossy, and it would still need raw-HTML sanitising.
- *Keep the iframe and style it.* It cannot share typography, the outline or citation components, and it keeps the token in the URL.
- *`sanitize-html` or a rehype sanitise chain.* Heavier (`sanitize-html` is about 50 kB) or less audited than DOMPurify.
- *Server-side sanitising.* It would be a second policy to keep in step; the client must sanitise anyway, because the parser is not a sanitiser.
- *One card per chip.* At 277 chips that means 277 popovers and a re-render of every chip on each hover.
- *Replace the chip text with a superscript number on screen.* The timestamp is part of the writer's sentence ("— Simplilearn (16:56)"). Numbers appear in print and in the endnotes instead.

**Consequences.**
- The legacy HTML route keeps its query-token fallback until T-8.8.1.5. D-079 made every *new* report route header-only on the same reasoning.
- All 30 dead anchors in the stored smoke-test report became real links: 20 matched by title, and 10 by sole channel where the writer had reworded a Kannada title.
- `GET /jobs/{id}/videos` had to start declaring `source_type`, `document_id` and `source_metadata`. They had always been built and always stripped by the schema, which also made the job page's approval cards fall back to the YouTube shape.
- A report truncated mid-tag by the compose step cannot be repaired client-side; that is filed as S-1.14.17. The R1 still slot (`resolveStill`) waits for S-1.18.2.
- Vite 8's dependency optimiser broke `html-dom-parser`'s CommonJS client in dev only. An alias to its ESM client entry fixes it, in both the Vite and the vitest configs.

**Addendum (2026-10-25): the query-token fallback is retired, T-8.8.1.5 (widened to every HTTP caller).** No HTTP route takes a JWT from the URL any more.
- *Retired.* `?token=` on `GET /jobs/{id}/report` and on all six `/exports/*` downloads (`qa-dataset/{openai,tuple}.jsonl`, `knowledge-dataset/{openai,tuple}.jsonl`, `notes.jsonl`, `notes.md`). `get_user_from_query_or_header` is deleted, and the rate limiter no longer picks a user's bucket from a URL token, so such a request counts as anonymous.
- *What the browser does instead.* It fetches each file with the Authorization header and hands it over as a blob: URL (`services/apiFiles.ts`). The quick peek frames the report in an iframe sandboxed to `allow-popups allow-popups-to-escape-sandbox`, so nothing runs and the document has an opaque origin while its `target="_blank"` source links still open tabs. A blob: URL takes the app's origin, and "Open in new tab" shows the same bytes top-level where no sandbox applies, so the report HTML also gets a `script-src 'none'` CSP meta tag ahead of everything else. Exports save through `<a download>` on the object URL. PDF citations, whose `/library/pdf/{digest}.pdf#page=N` permalinks 401'd in a new tab (E-1.8), fetch the PDF and open its blob URL with `#page=` kept, in Q&A answers, in the reader's chips, card and endnotes, in an Echo draft's sources and from the knowledge reader's "Open the source". Frame stills already loaded this way (S-1.18.2), as did Author downloads (S-6.7.2).
- *What remains, and why.* The `/ws/jobs` WebSocket still authenticates with `?token=`: the browser WebSocket API cannot set headers on the handshake. That token still reaches access logs. Moving it into the first message, or a single-use ticket, is the remaining option and is not taken here. `tests/test_routers/test_url_tokens.py` walks every route's dependency tree and fails if an HTTP route reads a credential from the query string again; it finds the WebSocket's own parameter to prove the walk can see one.
- *Trade-off.* An export is now held in memory as a blob before the save dialog appears, where the link streamed straight to disk. A short-lived single-use download ticket in the URL would keep streaming, but it needs server state for six read-only routes and still puts a credential in a URL.

**Linked initiatives / PRs.** [S-8.8.1](initiatives.md#s-881--report-content-endpoint-and-sanitised-renderer) (PR [#244](https://github.com/khoks/VideoResearchPro/pull/244)), [S-8.8.2](initiatives.md#s-882--citation-hover-cards-and-footnotes) (PR [#254](https://github.com/khoks/VideoResearchPro/pull/254)), T-8.8.1.5, S-1.14.17, D-079.

## D-086 — Markdown readers: react-markdown's own pipeline run once with a tree transform; the outline is the two shallowest structural heading levels (2026-10-19)

**Status:** accepted. It deviates from the M8 plan's sketch (`<ReactMarkdown>` with `rehype-slug`) for the reason below.

**Context.** S-8.8.3 puts knowledge reports and Author Studio books, both Markdown, into the same `ReaderShell` as HTML reports. The shell renders the outline beside the body, so it needs the outline before the body renders. Books built since S-6.1.2 nest each report's sections as `####` under a `## n. Chapter` heading. Lane C's HTML-to-Markdown keeps a report's `<h3>`-inside-`<li>` as `- ### …`. The book outputter writes its table of contents against its own slug of the bare chapter title (`#chapter-title`) while the heading reads "1. Chapter title", so every link in that table was dead.

**Decision.**
1. **One pass in a `useMemo`:** remark-parse → remark-gfm → remark-rehype → one tree transform → hast-util-to-jsx-runtime. These are react-markdown's own steps. Headings get ids from the **same slugger as reports**, so `rehype-slug` is not a dependency.
2. **The outline is the two shallowest heading levels outside list items, table cells and quotes.** For knowledge reports that is `h2` / `h3`; for books it is chapters and their sections. Nested headings keep ids but neither pick a level nor enter the outline.
3. **In-page links whose target was slugged differently are repointed** to the heading whose id equals, or ends with, the slug of the fragment.
4. **Safety without DOMPurify on this path:** remark-rehype runs without `allowDangerousHtml`, so raw HTML is dropped, and link and image URLs pass react-markdown's `defaultUrlTransform`.
5. The Author page's viewer modal is removed. Read, and a freshly generated book, navigate to `/author/outputs/:id`, which completes T-6.1.1.3's moved half. The knowledge drawer stays as a quick peek with "Open in reader".

**Alternatives considered.**
- *`<ReactMarkdown>` plus `rehype-slug`, with the outline from a second parse.* Two pipelines that must agree on every id drift. Collecting the outline during render is impure, and its order relative to the sibling outline component is fragile.
- *Markdown → HTML → the report pipeline.* It needs a converter dependency and would route trusted-by-construction Markdown through the HTML sanitiser for no gain.
- *`h2` / `h3` only.* A book's outline would list chapters and nothing inside them.
- *Fix the book outputter's slugs.* Worth doing, but the reader should not depend on every producer agreeing with its slugger.

**Consequences.** The knowledge response now names its source (`document_id`, `source_type`, `title`, `channel_name`, `url`, `published_at`), and its `video_id` became nullable: a PDF's artifact had failed serialisation. `remark-gfm` became a direct dependency (D-079 had already added it). The bundle is one chunk, about 262 kB gzipped after the reading lane (+32 kB over three PRs). Lazy-loading the reader routes is the obvious follow-up.

**Linked initiatives / PRs.** [S-8.8.3](initiatives.md#s-883--knowledge-artifacts-and-books-in-the-same-shell) (PR [#261](https://github.com/khoks/VideoResearchPro/pull/261)), T-6.1.1.3, S-6.1.2, D-079.

## D-087 — Mobile reading and install: a reading toolbar below 1200 px, a docked composer lifted by VisualViewport, hermetic device tests, a manifest without a service worker (2026-10-19)

**Status:** accepted, emulation only. The [M12 plan](plans/m12-mobile-reading.md)'s open question 1 (is a real-device pass part of acceptance?) is the user's call; no real-device pass was done. Its open question 2 (which icon) had no recommended default; the icon renders the mark `branding.md` §3 already recommends.

**Context.** S-8.12.1 and S-8.12.2 make the reading pages work on phones and make the app installable. Three facts shaped them: the outline column already needs 1200 px (S-8.8.1); neither iOS Safari nor Chrome on Android (by default) shrinks the layout viewport for the on-screen keyboard; and the repository is public.

**Decision.**
1. **A bottom reading toolbar replaces the outline column and the progress pill wherever the column is hidden** (below 1200 px, not only below 960 px). It holds Contents (the outline as a bottom sheet), text size in five steps (Zustand, kept per browser), theme, and the percentage. Controls are 44 px, and `scroll-padding-bottom` keeps focus clear of the bar (SC 2.4.11).
2. **The Q&A composer moves under the thread on phones and sticks to the bottom while its card is on screen.** The thread is already oldest first. The composer is lifted by `innerHeight − visualViewport.height − offsetTop`, rAF-throttled and ignored when pinch-zoomed. It is a set of wrappers (`components/qa/Composer.tsx`), so each page changed by nine lines.
3. **Touch:** a chip's first tap previews its card and the second follows the link. Chip state is read at `pointerdown`, which also fixed an unresolved chip opening and closing its card in one click.
4. **Device tests are hermetic.** Playwright runs iPhone 13 (WebKit), Pixel 7 and a 320 px phone (Chromium) in light and dark, against 18 checked-in baselines. Every `/api/v1` call is served from captured fixtures, and an unmatched call fails the test. The WebSocket and dev proxy are cut off. The **Q&A thread fixture is synthetic**: the test account has none, and the user's own exchanges do not belong in a public repository.
5. **A web-app manifest with no service worker**, as the plan decided (JWT-gated fetches and report invalidation; offline reading is not a requirement). Chromium's installability check passes without one. `theme_color` `#7a2c1a` and the page title come from `branding.md` §8. The icon is an interim rendering of the §3 echo mark, re-rendered from `logo-mark.svg` by `npm run icons`.

**Alternatives considered.**
- *Drop the outline below 960 px only.* That leaves 960–1199 px with no navigation, since the column is already gone there.
- *Sticky composer at the top.* It is keyboard-proof without VisualViewport, but `ui-design` §2.4 and the plan ask for a bottom, chat-like dock.
- *`interactive-widget=resizes-content`.* Chromium only; iOS ignores it.
- *Device tests against a live backend.* They would depend on a running stack and real data, which could leak into a public repository's baselines.
- *A designed new logo.* Out of scope; the rebrand's logo work stays open.

**Consequences.** `npm run test:mobile` needs `npx playwright install chromium webkit` once, and a page that starts calling a new endpoint on load fails it until a fixture is added. `ui-design` §2.4 carries an "as built" note. The VisualViewport lift is unverified on a real keyboard. The manifest unblocks T-3.7.6.1 (`share_target`).

**Linked initiatives / PRs.** [S-8.12.1](initiatives.md#s-8121--reading-pages-responsive-pass) (PR [#269](https://github.com/khoks/VideoResearchPro/pull/269)), [S-8.12.2](initiatives.md#s-8122--web-app-manifest) (PR [#272](https://github.com/khoks/VideoResearchPro/pull/272)), T-3.7.6.1.

**Status-changed 2026-10-25:** amended by [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) — a real-phone pass is part of M12's acceptance (S-8.12.3), which answers the plan's open question 1; question 2 is settled by E-2.8: the interim echo mark it rendered is the identity.

## D-088 — Report intermediates: persisted per run, on by default, frozen at the stage that produced them (2026-10-19)

**Status:** accepted (taken without the user; open to revision).

**Context.** S-1.14.6's second half: the report pipeline kept its per-batch map extractions and the reduced dataset only in LangGraph state, so a map regression stayed invisible unless it spoiled the finished report, and every stage measurement since D-055 had to replay a job's inputs. S-1.18.8 (modality labels, [D-075](#d-075--r1-after-three-runs-the-modality-boundary-needs-provenance-not-prompt-rules-2026-10-19)) also needs the map items of real runs to check the composed report against item provenance.

**Decision.**

1. A `job_report_intermediates` table: one row per map call — bisected halves and failed batches included, with the error and the videos the batch covered — plus one row for the reduce output with its processing notes. Rows carry a `run_id`, so a regeneration sits next to the job's original run instead of replacing it.
2. **On by default** (`REPORT_INTERMEDIATES_ENABLED=True`). The cost is about twice the reduced dataset per run, ~3 MB on the 200-video reference job and kilobytes on small jobs.
3. Payloads are **serialised when the stage produces them**, not at persist time, because compose mutates the same item dicts afterwards (quote forms today, S-1.18.8's evidence tags next).
4. Capture follows the search agent's `candidates_out` pattern (`run_report_agent(..., intermediates_out=)`); the job task persists best-effort, before the HTML is built, so a later failure still leaves the record.

**Alternatives considered.**

- *Off by default, a debug flag.* The story's original wording. Rejected: the point is continuous monitoring, and a flag nobody turns on leaves the next regression as invisible as the last. The setting remains for operators who want it off.
- *Sampling (persist one job in N).* Would save storage that is not scarce, at the cost of the run that regressed being the one not sampled.
- *Store the map batches only and recompute the reduced dataset.* Reduce is deterministic, but the even-compression path (`_compress_evenly`) and compose's own normalisation make "what compose received" worth recording rather than re-deriving.
- *Replace the job's rows on each run.* Loses the before/after comparison a model or prompt change needs.

**Consequences.** `scripts/audit_report_intermediates.py` reads a run back: map calls by status, items by category (and by modality once S-1.18.8 lands), dropped chunks, and the reduce accounting identity (items in − exact duplicates − trimmed = items out). There is no retention policy; rows go when the job is deleted (FK cascade). Channel jobs have no map/reduce stage and write nothing.

**Linked initiatives / PRs.** S-1.14.6, E-1.14, S-1.18.8, PR [#273](https://github.com/khoks/VideoResearchPro/pull/273). Follows D-055, D-056, D-075.

**Status-changed 2026-10-25:** ratified by [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) — on by default, as taken without the owner.


## D-089 — Echo's privacy contract: context-only by default, the brain is a registry, the archive is the user's whole copy, delete in a fixed order (2026-10-19)

**Status:** accepted. Item 1 takes the [L3 plan](plans/l3-echo-personal-brain.md#open-questions-the-users-call)'s open question 2 at its recommended default. Item 3 is an interpretation **awaiting the user's confirmation**.

**Context.** The first new Echo table (`shares_inbox`, S-3.7.1) shipped in the same PR as the whole-brain export (S-3.10.1) and delete (S-3.10.2), as the build order requires. Four questions had to be answered for that to be true:
- what Echo may do with words the user forwards but did not write;
- which stores count as "the brain";
- whether the archive may carry those third-party words;
- how a delete across SQL, the filesystem and Chroma stays honest when one store fails.

**Decision.**
1. **Third-party content is context-only by default.** `shares_inbox.author_is_tenant` is false unless the user says the words are theirs (the quick-share's "These are my own words" box or the inbox toggle). A context-only share:
   - may be retrieved as context once it is embedded;
   - is never quoted verbatim in anything Echo writes;
   - never feeds voice signals as the user's own words;
   - never enters a dataset or derived export.

   Marking one's own words is authorship, not an override. No per-thread override exists.
2. **The brain is a registry, not a convention.** It consists of:
   - every table in `echo_privacy_service.ECHO_TABLES` (each must carry `tenant_id`);
   - every collection in `echo_vectors.echo_collection_names()`;
   - the tenant's directory under `ECHO_SHARES_DIR`.

   An unregistered store is neither exported nor deleted. The research library, notes, the account and BYOK keys are outside the brain.
3. **The whole-brain archive carries everything, context-only content included.** The archive is a zip with a manifest, JSONL per table and the files, and its reader is the exact inverse. It is the user's own copy of what they handed over, which is what Article 20 portability covers. A complete archive is also what lets the user check a delete against what was there. "Never exported" in item 1 applies to dataset and derived exports.
4. **Delete runs in a fixed order, then verifies.** It removes vectors, then files, then rows in one commit, and then re-counts every store. If a store fails, the delete stops before the rows that would let a retry find what is left. If anything remains, the call fails rather than reporting success. Both export and delete are audited with counts only.

**Alternatives considered.**
- *Treat every share as the user's voice.* Rejected. A WhatsApp thread or a quote is someone else's personal data, and attributing it to the user would poison voice capture.
- *A per-thread override now.* Not built; it is the user's open question.
- *Exclude context-only content from the archive.* Rejected for now. The archive would no longer be lossless, and delete could not be verified against it. If the user prefers, a flagged section is the fallback, not omission.
- *Delete rows first.* Rejected. A failure in Chroma or the filesystem would then leave vectors or files with no row pointing at them, so nothing could find them again.
- *Hard-code the table list in the export and delete.* Rejected. A new Echo story would silently escape both; a registry with a `tenant_id` test makes the omission visible.

**Consequences.**
- S-3.7.2 must embed under `share:<id>` with `tenant_id` metadata (T-3.7.2.6) and keep context-only shares out of voice signals (T-3.7.2.7).
- Every later Echo story (signals, events, drafts, connector grants) registers its stores.
- The export is the canonical way to see what Echo holds, so it must stay lossless as tables are added.
- Zero-knowledge mode (S-3.10.3) is untouched.

**Linked initiatives / PRs.** [S-3.7.1](initiatives.md#s-371--shares_inbox-quick-share-and-the-inbox-page), [S-3.10.1](initiatives.md#s-3101--full-export), [S-3.10.2](initiatives.md#s-3102--full-delete) (PR [#286](https://github.com/khoks/VideoResearchPro/pull/286)), S-3.7.2, E-3.3, E-3.2, [D-074](#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19) (the same feeder-not-gate choice for shares).

**Status-changed 2026-10-25:** ratified by [D-110](#d-110--echo-only-sees-what-the-user-hands-it-no-background-capture-and-the-echo-scope-rulings-2026-10-25) — item 3 is confirmed as shipped in #286, and no per-thread override will be built.

## D-090 — Map batches never mix sources: `source` batching at a 30K cap, a truncated map response is a failure, and map calls run concurrently (2026-10-19)

**Status:** accepted, **post hoc** (see Context). Reversible with one setting (`REPORT_MAP_BATCHING=packed`). Run 7 tests it at report level against a pre-registered rule, and a failure there reverts the default.

**Context.** R1 run 6 lost on substance because the annotated report never engaged two of its ten channels. The persisted intermediates (S-1.14.6, D-088) put the loss at the map stage. The map model (gpt-5.6-luna, reasoning off) writes about 100 to 140 items per call whatever a batch holds, so sources late in a 120K-token batch got none: 0.23 items per chunk in a 400-chunk batch against 1.4 to 1.6 in a 27-chunk one. Measuring smaller caps exposed a second defect. The completion budget was 40% of the cap, so small batches were cut off; the truncated JSON came back as `{"raw": ...}`, counted as success, and reached the composer as one half-written unattributed "fact". Run 6's attribution errors traced to the same batching. One was cross-source: a version number shown on screen in Simplilearn's video was credited as "also on screen" to CodeWithMunnaX, who only said it. Packing Hindi and Bengali sources together also produced wrong-script `original`s (16 at a 30K cap). The experiment ([notes/2026-10-19-map-coverage.md](notes/2026-10-19-map-coverage.md)) had a pre-registered rule: largest config with no zero-item source and a per-source density floor of at least 0.4 times the median, in both arms. No config met it. Packed 60K passed once and failed its required repeat. The threshold itself was mis-specified: with no competition at all, long non-English lectures extract at 0.78 items per chunk against 2 to 4 for short English tutorials, a density difference that no batching removes.

**Decision.**
1. `REPORT_MAP_BATCHING=source`: a new source always starts a new map call, and a source larger than `REPORT_MAP_BATCH_TOKENS` (30K) is split into calls of its own.
2. A map response that stops for length, or is not a JSON object, raises `MapOutputError` and goes through the existing bisect-retry. A batch that still fails is dropped and disclosed, never passed on as raw text.
3. The map completion budget equals the batch cap (`_MAP_EXTRACTION_RATIO` 1.0), clamped to the model's output ceiling. Only generated tokens are billed.
4. Map calls run on `REPORT_MAP_CONCURRENCY` (4) threads, with results and counters merged in batch order.
5. *From an adversarial review of this change (8 confirmed findings, 4 distinct defects, all fixed before merge):*
   - each call's `max_tokens` is sized to its own batch (rounded to 4,096), not the cap;
   - a batch is capped at 1.5× the model's output ceiling, and a truncated response keeps halving (up to 2⁴ pieces), so a model with the 4,096-token default ceiling no longer loses every batch;
   - transient errors (429, 5xx, 529) back off and retry before any bisect;
   - `quote_fidelity.VideoText` locks its cached matcher; concurrent batches on one source raised IndexError or anchored on another thread's fragment.

**Alternatives considered.**
- *Keep packed at 120K and add a coverage guarantee (re-map empty sources).* It fixes the zero but leaves late sources at 0.1 to 0.3 items per chunk, and it keeps both cross-source failures.
- *Packed at 60K.* About 2× the items and a worst-source density of about 0.3. It failed its pre-registered repeat and still mixes sources (wrong-script quotes 0 to 1, a cross-source label channel kept open).
- *Packed at 30K.* Good coverage, but 16 wrong-script quotes in the annotated arm: more, smaller mixed batches make cross-source contamination worse.
- *Prompt the model to cover every listed source.* Asks the model to behave rather than removing the competition; D-075 showed prompt rules move errors rather than remove them.

**Consequences.**
- About 13 map calls instead of 2 on an 11-video job (about 150 s at concurrency 4 against 55 to 95 s), roughly one call per source on large corpora, and about 4.5× the map items for compose to absorb. Run 7 measures the effect on the finished report and on compose cost.
- Every source gets its own extraction, so no source can be starved, and no call can attribute one video's speech, script or screen to another.
- Within-source mislabelling persists: about 1% of `shown`/`both` items have no span from their own source within ±60 s, in every config.
- `{"raw": ...}` summaries no longer come from map. Reduce keeps its defensive handling for other shapes, and `MAP_UNPARSED` records no longer occur from this path.

**Linked initiatives / PRs.** S-1.14.19 (E-1.14), E-1.18 (R1 run 6 and run 7), D-075, D-088, #294 (R5 quote verification, which this makes mostly unnecessary for wrong-script quotes but keeps as the check).


---

## D-091 — Channel intelligence: aggregates computed on read and cached per reader behind an input fingerprint; derived links resolved at read time (2026-10-19)

**Status:** accepted.

**Context.** M7 (E-8.7) needed per-channel figures (cadence, durations, topics and concepts, a keyword cloud, stance, the reader's own questions) over the documents of the channel **this reader** can see (D-063), and a way for citation chips to reach the channel page. The plan left open how to keep the figures fresh (open question 2: "invalidate on sync and on new knowledge"), and the obvious link fix, a `channel_id` on every stored reference, sat in `qa_agent._chunk_to_reference`, which E-7.1 was rewriting at the same time.

**Decision.** Compute `GET /channels/{id}/intelligence` in the request and cache the payload per `(channel_id, tenant_id)` in `channel_intelligence_cache`, keyed by a fingerprint of the inputs (the visible document set, knowledge-extraction times, cached transcripts) plus a payload version, with `?refresh=true` to force it. Keywords are TF-IDF over cached transcripts with a project function-word and spoken-filler stop list. Citation chips find their channel at read time through a batched, visibility-scoped `GET /library/video-channels?video_ids=`, never a stored field. "Extract knowledge for N documents" runs from the browser, one document at a time, against the existing endpoint and the reader's quota.

**Alternatives considered.**
- *Materialise nightly on the scheduler.* Stale between runs, and a per-tenant table for every channel whether anyone opens it or not. Measured instead: 1.6 s cold and 13 ms cached at 500 documents, so on-read is affordable.
- *Invalidate from the sync and extraction paths.* Hooks in two hot paths that every future input would also need; the fingerprint notices any input change without them.
- *scikit-learn's built-in English stop list.* Its Glasgow list drops content words such as "interest", which a finance channel needs.
- *Store `channel_id` on references.* Edits a shared hot spot mid-rewrite, and every answer written before the change would stay unlinked; read-time resolution links every existing answer and cannot leak a channel the reader cannot see.
- *A Celery batch-extraction task.* A new task, progress channel and cancel path for something the existing endpoint already does per document.

**Consequences.**
- The first open after any input change pays the computation (about 1.6 s at 500 documents); a channel of several thousand documents would need the scheduler after all.
- Changing the payload shape means bumping `PAYLOAD_VERSION` so older cached rows recompute.
- A chip's channel costs one extra batched request per screen.
- Batch extraction stops when the tab closes; it is resumable because it only offers documents without a report.
- Topic clusters (k-means over chunk embeddings) were not built; they fold into the gated S-8.9.3.

**Linked initiatives / PRs.** E-8.7 (S-8.7.2 #280, S-8.7.3 #285, S-8.7.4 #291), M7 plan, D-063, D-070.

---

## D-092 — Library graph: computed per request, sigma used directly as a lazy chunk, three group colours, the accessibility layer inside the story (2026-10-19)

**Status:** accepted.

**Context.** M9 (E-8.9) needed a library graph that is useful rather than a hairball, tenant-scoped, readable without a mouse, and within the app's bundle budget. The plan left two questions to the user: `sigma` or `react-force-graph-2d`, and whether a whole-library view should ship in v1.

**Decision.**
- `GET /library/graph` builds nodes and edges per request from the reader's visible documents (documents, their channels, topics on at least two documents, the reader's answers that cite them; `co_occurs` edges between topics sharing two or more documents, five per topic). No edge table. Degree, then recency, choose nodes under a cap (default 300, max 2,000), and the response carries a one-paragraph summary.
- The UI is `sigma` 4 with `graphology` used directly (no `@react-sigma/core`), ForceAtlas2 in its web worker frozen after it settles, and seeded Louvain groups, all in a lazy route chunk (125 kB gzipped).
- The whole-library view ships, capped at 300 nodes with single-link nodes hidden; the local view opens from any node, channel or run.
- Only the three largest groups are coloured, in the first three slots of the reference categorical order validated against **all pairs** on both surfaces; the rest are grey, and a glyph marks each node kind.
- The accessibility layer is part of the first UI PR: one tab stop with arrow keys to the nearest node (neighbours first), Enter and Escape for the detail card, buttons for every pan and zoom gesture, a live region, the summary in words, and a table of the same nodes that is the default under 640 px. Reduced motion computes the layout before the first frame.

**Alternatives considered.**
- *A persisted `graph_edges` table.* Premature: the graph builds in about 0.07 s at 2,000 documents and 500 answers.
- *`react-force-graph-2d`.* Smaller (60 kB), but canvas-only with d3-force; sigma's WebGL leaves headroom and its camera and coordinate API is what the keyboard ring needs.
- *`@react-sigma/core`.* One more dependency wrapping calls the canvas makes directly anyway.
- *Local graphs only in v1.* Leaves the reader no overview; the cap and leaf hiding keep the global view legible, and the open question stays open for a real library.
- *A colour per group.* A fourth hue fails the all-pairs separation floors (orange against yellow), and on a node-link map any two groups can touch.
- *Accessibility as a follow-up.* A canvas has no DOM; shipping it without the table and keyboard model fails WCAG 1.1.1, 2.1.1 and 2.5.7 from day one.

**Consequences.**
- Libraries well beyond 5,000 nodes would need the edge table and server-side layout.
- Group colours follow group size, so a filter that changes the groups can recolour them; the legend names each group by its main topics.
- sigma 4's defaults need care: `itemSizesReference: "screen"`, a full `refresh()` after a reducer's inputs change, and mount only once the container has a width.
- Measured: 300 nodes, the page's request, draw in 1.3 s on the dev server; 2,000 nodes in 2.2 s, 3.0 s under reduced motion.
- S-8.9.3 (topic clusters by embedding centroid) stays gated on topic edges proving too sparse on a real library.

**Linked initiatives / PRs.** E-8.9 (S-8.9.1 #297, S-8.9.2 #301), M9 plan, D-063, D-070.

**Status-changed 2026-10-25:** ratified by [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) — sigma and the capped whole-library view stand; S-8.9.3 stays parked.

## D-093 — Book cohesion pass ships opt-in; `none` stays the default after two blind rounds (2026-10-19)

**Status:** accepted.

**Context.** S-6.1.3 adds model-written framing around a book's unchanged chapters. `author_book_outline` (gpt-5.5, medium) proposes order, parts, bridges and briefs; `author_book_prose` (claude-sonnet-5, medium) writes the introduction, bridges, conclusion and glossary. The plan made `full` the default only if it beat the `none` book in a blind judgement. The protocol and decision rule were fixed before generation in [docs/notes/2026-10-19-book-cohesion-judging.md](notes/2026-10-19-book-cohesion-judging.md). The material was three books from four real runs. Three judges took part, from different families. The rule required at least 6 of 9 verdicts for `full`, the non-Anthropic judges agreeing, and at most 3 flagged framing statements in total.

**Decision.** `cohesion` ships with `none` as the default and `light` / `full` as opt-in, priced before generation. Both rounds met the preference rules (18 of 18 verdicts for `full`, cohesion about 8 against 3) and failed the accuracy rule (27 flags per round). A book with framing says so in its front matter and names the models.

**Alternatives considered.**
- *Make `full` the default on the preference result.* The rule was fixed in advance to stop exactly that: framing a reader takes as fact must not invent. The flags include real defects as well as judge errors.
- *A third round with more prompt changes.* The protocol allowed no third round. More tuning against the same three books and judges would fit them, not the problem.
- *Count only flags verified against the chapters.* Judges do flag supported statements (the publication span, wording the chapter uses). But changing the rule after seeing the data would make the judgement meaningless; the notes report what the flags are without changing the outcome.

**Consequences.**
- Every book is still the deterministic manuscript unless the user chooses framing. The create modal shows the estimate, and the outputs list shows the measured cost from `usage_json`.
- Two defects found by the trial are fixed and tested: prose returned as JSON broke on paragraph breaks and quotation marks (now marked plain-text sections), and a reordered book's prose cited the user's chapter numbers (now reading-order numbers and titles).
- Cost per book: $0.09 to $0.17 for two to four chapters, input dominated by the digests (3,000 to 5,000 tokens for the outline, 10,000 to 17,000 for the prose).
- Revisit when a grounding check exists that tests each framing sentence against the chapters (for example an entailment pass) or a judge panel with a verified-flag protocol is fixed in advance.
- `gemini-3.1-pro-preview` hit its daily request quota (250, shared across sessions) and `gemini-3.6-flash` judged instead, as the notes record.

**Linked initiatives / PRs.** E-6.1 / S-6.1.3 (PR [#310](https://github.com/khoks/VideoResearchPro/pull/310)), D-055 (judging method), D-056 (disclose, never drop), D-066, D-067.

## D-094 — Map batching: `packed` restored by run 7's pre-registered rule, starved sources re-mapped alone; the switch to `source` is the user's call (2026-10-19)

**Status:** accepted for the default. Supersedes [D-090](#d-090--map-batches-never-mix-sources-source-batching-at-a-30k-cap-a-truncated-map-response-is-a-failure-and-map-calls-run-concurrently-2026-10-19)'s default choice only; every other part of D-090 stands: truncation is a failure, recursive bisect, backoff on transient errors, per-call budgets, concurrency, the matcher lock. **Open question for the user:** switch the default to `source` on the fabrication evidence below?

**Context.** D-090 made `source` batching the default and pre-registered a report-level test: run 7's plain arm (source-batched) against run 6's plain arm (packed 120K), blind three-family judges. Source had to be **preferred by at least two of three families** and have **no more confirmed fabrications**. Results ([notes/2026-10-19-map-coverage.md](notes/2026-10-19-map-coverage.md)):
- *Substance:* GPT-5.5 preferred source (8 vs 7); Sonnet 5 and Gemini 3.1 Pro tied. That is 1 of 3, so the gate **fails**.
- *Fabrications, after three-lens verification:* source **0** of 5 claims; packed **6** of 12. Five of the six are false exclusivity ("the one explicit API supersession", "no other source mentions distplot", "the only numerically specific conclusions"), which is what a composer asserts when the map stage never showed it two channels.
- *Cost:* the source-batched reports are about twice as long (17.9K against 10.4K words) and compose takes about twice as long.

**Decision.**
1. The default goes back to `packed` at 120K, as the pre-registered rule says. The rule was written before the data, so it stands even though its second criterion favoured `source`.
2. **S-1.14.20:** after a packed map pass, any source with at least 10 chunks and under 0.2 items per chunk is re-mapped on its own (30K calls), and those items **replace** its thin ones. The threshold comes from the data: solo, no source fell below 0.77; starved ones sat at 0.00 to 0.17. Map-only measurement on job 419e691d: zero-item sources go from 1 to 0, the floor ratio from 0.00/0.14 to 0.485/0.718 (the first config to clear the pre-registered 0.4 in both arms), worst-source density from 0.00/0.09 to 0.27/0.57, and items from about 150 to about 370 (source batching: about 600).
3. Whether to switch the default to `source` (0 confirmed fabrications, full coverage, double length) or keep `packed` with the re-map (unmeasured at report level) goes to the user. Overriding a pre-registered rule is a judgment, not a measurement.

**Alternatives considered.**
- *Keep `source` despite the failed gate.* That overrides the pre-registration on evidence the rule did not weigh. It may be right, and it is offered to the user rather than taken.
- *Plain `packed` with no repair.* Restores a measured defect: sources starved to zero in three of four runs, and false exclusivity in the report.
- *Lower the packed cap.* Measured in D-090: 60K failed its repeat, and 30K produced 16 wrong-script quotes.

**Consequences.** Reports keep roughly today's length and gain coverage for starved sources at the cost of a second map phase (about 200 s map-only, against 55 to 95 s). Within-source under-coverage above the 0.2 floor remains. A report-level comparison of packed + re-map against `source` is the natural next measurement if the user wants one.

**Linked initiatives / PRs.** S-1.14.19, S-1.14.20 (E-1.14), D-090, R1 run 7 (E-1.18).

**Status-changed 2026-10-25:** kept by [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) — `packed` plus the re-map stays the default; the report-level comparison against `source` runs later, under a rule pre-registered first.

---

## D-095 — Scoped library questions: one history table with a `scope_json` object, narrowing and provenance keys, unknown keys refused (2026-10-19)

**Status:** accepted.

**Context.** Shelf-scoped Q&A (S-8.1.4) and saved searches (S-8.3.2, lane A) both ask the library agent over something narrower than the whole library, and both want their exchanges in the one history the library Q&A page, the Q&A library index (`qa_library_global`) and the dataset exports already read. The M1 and M3 plans each named a `scope_json` column; they had to agree on one shape before either shipped.

**Decision.** `library_qa_exchanges.scope_json` holds a small JSON object documented in `app/schemas/qa_scope.py`, written and read only through `qa_scope_service` (`dump`, `load`, `resolve_document_ids`).
- `null` is the whole library: every document the reader can see. Every earlier row reads so.
- **Narrowing keys** intersect with the visible set and never widen it: `shelf_id` (the documents of the runs on one of the reader's shelves).
- **Provenance keys** record where an exchange came from and never change retrieval: `saved_search_id` (M3).
- Keys are added, never repurposed. Reading keeps keys this build does not know; resolving **refuses** them (`UnknownScopeKey`), because ignoring an unknown narrowing key would widen the question to the library.
- A scope that resolves to no documents retrieves nothing; a shelf that is not the reader's is `ScopeNotFound`, the same as a missing one.
- The scope is stored as asked, not as the resolved document list, so a shelf question later reads as "asked on Rates", not a frozen list of ids.
- Resolution uses the same query builder as the library listing (`library_query_service.documents_query`, extracted from `query_library_documents`), so a shelf means the same documents in its list and in its answers (D-083). It lives in a service so a Celery task can call it.

**Alternatives considered.**
- *A separate `shelf_qa_exchanges` table.* A second history to merge into the library page, the Q&A library index, the dataset exports and the palette search.
- *Typed columns (`shelf_id`, `saved_search_id`).* One migration per new scope kind, and the two lanes would each add their own column.
- *Storing the resolved document ids.* Large rows, and a shelf's history would stop meaning "this shelf" as runs are added.
- *Ignoring unknown keys when resolving.* The failure mode is silent widening, the exact thing D-063 forbids.

**Consequences.**
- The library Q&A history returns `scope` on every exchange; pages must badge scoped ones or a shelf answer reads as library-wide (M1 plan risk).
- Saved searches store the same object on `saved_searches.scope_json`, resolve it with `resolve_document_ids` before each run and stamp `saved_search_id` on the exchanges they produce.
- A new scope kind (a tag, a channel, a run) is a new key plus one branch in the resolver and its isolation test; no migration.
- Exchanges are not re-checked against their scope later: deleting a shelf leaves its questions in history with a dangling `shelf_id`.
- **Notes follow the scope** (added 2026-10-19 with PR [#319](https://github.com/khoks/VideoResearchPro/pull/319), after notes joined retrieval in S-8.5.2): a narrowing key narrows the asker's notes too. `qa_scope_service.note_target_keys` gives a shelf what job Q&A would draw for each run on it, plus notes on the shelf's earlier answers. It returns `[]` (no notes) for an empty shelf and `None` (every note) only for the whole library, and `run_library_qa_agent` takes them as `note_target_keys`. The scoped citation check covers note citations as well. The alternative, every note in every scope, would let a shelf answer cite a note about a source outside the shelf.
- Citations are polymorphic, so `LibraryReference.video_id` is optional (a note has none) and history parses citations one at a time; before this, a library answer citing a note failed while building its response.

**Linked initiatives / PRs.** S-8.1.4 (E-8.1), S-8.3.2 / S-8.3.3 (E-8.3), S-8.5.2 (E-8.5), M1 and M3 plans, PRs [#313](https://github.com/khoks/VideoResearchPro/pull/313), [#319](https://github.com/khoks/VideoResearchPro/pull/319). Follows D-063, D-070, D-083.

## D-096 — R1 frames reach the user: opt-in per run, lazy stills, and a `visual_extractions` quota (2026-10-19)

**Status:** accepted. The tier numbers are defaults flagged for the user's pricing call.

**Context.** S-1.18.2 surfaces R1's frames: a per-run toggle, stills on citation cards, and on-demand capture for a document already in the library. R1 run 8 passed quote fidelity, attribution and fabrication; its substance vote waits on Gemini Pro. The pre-registration says both remaining outcomes build the UI, opt-in, so the build did not wait.

**Decision.**
1. Visual analysis stays **opt-in per run** and per document. The copy makes no quality claim until run 8's vote is in; it states the cost (about $0.20 per video at D-081) and that frames are reused.
2. Report stills load **lazily**, when a citation card first asks for one. Eager prefetch was built first and measured in the browser at about 110 image requests per report. It spent the per-user rate limit (60 per minute on free) and starved the page's other calls.
3. On-demand capture is a **worker task** with a per-document Redis marker. Capture downloads video for up to `VISUAL_CAPTURE_TIMEOUT_SEC` (15 minutes), so it cannot run inline the way knowledge extraction does.
4. A new monthly quota `visual_extractions`: **free 2, Pro 30, Studio 300**. It is charged only when frames were actually captured, the same rule the job budget follows. At about $0.20 per capture that is $0.40, $6 and $60 of vision spend per month at the cap.

**Alternatives considered.**
- *Charge captures to `knowledge_extractions`.* Mixes a $0.20 multimodal pass with a text pass that costs cents, and hides which one ran out.
- *No quota.* The capture is the app's most expensive single action per document.
- *Tag stills into the report HTML server-side.* Reports are sanitised and parsed in the browser (D-085), and the citation card already had the slot.

**Consequences.** The tier numbers should be revisited with pricing. Stills beside Q&A references (T-1.18.2.5) reuse the same matcher. Annotations still do not reach Chroma or knowledge extraction for documents embedded before their frames existed (T-1.18.1.10/11). That only matters once Q&A shows stills.

**Linked initiatives / PRs.** S-1.18.2 (E-1.18), D-067, D-081, D-085, D-079; R1 runs 1-8.

*Addendum, 2026-10-19 (run 8 final).* Gemini 3.1 Pro's late vote passed rule 3, but its attribution claim was confirmed 3 of 3, so **rule 2 failed**. The UI had shipped on the premise that rules 2 and 4 passed. It stays opt-in with no quality claim, and its copy now discloses the measured risk. Keeping, hiding or flagging R1 is the user's decision, as the pre-registration requires (protocol note, "Eight runs, summarised").

**Status-changed 2026-10-25:** kept by [D-109](#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25) — the capture caps stay defaults, decided when R1 returns or Stripe pricing starts ([D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)).

## D-097 — Newsletter: featured section ships opt-in; the rest of an issue is listed from the database (2026-10-19)

**Status:** accepted.

**Context.** S-6.4.1 builds the newsletter: one issue per window, listing what is new to the reader and adding a model-written featured deep-dive about one source from their own library. The plan made the featured section the only model-written part. Its quality bar was fixed before any section was generated, in [docs/notes/2026-10-19-newsletter-featured-judging.md](notes/2026-10-19-newsletter-featured-judging.md). The material was four real reports, judged blind against the report's own summary paragraph by three judges from different families, with Gemini 3.6 Flash named in advance as the Google judge. The rule required at least 8 of 12 verdicts for the model, the non-Anthropic judges agreeing, and at most 4 unsupported claims in total.

**Decision.**
- The featured section ships **off by default and opt-in**. The trial met both preference rules: 12 of 12 verdicts, and usefulness about 9.4 against 2.1. It failed the accuracy rule with 16 flags.
- **Everything else in an issue is listed from the database**, with no model: documents new to this reader (visibility grants), knowledge reports, their questions, saved searches with new answers, and what they made.
- **An issue with nothing new is skipped**: a new `skipped` output status, with the reason as the row's message.
- The email is HTML with inline styles and no external CSS, images or scripts; its plain-text part is the issue's Markdown.

**Alternatives considered.**
- *Ship the featured section on by default on the preference result.* Every round so far has drawn real accuracy flags. The most common was a marker attached to the neighbouring moment, which a reader following the link would find does not say what the sentence claims.
- *Drop the featured section.* The judges found it far more useful than the summary, so readers who accept the risk can turn it on; the section names the model that wrote it.
- *premailer for the email styles (the plan's choice).* Our HTML comes from one renderer with a small, known set of tags, so a 15-line tag-to-style map does the same without a dependency.

**Consequences.**
- Three generation defects were fixed before judging: excerpts without markers, invented markers that resolved, and doubled timestamps. The notes describe them.
- Revisit the default together with D-093 when a sentence-level check exists that tests each cited sentence against the point its marker names (S-6.1.6 covers books).
- Cost of the featured call: $0.015 to $0.017 per issue on claude-sonnet-5 at reasoning low.

**Linked initiatives / PRs.** E-6.4 / S-6.4.1 (PR [#334](https://github.com/khoks/VideoResearchPro/pull/334)), D-093, D-056, D-063.

---

## D-098 — Echo connectors: events unique per reader, tokens in a secret store that is erased with the brain but never exported (2026-10-19)

**Status:** accepted.

**Context.** The connector runtime (S-3.2.1) is Echo's first store of third-party credentials and its first stream of events synced repeatedly from a provider. D-089 made the brain a registry whose archive is "every column of every row". Read literally, that would put OAuth tokens, encrypted or not, and the PKCE verifiers of connects in flight into a zip the user downloads and may share. The board also keyed event idempotency on `(connector, external_id)`, which is global across readers.

**Decision.**
- **Two registries in `echo_privacy_service`.** `ECHO_TABLES` is what the archive carries: `personal_context`, `shares_inbox`, now also `activity_events` and `echo_connector_grants` (that a connector was granted, when, under which consent version, as which account, and how syncing went). `ECHO_SECRET_TABLES` holds `echo_connector_credentials` (tokens, Fernet-encrypted with the install key, D-043) and `echo_connector_oauth_states` (CSRF state and PKCE verifier, single use, minutes long). Both registries are counted in the footprint and erased by the full delete. Only `ECHO_TABLES` is exported; the manifest's `withheld` block counts the secret rows and says why.
- **Events are unique on `(tenant_id, connector, external_id)`.** Re-syncs, retries and overlapping backfills update in place. Two readers may connect the same third-party account without colliding.
- **The contract lives in `app/connectors/`** (`ActivityConnector`, `ArchiveImporter`, two registries). The runtime around it (state, PKCE, tokens, storage, schedule, revoke) is not a connector's job. `echo_service`'s old names re-export it.
- **A processed share is one `internal` / `shared_to_pratidhvani` event**: metadata only, because the words stay in the inbox under D-089's context-only rule. Deleting the share deletes the event.

**Alternatives considered.**
- *Export the tokens encrypted.* The key is the install's, so the ciphertext is useless to the user and dangerous if the server key ever leaks with the zip; reconnecting is one click.
- *Drop the token columns from the grants table at export time.* It hides a secret store inside a brain table, and every future table would need its own exclusion list.
- *Unique on `(connector, external_id)`.* Blocks the second reader of a shared account, and makes one reader's revoke able to take rows another reader needs.

**Consequences.**
- A new secret store registers in `ECHO_SECRET_TABLES`, never `ECHO_TABLES`, and the privacy tests list both registries exactly.
- Importing an archive back can never restore a connection; the user reconnects.
- A revoke deletes the grant, the credentials, any pending state and every event that connector wrote, in one request (S-3.2.1's runtime PR).

**Linked initiatives / PRs.** S-3.2.1 (E-3.2), S-3.10.1 / S-3.10.2 (E-3.10), PR [#332](https://github.com/khoks/VideoResearchPro/pull/332). Extends D-089 item 2; follows D-043.

## D-099 — Signal extraction: verbatim-checked examples, language-free beliefs, stylometry without a model (2026-10-19)

**Status:** accepted.

**Context.** S-3.3.2 learns voice and personality signals from the user's own words. The plan specifies three layers: model-free stylometry, an open author embedding, and a batched economy-tier LLM pass. It requires that only the user's own text feeds a signal ([D-089](#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19)), and that a withdrawn note stops counting ([D-074](#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19)). Building it and measuring it on three synthetic writers ([cost note](notes/2026-10-19-signal-extraction-cost.md)) forced five choices.

**Decision.**
1. **Code, not the model, ties a signal to the user's words.** The model cites a passage id and quotes it. An example is kept only when its quote is found in that passage, ignoring case, spacing and curly quotes; the stored text is the passage's own span. A signal with no surviving example is dropped.
2. **A personality signal has no language; a style signal takes its language from its examples' passages**, as `language_of` reads them (script plus the word-level Hindi share), never from the model's label. The model labelled the same Hinglish `mixed` on one run and `hi-Latn` on the next, which split one belief into two rows.
3. **Stylometry is heuristic and model-free.** Sentence length, punctuation habits, function words from `code_mixing_service`'s closed classes (Roman and Devanagari), and character trigrams, with coarse floors, about three times the ordinary-prose rate. Similarity for S-3.3.4 is a cosine over function-word and trigram rates. Burrows' Delta needs a reference corpus for its z-scores, and a single user does not have one. **The open author embedding is not built:** both candidates are English-trained, and LUAR-MUD loads remote code. It is filed as T-3.3.2.7. Cadence reads prose only (notes and shares), because Q&A questions are always questions.
4. **Strict own-words inputs.** Live notes; the questions on the three Q&A surfaces (never the answers, and never a saved search's scheduled re-asks); and shares marked `author_is_tenant`. A context-only share's annotation is excluded too: D-089 says context-only shares never feed signals, and an annotation is part of the share.
5. **A ledger, `voice_signal_inputs`, records what was read.** It holds each input's content hash, its language, and a stylometric profile. An edit is read again, with its old evidence withdrawn first. A deletion is withdrawn at once (note delete, share delete), and the next run reconciles anything else. A failed call leaves its inputs pending and stylometry still runs. The ledger is in D-089's registry.

**Alternatives considered.**
- *Trust the model's quotes.* Measured drop rate was low (about 1 in 200), but one invented quote shown as "you wrote this" would break the panel's promise.
- *Per-language personality signals.* The bilingual-voice evidence the plan cites is about how opinions are expressed, which style signals capture. A belief split by language only fragments its weight.
- *Add `faststylometry` for Burrows' Delta.* It is a dependency for a statistic that needs a reference corpus Echo does not have per user.
- *Queue extraction on a beat schedule.* The scheduler has one beat entry by design (S-8.3.1). Hooks where the user writes (note create and edit, the three Q&A routes, own-words share processing) call `maybe_queue`. It runs once `ECHO_SIGNALS_MIN_NEW_INPUTS` (10) texts are waiting, or on "Learn now".

**Consequences.**
- Cost on the economy tier: about $0.005 per 100 inputs for a backlog and $0.02 per 100 for incremental runs.
- Signal quality is ungraded until S-3.3.4.
- `echo_extract_signals` is the 33rd registry entry, with guidance `unmeasured`.
- Connector text written by the user (lane B's runtime) joins the inputs when it exists, as T-3.3.2.8.

**Linked initiatives / PRs.** E-3.3 / S-3.3.2 (PR [#335](https://github.com/khoks/VideoResearchPro/pull/335)), D-089, D-074, D-057, D-080.

## D-100 — Voice-match gate: Mode A passes on synthetic writers; speak as me may be built, and is enabled per user only after the user-as-judge test (2026-10-19)

**Status:** accepted.

**Context.** S-3.3.4 is the gate for E-3.4. Its material, conditions, judges and pass rule were pre-registered in [docs/notes/2026-10-19-voice-match-preregistration.md](notes/2026-10-19-voice-match-preregistration.md) (#338) before any draft existed. The install holds none of the user's own writing (no notes on 2026-10-19), so the run used three synthetic writers with sharply different styles.

**Decision.**
- **The pre-registered gate is met.** E-3.4 may be built on Mode A: retrieval of the user's signals from `personal_context_global`, plus five style-diverse exemplars, with no fine-tuning.
- **Voice.** The voice draft was preferred in 36 of 36 verdicts. Both judges (claude-sonnet-5, and gemini-3.6-flash declared as the substitute for Gemini 3.1 Pro) preferred it for all three writers, with no abstentions.
- **Quality.** The guard passed: V was preferred or tied in 47% of quality verdicts, with 17 for V, 17 for N and 2 unparsed counted against V.
- **Automatic score.** Tier (i) passed with 15 of 18.
- **Not enabled for anyone yet.** "Speak as me" is switched on per user only after tier (iii), the user picking their own text in at most 80% of at least 20 blinded pairs, passes for that user. Tier (iii) needs at least 40 of their notes.

**Alternatives considered.**
- *Treat the synthetic pass as the product gate.* The writers were built to differ, and the neutral drafts are generic, so 100% is a ceiling. It shows the pipeline carries style through; it does not show the user would mistake a draft for their own writing.
- *Wait for the user's notes before building E-3.4.* The pre-registered rule says a pass on this run unblocks building. Holding the agent back would leave nothing to test tier (iii) with.

**Consequences.**
- S-3.4.1 is unblocked to build on this design.
- Tier (iii) is the per-user switch: `scripts/voice_match_harness.py user-pairs` and `user-score` are ready.
- Things to watch in S-3.4: phrase lifting from exemplars (none found here: no voice draft shared a run of four words with the writer's notes), and the 2 of 36 quality verdicts that named neither draft.
- Running the gate cost $0.31.
- The first launch stopped at its first judge call: `claude-sonnet-5` refuses an explicit temperature of 0. The app's Anthropic builder sends 0 whenever reasoning is off, so any use case set to `claude-sonnet-5` with reasoning off would fail the same way. Filed as a follow-up.

**Linked initiatives / PRs.** E-3.3 / S-3.3.4 (PR [#346](https://github.com/khoks/VideoResearchPro/pull/346)), #338 (pre-registration), D-055, D-097, [D-099](#d-099--signal-extraction-verbatim-checked-examples-language-free-beliefs-stylometry-without-a-model-2026-10-19).

## D-101 — Echo readiness v2: five domains measured from their stores, blocked reads as not connected, the voice test reported not gated (2026-10-20)

**Status:** accepted. Supersedes [D-049](#d-049--echo-cold-start-readiness-threshold-shipped-triple-is-v1-personal-brainmd-sub-table-is-forward-looking-spec-resolves-oq-6-2026-05-06).

**Context.** D-049 kept the shipped triple (100 personal-context rows, 3 distinct sources, one personality trait) as v1 until shares, activity and signals existed. They exist now: shares and importers (E-3.7), the connector runtime and GitHub (E-3.2), voice signals and the voice-match gate (E-3.3, [D-100](#d-100--voice-match-gate-mode-a-passes-on-synthetic-writers-speak-as-me-may-be-built-and-is-enabled-per-user-only-after-the-user-as-judge-test-2026-10-19)). The triple had also stopped measuring the right thing. A connector's derived facts and an import's facts counted as though the user had written them, and the sources gate could not be met by writing at all.

**Decision.** `ready` is the AND of five domains. Each is measured from its store on every call (`echo_readiness_service.evaluate`), with its thresholds in settings:

1. **Facts.** Live personal-context rows the user wrote (`source = 'manual'`): at least 30, across at least 3 kinds. Inferred facts are reported beside the count, not in it.
2. **Activity.** `activity_events` from every connector and import except `internal`: at least 200 events spanning at least 90 days. The internal share event mirrors a share, which domain 5 already counts.
3. **Signals.** Live voice signals (`suppressed_at` null): at least 50, across at least 4 types.
4. **Voice.** The user's own writing (live notes, plus shares marked `author_is_tenant` that carry text), grouped by script. The floor is met when one script holds at least 30 pieces or at least 2,000 words. Once the floor is met, the note vectors already in `notes_global` must be stable: the mean cosine distance of 50 bootstrap centroids from the full centroid is at most 0.05, over at least 10 vectors. With the notes index off, stability is reported as not measurable and does not block.
5. **Shares.** `shares_inbox`: at least 100, across at least 4 content types.

Each domain returns:

- its criteria;
- a progress fraction, the mean of its criteria with each capped at 1;
- what is missing, in words.

The page shows each domain. Its percentage is the mean of the five, capped at 99 until `ready` ([D-069](#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19)'s rule, applied to domains).

Some connectors cannot be offered on an install: there is no OAuth client for them, or they are not built yet. YouTube likes and Calendar wait on the user's Google setup (S-3.2.2, S-3.2.5). Such a connector reads `not_connected` with its reason. An activity domain with no events and nothing connected also reads `not_connected`, never as a failure.

A threshold of 0 switches that check off.

The D-100 user-as-judge test is **not** part of `ready`. Readiness reports whether the user can take the test (at least 40 live notes, `ECHO_VOICE_TEST_NOTES_MIN`). The test's result switches "speak as me" on per user, and storing it belongs to E-3.4.

**Alternatives considered.**
- *Keep the triple and add the domains beside it.* That gives two gates that can disagree, and inferred facts would still count as self-authored.
- *Count connector-derived and imported facts in domain 1.* `personal-brain.md`'s minimum is self-authored facts. A nightly GitHub sync could otherwise fill domain 1 without a word from the user.
- *One voice floor across languages.* A voice is learnt per language, and 1,000 English words plus 1,000 Hindi words is not 2,000 words of either. The split is by script, so romanised Hindi counts as Latin: `language_service`'s known gap. D-080 tags code-mixing per word, but no per-document language is stored to split on.
- *Measure stability by embedding the writing on the status call.* That loads the embedding model on a status request. The vectors are already in `notes_global`.
- *Put the user-as-judge test in the gate.* Deferred, because its result is not stored yet. Readiness can say when the user can take it.
- *A stored readiness flag, updated on writes.* Every store has its own delete paths (disconnect, undo an import, forget, suppress a signal), and a stored flag would drift from them. The counts are tenant-filtered queries.

**Consequences.**
- `GET /echo/status` gains `progress` and `domains`. The v1 fields stay, reported only.
- `ready` is stricter: an account that met the triple is not ready until all five domains are met.
- On master only the Echo page read `ready`. The bubble (E-3.8) and "speak as me" (E-3.4) should read `ready` and each domain's `missing` text rather than recompute them.
- The thresholds are untuned: `personal-brain.md`'s recommended minima plus the plan's voice floor. The 0.05 spread is a starting point, not a measurement, and needs a real user's notes; the install held none on 2026-10-20.
- Once the voice floor is met, a status call reads the tenant's note vectors: one Chroma `get` filtered by tenant, bounded by their note count.
- Open: should the user-as-judge result join the gate once E-3.4 stores it?

**Linked initiatives / PRs.** E-3.5 / S-3.5.1 (PR [#354](https://github.com/khoks/VideoResearchPro/pull/354)), [D-049](#d-049--echo-cold-start-readiness-threshold-shipped-triple-is-v1-personal-brainmd-sub-table-is-forward-looking-spec-resolves-oq-6-2026-05-06) (superseded), [D-069](#d-069--shipped-backend-surfaces-ingest-as-a-library-tab-author-studio-as-one-page-readiness-as-a-gate-mean-2026-10-19), [D-074](#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19) item 4, [D-100](#d-100--voice-match-gate-mode-a-passes-on-synthetic-writers-speak-as-me-may-be-built-and-is-enabled-per-user-only-after-the-user-as-judge-test-2026-10-19).

## D-102 — Speak as me: two switches, guards in code, the reply in the user's language (2026-10-20)

**Status:** accepted.

**Context.** [D-100](#d-100--voice-match-gate-mode-a-passes-on-synthetic-writers-speak-as-me-may-be-built-and-is-enabled-per-user-only-after-the-user-as-judge-test-2026-10-19) let E-3.4 be built on Mode A but switched on per user only after their user-as-judge test. [D-089](#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19) says a context-only share never becomes the user's voice and is never quoted. S-3.4.1 had to make both hold in a feature that writes in the user's name. The Echo bubble (S-3.8.1, lane D) hosts the same endpoint.

**Decision.**
- **Two switches.** `ECHO_SPEAK_AS_ME_ENABLED` turns the feature on for the install and is off by default. Each user also needs a passed voice test, stored in `echo_voice_gates`. The pass rule is D-100's: at least 20 pairs, own text picked in at most 80%. The tier and readiness ([D-101](#d-101--echo-readiness-v2-five-domains-measured-from-their-stores-blocked-reads-as-not-connected-the-voice-test-reported-not-gated-2026-10-20)) gate it too, and so does the daily cap. `GET /echo/draft/status` names every closed gate in words, in a fixed order. The page and the bubble show the gate rather than hiding the feature.
- **The voice test result is recorded by the harness for now.** `scripts/voice_match_harness.py user-score --record <db> --tenant <id>` writes it. There is no in-app test yet.
- **The user-as-judge result stays its own gate, beside readiness.** It does not join `ready`, which answers D-101's open question. Readiness says whether Echo knows enough. The test says whether the drafts pass for the user's writing. Each blocker's text says what to do next.
- **Guards are code, not prompt.**
  - Any run of 8 words shared with a third-party item (a library source, a context-only share, a past answer) is paraphrased once. If it survives, its sentence is dropped and the draft is flagged `verbatim_removed`.
  - The exemplars and the trait card come only from the user's own notes and own-words shares.
  - A message naming a person the classifier calls private stops with `names_need_confirmation` until the caller acknowledges the names. A relationship ("my uncle") is not a name.
  - Citations are the markers the draft actually used, mapped back to the items it was given. Markers that match nothing are dropped, and the delivered text carries none.
  - A question, opinion or recommendation that cites nothing is flagged `ungrounded`.
- **The reply is in the user's language.** That means the message's language, or the one the caller picks: `en`, `hi-Deva`, `hi-Latn` or `mixed`. This is not D-066's English. D-066 governs reports and answers about sources; a draft is the user speaking.
- **The critic is advisory.** Up to `ECHO_DRAFT_CRITIQUE_ROUNDS` (2) rounds score tone, vocabulary, structure and topicality from 1 to 5, and the best draft is kept. `voice_match_score` is their mean as a percentage. `confidence` is the share of up to 5 cited items. Neither blocks a draft.
- **Drafts are capped, metered and audited.** The cap is a daily quota resource, `echo_drafts`: Studio 20 a day, 0 on lower tiers. A stopped draft (a gate, names to confirm) is not counted. Each draft is audited as `echo_drafted` with counts only. A draft is never sent.
- **The bubble's shape.** The status carries the bubble's summary fields (`state`, `reasons`, the voice test's counts) beside the blocker list, so one endpoint serves both surfaces.

**Alternatives considered.**
- *Gate on readiness alone.* D-100 says the synthetic pass is a ceiling. Only the user's own test shows that a draft passes for their writing.
- *Put the voice test in `ready`.* Readiness would then fall whenever a test failed, and its five domains would stop saying what to collect.
- *Tell the model not to quote.* That cannot be tested. A prompt-only rule fails silently, and D-089 is a promise.
- *Draft in English (D-066).* A reply to a Hindi message in English is not the user's voice.
- *A separate endpoint for the bubble.* Two contracts for one feature would drift. The bubble's fields cost five keys.

**Consequences.**
- Nobody can draft until an operator turns the install switch on and the user's test is recorded. On 2026-10-20 the install held no notes, so no user could take the test yet.
- Each draft costs about $0.02 to $0.05 on the defaults (live smoke on a synthetic persona).
- Follow-ups:
  - an in-app voice test, so the user does not need the harness;
  - S-3.4.2, which turns the user's edit into a signal and makes the disclosure removable;
  - a calibration of the critic's score against the user's own judgements.
- New stores: `echo_drafts` and `echo_voice_gates`, registered in `ECHO_TABLES`, so they are exported and erased with the brain.

**Linked initiatives / PRs.** E-3.4 / S-3.4.1 (PR [#357](https://github.com/khoks/VideoResearchPro/pull/357)), E-3.8 / S-3.8.1 (PR [#355](https://github.com/khoks/VideoResearchPro/pull/355)), [D-100](#d-100--voice-match-gate-mode-a-passes-on-synthetic-writers-speak-as-me-may-be-built-and-is-enabled-per-user-only-after-the-user-as-judge-test-2026-10-19), [D-101](#d-101--echo-readiness-v2-five-domains-measured-from-their-stores-blocked-reads-as-not-connected-the-voice-test-reported-not-gated-2026-10-20), [D-089](#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19) item 1, D-066.

## D-103 — Anticipation cards: only in the opened panel, three a view, three days a key, three dismissals turn a kind off (2026-10-20)

**Status:** accepted. Pre-registered in [the note](notes/2026-10-20-anticipation-cards-preregistration.md) before any card was built.

**Context.** S-3.8.2 adds one-line next steps ("anticipation cards") to the Echo panel (S-3.8.1). There are three kinds: a saved search whose answer changed, shares read since the user last opened the inbox, and questions for the page in view. A surface that offers things unasked can become a nag, so the frequency cap and the dismissal rule were fixed before anything was shown.

**Decision.**
- **Where.** Cards appear only inside the Echo panel, after the user opened it, and only while that panel's conversation is empty. Never a popup, toast, sound, push, email, or badge or dot on the bubble.
- **Cap.** At most three cards a view, one per kind, in a fixed order. A card's key is shown on at most three distinct UTC days, and repeat views on one day count once. A card counts as shown only if it rendered: a questions card counts when a question is on screen.
- **Dismissal.** × retires a key for good. Acting on a card retires it without counting as a dismissal. Three dismissals of one kind within 30 days turn that kind off; the panel says so once and offers to turn it back on. The user can switch any kind off or on, and turning one back on restarts its count.
- **State.** One Echo table, `echo_card_state`, per tenant and key. It is exported and erased with the brain (D-089).
- **Reading after 30 days.** A kind with a dismiss rate above 50%, or an act rate below 10%, over at least 20 shown keys, is switched off by default. Nothing adjusts itself.

**Alternatives considered.**
- *A dot on the bubble when a card is waiting.* This is how a quiet surface becomes a nag. The value of a card is not worth an interruption, and the bell already carries the saved-search notice.
- *Server-side impression counting for every kind.* The questions card's content arrives separately and is often empty in a new library, so counting it on read would understate its act rate. The panel reports it shown instead.
- *Per-device state in browser storage.* The cap would reset on each device, and the reading needs the counts on the server.

**Consequences.**
- Routes `GET /echo/cards`, plus `POST /echo/cards/dismiss`, `/act`, `/shown` and `/seen/shares`, and `GET` and `PUT /echo/cards/settings`, in their own router (`routers/echo_cards.py`).
- The shares inbox reports when it opens, which resets the shares card.
- Any change to these numbers needs a new note and a new decision entry.

**Linked initiatives / PRs.** E-3.8 / S-3.8.2 (PR [#358](https://github.com/khoks/VideoResearchPro/pull/358)), D-089, S-8.3.3, S-8.4.1.

## D-104 — A draft edit teaches only the words the user typed (2026-10-20)

**Status:** accepted.

**Context.** S-3.4.2 closes the "speak as me" loop: when the user edits a draft into what they actually send, the edit should teach Echo their voice. The plan said to store "the diff as a voice-signals candidate". The provenance guard ([D-102](#d-102--speak-as-me-two-switches-guards-in-code-the-reply-in-the-users-language-2026-10-20)) says only the user's own words may set the voice. A draft is the model's text, and so are the words of it the user left alone.

**Decision.**
- **Only the typed words count.** `echo_draft_edits.edit_diff` compares the draft and the user's version word by word. A word counts as typed only if the user inserted it or wrote it in place of draft words. Case and surrounding punctuation are ignored, so "pays." becoming "pays!" is not something the user wrote. Each typed run is cut from the user's text exactly as they typed it.
- **The typed runs become one extraction input, `draft_edit:<id>`.** The runs are kept one per line and pass through the existing verbatim-checked extraction ([D-099](#d-099--signal-extraction-verbatim-checked-examples-language-free-beliefs-stylometry-without-a-model-2026-10-19)). Every example a signal keeps is therefore the user's own typed words, and the signal's provenance cites the draft. An edit below `ECHO_SIGNALS_MIN_PASSAGE_WORDS` (4 typed words) is not an input at all.
- **What the user repeats from the incoming message is the sender's, not theirs.** A reply often echoes the message it answers. S-3.4.1's verbatim guard therefore applies to the edit as well. Any stretch of 8 words (`echo_agent.VERBATIM_WORDS`) that the user's version shares with the incoming message is set aside as `quoted`, even if the user typed it. The stretch is found over the whole version, so a quote that runs across draft words the user kept is caught too. Shorter echoes count as the user's words, the same threshold S-3.4.1 uses for a quote.
- **What the user cut is shown, never learned.** The removed runs are evidence of what the user would not say, but they are the model's words. They appear in the response's `edit` only.
- **One view on both surfaces.** The Echo page card and the Echo bubble share one `DraftEditor` with the same edit, disclosure, Copy and Save, so the bubble's draft teaches Echo in the same way.
- **The disclosure is Echo's, never the user's.** A trailing disclosure line in the submitted text is stripped before the diff. Whether the user kept it is recorded as `disclosure_kept`.
- **Edits are not prose for stylometry.** Typed runs joined together are fragments, and counting them would bend the user's sentence-length figures, so they do not feed cadence. Questions are left out of cadence for the same reason.
- **Deleting the draft withdraws the edit at once,** as a deleted note does ([D-074](#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19)).
- **Feedback is not a draft.** It does not count against the daily cap and may be sent again (the newest wins). It is audited as `echo_draft_feedback` with counts only.
- **The cheap counter reads a stored count.** Feedback stores `written_words`. The cheap new-input counter reads it, so an edit too small to learn from never queues a run.

**Alternatives considered.**
- *Learn from the whole final text.* The unedited part is the model's writing. Echo would learn from itself and drift toward its own style, which is the feedback loop the provenance guard exists to prevent.
- *Store the diff as a ready-made signal* (for example "prefers X over Y") without extraction. Extraction already checks every example verbatim, merges by value and respects tombstones. A parallel path would need all of that again.
- *Treat every typed word as the user's.* A reply that repeats the sender's sentence would then put the sender's phrasing in the user's voice: the impersonation the provenance guard rules out.
- *Learn from what the user removed.* That is the model's words. "Avoids X" could be inferred from it, but an example quoting X would put the model's text in the user's profile.
- *Count edits in the cheap counter from the text.* That means reading every draft on every note and question hook, so a stored word count was chosen instead.

**Consequences.**
- The loop is closed and each signal it produces is inspectable: its example is a clause the user typed.
- A lightly edited draft teaches little, by design.
- The cut words are recorded, but nothing learns from them. "Avoids this phrasing" signals would need their own design.
- One additive column, `echo_drafts.written_words`.

**Linked initiatives / PRs.** E-3.4 / S-3.4.2 (PR [#359](https://github.com/khoks/VideoResearchPro/pull/359)), [D-102](#d-102--speak-as-me-two-switches-guards-in-code-the-reply-in-the-users-language-2026-10-20), [D-099](#d-099--signal-extraction-verbatim-checked-examples-language-free-beliefs-stylometry-without-a-model-2026-10-19), [D-074](#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19).

## D-105 — Visual analysis hidden in the UI until a deterministic attribution guard removes the residual error (2026-10-20)

**Status:** accepted (the user's decision, 2026-10-20). Answers the question D-096's run-8 addendum left open.

**Context.** Eight blind-judged R1 runs ([notes/2026-10-18-r1-visual-measurement.md](notes/2026-10-18-r1-visual-measurement.md), "Eight runs, summarised"):
- Annotations never made fabrication worse (0 vs 2 to 5 where the arms differed), and judges scored visual use higher.
- About one report sentence per run credits the speaker with something only shown on screen. Prompt rules (S-1.18.6) and said/shown labels (S-1.18.8) cut it from two to about one; they did not remove it.
- Run 8 failed its pre-registered attribution rule on exactly that shape. The pre-registration sent the UI decision to the user.

**Decision.** Hide everything in the UI that STARTS visual analysis (the per-run opt-in and on-demand frame capture) behind `frontend/src/config/features.ts` `featureFlags.visualAnalysis = false`, until a **deterministic** attribution guard (S-1.18.9) removes the residual error. The backend stays as built: the API still accepts `visual_analysis`, the frame routes and the worker task stay. Stills of frames that already exist still show on citation cards and in the video drawer, because a real frame cannot misattribute anything.

**Consequences.**
- A run duplicated from, or a template saved with, visual analysis on runs without it while the switch is hidden, and the form says so ("paused in this version"). Templates keep their stored setting, so it returns intact.
- The template list labels such a template "visual analysis (paused)".
- Unhiding is one line, plus whatever S-1.18.9's own acceptance requires.
- R1 follow-ups that only make sense while R1 is surfaced wait: S-1.18.4 (beyond YouTube), the R1 UI follow-ups (T-1.18.2.5) and the remaining S-1.18.5 tasks.

**Alternatives considered.** *Keep it opt-in with a caveat* (the state from #340 to this change): rejected by the user. A known, measured attribution slip in roughly every report is not acceptable even with disclosure. *Remove the backend*: rejected; the measurement corpus, frames and pipeline are what the guard will be built and tested on.

**Linked initiatives / PRs.** E-1.18, S-1.18.2, S-1.18.9; D-067, D-071, D-075, D-096.

**Status-changed 2026-10-25:** kept by [D-109](#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25) — visual analysis stays hidden and R1 measurement stops, so no run is pending that could unhide it.

## D-106 — The deterministic attribution guard ships in the report pipeline; R1 stays hidden after run 9 (2026-10-24)

**Status:** accepted (2026-10-24, S-1.18.9). D-105 stands: its condition is not met.

**Context.** D-105 hid R1's UI until a deterministic guard removes the residual attribution error: about one report sentence per run that credits a speaker with something only shown on screen. S-1.18.9 built the guard and measured it under a rule fixed before any run ([protocol note](notes/2026-10-18-r1-visual-measurement.md), "Runs 9 and 10").

**Decision.**
1. The guard (`backend/app/services/attribution_guard.py`) runs in every report, on by default (`REPORT_ATTRIBUTION_GUARD_ENABLED`). It is pure code and a no-op when no source has a visual span, which is every report started from the UI while R1 is hidden.
2. How it works:
   - It acts only on a specific detail (a number, an identifier, a quoted string, a visual descriptor pair, or three or more listed names) that it finds in a span. So every mark it writes is true by construction.
   - It marks the detail in place, "(on screen at mm:ss)", with the span's own timestamp. It never deletes a detail.
   - Screen-only is decided against the speech around the cited moment, not the whole video.
   - "Not spoken" is added only for figures and multi-word quotes absent from the whole of a Latin-script speech.
   - Map items are relabelled, split or listed before compose sees them.
   - Speech presented as screen is corrected, and an unsupported "also visible on screen" is removed.
   - Sections are guarded before the executive summary reads them, and the summary is guarded after.
   - It is fail-soft and disclosed in the report's processing note.
3. Visual analysis stays hidden. Run 9 failed rule 2 and rule 3, so run 10 was not run (as pre-registered):
   - Rule 2: one confirmed attribution error, a lone two-digit figure from the screen inside a speaker's examples in a Hindi video, below the guard's action threshold.
   - Rule 3: a substance tie.

**Alternatives considered.**
- *Rewrite or delete the offending clause.* Rewriting prose by rule breaks grammar and loses substance. A mark in place keeps every detail and is true whenever the detail is in the span.
- *"Not spoken" for every screen-only detail.* This is false whenever captions mangle the word ("carrot" for carat, "15 000" for 15,000) or the speech is in Devanagari or Bengali. A wrong "not spoken" is itself an attribution error: run 4 confirmed "This was not spoken" about a word read aloud in Bengali.
- *Decide screen-only against the whole video's speech.* This misses run 6's error: the presenter said "light grid lines" at 9:00, and the sentence about 22:28 took "light grid" from the 22:33 frame.
- *Act on a lone two-digit figure.* This would have caught run 9's error. But "10" appears in many spans (`10%`, `figsize=(10, 6)`, axis ticks), so a mark could cite the wrong thing, which is a new error. It is left to a measured follow-up.
- *Keep the guard off until it passes.* It changes only reports with visual spans, all seven of its run-9 changes held up under verification, and the follow-up builds on it.
- *Show R1 anyway, since rule 3 failed by a tie.* That is the user's call, not this decision's. D-105 is theirs, and the pre-registration does not allow it.

**Consequences.**
- R1 stays hidden, and `featureFlags.visualAnalysis` stays `false`.
- Follow-ups on S-1.18.9: lone figures in speaker credits, quote transliterations treated as quotation, an accurate processing note, then two new consecutive runs under the same rule.
- Rule 3 failed by a tie (8.67 against 8.67), which no attribution guard can change. Whether a tie should keep R1 hidden is a question for the user.

**Linked initiatives / PRs.** E-1.18, S-1.18.9; D-067, D-071, D-075, D-105.

**Status-changed 2026-10-25:** kept by [D-109](#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25) — the guard stays in the report pipeline, on by default, while R1 is parked.

## D-107 — R1's substance rule: a tie passes, any loss fails; attribution stays zero-error (2026-10-25)

**Status:** accepted (the user's decision, 2026-10-25). It amends rule 3 of the R1 protocol for the next pre-registered pair of runs (runs 10 and 11). D-105 and D-106 stand until that pair passes.

**Context.** Run 9 failed two rules ([protocol note](notes/2026-10-18-r1-visual-measurement.md), "Run 9: results"). Rule 2 failed on one confirmed attribution error. Rule 3 failed on a tie: one family preferred the annotated report, two called it a tie, none preferred the plain one, and mean substance was 8.67 against 8.67. Rule 3, unchanged since run 6, asked visual analysis to *beat* the plain report. A tie measured no loss, and no attribution guard can change one (D-106 left the question to the user).

**Decision.** The user, verbatim: *"For the next pre-registered pair of R1 runs, count a substance tie (no loss) as passing rule 3. Attribution stays zero-error."* For runs 10 and 11, rule 3 passes when ON's substance is equal to or higher than OFF's. Any loss fails, and there is no margin in either direction. The protocol measures substance two ways, and both must show no loss:
- (a) the mean substance score across the three families: ON ≥ OFF;
- (b) the families' substance preferences: at least as many prefer ON as prefer OFF (a tie counts for neither).

Rule 2 stays at zero confirmed ON attribution errors. Rules 1 and 4 are unchanged, and so are the guard rules 5 and 6 pre-registered for runs 9 and 10.

**Alternatives considered.**
- *Keep "at least two of three families prefer ON".* Rejected by the user: a tie is no loss.
- *Count ties toward ON in the old majority rule ("two of three prefer ON or tie").* This would pass one OFF preference and two ties, which is a loss, and the user's "(no loss)" excludes that.
- *A noise margin, such as passing an ON mean within 0.33 or 0.67 of OFF.* Rejected. The rule is read literally: equal passes, lower fails.
- *Only one of the two measures.* With one measure, a loss on the other would pass unseen. Requiring no loss on both is the literal reading of "any loss fails".

For reference: run 9's outcome (1–0–2, 8.67 vs 8.67) passes the amended rule. Run 8's (two of three preferred ON, but mean 8.33 vs 9.0) fails it on (a).

**Consequences.**
- The next pair, runs 10 and 11, is pre-registered under this rule before either run exists, on the code after T-1.18.9.5 to .7.
- The decision changes the quality bar, not the attribution bar. One confirmed attribution error in either run still fails it.

**Linked initiatives / PRs.** E-1.18, S-1.18.9 (T-1.18.9.8, T-1.18.9.9); D-105, D-106.

**Status-changed 2026-10-25:** kept by [D-109](#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25) — run 11 is not run, and any pair that reopens R1 is pre-registered under these rules.

## D-108 — The attribution guard never infers that a detail went unsaid; it checks only English speech in Latin script (2026-10-25)

**Status:** accepted (the user's decision, 2026-10-25, T-1.18.9.11). It narrows the guard that D-106 shipped. D-105 stands: visual analysis stays hidden, and no new R1 runs were made.

**Context.** R1 run 10 failed the pre-registered bar ([protocol note](notes/2026-10-18-r1-visual-measurement.md), "Run 10: results"). Four of the guard's eleven changes were confirmed attribution errors, and each one took a detail the guard could not find in the transcript as not said:
- The captions wrote "one to one" for "121", which the guard marked "not spoken".
- The speaker said "get started"; the guard marked "getting started" "not spoken".
- "seaborn" and "NumPy" were spoken in Bengali. One got an on-screen mark that read as screen-only; the other lost its "also".

**Decision.** The user chose T-1.18.9.11: no "not spoken" verdict, no removal of "also", and no mark on a source whose speech the guard cannot read. In code:
- A mark says only where a detail was shown: "(on screen at mm:ss)".
- At the map stage, an item's screen-only details are named in its compose tag. The item is never relabelled `shown` or split.
- A source is examined only when its speech is English in Latin script: a Latin share of at least 0.6 and no R5 code-mix profile. Devanagari, Bengali and romanised Hinglish sources are left as written, and the processing note says how many were not checked.
- What rests on positive evidence stays. Speech presented as screen is still marked as said, when the figure is found in the speech (Bengali digits included). An "also visible on screen" with no frame behind it is still removed.

**Alternatives considered.**
- *Keep "not spoken" and read numbers better* ("one to one" as 121, inflected forms). Each fix closes one misreading, and captions have more. The claim stays unprovable from a transcript.
- *Read Hindi and Bengali speech through a transliteration or the R5 English rendering.* Possible later. An LLM rendering is not evidence a guard can trust by construction.
- *Keep marks on unreadable sources for figures and name lists only.* That is where the old guard caught real errors, but it is the same inference that failed in run 10.

**Consequences.**
- Offline, on the stored reports of runs 1 to 10 (in-sample), the guard catches 6 of 11 confirmed errors, down from 9. All three it no longer catches are real errors in Hindi or Bengali sources: CodeWithMunnaX's dataset-name lists (runs 2 and 4) and DeepLoop Circle's "10" (run 9).
- Its report changes fall from 93 to 43, and it makes none the old guard did not make.
- None of run 10's four guard errors recurs. "121" and "getting started" are marked only "(on screen at mm:ss)", which is true, and the two Bengali sentences are left alone.
- Screen-only details in Hindi, Bengali or code-mixed sources are now unguarded, and the processing note discloses it.
- Whether R1 gets another pair of runs remains the user's call.

**Linked initiatives / PRs.** E-1.18, S-1.18.9 (T-1.18.9.10, T-1.18.9.11); D-105, D-106, D-107; [N-003](inventions.md#n-003--true-by-construction-modality-marks-for-reports-written-from-speech-plus-machine-described-screens-2026-10-24).

**Status-changed 2026-10-25:** kept by [D-109](#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25) — the narrowed guard stays as shipped while R1 is parked; way back (c) builds on its English-only reading.

## D-109 — R1 is parked: visual analysis stays hidden, its measurement stops, the code stays (2026-10-25)

**Status:** accepted (the owner's decision, 2026-10-25). It keeps [D-105](#d-105--visual-analysis-hidden-in-the-ui-until-a-deterministic-attribution-guard-removes-the-residual-error-2026-10-20) in force and stops the run series that [D-106](#d-106--the-deterministic-attribution-guard-ships-in-the-report-pipeline-r1-stays-hidden-after-run-9-2026-10-24) and [D-107](#d-107--r1s-substance-rule-a-tie-passes-any-loss-fails-attribution-stays-zero-error-2026-10-25) set up. The guard as [D-108](#d-108--the-attribution-guard-never-infers-that-a-detail-went-unsaid-it-checks-only-english-speech-in-latin-script-2026-10-25) narrowed it stays in the code.

**Context.** R1 has had ten blind-judged runs ([protocol note](notes/2026-10-18-r1-visual-measurement.md)). Annotations never made fabrication worse, but no run met the whole pre-registered bar:
- *Attribution.* About one report sentence per run credits a speaker with a detail shown only on screen. Prompt rules (S-1.18.6), said/shown labels (S-1.18.8) and the deterministic guard (S-1.18.9) each cut it; none removed it. In run 10 the guard's own inference caused four confirmed errors, and D-108 removed that inference by narrowing the guard to English speech in Latin script. Screen-only details in Hindi, Bengali and code-mixed sources are now unguarded, and that is where four of the five confirmed errors after S-1.18.6 were found.
- *Substance.* Runs 9 and 10 showed no gain over the plain report: 8.67 against 8.67, then 8.0 against 8.33. Rule 3 measures the annotations themselves, so no attribution guard can change it.
- *Cost of continuing.* Every pair spends Gemini 3.1 Pro judge quota that the report-level measurements batched in [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) also need.

**Decision.** The owner: *"park R1"*. The recommendation, adopted in full:
1. Visual analysis stays hidden (`featureFlags.visualAnalysis = false`) and R1 measurement stops. Run 11 is not run, and no new pair is pre-registered.
2. The backend, the captured frames and the attribution guard stay in the code. The guard stays on by default. It does nothing on a report without visual spans, which is every report started from the UI.
3. Deferred with R1: T-1.18.9.4 (unhide on a pass) and T-1.18.9.9 (the pair of runs), and the follow-ups T-1.18.1.10, T-1.18.1.11, T-1.18.2.5, T-1.18.5.5, T-1.14.18.6, T-1.14.19.6 and S-1.18.4.
4. Two ways back, taken only if the owner asks:
   - **(c)** annotate only sources whose speech is English in Latin script, the only speech the guard can check, and pre-register a pair on an English-only corpus;
   - **(e)** the post-compose LLM audit that [D-075](#d-075--r1-after-three-runs-the-modality-boundary-needs-provenance-not-prompt-rules-2026-10-19) deferred, checked offline on the stored reports of runs 1 to 10 before any new run.

   Either needs a new pre-registered pair under the [D-107](#d-107--r1s-substance-rule-a-tie-passes-any-loss-fails-attribution-stays-zero-error-2026-10-25) rules: a substance tie passes, any loss fails, and attribution stays zero-error.
5. The [D-096](#d-096--r1-frames-reach-the-user-opt-in-per-run-lazy-stills-and-a-visual_extractions-quota-2026-10-19) capture caps (`visual_extractions`: free 2, Pro 30, Studio 300) stay undecided until R1 returns. [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25) adds Stripe pricing as the other point at which they are decided.

**Alternatives considered.**
- *Run 11, or a new pair now.* Rule 3 failed in runs 9 and 10 for reasons the guard does not touch, so another pair would most likely spend the quota and fail again.
- *Unhide with a disclosure.* The owner rejected that in D-105.
- *Remove the backend.* Either way back is built and tested on the frames, the pipeline and the stored reports of ten runs. Keeping them costs little, since the guard is a no-op without visual spans.
- *Keep the follow-ups open.* They pay off only while R1 is surfaced (D-105), so they wait with it.

**Consequences.**
- E-1.18 is deferred (🔴) on the board, together with S-1.18.4, S-1.18.5, S-1.18.8, S-1.18.9 and the tasks above. T-1.18.8.4 is not named in item 3. It waits as well, because it re-runs the S-1.18.3 protocol and item 1 stops R1 measurement. Shipped stories keep their status.
- R1 spends nothing more, and the judge quota goes to the measurements D-112 batches.
- The guard's tests stay in the suite, so the parked code is still checked.
- Reopening R1 starts with a pre-registration, not a run.

**Linked initiatives / PRs.** E-1.18 (S-1.18.2, S-1.18.4, S-1.18.5, S-1.18.8, S-1.18.9: T-1.18.9.4, T-1.18.9.9), S-1.14.18, S-1.14.19; [D-075](#d-075--r1-after-three-runs-the-modality-boundary-needs-provenance-not-prompt-rules-2026-10-19), [D-096](#d-096--r1-frames-reach-the-user-opt-in-per-run-lazy-stills-and-a-visual_extractions-quota-2026-10-19), [D-105](#d-105--visual-analysis-hidden-in-the-ui-until-a-deterministic-attribution-guard-removes-the-residual-error-2026-10-20), [D-106](#d-106--the-deterministic-attribution-guard-ships-in-the-report-pipeline-r1-stays-hidden-after-run-9-2026-10-24), [D-107](#d-107--r1s-substance-rule-a-tie-passes-any-loss-fails-attribution-stays-zero-error-2026-10-25), [D-108](#d-108--the-attribution-guard-never-infers-that-a-detail-went-unsaid-it-checks-only-english-speech-in-latin-script-2026-10-25).

## D-110 — Echo only sees what the user hands it: no background capture, and the Echo scope rulings (2026-10-25)

**Status:** accepted (the owner's decision, 2026-10-25). It answers the [L3 plan](plans/l3-echo-personal-brain.md#open-questions-the-users-call)'s open questions 2, 4, 5, 6 and 7, sends question 1 to SaaS launch, and confirms [D-089](#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19) item 3.

**Context.** Echo's plan and board had left these calls to the owner:
- The privacy promise (plan question 7): may Echo record browsing in the background, opt-in per site, or does it see only what the user hands it? T-3.7.3.3 (history capture in the extension) was deferred until this was decided, and the browser-history connector (T-3.2.5) with it.
- Whether a fact the user deleted may come back (T-3.2.4.4). Today it can: the GitHub sync upserts derived facts by kind and key, so a forgotten "Python (GitHub)" returns with the next nightly sync.
- Private GitHub activity (T-3.2.4.3), which needs the `repo` scope, full read-write access to code.
- D-089 item 3, the whole-brain archive carrying other people's words the user shared, which shipped in #286 as an interpretation awaiting confirmation; and a per-thread override for quoting other people (plan question 2).
- The Spotify live tail (S-3.2.3, question 4), when Gmail (T-3.2.3, question 5), Mode B fine-tuning (E-3.9, question 6), and private-by-key encryption for SaaS (question 1).

**Decision.** The owner: *"Echo sees only what I hand it"*, with the Echo calls adopted as recommended.
1. **Echo only sees what you hand it.** Every input is something the user did: a share, an import, a note, a fact, or a connector they consented to. Nothing records browsing in the background.
   - T-3.7.3.3 and the background-capture part of T-3.2.5 are won't-do. The design the plan preferred, had the answer been yes, stays in the [L3 plan](plans/l3-echo-personal-brain.md#domain-5--shares-inbox-e-37) for the record.
   - The extension keeps what S-3.7.3 shipped: it sends a page, link, selection or image when the user asks.
   - Private-by-key encryption (question 1) waits until SaaS (S-3.10.3).
2. **Deleted facts stay deleted (T-3.2.4.4): accepted to build.** A delete records a tombstone per (source, kind, key), and syncs skip tombstoned keys. It covers every connector's derived facts, not only GitHub's.
3. **No private-repository scope (T-3.2.4.3): won't-do.** The GitHub connector stays public-only, on `read:user`.
4. **The archive keeps the other people's words the user shared (D-089 item 3): confirmed as shipped in #286.** "Never exported" means dataset and derived exports, not the user's own copy.
5. **No per-thread override for quoting other people** (question 2). Context-only content is retrievable and never quoted verbatim. Marking one's own words stays authorship, not an override.
6. **No Spotify live tail (S-3.2.3): won't-do** (question 4). The extended streaming-history import (S-3.7.5) covers the history.
7. **Gmail (T-3.2.3): never on SaaS before revenue** (question 5). Its restricted scope needs a yearly security assessment. Self-hosters use the IMAP inbox (S-3.7.4), where mail sent to a dedicated mailbox becomes a share.
8. **Mode B fine-tuning (E-3.9) stays parked** (question 6) until the owner's own voice test, the user-as-judge run (T-3.3.4.3), has run.

**Alternatives considered.**
- *Opt-in browsing capture per site and category,* the plan's design had the answer been yes: per-domain host permissions, URL, title and time only, never incognito. Not adopted. It still records in the background, and explicit sharing covers the need. "Only what you hand it" is a promise a user can check against their own actions.
- *Tombstones for GitHub only.* Every connector that derives facts upserts by kind and key, so each would bring a deleted fact back.
- *Private repositories behind a second consent.* GitHub OAuth apps have no read-only scope for private repositories; `repo` includes write access to code.
- *A flagged archive section for other people's words.* D-089's fallback, not needed now that the shipped reading is confirmed.
- *Gmail on SaaS now.* The yearly assessment is a cost before there is revenue to pay for it.

**Consequences.**
- On the board: T-3.7.3.3, T-3.2.5's background-capture part (the only part scoped), T-3.2.4.3 and S-3.2.3 are won't-do (✖); T-3.2.4.4 is accepted (🔵); T-3.2.3, E-3.9 and S-3.10.3 are deferred (🔴); E-3.10's open question is closed.
- A new connector that derives facts goes through the tombstone check once T-3.2.4.4 lands.
- `personal-brain.md` and the L3 plan still describe browser-history capture as an option. Each place now carries a line saying this decision answers it, and the design stays there for the record.
- A browser-history export that the user hands over would be an S-3.7.5 importer, which fits item 1. Nobody has ruled on building one.

**Linked initiatives / PRs.** E-3.2 (T-3.2.3, T-3.2.5, S-3.2.3, S-3.2.4: T-3.2.4.3, T-3.2.4.4), E-3.7 (S-3.7.3: T-3.7.3.3, S-3.7.4, S-3.7.5), E-3.9, T-3.3.4.3, E-3.10 (S-3.10.3); [D-089](#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19), [D-098](#d-098--echo-connectors-events-unique-per-reader-tokens-in-a-secret-store-that-is-erased-with-the-brain-but-never-exported-2026-10-19); PR [#286](https://github.com/khoks/VideoResearchPro/pull/286).

## D-111 — Operator-only tier switching and an honest pricing page (2026-10-25)

**Status:** accepted (the owner's decision, 2026-10-25). It amends [D-050](#d-050--self-service-tier-flip-with-mock-payment-until-e-53-stripe-ships-2026-05-15): the tier switch becomes operator-only. Mock payment, the endpoint's shape and the Stripe swap D-050 planned (T-5.3.1) are unchanged.

**Context.**
- D-050 made `PUT /auth/me/tier` self-service, gated on sign-in only, because on self-host "the operator and the user are the same person 99% of the time". Since then an install can hold several isolated users ([D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)), and the paid tiers unlock work the operator pays for (Author Studio, Echo, saved searches). Any signed-in account can still make itself Studio. `POST /admin/restart`, which restarts every service on the machine, has the same sign-in-only gate.
- The pricing page (`frontend/src/data/tiers.ts`) lists features that do not exist (reels, public report sharing, team workspaces, data-residency selection) and a daily LLM-token allowance (2M on Pro, 10M on Studio) that nothing enforces. In `TIER_CAPABILITIES`, `llm_tokens_per_day` and `document_count_cap` are defined but never checked.

**Decision.** The owner: *"operator-only tier switch, honest pricing page"*.
1. **Operator-only tier switching.** `PUT /auth/me/tier` and `POST /admin/restart` are restricted to operator accounts; every other account is refused.
   - Operators are the accounts listed in a new `ADMIN_EMAILS` setting (comma-separated, case-insensitive).
   - When `ADMIN_EMAILS` is unset, the earliest-registered account is the operator, so a single-user install behaves the same and needs no new configuration.
   - Mock payment, the request and response shapes and the `tier_changed` audit event stay as D-050 set them.
2. **An honest pricing page (E-5.2, `frontend/src/data/tiers.ts`).**
   - Reels, public sharing, team workspaces and data residency are marked as planned.
   - The daily-token lines are dropped, since nothing enforces them.
   - The document caps (500, 5,000, unlimited) stay advertised, and a later E-5.2 item enforces them.
   - The [D-096](#d-096--r1-frames-reach-the-user-opt-in-per-run-lazy-stills-and-a-visual_extractions-quota-2026-10-19) capture caps are decided when R1 returns or Stripe pricing starts ([D-109](#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25)).

**Alternatives considered.**
- *Keep D-050's sign-in-only gate.* On a shared install any account can give itself Studio and spend the operator's provider keys.
- *An `is_admin` column.* Setting it needs SQL or a script, the friction D-050 removed. A setting is one line in `.env`.
- *D-050's `ENABLE_SELF_SERVICE_TIER_FLIP` flag.* All or nothing: either every account can switch, or the operator cannot either.
- *No operator when `ADMIN_EMAILS` is unset.* Every existing single-user install would lose its tier switch on upgrade.
- *Drop the unbuilt features from the page.* Marked as planned, they still say what each tier is for; listing them as included is the defect.
- *Enforce the daily token allowance instead of dropping it.* Tokens are metered only on the Q&A path (T-5.2.7), so the line would stay untrue until metering covers reports and the other call sites.

**Consequences.**
- A multi-user install should name its operators in `ADMIN_EMAILS`. Without it, the first account created on the install is the operator.
- The Subscription page needs to know whether the reader is an operator, so it can say why the switch is unavailable instead of failing on submit.
- D-050's Stripe swap stands, and so does its rule that a SaaS deployment before Stripe turns the switch off. The flag is rejected only as the gate for a multi-user self-host install.
- Enforcing the document caps is its own task (T-5.2.10).

**Linked initiatives / PRs.** E-5.2 (T-5.2.6, T-5.2.8, T-5.2.9, T-5.2.10), E-5.3 (T-5.3.1), E-5.10; [D-045](#d-045--quota-metering-enforce-before-record-after-success-2026-05-05), [D-050](#d-050--self-service-tier-flip-with-mock-payment-until-e-53-stripe-ships-2026-05-15), [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-096](#d-096--r1-frames-reach-the-user-opt-in-per-run-lazy-stills-and-a-visual_extractions-quota-2026-10-19), [D-109](#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25).

## D-112 — The remaining rulings of 2026-10-25: map batching, public sharing, the code-mixing threshold and the quick calls (2026-10-25)

**Status:** accepted (the owner's decisions, 2026-10-25). One bullet per ruling. [D-109](#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25), [D-110](#d-110--echo-only-sees-what-the-user-hands-it-no-background-capture-and-the-echo-scope-rulings-2026-10-25) and [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25) carry the larger rulings of the same day.

**Context.** Questions left to the owner had collected across the log, the board and the plans: a default restored by a pre-registered rule against other evidence (D-094), designs waiting for a go-ahead, a threshold resting on Claude's own labels (D-080), plan defaults taken without the owner, and items marked "the user's call". The owner adopted every recommendation, among them *"keep packed batching and run the comparison later"*, *"defer public sharing"* and *"Hindi spot check before changing the threshold"*. The owner's message ended *"and ratify the plan"*, which names no plan. This record maps it to the plan defaults Claude took without the owner, which are listed in the "Ratified:" bullet below. The build order (`plans/build-order.md`) is not in that list and stays a recommendation. If the owner meant the build order, its status line changes to ratified.

**Decision.**

*Measurement and thresholds*
- **Map batching stays `packed` plus the starved-source re-map ([D-094](#d-094--map-batching-packed-restored-by-run-7s-pre-registered-rule-starved-sources-re-mapped-alone-the-switch-to-source-is-the-users-call-2026-10-19); T-1.14.20.4, S-1.14.18, S-1.17.4).** `source` batching failed run 7's pre-registered substance gate, so switching without a measurement would override that rule. The report-level comparison (the second half of T-1.14.20.4) runs later. Its pass rule is pre-registered first, in the [D-107](#d-107--r1s-substance-rule-a-tie-passes-any-loss-fails-attribution-stays-zero-error-2026-10-25) style (a tie passes, any loss fails), with an explicit fabrication count. It is batched with S-1.14.18 and S-1.17.4, because all three spend the shared Gemini 3.1 Pro judge quota.
- **The code-mixing dominant threshold stays at 0.6 ([D-080](#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19) open question 3; T-1.16.2.7).** It changes only after the native-reader spot check, because the 0.912 against 0.824 agreement figures that favour 0.5 rest on labels Claude made.
- **OQ-9 (E-1.17): S-1.17.4 runs first and decides it.** Today's `dominant` wording stays meanwhile ([D-072](#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19)).
- **OQ-16 (E-1.14): a model measured `unacceptable` is not refused.** The warning stays, because the verdicts rest on n=2 ([D-076](#d-076--model-guidance-measured-means-the-use-cases-own-output-was-graded-verdicts-warn-never-block-2026-10-19)).
- **OQ-7 (E-1.14): the model-quality harness is run by hand whenever a registry default changes,** not on a schedule.
- **S-1.17.3 may reverse D-072's no-backfill rule,** with an amendment to D-072 in the same PR.

*Sharing and output*
- **Public report sharing is deferred (E-8.11, M11).** The static site zip covers sharing meanwhile: S-6.2.1 accepts `job:<id>`, so one report can be handed over as a site. If sharing is ever built, the takedown and revoke hooks go inside S-8.11.2. That breaks the circle in which T-5.5.6 (takedown) waited for M11 and M11 waited for T-5.5.6.
- **S-6.2.2: download only, no one-click publishing (won't-do).** E-6.2 is shipped.
- **E-6.5 (reels) is deferred.** When built: hosted TTS by default, local TTS as opt-in, a Hindi listening test, and no B-roll (L2 plan questions 1 and 2).
- **L2 plan questions 3 and 4 are deferred:** book template variants, and a hosted site preview under the app's own origin.
- **E-2.8 (brand assets): the interim echo mark is the identity.** The full logo (T-2.8.2) and the marketing logos (T-2.8.4) are made from it now, which also gives the marketing site the favicon its layout links to. `og.png` (T-2.8.3) is made when M11 is scheduled. A newly designed glyph (T-2.8.1) is not pursued.

*Ranking and the workbench*
- **S-1.5.13 (source types on job creation): go-ahead.**
- **S-8.6.3 (a relative publish window in templates): yes,** as a ranking preference, never a filter ([D-059](#d-059--selection-quotas-preferred-channel-guarantee--concentration-cap-2026-07-30), [D-072](#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19)), built after S-1.5.13.
- **E-7.2 (perspective banding) waits until the owner has weighted channels for real.** If it starts sooner, it starts with a researched plan and a pre-registered rule.
- **T-7.1.2.2: a weight near 0 keeps today's behaviour** (on a broad corpus the channel drops out of answers). The channel page's slider text, which promises the opposite ("near 0 they appear only when little else matches"), is corrected ([D-068](#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18)).
- **S-8.2.3 (the semantic palette group) and S-8.9.3 (topic clusters) stay parked.**
- **M7 open question 1: no stance classification for YouTube videos.**

*Settled defaults and housekeeping*
- **Ratified** (*"ratify the plan"*: the plan defaults taken without the owner)**:** [D-083](#d-083--organisation-features-access-and-scope-defaults-on-the-plans-open-questions-2026-10-19) (its item 6, the read-only weight slot, is replaced by D-068's control, which S-7.1.1 shipped), [D-074](#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19), [D-079](#d-079--report-markdown-source-on-markdownify-new-report-routes-are-header-bearer-only-2026-10-19), [D-088](#d-088--report-intermediates-persisted-per-run-on-by-default-frozen-at-the-stage-that-produced-them-2026-10-19), [D-092](#d-092--library-graph-computed-per-request-sigma-used-directly-as-a-lazy-chunk-three-group-colours-the-accessibility-layer-inside-the-story-2026-10-19), and the M3 saved-search caps (Free 0, Pro 10, Studio 50; library and shelf scopes only; S-8.3.2). D-085 is amended in the PR that takes sign-in tokens out of URLs, not here.
- **`/health/quota` showing an install-wide total without sign-in is by design,** and T-5.10.2.5 is closed. The YouTube Data API quota it reports belongs to the install, not to a user.
- **The root `.env.example` is canonical.** `JWT_SECRET`, `ANTHROPIC_API_KEY` and `GOOGLE_API_KEY` are merged into it, `BYOK_ENCRYPTION_KEY` is added with its generate command, and then `backend/.env.example` is deleted.
- **A real-phone pass is part of M12's acceptance (S-8.12.3, [D-087](#d-087--mobile-reading-and-install-a-reading-toolbar-below-1200-px-a-docked-composer-lifted-by-visualviewport-hermetic-device-tests-a-manifest-without-a-service-worker-2026-10-19)).**

**Alternatives considered.**
- *Switch the default to `source` on its fabrication evidence (0 confirmed against 6).* That overrides a rule written before the data. The comparison can decide it under a rule written before it runs.
- *Move the dominant threshold to 0.5 now.* The figures that favour it rest on Claude's labels, so a native reader's check comes first.
- *Launch public sharing with the plan's cheap mitigations.* A public, unauthenticated route that hosts model-written content needs takedown tooling and abuse signals the app does not have, and the site zip already lets the owner hand a report over.
- *Refuse `unacceptable` models.* Two samples are too few to take a setting away from the user.
- *One-click site publishing.* It needs a stored provider token for something a downloaded zip already does.

**Consequences.**
- On the board: S-1.5.13, S-1.14.18, S-1.17.4, T-1.14.20.4, T-1.16.2.7, S-8.6.3, S-8.12.3, T-2.8.2, T-2.8.4 and two new tasks (T-5.6.7, the `.env.example` merge; T-7.1.1.6, the slider text) are accepted (🔵). E-8.11, E-6.5, E-7.2, S-8.2.3, S-8.9.3 and T-2.8.3 are deferred (🔴). S-6.2.2, T-7.1.2.2 and T-2.8.1 are won't-do (✖). E-6.2 is shipped (🟢), T-5.10.2.5 is closed, and E-8.12 reopens to 🟡 until the real-phone pass is done. E-8.2 and E-8.9 are marked shipped (🟢) as well, since their only open stories (S-8.2.3, S-8.9.3) are parked.
- The comparison's pass rule (T-1.14.20.4) is pre-registered before it runs; S-1.14.18 and S-1.17.4 are scheduled with it because all three spend the shared Gemini 3.1 Pro judge quota. *Recommendation, not part of the ruling:* pre-register the other two's pass rules the same way before they run.
- OQ-7, OQ-9 and OQ-16 on the board are answered; D-080's question 3 stays open with its condition.

**Linked initiatives / PRs.** E-1.14 (S-1.14.18, S-1.14.20: T-1.14.20.4), E-1.16 (T-1.16.2.3, T-1.16.2.7), E-1.17 (S-1.17.3, S-1.17.4), S-1.5.13, E-2.8, E-5.5 (T-5.5.6), E-5.6 (T-5.6.7), E-5.10 (T-5.10.2.5), E-6.1, E-6.2 (S-6.2.1, S-6.2.2), E-6.5, E-7.1 (T-7.1.1.6, T-7.1.2.2), E-7.2, E-8.1, E-8.2 (S-8.2.3), E-8.3 (S-8.3.2), E-8.6 (S-8.6.3), E-8.7, E-8.9 (S-8.9.3), E-8.11 (S-8.11.2), E-8.12 (S-8.12.3); [D-059](#d-059--selection-quotas-preferred-channel-guarantee--concentration-cap-2026-07-30), [D-068](#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18), [D-072](#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19), [D-074](#d-074--notes-one-stream-per-document-soft-delete-only-lossless-w3c-json-ld-export-echo-feeder-reported-not-gated-2026-10-19), [D-076](#d-076--model-guidance-measured-means-the-use-cases-own-output-was-graded-verdicts-warn-never-block-2026-10-19), [D-079](#d-079--report-markdown-source-on-markdownify-new-report-routes-are-header-bearer-only-2026-10-19), [D-080](#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19), [D-082](#d-082--job-templates-identity-plus-immutable-versions-provenance-without-a-foreign-key-starters-in-a-self-contained-data-migration-2026-10-19), [D-083](#d-083--organisation-features-access-and-scope-defaults-on-the-plans-open-questions-2026-10-19), [D-085](#d-085--reading-room-reports-stay-html-sanitised-and-parsed-in-the-browser-one-shared-citation-card-fed-by-the-runs-documents-2026-10-19), [D-087](#d-087--mobile-reading-and-install-a-reading-toolbar-below-1200-px-a-docked-composer-lifted-by-visualviewport-hermetic-device-tests-a-manifest-without-a-service-worker-2026-10-19), [D-088](#d-088--report-intermediates-persisted-per-run-on-by-default-frozen-at-the-stage-that-produced-them-2026-10-19), [D-092](#d-092--library-graph-computed-per-request-sigma-used-directly-as-a-lazy-chunk-three-group-colours-the-accessibility-layer-inside-the-story-2026-10-19), [D-094](#d-094--map-batching-packed-restored-by-run-7s-pre-registered-rule-starved-sources-re-mapped-alone-the-switch-to-source-is-the-users-call-2026-10-19), [D-107](#d-107--r1s-substance-rule-a-tie-passes-any-loss-fails-attribution-stays-zero-error-2026-10-25).
