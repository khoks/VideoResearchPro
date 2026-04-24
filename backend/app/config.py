from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "VideoResearchPro"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "sqlite:///./data/videoresearchpro.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ChromaDB
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHROMA_GLOBAL_COLLECTION_NAME: str = "videoresearchpro_global"
    CHROMA_QA_COLLECTION_NAME: str = "qa_library_global"

    # YouTube
    YOUTUBE_API_KEY: str = ""
    YOUTUBE_TRANSCRIPT_RATE_LIMIT: float = 0.5
    YOUTUBE_DAILY_QUOTA: int = 10000

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
    # LLM — Per-use-case route overrides
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
    LLM_ROUTE_OVERRIDES: str = ""

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
