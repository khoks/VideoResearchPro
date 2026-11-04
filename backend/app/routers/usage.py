"""``GET /api/v1/usage``: the signed-in user's own usage, by feature (E-5.2).

Read-only and scoped to the caller: only rows whose ``tenant_id`` is the
authenticated user's are read. Today and the last 30 days (today included),
in UTC days. Nothing here is a limit (D-111); ``GET /auth/quota`` is still
where caps are reported.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.schemas.usage import UsageSummaryResponse
from app.services import usage_service

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("", response_model=UsageSummaryResponse)
def my_usage(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> UsageSummaryResponse:
    return UsageSummaryResponse(**usage_service.summary(db, current_user.id))
