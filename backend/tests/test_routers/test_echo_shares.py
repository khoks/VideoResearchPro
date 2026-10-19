"""Echo shares inbox (S-3.7.1): `/api/v1/echo/shares`.

Asserted here:

- the routes are mounted and gated on the Studio-only `echo_personal_brain`
  feature (403 for Free, 401 without a token);
- link, text and file shares are stored with an inferred, correctable
  content type, `pending`, and **context-only by default** (`author_is_tenant`
  false);
- files land under `ECHO_SHARES_DIR/<tenant>/` with a name we choose, never
  the client's, so a traversal filename writes nothing outside; the size cap
  refuses before anything is written; downloads are attachments, never sniffed;
- a row whose stored path was tampered to point at another tenant's file
  cannot read or delete it;
- two tenants never see, edit, download or delete each other's shares;
- deleting one share removes its row, its file, its vector and the facts it
  produced, and nothing of anyone else's.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.models.personal_context import PersonalContext
from app.models.share import Share
from app.services import auth_service, echo_service, echo_vectors

SHARES = "/api/v1/echo/shares"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    """In-memory Chroma; the Echo collections only exist once a test writes."""
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield client
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


def add_vector(client, collection: str, vector_id: str, tenant_id: str) -> None:
    col = client.get_or_create_collection(name=collection)
    col.add(
        ids=[vector_id],
        embeddings=[[0.1, 0.2, 0.3]],
        metadatas=[{"tenant_id": tenant_id}],
        documents=["x"],
    )


@pytest.fixture
def two(db, shares_dir, chroma):
    a, ha = _studio(db, "echo-a@example.com")
    b, hb = _studio(db, "echo-b@example.com")
    return {"a": a, "ha": ha, "b": b, "hb": hb}


def _upload(client, headers, name="meme.png", data=b"\x89PNG fake", mime="image/png", **form):
    return client.post(
        f"{SHARES}/upload",
        files={"file": (name, data, mime)},
        data={k: str(v).lower() if isinstance(v, bool) else v for k, v in form.items()},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


def test_shares_require_studio(unauthenticated_client, db, shares_dir):
    free = auth_service.create_user(db, email="echo-free@example.com", password="pw" * 6)
    token, _ = auth_service.create_access_token(free.id)
    h = {"Authorization": f"Bearer {token}"}
    c = unauthenticated_client
    assert c.get(SHARES, headers=h).status_code == 403
    assert c.post(SHARES, json={"text": "x"}, headers=h).status_code == 403
    assert _upload(c, h).status_code == 403
    assert c.get("/api/v1/echo/export", headers=h).status_code == 403
    assert c.delete("/api/v1/echo/brain", params={"confirm": "delete-everything"}, headers=h).status_code == 403
    assert not shares_dir.exists(), "a refused upload must write nothing"


def test_shares_require_auth(unauthenticated_client):
    assert unauthenticated_client.get(SHARES).status_code == 401


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_link_share_infers_type_and_is_context_only_by_default(unauthenticated_client, two):
    r = unauthenticated_client.post(
        SHARES,
        json={"url": "https://www.youtube.com/watch?v=abc123", "annotation": "how I think about tariffs"},
        headers=two["ha"],
    )
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["kind"] == "url" and s["url"] == "https://www.youtube.com/watch?v=abc123"
    assert s["content_type"] == "youtube_video"
    assert s["surface"] == "manual_quick_share"
    assert s["processing_state"] == "pending"
    assert s["author_is_tenant"] is False, "third-party content is context-only unless the user says otherwise"
    assert s["user_annotation"] == "how I think about tariffs"
    assert s["text"] is None and s["file"] is None
    assert s["received_at"].endswith("Z") or "+00:00" in s["received_at"]


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://youtu.be/abc", "youtube_video"),
        ("https://www.youtube.com/shorts/abc", "youtube_short"),
        ("https://www.instagram.com/reel/xyz/", "instagram_reel"),
        ("https://x.com/someone/status/1", "tweet"),
        ("https://example.org/essay", "link"),
    ],
)
def test_content_type_inference(unauthenticated_client, two, url, expected):
    r = unauthenticated_client.post(SHARES, json={"url": url}, headers=two["ha"])
    assert r.json()["content_type"] == expected


def test_text_share_keeps_the_words_and_own_authorship(unauthenticated_client, two):
    text = "अहिंसा परमो धर्मः — the line I keep coming back to."
    r = unauthenticated_client.post(
        SHARES,
        json={"text": text, "content_type": "book_quote", "author_is_tenant": True},
        headers=two["ha"],
    )
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["kind"] == "text" and s["text"] == text
    assert s["content_type"] == "book_quote"
    assert s["author_is_tenant"] is True


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"url": "https://a.example", "text": "both"},
        {"url": "ftp://example.org/file"},
        {"url": "javascript:alert(1)"},
        {"text": "   "},
        {"text": "ok", "content_type": "Not A Type"},
        {"text": "ok", "surface": "carrier_pigeon"},
    ],
)
def test_invalid_shares_are_422(unauthenticated_client, two, body):
    assert unauthenticated_client.post(SHARES, json=body, headers=two["ha"]).status_code == 422


def test_text_over_cap_is_413(unauthenticated_client, two, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARE_TEXT_MAX_CHARS", 10)
    r = unauthenticated_client.post(SHARES, json={"text": "x" * 11}, headers=two["ha"])
    assert r.status_code == 413


def test_file_share_is_stored_under_the_tenant_and_downloads_as_attachment(
    unauthenticated_client, db, two, shares_dir
):
    data = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    r = _upload(unauthenticated_client, two["ha"], "Meme 1.PNG", data, "image/png",
                annotation="this is me every Monday")
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["kind"] == "file" and s["content_type"] == "image"
    assert s["file"] == {"filename": "Meme 1.PNG", "mime": "image/png", "size": len(data)}

    row = db.get(Share, s["id"])
    stored = shares_dir.resolve() / row.file_path
    assert stored.parent == (shares_dir / two["a"].id).resolve()
    assert stored.name == f"{s['id']}.png", "the stored name is ours, not the client's"
    assert stored.read_bytes() == data
    assert json.loads(row.raw_payload_json)["sha256"]

    dl = unauthenticated_client.get(f"{SHARES}/{s['id']}/file", headers=two["ha"])
    assert dl.status_code == 200
    assert dl.content == data
    assert dl.headers["content-disposition"].startswith("attachment")
    assert dl.headers["x-content-type-options"] == "nosniff"


def test_traversal_filename_writes_nothing_outside(unauthenticated_client, db, two, shares_dir, tmp_path):
    r = _upload(unauthenticated_client, two["ha"], "../../../escape.sh", b"echo pwned", "text/x-sh")
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["file"]["filename"] == "escape.sh"
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written == [(shares_dir / two["a"].id / f"{s['id']}.sh").resolve()] or all(
        p.resolve().is_relative_to((shares_dir / two["a"].id).resolve()) for p in written
    )
    assert not (tmp_path / "escape.sh").exists()


def test_upload_over_cap_is_413_and_writes_nothing(unauthenticated_client, two, shares_dir, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARE_MAX_BYTES", 16)
    r = _upload(unauthenticated_client, two["ha"], "big.bin", b"x" * 17, "application/octet-stream")
    assert r.status_code == 413
    assert not any(p.is_file() for p in shares_dir.rglob("*")) if shares_dir.exists() else True
    r = _upload(unauthenticated_client, two["ha"], "empty.bin", b"", "application/octet-stream")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# List, edit
# ---------------------------------------------------------------------------


def test_list_newest_first_with_search_and_state(unauthenticated_client, db, two):
    h = two["ha"]
    first = unauthenticated_client.post(SHARES, json={"text": "first about dumplings"}, headers=h).json()
    second = unauthenticated_client.post(SHARES, json={"url": "https://example.org/tariffs"}, headers=h).json()
    # Pin order against same-tick timestamps.
    row = db.get(Share, first["id"])
    row.received_at = row.received_at.replace(year=2020)
    db.commit()

    r = unauthenticated_client.get(SHARES, headers=h).json()
    assert [s["id"] for s in r["items"]] == [second["id"], first["id"]]
    assert r["total"] == 2

    assert [s["id"] for s in unauthenticated_client.get(SHARES, params={"q": "tariffs"}, headers=h).json()["items"]] == [second["id"]]
    assert unauthenticated_client.get(SHARES, params={"state": "processed"}, headers=h).json()["total"] == 0
    assert unauthenticated_client.get(SHARES, params={"state": "pending"}, headers=h).json()["total"] == 2
    assert unauthenticated_client.get(SHARES, params={"state": "weird"}, headers=h).status_code == 422


def test_patch_annotation_type_and_authorship(unauthenticated_client, two):
    h = two["ha"]
    s = unauthenticated_client.post(SHARES, json={"url": "https://example.org/a"}, headers=h).json()
    r = unauthenticated_client.patch(
        f"{SHARES}/{s['id']}",
        json={"annotation": "  my take  ", "content_type": "bookmark", "author_is_tenant": True},
        headers=h,
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["user_annotation"] == "my take"
    assert got["content_type"] == "bookmark"
    assert got["author_is_tenant"] is True
    # Omitted fields are untouched; annotation null clears it.
    r = unauthenticated_client.patch(f"{SHARES}/{s['id']}", json={"annotation": None}, headers=h)
    assert r.json()["user_annotation"] is None and r.json()["content_type"] == "bookmark"
    assert unauthenticated_client.patch(f"{SHARES}/{s['id']}", json={"content_type": "BAD"}, headers=h).status_code == 422
    assert unauthenticated_client.patch(f"{SHARES}/missing", json={"annotation": "x"}, headers=h).status_code == 404


# ---------------------------------------------------------------------------
# Two tenants
# ---------------------------------------------------------------------------


def test_two_tenants_never_touch_each_others_shares(unauthenticated_client, db, two, shares_dir):
    c, ha, hb = unauthenticated_client, two["ha"], two["hb"]
    mine = _upload(c, ha, "a.txt", b"A's private words", "text/plain").json()
    theirs = c.post(SHARES, json={"text": "B's thought"}, headers=hb).json()

    a_list = c.get(SHARES, headers=ha).json()
    b_list = c.get(SHARES, headers=hb).json()
    assert {s["id"] for s in a_list["items"]} == {mine["id"]}
    assert {s["id"] for s in b_list["items"]} == {theirs["id"]}
    assert "B's thought" not in c.get(SHARES, headers=ha).text

    for verb, url, kw in (
        ("get", f"{SHARES}/{mine['id']}", {}),
        ("get", f"{SHARES}/{mine['id']}/file", {}),
        ("patch", f"{SHARES}/{mine['id']}", {"json": {"annotation": "vandal"}}),
        ("delete", f"{SHARES}/{mine['id']}", {}),
    ):
        r = getattr(c, verb)(url, headers=hb, **kw)
        assert r.status_code == 404, f"{verb} {url} -> {r.status_code}"

    row = db.get(Share, mine["id"])
    assert row is not None and row.user_annotation is None
    assert (shares_dir.resolve() / row.file_path).read_bytes() == b"A's private words"


def test_a_tampered_path_cannot_reach_another_tenants_file(unauthenticated_client, db, two, shares_dir):
    c = unauthenticated_client
    victim = _upload(c, two["hb"], "secret.txt", b"B secret", "text/plain").json()
    attacker = _upload(c, two["ha"], "mine.txt", b"A", "text/plain").json()
    victim_rel = db.get(Share, victim["id"]).file_path
    row = db.get(Share, attacker["id"])
    own_file = shares_dir.resolve() / row.file_path
    row.file_path = victim_rel  # e.g. a corrupted or hand-edited row
    db.commit()

    assert c.get(f"{SHARES}/{attacker['id']}/file", headers=two["ha"]).status_code == 404
    assert c.delete(f"{SHARES}/{attacker['id']}", headers=two["ha"]).status_code == 200
    assert (shares_dir.resolve() / victim_rel).read_bytes() == b"B secret", "B's file must survive"
    own_file.unlink()


# ---------------------------------------------------------------------------
# Delete one share: the cascade
# ---------------------------------------------------------------------------


def test_delete_share_removes_row_file_vector_and_derived_facts(unauthenticated_client, db, two, shares_dir, chroma):
    c, a, b = unauthenticated_client, two["a"], two["b"]
    s = _upload(c, two["ha"], "memo.m4a", b"voice", "audio/mp4").json()
    assert s["content_type"] == "voice_memo"
    other = c.post(SHARES, json={"text": "B keeps this"}, headers=two["hb"]).json()

    fact = echo_service.record_context(
        db, user_id=a.id, kind="interest", key="tariffs", value="from the memo", source="share"
    )
    keep = echo_service.record_context(
        db, user_id=a.id, kind="hobby", key="running", value="manual", source="manual"
    )
    fact_id, keep_id = fact.id, keep.id
    row = db.get(Share, s["id"])
    row.derived_fact_ids_json = json.dumps([fact_id])
    db.commit()
    add_vector(chroma, settings.CHROMA_SHARES_COLLECTION_NAME, echo_vectors.share_vector_id(s["id"]), a.id)
    add_vector(chroma, settings.CHROMA_SHARES_COLLECTION_NAME, echo_vectors.share_vector_id(other["id"]), b.id)
    stored = shares_dir.resolve() / row.file_path
    assert stored.exists()

    r = c.delete(f"{SHARES}/{s['id']}", headers=two["ha"])
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": True, "vectors": 1, "files": 1, "derived_facts": 1}

    db.expire_all()
    assert db.get(Share, s["id"]) is None
    assert not stored.exists()
    assert db.get(PersonalContext, fact_id) is None
    assert db.get(PersonalContext, keep_id) is not None, "only the share's own facts go"
    col = chroma.get_collection(settings.CHROMA_SHARES_COLLECTION_NAME)
    assert col.get(ids=[echo_vectors.share_vector_id(s["id"])])["ids"] == []
    assert col.get(ids=[echo_vectors.share_vector_id(other["id"])])["ids"] != [], "B's vector survives"
    assert c.delete(f"{SHARES}/{s['id']}", headers=two["ha"]).status_code == 404


# ---------------------------------------------------------------------------
# Status and facts
# ---------------------------------------------------------------------------


def test_status_reports_shares_without_gating(unauthenticated_client, two):
    c, h = unauthenticated_client, two["ha"]
    before = c.get("/api/v1/echo/status", headers=h).json()
    c.post(SHARES, json={"text": "one"}, headers=h)
    c.post(SHARES, json={"url": "https://example.org/two"}, headers=h)
    after = c.get("/api/v1/echo/status", headers=h).json()
    assert before["shares_total"] == 0 and after["shares_total"] == 2
    assert after["ready"] is before["ready"] is False
    assert c.get("/api/v1/echo/status", headers=two["hb"]).json()["shares_total"] == 0


def test_record_context_stamps_tenant_id(db, two):
    row = echo_service.record_context(
        db, user_id=two["a"].id, kind="interest", key="x", value="y", source="manual"
    )
    assert row.tenant_id == two["a"].id
