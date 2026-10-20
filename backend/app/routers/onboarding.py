"""``/auth/me/onboarding`` — the first-run wizard's state (S-8.10.1).

A separate router so the auth router stays as it is. Both routes act on the
caller only; there is no way to read or write another account's state.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.onboarding import OnboardingPatch, OnboardingResponse
from app.services import onboarding_service

router = APIRouter(prefix="/auth/me/onboarding", tags=["onboarding"])


@router.get("", response_model=OnboardingResponse)
def get_onboarding(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OnboardingResponse:
    return OnboardingResponse(**onboarding_service.payload(db, current_user))


@router.patch("", response_model=OnboardingResponse)
def patch_onboarding(
    body: OnboardingPatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OnboardingResponse:
    try:
        data = onboarding_service.update(
            db,
            current_user,
            step=body.step,
            channels=body.channels,
            first_job_id=body.first_job_id,
            completed=body.completed,
            dismissed=body.dismissed,
            checklist_dismissed=body.checklist_dismissed,
            request=request,
        )
    except onboarding_service.OnboardingError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return OnboardingResponse(**data)
