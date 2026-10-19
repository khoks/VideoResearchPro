"""Shelves — the single accessor for `shelves` and `shelf_jobs` (S-8.1.1).

Every lookup takes the tenant. Nothing outside this module queries the two
tables, so a new surface cannot forget the tenant filter the way the library
listing once did (S-5.7.1). Foreign ids resolve to ``None`` and the routers
turn that into a 404; the service never raises for "not yours".

Jobs are resolved by the caller through ``job_service.get_job(db, job_id,
tenant_id=...)`` so the tenant check lives in one place; ``add_job`` still
refuses a job whose ``tenant_id`` differs from the shelf's, as a belt to that
brace.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.shelf import Shelf
from app.models.shelf_job import ShelfJob

logger = logging.getLogger(__name__)


class ShelfError(Exception):
    """Base class for shelf-service failures the router maps to 4xx."""


class ShelfNameTaken(ShelfError):
    """Another shelf of this tenant already has the name (case-insensitive)."""


class ForeignJob(ShelfError):
    """The job belongs to a different tenant than the shelf."""


_UNSET = object()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_shelf(db: Session, shelf_id: str, tenant_id: str) -> Shelf | None:
    return (
        db.query(Shelf)
        .filter(Shelf.id == shelf_id, Shelf.tenant_id == tenant_id)
        .first()
    )


def list_shelves(db: Session, tenant_id: str) -> list[Shelf]:
    return (
        db.query(Shelf)
        .filter(Shelf.tenant_id == tenant_id)
        .order_by(func.lower(Shelf.name).asc())
        .all()
    )


def job_counts(db: Session, shelf_ids: Iterable[str]) -> dict[str, int]:
    """``{shelf_id: number of jobs}`` for the given shelves in one query."""
    ids = list(shelf_ids)
    if not ids:
        return {}
    rows = (
        db.query(ShelfJob.shelf_id, func.count(ShelfJob.job_id))
        .filter(ShelfJob.shelf_id.in_(ids))
        .group_by(ShelfJob.shelf_id)
        .all()
    )
    return {shelf_id: count for shelf_id, count in rows}


def job_count(db: Session, shelf_id: str) -> int:
    return job_counts(db, [shelf_id]).get(shelf_id, 0)


def shelf_jobs(db: Session, shelf: Shelf) -> list[Job]:
    """The shelf's jobs, most recently added first. Only the shelf owner's
    jobs can be on it (``add_job`` guarantees that), so no extra filter."""
    return (
        db.query(Job)
        .join(ShelfJob, ShelfJob.job_id == Job.id)
        .filter(ShelfJob.shelf_id == shelf.id)
        .order_by(ShelfJob.added_at.desc(), Job.created_at.desc())
        .all()
    )


def job_ids_for_shelf(db: Session, shelf_id: str) -> list[str]:
    return [
        row[0]
        for row in db.query(ShelfJob.job_id).filter(ShelfJob.shelf_id == shelf_id)
    ]


def shelves_for_job(db: Session, job_id: str, tenant_id: str) -> list[Shelf]:
    """Shelves of ``tenant_id`` that hold ``job_id``. The tenant filter is on
    the shelf, so a job id guessed from another tenant yields nothing."""
    return (
        db.query(Shelf)
        .join(ShelfJob, ShelfJob.shelf_id == Shelf.id)
        .filter(ShelfJob.job_id == job_id, Shelf.tenant_id == tenant_id)
        .order_by(func.lower(Shelf.name).asc())
        .all()
    )


def _name_taken(
    db: Session, tenant_id: str, name: str, *, exclude_id: str | None = None
) -> bool:
    q = db.query(Shelf.id).filter(
        Shelf.tenant_id == tenant_id,
        func.lower(Shelf.name) == name.lower(),
    )
    if exclude_id is not None:
        q = q.filter(Shelf.id != exclude_id)
    return db.query(q.exists()).scalar() is True


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def create_shelf(
    db: Session,
    tenant_id: str,
    name: str,
    description: str | None = None,
    color: str = "default",
) -> Shelf:
    if _name_taken(db, tenant_id, name):
        raise ShelfNameTaken(name)
    shelf = Shelf(tenant_id=tenant_id, name=name, description=description, color=color)
    db.add(shelf)
    db.commit()
    db.refresh(shelf)
    logger.info("shelves: tenant %s created shelf %s", tenant_id[:8], shelf.id)
    return shelf


def update_shelf(
    db: Session,
    shelf: Shelf,
    *,
    name: str | object = _UNSET,
    description: str | None | object = _UNSET,
    color: str | object = _UNSET,
) -> Shelf:
    """Apply the fields that were sent. Renaming to the same name in a
    different case is allowed (it is the same shelf)."""
    if name is not _UNSET:
        assert isinstance(name, str)
        if _name_taken(db, shelf.tenant_id, name, exclude_id=shelf.id):
            raise ShelfNameTaken(name)
        shelf.name = name
    if description is not _UNSET:
        shelf.description = description  # type: ignore[assignment]
    if color is not _UNSET:
        assert isinstance(color, str)
        shelf.color = color
    db.commit()
    db.refresh(shelf)
    return shelf


def delete_shelf(db: Session, shelf: Shelf) -> None:
    """Remove the shelf and its membership rows. Jobs are never touched."""
    db.delete(shelf)
    db.commit()
    logger.info("shelves: tenant %s deleted shelf %s", shelf.tenant_id[:8], shelf.id)


def add_job(db: Session, shelf: Shelf, job: Job) -> bool:
    """Put ``job`` on ``shelf``. Idempotent: returns True when a row was
    added, False when it was already there."""
    if job.tenant_id != shelf.tenant_id:
        raise ForeignJob(job.id)
    existing = (
        db.query(ShelfJob)
        .filter(ShelfJob.shelf_id == shelf.id, ShelfJob.job_id == job.id)
        .first()
    )
    if existing is not None:
        return False
    db.add(ShelfJob(shelf_id=shelf.id, job_id=job.id))
    db.commit()
    return True


def remove_job(db: Session, shelf: Shelf, job_id: str) -> bool:
    """Take ``job_id`` off ``shelf``. Returns False when it was not there."""
    row = (
        db.query(ShelfJob)
        .filter(ShelfJob.shelf_id == shelf.id, ShelfJob.job_id == job_id)
        .first()
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def shelf_to_dict(shelf: Shelf, count: int) -> dict:
    return {
        "id": shelf.id,
        "name": shelf.name,
        "description": shelf.description,
        "color": shelf.color,
        "job_count": count,
        "created_at": shelf.created_at,
        "updated_at": shelf.updated_at,
    }
