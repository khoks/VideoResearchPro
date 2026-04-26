---
name: source-types
description: The multi-source ingest abstraction — videos today, podcasts/articles/threads/PDFs next
type: project
---

# Source-type abstraction

**Status:** design (2026-04-24). Today only `video` exists. This doc is the contract for adding `podcast`, `article`, `tweet`, `forum_post`, `pdf`, and future source types under L1 of the [feature-roadmap](feature-roadmap.md).

The user-facing claim of [vision](vision.md) Ring 2 is that **the curation flow is the product**: search → approve → ingest → embed → query. New source types must plug into that flow without adding a new flow. This doc is what guarantees that.

---

## Today's data model (video-only)

Three tables carry the document library:

- **`documents`** — global, deduplicated, primary key is the platform-native ID (today: YouTube `video_id`; the column is still named `video_id` until a future PR promotes it to a UUID). Carries title, creator/channel reference, thumbnail, duration, published date, description, transcript state, RAG state, and (since Unit 4) extracted knowledge artifacts. The Python ORM class is `Document` (`app.models.document`); `source_type` defaults to `'video'` for every existing row and is the discriminator the connector layer dispatches on.
- **`channels`** — subscribed YouTube channels with `last_synced_at`. (Generalizes to `creators` in a later PR.)
- **`transcript_cache`** — keyed by `video_id`, stores the raw segmented transcript so we never re-fetch. (Renamed to `text_cache` and re-keyed on `(source_type, source_id)` in a later PR.)
- **`job_videos`** — many-to-many between `jobs` and `documents`. (Renamed to `job_documents` alongside the `video_id` → `document_id` PK promotion.)

A single ChromaDB collection (`videoresearchpro_global`) holds chunked transcripts, with metadata `{video_id, job_id, chunk_index, start_time, end_time, channel_id}` per chunk. Per-job Q&A filters by `video_id ∈ approved_set` at query time.

This works because every "thing" in the library is a YouTube video. The L1 problem is that this stops working the moment the user wants to ingest a podcast episode that isn't on YouTube, or a long-form essay, or a PDF book.

---

## Target data model (multi-source)

### The `documents` table

`videos` is generalized into `documents`. The new schema:

| column | type | notes |
|--------|------|-------|
| `id` | UUID | primary key — no longer the platform-native ID |
| `tenant_id` | UUID | per [saas-roadmap](saas-roadmap.md) invariant |
| `source_type` | enum | `video`, `podcast`, `article`, `tweet`, `forum_post`, `pdf`, `book`, `note` |
| `source_id` | string | the platform-native ID — YouTube `video_id`, Spotify `episode_id`, URL hash for articles, file hash for PDFs |
| `source_url` | string | canonical URL or `file://` path |
| `source_metadata` | JSON | per-source-type structured data (see below) |
| `creator_id` | UUID | nullable; foreign key to `creators` (the new generalized `channels`) |
| `title` | string | |
| `published_at` | timestamp | nullable |
| `description` | text | nullable |
| `language` | string | nullable; ISO 639-1 |
| `duration_seconds` | int | nullable; meaningful for video/podcast, NULL for article/PDF |
| `word_count` | int | nullable; meaningful for text-based, also computed from transcript for video/podcast |
| `text_status` | string | `pending`, `extracted`, `failed`, `unavailable` (replaces `transcript_status`) |
| `text_source` | string | `youtube`, `whisper`, `spotify_transcript`, `trafilatura`, `pdf_extract`, `manual` |
| `embedded_in_chroma` | bool | |
| `extracted_knowledge_json` | text | nullable — same as today |
| `knowledge_report_md` | text | nullable — same as today |
| `knowledge_extracted_at` | timestamp | nullable — same as today |
| `user_provenance` | JSON | nullable — placeholder for [personal-brain](personal-brain.md) (e.g. "found via Spotify history") |
| `created_at` / `updated_at` | timestamp | |

A unique constraint on `(tenant_id, source_type, source_id)` deduplicates within a tenant.

### Migration shape (what landed in PR 1 / PR 4 vs. what's still ahead)

The renames happen in stages so each PR stays small and reversible:

1. **PR 1 — additive columns.** Added `source_type` / `source_id` / `source_url` / `source_metadata_json` / `language` / `word_count` / `user_provenance_json` to the existing `videos` table. Backfilled `source_type='video'` and `source_id=video_id` for every row. No renames; legacy ingest call sites kept working untouched via `__init__` defaults on the model. **Shipped.**
2. **PR 4 — `videos` → `documents` rename.** Pure rename of the table, the ORM class (`Video` → `Document`), the two indexes (`ix_documents_channel_id`, `ix_documents_source_type_source_id`), and the `job_videos.video_id` FK target. The PK column is intentionally still named `video_id` so this PR doesn't have to cascade into `job_videos.video_id` and `transcript_cache.video_id`. **Shipped.**
3. **Future PR — UUID PK.** Promote `documents.video_id` → `documents.id` (UUID); cascade the rename into `job_videos.document_id` (table also renamed `job_documents`) and `text_cache.document_id` (table renamed from `transcript_cache`). At this point the legacy `video_id` column either disappears or becomes a back-compat shadow alias.
4. **Future PR — `channels` → `creators`.** Same shape: rename table and ORM class, re-point `documents.channel_id` → `documents.creator_id`, retire the YouTube-specific column names.

No SQL `VIEW` is needed for back-compat: the `Document` ORM class keeps `__init__` defaults that turn legacy `Video(video_id=..., url=..., channel_id=...)` calls into a fully populated `Document` row, and the column `documents.video_id` still exists, so legacy SQL reads against the (now-renamed) table need only swap `videos` for `documents`.

### The `creators` table (replaces `channels`)

`channels` is YouTube-specific. We generalize:

| column | type | notes |
|--------|------|-------|
| `id` | UUID | |
| `tenant_id` | UUID | |
| `source_type` | enum | same enum as documents |
| `creator_external_id` | string | YouTube channel ID, Spotify show ID, RSS feed URL hash, Twitter handle, blog domain |
| `name` | string | |
| `url` | string | |
| `description` | text | nullable |
| `subscribed` | bool | "is this creator on the user's auto-pull list?" |
| `last_synced_at` | timestamp | nullable |
| `source_weight` | float | default 1.0; per [feature-roadmap](feature-roadmap.md) L4 |
| `metadata` | JSON | per-source-type extras |

Migration: existing `channels` rows become `creators` rows with `source_type='video'`. The `videos.channel_id` foreign key becomes `documents.creator_id`.

### The Chroma collection

Stays a single collection per tenant. The collection name is unchanged for back-compat (`videoresearchpro_global`, env-overridable as today). Chunk metadata grows new fields:

```
{
  "document_id": "<uuid>",
  "source_type": "video|podcast|article|...",
  "source_id": "<platform-native id>",
  "creator_id": "<uuid or null>",
  "tenant_id": "<uuid>",
  "chunk_index": 12,
  "start_time": 145.3,        # seconds, for time-based sources
  "end_time": 167.8,
  "page_number": null,        # for PDFs
  "section_anchor": null      # for articles, the heading anchor
}
```

Per-job Q&A filters by `document_id ∈ approved_set`. Library-wide Q&A queries unfiltered. Per-source-type filtered Q&A becomes trivial: filter by `source_type`.

---

## The connector contract

Every source type ships as a connector module under `backend/app/sources/<source_type>/`. The connector implements a single class:

```python
class SourceConnector:
    source_type: Literal["video", "podcast", "article", "tweet", "forum_post", "pdf"]

    # Discovery (search-phase) — returns candidates the user will approve
    def search(self, query: str, instructions: str, limit: int) -> list[Candidate]: ...

    # Per-creator listing — used by channel/subscription jobs
    def list_creator_items(self, creator_external_id: str, since: datetime | None) -> Iterator[Candidate]: ...

    # Single-item ingestion — the user approved this candidate, fetch its text
    def fetch_text(self, candidate: Candidate) -> ExtractedText: ...

    # Metadata enrichment — title, duration, published_at, etc.
    def fetch_metadata(self, candidate: Candidate) -> SourceMetadata: ...

    # Optional: creator metadata for the `creators` table
    def fetch_creator(self, creator_external_id: str) -> CreatorMetadata: ...
```

Where `Candidate`, `ExtractedText`, `SourceMetadata`, `CreatorMetadata` are typed dataclasses defined in `app/sources/types.py`.

**No connector touches the database directly.** The job orchestrator (Celery task in `app/tasks/job_tasks.py`) calls the connector for text extraction, then calls `app/services/document_service.py` to persist. This keeps connectors stateless and testable.

### Per-source-type implementations (sketch)

| source_type | search | fetch_text | text_source | timestamp granularity |
|-------------|--------|------------|-------------|------------------------|
| `video` | YouTube Data API v3 | `youtube-transcript-api`, fallback to Whisper-via-yt-dlp | `youtube` or `whisper` | `start_time` / `end_time` per chunk |
| `podcast` | Listen Notes / Spotify search / Apple Podcasts | RSS enclosure → Whisper if no transcript provided | `whisper` or `rss_transcript` | `start_time` / `end_time` per chunk |
| `article` | Google CSE / Brave Search / direct URL list | trafilatura / readability-py | `trafilatura` | `section_anchor` per chunk |
| `tweet` | Twitter/X API v2 (paid, BYOK — see [D-009](decisions.md#d-009--twitter--x-is-byok--opt-in-2026-04-25)); Mode B paste fallback | thread unrolling + top-K replies | `twitter_api` or `paste_extract` | reply position per chunk |
| `reddit_post` | `/search.json` + per-sub fallback (free, OAuth-app + 100 req/min) | OP + top-50 comments by score | `reddit_api` | reply depth per chunk |
| `hn_story` | Algolia HN search (free, no auth) | story + comment tree | `hn_algolia` | reply depth per chunk |
| `mastodon_post` | ActivityPub instance search | thread + replies | `activitypub` | reply depth per chunk |
| `bluesky_post` | AT-Proto search (app password) | thread + replies | `at_proto` | reply depth per chunk |
| `fb_post` / `ig_post` / `li_post` | ❌ no public-search API (see [D-008](decisions.md#d-008--no-scraping-of-search-result-pages-on-fb--ig--linkedin-2026-04-25)) — Mode B paste only | public fetch (trafilatura → Playwright); user-OAuth fallback per [D-013](decisions.md#d-013--personal-account-oauth-as-fallback-for-mode-b-paste-2026-04-25) | `paste_extract_public` or `paste_extract_user_auth` | reply position per chunk (when extractable) |
| `discord_message` | ❌ no global search (Mode A deferred per [D-010](decisions.md#d-010--defer-tiktok-and-per-server-discord-bot-indefinitely-2026-04-25)) — Mode B paste only | user-OAuth required (Discord messages are gated); public fetch always fails | `paste_extract_user_auth` | message position in channel |
| `tiktok_video` | ❌ Research API US-academic-gated; Display API has no search (Mode A deferred per [D-010](decisions.md#d-010--defer-tiktok-and-per-server-discord-bot-indefinitely-2026-04-25)) — Mode B paste only | public fetch first; user-OAuth fallback per [D-013](decisions.md#d-013--personal-account-oauth-as-fallback-for-mode-b-paste-2026-04-25); transcript via Whisper from video stream | `paste_extract_public`, `paste_extract_user_auth`, or `whisper` | `start_time` / `end_time` per chunk |
| `forum_post` | Reddit API / HN Algolia / Discourse API (umbrella for non-platform-specific forums) | top-level post + top N comments | `forum_extract` | comment depth per chunk |
| `pdf` | (no search; user uploads) | pdfplumber + table extraction | `pdf_extract` | `page_number` per chunk |
| `book` | (no search; user uploads EPUB/PDF) | calibre-style extraction | `pdf_extract` or `epub_extract` | `page_number` + chapter per chunk |
| `note` | (no search; user-authored in app) | direct text save | `manual` | none |

`note` is the user's own annotations (medium feature M5). Treating notes as a source type means they appear in retrieval, get cited like any other source, and inherit the same approval/curation surface.

---

## Social-media post specifics

Social-media post connectors (Reddit, HN, Mastodon, Bluesky, Twitter, plus paste-only FB/IG/LinkedIn) all conform to `BaseConnector` but share a few constraints unique to discussion-shaped content. Captured here so each connector's implementation stays consistent.

### Two ingestion modes

The choice is forced by per-platform API reality, not by design preference.

- **Mode A — Discovery (search).** Available on **Reddit, HN, Mastodon, Bluesky** (free APIs) and **Twitter/X** (paid API, BYOK per [D-009](decisions.md#d-009--twitter--x-is-byok--opt-in-2026-04-25)). The connector implements `search()` with topic + optional date range, returns candidate threads, user approves, ingest proceeds.
- **Mode B — Direct paste.** The only honest option for **Facebook, Instagram, LinkedIn, Discord, TikTok, X-without-paid-API** (see [D-008](decisions.md#d-008--no-scraping-of-search-result-pages-on-fb--ig--linkedin-2026-04-25), [D-010](decisions.md#d-010--defer-tiktok-and-per-server-discord-bot-indefinitely-2026-04-25)). The user pastes 1–N post URLs; the connector fetches each via a **two-step strategy** (per [D-013](decisions.md#d-013--personal-account-oauth-as-fallback-for-mode-b-paste-2026-04-25)). No `search()` exposed; the UI clearly labels these platforms as paste-only.

The submit-research form supports both modes per platform; the UI hides Mode A controls for platforms where it isn't available.

#### Mode B fetch strategy (public → user-auth fallback)

Per [D-013](decisions.md#d-013--personal-account-oauth-as-fallback-for-mode-b-paste-2026-04-25), every Mode B connector dispatches its `fetch_text` in two steps:

1. **Public anonymous fetch** — trafilatura → Playwright fallback against the pasted URL. Records `text_source='paste_extract_public'` on success.
2. **User-auth fallback** — only if step 1 returns gated content (login wall, content stripped, HTTP 401/403). Re-fetches the same URL using a per-user OAuth token stored under the **Connected Accounts** settings surface. Records `text_source='paste_extract_user_auth'`. Skipped silently when the user has not connected that platform.

```
candidate URL
   │
   ├─► public anonymous fetch (trafilatura / Playwright)
   │       │
   │       ├─► success → text + source='paste_extract_public'
   │       └─► gated/login-wall ↓
   │
   └─► user-OAuth fetch (per-user, per-platform token)
           │
           ├─► token absent → fail soft, surface "connect account?" prompt
           └─► success      → text + source='paste_extract_user_auth'
```

Tokens are held in a `user_platform_tokens` table (`user_id, platform, access_token_encrypted, refresh_token_encrypted, scope, expires_at`). In self-host they never leave the device. SaaS extends with per-tenant key rotation per [saas-roadmap.md](saas-roadmap.md).

This same pattern unblocks **TikTok** (paste a video URL → fetch via user's logged-in TikTok session) and **Discord** (paste a message URL → fetch via user's Discord session) from D-010's broad defer for Mode B only. **Mode A search remains deferred on those platforms.**

### One `Document` per thread (not per comment)

Per [D-006](decisions.md#d-006--one-document-row-per-social-post-thread-not-per-comment-2026-04-25). A social-media post **and its reply tree** is stored as a single `Document` row, with the comment tree flattened into the document text. Comment-level metadata (id, author, score, sentiment) lives in `source_metadata.comments[]`.

```jsonc
// source_metadata for a reddit_post Document
{
  "platform": "reddit",
  "subreddit": "r/economics",
  "score": 1342,
  "permalink": "https://reddit.com/r/economics/comments/abc123/...",
  "comments": [
    { "id": "def456", "author": "u/example", "score": 87,
      "depth": 0, "sentiment": {"stance": "against", "score": 0.82} },
    ...
  ],
  "stance": "neutral",
  "sentiment": {"label": "mixed", "score": 0.6},
  "topic_relevance": 0.91
}
```

The flattened text body uses explicit reply markers preserved through chunking so citations can name the specific reply:

```
<OP body text>

[--- reply by @u/example (score 87) ---]
<reply body>

[--- reply by @u/another (score 42, depth 1) ---]
<nested reply body>
```

Chunk metadata grows two new fields when chunks span replies:

```jsonc
{
  ...
  "thread_position": "op" | "reply:<id>" | "reply:<id>/reply:<sub_id>",
  "comment_id": "<id>"  // when the chunk is entirely within a reply
}
```

Citations dispatched by `source_type` build deep-links: `permalink#comment-<id>` for Reddit / Mastodon / Bluesky, `tweet_url` for Twitter (replies have their own URL), generic anchor-or-fragment for paste-extracted FB/IG/LI.

### Stance / sentiment classification at fetch time

Per [D-007](decisions.md#d-007--sentiment--stance-classification-at-fetch-time-2026-04-25). Each candidate document (and each comment) is classified at ingest time by the `social_classify_stance` LLM use case (default cheap-and-fast: `provider=openai, model=gpt-4.1-mini, reasoning=off`). Output schema:

```python
class StanceClassification(BaseModel):
    stance: Literal["for", "against", "neutral", "unclear"]
    sentiment: Literal["positive", "negative", "mixed", "neutral"]
    topic_relevance: float  # 0.0 - 1.0
```

Results land in `source_metadata.stance` / `.sentiment` / `.topic_relevance` on the `Document`, and per-comment under `source_metadata.comments[].sentiment`. The approval UI surfaces classification as a **hint** (filter chips, badge color), never as a hard gate that hides candidates — sarcasm and dog-whistle handling is too noisy to autopilot.

### Comment-tree depth

Default: top 50 comments by score. Configurable per-job (open question OQ-2 in [`initiatives.md`](initiatives.md)). Past depth 50 the cost grows fast and the marginal value drops; deeper threads can be re-ingested if a specific deep-thread analysis becomes a feature.

### Approval-UI surface

A social-post candidate card surfaces, beyond the standard video-card fields:

- Author handle + follower / karma proxy
- Post date + platform icon
- First ~200 chars of OP
- Comment count + score / likes / retweets
- **Stance + sentiment badges** (from `social_classify_stance`)
- "View on platform" deep-link

Filter chips ("show only against", "show only positive", "show only ≥100 score") filter the in-memory candidate list. They do not re-fetch or re-classify.

### Platforms with Mode A out of scope today

Per [D-013](decisions.md#d-013--personal-account-oauth-as-fallback-for-mode-b-paste-2026-04-25), Mode B paste-with-user-OAuth is supported for all of these. Only Mode A (search/discovery) remains out of scope.

- **TikTok** — Mode A: Research API is US-academic-gated; Display API has no search. Deferred per [D-010](decisions.md#d-010--defer-tiktok-and-per-server-discord-bot-indefinitely-2026-04-25). Mode B: paste a video URL, app fetches via public path or user-OAuth, transcript via Whisper.
- **Discord** — Mode A: no global search; per-server bot model only. Deferred per [D-010](decisions.md#d-010--defer-tiktok-and-per-server-discord-bot-indefinitely-2026-04-25). Mode B: paste a message link, app fetches via the user's Discord OAuth session.
- **YouTube comments as a standalone connector** — already accessible via the existing video pipeline; not a new source type.

### Sequencing

Per [E-1.5 in `initiatives.md`](initiatives.md#e-15--social-media-connectors): Reddit + HN first, then Mastodon + Bluesky, then Mode B paste mode for FB/IG/LI/X-without-paid (and Discord/TikTok per [D-013](decisions.md#d-013--personal-account-oauth-as-fallback-for-mode-b-paste-2026-04-25)), then BYOK Twitter API. The Connected-Accounts settings surface ships alongside the first paste-with-user-OAuth platform.

---

## The job pipeline (unchanged shape, generalized substance)

Today:

```
search → awaiting_approval → fetch_transcripts → embed → generate_report → completed
```

Future:

```
search → awaiting_approval → fetch_text → embed → generate_report → completed
```

The only change is `fetch_transcripts` becomes `fetch_text`, which dispatches to the connector for the document's source type.

Subscription jobs (channel auto-pull) generalize to **creator subscriptions**: every source type can have subscribed creators (YouTube channel, podcast show, RSS feed, Substack, X account). The subscription job loops across all subscribed creators, lists new items since `last_synced_at`, and fans them out into the same fetch_text → embed pipeline. No approval step (per current design).

---

## What the user sees (the "agency surface stays identical" promise)

1. **Submit research** — a single form. Today it has tabs for "Topic" / "Channels" / "Subscribe". Tomorrow it has tabs for "Topic" / "Creators" / "Subscribe" / "URL list" / "Upload files". The first three behave as today (with the dropdown for "search where" — YouTube, all, podcasts only, articles only). The last two are new but live in the same form.
2. **Approval list** — same UI as today, with a per-row source-type icon and source-type-aware metadata (duration for video/podcast, word count for article, page count for PDF).
3. **Library** — same browse surface. Filter by source type appears as a chip strip ("All / Videos / Podcasts / Articles / Threads / PDFs / Notes").
4. **Q&A** — same chat surface. Citations adapt: timestamp links for video/podcast, anchor links for articles, page links for PDFs, permalinks for tweets/forum posts.
5. **Search instructions** — same free-text "instructions" field. Per-source-type connectors interpret instructions appropriately ("focus on macroeconomic angles" works for any source).
6. **Preferred creators** (today: preferred channels) — generalizes to a per-source-type preference list ("My trusted YouTube channels", "My trusted podcasts", "My trusted Substacks").
7. **AI query instructions** — unchanged.

The user does not have to learn a new flow per source type. They learn the flow once.

---

## Migration plan

A single sprint (2-3 weeks):

1. **Schema migration** — done in three stages:
   - PR 1 (additive columns) — added `source_type`, `source_id`, `source_url`, `source_metadata_json`, `language`, `word_count`, `user_provenance_json` to `videos`; added `source_type`, `creator_external_id`, `source_weight`, `creator_metadata_json` to `channels`. Backfilled `source_type='video'`, `source_id=video_id`, `creator_external_id=channel_id`. **Shipped.**
   - PR 4 (videos → documents rename) — pure rename of the `videos` table and the `Video` ORM class to `documents` / `Document`. Indexes renamed `ix_documents_*`. `job_videos.video_id` FK re-pointed at `documents.video_id`. The PK column kept as `video_id` to avoid cascading FK changes; promoting it to a UUID `id` is the next schema PR. **Shipped.**
   - Future PRs — `channels` → `creators` rename; `transcript_cache` → `text_cache`; `video_id` PK → UUID `id` with cascading `job_videos`/`text_cache` FK updates; drop legacy compat columns once all reads migrate.
2. **Service layer** — introduce `app/services/document_service.py` with the same shape as today's `video_service.py`. The video service keeps its name temporarily and delegates to document_service.
3. **Connector module** — created `app/sources/types.py` with the dataclasses, and `app/sources/video/` containing today's YouTube logic, conforming to `BaseConnector`. The job orchestrator switches from direct YouTube calls to `connector_for(source_type).fetch_text(candidate)`. **Shipped (PR 2/3).**
4. **First new connector** — ship `app/sources/article/` (URL → trafilatura → text). Smallest possible connector. Validates the abstraction.
5. **Frontend tabs** — add "URL list" tab to the submit-research form. Approval list grows a source-type icon column.
6. **Subsequent connectors** — `pdf`, then `podcast`, then `tweet`, then `forum_post`. Each is its own PR.

The user-facing release cadence is one source type per release after the abstraction lands. Each new source type is a deliverable in its own right.

---

## What we don't do (scope discipline)

- **No video hosting.** We don't store the video file. We index its transcript.
- **No podcast hosting.** Same.
- **No article rehosting.** We extract and cite; we link back to the source on every retrieval.
- **No paywalled-content circumvention.** If a connector hits a paywall, it surfaces the error and offers the user a manual-paste path.
- **No mass-scraping from search engines.** Search connectors use official APIs (Google CSE, Brave) or platform APIs (YouTube, Reddit, HN Algolia). We accept that Twitter/X coverage is limited as a result.
- **No automatic translation at ingest.** We preserve original-language text. The Q&A agent translates at answer time per the [vision](vision.md) multilingual posture.

---

## Naming nits

The internal table is `documents` (after PR 4) and the ORM class is `Document` (`app.models.document`). The user-facing word is *"sources"* in some contexts and *"volumes"* in others — see [branding.md](branding.md) §voice. We never expose `documents` or `source_type` strings in user-facing copy. The user sees "Article", "Podcast episode", "Video", "Thread", "PDF", "Note" — capitalized, English, friendly.

The join table is still `job_videos` (with PK column `video_id` on both `documents` and `job_videos.video_id`) until a future PR promotes the PK to a UUID and renames the join to `job_documents`. The `Job.videos` relationship attribute is intentionally kept as-is for back-compat; it now returns `list[Document]` regardless of name.

---

## Cross-references

- [feature-roadmap.md](feature-roadmap.md) — L1 status, sequencing
- [vision.md](vision.md) — Ring 2 framing
- [architecture.md](architecture.md) — current data flow this generalizes
- [saas-roadmap.md](saas-roadmap.md) — tenancy invariants every new column respects
- [personal-brain.md](personal-brain.md) — `user_provenance` column motivation
