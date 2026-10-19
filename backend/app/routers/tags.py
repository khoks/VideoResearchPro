"""Tags REST (S-8.1.3 / E-8.1).

`/tags` manages the caller's tags; applying a tag to a document lives under
`/library/videos/{document_id}/tags/{tag_id}` in `routers/library.py`.
Tags are not tier-gated: they cost the operator nothing (the M6 plan's
reasoning for templates applies), and the `shelves` capability is about
grouping runs. Every id is tenant-scoped; a foreign one is a 404.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.tag import TagCreate, TagResponse, TagUpdate
from app.services import tag_service
from app.services.tag_service import MergeIntoSelf, TagNameTaken

router = APIRouter(
    prefix="/tags",
    tags=["tags"],
    dependencies=[Depends(get_current_user)],
)


def _tag_or_404(db: Session, tag_id: str, tenant_id: str):
    tag = tag_service.get_tag(db, tag_id, tenant_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


def _conflict(name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"You already have a tag named '{name}'.",
    )


@router.get("", response_model=list[TagResponse])
def list_tags(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return tag_service.tags_to_dicts(db, current_user.id, tag_service.list_tags(db, current_user.id))


@router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
def create_tag(
    body: TagCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        tag = tag_service.create_tag(db, current_user.id, body.name, body.color)
    except TagNameTaken:
        raise _conflict(body.name)
    return tag_service.tag_to_dict(tag, 0)


@router.put("/{tag_id}", response_model=TagResponse)
def update_tag(
    tag_id: str,
    body: TagUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tag = _tag_or_404(db, tag_id, current_user.id)
    kwargs: dict = {}
    if body.name is not None:
        kwargs["name"] = body.name
    if body.color is not None:
        kwargs["color"] = body.color
    try:
        tag = tag_service.update_tag(db, tag, **kwargs)
    except TagNameTaken:
        raise _conflict(body.name or "")
    return tag_service.tags_to_dicts(db, current_user.id, [tag])[0]


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: str,
    into: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a tag. With ``?into=<tag_id>`` it is a merge instead: every
    document carrying this tag gets the other one, then this tag goes."""
    tag = _tag_or_404(db, tag_id, current_user.id)
    if into is None:
        tag_service.delete_tag(db, tag)
        return
    target = _tag_or_404(db, into, current_user.id)
    try:
        tag_service.merge_tag(db, tag, target)
    except MergeIntoSelf:
        raise HTTPException(status_code=400, detail="A tag cannot be merged into itself.")
