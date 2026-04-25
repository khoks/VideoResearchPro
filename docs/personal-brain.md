---
name: personal-brain
description: L3 long-horizon design — activity connectors, voice capture, "speak as me" agent, privacy model
type: project
---

# Personal Brain — L3 long-horizon design

**Status:** future-work, design-only (2026-04-24). Not on the immediate roadmap. This doc exists so today's schema and connector decisions stay forward-compatible.

This is Ring 3 of the [vision](vision.md). It begins after Phase 4 of the [feature-roadmap](feature-roadmap.md) ships (post-2027 Q3). Nothing in this document is a commitment — it is the picture we're navigating toward, written down so day-to-day choices don't accidentally foreclose it.

---

## North star

Pratidhvani as a **second self**: not a clone, not a copy, but a research-grounded interlocutor that knows what the user knows, sounds like the user sounds, and can hold a conversation on the user's behalf when they are not available.

Three concrete capabilities mark "we got here":

1. **Anticipation** — given a topic the user opens, the system surfaces *the questions they would ask next*, the *podcast they saved but haven't listened to*, the *thread from last month they probably forgot*.
2. **Voice** — given a draft (email, comment, response), the system rewrites it in the user's voice, with the user's recurring opinions, framings, and citations.
3. **Delegation** — given an incoming message (email, DM, comment), the system drafts a reply *as the user would*, citing accumulated knowledge, marking confidence, never sending without approval.

The system never *acts* unilaterally. The user is always in the loop for outbound communication. "Speak as me" is a draft-generator, not an autopilot.

---

## Echo — the named L3 surface

The Ring 3 user-facing feature has a name: **Echo** (a proper-noun reuse of the brand's literal meaning, *Pratidhvani* = echo). Everything in the rest of this doc — personal context store, activity stream, personality capture, "speak as me" agent, constant-stream intake — exists to make Echo work. Echo is *the* showcase L3 feature; the five domains below are its supporting infrastructure.

### What makes Echo distinct from existing Q&A surfaces

- **Job Q&A** answers from a single job's approved videos.
- **Library Q&A** answers from the global ingested source library.
- **Q&A History Chat** answers about the user's past Q&A history.
- **Echo** answers *as the user themselves* — synthesising sources, history, personal facts, activity, and personality signals into a response that mirrors the user's lens, methodology, and conclusions. The user's framing (see [`notes/2026-04-24-echo-feature-vision.md`](notes/2026-04-24-echo-feature-vision.md)) is that Echo should "behave just like the individual who is using it… their own perception, their own lens, their own apprehensions, their own methodology."

### Always-evokable surface (the "Jarvis" pattern)

Echo lives as a **floating bubble** present on every page. One click expands it into a chat panel; one click collapses it back. It is summoned, not navigated to. Keyboard shortcut planned: `cmd+e` / `ctrl+e`.

The bubble is *always* there once a user has Echo enabled. Pages with their own primary surface (Job Q&A panel, Library Q&A page) keep working — Echo is additive, not a replacement. The user picks which surface to use based on the question shape.

### Cold-start: Echo refuses before it can echo well

The user's explicit framing:

> *"first the app has to obviously learn how to think like the user and have the substantial set of shared content first before it can echo the user end to end."*

Echo therefore ships with a **readiness threshold** measured against the five domains. Until a user crosses it, the floating bubble is either hidden, dimmed, or shows a "still listening — share more, ask later" state with a progress meter. Better to refuse than to mimic poorly and break trust.

Recommended initial threshold (subject to validation):

| Signal | Minimum |
|--------|---------|
| Self-authored personal facts (Domain 1) | 30 facts across ≥ 3 categories |
| Activity events (Domain 2, any connector) | 90 days of history with ≥ 200 events |
| Personality signals (Domain 3) | ≥ 50 distinct signals across ≥ 4 signal types |
| Constant-stream shares (Domain 5) | ≥ 100 shares spanning ≥ 4 content types |

Below threshold: Echo shows the readiness meter and explains what's missing (*"I've learned 38 of the 100 shares I'd like before I start speaking as you."*). Crossing threshold: the bubble lights up and a one-time onboarding moment introduces the user to it.

### Why Echo is *not* just a fancier Q&A agent

Echo's substrate is broader than retrieval. The user explicitly flagged that "just having a RAG to answer is" probably insufficient. Echo combines:

- **Retrieval over the user's curated library** — for grounding in the voices the user trusts (the existing library Q&A pipeline).
- **Retrieval over the user's history & activity** — past Q&As, watch history, listening, journaling, places visited.
- **Retrieval over personal facts and personality signals** — opinions, methodology, apprehensions, recommendation lens, trusted conclusions.
- **Optional fine-tuning** — a per-user model fine-tuned on the user's own writing and a curated set of dataset themes (problem-solution, recommendation lens, situational priority, opinion-formation, methodology), used as the answer model when the readiness threshold is crossed. See open question 1.
- **An agentic harness** — multi-step planning that consults the right substrate for each turn ("does this question want a personal-fact answer, a sourced answer, an activity-grounded answer, or a synthesis of all four?") rather than a single RAG pass.

The structured plumbing for all of this is what Domains 1-5 + the "speak as me" agent describe.

---

## What we add to the existing library

The current library has:

- **Sources** — videos, podcasts, articles, threads, PDFs (per [source-types](source-types.md)).
- **Knowledge artifacts** — extracted `{topics, concepts, events, facts}` per source.
- **Q&A history** — every question, answer, citation, and follow-up the user has run.
- **Notes** — user-authored annotations attached to sources, channels, exchanges (medium feature M5).

Personal Brain layers **five new domains** on top:

- **Personal context (Domain 1)** — who the user is, distinct from what they consume.
- **Activity stream (Domain 2)** — what the user passively does, in pull-mode connectors.
- **Personality capture (Domain 3)** — how the user thinks, talks, concludes, and decides — the substrate Echo speaks from.
- **"Speak as me" agent (Domain 4)** — the LangGraph pipeline that produces drafts and Echo answers.
- **Constant-stream intake (Domain 5)** — what the user actively pushes into Pratidhvani all day, across surfaces.

All five are **first-class library content**: searchable, citable, embedded into the same retrieval surface — though the curation/approval flow varies (Domain 5 is friction-free push, Domains 1-4 retain explicit user control).

---

## Domain 1 — Personal context store

A small, durable, hand-curated set of facts about the user. Different from the Q&A history (which is consumption-shaped) and the activity stream (which is event-shaped).

### Schema sketch

A new table, `personal_facts`:

| column | type | notes |
|--------|------|-------|
| `id` | UUID | PK |
| `tenant_id` | UUID | per [saas-roadmap](saas-roadmap.md) invariant |
| `user_id` | UUID | every fact belongs to one user, even within a shared tenant |
| `category` | enum | `identity`, `interest`, `expertise`, `opinion`, `routine`, `relationship`, `goal`, `event`, `place` |
| `content` | text | the fact itself, in the user's own words |
| `source` | enum | `self_authored`, `derived_from_qa`, `derived_from_activity`, `imported` |
| `confidence` | float | 0–1; self-authored = 1.0, derived = retrieval similarity |
| `valid_from` | date | when the fact became true |
| `valid_to` | date | nullable; when it stopped being true (we never delete, we tombstone) |
| `created_at` | timestamp | |
| `updated_at` | timestamp | |
| `embedding_id` | string | reference into a new Chroma collection |

A **new Chroma collection** (`personal_context_global`) embeds every fact so retrieval can pull them into Q&A and "speak as me" context.

### Categories with examples

- **identity** — *"I am a senior backend engineer."* / *"I live in Bangalore."* / *"I read primarily in English and Hindi."*
- **interest** — *"I follow Indian macroeconomics closely."* / *"I'm learning Tamil this year."*
- **expertise** — *"I have ten years of distributed-systems experience."* / *"I worked on latency-critical infra at $company."*
- **opinion** — *"I think LLM agents are oversold for production right now."* / *"I prefer narrow focused podcasts to celebrity-host long-form."*
- **routine** — *"I review my reading queue every Sunday morning."* / *"I run 5km on Tue/Thu/Sat."*
- **relationship** — *"My co-founder and I disagree about pricing strategy."* (relationships intentionally vague — we never store contact graphs in the brain)
- **goal** — *"I want to ship Pratidhvani SaaS by 2027 Q2."* / *"I want to publish a book on $topic by 2028."*
- **event** — *"Joined $company on 2024-08-15."* / *"Moved to Bangalore on 2025-01-10."*
- **place** — *"Frequent: Koramangala, Indiranagar. Travel: Goa twice a year."*

### How facts enter the store

Three pathways, in order of trust:

1. **Self-authored** — the user writes them directly via a "Personal context" page. Highest trust.
2. **Confirmed-derived** — the system *suggests* a fact ("It looks like you've been asking a lot about supply chains — should I save this as a current interest?") and the user confirms. Saved with `source=derived_from_qa` and `confidence` capped at 0.8 even after confirmation, since derivation can drift.
3. **Auto-derived** — the system infers a fact from activity stream patterns (see Domain 2) and stores it with `confidence < 0.5`, *not yet shown* in Q&A retrieval, but available for the user to promote to a confirmed fact.

Tombstoning is a first-class action. *"That used to be true; it isn't anymore."* The fact is kept (for "what did I think in 2027?") but `valid_to` is set, and retrieval respects the date range.

---

## Domain 2 — Activity stream

The history of what the user does, consumes, and visits, ingested via opt-in connectors. Different from the personal context store (which is curated facts) — this is raw events.

### Schema sketch

A new table, `activity_events`:

| column | type | notes |
|--------|------|-------|
| `id` | UUID | PK |
| `tenant_id` | UUID | |
| `user_id` | UUID | |
| `connector` | string | `youtube_history`, `spotify_history`, `email`, `calendar`, `browser_history`, `apple_health`, `strava`, `goodreads`, `letterboxd`, `github`, `journal` |
| `event_type` | string | per-connector vocabulary, see below |
| `occurred_at` | timestamp | when the event happened in the user's timezone |
| `ingested_at` | timestamp | when we received it |
| `payload` | JSON | connector-specific structured data |
| `text_content` | text | extracted searchable text (nullable; e.g. email body, journal entry) |
| `embedding_id` | string | nullable; only embedded if `text_content` is meaningful |
| `linked_source_id` | UUID | nullable; foreign key to `documents` if this event relates to an ingested source (e.g. you watched a video that's already in your library) |

A **new Chroma collection** (`activity_stream_global`) embeds events with meaningful text. Events without text (e.g. "Strava run, 5km, 28 min") are queryable via SQL only — they don't need vector retrieval.

### Connector catalog (proposed launch order)

Order chosen by: ease of ingestion → privacy weight → leverage. Cheapest signals first; emails last because they are heaviest privacy load.

| # | Connector | Why first | Privacy weight | Notes |
|---|-----------|-----------|----------------|-------|
| 1 | **YouTube watch history** | Already in our orbit (we own the YouTube ingestion). One Google OAuth scope. Massive signal: which creators the user actually consumes vs. just searches. | low — user consented context | Google Takeout export as bootstrap; OAuth `youtube.readonly` for incremental |
| 2 | **Spotify listening history** | Single OAuth, clean API, podcast/song split is rich. Tells us *which* podcast episodes the user really listens to (not just subscribes to). | low | Spotify recently-played + saved |
| 3 | **Goodreads / Letterboxd** | Tiny, structured, intentional (the user marks it themselves). Strong signal for "what they consume." | low | RSS or scraping |
| 4 | **Calendar** | Where time goes. Critical for routine inference. | medium — work info | Google Calendar / iCal read-only |
| 5 | **Apple Health / Strava** | Sleep, runs, activity. Tells us when the user is in flow vs. fatigued, when to expect them online. | medium — biometric | Apple Health export, Strava OAuth |
| 6 | **GitHub** | If user codes, what they push tells us their current focus and expertise areas. | low — public anyway | OAuth `read:user`, `repo` for private |
| 7 | **Browser history** | Extremely rich, extremely sensitive. Probably opt-in *per category* (work vs. personal) via browser extension. | high | Custom browser extension; never ingest incognito |
| 8 | **Journal entries** | User-authored. The richest signal we have for "voice." | high — but self-authored | Plain markdown files in a folder, or in-app editor |
| 9 | **Email (read-only)** | The single largest unstructured personal corpus. Last because of privacy load and the volume problem (a typical inbox is 100K+ messages). | very high | Gmail/IMAP read-only; user picks which labels to ingest |

Each connector ships as a **small, isolated module** under `backend/app/connectors/<name>/`, conforming to a single interface (see §6).

### Event-type vocabulary (per connector, examples)

- **youtube_history**: `watched`, `liked`, `subscribed`, `unsubscribed`, `added_to_playlist`
- **spotify_history**: `played_track`, `played_episode`, `saved`, `created_playlist`
- **calendar**: `event_attended`, `event_declined`, `event_organized`
- **apple_health**: `sleep_session`, `workout`, `mindful_minutes`, `heart_rate_anomaly`
- **email**: `message_received`, `message_sent`, `thread_archived`, `flagged`, `replied`

The vocabulary is intentionally per-connector. We don't try to unify "watched a video" and "played a track" into one global event-type — they're searched and reasoned over differently.

### What we do NOT ingest, ever

- **Other people's content.** A friend's email to the user is theirs, not the user's; we ingest it for the user's personal index but never embed it into anything that might leave the user's tenant.
- **Live location streams.** We ingest *places visited* (city, neighborhood) at calendar-event granularity, never live GPS.
- **Financial transactions.** Out of scope.
- **Private messages from other people.** We can ingest *the user's outgoing messages* for voice capture, but we don't index the other party's content beyond what's needed to understand context.
- **Anything from a connector the user didn't explicitly enable for that data type.** Browser history connector enabled ≠ work-domain browser history ingested unless work-domain is enabled.

---

## Domain 3 — Personality capture

Goal: a model of who the user *is* across many dimensions, not just how they talk. Style and cadence (lexical / syntactic / rhetorical) sit alongside the deeper layers — what conclusions they trust, what solutions they reach for, what they're apprehensive about, what methodology they apply, what topics they emphasise. Used by the "speak as me" agent and by Echo (the named Ring 3 surface above).

The user's explicit framing on 2026-04-24 (verbatim in [`notes/2026-04-24-echo-feature-vision.md`](notes/2026-04-24-echo-feature-vision.md)):

> *"their own perception, their own lens through which they view the world, their own set of knowledge which they quote and use and rely on, their own concepts on which they build on, their own solutions, their own recommendations, their own apprehentions, their own methodology, their own style of talking, their own interests, their own topics on which they pay more emphasis on."*

Style is one signal among many. The schema below treats them all as first-class.

### Inputs to personality capture

Ranked by signal density:

1. **The user's notes** (M5) — annotations, marginalia, "your take" comments. Highest signal because they're explicit user voice, often opinionated.
2. **The user's Q&A questions** — phrasing reveals concerns and emphasis ("why is X always so bad?" vs. "what are the tradeoffs of X?").
3. **Journal entries** — long-form, unfiltered.
4. **Outgoing emails / sent messages** — formal voice.
5. **GitHub commits & PR descriptions** — technical voice.
6. **Outgoing tweets / forum posts** (if connector enabled) — public voice.

Notably **incoming** content (emails received, videos watched) is *not* a voice signal — it's a consumption signal that goes to Domain 2.

### Personality-capture output

Stored in a new table, `voice_signals` (table name kept for back-compat; treats every dimension below as a row):

| column | type | notes |
|--------|------|-------|
| `id` | UUID | |
| `tenant_id` / `user_id` | UUID | |
| `signal_type` | enum | **Style layer:** `vocabulary`, `cadence`, `framing`, `recurring_reference`, `formality_register`, `register_per_audience`. **Personality layer:** `trusted_conclusion`, `preferred_solution`, `recommendation_lens`, `apprehension`, `methodology`, `topic_emphasis`, `perception_lens`, `interest`. |
| `value` | text | the signal — a phrase, a regex of cadence, a stance, a methodology step |
| `weight` | float | how often / strongly this appears |
| `examples` | JSON | up to 5 verbatim quotes / shares / Q&As where this signal was learned |
| `audience` | text | nullable; some signals are audience-specific (formal email vs. forum post) |
| `language` | text | nullable; signal scoped to a language (the user's English voice ≠ their Hindi voice) |
| `derived_from_share_id` | UUID | nullable; backlink into Domain 5 if this signal came from a constant-stream share |

Personality capture has two complementary modes — both are inspectable, editable, exportable, and revocable; neither happens without the user's awareness:

**Mode A — Prompt-time retrieval (default).** Personality signals are retrieved at generation time and fed into the prompt of the "speak as me" agent / Echo. This is what we do first; it requires no training, ships fastest, and is the only mode in early Echo readiness states.

**Mode B — Fine-tuned per-user model (opt-in, post-readiness).** Once the readiness threshold is crossed and the corpus is large enough to be worth it, the user can opt in to fine-tuning a small per-user model on curated dataset themes derived from their personality signals (problem-solution, recommendation lens, situational priority, opinion-formation, methodology). The fine-tuned model becomes the answer LLM for Echo; prompt-time retrieval still augments it with fresh context. See open question 1 for the cost/benefit analysis.

Across both modes:

- Personality signals are **inspectable**. The user can see exactly which phrases / framings / conclusions / methodologies the system thinks define them.
- Personality signals are **editable**. The user can remove a signal that's wrong ("I don't actually say 'circle back' that often" — or "I don't actually trust that conclusion any more").
- Personality signals are **exportable**. The user can take their personality profile elsewhere.
- Personality signals are **revocable**. Wiping the `voice_signals` table erases the model of the user; if Mode B is active, the fine-tuned weights are deleted alongside.

---

## Domain 4 — The "Speak as me" agent

A LangGraph agent that takes (a) an input prompt — incoming message, draft to revise, blank template — and (b) optional audience hint, and produces a draft response in the user's voice.

### Pipeline

```
classify_intent → retrieve_relevant_knowledge → retrieve_voice_signals → retrieve_personal_context → draft → self_critique_against_voice → finalize
```

1. **classify_intent.** Is this a reply to a question? A new outreach? A short ack? A long-form post? Different intents pull different voice signals (the user's "ack" voice ≠ their "essay" voice).
2. **retrieve_relevant_knowledge.** Standard RAG over the source library — what does the user *know* that's relevant to this message? Pulls from the same `videoresearchpro_global` collection.
3. **retrieve_voice_signals.** Fetches the user's relevant style and framing signals from `voice_signals`, scoped by audience hint.
4. **retrieve_personal_context.** Pulls relevant `personal_facts` — opinions, current goals, expertise. This is what makes "speak as me" different from "speak generically": the agent knows the user *is* a backend engineer, *does* think LLM agents are oversold, *is* trying to ship SaaS by Q2.
5. **draft.** A long, carefully-prompted call to a strong model with all of the above.
6. **self_critique_against_voice.** A second model call that grades the draft against the voice signals. *"Does this sound like the user? Where does it deviate? Score 0-10 per dimension."* Below threshold → rewrite once.
7. **finalize.** Attach citations (every claim ties back to a source or a personal fact) and a confidence score.

### Output contract

```json
{
  "draft": "...",
  "confidence": 0.78,
  "voice_match_score": 8.2,
  "citations": [
    { "type": "source", "id": "...", "quote": "..." },
    { "type": "personal_fact", "id": "...", "fact": "..." },
    { "type": "past_qa", "id": "...", "summary": "..." }
  ],
  "deviation_notes": "Drafted slightly more formal than your usual register because the recipient is unknown."
}
```

The user reads the draft, the citations, and the deviation notes. They edit, accept, or discard. If they edit, the diff feeds back as a new voice signal.

### What "Speak as me" never does

- **Send.** Drafts only. Sending is always manual, always one click after review.
- **Speak in voice modes the user hasn't authorized.** Drafting a reply in casual register requires the user has previously approved at least one casual draft.
- **Cite things the user hasn't ingested.** No "general world knowledge" claims. Every factual claim ties to a source the user has chosen to listen to.
- **Speak about other people in their absence.** If a draft would name a non-public person, the agent flags it: *"This draft references your colleague Alice. I'm willing to draft this only with your explicit go-ahead."*

---

## Domain 5 — Constant-stream intake (push-mode sharing)

Domain 2 (activity stream) is **pull-mode**: connectors authenticate to external systems and pull events on a schedule. Domain 5 is **push-mode**: the user actively forwards content to Pratidhvani, item-by-item, throughout the day, with as little friction as possible.

The user's framing on 2026-04-24 (verbatim in [`notes/2026-04-24-echo-feature-vision.md`](notes/2026-04-24-echo-feature-vision.md)):

> *"the user can constantly share their liked videos, reels, memes, whattsapp conversations, their posts, their google keep notes, the quotes they like and other such stuff."*

Constant-stream intake is what Echo's readiness threshold leans on most heavily — these shares are signal-rich, intentional, and reveal the user's *active interest* (vs the activity stream's *passive consumption*).

### Intake surfaces

| Surface | Platform | Friction model |
|---------|----------|----------------|
| **OS share target** | iOS / Android share sheet | One tap from any app: select Pratidhvani as a share destination. Item lands in inbox. |
| **Browser extension** | Chrome / Firefox | Right-click any URL / selection / image → "Share to Pratidhvani". Captures URL + extracted text + screenshot. |
| **Email-in inbox** | dedicated address per user | Forward emails / WhatsApp web messages / quotes to `<user-slug>@in.pratidhvani.app` (SaaS) or local IMAP poller (self-host). |
| **Drag-and-drop dropzone** | web app, every page | Drag a file / image / clip / link onto the floating Echo bubble. Inbox capture. |
| **Manual quick-share** | web app sidebar | "Add to Echo" button always visible: paste a URL / quote / note / clip. |

All surfaces drop into the same `shares_inbox` table. The user can review the inbox periodically (or it auto-flushes after 24h with default categorisation).

### Intake content types

Per the user's explicit list, plus the natural extensions:

- **Liked videos** (YouTube / TikTok / Instagram Reels / Twitter video / Vimeo)
- **Reels & short clips** (Instagram / TikTok / YouTube Shorts)
- **Memes & images** (with OCR extraction; the meme's text is signal-bearing)
- **WhatsApp conversations** (single message or thread; user-redacted before share)
- **The user's own posts** (their tweets, their LinkedIn posts, their forum posts)
- **Google Keep / Apple Notes / Notion notes** (text exported via share sheet)
- **Quotes the user likes** (book passages, podcast quotes, article pull-quotes)
- **Bookmarks** (URL only, lightest intake; useful as interest signal)
- **Voice memos** (transcribed; the user thinking out loud is high-signal)

The list is open-ended. The intake schema does not enforce a fixed content-type taxonomy; it stores `(content_type, raw_payload, extracted_text, source_metadata)` and lets downstream processing (Domain 1 fact derivation, Domain 3 signal extraction) decide what to do with each share.

### Schema sketch

A new table, `shares_inbox`:

| column | type | notes |
|--------|------|-------|
| `id` | UUID | PK |
| `tenant_id` / `user_id` | UUID | per [saas-roadmap](saas-roadmap.md) invariant |
| `received_at` | timestamp | when the share landed in the inbox |
| `surface` | enum | `os_share`, `browser_ext`, `email_in`, `drag_drop`, `manual_quick_share` |
| `content_type` | string | open-ended, e.g. `youtube_video`, `instagram_reel`, `meme_image`, `whatsapp_thread`, `keep_note`, `book_quote`, `voice_memo` |
| `raw_payload` | JSON or blob | URL / image bytes / message text / OCR result |
| `extracted_text` | text | normalised text content for embedding & signal extraction |
| `user_annotation` | text | nullable; what the user said when they shared it ("this is exactly how I think about X") |
| `processing_state` | enum | `pending`, `processed`, `skipped`, `failed` |
| `derived_fact_ids` | JSON array | populated by Domain 1 derivation |
| `derived_signal_ids` | JSON array | populated by Domain 3 derivation |
| `linked_source_id` | UUID | nullable; if the share resolves to an ingestable source (a YouTube video, a podcast episode), it is also added to the user's source library via the standard ingest pipeline |
| `embedding_id` | string | nullable; for semantic retrieval over shares |

A new Chroma collection (`shares_global`) embeds shares with meaningful text. Shares with `linked_source_id` set are *also* embedded in the regular source-library collection so they participate in normal Q&A retrieval.

### Friction model: zero approval, not zero trust

Source ingestion (Ring 1 / Ring 2) preserves the user's curation surface — explicit approval before anything enters the library. Constant-stream intake is the **opposite**: the user has *already* curated by the act of sharing. Approval would be a friction-killer at this scale.

But "no approval" does not mean "no review". The shares inbox is browsable and editable: the user can re-categorise, annotate, or delete any share. Personality signals derived from a share carry a back-link to it (`derived_from_share_id`), so removing a share also tombstones its derived signals.

### Cross-domain wiring

Constant-stream intake is the **richest single feeder** of the other domains:

- A shared quote is a candidate **personal fact** (Domain 1, `confidence ≈ 0.6` until user-confirmed).
- A shared meme's text is a candidate **personality signal** of type `framing` or `apprehension` (Domain 3).
- A shared YouTube video is also added to the **source library** (Ring 1 / 2 ingestion), if the user wants depth on it later.
- The act of sharing is itself an **activity event** (Domain 2, `event_type=shared_to_pratidhvani`, `connector=internal`).

This cross-wiring is what gives Echo its substance: a single share simultaneously contributes facts, signals, and source content, all citable back to "you shared this on YYYY-MM-DD".

### Privacy carry-over

Everything in the privacy model below applies to constant-stream intake too. Most importantly:

- **Other people's content.** A WhatsApp thread the user shares often contains another person's words. Treat per the Domain 2 rule: ingest for the user's personal index but never cross-tenant, never bulk-share, and offer a one-click "redact other party" before final storage.
- **OCR'd faces / images.** Default to *no* face detection / identification; OCR text only.
- **Voice memos.** Transcribed locally where possible (self-host Whisper); SaaS routes through the standard transcription pipeline with the same retention rules.

---

## Privacy model

The single hardest constraint in this entire roadmap. Every choice below is durable and cannot be relaxed without a major-version bump.

### Self-host (today and forever)

- **Local data, period.** The activity stream, personal facts, voice signals, and connector OAuth tokens never leave the user's machine.
- **No telemetry on personal-brain features.** General app telemetry stays opt-in and never sees personal-brain content.
- **Local LLM is supported.** Per-use-case LLM config already supports `provider=local`. A user can run the entire brain off a local model with zero outbound LLM calls.

### SaaS (future)

Per [saas-roadmap](saas-roadmap.md):

- **Zero-knowledge mode.** A SaaS tier where personal-brain content is encrypted client-side with a key the user holds, and the server stores only ciphertext. We *cannot* retrieve content for the user without their key. This is offered as an explicit tier — not the default — because it disables some server-side conveniences (cross-device sync of derived voice signals, server-side scheduled "speak as me" runs).
- **Standard mode** still encrypts at rest with our keys, but server-side processing has access. This is the default because it allows server-side activity-stream ingestion and async voice-signal computation. Users opting into Personal Brain *must* explicitly choose between standard and zero-knowledge.
- **Per-connector consent.** Connector enable is granular: enabling the calendar connector does not enable email. Each connector ships with a one-screen "what we ingest, what we do not" disclosure that is part of the activation flow.
- **Revocability.** Disabling a connector deletes its events from the activity stream within 24 hours and marks any derived voice signals or personal facts for re-derivation.
- **Export and full delete.** Per the [saas-roadmap](saas-roadmap.md) tenancy invariants, the user can export the entire personal brain (sources + activity + voice + facts) as a portable archive at any time, and can delete the entire brain (which cascades to all derived data) within 30 days of request.

### Sharing (a hard line)

By default, **personal-brain content is never shared between users, ever**, regardless of tenant. Even within a multi-user tenant (a workspace), each user's brain is private to them.

Exceptions are explicit, signed-URL, and revocable:

- **Voice-export-for-collaboration.** A user can grant another user (within or outside the tenant) read-only access to a *snapshot* of their voice signals, scoped to a single conversation. The snapshot expires.
- **Quote-for-quote.** When a user pulls a quote from their personal brain into a public artifact (book, post, deck, reel), the quote and citation become public. The rest of the brain stays private.

We never bulk-share personal-brain content for any feature.

---

## Connector interface contract

Every Domain 2 connector lives at `backend/app/connectors/<name>/` and exports a single class implementing:

```python
class ActivityConnector:
    name: str                          # "youtube_history", "spotify_history", ...
    privacy_weight: Literal["low", "medium", "high", "very_high"]
    consent_disclosure: str            # the one-screen text shown at activation

    def authenticate(self, user_id: UUID) -> AuthState: ...
    def revoke(self, user_id: UUID) -> None: ...

    def initial_backfill(self, user_id: UUID) -> Iterator[ActivityEvent]: ...
    def incremental_sync(self, user_id: UUID, since: datetime) -> Iterator[ActivityEvent]: ...

    def event_types(self) -> list[str]: ...
    def schema_for_event_type(self, event_type: str) -> dict: ...
```

Conformance to this interface is the *only* way new connectors enter the system. PR-time review of any new connector specifically checks:

- The consent disclosure is human-readable, not legalese.
- `revoke()` actually deletes data, not just stops sync.
- `incremental_sync()` is idempotent (we'll re-run it on transient failure).
- The privacy_weight is honest. *Email is not "medium."*

---

## What this means for today's PRs

Even though Personal Brain is years out, today's choices matter. Specifically:

1. **Every new user-scoped table gets `tenant_id` AND `user_id`** — not just `tenant_id`. Personal-brain data is per-user even within a tenant; tables that conflate this will need migrations later. (See the [saas-roadmap](saas-roadmap.md) invariants — Personal Brain extends them.)
2. **The `documents` table (post-L1) gets a `user_provenance` JSON column placeholder** so we can later record "the user found this via Spotify history" without a schema migration.
3. **Connector code never lives in `app/services/`.** Even today, when we add YouTube ingestion features, we resist the temptation to colocate "fetch user's watch history" with "fetch a video's transcript." Watch history is a connector; transcripts are a service. Keep them apart.
4. **Voice/style hints in user-facing copy stay generic.** Don't write "your library" assuming a single user — write it in a way that survives multi-user tenants.
5. **`anthropic-skills` and similar provider-specific surfaces** (used today for PPTX generation in [feature-roadmap](feature-roadmap.md) L2) must not absorb personal-brain content into their cloud-side processing in zero-knowledge mode. Audit the skill's data flow before wiring it to brain content.

---

## Open questions (long-horizon, no rush)

These are not blocking. Listed so they don't get lost.

1. **Personality capture: prompt-time retrieval vs. fine-tuning.** Per Domain 3, both modes are now in-scope. Mode A (retrieval) ships first and is the only Echo path until the readiness threshold is crossed. Mode B (per-user fine-tuning, on curated dataset themes — problem-solution, recommendation lens, situational priority, opinion-formation, methodology) becomes available post-threshold and is opt-in. Open sub-questions: which themes have the highest leverage? What is the minimum corpus size per theme to avoid overfitting? Is it a single fine-tuned model per user, or one per theme + a dispatcher? How does the fine-tuned model handle the user's evolution over time (re-train on a rolling window vs additive LoRA)? For SaaS: cost model — pay per fine-tune, dedicated tier, or SaaS-supplied hosted small models the user customises? The 2026-04-24 user framing leans toward "yes, fine-tune, with curated dataset themes and an agentic harness" — see [`notes/2026-04-24-echo-feature-vision.md`](notes/2026-04-24-echo-feature-vision.md).
2. **Conflict resolution between facts.** *"I think LLM agents are oversold"* (2026-04) vs. *"I think LLM agents are the future"* (2027-09). Both true at their time. Surface both with dates? Always prefer recent? User-pinned?
3. **Anticipation UX.** Where in the UI does anticipation surface? A passive sidebar? A daily digest? A pull-only command palette? Probably all three, but design needs validation.
4. **"Speak as me" abuse.** Even with manual sending, the agent could be used to autogenerate convincing-sounding-but-wrong messages at scale. Rate limits and a "drafts per day" cap matter even in self-host.
5. **Inheritance.** When the user dies, what happens to the brain? The export-everything contract gives a clean answer (designate a literary executor, give them the export key) but it's worth being explicit in product copy.
6. **Multi-language voice.** The user's English voice and Hindi voice are different people, stylistically. Voice signals need a language dimension. (This is moot today — voice capture isn't building yet — but the schema should reserve room.)

---

## Cross-references

- [vision.md](vision.md) — Ring 3 framing, three-circle model
- [feature-roadmap.md](feature-roadmap.md) — L3 status, sequencing, M5 (Notes)
- [saas-roadmap.md](saas-roadmap.md) — tenancy invariants, zero-knowledge tier
- [source-types.md](source-types.md) — source-type abstraction Personal Brain extends
- [branding.md](branding.md) — voice and copy conventions
- [architecture.md](architecture.md) — current data model the brain extends
