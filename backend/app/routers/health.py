from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import settings
from app.schemas.quota import QuotaStatus
from app.services import quota_service
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
    - ``playwright_fallback_enabled``: ``ARTICLE_PLAYWRIGHT_ENABLED``
      is True (FB / IG SPA-shell paste-mode works; operator has
      installed ``pratidhvani[spa]`` extras + ``playwright install
      chromium``).
    - ``whisper_transcribe_enabled``: ``OPENAI_API_KEY`` is set
      (podcast / YouTube fallback transcription works).
    """
    return {
        "twitter_search_enabled": bool(settings.TWITTER_BEARER_TOKEN),
        "article_search_enabled": bool(settings.BRAVE_SEARCH_API_KEY),
        "playwright_fallback_enabled": bool(settings.ARTICLE_PLAYWRIGHT_ENABLED),
        "whisper_transcribe_enabled": bool(settings.OPENAI_API_KEY),
    }


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": "Pratidhvani",
        "llm": _STATUS.summary(),
        "capabilities": _capabilities(),
    }


@router.get("/health/llm")
def health_llm():
    """Detailed per-use-case LLM probe status."""
    return _STATUS.as_dict()


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
