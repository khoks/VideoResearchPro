# Pratidhvani — Vision & North Star

**Status:** approved (2026-04-24). This is the durable "what is this app, and why does it exist" document.

---

## What is Pratidhvani?

Pratidhvani (`प्रतिध्वनि`, Sanskrit/Hindi for *echo*) is a **personal, curated wiki and second brain** built from the sources its user has chosen to listen to.

It ingests videos, podcasts, blogs, articles, forum threads, and books that the user explicitly selects, transcribes and embeds them into a global personal library, lets the user ask citation-grounded questions across that library, and accumulates every question, answer, and annotation as durable knowledge — eventually learning enough about the user to speak in their voice.

Wikipedia is moderated, balanced, diluted, and tries to take no side. Pratidhvani is the opposite: **opinionated, user-curated, often unofficial, and unapologetically personal.** It captures what common people say when they talk to each other — in podcasts, on forums, in long YouTube essays — that mainstream encyclopedias either omit or sand down to neutrality.

If Wikipedia is the public square's negotiated truth, Pratidhvani is **your** truth: the version of the world built from the voices you trust.

---

## Why this exists

### The problem with "balanced" knowledge

The dominant knowledge tools today — Wikipedia, official news, mainstream search — optimize for consensus, citability, and neutrality. That has real value, and Pratidhvani does not exist to replace it. But three things go missing:

1. **The voices common people actually listen to.** Most knowledge people carry around comes from podcasts they trust, creators they follow, forums they read, and friends they talk to — not from Wikipedia. Those voices rarely meet the citability bar of an official source, but they're often more accurate to *how the user actually thinks*.
2. **Opinion and stance.** Mainstream sources strip opinion in the name of neutrality. But the user's mental model of any non-trivial topic is shaped *by* opinions, not in spite of them. A wiki that pretends opinion doesn't exist isn't useful for thinking — it's useful for citing.
3. **Disagreement.** Mainstream sources resolve disagreements with a "some say X, others say Y" sentence. The user wants to hear both sides at length, in the speakers' own words, and decide for themselves.

Pratidhvani is built on the premise that **a wiki of voices the user has chosen to weight** — opinionated, unofficial, sometimes contradictory — is more useful for thinking than a neutralized one.

### The problem with "AI knows everything"

Generic LLMs and search-augmented chatbots have the opposite failure mode: they pull from everything indiscriminately and present it as one confident voice. The user has no way to ask *who* said what, no way to weight sources, no way to surface their preferred voices over mainstream ones, and no way to grow the model's knowledge with the specific conversations they care about.

Pratidhvani inverts this:

- The user controls **which sources** the system listens to.
- Every answer cites **exactly which voice** said which fragment, with timestamps and links.
- The user can **weight sources** so their trusted creators outrank mainstream ones in retrieval (see L4 in [feature-roadmap.md](feature-roadmap.md)).
- The user's own **notes, opinions, and Q&As** become first-class citizens in the same library.

---

## Three concentric circles of vision

Pratidhvani's vision unfolds in three nested rings, each strictly contained by the next.

### Ring 1 — Personal wiki (today + near-term)

The smallest, most concrete circle. **Already largely shipped.**

The user picks sources (currently YouTube channels and topics), curates a discovery list, approves which videos to actually ingest, and then queries the resulting transcript library for citation-grounded answers. Subscriptions auto-pull new content from chosen channels. Knowledge reports extract structured `{topics, concepts, events, facts}` per video. Q&A history accumulates into its own searchable corpus.

**The product north-star here**: a wiki the user has *built themselves*, source-by-source, opinion-by-opinion. It looks and reads like a research journal, not a database.

### Ring 2 — Multi-source curated knowledge (next 1-2 quarters)

The middle ring. **Begins with L1 in [feature-roadmap.md](feature-roadmap.md).**

The same job/approval/curation flow generalizes beyond YouTube to:

- Podcasts (Spotify, Apple, RSS — Whisper-transcribed if no transcript)
- Articles & blogs (URL → readable text extraction)
- Twitter/X threads (unrolled)
- Forum threads (Reddit, Hacker News, Discourse)
- PDFs & e-books (uploaded files)
- Eventually: Substack, Medium, podcast newsletters, Discord public threads

Crucially the **user-agency surface stays identical** across all source types: search instructions, approval list, preferred-source filters, AI-query-instructions. The user wants the curation flow preserved because *that flow is the product*. Each new source type just plugs into the same shape.

The library at this stage is **multi-modal, multi-source, all citation-grounded.** Asking "what do I think about supply chains?" can pull from a Lex Fridman episode, a substack article, a Reddit thread, a book PDF, and the user's own notes — all in one answer, all cited.

The user can then turn this curated knowledge into outputs:

- **Books** (Markdown → PDF/EPUB) on selected topics
- **Static personal-wiki sites** published from a chosen subset of the library
- **Slide decks** (PPTX) summarizing a topic
- **Newsletters / digests** running on a schedule
- **Reels / videos** scripted from knowledge artifacts, narrated via TTS

This is the "Author Studio" surface (L2 in [feature-roadmap.md](feature-roadmap.md)).

### Ring 3 — Personal brain / second self (long-horizon)

The widest, most ambitious circle. **Multi-quarter trajectory; design lives in [personal-brain.md](personal-brain.md).**

The wiki keeps growing. The Q&A library keeps growing. Notes and opinions keep accumulating. Now the system also begins ingesting *the user themselves*:

- Email (read-only)
- YouTube watch history & likes
- Spotify listening history
- Browser history (opt-in, scoped)
- Calendar
- Places visited (location history)
- Apple Health / Strava (activity, sleep, heart-rate)
- Goodreads / Letterboxd / GitHub (consumption history)
- Daily journaling input the user provides

Each connector is **opt-in, scoped, revocable, encrypted-at-rest**, and respects a clear privacy model. Self-host stores everything locally; the eventual SaaS tier offers a zero-knowledge mode (see [saas-roadmap.md](saas-roadmap.md)).

From this combined corpus — sources the user trusts + the user's own life — Pratidhvani begins to:

1. **Suggest questions** the user would likely ask, based on their patterns.
2. **Anticipate what they need** when they open a topic (e.g. surface their saved-but-unread podcast on it).
3. **Capture their voice** — writing samples, conversational style, recurring opinions — so that…
4. **The "Speak as me" agent** can draft responses to incoming messages, emails, comments — in the user's voice, citing their accumulated knowledge.

The endpoint of this ring is a **second self**: not a clone, not a copy, but a research-grounded interlocutor that knows what the user knows, sounds like the user sounds, and can hold a conversation on the user's behalf when they're not available.

---

## Design principles (these constrain every PR)

### 1. Curation is the product

Every feature must preserve or strengthen the user's curation surface. The search → approval → channel-suggestion → AI-query-instructions flow is non-negotiable. New source types plug into it; new agents respect it; new outputs cite it.

### 2. Sources are first-class. Voices are first-class. The user is first-class.

Every answer cites a specific voice (creator, author, podcaster, the user themselves) with a specific timestamp / page / URL. There is no anonymous "the system says". Even the user's notes are cited as "you said this on 2026-03-15".

### 3. Opinion is preserved, not flattened

Reports must not average out disagreement. If two sources disagree, both views appear in the answer, attributed to their voice. Source-weight adjusts ordering, never erases.

### 4. Privacy-first, especially for Ring 3

Self-host data is local. Activity connectors are opt-in per connector, revocable, scoped. SaaS tier ships with zero-knowledge mode and full export / full delete. We never share user data between users by default; sharing is explicit, signed-URL, and revocable.

### 5. Forward-compatible with public SaaS

Today is open-source self-host. Tomorrow is public SaaS with subscription tiers, billing, abuse prevention, and scaling. Every PR today checks against [saas-roadmap.md](saas-roadmap.md) so we don't ship code that blocks the migration. Specifically: every user-scoped table grows a `tenant_id`/`workspace_id` column from the start, even though only one tenant exists per self-host install.

### 6. Editorial, not technical, voice in user-facing copy

Pratidhvani reads like a research journal, not a SaaS dashboard. "Library" not "database". "Volume" not "row". "Echo" not "result". The brand voice rules in [branding.md](branding.md) bind every user-facing string.

### 7. Fail-soft, never brick

LLM provider down? Banner on top, primary actions disabled, the rest of the app stays interactive. YouTube quota exhausted? Surface it; let the user keep reading existing content. The user must always be able to *read* their accumulated library, even when *new* ingestion is blocked. Already implemented for LLMs; same posture extends to every external dependency.

---

## What Pratidhvani is not

To keep scope honest:

- **Not a Wikipedia replacement.** Wikipedia's negotiated-consensus role is genuinely useful and Pratidhvani complements it rather than competing with it.
- **Not a YouTube alternative.** We don't host video; we transcribe and index.
- **Not a generic LLM chatbot.** We're not trying to know everything. We know exactly what the user has chosen to listen to.
- **Not a creator monetization platform.** Creators are the source of voices; we don't intermediate their revenue.
- **Not anonymous.** Every answer cites who said what. No "AI says".
- **Not opinion-laundering.** We don't strip opinion to look neutral. We preserve and attribute it.
- **Not free of friction.** The approval step exists on purpose. The user is meant to think about which sources to ingest. We don't auto-ingest the world.

---

## Trajectory & milestones

Roughly:

| Phase | When | Scope |
|-------|------|-------|
| **Phase 0 — VideoResearchPro era** (shipped) | Through 2026 Q1 | YouTube-only ingest, jobs (topic/channel/subscription), global library, citation Q&A, knowledge artifacts, dataset exports, multi-user auth, fail-soft LLM routing. |
| **Phase 1 — Pratidhvani rebrand** (current) | 2026 Q2 | Name, brand, warm-editorial visual identity, sidebar navigation, design tokens, doc consolidation. **No functional regression.** |
| **Phase 2 — Multi-source ingest** | 2026 Q3 | L1 lands. Podcasts + articles + threads + PDFs feed the same job/approval/library flow. `videos` table generalized to `documents`. |
| **Phase 3 — Author Studio** | 2026 Q4 | L2 lands incrementally: Books → static sites → decks → reels. |
| **Phase 4 — Curated source ranking** | 2027 Q1 | L4 lands. Source weights, disagreement-preserving answers, side-by-side narratives. |
| **Phase 5 — SaaS** | 2027 Q2+ | L5 lands. Hosted SaaS, billing tiers, OAuth, regions, abuse prevention. Self-host stays first-class. |
| **Phase 6 — Personal Brain** | 2027 Q3+ | L3 begins. Activity connectors opt-in, voice capture, "speak as me" agent. |

Targets are aspirational, not commitments. Each phase only ships when its design doc, schema migration, and user-facing flow are stable enough to live with.

---

## Cross-references

- Naming, identity, palette, typography → [branding.md](branding.md)
- Concrete feature list (L1-L5, M1-M12) → [feature-roadmap.md](feature-roadmap.md)
- Multi-source abstraction (L1) → [source-types.md](source-types.md)
- Personal Brain ring 3 design → [personal-brain.md](personal-brain.md)
- SaaS forward-compat constraints → [saas-roadmap.md](saas-roadmap.md)
- Current architecture → [architecture.md](architecture.md)
- API → [api-reference.md](api-reference.md)
- UI → [ui-design.md](ui-design.md), [ui-pages.md](ui-pages.md)
