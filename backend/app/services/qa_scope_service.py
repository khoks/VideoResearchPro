"""Read, write and resolve the scope of a library question (S-8.1.4).

The shape is documented in ``app/schemas/qa_scope.py``. Three rules matter:

1. A scope only ever NARROWS the reader's visible set (D-063 / D-070).
2. A scope that resolves to no documents retrieves nothing. The caller passes
   the empty list on to the agent, whose retrieval treats ``[]`` as "nothing"
   and only ``None`` as unrestricted; no user-facing caller passes ``None``.
3. A key the resolver does not know is refused, never ignored, because
   ignoring an unknown narrowing key would widen the question.

Saved searches (S-8.3.2) store and resolve the same shape with these helpers.
"""
import json
import logging

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.schemas.qa_scope import QAScope
from app.services import library_query_service, shelf_service, visibility_service

logger = logging.getLogger(__name__)

# Keys that restrict what a question may retrieve.
NARROWING_KEYS = frozenset({"shelf_id", "document_id"})
# Keys that only record where an exchange came from.
PROVENANCE_KEYS = frozenset({"saved_search_id"})


class ScopeNotFound(Exception):
    """A scope names something that is not the reader's (or no longer exists).
    Raised as one error whatever the cause, so a foreign id and a missing one
    are indistinguishable."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class UnknownScopeKey(ValueError):
    """The scope carries a key this build cannot resolve."""


def _as_dict(scope: QAScope | dict | None) -> dict:
    if scope is None:
        return {}
    data = scope.model_dump() if isinstance(scope, QAScope) else dict(scope)
    return {k: v for k, v in data.items() if v is not None}


def dump(scope: QAScope | dict | None) -> str | None:
    """The column value: ``None`` for the whole library, else compact JSON
    with sorted keys (so equal scopes store equal strings)."""
    data = _as_dict(scope)
    if not data:
        return None
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def load(raw: str | None) -> QAScope | None:
    """The stored scope, or ``None`` for the whole library. Unknown keys are
    kept. A malformed value is logged and read as ``None``: it is only ever
    displayed from here, never re-resolved."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("Unreadable scope_json %r", raw[:200])
        return None
    if not isinstance(data, dict):
        logger.warning("scope_json is not an object: %r", raw[:200])
        return None
    try:
        scope = QAScope.model_validate(data)
    except ValidationError:
        logger.warning("scope_json does not match QAScope: %r", raw[:200])
        return None
    return scope if _as_dict(scope) else None


def narrowing(scope: QAScope | dict | None) -> dict:
    """The keys that restrict retrieval (everything but provenance)."""
    return {k: v for k, v in _as_dict(scope).items() if k not in PROVENANCE_KEYS}


def note_target_keys(
    db: Session, tenant_id: str, scope: QAScope | dict | None, document_ids: list[str]
) -> list[str] | None:
    """Which of the asker's notes a question over ``scope`` may draw (S-8.5.2
    keys, ``"<type>:<id>"``). ``None`` for the whole library: every note.

    A shelf draws what job Q&A would draw for each of its runs (notes on the
    run, its documents in scope and their knowledge reports, its answers and
    its channels) plus notes on answers asked on this shelf before. One
    source (T-8.4.2.4) draws the notes on that source, its knowledge report
    and its channel, plus notes on answers asked about it before; it is the
    narrowest scope, so with a shelf as well it draws only those. Call after
    ``resolve_document_ids``, with its result.
    """
    keys = narrowing(scope)
    if not keys:
        return None
    from app.models.job_video import JobVideo
    from app.services import note_index

    allowed = set(document_ids)
    if "document_id" in keys:
        return _document_note_keys(db, tenant_id, str(keys["document_id"]), document_ids)
    shelf = shelf_service.get_shelf(db, str(keys["shelf_id"]), tenant_id)
    if shelf is None:
        raise ScopeNotFound("shelf")
    out: list[str] = []
    for job_id in shelf_service.job_ids_for_shelf(db, shelf.id):
        docs = [
            row[0]
            for row in db.query(JobVideo.document_id).filter(JobVideo.job_id == job_id)
            if row[0] in allowed
        ]
        out.extend(note_index.job_target_keys(db, job_id, docs))
    out.extend(_earlier_answer_keys(db, tenant_id, "shelf_id", shelf.id))
    return list(dict.fromkeys(out))


def exchanges_scoped_to(db: Session, tenant_id: str, key: str, value: str) -> list[tuple[str, str]]:
    """``(id, question)`` of the asker's library exchanges whose stored scope
    has ``key == value``, newest first. ``dump`` writes compact JSON, so the
    LIKE marker finds candidates and the parsed scope confirms each one."""
    from app.models.library_qa_exchange import LibraryQAExchange

    marker = f'"{key}":"{value}"'
    rows = (
        db.query(LibraryQAExchange.id, LibraryQAExchange.question, LibraryQAExchange.scope_json)
        .filter(
            LibraryQAExchange.tenant_id == tenant_id,
            LibraryQAExchange.scope_json.like(f"%{marker}%"),
        )
        .order_by(LibraryQAExchange.created_at.desc())
    )
    out: list[tuple[str, str]] = []
    for qa_id, question, raw in rows:
        scope_row = load(raw)
        if scope_row is not None and getattr(scope_row, key, None) == value:
            out.append((qa_id, question))
    return out


def _earlier_answer_keys(db: Session, tenant_id: str, key: str, value: str) -> list[str]:
    """Note keys of the asker's earlier library answers over this scope."""
    from app.services import note_index

    return [
        note_index.target_key("library_qa_exchange", qa_id)
        for qa_id, _ in exchanges_scoped_to(db, tenant_id, key, value)
    ]


def _document_note_keys(db: Session, tenant_id: str, raw_id: str, document_ids: list[str]) -> list[str]:
    """What a question about one source may draw notes from. ``document_ids``
    is what ``resolve_document_ids`` returned for the same scope: empty when
    a shelf in the scope does not hold this source, and then no notes."""
    from app.models.document import Document
    from app.services import note_index

    doc = visibility_service.visible_document(db, tenant_id, raw_id)
    if doc is None:
        raise ScopeNotFound("document")
    if doc.document_id not in set(document_ids):
        return []
    out = [
        note_index.target_key("document", doc.document_id),
        note_index.target_key("knowledge_artifact", doc.document_id),
    ]
    channel_id = db.query(Document.channel_id).filter(Document.document_id == doc.document_id).scalar()
    if channel_id:
        out.append(note_index.target_key("channel", channel_id))
    out.extend(_earlier_answer_keys(db, tenant_id, "document_id", doc.document_id))
    return list(dict.fromkeys(out))


def resolve_document_ids(db: Session, tenant_id: str, scope: QAScope | dict | None) -> list[str]:
    """The document ids a question asked over ``scope`` may retrieve from,
    always inside the tenant's visible set. ``[]`` means nothing.

    Raises ``ScopeNotFound`` for a shelf that is not the tenant's or a
    document the tenant cannot see, and ``UnknownScopeKey`` for a key this
    build cannot resolve. A document scope with a shelf as well is the
    intersection: that source if a run on the shelf selected it, else ``[]``.
    """
    keys = narrowing(scope)
    unknown = sorted(set(keys) - NARROWING_KEYS)
    if unknown:
        raise UnknownScopeKey(f"Unknown scope key(s): {', '.join(unknown)}")

    filters: dict = {}
    if "shelf_id" in keys:
        shelf = shelf_service.get_shelf(db, str(keys["shelf_id"]), tenant_id)
        if shelf is None:
            raise ScopeNotFound("shelf")
        filters["job_ids"] = shelf_service.job_ids_for_shelf(db, shelf.id)
    if "document_id" in keys:
        # T-8.4.2.4: one source. By its primary key or its legacy YouTube
        # id, but only one the tenant can see: another reader's source and
        # a missing one are the same "not found".
        doc = visibility_service.visible_document(db, tenant_id, str(keys["document_id"]))
        if doc is None:
            raise ScopeNotFound("document")
        filters["document_id"] = doc.document_id
    return library_query_service.document_ids(db, tenant_id, **filters)
