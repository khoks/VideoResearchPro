import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.routers import admin, auth, channels, health, jobs, library, qa, ws

# Ensure all app.* loggers emit at INFO level.
# uvicorn sets up root logger handlers; this just lowers the threshold for our loggers.
logging.getLogger("app").setLevel(logging.INFO)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables and data directories
    Base.metadata.create_all(bind=engine)
    os.makedirs(settings.REPORTS_DIR, exist_ok=True)
    os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)
    logger.info("VideoResearchPro startup complete")
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

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(auth.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(channels.router, prefix="/api/v1")
app.include_router(qa.router, prefix="/api/v1")
app.include_router(library.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(ws.router)
