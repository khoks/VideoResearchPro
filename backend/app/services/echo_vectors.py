"""Echo's private Chroma collections — the erasure side (S-3.10.2).

Echo keeps personal vectors apart from the shared transcript collection:
``shares_global`` (shares, written by S-3.7.2) and ``personal_context_global``
(facts, written by S-3.3.3). Both carry ``tenant_id`` metadata and every query
against them filters on it, the ``qa_library_global`` pattern.

The erasure side (find a collection if it exists, count a tenant's vectors,
delete a tenant's or one share's vectors) never creates a collection —
deleting from a collection that was never written is a no-op, not an error —
and never embeds, so it does not load the sentence-transformer. The one
write, ``upsert_share_vector`` (S-3.7.2), creates ``shares_global`` with the
shared embedder on first use. It deliberately does not live in
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


def delete_share_vectors(tenant_id: str, share_ids: list[str], *, chunk: int = 2000) -> int:
    """Delete many shares' vectors, only those belonging to ``tenant_id``."""
    col = _existing(settings.CHROMA_SHARES_COLLECTION_NAME)
    if col is None or not share_ids:
        return 0
    removed = 0
    for i in range(0, len(share_ids), chunk):
        got = col.get(ids=[share_vector_id(s) for s in share_ids[i : i + chunk]], include=["metadatas"])
        ids = [
            vid
            for vid, meta in zip(got.get("ids") or [], got.get("metadatas") or [])
            if (meta or {}).get("tenant_id") == tenant_id
        ]
        if ids:
            col.delete(ids=ids)
            removed += len(ids)
    return removed


def upsert_share_vector(share_id: str, text: str, metadata: dict) -> str:
    """Embed one share (S-3.7.2) under ``share_vector_id`` with its tenant in
    the metadata, the only shape the deletes above look for. Returns the
    vector id. Raises on a Chroma failure; the caller decides fail-soft."""
    tenant_id = (metadata or {}).get("tenant_id")
    if not tenant_id:
        raise ValueError("a share vector needs tenant_id metadata")
    client = get_chroma_client()
    col = client.get_or_create_collection(
        name=settings.CHROMA_SHARES_COLLECTION_NAME,
        metadata={"scope": "echo_shares"},
        embedding_function=_embedding_function(),
    )
    vid = share_vector_id(share_id)
    clean = {k: v for k, v in metadata.items() if v is not None}
    col.upsert(ids=[vid], documents=[text], metadatas=[clean])
    return vid


def upsert_share_vectors(items: list[tuple[str, str, dict]]) -> list[str]:
    """Batch form of ``upsert_share_vector`` for imports (S-3.7.5): one
    embedder pass over ``(share_id, text, metadata)`` items. Same ids and
    metadata shape, so the per-share and whole-brain deletes find them."""
    if not items:
        return []
    if any(not (meta or {}).get("tenant_id") for _, _, meta in items):
        raise ValueError("a share vector needs tenant_id metadata")
    client = get_chroma_client()
    col = client.get_or_create_collection(
        name=settings.CHROMA_SHARES_COLLECTION_NAME,
        metadata={"scope": "echo_shares"},
        embedding_function=_embedding_function(),
    )
    ids = [share_vector_id(sid) for sid, _, _ in items]
    col.upsert(
        ids=ids,
        documents=[text for _, text, _ in items],
        metadatas=[{k: v for k, v in meta.items() if v is not None} for _, _, meta in items],
    )
    return ids


def delete_import_vectors(tenant_id: str, import_id: str) -> int:
    """Remove every vector an import wrote (S-3.7.5), matched on both the
    tenant and the import id. Returns how many were removed."""
    col = _existing(settings.CHROMA_SHARES_COLLECTION_NAME)
    if col is None:
        return 0
    where = {"$and": [{"tenant_id": tenant_id}, {"import_id": import_id}]}
    got = col.get(where=where, include=[])
    ids = got.get("ids") or []
    if ids:
        col.delete(ids=ids)
    return len(ids)


def _embedding_function():
    from app.services import chroma_service

    return chroma_service._get_embedding_function()


def query_share_vectors(tenant_id: str, text: str, n: int = 4) -> list[dict]:
    """The tenant's shares nearest ``text`` (S-3.4.1 grounds drafts with
    them). Fails closed: no tenant raises; every query filters on it, and
    every hit is checked again. Returns ``{"text", "metadata", "distance"}``.
    Never creates the collection."""
    if not tenant_id:
        raise ValueError("tenant_id is required; an unscoped share query would read everyone's inbox")
    col = _existing(settings.CHROMA_SHARES_COLLECTION_NAME)
    if col is None or not (text or "").strip():
        return []
    where = {"tenant_id": tenant_id}
    total = len(col.get(where=where, include=[]).get("ids") or [])
    if total == 0:
        return []
    from app.services import chroma_service

    res = col.query(
        query_embeddings=chroma_service._get_embedding_function()([text]),
        n_results=min(n, total),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return [
        {"text": doc, "metadata": meta or {}, "distance": float(dist)}
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])
        if (meta or {}).get("tenant_id") == tenant_id
    ]
