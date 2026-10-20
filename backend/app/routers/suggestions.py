"""``/suggestions`` — "You might ask…" (S-8.4.1, plan docs/plans/m4-question-suggestions.md)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.suggestions import SuggestionFeedback, SuggestionsResponse
from app.services import audit_service, suggestion_service
from app.services.llm_smoke import _STATUS

router = APIRouter(prefix="/suggestions", tags=["suggestions"])

#: Fail-soft like the era extractor: a failed probe turns the generator off
#: (the reader's past questions still come back) rather than gating a
#: health feature, so it is deliberately not in FEATURE_TO_USE_CASES.
USE_CASE = suggestion_service.USE_CASE


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, suggestion_service.ContextError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, suggestion_service.ContextNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


_CONTEXT_ERRORS = (
    suggestion_service.ContextError,
    suggestion_service.ContextNotFound,
    suggestion_service.ContextNotReady,
)


@router.get("", response_model=SuggestionsResponse)
def get_suggestions(
    request: Request,
    context: str = Query(..., max_length=120, description="job:<id>, document:<id> or library"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuggestionsResponse:
    available = _STATUS.is_use_case_available(USE_CASE)
    try:
        payload = suggestion_service.suggestions_for(
            db, current_user, context, generator_available=available
        )
    except _CONTEXT_ERRORS as exc:
        raise _http_error(exc)
    audit_service.record(
        db,
        event=audit_service.Event.SUGGESTION_SHOWN,
        user_id=current_user.id,
        request=request,
        metadata={
            "context": payload["context"],
            "count": len(payload["suggestions"]),
            "cached": payload["cached"],
            "generated": payload["generated"],
        },
    )
    return SuggestionsResponse(**payload)


@router.post("/feedback", status_code=204)
def suggestion_feedback(
    body: SuggestionFeedback,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """A suggestion was used: ``fill`` (into the composer) or ``ask``."""
    try:
        key = suggestion_service.check_context(db, current_user, body.context)
    except _CONTEXT_ERRORS as exc:
        raise _http_error(exc)
    audit_service.record(
        db,
        event=audit_service.Event.SUGGESTION_CLICKED,
        user_id=current_user.id,
        request=request,
        metadata={
            "context": key,
            "action": body.action,
            "source": body.source,
            "question": body.question,
        },
    )
    return Response(status_code=204)
