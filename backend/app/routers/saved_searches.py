"""``/saved-searches`` — pinned library questions on a schedule (S-8.3.2).

Plan: docs/plans/m3-saved-searches-alerts.md. Every route acts on the
caller's own rows and needs the ``saved_searches`` tier feature (Pro and
Studio). The schedule is a ``scheduled_runs`` row the service keeps in step.
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.user import User
from app.schemas.saved_search import (
    RunNowResponse,
    SavedSearchCreate,
    SavedSearchList,
    SavedSearchResponse,
    SavedSearchUpdate,
)
from app.services import quota_metering_service, saved_search_service, task_routing_service
from app.services.tier_service import require_feature

router = APIRouter(prefix="/saved-searches", tags=["saved-searches"])

SAVED_SEARCHES = require_feature(saved_search_service.FEATURE)


def _errors(exc: Exception) -> HTTPException:
    if isinstance(exc, saved_search_service.ScopeNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, saved_search_service.CapReached):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


_KNOWN = (
    saved_search_service.SavedSearchError,
    saved_search_service.ScopeNotFound,
    saved_search_service.CapReached,
)


def _own_or_404(db: Session, user: User, saved_search_id: str):
    ss = saved_search_service.get_for(db, user.id, saved_search_id)
    if ss is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return ss


@router.get("", response_model=SavedSearchList)
def list_saved_searches(db: Session = Depends(get_db), current_user: User = Depends(SAVED_SEARCHES)):
    rows = saved_search_service.list_for(db, current_user.id)
    return SavedSearchList(
        items=[SavedSearchResponse(**saved_search_service.to_dict(db, r)) for r in rows],
        active=sum(1 for r in rows if r.enabled),
        cap=saved_search_service.active_cap(current_user),
    )


@router.post("", response_model=SavedSearchResponse, status_code=status.HTTP_201_CREATED)
def create_saved_search(
    body: SavedSearchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(SAVED_SEARCHES),
):
    try:
        ss = saved_search_service.create(
            db,
            current_user,
            question=body.question,
            cadence=body.cadence.model_dump(exclude_none=True),
            answer_language=body.answer_language,
            scope=body.scope.model_dump() if body.scope else None,
            notify_email=body.notify_email,
        )
    except _KNOWN as exc:
        raise _errors(exc)
    return SavedSearchResponse(**saved_search_service.to_dict(db, ss))


@router.get("/{saved_search_id}", response_model=SavedSearchResponse)
def get_saved_search(
    saved_search_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(SAVED_SEARCHES),
):
    return SavedSearchResponse(**saved_search_service.to_dict(db, _own_or_404(db, current_user, saved_search_id)))


@router.patch("/{saved_search_id}", response_model=SavedSearchResponse)
def update_saved_search(
    saved_search_id: str,
    body: SavedSearchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(SAVED_SEARCHES),
):
    ss = _own_or_404(db, current_user, saved_search_id)
    kwargs = {}
    if "scope" in body.model_fields_set:
        kwargs["scope"] = body.scope.model_dump() if body.scope else None
    try:
        ss = saved_search_service.update(
            db,
            current_user,
            ss,
            question=body.question,
            cadence=body.cadence.model_dump(exclude_none=True) if body.cadence else None,
            answer_language=body.answer_language,
            notify_email=body.notify_email,
            enabled=body.enabled,
            **kwargs,
        )
    except _KNOWN as exc:
        raise _errors(exc)
    return SavedSearchResponse(**saved_search_service.to_dict(db, ss))


@router.delete("/{saved_search_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_search(
    saved_search_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(SAVED_SEARCHES),
):
    saved_search_service.delete(db, _own_or_404(db, current_user, saved_search_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{saved_search_id}/run-now", response_model=RunNowResponse, status_code=status.HTTP_202_ACCEPTED)
def run_saved_search_now(
    saved_search_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(SAVED_SEARCHES),
):
    """Queue a run outside the schedule. The quota is checked here as well as
    in the run, so an exhausted month answers 429 now instead of a silent
    skip later (D-045)."""
    ss = _own_or_404(db, current_user, saved_search_id)
    quota_metering_service.enforce_quota_or_raise(db, current_user, saved_search_service.QUOTA_RESOURCE)
    from app.tasks.saved_search_tasks import run_saved_search

    task_routing_service.dispatch_for_user(run_saved_search, current_user, ss.id, trigger="manual")
    return RunNowResponse(status="queued")
