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

**Status:** accepted (partially superseded by [D-013](#d-013--personal-account-oauth-as-fallback-for-mode-b-paste-2026-04-25) — paste-only Mode B *is* supported on TikTok and Discord via user-OAuth; only Mode A search / per-server bot remain deferred).

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

## D-013 — Personal-account OAuth as fallback for Mode B paste (2026-04-25)

**Status:** accepted.

**Context.** Mode B (manual paste of post URLs) was originally scoped to fetch only **public** posts via the article pipeline (trafilatura → Playwright fallback). Many social-media posts on Facebook / Instagram / LinkedIn / Discord / TikTok are partially or fully gated — visible to logged-in users but stripped or denied for an anonymous request. Without an authenticated path, paste mode fails on a large fraction of real-world URLs the user wants to ingest.

The user's framing: "the user shares the link with the app, and the app accesses it either as a public post or via the auth of the user's own accounts."

**Decision.** Each Mode B connector is upgraded to a two-step fetch:

1. **Try public anonymous fetch first** (today's trafilatura → Playwright pipeline).
2. **If the response is gated** (login wall, content stripped, error 401/403), fall back to a fetch using a **per-user, per-platform stored OAuth token** — when the user has connected that account in a "Connected accounts" settings surface.

OAuth connection is **opt-in per platform**. Tokens are stored encrypted and scoped to a single user; in self-host they never leave the device. Refresh handled by the same connector. Same pattern as [D-009](#d-009--twitter--x-is-byok--opt-in-2026-04-25) (BYOK Twitter), generalized: every platform that has an OAuth flow can accept a personal account as the fetch identity.

This **partially supersedes D-010**: TikTok and Discord were deferred indefinitely on the assumption that no public-search and no global-bot path was viable. With paste-mode + user-OAuth, the user can drop a TikTok video URL or a Discord message URL and the connector fetches via the user's logged-in session. **Mode A (search/discovery) on those platforms remains deferred.**

**Alternatives considered.**
- *Paste public-only forever.* Roughly half of real FB/IG/LI URLs strip content for anonymous fetches. Users hit dead-ends and lose trust in the paste flow.
- *Require BYOK API tokens for every platform.* Higher friction than OAuth (FB/IG/LI/Discord/TikTok don't expose user-level "developer keys" for casual users; OAuth is the natural path). Twitter's BYOK works precisely because Twitter offers a paid API tier; the others don't.
- *Use third-party scraping vendors with shared session cookies.* Same ToS objection as [D-008](#d-008--no-scraping-of-search-result-pages-on-fb--ig--linkedin-2026-04-25), now with vendor-lock-in costs.
- *Require the user to copy-paste the post text manually instead of the URL.* Loses metadata (author, date, score, thread structure), breaks citations, breaks the curation flow uniformity Ring 2 of the [vision](vision.md) promises.

**Consequences.**
- New schema: `user_platform_tokens` table — `(user_id, platform, access_token_encrypted, refresh_token_encrypted, scope, expires_at)`. Reuses the SaaS BYOK pattern; SaaS later adds per-tenant scoping and key rotation.
- New connector capability: `fetch_text_with_user_auth(candidate, user_id) -> ExtractedText`. Default `fetch_text` keeps the public-anonymous path; the orchestrator dispatches to the auth fallback only when the public path returns gated content.
- New frontend surface: **Connected Accounts** settings page (planned under E-2 / I-2, but the data model lives under I-1 / E-1.5).
- TikTok and Discord enter the supported-paste-platforms set. Mode A (search / per-server bot) remains deferred until a clear user need emerges.
- Each connector's fetch result records `text_source` accurately: `paste_extract_public` vs `paste_extract_user_auth` so the audit trail distinguishes how the content was reached.
- Privacy posture sharpens: the same self-host model that already handles `OPENAI_API_KEY` now also holds platform OAuth tokens. SaaS tier inherits this cleanly via per-tenant secrets storage from [saas-roadmap.md](saas-roadmap.md).

**Linked initiatives / PRs.** I-1 / E-1.5 / S-1.5.8 (extended). New stories tracked under E-1.5 for Discord-paste, TikTok-paste, and the Connected-Accounts settings surface. Partially supersedes [D-010](#d-010--defer-tiktok-and-per-server-discord-bot-indefinitely-2026-04-25).
