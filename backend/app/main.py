import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import Base, engine
from app.middleware.content_security_policy import ContentSecurityPolicyMiddleware
from app.middleware.cors import AppOriginsCORSMiddleware
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
    job_templates,
    jobs,
    frames,
    knowledge,
    library,
    llm_settings,
    mfa,
    notes,
    oauth,
    onboarding,
    suggestions,
    saved_searches,
    notifications,
    echo_cards,
    echo_connectors,
    echo_signals,
    echo_drafts,
    echo_voice_test,
    qa,
    qa_history,
    reports,
    search,
    sessions,
    shelves,
    tags,
    usage,
    ws,
)
from app.services import auth_service, byok_service, chroma_service, note_index, search_service
from app.services.llm_smoke import run_startup_probes
from app.services.schema_init_service import ensure_schema_at_head
from app.sources.twitter import client as twitter_client
from app.utils import app_origins, tiktoken_cache
from app.utils.shared_url_log import traceback_without_text

# T-8.8.6.5: tiktoken's encoding in TIKTOKEN_ENCODINGS_DIR rather than the
# temp folder, before anything counts a token. The worker does the same in
# app/tasks/celery_app.py; whichever runs first decides, the other agrees.
tiktoken_cache.use_app_folder(settings.TIKTOKEN_ENCODINGS_DIR)

# The API's app.* loggers at INFO; the worker's follow Celery's --loglevel.
# uvicorn gives the root logger no handler, so this level alone wrote nothing:
# under LOG_FORMAT=text the "app" logger has a handler of its own, and under
# json the root logger has one (app/utils/json_logging.py, from app/__init__.py).
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

    # S-8.2.1: the search index. Migration a9f3c1e7b5d2 created the FTS5
    # tables if SQLite had FTS5 at the time; this re-probes on every boot so
    # a Python upgrade that gains FTS5 later still gets them, and records
    # the backend for /health. Never blocks startup: LIKE is the fallback.
    try:
        backend = search_service.ensure_index_for_url(settings.DATABASE_URL)
        logger.info("search: backend=%s", backend)
    except Exception:
        logger.exception("search: index setup failed; searching with LIKE")

    os.makedirs(settings.REPORTS_DIR, exist_ok=True)
    os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)

    # T-4.11.3.3: the pages CORS answers and sign-in returns to, one list. A
    # bad entry in it is logged here, at startup, not at the first request.
    logger.info("App origins (CORS and OAuth sign-in): %s", app_origins.describe())

    # T-1.5.9.1: whether X search is configured, from the token's presence
    # alone (a D-141 hold is /health's to report, not this line's).
    twitter_client.log_token_presence()

    # Idempotent one-shot backfill of the Q&A library Chroma collection.
    # Upsert on fixed `qa:{id}` chunk IDs means this is safe to run on every
    # startup; a Chroma failure here must never prevent the app from coming up.
    try:
        chroma_service.backfill_qa_library()
    except Exception:
        logger.exception("Q&A library backfill failed; continuing startup")

    # D-070: stamp `document_id` onto transcript chunks that predate the
    # retrieval filter change. Metadata-only (no re-embedding), idempotent,
    # and a Chroma failure here must not stop the app either.
    try:
        chroma_service.backfill_chunk_document_ids()
    except Exception:
        logger.exception("Chunk document_id backfill failed; continuing startup")

    # S-8.5.2: the notes retrieval index. Idempotent (upsert live notes on
    # `note:{id}`, remove withdrawn ones); a failure never stops startup.
    try:
        note_index.backfill()
    except Exception:
        logger.exception("Notes index backfill failed; continuing startup")

    # S-3.3.3: Echo's personal retrieval collection. Embeds only what is
    # missing or changed, removes vectors of rows that are gone or
    # tombstoned; a failure never stops startup.
    try:
        from app.services import echo_personal_vectors

        echo_personal_vectors.backfill()
    except Exception:
        logger.exception("Personal-context backfill failed; continuing startup")

    # D-111 review: an ADMIN_EMAILS entry with no account names nobody, and
    # password registration refuses it. Say so at startup, so the operator
    # registers before listing. A failure here never stops startup.
    try:
        auth_service.warn_unregistered_operators()
    except Exception as e:
        # T-4.11.4.4: by its frames and type. A database error's text quotes
        # the query's values, which are the listed addresses.
        logger.error("ADMIN_EMAILS check failed; continuing startup: %s", traceback_without_text(e))

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


# T-5.6.9: the net under every route that encrypts or decrypts with the
# shared Fernet key (D-043). A malformed BYOK_ENCRYPTION_KEY raises
# EncryptionConfigurationError from byok_service._get_fernet; the routes that
# can meet it (/auth/credentials, two-step verification, Echo connectors)
# answer 503 in their own words, and any route that does not catch it answers
# this instead of a bare 500. Neither the response nor the log carries the
# configured key.
@app.exception_handler(byok_service.EncryptionConfigurationError)
async def _encryption_key_invalid(
    request: Request, exc: byok_service.EncryptionConfigurationError
) -> JSONResponse:
    logger.error("%s %s refused: %s", request.method, request.url.path, exc.log_cause)
    return JSONResponse(
        status_code=503,
        content={"detail": exc.detail("Nothing stored encrypted can be saved or read")},
    )


@app.exception_handler(RequestValidationError)
async def _validation_error_without_values(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's default 422, minus ``input``, on every route.

    ``input`` quotes what was sent: the rejected value, the whole body when
    a field is missing, the raw bytes when the content type is not JSON. A
    body here can be a password or a provider key, and a response goes
    through whatever proxy or error tracker logs it. ``type``, ``loc`` and
    ``msg`` still say what is wrong and where; nothing reads ``input``.
    """
    errors = [{k: v for k, v in error.items() if k != "input"} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


# E-5.5: per-route + per-tier rate limiting. Disabled in tests via
# RATE_LIMIT_ENABLED=False (set automatically in conftest.py).
# Added BEFORE CORS on purpose: Starlette makes the last-added middleware the
# outermost, and CORS must wrap the limiter. The other way round, a 429 went
# out without CORS headers (the browser reported a CORS failure, not a rate
# limit) and preflight OPTIONS requests were themselves rate-limited.
# Found 2026-10-19 verifying S-1.18.2.
app.add_middleware(RateLimitMiddleware)
# T-4.11.3.3: the origins come from APP_BASE_URL and
# OAUTH_ALLOWED_REDIRECT_ORIGINS, the list OAuth start checks
# (app/utils/app_origins.py), no longer from a list written here.
app.add_middleware(AppOriginsCORSMiddleware)
# T-4.11.2.1: added last, so outermost, so a 429 and a preflight carry it too.
app.add_middleware(ContentSecurityPolicyMiddleware)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(auth.router, prefix="/api/v1")
app.include_router(credentials.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(mfa.router, prefix="/api/v1")
app.include_router(oauth.router, prefix="/api/v1")
app.include_router(onboarding.router, prefix="/api/v1")
app.include_router(suggestions.router, prefix="/api/v1")
app.include_router(saved_searches.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(echo_connectors.router, prefix="/api/v1")
app.include_router(echo_signals.router, prefix="/api/v1")
app.include_router(echo_drafts.router, prefix="/api/v1")
app.include_router(echo_voice_test.router, prefix="/api/v1")
app.include_router(echo_cards.router, prefix="/api/v1")
app.include_router(echo.router, prefix="/api/v1")
app.include_router(author.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(job_templates.router, prefix="/api/v1")
app.include_router(channels.router, prefix="/api/v1")
app.include_router(shelves.router, prefix="/api/v1")
app.include_router(tags.router, prefix="/api/v1")
app.include_router(qa.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(reports.markdown_router, prefix="/api/v1")
app.include_router(library.router, prefix="/api/v1")
app.include_router(qa_history.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(frames.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(notes.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(exports.router, prefix="/api/v1")
app.include_router(llm_settings.router, prefix="/api/v1")
app.include_router(usage.router, prefix="/api/v1")
app.include_router(ws.router)
