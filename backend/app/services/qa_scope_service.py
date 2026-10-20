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
from app.services import library_query_service, shelf_service

logger = logging.getLogger(__name__)

# Keys that restrict what a question may retrieve.
NARROWING_KEYS = frozenset({"shelf_id"})
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


def resolve_document_ids(db: Session, tenant_id: str, scope: QAScope | dict | None) -> list[str]:
    """The document ids a question asked over ``scope`` may retrieve from,
    always inside the tenant's visible set. ``[]`` means nothing.

    Raises ``ScopeNotFound`` for a shelf that is not the tenant's and
    ``UnknownScopeKey`` for a key this build cannot resolve.
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
    return library_query_service.document_ids(db, tenant_id, **filters)
