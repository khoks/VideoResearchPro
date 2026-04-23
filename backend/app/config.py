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

    # LLM
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "gpt-5"
    LLM_FALLBACK_MODEL: str = "gpt-4o"
    LLM_MAX_CONTEXT_TOKENS: int = 1047576

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

    # Auth
    JWT_SECRET: str = "dev-insecure-secret-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
