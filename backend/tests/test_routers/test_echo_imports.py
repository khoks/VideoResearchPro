"""Echo export-file importers (S-3.7.5, part 1): WhatsApp chats and Google
Keep notes from Takeout, the ``/echo/import`` endpoints, embedding and undo.

Fixtures in ``tests/fixtures/echo_imports/`` carry the real formats' invisible
characters (left-to-right marks, narrow no-break spaces); see the generator
note in that folder's README. Chroma is in-memory with the real embedder,
because "an import's vectors carry its tenant and import id" is what undo and
the whole-brain delete depend on. Nothing here calls a remote service.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import settings
from app.models.echo_import import EchoImport
from app.models.share import Share
from app.services import auth_service, echo_import_service, echo_intake_service, echo_vectors
from app.connectors import registry
from app.connectors.archive import ExportUnreadable, ImportSource
from app.connectors.base import ArchiveImporter, ImportedShare
from app.connectors.whatsapp import importer as whatsapp

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "echo_imports"
IMPORT = "/api/v1/echo/import"
PREVIEW = "/api/v1/echo/import/preview"
IMPORTS = "/api/v1/echo/imports"
SHARES = "/api/v1/echo/shares"
IOS = "whatsapp_ios_chat.txt"
ANDROID = "WhatsApp Chat with Asha.txt"


def _studio(db, email):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


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


@pytest.fixture
def two(db, tmp_path, monkeypatch, chroma):
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    a, ha = _studio(db, "import-a@example.com")
    b, hb = _studio(db, "import-b@example.com")
    return {"a": a, "ha": ha, "b": b, "hb": hb}


@pytest.fixture
def inline(monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARE_PROCESSING", "inline")


def _bytes(name: str) -> bytes:
    return (FIX / name).read_bytes()


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _takeout() -> bytes:
    members = {f"Takeout/Keep/{p.name}": p.read_bytes() for p in (FIX / "keep").glob("*.json")}
    members["Takeout/Keep/1f2e3d.jpeg"] = b"\xff\xd8 not really a jpeg"
    members["Takeout/YouTube and YouTube Music/history/watch-history.json"] = b"[]"
    return _zip(members)


def _post(client, url, headers, filename, data, **form):
    fields = {k: (json.dumps(v) if k == "options" else v) for k, v in form.items()}
    return client.post(url, headers=headers, files={"file": (filename, data, "application/octet-stream")}, data=fields)


def _preview_file(name: str, data: bytes | None = None, options=None):
    return echo_import_service.preview(io.BytesIO(data if data is not None else _bytes(name)), name, options=options)


def _vectors(chroma, tenant_id):
    names = {c if isinstance(c, str) else c.name for c in chroma.list_collections()}
    if settings.CHROMA_SHARES_COLLECTION_NAME not in names:
        return {}
    got = chroma.get_collection(settings.CHROMA_SHARES_COLLECTION_NAME).get(
        where={"tenant_id": tenant_id}, include=["metadatas", "documents"]
    )
    return {i: (m, d) for i, m, d in zip(got["ids"], got["metadatas"], got["documents"])}


# ---------------------------------------------------------------------------
# WhatsApp parsing
# ---------------------------------------------------------------------------


def test_ios_export_reads_participants_media_and_system_lines():
    pv = _preview_file(IOS)
    assert pv.importer == "whatsapp"
    assert {p["name"]: p["messages"] for p in pv.participants} == {"Priya Sharma": 4, "Rahul": 4}
    s = pv.summary
    assert (s["messages"], s["media"], s["system_lines"], s["deleted"], s["turns"]) == (8, 2, 1, 1, 5)
    assert s["date_order"] == "dmy" and s["date_order_inferred"] is True
    assert pv.warnings == []


def test_android_export_groups_turns_and_keeps_continuation_lines():
    stats: dict = {}
    with open(FIX / ANDROID, "rb") as fh:
        source = ImportSource(fh, ANDROID, max_uncompressed=10**9)
        turns = list(whatsapp.IMPORTER.parse(source, tenant_id="t", options={"self_name": "Rahul"}, stats=stats))
    assert all(isinstance(t, ImportedShare) for t in turns)
    assert [(t.author, t.metadata["messages"], t.author_is_tenant) for t in turns] == [
        ("Rahul", 2, True),   # the list, three lines, and the photo a minute later
        ("Rahul", 1, True),   # 34 minutes on: a new turn
        ("Asha", 1, False),
        ("Asha", 2, False),
    ]
    assert turns[0].text == (
        "Reading list for the weekend:\n1. Who pays for tariffs\n2. The China shock, revisited\n[media]"
    )
    assert turns[3].text == "[image]\nMorning! Found the episode"
    assert whatsapp.chat_name(ImportSource(io.BytesIO(b""), ANDROID, max_uncompressed=1)) == "Asha"


def test_month_first_is_inferred_and_an_undecided_order_warns():
    us = _preview_file("WhatsApp Chat with Sam.txt")
    assert us.summary["date_order"] == "mdy" and us.summary["first_at"].startswith("2024-01-31T21:05")
    ambiguous = _preview_file("WhatsApp Chat with Kiran.txt")
    assert ambiguous.summary["date_order_inferred"] is False and "day-first" in ambiguous.warnings[0]
    assert ambiguous.summary["first_at"].startswith("2024-02-01")
    forced = _preview_file("WhatsApp Chat with Kiran.txt", options={"date_order": "mdy"})
    assert forced.summary["first_at"].startswith("2024-01-02") and forced.warnings == []


def test_times_are_converted_from_the_phones_time_zone():
    pv = _preview_file(ANDROID, options={"timezone": "Asia/Kolkata"})
    assert pv.summary["first_at"] == "2024-01-31T15:35:00+00:00"
    bad = _preview_file(ANDROID, options={"timezone": "Mars/Olympus"})
    assert any("Unknown time zone" in w for w in bad.warnings)


def test_ios_zip_export_reads_the_chat_and_names_it_from_the_archive():
    data = _zip({"_chat.txt": _bytes(IOS), "00000012-PHOTO-2024-02-13-08-01-00.jpg": b"\xff\xd8"})
    pv = _preview_file("WhatsApp Chat - Priya Sharma.zip", data)
    assert pv.importer == "whatsapp" and pv.summary["chat"] == "Priya Sharma"
    assert pv.summary["messages"] == 8


def test_parsing_streams_and_never_reads_the_whole_file():
    class NoSlurp(io.BytesIO):
        def read(self, size=-1):
            if size is None or size < 0:
                raise AssertionError("read() without a size loads the whole export")
            return super().read(size)

        def readall(self):
            raise AssertionError("readall() loads the whole export")

    big = _bytes(ANDROID) * 200
    pv = echo_import_service.preview(NoSlurp(big), ANDROID)
    assert pv.summary["messages"] == 6 * 200


# ---------------------------------------------------------------------------
# Running an import
# ---------------------------------------------------------------------------


def test_preview_endpoint_writes_nothing(unauthenticated_client, db, two):
    r = _post(unauthenticated_client, PREVIEW, two["ha"], IOS, _bytes(IOS))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["importer"] == "whatsapp" and {p["name"] for p in body["participants"]} == {"Priya Sharma", "Rahul"}
    assert "self_name" in body["options"] and "redact_other_party" in body["options"]
    assert db.query(Share).count() == 0 and db.query(EchoImport).count() == 0


def test_whatsapp_import_writes_turns_with_authorship(unauthenticated_client, db, two):
    r = _post(unauthenticated_client, IMPORT, two["ha"], IOS, _bytes(IOS),
              options={"self_name": "Rahul", "timezone": "Asia/Kolkata"})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["importer"] == "whatsapp" and item["status"] == "embedding"
    assert item["counts"] == {"shares": 5, "own_words": 2, "context_only": 3, "embedded": 0}
    assert item["options"]["self_name"] == "Rahul" and item["options"]["date_order"] == "dmy"

    listed = unauthenticated_client.get(SHARES, params={"import_id": item["id"]}, headers=two["ha"]).json()
    assert listed["total"] == 5
    first = listed["items"][0]
    assert first["surface"] == "file_import" and first["content_type"] == "whatsapp_message"
    assert first["kind"] == "text" and first["text"] == "Did you read the tariff piece?\nIt says importers pay, not China"
    assert first["author_is_tenant"] is False and first["occurred_at"].startswith("2024-02-12T15:35:01")
    assert first["imported"]["sender"] == "Priya Sharma" and first["imported"]["chat"] == "whatsapp_ios_chat"
    assert [s["author_is_tenant"] for s in listed["items"]] == [False, True, False, True, False]

    # The ordinary inbox stays the user's own hand-picked shares.
    assert unauthenticated_client.get(SHARES, headers=two["ha"]).json()["total"] == 0
    assert unauthenticated_client.get(SHARES, params={"origin": "import"}, headers=two["ha"]).json()["total"] == 5
    assert unauthenticated_client.get(SHARES, params={"origin": "all"}, headers=two["ha"]).json()["total"] == 5


def test_redacting_the_other_party_never_stores_their_words(unauthenticated_client, db, two):
    r = _post(unauthenticated_client, IMPORT, two["ha"], IOS, _bytes(IOS),
              options={"self_name": "Rahul", "redact_other_party": True})
    assert r.status_code == 201, r.text
    counts = r.json()["counts"]
    assert counts["shares"] == 2 and counts["context_only"] == 0
    assert counts["redacted_turns"] == 3 and counts["redacted_messages"] == 4
    stored = " ".join(
        f"{s.raw_payload_json} {s.extracted_text}" for s in db.query(Share).filter(Share.tenant_id == two["a"].id)
    )
    for their_words in ("importers pay", "Send me the paper", "अहिंसा", "Priya Sharma"):
        assert their_words not in stored
    assert all(s.author_is_tenant for s in db.query(Share).filter(Share.tenant_id == two["a"].id))


def test_options_that_cannot_be_right_are_refused(unauthenticated_client, db, two):
    stranger = _post(unauthenticated_client, IMPORT, two["ha"], IOS, _bytes(IOS), options={"self_name": "Nobody"})
    assert stranger.status_code == 422 and "does not appear" in stranger.json()["detail"]
    redact_alone = _post(unauthenticated_client, IMPORT, two["ha"], IOS, _bytes(IOS),
                         options={"redact_other_party": True})
    assert redact_alone.status_code == 422 and "which participant is you" in redact_alone.json()["detail"]
    assert db.query(EchoImport).count() == 0 and db.query(Share).count() == 0


def test_without_a_self_name_everything_is_context_only(unauthenticated_client, db, two):
    r = _post(unauthenticated_client, IMPORT, two["ha"], ANDROID, _bytes(ANDROID))
    assert r.json()["counts"]["own_words"] == 0 and r.json()["counts"]["context_only"] == 4


def test_unreadable_uploads_are_refused(unauthenticated_client, two, monkeypatch):
    junk = _post(unauthenticated_client, IMPORT, two["ha"], "notes.txt", b"just some text\nnothing else\n")
    assert junk.status_code == 422 and "Supported" in junk.json()["detail"]
    empty = _post(unauthenticated_client, IMPORT, two["ha"], ANDROID, b"")
    assert empty.status_code == 422
    monkeypatch.setattr(settings, "ECHO_IMPORT_MAX_BYTES", 100)
    big = _post(unauthenticated_client, PREVIEW, two["ha"], ANDROID, _bytes(ANDROID))
    assert big.status_code == 413
    bad_options = _post(unauthenticated_client, PREVIEW, two["ha"], "x.txt", b"x", options=["not", "an", "object"])
    assert bad_options.status_code in (413, 422)


def test_a_zip_bomb_is_refused_before_reading(two, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_IMPORT_MAX_UNCOMPRESSED_BYTES", 1000)
    data = _zip({"_chat.txt": b"a" * 5000})
    with pytest.raises(ExportUnreadable, match="unpacks to more than"):
        _preview_file("WhatsApp Chat - X.zip", data)


# ---------------------------------------------------------------------------
# Google Keep
# ---------------------------------------------------------------------------


def test_keep_takeout_import(unauthenticated_client, db, two):
    data = _takeout()
    pv = _post(unauthenticated_client, PREVIEW, two["ha"], "takeout-20241019.zip", data).json()
    assert pv["importer"] == "google_keep"
    s = pv["summary"]
    assert (s["notes"], s["trashed"], s["empty"], s["pinned"], s["lists"]) == (2, 1, 1, 1, 1)
    assert s["labels"] == {"Essays": 1, "Economics": 1}
    assert any("YouTube and YouTube Music" in w for w in pv["warnings"])

    item = _post(unauthenticated_client, IMPORT, two["ha"], "takeout-20241019.zip", data).json()
    assert item["counts"]["shares"] == 2 and item["counts"]["own_words"] == 2
    assert item["counts"]["skipped_trashed"] == 1 and item["counts"]["skipped_empty"] == 1
    shares = unauthenticated_client.get(SHARES, params={"import_id": item["id"]}, headers=two["ha"]).json()["items"]
    tariff = next(x for x in shares if x["imported"]["title"] == "Tariff thoughts")
    assert tariff["content_type"] == "keep_note" and tariff["author_is_tenant"] is True
    assert "pass-through numbers" in tariff["text"] and "https://example.org/who-pays" in tariff["text"]
    assert tariff["imported"]["labels"] == ["Essays", "Economics"] and tariff["imported"]["pinned"] is True
    assert tariff["occurred_at"].startswith("2024-02-03")
    groceries = next(x for x in shares if x["imported"]["title"] == "Groceries")
    assert groceries["text"] == "Groceries\n\n- [x] doodh\n- [ ] atta"


def test_keep_notes_can_be_marked_as_not_my_words(unauthenticated_client, db, two):
    item = _post(unauthenticated_client, IMPORT, two["ha"], "takeout.zip", _takeout(),
                 options={"own_words": False, "include_trashed": True}).json()
    assert item["counts"]["shares"] == 3 and item["counts"]["context_only"] == 3


def test_a_single_keep_note_json_is_accepted(unauthenticated_client, two):
    r = _post(unauthenticated_client, IMPORT, two["ha"], "Tariff thoughts.json", _bytes("keep/Tariff thoughts.json"))
    assert r.status_code == 201 and r.json()["importer"] == "google_keep" and r.json()["counts"]["shares"] == 1


# ---------------------------------------------------------------------------
# Embedding, undo, isolation
# ---------------------------------------------------------------------------


def test_embedding_writes_one_vector_per_share_with_tenant_and_import(unauthenticated_client, db, two, chroma, inline):
    item = _post(unauthenticated_client, IMPORT, two["ha"], IOS, _bytes(IOS), options={"self_name": "Rahul"}).json()
    assert item["status"] == "done" and item["counts"]["embedded"] == 5
    vectors = _vectors(chroma, two["a"].id)
    assert len(vectors) == 5
    for share in db.query(Share).filter(Share.import_id == item["id"]):
        meta, doc = vectors[echo_vectors.share_vector_id(share.id)]
        assert share.processing_state == "processed" and share.embedding_id
        assert meta["import_id"] == item["id"] and meta["tenant_id"] == two["a"].id
        assert meta["voice_eligible"] is share.author_is_tenant
        assert doc.strip() and doc in share.extracted_text


def test_an_embedding_failure_is_resumable(unauthenticated_client, db, two, chroma, inline):
    calls = {"n": 0}
    real = echo_vectors.upsert_share_vectors

    def flaky(items):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("chroma down")
        return real(items)

    with patch.object(echo_vectors, "upsert_share_vectors", side_effect=flaky):
        item = _post(unauthenticated_client, IMPORT, two["ha"], IOS, _bytes(IOS)).json()
        assert item["status"] == "failed" and "Retry" in item["error"]
        assert db.query(Share).filter(Share.processing_state == "pending").count() == 5
        retried = unauthenticated_client.post(f"{IMPORTS}/{item['id']}/embed", headers=two["ha"]).json()
    assert retried["status"] == "done" and retried["error"] is None and retried["counts"]["embedded"] == 5


def test_undo_removes_one_import_and_nothing_else(unauthenticated_client, db, two, chroma, inline):
    keep = _post(unauthenticated_client, IMPORT, two["ha"], "takeout.zip", _takeout()).json()
    chat = _post(unauthenticated_client, IMPORT, two["ha"], IOS, _bytes(IOS), options={"self_name": "Rahul"}).json()
    mine = {"id": echo_intake_service.create_text_share(db, two["a"].id, two["a"].id, text="a share of my own").id}
    theirs = _post(unauthenticated_client, IMPORT, two["hb"], IOS, _bytes(IOS)).json()
    assert len(_vectors(chroma, two["a"].id)) == 7

    r = unauthenticated_client.delete(f"{IMPORTS}/{chat['id']}", headers=two["ha"])
    assert r.status_code == 200 and r.json() == {"deleted": True, "shares": 5, "vectors": 5, "facts": 0}

    db.expire_all()
    assert db.query(Share).filter(Share.import_id == chat["id"]).count() == 0
    assert db.get(EchoImport, chat["id"]) is None
    assert db.query(Share).filter(Share.import_id == keep["id"]).count() == 2
    assert db.get(Share, mine["id"]) is not None
    assert len(_vectors(chroma, two["a"].id)) == 2
    assert db.query(Share).filter(Share.import_id == theirs["id"]).count() == 5
    assert len(_vectors(chroma, two["b"].id)) == 5
    listed = unauthenticated_client.get(IMPORTS, headers=two["ha"]).json()["items"]
    assert [i["id"] for i in listed] == [keep["id"]]


def test_another_tenant_cannot_see_or_undo_my_import(unauthenticated_client, db, two):
    item = _post(unauthenticated_client, IMPORT, two["ha"], IOS, _bytes(IOS)).json()
    hb = two["hb"]
    assert unauthenticated_client.get(f"{IMPORTS}/{item['id']}", headers=hb).status_code == 404
    assert unauthenticated_client.delete(f"{IMPORTS}/{item['id']}", headers=hb).status_code == 404
    assert unauthenticated_client.post(f"{IMPORTS}/{item['id']}/embed", headers=hb).status_code == 404
    assert unauthenticated_client.get(IMPORTS, headers=hb).json()["items"] == []
    assert unauthenticated_client.get(SHARES, params={"import_id": item["id"]}, headers=hb).json()["total"] == 0
    assert unauthenticated_client.get(SHARES, params={"origin": "all"}, headers=hb).json()["total"] == 0
    assert db.query(Share).filter(Share.import_id == item["id"]).count() == 5


def test_imports_need_studio(unauthenticated_client, db):
    user = auth_service.create_user(db, email="free-import@example.com", password="pw" * 6)
    token, _ = auth_service.create_access_token(user.id)
    r = _post(unauthenticated_client, PREVIEW, {"Authorization": f"Bearer {token}"}, IOS, _bytes(IOS))
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# One registry (S-3.2.1's ArchiveImporter contract)
# ---------------------------------------------------------------------------


def test_the_importers_meet_the_archive_contract_and_register_once():
    registry.load_builtin()
    for name in ("whatsapp", "google_keep"):
        importer = registry.get_importer(name)
        assert isinstance(importer, ArchiveImporter), name
        assert importer.consent_disclosure and importer.privacy_weight in ("high", "very_high")
    # By filename alone they claim only their own exports.
    assert registry.importer_for("WhatsApp Chat with Asha.txt").name == "whatsapp"
    assert registry.importer_for("folder/_chat.txt").name == "whatsapp"
    assert registry.importer_for("takeout-20241019T101010Z-001.zip").name == "google_keep"
    for other in ("mine.txt", "notes.json", "StreamingHistory_music_0.json", "export.zip"):
        assert registry.importer_for(other) is None, other


def test_a_renamed_export_is_still_recognised_by_its_content():
    pv = _preview_file("chat-backup-final.txt", _bytes(ANDROID))
    assert pv.importer == "whatsapp" and pv.summary["messages"] == 6
    pv = _preview_file("my-notes.zip", _takeout())
    assert pv.importer == "google_keep"


def test_the_contract_parse_works_without_the_extras():
    stream = io.BytesIO(_bytes(ANDROID))
    items = list(whatsapp.IMPORTER.parse(stream, tenant_id="t"))
    assert len(items) == 4 and not any(i.author_is_tenant for i in items)
    assert len({i.external_id for i in items}) == 4
    again = list(whatsapp.IMPORTER.parse(io.BytesIO(_bytes(ANDROID)), tenant_id="t"))
    assert [i.external_id for i in again] == [i.external_id for i in items], "stable across imports"
