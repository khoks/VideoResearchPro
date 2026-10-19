"""Echo's private Chroma collections — the erasure side (S-3.10.2).

Echo keeps personal vectors apart from the shared transcript collection:
``shares_global`` (shares, written by S-3.7.2) and ``personal_context_global``
(facts, written by S-3.3.3). Both carry ``tenant_id`` metadata and every query
against them filters on it, the ``qa_library_global`` pattern.

This module owns only what erasure and the footprint check need: find a
collection if it exists, count a tenant's vectors, delete a tenant's or one
share's vectors. It never creates a collection — deleting from a collection
that was never written is a no-op, not an error — and it never embeds, so it
does not load the sentence-transformer. It deliberately does not live in
``chroma_service``: that module is the retrieval path, and Echo's erasure must
not depend on retrieval-side changes.
"""
from __future__ import annotations

import logging

import chromadb

from app.config import settings
from app.services.chroma_service import get_chroma_client

logger = logging.getLogger(__name__)


def echo_collection_names() -> tuple[str, ...]:
    """Every Chroma collection that can hold Echo data. A new Echo collection
    must be added here, or the full delete will leave its vectors behind."""
    return (
        settings.CHROMA_SHARES_COLLECTION_NAME,
        settings.CHROMA_PERSONAL_CONTEXT_COLLECTION_NAME,
    )


def share_vector_id(share_id: str) -> str:
    """The id S-3.7.2 must use when it embeds a share (one vector per share)."""
    return f"share:{share_id}"


def _existing(name: str) -> chromadb.Collection | None:
    client = get_chroma_client()
    try:
        names = {c if isinstance(c, str) else c.name for c in client.list_collections()}
    except Exception:
        logger.exception("echo_vectors: could not list Chroma collections")
        raise
    if name not in names:
        return None
    return client.get_collection(name=name)


def count_tenant_vectors(tenant_id: str) -> dict[str, int]:
    """Vectors attributed to ``tenant_id`` in each Echo collection."""
    out: dict[str, int] = {}
    for name in echo_collection_names():
        col = _existing(name)
        if col is None:
            out[name] = 0
            continue
        got = col.get(where={"tenant_id": tenant_id}, include=[])
        out[name] = len(got.get("ids") or [])
    return out


def delete_tenant_vectors(tenant_id: str) -> dict[str, int]:
    """Delete every vector attributed to ``tenant_id`` from every Echo
    collection. Returns how many were removed per collection. Raises on a
    Chroma failure so the caller can stop before it deletes the rows that
    would let a retry find these vectors again."""
    if not tenant_id:
        raise ValueError("tenant_id is required; an empty filter would match everyone")
    removed: dict[str, int] = {}
    for name in echo_collection_names():
        col = _existing(name)
        if col is None:
            removed[name] = 0
            continue
        ids = col.get(where={"tenant_id": tenant_id}, include=[]).get("ids") or []
        if ids:
            col.delete(ids=ids)
        removed[name] = len(ids)
    return removed


def delete_share_vector(tenant_id: str, share_id: str) -> int:
    """Delete one share's vector, only if it belongs to ``tenant_id``."""
    col = _existing(settings.CHROMA_SHARES_COLLECTION_NAME)
    if col is None:
        return 0
    got = col.get(ids=[share_vector_id(share_id)], include=["metadatas"])
    ids = [
        i
        for i, meta in zip(got.get("ids") or [], got.get("metadatas") or [])
        if (meta or {}).get("tenant_id") == tenant_id
    ]
    if ids:
        col.delete(ids=ids)
    return len(ids)
