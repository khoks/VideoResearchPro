# Pratidhvani — Decision Log

**Status:** living doc (last refreshed 2026-11-10). Owner: [`/knowledge-curator`](../.claude/skills/knowledge-curator/SKILL.md) skill.

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
- The chunker rework is also the natural moment to revisit pseudo-timestamp synthesis ([D-013](#d-013--pseudo-timestamps-at-3-wps-for-text-based-connectors-2026-04-25)) — they could be replaced with explicit per-segment indices once `extra` is preserved.

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

**Status-changed 2026-11-04:** a correction, found by PR [#401](https://github.com/khoks/VideoResearchPro/pull/401). The decision and its consequences say the codebase keeps the legacy defaults. That was already untrue of the Chroma collection when this was written: T-2.6.1 (PR [#106](https://github.com/khoks/VideoResearchPro/pull/106), merged 2026-05-02) had moved `CHROMA_GLOBAL_COLLECTION_NAME`'s default to `pratidhvani_global`, so an install that embedded under the old default has to pin that name or migrate. `DATABASE_URL` is the default that stayed legacy. The runbook approach stands.

**Status-changed 2026-11-05:** the runbook's table row for `backend/alembic.ini` no longer applies. [D-139](#d-139--alembic-uses-the-url-a-caller-names-else-the-setting-and-alembicini-holds-none-2026-11-05) makes Alembic follow `DATABASE_URL`, so section B needs no ini edit (T-2.6.7, PR [#412](https://github.com/khoks/VideoResearchPro/pull/412)). The reasoning here, an operator-coordinated rename, stands.

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

**Status-changed 2026-11-04:** the 25 MB limitation under Consequences is lifted, and the audio-split hook fired. PR [#408](https://github.com/khoks/VideoResearchPro/pull/408) sends an episode over the cap through the chunked path YouTube has used since S-1.11.2 ([D-135](#d-135--the-publish-window-is-a-preference-that-leads-the-inferred-profile-a-window-that-cannot-act-is-refused-and-starters-name-only-sources-that-need-no-search-credential-2026-11-04)). The expectation that in-feed transcripts sidestep the limit did not hold in a live sample: 0 of 8 episodes published one and 4 were over the cap, so Whisper is the main text path for podcasts, not a fallback. The decision itself, reusing the OpenAI path, stands.

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

**Status-changed 2026-10-29:** amended by [D-116](#d-116--oauth-links-or-creates-an-account-only-from-a-provider-verified-email-and-the-link-records-it-2026-10-29) (T-5.4.10, PR [#384](https://github.com/khoks/VideoResearchPro/pull/384)), which adopts option (B'). A first OAuth link or a new OAuth account now needs a provider-verified email (Google's `email_verified` claim; GitHub's primary address in `/user/emails` with `verified: true`, since the `/user` public email carries no verification we can check), and `oauth_identities.email_verified_at` records it. Path B stands for verified addresses.

**Status-changed 2026-11-04:** an OAuth sign-in to an account with two-step verification on now stops at the second factor, like a password sign-in ([D-121](#d-121--reset-codes-never-appear-in-a-response-two-step-verification-guards-every-sign-in-and-tokens-say-what-they-are-2026-11-04), S-5.4.1, PR [#389](https://github.com/khoks/VideoResearchPro/pull/389)). Before, the callback issued a full session, so whoever controlled the linked provider account skipped the TOTP the user had turned on.

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
- The "no discovery surface" pattern from [D-035](#d-035--connectors-with-no-discovery-surface-raise-notimplementederror-dispatcher-treats-as-zero-candidates-2026-05-03) is preserved — URL-fetch would be intake, not discovery.
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

**Context.** Self-host operators today must `UPDATE users SET tier = 'studio' WHERE email = '...'` directly in SQL to evaluate paid-tier features (BYOK, Author Studio, Echo). That's hostile UX — the user has to know the schema, find the DB path, write SQL — and it's an obstacle to "kick the tires on Pro before deciding". The cleanest fix is a self-service Subscription page inside the app + a public Pricing page that explains what each tier unlocks. But the project is pre-Stripe (E-5.3 deferred to SaaS launch per [D-038](#d-038--tenancy-retrofit-ships-in-four-phases-audit--additive--backfillwrites--reads--not-null-2026-05-04) sequencing), so a "real" payment flow isn't shippable today.

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

**Context.** [D-055](#d-055--intelligence-delta-evaluation-methodology-production-input-replay--blind-ab-judging-2026-07-29) measured the report pipeline losing ~99.6% of its source material: a 200-video job produced a report citing 2 channels out of 92 and 4 videos out of 200, with zero quantitative claims, while asserting it synthesized 137 videos. Blind judging scored it 3.5/10 against a max-effort control at 8.5. The user approved fixing the funnel first (it is model-independent and cheaper than a tier upgrade), and added a requirement: **report size should scale with the amount of information the corpus actually yielded**, comparable to the depth seen in per-video knowledge extraction.

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

**Context.** [D-055](#d-055--intelligence-delta-evaluation-methodology-production-input-replay--blind-ab-judging-2026-07-29) measured the production report at **3.5/10 against a max-effort control at 8.5/10, gap SEVERE**. Every structural cause of that verdict has since changed (D-056 funnel fix, D-057 Luna volume tier, D-060 extraction ratio), so the verdict was re-run on the same 200-video corpus with the same blind method.

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

**Status-changed 2026-11-04:** knowledge synthesis, the last surface with no preference, is covered by [D-125](#d-125--a-knowledge-reports-depth-applies-d-064-without-a-bracket-and-belongs-to-the-shared-artifact-and-a-failed-synthesis-never-reaches-it-2026-11-04), and the per-request override is now on the Q&A pages.

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

**Status-changed 2026-11-04:** extended by [D-128](#d-128--one-source-is-a-narrowing-key-on-qascope-every-citation-carries-document_id-and-the-notification-push-is-a-doorbell-2026-11-04): every citation carries `document_id`, and that is the id a scope check compares.

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

**Status-changed 2026-11-04:** point 2's "no backfill" is amended by [D-120](#d-120--older-chunks-gain-their-era-and-publish-fields-by-a-metadata-only-pass-amends-d-072-the-language-profile-is-stored-on-the-document-2026-11-04) (S-1.17.3, PR [#390](https://github.com/khoks/VideoResearchPro/pull/390)). An owner-run, metadata-only pass brings older chunks up to the era and publish fields the chunker writes today, still omitting unknown fields. The alternative below, *Backfill the existing Chroma collection*, was rejected for the cost of re-embedding, which a metadata update does not incur.

**Status-changed 2026-11-09:** a pasted social post or article now gets `published_at` from the page, or for X and LinkedIn from the post's id, and a date before 1995-01-01 or after tomorrow is stored as unknown, never as a sentinel ([D-154](#d-154--a-posts-id-dates-it-a-placeholder-date-is-no-date-a-connector-request-gets-one-retry-and-xs-only-when-unanswered-and-the-x-token-line-reports-configuration-only-2026-11-09), T-1.5.8.4, PR [#431](https://github.com/khoks/VideoResearchPro/pull/431)).

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

**Status-changed 2026-11-04:** three addenda are in [D-133](#d-133--the-tagger-abstains-without-hindi-evidence-the-presence-floor-reads-grammar-an-offline-lexicon-sees-english-in-devanagari-and-scores-are-quoted-from-the-production-row-2026-11-04) (PR [#403](https://github.com/khoks/VideoResearchPro/pull/403)): `OTHER` refines "non-English", the presence floor reads grammar, and English in Devanagari is an offline lexicon, not the hybrid LLM pass deferred here. On open question 3, TEST Devanagari agreement at 0.5 / 0.6 / 0.8 moved from 0.912 / 0.824 / 0.647 to 0.971 / 0.912 / 0.882, so the robustness case for 50% is much weaker but not gone. [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25)'s 0.6 stands until T-1.16.2.7.

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

**Status-changed 2026-11-04:** point 2's "a revision is a new migration that copies them" is amended by [D-135](#d-135--the-publish-window-is-a-preference-that-leads-the-inferred-profile-a-window-that-cannot-act-is-refused-and-starters-name-only-sources-that-need-no-search-credential-2026-11-04): a revision carries only the entries it changes, because its downgrade walks the list and a whole-list copy would delete the five built-ins. The relative window shipped as S-8.6.3 and the two deferred starters as S-8.6.4 (PR [#408](https://github.com/khoks/VideoResearchPro/pull/408)).

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
- *What the browser does instead.* It fetches each file with the Authorization header and hands it over as a blob: URL (`services/apiFiles.ts`). The quick peek frames the report in an iframe sandboxed to `allow-popups allow-popups-to-escape-sandbox`, so nothing runs and the document has an opaque origin while its `target="_blank"` source links still open tabs. A blob: URL takes the app's origin, and "Open in new tab" shows the same bytes top-level where no sandbox applies, so the report HTML also gets a `script-src 'none'` CSP meta tag ahead of everything else. Exports save through `<a download>` on the object URL. PDF citations, whose `/library/pdf/{digest}.pdf#page=N` permalinks 401'd in a new tab (E-1.8), fetch the PDF and open its blob URL with `#page=` kept, in Q&A answers, in the reader's chips, card and endnotes, in an Echo draft's sources and from the knowledge reader's "Open the source". Only that route opens in a tab (`OPENABLE_API_FILES`), and its bytes are re-wrapped as `application/pdf` whatever came back: a chip's href can be written by the model, and a generic "fetch any `/api/v1` href and open it" would show an authenticated response top-level on the app's origin. Any other API href stays a plain link and 401s. The tab is opened inside the click, before the download, with its opener cut by hand, because a `window.open` after the await is blocked once the click's user activation lapses (any async gap in Safari) and with `noopener` returns null even on success; a blocked tab now gets a toast instead of nothing. Frame stills already loaded this way (S-1.18.2), as did Author downloads (S-6.7.2).
- *What remains, and why.* The `/ws/jobs` WebSocket still authenticates with `?token=`: the browser WebSocket API cannot set headers on the handshake. That token still reaches access logs. Moving it into the first message, or a single-use ticket, is the remaining option and is not taken here. `tests/test_routers/test_url_tokens.py` walks every route's dependency tree and fails if an HTTP route reads a credential from the query string again; it finds the WebSocket's own parameter to prove the walk can see one.
- *Trade-off.* An export is now held in memory as a blob before the save dialog appears, where the link streamed straight to disk. A short-lived single-use download ticket in the URL would keep streaming, but it needs server state for six read-only routes and still puts a credential in a URL.

**Linked initiatives / PRs.** [S-8.8.1](initiatives.md#s-881--report-content-endpoint-and-sanitised-renderer) (PR [#244](https://github.com/khoks/VideoResearchPro/pull/244)), [S-8.8.2](initiatives.md#s-882--citation-hover-cards-and-footnotes) (PR [#254](https://github.com/khoks/VideoResearchPro/pull/254)), T-8.8.1.5, S-1.14.17, D-079.

**Status-changed 2026-11-09:** the addendum's "what remains" is closed. `/ws/jobs` takes its token as a WebSocket subprotocol offered after `bearer`, never in the URL, so no route takes a credential from a URL ([D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09), T-5.4.23, PR [#425](https://github.com/khoks/VideoResearchPro/pull/425)).

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

**Status-changed 2026-11-04:** point 3's repointing now matters only for stored books. A book's contents take their ids from the rendered manuscript ([D-136](#d-136--a-books-contents-take-their-ids-from-the-rendered-manuscript-the-main-chunk-meets-its-budget-with-lazy-markdown-and-lazy-routes-and-the-device-suites-server-is-dual-stack-2026-11-04), T-8.8.4.2, PR [#410](https://github.com/khoks/VideoResearchPro/pull/410)), so a newly generated book needs none of it, and the reader keeps it for books written earlier.

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

**Status-changed 2026-11-04:** point 5 is amended by [D-137](#d-137--a-share-target-posts-to-a-worker-scoped-to-one-path-and-waits-for-one-tap-mail-is-unverified-text-that-never-trains-the-voice-shared-links-go-through-the-public-address-guard-2026-11-04). The app now has one service worker, scoped to `/echo/share-target` alone, for a `POST` share target (T-3.7.6.1, PR [#407](https://github.com/khoks/VideoResearchPro/pull/407)). It redirects outside its scope, so it controls no page, no request of the app's goes through it, and it caches nothing for reading. The reasons given here for having no service worker stand.

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

**Status-changed 2026-11-04:** the archive now filters a rejected signal's evidence at export time, a second counted exception to its lossless round trip beside the open voice test ([D-134](#d-134--a-live-manual-fact-holds-its-key-against-every-source-a-401-retries-one-call-a-lease-guards-the-refresh-token-and-a-changed-row-beats-a-refresh-answer-2026-11-04), T-3.3.1.7, PR [#409](https://github.com/khoks/VideoResearchPro/pull/409)). `echo_email_messages` is in `ECHO_TABLES`, so it is exported and erased with the brain ([D-137](#d-137--a-share-target-posts-to-a-worker-scoped-to-one-path-and-waits-for-one-tap-mail-is-unverified-text-that-never-trains-the-voice-shared-links-go-through-the-public-address-guard-2026-11-04)).

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

**Status-changed 2026-11-04:** extended by [D-128](#d-128--one-source-is-a-narrowing-key-on-qascope-every-citation-carries-document_id-and-the-notification-push-is-a-doorbell-2026-11-04): `document_id` is a new narrowing key, and the narrowest one.

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

**Status-changed 2026-11-05:** `language_of` gains a fifth label, `other`, a label on what the user wrote and never a language to write in ([D-144](#d-144--a-fifth-voice-label-other-names-no-language-to-write-in-a-job-fills-gaps-and-only-the-backfill-rewrites-and-the-declared-audio-language-is-a-key-on-the-document-2026-11-05), T-3.3.2.11, PR [#418](https://github.com/khoks/VideoResearchPro/pull/418)).

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

**Status-changed 2026-11-04:** tier (iii) now also runs in the app, with no operator ([D-127](#d-127--the-in-app-voice-test-is-a-rolled-back-what-if-on-the-echo_draft-use-case-and-an-open-tests-answers-stay-out-of-the-export-2026-11-04)). The rule is unchanged, and nobody has taken the test yet.

**Status-changed 2026-11-05:** the voice test's procedure is amended for one case. A held-out note that reads `other` has no language to name, so the drafter is told "the language of the situation above" ([D-144](#d-144--a-fifth-voice-label-other-names-no-language-to-write-in-a-job-fills-gaps-and-only-the-backfill-rewrites-and-the-declared-audio-language-is-a-key-on-the-document-2026-11-05), T-3.3.2.11, PR [#418](https://github.com/khoks/VideoResearchPro/pull/418)). That relies on the topic call answering in the note's language, which has not been checked on a real note (T-3.4.1.16). `TOPIC_PROMPT` is unchanged.

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

**Status-changed 2026-11-04:** the in-app test writes `echo_voice_gates` as `--record` does, and drafts now honour the user's pins for the three Echo use cases ([D-127](#d-127--the-in-app-voice-test-is-a-rolled-back-what-if-on-the-echo_draft-use-case-and-an-open-tests-answers-stay-out-of-the-export-2026-11-04)).

**Status-changed 2026-11-05:** "flagged `ungrounded`" is superseded by a refusal, `409 ungrounded`, and "a stopped draft is not counted" is narrowed: a refusal the model wrote counts against the daily cap ([D-142](#d-142--a-draft-with-nothing-behind-it-is-refused-a-register-needs-a-saved-draft-and-overlapping-syncs-are-settled-by-the-databases-insert-2026-11-05), T-3.4.1.11, PR [#416](https://github.com/khoks/VideoResearchPro/pull/416)). The other points stand, including an advisory critic.

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

**Status-changed 2026-11-04:** item 2 is built ([D-122](#d-122--a-deleted-derived-fact-stays-deleted-per-connector-only-a-refused-refresh-asks-for-a-reconnect-restore-re-checks-the-evidence-2026-11-04), T-3.2.4.4, PR [#392](https://github.com/khoks/VideoResearchPro/pull/392)). Tombstones are keyed on the connector or importer name rather than the fact's source string, so a re-import of the same kind of export is covered as well as a re-sync.

**Status-changed 2026-11-04:** item 7's IMAP inbox is built for self-hosters, off by default ([D-137](#d-137--a-share-target-posts-to-a-worker-scoped-to-one-path-and-waits-for-one-tap-mail-is-unverified-text-that-never-trains-the-voice-shared-links-go-through-the-public-address-guard-2026-11-04), T-3.7.4.1, PR [#407](https://github.com/khoks/VideoResearchPro/pull/407)). It has not run on a real mailbox (T-3.7.4.3).

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
- An address in `ADMIN_EMAILS` makes whoever holds that account an operator, and `POST /auth/register` verifies no email. So the operator registers the account before listing it: password registration refuses a listed address (403), OAuth creates or links one only when the provider verified it (Google's `email_verified`; GitHub's public email, which GitHub only allows to be a verified address), and startup logs a warning for every listed address with no account (review of the T-5.2.8 PR).
- The Subscription page needs to know whether the reader is an operator, so it can say why the switch is unavailable instead of failing on submit.
- D-050's Stripe swap stands, and so does its rule that a SaaS deployment before Stripe turns the switch off. The flag is rejected only as the gate for a multi-user self-host install.
- Enforcing the document caps is its own task (T-5.2.10).

**Linked initiatives / PRs.** E-5.2 (T-5.2.6, T-5.2.8, T-5.2.9, T-5.2.10), E-5.3 (T-5.3.1), E-5.10; [D-045](#d-045--quota-metering-enforce-before-record-after-success-2026-05-05), [D-050](#d-050--self-service-tier-flip-with-mock-payment-until-e-53-stripe-ships-2026-05-15), [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-096](#d-096--r1-frames-reach-the-user-opt-in-per-run-lazy-stills-and-a-visual_extractions-quota-2026-10-19), [D-109](#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25).

**Status-changed 2026-10-29:** the rulings stand; two consequences were carried further while building. The document caps are enforced as [D-115](#d-115--the-document-cap-counts-visible-documents-a-request-that-names-its-documents-is-all-or-nothing-and-nothing-is-granted-before-approval-2026-10-29) sets out (T-5.2.10, PR [#385](https://github.com/khoks/VideoResearchPro/pull/385)). The OAuth rule for listed addresses is replaced by [D-116](#d-116--oauth-links-or-creates-an-account-only-from-a-provider-verified-email-and-the-link-records-it-2026-10-29), which requires a provider-verified email for every first link or new account, and no longer counts GitHub's public email as verified (T-5.4.10, PR [#384](https://github.com/khoks/VideoResearchPro/pull/384)).

**Status-changed 2026-11-05:** the pricing links drop `?intent=`, and the paid cards read **Start on Free**, because every new account starts on Free ([D-140](#d-140--a-sign-in-makes-one-redirect-the-query-cache-ends-with-the-session-the-error-screen-replaces-the-page-and-signed-out-pricing-leads-to-free-2026-11-05), T-4.11.2.5, PR [#414](https://github.com/khoks/VideoResearchPro/pull/414)).

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

**Status-changed 2026-11-04:** the one-`.env.example` ruling shipped in PR [#401](https://github.com/khoks/VideoResearchPro/pull/401), which also deleted `frontend/.env.example`, a file this entry did not name ([D-129](#d-129--drift-tests-hold-the-docs-to-the-code-the-repo-has-one-env-template-and-the-anchor-checker-writes-only-when-told-to-2026-11-04)).

**Status-changed 2026-11-04:** two more rulings are built. T-2.8.2 and T-2.8.4 shipped in PR [#404](https://github.com/khoks/VideoResearchPro/pull/404) ([D-130](#d-130--the-brand-lockup-follows-branding-section-3-dark-logos-are-separate-files-and-the-outline-generators-tools-are-not-dependencies-2026-11-04)), though the owner has not seen the artwork, and S-8.6.3 shipped in PR [#408](https://github.com/khoks/VideoResearchPro/pull/408) ([D-135](#d-135--the-publish-window-is-a-preference-that-leads-the-inferred-profile-a-window-that-cannot-act-is-refused-and-starters-name-only-sources-that-need-no-search-credential-2026-11-04)). The 0.6 threshold stands: [D-133](#d-133--the-tagger-abstains-without-hindi-evidence-the-presence-floor-reads-grammar-an-offline-lexicon-sees-english-in-devanagari-and-scores-are-quoted-from-the-production-row-2026-11-04)'s figures weaken the case for 50% without closing it.

**Status-changed 2026-11-05:** the trust-weight slider's text is corrected as ruled (T-7.1.1.6, PR [#414](https://github.com/khoks/VideoResearchPro/pull/414)).

## D-113 — Knowledge text for any source: the transcript cache, else the document's chunks put back together (2026-10-29)

**Status:** accepted (2026-10-29). Made while building knowledge reports for non-video documents (PR [#383](https://github.com/khoks/VideoResearchPro/pull/383)) and its review fixes, not ruled by the owner.

**Context.**
- `POST /videos/{id}/extract-knowledge` read the text from `transcript_cache` by `video_id`. That column is NULL for every non-video source ([D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19)), and PDFs, pasted pages and connector documents keep their text only as chunks in the global Chroma collection. So every one of them got a 422. It was found while shipping S-5.10.5 (PR [#378](https://github.com/khoks/VideoResearchPro/pull/378)), which made their artifacts exportable.
- Neighbouring chunks overlap by `CHUNK_OVERLAP` tokens, and chunk ids do not sort in reading order (`:10` sorts before `:2`).
- `insert_chunks` upserts and never deletes, so a re-ingest that produces fewer chunks leaves the earlier ingest's higher-index chunks in place.

**Decision.**
1. `document_text_service.full_text(db, document)`, keyed on `document_id`, is the one reader. It takes the `transcript_cache` row (by `document_id`, then the legacy `video_id`), otherwise the document's chunks from the global collection. The router returns 422 only when neither holds any text.
2. Chunks are put back together:
   - in numeric `chunk_index` order (the chunk-id suffix when a chunk has no index), each index read once;
   - with the overlap removed: the longest run of words that ends one chunk and starts the next is dropped, capped at `max(4 × CHUNK_OVERLAP, 64)` words, and the rest of the chunk is kept exactly as stored;
   - one paragraph per chunk, so the knowledge splitter gets sentence-aligned boundaries;
   - after dropping chunks left by an earlier, longer ingest. Every ingest rewrites chunk 0, so its `total_chunks` is the current count; a chunk at or past that index, or carrying a different count, is dropped and logged. When chunk 0 has no count, every chunk is kept.
3. The Chroma read is fail-soft: an error reads as no chunks, so the request gets a 422, not a 500.
4. The knowledge prompts name the source by its type through `knowledge_prompts.SOURCE_PROFILES` (a PDF is "the text of a PDF document", with `Document:` / `Author:`). A video's prompts stay byte-identical, so measured video behaviour cannot move. Every profile keeps the English-output rule, the three quote forms, the temporal note, the code-mixing note and the visual contract.

**Alternatives considered.**
- *Write a `transcript_cache` (or `text_cache`) row from every ingest path.* A schema-wide change across five paths, and generalising the cache into `text_cache` is its own story.
- *Re-extract a PDF from its stored bytes (`PDF_UPLOAD_DIR`).* It covers PDFs only and puts PyMuPDF on this path. Chunks are the one store every source type has, and putting them back together returns the original text up to whitespace.
- *Hand the chunks to the agent as stored.* The overlap repeats the sentences at every boundary, and id order scrambles any document of ten or more chunks.

**Consequences.**
- Every library row whose text has been read has a Knowledge button, whatever its source type, and the job page opens the drawer by `document_id`.
- Since PR [#382](https://github.com/khoks/VideoResearchPro/pull/382) ([D-114](#d-114--which-sources-a-topic-run-searches-settings-decide-one-budget-for-the-run-no-whisper-before-approval-2026-10-29), point 7), a document fetched by a topic run's search has a `transcript_cache` row keyed on `document_id`, so its text is read from the cache. Uploaded PDFs and pasted pages are still read from their chunks.
- The token budgets (`KNOWLEDGE_MAX_TRANSCRIPT_TOKENS` and the 500K ceiling) are unchanged.
- A video with no cache row falls back to its chunks, which may carry `[VISUAL @ ...]` spans; the extract prompt's visual contract covers them ([D-067](#d-067--visual-understanding-separate-frames-table-marker-in-text-annotation-opt-in-per-job-2026-07-31)).
- A length preference for knowledge reports stays S-1.15.3.

**Linked initiatives / PRs.** E-1.8 (follow-up: knowledge reports for non-video documents), S-5.10.5, S-1.15.3; PR [#383](https://github.com/khoks/VideoResearchPro/pull/383); [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-066](#d-066--language-contract-temporal-awareness-and-corpus-aware-qa-length-2026-07-31), [D-067](#d-067--visual-understanding-separate-frames-table-marker-in-text-annotation-opt-in-per-job-2026-07-31), [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19).

## D-114 — Which sources a topic run searches: settings decide, one budget for the run, no Whisper before approval (2026-10-29)

**Status:** accepted (2026-10-29). Made while building S-1.5.13 (PR [#382](https://github.com/khoks/VideoResearchPro/pull/382)) and its review fixes, not ruled by the owner; the owner's go-ahead for the story is [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25). Point 4 was amended the same day by [D-115](#d-115--the-document-cap-counts-visible-documents-a-request-that-names-its-documents-is-all-or-nothing-and-nothing-is-granted-before-approval-2026-10-29): no candidate of any source type is granted before approval.

**Context.**
- `JobCreate` had no `source_types` field and nothing wrote `jobs.source_types_json`, so every topic run searched YouTube only, and the dispatch through `connector_dispatch` shipped in S-1.5.11 could not be reached from the API (the S-8.6.1 finding, [D-082](#d-082--job-templates-identity-plus-immutable-versions-provenance-without-a-foreign-key-starters-in-a-self-contained-data-migration-2026-10-19)).
- Wiring it up raised questions the connectors had left open: what a run that asks for an unconfigured source gets, how the tier cap applies to several sources, and when podcast audio may go to Whisper.

**Decision.**
1. **Settings decide which sources a run may search, and a source this install has not set up is refused with a 422 that names the missing setting.** `app/services/job_source_types.py` is the one place that knows. The searchable types are listed in code (`SEARCHABLE_SOURCE_TYPES`) and never read from the connector registry, because tests swap connectors in and out of it. Reddit needs `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`, web articles `BRAVE_SEARCH_API_KEY`, and X / Twitter `TWITTER_BEARER_TOKEN` ([D-009](#d-009--twitter--x-is-byok--opt-in-2026-04-25)). Unknown types, library-only types (`pdf`, `fb_post`, `ig_post`, `li_post`), an empty list and non-YouTube types on channel and subscription runs are refused too. The same check drives the `/health` flags (`reddit_search_enabled` is new) and the submit form.
2. **The YouTube-only default is stored as NULL, and a list is stored in canonical order.** This follows the `output_length` "auto → NULL" pattern. Responses always return the resolved list (`["video"]` by default).
3. **Template versions are compared as parsed parameters, not as stored JSON text,** so adding an optional field never creates a new version on an identical save. A template stores `source_types` normalised the way `JobCreate` normalises it.
4. **Dispatched non-video documents are granted visibility at search time**, to match the video branch. *Amended by D-115 point 5: the premise was wrong (video candidates were never granted at search time), and the grant let a mixed run past the document cap. Nothing is granted before approval.*
5. **`num_videos` is the whole run's budget, shared across its sources.** `job_source_types.share_limits` splits it as evenly as possible, with the remainder going to the earlier types in canonical order. The search agent gets YouTube's share, and each dispatched type is cut to its share even when its connector returns more. Asking for fewer results than sources is a 422. The tier cap therefore bounds the whole run.
6. **No Whisper before approval, for any source.** The search phase reads only text a source already publishes: connectors are called with `allow_whisper=False`, and an episode without an in-feed transcript is stored as `pending`. Whisper runs at extraction under `WHISPER_MAX_PER_JOB`, which now counts podcast episodes as well as YouTube videos.
7. **A dispatched document's search-time text is cached in `transcript_cache` keyed on `document_id`** (`video_id` NULL, [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19)) and reused at extraction, so each approved document is fetched, and for social sources classified, once. The extraction query joins approvals on `document_id`; the join on `video_id` had dropped every approved non-video document.

**Alternatives considered.**
- *Let an unconfigured source return zero candidates,* as the connector docstrings assumed. The run would look like a search that found nothing, and the user could not tell a missing key from an empty topic.
- *Read the searchable types from the connector registry.* Tests replace registry entries, so the API's answer would depend on test order.
- *Store the default as `["video"]`.* Existing jobs and templates would differ from new ones that mean the same thing.
- *Apply `num_videos` to each source.* A three-source run would get three times the tier cap.
- *Whisper at search time, as the podcast connector did.* It pays for episodes the user may reject at approval, outside the per-job budget ([D-033](#d-033--whisper-as-service-for-podcasts-reuse-existing-openai-whisper-path-resolves-oq-4-2026-05-03)).

**Consequences.**
- The multi-source dispatch shipped in S-1.5.11 is reachable from the API, the submit form, Duplicate and templates. X / Twitter is offered only when `/health` reports `twitter_search_enabled`, which closes T-1.5.9.3.
- A duplicated run or a template that names a source the install no longer has shows it struck through, and it must be removed before submitting; a saved template lists it as a problem.
- The non-video dispatch and the extraction-phase fetch run inside the submitter's BYOK context ([D-041](#d-041--contextvar-plumbing-vs-explicit-kwargs-for-cross-cutting-per-user-state-2026-05-05)).
- Mastodon and Bluesky are always offered: their base URLs have defaults, and a blank one is not treated as "not set up".
- No connector was checked live; they are faked in the tests.
- Follow-ups: S-8.6.3 and S-8.6.4 are unblocked; the job detail page does not show a run's sources yet; a per-job Whisper control (S-1.11.7) would now cover podcasts too; the Twitter reply fetch (T-1.5.10.3) is connector work.

**Linked initiatives / PRs.** E-1.5 (S-1.5.9, S-1.5.11, S-1.5.13), E-1.7, E-8.6 (S-8.6.1, S-8.6.3, S-8.6.4), S-1.11.7; PR [#382](https://github.com/khoks/VideoResearchPro/pull/382); [D-009](#d-009--twitter--x-is-byok--opt-in-2026-04-25), [D-020](#d-020--file-orchestrator-dispatch-as-standalone-story-s-1511-2026-04-26), [D-033](#d-033--whisper-as-service-for-podcasts-reuse-existing-openai-whisper-path-resolves-oq-4-2026-05-03), [D-041](#d-041--contextvar-plumbing-vs-explicit-kwargs-for-cross-cutting-per-user-state-2026-05-05), [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19), [D-082](#d-082--job-templates-identity-plus-immutable-versions-provenance-without-a-foreign-key-starters-in-a-self-contained-data-migration-2026-10-19), [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25), [D-115](#d-115--the-document-cap-counts-visible-documents-a-request-that-names-its-documents-is-all-or-nothing-and-nothing-is-granted-before-approval-2026-10-29).

**Status-changed 2026-11-04:** PR [#408](https://github.com/khoks/VideoResearchPro/pull/408) made the first live calls this entry says were not made, read-only. Bluesky answered 403 on `searchPosts`, and Hacker News and a Mastodon phrase returned nothing for a long topic, so those runs read as no results ([D-135](#d-135--the-publish-window-is-a-preference-that-leads-the-inferred-profile-a-window-that-cannot-act-is-refused-and-starters-name-only-sources-that-need-no-search-credential-2026-11-04), [S-1.5.14](initiatives.md#s-1514--sources-that-quietly-return-nothing)). The decision stands.

**Status-changed 2026-11-05:** the split stands, and a share a source cannot fill now moves. Non-video sources search before YouTube, YouTube takes a shortfall on its one search if the worst case fits the day's quota, and what YouTube cannot fill goes to sources with more ([D-141](#d-141--a-connectors-search-raises-on-failure-a-refusal-is-a-24-hour-hold-on-a-sources-own-endpoint-non-video-sources-search-before-youtube-and-a-recording-counts-once-2026-11-05), T-1.5.14.3, PR [#415](https://github.com/khoks/VideoResearchPro/pull/415)). `POST /jobs` still accepts a source the form holds off for 24 hours.

## D-115 — The document cap counts visible documents; a request that names its documents is all or nothing, and nothing is granted before approval (2026-10-29)

**Status:** accepted (2026-10-29). Made while building T-5.2.10 (PR [#385](https://github.com/khoks/VideoResearchPro/pull/385)) and its review fixes, not ruled by the owner. The ruling it carries out is [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25): the caps stay advertised and a later E-5.2 item enforces them. Point 5 amends [D-114](#d-114--which-sources-a-topic-run-searches-settings-decide-one-budget-for-the-run-no-whisper-before-approval-2026-10-29) point 4.

**Context.**
- `document_count_cap` (Free 500, Pro 5,000, Studio unlimited) was advertised on the pricing page and checked nowhere.
- `documents` is a shared, deduplicated cache ([D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)): one row can be visible to many tenants, and a tenant can see documents someone else caused to be created. What a cap counts is not obvious.
- Documents reach a tenant's library through job approval, PDF upload, pasted URLs, channel subscribe and sync, and subscription jobs. A sync cannot know in advance how many uploads it will add.
- The resume task that granted an approval's documents can wait hours behind other work on a solo worker.

**Decision.**
1. **The cap counts the tenant's visible documents** (their `document_visibility` rows), not the documents they created and not a metering counter. A dedup hit on a document the tenant already sees never counts. A cached document that only another tenant sees counts as new. `GET /auth/quota` reads `documents` usage from visibility.
2. **A request that names what it adds is all or nothing.** An approval counts only the approved documents the tenant cannot see yet; a paste batch counts each distinct, not-yet-visible URL once, before any page is fetched; an upload is checked before its bytes are written. If it does not fit, nothing changes (no approval flag, no task, no file, no fetch) and the refusal says how much room is left, so the user chooses what to drop.
3. **A sync names nothing in advance, so it is refused only when the library is already full.** Otherwise it stops at the cap: uploads the tenant already sees always pass, new ones are taken newest first, and the job's note says how many were left out. It fails with that note if nothing could be linked. The cap lives in `execute_subscription_job`, so any future scheduled sync behaves the same.
4. **Refusals are HTTP 429** in the `QuotaExceededError` shape every quota uses ([D-045](#d-045--quota-metering-enforce-before-record-after-success-2026-05-05)), with `resource: documents` plus `requested`, `available` and a `message` shown as is.
5. **Visibility is granted for approved links only, when a document is admitted.** An approval grants its approved set in the request; a sync grants each channel's admitted uploads as it links them, and a redelivered sync grants its earlier links before it reads the budget; the search phase grants nothing, for any source type. Deselected candidates are never granted. This amends D-114 point 4, whose search-time grant covered every candidate of a mixed run, video ones included, and so let any approval of such a run past the cap check.
6. **There is no backstop in `visibility_service.grant`.** A refusal there would come after the work is done and would hide finished work.

**Alternatives considered.**
- *Count the documents a tenant created, or a metering counter.* Dedup makes "created" depend on who ingested first, and a counter drifts from what the tenant can actually see.
- *Admit as much of a request as fits.* The server would choose which documents to drop; the user knows which ones matter.
- *Cap topic and channel job creation.* Their new documents are checked at approval, and refusing at creation would block runs made entirely of documents the tenant already has. The cost is that a full library still pays for the search step.
- *Grant in the resume task, as before.* The cap counts grants, so documents admitted but not yet granted would be invisible to the next check, and a second approval, paste or upload could pass the cap while the first resume waited.
- *A per-tenant lock.* Two requests in the same instant can still each pass the check; with every admission granted at once, sequential use cannot. Not worth a lock today.

**Consequences.**
- A refusal is shown where the action starts: above the approve button (the selection is kept), on the upload row, in the paste alert, under the subscribe and sync buttons, and in the Submit page's form. The global error toast shows the server's message and stays quiet for document-cap refusals. The Subscription page shows a usage line.
- A tenant over the cap after a downgrade keeps everything and can re-use it, but cannot add new documents.
- There is no way to free room, because there is no "remove from my library" feature; only a plan change raises a full library (T-5.2.11, proposed).
- Grants written before this change for deselected candidates are not revoked. An approved run cancelled before its resume keeps its grants. The paste check counts entries whose extraction may still fail, so it errs towards refusing.

**Linked initiatives / PRs.** E-5.2 (T-5.2.10, T-5.2.11), E-5.10, S-1.5.13; PR [#385](https://github.com/khoks/VideoResearchPro/pull/385); [D-045](#d-045--quota-metering-enforce-before-record-after-success-2026-05-05), [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19), [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25), [D-114](#d-114--which-sources-a-topic-run-searches-settings-decide-one-budget-for-the-run-no-whisper-before-approval-2026-10-29).

**Status-changed 2026-11-09:** an approval grants its documents once its resume task is queued, not before the dispatch, so an approval the task queue refused holds no place under the cap. A queued approval still counts at once ([D-155](#d-155--stored-exception-text-goes-through-error_summary-an-empty-whisper-answer-is-charged-a-refused-dispatch-fails-a-new-run-and-leaves-an-approval-waiting-and-a-start-the-queue-refused-uses-up-nothing-2026-11-09), T-5.2.17, PR [#430](https://github.com/khoks/VideoResearchPro/pull/430)).

## D-116 — OAuth links or creates an account only from a provider-verified email, and the link records it (2026-10-29)

**Status:** accepted (2026-10-29). Made while building T-5.4.10 (PR [#384](https://github.com/khoks/VideoResearchPro/pull/384)) and its review fixes, not ruled by the owner. It amends [D-042](#d-042--oauth-first-login-links-to-existing-user-by-email-2026-05-05) by adopting its option (B'), and replaces the narrower OAuth check in [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)'s consequences, which covered only `ADMIN_EMAILS` addresses and counted GitHub's public email as verified.

**Context.**
- D-042 links a first OAuth sign-in to an existing account by email, trusting both providers to verify the address by construction. Its re-evaluation hook said to add an `email_verified` check for any provider that did not.
- T-5.2.8 (PR [#377](https://github.com/khoks/VideoResearchPro/pull/377)) added that check only for addresses in `ADMIN_EMAILS`. Any other existing account could be reached by an OAuth identity that reported the same address unverified.
- GitHub's `/user` email was counted as verified on the understanding that GitHub only lets a verified address be public. `GET /user/emails` reports verification directly, so there is no need to assume it.

**Decision.**
1. **A first OAuth link, or a new OAuth account, needs a provider-verified email**; otherwise the sign-in is refused and nothing is linked or created. Google: the OIDC `email_verified` claim, with a missing claim counting as unverified. GitHub: the primary address in `GET /user/emails` with `verified: true`. The `/user` public email is never trusted, and there is no fallback to a verified address that is not the primary.
2. **The refusal is a 403 with a plain message**, not [D-040](#d-040--failed-logins-for-unknown-emails-do-not-create-user-rows-lock-arbitrary-account-defence-2026-05-04)'s generic 401. It is a policy refusal after the provider has authenticated the user, and the user needs to know what to do next. It is audited as `login_failure` with `reason: oauth_email_unverified`. Every other callback failure is still the generic 401.
3. **The check runs before any account lookup, and the message is the same whether or not an account has the address,** so the refusal cannot be used to find out which addresses are registered.
4. **A failed `/user/emails` lookup is unknown, not unverified.** An outage, a rate limit, a timeout or an answer with no primary address gives a first sign-in the generic, retryable 401 (audited `oauth_failure`). A returning user, matched by provider id, is unaffected, including when the lookup fails.
5. **The link records the verification** in a new nullable column, `oauth_identities.email_verified_at`, set when an identity is linked (migration `066d3f4b4d4d`). NULL marks identities linked before T-5.4.10.
6. `user:email` has been in the GitHub scope since T-5.4.5, so existing GitHub sign-ins need no fresh consent; a test pins the scope.

**Alternatives considered.**
- *Keep the check for `ADMIN_EMAILS` addresses only.* Every other existing account stays reachable from an unverified address.
- *Keep trusting GitHub's public `/user` email.* Nothing in that response says the address was verified, and `/user/emails` does.
- *Treat a failed lookup as unverified (403).* An outage would tell users whose address may well be verified to go and verify it, and would fill the audit log with policy refusals.
- *A confirmation-email round trip before linking (D-042's option C).* An extra step on a one-click flow; still out of scope.
- *Re-check or revoke identities linked before this change.* There is no record of whether they were verified, and revoking could lock out real users.

**Consequences.**
- No frontend change: the app has no OAuth sign-in UI yet, so the 403 message is for whichever client shows it. `docs/api-reference.md` documents the three OAuth endpoints.
- Identities linked before T-5.4.10 still sign in. An operator who is worried can look for rows with `email_verified_at` NULL, or for `login_success` events with `via: oauth` on accounts first registered with a password.
- **Open risk, the verified direction:** `POST /auth/register` verifies no email. Someone can register a password account with another person's address before that person uses the app. When the real owner later signs in with a verified Google or GitHub address, the identity links to that account and the registrant keeps the password. Two remedies were named, and choosing needs the owner: OAuth never links automatically to an existing password account; or, when it links, the account's password is cleared and its sessions are revoked (the reset flow, which proves the address, sets a new one; this ends password sign-in for people who registered honestly and then add Google). Filed as T-5.4.11. **Deferred by the owner on 2026-11-03** with email verification as a whole ("keep email verification for later"); the risk stays open until then.
- The live database needs migration `066d3f4b4d4d`, which `schema_init` applies at startup. Applied on 2026-11-03, when the owner's services were restarted on master.

**Linked initiatives / PRs.** E-5.4 (T-5.4.5, T-5.4.10, T-5.4.11), E-5.2 (T-5.2.8); PR [#384](https://github.com/khoks/VideoResearchPro/pull/384); [D-040](#d-040--failed-logins-for-unknown-emails-do-not-create-user-rows-lock-arbitrary-account-defence-2026-05-04), [D-042](#d-042--oauth-first-login-links-to-existing-user-by-email-2026-05-05), [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25).

## D-117 — The caption track is the one in the spoken language; auto-dubs are read from the player's audio tracks (2026-10-29)

**Status:** accepted (2026-10-29). Made while building S-1.11.11 (PR [#386](https://github.com/khoks/VideoResearchPro/pull/386)), not ruled by the owner: first drafted 2026-10-25 and revised in review on 2026-10-29 with the three-signal order below. It departs from the brief's literal order (see the first alternative), which the owner may want to confirm (OQ-18 on the board, under S-1.11.11).

**Context.**
- `_fetch_transcript_once` tried `en` / `en-auto` and then took the first listed track. YouTube auto-dubs videos into other languages, and each dub's caption track is listed beside the original's. The S-1.16.2 held-out evaluation found 2 of 13 Hindi-speech videos ingested as machine-dubbed tracks: `1v3_AQ26jZ0`, a Hindi lecture, was in the library as a Bengali dub. An English dub is undetectable downstream, so every quote from it is words the speaker never said.
- Measured before fixing ([note](notes/2026-10-25-caption-track-choice.md)), on 37 Hindi, Hinglish and Kannada library videos, for 1 quota unit:
  - Dubs show up only in the player response that `youtube-transcript-api` already fetches and then discards. The original audio track is `<lang>.4`, each dub is `<lang>.10`, and a dub's caption track carries exactly the dub's code.
  - `v6CuYULP3tM`, one of the two known dubs, declares no `defaultAudioLanguage`. Only its `hi.4` audio track says the speech is Hindi.
  - `IcVYyF3EEbk` has a real `en` track beside an `en-US` dub, so a dub has to be matched on its exact code.
  - The old and new rules disagree on 7 of the 35 videos that could be listed: 5 auto-dubs, 1 creator's English translation of Hindi speech, and 1 manual track preferred over an automatic one.

**Decision.**
1. **The spoken language is the first of three signals that some non-dub track is in:**
   1. `snippet.defaultAudioLanguage`, looked up lazily (1 unit, `videos.list`): at most once per fetch, and only when the non-dub tracks span more than one language;
   2. the player's original audio track (`<lang>.4`, or the default track when there is no `.4`);
   3. on a single-audio video, the language of its automatic (ASR) track.

   A signal with no track in its language is passed over, not taken as the answer. `snippet.defaultLanguage` is never a speech signal.
2. **An auto-dub is an automatic track whose code exactly equals a non-original audio track's code,** and it is dropped.
3. **Within the spoken language, a manual track beats an automatic one.** The old English-first fallback applies only when all three signals come up empty.
4. **A list of nothing but dubs is refused, never ingested.** The fetch is not retried and goes to Whisper, or the video is recorded unavailable when the Whisper budget is spent.
5. The chosen track is recorded on `documents.source_metadata_json["caption_track"]`: its language, manual or automatic, why it was chosen, the declared audio language and the dubs skipped. No migration.
6. **Accepted risk:** dub detection reads two `youtube-transcript-api` internals (`_fetcher._fetch_captions_json`, `_fetcher._http_client`). A test pins them, and if they move the code falls back to the public `list()` without dub detection.

**Alternatives considered.**
- *The brief's literal order: take `defaultAudioLanguage` from the Data API for every video.* It misses `v6CuYULP3tM`, which declares nothing; it fails when the quota is spent; and it costs a unit for every video, where the measured sample needed one for 2 of 35.
- *Recognise a dub by its language rather than its exact code.* Treating an `en-US` dub as covering every English track would have thrown away `IcVYyF3EEbk`'s only real track, its `en` automatic track. Tracks that are not dubs are still matched to the spoken language on the primary subtag, so a regional English track counts as English once the dubs are gone, which is what T-1.11.11.1 asked for.
- *Trust a declaration that has no track in its language.* A declared `ur` with no Urdu track would have sent the fetch to English-first and a creator's translation, though the original audio's `hi` track was there.
- *Take a dub when nothing else exists.* An English dub of Hindi speech puts words in the speaker's mouth; Whisper on the real audio does not.

**Consequences.**
- New fetches never ingest an auto-dub. On the 35 measured videos, the review's signal order changes no chosen track, only the recorded reason.
- When this shipped, three library documents held dubbed transcripts: `1v3_AQ26jZ0` (Bengali dub of Hindi), `5AuuOZ4vuxI` (Bengali dub of Hindi) and `v6CuYULP3tM` (`en-US` dub of Hindi); none had a knowledge report. `scripts/refetch_dubbed_transcripts.py --write` replaces them. It is an owner step on live data, and re-embedding their Hindi chunks makes paid `code_mixing_render_english` calls ([D-084](#d-084--code-mixed-retrieval-embed-an-english-rendering-keep-the-original-as-the-stored-text-2026-10-19)) while `CODE_MIX_ENGLISH_RENDERING_ENABLED` is on. Its dry run, the default, writes nothing and is paced per [D-051](#d-051--transcript-pipeline-resilience-bundle-circuit-breaker--segmented-whisper--yt-dlp-client-fallback-2026-07-22). The owner ran `--write` on 2026-11-03 and re-fetched all three (T-1.11.11.3).
- A judgement call left as it is: `9tigHWH-UD8` declares `en`, so its manual English track is taken although YouTube's recogniser heard Hindi. On Hinglish speech both are plausible (OQ-19 on the board, under S-1.11.11).
- Not in the sample, and both fail safe to Whisper: creator-uploaded multi-language audio, and a dub whose code equals the original's automatic track's code.
- Passing `get_video_details`' `defaultAudioLanguage` through to `fetch_transcript` would save the lazy lookup (T-1.11.11.4, proposed).

**Linked initiatives / PRs.** E-1.11 (S-1.11.11), E-1.16 (S-1.16.2, T-1.16.2.6); PR [#386](https://github.com/khoks/VideoResearchPro/pull/386); [D-051](#d-051--transcript-pipeline-resilience-bundle-circuit-breaker--segmented-whisper--yt-dlp-client-fallback-2026-07-22), [D-066](#d-066--language-contract-temporal-awareness-and-corpus-aware-qa-length-2026-07-31), [D-080](#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19), [D-084](#d-084--code-mixed-retrieval-embed-an-english-rendering-keep-the-original-as-the-stored-text-2026-10-19).

**Status-changed 2026-11-05:** `defaultAudioLanguage` now travels from `get_video_details` onto the document, at `source_metadata_json["default_audio_language"]`, and into `fetch_transcript`, so a video that declares one needs no lazy lookup ([D-144](#d-144--a-fifth-voice-label-other-names-no-language-to-write-in-a-job-fills-gaps-and-only-the-backfill-rewrites-and-the-declared-audio-language-is-a-key-on-the-document-2026-11-05), T-1.11.11.4, PR [#418](https://github.com/khoks/VideoResearchPro/pull/418)).

## D-118 — A provider key is stored only for a provider a call reads it for; the settings report the encryption key's state, never the key (2026-11-04)

**Status:** accepted (2026-11-04). Made while building the BYOK keys panel and the system status page (S-5.6.1, PR [#388](https://github.com/khoks/VideoResearchPro/pull/388)) and its review fixes, not ruled by the owner.

**Context.**
- E-5.6 shipped per-user provider keys in May 2026 with no UI. `byok_service.SUPPORTED_PROVIDERS` listed `openai`, `anthropic`, `google` and `local`, but `llm_service` reads a stored key only for the first three: the local endpoint is install-wide (`LLM_LOCAL_BASE_URL` / `LLM_LOCAL_API_KEY`). A panel built on `SUPPORTED_PROVIDERS` would have offered a key no call reads.
- `PUT /auth/credentials/{provider}` checked the key's length with a pydantic `max_length`. FastAPI's 422 body carries the rejected value as `input` (confirmed on the pinned version), so an over-long key was sent straight back.
- Without `BYOK_ENCRYPTION_KEY`, each process makes its own temporary Fernet key ([D-043](#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05)). A key saved through the API cannot be read by the Celery worker, so search and report runs quietly use the install's key, and every saved key is lost at the next restart. A malformed key turned every save into a bare 500.
- The health endpoints (`/health/llm`, `/health/scheduler`, `/health/quota`) are public and had no viewer in the app. The restart endpoint is operator-only ([D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)).

**Decision.**
1. **A stored key is accepted only for a provider a call reads it for.** `byok_service.RESOLVED_PROVIDERS` (openai, anthropic, google) is the one list. `llm_service._resolve_byok_api_key` reads it, `GET /settings/llm` reports it as `byok.providers`, `GET /auth/credentials/providers` returns it, and `PUT` refuses any other provider with a 400. `local` stays in `SUPPORTED_PROVIDERS` for `DELETE` only, so an old row can still be removed; the panel shows such a row as "Not used".
2. **The settings report the encryption key's state as two booleans, never the key or any part of it:** `byok.keys_persist` (true only for a valid Fernet key) and `byok.key_invalid` (set but malformed), from `byok_service.encryption_key_state()`. Unset: saves work until a restart, and the worker cannot read them. Malformed: no save works, and `PUT` answers 503 with a detail that names the cause and quotes neither key. The panel says which, and turns saving off while the key is malformed; Remove still works.
3. **A credential secret is length-checked in the handler, never by a pydantic constraint,** because FastAPI's 422 echoes the rejected `input`. An over-long key gets a 400 that does not quote it.
4. **The browser sends a secret with a direct call, not a React Query mutation, and empties the field at submit,** so the key never sits in the mutation cache, a toast or the console. The key field is `autocomplete="one-time-code"` and sits in no `<form>`, so browser password managers do not offer to save it.
5. **The system status page is open to every signed-in user,** since the health endpoints it reads are already public. The restart control renders only for operators (`is_operator`), and `require_operator` on the server stays the enforcement.

**Alternatives considered.**
- *Store a `local` key and ignore it.* A silently ignored key is exactly the drift a shared constant exists to prevent.
- *Report the key's state as one flag.* "Keys do not persist" would read the same for an unset and a malformed key, which need different fixes.
- *`autocomplete="new-password"`,* the review's suggestion. It is the sign-up signal: Chromium offers its password generator on focus and is more eager to offer saving.
- *A "verify key" button.* The API has no verify call, and one would make a paid provider request with the user's key (T-5.6.8, proposed).
- *Restrict the health endpoints in the same change.* Outside this item; asked of the owner as OQ-21.

**Consequences.**
- A Studio user can add, replace and remove their keys on `/account/ai-models`. Free and Pro see what the plan adds and never call `/auth/credentials`.
- Until the owner sets `BYOK_ENCRYPTION_KEY` (T-5.6.7), the panel warns that saved keys do not last and that background work cannot read them.
- Other paths that encrypt with the same shared key, MFA enrolment among them, may still answer a malformed key with a bare 500 (T-5.6.9, proposed). The Echo connector sync already handles it (T-3.2.1.10).
- Headless tests cannot see a browser's "Save password?" prompt; the owner checks it once by hand.

**Linked initiatives / PRs.** E-5.6 (S-5.6.1, T-5.6.7 to T-5.6.9), E-5.2 (T-5.2.8); PR [#388](https://github.com/khoks/VideoResearchPro/pull/388); [D-041](#d-041--contextvar-plumbing-vs-explicit-kwargs-for-cross-cutting-per-user-state-2026-05-05), [D-043](#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05), [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25).

**Status-changed 2026-11-05:** the verify action this entry left out shipped as **Verify key** ([D-146](#d-146--a-pool-never-carries-the-session-max_concurrent_jobs-is-per-user-a-key-check-says-good-or-bad-only-when-the-provider-did-and-whispers-key-and-count-hold-on-every-sync-2026-11-05), T-5.6.8, PR [#417](https://github.com/khoks/VideoResearchPro/pull/417)).

## D-119 — Usage is metered at a scope that names the tenant, and written in a session of its own (2026-11-04)

**Status:** accepted (2026-11-04). Made while building per-user usage recording (S-5.2.1, PR [#391](https://github.com/khoks/VideoResearchPro/pull/391)) and its review fixes, not ruled by the owner. It records usage and enforces nothing new, as [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25) ruled when it dropped the daily-token line from the pricing page.

**Context.**
- Tokens were recorded per user only on the job Q&A path (T-5.2.7) and in suggestions, each by hand. YouTube Data API units were recorded install-wide only (`api_quota_log`). Every other feature spent without a record.
- Every LLM call goes through `llm_service.get_llm_for` for a named use case, and every YouTube request through `quota_service.record`. Many entry points share use cases: library Q&A calls the job-Q&A sub-query and reference use cases.
- The meter runs inside the work it measures: routers, services and Celery tasks with their own sessions and transactions, some of which flush and later roll back.
- `report_agent.map_chunks` runs batches on a thread pool (S-1.14.19). A pool thread starts with an empty context, so the ContextVars of [D-041](#d-041--contextvar-plumbing-vs-explicit-kwargs-for-cross-cutting-per-user-state-2026-05-05) did not reach those batches.

**Decision.**
1. **Usage is metered at a scope that names the tenant, not at each call site.** `usage_service.metered(db, tenant_id, feature=None)` opens one, and `llm_service.byok_context` opens one too, so every path that already set the BYOK context is metered with no extra line. `get_llm_for` attaches a LangChain callback to each client it builds, which adds the call's reported tokens and one call to the open scope; `quota_service.record` adds each YouTube request's units. Nested scopes for the same tenant share one ledger.
2. **A call is charged to its use case's feature** (`USE_CASE_FEATURES`, which covers the whole registry; a test enforces it), **unless an entry point that shares use cases names one, and then the outermost named feature wins.** Library Q&A names `library_qa`; a saved-search run names `saved_search`.
3. **YouTube units are grouped by the kind of call:** `youtube_search` ("Searches (YouTube)") for every `search.list`, `video_metadata` and `channel_sync`. `search.list` is kept apart from the `search` feature (the topic planner's and curator's model calls), because channel jobs and subscription syncs also call it to resolve a channel typed by name.
4. **The meter writes through a session of its own and never commits or rolls back the caller's.** When the caller's open transaction has already written (seen by session events, and on SQLite by the connection's own transaction state, which also catches bulk and raw-connection writes), the write waits until that transaction ends by commit, rollback or close. Usage spent on work that is then rolled back is still recorded, because it was spent. Metering never raises into the work it measures.
5. **Daily totals go to both tables:** one row per (tenant, UTC day, feature, metric) in `usage_records` (migration `6cf03630d943`), and the matching `quota_usage` totals, so `GET /auth/quota` and `record_usage` keep their meaning and now count every feature. The hand-written token recording in the job Q&A router and `suggestion_service` is removed, so nothing is counted twice.
6. **Concurrent report map batches run in a copy of the caller's context** (`_map_in_context`). Since S-1.14.19 they had ignored the user's BYOK key and model overrides.

**Alternatives considered.**
- *A tally threaded through every agent,* the job-Q&A pattern. It covers only the paths someone remembered, and double-counts when a second path is added.
- *Charge YouTube units to the action that made them.* A channel resolve inside a subscription sync would read as a topic search.
- *Write on the caller's commit (`before_commit`) inside a SAVEPOINT.* Usage is lost whenever the caller ends without another commit, as a Celery task that raised and closed its session does, and a savepoint still writes inside the caller's transaction.
- *Commit the caller's session when it has nothing pending,* the first draft. Review showed it could commit or roll back part of the caller's work.
- *Derive the daily totals from `usage_records`.* It would change `/auth/quota`'s semantics and its tests for no gain.

**Consequences.**
- `GET /api/v1/usage` returns the caller's own usage, today and over the last 30 UTC days, by feature. The Subscription page shows it with a note that nothing there is limited, and says when recording started while that date is inside the window.
- Not recorded: Whisper audio minutes (billed per minute, outside LangChain; T-5.2.12, proposed), embeddings (local), startup probes and operator scripts, and tokens from local models that report none (their calls are counted). Per-job spend stays T-5.2.7's deferred item.
- A task's usage is written when the task ends, so a worker that dies mid-run loses that run's usage (T-5.2.13, proposed).
- On a database other than SQLite, writes made around the session (bulk saves, the raw connection) are not seen by the session events. On Postgres that risks a lock wait, never committing the caller's work, since the meter has its own connection. A ledger deferred on a session that closes without ever starting a transaction is lost; this is rare.
- The job and library clarify endpoints are now metered but never open `byok_context`, so they still use the install's key (T-5.6.10, proposed).

**Linked initiatives / PRs.** E-5.2 (S-5.2.1, T-5.2.7, T-5.2.12, T-5.2.13), E-5.6 (T-5.6.4, T-5.6.10), S-1.14.19; PR [#391](https://github.com/khoks/VideoResearchPro/pull/391); [D-041](#d-041--contextvar-plumbing-vs-explicit-kwargs-for-cross-cutting-per-user-state-2026-05-05), [D-045](#d-045--quota-metering-enforce-before-record-after-success-2026-05-05), [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25).

**Status-changed 2026-11-05:** two "not recorded" items are closed: Whisper audio is recorded, and a long task writes part-way ([D-131](#d-131--whisper-is-charged-at-the-shared-call-and-usage-is-written-part-way-on-a-timer-after-every-billed-response-2026-11-04), T-5.2.12, T-5.2.13, PR [#405](https://github.com/khoks/VideoResearchPro/pull/405)). The clarify endpoints now open `byok_context` ([D-138](#d-138--code-attempts-count-on-a-shared-row-sockets-end-with-their-session-one-reader-takes-the-client-address-from-the-right-and-a-rotated-key-is-reported-2026-11-05), T-5.6.10, PR [#411](https://github.com/khoks/VideoResearchPro/pull/411)).

## D-120 — Older chunks gain their era and publish fields by a metadata-only pass (amends D-072); the language profile is stored on the document (2026-11-04)

**Status:** accepted (2026-11-04). Made while building T-1.16.1.7 and S-1.17.3 (PR [#390](https://github.com/khoks/VideoResearchPro/pull/390)) and its review fixes, not ruled by the owner. Point 1 amends [D-072](#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19) point 2's "no backfill", as [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25) allowed S-1.17.3 to do.

**Context.**
- D-072 left chunks embedded before R3 (2026-10-19) without `era_*`, `published_ts` and `published_year`, so they read as unknown. It rejected a backfill because it "would re-embed the whole library for a metadata field". A document gains its era the next time a job re-chunks it, but its old chunks in Chroma do not.
- Chroma updates metadata without re-embedding. `backfill_chunk_document_ids` ([D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19)) already does exactly that at every startup.
- Measured on a read-only snapshot of the live library: 5,549 of 8,567 chunks lack the publish fields and 5,111 lack the era.
- The per-document language profile (`code_mixing_service.profile_transcript`, S-1.16.2) lived only on chunks, as `code_mix_*`. Documents chunked before S-1.16.2 had it nowhere, and a page could show only the caption-track label, which reads `en` for romanised Hinglish.

**Decision.**
1. **Chunks no longer stay unknown for good.** An owner-run, metadata-only pass (`scripts/backfill_chunk_temporal_fields.py`) brings existing chunks up to the era and publish fields the chunker writes today, through the chunker's own functions (`temporal_service.era_metadata`, `chunking.published_numeric_fields`, `chunking.published_at_field`). Unknown fields are still omitted, never sentinels. Nothing is removed and nothing is re-embedded.
2. **The pass sends each chunk's whole metadata back,** re-read just before the update, so `document_id`, `code_mix_*`, `text_en` and the timestamps survive whether the store merges (Chroma 1.5.5 does, probed) or replaces.
3. **A chunk's `published_at` display string moves with its numeric twins** (a review fix). Whenever the pass writes `published_ts` / `published_year` it writes the matching `published_at`, compared as an instant, so the date the prompts show and the one a range filter reads never disagree.
4. **It stays owner-run, a dry run by default, idempotent and resumable,** not a startup hook. A failed batch stops the pass and a re-run resumes.
5. **`documents.language_mix` holds the full `profile_transcript` result as JSON text** (migration `0253eef57358`, the `discussed_era_json` convention). It is recomputed from the speech segments at every chunking and written only when it changes, so it follows a re-fetched transcript. The chunk `code_mix_*` fields are derived from the same profile (`chunk_transcript(language_profile=...)`), which keeps visual annotations out of it. `scripts/backfill_language_mix.py` profiles older documents from `transcript_cache`, else from their chunks put back together ([D-113](#d-113--knowledge-text-for-any-source-the-transcript-cache-else-the-documents-chunks-put-back-together-2026-10-29)), with no LLM.
6. **The API's `language_mix.code_mixed` describes the measured text, not the stored chunks** (a review clarification). A document chunked before S-1.16.2 and profiled since can read true while its chunks carry no `code_mix_*` until it is re-chunked. The OpenAPI description says so.

**Alternatives considered.**
- *Keep D-072's no-backfill rule.* Its reason was the cost of re-embedding, which a metadata update does not incur, and two thirds of the library's chunks would never range-filter by date.
- *Send only the new fields and rely on Chroma merging.* Correct on 1.5.5, but a store that replaces would lose `code_mix_*` and `text_en`; a test runs against one.
- *A startup hook, like the `document_id` backfill.* The pass reads every chunk's metadata and should run while no job is ingesting, so the owner runs it.
- *Compute the profile once per document and reuse it.* It would keep describing a dub after the transcript was re-fetched (S-1.11.11).
- *Rename `code_mixed`.* The name is right for the words, and nothing renders it yet.

**Consequences.**
- Owner steps: apply migration `0253eef57358` (a restart does), then, with no job ingesting, run each script's dry run and then `--write`. The snapshot counts above were taken before the `published_at` fix, so the owner's dry run will print one more field.
- On an R1 visual run (parked, [D-109](#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25)), chunk `code_mix_*` now comes from the speech alone. Every other run's chunks are byte-identical, which a test pins.
- `language_mix` is a read-only field on the library, job and channel video listings; nothing renders it yet (T-1.16.1.9, proposed).
- A job that reuses an embedded document and extracts its era for the first time does not stamp the old chunks; they wait for the next run of the script (T-1.17.3.3, proposed).
- Stamping the document-level `code_mix_*` onto chunks written before S-1.16.2 is a separate decision, since those chunks would still be embedded as their original text ([D-084](#d-084--code-mixed-retrieval-embed-an-english-rendering-keep-the-original-as-the-stored-text-2026-10-19)) (T-1.16.2.14, proposed).

**Linked initiatives / PRs.** E-1.16 (T-1.16.1.7, T-1.16.1.9, T-1.16.2.14), E-1.17 (S-1.17.3, T-1.17.3.3, OQ-20), S-1.11.11; PR [#390](https://github.com/khoks/VideoResearchPro/pull/390); [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19), [D-072](#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19), [D-080](#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19), [D-084](#d-084--code-mixed-retrieval-embed-an-english-rendering-keep-the-original-as-the-stored-text-2026-10-19), [D-109](#d-109--r1-is-parked-visual-analysis-stays-hidden-its-measurement-stops-the-code-stays-2026-10-25), [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25), [D-113](#d-113--knowledge-text-for-any-source-the-transcript-cache-else-the-documents-chunks-put-back-together-2026-10-29).

**Status-changed 2026-11-04:** migration `0253eef57358` is applied. OQ-20 is answered: the services read `pratidhvani_global`, and both scripts write it. Dry runs on the live store would store 254 language profiles and update 5,549 of 8,567 chunks; the `--write` runs wait for the owner. `language_mix` is now rendered ([D-123](#d-123--unused-read-routes-are-removed-an-outputs-sources-list-groups-by-source-and-a-language-badge-names-a-language-only-on-evidence-2026-11-04)).

**Status-changed 2026-11-04:** T-1.17.3.3 and T-1.16.2.14 shipped in PR [#403](https://github.com/khoks/VideoResearchPro/pull/403) ([D-133](#d-133--the-tagger-abstains-without-hindi-evidence-the-presence-floor-reads-grammar-an-offline-lexicon-sees-english-in-devanagari-and-scores-are-quoted-from-the-production-row-2026-11-04)). A job that extracts an era for the first time stamps the document's stored chunks, and `scripts/backfill_chunk_language_fields.py` stamps `code_mix_*`; those chunks stay embedded as their original text. **The order changed:** `backfill_language_mix.py --write` must run with the new tagger, and the chunk pass follows it ([S-1.16.2](initiatives.md#s-1162--proportion-driven-rendering-for-code-mixed-speech--implements-n-002)). Both `--write` backfills still wait on the owner.

## D-121 — Reset codes never appear in a response, two-step verification guards every sign-in, and tokens say what they are (2026-11-04)

**Status:** accepted (2026-11-04). Made while building the account security page (S-5.4.1, PR [#389](https://github.com/khoks/VideoResearchPro/pull/389)) and its review fixes, not ruled by the owner. Point 1 supersedes T-5.4.8's self-host `debug_secret` handoff.

**Context.**
- E-5.4's backend (audit log, password reset, OAuth, TOTP, sessions) shipped in May 2026 with no UI. Building the UI made several older server paths reachable from the app for the first time.
- `POST /auth/password-reset/request` returned the reset secret as `debug_secret` whenever SMTP was unset (T-5.4.8). The route needs no sign-in, so on any install without SMTP anyone who knew an address could reset that account's password, and the field's presence revealed which addresses had accounts.
- The OAuth callback issued a full session even when the account had two-step verification on.
- The second-factor ticket from `/auth/login` (T-5.4.6) was signed with the access-token key, and `_resolve_user` took any token `decode_token` accepted. For its five minutes the ticket worked as an access token, so two-step verification could be skipped by never sending the code. Found in review.
- `audit_log` holds account events and product analytics (suggestion impressions and clicks, onboarding milestones, Echo drafts), and the analytics are written far more often.
- Session rows are never deleted, so `GET /auth/sessions` listed every sign-in since the account was made as if it were live.

**Decision.**
1. **A password-reset secret never appears in an API response.** The response is the same message with or without SMTP, and for known and unknown addresses. With SMTP unset, the operator reads the code from the server log, where `email_service`'s log fallback already wrote it. The email names the bare `{APP_BASE_URL}/reset-password` page; the code is in no URL.
2. **Two-step verification guards every sign-in path, OAuth included.** A provider sign-in to an account with TOTP on gets the same five-minute ticket and second step as a password sign-in.
3. **Tokens say what they are.** Access tokens carry `typ: "access"` and the ticket `typ: "mfa_step"`. Every bearer check (`_resolve_user`, `get_current_jti`, the `/ws/jobs` handshake) decodes through `auth_service.decode_access_token`, which refuses a token with `mfa_step` set or any other `typ`. The ticket authenticates nothing but `/auth/login/mfa`. A token with no `typ` is still accepted when it has no `mfa_step`, so the deploy signs no one out.
4. **The account view of the audit log reads an inclusion list** (`audit_service.ACCOUNT_EVENTS`, behind `GET /auth/audit-log?scope=account`), so an event added later stays out of the security view until someone classifies it. The default `scope=all` is unchanged.
5. **A session is active when it is neither revoked nor expired.** `GET /auth/sessions` returns `active` and `expires_at` (`created_at + JWT_EXPIRY_HOURS`, which is how tokens are issued), and the page lists only active sessions.

**Alternatives considered.**
- *Return the secret only on a single-account install.* The route is still unauthenticated, so anyone who knows or guesses the one address could take the account, and the field would still reveal that the address exists.
- *A separate signing key or audience for the ticket.* Two places to check; one decoding helper is one.
- *Require `typ` on every token at once.* It would sign out every session issued before the deploy.
- *An exclusion list of analytics events.* Every new analytics event would show in the security view until someone excluded it.

**Consequences.**
- `/account/security` lists active sessions and signs out one or all the others, sets up and turns off two-step verification, links to the reset flow and pages through account activity. Sign-in asks for the second factor or a recovery code, and shows OAuth buttons only for providers the install has set up. There is no QR code: no QR library is a dependency, so setup shows the key and the `otpauth://` link to copy.
- Owner steps: restart the backend; set `APP_BASE_URL` to the frontend's public origin so the reset email's link is right; on an install without SMTP, a reset code is only in `.uvicorn.*.log` ("Password reset request"); the OAuth buttons need `OAUTH_GOOGLE_*` / `OAUTH_GITHUB_*` and the redirect URI `<frontend origin>/login/oauth/<provider>/callback` registered with each provider.
- Left open, all proposed: a reset leaves the account's other sessions alive (T-5.4.12); `/auth/login/mfa` has no per-ticket attempt cap (T-5.4.13); there is no password change while signed in (T-5.4.14); the `/ws/jobs` handshake refuses the ticket but does not check whether an access token's session was revoked, a gap older than this PR (T-5.4.15). Email verification stays deferred with T-5.4.11.

**Linked initiatives / PRs.** E-5.4 (S-5.4.1, T-5.4.3, T-5.4.5 to T-5.4.8, T-5.4.11 to T-5.4.15); PR [#389](https://github.com/khoks/VideoResearchPro/pull/389); [D-040](#d-040--failed-logins-for-unknown-emails-do-not-create-user-rows-lock-arbitrary-account-defence-2026-05-04), [D-042](#d-042--oauth-first-login-links-to-existing-user-by-email-2026-05-05), [D-043](#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05), [D-116](#d-116--oauth-links-or-creates-an-account-only-from-a-provider-verified-email-and-the-link-records-it-2026-10-29).

**Status-changed 2026-11-04:** T-5.4.12 to T-5.4.15, the four items left open here, shipped in PR [#399](https://github.com/khoks/VideoResearchPro/pull/399) ([D-124](#d-124--second-factor-attempts-count-on-the-ticket-one-bearer-check-for-http-and-the-socket-and-a-validation-error-never-quotes-what-was-sent-2026-11-04)).

## D-122 — A deleted derived fact stays deleted per connector; only a refused refresh asks for a reconnect; restore re-checks the evidence (2026-11-04)

**Status:** accepted (2026-11-04). Made while building T-3.2.4.4, T-3.2.2.5 and T-3.3.1.6 (PR [#392](https://github.com/khoks/VideoResearchPro/pull/392)) and its review fixes, not ruled by the owner. Point 1 carries out [D-110](#d-110--echo-only-sees-what-the-user-hands-it-no-background-capture-and-the-echo-scope-rulings-2026-10-25) item 2.

**Context.**
- D-110 ruled that a fact the user deleted stays deleted, for every connector. The nightly GitHub sync upserted derived facts by kind and key, so a forgotten "Python (GitHub)" came back, and re-importing an export did the same.
- Google's access tokens last an hour. The runtime stored `refresh_token` and `expires_at` but had no refresh step, so the Google connectors (S-3.2.2, S-3.2.5, still blocked on the owner's OAuth client) could not sync past the first hour. GitHub's tokens do not expire.
- "That's not me" on a voice signal could not be undone: re-adding the signal was refused with a 422, and extraction dropped it.
- `withdraw_source`, `withdraw_sources` and `withdraw_missing_events` skipped rejected signals, so a rejected signal kept the exact words of a share or event the user had since deleted. The delete paths drop the ledger row at once, so nothing cleaned them later.

**Decision.**
1. **Tombstones (`echo_fact_tombstones`, migration `a68953e57c63`) are keyed on the connector or importer name, the kind and the key,** not on the fact's source string, so they cover a re-import of the same kind of export as well as a re-sync.
   - They are recorded only when the user deletes a derived fact: one at a time (`echo_service.delete_context`) or a whole source (`revoke_source`, through `DELETE /echo/sources/{source}`). A fact the user typed gets none.
   - They are not recorded on disconnect, import undo or share delete, which remove what a source brought in rather than saying a fact is wrong.
   - They survive a disconnect and reconnect, and the deleted value is not kept.
   - The connector sync (`_store_facts`) and the export importer skip tombstoned keys. The user clears one with "Allow again".
   - The table is in `ECHO_TABLES`, so the brain export carries it and the full delete erases it ([D-089](#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19)).
2. **Token refresh is an optional protocol beside `ActivityConnector`** (`RefreshableConnector.refresh_tokens`), so a connector whose tokens never expire still meets the contract. `run_sync` renews a token that has expired or expires within 60 s, before calling the provider. The new token is stored encrypted, and the stored refresh token is kept when the provider returns none.
3. **Only a refusal asks the user to reconnect.** `invalid_grant` (`ConnectorError(auth=True)`), a missing refresh token, or a connector that cannot refresh marks the grant with `RECONNECT_PREFIX`. A transient refresh failure is an ordinary error that the next sync retries. Nothing raises inside the Celery task, and no token is logged.
4. **Withdrawing a source cleans rejected signals too; they stay rejected.**
5. **Restore re-checks the evidence against the live inputs** (`echo_signal_extraction.live_evidence_texts`, `gather_inputs`' rules without sampling) rather than trusting what the rejected row kept. It drops every ref that is no longer a live input and every example its source no longer contains. A learned signal with no evidence left comes back as `source_deleted` (re-derivable, out of the profile), not live.
6. **Restoring one rejection lifts every rejection of the same (type, wording, language),** merging their checked evidence and recording the restored row on their shares. If an equal live signal exists, every tombstone row is dropped and the live one kept. The Rejected list sends no examples.

**Alternatives considered.**
- *Key tombstones on the fact's source string* (`import:<id>`). A second import of the same export gets a new id and would bring the fact back.
- *Tombstone on disconnect too.* Disconnecting says "stop reading this account", not "this fact is wrong"; reconnecting should bring the facts back.
- *Ask for a reconnect on any failed refresh,* as the computed task said. A brief provider outage would send the user through OAuth again; the board entry named `invalid_grant`.
- *Make refresh a required connector method.* GitHub would need a stub that does nothing.
- *Trust the rejected row's examples on restore.* Rejections made before this change can still hold the words of a deleted source.

**Consequences.**
- The Echo page shows "Kept deleted (N)" with "Allow again", and the delete and revoke dialogs say a derived fact stays deleted. The signals panel shows "Rejected (N)" with "Restore". New endpoints: `GET` and `DELETE /echo/fact-tombstones[/{id}]`, `GET /echo/signals/rejected` and `POST /echo/signals/{id}/restore`. An import's counts report `facts_kept_deleted`.
- S-3.2.2 and S-3.2.5 stay blocked on the owner's Google OAuth client. The refresh step is tested with a fake connector, and each Google connector still has to implement `refresh_tokens`.
- Left out: no retry after a 401 mid-sync, and two concurrent refreshes against a provider that rotates refresh tokens could ask for a spurious reconnect (T-3.2.1.12, proposed); a sync still overwrites a connector-derived fact the user edited (T-3.2.1.11, proposed); there is no "clear all" for tombstones; rejections that went stale before this change keep their examples at rest, though restore and the Rejected list never show them (T-3.3.1.7, proposed).
- Owner step: apply migration `a68953e57c63` (a restart does) and restart the API and the worker.

**Linked initiatives / PRs.** E-3.2 (S-3.2.1: T-3.2.1.11, T-3.2.1.12; S-3.2.2: T-3.2.2.5; S-3.2.4: T-3.2.4.4; S-3.2.5), E-3.3 (S-3.3.1: T-3.3.1.6, T-3.3.1.7), E-3.10; PR [#392](https://github.com/khoks/VideoResearchPro/pull/392); [D-089](#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19), [D-098](#d-098--echo-connectors-events-unique-per-reader-tokens-in-a-secret-store-that-is-erased-with-the-brain-but-never-exported-2026-10-19), [D-099](#d-099--signal-extraction-verbatim-checked-examples-language-free-beliefs-stylometry-without-a-model-2026-10-19), [D-110](#d-110--echo-only-sees-what-the-user-hands-it-no-background-capture-and-the-echo-scope-rulings-2026-10-25).

**Status-changed 2026-11-04:** refined by [D-134](#d-134--a-live-manual-fact-holds-its-key-against-every-source-a-401-retries-one-call-a-lease-guards-the-refresh-token-and-a-changed-row-beats-a-refresh-answer-2026-11-04) (PR [#409](https://github.com/khoks/VideoResearchPro/pull/409)). Point 1: a typed fact that has turned a source away now gets a tombstone, through `personal_context.wanted_by`. Point 3: a 401 on a token just issued, or with nothing to renew with, also asks for a reconnect. T-3.2.1.11, T-3.2.1.12 and T-3.3.1.7 are closed.

**Status-changed 2026-11-10:** a derived fact whose key holds `/` is now deleted by its route, its tombstone keeps the whole key, and the next sync skips it ([D-174](#d-174--a-facts-key-is-the-rest-of-its-delete-routes-path-the-access-log-writes-all-of-it-and-the-echo-pages-form-accepts--in-a-label-2026-11-10), T-3.1.1.1, PR [#462](https://github.com/khoks/VideoResearchPro/pull/462)).

## D-123 — Unused read routes are removed, an output's Sources list groups by source, and a language badge names a language only on evidence (2026-11-04)

**Status:** accepted (2026-11-04). Made while building the reader and route gaps (S-8.8.5, T-8.8.4.1, T-1.16.1.9, PR [#396](https://github.com/khoks/VideoResearchPro/pull/396)) and its review fixes, not ruled by the owner.

**Context.**
- `GET /channels/{id}/videos` and `GET /jobs/{id}/shelves` had no caller, and the pages that would use them already read the same data another way. Both still had to be kept in step with [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31).
- `GET /author/outputs/{id}/citations` (S-6.7.3) had no UI. All four output kinds record citations, but they number them differently: only a book's endnote `n` is citation `n`.
- `language_mix` (T-1.16.1.7) was served but not shown, while the caption label still calls romanised Hinglish `en`. The tagger's classes are English and everything else: any Latin-script word outside its English lexicon counts as `hi`, and a passage with no function words votes by word majority. On short samples, Spanish, Portuguese, Italian, Indonesian, Tagalog and Turkish read primary `hi` with 60 to 100% "Hindi grammar", and Arabic reads `hi` too.

**Decision.**
1. **Unused read routes are removed, not kept "in case".** Each extra scoped read is another place D-063 must be kept true. `GET /channels/{id}/videos` goes in favour of `GET /library/videos?channel_id=`, and `GET /jobs/{id}/shelves` (with `shelf_service.shelves_for_job`) in favour of the `job_ids` in the cached `GET /shelves` listing. A test pins each absence, built so that restoring the route fails it.
2. **The output reader's Sources list groups citations by source, and prints only where the text cannot stand in for it.** One entry per cited source, with each citation as a chip. A book's endnotes and a deck's sources list every cited moment, so the list stays off paper there; a site's contents and a newsletter do not, so there it prints. Only a book names endnote numbers, because `position` equals the footnote number only there.
3. **The language badge's existence follows the server's `code_mixed`; its name needs evidence.** The frontend never decides whether a mix exists: that stays the chunker's 3% rule ([D-080](#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19)) through `language_mix_service.public_view`. But the profile cannot say which language a Latin-script source is. So Hindi is named only with a `hi` or `ur` label, in Devanagari, or on a video captioned `en` with at least 5% Hindi grammar (`HINDI_GRAMMAR_FLOOR`; the library's 219 English transcripts read 0 to 0.4%). An `en` label counts only on a video, because PDFs, Reddit and HN are `en` by assumption. Otherwise the badge shows the labelled language or a neutral name.

**Alternatives considered.**
- *Point the channel page at `GET /channels/{id}/videos`.* It would lose `job_count` / `job_titles`, which the shared `VideoRow` needs, and the library's search, filters and paging.
- *Read a job's shelves from `GET /jobs/{id}/shelves`.* A page of twenty cards would cost twenty requests instead of one.
- *One row per citation.* It would repeat a title dozens of times in a book.
- *A neutral label only when `matrix_hi_share` is 0,* the review's first suggestion. It would still put Hindi on most of the samples above, because the matrix breaks ties by word majority.

**Consequences.**
- No badge appears on the live library until the owner runs `scripts/backfill_language_mix.py --write`. The dry run of 2026-11-04 would store 254 profiles.
- The prompts keep the old naming: `code_mixing_service.source_note` still tells the models a Spanish source is "Hindi (romanised)" (T-1.16.2.15, proposed). The badge's fix is on the client because only the row holds the label and the source type together.
- Accepted gaps: a Hinglish Reddit thread or PDF reads "Other language + English", a Spanish video really labelled `en` would read as romanised Hindi, and ISO 639-2 labels are unread (T-1.16.1.10, proposed). No such document is in the library today.
- `GET /author/outputs/{id}/citations` joins `documents` without `visibility_service`. Citations resolve only against documents visible when the output is written, and no route revokes a grant today, so the join reveals nothing new. It was left unchanged.

**Linked initiatives / PRs.** E-8.8 (S-8.8.5, T-8.8.4.1, T-8.8.4.5), E-1.16 (T-1.16.1.9, T-1.16.1.10, T-1.16.2.15), E-6.7 (S-6.7.3); PR [#396](https://github.com/khoks/VideoResearchPro/pull/396); [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-080](#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19), [D-120](#d-120--older-chunks-gain-their-era-and-publish-fields-by-a-metadata-only-pass-amends-d-072-the-language-profile-is-stored-on-the-document-2026-11-04).

**Status-changed 2026-11-04:** the gaps here narrowed in PR [#403](https://github.com/khoks/VideoResearchPro/pull/403) ([D-133](#d-133--the-tagger-abstains-without-hindi-evidence-the-presence-floor-reads-grammar-an-offline-lexicon-sees-english-in-devanagari-and-scores-are-quoted-from-the-production-row-2026-11-04)). `source_note` no longer calls a Spanish source Hindi (T-1.16.2.15), the badge reads ISO 639-2 labels (T-1.16.1.10), and an `other` source is no longer "Hindi (romanised)" under an `en` label. The client guard stays for third-language labels; the Hinglish Reddit gap is T-1.16.1.11.

## D-124 — Second-factor attempts count on the ticket, one bearer check for HTTP and the socket, and a validation error never quotes what was sent (2026-11-04)

**Status:** accepted (2026-11-04). Made while building T-5.4.12 to T-5.4.15 and T-5.6.9 (PR [#399](https://github.com/khoks/VideoResearchPro/pull/399)) and its review fixes, not ruled by the owner. It closes the four items [D-121](#d-121--reset-codes-never-appear-in-a-response-two-step-verification-guards-every-sign-in-and-tokens-say-what-they-are-2026-11-04) left open.

**Context.**
- A password reset is what someone does when they think their password is known, and it left whoever was already signed in signed in.
- One five-minute second-factor ticket could be tried from many addresses, because the only bound was the per-IP sign-in limit.
- There was no way to change a password while signed in.
- A token from a signed-out session kept opening the progress socket until it expired.
- A malformed `BYOK_ENCRYPTION_KEY` surfaced as a bare 500 or as "wrong code", which sends the user to check their phone's clock when the fault is the operator's.
- FastAPI's default 422 put the rejected value in `input`: the whole body when a field was missing, and the raw bytes when the content type was not JSON.

**Decision.**
1. **Second-factor attempts live in the database, keyed on the ticket's `jti`, and a ticket buys one session.** A ticket with no `jti` is refused rather than left uncounted. Five is a constant (`MFA_TICKET_MAX_ATTEMPTS`), beside `MFA_TOKEN_TTL_MIN`.
2. **`users.has_password` rather than a nullable hash.** OAuth accounts keep a random hash, so the flag only decides what the change route answers, and sign-in never reads it. The backfill rule: first identity linked within 60 seconds of the account, no completed reset, and no `user_registered` event, which only `POST /auth/register` writes.
3. **A wrong current password counts toward the account lockout,** through the same check as sign-in. A stolen session can then guess no faster than the sign-in page allows. It adds no new denial of service, since anyone who knows the address can already lock an account at `/auth/login` ([D-040](#d-040--failed-logins-for-unknown-emails-do-not-create-user-rows-lock-arbitrary-account-defence-2026-05-04)).
4. **The change route answers 400 or 429, never 401.** The web client treats a 401 as a dead session and would sign the user out for a typo.
5. **A validation error never quotes what was sent, on any route.** `input` is dropped in one app-level handler; `type`, `loc` and `msg` stay, and nothing in the backend, the web app or the extension reads `input`. The new password is still measured in the route, so a bad one gets a sentence the page can show.
6. **Recovery codes keep working with a broken key,** since they are hashed. `verify_at_login` tries them before it raises, so they are the way in until the operator fixes the key.
7. **One bearer check for HTTP and the socket** (`auth_service.authenticate_access_token`), with an app-level exception handler as the net under the per-route 503s for the key error ([D-043](#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05)).

**Alternatives considered.**
- *Count attempts in the in-memory rate limiter.* It resets on restart and is per process.
- *Clear the password hash on OAuth accounts.* A wrong backfill guess would lock a user out, where a wrong flag costs them a pointer to the reset.
- *Type the password fields `Any`, so the schema stops rejecting them.* A body that is not an object, and a form-encoded body, would still be quoted back.

**Consequences.**
- New table `mfa_step_tickets` and column `users.has_password` (migration `f748717dcb01`). On the owner's database the backfill marks nobody. Owner step: `./scripts/restart_services.ps1`; anyone mid-sign-in holds a ticket with no `jti` and is asked to start over.
- Every route's 422 body changes: `input` is gone.
- `_client_ip` trusts `X-Forwarded-For` from any caller, so the ticket cap and the lockout are the real bounds here, not the per-IP bucket (T-5.5.8, proposed).
- A ticket issued before a reset survives it for at most five minutes, and it still needs the second factor. An open socket is not closed when its session is revoked later; only the handshake checks (T-5.4.19, proposed).
- Left open, all proposed: `DELETE /auth/mfa` has no attempt cap (T-5.4.16); there is no account-wide second-factor count, which is the owner's call because it changes who gets locked out (T-5.4.17); a NUL or lone surrogate in a password is still a bare 500 on register and reset (T-5.4.18); a rotated key still reads as a wrong code (T-5.6.11).

**Linked initiatives / PRs.** E-5.4 (T-5.4.12 to T-5.4.19), E-5.5 (T-5.5.8), E-5.6 (T-5.6.9, T-5.6.11); PR [#399](https://github.com/khoks/VideoResearchPro/pull/399); [D-040](#d-040--failed-logins-for-unknown-emails-do-not-create-user-rows-lock-arbitrary-account-defence-2026-05-04), [D-043](#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05), [D-121](#d-121--reset-codes-never-appear-in-a-response-two-step-verification-guards-every-sign-in-and-tokens-say-what-they-are-2026-11-04).

**Status-changed 2026-11-05:** T-5.4.16, T-5.4.18, T-5.4.19, T-5.5.8 and T-5.6.11, left open here, shipped in PR [#411](https://github.com/khoks/VideoResearchPro/pull/411) ([D-138](#d-138--code-attempts-count-on-a-shared-row-sockets-end-with-their-session-one-reader-takes-the-client-address-from-the-right-and-a-rotated-key-is-reported-2026-11-05)). T-5.4.17 stays the owner's call.

## D-125 — A knowledge report's depth applies D-064 without a bracket and belongs to the shared artifact, and a failed synthesis never reaches it (2026-11-04)

**Status:** accepted (2026-11-04). Made while building S-1.15.3 and S-1.15.4 (PR [#395](https://github.com/khoks/VideoResearchPro/pull/395)) and its review fixes, not ruled by the owner. It extends [D-064](#d-064--output-length-corpus-brackets-with-an-optional-user-override-2026-07-31) to the last surface with no preference. Point 4 reverses a deliberate earlier behaviour, so the owner may want to rule on it (OQ-23).

**Context.**
- Knowledge synthesis was the only output surface with no user preference. S-1.14.8 already made its budget follow the size of the extraction.
- Since T-1.15.2.3 the job and library Q&A requests accepted `output_length`, but no page sent it.
- Every provider counts thinking inside `max_tokens`. On a short source brief alone is 3,600, under the 4,096 a Claude model on legacy thinking is budgeted at medium, and the API refuses that call.
- `synthesize_report` turns any failure into an empty report, and the router stored that over the shared artifact, spent the caller's quota and returned 200.
- A knowledge report is metered (10 a month on Free) and takes about a minute, and the drawer started one as soon as it opened.

**Decision.**
1. **Knowledge depth applies D-064 without a bracket.** One document is not a corpus, and S-1.14.8 already makes the budget follow the extraction. An explicit preference multiplies that budget, including its 8,000 floor; unset is exactly 1.0 with no brief. A shrunken budget keeps a thinking reserve (the floor's scaled share plus `thinking_reserve_tokens`, capped at the unset budget), because thinking is counted inside `max_tokens` and the brief, not the ceiling, does the shortening ([D-062](#d-062--report_compose-upgraded-to-claude-opus-5-2026-07-31)).
2. **A knowledge report's depth is a property of the shared artifact.** Under [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), `documents` holds one report per document for every tenant who can see it, so the depth one tenant chooses is what the others read, and a Regenerate overwrites it for all of them. The overwrite already existed. The depth is now recorded and shown, so the effect is visible.
3. **A failed synthesis never reaches the shared artifact.** An empty report is a 502: nothing is stored and no quota is spent.
4. **The knowledge drawer asks before it spends.** It no longer starts a report on open. The select is preset to the surface's default, so accepting it is still one click, and Regenerate sits in the same row.
5. **A per-ask depth applies to one ask,** unlike the answer language: it clears when the answer lands, and survives a failed ask and "Edit question". The request carries `output_length` only when a depth is picked, so the router's precedence (request, else job, else bracket) is unchanged.

**Alternatives considered.**
- *Bracket the document.* Every document would classify as `small`, and every unset request would get 1.25x plus the small-corpus nudge.
- *Keep auto-start and offer depth only on Regenerate.* A reader who wants another depth pays for two metered reports.
- *Put the Q&A select beside Ask, as the spec said.* On a 320 px phone it would leave the input about 65 px, so it sits with each surface's other per-ask option, and a thin note in the docked composer shows a picked depth on phones (OQ-22).

**Consequences.**
- Unset or `auto` is byte-identical to S-1.14.8, in budget and prompt. Regenerating without a depth clears the recorded one. `output_length` is `null` on every report written before this.
- With reasoning on, a brief report on a short source gets 7,696 rather than 8,000 on the default model, so the brief does the shortening. The brief depth has not run on a live model (T-1.15.3.6, an owner step).
- Left open, all proposed: `BatchExtract` sends no depth (T-1.15.3.7); a truncated report is stored with only a logged warning (T-1.15.3.8); there is no account-level preference, though the spec mentions one (T-1.15.3.9); Q&A brief has the same thinking arithmetic at 2,025 tokens (T-1.15.4.4).

**Linked initiatives / PRs.** E-1.15 (S-1.15.3, S-1.15.4, T-1.15.3.6 to T-1.15.3.9, T-1.15.4.4, OQ-22, OQ-23); PR [#395](https://github.com/khoks/VideoResearchPro/pull/395); [D-062](#d-062--report_compose-upgraded-to-claude-opus-5-2026-07-31), [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-064](#d-064--output-length-corpus-brackets-with-an-optional-user-override-2026-07-31).

**Status-changed 2026-11-04:** point 1's cap does not carry over to Q&A. Q&A brief keeps the whole reserve with no cap, because the unset figure there is 4,500 from a `large` corpus up ([D-132](#d-132--qa-brief-keeps-the-whole-thinking-reserve-a-cut-off-report-offers-deep-a-citation-with-no-document-casts-no-vote-and-clarify-is-one-optional-route-2026-11-04), T-1.15.4.4, PR [#406](https://github.com/khoks/VideoResearchPro/pull/406), OQ-29). T-1.15.3.7 and T-1.15.3.8 are closed too.

**Status-changed 2026-11-05:** the account-level depth preference exists. On the knowledge drawer it is a preset, not an action, so a report generated from it stores that depth on the shared artifact, as a manual pick does ([D-145](#d-145--a-cut-off-flag-is-a-fact-about-one-reply-the-offer-keeps-the-cards-scope-and-the-server-never-applies-the-accounts-default-depth-2026-11-05), T-1.15.3.9, PR [#419](https://github.com/khoks/VideoResearchPro/pull/419), OQ-37).

## D-126 — A knowledge report is cited as its whole document, and an outputter can refuse a source before its row exists (2026-11-04)

**Status:** accepted (2026-11-04). Made while building S-6.3.2 (PR [#398](https://github.com/khoks/VideoResearchPro/pull/398)) and its review fixes, not ruled by the owner.

**Context.**
- S-6.3.1 shipped decks from runs only, and E-6.3's scope also named a knowledge artifact. The board asked for the report's "citations as source markers, as reports do".
- A knowledge report has no citations to link. The synthesis prompt never asks for them, and extraction reads text with the times already dropped (`_text_from_segments` keeps only each segment's text). The only times a report can hold are plain words such as "On screen at 4:12".
- An uploaded PDF has no public address: its file is a relative path behind sign-in.

**Decision.**
1. **A knowledge report is cited as its whole document, not at moments.** The model is offered one marker, the document's, on every paragraph, list item and table row. Links are reduced to their labels and stray markers are removed, so the only marker on offer is one the sources slide can link.
2. **The sources slide links the document where it lives,** or its knowledge report in the app when it has no public address.
3. **An outputter may define `check_sources(db, user, source_ids)`,** which the router runs before the row exists, on create and on estimate. `OutputSourceNotFound` maps to 404 and `OutputSourceNotReady` to 409, matching [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)'s existence-leak posture: a document the caller cannot see reads exactly like one that does not exist. Runs are not pre-checked: a bad run is still left out at generation and disclosed, as in S-6.3.1.
4. **The run-only prompt stays identical,** so S-6.3.1's trial still describes it. A note goes out only with a knowledge report: the marker cites the source as a whole, the source may not be a video, and a report's own sentences are not the source's words, so a quote slide may use only words the report itself gives as a quotation.

**Alternatives considered.**
- *Ground each sentence to its nearest transcript chunk by embedding similarity.* It would invent precision the report does not have and could pin a claim to the wrong moment.
- *Give each section its own marker.* The markers would all resolve to the same link.
- *Pre-check runs too.* It would change a shipped contract, and the spec asked for the document refusals only.

**Consequences.**
- In a deck from one knowledge report every slide cites the same source. "Every content slide cites a linked source" holds but says less than it does for runs: it shows the model cited what it was given, not that each bullet is supported.
- What would change this: knowledge extraction that carries time ranges through to each item. `transcript_cache` segments have the times, but `document_text_service` drops them before the agent sees the text, so it needs a change to extraction and a fresh extraction per document.
- The knowledge header carries no speech note (`code_mixing_service.source_note`). The model sees the English report, not the source's own text, and the run-report deck prompt carries none either. CLAUDE.md asks a new prompt that shows sources to carry it, so this is a reading of that rule the owner can overrule.
- `DECK_SYSTEM` still says the reports "were compiled from video transcripts", so that the run-only prompt stays identical; the note corrects it for knowledge reports. Nothing checks a quote slide against any text: the note is the only guard, and no real model has run on it.
- Owner steps: restart the API and the worker, and make one real deck (T-6.3.2.4). It would also give the first cost figure.

**Linked initiatives / PRs.** E-6.3 (S-6.3.2, T-6.3.2.4); PR [#398](https://github.com/khoks/VideoResearchPro/pull/398); [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19).

## D-127 — The in-app voice test is a rolled-back what-if on the `echo_draft` use case, and an open test's answers stay out of the export (2026-11-04)

**Status:** accepted (2026-11-04). Made while building T-3.4.1.8 (PR [#400](https://github.com/khoks/VideoResearchPro/pull/400)) and its review fixes, not ruled by the owner. It brings [D-100](#d-100--voice-match-gate-mode-a-passes-on-synthetic-writers-speak-as-me-may-be-built-and-is-enabled-per-user-only-after-the-user-as-judge-test-2026-10-19)'s tier (iii) into the app and writes [D-102](#d-102--speak-as-me-two-switches-guards-in-code-the-reply-in-the-users-language-2026-10-20)'s per-user gate. Five review questions stay open for the owner (OQ-24 to OQ-28).

**Context.**
- The switch for E-3.4 needed an operator to run two commands against a copy of the database and pass files back and forth, and T-3.3.4.3 had not run for anyone.
- `user-pairs` soft-deletes the held-out notes in a copy and re-runs extraction, so nothing those notes taught reaches the draft. Without that, a draft could borrow from the note it is paired with and a user would pass falsely. The app can do neither on live data.
- A test makes about 40 model calls on copies of a user's own notes, so it has to run on the model that user chose.

**Decision.**
1. **A rolled-back what-if instead of a copy.** `withdrawn_signals` runs the database half of an extraction run with the held-out notes gone, using the code the harness runs (`apply_pending`, split out of `_run`, plus `sync_stylometry`), on its own connection in a transaction that is always rolled back, with `join_transaction_mode="rollback_only"` so even a commit inside cannot persist. The surviving signals are ranked in a throwaway in-memory Chroma collection.
2. **`echo_draft`, not the harness's pinned `DRAFTER`.** This gives routing, the user's pin and BYOK key, and metering, through `llm_service.byok_context`. The default is the same model and reasoning, and a test pins that. `echo_draft_service.draft` now resolves it the same way, so whoever moves `echo_draft` tests the drafts they will get.
3. **One difference from the harness.** Texts Echo has not learned from yet are not learned during the test. Their stylometry still counts. This can only weaken the trait card, which pushes toward a fail.
4. **The stored test is part of the brain.** `echo_voice_tests` is in `ECHO_TABLES`, so it is exported and erased with the brain ([D-089](#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19)). It keeps copies of notes and drafts after scoring, which T-3.4.1.9 can read.
5. **Limits.** One open test at a time, held by a partial unique index, and 3 starts a day per user.
6. **An open test's answers stay out of the export.** `key_json` and `seed` are exported as null while a test is open, and the manifest counts those rows. The export is complete once a test is scored. The user can always find their own text on `/notes`, so the blinding rests on honesty either way; this keeps the server from handing them the answer.
7. **A closed test stays closed.** Staleness runs from the worker's last progress, and every write to a generating test is conditional on it still generating.

**Alternatives considered.**
- *Copy the database and Chroma per test.* Too heavy for a request flow.
- *Reimplement withdrawal in memory.* It could drift from the real code.
- *Learn pending texts during the test.* It would run the extraction model on live data for every test.
- *Blank `key_json` alone in the export.* `seed` fixes the held-out sample and every coin flip, so with the user's notes it rebuilds the key.
- *Show which side was theirs after scoring.* It would teach the tells a retake depends on.

**Consequences.**
- Scoring follows `user-score`, and a fail stores `status="failed"` as `--record` does, so a failed retake closes a gate that had passed. The page warns about that before a retake starts (OQ-24).
- `echo_draft_service.draft` now honours the user's pins for `echo_draft`, `echo_classify_intent` and `echo_critique`, which it ignored until now.
- The real drafts have not been seen in this flow: tests must not call paid providers.
- Owner steps: restart the API and the worker (migration `6d5b3d5aa6fa`, new task `echo.generate_voice_test`), and set `ECHO_SPEAK_AS_ME_ENABLED=True` when the test should be offered. T-3.3.4.3 can then run from the Echo page.
- Left open: `echo_drafts.model` stays `String(64)` (T-3.4.1.10, proposed); lost updates between concurrent pick requests were not reviewed.

**Linked initiatives / PRs.** E-3.4 (T-3.4.1.8 to T-3.4.1.10, OQ-24 to OQ-28), E-3.3 (T-3.3.4.3); PR [#400](https://github.com/khoks/VideoResearchPro/pull/400); [D-089](#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19), [D-100](#d-100--voice-match-gate-mode-a-passes-on-synthetic-writers-speak-as-me-may-be-built-and-is-enabled-per-user-only-after-the-user-as-judge-test-2026-10-19), [D-102](#d-102--speak-as-me-two-switches-guards-in-code-the-reply-in-the-users-language-2026-10-20).

**Status-changed 2026-11-04:** T-3.4.1.10 shipped in PR [#409](https://github.com/khoks/VideoResearchPro/pull/409) ([D-134](#d-134--a-live-manual-fact-holds-its-key-against-every-source-a-401-retries-one-call-a-lease-guards-the-refresh-token-and-a-changed-row-beats-a-refresh-answer-2026-11-04)): `echo_drafts.model` is `String(128)`.

## D-128 — One source is a narrowing key on `QAScope`, every citation carries `document_id`, and the notification push is a doorbell (2026-11-04)

**Status:** accepted (2026-11-04). Made while building T-8.4.2.4, T-8.3.3.8, T-8.10.1.6 and T-8.10.1.7 (PR [#397](https://github.com/khoks/VideoResearchPro/pull/397)) and its review fixes, not ruled by the owner. Point 4 is a reading of "at least one citation" that the owner may want to confirm.

**Context.**
- The knowledge drawer's suggestions read as being about the source but were asked across the library.
- A saved search runs in the worker, so nothing reached an open page for up to a minute. Pushing to the bell opens the socket on every signed-in page, not just on a running job.
- M10 named `first_cited_answer` as its alternative activation milestone, and nothing wrote it.
- The wizard collects up to five channels, and only the first run read one of them.
- The review found a blocker: a scope check keyed on `video_id` dropped every citation of a non-YouTube source, because `video_id` is empty there.

**Decision.**
1. **`document_id` is a narrowing key on `QAScope`** (extends [D-095](#d-095--scoped-library-questions-one-history-table-with-a-scope_json-object-narrowing-and-provenance-keys-unknown-keys-refused-2026-10-19)). One source is the narrowest scope: with a shelf it intersects for documents, and its notes are the source's own rather than the union of both scopes.
2. **The notification push is a doorbell.** It carries `id` and `kind`, never the title or body, so a notice's text is only read over HTTP, where the session is checked. Routing is by Redis channel, and the subscribing user comes from the token.
3. **A signed-out browser keeps no socket, and a revoked token opens none.** `AuthProvider` closes the socket on any sign-out, the client replaces it when the stored token changes, and the handshake refuses a revoked token ([D-124](#d-124--second-factor-attempts-count-on-the-ticket-one-bearer-check-for-http-and-the-socket-and-a-validation-error-never-quotes-what-was-sent-2026-11-04)). A session revoked elsewhere does not close a socket already open: that is the stated gap, not a guarantee.
4. **`first_cited_answer` means a source was cited.** An answer citing only the reader's own notes does not count, and neither does a saved-search run, which does not go through the routers. It is check-then-insert like the other activation events, so two truly concurrent first answers could write two.
5. **The pre-fill offers channels no run has named,** whatever became of that run, derived on read. The "once" is per browser (localStorage), a convenience rather than server state, and it is spent only when the list is on screen.
6. **Every citation carries `document_id`, and that is the id a scope check compares** (extends [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19)). `video_id` stays as a fallback for stored references only.

**Alternatives considered.**
- *Pin a question about one source.* A saved search takes the library or a shelf, and one document's answer has little to change. The button is hidden, because it would have pinned the question over the whole library.
- *An inline composer in the drawer.* The card hands over to library Q&A, as it did; the spec asks it to ask about the source and say so.
- *Name the source's title on the answer card.* The exchange stores only the id, so it would mean a lookup per card or storing something that goes stale.
- *Close the socket in `useLiveNotifications`.* The layout has already unmounted by the time the token is gone, so it lives in `AuthProvider`.

**Consequences.**
- New setting `NOTIFICATIONS_PUSH_ENABLED`, default on, off for the test suite. A worker on the new code with an API on the old code publishes unheard, and the one-minute poll covers it, as it does a notice published while the socket is down.
- The bell has not been checked end to end in one running app: the server route, the Redis path and the client are each tested, but not together.
- `document:<id>` suggestions now read questions asked about that source, and such a question invalidates their cache.
- Left open, proposed: closing a socket already open when its session is revoked (T-5.4.19), and saved-search change detection, which still keys the cited set on `video_id`, so a non-YouTube citation is not counted there (T-8.3.3.10).
- Owner step: restart the API, the worker and the frontend. No migration.

**Linked initiatives / PRs.** E-8.4 (T-8.4.2.4), E-8.3 (T-8.3.3.8, T-8.3.3.10), E-8.10 (T-8.10.1.6, T-8.10.1.7), E-5.4 (T-5.4.19); PR [#397](https://github.com/khoks/VideoResearchPro/pull/397); [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19), [D-095](#d-095--scoped-library-questions-one-history-table-with-a-scope_json-object-narrowing-and-provenance-keys-unknown-keys-refused-2026-10-19), [D-124](#d-124--second-factor-attempts-count-on-the-ticket-one-bearer-check-for-http-and-the-socket-and-a-validation-error-never-quotes-what-was-sent-2026-11-04).

**Status-changed 2026-11-05:** both items left open here are closed. Saved-search change detection keys on `document_id` ([D-132](#d-132--qa-brief-keeps-the-whole-thinking-reserve-a-cut-off-report-offers-deep-a-citation-with-no-document-casts-no-vote-and-clarify-is-one-optional-route-2026-11-04), T-8.3.3.10, PR [#406](https://github.com/khoks/VideoResearchPro/pull/406)), and a revoked session's open socket closes ([D-138](#d-138--code-attempts-count-on-a-shared-row-sockets-end-with-their-session-one-reader-takes-the-client-address-from-the-right-and-a-rotated-key-is-reported-2026-11-05), T-5.4.19, PR [#411](https://github.com/khoks/VideoResearchPro/pull/411)).

## D-129 — Drift tests hold the docs to the code, the repo has one env template, and the anchor checker writes only when told to (2026-11-04)

**Status:** accepted (2026-11-04). Made while building E-4.11, T-4.8.5 and T-5.6.7 (PR [#401](https://github.com/khoks/VideoResearchPro/pull/401)) and its review fixes, not ruled by the owner. It carries out [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25)'s one-template ruling and goes further than it in point 2, and corrects [D-032](#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03).

**Context.**
- CLAUDE.md loads into every session, so a wrong count or a phantom route misleads every later piece of work. It said 168 tests and 6 LangGraph agents, listed 54 of 199 endpoints with one route that did not exist, and left 61 settings out.
- Three `.env.example` files existed, and the backend's still said 0.5 s between transcript fetches, the pace that got the install IP-blocked ([D-051](#d-051--transcript-pipeline-resilience-bundle-circuit-breaker--segmented-whisper--yt-dlp-client-fallback-2026-07-22)).
- `fix_anchor_links.py` saw only 10 target docs, had no dry-run flag and ignored `--report`.
- Without a test, docs like these drift again within weeks.

**Decision.**
1. **The drift tests go beyond the spec, and that is a standing rule for every session.** Besides `.env.example`, they cover CLAUDE.md's env table, its API list and `docs/api-reference.md`. A PR that adds a setting must touch three files and one that adds a route must touch two, or CI fails. That cost is the point.
2. **`frontend/.env.example` is deleted too,** though D-112 named only the backend's. The `VITE_*` variables are a section of the root file: `VITE_API_BASE_URL` and `VITE_WS_URL` go in `frontend/.env`, and `VITE_PROXY_TARGET` in the shell, because `vite.config.ts` reads `process.env` and was left that way rather than given `loadEnv`, since its comment and Playwright's config already set it so.
3. **`fix_anchor_links.py` writes only with `--write`,** like the backfill scripts. `--report` is removed rather than kept as an alias, so an unknown flag rewrites nothing. Its oracle is GitHub's rendered ids, and it deliberately does not read raw HTML headings or headings in list items: a good link to one fails `--check`, and the failure output says why.
4. **Settings nothing reads are marked, not removed.** Removing them is a code change for its own PR, and a test holds the list to an AST scan of the code that runs, so wiring one up later fails until its marker comes off.

**Alternatives considered.**
- *Test only `.env.example`, the spec's scope.* CLAUDE.md's table and route list are what mislead sessions.
- *Keep `--report` as an alias.* The board complained about exactly that flag, which was ignored while files were rewritten.
- *Read routes from `app.routes`.* On FastAPI 0.162, which CI installs, it holds no `APIRoute`, so the tests read `app.openapi()` and the WS router and pass on both versions.

**Consequences.**
- Every later PR that adds a setting or a route pays this cost.
- After the batch 4 tracker pass repaired the last 18 links, CI's lint job checks every Markdown file with nothing skipped.
- Left open, proposed: the seven unread settings (T-4.11.1.4), a re-audit of `docs/ui-pages.md` and the docs #401 did not cover (T-4.11.1.5), section B of the runbook and `backend/alembic.ini` (T-2.6.7, the owner's call), and `MAX_CONCURRENT_JOBS` being install-wide (T-5.2.14).
- Owner step: set `BYOK_ENCRYPTION_KEY` if it is not set. The template change touches no existing `.env`.

**Linked initiatives / PRs.** E-4.11 (S-4.11.1), E-4.8 (T-4.8.5), E-5.6 (T-5.6.7), E-2.6 (T-2.6.1, T-2.6.7), E-5.2 (T-5.2.14); PR [#401](https://github.com/khoks/VideoResearchPro/pull/401); [D-032](#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03), [D-051](#d-051--transcript-pipeline-resilience-bundle-circuit-breaker--segmented-whisper--yt-dlp-client-fallback-2026-07-22), [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25).

**Status-changed 2026-11-05:** point 4 is settled in PR [#412](https://github.com/khoks/VideoResearchPro/pull/412): four unread settings are removed and three stay marked reserved ([D-139](#d-139--alembic-uses-the-url-a-caller-names-else-the-setting-and-alembicini-holds-none-2026-11-05)). T-4.11.1.4, T-4.11.1.5 and T-2.6.7 are closed.

## D-130 — The brand lockup follows branding section 3, dark logos are separate files, and the outline generator's tools are not dependencies (2026-11-04)

**Status:** accepted (2026-11-04). Made while building T-2.8.2 and T-2.8.4 (PR [#404](https://github.com/khoks/VideoResearchPro/pull/404)) and its review fixes, not ruled by the owner. It carries out [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25)'s ruling that the interim echo mark is the identity. **The owner has not seen the artwork,** so it stands as a proposal until they look (T-2.8.5).

**Context.**
- D-112 made the echo mark the identity and asked for the full logo and the marketing set to be made from it.
- `docs/branding.md` section 3 sets the Latin line in Fraunces italic and says "Set lowercase", though it shows a capital P. The app's pages set the line in tracked roman capitals and the Astro site in roman mixed case. Section 3 sets no colours for the lockup.
- `prefers-color-scheme` follows the OS, while the app's theme is a `data-theme` toggle.
- Devanagari needs a real shaper. Glyph by glyph, `प्रतिध्वनि` is 10 glyphs with the halants left hanging and the vowel signs on the wrong side of their consonants. HarfBuzz gives the correct 6.
- This Fraunces file's default instance is Black (wght 900).

**Decision.**
1. **The Latin wordmark follows section 3 rather than the live pages,** because the brand document says it is the source. The instruction is taken literally: `pratidhvani`, lowercase.
2. **The lockup's other conventions come from the app.** Colours are the app's lockups' (Devanagari `accent`, Latin `textSecondary`). The text block is exactly as tall as the mark's ink. The smallest size is 32 px tall, measured at 1× pixels; below that, the mark alone.
3. **Dark logos are separate files, not a media query,** because a media query would follow the OS and ignore the app's toggle.
4. **The generator is committed; its tools are not dependencies.** The output is committed and nothing runs `frontend/scripts/outline-logos.py` at build time. Its header pins the versions. Fonts came from `@fontsource/tiro-devanagari-hindi@5.3.0` and `@fontsource-variable/fraunces@5.3.0`, both SIL OFL 1.1 with no Reserved Font Name declared, and no font file is in the repository. It reads the arcs from `logo-mark.svg`, so a lockup cannot drift from the master, and it refuses to run with a Fraunces axis unpinned.
5. **A wordmark's identity is pinned by a sha256 of its path data,** not by measurements. In review, eight regenerations (a wrong weight, misspelt and transposed words, wrong sizes) passed all 32 earlier tests. A hash says only that the outline changed, so a run that changes a wordmark fails until someone has rendered it, read it and updated `WORDMARK_SHA256`.

**Alternatives considered.**
- *Follow the live pages' Latin line.* The brand document says it is the source, and changing the logo later is one constant plus a regeneration.
- *One SVG with a `prefers-color-scheme` media query.* See point 3.
- *Add the shaper and the fonts to a requirements file.* Nothing else would use them, and nothing runs the generator at build time.
- *Pin contour counts and the ink box.* These errors barely move the box: a misspelt Devanagari word is 0.10 wider of 109.59.

**Consequences.**
- The logo and the live pages disagree on the Latin line until the owner chooses (T-2.8.5).
- Dark Devanagari `#b04a2f` on `#1c1814` is 3.25:1. That clears the 3:1 graphics floor and is the token the app uses there, but it is the weakest figure in the set. The dark favicon's non-token `#c45a3e` reads 4.10:1.
- No app page changes, so nothing references `logo-full.svg` yet. `og.png` (T-2.8.3) stays deferred.
- A deliberate layout change also trips the pin, because the path data holds absolute coordinates. That is intended: the failure sends someone to look at the artwork.
- CI does not build `marketing/` (T-2.8.6). A test reads the layout, and the real build was run by hand.

**Linked initiatives / PRs.** E-2.8 (T-2.8.2 to T-2.8.6); PR [#404](https://github.com/khoks/VideoResearchPro/pull/404); [D-087](#d-087--mobile-reading-and-install-a-reading-toolbar-below-1200-px-a-docked-composer-lifted-by-visualviewport-hermetic-device-tests-a-manifest-without-a-service-worker-2026-10-19), [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25).

## D-131 — Whisper is charged at the shared call, and usage is written part-way, on a timer, after every billed response (2026-11-04)

**Status:** accepted (2026-11-04). Made while building T-5.2.12 and T-5.2.13 (PR [#405](https://github.com/khoks/VideoResearchPro/pull/405)) and its review fixes, not ruled by the owner. It closes two items [D-119](#d-119--usage-is-metered-at-a-scope-that-names-the-tenant-and-written-in-a-session-of-its-own-2026-11-04) listed as not recorded. It records usage and enforces nothing new ([D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)).

**Context.**
- Whisper is billed per minute and bypasses LangChain, so S-5.2.1 recorded none of it.
- Every hosted Whisper call goes through `youtube_service._whisper_transcribe_with_retry`: the YouTube fallback, Echo recordings and podcast audio, which the board entry did not name.
- A task's usage was written only when the task ended, so a worker that died mid-sync lost the whole run's usage.
- A report's map phase has no loop of the task's to hook into, and the chunks of a split recording are billed minutes apart inside one iteration of the extraction loop, with no model call among them.
- Report map batches run on a pool, and a `Session` is not thread-safe.

**Decision.**
1. **Whisper is charged at `_whisper_transcribe_with_retry`, not at each caller,** so a new caller cannot ship unmetered. The amount is the response's `duration`, rounded to the nearest second with a floor of one, and overlap counts because it is billed. Video and podcast audio go to `ingest`, Echo recordings to `echo_shares`.
2. **Part-way writes are time-gated and tried after every billed response.** An open scope writes at most every `USAGE_FLUSH_INTERVAL_SECONDS` (default 60, `0` = only at close). It tries after every model call and every Whisper response, and at `usage_service.checkpoint()` after each video and each channel. Time rather than amount, because a write costs the same whatever it holds. After every billed response, because the convention is "at the scope, not the call site".
3. **A checkpoint never touches the caller's session.** It writes through the meter's own session, and while the caller's transaction has written it leaves the amounts in the ledger. A try that had to wait does not restart the interval. Amounts leave the ledger before they are written and go back only when that write rolled back, so a checkpoint and the close never write the same amount.
4. **Off the scope's thread, the meter reads only its own bookkeeping,** so a raw write on another thread's session is not seen. The cost of missing one is a stalled write that fails and is restored, never a committed caller transaction.

**Alternatives considered.**
- *Charge Whisper at each caller.* A new caller could ship unmetered.
- *A background flusher thread.* It would have to inspect the caller's session from another thread.
- *Write only at the end of each iteration.* A report's map phase has no iteration of the task's, and a split recording is one iteration of one.
- *An idempotency key on each write.* Only a commit whose acknowledgement is lost could write an amount twice, which cannot happen on local SQLite. It needs a table and a migration; worth revisiting with Postgres.
- *Mirror Whisper into `quota_usage`.* That table reports caps, and Whisper has none, so `/auth/quota` is unchanged.

**Consequences.**
- `GET /usage` and "Your usage" show audio minutes. There is no migration, because `usage_records` holds any metric name.
- A dead worker loses what it counted since its last write: at most about one interval, unless the caller's open transaction kept making the tries wait. Echo learning runs hold their writes open by design, so theirs is written at the close.
- Work a redelivery really repeats is recorded again, because it was paid for again.
- A Whisper request that got no response records nothing, though OpenAI may still bill one that timed out. Operator scripts open no scope, so their Whisper use stays unrecorded.
- Found on the way, not changed: pool threads read through the task's `Session` for the BYOK lookup (T-5.6.12); the YouTube fallback and podcast audio use the install's key while Echo recordings use the tenant's (T-5.6.13); a podcast document's feed URL sits in a `String(50)` foreign key (T-1.7.1.4).
- No owner step beyond a restart. The setting is optional.

**Linked initiatives / PRs.** E-5.2 (T-5.2.12, T-5.2.13), E-5.6 (T-5.6.12, T-5.6.13), [S-1.7.1](initiatives.md#s-171--podcast-text-path-follow-ups); PR [#405](https://github.com/khoks/VideoResearchPro/pull/405); [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25), [D-119](#d-119--usage-is-metered-at-a-scope-that-names-the-tenant-and-written-in-a-session-of-its-own-2026-11-04).

**Status-changed 2026-11-05:** both items found on the way are closed: pool threads no longer use the task's `Session`, and the YouTube fallback and podcast audio use the tenant's key ([D-146](#d-146--a-pool-never-carries-the-session-max_concurrent_jobs-is-per-user-a-key-check-says-good-or-bad-only-when-the-provider-did-and-whispers-key-and-count-hold-on-every-sync-2026-11-05), T-5.6.12, T-5.6.13, PR [#417](https://github.com/khoks/VideoResearchPro/pull/417)). Whisper's key changed; how its seconds are recorded did not.

## D-132 — Q&A brief keeps the whole thinking reserve, a cut-off report offers Deep, a citation with no document casts no vote, and clarify is one optional route (2026-11-04)

**Status:** accepted (2026-11-04). Made while building T-1.15.4.4, T-1.15.3.7, T-1.15.3.8, T-8.3.3.10 and S-8.13.2 (PR [#406](https://github.com/khoks/VideoResearchPro/pull/406)) and its review fixes, not ruled by the owner. Point 1 departs from [D-125](#d-125--a-knowledge-reports-depth-applies-d-064-without-a-bracket-and-belongs-to-the-shared-artifact-and-a-failed-synthesis-never-reaches-it-2026-11-04)'s cap for Q&A, so the owner may want to rule on it (OQ-29).

**Context.**
- Brief is 4,500 × 0.45 = 2,025 tokens, every provider counts thinking inside `max_tokens`, and the reserve figure for medium is 4,096. On `claude-sonnet-5:medium` nothing refuses 2,025, so thinking eats the answer; a Claude model on legacy thinking is refused outright. This is shown by arithmetic. No live call was made, and how often it happened is unmeasured.
- D-125 caps a lifted budget at the unset budget. A knowledge report's reserve fits under that cap (3,600 + 4,096 is under 8,000). Q&A's does not: the unset figure is 4,500 from a `large` corpus up.
- A Regenerate is metered, and on a short source Standard's ceiling (8,000) is barely above Brief's (7,696).
- Change detection reads its baseline from the stored exchange's references. A YouTube reference from before #397 has only `video_id`, and a non-YouTube one has no id at all.
- `POST /library/qa/clarify` sends only the question to the model, and "Skip clarifications" appears only after clarify succeeds.

**Decision.**
1. **Q&A brief keeps the whole thinking reserve on top of a budget the multiplier shrinks, with no cap.** `qa_agent._answer_budget` sits in `_answer_policy`, so job, library and shelf answers all get it. Brief on the default model is 6,121 on every corpus size, and 2,025 with reasoning off. Unset, standard and deep do not move. So on a thinking model brief's ceiling sits above standard's (4,500). It is a ceiling, not a length: the brief does the shortening ([D-062](#d-062--report_compose-upgraded-to-claude-opus-5-2026-07-31)).
2. **The cut-off note offers Deep, not the next step up,** because stepping up risks paying twice.
3. **A citation that names no document means no citation vote.** A new `decided_by` value, `embedding_only`, with a null `jaccard`. The embedding alone decides whether to ask the judge, and a failed judge stays quiet. It happens once, because that run's answer becomes the next baseline.
4. **Clarify has one route for library and shelf.** It reads no scoped data, so a shelf route would add surface and no protection. Its 400 tokens are the reply's share, with the thinking reserve on top.
5. **On the shelf, clarifying is optional.** A failed clarify becomes a direct ask with no context, and the reader sees the failure toast, then the answer.

**Alternatives considered.**
- *Cap at the unset budget, as D-125 does.* This PR's first version. From a large corpus up it leaves 404 tokens for a 2,025 answer after a full 4,096 of thinking.
- *Read the finish reason instead of lifting the budget.* That reports a cut answer without preventing one (T-1.15.4.5).
- *A shelf clarify route.* A foreign shelf id never reaches this one, so a second route protects nothing.
- *Let a failed clarify stop the shelf ask.* A shelf ask worked before this step existed, and an outage in an optional step must not stop it.

**Consequences.**
- Standard and unset keep their exposure: on the default model, from a `large` corpus up, a full 4,096 of thinking leaves 404 tokens (OQ-29). The spec keeps unset byte-identical.
- No migration, data write or new setting. `_report_cut_off` sits in `extracted_knowledge_json`, and `report_cut_off` is `false` on older reports.
- A shelf-scoped baseline from before #397 may lack a PDF the old check dropped. That PDF reads as added once, and unless the answer's embedding moved too, the judge decides.
- `POST /library/qa/clarify` now runs on the asker's key. The job route had the same gap, closed by [D-138](#d-138--code-attempts-count-on-a-shared-row-sockets-end-with-their-session-one-reader-takes-the-client-address-from-the-right-and-a-rotated-key-is-reported-2026-11-05).
- Left open: the library page still stops at a failed clarify ([S-8.13.3](initiatives.md#s-8133--the-library-page-stops-at-a-failed-clarify)), a cut answer is stored silently (T-1.15.4.5), and the shelf panel has no depth select (T-1.15.4.6). The Q&A brief has not run on a live model (T-1.15.3.6).

**Linked initiatives / PRs.** E-1.15 (T-1.15.3.6 to T-1.15.3.8, T-1.15.4.4 to T-1.15.4.6, OQ-29), E-8.3 (T-8.3.3.10), E-8.13 ([S-8.13.2](initiatives.md#s-8132--a-clarify-step-on-the-shelf-panel), [S-8.13.3](initiatives.md#s-8133--the-library-page-stops-at-a-failed-clarify)); PR [#406](https://github.com/khoks/VideoResearchPro/pull/406); [D-062](#d-062--report_compose-upgraded-to-claude-opus-5-2026-07-31), [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19), [D-125](#d-125--a-knowledge-reports-depth-applies-d-064-without-a-bracket-and-belongs-to-the-shared-artifact-and-a-failed-synthesis-never-reaches-it-2026-11-04).

**Status-changed 2026-11-05:** the items left open here are closed: a cut answer is noticed, the shelf has a depth select, and a failed clarify no longer blocks the library page ([D-145](#d-145--a-cut-off-flag-is-a-fact-about-one-reply-the-offer-keeps-the-cards-scope-and-the-server-never-applies-the-accounts-default-depth-2026-11-05), T-1.15.4.5, T-1.15.4.6, S-8.13.3, PR [#419](https://github.com/khoks/VideoResearchPro/pull/419)). OQ-29 stays the owner's.

**Status-changed 2026-11-09:** how often answers are cut is still unmeasured, but every new exchange now stores what the check found, `false` included, so it can be measured ([D-150](#d-150--the-cut-off-flag-is-stored-as-what-the-check-found-a-cut-answer-is-never-a-saved-searchs-baseline-and-a-cut-first-answer-stands-in-on-the-card-2026-11-09), T-1.15.4.8, PR [#426](https://github.com/khoks/VideoResearchPro/pull/426)).

## D-133 — The tagger abstains without Hindi evidence, the presence floor reads grammar, an offline lexicon sees English in Devanagari, and scores are quoted from the production row (2026-11-04)

**Status:** accepted (2026-11-04). Made while building T-1.16.2.15, T-1.16.2.8, T-1.16.1.10, T-1.16.2.14 and T-1.17.3.3 (PR [#403](https://github.com/khoks/VideoResearchPro/pull/403)) and its review fixes, not ruled by the owner. Points 1 to 3 are addenda to [D-080](#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19). [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25)'s 0.6 threshold stands until T-1.16.2.7.

**Context.**
- The tagger's classes were English and everything else, so `source_note` told every model a Spanish source was "Hindi (romanised)", and `quote_mode` followed the same measure. #396's badge guard hid this from the screen, not from the prompts.
- Every Devanagari word outside a closed function-word list read as Hindi, which overstated the share that decides quoting (TEST MAE 0.204).
- Two document-level facts could reach old chunks only through a re-chunk that never re-inserts.
- The tagger must not be tuned against the labelled set's `test` split. An acceptance rule went into the PR before any change was measured, and the tagger was frozen before the held-out data was read.

**Decision.**
1. **`OTHER` refines "non-English"; it is not a third class for the policy.** `tag_tokens` abstains (`OTHER`, `xx`) on Latin text with no Hindi evidence. `shares` counts it as non-English, so a share, a rendering decision and the English rendering behave as before on any span that keeps its words, and a foreign chunk is still rendered for retrieval ([D-084](#d-084--code-mixed-retrieval-embed-an-english-rendering-keep-the-original-as-the-stored-text-2026-10-19)). On the labelled sets abstention changes the name a word gets and `named_share`, not the shares.
2. **The presence floor tells stray names from a passage by grammar.** It counts named words, unless the word share AND the grammar share both clear 3%. Requiring both keeps the old rule for a source with a few Hindi windows under the floor, which grammar alone would have changed. Chunks carry `code_mix_named_share`, because nothing else on a chunk can tell Sanskrit verse in an English talk from a Hindi clause in one.
3. **English in Devanagari is an offline lexicon plus the vowel signs ॉ ऑ ॅ,** not the hybrid LLM pass D-080 deferred. Words that are also ordinary Hindi stay out on purpose. TEST precision 0.792 to 0.940, recall stays 1.000, share MAE 0.204 to 0.051.
4. **Scoring has two rows.** `code_mixing_eval.score` reports "called Hindi by name" and "production". A figure quoted for a share or a rendering decision comes from the production row, which reads `NON_ENGLISH_TAGS`, the tuple `shares` uses.
5. **Metadata-only stamping is safe for language fields too,** and a stamped chunk's vector is unchanged. Chunks stamped this way are labelled, not rendered.

**Alternatives considered.**
- *Leave abstained words out of the share.* Spanish would read as plain English and lose D-084's rendering.
- *The hybrid LLM pass on Devanagari.* The lexicon met the rule, with no LLM on this path.
- *Grammar share alone as the floor.* It changes the rule for a source with a little Hindi.
- *Name the language.* Offline language ID has no romanised-Hindi class, and nothing here needs more than "not Hindi".
- *Clear stale chunks by default.* `--clear-stale` is opt-in because it is the only step here that removes data.

**Consequences.**
- D-080's open question 3: TEST Devanagari agreement at 0.5 / 0.6 / 0.8 was 0.912 / 0.824 / 0.647 and is 0.971 / 0.912 / 0.882. The 0.6 default now agrees with gold as often as 0.5 did before, and 0.5 still scores best by two units of 34, so the robustness argument for moving is much weaker but not gone.
- Foreign sample: 6 of 6 tuning and 5 of 5 unseen documents read `other`, and romanised Hindi controls stay Hindi. In the live library, profiled in memory, no primary language changed in 254 documents and two name-heavy English talks stop reading as code-mixed. The library holds no foreign-language transcript, so the live check shows no harm and only the fixture shows the fix.
- The PR's first claims of abstention's cost and gain were wrong, because the scorer counted only `hi`. Point 4 exists for that reason. The held-out data was read a second time after review changed the metric and five lexicon words came out; that read set nothing, and the Devanagari row did not move at the third decimal place.
- Chunks stamped by the script stay embedded as their original text (648 on a copy of the live store), because the English rendering needs the LLM and a re-embed. Nothing about what a question retrieves changes for them.
- The #396 client guard stays, narrower. Third-language labels stay for good, since only a label can name a language. The rule that `hi` on Latin text needs a supporting label can relax after the owner's refresh (T-1.16.1.11).
- Limits: a short span of unplaced names can read as a non-English grammar. Dutch gets the "partly English" hedge, because the tagger cannot tell its cognates from English. All labels are still Claude's, not a native speaker's (T-1.16.2.7). Spanish through the render prompt is unverified (T-1.16.2.17).
- Left open: stamping `code_mix_*` when a job reuses a document (T-1.16.2.16) and `language_of` in signal extraction (T-3.3.2.11).
- Owner steps, none run: four in one order, listed under [S-1.16.2](initiatives.md#s-1162--proportion-driven-rendering-for-code-mixed-speech--implements-n-002). Both `--write` backfills still wait on the owner.

**Linked initiatives / PRs.** E-1.16 (T-1.16.1.10, T-1.16.1.11, T-1.16.2.7, T-1.16.2.8, T-1.16.2.14 to T-1.16.2.17), E-1.17 (T-1.17.3.3), E-3.3 (T-3.3.2.11); PR [#403](https://github.com/khoks/VideoResearchPro/pull/403); [D-080](#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19), [D-084](#d-084--code-mixed-retrieval-embed-an-english-rendering-keep-the-original-as-the-stored-text-2026-10-19), [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25), [D-120](#d-120--older-chunks-gain-their-era-and-publish-fields-by-a-metadata-only-pass-amends-d-072-the-language-profile-is-stored-on-the-document-2026-11-04), [D-123](#d-123--unused-read-routes-are-removed-an-outputs-sources-list-groups-by-source-and-a-language-badge-names-a-language-only-on-evidence-2026-11-04).

**Status-changed 2026-11-05:** point 5 is extended. A job that reuses an embedded document now adds the document-level `code_mix_*` fields to chunks that lack them, and only the backfill rewrites a value ([D-144](#d-144--a-fifth-voice-label-other-names-no-language-to-write-in-a-job-fills-gaps-and-only-the-backfill-rewrites-and-the-declared-audio-language-is-a-key-on-the-document-2026-11-05), T-1.16.2.16, PR [#418](https://github.com/khoks/VideoResearchPro/pull/418)).

## D-134 — A live manual fact holds its key against every source, a 401 retries one call, a lease guards the refresh token, and a changed row beats a refresh answer (2026-11-04)

**Status:** accepted (2026-11-04). Made while building T-3.2.1.11, T-3.2.1.12, T-3.3.1.7 and T-3.4.1.10 (PR [#409](https://github.com/khoks/VideoResearchPro/pull/409)) and its review fixes, not ruled by the owner. It extends [D-122](#d-122--a-deleted-derived-fact-stays-deleted-per-connector-only-a-refused-refresh-asks-for-a-reconnect-restore-re-checks-the-evidence-2026-11-04) points 1 and 3.

**Context.**
- Editing a derived fact makes it `manual`, and the next sync wrote the connector's value over it under the same key. The export importer does the same upsert, so it had the same bug.
- A `manual` row gets no tombstone by itself, so a delete would have let the next sync bring the fact back.
- A rotating provider answers a second use of the old token with `invalid_grant`, and some revoke the whole grant for it, so a scheduled sync racing "Sync now" could disconnect a user for nothing. Google does not rotate, so S-3.2.2 and S-3.2.5 are not blocked by this, though they do benefit from the 401 retry.
- The full brain archive carried every column, so a rejected signal could carry a deleted source's words out in an export.

**Decision.**
1. **A live manual row wins for importers and for facts typed first, not only for edited ones.** `echo_service.record_derived_context` asks per fact at write time, so an edit made during a long sync is seen. `personal_context.wanted_by` names the connector or importer that wants the key. It is set when the user edits what a source derived and when a typed row turns a source away, so a delete tombstones that key. This refines D-122's "a fact the user typed gets none". It holds the name, as a tombstone does, because an `import:<id>` source does not outlive undoing that import.
2. **An expired manual row holds nothing.** It is gone from the list and from retrieval, so the user could not see what was blocking the connector. The connector takes the key back and clears `wanted_by`, which only a manual row carries.
3. **The 401 retry lives in `SyncContext.call`, per provider call, not around the sync pass.** The runtime cannot see individual calls and a generator cannot be resumed, so a connector opts in. One renewal per sync.
4. **The refresh claim is a lease on the credential row,** not a Redis lock or a sync-wide lock. It works in `inline` mode and in the test suite with no Redis, the row vanishes with a revoke, and the secret table is already never exported. TTL 120 s, wait 30 s.
5. **What counts as a real revocation:** a refused refresh, a 401 on a token just issued, or a 401 with nothing to renew with. D-122 point 3 said "only a refusal"; this extends it to the mid-sync case. A later 401 in the same sync is left for the next sync.
6. **A changed row beats a refresh answer.** The stored pair is compared with the pair just spent after the provider answers, and anything newer stands. The claim decides who may call the provider, not whose answer is kept. If nothing changed the answer is stored even when the claim lapsed, because a rotated token is then the only live copy. The pair, not the refresh token alone, because a provider that does not rotate can return the same refresh token on a reconnect.
7. **The brain archive filters a rejection's evidence at export time.** A second counted exception to "every column of every row", beside the open voice test ([D-127](#d-127--the-in-app-voice-test-is-a-rolled-back-what-if-on-the-echo_draft-use-case-and-an-open-tests-answers-stay-out-of-the-export-2026-11-04)). It reads at export time and writes nothing, so the words cannot leak before the sweep runs.

**Alternatives considered.**
- *Re-run the whole sync pass after a 401.* It needs no connector change but re-fetches every page, and it is not "that call".
- *A Redis lock, or a lock across the whole sync.* A Redis lock is missing in `inline` mode, and T-3.2.1.12 is about the refresh token.
- *Trust the claim alone when storing.* A reconnect during a refresh would be written over.
- *Rely on the sweep alone.* The words would leave in any export made before it ran.

**Consequences.**
- Migration `5f8caf39b5b1` holds `wanted_by`, the claim columns and `echo_drafts.model` at `String(128)`. A connector panel line and `facts_kept_manual` say when a row held its key.
- `scripts/sweep_rejected_signal_evidence.py` found 0 rejections on the owner's database, so `--write` is a no-op today.
- Left out: two concurrent syncs can still collide in `store_events` (T-3.2.1.13), and the delete dialog's "will keep it deleted" line says nothing for a manual row with `wanted_by` (T-3.2.1.14).
- Accepted limits: a process that dies between the provider's answer and the store loses a rotated token, and no client can close that gap. The compare and the write in point 6 are two steps, so a reconnect in the milliseconds between them could still be written over. `wanted_by` holds one source; no two sources share a key today. A fact typed and deleted before any source asked for its key gets no tombstone. A connector that raises a 401 outside `ctx.call` still asks for a reconnect.
- Owner step: apply the migration (a restart does) and restart the API and the worker.

**Linked initiatives / PRs.** E-3.2 (T-3.2.1.11 to T-3.2.1.14), E-3.3 (T-3.3.1.7), E-3.4 (T-3.4.1.10); PR [#409](https://github.com/khoks/VideoResearchPro/pull/409); [D-089](#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19), [D-110](#d-110--echo-only-sees-what-the-user-hands-it-no-background-capture-and-the-echo-scope-rulings-2026-10-25), [D-122](#d-122--a-deleted-derived-fact-stays-deleted-per-connector-only-a-refused-refresh-asks-for-a-reconnect-restore-re-checks-the-evidence-2026-11-04), [D-127](#d-127--the-in-app-voice-test-is-a-rolled-back-what-if-on-the-echo_draft-use-case-and-an-open-tests-answers-stay-out-of-the-export-2026-11-04).

**Status-changed 2026-11-05:** T-3.2.1.13 and T-3.2.1.14 are closed. Overlapping syncs both finish, through inserts the database decides, not the per-grant lock the follow-up suggested, and a sync can still reach the refresh claim here ([D-142](#d-142--a-draft-with-nothing-behind-it-is-refused-a-register-needs-a-saved-draft-and-overlapping-syncs-are-settled-by-the-databases-insert-2026-11-05), PR [#416](https://github.com/khoks/VideoResearchPro/pull/416)).

## D-135 — The publish window is a preference that leads the inferred profile, a window that cannot act is refused, and starters name only sources that need no search credential (2026-11-04)

**Status:** accepted (2026-11-04). Made while building S-8.6.3 and S-8.6.4 (PR [#408](https://github.com/khoks/VideoResearchPro/pull/408)) and its review fixes, not ruled by the owner. The owner's go-ahead for the window is [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25). S-8.6.4 was proposed and not agreed; it was built because batch 5's brief asked for it. Point 5 amends [D-082](#d-082--job-templates-identity-plus-immutable-versions-provenance-without-a-foreign-key-starters-in-a-self-contained-data-migration-2026-10-19), and point 6 lifts [D-033](#d-033--whisper-as-service-for-podcasts-reuse-existing-openai-whisper-path-resolves-oq-4-2026-05-03)'s known limitation. OQ-33 and OQ-34 are the owner's.

**Context.**
- D-112 accepted the window as a ranking preference, never a filter ([D-059](#d-059--selection-quotas-preferred-channel-guarantee--concentration-cap-2026-07-30), [D-072](#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19)).
- The planner's `temporal_profile` reaches the ranker through graph state, and the planner never sees the window, so the two can disagree on a `minimal` topic.
- Only YouTube results are ranked, and D-082 rejected settings that silently do nothing.
- A migration cannot vary by install, so a starter must work on a stock one. A run's budget is split in advance ([D-114](#d-114--which-sources-a-topic-run-searches-settings-decide-one-budget-for-the-run-no-whisper-before-approval-2026-10-29)), so a source that returns nothing wastes its share.
- D-114 notes that no connector had been checked live. Read-only public calls on 2026-11-04 found: Hacker News 6 for "nuclear power" and 0 for a full sentence, podcasts 6 for both, Bluesky HTTP 403 on `searchPosts`, and a Mastodon phrase returning nothing.
- The review asked what happens after approval. Of 8 live episodes, 0 published an in-feed transcript and 4 were over Whisper's 25 MB cap, and the code sent each file whole.

**Decision.**
1. **The window leads `temporal_profile` where they disagree,** because it is explicit and the profile is inferred, the order D-059 used. It stays a preference: both stay in the prompt, and a foundational older video can still win. `target_era` does not conflict, since it is what a video discusses and the window is when it was posted.
2. **A window that cannot act is refused, not ignored:** a 422 on channel and subscription runs and on topic runs without YouTube. A mixed run accepts it, and it steers the YouTube half only.
3. **The window is a frozen template field, editable on the form.** The M6 plan listed it as variable at run time; board T-8.6.3.1 says a template field, and frozen is what makes the recipe keep it. It is stored as days and turned into a date when the run ranks, so a saved recipe never goes stale.
4. **Starters name only sources that need no search credential, and only sources checked live:** `podcast-digest` (podcasts, 8, brief) and `mixed-source-debate` (YouTube, Hacker News, podcasts, 18). Reading a podcast can need more, and `job_source_types.transcription_gap` says so on `/templates`.
5. **A revision migration carries only the entries it changes, not the whole set,** which amends D-082's "copies them". Its downgrade walks the list, so a whole-list copy would delete the five built-ins the first migration owns.
6. **D-033's known limitation is lifted.** An episode over 25 MB goes through the chunked path YouTube has used since S-1.11.2 (`_transcribe_in_chunks`, moved out of `_transcribe_with_whisper` unchanged). A chunk that fails loses the episode, because a transcript with a hole would read as complete.
7. **Podcast search takes shows in turn,** because a fixed share is small and iTunes' top show should not fill it. It gives up the early stop: it always makes the three feed fetches.

**Alternatives considered.**
- *`publishedAfter` on discovery.* As a filter it breaks the ruling. An extra query that only adds candidates would not, but it costs 100 quota units per page and the brief was to thread this into ranking (OQ-33).
- *A date cut or a per-candidate marker in code.* The first is the numeric re-rank D-072 rejected, and the second means editing the line format of a hardened prompt.
- *Edit `PLAN_SEARCHES_PROMPT` so the planner sees the window.* The brief asked to avoid that, so query planning cannot lean recent.
- *Add Bluesky or Mastodon to the debate starter.* Both returned nothing in the live check.

**Consequences.**
- With no window the prompt is byte-identical, pinned by fixtures rendered from master before any change. No code reads a publish date, so the pool, the tournament, the fallback and the D-059 quotas are unchanged, and nothing can be dropped because no path can drop anything.
- A short window may have little to choose from, since discovery uses `order=relevance` (OQ-33).
- **This is new Whisper spend, not only new reach** (OQ-34). A long episode used to fail at the upload for free and now costs its full length, on any run that names podcasts. The live sample was 248 minutes for 8 episodes and 199 for 6, about $1.49 and $1.19 at D-033's 2025 price, not measured on a real run. Whisper is the main text path for these starters, not a fallback.
- Long episodes need `ffmpeg` and `ffprobe` on the worker's PATH. Without them they are skipped and `/templates` says so.
- Not measured: whether a real model honours the window line (S-1.17.4), and no real Whisper request has seen a podcast chunk. No browser check.
- Findings left open: [S-1.5.14](initiatives.md#s-1514--sources-that-quietly-return-nothing) and [S-1.7.1](initiatives.md#s-171--podcast-text-path-follow-ups).
- Owner step: restart after pulling. The API applies migrations `b84e405ab989` and `927718ee5b78` at startup, and the worker needs the new column.

**Linked initiatives / PRs.** E-8.6 ([S-8.6.3](initiatives.md#s-863--relative-publish-window), [S-8.6.4](initiatives.md#s-864--source-type-starters-podcast-digest-mixed-source-debate), OQ-33, OQ-34), E-1.7 ([S-1.7.1](initiatives.md#s-171--podcast-text-path-follow-ups)), E-1.5 ([S-1.5.14](initiatives.md#s-1514--sources-that-quietly-return-nothing)), S-1.17.2, S-1.17.4; PR [#408](https://github.com/khoks/VideoResearchPro/pull/408); [D-033](#d-033--whisper-as-service-for-podcasts-reuse-existing-openai-whisper-path-resolves-oq-4-2026-05-03), [D-059](#d-059--selection-quotas-preferred-channel-guarantee--concentration-cap-2026-07-30), [D-072](#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19), [D-082](#d-082--job-templates-identity-plus-immutable-versions-provenance-without-a-foreign-key-starters-in-a-self-contained-data-migration-2026-10-19), [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25), [D-114](#d-114--which-sources-a-topic-run-searches-settings-decide-one-budget-for-the-run-no-whisper-before-approval-2026-10-29).

**Status-changed 2026-11-05:** what PR [#408](https://github.com/khoks/VideoResearchPro/pull/408)'s live check found is closed. A failed search now says so, Bluesky works from `api.bsky.app` with no credentials, and a topic is sent in forms each service can answer ([D-141](#d-141--a-connectors-search-raises-on-failure-a-refusal-is-a-24-hour-hold-on-a-sources-own-endpoint-non-video-sources-search-before-youtube-and-a-recording-counts-once-2026-11-05), [S-1.5.14](initiatives.md#s-1514--sources-that-quietly-return-nothing), PR [#415](https://github.com/khoks/VideoResearchPro/pull/415)).

## D-136 — A book's contents take their ids from the rendered manuscript, the main chunk meets its budget with lazy Markdown and lazy routes, and the device suite's server is dual-stack (2026-11-04)

**Status:** accepted (2026-11-04). Made while building T-8.8.4.2, T-8.8.4.5, T-8.8.4.6, T-8.8.4.7 and T-3.7.3.4 (PR [#410](https://github.com/khoks/VideoResearchPro/pull/410)) and its review fixes, not ruled by the owner.

**Context.**
- The bug T-8.8.4.2 described was already fixed by T-6.1.4.4. Testing against real rendered ids found three that remained. The id scan read `body` element by element and a whole chapter is one element, so the book's Conclusion linked to a report's. Typed titles such as `a ] b` broke links. The reader dropped the book's title before slugging, so a book called "Introduction" disagreed with its EPUB.
- Lazy Markdown alone left the main chunk at 211.51 kB gzip, against a 170 kB budget.
- Without bold in the fallback, the 320 px job Q&A baselines failed about 14 px off, because bold text wraps differently.
- A Chromium NetLog of the refused connection shows Windows now and then failing a connect to `[::1]` outright (`WSAEADDRINUSE`, or `WSAENOBUFS`). Chromium correctly moves to `localhost`'s other address, and with Vite on one family nobody is there.

**Decision.**
1. **A book's contents take their ids from rendering the manuscript, not from slugging titles,** keyed by source line (`Heading.line`), so they cannot drift from it. Typed titles are written as literal Markdown. The EPUB knows the book's own contents and endnotes by text and place (the first and last `h2`), because an `h2` of either name elsewhere is a chapter's own text. An answer's headings sit below the chapter's, so a stored answer cannot add a chapter.
2. **The main-chunk budget is met by lazy Markdown with a same-elements text fallback, plus lazy routes for occasional pages.** New page code imports `components/common/Markdown`, and a test enforces it. The fallback may lose formatting but never changes the words: a mark comes off only as half of a pair, and marks inside code are characters.
3. **The device suite's dev server is dual-stack (`--host ::`), and Playwright retries stay off.** The cause is handled, and a retry would turn a real intermittent failure into a green run.

**Alternatives considered.**
- *Keep slugging titles, in step with each renderer.* That is how the two drifted.
- *Find the EPUB's sections by id, or by text alone.* A repeated heading gets a different id, and text alone takes a chapter's own "Endnotes".
- *An IP literal as the device suite's URL.* It only relabels the failure: `127.0.0.1` alone still lost pages to `ERR_NO_BUFFER_SPACE`.
- *A lazy security page too.* `signInFlows.test.tsx` pins its route, and the budget did not need it.

**Consequences.**
- Main chunk 246.49 to 162.88 kB gzip, first paint about 317 to about 238 kB, with every device baseline unchanged. Master had grown past the 241.82 the task named. Moving between Echo or Author pages shows a brief spinner the first time in a session.
- Server on `::1` only: 6 failures in 6,514 pages. Dual-stack: 0 in 5,899, with failed connects rescued in the NetLog.
- `--host ::` listens beyond loopback for the length of a device run, so a first local run may show a Windows Firewall prompt. Denying it changes nothing for the tests. Vite's normal `npm run dev` stays on `localhost`.
- Stored books keep the contents they were written with, and the reader's repointing ([D-086](#d-086--markdown-readers-react-markdowns-own-pipeline-run-once-with-a-tree-transform-the-outline-is-the-two-shallowest-structural-heading-levels-2026-10-19)) stays for them.
- `tests/hf_offline.py` keeps the suite off huggingface.co when the model is fully cached, and T-3.7.3.4 is a test fix with no product change. Neither needed a decision of its own.
- Follow-ups: [S-8.8.6](initiatives.md#s-886--follow-ups-from-the-reader-and-test-infra-pass).

**Linked initiatives / PRs.** E-8.8 ([S-8.8.4](initiatives.md#s-884--reader-follow-ups-surfaced-while-building-e-88), [S-8.8.6](initiatives.md#s-886--follow-ups-from-the-reader-and-test-infra-pass)), E-3.7 (T-3.7.3.4), E-6.1 (T-6.1.4.4); PR [#410](https://github.com/khoks/VideoResearchPro/pull/410); [D-085](#d-085--reading-room-reports-stay-html-sanitised-and-parsed-in-the-browser-one-shared-citation-card-fed-by-the-runs-documents-2026-10-19), [D-086](#d-086--markdown-readers-react-markdowns-own-pipeline-run-once-with-a-tree-transform-the-outline-is-the-two-shallowest-structural-heading-levels-2026-10-19).

**Status-changed 2026-11-05:** three of the follow-ups in [S-8.8.6](initiatives.md#s-886--follow-ups-from-the-reader-and-test-infra-pass) are closed ([D-147](#d-147--the-rendering-parser-decides-what-is-a-heading-in-book-markdown-a-rewrite-parses-what-it-will-emit-and-the-suites-tiktoken-file-lives-at-a-fixed-path-2026-11-05), PR [#421](https://github.com/khoks/VideoResearchPro/pull/421)). T-8.8.6.3 stays proposed.

## D-137 — A share target posts to a worker scoped to one path and waits for one tap; mail is unverified text that never trains the voice; shared links go through the public-address guard (2026-11-04)

**Status:** accepted (2026-11-04). Made while building S-3.7.6 and T-3.7.4.1 (PR [#407](https://github.com/khoks/VideoResearchPro/pull/407)) and its review fixes, not ruled by the owner. Point 1 amends [D-087](#d-087--mobile-reading-and-install-a-reading-toolbar-below-1200-px-a-docked-composer-lifted-by-visualviewport-hermetic-device-tests-a-manifest-without-a-service-worker-2026-10-19). OQ-30 to OQ-32 are the owner's.

**Context.**
- Sharing has to be as quick as the moment that prompts it, and [D-110](#d-110--echo-only-sees-what-the-user-hands-it-no-background-capture-and-the-echo-scope-rulings-2026-10-25) makes IMAP the self-host answer to email.
- A GET share target sends the words in the query string to whatever serves the app, so an access log has them before any script can run. It also carries no files.
- A share target is a form post. Any website can post it, the worker cannot see `Sec-Fetch-Site`, and a form can suppress its `Referer`, which is what the share sheet looks like. The first version posted on load with the victim's Bearer token, with no click; the review found it.
- `docs/personal-brain.md` called intake "zero approval", because the act of sharing is the curation step.
- Images shared by address had a public-address guard, and the article extractor's fetch had none.
- Mail is unauthenticated, and a From line proves nothing. Python reads `owner@x.com <evil@y.com>` as the first address while a DMARC check reads the second.

**Decision.**
1. **A POST share target with a service worker scoped to one path.** Its scope is `/echo/share-target` alone. It keeps the form in the Cache API, which both the worker and the page can reach and which holds files, and answers everything there with a redirect to `/echo/incoming`, outside the scope. So no document is ever controlled, no request of the app's goes through it, and it caches nothing for reading. That leaves D-087's reasons standing, and the device suite asserts no controller.
2. **A share from the share target needs one tap, the one approval step in Echo's intake.** Nothing proves there was an act of sharing. The tap covers the keys the page showed, not what is in the cache at that moment. The extension and the Shortcut keep adding at once, because a token in a header proves who is asking.
3. **Shared links go through the public-address guard on every share surface,** on the first address and every redirect. `extract_text` gained an optional `guard`, which walks redirects itself, and the browser fallback is skipped under a guard. The paste and connector paths pass none: they run behind a session, with no way for a stranger to start them.
4. **Mail stays retrievable in drafts, marked unverified, rather than left out,** since shares reach nothing else. A label alone cannot stop a model, so the flag is in code: a draft citing mail is flagged `unverified_source`, says so under the draft and lists the email among its sources, and citing only mail leaves it `ungrounded`.
5. **Mail can never be marked as the user's own words, even by the user.** The block is at the intake, on create and on `PATCH`, and the inbox hides the button. To count those words, the user adds them through quick share.
6. **Mail is always text, and attachments are listed, not read.** The sender is unauthenticated, so mail must not reach a code path that fetches or spends. The guard limits where a fetch goes, not whether a stranger starts one.
7. **The ledger outlives the share,** as `echo_fact_tombstones` does for facts: a deleted share stays deleted, and a re-poll adds nothing.
8. **A settings-driven schedule row is kept by the tick,** because no request ever touches it. A new `sync_schedule` runs before `run_tick`, fail-soft.
9. **A waiting share is picked up at `/` (`OnboardingGate`),** the one place every sign-in ends. A second redirect in `AppLayout` lost a race to `/submit`, which the device test caught.

**Alternatives considered.**
- *A GET share target.* See the context: no client code can undo an access log.
- *Keep posting on arrival and check the origin.* The worker cannot tell a stranger's page from the share sheet.
- *`location.replace` on the share page.* It would lose the toast and leave that page controlled.
- *Leave mail out of drafts.* The mailbox would then feed only the inbox list (OQ-30).
- *Read links and attachments in mail.* Making either work needs a sender we can trust.

**Consequences.**
- **No real phone or mailbox was available, so none of the three surfaces has run on one** (T-3.7.6.2, T-3.7.4.3). The Shortcut's steps have never run on an iPhone.
- SPF, DKIM and DMARC are not checked, and STARTTLS is not offered. `docs/echo-share-surfaces.md` states the limits and recommends a provider that rejects DMARC failures.
- The guard does not stop DNS rebinding, because the name is resolved again at fetch time. The same holds for images.
- A waiting share has no owner. Sign-out clears it, but a session that merely expired leaves it, and it is shown to whoever signs in next on that browser. It goes nowhere without their tap.
- Mail counts toward readiness domain 5, so a forged stream could fill that count. It does not reach the voice gate (OQ-32). A model can use mail without citing it, which raises no flag (OQ-30).
- Found, not fixed: `PublicOnlyRoute` races `LoginPage` (T-5.4.20), and the article extractor logs a shared URL when its fetch fails (T-3.7.2.9).
- T-3.7.4.2 stays open for SaaS. New table `echo_email_messages` (migration `c62da1d081c6`), in `ECHO_TABLES`.

**Linked initiatives / PRs.** E-3.7 ([S-3.7.4](initiatives.md#s-374--email-in-inbox), [S-3.7.6](initiatives.md#s-376--os-share-target), OQ-30 to OQ-32), S-8.12.2; PR [#407](https://github.com/khoks/VideoResearchPro/pull/407); [D-087](#d-087--mobile-reading-and-install-a-reading-toolbar-below-1200-px-a-docked-composer-lifted-by-visualviewport-hermetic-device-tests-a-manifest-without-a-service-worker-2026-10-19), [D-089](#d-089--echos-privacy-contract-context-only-by-default-the-brain-is-a-registry-the-archive-is-the-users-whole-copy-delete-in-a-fixed-order-2026-10-19), [D-110](#d-110--echo-only-sees-what-the-user-hands-it-no-background-capture-and-the-echo-scope-rulings-2026-10-25), [D-122](#d-122--a-deleted-derived-fact-stays-deleted-per-connector-only-a-refused-refresh-asks-for-a-reconnect-restore-re-checks-the-evidence-2026-11-04).

**Status-changed 2026-11-05:** point 4 now reads as a refusal. A claiming reply that cites only mail is refused, naming the email, so there is no draft for `unverified_source` to sit under ([D-142](#d-142--a-draft-with-nothing-behind-it-is-refused-a-register-needs-a-saved-draft-and-overlapping-syncs-are-settled-by-the-databases-insert-2026-11-05), T-3.4.1.11, PR [#416](https://github.com/khoks/VideoResearchPro/pull/416)). `unverified_source` still applies to a mixed draft and to a reply that claims nothing. The owner may want to rule on this (OQ-35, which touches OQ-30).

**Status-changed 2026-11-05:** point 9 stands. A share waiting behind a deep link now gets a **Review it** link on every other page, never a second redirect ([D-148](#d-148--a-401-ends-a-session-in-react-and-keeps-the-page-in-this-tab-a-waiting-share-gets-a-link-a-mutation-that-answers-its-own-failures-says-so-and-tabs-opens-on-focus-2026-11-05), T-3.7.6.3, PR [#423](https://github.com/khoks/VideoResearchPro/pull/423)).

## D-138 — Code attempts count on a shared row, sockets end with their session, one reader takes the client address from the right, and a rotated key is reported (2026-11-05)

**Status:** accepted (2026-11-05). Made while building T-5.4.16, T-5.4.18, T-5.4.19, T-5.5.8, T-5.6.10 and T-5.6.11 (PR [#411](https://github.com/khoks/VideoResearchPro/pull/411)) and its review fixes, not ruled by the owner. It builds on [D-124](#d-124--second-factor-attempts-count-on-the-ticket-one-bearer-check-for-http-and-the-socket-and-a-validation-error-never-quotes-what-was-sent-2026-11-04). T-5.4.17 and OQ-21 stay the owner's.

**Context.**
- `DELETE /auth/mfa` checks a code and takes no ticket, so a stolen session could guess at up to 6,000 a minute.
- `POST /auth/mfa/verify-enrollment` never checked `row.enabled`. On an account already on, it tested codes against the live secret with no count, and a match replaced the recovery codes.
- Pub/sub keeps nothing, so a message lost to an outage never arrives.
- The per-IP limits read `X-Forwarded-For` from any caller. uvicorn's own proxy handling is on by default for peers at 127.0.0.1 and rewrites the peer from the header before the app runs.
- `byok_context` also loads the per-user model pins, so opening it on clarify lets a pin reach that call. Claude on legacy thinking refuses a cap at or below its budget, and `handleAsk` awaits clarify with no catch, so a refusal stops the Ask button.
- A valid key that cannot read the stored secret made a TOTP code read as a wrong code.

**Decision.**
1. **The turn-off count reuses `mfa_step_tickets` under `turn-off:{user_id}`:** five per user per 15 minutes, the window fixed at the first code. The fifth miss answers 429 at once, as a ticket's does, rather than waiting for a sixth try.
2. **`verify-enrollment` refuses an enabled row outright,** with a 409, rather than taking a cap of its own. The route confirms a new secret, so an account already on has nothing to confirm.
3. **A broken key refunds only a code that cannot be a recovery code.** With the key broken only recovery codes can be checked, so an authenticator code checked nothing and its attempt goes back. A code shaped like a recovery code was checked and stays counted.
4. **Sockets end with their session by pub/sub plus a once-a-minute read of the sessions table.** The read is what makes "closes later" true. Publishes are bounded at two seconds, and closes run outside the listener loop, which carries everyone's progress.
5. **`X-Forwarded-For` is read from the right across all its lines, and a request whose every hop is trusted is the peer.** A proxy may add a line rather than extend one, so reading the first line would take the client's. `app/utils/client_ip.py` is the one reader, and the launchers pass `--no-proxy-headers`, since uvicorn's default would otherwise rewrite the peer first.
6. **`byok_context` on clarify also brings the model pins,** for every tier. Clarify ignored them until now, which goes beyond the task's wording.
7. **`max_tokens_for_reply` ignores a ceiling only at or under a Claude `budget_tokens`.** Elsewhere the ceiling holds. An unmeasured model's ceiling is 4,096, exactly the medium budget, so #406's clamp alone was still refused on `claude-opus-4-5:medium`.
8. **A stored secret that cannot be read is a subclass of the malformed-key error,** including an unset key after a restart, so the two can never be handled differently by accident. Any decrypt failure counts, and the log line names the account and no exception text.

**Alternatives considered.**
- *A new table for the count.* A migration for the same row.
- *The account lockout.* It would lock out sign-in, which the task forbids.
- *A cap of its own on `verify-enrollment`.* The route has no job on an enabled account.
- *Re-checking on the client's ping.* A client that stops pinging keeps its socket.
- *Redis keys for revoked `jti`s.* A second store of what the table already says.
- *Always clamping to the ceiling.* The refusal on every unmeasured Claude model. *Never clamping* loses #406's conservative figure for models nothing refuses.
- *Refund every 503.* A broken key would be a way round the cap. *Changing the 503's sentence* would leave users locked out of the recovery code for 15 minutes for retrying during an outage.

**Consequences.**
- **Behaviour change:** a user whose first confirm succeeded but whose response was lost can no longer get recovery codes by confirming again (409). They turn two-step off and set it up afresh. That retry only ever worked because of the bypass.
- A password holding a NUL is a fixed 400 on register and reset, checked first so the reset code is not spent, and a plain 401 at login that logs nothing.
- Sign-in still spends a ticket attempt on a 503, because a dead ticket costs one password step and the next ticket takes the recovery code.
- A socket whose token expires while open stays open (T-5.4.21). No re-check runs right after the handshake; the one-minute read covers that gap.
- `max_output_for` still gives an unmeasured model 4,096, so an answer-path pin of `claude-opus-4-5:medium` gets a cap equal to its budget (S-1.14.22). It predates this PR.
- Not checked: a real reverse proxy, a real provider refusing a user's key, a real Claude refusal (no paid calls), and the 429 sentence, the 409 path and the reset page in a browser.
- Owner step: `./scripts/restart_services.ps1`. Set `TRUSTED_PROXY_IPS` only if the install ever sits behind a proxy; unset there, every user shares one address and one per-IP limit.

**Linked initiatives / PRs.** E-5.4 (T-5.4.16 to T-5.4.19, T-5.4.21), E-5.5 (T-5.5.8, T-5.5.9), E-5.6 (T-5.6.10, T-5.6.11, OQ-21), S-1.14.22; PR [#411](https://github.com/khoks/VideoResearchPro/pull/411); [D-043](#d-043--single-shared-fernet-key-for-all-encrypted-at-rest-credentials-2026-05-05), [D-119](#d-119--usage-is-metered-at-a-scope-that-names-the-tenant-and-written-in-a-session-of-its-own-2026-11-04), [D-124](#d-124--second-factor-attempts-count-on-the-ticket-one-bearer-check-for-http-and-the-socket-and-a-validation-error-never-quotes-what-was-sent-2026-11-04), [D-125](#d-125--a-knowledge-reports-depth-applies-d-064-without-a-bracket-and-belongs-to-the-shared-artifact-and-a-failed-synthesis-never-reaches-it-2026-11-04).

**Status-changed 2026-11-05:** T-5.4.21 and T-5.5.9, left open here, shipped in PR [#420](https://github.com/khoks/VideoResearchPro/pull/420) ([D-143](#d-143--the-apis-content-security-policy-is-locked-by-default-oauth-redirects-are-compared-as-origins-a-socket-ends-at-its-tokens-expiry-and-a-shared-link-is-logged-by-host-alone-2026-11-05)): a socket closes when its token expires, and IPv6 callers and a port in the header are read as the board asked.

## D-139 — Alembic uses the URL a caller names, else the setting, and `alembic.ini` holds none (2026-11-05)

**Status:** accepted (2026-11-05). Made while building T-2.6.7, T-4.11.1.4 and T-4.11.1.5 (PR [#412](https://github.com/khoks/VideoResearchPro/pull/412)) and its review fixes, not ruled by the owner. It amends the table in [D-032](#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03)'s runbook; D-032's reasoning, an operator-coordinated rename, stands.

**Context.**
- `backend/alembic.ini` repeated `DATABASE_URL`, and `backend/alembic/env.py` never read settings. After a rename by the runbook's section B, a manual `alembic upgrade head` built an empty database at the old path and reported success.
- The app's startup and every migration test name a URL, and some of those tests downgrade to base.
- `./venv/Scripts/alembic`, the command in the README, could not run at all: it ended in `ModuleNotFoundError: No module named 'app'`, because the console script does not put the working directory on `sys.path`.
- [D-129](#d-129--drift-tests-hold-the-docs-to-the-code-the-repo-has-one-env-template-and-the-anchor-checker-writes-only-when-told-to-2026-11-04) point 4 marked seven settings nothing reads, leaving their removal to its own PR.

**Decision.**
1. **The URL a caller names wins, else `settings.DATABASE_URL`.** The caller's has to win, or those tests would run against whatever `DATABASE_URL` points at.
2. **`alembic.ini` holds no URL.** A `sqlalchemy.url` line an operator adds still wins, and section B of the runbook tells them to delete it and adds `alembic current` as a check.
3. **`prepend_sys_path = .` and `path_separator = os` go in the ini,** so the documented command runs.
4. **The unread settings are settled one by one.** `MAX_VIDEOS_PER_JOB`, `MAX_REPORT_WORDS`, `LLM_MAX_CONTEXT_TOKENS` and `OAUTH_REDIRECT_BASE_URL` are removed, and an `.env` that still sets one starts, because `model_config` has `extra: ignore`. The two `OAUTH_GOOGLE_CONNECTOR_*` settings and `TWITTER_REPLY_DEPTH_DEFAULT` stay, marked reserved.

**Alternatives considered.**
- *A note in the runbook,* the task's wording. It leaves two copies of one value in a tracked file an operator would have to keep editing, and the failure is silent.
- *Settings always win.* See point 1.
- *Run Alembic from the launchers.* They run none: migration happens in the API's lifespan, which always named its URL.
- *Wire up `TWITTER_REPLY_DEPTH_DEFAULT` here.* It adds a paid X API call per fetched tweet and cannot be tested without a token, so it is a spending choice for the owner (T-1.5.10.3).

**Consequences.**
- No owner step. The owner's `DATABASE_URL` equals the old `alembic.ini` value (compared without printing it), so `alembic` keeps migrating the same file, and their `.env` sets none of the seven.
- New drift tests hold `docs/ui-pages.md`'s route table to the router both ways, and read claims about tenancy, scheduler kinds and the Echo graph against the code. `test_the_test_count_is_what_the_suite_collects` compares CLAUDE.md's figure with a full run, and fails on purpose once the suite reaches 4,900, naming the docs to update.
- The audit documented these gaps as they are and fixed none of them: [S-4.11.2](initiatives.md#s-4112--gaps-the-docs-audit-documented-and-did-not-fix), no scheduled channel sync ([S-8.3.4](initiatives.md#s-834--scheduled-channel-sync)), and two speak-as-me rules never built (T-3.4.1.11).
- `docs/requirements.md` NFR-7.1 now names the nine tables that key on `user_id` alone, so that retrofit is stated for SaaS.

**Linked initiatives / PRs.** E-2.6 (T-2.6.7), E-4.11 (T-4.11.1.4, T-4.11.1.5, [S-4.11.2](initiatives.md#s-4112--gaps-the-docs-audit-documented-and-did-not-fix)), [S-8.3.4](initiatives.md#s-834--scheduled-channel-sync), T-1.5.10.3, T-3.4.1.11; PR [#412](https://github.com/khoks/VideoResearchPro/pull/412); [D-032](#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03), [D-129](#d-129--drift-tests-hold-the-docs-to-the-code-the-repo-has-one-env-template-and-the-anchor-checker-writes-only-when-told-to-2026-11-04).

**Status-changed 2026-11-05:** every gap in [S-4.11.2](initiatives.md#s-4112--gaps-the-docs-audit-documented-and-did-not-fix) is closed, in PRs [#414](https://github.com/khoks/VideoResearchPro/pull/414), [#419](https://github.com/khoks/VideoResearchPro/pull/419) and [#420](https://github.com/khoks/VideoResearchPro/pull/420), and both speak-as-me rules are built (T-3.4.1.11, PR [#416](https://github.com/khoks/VideoResearchPro/pull/416)). [S-8.3.4](initiatives.md#s-834--scheduled-channel-sync) stays proposed. The drift test on the test count fired as designed, and the docs now say 4,900+.

## D-140 — A sign-in makes one redirect, the query cache ends with the session, the error screen replaces the page, and signed-out pricing leads to Free (2026-11-05)

**Status:** accepted (2026-11-05). Made while building T-5.4.20, T-4.11.2.3 and T-4.11.2.5 (PR [#414](https://github.com/khoks/VideoResearchPro/pull/414)) and its review fixes, not ruled by the owner. Point 7 follows [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)'s honest pricing page.

**Context.**
- Setting the token made `PublicOnlyRoute` send the reader to `/` while `LoginPage` was navigating to `from`, so `state.from` was not reliably honoured. OAuth lost `from` at the provider.
- Honouring `from` reliably makes two things real that the race used to hide. A sign-out could leave its page in `state.from`, so the next account to sign in would land on it. The marketing header's **Sign in** passed its own page, so a sign-in begun on `/landing` or `/pricing` would end back there, past the onboarding gate.
- A sign-out in another tab reaches this tab only as a storage event, and this tab kept the last account's data in its query cache.
- In the OAuth callback the router commits the address change after `navigate` returns, so a fast token could beat the restored `from`.
- The eager pages had no error boundary, so a render error landed on React Router's default screen.
- `/register?intent=<tier>` was read by nothing, and a paid card's "Sign up for Pro" made a Free account.

**Decision.**
1. **A sign-in makes one redirect, from `PublicOnlyRoute`.** The sign-in pages only set the token, and `from` keeps its query and fragment. The OAuth exchange waits for the router's commit.
2. **A sign-out leaves no `from`, in this tab or another.** `AuthProvider` knows a session ended while the tab was open (`signedOut`), and `ProtectedRoute` then carries no page. A 401 in another tab counts as a sign-out, since this tab cannot tell the two apart, so such a tab loses its page on the next sign-in.
3. **The marketing pages' Sign in carries no page, and Open app goes to `/`,** so the onboarding gate decides both ways in.
4. **OAuth keeps the page in this tab's `sessionStorage` for the trip.** A provider's answer on a `/callback` address is never stored, so such a page comes back bare, as it did before.
5. **The query cache ends with the session, in `AuthProvider`.** Any change from a token to none clears it, which replaces the clear in `AppLayout`'s sign-out button. `AuthProvider` must therefore sit under `QueryClientProvider`, as it does in `App.tsx`. It is the same place the socket closes, for the same reason. The clear fires only on the change, because a page opened signed out has public queries that start before the effect runs.
6. **The error screen replaces the page.** One root `errorElement`, `RouteError`, covers every route, shows nothing of the error and sends it to the console. Lazy routes keep `RouteLoadError` inside the layout.
7. **Signed-out pricing cards all lead to Free.** The links drop `?intent=`, the paid cards read **Start on Free**, and the page's note says the operator changes plans.

**Alternatives considered.**
- *Wrapping the layout's children in the error element.* It would keep the sidebar on an eager page's crash, at the cost of re-indenting a route table parallel branches were editing.
- *Reading `?intent=` on the register page.* It needs new copy for a choice that does nothing yet. Dropping the parameter alone would have left a "Sign up for Pro" button that makes a Free account, so that label went too.

**Consequences.**
- A session that expires while a page is open still ends at `/`, because the 401 interceptor does a hard redirect to `/login` with no `from` (T-5.4.22). This is probably the most common real deep link.
- `/register` does not carry `from`, so a new account goes to `/` and the wizard opens.
- With a deep link while a share is waiting, the reader goes to the deep link and the share waits up to 24 hours for the next visit to `/` (T-3.7.6.3).
- Four context tests now mount `AuthProvider` under `QueryClientProvider`.
- No device baseline changed, and there is no owner step.

**Linked initiatives / PRs.** E-5.4 (T-5.4.20, T-5.4.22), [S-4.11.2](initiatives.md#s-4112--gaps-the-docs-audit-documented-and-did-not-fix) (T-4.11.2.3, T-4.11.2.5), E-2.2 (T-2.2.1 to T-2.2.5), T-1.5.13.5, T-6.1.3.7, T-6.7.1.7, T-7.1.1.6; PR [#414](https://github.com/khoks/VideoResearchPro/pull/414); [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25), [D-112](#d-112--the-remaining-rulings-of-2026-10-25-map-batching-public-sharing-the-code-mixing-threshold-and-the-quick-calls-2026-10-25).

**Status-changed 2026-11-05:** the consequence about T-5.4.22 is amended. A 401 no longer reloads the page: it ends the session in React, and the tab that met it keeps its page through the sign-in. Point 2 stands for other tabs (OQ-41). A share waiting behind a deep link now gets a link on other pages (T-3.7.6.3). Both in [D-148](#d-148--a-401-ends-a-session-in-react-and-keeps-the-page-in-this-tab-a-waiting-share-gets-a-link-a-mutation-that-answers-its-own-failures-says-so-and-tabs-opens-on-focus-2026-11-05), PR [#423](https://github.com/khoks/VideoResearchPro/pull/423).

## D-141 — A connector's search raises on failure, a refusal is a 24-hour hold on a source's own endpoint, non-video sources search before YouTube, and a recording counts once (2026-11-05)

**Status:** accepted (2026-11-05). Made while building S-1.5.14, T-1.5.13.6 and T-1.7.1.1 to T-1.7.1.3 (PR [#415](https://github.com/khoks/VideoResearchPro/pull/415)) and its review fixes, not ruled by the owner. Point 2 reverses the connectors' "degrade to an empty list" contract, and points 4 to 6 change what [D-114](#d-114--which-sources-a-topic-run-searches-settings-decide-one-budget-for-the-run-no-whisper-before-approval-2026-10-29)'s split does with a share a source cannot fill. OQ-33 and OQ-34 stay the owner's.

**Context.**
- A run's budget is split in advance, so a source that returned nothing wasted its share, and the run read as "no results" whether the service had refused or the topic was thin. [D-135](#d-135--the-publish-window-is-a-preference-that-leads-the-inferred-profile-a-window-that-cannot-act-is-refused-and-starters-name-only-sources-that-need-no-search-credential-2026-11-04) found this in PR [#408](https://github.com/khoks/VideoResearchPro/pull/408)'s live check and left it open.
- Bluesky, Mastodon, X, Brave and iTunes swallowed failures. Reddit and Hacker News raised, but only the log heard about it. YouTube's `_run_broad_searches` swallowed refusals too, so a spent quota read as "no candidates".
- `public.api.bsky.app` refuses `searchPosts` at its CDN: HTML 403, any user agent, while its other endpoints answer. `api.bsky.app` answered all four endpoints the connector uses, with no credentials.
- Since PR [#408](https://github.com/khoks/VideoResearchPro/pull/408) Whisper is the main text path for podcasts. `WHISPER_MAX_PER_JOB` counts recordings, not minutes, and `fetch_audio` held a whole enclosure in memory.

**Decision.**
1. **The default Bluesky base moves to `api.bsky.app`.**
2. **A connector's `search()` raises on failure.** An empty list means nothing was found. The dispatcher already isolated failures, so swallowing them protected nothing.
3. **A refusal is a 24-hour hold, off the form but not refused by the API.** A hold is one run's evidence, so a saved recipe loses a share and gets a note, not a 422. It sits in a table so it survives a restart and tests stay isolated. It ends early on a settings change, which is how credentials arrive, or when a search answers.
4. **Non-video sources search before YouTube,** so a top-up is a bigger target on YouTube's one search.
5. **Sources are asked for the whole budget,** since the search costs the same. X is the exception (`METERED_SOURCE_TYPES`): it bills by what a search reads, so it is asked for its share alone and never takes spare budget.
6. **The YouTube top-up is all or nothing against the ceiling,** not an estimate, because a limit should be checked against the worst case. If the ceiling does not fit in what is left of `YOUTUBE_DAILY_QUOTA`, YouTube keeps its share and the run says so.
7. **A recording counts as the larger of its declared length and its transcript's end,** never from the usage meter ([D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)) and never the sum of its chunks, so a split file counts once and overlaps are not counted twice.
8. **The minute cap applies to subscription jobs too,** which reach the longest audio of any job.
9. **A hold is for a source's own search endpoint, not for a target of it.** A hold reaches every tenant, so one user's topic must not be able to start one. `SearchFailed` is how a connector says so, and it is also how the agent marks YouTube being out of reach, so the job can tell that from its own model failing.
10. **On a mixed run a model failure in the search agent costs YouTube's half, not the run.** With nothing else found the failure stays the run's own, so the reader keeps its real reason.

**Alternatives considered.**
- *A credentials path for Bluesky.* It cannot be verified here, and the live check showed none is needed.
- *A second agent run for a top-up.* It would double the LLM spend and the quota.
- *Refusing a held source at `POST /jobs`.* See point 3. *Holding in Redis.* It would not survive a restart.
- *Catching any exception from the agent and classifying it.* An LLM SDK's 401 carries a `.response` and would read as YouTube refusing.

**Consequences.**
- A run where every source fills its share costs what it did. A top-up usually costs about 100 units per 10 extra videos, with a ceiling of 600 up to 16 videos and 1,200 past that, plus 2 to 4 units of enrichment. The check reads the Redis daily counter, which reads as 0 if Redis is down; YouTube's own quota error still stops the search then.
- The live counts are recall, not relevance: a Mastodon hit for the tariffs topic can come from one hashtag. The reader still approves what the run keeps.
- `api.bsky.app` was checked only from this machine, and Bluesky does not promise unauthenticated search on either host. If it starts refusing, the run says so and the form holds it.
- Reddit, X and Brave still get the topic verbatim, since none could be checked live (T-1.5.14.5). A hold cannot be cleared by hand, except by changing a setting or waiting (T-1.5.14.6).
- A transcription that fails part-way is not charged to the minute cap, though its finished chunks were billed (T-1.7.1.5).
- Streaming removes the memory limit that used to stop a runaway download, so `fetch_audio_to_file` has a new 1 GB ceiling (`AUDIO_MAX_BYTES`, about 50 hours of speech).
- PR [#415](https://github.com/khoks/VideoResearchPro/pull/415) left `WHISPER_MAX_PER_JOB` off subscription jobs on purpose. **That no longer holds:** [D-146](#d-146--a-pool-never-carries-the-session-max_concurrent_jobs-is-per-user-a-key-check-says-good-or-bad-only-when-the-provider-did-and-whispers-key-and-count-hold-on-every-sync-2026-11-05) point 5 applies it to every sync the same day, and the owner has yet to confirm it (OQ-36).
- Found on the way: a topic run with preferred channels could not be read back, since PR [#189](https://github.com/khoks/VideoResearchPro/pull/189) (T-1.5.14.4).
- Not checked: a browser look at the form or the job page, a real Whisper request, and any call to Reddit, X or Brave.

**Linked initiatives / PRs.** E-1.5 ([S-1.5.14](initiatives.md#s-1514--sources-that-quietly-return-nothing), T-1.5.13.6), E-1.7 ([S-1.7.1](initiatives.md#s-171--podcast-text-path-follow-ups)), OQ-33, OQ-34, OQ-36; PR [#415](https://github.com/khoks/VideoResearchPro/pull/415); [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25), [D-114](#d-114--which-sources-a-topic-run-searches-settings-decide-one-budget-for-the-run-no-whisper-before-approval-2026-10-29), [D-135](#d-135--the-publish-window-is-a-preference-that-leads-the-inferred-profile-a-window-that-cannot-act-is-refused-and-starters-name-only-sources-that-need-no-search-credential-2026-11-04), [D-146](#d-146--a-pool-never-carries-the-session-max_concurrent_jobs-is-per-user-a-key-check-says-good-or-bad-only-when-the-provider-did-and-whispers-key-and-count-hold-on-every-sync-2026-11-05).

**Status-changed 2026-11-09:** point 3 is extended: a held source chosen on the form is tried, and its own answer ends or renews the hold, so **Try X anyway** is the manual way to clear one (T-1.5.14.6). Point 7 is extended: a recording Whisper finished only part of counts once, at its reach on the timeline, through `TranscriptionCutShort` (T-1.7.1.5). Both in [D-149](#d-149--fetch_text-may-raise-transcriptioncutshort-a-sync-reads-only-what-the-library-lacks-the-job-limit-never-refuses-a-subscribe-and-a-held-source-can-be-tried-anyway-2026-11-09), PR [#424](https://github.com/khoks/VideoResearchPro/pull/424). Podcast logs name the host alone ([D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09), T-1.7.1.6, PR [#425](https://github.com/khoks/VideoResearchPro/pull/425)).

**Status-changed 2026-11-09:** point 2 is refined. A connector's HTTP client retries once after 1 s on a transient error before its search raises, and never on a 401 or 403, so a refusal reaches the hold once. X is retried only when it never answered ([D-154](#d-154--a-posts-id-dates-it-a-placeholder-date-is-no-date-a-connector-request-gets-one-retry-and-xs-only-when-unanswered-and-the-x-token-line-reports-configuration-only-2026-11-09), T-1.5.11.2, PR [#431](https://github.com/khoks/VideoResearchPro/pull/431)).

## D-142 — A draft with nothing behind it is refused, a register needs a saved draft, and overlapping syncs are settled by the database's insert (2026-11-05)

**Status:** accepted (2026-11-05). Made while building T-3.2.1.13, T-3.2.1.14 and T-3.4.1.11 (PR [#416](https://github.com/khoks/VideoResearchPro/pull/416)) and its review fixes, not ruled by the owner. Point 2 supersedes [D-102](#d-102--speak-as-me-two-switches-guards-in-code-the-reply-in-the-users-language-2026-10-20)'s "flagged `ungrounded`"; D-102's other points stand, including an advisory critic. Point 3 reads [D-137](#d-137--a-share-target-posts-to-a-worker-scoped-to-one-path-and-waits-for-one-tap-mail-is-unverified-text-that-never-trains-the-voice-shared-links-go-through-the-public-address-guard-2026-11-04) point 4 as a refusal, and the owner may want to rule on it (OQ-35). Point 6 narrows D-102's "a stopped draft is not counted". Speak as me is off on this install, so nothing here changes anything live.

**Context.**
- Two overlapping syncs of one grant could collide on a unique key, and the second showed "Sync failed: IntegrityError" until the next sync. `record_context` has the same check-then-insert and its own unique key, and a first sync writes both, so closing only `store_events` would have moved the failure one line down.
- The delete dialog read `source`, so it said nothing for a `manual` row that has `wanted_by`, though the row still landed under "Kept deleted". The revoke dialog had the same gap.
- Two Domain 4 rules in `docs/personal-brain.md` were never built: a register needs an earlier approved draft, and a draft with nothing behind it is refused rather than flagged. T-3.4.1.11 said to build them or drop them.
- Readiness needs 30 facts and a nearest-six always fills up, so with no distance cut on facts the stop before the model could not fire for anyone ready to draft.

**Decision.**
1. **Overlapping syncs are closed by inserts the database decides, not by a sync lease.** `database.insert_if_absent` runs `INSERT ... ON CONFLICT DO NOTHING`, and an event the other sync stored first counts as unchanged, so each event is counted once.
2. **A draft with nothing behind it is refused,** with `409 ungrounded`. It covers a question, opinion or recommendation, and any message the classifier could not read. It stops before the draft model when retrieval found nothing usable, and at finalize when the draft cites nothing usable. Nothing is stored, and no field gets past it. The words name the reason, because each has its own remedy: `nothing`, `mail_only`, `uncited`, `unread`, `unreachable`.
3. **[D-137](#d-137--a-share-target-posts-to-a-worker-scoped-to-one-path-and-waits-for-one-tap-mail-is-unverified-text-that-never-trains-the-voice-shared-links-go-through-the-public-address-guard-2026-11-04) point 4 now reads as a refusal.** It says citing only mail "leaves it `ungrounded`", which this reads as "mail grounds nothing", not as a ruling that such a draft must be delivered. The refusal names the email when only mail was found. `unverified_source` still applies to a mixed draft and to a reply that claims nothing.
4. **A first draft in a register needs a go-ahead.** The doc's rule cannot be met as written, because no draft can be approved before the first exists. A first draft stops with `409 register_needs_approval` before any model call. `acknowledge_register` names the register and covers one draft: it lasts through a private-name stop and nothing else.
5. **"Approved" means a saved version,** the only approval the app records, even one the user rewrote completely. Deleting that draft withdraws the approval.
6. **A refusal the model wrote counts against the daily cap; one stopped before the model does not.** A refusal after drafting costs what a draft costs, and not counting it would leave that spend uncapped.
7. **A failed classifier fails closed.** Its `other` default would otherwise wave a draft through with no flag, and retrying costs little.
8. **The dialog reads a server field,** `kept_deleted_by`, from `connector_for_fact`, the function the delete itself uses, so the two cannot disagree. The raw `wanted_by` stays on the server.
9. **Facts, shares and past answers are cut in the retrievers, at `RAG_DISTANCE_THRESHOLD`, with no new setting.** The cut is on what reaches the model, so an off-subject fact can neither fill the prompt nor be cited as backing.
10. **A reply that needs backing and cites nothing always gets a revise round,** whatever the critic scored or if the critic failed. That raises the most a refusal can cost to that of a full run, and that is what the cap charges.

**Alternatives considered.**
- *A per-grant sync lease.* It needs two columns, a TTL a long backfill can outlive (so a heartbeat) and a new "skipped" outcome, and it would stop [D-134](#d-134--a-live-manual-fact-holds-its-key-against-every-source-a-401-retries-one-call-a-lease-guards-the-refresh-token-and-a-changed-row-beats-a-refresh-answer-2026-11-04)'s refresh claim being reached by a sync at all. The insert needs no schema change and also covers the importer and share writers, which have no grant to lease.
- *Dropping the two rules from the spec.* T-3.4.1.11 allowed it, and no later decision contradicts either rule.
- *A client copy of the dialog's rule.* It could disagree with the delete.

**Consequences.**
- No real model ran. How often a real draft cites nothing, and so how often this refuses, is unmeasured (T-3.4.1.14). The distance cut was checked on 12 synthetic facts against 9 topics with the real embedder: on-subject 0.21 to 0.54, off-subject 0.68 and above, one adjacent fact passed at 0.58.
- A `social` or `request` reply also loses off-subject facts from its prompt.
- "Whatever fits" names no register and nothing checks the register a draft came out in, so the rule gates a named register only (T-3.4.1.12). The bubble sends none.
- `request`, `social` and `other` replies stay ungated, so "every factual claim ties to a source" is not fully enforced (T-3.4.1.13). A model can still lean on an item without citing it, as D-137 notes for mail.
- A draft whose only cited sentence is cut by the verbatim guard at finalize is refused as `uncited` with no further revise round. A store that answers `count()` but fails `query()` still reads as `nothing`.
- Two overlapping syncs still each call the provider, which is harmless and rare.
- `globalErrorToastMessage` skips the three stops the panel shows, which also stops the private-name stop doubling. `daily_cap` still shows two toasts (T-3.4.1.15).

**Linked initiatives / PRs.** E-3.2 (T-3.2.1.13, T-3.2.1.14), E-3.4 (T-3.4.1.11 to T-3.4.1.15), OQ-30, OQ-35; PR [#416](https://github.com/khoks/VideoResearchPro/pull/416); [D-102](#d-102--speak-as-me-two-switches-guards-in-code-the-reply-in-the-users-language-2026-10-20), [D-134](#d-134--a-live-manual-fact-holds-its-key-against-every-source-a-401-retries-one-call-a-lease-guards-the-refresh-token-and-a-changed-row-beats-a-refresh-answer-2026-11-04), [D-137](#d-137--a-share-target-posts-to-a-worker-scoped-to-one-path-and-waits-for-one-tap-mail-is-unverified-text-that-never-trains-the-voice-shared-links-go-through-the-public-address-guard-2026-11-04).

**Status-changed 2026-11-05:** `daily_cap` no longer shows two toasts. `useCreateDraft` answers every failure in its own `onError` and sets `meta.errorsShownHere` ([D-148](#d-148--a-401-ends-a-session-in-react-and-keeps-the-page-in-this-tab-a-waiting-share-gets-a-link-a-mutation-that-answers-its-own-failures-says-so-and-tabs-opens-on-focus-2026-11-05), T-3.4.1.15, PR [#423](https://github.com/khoks/VideoResearchPro/pull/423)).

## D-143 — The API's Content-Security-Policy is locked by default, OAuth redirects are compared as origins, a socket ends at its token's expiry, and a shared link is logged by host alone (2026-11-05)

**Status:** accepted (2026-11-05). Made while building T-4.11.2.1, T-4.11.2.2, T-4.11.2.4, T-4.11.2.7, T-3.7.2.9, T-5.4.21 and T-5.5.9 (PR [#420](https://github.com/khoks/VideoResearchPro/pull/420)) and its review fixes, not ruled by the owner. It finishes two items [D-138](#d-138--code-attempts-count-on-a-shared-row-sockets-end-with-their-session-one-reader-takes-the-client-address-from-the-right-and-a-rotated-key-is-reported-2026-11-05) left open.

**Context.**
- `docs/requirements.md` claimed a `Content-Security-Policy` and JSON logs until PR [#412](https://github.com/khoks/VideoResearchPro/pull/412) corrected it.
- `GET /auth/oauth/{provider}/start` stored whatever `redirect_uri` the caller sent, so only the provider's registered callback restricted it.
- Two libraries also wrote a shared URL to the logs: httpx at INFO, which a Celery worker keeps, and trafilatura at ERROR.
- `transformers` and `huggingface_hub` hold stderr handlers of their own, and a real model load wrote ten bare lines into a JSON stream.
- A socket whose token expired while it was open stayed open.

**Decision.**
1. **The API's CSP is default-locked, by response type and a named list.** JSON gets `default-src 'none'; frame-ancestors 'none'`, and any other response nobody named also gets `sandbox`, so forgetting a route fails shut. It is a pure ASGI middleware, outermost, so a 429 and a preflight carry it and the Q&A stream is not held. Only `/docs` and `/redoc` are buffered, to hash the page as actually sent.
2. **`sandbox` on files.** Downloads are attachments and the app shows bytes from blob: URLs, so nothing renders on the API origin, and an upload opened by hand runs nothing. A sandboxed attachment was checked to still download in Chromium.
3. **`LOG_FORMAT` is applied in `app/__init__.py`,** so a line logged during import is formatted too, and again after Alembic's `fileConfig`, which replaces the root logger's handlers in-process. Output is ASCII-escaped JSON, because a Windows log can be cp1252. An unknown value warns and reads as text, never fatal. Python warnings go through `logging.captureWarnings` under `json`.
4. **An OAuth redirect is compared as `(scheme, host, port)` after refusing anything a browser could read differently from `urlsplit`:** a backslash, credentials before the host, whitespace or control characters. The allowed origins are `APP_BASE_URL`'s and the new `OAUTH_ALLOWED_REDIRECT_ORIGINS`. There is no loopback alias, because the code does not treat `localhost` and `127.0.0.1` alike: CORS lists `localhost` alone, and providers register each as its own callback.
5. **A socket's expiry is the token's `exp`, held in memory,** not a column read from the sessions table. It is the value HTTP routes enforce, it covers a token with no session row, and it needs neither the database nor Redis. Expiry runs first on each tick of the once-a-minute check.
6. **Logs on a shared link carry the host and the exception's type only.** The extraction itself still gets the whole URL, since trafilatura reads a publication date from the path. `shared_url_fetch()` silences httpx's line around these fetches alone, and the `trafilatura` logger tree is raised to CRITICAL.
7. **`X-Forwarded-For` accepts only two port shapes,** dotted-quad with a port and bracketed IPv6. An out-of-range port or a bracketed IPv4 is malformed, and a bare IPv6 address is never split. The limiter counts IPv6 per /64; the audit log and the session keep the full address.
8. **Model libraries are routed at each load point, not in `configure_logging`.** Importing them there would add seconds to every process that never loads a model. Both builders call `route_model_libraries` before the import, a no-op under `text`, and a test keeps a third load point from skipping it.

**Alternatives considered.**
- *A hand-kept route table for the CSP.* It fails open. *`'unsafe-inline'` for Swagger.* It gives up the policy on that page. *A hash computed at startup.* It would blank the page on a `root_path` or a FastAPI change.
- *`BaseHTTPMiddleware`.* It would hold the Q&A stream.
- *A sessions-table read for expiry.* It adds a dependency for a value the socket already holds.

**Consequences.**
- The Echo connector authorize route takes no redirect, so it needs no allow-list. A test pins that a `redirect_uri` in the body goes nowhere.
- A page at `localhost:3000` is now refused at OAuth start unless that origin is added to the new setting, though CORS lists it (T-4.11.3.3).
- Starlette's last-resort 500 goes out from outside all middleware, so it has no CSP. Its body is one fixed line of plain text.
- Under `json`, Celery's start banner stays text, and so does the `JWT_SECRET is blank` warning, which fires before `LOG_FORMAT` can be read (T-4.11.3.2). An ordinary API start also shows `app.*` INFO lines that `text` shows only after a migration.
- uvicorn's WebSocket line may log `/ws/jobs?token=<JWT>` at INFO, in both formats. That comes from reading uvicorn 0.42; no such line has been seen in the current logs (T-5.4.23).
- `sources/podcast/connector.py` logs feed and audio URLs and `PodcastClient.fetch_feed` keeps httpx's line, so a private feed's token can reach a worker log (T-1.7.1.6).
- A real reverse proxy and a real OAuth provider were not used.
- Owner steps: restart the services, and see I-5's batch 6 note for `APP_BASE_URL` and the README's "Content-Security-Policy for the app".

**Linked initiatives / PRs.** [S-4.11.2](initiatives.md#s-4112--gaps-the-docs-audit-documented-and-did-not-fix) (T-4.11.2.1, T-4.11.2.2, T-4.11.2.4, T-4.11.2.7), T-3.7.2.9, T-5.4.21, T-5.4.23, T-5.5.9, T-1.7.1.6, [S-4.11.3](initiatives.md#s-4113--follow-ups-from-the-operations-pass); PR [#420](https://github.com/khoks/VideoResearchPro/pull/420); [D-138](#d-138--code-attempts-count-on-a-shared-row-sockets-end-with-their-session-one-reader-takes-the-client-address-from-the-right-and-a-rotated-key-is-reported-2026-11-05).

**Status-changed 2026-11-09:** point 4's origin list now also decides CORS, and `localhost:3000` is no longer a default ([D-152](#d-152--cors-reads-the-oauth-origin-list-and-the-app-keeps-tiktokens-encoding-in-a-folder-of-its-own-2026-11-09), T-4.11.3.3, PR [#427](https://github.com/khoks/VideoResearchPro/pull/427)). The consequence about uvicorn's socket line was wrong: such a line was in the repo root's gitignored `.uvicorn.log`, from April, its token expired. The socket's token is now a subprotocol ([D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09), T-5.4.23, PR [#425](https://github.com/khoks/VideoResearchPro/pull/425)). The same PR closes two more consequences: Celery's banners and the `JWT_SECRET` warning follow `LOG_FORMAT=json` (T-4.11.3.2), and podcast logs name the host alone (T-1.7.1.6).

**Status-changed 2026-11-09:** the consequence about `app.*` INFO lines is out of date. Under `text` an ordinary API start now writes them too, through a handler on `app` that steps aside while the root logger has one, and an in-process migration no longer leaves Alembic's handler on root ([D-157](#d-157--the-apps-log-lines-get-a-handler-that-steps-aside-while-the-root-logger-has-one-an-in-process-migration-restores-the-root-logger-and-a-log-line-names-no-email-recipient-subject-or-connector-account-2026-11-09), T-4.11.4.1, PR [#437](https://github.com/khoks/VideoResearchPro/pull/437)).

**Status-changed 2026-11-09:** point 6 now also covers a connector's search and Echo's GitHub calls, whose URLs hold a user's query or account: they send inside `shared_url_fetch()`, so httpx writes no line for them ([D-160](#d-160--a-users-words-leave-the-workers-log-at-the-call-site-an-exception-that-can-quote-a-request-is-logged-by-its-frames-and-a-connectors-search-counts-as-a-shared-link-2026-11-09), T-4.11.4.2, PR [#442](https://github.com/khoks/VideoResearchPro/pull/442)).

## D-144 — A fifth voice label `other` names no language to write in, a job fills gaps and only the backfill rewrites, and the declared audio language is a key on the document (2026-11-05)

**Status:** accepted (2026-11-05). Made while building T-1.16.2.16, T-3.3.2.11 and T-1.11.11.4 (PR [#418](https://github.com/khoks/VideoResearchPro/pull/418)) and its review fixes, not ruled by the owner. Point 1 amends [D-099](#d-099--signal-extraction-verbatim-checked-examples-language-free-beliefs-stylometry-without-a-model-2026-10-19) and the voice test's procedure ([D-100](#d-100--voice-match-gate-mode-a-passes-on-synthetic-writers-speak-as-me-may-be-built-and-is-enabled-per-user-only-after-the-user-as-judge-test-2026-10-19), T-3.4.1.8). Point 2 extends [D-133](#d-133--the-tagger-abstains-without-hindi-evidence-the-presence-floor-reads-grammar-an-offline-lexicon-sees-english-in-devanagari-and-scores-are-quoted-from-the-production-row-2026-11-04) point 5, and point 3 extends [D-117](#d-117--the-caption-track-is-the-one-in-the-spoken-language-auto-dubs-are-read-from-the-players-audio-tracks-2026-10-29) point 5.

**Context.**
- `language_of` read `hi_share`, which still counts abstained words, so a Spanish note read `hi-Latn`. Bengali, Tamil and Urdu notes read the same, because the tagger files other scripts under `hi`.
- The board called the label "not a prompt claim", but it reaches prompts: it sets the language name in the voice test, picks the draft exemplar pool, is the draft language fallback, and heads the extraction prompt. A Spanish held-out note was drafted as "Hindi in Roman letters".
- A job that reused an embedded document stamped its era (T-1.17.3.3) but not `code_mix_*`.
- `api_quota_log` holds 3,773 units since 2026-05-16, and only 5 `videos` units postdate PR [#386](https://github.com/khoks/VideoResearchPro/pull/386). By timing the lazy lookup has cost 0 units, with a hard ceiling of 5, and no real job has run it. The log records it under the same `videos` label as `get_video_details`, so that is an inference. [D-117](#d-117--the-caption-track-is-the-one-in-the-spoken-language-auto-dubs-are-read-from-the-players-audio-tracks-2026-10-29)'s sample (about 6 units per 100 new videos) stays the only estimate.

**Decision.**
1. **A fifth voice-signal label, `other`:** a label on what the user wrote, never a language to write in. `language_of` reads `hi_share × named_share`, the figure the chunker's presence floor already uses. `routers/echo_drafts.py` keeps its four values. For a held-out note that reads `other`, the drafter is told "the language of the situation above".
2. **A job fills gaps; only the backfill rewrites.** `stamp_chunk_language_fields` adds document-level `code_mix_*` fields in both reuse branches, through the era stamp's metadata-only update, and skips any chunk with `code_mix_primary`, including one holding an older value. A refreshed profile still needs `backfill_chunk_language_fields.py`.
3. **The declared audio language is a key in `source_metadata_json`, not a column.** Whether the key is present carries the three states (declared, declares nothing, unknown), which a nullable column cannot do without a sentinel, and it needs no migration.

**Alternatives considered.**
- *Reading `en` for such a note.* It is false, and it pollutes the English cadence bucket.
- *`null`.* It reads as "not language-specific", and `by_language` is a dict of strings, so it would have been a 500 on `GET /echo/signals`.
- *Editing `TOPIC_PROMPT`.* The pre-registration fixes it.
- *Stamping `code_mix_chunk_share` and `code_mix_chunk_matrix`.* They are per chunk, and a re-chunk's chunks may not map 1:1 onto the stored ones.

**Consequences.**
- Point 1 relies on the topic call answering in the note's language, which `TOPIC_PROMPT` does not ask for and which has not been checked on a real note. If the topic comes back in English, so does the draft, the user spots their own note by its language, and `picked_own_share` rises whatever the voice quality. It fails closed, since speak as me stays gated, and it is no worse than the old "Hindi in Roman letters". The check waits for the next live voice test (T-3.4.1.16).
- Stored labels stay until their text is edited, because an unchanged input is never re-read. On the live install `voice_signals`, `voice_signal_inputs` and `notes` hold 0 rows, so nothing is affected.
- On classifier failure a Spanish message drafts in English, because `other` is not a draft language. Cadence signals for `other` pool every unnamed language, and drafts never read that bucket.
- T-1.11.11.4 does not pay for itself in quota. Its gain is that a fetch stops depending on the Data API, so the declaration still arrives when the day's quota is spent.
- `caption_track` now records `spoken_language_source: data_api` on more videos. The language ingested cannot change, pinned across 14 caption-track shapes, but between two tracks in one language that differ only by region the declared region now wins.
- `language_of` costs about 20% more (0.36 to 0.44 ms per unit), and `GET /echo/signals` calls it on every input.
- Stamped chunks keep their vectors and gain no `text_en`. A plain-English document costs no Chroma read.
- Noticed, not changed: the quota log cannot tell the lookup from `get_video_details` (T-1.11.11.5), and `execute_subscription_job` looks videos up by the wrong key (T-1.11.11.6).
- No write run and no new owner step. The four `--write` steps under S-1.16.2 keep their order. Restart the worker: the 10-30 evidence shows a running worker can stay on old code for days.

**Linked initiatives / PRs.** E-1.16 (T-1.16.2.16), E-3.3 (T-3.3.2.11), E-3.4 (T-3.4.1.8, T-3.4.1.16), E-1.11 (T-1.11.11.4 to T-1.11.11.6); PR [#418](https://github.com/khoks/VideoResearchPro/pull/418); [D-099](#d-099--signal-extraction-verbatim-checked-examples-language-free-beliefs-stylometry-without-a-model-2026-10-19), [D-100](#d-100--voice-match-gate-mode-a-passes-on-synthetic-writers-speak-as-me-may-be-built-and-is-enabled-per-user-only-after-the-user-as-judge-test-2026-10-19), [D-117](#d-117--the-caption-track-is-the-one-in-the-spoken-language-auto-dubs-are-read-from-the-players-audio-tracks-2026-10-29), [D-127](#d-127--the-in-app-voice-test-is-a-rolled-back-what-if-on-the-echo_draft-use-case-and-an-open-tests-answers-stay-out-of-the-export-2026-11-04), [D-133](#d-133--the-tagger-abstains-without-hindi-evidence-the-presence-floor-reads-grammar-an-offline-lexicon-sees-english-in-devanagari-and-scores-are-quoted-from-the-production-row-2026-11-04).

**Status-changed 2026-11-09:** both items noticed here are closed. The lazy lookup logs as `videos_audio_language`, and a sync looks videos up by `Document.video_id` ([D-149](#d-149--fetch_text-may-raise-transcriptioncutshort-a-sync-reads-only-what-the-library-lacks-the-job-limit-never-refuses-a-subscribe-and-a-held-source-can-be-tried-anyway-2026-11-09), T-1.11.11.5, T-1.11.11.6, PR [#424](https://github.com/khoks/VideoResearchPro/pull/424)). A document read before no longer gets the audio-language key through a sync, so it keeps the lazy lookup.

**Status-changed 2026-11-09:** point 2 is extended to the publish date. A job dates an undated shared row, the `Candidate`'s date first and then the page's, never over a date the row has, and stamps an embedded row's stored chunks after its commit ([D-158](#d-158--a-job-task-returns-at-once-on-a-failed-row-a-job-dates-an-undated-row-and-its-stored-chunks-whisper-text-without-segments-is-a-transcription-and-a-manual-dispatchs-503-promises-nothing-2026-11-09), T-1.6.7, PR [#436](https://github.com/khoks/VideoResearchPro/pull/436)).

## D-145 — A cut-off flag is a fact about one reply, the offer keeps the card's scope, and the server never applies the account's default depth (2026-11-05)

**Status:** accepted (2026-11-05). Made while building T-1.15.4.5, T-1.15.4.6, S-8.13.3, T-4.11.2.6 and T-1.15.3.9 (PR [#419](https://github.com/khoks/VideoResearchPro/pull/419)) and its review fixes, not ruled by the owner. It closes items [D-132](#d-132--qa-brief-keeps-the-whole-thinking-reserve-a-cut-off-report-offers-deep-a-citation-with-no-document-casts-no-vote-and-clarify-is-one-optional-route-2026-11-04) left open and builds on [D-125](#d-125--a-knowledge-reports-depth-applies-d-064-without-a-bracket-and-belongs-to-the-shared-artifact-and-a-failed-synthesis-never-reaches-it-2026-11-04). OQ-29 is untouched: `_answer_budget` did not change, and unset requests are identical. OQ-37 is the owner's.

**Context.**
- A cut answer was stored with no trace on standard or unset.
- The shelf route took `output_length` with no way to send it.
- A clarify outage was a dead end on the library page, because "Skip clarifications" appears only after clarify succeeds.
- `KNOWLEDGE_MAX_TRANSCRIPT_TOKENS` had no effect at its default.
- The spec for per-depth choice mentions an account preference that did not exist.
- A depth sent with a run becomes that run's own from then on, so an unseen one would set every answer and knowledge report on it.
- A library page's history holds shelf and one-source exchanges, and the offer only fills this page's composer.

**Decision.**
1. **A cut-off flag is a fact about one reply.** `QAAnswerResponse` and `LibraryQAAnswerResponse` extend the history shapes, so a stored row never claims `false`.
2. **The offer fills the composer rather than asking,** unlike **Regenerate at Deep depth**. A question has a scope and a clarify step, and what the reader told clarify is not stored, so re-sending blind could answer a different question. Nothing is spent until they press Ask. An answer already at Deep, including through the run's own depth, gets the note alone.
3. **The server never applies the preference.** Pages preset their control from it, so a request always carries what the page showed, and a request with no depth behaves the same with a preference set. Only `GET /auth/me` returns it.
4. **What counts as a choice made on a page.** A pick wins, including Default or Auto. A run's own depth wins on that run's page. A duplicated run keeps its depth, including Auto. A template with a depth keeps it; a template with none froze none, so the preference applies.
5. **A saved template does not pick the preference up,** because a template is a recipe and the preference is one person's. So the select can show Deep while the saved template holds no depth.
6. **On the knowledge drawer the preference is a preset, not an action.** The report is a shared artifact ([D-125](#d-125--a-knowledge-reports-depth-applies-d-064-without-a-bracket-and-belongs-to-the-shared-artifact-and-a-failed-synthesis-never-reaches-it-2026-11-04)), so the depth of a report someone generates from the preset is stored on it and read by others, as with a manual pick. The value in `users` reaches nobody. The drawer still starts nothing on open.
7. **The control is on `/account/ai-models`,** rather than a new page. It is the account page about how answers are made, and it shows even when the settings service fails.
8. **The account's default depth stands in only where a depth control is on screen.** On the submit form that is the Topic tab.
9. **The cut-off offer stays on the card's own scope.** A page offers it only when its next ask would run over the scope the answer was asked over; it never switches the page's scope to fit.

**Alternatives considered.**
- *Storing the flag.* It needs a column on both exchange tables, and the spec asked for no migration for it.
- *Re-sending the question at Deep.* See point 2.
- *Restoring a source on the library page to fit the offer.* The exchange stores no source title for the chip.

**Consequences.**
- The cut-off note does not survive a reload (T-1.15.4.8). The server's warning, which names the use case and the model and never the text, is what remains.
- Nothing has been seen to stop at its budget on a live model: the path is exercised with mocked LLMs and with each SDK's own objects offline. T-1.15.3.6, the owner's live look, gains that as a reason.
- `stopped_for_length` read no field from OpenAI's Responses API, so it returned False on langchain's responses-only models. It now reads `incomplete_details.reason`, which also corrects the report and knowledge agents on those models (T-1.15.4.7).
- A Regenerate from a drawer preset can overwrite a shared report at the preset depth, the closest the preference comes to something shared (OQ-37).
- A strip opened with a legacy video id compares unequal to the exchange's canonical `document_id`, so that card gets the note alone, which is the safe side.
- `KNOWLEDGE_MAX_TRANSCRIPT_TOKENS` now defaults to 20000 with the literal gone, so nobody's spend moves, except an install that pins it higher. `cost_estimator` reads the setting too.
- `BatchExtract` does not start from the preference (T-1.15.3.10). The job page's clarify has the same dead end (T-8.13.4.1). Q&A-history answers are not checked for a cut, and saved-search runs log the warning but show nothing (T-1.15.4.9).
- Owner step: migration `869754146393`, one nullable column on `users`, reversible, with no backfill.

**Linked initiatives / PRs.** E-1.15 (T-1.15.3.6, T-1.15.3.9, T-1.15.3.10, T-1.15.4.5 to T-1.15.4.9, OQ-37), E-8.13 ([S-8.13.3](initiatives.md#s-8133--the-library-page-stops-at-a-failed-clarify), T-8.13.4.1), T-4.11.2.6; PR [#419](https://github.com/khoks/VideoResearchPro/pull/419); [D-125](#d-125--a-knowledge-reports-depth-applies-d-064-without-a-bracket-and-belongs-to-the-shared-artifact-and-a-failed-synthesis-never-reaches-it-2026-11-04), [D-132](#d-132--qa-brief-keeps-the-whole-thinking-reserve-a-cut-off-report-offers-deep-a-citation-with-no-document-casts-no-vote-and-clarify-is-one-optional-route-2026-11-04).

**Status-changed 2026-11-09:** the flag is now stored, which this entry's first alternative set aside for want of a migration: `answer_cut_off` on all three exchange tables, NULL for older rows, and on the wire a stored row still says `true` or nothing ([D-150](#d-150--the-cut-off-flag-is-stored-as-what-the-check-found-a-cut-answer-is-never-a-saved-searchs-baseline-and-a-cut-first-answer-stands-in-on-the-card-2026-11-09), T-1.15.4.8, T-1.15.4.9, PR [#426](https://github.com/khoks/VideoResearchPro/pull/426)). Point 2 stands, so after a reload the note stays and the offer goes (OQ-39). `BatchExtract` starts from the preference, and the job page's clarify no longer dead-ends ([D-148](#d-148--a-401-ends-a-session-in-react-and-keeps-the-page-in-this-tab-a-waiting-share-gets-a-link-a-mutation-that-answers-its-own-failures-says-so-and-tabs-opens-on-focus-2026-11-05), T-1.15.3.10, T-8.13.4.1, PR [#423](https://github.com/khoks/VideoResearchPro/pull/423)).

## D-146 — A pool never carries the `Session`, `MAX_CONCURRENT_JOBS` is per user, a key check says good or bad only when the provider did, and Whisper's key and count hold on every sync (2026-11-05)

**Status:** accepted (2026-11-05). Made while building T-5.6.12, T-5.6.13, T-5.2.14 and T-5.6.8 (PR [#417](https://github.com/khoks/VideoResearchPro/pull/417)) and its review fixes, not ruled by the owner. Point 5 reverses what PR [#415](https://github.com/khoks/VideoResearchPro/pull/415) told the owner about subscription jobs, so the owner has yet to confirm it (OQ-36). [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25) and [D-131](#d-131--whisper-is-charged-at-the-shared-call-and-usage-is-written-part-way-on-a-timer-after-every-billed-response-2026-11-04) stand: nothing here enforces anything from the usage numbers.

**Context.**
- Pool threads read through the task's `Session` for the BYOK lookup, and `_resolve_byok_api_key` answers any exception with the install's key, so a user's work could run on the install's bill with nothing to show for it. In production a lock and SQLite's check being off made the read usually work, which is luck, not a guarantee.
- A user who brought an OpenAI key was still transcribed on the install's, while Echo recordings used theirs.
- `_run_extraction_and_rag` (subscription jobs) metered its run but opened no `byok_context` and passed no Whisper budget, so moving the fallback onto a tenant's key alone would have moved an unbounded spend onto their bill.
- One user's five jobs refused everyone else on the install.
- A key could be saved but not tested until a real run failed.
- A provider's error text can quote a key: an OpenAI 401 does, and `test_the_provider_text_really_did_carry_the_key` pins that.

**Decision.**
1. **A pool never carries the `Session`.** `llm_service.byok_keys_for_pool()` reads every provider's key once, on the task's thread, and takes the session out of the context the threads copy. The tenant stays, for the meter. Every provider is read, not just the one the use case resolves to, because a user's model pin can point the map at any provider, and one left out would read as "no key" and fall back silently.
2. **`MAX_CONCURRENT_JOBS` means per user** and bounds refusals only. The worker's order is unchanged, and there is no install-wide ceiling.
3. **A key check says good or bad only when the provider did.** 401, 402, 403, 429 and a 400 about the key are `refused`. A 5xx, a 404, any other 400, a 403 about the model, no answer, or 30 seconds are `unreachable`. An empty answer is `valid`, since the provider took the request. The response is that one word, and `ProbeResult.status_code` is a number, so nothing a provider said reaches the response or the log. The wording lives in the panel.
4. **Whisper's key follows `get_llm_for`'s rule:** the tenant's key when they brought one, else the install's, with no fallback from a refused tenant key. `llm_service.whisper_api_key` is the one rule for the YouTube fallback, podcast audio and Echo recordings. A transcript a tenant's key paid for goes into the shared cache like any other ([D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)).
5. **`WHISPER_MAX_PER_JOB` bounds subscription jobs, on every key.** This goes further than T-5.6.13's "without a key, nothing changes", which was read as being about whose key pays: a user with no key keeps the install's key, and their sync is capped too. It makes "`0` disables Whisper" true. Capping is the recoverable side: money spent past a cap does not come back, and a capped video is read by a later sync, which a test proves over three syncs.

**Alternatives considered.**
- *Capping only a tenant's own key.* It would leave free users unbounded on the install's bill while capping the people paying for themselves.
- *Leaving the sync cap for later,* which the review offered and #415 had chosen. It would have put an unbounded spend on a tenant's key.
- *Per-tenant queues for a fair share.* Not the smallest design, so left out and documented.
- *429 as `unreachable`.* OpenAI uses 429 for an account with no credit, and "could not reach" would send that user looking for a network fault. The panel's words say the key may be over its rate limit.

**Consequences.**
- **Owner step, OQ-36:** a channel with many uncaptioned videos now reads 50 Whisper recordings per sync, says so in a `whisper_budget_spent` run note, and the next sync reads 50 more. For the old behaviour, raise `WHISPER_MAX_PER_JOB`. A sync ends in "completed", so without that note a stop at the limit would leave no lasting trace.
- Worker order is not fair: `worker_concurrency` still reads `MAX_CONCURRENT_JOBS` and is shared, so a second user's job is accepted at once but can wait behind the first user's running tasks (T-5.2.16). On a shared install the total of active jobs can exceed the old five.
- Channel syncs still skip the limit, though they count toward their owner's total, so a user can be over it (T-5.2.15).
- A brief rate limit on a good key reads as `refused`.
- A key check is not recorded as usage: it is on the user's own key, about 16 tokens.
- `gpt-5.6-luna`, `claude-haiku-4-5` and `gemini-3.1-flash-lite`, the check models in `KEY_CHECK_MODELS`, have not been tried live. The wire tests prove the request shape, not the models' availability (T-5.6.15).
- `whisper_error_text` names auth errors by type alone, because a Whisper failure line can now hold a tenant's key. Model-call error logs elsewhere still can (T-5.6.16).
- `langchain-anthropic` was never declared, though Q&A answers default to Anthropic. It is in `requirements.txt` now (T-5.6.14). A clean install resolves `anthropic` 2.5.0 against the dev venv's 0.120.0; the tests pass on both, against a loopback provider only.
- `/health`'s `whisper_transcribe_enabled` stays install-level, since it is public and has no user.
- An approved run that hits the count limit keeps its progress line and has no run note, pinned by a test, because an approved run has a reviewer.

**Linked initiatives / PRs.** E-5.6 (T-5.6.8, T-5.6.12 to T-5.6.16, OQ-36), E-5.2 (T-5.2.14 to T-5.2.16), T-1.7.1.1; PR [#417](https://github.com/khoks/VideoResearchPro/pull/417); [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25), [D-141](#d-141--a-connectors-search-raises-on-failure-a-refusal-is-a-24-hour-hold-on-a-sources-own-endpoint-non-video-sources-search-before-youtube-and-a-recording-counts-once-2026-11-05).

**Status-changed 2026-11-09:** point 2 is extended: the job limit holds a sync, never a subscribe, and a sync the broker refused fails its row ([D-149](#d-149--fetch_text-may-raise-transcriptioncutshort-a-sync-reads-only-what-the-library-lacks-the-job-limit-never-refuses-a-subscribe-and-a-held-source-can-be-tried-anyway-2026-11-09), T-5.2.15, PR [#424](https://github.com/khoks/VideoResearchPro/pull/424)). `whisper_error_text`'s rule is generalised to every log record as `provider_error_text`, and `ProbeResult.error` is scrubbed where it is made ([D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09), T-5.6.16, PR [#425](https://github.com/khoks/VideoResearchPro/pull/425)).

## D-147 — The rendering parser decides what is a heading in book Markdown, a rewrite parses what it will emit, and the suite's tiktoken file lives at a fixed path (2026-11-05)

**Status:** accepted (2026-11-05). Made while building T-8.8.6.1, T-8.8.6.2, T-8.8.6.4 and T-2.8.6 (PR [#421](https://github.com/khoks/VideoResearchPro/pull/421)) and its review fixes, not ruled by the owner.

**Context.**
- tiktoken's default cache is the temp directory, which a runner starts empty, so CI fetched the encoding on every run. `report_agent._count_tokens` and `knowledge_agent._count_tokens` catch a failure and count words instead, so a DNS drop could change what a test sees rather than fail it.
- An `h2` is the book's own level: the EPUB cuts a file at each one, and marks the last as backmatter when it is named Endnotes. Only ATX headings were demoted. A pattern cannot do this: `Text` over `---` is a heading, but `- item` over `---` is a list and a rule.
- `report_markdown` caches its conversion beside the report, and a test that patches `get_report_html` needs no real file, so `"/r.html"` wrote to the root of the drive.
- The marketing site's real build had only been run by hand.

**Decision.**
1. **What counts as a heading in book Markdown is the rendering parser's call.** `book_html.top_level_headings` is the one source, and `_demote_headings` no longer uses a pattern. Setext comes out as ATX, because only ATX can say a level below H2. Headings inside a quote or a list keep their level, since the EPUB reads the top level only.
2. **A rewrite of book Markdown parses the text it will emit.** Anything that changes the text around a heading happens before the parse that demotes, because trimming or dropping a line afterwards can make a heading of what the parser called something else. The H1 is dropped in a pass of its own. The cost is one more parse when an H1 is dropped.
3. **A question in a book is one line.** It has no level to demote to.
4. **`clean_prose` drops a line of only `-` or `=`,** a lone rule included.
5. **`clean_prose` reads text as the renderer does before cleaning it,** through the new `book_html.sanitise`, and removes quote and heading marks in one pattern, repeated, behind an indent of any width or kind. The indent there is not the parser's: it strips every paragraph, so a mark behind one still reaches the start of a line.
6. **The suite's tiktoken file lives in `~/.cache/tiktoken`,** a fixed path that CI's cache lists. A test on a runner stands in for the offline switch tiktoken lacks: it reloads the encoding with requests and DNS failing, and fails rather than skips when the file did not come from the cache.

**Alternatives considered.**
- *A blank line in place of a dropped H1.* It is not enough: `# Report`, a blank line, then `    Title` over `---` is still trimmed into a heading.
- *Widening `_HEADING_LINE` for `clean_prose`.* `_plain_lines` also uses it for chapter digests, and it would count indented code as headings there.
- *A step in the `frontend` job for the marketing build.* It would add to that job and hide which build failed. The new job takes 19 seconds and adds nothing to a run's length.

**Consequences.**
- Only the suite's cache changed. The app, workers included, still fetches into the temp directory and `chunking._count_tokens` has no fallback, so a cleared temp directory plus a network drop would fail a job at chunking (T-8.8.6.5, the owner's call).
- `_demote_headings` now removes XML-invalid control characters from its output, as the rendered book always did. Dropping an H1 that is not first adds one blank line. A first-line indent is trimmed before the parse, so `    Title` over `---` on the first line becomes a heading and is demoted.
- Stored books keep their text until regenerated.
- conftest fails any test that puts a report at the filesystem root, using `pytest.fail` because the book catches `Exception` and would otherwise print a placeholder chapter.
- CI's `MODEL_CACHE_KEY` goes to `v3`. Both cache paths ran on a runner: a miss (download 15 s, save 4 s), then a hit.
- Owner steps, both optional: clear the 177 files at `D:\`, and add "Marketing site build (Astro)" to branch protection if it lists required checks.

**Linked initiatives / PRs.** [S-8.8.6](initiatives.md#s-886--follow-ups-from-the-reader-and-test-infra-pass) (T-8.8.6.1, T-8.8.6.2, T-8.8.6.4, T-8.8.6.5), E-2.8 (T-2.8.6); PR [#421](https://github.com/khoks/VideoResearchPro/pull/421); [D-136](#d-136--a-books-contents-take-their-ids-from-the-rendered-manuscript-the-main-chunk-meets-its-budget-with-lazy-markdown-and-lazy-routes-and-the-device-suites-server-is-dual-stack-2026-11-04).

**Status-changed 2026-11-09:** the app now keeps its encoding in `TIKTOKEN_ENCODINGS_DIR` too, and every load in `app/` goes through one helper that survives a lost first-download race ([D-152](#d-152--cors-reads-the-oauth-origin-list-and-the-app-keeps-tiktokens-encoding-in-a-folder-of-its-own-2026-11-09), T-8.8.6.5, PR [#427](https://github.com/khoks/VideoResearchPro/pull/427)). The suite's fixed path in point 6 is untouched, because a variable already set wins.

## D-148 — A 401 ends a session in React and keeps the page in this tab, a waiting share gets a link, a mutation that answers its own failures says so, and Tabs opens on focus (2026-11-05)

**Status:** accepted (2026-11-05). Made while building T-5.4.22, T-3.7.6.3, T-8.13.4.1, T-8.13.4.2, T-1.5.13.7, T-2.2.5, T-3.4.1.15 and T-1.15.3.10 (PR [#423](https://github.com/khoks/VideoResearchPro/pull/423)) and its review fixes, not ruled by the owner. Point 1 amends [D-140](#d-140--a-sign-in-makes-one-redirect-the-query-cache-ends-with-the-session-the-error-screen-replaces-the-page-and-signed-out-pricing-leads-to-free-2026-11-05)'s consequence about T-5.4.22, and D-140 point 2 stands for other tabs. Point 4 keeps [D-137](#d-137--a-share-target-posts-to-a-worker-scoped-to-one-path-and-waits-for-one-tap-mail-is-unverified-text-that-never-trains-the-voice-shared-links-go-through-the-public-address-guard-2026-11-04) point 9. OQ-41 is the owner's.

**Context.**
- `api.ts` answered a 401 with `window.location.href = '/login'` and no page, so an old tab, or an email link a day later, ended at `/`. D-140 called this probably the most common real deep link.
- The hard redirect also wiped memory. A soft one does not.
- A page has several requests out at once, and one refused after the reader signed in again must not take the new session with it.
- The streaming ask uses `fetch`, which never reached the interceptor.
- A clear of site data, or a page back from the back/forward cache after another tab signed out, leaves React signed in with nothing to send, so every request goes out bare and comes back 401.
- With a deep link while a share was waiting, the share waited up to 24 hours for the next visit to `/`.
- A failed draft showed two toasts. The global handler alone says "Network Error" for a 500 or no answer, where the panel has a real sentence, and TanStack drops a per-call `onError` once the component has unmounted.

**Decision.**
1. **A 401 ends a session in React, not with a page load.** One module, `services/sessionExpiry.ts`, removes the token and tells `AuthProvider`. `ProtectedRoute` carries the page to `/login`, and `PublicOnlyRoute` returns through `signInReturn` with its existing checks. A 401 counts only for the token it refused, and never on the sign-in calls or `/auth/logout`. A 401 during a sign-out counts as the sign-out. A 401 that finds no token in storage ends a session this tab still holds, as a sign-out, because this tab cannot tell who took the token.
2. **With no reload, `AuthProvider`'s session-end effect owns what memory holds:** the query cache, the Echo thread and the toasts.
3. **A session the server stopped accepting keeps the page in this tab only.** Another tab hears only that the token went, cannot tell that from a sign-out, and gives its page up (D-140 point 2, unchanged).
4. **A waiting share gets a link, never a second redirect** (D-137 point 9). `WaitingShareNotice` in `AppLayout` shows **Review it** on every page but `/` and the review page, and nothing is posted until the tap there.
5. **A mutation that answers every failure itself says so with `meta.errorsShownHere`, and answers in the hook's own `onError`.** A per-call `onError` is invisible to the mutation cache, which is where double toasts come from, and TanStack drops it once the component has unmounted, so it cannot be the only answer.
6. **`Tabs` opens on focus,** with arrows, Home and End wrapping and a roving tabindex, since every panel swaps in place and spends nothing. With a modifier held the key stays the browser's.

**Alternatives considered.**
- *Dropping the panel's toast.* The global handler alone says "Network Error" for a 500 or no answer.
- *An `onError` on the panel's `mutate` call.* TanStack drops it once the panel has unmounted, and a draft runs long enough to be left behind.
- *A storage marker so another tab can tell a sign-out from a 401.* D-140 point 2 stands, and the spec asked to say what happens rather than change it (OQ-41).
- *A second redirect for a waiting share.* It loses the race D-137 point 9 describes.

**Consequences.**
- A deliberate sign-out no longer leaves the last account's Echo thread in the tab.
- The same double toast remains on `VoiceTestPanel` (three sites) and on the Echo page's delete and revoke. A page's own per-call toast can still land on the sign-in page when a 401 arrives after another request ended the session; it takes two requests racing (T-3.4.1.17).
- A draft stop after the panel has gone says nothing, as on master, because each stop needs the panel to act on it.
- A page restored from the back/forward cache finds out at its next request, since no `pageshow` listener was added.
- The submit form already read right for T-1.5.13.7; the job page's **Job parameters** now reads **Number of results** on a run over other sources. `BatchExtract`'s existing depth select starts from the preference, and the server applies nothing ([D-145](#d-145--a-cut-off-flag-is-a-fact-about-one-reply-the-offer-keeps-the-cards-scope-and-the-server-never-applies-the-accounts-default-depth-2026-11-05)).
- Left out: `role="tabpanel"` and `aria-controls` on the panels, Echo's `ModeTab`, a "your session ended" line on the sign-in page, and a dismiss on the notice.
- Tested against fixtures only: no real expired JWT, Android share sheet or model. No device baseline changed, and there is no owner step.

**Linked initiatives / PRs.** E-5.4 (T-5.4.22, OQ-41), E-3.7 (T-3.7.6.3), E-8.13 ([S-8.13.4](initiatives.md#s-8134--clarify-follow-ups-from-the-library-fix)), E-2.2 (T-2.2.5), E-3.4 (T-3.4.1.15, T-3.4.1.17), T-1.5.13.7, T-1.15.3.10; PR [#423](https://github.com/khoks/VideoResearchPro/pull/423); [D-137](#d-137--a-share-target-posts-to-a-worker-scoped-to-one-path-and-waits-for-one-tap-mail-is-unverified-text-that-never-trains-the-voice-shared-links-go-through-the-public-address-guard-2026-11-04), [D-140](#d-140--a-sign-in-makes-one-redirect-the-query-cache-ends-with-the-session-the-error-screen-replaces-the-page-and-signed-out-pricing-leads-to-free-2026-11-05), [D-145](#d-145--a-cut-off-flag-is-a-fact-about-one-reply-the-offer-keeps-the-cards-scope-and-the-server-never-applies-the-accounts-default-depth-2026-11-05).

**Status-changed 2026-11-09:** point 5 now holds on every page. The double toast the consequences name on `VoiceTestPanel` and the Echo page is closed, with the rest of the 33 sites in 12 files that had it, through `toastMutationError`, which says nothing on a 401, and a guard test that reads every module ([D-153](#d-153--a-hook-that-answers-its-own-failures-says-them-through-one-helper-a-hook-whose-callers-differ-takes-an-option-and-a-guard-test-holds-the-rule-2026-11-09), T-3.4.1.17, PR [#429](https://github.com/khoks/VideoResearchPro/pull/429)).

## D-149 — `fetch_text` may raise `TranscriptionCutShort`, a sync reads only what the library lacks, the job limit never refuses a subscribe, and a held source can be tried anyway (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-1.11.11.6, T-1.11.11.5, T-5.2.15, T-1.5.14.6 and T-1.7.1.5 (PR [#424](https://github.com/khoks/VideoResearchPro/pull/424)) and its review fixes, not ruled by the owner. Point 1 amends the connector contract's "returns None rather than raising" and extends [D-141](#d-141--a-connectors-search-raises-on-failure-a-refusal-is-a-24-hour-hold-on-a-sources-own-endpoint-non-video-sources-search-before-youtube-and-a-recording-counts-once-2026-11-05) point 7. Point 3 extends [D-146](#d-146--a-pool-never-carries-the-session-max_concurrent_jobs-is-per-user-a-key-check-says-good-or-bad-only-when-the-provider-did-and-whispers-key-and-count-hold-on-every-sync-2026-11-05) point 2, and point 4 extends D-141 point 3. OQ-36 is untouched, and OQ-38 is the owner's.

**Context.**
- `execute_subscription_job` looked videos up with `db.get(Document, vid)`, a YouTube id against the UUID primary key, so every unlinked video counted as missing and each sync re-read its whole channel at 1 unit per 50 videos. PR [#418](https://github.com/khoks/VideoResearchPro/pull/418) found it reading the quota log.
- The lazy audio-language lookup logged as `videos`, the label `get_video_details` uses, so the log could not name it.
- `_dispatch_subscription_sync` wrote its row directly, so Sync now and subscribe skipped `MAX_CONCURRENT_JOBS`, though a sync counts toward its owner's total.
- A hold could end only through a settings change or after 24 hours.
- A transcription that failed part-way charged nothing to either Whisper limit, though its finished chunks were billed. [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25) keeps enforcement off the usage meter, so the job has to learn it from the connector.

**Decision.**
1. **`fetch_text` may raise `TranscriptionCutShort(seconds)`** when a chunk after the first fails. Both extraction loops leave the document unavailable and charge one recording to the count and the recording's reach on its timeline to the minute cap, never the declared length, which was never heard, and never from the meter. A failure on the first chunk billed nothing, so it still returns `None`. The exception carries a number and no provider text, and is raised outside the `except` block, so nothing chains.
2. **A sync reads details only for what the library lacks,** by `Document.video_id`. A row carries only what the details said, so a document another tenant ingested is never renamed "Unknown" for everyone. A placeholder row titled "Unknown" counts as not yet read, so a video that goes public is corrected by the next sync. A library hit is linked and granted as before ([D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)).
3. **The job limit never refuses a subscribe.** It only keeps the first sync from starting, and the response says so in a new `sync_note`. Sync now answers 429 with the sentence `POST /jobs` uses. A sync the broker refused fails its row, so a row nothing will run holds no place. `job_service.refuse_if_at_limit` is the one check.
4. **A held source chosen on the form is not "unavailable".** **Try X anyway** is the manual way to end a hold, through the source's own answer and with no new route: an answer clears the hold, an empty one included, and a refusal restarts the 24 hours. A template or Duplicate that carries a held source submits with the same note.
5. **The lookup logs as `videos_audio_language`,** listed in `OPERATION_COSTS` at 1 unit and mapped to `video_metadata` in `YOUTUBE_FEATURES`, so no tenant's figure moves.

**Alternatives considered.**
- *A new return shape from `fetch_text`.* Its `None` runs through up to four layers, and a falsy result object would fail silently in `extracted is None` callers. An exception needs no change in the layers between, and reaches only callers that allow Whisper.
- *Charging a part-paid recording at its declared length.* Only part of it was heard.
- *A route to clear a hold.* `POST /jobs` already took a held source.
- *Refusing a subscribe at the job limit.* The brief has subscribing always succeed there; only the first sync waits.

**Consequences.**
- A full library still refuses a subscribe with 429, under T-5.2.10's rule. Whether it should is the owner's call (OQ-38).
- `POST /jobs` has the same orphan: a failed dispatch returns 500 and leaves a `pending` row counting toward the limit (T-5.2.17).
- Whisper that answered but left no text is billed and not charged (T-1.7.1.7).
- A sync no longer refreshes a read document's title or thumbnail, which the bug did by accident, and older documents no longer get the T-1.11.11.4 audio-language key through a sync, so they keep the lazy lookup. A real video titled "Unknown", or a row with a NULL title, is read again on every sync, at most 1 unit per 50.
- OQ-36 is unchanged. A part-paid recording counts in the sync loop as in the approved one, so such a sync stops one recording sooner.
- A part-paid recording gets no run note. The document reads unavailable, and the log says how far it got.
- Existing `api_quota_log` rows keep `videos`. No migration and no new setting.

**Linked initiatives / PRs.** E-1.11 (T-1.11.11.5, T-1.11.11.6), E-5.2 (T-5.2.15, T-5.2.17, OQ-38), E-1.5 (T-1.5.14.6), E-1.7 (T-1.7.1.5, T-1.7.1.7), OQ-36; PR [#424](https://github.com/khoks/VideoResearchPro/pull/424); [D-063](#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31), [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25), [D-141](#d-141--a-connectors-search-raises-on-failure-a-refusal-is-a-24-hour-hold-on-a-sources-own-endpoint-non-video-sources-search-before-youtube-and-a-recording-counts-once-2026-11-05), [D-144](#d-144--a-fifth-voice-label-other-names-no-language-to-write-in-a-job-fills-gaps-and-only-the-backfill-rewrites-and-the-declared-audio-language-is-a-key-on-the-document-2026-11-05), [D-146](#d-146--a-pool-never-carries-the-session-max_concurrent_jobs-is-per-user-a-key-check-says-good-or-bad-only-when-the-provider-did-and-whispers-key-and-count-hold-on-every-sync-2026-11-05).

**Status-changed 2026-11-09:** two consequences are closed. `POST /jobs` fails a run the task queue refused and answers 503 (T-5.2.17), and Whisper that answered but left no text is charged through `TranscriptionEmpty`, a sibling of `TranscriptionCutShort` under a new base, `PaidTranscriptionLost` (T-1.7.1.7). Both in [D-155](#d-155--stored-exception-text-goes-through-error_summary-an-empty-whisper-answer-is-charged-a-refused-dispatch-fails-a-new-run-and-leaves-an-approval-waiting-and-a-start-the-queue-refused-uses-up-nothing-2026-11-09), PR [#430](https://github.com/khoks/VideoResearchPro/pull/430).

## D-150 — The cut-off flag is stored as what the check found, a cut answer is never a saved search's baseline, and a cut first answer stands in on the card (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-1.15.4.8 and T-1.15.4.9 (PR [#426](https://github.com/khoks/VideoResearchPro/pull/426)) and its review fixes, not ruled by the owner. It takes up the alternative [D-145](#d-145--a-cut-off-flag-is-a-fact-about-one-reply-the-offer-keeps-the-cards-scope-and-the-server-never-applies-the-accounts-default-depth-2026-11-05) set aside, storing the flag, and changes how S-8.3.3's change detector treats a cut answer. OQ-29 is untouched. OQ-39 and OQ-40 are the owner's.

**Context.**
- D-145 left the cut-off note in a client store, so a reload lost it.
- Q&A-history answers were not checked for a cut, and saved-search runs logged the warning but showed nothing.
- A run's answer feeds the change detector. A cut answer has lost its end and the `[Source: ...]` citations there, so the cited set shrank. The reader got a false "No longer cites X" alert and email, and the cut answer became the baseline, so the next full answer read as "Now cites N new sources".

**Decision.**
1. **What the column means.** `answer_cut_off` is a nullable boolean on `qa_exchanges`, `library_qa_exchanges` and `qa_history_exchanges` (migration `7bc07679d355`, no backfill). True and False are what the check found, and False includes a provider that reports no stop reason. NULL is a row from before the column: unknown, never "not cut". Writing False, rather than leaving NULL, keeps a checked denominator, so how often answers are cut can be measured later.
2. **On the wire a stored row says `true` or nothing,** so uncut and unknown look alike and neither claims "not cut". The fresh replies of `POST /jobs/{id}/qa` and `POST /library/qa` keep sending `false`, as PR [#419](https://github.com/khoks/VideoResearchPro/pull/419) shipped, byte for byte and in key order. `POST /qa-history/chat` is new to the flag and sends it only on a cut.
3. **A cut answer is never a saved search's baseline, and the gate still moves, with a baseline or without one.** A cut run is not compared, calls no judge, sends no alert, and writes no answer hash, cited ids or embedding. `last_scope_hash` and `last_success_at` advance, because the same question over the same documents gets the same budget, so keeping the gate open would pay every cadence to stop in the same place. The run is stored as `decided_by="cut_off"`, with no new column.
4. **A cut first answer stands in on the card** while there is no full one, or the card would say "No answer yet" after a run that answered. The card says it was cut (`last_answer_cut_off`, sent only when true), since run history is closed by default. It writes no embedding, so `compare` treats it as no baseline.
5. **`qaCutOffStore.ts` holds only the depth of the ask,** which a boolean cannot, so D-145 point 2 still keeps Deep from being offered to an answer asked at Deep. After a reload the note stays and the offer goes, which D-145 calls the safe side.

**Alternatives considered.**
- *Leaving NULL for an uncut answer.* It loses the denominator.
- *A base class carrying the stored flag.* Pydantic keeps an overridden field at the parent's position, which moved the flag to the front of every fresh reply. Each response declares it last instead.
- *Keeping the gate open after a cut.* It would re-ask every cadence, against S-8.3.3's "cost follows ingest".
- *A second column for the ask's depth.* It would bring the offer back after a reload and retire the store (OQ-39).

**Consequences.**
- A change the cut run could not compare waits for the next ingest, or for **Run now**, which always asks. With no baseline the card holds the cut answer, with its note, until then.
- A baseline cut before PR [#426](https://github.com/khoks/VideoResearchPro/pull/426) is unknown, so it stays a baseline and may raise one false alert. Nothing can tell those rows apart.
- A saved-search card with a full answer does not say a later run was cut; only the run history does.
- The Q&A dataset exports still include cut answers, which can now be filtered (T-1.15.4.10).
- The cut path has only run on mocked models and on each SDK's own objects offline. No answer has been seen to stop at its budget on a live model (T-1.15.3.6).
- `requirements.txt` declares `pydantic>=2.12.0`, because `Field(exclude_if=...)` is new in 2.12 and older versions ignore it silently.
- Owner step: the migration applies on the next API start, before the worker writes the column. On SQLite the downgrade rebuilds the three tables, and their search triggers return at the next API start.

**Linked initiatives / PRs.** E-1.15 (T-1.15.4.8 to T-1.15.4.10, T-1.15.3.6, OQ-39, OQ-40), E-8.3 ([S-8.3.3](initiatives.md#s-833--re-run-change-detection-and-notification)); PR [#426](https://github.com/khoks/VideoResearchPro/pull/426); [D-132](#d-132--qa-brief-keeps-the-whole-thinking-reserve-a-cut-off-report-offers-deep-a-citation-with-no-document-casts-no-vote-and-clarify-is-one-optional-route-2026-11-04), [D-145](#d-145--a-cut-off-flag-is-a-fact-about-one-reply-the-offer-keeps-the-cards-scope-and-the-server-never-applies-the-accounts-default-depth-2026-11-05).

## D-151 — The socket's token is a subprotocol, provider errors are scrubbed as each log record is made, and JSON logs hold their format from the first line (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-5.4.23, T-1.7.1.6, T-5.6.16 and T-4.11.3.2 (PR [#425](https://github.com/khoks/VideoResearchPro/pull/425)) and its review fixes, not ruled by the owner. **T-5.4.23 was filed as the owner's call.** The main session put it in batch 7 because it is a credential in a log; the owner is free to reverse it. Point 1 closes what [D-085](#d-085--reading-room-reports-stay-html-sanitised-and-parsed-in-the-browser-one-shared-citation-card-fed-by-the-runs-documents-2026-10-19)'s addendum left open, and the context below corrects [D-143](#d-143--the-apis-content-security-policy-is-locked-by-default-oauth-redirects-are-compared-as-origins-a-socket-ends-at-its-tokens-expiry-and-a-shared-link-is-logged-by-host-alone-2026-11-05)'s consequence that no such line had been seen.

**Context.**
- D-085's addendum left `/ws/jobs` as the one route with a credential in a URL, because a browser cannot set a header on the handshake. It can offer subprotocols.
- The board said the socket's token had not been seen in a log. The main session found a line of the form `WebSocket /ws/jobs?token=<JWT> [accepted]` in the repo root's gitignored `.uvicorn.log`, dated April, its token long expired. `.uvicorn.out.log` and `.uvicorn.err.log` read clean only because a restart truncates them. So any session that opened a socket wrote its JWT to disk, and a reverse proxy would log the URL too.
- `sources/podcast/connector.py` logged feed and audio URLs, and a private feed's URL can carry a token.
- A provider exception can quote a key. It reaches a log line as an argument, in an f-string or as a `logger.exception` traceback, at dozens of call sites in the agents alone, and the app has 191 `logger.exception` calls. A YouTube `HttpError` holds the install's `YOUTUBE_API_KEY` in its URL.
- Under `LOG_FORMAT=json`, Celery's start banners and the `JWT_SECRET is blank` warning stayed text, so NFR-5.1 did not hold.

**Decision.**
1. **The socket's token is a subprotocol, offered after `bearer`.** The client opens `new WebSocket(url, ['bearer', token])`. The server authenticates the token exactly as before and answers `bearer` alone, because a browser fails a handshake whose answer names nothing it offered, and the token is never reflected. Every character of a JWT is legal in a subprotocol name. `?token=` is retired, and `test_url_tokens.py` holds every route, the socket included, to no credential in a URL.
2. **uvicorn's loggers redact credentials** through a filter on `uvicorn.error` and `uvicorn.access` that works on `record.args` and keeps their shape: the values of `token`, `access_token`, `jwt`, `auth`, `authorization` and `code`, and anything shaped like a JWT, which at `--log-level debug` covers the handshake header.
3. **`code` is in the URL log net but not in `CREDENTIAL_QUERY_NAMES`,** because the OAuth callback must take it from the URL.
4. **Provider errors are scrubbed in a log-record factory, not at each call site.** `provider_error_text`, the Whisper rule of [D-146](#d-146--a-pool-never-carries-the-session-max_concurrent_jobs-is-per-user-a-key-check-says-good-or-bad-only-when-the-provider-did-and-whispers-key-and-count-hold-on-every-sync-2026-11-05) generalised, names a refusal from `openai`, `anthropic` or `google`, or anything it caused, by its type alone, and takes the shapes of a key out of any other text, tracebacks included. A refusal is told by class name and top-level package, so a log call never imports an SDK. An argument that is not text is judged by the text the line will show for it, and replaced only when that held a key. `ProbeResult.error` is scrubbed where it is made.
5. **A fetched podcast URL is logged by host and exception type,** as [D-143](#d-143--the-apis-content-security-policy-is-locked-by-default-oauth-redirects-are-compared-as-origins-a-socket-ends-at-its-tokens-expiry-and-a-shared-link-is-logged-by-host-alone-2026-11-05) point 6 does for the article path, and `loggable_id` takes a source id that holds a URL down to its host.
6. **Under `LOG_FORMAT=json` the start banners are off, and a warning from a settings validator is held until logging has its format,** then said once.

**Alternatives considered.**
- *First-message auth.* It needs a socket open and unauthenticated, a state the manager does not have.
- *A single-use ticket.* It needs server state and still puts a credential in a URL.
- *A filter per logger, or on a handler.* A filter sees only its own logger, and a handler filter is lost whenever uvicorn, Celery or Alembic replaces the handlers. The factory's cost is a regex on each record's strings.
- *Scrubbing at each call site.* There are too many, and the next one would miss it.

**Consequences.**
- Provider exception text still reaches stored rows and messages, which are not logs: `jobs.error_message` and the socket's error event, `report_agent`'s map notes and its "Channel narrative generation failed" text, and `outputs.error_message`. A tenant can read some of them, and the key quoted can be the install's (T-5.6.17). Celery's result backend keeps a failed task's traceback in Redis.
- A key in a shape `scrub_keys` does not know is caught only inside the refusal itself, so a log line should pass the exception, never `e.body` or a response object. Celery swaps an exception that will not pickle for its nearest base class, so its failure line is protected by text alone.
- NFR-5.1 names two exceptions left: a worker told to stop writes its shutdown notices straight to the stream, and under `uvicorn --reload` or `--workers`, which the launchers do not pass, a parent process writes a few start lines as text.
- `PodcastConnector.search` keeps the httpx error as its cause, and its traceback quotes a feed URL. Those feeds are public ones iTunes names.
- Not checked: a real reverse proxy, and a real provider refusing a key.
- Owner steps: restart the services. A tab still running the old script fails to connect until it is reloaded. Delete the repo root's `.uvicorn.log`.

**Linked initiatives / PRs.** E-5.4 (T-5.4.23), E-1.7 (T-1.7.1.6), E-5.6 (T-5.6.16, T-5.6.17, OQ-21), [S-4.11.3](initiatives.md#s-4113--follow-ups-from-the-operations-pass) (T-4.11.3.2); PR [#425](https://github.com/khoks/VideoResearchPro/pull/425); [D-085](#d-085--reading-room-reports-stay-html-sanitised-and-parsed-in-the-browser-one-shared-citation-card-fed-by-the-runs-documents-2026-10-19), [D-124](#d-124--second-factor-attempts-count-on-the-ticket-one-bearer-check-for-http-and-the-socket-and-a-validation-error-never-quotes-what-was-sent-2026-11-04), [D-143](#d-143--the-apis-content-security-policy-is-locked-by-default-oauth-redirects-are-compared-as-origins-a-socket-ends-at-its-tokens-expiry-and-a-shared-link-is-logged-by-host-alone-2026-11-05), [D-146](#d-146--a-pool-never-carries-the-session-max_concurrent_jobs-is-per-user-a-key-check-says-good-or-bad-only-when-the-provider-did-and-whispers-key-and-count-hold-on-every-sync-2026-11-05).

**Status-changed 2026-11-09:** the consequence about provider text in stored rows and messages is closed: what is stored, published or answered goes through `error_summary`, which scrubs the same shapes ([D-155](#d-155--stored-exception-text-goes-through-error_summary-an-empty-whisper-answer-is-charged-a-refused-dispatch-fails-a-new-run-and-leaves-an-approval-waiting-and-a-start-the-queue-refused-uses-up-nothing-2026-11-09), T-5.6.17, PR [#430](https://github.com/khoks/VideoResearchPro/pull/430)). Celery's result backend still keeps a failed task's traceback.

**Status-changed 2026-11-10:** the filter this entry put on `uvicorn.access` now also writes a user's search words by their length, chosen by parameter name (`q`, `search`, `focus`), so the access log keeps the path, the other parameters and the status but not what a user typed into a search box ([D-168](#d-168--the-access-log-writes-a-users-words-by-their-length-chosen-by-parameter-name-in-one-filter-a-fail-soft-handler-rolls-back-before-it-reads-and-an-imports-own-row-fails-as-importstopped-2026-11-10), T-4.11.4.5, PR [#454](https://github.com/khoks/VideoResearchPro/pull/454)).

**Status-changed 2026-11-10 (II):** the same filter now also writes a user's words in a URL path by their length, chosen by route template, today a fact's key in `DELETE /echo/context/{kind}/{key}`; a path no template matches is written whole ([D-171](#d-171--a-users-words-in-a-url-path-are-chosen-by-route-template-in-the-same-filter-a-path-no-template-matches-is-written-whole-and-the-import-script-answers-a-stop-on-one-line-and-names-what-a-part-way-stop-kept-2026-11-10), T-4.11.4.8, PR [#459](https://github.com/khoks/VideoResearchPro/pull/459)).

**Status-changed 2026-11-10 (III):** the fact key's template is now `DELETE /echo/context/{kind}/{key:path}`, and a words `:path` parameter takes the rest of the path, a trailing `/` included, so the key is written by its length however many `/` it holds ([D-174](#d-174--a-facts-key-is-the-rest-of-its-delete-routes-path-the-access-log-writes-all-of-it-and-the-echo-pages-form-accepts--in-a-label-2026-11-10), T-3.1.1.1, PR [#462](https://github.com/khoks/VideoResearchPro/pull/462)).

## D-152 — CORS reads the OAuth origin list, and the app keeps tiktoken's encoding in a folder of its own (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-4.11.3.3, T-8.8.6.5 and T-4.11.3.1 (PR [#427](https://github.com/khoks/VideoResearchPro/pull/427)) and its review fix, not ruled by the owner. **T-8.8.6.5 was filed as the owner's call.** The main session put it in batch 7 because it has no product trade-off; the owner is free to reverse it. Point 1 extends [D-143](#d-143--the-apis-content-security-policy-is-locked-by-default-oauth-redirects-are-compared-as-origins-a-socket-ends-at-its-tokens-expiry-and-a-shared-link-is-logged-by-host-alone-2026-11-05) point 4 to CORS, and point 5 extends [D-147](#d-147--the-rendering-parser-decides-what-is-a-heading-in-book-markdown-a-rewrite-parses-what-it-will-emit-and-the-suites-tiktoken-file-lives-at-a-fixed-path-2026-11-05) point 6 from the suite to the app.

**Context.**
- CORS `allow_origins` was hard-coded to `localhost:5173` and `:3000`, so an install at any other address needed a code edit, and a page at `:3000` passed CORS and then got a 400 at OAuth start.
- Nothing serves the app at `:3000`: its only uses were the CORS line itself and the docs describing it. A worktree's live check goes through the Vite proxy, Playwright serves its own fixtures, and the extension's host permissions bypass CORS.
- Only the suite kept tiktoken's encoding at a fixed path. A worker fetched into the temp directory, and `chunking._count_tokens` has no fallback, so a cleared temp directory plus a network drop would fail a job at chunking.
- With the folder named in the environment, tiktoken re-raises an error from writing what it downloaded. On Windows a rename onto an existing file raises `FileExistsError`, and tiktoken's lock covers one process's threads only.
- `docs/architecture.md` still said Whisper minutes were not recorded.

**Decision.**
1. **CORS reads the OAuth origin list.** The API answers the origin of `APP_BASE_URL` plus `OAUTH_ALLOWED_REDIRECT_ORIGINS`, compared by scheme, host and port by the same `app_origins.allows()` as OAuth start, read when each runs, with the parse cached by value. Starlette's `allow_origins` stays empty, so its `*` branch, which with credentials echoes any origin, is never taken.
2. **The setting keeps its name,** though it now covers more than it says, because a rename breaks every `.env` that pins it.
3. **An entry containing `*` is refused,** logged and skipped, never fatal, because the API allows credentials.
4. **`localhost:3000` is no longer a default.** An install that used it adds it to the list.
5. **The app keeps tiktoken's encoding in `TIKTOKEN_ENCODINGS_DIR`** (`./data/tiktoken`), set at import in the API and the worker. A `TIKTOKEN_CACHE_DIR` or `DATA_GYM_CACHE_DIR` already in the environment wins, so the suite keeps its arrangement. Empty means tiktoken's default. A copy in the temp folder is brought over in one atomic step. A folder that cannot be written leaves the default, with a warning. A missing encoding still fails loudly.
6. **Every load in `app/` goes through `tiktoken_cache.encoding()`,** which tolerates losing the first download to another process: it removes its own spare download and loads once more, reading the winner's copy under tiktoken's hash check. The same error twice is raised.

**Alternatives considered.**
- *A CORS list of its own.* Two lists can disagree, which is how a page at `:3000` passed CORS and failed at OAuth start.
- *A cross-process lock around the first download.* It needs a stale-lock timeout for a process that dies holding it, and still misses any process that does not take it.
- *A word-count fallback in chunking.* It would miscount silently.

**Consequences.**
- An app opened anywhere other than `http://localhost:5173`, `localhost:3000` included, needs `APP_BASE_URL` set to that address or its origin added, or every API call fails in the browser as a CORS error. The owner's `.env` sets neither, so the default install is unaffected.
- `backend/scripts/*` still use tiktoken's temp default (T-8.8.6.6), and `report_agent._count_tokens` and `knowledge_agent._count_tokens` still fall back to counting words, as before PR [#421](https://github.com/khoks/VideoResearchPro/pull/421) (T-8.8.6.7).
- The WebSocket handshake checks no `Origin`: CORS does not cover sockets, and the token travels as a subprotocol only the app's own page holds ([D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09)).
- An internationalised host in `APP_BASE_URL` is compared as written, not in the punycode a browser sends, as since PR [#420](https://github.com/khoks/VideoResearchPro/pull/420).
- `docs/architecture.md`'s usage paragraph now says Whisper seconds are recorded, that a scope writes part-way, and that the per-run Whisper limits count inside the task, not from the usage numbers ([D-131](#d-131--whisper-is-charged-at-the-shared-call-and-usage-is-written-part-way-on-a-timer-after-every-billed-response-2026-11-04)).
- Owner step: restart the API and the worker. On its first count each copies `cl100k_base` from the temp folder, or downloads it once.

**Linked initiatives / PRs.** [S-4.11.3](initiatives.md#s-4113--follow-ups-from-the-operations-pass) (T-4.11.3.1, T-4.11.3.3), [S-8.8.6](initiatives.md#s-886--follow-ups-from-the-reader-and-test-infra-pass) (T-8.8.6.5 to T-8.8.6.7); PR [#427](https://github.com/khoks/VideoResearchPro/pull/427); [D-131](#d-131--whisper-is-charged-at-the-shared-call-and-usage-is-written-part-way-on-a-timer-after-every-billed-response-2026-11-04), [D-143](#d-143--the-apis-content-security-policy-is-locked-by-default-oauth-redirects-are-compared-as-origins-a-socket-ends-at-its-tokens-expiry-and-a-shared-link-is-logged-by-host-alone-2026-11-05), [D-147](#d-147--the-rendering-parser-decides-what-is-a-heading-in-book-markdown-a-rewrite-parses-what-it-will-emit-and-the-suites-tiktoken-file-lives-at-a-fixed-path-2026-11-05), [D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09).

**Status-changed 2026-11-09:** the consequence about `backend/scripts/*` is closed. The nine scripts that count tokens name the app's folder; six of them already had it through an import of `job_tasks` (T-8.8.6.6, PR [#432](https://github.com/khoks/VideoResearchPro/pull/432), which needed no entry of its own). The agents' word-count fallbacks stay the owner's call (T-8.8.6.7).

## D-153 — A hook that answers its own failures says them through one helper, a hook whose callers differ takes an option, and a guard test holds the rule (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-3.4.1.17 (PR [#429](https://github.com/khoks/VideoResearchPro/pull/429)), not ruled by the owner. It extends [D-148](#d-148--a-401-ends-a-session-in-react-and-keeps-the-page-in-this-tab-a-waiting-share-gets-a-link-a-mutation-that-answers-its-own-failures-says-so-and-tabs-opens-on-focus-2026-11-05) point 5 from one hook to every page.

**Context.**
- D-148 point 5 moved `useCreateDraft`'s toast into its own `onError` with `meta.errorsShownHere`. The same double toast stayed on `VoiceTestPanel` and the Echo page, and a sweep found it at 33 sites in 12 files: a page toasted from its own `mutate` call, or ran a `useMutation` with no `meta`, beside the query client's global toast.
- The second toast was usually axios's "Request failed with status code 500" or "Network Error".
- TanStack drops a per-call `onError` once the component has unmounted and calls it only for an observer's last `mutate`. A toast there was lost when the reader left a long request, and said once for several dropped files.
- The page's own toasts also fired on a 401, after the session-expiry path had taken the reader to the sign-in page.
- `useCreateShare` and `useUploadShare` have two callers that answer a failure differently: the drop zone toasts, and quick share shows a line in its dialog.

**Decision.**
1. **A hook that answers its own failures says them through `toastMutationError(err, fallback)`,** from its own `onError`, and sets `meta: ERRORS_SHOWN_HERE` (both in `services/queryClient.ts`). The toast says the server's words first (a string `detail`, a quota refusal's `detail.message`, a 422 list), else the page's sentence, and nothing on a 401, which the session-expiry path owns (D-148 point 1). Fixed page sentences that ignored the server ("Revoke failed.", "Delete failed. The entry may already be gone.") now give way to the server's `detail` when one is sent.
2. **A hook whose callers answer failures differently takes an option** (`{ toastErrors }` on the two share hooks) rather than setting `meta` for every caller. Each hook's callers were checked before `meta` was set; the rest have one caller.
3. **A guard test that reads every module holds the rule, not review.** `services/__tests__/oneToastPerFailure.test.ts` fails on an error toast in a per-call `onError` (inline or through a local helper), in the `catch` of a `try` that awaits `mutateAsync`, or in a `.mutateAsync().catch()`, and on a `useMutation` with no `meta`.
4. **`describeCreateError` says nothing about a session on a 401,** and "Generation failed. Try again." where axios's message used to show.

**Alternatives considered.**
- *Dropping each page's toast and keeping the global one.* For a 500 or no answer the global toast alone says axios's words, where the page has a sentence (D-148's reasoning).
- *A per-call `onError` beside `meta`.* It is lost once the page unmounts, and runs for the last `mutate` only.
- *`meta` on the share hooks for every caller.* Quick share would lose the global toast it relies on beside its dialog line.
- *Review alone.* The pattern had already spread to 33 sites.

**Consequences.**
- A failure can still be said twice, inline and as a toast, where a page shows it itself: quick share, the tags manager, the delete-shelf modal, template delete, the connector callback page and the Echo bubble's ask turns (T-3.4.1.18). Quick share also needs a ruling on what is said when its dialog closes mid-request.
- The drop zone's success toast shows for the last dropped file only (T-3.4.1.19), and a failed disconnect in `ConnectorsPanel` leaves an unhandled rejection (T-3.4.1.20).
- `useCreateDraft` keeps its literal `meta` and its own wording from PR [#423](https://github.com/khoks/VideoResearchPro/pull/423).
- Frontend only: no setting, migration, route or device baseline changed, and no owner step.

**Linked initiatives / PRs.** E-3.4 (T-3.4.1.17 to T-3.4.1.20); PR [#429](https://github.com/khoks/VideoResearchPro/pull/429); [D-148](#d-148--a-401-ends-a-session-in-react-and-keeps-the-page-in-this-tab-a-waiting-share-gets-a-link-a-mutation-that-answers-its-own-failures-says-so-and-tabs-opens-on-focus-2026-11-05).

**Status-changed 2026-11-09:** its consequences are closed but one. A failure shown on the page now stands alone at the tags manager, the delete-shelf modal, a template's delete, the connector callback page and the Echo bubble's ask turns, every dropped file that lands is named, and a failed disconnect cannot reject unhandled ([D-156](#d-156--a-failure-said-on-the-page-stands-alone-a-dialog-waits-for-its-answer-the-drop-zone-names-each-file-that-lands-and-a-disconnect-goes-through-mutate-2026-11-09), T-3.4.1.18 to T-3.4.1.20, PR [#435](https://github.com/khoks/VideoResearchPro/pull/435)). Quick share's dialog waits for the owner's ruling (T-3.4.1.21).

**Status-changed 2026-11-10:** the rule and its guard now cover queries. A query's toast stands aside for each mounted reader that says the failure on the page, and a query hook whose readers differ takes `{ inlineErrors }`, as the ask hooks do ([D-167](#d-167--a-querys-toast-stands-aside-per-mounted-reader-a-reader-may-say-every-failure-or-only-a-first-load-and-the-guard-holds-each-condition-to-a-page-test-2026-11-10), T-3.4.1.26, PR [#452](https://github.com/khoks/VideoResearchPro/pull/452)).

## D-154 — A post's id dates it, a placeholder date is no date, a connector request gets one retry and X's only when unanswered, and the X token line reports configuration only (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-1.5.8.4, T-1.5.9.1 and T-1.5.11.2 (PR [#431](https://github.com/khoks/VideoResearchPro/pull/431)) and its review fixes, not ruled by the owner. Point 2 applies [D-072](#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19)'s rule that an unknown date is omitted, never a sentinel, to pasted pages. Point 3 refines [D-141](#d-141--a-connectors-search-raises-on-failure-a-refusal-is-a-24-hour-hold-on-a-sources-own-endpoint-non-video-sources-search-before-youtube-and-a-recording-counts-once-2026-11-05) point 2: a source counts as failed only after one retry on a transient error, and a refusal still reaches the hold once. OQ-42 is the owner's.

**Context.**
- Pasted social posts showed the site name or nothing as their author and had no date, so the library row, date preferences and Q&A's corpus span left them out. trafilatura's metadata pass suits articles and is weak on Facebook, Instagram, LinkedIn and X, and X serves a page with no metadata at all to a client that runs no script.
- `job_tasks._build_video_metadata` read `source_metadata_json` only as a dict, though the column holds JSON text, so a pasted page's author never reached its chunks and library Q&A called every pasted page "by Unknown".
- One transient 503 or timeout marked a source unavailable for the whole run.
- X bills what it serves ([D-139](#d-139--alembic-uses-the-url-a-caller-names-else-the-setting-and-alembicini-holds-none-2026-11-05)).
- The operator had no startup signal for whether X search was configured. `/health`'s `twitter_search_enabled` is also false while X is on hold, and the lifespan cannot read the hold without a database session.

**Decision.**
1. **A post's id is a date source.** An X status id and a LinkedIn activity, share or ugcPost id encode when the post was made. For those two platforms the id's date comes before the page's own, because the id is exact and the page may describe another post. Facebook and Instagram ids carry no usable time.
2. **A placeholder date is no date.** A date before 1995-01-01 (htmldate's floor) or after tomorrow is stored as unknown, for every pasted page, trafilatura's dates included. A known date is stored on `documents.published_at` as timezone-aware UTC, as the other connectors store it.
3. **One retry, in one helper, with no setting.** `app/sources/_http_retry.py` gives a request one more try after 1 s on a timeout, a failed or lost connection, a 5xx, or a 429 whose `Retry-After` is 5 s or less. A 5xx whose `Retry-After` is longer, and every other 4xx, are not retried, so a 401 or 403 reaches the hold once. Each try waits on the client's own rate limiter, and the log line names the host and the status or exception type. No source needs a different figure.
4. **X is retried only when it never answered:** on a timeout, `ReadTimeout` included as the task said, and on `ConnectError`; never on a broken read, a 5xx or a 429.
5. **An X name belongs to the post's own account.** A JSON-LD author's name is kept only when its handle (`alternateName`, else `identifier`) is absent or equals the post's handle, ignoring case. A bare-number identifier is an account id, never a handle. A title's `(@handle)` is read only from the poster's part, before " on X" or the caption's opening quote.
6. **The startup line reports configuration only.** `log_token_presence()` says whether `TWITTER_BEARER_TOKEN` is set and that tweet search is configured, never that it is on, and points to `/health`'s `source_holds`. It never includes the token, and nothing calls X.

**Alternatives considered.**
- *Per-subclass retry config in `BaseConnector`, as the task was filed.* No source needed a different figure, and one helper keeps the pacing and the log rule in one place.
- *Retrying every 4xx, or every 429.* A refusal would be asked twice, and a long `Retry-After` would stall the run.
- *The page's date over the id's on X and LinkedIn.* The page can describe a quoted or parent post.
- *Reading the hold at startup.* It opens a database session in the lifespan, which in the suite is bound to the developer's database.
- *Checking the token against X at startup.* It is a paid call.

**Consequences.**
- A `ReadTimeout` means X received the request. If X bills a response it served but we never read, the one retry costs one extra read; only the owner's account can show it (OQ-42).
- An article found by Brave search in a topic job still gets no `published_at`, since `job_tasks` takes the date from the candidate (T-1.6.7). The library row shows no author for a pasted page (T-1.5.8.6, the owner's call).
- Pages pasted before PR [#431](https://github.com/khoks/VideoResearchPro/pull/431) keep what they had: a backfill would re-fetch every page.
- Not retried, on purpose: podcast audio and in-feed transcripts, the pasted-page fetch, and YouTube with its D-051 breaker and Whisper.
- Nothing to do to ship. Confirming that X accepts the token takes one paid search, which stays the owner's.

**Linked initiatives / PRs.** E-1.5 ([S-1.5.9](initiatives.md#s-159--pluggable-twitter-bearer-token-byok) closes; T-1.5.8.4, T-1.5.8.6, T-1.5.11.2, OQ-42), E-1.6 (T-1.6.7); PR [#431](https://github.com/khoks/VideoResearchPro/pull/431); [D-009](#d-009--twitter--x-is-byok--opt-in-2026-04-25), [D-072](#d-072--two-dates-per-source-era-at-ingest-time-as-a-ranking-preference-qa-statistics-from-the-database-2026-10-19), [D-139](#d-139--alembic-uses-the-url-a-caller-names-else-the-setting-and-alembicini-holds-none-2026-11-05), [D-141](#d-141--a-connectors-search-raises-on-failure-a-refusal-is-a-24-hour-hold-on-a-sources-own-endpoint-non-video-sources-search-before-youtube-and-a-recording-counts-once-2026-11-05).

**Status-changed 2026-11-09:** the consequence about Brave articles is closed: an article found by search takes its page's date through the same date rule ([D-158](#d-158--a-job-task-returns-at-once-on-a-failed-row-a-job-dates-an-undated-row-and-its-stored-chunks-whisper-text-without-segments-is-a-transcription-and-a-manual-dispatchs-503-promises-nothing-2026-11-09), T-1.6.7, PR [#436](https://github.com/khoks/VideoResearchPro/pull/436)). Point 6's line reached the API's log only from PR [#437](https://github.com/khoks/VideoResearchPro/pull/437), because `app.*` INFO records had no handler under uvicorn's default logging ([D-157](#d-157--the-apps-log-lines-get-a-handler-that-steps-aside-while-the-root-logger-has-one-an-in-process-migration-restores-the-root-logger-and-a-log-line-names-no-email-recipient-subject-or-connector-account-2026-11-09), T-4.11.4.1).

## D-155 — Stored exception text goes through `error_summary`, an empty Whisper answer is charged, a refused dispatch fails a new run and leaves an approval waiting, and a start the queue refused uses up nothing (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-5.6.17, T-1.7.1.7 and T-5.2.17 (PR [#430](https://github.com/khoks/VideoResearchPro/pull/430)) and its review fixes, not ruled by the owner. Point 1 carries [D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09) point 4 from log records to stored and published text. Point 2 extends [D-149](#d-149--fetch_text-may-raise-transcriptioncutshort-a-sync-reads-only-what-the-library-lacks-the-job-limit-never-refuses-a-subscribe-and-a-held-source-can-be-tried-anyway-2026-11-09) point 1. Point 4 refines [D-115](#d-115--the-document-cap-counts-visible-documents-a-request-that-names-its-documents-is-all-or-nothing-and-nothing-is-granted-before-approval-2026-10-29)'s "nothing is granted before approval": an approval grants once its run is queued. OQ-43 is the owner's.

**Context.**
- D-151's record factory scrubs log lines only. A failed run's `error_message`, the socket's error event, a saved search's `last_error`, the report body and similar text are not log records, and a tenant reads them. A refused OpenAI key is quoted in its error, and a YouTube `HttpError` carries the install's key in its URL.
- Whisper can answer, be billed and leave no text. That read as a failed download, so neither Whisper limit heard about it.
- A `POST /jobs` whose dispatch raised answered 500 and left a `pending` row, which the job limit counts. A refused approval answered a bare 500, and its documents had already been granted, which the document cap counts.
- A voice test the queue refused was failed, but `tests_today` counted every row created that day, so three presses during a broker outage locked the user out until the next UTC day with nothing generated.

**Decision.**
1. **Exception text that is stored, published or answered goes through `error_summary`:** `Class: words` with a key's shapes taken out, or the class alone for a provider's refusal or anything it caused, with any length limit applied after the scrub. `_handle_failure` also scrubs whatever it is given. The class comes first so that a refusal, which keeps only its class, still says something. Sites that store only fixed sentences, our own exception text or a type name are left alone.
2. **An empty Whisper answer is `TranscriptionEmpty`,** a sibling of `TranscriptionCutShort` under a new base, `PaidTranscriptionLost(seconds)`, which `fetch_text` may raise. It is charged as one recording plus the seconds Whisper reported hearing, never the declared length, and the job learns it from the connector, never the meter ([D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25)). A base class rather than a subclass of `TranscriptionCutShort`, because an empty answer is not a failure part-way.
3. **A refused dispatch fails a new run and leaves an approval waiting.** `POST /jobs` marks the row failed with a sentence to submit again and answers 503 with no exception text, rather than 201 with a failed row as Author Studio does, so the form keeps what was typed and does not say the research was submitted. `PUT /jobs/{id}/approve` answers 503 and stays `awaiting_approval` with its picks, since failing it would throw the reviewed candidates away.
4. **An approval grants its documents only after its run is queued,** so a refused approval holds no place under the document cap. `visibility_service.grant` never raises and the resume task re-grants, so a queued approval still counts at once (T-5.2.10).
5. **A voice test the queue refused does not count toward `ECHO_VOICE_TESTS_PER_DAY`.** It is recognised by `status = failed`, no pairs and the `NOT_QUEUED` sentence, which is written in one place, rather than by a new column and its migration. A test that failed on its worker, or failed with no error, still counts.

**Alternatives considered.**
- *The scrubbed words alone, with no class name.* A refusal would store nothing readable (OQ-43).
- *`TranscriptionEmpty` as a subclass of `TranscriptionCutShort`.* An empty answer is not a cut.
- *201 with a failed row for `POST /jobs`.* The form would say the research was submitted for a run that never started.
- *Failing a refused approval.* It throws the reviewed candidates away.
- *A "never queued" column on voice tests.* A migration for a fact one sentence already marks.

**Consequences.**
- **User-visible:** `jobs.error_message` from an exception now starts with its class name (`RuntimeError: ...`).
- A dispatch that raised after the broker had accepted the message leaves a failed row a worker may still run, as #424's sync does (T-5.2.18). `run-now` and `send-now` still answer a bare 500 on a broker outage, with nothing stuck (T-5.2.19).
- The podcast single-file path drops a Whisper answer that has text but no segments. It is now charged as empty, and its words are still lost (T-1.7.1.8).
- Celery's result backend still keeps a failed task's traceback in Redis, as D-151 says.
- No migration and no new setting. Owner step: restart the API and the worker.

**Linked initiatives / PRs.** E-5.6 (T-5.6.17, OQ-43), E-1.7 (T-1.7.1.7, T-1.7.1.8), E-5.2 (T-5.2.17 to T-5.2.19), E-3.4 (the voice test's daily count); PR [#430](https://github.com/khoks/VideoResearchPro/pull/430); [D-111](#d-111--operator-only-tier-switching-and-an-honest-pricing-page-2026-10-25), [D-115](#d-115--the-document-cap-counts-visible-documents-a-request-that-names-its-documents-is-all-or-nothing-and-nothing-is-granted-before-approval-2026-10-29), [D-149](#d-149--fetch_text-may-raise-transcriptioncutshort-a-sync-reads-only-what-the-library-lacks-the-job-limit-never-refuses-a-subscribe-and-a-held-source-can-be-tried-anyway-2026-11-09), [D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09).

**Status-changed 2026-11-09:** three consequences are closed. A job task returns at once on a failed row, so a dispatch that raised after the broker took the message no longer brings the run back (T-5.2.18); `run-now` and `send-now` answer 503 (T-5.2.19); and the podcast path keeps a Whisper answer with text but no segments as a transcription (T-1.7.1.8), which amends the consequence about it. All in [D-158](#d-158--a-job-task-returns-at-once-on-a-failed-row-a-job-dates-an-undated-row-and-its-stored-chunks-whisper-text-without-segments-is-a-transcription-and-a-manual-dispatchs-503-promises-nothing-2026-11-09), PR [#436](https://github.com/khoks/VideoResearchPro/pull/436).

## D-156 — A failure said on the page stands alone, a dialog waits for its answer, the drop zone names each file that lands, and a disconnect goes through mutate (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-3.4.1.18 (all but quick share), T-3.4.1.19 and T-3.4.1.20 (PR [#435](https://github.com/khoks/VideoResearchPro/pull/435)) and its review fixes, not ruled by the owner. It extends [D-153](#d-153--a-hook-that-answers-its-own-failures-says-them-through-one-helper-a-hook-whose-callers-differ-takes-an-option-and-a-guard-test-holds-the-rule-2026-11-09) from two toasts to a line and a toast. What quick share says when its dialog closes mid-request is the owner's ruling (T-3.4.1.21).

**Context.**
- After D-153 a failure could still be said twice where a page shows it itself: a line where the reader acted, and the global toast. The tags manager (save, merge, delete), the delete-shelf modal, a template's delete, the connector callback page, the Echo bubble's ask turns and quick share's dialog did this.
- `useAskLibraryQA` and `useAskQAHistoryChat` have callers that differ. The library Q&A and history pages show no line and rely on the global toast; the Echo bubble shows the failure in its turn.
- With the toast standing aside, the line is the only message. The bubble's `requestErrorLine` read the status alone, so a rate-limit 429 said "resets tomorrow" when a minute was enough, and a plan's or a missing source's reason was lost.
- A line closed with its dialog before the answer arrives is said nowhere.
- TanStack calls a per-call `onSuccess` for an observer's last `mutate` alone, so the drop zone named only the last file of a drop, and only the second of a link and some text dropped back to back.
- `ConnectorsPanel` awaited `revoke.mutateAsync(...)` with nothing to catch a failure, so a failed disconnect rejected unhandled.

**Decision.**
1. **A failure said on the page stands alone.** Its hook sets `meta: ERRORS_SHOWN_HERE` with no toast of its own, and the line uses `inlineErrorMessage(err, fallback)` (`utils/apiError.ts`): the server's words first, else the page's sentence, and nothing on a 401, which the session-expiry path owns. A hook whose callers differ takes an option (`{ inlineErrors }` on the two ask hooks), as D-153 point 2 does. `ERRORS_SHOWN_HERE` now means that every failure is already said once: by the hook's toast, or by every caller's line.
2. **A dialog that says its own failure waits for the answer.** Close, Escape and the backdrop do nothing while its request is in flight (the delete-shelf modal, and the tags manager through `useIsMutating` on `tagEditsKey`), so its line is never closed away before it is written.
3. **Guard tests hold both sides.** D-153's guard gains a second half: a page that says a mutation's failure needs its hook's `meta`, always or through the option the caller sets to `true`. It is a ratchet with a named `NOT_YET` list (`QuickShare.tsx`, for the ruling, and `WelcomePage.tsx`, which the guard found) that fails when a listed file gets fixed. A third half fails when a caller of a hook that leaves its failures to the page calls it without a handler that says them.
4. **The drop zone says each dropped thing that lands in its own toast,** in today's words, from each request's own promise. A failure stays the hook's single toast, and nothing is said once the zone has unmounted, so a file's name never shows on the sign-in page. A drop takes at most 10 files.
5. **Disconnect uses `mutate` with a per-call `onSuccess`,** and the global toast stays its one message.

**Alternatives considered.**
- *Dropping the line and keeping the toast.* The line sits where the reader acted.
- *`meta` on the ask hooks for every caller.* The library Q&A and history pages would say nothing.
- *One summary toast per drop ("Added 3 files to Echo.").* New wording, and it waits for the slowest file. *A per-call `onSuccess`* runs for the last `mutate` only.
- *An empty `catch` around `mutateAsync` for disconnect.* `mutate` already handles the rejection and reads plainer.

**Consequences.**
- A line whose page is left before the answer says nothing: a template card left mid-delete, since navigation cannot be held. Before, the global toast said it. Quick share's dialog still shows its line beside the toast; the owner's ruling on what is said when it closes mid-request should cover the template card too (T-3.4.1.21).
- More doubles of the same kind remain, most through props or `isError` lines the guard cannot see (T-3.4.1.22), and `WelcomePage`'s first-run start can report a started run as not started (T-3.4.1.23).
- A failed disconnect's toast still says axios's words for a 500 or no answer, as before.
- Frontend only: no setting, migration, route or device baseline changed, and no owner step.

**Linked initiatives / PRs.** E-3.4 (T-3.4.1.18 to T-3.4.1.23); PR [#435](https://github.com/khoks/VideoResearchPro/pull/435); [D-148](#d-148--a-401-ends-a-session-in-react-and-keeps-the-page-in-this-tab-a-waiting-share-gets-a-link-a-mutation-that-answers-its-own-failures-says-so-and-tabs-opens-on-focus-2026-11-05), [D-153](#d-153--a-hook-that-answers-its-own-failures-says-them-through-one-helper-a-hook-whose-callers-differ-takes-an-option-and-a-guard-test-holds-the-rule-2026-11-09).

**Status-changed 2026-11-09:** two consequences are closed. The doubles T-3.4.1.22 named say one failure once, and the welcome page no longer reports a started run as not started (T-3.4.1.22, T-3.4.1.23). The consequence about a page left before the answer is wider: point 2's wait now reaches every control on a line's own surface, and every line whose page is left through the app's own navigation or the welcome page's Skip is said nowhere, which is T-3.4.1.21's case ([D-159](#d-159--a-lines-own-surface-waits-for-its-answer-and-the-apps-navigation-does-not-each-action-gets-its-own-line-a-started-run-is-never-offered-twice-and-the-guard-follows-a-line-through-props-and-iserror-2026-11-09), PR [#441](https://github.com/khoks/VideoResearchPro/pull/441)).

**Status-changed 2026-11-10:** `inlineErrorMessage` now also shows a `FormValidationError`'s words, which the app wrote for the reader, and still never any other exception's text ([D-165](#d-165--a-forms-own-words-travel-in-a-typed-error-a-surface-waits-only-for-its-own-save-a-control-that-would-replace-a-line-is-part-of-its-surface-and-a-lines-request-waits-for-whatever-would-take-the-line-away-2026-11-10), T-3.4.1.25, PR [#446](https://github.com/khoks/VideoResearchPro/pull/446)).

## D-157 — The app's log lines get a handler that steps aside while the root logger has one, an in-process migration restores the root logger, and a log line names no email recipient, subject or connector account (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-4.11.4.1 (PR [#437](https://github.com/khoks/VideoResearchPro/pull/437)) and its review fix, not ruled by the owner. It corrects [D-143](#d-143--the-apis-content-security-policy-is-locked-by-default-oauth-redirects-are-compared-as-origins-a-socket-ends-at-its-tokens-expiry-and-a-shared-link-is-logged-by-host-alone-2026-11-05)'s consequence that `text` shows `app.*` INFO lines only after a migration, and completes [D-154](#d-154--a-posts-id-dates-it-a-placeholder-date-is-no-date-a-connector-request-gets-one-retry-and-xs-only-when-unanswered-and-the-x-token-line-reports-configuration-only-2026-11-09) point 6, whose line reaches the API's log only from here. OQ-44 is the owner's.

**Context.**
- uvicorn's `LOGGING_CONFIG` configures only `uvicorn`, `uvicorn.error` and `uvicorn.access`, so the root logger has no handler. `main.py` lowered the `app` logger to INFO, but its records reached no handler: an INFO line was dropped, and a WARNING went out bare through `logging.lastResort`, with no time, level or logger. Reproduced on `d724247b`.
- The one exception was a process that had migrated in-process at startup. Alembic's `fileConfig` left its handler on root for the rest of the process, so the app's lines appeared, in Alembic's format and with no time.
- The same `configure_logging` runs in the worker, beat, Alembic and pytest, because `app/__init__.py` calls it everywhere, and Celery puts a handler on root only after the app has imported.
- Batch 8's live check found T-1.5.9.1's X-token startup line missing from the API's log. The password-reset email that CLAUDE.md says goes to the server log when `SMTP_HOST` is unset is logged at INFO, so in an ordinary API start it was dropped too.
- Once the app's INFO lines reach the log, what they say matters. One logged the first 80 characters of the user's question, one the recipient and subject of each delivered email (a saved-search alert's subject holds the user's question), and one a connector's account label, which a connector may set to an email address.

**Decision.**
1. **Under `LOG_FORMAT=text`, the app's lines get `AppStderrHandler` on the `app` logger, which writes only while the root logger has no handler, checked as each record comes in.** It writes to the current `sys.stderr` at INFO, as `time LEVEL logger: message`. Checking when a record arrives, not when the handler is added, covers every process that gives root a handler, before or after the app imports: Celery, Alembic's `fileConfig`, `LOG_FORMAT=json`, pytest and a script's `basicConfig`. Each line is then written once, in that handler's format. The handler is found by name, so configuring twice or reloading the module adds no copy. Root's handlers and level are left alone.
2. **An in-process Alembic command leaves the root logger as it found it** (`schema_init_service._keeping_the_root_logger`). The migration's own lines still show while it runs.
3. **A log line names no recipient or subject of an email SMTP delivered, and no connector's account label, and `chroma_service.query_collection` logs the question's length, not its text.** The SMTP-unset fallback still writes the whole email, recipient included, because the operator has to deliver it.

**Alternatives considered.**
- *A root handler or `basicConfig`.* It would write every library's INFO lines, httpx's whole URLs among them.
- *Removing the handler in Celery's `after_setup_logger`.* It misses Alembic, pytest and scripts.
- *`propagate=False` on `app`.* It hides the app's lines from Celery's format and from caplog.

**Consequences.**
- The API's stderr (`.uvicorn.err.log` under the launchers) now holds the app's own lines with time, level and logger. With `SMTP_HOST` unset it also holds live password-reset codes, valid for 30 minutes and single use, as documented.
- The fallback writes every email whole, a newsletter issue sent with **Send now** and saved-search alerts, which hold the user's question, included (OQ-44).
- In the worker, warnings logged before Celery sets up logging, such as the held `JWT_SECRET` warning, now carry time, level and logger instead of going out bare. Nothing after Celery's setup changes or doubles.
- Third-party loggers keep their visibility: in the API their WARNINGs still go through `lastResort`, and their INFO lines stay unwritten.
- Worker-only INFO lines that carry a user's words were already written and are unchanged (T-4.11.4.2). Under `--reload` or `--workers` the parent process never imports the app, as NFR-5.1 records.
- No migration and no new setting. Owner step: restart the API.

**Linked initiatives / PRs.** E-4.11 ([S-4.11.4](initiatives.md#s-4114--the-apis-own-log-lines): T-4.11.4.1 to T-4.11.4.3, OQ-44), E-1.5 (T-1.5.9.1); PR [#437](https://github.com/khoks/VideoResearchPro/pull/437); [D-143](#d-143--the-apis-content-security-policy-is-locked-by-default-oauth-redirects-are-compared-as-origins-a-socket-ends-at-its-tokens-expiry-and-a-shared-link-is-logged-by-host-alone-2026-11-05), [D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09), [D-154](#d-154--a-posts-id-dates-it-a-placeholder-date-is-no-date-a-connector-request-gets-one-retry-and-xs-only-when-unanswered-and-the-x-token-line-reports-configuration-only-2026-11-09).

**Status-changed 2026-11-09:** the consequence about worker-only lines is closed. The worker's lines name a user's words by length, place or kind, and an exception that can quote a request is logged by its frames and types ([D-160](#d-160--a-users-words-leave-the-workers-log-at-the-call-site-an-exception-that-can-quote-a-request-is-logged-by-its-frames-and-a-connectors-search-counts-as-a-shared-link-2026-11-09), T-4.11.4.2, PR [#442](https://github.com/khoks/VideoResearchPro/pull/442)). Batch 9's live check after the restart found the API's log carrying the app's own lines, the X-token line among them.

## D-158 — A job task returns at once on a failed row, a job dates an undated row and its stored chunks, Whisper text without segments is a transcription, and a manual dispatch's 503 promises nothing (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-5.2.18, T-5.2.19, T-1.6.7 and T-1.7.1.8 (PR [#436](https://github.com/khoks/VideoResearchPro/pull/436)) and its review fixes, not ruled by the owner. Point 1 extends [D-155](#d-155--stored-exception-text-goes-through-error_summary-an-empty-whisper-answer-is-charged-a-refused-dispatch-fails-a-new-run-and-leaves-an-approval-waiting-and-a-start-the-queue-refused-uses-up-nothing-2026-11-09) point 3 from the route to the worker. Point 2 extends [D-144](#d-144--a-fifth-voice-label-other-names-no-language-to-write-in-a-job-fills-gaps-and-only-the-backfill-rewrites-and-the-declared-audio-language-is-a-key-on-the-document-2026-11-05) point 2's "a job fills gaps" to `published_at`, through [D-154](#d-154--a-posts-id-dates-it-a-placeholder-date-is-no-date-a-connector-request-gets-one-retry-and-xs-only-when-unanswered-and-the-x-token-line-reports-configuration-only-2026-11-09) point 2's date rule. Point 3 amends D-155's consequence for the podcast path.

**Context.**
- A dispatch can raise after the broker has taken the message: the publish went out and the reply was lost. `POST /jobs` (D-155) and `_dispatch_subscription_sync` ([D-149](#d-149--fetch_text-may-raise-transcriptioncutshort-a-sync-reads-only-what-the-library-lacks-the-job-limit-never-refuses-a-subscribe-and-a-held-source-can-be-tried-anyway-2026-11-09)) then fail the row and tell the user the run never started, but a worker still gets the message. It brought the run back from `failed`, spent the owner's quota and model calls, and published progress for a run its page called failed.
- `POST /saved-searches/{id}/run-now` and `POST /author/newsletter/send-now` answered a bare 500 on a broker outage. Neither writes before it dispatches, and neither task dedupes a manual trigger.
- A Brave result's `age` is a relative string, so an article's `Candidate` had no date, and every searched article read as undated, though its page's date has been extracted since PR [#431](https://github.com/khoks/VideoResearchPro/pull/431). An existing row never took a `Candidate`'s date at all.
- The search phase re-fetches every candidate, a library row included, while the resume reuses an embedded row's chunks without writing them.
- Whisper can answer with the whole text and empty `segments`. On the podcast single-file path that answer has been charged as empty since PR [#430](https://github.com/khoks/VideoResearchPro/pull/430), and its words were lost. YouTube's `_synthesize_pseudo_segments` gives a segment only to a 30-second slot that gets a word, so sparse speech ends its timeline early.

**Decision.**
1. **A job task returns at once when its row is already `failed`,** before the usage scope opens and before any write or publish: the topic and channel first runs, the resume after approval and the subscription sync (`job_tasks._already_failed`). Only `failed`: `cancelled` and the transient states are unchanged. Nothing runs a failed row again in place: no route retries a run, the scheduler queues no job task, the tasks never call `self.retry`, and a redelivery after a worker died finds the row in a transient state.
2. **A job dates an undated shared row: the `Candidate`'s date first, then the page's, never over a date the row already has** (`_fill_published_at`). The page's date goes through `to_utc_post_date`: UTC, and unknown before 1995 or after tomorrow. When the row is already embedded, the job stamps its stored chunks after its commit (metadata only, fail-soft), as T-1.17.3.3 does for the era, so a job never leaves a row's date and its chunks' dates disagreeing. As before, only a backfill rewrites.
3. **Whisper's text with no segments is a transcription on every path.** It is kept as YouTube's pseudo-segments, with the timeline ending where Whisper stopped (`_end_where_whisper_stopped`), and charged once, as read. Only an answer with no words is `TranscriptionEmpty`. YouTube's helper is unchanged: there the declared length covers the minute cap.
4. **A 503 from a manual dispatch promises nothing either way.** The broker may have taken the message, so the sentence says the run or issue may or may not happen and asks the user to check its history or their outputs before pressing again. The broker's error, which can hold its URL and password, goes only to the log, where the record factory scrubs it.

**Alternatives considered.**
- *`cancelled` in the same guard.* The brief kept cancelled unchanged; it is the follow-up T-5.2.20.
- *Dating the row without stamping its stored chunks.* The row and the corpus statistics would be dated and the chunks not, as in the PR's first version.
- *Copying YouTube's pseudo-segment code into the podcast connector.* The connector calls YouTube's helper and stretches only its last segment.
- *"Nothing was sent, try again."* Untrue when the broker took the message. *A dedupe key minted by the route* does not help, because the user's retry is a new request with a new key.

**Consequences.**
- A cancelled run whose task is delivered anyway comes back, because each entry point writes a status before it reads `_is_cancelled`, and a worker that picks a task up before the route marks the row failed runs on (T-5.2.20).
- Articles embedded before this that no new search finds stay undated. Dating them needs a backfill that re-fetches pages, a network action for the owner (T-1.6.8).
- YouTube's own sparse-text timeline still ends early; its declared length covers the minute cap.
- No migration and no new setting. Owner step: restart the API and the worker.

**Linked initiatives / PRs.** E-5.2 (T-5.2.18 to T-5.2.20), E-1.6 (T-1.6.7, T-1.6.8), E-1.7 (T-1.7.1.8); PR [#436](https://github.com/khoks/VideoResearchPro/pull/436); [D-144](#d-144--a-fifth-voice-label-other-names-no-language-to-write-in-a-job-fills-gaps-and-only-the-backfill-rewrites-and-the-declared-audio-language-is-a-key-on-the-document-2026-11-05), [D-149](#d-149--fetch_text-may-raise-transcriptioncutshort-a-sync-reads-only-what-the-library-lacks-the-job-limit-never-refuses-a-subscribe-and-a-held-source-can-be-tried-anyway-2026-11-09), [D-154](#d-154--a-posts-id-dates-it-a-placeholder-date-is-no-date-a-connector-request-gets-one-retry-and-xs-only-when-unanswered-and-the-x-token-line-reports-configuration-only-2026-11-09), [D-155](#d-155--stored-exception-text-goes-through-error_summary-an-empty-whisper-answer-is-charged-a-refused-dispatch-fails-a-new-run-and-leaves-an-approval-waiting-and-a-start-the-queue-refused-uses-up-nothing-2026-11-09).

**Status-changed 2026-11-09:** the consequence about a cancelled run and a run picked up before the route failed it is closed, and point 1 is extended. The start guard reads `cancelled` beside `failed`, and every status write a job task makes is conditional on the row being neither ([D-161](#d-161--a-job-tasks-status-writes-are-one-conditional-update-the-first-stops-words-win-a-progress-callback-may-end-the-search-and-embedded_in_chroma-follows-the-chunks-2026-11-09), T-5.2.20, PR [#440](https://github.com/khoks/VideoResearchPro/pull/440)).

**Status-changed 2026-11-09:** point 1 now also covers `completed`. A job task delivered again after its run completed returns at once, and a first phase leaves alone a row at `awaiting_approval` or past it ([D-163](#d-163--a-progress-line-is-written-before-it-is-published-a-cancel-that-loses-the-race-answers-with-the-runs-end-and-revokes-nothing-and-completed-is-a-stopped-status-2026-11-09), T-5.2.23, PR [#449](https://github.com/khoks/VideoResearchPro/pull/449)).

## D-159 — A line's own surface waits for its answer and the app's navigation does not, each action gets its own line, a started run is never offered twice, and the guard follows a line through props and `isError` (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-3.4.1.22 and T-3.4.1.23 (PR [#441](https://github.com/khoks/VideoResearchPro/pull/441)) and its review fix, not ruled by the owner. It applies [D-156](#d-156--a-failure-said-on-the-page-stands-alone-a-dialog-waits-for-its-answer-the-drop-zone-names-each-file-that-lands-and-a-disconnect-goes-through-mutate-2026-11-09) to the last sites the board named, and says how far D-156 point 2's wait reaches. What is said when a page is left mid-request stays the owner's ruling (T-3.4.1.21); once it exists, it should replace point 2's exception.

**Context.**
- After D-156 a failure was still said twice, on a line and in the global toast, at the welcome page (saving the channels, the first-run start, the approval), a run's approval section, subscribe and sync on the channel page and the library's channel list, the trust weight, the shelf form, the template dialog and the label pickers. Most came through a `mutateAsync` passed in as a prop, or through an `isError` line, which D-156's guard could not see.
- `useCreateJob`, `useUpdateOnboarding`, `useUpdateTemplate` and `useRemoveJobFromShelf` also have callers that show no line and rely on the global toast.
- With the toast standing aside, a line closed away before its answer arrives is said nowhere. A dialog, a popover, a wizard step and a shared list can each be closed or moved on mid-request. The sidebar, the browser's Back and a link elsewhere on the page cannot be held on any page.
- On both channel pages one line served subscribe and sync, so a subscribe failure hid a sync failure. The library's channel list has one line for all its rows.
- The welcome page's start caught a failed start and a failed save of the step after it in one `catch`, said "The run could not be started" for both and left "Start the run" on the page, so a run that had started could be started again.

**Decision.**
1. **The last sites follow D-156.** A hook whose every caller shows a line sets `meta: ERRORS_SHOWN_HERE`; a hook whose callers differ takes `{ inlineErrors }` (`useCreateJob`, `useUpdateOnboarding`, `useUpdateTemplate`, `useRemoveJobFromShelf`). Each line uses `inlineErrorMessage`. The trust weight's line gives the server's words instead of a fixed sentence.
2. **Every control on a line's own surface waits for its answer, and the app's own navigation does not.** A dialog's Cancel, Escape and backdrop, a popover's outside click, Escape and button, a wizard's Back and steps, a run's Cancel during an approval and the other rows of a shared list wait while the request is in flight. The sidebar, the browser's Back, links elsewhere on the page and the welcome page's Skip, which only leaves for /submit and is promised always to work, stay free. A line whose page is left that way says nothing: T-3.4.1.21's case.
3. **A page with two actions gives each its own line, and a list whose rows share one mutation holds its other rows while one row's request is in flight,** since one line follows the last press.
4. **A run that started is never offered again.** A failed start and a failed save of the step after it are told apart. When the run started and recording it failed, the step says "The run started." with the server's words and offers no second start, even after the reader leaves the step and comes back, unless that run has since failed. "See its progress" retries the save, and the global toast says a second failure.
5. **The guard follows a line through a callback prop and through `isError`,** in both its second and third halves. It stays a ratchet: `NOT_YET` names `QuickShare.tsx` and the seven files the new reading found.

**Alternatives considered.**
- *Keeping the toast wherever a page can be left mid-request.* Every page can be left through the sidebar, so that keeps every double, and the welcome page could not leave the guard's list.
- *Holding Skip too.* It took away the page's one advertised exit, and the API client has no timeout, so a hung `POST /jobs` would trap a new reader. It also protected nothing, since Skip is the sidebar's case (the review's finding).
- *One line for subscribe and sync.* Once the toast stands aside, one failure hides the other.
- *Fixing the seven newly found files in the same PR.* They were outside the task; the ratchet fails as each is fixed (T-3.4.1.24).

**Consequences.**
- A line whose page is left through the app's navigation or the welcome page's Skip says nothing, as a template card left mid-delete already did. The owner's T-3.4.1.21 ruling can cover all of them with one mechanism.
- The shelves page's edit form now resets by value, so a failed edit's line stays; before, the next render wiped it and only the toast spoke.
- The Echo bubble's draft turn was not a double, since it calls `echoApi.draft` directly. It now says the server's words first and nothing on a 401.
- Seven files still say one failure twice (T-3.4.1.24). The submit form's "Save as template" still shows the dialog's fallback sentence for its own validation message (T-3.4.1.25).
- Frontend only: no setting, migration, route or device baseline changed, and no owner step.

**Linked initiatives / PRs.** E-3.4 (T-3.4.1.21 to T-3.4.1.25); PR [#441](https://github.com/khoks/VideoResearchPro/pull/441); [D-153](#d-153--a-hook-that-answers-its-own-failures-says-them-through-one-helper-a-hook-whose-callers-differ-takes-an-option-and-a-guard-test-holds-the-rule-2026-11-09), [D-156](#d-156--a-failure-said-on-the-page-stands-alone-a-dialog-waits-for-its-answer-the-drop-zone-names-each-file-that-lands-and-a-disconnect-goes-through-mutate-2026-11-09).

**Status-changed 2026-11-10:** two consequences are closed. The seven files say one failure once, and the template dialog shows the form's own validation words (T-3.4.1.24, T-3.4.1.25). Point 2's surface now also takes in a control that would put something else in a line's place, and a line's own request waits for a request that would take the line away; the library page's tabs and the Echo panel's auto-close on phones join T-3.4.1.21's case ([D-165](#d-165--a-forms-own-words-travel-in-a-typed-error-a-surface-waits-only-for-its-own-save-a-control-that-would-replace-a-line-is-part-of-its-surface-and-a-lines-request-waits-for-whatever-would-take-the-line-away-2026-11-10), PR [#446](https://github.com/khoks/VideoResearchPro/pull/446)).

## D-160 — A user's words leave the worker's log at the call site, an exception that can quote a request is logged by its frames, and a connector's search counts as a shared link (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-4.11.4.2 (PR [#442](https://github.com/khoks/VideoResearchPro/pull/442)) and its review fixes, not ruled by the owner. It carries [D-157](#d-157--the-apps-log-lines-get-a-handler-that-steps-aside-while-the-root-logger-has-one-an-in-process-migration-restores-the-root-logger-and-a-log-line-names-no-email-recipient-subject-or-connector-account-2026-11-09) point 3 from the API's INFO lines to every line the worker writes, at every level, and extends [D-143](#d-143--the-apis-content-security-policy-is-locked-by-default-oauth-redirects-are-compared-as-origins-a-socket-ends-at-its-tokens-expiry-and-a-shared-link-is-logged-by-host-alone-2026-11-05) point 6 to connector searches. Hiding a database error's bound values when `DEBUG` is off was in the PR and was taken out on review; it is the owner's call (OQ-45, [S-4.11.4](initiatives.md#s-4114--the-apis-own-log-lines)).

**Context.**
- Celery's root handler writes the worker's INFO lines to disk. Several held what a user typed: a topic job's `topic=`, the planner's queries in `search_videos`, Mastodon's query and hashtags, and channel inputs, which can be a pasted link carrying a share token.
- Exception text carries them too. A YouTube `HttpError` quotes its request URI with `q=`, an httpx error its URL with `?query=`, and a database error its statement's bound values, and `logger.exception` writes that text.
- httpx writes its own INFO request line, URL included, for every request, so every connector search wrote its query to the worker's log. Echo's GitHub connector calls URLs that name the account's login and repositories.
- A user's words have no shape a record factory could find, unlike a key ([D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09)).
- `DEBUG=true` turns on SQLAlchemy's echo, which writes each statement's bound values (checked on 2.0.48). The docs did not say so.

**Decision.**
1. **A user's words leave the worker's log at the call site.** A line names a topic, a question or a planner query by its length or its place ("broad search 1 of 2"). A channel input is named by its kind (`loggable_channel_input`): an id or an `@handle` as written, a link by its host, a name by its length. A failed YouTube request is named by its status and Google's reason code. The words stay on the row the user reads, such as the run's `error_message`.
2. **An exception whose text can quote a request is logged by `traceback_without_text`, at `logger.error`, not `logger.exception`.** The frames and types are kept, causes and contexts included, and every message is dropped.
3. **A connector's search counts as a shared link for httpx's request line, and so do Echo's GitHub calls.** The eight search methods and GitHub's `_default_request` send inside `shared_url_fetch()`. `errors_by_source_type` carries the exception's type alone, and a GitHub error names the endpoint, not the login or the repository.
4. **Public names stay.** A YouTube channel id or `@handle`, and Mastodon, Bluesky and X handles and post ids, are logged as written, as #437 kept X handles. An input counts as a channel id only by its exact shape (`is_channel_id`: `UC` and 22 characters of the id alphabet).
5. **`DEBUG` behaves as before, and the docs now say that its echo writes bound values.** A value over 300 characters keeps its first and last 149.

**Alternatives considered.**
- *A record-factory net like D-151's.* A user's words have no shape to detect.
- *`hide_parameters=not settings.DEBUG` on the engine.* It would close every database error's values at once, in tracebacks, task failure lines and stored errors. The brief kept `DEBUG`'s behaviour, so it is the owner's call (OQ-45).
- *Dropping handles too.* They are public names that help the operator, as #437 decided for X.

**Consequences.**
- A 24-character name that starts with `UC`, such as "UC Berkeley Data Science", is no longer returned as a channel id. It goes to the search fallback, as a name does.
- `social_classify`'s fallback lines log a reply's length, its JSON type or the failing schema fields, never a value.
- With `DEBUG` on or off, a database error's text still quotes its values wherever such an error is not logged by its frames (OQ-45). The SMTP-unset fallback still writes every email whole (OQ-44).
- API-only lines that can carry a user's words remain: an Echo import's file name on an importer failure, the operator addresses in the startup warning, and `echo_agent`'s classify and critique errors (T-4.11.4.4).
- Older `.celery.*.log` files still hold what was written before. No migration and no new setting. Owner step: restart the worker and the API.

**Linked initiatives / PRs.** E-4.11 ([S-4.11.4](initiatives.md#s-4114--the-apis-own-log-lines): T-4.11.4.2, T-4.11.4.4, OQ-44, OQ-45); PR [#442](https://github.com/khoks/VideoResearchPro/pull/442); [D-143](#d-143--the-apis-content-security-policy-is-locked-by-default-oauth-redirects-are-compared-as-origins-a-socket-ends-at-its-tokens-expiry-and-a-shared-link-is-logged-by-host-alone-2026-11-05), [D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09), [D-157](#d-157--the-apps-log-lines-get-a-handler-that-steps-aside-while-the-root-logger-has-one-an-in-process-migration-restores-the-root-logger-and-a-log-line-names-no-email-recipient-subject-or-connector-account-2026-11-09).

**Status-changed 2026-11-09:** the consequence about API-only lines is closed. The API's warnings and errors follow the same rules: an operator address is named by its place and a mask, Echo's model failures by type and status, and a file name a user chose by its extension and length ([D-164](#d-164--the-apis-warnings-and-errors-carry-no-users-words-an-operator-by-place-and-mask-echos-model-failures-by-type-and-status-a-chosen-file-name-by-its-extension-and-length-and-a-failure-logged-by-its-frames-is-never-re-raised-bare-2026-11-09), T-4.11.4.4, PR [#447](https://github.com/khoks/VideoResearchPro/pull/447)). OQ-45 is unchanged.

**Status-changed 2026-11-10:** point 2 now reaches the four worker sites #442 missed, each a `logger.exception` around a database write: the newsletter's and the saved search's notification writes, the saved-search run's handler and the scheduler tick's inbox sync ([D-168](#d-168--the-access-log-writes-a-users-words-by-their-length-chosen-by-parameter-name-in-one-filter-a-fail-soft-handler-rolls-back-before-it-reads-and-an-imports-own-row-fails-as-importstopped-2026-11-10), T-4.11.4.7, PR [#454](https://github.com/khoks/VideoResearchPro/pull/454)). OQ-45 is unchanged.

## D-161 — A job task's status writes are one conditional update, the first stop's words win, a progress callback may end the search, and `embedded_in_chroma` follows the chunks (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-5.2.20 and T-8.8.6.12 (PR [#440](https://github.com/khoks/VideoResearchPro/pull/440)) and its review fixes, not ruled by the owner. It extends [D-158](#d-158--a-job-task-returns-at-once-on-a-failed-row-a-job-dates-an-undated-row-and-its-stored-chunks-whisper-text-without-segments-is-a-transcription-and-a-manual-dispatchs-503-promises-nothing-2026-11-09) point 1 from `failed` to `cancelled` and from the start to every status write, and [D-155](#d-155--stored-exception-text-goes-through-error_summary-an-empty-whisper-answer-is-charged-a-refused-dispatch-fails-a-new-run-and-leaves-an-approval-waiting-and-a-start-the-queue-refused-uses-up-nothing-2026-11-09) point 3 to the approval's own write: a route that writes after it dispatches writes only from the status it expects. T-8.8.6.12 applies [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19) to the subscription sync.

**Context.**
- `POST /jobs/{id}/cancel` writes `cancelled`, then revokes. A revoke reaches only the workers alive at that moment and lives in their memory, so a task still queued while no worker was up, or across a restart, is delivered later. Each entry point wrote `searching` or `extracting` before it read `_is_cancelled`, so such a run came back.
- The solo pool cannot terminate a running task, so on the owner's Windows setup a cancel during the report ended `completed`.
- A worker that picked a task up before the route marked the row failed ran on and wrote over `failed` at its next status change, and `_handle_failure` wrote `failed` over a cancelled run that then raised.
- `PUT /jobs/{id}/approve` wrote `extracting` after queuing the resume, so a resume that had already failed was stranded at `extracting`.
- The search agent swallowed every progress-callback error, so a run cancelled during its search still published "Found N videos", which flipped the open page back from Cancelled, and fetched every non-video post with its stance calls ([D-023](#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28)). The non-video store held one SQLite write transaction across every fetch, so the cancel route's write waited on the lock.
- Both extraction loops committed `embedded_in_chroma=True` as each document was chunked, while its chunks reached Chroma only at the RAG build. A run stopped or raising between the two left documents flagged with no chunks, which every later job reused without inserting, so no Q&A could retrieve them.
- The subscription sync still joined a job's documents on `video_id`.

**Decision.**
1. **A job task's status writes are one conditional UPDATE.** `_write_unless_stopped` writes only `WHERE status NOT IN ('failed', 'cancelled')`. Refused, `_update_job` raises `_RunStopped`, which each entry point catches before its `except Exception`. The start guard (`_already_stopped`) and the per-item checks (`_is_stopped`) read both stopped states and stay as the cheap way to stop spending, with a new check before the YouTube search agent; the conditional write is what guarantees the row.
2. **Progress writes take the same condition and are published only when written,** so a stopped run's page gets no event that shows it running.
3. **The first stop's words win.** `_handle_failure`, its fallback and `_backstop_orphan` are conditional too, so the route's sentence or the cancel stays, and a later failure goes only to the log. A report built for a run stopped meanwhile is deleted.
4. **A route that writes after it dispatches writes only from the status it expects** (`update_job_status(..., only_from=...)`, used by approve).
5. **A progress callback may end the search agent through one named exception, `SearchStopped`;** every other callback error stays swallowed. The topic search's non-video store checks before each candidate and commits each one, so a cancel lands between fetches and one bad candidate is rolled back alone.
6. **`embedded_in_chroma` is set only after `insert_chunks` returns,** in one commit for the run (`_insert_and_mark_embedded`), so the flag means the chunks are in the library.
7. **The subscription sync selects a job's documents through `job_documents` on `document_id`** (`_approved_documents`, shared with the resume) and reads the transcript cache by `document_id` first.

**Alternatives considered.**
- *More checks through the loop and no conditional write.* A stop that lands between a check and a write is still written over.
- *Letting every callback error end the agent.* A bug in a progress report would end a healthy search.
- *Flagging each document as it is chunked and clearing the flag on failure.* A crash between the two still strands it.
- *Gating every standalone `publish_progress`.* A read per publish, for a short window (T-5.2.21).

**Consequences.**
- On the solo pool a cancel during the report now ends `cancelled`, and the unused report file is removed.
- A standalone progress publish can still go out between a stop and the next check (T-5.2.21). The cancel route's own write is unconditional and can write `cancelled` over a row that completed or failed between its read and its write (T-5.2.22). `completed` is not a stopped status, so a redelivery after a worker died between writing it and the ack runs the run again (T-5.2.23).
- Documents that older runs left flagged with no chunks are not repaired. Finding them takes a check of the library against Chroma and a write run, the owner's (T-5.2.24).
- No migration and no new setting. Owner step: restart the API and the worker.

**Linked initiatives / PRs.** E-5.2 (T-5.2.20 to T-5.2.24), E-8.8 (T-8.8.6.12); PR [#440](https://github.com/khoks/VideoResearchPro/pull/440); [D-023](#d-023--social_classify_stance-invoked-inline-inside-each-connector-2026-04-28), [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19), [D-155](#d-155--stored-exception-text-goes-through-error_summary-an-empty-whisper-answer-is-charged-a-refused-dispatch-fails-a-new-run-and-leaves-an-approval-waiting-and-a-start-the-queue-refused-uses-up-nothing-2026-11-09), [D-158](#d-158--a-job-task-returns-at-once-on-a-failed-row-a-job-dates-an-undated-row-and-its-stored-chunks-whisper-text-without-segments-is-a-transcription-and-a-manual-dispatchs-503-promises-nothing-2026-11-09).

**Status-changed 2026-11-09:** three consequences are closed and point 1 is extended. A progress line is written before it is published, a cancel never writes over a run that ended, and `completed` is a stopped status ([D-163](#d-163--a-progress-line-is-written-before-it-is-published-a-cancel-that-loses-the-race-answers-with-the-runs-end-and-revokes-nothing-and-completed-is-a-stopped-status-2026-11-09), T-5.2.21 to T-5.2.23, PR [#449](https://github.com/khoks/VideoResearchPro/pull/449)); the gate this entry's alternatives set aside at a read per publish is adopted at a write's cost. The documents older runs left flagged with no chunks have a dry-run check, which found none on the live store ([D-162](#d-162--a-document-counts-as-embedded-when-any-chunk-names-it-every-doubt-keeps-the-flag-a-document-with-no-words-keeps-it-and-the-check-embeds-nothing-2026-11-09), T-5.2.24, PR [#448](https://github.com/khoks/VideoResearchPro/pull/448)).

## D-162 — A document counts as embedded when any chunk names it, every doubt keeps the flag, a document with no words keeps it, and the check embeds nothing (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-5.2.24's check (PR [#448](https://github.com/khoks/VideoResearchPro/pull/448)) and its review fix, not ruled by the owner. It gives [D-161](#d-161--a-job-tasks-status-writes-are-one-conditional-update-the-first-stops-words-win-a-progress-callback-may-end-the-search-and-embedded_in_chroma-follows-the-chunks-2026-11-09) point 6's flag a repair path for the documents older runs stranded. The `--write` run is the owner's step, and the live dry run found nothing for it to do.

**Context.**
- Before #440 ([D-161](#d-161--a-job-tasks-status-writes-are-one-conditional-update-the-first-stops-words-win-a-progress-callback-may-end-the-search-and-embedded_in_chroma-follows-the-chunks-2026-11-09)), both extraction loops committed `embedded_in_chroma=True` as each document was chunked, while its chunks reached Chroma only at the RAG build, so a run that stopped between the two left documents flagged with no chunks. Before [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19), `insert_chunks` also skipped every chunk without a `video_id`, while the routes still flagged those documents.
- The approval resume and the subscription sync take three branches. A flagged document with cached text is reused: re-chunked for the report, nothing inserted. An unflagged one with cached text is re-chunked and inserted. One with no usable cache is fetched again, flagged or not. Only the first strands a document, and then no job or library Q&A retrieves it.
- Chunks have named their document four ways: the `document_id` metadata field (since 2026-10-19, stamped on older chunks by the startup backfill), `(source_type, source_id)` and `video_id` metadata, and the chunk id, `{video_id}:{n}` for YouTube and `{document_id}:{n}` otherwise.
- The API's startup creates the configured collection with `get_or_create_collection`. An install that embedded under the legacy `videoresearchpro_global` and lost its `CHROMA_GLOBAL_COLLECTION_NAME` pin reads an empty `pratidhvani_global`, in which every flagged document looks chunkless.

**Decision.**
1. **A document counts as embedded when any chunk names it,** by `document_id`, `(source_type, source_id)`, `video_id` or chunk id. Clearing the flag on a document that does have chunks costs an upsert at the next job; the opposite mistake keeps a document out of retrieval.
2. **The check reads metadata only.** It opens the collection with `get_collection(..., embedding_function=None)`, so it never creates the collection or loads a model. It reads no chunk text, makes no model or network call, and prints ids and counts, never titles or text. The dry run is the default, and on SQLite its session runs with `PRAGMA query_only`.
3. **Every doubt keeps the flag.** `--write` re-checks each document against Chroma just before clearing it and clears with a conditional `UPDATE ... WHERE embedded_in_chroma IS TRUE`. It writes nothing on a partial scan, a missing collection, a store with chunks that match no document in this database, or an empty collection while documents are flagged. The last stops the dry run too, naming `CHROMA_GLOBAL_COLLECTION_NAME` and `CHROMA_PERSIST_DIR`, and only `--empty-store-ok` clears against a store that really was emptied.
4. **A document whose cached text has no words keeps its flag,** since the next job would chunk nothing and set it again. The report counts these as `empty`, beside `cached` and `fetch_again`.
5. **The check changes nothing in Chroma and embeds nothing.** An `--embed` option waits until a dry run finds documents to repair.

**Alternatives considered.**
- *An `--embed` option that chunks and inserts the cached text.* It would be a second chunking path outside the job task, keeping the language profile, the era call, the English rendering and the visual annotations in step with the two loops, with model spend, a re-extraction for a PDF and a network fetch for a pasted page. The live store has nothing to repair, and a cleared cached document is embedded by the next job that selects it.
- *Counting a document as embedded by its `document_id` field alone.* Chunks the startup backfill has not stamped, and chunks named only by their id, would look chunkless, and a write would clear their flags.
- *Trusting an empty collection.* It is the likeliest form of the wrong-store mistake, and a write would clear every flag (the review's finding).

**Consequences.**
- The read-only dry run on the live store on 2026-11-09 scanned 8,567 chunks in `pratidhvani_global`: 254 documents flagged embedded, all videos, every one with chunks, and 0 to clear. A SQL count over a read-only snapshot agreed. `--write` was not run.
- A cleared document that no job selects again stays out of retrieval until one does, which includes every PDF and any pasted page no search finds again. `--embed` is the follow-up if a dry run finds such documents (T-5.2.25).
- A configured collection that holds a few chunks of this database while most sit in the legacy collection passes every guard, and the documents only in the legacy collection would look chunkless (T-5.2.26).
- A cached transcript with no words is still chunked into nothing and flagged embedded by the job loops, before and after #440 (T-5.2.27).
- No migration, no new setting and no restart. Owner steps: the dry run whenever wanted, and `--write` only if it finds documents, run while no job is ingesting.

**Linked initiatives / PRs.** E-5.2 (T-5.2.24 to T-5.2.27); PR [#448](https://github.com/khoks/VideoResearchPro/pull/448); [D-070](#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19), [D-161](#d-161--a-job-tasks-status-writes-are-one-conditional-update-the-first-stops-words-win-a-progress-callback-may-end-the-search-and-embedded_in_chroma-follows-the-chunks-2026-11-09).

**Status-changed 2026-11-10:** point 3 now reaches across the store. The check refuses, its dry run included, while any other collection holds chunks of this database's documents, which closes the consequence about a library split between a legacy collection and the configured one ([D-166](#d-166--the-embedded-flag-check-refuses-while-another-collection-holds-chunks-of-this-library-told-apart-by-name-and-by-shape-and-its-advice-follows-the-collections-kind-2026-11-10), T-5.2.26, PR [#451](https://github.com/khoks/VideoResearchPro/pull/451)). Of the other two, the `--embed` option waits for a dry run that finds documents (T-5.2.25), and the empty document's flag is closed with no change, since point 4 already keeps it and clearing it would make every later job read the empty text again (T-5.2.27).

## D-163 — A progress line is written before it is published, a cancel that loses the race answers with the run's end and revokes nothing, and `completed` is a stopped status (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-5.2.21, T-5.2.22 and T-5.2.23 (PR [#449](https://github.com/khoks/VideoResearchPro/pull/449)) and its review fixes, not ruled by the owner. It closes the three edges [D-161](#d-161--a-job-tasks-status-writes-are-one-conditional-update-the-first-stops-words-win-a-progress-callback-may-end-the-search-and-embedded_in_chroma-follows-the-chunks-2026-11-09) left, extends D-161 point 1's condition and [D-158](#d-158--a-job-task-returns-at-once-on-a-failed-row-a-job-dates-an-undated-row-and-its-stored-chunks-whisper-text-without-segments-is-a-transcription-and-a-manual-dispatchs-503-promises-nothing-2026-11-09) point 1's start guard to `completed`, and adopts, at a write's cost, the gate D-161's alternatives set aside at a read's.

**Context.**
- The sync's "N videos ingested so far" went out with no check before it, and the other per-channel and per-phase publishes followed an `_is_stopped` read, after which a stop could land. The open page applies an event's status, so it flipped back from Cancelled until the next refetch.
- `POST /jobs/{id}/cancel` read the row, revoked the task, then wrote `cancelled` unconditionally. A run that completed or failed between the read and the write became a cancelled one: the report left the page and the failure's words were overwritten.
- `celery_app.py` sets `task_acks_late=True` and leaves `task_reject_on_worker_lost` unset. A worker that dies after the run's last write and before the ack leaves the message unacked, and the Redis transport hands it out again; on the solo pool that covers a kill, a restart or a machine restart. The redelivered task ran the whole run again, and a first phase redelivered after approval searched again and wrote `searching` over the user's review or over the running resume.
- Nothing starts a job task on a completed row on purpose: `POST /jobs`, Sync now and subscribe create a new row, approve starts the resume from `awaiting_approval`, the scheduler queues no job task, nothing calls `self.retry`, and `scripts/regenerate_report.py` dispatches none. The approve route stores the resume's task id itself, before the resume runs.

**Decision.**
1. **A progress line not tied to a status write goes through `_report_progress`:** written first, in the run's conditional write, and published only once written. A refused write raises `_RunStopped`, so the run stops there too. The write is the check: where an `_is_stopped` read stood, a gate costs a conditional UPDATE, its COMMIT and a refresh SELECT (plus a SELECT when a commit since the last write expired the job), once per channel or phase. The row holds each line, cut to 500 characters, so a reload shows what the socket said.
2. **A cancel writes `cancelled` only while the row has not ended** (`update_job_status(..., unless_ended=True)`, one conditional UPDATE). A cancel that loses the race answers what a cancel a moment later would: 400 with what the run ended as ("This run has already completed, so there is nothing to cancel."), the words the route's first check gives too. The end stays and nothing is revoked.
3. **The revoke comes after the write,** with the task id the row holds then, and only when the row says cancelled. A revoke the broker refuses is logged by exception type alone and the route still answers 200, since the row is what stops a run. `useCancelJob` refetches the run and the list when a cancel fails.
4. **`completed` is a stopped status for job tasks,** beside `failed` and `cancelled`, at the start guard, the in-run writes, the per-item checks and the failure handler. The topic and channel first phases also leave alone a row at `awaiting_approval` or past it, and their orphan backstop fails only `pending` and `searching`. A redelivery is told apart by status, not by task id.
5. **A second delivery whose `completed` write is refused keeps the report file the row points at,** since every delivery of a job writes `report_<job_id>.html`.

**Alternatives considered.**
- *An `_is_stopped` read before each publish.* A stop that lands between the read and the publish still goes out. D-161 set the gate aside at a read per publish; this one costs a short write transaction and closes the window up to the commit.
- *Telling a redelivery apart by task id.* The approve route writes the resume's task id itself, so the id cannot tell a first delivery from a second.
- *Revoking first, as before.* Terminating a run that is closing could lose the usage its scope writes on the way out, and a revoke cannot stop a solo-pool task anyway.
- *Setting a longer `visibility_timeout` here.* It is a deployment setting, so it is the owner's call (T-5.2.29).

**Consequences.**
- One gap remains, between a write's commit and its publish: a cancel that commits inside it can be followed by one event, which the page's 5-second refetch corrects. Closing it needs the page to drop events for a run it holds as ended (T-5.2.28).
- With late acks and Redis's default one-hour visibility timeout, a run that has not acked within the hour can be handed to a second worker process while the first still runs. The writes here keep a completed row completed and keep its report, but the second copy still spends. The owner's single solo worker cannot take the message while it runs the first copy; a prefork pool with several processes can (T-5.2.29, the owner's call).
- The cancel route publishes no status change on the socket, so another open tab learns of a cancel at its next refetch (T-5.2.30).
- A redelivery after a worker died mid-run still runs again from the start, as before.
- No migration and no new setting. Owner step: restart the API and the worker.

**Linked initiatives / PRs.** E-5.2 (T-5.2.21 to T-5.2.23, T-5.2.28 to T-5.2.30); PR [#449](https://github.com/khoks/VideoResearchPro/pull/449); [D-158](#d-158--a-job-task-returns-at-once-on-a-failed-row-a-job-dates-an-undated-row-and-its-stored-chunks-whisper-text-without-segments-is-a-transcription-and-a-manual-dispatchs-503-promises-nothing-2026-11-09), [D-161](#d-161--a-job-tasks-status-writes-are-one-conditional-update-the-first-stops-words-win-a-progress-callback-may-end-the-search-and-embedded_in_chroma-follows-the-chunks-2026-11-09).

**Status-changed 2026-11-10:** two consequences are closed. A cancel that takes is announced on the run's channel after its commit and before its revoke, so every open tab shows it at once, and a page takes no more events for a run it holds as ended, so a progress line published after a cancel's commit no longer flips it back ([D-169](#d-169--a-cancel-that-takes-is-announced-after-its-commit-a-page-takes-no-more-events-for-a-run-it-holds-as-ended-the-runs-videos-follow-its-cached-status-and-every-cached-jobs-list-takes-a-runs-events-2026-11-10), T-5.2.28, T-5.2.30, PR [#453](https://github.com/khoks/VideoResearchPro/pull/453)). Point 2's lost race announces nothing. T-5.2.29 is unchanged.

## D-164 — The API's warnings and errors carry no user's words: an operator by place and mask, Echo's model failures by type and status, a chosen file name by its extension and length, and a failure logged by its frames is never re-raised bare (2026-11-09)

**Status:** accepted (2026-11-09). Made while building T-4.11.4.4 (PR [#447](https://github.com/khoks/VideoResearchPro/pull/447)) and its review fixes, not ruled by the owner. It carries [D-160](#d-160--a-users-words-leave-the-workers-log-at-the-call-site-an-exception-that-can-quote-a-request-is-logged-by-its-frames-and-a-connectors-search-counts-as-a-shared-link-2026-11-09) from the worker's lines to the API's warnings, errors and exceptions. The PR proposed it as an addendum to D-160 or a new entry; it is recorded as a new entry. Hiding a database error's bound values stays the owner's call (OQ-45, [S-4.11.4](initiatives.md#s-4114--the-apis-own-log-lines)).

**Context.**
- #437 made the API's own lines reach its log ([D-157](#d-157--the-apps-log-lines-get-a-handler-that-steps-aside-while-the-root-logger-has-one-an-in-process-migration-restores-the-root-logger-and-a-log-line-names-no-email-recipient-subject-or-connector-account-2026-11-09)), and #442 took a user's words out of the worker's. The API still wrote an uploaded export's file name, which is named after the person the export is with, the operator addresses in `ADMIN_EMAILS` at startup, and exception text that can quote an incoming message, a draft, a share's words, a password's hash or an address.
- Echo's fail-soft lines around a model call quoted the exception. A critique score the model wrote as words goes through `float()`, whose `ValueError` quotes them, often the draft's.
- `run_import` logged its failure and re-raised it bare, so it also reached uvicorn's "Exception in ASGI application" line whole, where a database error quotes the batch's rows. The preview step ran outside every handler, and a preview reads the whole file, so a cell it cannot read raised a `ValueError` quoting it.
- A mask alone often cannot tell two addresses apart: `bob@example.com` and `bill@example.com` both read `b***@e***.com`.

**Decision.**
1. **An `ADMIN_EMAILS` entry is named by its place in the list as written and a masked form** (`entry 2 of 3 (b***@e***.com)`), never the whole address. A repeated address keeps its place and is named by its first, and a blank slot takes none.
2. **Echo's fail-soft lines over a model call whose prompt is the user's own words or an incoming message name the error by `exception_kind`,** its type and any HTTP status (`RateLimitError (HTTP 429)`). Elsewhere a provider's error text stands, as #442 kept `social_classify`'s: [D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09)'s record factory takes keys out, and the hosted providers' messages describe the fault, not the prompt.
3. **A file name a user chose is named by `loggable_filename`,** its extension and length.
4. **An exception whose text can quote stored values goes to `logger.error` with `traceback_without_text`,** as D-160 point 2 says, at each API call site that used `logger.exception` around a credential, a database write or a share's words; the PR lists each. A model's own text inside an answer, and a non-JSON knowledge reply, are logged by their length.
5. **A service that logs its own failure by its frames does not re-raise it bare into uvicorn.** `run_import` raises `ImportStopped` with the row's words, and `POST /echo/import` answers 500 with them. A failed preview raises `ImportStopped("Preview stopped: <type>")`, which `POST /echo/import/preview` and `POST /echo/import` answer as a 500, the latter before any row is written. `ExportUnreadable` keeps its 422.

**Alternatives considered.**
- *An addendum to D-160.* The API's rules add a mask, two helpers and a route's answer, more than a status note carries.
- *A filter on `uvicorn.error` that writes every unhandled traceback by its frames.* It would close the last way a database error's values reach the API's log, but drop every unhandled error's words, useful ones included. With OQ-45's `hide_parameters` it is the owner's choice (T-4.11.4.6).
- *Counting an operator's place after blanks and duplicates are dropped.* With a repeated address the place pointed at the wrong written entry (the review's finding).

**Consequences.**
- 265 warning, error and exception calls in 83 files of API-run code were read and 21 changed; the PR names every kept line and why.
- An exception no route handles still reaches uvicorn's own line whole, and a database error there quotes its values, `run_import`'s own insert and commit among them, which sit outside its `try` (T-4.11.4.6, with OQ-45).
- uvicorn's access log writes the query string, so `GET /search?q=`, `GET /echo/shares?q=` and `GET /author/knowledge-sources?q=` put a user's search words in `.uvicorn.out.log` (T-4.11.4.5).
- Worker-only lines in `newsletter_service` and `saved_search_service` still use `logger.exception` around writes that carry a saved search's question or an issue's subject (T-4.11.4.7).
- CLAUDE.md's `ADMIN_EMAILS` row, `.env.example` and `docs/api-reference.md` say so. No migration and no new setting. Owner step: restart the API and the worker.

**Linked initiatives / PRs.** E-4.11 ([S-4.11.4](initiatives.md#s-4114--the-apis-own-log-lines): T-4.11.4.4 to T-4.11.4.7, OQ-45); PR [#447](https://github.com/khoks/VideoResearchPro/pull/447); [D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09), [D-157](#d-157--the-apps-log-lines-get-a-handler-that-steps-aside-while-the-root-logger-has-one-an-in-process-migration-restores-the-root-logger-and-a-log-line-names-no-email-recipient-subject-or-connector-account-2026-11-09), [D-160](#d-160--a-users-words-leave-the-workers-log-at-the-call-site-an-exception-that-can-quote-a-request-is-logged-by-its-frames-and-a-connectors-search-counts-as-a-shared-link-2026-11-09).

**Status-changed 2026-11-10:** three consequences are closed. uvicorn's access log writes a search's words by their length, the worker-only lines in `newsletter_service` and `saved_search_service` log by their frames, and `run_import`'s own insert and commit fail as `ImportStopped("Import could not start: <type>")`, answered as a 500 with no row written ([D-168](#d-168--the-access-log-writes-a-users-words-by-their-length-chosen-by-parameter-name-in-one-filter-a-fail-soft-handler-rolls-back-before-it-reads-and-an-imports-own-row-fails-as-importstopped-2026-11-10), T-4.11.4.5, T-4.11.4.7 and T-4.11.4.6's `run_import` part, PR [#454](https://github.com/khoks/VideoResearchPro/pull/454)). Any other exception no route handles still reaches uvicorn's own line whole (T-4.11.4.6's general part, with OQ-45).

## D-165 — A form's own words travel in a typed error, a surface waits only for its own save, a control that would replace a line is part of its surface, and a line's request waits for whatever would take the line away (2026-11-10)

**Status:** accepted (2026-11-10). Made while building T-3.4.1.24 and T-3.4.1.25 (PR [#446](https://github.com/khoks/VideoResearchPro/pull/446)) and its review fixes, not ruled by the owner. It applies [D-156](#d-156--a-failure-said-on-the-page-stands-alone-a-dialog-waits-for-its-answer-the-drop-zone-names-each-file-that-lands-and-a-disconnect-goes-through-mutate-2026-11-09) and [D-159](#d-159--a-lines-own-surface-waits-for-its-answer-and-the-apps-navigation-does-not-each-action-gets-its-own-line-a-started-run-is-never-offered-twice-and-the-guard-follows-a-line-through-props-and-iserror-2026-11-09) to the seven files D-159's guard found, and says how far a line's surface reaches. What is said when a page is left mid-request stays the owner's ruling (T-3.4.1.21).

**Context.**
- Seven files said one failure twice, an `isError` line beside the global toast: `DraftEditor` (on the Echo page and in the bubble), `VideoFramesPanel`, `PasteUrlsForm`, `NotesPanel`, `NotesPage`, `PinQuestionButton` and `SavedSearchesPage`.
- The submit form's "Save as template" re-checks the form when the dialog saves and threw its validation message as a plain `Error`. `inlineErrorMessage` never shows a plain `Error`'s text, so the dialog said "Could not save the template."
- `DraftEditor` serves two surfaces through one hook, so one surface's save could hold the other's controls. Controls beside a line could also replace it without closing anything: another note's Edit, another draft's Open, the bubble's Clear, "See them on the shelf".
- Found in review: a new draft, or a delete of the open draft, already in flight could take the draft view away while a save was going, and a failed save was then said nowhere. A delete's `onSuccess` cleared whichever draft had been open when Delete was pressed.
- The frames panel said "this month's frame captures" for any 429, the rate limiter's included.

**Decision.**
1. **Words the app wrote for the reader travel in a typed `FormValidationError`** (`utils/apiError.ts`), and `inlineErrorMessage` shows those and the server's words, never any other exception's text. An unknown `Error`, a `TypeError` or a thrown string still gets the page's sentence, and a 401 nothing.
2. **A surface waits only for a save made on it.** `useDraftFeedback` takes its surface (`page` or `bubble`) and keys its mutation by it. In the bubble the openers and the Mod-Shift-E shortcut wait as well as ×, Escape and Clear, since they are the panel's own buttons, as D-159 counts a popover's button.
3. **A control that would put something else in a line's place is part of the line's surface** and waits: another note's Edit, Add a note and the inline panel's fold, another draft's Open and Delete, the bubble's Clear, "See them on the shelf", and on a saved search's card the other changes and Delete. Filters that only hide a line whose state lives in the page stay free (the notes page's search, type chips and "Show withdrawn"), and so does the app's navigation, the library page's tabs included.
4. **A line's own request waits while a request that would take the line away is out,** the reverse of point 3: a draft's "Save my version" waits while a new draft, or a delete of that draft, is in flight, and a delete's `onSuccess` checks the draft open when it lands.
5. **Each action on a saved search's card has its own line** (change, run now, delete), as D-159 point 3 asks, **and the frames panel's monthly sentence follows the quota's own refusal** (`detail.error == 'quota_exceeded'`), not the status, so the rate limiter's 429 shows its own words.

**Alternatives considered.**
- *Showing a plain `Error`'s message.* It would put a library's or the runtime's text, which can quote anything, on the page.
- *One hold for both draft surfaces.* A save in the bubble would freeze the Echo page's card, and the reverse, for a line the other surface does not show.
- *Holding the notes page's filters.* The edit's state lives in the page, so a filter hides the editor and its line without losing them, and clearing it brings both back.
- *Standing a query's failure line aside in the same change.* Queries go through the `QueryCache`, which has no `meta` to stand aside, and the guard reads mutations only (T-3.4.1.26).

**Consequences.**
- The guard's `NOT_YET` list names only `QuickShare.tsx`, which waits on T-3.4.1.21, and the guard found no other file.
- A failed note edit's line no longer shows in the next note's editor; a new editor starts clean.
- A line left through the app's navigation says nothing: the library page's tabs left mid-paste, and the Echo panel's auto-close on phones when a link inside it is followed. T-3.4.1.21's ruling covers both.
- A query's failure line still sits beside the global query toast, as on `NotesPage`, `SavedSearchesPage` and `SpeakAsMePanel`'s status line (T-3.4.1.26).
- CLAUDE.md's "One toast per failure" bullet says which controls wait, that the app's navigation does not and that `FormValidationError` exists, and drops a stale clause that the welcome page's Skip waits. Frontend only: no setting, migration, route or device baseline changed, and no owner step.

**Linked initiatives / PRs.** E-3.4 (T-3.4.1.21, T-3.4.1.24 to T-3.4.1.26); PR [#446](https://github.com/khoks/VideoResearchPro/pull/446); [D-153](#d-153--a-hook-that-answers-its-own-failures-says-them-through-one-helper-a-hook-whose-callers-differ-takes-an-option-and-a-guard-test-holds-the-rule-2026-11-09), [D-156](#d-156--a-failure-said-on-the-page-stands-alone-a-dialog-waits-for-its-answer-the-drop-zone-names-each-file-that-lands-and-a-disconnect-goes-through-mutate-2026-11-09), [D-159](#d-159--a-lines-own-surface-waits-for-its-answer-and-the-apps-navigation-does-not-each-action-gets-its-own-line-a-started-run-is-never-offered-twice-and-the-guard-follows-a-line-through-props-and-iserror-2026-11-09).

**Status-changed 2026-11-10:** the consequence about query lines is closed. A page that says a failed load on its own line no longer also gets the global toast: the `QueryCache` stands aside for each mounted reader that says the failure, and the guard reads queries too ([D-167](#d-167--a-querys-toast-stands-aside-per-mounted-reader-a-reader-may-say-every-failure-or-only-a-first-load-and-the-guard-holds-each-condition-to-a-page-test-2026-11-10), T-3.4.1.26, PR [#452](https://github.com/khoks/VideoResearchPro/pull/452)). T-3.4.1.21 is unchanged.

## D-166 — The embedded-flag check refuses while another collection holds chunks of this library, told apart by name and by shape, and its advice follows the collection's kind (2026-11-10)

**Status:** accepted (2026-11-10). Made while building T-5.2.26 (PR [#451](https://github.com/khoks/VideoResearchPro/pull/451)) and its review fixes, not ruled by the owner. The PR proposed it as an addition to [D-162](#d-162--a-document-counts-as-embedded-when-any-chunk-names-it-every-doubt-keeps-the-flag-a-document-with-no-words-keeps-it-and-the-check-embeds-nothing-2026-11-09); it is recorded as a new entry, with a status note there. It carries D-162 point 3's "every doubt keeps the flag" across the store's collections.

**Context.**
- D-162's guards looked at the configured collection alone. After a lost `CHROMA_GLOBAL_COLLECTION_NAME` pin and a partial re-embed, `pratidhvani_global` holds a few chunks of this database, so the mismatch guard and the empty-store guard both pass, while most of the library sits in `videoresearchpro_global`. Every document whose chunks are only there looks chunkless, and `--write` would clear flags that are right.
- The store also holds collections that are not chunk collections: Q&A (`qa_library_global`), notes, and Echo's shares and personal context. Some of their rows name a document (a note's target, a share added to the library), and Echo's hold a tenant's private rows.
- A pre-global install may still hold per-job `job_<id>` collections, which `migrate_legacy_per_job_collections` merges. Collection-level `scope` metadata is absent on those and on any collection made outside the app.
- A migration that crashed part-way leaves every document with some chunks in both collections.

**Decision.**
1. **The check refuses, its dry run included, while any other collection in the store holds chunks of this database's documents.** The dry run exits 1 and `--write` writes nothing, with or without `--empty-store-ok` or `--document-ids`, and whether or not the documents a write would clear are named there. A collection that cannot be listed, opened or fully scanned is a doubt and stops the check too.
2. **Collections are told apart by name and by shape, together.** The Q&A, notes and Echo collections (`echo_vectors.echo_collection_names()`), under their configured names, are never opened. In every other collection a row counts only when its id is `{video_id}:{n}` or `{document_id}:{n}` naming a document here, or its metadata names one (by `document_id`, `(source_type, source_id)` or `video_id`) and carries an integer `chunk_index`. A renamed setting's old Q&A or notes collection therefore does not block, and a legacy chunk collection under any name does.
3. **Every other collection is read for metadata only,** through `list_collections()` and `get_collection(name, embedding_function=None)`: nothing is created and no model is loaded.
4. **The stop's advice follows the collection's kind, and all three refuse.** A `job_<id>` collection is merged with `chroma_service.migrate_legacy_per_job_collections()` and never pinned, since every question would then see that one job. A collection holding no document and no chunk id of this database that the configured collection lacks (`documents_only_here` and `chunks_only_here` both 0) is a leftover copy, to delete once Q&A answers from the configured collection. Anything else is re-pinned or migrated (`docs/migration-code-identifiers.md`, section A).
5. **The report names every collection seen,** and for each one read gives rows scanned, chunks of this database, documents named, `documents_only_here`, `chunks_only_here` and how many a write would have cleared.

**Alternatives considered.**
- *Shape alone.* It reads Echo's private rows, and breaks the day one of those collections splits long rows into `chunk_index`ed pieces.
- *Collection `scope` metadata.* Old and outside collections do not carry it, and the row shape is what decides whether a document would look chunkless.
- *Refusing only when a document a write would clear is named elsewhere.* More precise, but it trusts the shape test on a collection the app does not own; the counts are reported, so the owner sees the overlap anyway.
- *An override flag, such as `--other-collection-ok NAME`.* Deleting the migrated collection is the runbook's way out, and a backup of `data/chroma/` its recovery path.
- *Calling a copy a leftover on `documents_only_here == 0` alone.* A migration that crashed part-way would read as one, and the advice would delete chunks only that copy holds (the review's finding).
- *Reading other stores, under another `CHROMA_PERSIST_DIR`.* The check sees one store, and a wrong persist dir is still caught by the mismatch and empty-store guards.

**Consequences.**
- The live store's read-only runs saw `pratidhvani_global` (8,567 chunks, none of a document missing from this database) and `qa_library_global` (another kind, not read), and no legacy, per-job, notes, shares or personal-context collection: 254 documents flagged, all videos with chunks, 0 to clear.
- An owner who keeps a migrated legacy collection in the same store as a backup can never run `--write` (T-5.2.31, the owner's call).
- The prefix of a pre-global per-job collection lives in one place, `chroma_service.LEGACY_PER_JOB_PREFIX` and `is_legacy_per_job_collection`, which the migrator uses too. The runbook's Rollback says the check refuses while the unused copy exists, and a new paragraph gives the per-job merge command, with a backup first.
- No migration, no new setting, nothing to restart and no owner step.

**Linked initiatives / PRs.** E-5.2 (T-5.2.26, T-5.2.31); PR [#451](https://github.com/khoks/VideoResearchPro/pull/451); [D-032](#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03), [D-162](#d-162--a-document-counts-as-embedded-when-any-chunk-names-it-every-doubt-keeps-the-flag-a-document-with-no-words-keeps-it-and-the-check-embeds-nothing-2026-11-09).

## D-167 — A query's toast stands aside per mounted reader, a reader may say every failure or only a first load, and the guard holds each condition to a page test (2026-11-10)

**Status:** accepted (2026-11-10). Made while building T-3.4.1.26 (PR [#452](https://github.com/khoks/VideoResearchPro/pull/452)) and its review fixes, not ruled by the owner. It carries [D-148](#d-148--a-401-ends-a-session-in-react-and-keeps-the-page-in-this-tab-a-waiting-share-gets-a-link-a-mutation-that-answers-its-own-failures-says-so-and-tabs-opens-on-focus-2026-11-05) point 5 and [D-153](#d-153--a-hook-that-answers-its-own-failures-says-them-through-one-helper-a-hook-whose-callers-differ-takes-an-option-and-a-guard-test-holds-the-rule-2026-11-09)'s `meta` from mutations to queries, which closes [D-165](#d-165--a-forms-own-words-travel-in-a-typed-error-a-surface-waits-only-for-its-own-save-a-control-that-would-replace-a-line-is-part-of-its-surface-and-a-lines-request-waits-for-whatever-would-take-the-line-away-2026-11-10)'s consequence about query lines. What is said when a page is left mid-request stays the owner's ruling (T-3.4.1.21).

**Context.**
- The query client's `QueryCache` toasted every failed query and had no way to stand aside, so a page that showed a query's own failure line said that failure twice. The guard read mutations only.
- `query.meta` belongs to the query, so it is whichever reader rendered last. One key is often read by a page with a line and by a silent component: the shelves page and the sidebar, the run page and the channel page.
- Some pages show their line only in place of a first load and keep their data on screen when a refresh fails: the graph, the report peek, Echo's data card and readiness, the run page and the knowledge drawer.
- Some readers show a line only under a condition: the library's visible tab, the two-step card's setup step, the models page's cost panel, a book's framing in the studio, the palette with no matching action.

**Decision.**
1. **The toast stands aside per mounted, enabled reader.** `queryFailureShownOnPage(query)` reads `query.observers` when the failure lands, not `query.meta`, and a disabled reader does not count. Where only a silent reader is mounted the toast speaks, and a reader that has gone says nothing, so a page left mid-load leaves the failure to the toast.
2. **Two metas.** `ERRORS_SHOWN_HERE` means the reader shows every failure, a failed refresh included. `LOAD_ERRORS_SHOWN_HERE` means it shows a line only in place of a first load, so a failed refresh behind data still on screen keeps its toast.
3. **A query hook whose readers differ takes `{ inlineErrors }`** (`boolean | 'load'`, turned into a meta by `queryErrorsMeta()`), as the ask hooks do for mutations. A caller may work it out from what is on screen.
4. **A line under an open dialog counts as said,** by D-159's surface rule; modal awareness was not attempted.
5. **The guard checks queries per reader.** A reader that builds a line from a query's failure (`isError`, `error` or `status === 'error'`, or the query handed to a section's prop) must stand aside, and one that stands aside must show a line; hiding the component, navigating away or a call that keeps no result is not a line. A reader that stands aside only under a condition must be listed in `CONDITIONAL_READERS` beside a page test that checks the condition both ways, and the guard fails on an unlisted file or a missing test.
6. **Retries are unchanged.** A failure is said, or stood aside from, once its retries have failed too.

**Alternatives considered.**
- *Reading `query.meta`.* Render order would decide whether the toast speaks, and a page left mid-load would stand aside with nothing on screen.
- *One meta for any failure.* On a page that keeps its data, a refresh failing behind it would be said nowhere.
- *Setting the meta in a shared hook for every caller.* The sidebar, the `/` gate and the Echo panel read silently and would lose the only word.
- *Leaving the conditions to a comment that page tests check them.* Only one condition had such a test (the review's finding).
- *Silencing the health poll, which shows no line.* The failure would then be said nowhere (T-3.4.1.27).

**Consequences.**
- About 40 query readers in about 45 files say a failed load once, with the server's words through `inlineErrorMessage` and nothing on a 401. The run page says "Couldn't load this run." for a failure that is not a 404, and the knowledge and report readers no longer show axios's text.
- On the runs list and the system page a failed poll is no longer toasted every interval, and a run page that 404s no longer toasts every 5 seconds. A run-page poll failing behind a run on screen still toasts every 5 seconds, and a failing health poll every 60 (T-3.4.1.27).
- A 403 on a refresh while Echo's readiness is on screen shows the upgrade card and the toast both; it takes a plan change while the page is open.
- The guard's `QUERY_NOT_YET` list is empty, and `NOT_YET` still names only `QuickShare.tsx` (T-3.4.1.21).
- CLAUDE.md's "One toast per failure" bullet says queries follow the rule. Frontend only: no setting, migration, route or device baseline changed, and no owner step.

**Linked initiatives / PRs.** E-3.4 (T-3.4.1.26, T-3.4.1.27); PR [#452](https://github.com/khoks/VideoResearchPro/pull/452); [D-148](#d-148--a-401-ends-a-session-in-react-and-keeps-the-page-in-this-tab-a-waiting-share-gets-a-link-a-mutation-that-answers-its-own-failures-says-so-and-tabs-opens-on-focus-2026-11-05), [D-153](#d-153--a-hook-that-answers-its-own-failures-says-them-through-one-helper-a-hook-whose-callers-differ-takes-an-option-and-a-guard-test-holds-the-rule-2026-11-09), [D-159](#d-159--a-lines-own-surface-waits-for-its-answer-and-the-apps-navigation-does-not-each-action-gets-its-own-line-a-started-run-is-never-offered-twice-and-the-guard-follows-a-line-through-props-and-iserror-2026-11-09), [D-165](#d-165--a-forms-own-words-travel-in-a-typed-error-a-surface-waits-only-for-its-own-save-a-control-that-would-replace-a-line-is-part-of-its-surface-and-a-lines-request-waits-for-whatever-would-take-the-line-away-2026-11-10).

**Status-changed 2026-11-10:** two consequences are closed ([D-170](#d-170--a-poll-says-a-run-of-failures-once-the-streak-is-the-caches-own-record-a-page-may-take-a-failure-no-reader-says-and-the-guard-lists-every-poll-2026-11-10), T-3.4.1.27, PR [#458](https://github.com/khoks/VideoResearchPro/pull/458)). A poll that no line shows says a run of failures once, so the health poll and a run-page poll behind a run on screen no longer toast every interval, and with the Echo page open a change of plan shows the upgrade card and no toast. Point 1 stands, and a page may now also take a failure no mounted reader says while it is open (`sayFailuresOnPage`).

## D-168 — The access log writes a user's words by their length, chosen by parameter name in one filter, a fail-soft handler rolls back before it reads, and an import's own row fails as `ImportStopped` (2026-11-10)

**Status:** accepted (2026-11-10). Made while building T-4.11.4.5, T-4.11.4.7 and T-4.11.4.6's `run_import` part (PR [#454](https://github.com/khoks/VideoResearchPro/pull/454)), not ruled by the owner. It carries [D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09)'s filter on `uvicorn.access` from credentials to words, takes [D-160](#d-160--a-users-words-leave-the-workers-log-at-the-call-site-an-exception-that-can-quote-a-request-is-logged-by-its-frames-and-a-connectors-search-counts-as-a-shared-link-2026-11-09) point 2 to the worker sites #442 missed, and applies [D-164](#d-164--the-apis-warnings-and-errors-carry-no-users-words-an-operator-by-place-and-mask-echos-model-failures-by-type-and-status-a-chosen-file-name-by-its-extension-and-length-and-a-failure-logged-by-its-frames-is-never-re-raised-bare-2026-11-09) point 5 to `run_import`'s own row. T-4.11.4.6's general part, a filter on `uvicorn.error` or `hide_parameters`, stays the owner's (OQ-45, [S-4.11.4](initiatives.md#s-4114--the-apis-own-log-lines)).

**Context.**
- uvicorn's access log is on at INFO under both launchers and writes each request's path and raw query string to `.uvicorn.out.log`, so what users typed into four search boxes, two library filters and the map was written as typed.
- On the library map a topic node's id is `topic:<label>`, the topic's label.
- Four worker `logger.exception` calls wrapped database writes that carry a saved search's question, an issue's title or `ECHO_IMAP_TENANT_EMAIL`, and a database error ("database is locked" is enough) quotes its statement's values in the traceback. #442 judged those lines by their arguments and missed their tracebacks.
- A failed flush rolls the session back and expires every loaded object. Both notification handlers read their row's id before rolling back, so the handler itself raised `PendingRollbackError`: the newsletter's `deliver` raised out of the task after the email had gone, and a saved search's run already committed as a success was recorded as failed.
- `run_import`'s own `EchoImport` insert and commit sat outside every handler, so a failure there reached uvicorn's "Exception in ASGI application" line quoting the file's name and `options_json`, whose `self_name` is a participant's name.

**Decision.**
1. **uvicorn's access log writes a user's words by their length, chosen by parameter name in the one filter on `uvicorn.access`** (`log_redaction.WORDS_QUERY_NAMES`: `q`, `search` and `focus`, written as `q=[41 characters]`). `focus` counts as words because a topic node's id is the topic's label. The path, the other parameters and the status stay.
2. **A value is counted as the route reads it:** percent-decoded with `+` as a space, running to the next `&`, each repeat by its own length. A name matches percent-encoded and in any case, also after a `;` or inside another value, so a crafted URL hides more, never less.
3. **Every other query parameter is kept on its route with a reason,** in a guard test that reads every route's parameters from FastAPI's dependants and fails on one in neither list, so each new parameter is a choice.
4. **A fail-soft handler around a database write rolls back before it reads any row,** and logs an id read before the write.
5. **The worker's last `logger.exception` lines around such writes go to `logger.error` with `traceback_without_text`:** the newsletter's and the saved search's notification writes, the saved-search run's handler, whose words stay on `last_error` where the user reads them, and the scheduler tick's inbox sync.
6. **`run_import`'s own row follows D-164 point 5.** A failure writing it is logged by `loggable_filename` and its frames and raised as `ImportStopped("Import could not start: <type>")`; `POST /echo/import` answers 500 with those words, and nothing is written.

**Alternatives considered.**
- *Redacting the whole query string.* It loses the ids and enums an operator reads.
- *A per-route rule in the filter.* A second place to keep in step with the routes.
- *A filter on `uvicorn.error` that writes every unhandled traceback by its frames, or `hide_parameters`.* Out of scope by the brief; both stay the owner's (OQ-45).

**Consequences.**
- All 93 query parameters on 38 paths were read: `q` on four routes, `search` on two and `focus` on one are written by length, and the other 86 are kept with reasons. The real `app.main:app` under the real uvicorn CLI wrote none of the words.
- A user's words in a path segment still reach the access log: `DELETE /echo/context/{kind}/{key}` carries a fact's key (T-4.11.4.8).
- `newsletter_service.deliver`'s other writes are not caught, so a database error there reaches Celery's own failure line with its values (OQ-45). `scripts/echo_import.py` prints `ImportStopped`'s traceback to the operator's own terminal (T-4.11.4.9).
- A PR that adds a query parameter must list it in `WORDS_QUERY_NAMES` or the guard's kept list.
- No migration and no new setting. Owner step: restart the API and the worker; `.uvicorn.out.log` holds the words written before until then.

**Linked initiatives / PRs.** E-4.11 ([S-4.11.4](initiatives.md#s-4114--the-apis-own-log-lines): T-4.11.4.5 to T-4.11.4.9, OQ-45); PR [#454](https://github.com/khoks/VideoResearchPro/pull/454); [D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09), [D-160](#d-160--a-users-words-leave-the-workers-log-at-the-call-site-an-exception-that-can-quote-a-request-is-logged-by-its-frames-and-a-connectors-search-counts-as-a-shared-link-2026-11-09), [D-164](#d-164--the-apis-warnings-and-errors-carry-no-users-words-an-operator-by-place-and-mask-echos-model-failures-by-type-and-status-a-chosen-file-name-by-its-extension-and-length-and-a-failure-logged-by-its-frames-is-never-re-raised-bare-2026-11-09).

**Status-changed 2026-11-10:** two consequences are closed ([D-171](#d-171--a-users-words-in-a-url-path-are-chosen-by-route-template-in-the-same-filter-a-path-no-template-matches-is-written-whole-and-the-import-script-answers-a-stop-on-one-line-and-names-what-a-part-way-stop-kept-2026-11-10), T-4.11.4.8, T-4.11.4.9, PR [#459](https://github.com/khoks/VideoResearchPro/pull/459)). The same filter writes a fact's key in `DELETE /echo/context/{kind}/{key}`'s path by its length, chosen by route template, and `scripts/echo_import.py` answers `ImportStopped` in the route's words on one line. `newsletter_service.deliver`'s other writes stay with OQ-45.

## D-169 — A cancel that takes is announced after its commit, a page takes no more events for a run it holds as ended, the run's videos follow its cached status, and every cached jobs list takes a run's events (2026-11-10)

**Status:** accepted (2026-11-10). Made while building T-5.2.28 and T-5.2.30 (PR [#453](https://github.com/khoks/VideoResearchPro/pull/453)) and its review fixes, not ruled by the owner. It closes two consequences [D-163](#d-163--a-progress-line-is-written-before-it-is-published-a-cancel-that-loses-the-race-answers-with-the-runs-end-and-revokes-nothing-and-completed-is-a-stopped-status-2026-11-09) left: another tab learned of a cancel only at its next refetch, and a progress line committed just before a cancel could flip the page back from Cancelled.

**Context.**
- `POST /jobs/{id}/cancel` wrote `cancelled` and revoked the task but published nothing. A run's own transitions publish a `job_status_change` on `job_progress:{job_id}`, which `useJobProgress` applies, so another open tab saw a cancel only at its 5-second refetch.
- A worker commits a progress write and then publishes it (D-163 point 1). A cancel that commits in between is followed by one progress event, which flipped the page back from Cancelled until the next refetch.
- An ended status reaches the frontend's cache only on the server's word: the `useJob` and `useJobs` fetches, `useCancelJob`'s and `useApproveJob`'s `onSuccess`, which store the server's answer, and socket events. Every socket event that names an end goes out after the write that ends the row, and only when that write took. No `job_progress` stage is an ended status, and the zustand store holds no job status.
- The three run-event publishers in `progress_service` catch Redis errors themselves, and logged the error's text.
- Both progress hooks wrote events to `['jobs', undefined]`, a key no list has: `useJobs` keys on `['jobs', status, limit, offset]`, so the jobs page's first page is `['jobs', null, 20, 0]`. The jobs page learned of every change only at its 10-second refetch.
- The `jobVideos` query has no poll of its own. Its end-of-run refetch rode on the status event, so dropping that event would drop the refetch too (the review's finding).

**Decision.**
1. **A cancel that takes is announced** as a `job_status_change` to `cancelled` on `job_progress:{job_id}`, the event a run's own transitions send. It goes out after the conditional write's commit, so no page reads `cancelled` before the row says it, and before the revoke, which can wait on a broker that is down.
2. **A lost race or an already-ended run announces nothing.** A cancel that loses to the run's end (the 400 since D-163) and a cancel of a run that had already ended publish nothing: the end is not the cancel's to announce.
3. **A failed announce never fails the cancel.** `_announce_cancelled` catches anything the publisher raises and logs it by exception type, as a refused revoke is, and the route still answers 200. The three run-event publishers log a refused publish by type too, so the rule holds on the real Redis-down path.
4. **A page drops progress, status and error events for a run it holds as ended** (`completed`, `failed` or `cancelled`), in the run's own query and in each row of each cached jobs list, and a dropped event refetches nothing. A refetch is not an event, so it still sets the cache in both directions. This is safe only while the page never writes an ended status itself (no optimistic cancel) and every event that ends a run goes out after the write that ends it. CLAUDE.md's convention says so.
5. **The run's videos follow its cached status, not its events.** `useJobProgress` watches the `['job', id]` query and refetches `['jobVideos', id]` when the status moves to `awaiting_approval` or to an end, whatever moved it: an event, the poll or this tab's cancel answer. The first status the cache receives is not a move, so a page that opens on an ended run fetches its videos once.
6. **Every cached jobs list takes a run's events.** Neither progress hook ever updated a jobs list, because of the wrong key. Both now fold each event into every cached list with `setQueriesData({ queryKey: ['jobs'] })`, row by row and guarded as in point 4. A status change to `cancelled` refetches the run and the lists, as `completed` and `failed` already did, and `useAllJobsProgress` refetches the lists when an event ends a row, to pick up its report and finish time.

**Alternatives considered.**
- *Announcing before the write.* A page could read `cancelled` for a run that then completed, and a cancel that lost the race would still publish.
- *Telling a second, racing cancel apart so it does not publish again.* It needs `update_job_status` to return its row count, which changes its contract for every caller. The duplicate is true, and a tab that holds the run as cancelled drops it (T-5.2.32).
- *Comparing the fetched row's `updated_at` with the event's,* so a refetch in flight when a cancel commits cannot show the run active again. A bigger change, and the next refetch corrects it (T-5.2.33).
- *Special-casing the end-of-run event so a dropped one still refetches the videos.* Following the cached status also covers an event the socket lost, and the approval list.
- *Writing each list by its exact key.* `useJobs` keys every filter and page apart, so no one key reaches them all.

**Consequences.**
- Every tab open on a run shows a cancel at once, and the jobs page shows it without waiting for its refetch.
- A progress line published after a cancel's commit no longer flips the page back from Cancelled.
- A refetch already in flight when a cancel commits can still show the run active for about 5 seconds (T-5.2.33), and a second cancel that raced the first publishes the same event again (T-5.2.32).
- Author outputs keep the same commit-then-publish gap in `useOutputsProgress` (T-5.2.34). A `job_error` event refetches the run's videos but neither the run nor the lists (T-5.2.35).
- Nothing else uses the `['jobs', ...]` prefix: `['jobs', 'create']` and `['jobs', 'approve']` are mutation keys.
- `docs/api-reference.md` gives the three event shapes the server sends (`job_progress`, `job_status_change`, `job_error`), in place of ones it never sent.
- No migration, no new setting and no route change. Owner step: restart the API and reload the frontend.

**Linked initiatives / PRs.** E-5.2 (T-5.2.28, T-5.2.30, T-5.2.32 to T-5.2.35); PR [#453](https://github.com/khoks/VideoResearchPro/pull/453); [D-163](#d-163--a-progress-line-is-written-before-it-is-published-a-cancel-that-loses-the-race-answers-with-the-runs-end-and-revokes-nothing-and-completed-is-a-stopped-status-2026-11-09).

**Status-changed 2026-11-10:** the four consequences this entry left are closed ([D-172](#d-172--only-the-cancel-whose-own-write-took-announces-it-an-author-output-stops-at-the-write-and-keeps-nothing-when-it-ends-unfinished-a-failure-refetches-the-run-and-a-refetch-in-flight-at-an-end-is-cancelled-rather-than-out-ranked-2026-11-10), T-5.2.32 to T-5.2.35, PR [#457](https://github.com/khoks/VideoResearchPro/pull/457)). Only the cancel whose own write took announces it, Author outputs stop at the write, and a `job_error` refetches the run and the lists. Point 4 stands with one addition: a refetch in flight when the run ends is cancelled, by the ending event's refetch or by this tab's cancel or approve answer, rather than ranked by `updated_at`.

## D-170 — A poll says a run of failures once, the streak is the cache's own record, a page may take a failure no reader says, and the guard lists every poll (2026-11-10)

**Status:** accepted (2026-11-10). Made while building T-3.4.1.27 (PR [#458](https://github.com/khoks/VideoResearchPro/pull/458)) and its review fixes, not ruled by the owner. It adds to [D-167](#d-167--a-querys-toast-stands-aside-per-mounted-reader-a-reader-may-say-every-failure-or-only-a-first-load-and-the-guard-holds-each-condition-to-a-page-test-2026-11-10) and closes two of its consequences: a failing poll that no line shows toasted on every interval, and a 403 on a refresh behind Echo's readiness showed the upgrade card and the toast both. What is said when a page is left mid-request stays the owner's ruling (T-3.4.1.21).

**Context.**
- After D-167 a failed query toasted unless a mounted reader stood aside, so a poll whose readers show no line toasted on every interval: `useSystemStatus` in `AppLayout` every 60 seconds, the run page every 5 seconds behind a run already on screen, and the bell, the frames panel, the importer and the voice test while they poll. Silencing those polls would say their failures nowhere.
- The query's own state cannot mark a run of failures. Checked against TanStack Query 5.95.2 in a test: by the time the cache's `onError` runs, the query already reads `error`, holds the new error and has raised `errorUpdateCount`; a fetch with no data clears the error when it starts; and `dataUpdateCount` also moves on `setQueryData`, which `useJobProgress` calls on every socket message.
- Each Echo route's only 403 is the Studio gate, so a plan change while the Echo page is open refuses every Echo read. Each section is its own query, and the upgrade card replaces the sections, so a section's refusal could land with its reader gone and toast; when the account read answered first, the page's own readers were disabled and none stood aside. The review found both, seven toasts on the first commit.

**Decision.**
1. **A poll says a run of failures once.** A poll is a query that a mounted, enabled reader asks for on a `refetchInterval` that resolves to a positive number now (`queryIsPolling`). A streak starts with the first failure the toast says. It ends when a fetch succeeds (the `QueryCache`'s `onSuccess`, which `setQueryData` never calls) or when the poll's last reader unmounts (the cache's `observerRemoved` with no observer left), so a return to a page whose poll still fails says it once more, at most once a visit.
2. **Within a streak each kind of failure is said once.** The kind is the HTTP status, or no answer (`pollFailureKind`), never the message text, so words that carry a count or a time cannot repeat the toast. A 401 still says nothing, and a query that does not poll still toasts every failure.
3. **The streak is the cache's own record** (`PollFailureStreaks`, a `WeakMap` per client), not the query's state, for the reasons above.
4. **A failure a line said is not counted as said,** so when that line goes and a silent reader stays, the toast says the next failure.
5. **A page may take a failure no mounted reader says** while it is open (`sayFailuresOnPage(cache, rule)`, asked after the readers). It must then show that failure, worked out from the failure itself, through the cache's `updated` event, which TanStack sends before `onError`, not from what has rendered; otherwise the order the answers arrive in would decide between the page and the toast. The Echo page takes every 403 on an `['echo', ...]` read for its upgrade card (`useEchoPlanRefusal`), and a status read that succeeds again takes the card away. A 500 still toasts, and a 403 that lands once the page has gone toasts as before.
6. **The guard lists every poll.** `oneToastPerFailure.test.ts` gains a fifth part: every `refetchInterval` in `src`, written out, short, spread or assigned, is listed in `POLLS` beside the tests that check it, and nothing polls by a timer of its own, whether a `setInterval` that asks a query again (inline, named or a member reference) or a `setTimeout` loop. A one-shot debounce is allowed.

**Alternatives considered.**
- *Silencing the health poll, which shows no line.* Its failure would be said nowhere, as D-167 found.
- *Reading the query's own state* (`status`, `errorUpdateCount`, `dataUpdateCount`). TanStack writes the failure before `onError`, and progress writes move the data counters, so a run-page poll failing while progress arrives would toast every interval again.
- *Ending the streak only on a successful fetch,* as the item worded it. A reader coming back to a page whose poll still fails would see stale data and no word.
- *The message text as the kind.* A sentence with a count or a time in it would toast every interval.
- *A per-reader `ShownOnPage(error, hasData)` form of `inlineErrors`* (the first commit). It covered readiness only, not the sections the card replaces or the page's disabled readers.

**Consequences.**
- The health check, `useJob` behind a run on screen, `useJobs` where no line shows, the bell, the frames panel, the importer and the voice test say a run of failures once. `useSavedSearches` and the system page's three polls always stand aside for their own line, so the streak never applies to them.
- A change of plan while the Echo page is open shows the upgrade card and no toast, whatever order the answers arrive in.
- The guard cannot read a timer callback passed through a prop or defined in another module; none exists today. A query that does not poll still says every failure, since a refetch on focus, remount or retry is the reader asking again.
- CLAUDE.md's "One toast per failure" bullet gains a passage on polls. Frontend only: no setting, migration, route or device baseline changed, and no owner step.

**Linked initiatives / PRs.** E-3.4 (T-3.4.1.27); PR [#458](https://github.com/khoks/VideoResearchPro/pull/458); [D-153](#d-153--a-hook-that-answers-its-own-failures-says-them-through-one-helper-a-hook-whose-callers-differ-takes-an-option-and-a-guard-test-holds-the-rule-2026-11-09), [D-167](#d-167--a-querys-toast-stands-aside-per-mounted-reader-a-reader-may-say-every-failure-or-only-a-first-load-and-the-guard-holds-each-condition-to-a-page-test-2026-11-10).

## D-171 — A user's words in a URL path are chosen by route template in the same filter, a path no template matches is written whole, and the import script answers a stop on one line and names what a part-way stop kept (2026-11-10)

**Status:** accepted (2026-11-10). Made while building T-4.11.4.8 and T-4.11.4.9 (PR [#459](https://github.com/khoks/VideoResearchPro/pull/459)) and its review fixes, not ruled by the owner. It carries [D-168](#d-168--the-access-log-writes-a-users-words-by-their-length-chosen-by-parameter-name-in-one-filter-a-fail-soft-handler-rolls-back-before-it-reads-and-an-imports-own-row-fails-as-importstopped-2026-11-10)'s words rule from the query string to the path, in the filter [D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09) put on `uvicorn.access`, and takes [D-164](#d-164--the-apis-warnings-and-errors-carry-no-users-words-an-operator-by-place-and-mask-echos-model-failures-by-type-and-status-a-chosen-file-name-by-its-extension-and-length-and-a-failure-logged-by-its-frames-is-never-re-raised-bare-2026-11-09) point 5's `ImportStopped` to the command line. T-4.11.4.6's general part stays the owner's (OQ-45).

**Context.**
- `DELETE /api/v1/echo/context/{kind}/{key}` carries a fact's key, which the user types, as a path segment, and uvicorn's access log, on at INFO under both launchers, wrote the path whole to `.uvicorn.out.log`. D-168 covered query parameters only.
- Of the 74 path parameters on the app's 69 templated routes, only that `key` holds what a user typed. The rest are ids, a PDF's digest, a session's `jti`, a share token's row id, YouTube ids, or names from a fixed set.
- uvicorn writes `quote(scope["path"])`, the path it routed, decoded and encoded again. Starlette decodes `%2F` before matching, so a key holding `/` arrives as one segment too many and the route answers 404.
- Under FastAPI 0.162, CI's fresh install, `app.routes` holds `_IncludedRouter` entries and a walk at runtime finds no route, so the filter cannot read the templates from the app.
- `scripts/echo_import.py` did not catch `ImportStopped`, so a stopped import printed Python's traceback to the operator's terminal, whose cause can quote what the importer could not read, such as a Goodreads rating cell holding words. `run_import` commits shares, events and facts in batches, so a run that stops part-way keeps what it committed under a failed import, and its `counts_json` also counts a batch that rolled back.

**Decision.**
1. **A user's words in a URL path are written by their length in the same filter,** chosen by route template in `log_redaction.WORDS_PATH_PARAMS`, today the fact key alone: `DELETE /api/v1/echo/context/interest/[25 characters]`. The method, the other segments, the query rules and the status stay.
2. **The path is matched as the route matched it.** Each template compiles once to a pattern: a kept parameter matches `[^/]+`, as Starlette's does, and only a words value may run over a decoded `/`. The length is counted with `unquote`, not `unquote_plus`, since `+` is a `+` in a path. Literals match in any case and percent-encoded, so a crafted URL hides more, never less, as D-168 point 2 has it for the query.
3. **A path no template matches is written whole.** The filter knows which segment holds words only from a template, no page builds such a path, and an operator reading a 404 needs it as it came. The one way a path the app builds misses its template's segment count, a decoded `/`, still matches.
4. **The templates are written in `log_redaction` and held to the routes by the guard.** `test_access_log_words.py` reads every route's template, not the handler's arguments, since a segment the handler never names is still in the URL. It fails on a path parameter in neither `WORDS_PATH_PARAMS` nor its kept list, where each has a reason, on a stale entry, and on one in both.
5. **The import script answers a stop in the route's words.** `scripts/echo_import.py` catches `ImportStopped` from the preview and from the run, prints the words `POST /echo/import` answers its 500 with on one stderr line, and exits 1. The service's own line of the stop, its frames, is marked (`is_stop_log`) and filtered from the service's logger for the script's run alone, so the API's log keeps it and the service's other lines still show.
6. **A part-way stop names what it kept.** `ImportStopped` carries `import_id`, and `run_import` sets it on an `ExportUnreadable` raised mid-run too. The script then prints a second line naming the import and its shares, activity events and facts, counted from the rows by `echo_import_service.stored_by`, which refuses another tenant's import, not from `counts_json`. It says "Import stopped" rather than "Not imported", and points to Your imports to undo it.

**Alternatives considered.**
- *Moving the key into a body.* An API change nobody asked for.
- *Reading the templates from the app at runtime.* FastAPI 0.162's route table yields none.
- *Redacting a path no template matches by guesswork,* such as every segment after a known prefix. It would hide what an operator needs from a 404 and protect no path the app builds.
- *Reading the guard's parameters from the handler's arguments.* A segment the handler never names would slip past.
- *Leaving the service's frames on the terminal.* stderr would no longer be one line, and the API's log already keeps them; a `--verbose` flag could bring them back if wanted.
- *Counting a part-way stop from `counts_json`.* It counts a batch that rolled back.

**Consequences.**
- The access log no longer writes a fact's key: the real `app.main:app` under the real uvicorn CLI wrote none of six keys. A route that adds a path parameter must list it as words or kept, or the guard fails.
- A fact whose key holds `/` still cannot be deleted by its route, which answers 404. The Echo page's form refuses such a label, but the API does not ([S-3.1.1](initiatives.md#s-311--deleting-a-fact-whose-key-holds-)). With a `{key:path}` template, `WORDS_PATH_PARAMS` and the guard must name the new template; the filter already treats a `:path` parameter as spanning.
- Vite's dev proxy still writes a failed request's path whole to `.frontend.*.log` while the backend is down or restarting (T-4.11.4.10).
- The command line no longer shows where a stopped import failed; the API's log does.
- The unused `Output` import is gone from `newsletter_service.py`. No migration and no new setting. Owner step: restart the API; `.uvicorn.out.log` keeps any fact key written before until then.

**Linked initiatives / PRs.** E-4.11 ([S-4.11.4](initiatives.md#s-4114--the-apis-own-log-lines): T-4.11.4.8 to T-4.11.4.10, OQ-45), E-3.1 ([S-3.1.1](initiatives.md#s-311--deleting-a-fact-whose-key-holds-)); PR [#459](https://github.com/khoks/VideoResearchPro/pull/459); [D-151](#d-151--the-sockets-token-is-a-subprotocol-provider-errors-are-scrubbed-as-each-log-record-is-made-and-json-logs-hold-their-format-from-the-first-line-2026-11-09), [D-164](#d-164--the-apis-warnings-and-errors-carry-no-users-words-an-operator-by-place-and-mask-echos-model-failures-by-type-and-status-a-chosen-file-name-by-its-extension-and-length-and-a-failure-logged-by-its-frames-is-never-re-raised-bare-2026-11-09), [D-168](#d-168--the-access-log-writes-a-users-words-by-their-length-chosen-by-parameter-name-in-one-filter-a-fail-soft-handler-rolls-back-before-it-reads-and-an-imports-own-row-fails-as-importstopped-2026-11-10).

**Status-changed 2026-11-10:** two consequences are closed. A fact whose key holds `/` is deleted by its route, `DELETE /echo/context/{kind}/{key:path}`; `WORDS_PATH_PARAMS` names that template, and a words `:path` parameter takes the rest of the path, a trailing `/` included ([D-174](#d-174--a-facts-key-is-the-rest-of-its-delete-routes-path-the-access-log-writes-all-of-it-and-the-echo-pages-form-accepts--in-a-label-2026-11-10), T-3.1.1.1, PR [#462](https://github.com/khoks/VideoResearchPro/pull/462)). Vite's dev proxy writes a failed request as `http proxy error: <METHOD> [path left out]` and its stack ([D-173](#d-173--the-dev-proxys-failed-request-line-names-its-method-and-leaves-the-path-out-through-a-customlogger-that-rewrites-that-line-alone-and-a-stack-loses-only-the-url-vite-was-given-2026-11-10), T-4.11.4.10, PR [#461](https://github.com/khoks/VideoResearchPro/pull/461)).

## D-172 — Only the cancel whose own write took announces it, an Author output stops at the write and keeps nothing when it ends unfinished, a failure refetches the run, and a refetch in flight at an end is cancelled rather than out-ranked (2026-11-10)

**Status:** accepted (2026-11-10). Made while building T-5.2.32 to T-5.2.35 (PR [#457](https://github.com/khoks/VideoResearchPro/pull/457)) and its review fixes, not ruled by the owner. It closes the four consequences [D-169](#d-169--a-cancel-that-takes-is-announced-after-its-commit-a-page-takes-no-more-events-for-a-run-it-holds-as-ended-the-runs-videos-follow-its-cached-status-and-every-cached-jobs-list-takes-a-runs-events-2026-11-10) left, takes [D-163](#d-163--a-progress-line-is-written-before-it-is-published-a-cancel-that-loses-the-race-answers-with-the-runs-end-and-revokes-nothing-and-completed-is-a-stopped-status-2026-11-09)'s conditional writes to Author outputs, and adds to D-169 point 4. T-5.2.29 stays the owner's call.

**Context.**
- A second cancel that raced the first answered 200 and published the same `cancelled` event again, because the route could not tell whether its own write took: `update_job_status` returned only the row.
- Author outputs already followed the run's stop rule at the start, where a terminal output is not run again, and in the cancel. But every write was a read followed by an unconditional ORM write: `report_progress` could publish `generating` after a cancel landed, the run's `completed` could overwrite a cancel that landed between its check and its write, and `cancel_output` could write `cancelled` over an output that finished after its read.
- A book commits its manuscript, citations and EPUB path with its 92% and 95% progress reports, so an output cancelled, failed, skipped or crashed after them kept that content, and `GET .../content` still served it (the review's finding).
- `POST /author/outputs` wrote `Queued` unconditionally after its dispatch, over a worker that had already failed the output.
- A `job_error` event set the page to failed but refetched neither the run nor the jobs lists.
- A refetch in flight when a run ends: in a tab that hears the end by its event, the event's refetch already cancels it (`cancelRefetch`, React Query's default). The one open path was the tab that pressed Cancel, when the HTTP answer arrives before the event: the answer stored `cancelled`, the event was then dropped as late by D-169 point 4, and the stale poll showed the run active for up to 5 seconds. Reproduced in vitest.
- `updated_at` is wall-clock time written by two processes, the API and the worker. On Windows two writes a few milliseconds apart can carry the same value.

**Decision.**
1. **Only the cancel whose own write took announces it.** `job_service.write_job_status` returns `StatusWrite(job, written)`, `written` coming from the conditional UPDATE's row count. `update_job_status` delegates to it and returns the row as before, so its other callers keep their contract. A racing second cancel still answers 200 and still revokes.
2. **An Author output stops at the write.** Every output status and progress write is one conditional `UPDATE ... WHERE status NOT IN TERMINAL_STATUSES` (`output_service._write_unless_ended`). The run's pending changes are flushed into the same transaction and rolled back on a refusal, and each event is published after its commit. `transition_to` returns whether it wrote. `cancel_output` writes conditionally, revokes only once the row says cancelled, and answers 400 when the output finished between its read and its write. A progress write refused on a row that another delivery ended raises `OutputStopped`, and the run stops. The create route writes `Queued` only over `pending` (`record_queued`) and keeps the task id whatever the status.
3. **An output that ends other than completed keeps no text, citations or files.** The cancel's write and the run's own `failed` or `skipped` write clear `content_text`, `content_path` and the citations in the same transaction (`drop_content`). A run that finds an end someone else wrote clears them with one write conditional on that end, and removes the folder (`_clear_unfinished`). A completed output keeps everything.
4. **The page drops a late output event.** `applyOutputProgress` leaves an ended row as it is, and `useOutputsProgress` counts the cached copies that took an event; an event every copy drops refetches nothing. `skipped` counts as an end.
5. **A failure is an end for refetching.** A `job_error` refetches the run and the jobs lists once. The videos stay with D-169 point 5's status watch.
6. **A refetch in flight when a run ends is cancelled, not out-ranked.** D-169 point 4's "a refetch still sets the cache in both directions" stands. A fetch that started before an end this tab stored is cancelled, by the ending event's refetch or by `storeAnswer`, which `useCancelJob` and `useApproveJob` call to cancel a fetch of the run in flight before they store their answer.

**Alternatives considered.**
- *Changing `update_job_status` to return its row count.* Every caller's contract would change; delegating keeps it.
- *Comparing `updated_at`, the newer row winning* (T-5.2.33's suggestion). A clock stepping back, or skew between hosts, would make a page drop the true row indefinitely, where today the next poll corrects it; two writes close together can tie; and the event would have to carry the row's time.
- *Revoking only from the cancel that wrote.* Not asked for: a second revoke is harmless, and the row is what stops a run.
- *Clearing an unfinished output's content only once its run notices the end.* A PDF render can take up to 180 seconds, while the cancelled output would still serve its manuscript.

**Consequences.**
- One cancel publishes one event. A cancelled, failed or skipped output never shows generating again, is never overwritten by `completed`, and serves no content from the moment it reads ended.
- A failed run's page refetches its row and the lists at once, and this tab's cancel or approve answer can no longer be undone by a poll already in flight.
- If two live deliveries of one output task run at once (T-5.2.29's situation), a file the second writes after the first completed, before its next progress report, can still replace the first's (T-5.2.36, the owner's call). Where the first ended failed or skipped, the second's late files are removed.
- `backend/tests/mutation.py` holds the mutation helper both run-event test files share. CLAUDE.md's WebSocket convention, `docs/architecture.md` and `docs/api-reference.md` (both cancel entries, the create route and the socket events) are updated.
- No migration, no new setting and no route change. Owner step: restart the API and the worker, and reload the frontend.

**Linked initiatives / PRs.** E-5.2 (T-5.2.29, T-5.2.32 to T-5.2.36), I-6; PR [#457](https://github.com/khoks/VideoResearchPro/pull/457); [D-163](#d-163--a-progress-line-is-written-before-it-is-published-a-cancel-that-loses-the-race-answers-with-the-runs-end-and-revokes-nothing-and-completed-is-a-stopped-status-2026-11-09), [D-169](#d-169--a-cancel-that-takes-is-announced-after-its-commit-a-page-takes-no-more-events-for-a-run-it-holds-as-ended-the-runs-videos-follow-its-cached-status-and-every-cached-jobs-list-takes-a-runs-events-2026-11-10).

## D-173 — The dev proxy's failed-request line names its method and leaves the path out, through a `customLogger` that rewrites that line alone, and a stack loses only the URL Vite was given (2026-11-10)

**Status:** accepted (2026-11-10). Made while building T-4.11.4.10 (PR [#461](https://github.com/khoks/VideoResearchPro/pull/461)), not ruled by the owner. It carries the rule of [D-168](#d-168--the-access-log-writes-a-users-words-by-their-length-chosen-by-parameter-name-in-one-filter-a-fail-soft-handler-rolls-back-before-it-reads-and-an-imports-own-row-fails-as-importstopped-2026-11-10) and [D-171](#d-171--a-users-words-in-a-url-path-are-chosen-by-route-template-in-the-same-filter-a-path-no-template-matches-is-written-whole-and-the-import-script-answers-a-stop-on-one-line-and-names-what-a-part-way-stop-kept-2026-11-10), no user's words in a log, from the API's access log to the log of Vite's dev proxy, and closes one of D-171's consequences.

**Context.**
- Under `scripts/start.ps1` the browser reaches the API through Vite's dev proxy. While the backend is down or restarting, Vite 8.0.3 logged every failed request as `http proxy error: ${res.req.url}` plus the error's stack, to `.frontend.err.log`, so a search's `?q=` words or a fact's key landed there, percent-encoded, on every restart under the launchers.
- Of the lines Vite 8.0.3's proxy writes, only that one holds a URL. The three `ws proxy` lines and the Origin-header warning name none. The `DEBUG=vite:proxy`, `vite:time` and `http-proxy-3` debug lines print the URL, but through the `debug` package straight to stderr, out of any logger's reach, and they are off unless `DEBUG` names them.
- The stacks hold no path. A real check got `AggregateError [ECONNREFUSED]`, `write ECONNRESET`, and `socket hang up` both for a backend that closes the socket and for a `proxyTimeout`; Node names the target's address at most. Only Vite's fetch-based proxy path, used with `FORCE_FETCH_PATH` or a custom `fetch`, neither set here, can raise an error that quotes the target URL.
- A `configure(proxy)` listener of its own cannot stop the line: Vite adds its own `error` listener after `configure`, and both fire. The listener does receive the same error object that Vite's then logs.

**Decision.**
1. **The line names its method and leaves the path out.** `frontend/vite.config.ts` sets `customLogger: withoutProxyPaths(createLogger())`, and `frontend/viteProxyLog.ts` rewrites `http proxy error: <url>` to `http proxy error: <METHOD> [path left out]`. The colour codes, the timestamp and the stack stay, and the stack says that the API was not answering and how.
2. **The method comes from a `configure` hook keyed by the error.** `noteFailedRequestMethod` on the `/api` proxy records `req.method` in a `WeakMap` keyed by the error object, and the logger looks it up from `options.error`. With none recorded the line reads `http proxy error: [path left out]`.
3. **A stack loses only the URL Vite was given,** as given and percent-decoded, never a guessed pattern, and never a bare `/`, which would match every slash in a frame.
4. **Every other line passes through unchanged** with its options object, from any method. Nothing is dropped, a non-string message goes on as it came, and `hasWarned`, `hasErrorLogged` and `clearScreen` are forwarded to Vite's logger.

**Alternatives considered.**
- *A `configure` listener alone.* Vite's own listener still fires and writes the line.
- *Writing the path's length,* as D-168 and D-171 do for the access log. The proxy line's only use is to say that the API was not answering.
- *Dropping the line.* The operator would lose the sign that the API was down.
- *A plugin `config` hook that builds the logger from the merged config,* which would keep `--logLevel` and `--clearScreen` working. The flags have no user here, and the item asked for a `customLogger` in the config.

**Consequences.**
- No run of the real check printed a user's word or `/api/v1`; with only the `customLogger` line removed, both URLs were printed whole.
- Vite skips its own `logLevel` and `clearScreen` handling for a custom logger, so `--logLevel` and `--clearScreen` on the command line no longer reach it. Nothing in the repo passes either; a level would go in `createLogger(...)`, as the config's comment says.
- The debug-only lines still print the URL when `DEBUG` names them.
- Found on the way: when Vite 8 detects an agent in its environment, it relays the browser's `console.error` and `console.warn` calls and its unhandled errors to the dev server's log (`server.forwardConsole`). Turning that off is T-4.11.4.11, the owner's call.
- `vitest.config.ts` and `tsconfig.node.json` include the module and its test, and CLAUDE.md's access-log convention gains a sentence. Frontend dev server only, with no owner step: Vite restarts its dev server when the config changes. `.frontend.err.log` keeps the lines written before.

**Linked initiatives / PRs.** E-4.11 ([S-4.11.4](initiatives.md#s-4114--the-apis-own-log-lines): T-4.11.4.10, T-4.11.4.11); PR [#461](https://github.com/khoks/VideoResearchPro/pull/461); [D-168](#d-168--the-access-log-writes-a-users-words-by-their-length-chosen-by-parameter-name-in-one-filter-a-fail-soft-handler-rolls-back-before-it-reads-and-an-imports-own-row-fails-as-importstopped-2026-11-10), [D-171](#d-171--a-users-words-in-a-url-path-are-chosen-by-route-template-in-the-same-filter-a-path-no-template-matches-is-written-whole-and-the-import-script-answers-a-stop-on-one-line-and-names-what-a-part-way-stop-kept-2026-11-10).

## D-174 — A fact's key is the rest of its delete route's path, the access log writes all of it, and the Echo page's form accepts `/` in a label (2026-11-10)

**Status:** accepted (2026-11-10). Made while building T-3.1.1.1 (PR [#462](https://github.com/khoks/VideoResearchPro/pull/462)), not ruled by the owner. It closes the consequence of [D-171](#d-171--a-users-words-in-a-url-path-are-chosen-by-route-template-in-the-same-filter-a-path-no-template-matches-is-written-whole-and-the-import-script-answers-a-stop-on-one-line-and-names-what-a-part-way-stop-kept-2026-11-10) that named this bug, takes D-171's path filter to a `:path` template, and keeps the tombstones of [D-122](#d-122--a-deleted-derived-fact-stays-deleted-per-connector-only-a-refused-refresh-asks-for-a-reconnect-restore-re-checks-the-evidence-2026-11-04) (T-3.2.4.4, ruled in [D-110](#d-110--echo-only-sees-what-the-user-hands-it-no-background-capture-and-the-echo-scope-rulings-2026-10-25)) on the whole key.

**Context.**
- `DELETE /api/v1/echo/context/{kind}/{key}` answered 404 for a key holding `/`: the server decodes `%2F` before it routes, so the key reached the router as one segment too many.
- Every write goes through `echo_service.record_context`. `POST /echo/context` accepts any key of 1 to 128 characters, `/` included; only the Echo page's form refused it, and its comment gave this bug as its only reason. The GitHub connector derives `"{language} (GitHub)"` from GitHub's language names; none known holds `/`, but nothing stops one. Apple Health's keys are fixed (`sleep`, `steps`, `workouts`), no other importer derives facts, and signal extraction writes its own table.
- The live database, opened read-only, held 0 `personal_context` rows, so 0 keys with `/`, and 0 tombstone keys with one.
- D-171's path filter matched a words value lazily, so a key ending in `/` was written `[1 character]/`.
- Starlette's `TestClient` decodes a path twice, since httpx's `URL.path` is already decoded and the transport unquotes it again; `httpx.ASGITransport` decodes it once, as uvicorn does.

**Decision.**
1. **The key is the rest of the path.** The route is `DELETE /api/v1/echo/context/{kind}/{key:path}`, so every `/` in the key is part of it. A key with no `/` is matched and answered as before, and rows already stored with a `/` can be deleted. This is safe only while no other route sits under `/echo/context/`, which a test pins; the tombstone routes were already kept out of it for that reason.
2. **The access log writes all of it.** `log_redaction.WORDS_PATH_PARAMS` names the new template, and a words parameter with the `:path` convertor takes the rest of the path as Starlette's `.*` reads it, a trailing `/` included, so the whole key is written by its length however many `/` it holds. A words parameter without the convertor still stops before a trailing `/`.
3. **The Echo page's form accepts `/` in a label.** `echoApi.deleteContext` already encoded the key whole with `encodeURIComponent`.
4. **A tombstone keeps the whole key.** A derived fact holding `/` is deleted by the route, its tombstone lists the whole key, the next sync skips it, and "Allow again", which clears by the tombstone's id, brings it back.

**Alternatives considered.**
- *Refusing `/` at write time.* The API already accepts such keys, any API client can write one, and a connector can derive one; a refusal would strand stored rows and could break a connector.
- *Moving the key into a body.* An API change nobody asked for, as D-171 found.
- *Keeping the words match lazy.* A trailing `/`, which the route reads as part of the key, would stay outside the count.

**Consequences.**
- A fact whose key holds `/` is deleted by its route. The real `app.main:app` under the real uvicorn CLI answered 200 for each of 15 keys, and its access log held only their lengths.
- A fact labelled exactly `.` or `..` still cannot be deleted from a page: a browser resolves such a path segment before it sends the request, written or percent-encoded, so the request goes out as `.../context/`. Unrelated to `/`, and true before. Refusing those two labels at write, or a delete that carries the key in a body, is [S-3.1.2](initiatives.md#s-312--deleting-a-fact-labelled--or-) (T-3.1.2.1), the owner's call; `docs/api-reference.md` notes the limit.
- CLAUDE.md's API line says the key may hold `/`. Its access-log convention still names the route as `{key}`, which stays true.
- No migration and no new setting. Owner step: restart the API.

**Linked initiatives / PRs.** E-3.1 ([S-3.1.1](initiatives.md#s-311--deleting-a-fact-whose-key-holds-): T-3.1.1.1; [S-3.1.2](initiatives.md#s-312--deleting-a-fact-labelled--or-): T-3.1.2.1), E-3.2 (T-3.2.4.4), E-4.11 ([S-4.11.4](initiatives.md#s-4114--the-apis-own-log-lines)); PR [#462](https://github.com/khoks/VideoResearchPro/pull/462); [D-110](#d-110--echo-only-sees-what-the-user-hands-it-no-background-capture-and-the-echo-scope-rulings-2026-10-25), [D-122](#d-122--a-deleted-derived-fact-stays-deleted-per-connector-only-a-refused-refresh-asks-for-a-reconnect-restore-re-checks-the-evidence-2026-11-04), [D-171](#d-171--a-users-words-in-a-url-path-are-chosen-by-route-template-in-the-same-filter-a-path-no-template-matches-is-written-whole-and-the-import-script-answers-a-stop-on-one-line-and-names-what-a-part-way-stop-kept-2026-11-10).
