"""Shelves REST (S-8.1.1 / E-8.1).

Reads are open to every tier so a shelf outlives a downgrade read-only (the
plan's recommended default for its first open question, taken here). Writes
— create, rename, recolour, delete, add or remove a job — are gated on the
`shelves` capability (Pro and Studio, `tier_service.TIER_CAPABILITIES`).

Every lookup is tenant-scoped through `shelf_service` / `job_service`; a
shelf or job that belongs to someone else is a 404, never a 403.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.shelf import (
    ShelfCreate,
    ShelfDetailResponse,
    ShelfResponse,
    ShelfUpdate,
)
from app.services import job_service, shelf_service
from app.services.shelf_service import ForeignJob, ShelfNameTaken
from app.services.tier_service import require_feature

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/shelves",
    tags=["shelves"],
    dependencies=[Depends(get_current_user)],
)

SHELVES_WRITE = require_feature("shelves")


def _shelf_or_404(db: Session, shelf_id: str, tenant_id: str):
    shelf = shelf_service.get_shelf(db, shelf_id, tenant_id)
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf not found")
    return shelf


def _job_or_404(db: Session, job_id: str, tenant_id: str):
    job = job_service.get_job(db, job_id, tenant_id=tenant_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _summary(db: Session, shelf) -> dict:
    return shelf_service.shelf_to_dict(shelf, shelf_service.job_count(db, shelf.id))


@router.get("", response_model=list[ShelfResponse])
def list_shelves(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    shelves = shelf_service.list_shelves(db, current_user.id)
    counts = shelf_service.job_counts(db, [s.id for s in shelves])
    return [shelf_service.shelf_to_dict(s, counts.get(s.id, 0)) for s in shelves]


@router.post("", response_model=ShelfResponse, status_code=status.HTTP_201_CREATED)
def create_shelf(
    body: ShelfCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(SHELVES_WRITE),
):
    try:
        shelf = shelf_service.create_shelf(
            db, current_user.id, body.name, body.description, body.color
        )
    except ShelfNameTaken:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a shelf named '{body.name}'.",
        )
    return _summary(db, shelf)


@router.get("/{shelf_id}", response_model=ShelfDetailResponse)
def get_shelf(
    shelf_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    shelf = _shelf_or_404(db, shelf_id, current_user.id)
    jobs = shelf_service.shelf_jobs(db, shelf)
    payload = shelf_service.shelf_to_dict(shelf, len(jobs))
    payload["jobs"] = [job_service.job_to_response_dict(j) for j in jobs]
    return payload


@router.put("/{shelf_id}", response_model=ShelfResponse)
def update_shelf(
    shelf_id: str,
    body: ShelfUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(SHELVES_WRITE),
):
    shelf = _shelf_or_404(db, shelf_id, current_user.id)
    sent = body.model_fields_set
    kwargs: dict = {}
    if "name" in sent and body.name is not None:
        kwargs["name"] = body.name
    if "description" in sent:
        kwargs["description"] = body.description
    if "color" in sent and body.color is not None:
        kwargs["color"] = body.color
    try:
        shelf = shelf_service.update_shelf(db, shelf, **kwargs)
    except ShelfNameTaken:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a shelf named '{body.name}'.",
        )
    return _summary(db, shelf)


@router.delete("/{shelf_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shelf(
    shelf_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(SHELVES_WRITE),
):
    shelf = _shelf_or_404(db, shelf_id, current_user.id)
    shelf_service.delete_shelf(db, shelf)


@router.post("/{shelf_id}/jobs/{job_id}", response_model=ShelfResponse)
def add_job_to_shelf(
    shelf_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(SHELVES_WRITE),
):
    """Idempotent: adding a job that is already on the shelf is a 200 with
    the unchanged count, not an error."""
    shelf = _shelf_or_404(db, shelf_id, current_user.id)
    job = _job_or_404(db, job_id, current_user.id)
    try:
        shelf_service.add_job(db, shelf, job)
    except ForeignJob:
        # Unreachable through the tenant-scoped lookup above; kept so the
        # service's own guard reads as a 404 rather than a 500 if a future
        # caller bypasses it.
        raise HTTPException(status_code=404, detail="Job not found")
    return _summary(db, shelf)


@router.delete("/{shelf_id}/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_job_from_shelf(
    shelf_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(SHELVES_WRITE),
):
    shelf = _shelf_or_404(db, shelf_id, current_user.id)
    if not shelf_service.remove_job(db, shelf, job_id):
        raise HTTPException(status_code=404, detail="Job is not on this shelf")
