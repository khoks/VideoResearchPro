"""``GET /api/v1/search`` — grouped, tenant-scoped keyword search (S-8.2.1 / M2).

The endpoint the command palette (S-8.2.2) will call; useful on its own for
any page's search box. One query, up to five groups (jobs, documents,
channels, qa, knowledge), each capped at ``limit`` items. Every group is
scoped to the caller: a tenant with nothing visible gets empty groups,
never everything (D-063). Engine and ranking: ``services/search_service``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.search import SearchResponse
from app.services import search_service

router = APIRouter(prefix="/search", tags=["search"])


def _parse_types(raw: str | None) -> list[str] | None:
    if raw is None or not raw.strip():
        return None
    wanted = [t.strip().lower() for t in raw.split(",") if t.strip()]
    unknown = sorted(set(wanted) - set(search_service.SEARCH_TYPES))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown search type(s) {unknown}; expected a subset of {list(search_service.SEARCH_TYPES)}",
        )
    return wanted


@router.get("", response_model=SearchResponse)
def global_search(
    q: str = Query(..., min_length=1, max_length=200, description="Free text; tokens of 3+ characters match as substrings"),
    types: str | None = Query(None, description="Comma-separated subset of jobs,documents,channels,qa,knowledge"),
    limit: int = Query(5, ge=1, le=25, description="Max items per group"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SearchResponse:
    wanted = _parse_types(types)
    result = search_service.search(db, current_user.id, q, types=wanted, limit=limit)
    return SearchResponse(**result)
