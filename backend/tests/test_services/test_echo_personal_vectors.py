"""``personal_context_global`` (S-3.3.3): Echo's facts and signals for retrieval.

What it must hold:

- Every live fact and signal has one vector carrying its tenant; a rejected
  or source-deleted signal, an expired or deleted fact, has none. That holds
  whichever path changed the row (the API, an extraction run, a note or
  share delete), because each calls the same sync after its commit.
- Reads fail closed: no tenant, no query; one tenant never sees another's.
- ``DELETE /echo/brain`` leaves no vector of the tenant (T-3.3.3.4).
- The startup backfill repairs whatever a failed sync missed.
- A Chroma failure never fails the write that triggered the sync.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.models.job import Job
from app.services import auth_service, echo_service, echo_signal_service, note_service
from app.services import echo_personal_vectors as pv
from app.services import echo_signal_extraction as ex

SIGNALS = "/api/v1/echo/signals"


@pytest.fixture
def chroma(monkeypatch):
    # The suite runs with the index off (conftest); these tests turn it on
    # against an ephemeral client.
    monkeypatch.setattr(settings, "ECHO_PERSONAL_INDEX_ENABLED", True)
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield client
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


def _user(db, email, tier="studio"):
    u = auth_service.create_user(db, email=email, password="pw" * 6)
    u.tier = tier
    db.commit()
    token, _ = auth_service.create_access_token(u.id)
    return u, {"Authorization": f"Bearer {token}"}


def _ids(client, tenant_id):
    names = {c if isinstance(c, str) else c.name for c in client.list_collections()}
    if settings.CHROMA_PERSONAL_CONTEXT_COLLECTION_NAME not in names:
        return set()
    col = client.get_collection(settings.CHROMA_PERSONAL_CONTEXT_COLLECTION_NAME)
    return set(col.get(where={"tenant_id": tenant_id})["ids"])


def test_facts_and_signals_get_vectors_and_tombstones_lose_them(unauthenticated_client, db, chroma):
    a, ha = _user(db, "pv-a@example.com")
    fact = echo_service.record_context(db, user_id=a.id, kind="interest", key="tariffs", value="since 2019", source="manual")
    sig = unauthenticated_client.post(SIGNALS, json={"signal_type": "apprehension", "value": "Wary of single-source claims"}, headers=ha).json()
    assert _ids(chroma, a.id) == {pv.fact_vector_id(fact.id), pv.signal_vector_id(sig["id"])}

    col = chroma.get_collection(settings.CHROMA_PERSONAL_CONTEXT_COLLECTION_NAME)
    meta = col.get(ids=[pv.signal_vector_id(sig["id"])])["metadatas"][0]
    assert meta["tenant_id"] == a.id and meta["kind"] == "signal" and meta["signal_type"] == "apprehension"

    # An edit re-embeds; the document follows the wording.
    unauthenticated_client.patch(f"{SIGNALS}/{sig['id']}", json={"value": "Distrusts single-source claims"}, headers=ha)
    doc = col.get(ids=[pv.signal_vector_id(sig["id"])])["documents"][0]
    assert "Distrusts single-source claims" in doc

    # "That's not me": the vector goes with the tombstone.
    unauthenticated_client.delete(f"{SIGNALS}/{sig['id']}", headers=ha)
    assert _ids(chroma, a.id) == {pv.fact_vector_id(fact.id)}

    echo_service.delete_context(db, a.id, "interest", "tariffs")
    assert _ids(chroma, a.id) == set()


def test_expired_facts_and_revoked_sources_have_no_vectors(db, chroma):
    a, _ = _user(db, "pv-exp@example.com")
    past = datetime.now(timezone.utc) - timedelta(days=1)
    echo_service.record_context(db, user_id=a.id, kind="daily_routine", key="old", value="x", source="manual", expires_at=past)
    live = echo_service.record_context(db, user_id=a.id, kind="daily_routine", key="new", value="y", source="spotify_history")
    assert _ids(chroma, a.id) == {pv.fact_vector_id(live.id)}
    echo_service.revoke_source(db, a.id, "spotify_history")
    assert _ids(chroma, a.id) == set()


def test_queries_fail_closed_and_never_cross_tenants(db, chroma):
    a, _ = _user(db, "pv-qa@example.com")
    b, _ = _user(db, "pv-qb@example.com")
    echo_signal_service.create(db, tenant_id=a.id, user_id=a.id, signal_type="interest", value="Monetary history of India")
    echo_signal_service.create(db, tenant_id=b.id, user_id=b.id, signal_type="interest", value="Monetary history of Rome")
    echo_service.record_context(db, user_id=a.id, kind="interest", key="cricket", value="test matches", source="manual")

    hits = pv.query_personal_context(a.id, "money and central banks", n=10)
    assert hits and {h.metadata["tenant_id"] for h in hits} == {a.id}
    assert all("Rome" not in h.text for h in hits)
    only_signals = pv.query_personal_context(a.id, "money", kinds=["signal"])
    assert {h.kind for h in only_signals} == {"signal"}
    assert pv.query_personal_context(a.id, "money", signal_types=["apprehension"]) == []
    with pytest.raises(ValueError):
        pv.query_personal_context("", "money")


def test_extraction_and_note_deletion_keep_vectors_in_step(db, chroma):
    a, _ = _user(db, "pv-ex@example.com")
    db.add(Job(id=f"job-{a.id[:8]}", tenant_id=a.id, job_type="topic", topic="t", status="completed"))
    db.commit()
    note = note_service.create_note(db, a.id, target_type="job", target_id=f"job-{a.id[:8]}", body_md="One source is not evidence. Ever.")

    def llm(prompt):
        import json as _json
        import re as _re

        pid = _re.search(r"\[(P\d+)\]", prompt).group(1)
        return _json.dumps({"signals": [{"signal_type": "apprehension", "value": "Distrusts single sources",
                                         "examples": [{"id": pid, "quote": "One source is not evidence."}]}]}), 10, 10

    ex.run(db, a.id, llm=llm, model="m")
    sig = next(r for r in echo_signal_service.list_signals(db, a.id) if r.signal_type == "apprehension")
    assert pv.signal_vector_id(sig.id) in _ids(chroma, a.id)

    note_service.delete_note(db, a.id, note.id)
    assert pv.signal_vector_id(sig.id) not in _ids(chroma, a.id), "the withdrawn note's signal is out of retrieval"


def test_the_brain_delete_leaves_no_personal_vector(unauthenticated_client, db, chroma, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path))
    a, ha = _user(db, "pv-del@example.com")
    b, _ = _user(db, "pv-keep@example.com")
    for u in (a, b):
        echo_service.record_context(db, user_id=u.id, kind="interest", key="k", value="v", source="manual")
        echo_signal_service.create(db, tenant_id=u.id, user_id=u.id, signal_type="interest", value="Cricket")
    assert len(_ids(chroma, a.id)) == 2

    r = unauthenticated_client.delete("/api/v1/echo/brain", params={"confirm": "delete-everything"}, headers=ha)
    assert r.status_code == 200, r.text
    assert _ids(chroma, a.id) == set()
    assert len(_ids(chroma, b.id)) == 2, "the other tenant keeps theirs"


def test_backfill_repairs_a_missed_sync(db, chroma):
    a, _ = _user(db, "pv-bf@example.com")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pv, "sync_tenant", lambda *a_, **k: (_ for _ in ()).throw(RuntimeError("chroma down")))
        row = echo_signal_service.create(db, tenant_id=a.id, user_id=a.id, signal_type="interest", value="Chess")
    assert row.id, "the write succeeded although the sync failed"
    assert pv.signal_vector_id(row.id) not in _ids(chroma, a.id)

    totals = pv.backfill(session_factory=lambda: _NoClose(db))
    assert totals["upserted"] >= 1
    assert pv.signal_vector_id(row.id) in _ids(chroma, a.id)

    # A row deleted while the API was down loses its vector at the next backfill.
    db.delete(row)
    db.commit()
    pv.backfill(session_factory=lambda: _NoClose(db))
    assert _ids(chroma, a.id) == set()


class _NoClose:
    """Lend the test session to ``backfill`` without letting it close it."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


def test_the_index_switch_turns_every_path_off(db, chroma, monkeypatch):
    a, _ = _user(db, "pv-off@example.com")
    monkeypatch.setattr(settings, "ECHO_PERSONAL_INDEX_ENABLED", False)
    echo_signal_service.create(db, tenant_id=a.id, user_id=a.id, signal_type="interest", value="Chess")
    assert _ids(chroma, a.id) == set()
    assert pv.backfill(session_factory=lambda: _NoClose(db)) == {"tenants": 0, "upserted": 0, "deleted": 0}


def test_an_unchanged_sync_embeds_nothing(db, chroma):
    a, _ = _user(db, "pv-idem@example.com")
    echo_signal_service.create(db, tenant_id=a.id, user_id=a.id, signal_type="interest", value="Chess")
    again = pv.sync_tenant(db, a.id)
    assert again == pv.SyncResult(upserted=0, deleted=0, unchanged=1)
