from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import settings
from app.schemas.quota import QuotaStatus
from app.services import quota_service
from app.services.llm_smoke import _STATUS as _LLM_STATUS

router = APIRouter()


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": "VideoResearchPro",
        "llm": _LLM_STATUS.summary(),
    }


@router.get("/health/llm")
def llm_health():
    """Per-use-case LLM availability from the most recent smoke probe."""
    return _LLM_STATUS.as_dict()


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
