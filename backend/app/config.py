from typing import Literal

from pydantic_settings import BaseSettings


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

    # YouTube
    YOUTUBE_API_KEY: str = ""
    YOUTUBE_TRANSCRIPT_RATE_LIMIT: float = 0.5
    YOUTUBE_DAILY_QUOTA: int = 10000

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
    EMBEDDING_MODEL_NAME: str = "paraphrase-multilingual-MiniLM-L12-v2"

    # Reports
    REPORTS_DIR: str = "./data/reports"
    MAX_REPORT_WORDS: int = 20000

    # Knowledge extraction (Unit 4)
    KNOWLEDGE_EXTRACT_BATCH_TOKENS: int = 8000
    KNOWLEDGE_MAX_TRANSCRIPT_TOKENS: int = 60000

    # Auth
    JWT_SECRET: str = "dev-insecure-secret-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
