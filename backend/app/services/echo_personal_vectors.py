"""``personal_context_global``: Echo's facts and signals for retrieval (S-3.3.3).

One vector per live fact (``personal_context`` row) and per live voice
signal, with ``tenant_id`` metadata, in ``CHROMA_PERSONAL_CONTEXT_COLLECTION_NAME``
(already swept by the full delete, ``echo_vectors.echo_collection_names``).

**Sync, not per-write bookkeeping.** ``sync_tenant`` compares the tenant's
live rows with the vectors already stored (each carries a hash of the text
it embedded) and embeds only what is new or changed, deleting vectors whose
row is gone, expired, rejected or suppressed. Every write path calls it
after its commit (fact record and delete, signal create, edit and reject,
an extraction run, a note or share delete), so a tombstone's vector is gone
as soon as the tombstone exists, whichever path wrote it; the startup
backfill runs it for every tenant. Fail-soft at the callers: a Chroma
failure never fails the write, and the next sync repairs the gap.

**Reads fail closed.** ``query_personal_context`` refuses an empty tenant and
always filters on it; there is no unscoped query.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.config import settings
from app.models.personal_context import PersonalContext
from app.models.voice_signal import VoiceSignal
from app.services import echo_vectors

logger = logging.getLogger(__name__)

KINDS = ("fact", "signal")


def enabled() -> bool:
    return bool(settings.ECHO_PERSONAL_INDEX_ENABLED)


def fact_vector_id(fact_id: str) -> str:
    return f"fact:{fact_id}"


def signal_vector_id(signal_id: str) -> str:
    return f"signal:{signal_id}"


def _collection(create: bool):
    if not create:
        return echo_vectors._existing(settings.CHROMA_PERSONAL_CONTEXT_COLLECTION_NAME)
    from app.services.chroma_service import get_chroma_client

    return get_chroma_client().get_or_create_collection(
        name=settings.CHROMA_PERSONAL_CONTEXT_COLLECTION_NAME,
        metadata={"scope": "echo_personal_context"},
        embedding_function=echo_vectors._embedding_function(),
    )


def _fact_text(row: PersonalContext) -> str:
    try:
        value = json.loads(row.value)
    except (TypeError, ValueError):
        value = row.value
    shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return f"{row.kind.replace('_', ' ')}: {row.key} — {shown}"


def _signal_text(row: VoiceSignal) -> str:
    from app.services import echo_signal_service

    examples = [e.get("text", "") for e in json.loads(row.examples_json or "[]")][:3]
    layer = "style" if row.signal_type in echo_signal_service.STYLE_TYPES else "personality"
    body = f"{layer} · {row.signal_type.replace('_', ' ')}: {row.value}"
    return body + ("\nExamples: " + " | ".join(examples) if examples else "")


def _hash(text: str, meta: dict) -> str:
    return hashlib.sha256((text + json.dumps(meta, sort_keys=True)).encode("utf-8")).hexdigest()[:32]


def _live_facts(db: Session, tenant_id: str) -> list[PersonalContext]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = db.query(PersonalContext).filter(
        (PersonalContext.tenant_id == tenant_id) | (PersonalContext.user_id == tenant_id)
    )
    out = []
    for r in rows:
        exp = r.expires_at
        if exp is not None and (exp.replace(tzinfo=None) if exp.tzinfo else exp) <= now:
            continue
        out.append(r)
    return out


def _live_signals(db: Session, tenant_id: str) -> list[VoiceSignal]:
    return (
        db.query(VoiceSignal)
        .filter(VoiceSignal.tenant_id == tenant_id, VoiceSignal.suppressed_at.is_(None))
        .all()
    )


def desired(db: Session, tenant_id: str) -> dict[str, tuple[str, dict]]:
    """vector id -> (text, metadata) for everything that should be stored."""
    out: dict[str, tuple[str, dict]] = {}
    for r in _live_facts(db, tenant_id):
        meta = {"tenant_id": tenant_id, "kind": "fact", "row_id": r.id, "fact_kind": r.kind, "source": r.source}
        text = _fact_text(r)
        out[fact_vector_id(r.id)] = (text, {**meta, "content_hash": _hash(text, meta)})
    for r in _live_signals(db, tenant_id):
        meta = {
            "tenant_id": tenant_id,
            "kind": "signal",
            "row_id": r.id,
            "signal_type": r.signal_type,
            "origin": r.origin,
            "weight": float(r.weight),
            **({"language": r.language} if r.language else {}),
            **({"register": r.register} if r.register else {}),
        }
        text = _signal_text(r)
        out[signal_vector_id(r.id)] = (text, {**meta, "content_hash": _hash(text, meta)})
    return out


@dataclass(frozen=True)
class SyncResult:
    upserted: int
    deleted: int
    unchanged: int


def sync_tenant(db: Session, tenant_id: str) -> SyncResult:
    """Make the collection match the tenant's live facts and signals.
    Raises on a Chroma failure; callers decide fail-soft (``sync_soft``)."""
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if not enabled():
        return SyncResult(0, 0, 0)
    want = desired(db, tenant_id)
    col = _collection(create=bool(want))
    if col is None:
        return SyncResult(0, 0, 0)
    got = col.get(where={"tenant_id": tenant_id}, include=["metadatas"])
    have = {i: (m or {}).get("content_hash") for i, m in zip(got.get("ids") or [], got.get("metadatas") or [])}
    stale = [i for i in have if i not in want]
    todo = [i for i, (_, meta) in want.items() if have.get(i) != meta["content_hash"]]
    if stale:
        col.delete(ids=stale)
    if todo:
        col.upsert(ids=todo, documents=[want[i][0] for i in todo], metadatas=[want[i][1] for i in todo])
    return SyncResult(upserted=len(todo), deleted=len(stale), unchanged=len(want) - len(todo))


def sync_soft(db: Session, tenant_id: str) -> SyncResult | None:
    """``sync_tenant`` for write paths: logs and returns None on failure."""
    try:
        return sync_tenant(db, tenant_id)
    except Exception:  # noqa: BLE001
        logger.exception("personal_context_global: sync failed for tenant %s; the next sync repairs it", tenant_id[:8])
        return None


def backfill(session_factory=None) -> dict[str, int]:
    """Startup backfill (the ``note_index.backfill`` pattern): sync every
    tenant with a fact or a signal, plus every tenant that still has vectors
    (so a row deleted while the API was down loses its vector too)."""
    if not enabled():
        return {"tenants": 0, "upserted": 0, "deleted": 0}
    if session_factory is None:
        from app.database import SessionLocal

        session_factory = SessionLocal
    db = session_factory()
    try:
        tenants = {r[0] for r in db.query(PersonalContext.tenant_id).distinct() if r[0]}
        tenants |= {r[0] for r in db.query(PersonalContext.user_id).distinct() if r[0]}
        tenants |= {r[0] for r in db.query(VoiceSignal.tenant_id).distinct() if r[0]}
        # Vectors whose tenant has no row left (deleted while the API was down)
        # still need removing, so look at the collection whatever the rows say.
        col = _collection(create=False)
        if col is not None:
            got = col.get(include=["metadatas"])
            tenants |= {(m or {}).get("tenant_id") for m in got.get("metadatas") or [] if (m or {}).get("tenant_id")}
        totals = {"tenants": 0, "upserted": 0, "deleted": 0}
        for t in sorted(tenants):
            res = sync_soft(db, t)
            if res is None:
                continue
            totals["tenants"] += 1
            totals["upserted"] += res.upserted
            totals["deleted"] += res.deleted
        return totals
    finally:
        db.close()


@dataclass(frozen=True)
class PersonalHit:
    vector_id: str
    kind: str
    row_id: str
    text: str
    distance: float
    metadata: dict[str, Any]


def query_personal_context(
    tenant_id: str,
    text: str,
    *,
    n: int = 8,
    kinds: Iterable[str] | None = None,
    signal_types: Iterable[str] | None = None,
) -> list[PersonalHit]:
    """The tenant's facts and signals nearest ``text``. Fails closed: an
    empty tenant raises, and every query filters on the tenant."""
    if not tenant_id:
        raise ValueError("tenant_id is required; an unscoped personal query would read everyone's brain")
    col = _collection(create=False)
    if col is None or not text.strip():
        return []
    clauses: list[dict] = [{"tenant_id": tenant_id}]
    kinds = [k for k in (kinds or []) if k in KINDS]
    if kinds:
        clauses.append({"kind": {"$in": kinds}})
    types = list(signal_types or [])
    if types:
        clauses.append({"signal_type": {"$in": types}})
    where = clauses[0] if len(clauses) == 1 else {"$and": clauses}
    try:
        total = len(col.get(where=where, include=[]).get("ids") or [])
    except Exception:
        logger.exception("personal_context_global: count failed")
        return []
    if total == 0:
        return []
    res = col.query(query_texts=[text], n_results=min(n, total), where=where, include=["documents", "metadatas", "distances"])
    hits = []
    for vid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]):
        if (meta or {}).get("tenant_id") != tenant_id:  # defence in depth
            continue
        hits.append(PersonalHit(vid, meta.get("kind", ""), meta.get("row_id", ""), doc, float(dist), dict(meta)))
    return hits
