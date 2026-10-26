from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_db
from app.schemas.quota import QuotaStatus
from app.services import job_source_types, quota_service, scheduler_service, search_service
from app.services.llm_smoke import _STATUS

router = APIRouter()


def _capabilities() -> dict[str, bool]:
    """Per-S-1.5.9 (BYOK Twitter capability flag) and beyond, surface
    which opt-in features are enabled so the frontend can decide which
    UI surfaces to expose without inspecting env state directly.

    - ``twitter_search_enabled``: ``TWITTER_BEARER_TOKEN`` is set
      (Topic-search-with-Twitter source-type checkbox lights up).
    - ``article_search_enabled``: ``BRAVE_SEARCH_API_KEY`` is set
      (article search via Brave is available).
    - ``reddit_search_enabled``: ``REDDIT_CLIENT_ID`` and
      ``REDDIT_CLIENT_SECRET`` are set (S-1.5.13).
    - ``playwright_fallback_enabled``: ``ARTICLE_PLAYWRIGHT_ENABLED``
      is True (FB / IG SPA-shell paste-mode works; operator has
      installed ``pratidhvani[spa]`` extras + ``playwright install
      chromium``).
    - ``whisper_transcribe_enabled``: ``OPENAI_API_KEY`` is set
      (podcast / YouTube fallback transcription works).

    The three source-search flags come from ``job_source_types``, the
    same check that refuses an unconfigured type on ``POST /jobs``, so the
    submit form never offers what the API would reject.
    """
    return {
        **job_source_types.capabilities(),
        "playwright_fallback_enabled": bool(settings.ARTICLE_PLAYWRIGHT_ENABLED),
        "whisper_transcribe_enabled": bool(settings.OPENAI_API_KEY),
        # S-1.18.2: the install-wide R1 switch. Off means the job toggle and
        # "Capture frames" are disabled; stored frames still show.
        "visual_analysis_enabled": bool(settings.VISUAL_ENABLED),
    }


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": "Pratidhvani",
        "llm": _STATUS.summary(),
        "capabilities": _capabilities(),
        # S-8.2.1: "fts5" when SQLite has FTS5 (ranked substring search),
        # "like" on the fallback path, so the UI can label it.
        "search_backend": search_service.current_backend(),
    }


@router.get("/health/llm")
def health_llm():
    """Detailed per-use-case LLM probe status."""
    return _STATUS.as_dict()


@router.get("/health/scheduler")
def scheduler_status(db: Session = Depends(get_db)) -> dict:
    """S-8.3.1: scheduler configuration, the kinds THIS process can
    dispatch, and `scheduled_runs` row counts (total / enabled / due /
    claimed). `last_run_at` is the newest dispatch across all rows — the
    cheapest "is beat alive" signal once anything is scheduled. Note the
    API process's kind list can differ from the worker's; the worker is
    the one that dispatches."""
    return scheduler_service.status(db)


@router.get("/health/quota", response_model=QuotaStatus)
def quota_status() -> QuotaStatus:
    """Report today's YouTube Data API quota usage."""
    used = quota_service.get_today_usage()
    daily_limit = settings.YOUTUBE_DAILY_QUOTA
    return QuotaStatus(
        date=datetime.now(timezone.utc).date().isoformat(),
        used=used,
        daily_limit=daily_limit,
        remaining=max(0, daily_limit - used),
    )
