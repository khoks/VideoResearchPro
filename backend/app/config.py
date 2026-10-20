from typing import Literal

from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Pratidhvani"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "sqlite:///./data/videoresearchpro.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ChromaDB
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHROMA_GLOBAL_COLLECTION_NAME: str = "pratidhvani_global"
    CHROMA_QA_COLLECTION_NAME: str = "qa_library_global"
    # Echo (I-3) collections. Private per tenant: every query carries a
    # fail-closed tenant filter, and `DELETE /echo/brain` removes the
    # tenant's vectors from each. Created by the processing story
    # (S-3.7.2); erasure already sweeps them if they exist.
    # M5 / S-8.5.2: the user's own notes, one vector per live note, private per
    # tenant (every query carries a fail-closed tenant filter). Separate from
    # the shared transcript collection because notes are private and chunks
    # are shared (D-063).
    CHROMA_NOTES_COLLECTION_NAME: str = "notes_global"
    CHROMA_SHARES_COLLECTION_NAME: str = "shares_global"
    CHROMA_PERSONAL_CONTEXT_COLLECTION_NAME: str = "personal_context_global"

    # YouTube
    YOUTUBE_API_KEY: str = ""
    # E-1.11 (D-051): 0.5s pacing triggered a YouTube IP block after ~60
    # serial transcript fetches in the 200-video test run. 3s + jitter keeps
    # a 200-video job under the observed block threshold.
    YOUTUBE_TRANSCRIPT_RATE_LIMIT: float = 3.0
    YOUTUBE_TRANSCRIPT_RATE_JITTER: float = 0.4  # ± fraction of the base rate
    YOUTUBE_DAILY_QUOTA: int = 10000
    # Paginated broad search (S-1.11.5). Each page costs 100 quota units;
    # 2 pages/query = up to 100 results/query at 200 units.
    YOUTUBE_SEARCH_MAX_PAGES: int = 2

    # Transcript-fetch circuit breaker (S-1.11.1 / D-051). After
    # `THRESHOLD` consecutive IP-block signals the breaker opens for
    # `COOLDOWN_BASE` seconds, doubling per re-trip up to `COOLDOWN_MAX`.
    # While open, a video waits out the remaining cooldown when it is at
    # most `MAX_WAIT` seconds; longer waits fall through to Whisper.
    TRANSCRIPT_BREAKER_THRESHOLD: int = 3
    TRANSCRIPT_BREAKER_COOLDOWN_BASE: float = 120.0
    TRANSCRIPT_BREAKER_COOLDOWN_MAX: float = 900.0
    TRANSCRIPT_BREAKER_MAX_WAIT: float = 300.0

    # IP-block workarounds (S-1.11.10 / D-051 re-evaluation hooks).
    # Proxy for BOTH the transcript API and yt-dlp audio downloads, e.g.
    # "http://user:pass@host:port" or "socks5://host:port". Unset = direct.
    YOUTUBE_PROXY_URL: str = ""
    # yt-dlp cookie sources for YouTube's "confirm you're not a bot" wall.
    # COOKIES_FROM_BROWSER uses the operator's own logged-in browser session
    # (e.g. "chrome", "firefox", "edge", or "chrome:ProfileName") — explicit
    # opt-in ONLY; requests then carry the operator's YouTube account.
    # COOKIES_FILE points at a Netscape-format cookies.txt export instead.
    # FROM_BROWSER wins when both are set.
    YTDLP_COOKIES_FROM_BROWSER: str = ""
    YTDLP_COOKIES_FILE: str = ""
    # Pacing between yt-dlp download attempts (seconds; jitter shared with
    # the transcript limiter). The 60-video recovery sweep issued ~180
    # back-to-back download hits and escalated YouTube's blocking.
    YTDLP_DOWNLOAD_RATE_LIMIT: float = 2.0

    # Whisper fallback controls (S-1.11.2 / S-1.11.7 / D-051).
    # Audio larger than 25 MB is split into ~TARGET_MB chunks with
    # OVERLAP_SECONDS of shared audio between neighbours; per-chunk
    # transcripts are merged with chunk-offset-adjusted timestamps.
    WHISPER_SEGMENT_TARGET_MB: int = 20
    WHISPER_SEGMENT_OVERLAP_SECONDS: float = 15.0
    # Max Whisper transcriptions per job — bounds worst-case OpenAI spend
    # when a block storm makes Whisper the primary path. 0 disables Whisper.
    WHISPER_MAX_PER_JOB: int = 50

    # Reddit (S-1.5.1) — read-only access via script-app OAuth (client_credentials).
    # The token is for the *app*, not the user; suitable for reading public
    # subreddits and posts. User-OAuth (per D-013) is a separate code path
    # that lives in the Connected Accounts surface (S-1.5.13).
    #
    # Register a script-type app at https://www.reddit.com/prefs/apps to obtain
    # CLIENT_ID + CLIENT_SECRET. USER_AGENT must follow Reddit's required format
    # (`<platform>:<app-id>:<version> (by /u/<reddit-username>)`) — Reddit
    # rate-limits requests with bad/empty User-Agent strings aggressively.
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "pratidhvani/0.1 (by u/anonymous)"
    REDDIT_RATE_LIMIT_RPM: int = 100  # 100 req/min on Reddit's free OAuth tier
    REDDIT_COMMENT_DEPTH_DEFAULT: int = 50  # top N comments by score; OQ-2

    # -------------------------------------------------------------------
    # Hacker News connector (Algolia API)
    # -------------------------------------------------------------------
    # HN's Algolia search API is free and unauthenticated:
    #   https://hn.algolia.com/api/v1/search?query=...&tags=story
    #   https://hn.algolia.com/api/v1/items/<item_id>
    # No keys to register; we still send a polite User-Agent so the
    # operator can identify us if Algolia ever decides to throttle.
    HN_USER_AGENT: str = "pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani)"
    HN_RATE_LIMIT_RPM: int = 60  # Algolia is generous; stay well under any soft cap
    HN_COMMENT_DEPTH_DEFAULT: int = 50  # top N comments by points (parity with Reddit)

    # -------------------------------------------------------------------
    # Mastodon connector (public ActivityPub instance)
    # -------------------------------------------------------------------
    # Mastodon's public hashtag-timeline endpoint requires no auth on most
    # instances:
    #   GET /api/v1/timelines/tag/<hashtag>
    #   GET /api/v1/statuses/<id>
    #   GET /api/v1/statuses/<id>/context
    # The instance is configurable per-job via the source_metadata
    # ``mastodon_instance`` field; this default is the fallback when no
    # instance is supplied. Self-hosters running on a private instance
    # can override globally via this env var.
    MASTODON_INSTANCE_BASE: str = "https://mastodon.social"
    MASTODON_USER_AGENT: str = (
        "pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani)"
    )
    MASTODON_RATE_LIMIT_RPM: int = 60  # Mastodon's per-IP unauth limit is 300 req/5min ≈ 60 rpm
    MASTODON_COMMENT_DEPTH_DEFAULT: int = 50  # top-N replies by favourites (parity with Reddit/HN)

    # -------------------------------------------------------------------
    # Bluesky connector (public AT-Protocol XRPC)
    # -------------------------------------------------------------------
    # Bluesky exposes its public read API without auth at:
    #   GET https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts
    #   GET https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread
    #   GET https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile
    #   GET https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed
    # No app password is needed for ingest today; if Bluesky tightens
    # rate limits we can swap to an authenticated PDS endpoint by
    # adding a token-fetching path. Operators running a private
    # Bluesky PDS can override the base URL.
    BLUESKY_XRPC_BASE: str = "https://public.api.bsky.app"
    BLUESKY_USER_AGENT: str = (
        "pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani)"
    )
    BLUESKY_RATE_LIMIT_RPM: int = 60  # Bluesky's public unauth caps are generous; stay polite at 60 rpm
    BLUESKY_COMMENT_DEPTH_DEFAULT: int = 50  # top-N replies by likes (parity with Reddit/HN/Mastodon)

    # -------------------------------------------------------------------
    # Podcast connector (M-1.7 / E-1.7)
    # -------------------------------------------------------------------
    # Two HTTP surfaces:
    #
    # 1. iTunes Search API at https://itunes.apple.com/search — free, no
    #    auth, used for show discovery. Returns shows matching a topic
    #    query; the connector then fetches each show's RSS feed to yield
    #    episode candidates.
    # 2. Direct RSS feed fetch — the canonical episode-data path. Each
    #    podcast's `feedUrl` from iTunes (or a user-provided RSS URL)
    #    gets parsed via feedparser. Episode <enclosure> tags carry the
    #    audio URLs; <podcast:transcript> tags (when present) skip the
    #    Whisper step.
    #
    # Whisper-as-service decision (resolves OQ-4): we reuse the existing
    # OpenAI Whisper integration (same path used as YouTube fallback)
    # rather than introducing a separate service. Gated on
    # `OPENAI_API_KEY` like the YouTube fallback. A future PR may add
    # a local-Whisper-via-faster-whisper opt-in for self-hosters who
    # don't want OpenAI in the loop, but that's not on the critical
    # path for M-1.7.
    PODCAST_USER_AGENT: str = (
        "pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani)"
    )
    PODCAST_RATE_LIMIT_RPM: int = 60  # iTunes Search is generous; stay polite
    # Per-show search yields up to this many recent episodes per show.
    # Combined with `PODCAST_SEARCH_TOP_N_SHOWS`, a topic search returns
    # up to `top_n_shows * episodes_per_show` candidates.
    PODCAST_EPISODES_PER_SHOW: int = 5
    PODCAST_SEARCH_TOP_N_SHOWS: int = 3
    # Audio-download timeout for the Whisper-fallback path. Podcasts are
    # often 1-2 hour episodes (50-150MB MP3), so we allow a generous
    # window. Connect-timeout stays short.
    PODCAST_AUDIO_FETCH_TIMEOUT_SEC: int = 180

    # -------------------------------------------------------------------
    # Article extraction Playwright fallback (E-1.6 T-1.6.6)
    # -------------------------------------------------------------------
    # `playwright` + Chromium browser binaries are ~150MB and slow to
    # install. We make the SPA-extraction fallback opt-in via a
    # separate `backend/requirements-spa.txt` constraint set + this
    # env flag. When `ARTICLE_PLAYWRIGHT_ENABLED=False` (default), the
    # fallback short-circuits with a single INFO log and returns None
    # — exactly as the T-1.6.1 stub did. When enabled, it launches
    # headless Chromium, navigates, waits for hydration, and re-feeds
    # the rendered DOM through trafilatura.
    #
    # Install (operator opt-in):
    #   pip install -r backend/requirements-spa.txt
    #   playwright install chromium
    #
    # Then set:
    #   ARTICLE_PLAYWRIGHT_ENABLED=True
    ARTICLE_PLAYWRIGHT_ENABLED: bool = False
    # Hard timeout for the whole fetch + hydrate + extract loop. Long
    # SPAs can take a while to settle; we cap at 30s so a single bad
    # URL doesn't stall the orchestrator.
    ARTICLE_PLAYWRIGHT_TIMEOUT_SEC: int = 30

    # -------------------------------------------------------------------
    # PDF / e-book connector (M-1.8 / E-1.8)
    # -------------------------------------------------------------------
    # PDFs come from user upload — there's no search / discovery
    # surface. The connector's `search()` and `list_creator_items()`
    # raise NotImplementedError, which the dispatcher handles per
    # D-026 (sequential fan-out, fail-isolated per source).
    #
    # `PDF_UPLOAD_DIR` is where raw PDF bytes get persisted on
    # upload. We don't store them in Chroma or the SQLite DB — only
    # extracted text + per-page segment metadata. The raw file is
    # kept so a future PR can re-extract (e.g. when PyMuPDF improves
    # table extraction) without re-uploading.
    PDF_UPLOAD_DIR: str = "./data/uploads/pdf"
    # Hard cap on uploaded file size. PyMuPDF can technically handle
    # arbitrary sizes but extraction time scales with page count;
    # capping at 100MB keeps a single ingest from monopolising the
    # worker. Larger files (academic books, technical manuals) can
    # be split before upload.
    PDF_MAX_BYTES: int = 100 * 1024 * 1024  # 100 MB

    # Echo shares inbox (S-3.7.1). Files land under
    # `ECHO_SHARES_DIR/<tenant>/` and nowhere else; the full Echo delete
    # removes that directory. The cap bounds one quick-share upload (a
    # screenshot, a voice memo, a small export), not the bulk importers
    # that S-3.7.5 adds.
    ECHO_SHARES_DIR: str = "./data/echo/shares"
    ECHO_SHARE_MAX_BYTES: int = 25 * 1024 * 1024  # 25 MB
    ECHO_SHARE_TEXT_MAX_CHARS: int = 50_000
    # S-3.7.2: how shares are processed after intake. "celery" queues one
    # `echo.process_share` task per share; "inline" processes in the request
    # (single-process dev); "off" leaves shares pending (the test suite).
    ECHO_SHARE_PROCESSING: str = "celery"
    # S-3.2.1: how a connector sync runs after connect and on "Sync now":
    # `celery` queues `echo.sync_connector` (production), `inline` runs it in
    # the request (self-host without a worker), `off` leaves it to the
    # scheduler tick. Scheduled syncs always go through the tick.
    ECHO_CONNECTOR_SYNC: str = "celery"
    # S-3.2.4: a separate GitHub OAuth app for the connector. Unset, the
    # sign-in app (OAUTH_GITHUB_CLIENT_ID/SECRET) is used; its callback URL
    # must then cover both redirects (register the frontend origin).
    OAUTH_GITHUB_CONNECTOR_CLIENT_ID: str | None = None
    OAUTH_GITHUB_CONNECTOR_CLIENT_SECRET: str | None = None
    # S-3.2.2 / S-3.2.5 (not built): Google connectors use their own OAuth
    # client so a scope review never touches Google sign-in.
    OAUTH_GOOGLE_CONNECTOR_CLIENT_ID: str | None = None
    OAUTH_GOOGLE_CONNECTOR_CLIENT_SECRET: str | None = None
    # Text embedded per share in shares_global (one vector per share, like
    # notes): the annotation, the title and the opening of the text.
    ECHO_SHARE_EMBED_MAX_CHARS: int = 2000
    # S-3.7.5: export-file importers (WhatsApp, Google Takeout). The upload
    # cap bounds one request; parsing streams, so memory stays flat. A zip may
    # unpack to at most ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES (a zip-bomb guard).
    # A WhatsApp chat is stored as turns: consecutive messages from one sender
    # at most ECHO_IMPORT_TURN_GAP_MIN apart, up to ECHO_IMPORT_TURN_MAX_CHARS.
    ECHO_IMPORT_MAX_BYTES: int = 200 * 1024 * 1024
    ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES: int = 1024 * 1024 * 1024
    ECHO_IMPORT_TURN_GAP_MIN: int = 10
    ECHO_IMPORT_TURN_MAX_CHARS: int = 2000
    # S-3.7.3: share tokens (browser extension) per tenant, and fetching an
    # image shared by its address. The fetch refuses hosts that resolve to
    # private, loopback or link-local addresses unless the install allows it
    # (a self-hosted LAN).
    ECHO_SHARE_TOKENS_MAX: int = 10
    ECHO_FETCH_TIMEOUT_SEC: int = 20
    ECHO_FETCH_ALLOW_PRIVATE: bool = False
    # S-3.7.2 part 2: media shares. Images go through on-device OCR
    # (RapidOCR) first; a reading counts as confident when it has at least
    # ECHO_OCR_MIN_CHARS non-space characters at a mean box score of at
    # least ECHO_OCR_MIN_CONFIDENCE. Measured 2026-10-19: English text
    # scored 0.978-0.988 and read 97.6-100% right, clean or degraded; the
    # default models cannot read Devanagari (Hindi read nothing or noise
    # at 0.69, mixed Hindi-English 0.82-0.87 at 42-54% accuracy), so
    # 0.90 sends those to the vision fallback.
    ECHO_OCR_MIN_CHARS: int = 20
    ECHO_OCR_MIN_CONFIDENCE: float = 0.90
    # ONNX threads for on-device OCR. onnxruntime's default (every core)
    # oversubscribes: on a 32-thread machine a 1080x1920 screenshot took
    # 6.0 s with the default and 1.4 s with 4 threads (2026-10-19).
    ECHO_OCR_THREADS: int = 4
    # Longest image side sent to the vision fallback. Providers downscale
    # beyond about 2048 px anyway, so larger only costs upload time.
    ECHO_OCR_VISION_MAX_SIDE: int = 2048
    ECHO_OCR_VISION_MAX_TOKENS: int = 4000
    # Whether Echo may send a shared image (the vision fallback) or a
    # recording (Whisper) to a remote provider. Off: images use on-device
    # OCR only (or a vision model the install runs locally) and audio is
    # skipped with a note. On by default, like the rest of the install,
    # which already sends transcripts and audio to providers.
    ECHO_REMOTE_MEDIA: bool = True
    # Wall-clock cap on decoding one shared recording with ffmpeg.
    ECHO_MEDIA_DECODE_TIMEOUT_SEC: int = 300
    # S-3.3.2: voice and personality signal extraction. "celery" queues one
    # `echo.extract_signals` run per tenant once ECHO_SIGNALS_MIN_NEW_INPUTS
    # new or edited texts (notes, questions, own-words shares) are waiting;
    # "inline" runs in the request (single-process dev); "off" never runs
    # (the test suite).
    ECHO_SIGNAL_EXTRACTION: str = "celery"
    ECHO_SIGNALS_MIN_NEW_INPUTS: int = 10
    # One economy-tier call reads up to this many tokens of the user's text.
    ECHO_SIGNALS_BATCH_TOKENS: int = 6000
    # Candidate signals one batch may return, and the output cap that bounds
    # them (reasoning stays off: OpenAI counts reasoning tokens against it).
    ECHO_SIGNALS_MAX_PER_BATCH: int = 12
    ECHO_SIGNALS_MAX_OUTPUT_TOKENS: int = 2500
    # Cost bound per run: a backlog larger than this many batches is read
    # over several runs.
    ECHO_SIGNALS_MAX_BATCHES_PER_RUN: int = 20
    # An export import (a WhatsApp chat can be 100k turns) is ONE input:
    # stylometry reads every own-words turn, the model reads a time-spread
    # sample of at most this many, skipping turns shorter than
    # ECHO_SIGNALS_MIN_PASSAGE_WORDS ("ok", "haha"), which carry style but
    # no view.
    ECHO_SIGNALS_IMPORT_SAMPLE: int = 300
    ECHO_SIGNALS_MIN_PASSAGE_WORDS: int = 4
    # S-3.4.1 "speak as me". Off by default for the whole install, AND
    # enabled per user only after they pass the blinded "which did you
    # write?" test (D-100; echo_voice_gates). A draft is never sent.
    ECHO_SPEAK_AS_ME_ENABLED: bool = False
    # The tier (iii) test needs this many live notes before it can be taken
    # (pre-registered, docs/notes/2026-10-19-voice-match-preregistration.md).
    ECHO_VOICE_TEST_MIN_NOTES: int = 40
    # Critique rounds per draft, and the mean voice score (1-5, tone,
    # vocabulary, structure, topicality) at which the critic stops early.
    ECHO_DRAFT_CRITIQUE_ROUNDS: int = 2
    ECHO_DRAFT_CRITIQUE_TARGET: float = 4.0
    # Library sources retrieved for one draft.
    ECHO_DRAFT_SOURCES: int = 6
    # S-3.3.3: keep personal_context_global (one vector per live fact and
    # signal) in step on every write and at startup. Off for the test suite,
    # like NOTES_INDEX_ENABLED, so no test embeds into a persistent Chroma;
    # the retrieval tests turn it on with an ephemeral client.
    ECHO_PERSONAL_INDEX_ENABLED: bool = True

    # -------------------------------------------------------------------
    # Visual understanding (R1 / E-1.18) — frame capture + description
    # -------------------------------------------------------------------
    # Everything here is OFF by default and opt-in per job. Two reasons,
    # both learned the hard way:
    #
    # 1. Cost. Frame description is the only multimodal call site in the
    #    app. A 200-video corpus at 12 frames/video is 2,400 vision calls.
    # 2. Bot-wall risk. Capturing frames needs a *video* stream, not the
    #    audio-only stream the Whisper path downloads. That is strictly
    #    more yt-dlp traffic against YouTube, and D-051 records what
    #    happened last time we got greedy: an IP block that cost 63
    #    videos mid-job.
    #
    # `VISUAL_ENABLED` is the install-wide kill switch; a job also has to
    # ask for it (`jobs.visual_analysis`). Both must be true.
    VISUAL_ENABLED: bool = False
    # Where extracted JPEGs live. Frames are keyed by document, not by
    # job — like transcripts and embeddings they are computed once and
    # reused by every job that references the document.
    VISUAL_FRAMES_DIR: str = "./data/frames"
    # Per-document cap on captured frames. The selector is asked for at
    # most this many moments; anything beyond is truncated, and the
    # truncation is logged rather than silently dropped.
    VISUAL_MAX_FRAMES_PER_VIDEO: int = 12
    # Per-job ceiling across all documents. Bounds worst-case spend on a
    # large corpus even when every video wants its full per-video quota.
    VISUAL_MAX_FRAMES_PER_JOB: int = 200
    # Minimum spacing between two selected moments. Without this the
    # selector clusters around a single dense passage ("as you can see…"
    # repeated over one slide) and burns the quota on near-duplicates.
    VISUAL_MIN_GAP_SECONDS: float = 20.0
    # Downscale width before sending to the vision model. Vision cost
    # scales with pixel count; 1280px is comfortably enough to read a
    # slide or a chart axis label.
    VISUAL_FRAME_MAX_WIDTH: int = 1280
    # ffmpeg -q:v for the extracted JPEG (2 = near-lossless, 31 = worst).
    # 5 keeps small text legible at a fraction of PNG size.
    VISUAL_FRAME_JPEG_QUALITY: int = 5
    # Hard cap on the intermediate video download. A frame grab needs
    # video, and we deliberately fetch the *worst* stream that still
    # clears 360p. If even that exceeds this cap we skip the document
    # rather than pull hundreds of MB for 12 JPEGs.
    VISUAL_MAX_VIDEO_DOWNLOAD_MB: int = 400
    # Per-document wall-clock budget for download + extraction. A single
    # slow document must not stall a 200-video job.
    VISUAL_CAPTURE_TIMEOUT_SEC: int = 900

    # R3 / S-1.17.2: per-document "which era does this source discuss"
    # extraction (`temporal_scope_extract`). One economy-tier call per
    # document on its first ingest, persisted to `documents.discussed_era_json`
    # and reused by every later job. Off = every era reads as unknown, which
    # is exactly how a missing value is treated anyway, so flipping this
    # never changes the shape of anything downstream.
    TEMPORAL_SCOPE_ENABLED: bool = True
    # Transcript text sampled for the era call: three windows (opening,
    # middle, close) of this many tokens each. The opening usually names the
    # subject; the middle and close catch a source that pivots.
    TEMPORAL_SCOPE_WINDOW_TOKENS: int = 1500

    # S-8.4.1: how long a context's question suggestions are reused before
    # they are recomputed, even if nothing on the context changed. A new
    # exchange, report or knowledge state invalidates sooner (fingerprint).
    # The plan's proposed hour (docs/plans/m4-question-suggestions.md, open
    # question 2). 0 = never reuse.
    SUGGESTIONS_CACHE_TTL_MIN: int = 60

    # S-8.3.3 saved-search change detection. Pre-registered in
    # docs/notes/2026-10-19-saved-search-change-thresholds.md (#323): the
    # history held 2 re-ask pairs, under the protocol's minimum of 20, so
    # these are its priors until the protocol is re-run (T-8.3.3.7).
    # A run is "changed" when the cited-set Jaccard is BELOW the first or
    # the answer-embedding cosine distance is ABOVE the second; when only
    # one says so, the saved_search_judge decides.
    SAVED_SEARCH_JACCARD_THRESHOLD: float = 0.50
    SAVED_SEARCH_EMBEDDING_THRESHOLD: float = 0.15
    # Stage 1: skip a scheduled run whose scope gained no newly visible
    # document since the last good run (cost follows ingest). Run now
    # always asks.
    SAVED_SEARCH_GATE_ENABLED: bool = True

    # Links in emails (saved-search alerts) point here.
    APP_BASE_URL: str = "http://localhost:5173"

    # S-1.14.6: persist the report pipeline's map/reduce intermediates
    # (per-batch extraction JSON, the reduced dataset) to
    # `job_report_intermediates`, so stage quality can be audited after a
    # run instead of only replayed. On by default: about twice the reduced
    # dataset's size per run (~3 MB on the 200-video reference job), and the
    # rows are what makes a map regression or a modality label (S-1.18.8)
    # checkable on real runs. Off = nothing is captured or written.
    REPORT_INTERMEDIATES_ENABLED: bool = True

    # S-1.14.19: map-stage batching (docs/notes/2026-10-19-map-coverage.md).
    # The map model writes roughly 100-140 items per call whatever a batch
    # holds, so a large batch starves the sources late in it. `packed` fills
    # batches in source order up to REPORT_MAP_BATCH_TOKENS (also capped by
    # the model's window); `source` never puts two sources in one call (a
    # long source still splits at the cap), which also stops one video's
    # on-screen span or script leaking into another video's items. D-090
    # made `source` at 30K the default; R1 run 7's pre-registered batching
    # comparison did not show it better on substance (1 for, 2 ties), so
    # D-094 restored `packed` at 120_000. `source` doubles report length.
    REPORT_MAP_BATCHING: str = "packed"
    REPORT_MAP_BATCH_TOKENS: int = 120_000
    # Map calls in flight at once. Batches are independent and results are
    # kept in batch order, so the report never depends on completion order.
    REPORT_MAP_CONCURRENCY: int = 4

    # R5 / S-1.16.2 (invention N-002): how a code-mixed span is QUOTED,
    # decided from its measured Hindi share and matrix (grammar) language.
    # - Hindi grammar and Hindi share >= DOMINANT -> the whole quote in
    #   Devanagari, with transliteration and translation (D-066's full form);
    # - English grammar and Hindi share <= BORROWING_MAX -> plain English
    #   (a few borrowed words, translated inline);
    # - anything between -> Roman script throughout, with translation.
    # Defaults chosen on the DEV split of the labelled set as the centres of
    # the plateaus where the detector's decision agrees with the gold one;
    # see docs/notes/2026-10-19-code-mixing-detection.md section 8. What
    # DOMINANT should rest on is an open question recorded in D-080.
    CODE_MIX_DOMINANT_SHARE: float = 0.6
    CODE_MIX_BORROWING_MAX_SHARE: float = 0.2
    # T-1.16.2.5 part B: embed non-English chunks as an English rendering
    # (`code_mixing_render_english`, one volume-tier call per ~6 chunks, once
    # per document) while the stored text stays the original. Off = chunks
    # embed as written, which retrieval measured at MRR 0.565 (Devanagari) /
    # 0.402 (romanised) against 0.805 rendered.
    CODE_MIX_ENGLISH_RENDERING_ENABLED: bool = True

    # -------------------------------------------------------------------
    # Scheduler (S-8.3.1 / M3) — the shared Celery-beat tick
    # -------------------------------------------------------------------
    # One static beat entry, `scheduler.tick`, every TICK_SECONDS. The tick
    # claims due `scheduled_runs` rows with a short lease and dispatches each
    # kind's task on the owning tenant's tier queue. Saved searches, the
    # newsletter and Echo syncs all ride on this. Off = the beat entry is
    # not registered and a tick that still arrives no-ops.
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TICK_SECONDS: int = 300
    # A claim older than this is stale (the holder died between claim and
    # advance) and may be taken again. Longer than any plausible dispatch.
    SCHEDULER_LEASE_SECONDS: int = 600
    # Rows due within this many seconds count as due, so a beat that fires
    # a little early still runs them; `next_run_at` then advances from the
    # scheduled time, not from `now`, so nothing runs twice.
    SCHEDULER_GRACE_SECONDS: int = 30
    # Max rows one tick claims. Bounds a backlog after downtime.
    SCHEDULER_BATCH_SIZE: int = 50
    # A failed dispatch (broker down) is retried at the next tick this many
    # times before the row waits for its next cadence slot instead.
    SCHEDULER_MAX_RETRY_TICKS: int = 3

    # -------------------------------------------------------------------
    # Article connector — search engine + RSS (E-1.6 T-1.6.2 + T-1.6.3)
    # -------------------------------------------------------------------
    # Search-engine integration is opt-in via API key. Brave Search is
    # the default supported provider because (a) it has a generous
    # free tier without requiring credit-card details, (b) the API
    # surface is simple (single GET, JSON response), (c) it doesn't
    # demand a contract or per-query approval like Google Custom
    # Search. Future PRs can add Tavily / Kagi as alternative
    # providers; the connector picks whichever is configured.
    BRAVE_SEARCH_API_KEY: str = ""
    BRAVE_SEARCH_BASE: str = "https://api.search.brave.com/res/v1/web/search"
    ARTICLE_USER_AGENT: str = (
        "pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani)"
    )
    # Per-search-call rate limit. Brave's free tier is ~1 req/sec.
    ARTICLE_SEARCH_RATE_LIMIT_RPM: int = 60

    # -------------------------------------------------------------------
    # Twitter / X connector — BYOK paid API (S-1.5.9 + S-1.5.10)
    # -------------------------------------------------------------------
    # Per [D-009](docs/decisions.md), Twitter / X access is BYOK + opt-in.
    # The platform's free tier is too restrictive for ingest at the
    # scale this project needs (1500 reads/month; Pro tier @ $100/mo
    # gets 10K). Operators opt in by registering at
    # https://developer.twitter.com and pasting the bearer token here.
    #
    # When `TWITTER_BEARER_TOKEN` is set:
    # - The `tweet` source_type's connector is upgraded from paste-
    #   only (S-1.5.8) to search-having (Twitter API v2).
    # - The `/api/v1/health` endpoint reports `twitter_search_enabled:
    #   true` so the frontend can show the topic-search-with-Twitter
    #   path.
    # When unset, the paste-mode `TweetConnector` from
    # `app.sources.paste_url` is the only path — same fail-soft as
    # E-1.6 article search-without-Brave.
    TWITTER_BEARER_TOKEN: str = ""
    TWITTER_API_BASE: str = "https://api.twitter.com/2"
    TWITTER_USER_AGENT: str = (
        "pratidhvani/0.1 (+https://github.com/anthropics/pratidhvani)"
    )
    # Pro tier is ~50 req/15min on most search endpoints. Stay under
    # the cap with a 60-rpm token bucket; operators on higher tiers
    # can lift via env if they hit the floor.
    TWITTER_RATE_LIMIT_RPM: int = 60
    TWITTER_REPLY_DEPTH_DEFAULT: int = 50

    # -------------------------------------------------------------------
    # LLM — Primary (high-quality) model
    # -------------------------------------------------------------------
    # Provider dispatches which chat client is built. The call-site code is
    # provider-agnostic: every LangChain chat model exposes the same
    # ``.invoke([HumanMessage(...)])`` contract, so no agent code cares
    # which provider is actually serving the request.
    #
    #   "openai"    → langchain_openai.ChatOpenAI using OPENAI_API_KEY
    #   "anthropic" → langchain_anthropic.ChatAnthropic using ANTHROPIC_API_KEY
    #                 (requires: pip install langchain-anthropic)
    #   "google"    → langchain_google_genai.ChatGoogleGenerativeAI using
    #                 GOOGLE_API_KEY (requires: pip install langchain-google-genai)
    LLM_PRIMARY_PROVIDER: Literal["openai", "anthropic", "google"] = "openai"

    # Primary model name. Interpreted per provider:
    #   openai    → "gpt-5", "gpt-4.1", "gpt-4o", ...
    #   anthropic → "claude-opus-4-5", "claude-sonnet-4-5", ...
    #   google    → "gemini-2.5-pro", "gemini-2.5-flash", ...
    # Left blank → falls back to the legacy LLM_MODEL for back-compat.
    LLM_PRIMARY_MODEL: str = ""

    # Provider credentials. Only the one matching LLM_PRIMARY_PROVIDER is
    # actually required at runtime, but we accept all three so switching
    # providers is a one-line .env edit.
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""

    # Legacy OpenAI-only knobs. Still honored when LLM_PRIMARY_PROVIDER ==
    # "openai"; kept to avoid a breaking change for existing deployments.
    LLM_MODEL: str = "gpt-5"
    LLM_FALLBACK_MODEL: str = "gpt-4o"
    LLM_MAX_CONTEXT_TOKENS: int = 1047576

    # -------------------------------------------------------------------
    # LLM — Fast (cheap / local) model
    # -------------------------------------------------------------------
    # The fast path is intentionally OpenAI-compatible only, because every
    # serious local inference server (LM Studio, vLLM, llama.cpp server,
    # Ollama) exposes an ``/v1/chat/completions`` shim. Keeping this path
    # single-flavor simplifies the service.
    #
    # LLM_FAST_BASE_URL set → route "fast" calls to that OpenAI-compat
    # server (typically LM Studio at http://localhost:1234/v1).
    # LLM_FAST_BASE_URL unset → still use LLM_FAST_MODEL, but hit the
    # OpenAI API — handy for running cheaper OpenAI models on the fast slot
    # without any local server.
    LLM_FAST_MODEL: str = "gpt-4.1-mini"
    LLM_FAST_BASE_URL: str | None = None
    LLM_FAST_API_KEY: str = "not-needed"

    # -------------------------------------------------------------------
    # LLM — Local inference endpoint (OpenAI-compatible)
    # -------------------------------------------------------------------
    # Canonical names for the local endpoint. If unset, the legacy
    # LLM_FAST_BASE_URL / LLM_FAST_API_KEY are used as fallback so existing
    # .env files keep working. Either may point at LM Studio, Ollama,
    # vLLM, llama.cpp-server, etc.
    LLM_LOCAL_BASE_URL: str = ""
    LLM_LOCAL_API_KEY: str = ""

    # -------------------------------------------------------------------
    # LLM — Per-use-case route overrides (legacy, binary primary/fast)
    # -------------------------------------------------------------------
    # Comma-separated ``use_case=route`` pairs. Lets you flip any single
    # call site between primary/fast without touching code.
    #
    # Example, keep the big refine calls on OpenAI while routing the map
    # phase to your local model::
    #
    #   LLM_ROUTE_OVERRIDES=qa_refine_context=primary,library_qa_refine_context=primary
    #
    # The full list of use_case names (with descriptions and token budgets)
    # lives in app/services/llm_routing.py::USE_CASE_REGISTRY. Unknown
    # names are logged and ignored, not fatal.
    #
    # NOTE: This knob is superseded by LLM_USE_CASE_CONFIG below (which
    # picks provider+model+reasoning per call site). LLM_ROUTE_OVERRIDES
    # is still honored for back-compat; entries here are the *lowest*
    # precedence and only apply when LLM_USE_CASE_CONFIG is empty or
    # missing for that use case.
    LLM_ROUTE_OVERRIDES: str = ""

    # -------------------------------------------------------------------
    # LLM — Per-use-case inline config (provider + model + reasoning)
    # -------------------------------------------------------------------
    # Comma-separated entries. Each entry::
    #
    #   <use_case>=<provider>:<model>[:<reasoning>]
    #
    # where provider ∈ {openai, anthropic, google, local}, model is the
    # provider-specific name, and reasoning (optional, default "off") is
    # one of {off, minimal, low, medium, high, auto}. Whitespace and line
    # breaks between entries are tolerated (pydantic ignores newlines in
    # env values by default; if you need multi-line, set env var via a
    # shell one-liner and keep commas).
    #
    # Example::
    #
    #   LLM_USE_CASE_CONFIG=qa_formulate_answer=openai:gpt-5.4:medium,qa_clarification=local:qwen/qwen3.5-9b:off,knowledge_synthesize_report=anthropic:claude-opus-4-5:medium
    #
    # Missing use cases fall back to the registry's default_config (see
    # app/services/llm_routing.py::USE_CASE_REGISTRY). Unknown use-case
    # names, unknown providers, and unknown reasoning levels are logged
    # as warnings and ignored — never fatal, so a typo doesn't take down
    # the app.
    LLM_USE_CASE_CONFIG: str = ""

    # Jobs
    MAX_CONCURRENT_JOBS: int = 5
    MAX_VIDEOS_PER_JOB: int = 100
    DEFAULT_TRANSCRIPT_LANGUAGE: str = "en"

    # RAG
    CHUNK_SIZE: int = 256
    CHUNK_OVERLAP: int = 32
    RAG_TOP_K: int = 15
    RAG_DISTANCE_THRESHOLD: float = 0.6
    # S-8.5.2: notes join job and library Q&A retrieval. Off switch for the
    # whole notes index (writes and reads); the test suite turns it off so no
    # router test embeds or touches a persistent collection.
    NOTES_INDEX_ENABLED: bool = True
    # D-068 re-rank weight for the user's own notes: distance / weight, applied
    # after the raw relevance threshold, like a channel trust weight. 1.5 is
    # the M5 plan's starting value (the plan's open question 1); see the
    # S-8.5.2 measurement before changing it.
    NOTE_RETRIEVAL_WEIGHT: float = 1.5
    EMBEDDING_MODEL_NAME: str = "paraphrase-multilingual-MiniLM-L12-v2"

    # Reports
    REPORTS_DIR: str = "./data/reports"
    # S-6.7.2: Author Studio binary artifacts (PDF, EPUB, PPTX, site zips),
    # one directory per output: <OUTPUTS_DIR>/<user_id>/<output_id>/.
    # `outputs.content_path` is stored relative to this root.
    OUTPUTS_DIR: str = "./data/outputs"
    # S-6.1.5: which converter prints a book's PDF. "auto" tries WeasyPrint
    # (needs Pango) and then Chromium through Playwright; "weasyprint" or
    # "chromium" pins one; "off" disables PDF. Both are optional installs
    # (backend/requirements-author.txt); EPUB and Markdown need neither.
    AUTHOR_PDF_ENGINE: str = "auto"
    # Wall-clock budget for Chromium to launch and lay out one book.
    AUTHOR_PDF_TIMEOUT_SEC: int = 180
    MAX_REPORT_WORDS: int = 20000

    # Knowledge extraction (Unit 4)
    KNOWLEDGE_EXTRACT_BATCH_TOKENS: int = 8000
    KNOWLEDGE_MAX_TRANSCRIPT_TOKENS: int = 60000

    # Auth
    JWT_SECRET: str = "dev-insecure-secret-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24

    @field_validator("JWT_SECRET", mode="before")
    @classmethod
    def _jwt_secret_not_blank(cls, v: object) -> object:
        """A blank ``JWT_SECRET=`` in .env is unset, not a key.

        python-jose signed with an empty HMAC key without complaint; PyJWT
        (T-5.4.9) refuses, which is how this install was found to have been
        issuing tokens with no secret. Fall back to the dev default, loudly;
        production must set a real value.
        """
        if v is None or (isinstance(v, str) and not v.strip()):
            import logging

            logging.getLogger("app.config").warning(
                "JWT_SECRET is blank; using the insecure development default. "
                "Set JWT_SECRET in backend/.env (any long random string)."
            )
            return "dev-insecure-secret-change-me-in-production"
        return v
    # E-5.4: Account lockout. Failed-login threshold; on the (Nth) failure
    # the account locks for ``LOCKOUT_DURATION_MIN`` minutes. Set to 0 to
    # disable lockout (not recommended in production).
    LOCKOUT_FAILURE_THRESHOLD: int = 5
    LOCKOUT_DURATION_MIN: int = 15
    # E-5.4: Password-reset token TTL (minutes). Tokens expire after this
    # window AND are single-use.
    PASSWORD_RESET_TOKEN_TTL_MIN: int = 30
    # T-5.4.6 MFA — issuer name shown by the user's authenticator app.
    MFA_ISSUER_NAME: str = "Pratidhvani"

    # T-5.4.5 OAuth — Google + GitHub PKCE. Each provider needs both a
    # client_id and a client_secret. When unset, the corresponding
    # /auth/oauth/<provider>/* endpoints return 503 with a clear message.
    OAUTH_GOOGLE_CLIENT_ID: str | None = None
    OAUTH_GOOGLE_CLIENT_SECRET: str | None = None
    OAUTH_GITHUB_CLIENT_ID: str | None = None
    OAUTH_GITHUB_CLIENT_SECRET: str | None = None
    # Override per-deployment (e.g. to support a frontend on a different
    # origin). Defaults assume the API itself is the redirect target.
    OAUTH_REDIRECT_BASE_URL: str | None = None

    # T-5.4.8: SMTP delivery for password-reset / future verification emails.
    # When SMTP_HOST is unset, the email_service falls back to logging the
    # rendered email to stderr so self-host operators can hand-deliver it
    # without configuring SMTP. Set in production / SaaS.
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_ADDRESS: str | None = None
    SMTP_USE_SSL: bool = False
    SMTP_USE_STARTTLS: bool = True

    # E-5.6: BYOK encryption key. 32 url-safe base64-encoded bytes
    # (generate via cryptography.fernet.Fernet.generate_key()). When unset,
    # a process-local key is generated at startup with a loud warning —
    # stored credentials will be unrecoverable after a process restart in
    # that mode. Operators MUST set this in production.
    BYOK_ENCRYPTION_KEY: str | None = None

    # E-5.5: Rate limiting. Per-minute caps applied by the
    # RateLimitMiddleware. Set RATE_LIMIT_ENABLED=False to disable in dev /
    # under-test contexts where rate limits get in the way of fast iteration.
    RATE_LIMIT_ENABLED: bool = True
    # Per-user (authenticated) caps, scaled per tier.
    RATE_LIMIT_PER_MIN_FREE: int = 60
    RATE_LIMIT_PER_MIN_PRO: int = 600
    RATE_LIMIT_PER_MIN_STUDIO: int = 6000
    # Per-IP cap for unauthenticated GETs (health, etc.).
    RATE_LIMIT_PER_MIN_UNAUTH: int = 100
    # Sensitive endpoints — credential-stuffing / brute-force / mass-reset
    # defence. Per-IP, applied BEFORE the per-user bucket.
    RATE_LIMIT_LOGIN_PER_MIN: int = 10
    RATE_LIMIT_RESET_PER_MIN: int = 5
    RATE_LIMIT_REGISTER_PER_MIN: int = 5

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
