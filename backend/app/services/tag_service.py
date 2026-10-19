"""Tags — the single accessor for `tags` and `taggings` (S-8.1.3).

Every lookup takes the tenant; foreign ids resolve to ``None`` and the
routers return 404. A document can be tagged only if it is visible to the
tenant (D-063 / D-070, `visibility_service.visible_document_ids`), and every
count and filter re-applies that scope, so a tag never reveals a document
its owner cannot see.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.tag import Tag
from app.models.tagging import TARGET_DOCUMENT, Tagging
from app.services import visibility_service

logger = logging.getLogger(__name__)


class TagNameTaken(Exception):
    """Another tag of this tenant already has the name (case-insensitive)."""


class MergeIntoSelf(Exception):
    """A tag cannot be merged into itself."""


_UNSET = object()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_tag(db: Session, tag_id: str, tenant_id: str) -> Tag | None:
    return db.query(Tag).filter(Tag.id == tag_id, Tag.tenant_id == tenant_id).first()


def list_tags(db: Session, tenant_id: str) -> list[Tag]:
    return (
        db.query(Tag)
        .filter(Tag.tenant_id == tenant_id)
        .order_by(func.lower(Tag.name).asc())
        .all()
    )


def document_counts(db: Session, tenant_id: str, tag_ids: Iterable[str]) -> dict[str, int]:
    """``{tag_id: visible documents carrying it}`` in one query."""
    ids = list(tag_ids)
    if not ids:
        return {}
    rows = (
        db.query(Tagging.tag_id, func.count(Tagging.id))
        .filter(
            Tagging.tag_id.in_(ids),
            Tagging.tenant_id == tenant_id,
            Tagging.target_type == TARGET_DOCUMENT,
            Tagging.target_id.in_(visibility_service.visible_document_ids(db, tenant_id)),
        )
        .group_by(Tagging.tag_id)
        .all()
    )
    return {tag_id: count for tag_id, count in rows}


def tags_for_documents(
    db: Session, tenant_id: str, document_ids: Iterable[str]
) -> dict[str, list[dict]]:
    """``{document_id: [{id, name, color}, ...]}`` — the caller's own tags
    only, A→Z, for one page of library rows in one query."""
    ids = list(document_ids)
    out: dict[str, list[dict]] = {}
    if not ids:
        return out
    rows = (
        db.query(Tagging.target_id, Tag.id, Tag.name, Tag.color)
        .join(Tag, Tag.id == Tagging.tag_id)
        .filter(
            Tagging.tenant_id == tenant_id,
            Tag.tenant_id == tenant_id,
            Tagging.target_type == TARGET_DOCUMENT,
            Tagging.target_id.in_(ids),
        )
        .order_by(func.lower(Tag.name).asc())
        .all()
    )
    for doc_id, tag_id, name, color in rows:
        out.setdefault(doc_id, []).append({"id": tag_id, "name": name, "color": color})
    return out


def tagged_document_ids(db: Session, tenant_id: str, tag_id: str):
    """Subquery of document ids carrying ``tag_id`` for ``tenant_id``. A
    foreign tag id matches nothing, because the tenant is in the filter."""
    return db.query(Tagging.target_id).filter(
        Tagging.tag_id == tag_id,
        Tagging.tenant_id == tenant_id,
        Tagging.target_type == TARGET_DOCUMENT,
    )


def visible_document(db: Session, tenant_id: str, document_id: str) -> Document | None:
    """The document, if the tenant may see it — the precondition for tagging."""
    return (
        db.query(Document)
        .filter(
            Document.document_id == document_id,
            Document.document_id.in_(visibility_service.visible_document_ids(db, tenant_id)),
        )
        .first()
    )


def _name_taken(db: Session, tenant_id: str, name: str, *, exclude_id: str | None = None) -> bool:
    q = db.query(Tag.id).filter(Tag.tenant_id == tenant_id, func.lower(Tag.name) == name.lower())
    if exclude_id is not None:
        q = q.filter(Tag.id != exclude_id)
    return db.query(q.exists()).scalar() is True


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def create_tag(db: Session, tenant_id: str, name: str, color: str = "default") -> Tag:
    if _name_taken(db, tenant_id, name):
        raise TagNameTaken(name)
    tag = Tag(tenant_id=tenant_id, name=name, color=color)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def update_tag(
    db: Session, tag: Tag, *, name: str | object = _UNSET, color: str | object = _UNSET
) -> Tag:
    """Rename keeps the id, so every tagging follows the new name."""
    if name is not _UNSET:
        assert isinstance(name, str)
        if _name_taken(db, tag.tenant_id, name, exclude_id=tag.id):
            raise TagNameTaken(name)
        tag.name = name
    if color is not _UNSET:
        assert isinstance(color, str)
        tag.color = color
    db.commit()
    db.refresh(tag)
    return tag


def delete_tag(db: Session, tag: Tag) -> None:
    """Remove the tag and every tagging of it. Documents are never touched."""
    db.delete(tag)
    db.commit()


def merge_tag(db: Session, source: Tag, target: Tag) -> Tag:
    """Fold ``source`` into ``target``: its taggings move over (ones the
    target already has are dropped, not duplicated) and ``source`` goes.
    Both must belong to the same tenant — the router resolves both through
    ``get_tag`` with the caller's tenant."""
    if source.id == target.id:
        raise MergeIntoSelf(source.id)
    assert source.tenant_id == target.tenant_id
    already = {
        (row.target_type, row.target_id)
        for row in db.query(Tagging.target_type, Tagging.target_id).filter(
            Tagging.tag_id == target.id
        )
    }
    to_move = [
        row.id
        for row in db.query(Tagging.id, Tagging.target_type, Tagging.target_id).filter(
            Tagging.tag_id == source.id
        )
        if (row.target_type, row.target_id) not in already
    ]
    if to_move:
        db.query(Tagging).filter(Tagging.id.in_(to_move)).update(
            {Tagging.tag_id: target.id}, synchronize_session=False
        )
    # Reload so the cascade on delete only sees the duplicates left behind.
    db.expire_all()
    db.delete(db.get(Tag, source.id))
    db.commit()
    db.refresh(target)
    logger.info(
        "tags: tenant %s merged tag %s into %s", target.tenant_id[:8], source.id, target.id
    )
    return target


def apply_tag(db: Session, tag: Tag, document_id: str) -> bool:
    """Tag a document. Idempotent: False when it already carried the tag.
    The caller checks visibility first (``visible_document``)."""
    exists = (
        db.query(Tagging.id)
        .filter(
            Tagging.tag_id == tag.id,
            Tagging.target_type == TARGET_DOCUMENT,
            Tagging.target_id == document_id,
        )
        .first()
    )
    if exists is not None:
        return False
    db.add(
        Tagging(
            tag_id=tag.id,
            tenant_id=tag.tenant_id,
            target_type=TARGET_DOCUMENT,
            target_id=document_id,
        )
    )
    db.commit()
    return True


def remove_tag(db: Session, tag: Tag, document_id: str) -> bool:
    row = (
        db.query(Tagging)
        .filter(
            Tagging.tag_id == tag.id,
            Tagging.target_type == TARGET_DOCUMENT,
            Tagging.target_id == document_id,
        )
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

def tag_to_dict(tag: Tag, document_count: int) -> dict:
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "document_count": document_count,
        "created_at": tag.created_at,
    }


def tags_to_dicts(db: Session, tenant_id: str, tags: list[Tag]) -> list[dict]:
    counts = document_counts(db, tenant_id, [t.id for t in tags])
    return [tag_to_dict(t, counts.get(t.id, 0)) for t in tags]
