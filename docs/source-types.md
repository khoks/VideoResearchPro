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

Three tables carry the video library:

- **`videos`** — global, deduplicated, primary key is YouTube `video_id`. Carries title, channel reference, thumbnail, duration, published date, description, transcript state, RAG state, and (since Unit 4) extracted knowledge artifacts.
- **`channels`** — subscribed YouTube channels with `last_synced_at`.
- **`transcript_cache`** — keyed by `video_id`, stores the raw segmented transcript so we never re-fetch.
- **`job_videos`** — many-to-many between `jobs` and `videos`.

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

### Backwards-compat: the `videos` view

Old code reads `videos`. New code reads `documents WHERE source_type='video'`. We bridge the two by:

1. Renaming the existing `videos` table to `documents` in a migration.
2. Adding the new columns with defaults inferred from existing data (`source_type='video'`, `source_id=video_id`, `source_url=url`, etc.).
3. Creating a SQL `VIEW videos AS SELECT video_id, title, ... FROM documents WHERE source_type='video'` so legacy reads continue to work during the rollover.
4. Migrating call sites batch by batch over a single sprint, then dropping the view.

The legacy `video_id`-as-primary-key gives way to the new UUID `id`. The `transcript_cache` table is renamed `text_cache` and re-keyed on `(source_type, source_id)`.

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
| `tweet` | Twitter/X API (single tweet or thread URL) | thread unrolling | `unrolled` | thread position per chunk |
| `forum_post` | Reddit API / HN Algolia / Discourse API | top-level post + top N comments | `forum_extract` | comment depth per chunk |
| `pdf` | (no search; user uploads) | pdfplumber + table extraction | `pdf_extract` | `page_number` per chunk |
| `book` | (no search; user uploads EPUB/PDF) | calibre-style extraction | `pdf_extract` or `epub_extract` | `page_number` + chapter per chunk |
| `note` | (no search; user-authored in app) | direct text save | `manual` | none |

`note` is the user's own annotations (medium feature M5). Treating notes as a source type means they appear in retrieval, get cited like any other source, and inherit the same approval/curation surface.

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

1. **Schema migration** — add `documents` (rename `videos`), add `creators` (rename `channels`), add new columns with defaults. Create the `videos` view for back-compat. Backfill `source_type='video'` for all existing rows.
2. **Service layer** — introduce `app/services/document_service.py` with the same shape as today's `video_service.py`. The video service keeps its name temporarily and delegates to document_service.
3. **Connector module** — create `app/sources/types.py` with the dataclasses, and `app/sources/video/` containing today's YouTube logic, conforming to `SourceConnector`. The job orchestrator switches from direct YouTube calls to `connector_for(source_type).fetch_text(candidate)`.
4. **First new connector** — ship `app/sources/article/` (URL → trafilatura → text). Smallest possible connector. Validates the abstraction.
5. **Frontend tabs** — add "URL list" tab to the submit-research form. Approval list grows a source-type icon column.
6. **Drop the `videos` view** once all reads have migrated.
7. **Subsequent connectors** — `pdf`, then `podcast`, then `tweet`, then `forum_post`. Each is its own PR.

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

The internal codename is `documents`. The user-facing word is *"sources"* in some contexts and *"volumes"* in others — see [branding.md](branding.md) §voice. We never expose `documents` or `source_type` strings in user-facing copy. The user sees "Article", "Podcast episode", "Video", "Thread", "PDF", "Note" — capitalized, English, friendly.

The internal codename for the join is still `job_videos` until we rename it to `job_documents` in the same migration. (The schema migration covers it.) The `Job` model gains a `document_count` accessor that just delegates.

---

## Cross-references

- [feature-roadmap.md](feature-roadmap.md) — L1 status, sequencing
- [vision.md](vision.md) — Ring 2 framing
- [architecture.md](architecture.md) — current data flow this generalizes
- [saas-roadmap.md](saas-roadmap.md) — tenancy invariants every new column respects
- [personal-brain.md](personal-brain.md) — `user_provenance` column motivation
