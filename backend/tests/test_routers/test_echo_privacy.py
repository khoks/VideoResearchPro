"""Echo privacy (S-3.10.1 full export, S-3.10.2 full delete).

The two promises `personal-brain.md` makes about Echo, held to the stores
themselves rather than to the API's own report:

- **Export is lossless.** `read_archive(export)` gives back every column of
  every Echo row of the tenant and every file's exact bytes, and nothing of
  any other tenant.
- **Delete removes the data.** After `DELETE /echo/brain`, a direct look at
  each store finds nothing of the tenant: no row in any Echo table, no file
  under `ECHO_SHARES_DIR/<tenant>`, no vector in any Echo Chroma collection.
  The other tenant's rows, files and vectors are all still there.

Plus: deletion is ordered so a failing store leaves the rows that let a
retry finish; it needs an explicit confirmation; it does not touch the
library or notes; and share text never leaks into the dataset exports
(context-only by default).
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.connectors.base import ActivityEvent as EventIn
from app.models.activity_event import ActivityEvent
from app.models.audit_log import AuditLog
from app.models.echo_connector import EchoConnectorCredential, EchoConnectorGrant, EchoConnectorOAuthState
from app.models.job import Job
from app.models.note import Note
from app.models.personal_context import PersonalContext
from app.models.share import Share
from app.models.voice_signal import VoiceSignal
from app.models.voice_signal_input import VoiceSignalInput
from app.services import (
    activity_event_service,
    auth_service,
    byok_service,
    echo_intake_service,
    echo_privacy_service,
    echo_service,
    echo_signal_extraction,
    echo_signal_service,
    echo_vectors,
    note_service,
)
from app.models.echo_import import EchoImport
from app.models.echo_draft import EchoDraft, EchoVoiceGate
from app.models.echo_share_token import EchoShareToken
from app.services import echo_import_service, echo_share_token_service
from app.services.echo_privacy_service import ECHO_SECRET_TABLES, ECHO_TABLES, read_archive, row_columns

EXPORT = "/api/v1/echo/export"
BRAIN = "/api/v1/echo/brain"
CONFIRM = {"confirm": "delete-everything"}


def _studio(db, email: str):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def shares_dir(tmp_path, monkeypatch):
    root = tmp_path / "echo-shares"
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(root))
    return root


@pytest.fixture
def chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield client
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


def _vector(client, collection: str, vector_id: str, tenant_id: str) -> None:
    client.get_or_create_collection(name=collection).add(
        ids=[vector_id],
        embeddings=[[0.1, 0.2, 0.3]],
        metadatas=[{"tenant_id": tenant_id}],
        documents=["x"],
    )


def _seed_brain(db, chroma, user, *, marker: str) -> dict:
    """Facts, three kinds of share (one with a binary file), two voice
    signals (one rejected: tombstones are part of the brain too), and a
    vector in each Echo collection, all for ``user``."""
    f1 = echo_service.record_context(
        db, user_id=user.id, kind="interest", key=f"{marker}-tariffs",
        value={"since": 2019, "depth": "deep"}, source="manual", confidence=0.8,
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    f2 = echo_service.record_context(
        db, user_id=user.id, kind="personality_trait", key=f"{marker}-contrarian",
        value="yes", source="manual",
    )
    link = echo_intake_service.create_url_share(
        db, user.id, user.id, url=f"https://example.org/{marker}", annotation="mine?",
    )
    text = echo_intake_service.create_text_share(
        db, user.id, user.id, text=f"{marker} — शब्द and words", author_is_tenant=True,
        content_type="book_quote",
    )
    blob = bytes(range(256)) * 4 + marker.encode()
    file = echo_intake_service.create_file_share(
        db, user.id, user.id, filename=f"{marker}.png", data=blob, mime="image/png",
    )
    file.derived_fact_ids_json = json.dumps([f1.id])
    db.commit()
    echo_signal_service.create(
        db, tenant_id=user.id, user_id=user.id, signal_type="framing",
        value=f"{marker} starts from first principles", language="en",
    )
    rejected = echo_signal_service.create(
        db, tenant_id=user.id, user_id=user.id, signal_type="interest", value=f"{marker} cricket",
    )
    echo_signal_service.suppress(db, user.id, rejected.id)
    # S-3.3.2: the extraction ledger, written by a real run (no LLM): it
    # reads the one share marked as the user's own words.
    echo_signal_extraction.run(db, user.id, use_llm=False)
    # S-3.4.1: a "speak as me" draft and the voice test that gates it.
    from app.services import echo_draft_service

    echo_draft_service.record_voice_test(db, user.id, pairs=20, picked_own=10)
    db.add(EchoDraft(tenant_id=user.id, user_id=user.id, input_message=f"{marker} asks who pays",
                     language="en", draft=f"{marker} thinks the importer pays", disclosure="Drafted with Echo, reviewed by me"))
    db.commit()
    _vector(chroma, settings.CHROMA_SHARES_COLLECTION_NAME, echo_vectors.share_vector_id(file.id), user.id)
    _vector(chroma, settings.CHROMA_PERSONAL_CONTEXT_COLLECTION_NAME, f"fact:{f2.id}", user.id)
    # S-3.2.1: a connector's event, its grant, its (encrypted) token and a
    # connect still in flight.
    activity_event_service.store_events(db, user.id, "github", [EventIn(
        external_id=f"{marker}-push-1", event_type="pushed_commit",
        occurred_at=datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
        payload={"repo": f"{marker}/repo"}, text_content=f"{marker} fix the parser",
    )])
    token = f"gho_{marker}_SECRET_TOKEN"
    db.add(EchoConnectorGrant(tenant_id=user.id, connector="github", consent_version="1", account_label=marker))
    db.add(EchoConnectorCredential(tenant_id=user.id, connector="github",
                                   access_token_encrypted=byok_service.encrypt_secret(token)))
    db.add(EchoConnectorOAuthState(state=f"state-{marker}", tenant_id=user.id, connector="github",
                                   code_verifier=f"verifier-{marker}-SECRET", redirect_uri="http://x/cb",
                                   consent_version="1", expires_at=datetime(2030, 1, 1)))
    db.commit()
    # S-3.7.5: an export import (its echo_imports row and the shares it
    # wrote, which carry import_id and occurred_at).
    chat = (
        f"31/01/2024, 21:05 - Me: {marker} my own line\n"
        f"31/01/2024, 21:06 - Friend: {marker} their line\n"
    ).encode()
    # S-3.7.3: a share token for the browser extension (stored as a hash).
    _, share_token = echo_share_token_service.create(db, user.id, f"{marker} browser")
    imported = echo_import_service.run_import(
        db, user, io.BytesIO(chat), "WhatsApp Chat with Friend.txt", options={"self_name": "Me"},
    )
    return {"facts": [f1.id, f2.id], "shares": [link.id, text.id, file.id], "file_id": file.id, "blob": blob,
            "token": token, "verifier": f"verifier-{marker}-SECRET", "import_id": imported.id,
            "share_token": share_token}


@pytest.fixture
def brains(db, shares_dir, chroma):
    a, ha = _studio(db, "brain-a@example.com")
    b, hb = _studio(db, "brain-b@example.com")
    return {
        "a": a, "ha": ha, "b": b, "hb": hb,
        "seed_a": _seed_brain(db, chroma, a, marker="ALPHA"),
        "seed_b": _seed_brain(db, chroma, b, marker="BRAVO"),
    }


def _direct_footprint(db, chroma, shares_dir, tenant_id: str) -> dict:
    """Look in each store directly; do not trust the service's own count."""
    rows = {
        "personal_context": db.query(PersonalContext).filter(
            (PersonalContext.tenant_id == tenant_id) | (PersonalContext.user_id == tenant_id)
        ).count(),
        "shares_inbox": db.query(Share).filter(Share.tenant_id == tenant_id).count(),
        "echo_imports": db.query(EchoImport).filter(EchoImport.tenant_id == tenant_id).count(),
        "echo_drafts": db.query(EchoDraft).filter(EchoDraft.tenant_id == tenant_id).count(),
        "echo_voice_gates": db.query(EchoVoiceGate).filter(EchoVoiceGate.tenant_id == tenant_id).count(),
        "echo_share_tokens": db.query(EchoShareToken).filter(EchoShareToken.tenant_id == tenant_id).count(),
        "voice_signals": db.query(VoiceSignal).filter(VoiceSignal.tenant_id == tenant_id).count(),
        "voice_signal_inputs": db.query(VoiceSignalInput).filter(VoiceSignalInput.tenant_id == tenant_id).count(),
        "activity_events": db.query(ActivityEvent).filter(ActivityEvent.tenant_id == tenant_id).count(),
        "echo_connector_grants": db.query(EchoConnectorGrant).filter(EchoConnectorGrant.tenant_id == tenant_id).count(),
        "echo_connector_credentials": db.query(EchoConnectorCredential)
        .filter(EchoConnectorCredential.tenant_id == tenant_id).count(),
        "echo_connector_oauth_states": db.query(EchoConnectorOAuthState)
        .filter(EchoConnectorOAuthState.tenant_id == tenant_id).count(),
    }
    tenant_dir = shares_dir / tenant_id
    files = sum(1 for p in tenant_dir.rglob("*") if p.is_file()) if tenant_dir.exists() else 0
    vectors = {}
    existing = {c if isinstance(c, str) else c.name for c in chroma.list_collections()}
    for name in echo_vectors.echo_collection_names():
        vectors[name] = (
            len(chroma.get_collection(name).get(where={"tenant_id": tenant_id})["ids"])
            if name in existing else 0
        )
    return {"rows": rows, "files": files, "vectors": vectors}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_round_trip_is_lossless(unauthenticated_client, db, brains, shares_dir):
    r = unauthenticated_client.get(EXPORT, headers=brains["ha"])
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "echo-export-" in r.headers["content-disposition"]

    archive = read_archive(io.BytesIO(r.content))
    a = brains["a"]
    for name, model in ECHO_TABLES:
        expected = sorted(
            (row_columns(row) for row in db.query(model).filter(model.tenant_id == a.id)),
            key=lambda d: d["id"],
        )
        got = sorted(archive.tables[name], key=lambda d: d["id"])
        assert got == expected, f"{name} did not round-trip"
        assert archive.manifest["tables"][name]["rows"] == len(expected) > 0

    file_row = db.get(Share, brains["seed_a"]["file_id"])
    assert archive.files == {file_row.file_path: brains["seed_a"]["blob"]}
    assert archive.manifest["missing_files"] == []
    assert archive.manifest["tenant_id"] == a.id
    # Unicode and JSON-text columns survive as stored.
    text_row = next(r for r in archive.tables["shares_inbox"] if r["content_type"] == "book_quote")
    assert text_row["extracted_text"] == "ALPHA — शब्द and words"
    fact = next(r for r in archive.tables["personal_context"] if r["key"] == "ALPHA-tariffs")
    assert json.loads(fact["value"]) == {"since": 2019, "depth": "deep"}
    assert fact["expires_at"] == datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert archive.tables["activity_events"][0]["text_content"] == "ALPHA fix the parser"


def test_export_withholds_connector_secrets(unauthenticated_client, brains):
    """Tokens and PKCE verifiers are erased with the brain but never exported,
    in any form: the manifest counts them and says why."""
    r = unauthenticated_client.get(EXPORT, headers=brains["ha"])
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        blob = b"".join(zf.read(n) for n in names)
    for name, _ in ECHO_SECRET_TABLES:
        assert f"{name}.jsonl" not in names
    assert brains["seed_a"]["token"].encode() not in blob
    assert brains["seed_a"]["verifier"].encode() not in blob
    share_token = brains["seed_a"]["share_token"]
    assert share_token.encode() not in blob
    assert hashlib.sha256(share_token.encode()).hexdigest().encode() not in blob
    assert b"access_token_encrypted" not in blob
    manifest = read_archive(io.BytesIO(r.content)).manifest
    assert manifest["withheld"]["tables"] == {
        "echo_connector_credentials": 1, "echo_connector_oauth_states": 1, "echo_share_tokens": 1,
    }
    assert "never leave the server" in manifest["withheld"]["reason"]


def test_export_never_carries_another_tenant(unauthenticated_client, brains):
    r = unauthenticated_client.get(EXPORT, headers=brains["ha"])
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        blob = b"".join(zf.read(n) for n in zf.namelist())
        names = zf.namelist()
    assert b"BRAVO" not in blob
    assert all(brains["b"].id not in n for n in names)


def test_export_is_audited_with_counts_only(unauthenticated_client, db, brains):
    unauthenticated_client.get(EXPORT, headers=brains["ha"])
    row = db.query(AuditLog).filter(AuditLog.event == "echo_exported").one()
    assert row.user_id == brains["a"].id
    meta = json.loads(row.metadata_json)
    assert meta == {
        "rows": {"personal_context": 2, "shares_inbox": 5, "voice_signals": 2, "voice_signal_inputs": 1, "activity_events": 1, "echo_connector_grants": 1, "echo_imports": 1, "echo_drafts": 1, "echo_voice_gates": 1},
        "files": 1,
        "missing_files": 0,
    }
    assert "ALPHA" not in row.metadata_json


def test_export_flags_a_missing_file(unauthenticated_client, db, brains, shares_dir):
    row = db.get(Share, brains["seed_a"]["file_id"])
    (shares_dir.resolve() / row.file_path).unlink()
    archive = read_archive(io.BytesIO(unauthenticated_client.get(EXPORT, headers=brains["ha"]).content))
    assert archive.manifest["missing_files"] == [row.file_path]
    assert archive.files == {}


def test_read_archive_rejects_foreign_and_tampered_archives(unauthenticated_client, brains):
    good = unauthenticated_client.get(EXPORT, headers=brains["ha"]).content
    with zipfile.ZipFile(io.BytesIO(good)) as zf:
        entries = {n: zf.read(n) for n in zf.namelist()}

    def rezip(mutate) -> io.BytesIO:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            for n, data in mutate(dict(entries)).items():
                zf.writestr(n, data)
        out.seek(0)
        return out

    def tamper_file(e):
        name = next(n for n in e if n.startswith("files/"))
        e[name] = e[name] + b"!"
        return e

    def foreign(e):
        m = json.loads(e["manifest.json"]); m["format"] = "something-else"
        e["manifest.json"] = json.dumps(m).encode()
        return e

    def drop_row(e):
        e["shares_inbox.jsonl"] = b"\n".join(e["shares_inbox.jsonl"].splitlines()[:-1])
        return e

    for mutate in (tamper_file, foreign, drop_row):
        with pytest.raises(ValueError):
            read_archive(rezip(mutate))


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_brain_empties_every_store_and_spares_the_other_tenant(
    unauthenticated_client, db, brains, shares_dir, chroma
):
    a, b = brains["a"], brains["b"]
    before_a = _direct_footprint(db, chroma, shares_dir, a.id)
    before_b = _direct_footprint(db, chroma, shares_dir, b.id)
    assert before_a == {
        "rows": {"personal_context": 2, "shares_inbox": 5, "voice_signals": 2, "voice_signal_inputs": 1, "activity_events": 1, "echo_connector_grants": 1, "echo_connector_credentials": 1, "echo_connector_oauth_states": 1, "echo_imports": 1, "echo_drafts": 1, "echo_voice_gates": 1, "echo_share_tokens": 1},
        "files": 1,
        "vectors": {settings.CHROMA_SHARES_COLLECTION_NAME: 1, settings.CHROMA_PERSONAL_CONTEXT_COLLECTION_NAME: 1},
    }

    r = unauthenticated_client.delete(BRAIN, params=CONFIRM, headers=brains["ha"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["removed"] == before_a
    assert body["footprint_after"] == {
        "rows": {"personal_context": 0, "shares_inbox": 0, "voice_signals": 0, "voice_signal_inputs": 0, "activity_events": 0, "echo_connector_grants": 0, "echo_connector_credentials": 0, "echo_connector_oauth_states": 0, "echo_imports": 0, "echo_drafts": 0, "echo_voice_gates": 0, "echo_share_tokens": 0},
        "files": 0,
        "vectors": {n: 0 for n in echo_vectors.echo_collection_names()},
    }

    db.expire_all()
    after_a = _direct_footprint(db, chroma, shares_dir, a.id)
    assert after_a["rows"] == {"personal_context": 0, "shares_inbox": 0, "voice_signals": 0, "voice_signal_inputs": 0, "activity_events": 0, "echo_connector_grants": 0, "echo_connector_credentials": 0, "echo_connector_oauth_states": 0, "echo_imports": 0, "echo_drafts": 0, "echo_voice_gates": 0, "echo_share_tokens": 0}
    assert after_a["files"] == 0 and not (shares_dir / a.id).exists()
    assert not any(after_a["vectors"].values())
    for share_id in brains["seed_a"]["shares"]:
        assert db.get(Share, share_id) is None
    for fact_id in brains["seed_a"]["facts"]:
        assert db.get(PersonalContext, fact_id) is None

    assert _direct_footprint(db, chroma, shares_dir, b.id) == before_b, "B's brain is untouched"
    b_file = db.get(Share, brains["seed_b"]["file_id"])
    assert (shares_dir.resolve() / b_file.file_path).read_bytes() == brains["seed_b"]["blob"]

    audit = db.query(AuditLog).filter(AuditLog.event == "echo_brain_deleted").one()
    assert audit.user_id == a.id and "ALPHA" not in (audit.metadata_json or "")


def test_delete_brain_requires_the_confirmation(unauthenticated_client, db, brains, shares_dir, chroma):
    before = _direct_footprint(db, chroma, shares_dir, brains["a"].id)
    assert unauthenticated_client.delete(BRAIN, headers=brains["ha"]).status_code == 422
    assert unauthenticated_client.delete(BRAIN, params={"confirm": "yes"}, headers=brains["ha"]).status_code == 400
    assert _direct_footprint(db, chroma, shares_dir, brains["a"].id) == before


def test_a_failing_vector_store_stops_the_delete_before_rows_and_files(
    unauthenticated_client, db, brains, shares_dir, chroma, monkeypatch
):
    before = _direct_footprint(db, chroma, shares_dir, brains["a"].id)

    def boom(_tenant_id):
        raise RuntimeError("chroma is down")

    monkeypatch.setattr(echo_vectors, "delete_tenant_vectors", boom)
    r = unauthenticated_client.delete(BRAIN, params=CONFIRM, headers=brains["ha"])
    assert r.status_code == 500 and "vectors" in r.json()["detail"]
    assert _direct_footprint(db, chroma, shares_dir, brains["a"].id) == before, "nothing went; a retry can finish"
    monkeypatch.undo()


def test_delete_brain_twice_is_harmless(unauthenticated_client, brains):
    assert unauthenticated_client.delete(BRAIN, params=CONFIRM, headers=brains["ha"]).status_code == 200
    r = unauthenticated_client.delete(BRAIN, params=CONFIRM, headers=brains["ha"])
    assert r.status_code == 200
    assert r.json()["removed"]["rows"] == {"personal_context": 0, "shares_inbox": 0, "voice_signals": 0, "voice_signal_inputs": 0, "activity_events": 0, "echo_connector_grants": 0, "echo_connector_credentials": 0, "echo_connector_oauth_states": 0, "echo_imports": 0, "echo_drafts": 0, "echo_voice_gates": 0, "echo_share_tokens": 0}


def test_delete_brain_leaves_notes_and_the_library_alone(unauthenticated_client, db, brains):
    a = brains["a"]
    db.add(Job(id="job-a", tenant_id=a.id, job_type="topic", topic="kept", status="completed"))
    db.commit()
    note = note_service.create_note(db, a.id, target_type="job", target_id="job-a", body_md="kept note")
    unauthenticated_client.delete(BRAIN, params=CONFIRM, headers=brains["ha"])
    db.expire_all()
    assert db.get(Job, "job-a") is not None
    assert db.get(Note, note.id) is not None


def test_footprint_endpoint_matches_the_stores(unauthenticated_client, db, brains, shares_dir, chroma):
    r = unauthenticated_client.get(f"{BRAIN}/footprint", headers=brains["ha"])
    assert r.status_code == 200
    assert r.json() == _direct_footprint(db, chroma, shares_dir, brains["a"].id)


# ---------------------------------------------------------------------------
# Context-only default: share text never reaches a dataset or derived export
# ---------------------------------------------------------------------------


def test_share_text_never_reaches_dataset_or_notes_exports(unauthenticated_client, db, shares_dir, chroma):
    user, headers = _studio(db, "ctx-only@example.com")
    marker = "THIRD-PARTY-WHATSAPP-LINE-7f3a"
    r = unauthenticated_client.post("/api/v1/echo/shares", json={"text": marker}, headers=headers)
    assert r.status_code == 201 and r.json()["author_is_tenant"] is False
    for url in (
        "/api/v1/exports/qa-dataset/openai.jsonl",
        "/api/v1/exports/qa-dataset/tuple.jsonl",
        "/api/v1/exports/knowledge-dataset/openai.jsonl",
        "/api/v1/exports/knowledge-dataset/tuple.jsonl",
        "/api/v1/exports/notes.jsonl",
        "/api/v1/exports/notes.md",
    ):
        resp = unauthenticated_client.get(url, headers=headers)
        assert resp.status_code == 200, url
        assert marker not in resp.text, f"{url} leaked share text"


def test_every_echo_table_is_tenant_keyed():
    """A table added to ECHO_TABLES without `tenant_id` could be neither
    exported nor deleted per tenant."""
    assert [name for name, _ in ECHO_TABLES] == [
        "personal_context", "shares_inbox", "voice_signals", "voice_signal_inputs", "activity_events", "echo_connector_grants",
        "echo_imports", "echo_drafts", "echo_voice_gates",
    ]
    assert [name for name, _ in ECHO_SECRET_TABLES] == [
        "echo_connector_credentials", "echo_connector_oauth_states", "echo_share_tokens",
    ]
    for _, model in ECHO_TABLES + ECHO_SECRET_TABLES:
        assert "tenant_id" in model.__table__.columns
