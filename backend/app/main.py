import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.middleware.rate_limit import RateLimitMiddleware
from app.routers import (
    admin,
    auth,
    author,
    channels,
    credentials,
    echo,
    exports,
    health,
    jobs,
    knowledge,
    library,
    llm_settings,
    mfa,
    oauth,
    qa,
    qa_history,
    sessions,
    ws,
)
from app.services import chroma_service
from app.services.llm_smoke import run_startup_probes
from app.services.schema_init_service import ensure_schema_at_head

# Ensure all app.* loggers emit at INFO level.
# uvicorn sets up root logger handlers; this just lowers the threshold for our loggers.
logging.getLogger("app").setLevel(logging.INFO)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # E-4.10: Schema init. Replaces the historical
    # ``Base.metadata.create_all`` lifespan hook with an Alembic-managed
    # init that handles fresh installs (run upgrade head) + up-to-date
    # installs (no-op) + pre-E-4.10 operators stuck at intermediate
    # revisions with create_all'd tables (auto-stamp head when the live
    # schema matches the ORM). See ``app/services/schema_init_service.py``.
    try:
        result = ensure_schema_at_head(settings.DATABASE_URL, Base.metadata)
        logger.info(f"schema_init: {result}")
    except Exception:
        logger.exception(
            "schema_init failed catastrophically — app may not work correctly. "
            "Run `alembic upgrade head` manually and restart, or see "
            "docs/migration-create-all-conflict-recovery.md for the recovery "
            "runbook."
        )
        raise

    os.makedirs(settings.REPORTS_DIR, exist_ok=True)
    os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)

    # Idempotent one-shot backfill of the Q&A library Chroma collection.
    # Upsert on fixed `qa:{id}` chunk IDs means this is safe to run on every
    # startup; a Chroma failure here must never prevent the app from coming up.
    try:
        chroma_service.backfill_qa_library()
    except Exception:
        logger.exception("Q&A library backfill failed; continuing startup")

    try:
        await run_startup_probes()
    except Exception:
        logger.exception("LLM startup probes failed catastrophically")

    logger.info("Pratidhvani startup complete")
    yield
    # Shutdown: cleanup if needed


app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# E-5.5: per-route + per-tier rate limiting. Disabled in tests via
# RATE_LIMIT_ENABLED=False (set automatically in conftest.py).
app.add_middleware(RateLimitMiddleware)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(auth.router, prefix="/api/v1")
app.include_router(credentials.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(mfa.router, prefix="/api/v1")
app.include_router(oauth.router, prefix="/api/v1")
app.include_router(echo.router, prefix="/api/v1")
app.include_router(author.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(channels.router, prefix="/api/v1")
app.include_router(qa.router, prefix="/api/v1")
app.include_router(library.router, prefix="/api/v1")
app.include_router(qa_history.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(exports.router, prefix="/api/v1")
app.include_router(llm_settings.router, prefix="/api/v1")
app.include_router(ws.router)
