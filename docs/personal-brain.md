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

## What we add to the existing library

The current library has:

- **Sources** — videos, podcasts, articles, threads, PDFs (per [source-types](source-types.md)).
- **Knowledge artifacts** — extracted `{topics, concepts, events, facts}` per source.
- **Q&A history** — every question, answer, citation, and follow-up the user has run.
- **Notes** — user-authored annotations attached to sources, channels, exchanges (medium feature M5).

Personal Brain layers two new domains on top:

- **Personal context** — who the user is, distinct from what they consume.
- **Activity stream** — what the user does, distinct from what they consume.

Both are **first-class library content**: searchable, citable, embedded into the same retrieval surface, subject to the same approval/curation flow.

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

## Domain 3 — Voice capture

Goal: a model of the user's *style* (lexical, syntactic, rhetorical) and *recurring positions* (opinions, framings, references they reach for). Used by the "speak as me" agent.

### Inputs to voice capture

Ranked by signal density:

1. **The user's notes** (M5) — annotations, marginalia, "your take" comments. Highest signal because they're explicit user voice, often opinionated.
2. **The user's Q&A questions** — phrasing reveals concerns and emphasis ("why is X always so bad?" vs. "what are the tradeoffs of X?").
3. **Journal entries** — long-form, unfiltered.
4. **Outgoing emails / sent messages** — formal voice.
5. **GitHub commits & PR descriptions** — technical voice.
6. **Outgoing tweets / forum posts** (if connector enabled) — public voice.

Notably **incoming** content (emails received, videos watched) is *not* a voice signal — it's a consumption signal that goes to Domain 2.

### Voice-capture output

Stored in a new table, `voice_signals`:

| column | type | notes |
|--------|------|-------|
| `id` | UUID | |
| `tenant_id` / `user_id` | UUID | |
| `signal_type` | enum | `vocabulary`, `cadence`, `framing`, `recurring_reference`, `formality_register`, `register_per_audience` |
| `value` | text | the signal — a phrase, a regex of cadence, a concept |
| `weight` | float | how often / strongly this appears |
| `examples` | JSON | up to 5 verbatim quotes where this signal was learned |
| `audience` | text | nullable; some signals are audience-specific (formal email vs. forum post) |

Voice capture is **never autonomous training**. We don't fine-tune a model on the user's writing. We retrieve voice signals at generation time and feed them into the prompt of the "speak as me" agent. This means:

- Voice signals are inspectable. The user can see exactly which 50 phrases / framings / references the system thinks define them.
- Voice signals are editable. The user can remove a signal that's wrong ("I don't actually say 'circle back' that often").
- Voice signals are exportable. The user can take their voice profile elsewhere.
- Voice signals are revocable. Wiping the `voice_signals` table erases the model of the user.

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

1. **Voice capture vs. fine-tuning.** Today's design uses prompt-time retrieval of voice signals. At what scale of personal corpus does fine-tuning a small per-user model become worthwhile? Probably never for SaaS (cost prohibitive); maybe yes for self-host (the user pays the GPU).
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
