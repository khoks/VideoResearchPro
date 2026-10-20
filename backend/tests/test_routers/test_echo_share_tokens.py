"""Adding to Echo from outside the app (S-3.7.3): share tokens, where a quote
or an image came from, and images shared by their address.

A share token is accepted by the share intake endpoints and the connection
check, and nowhere else. Image fetching runs against a mocked HTTP transport
and a mocked DNS, so nothing leaves the machine.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.models.echo_share_token import EchoShareToken
from app.models.share import Share
from app.services import auth_service, echo_media, echo_processing_service, echo_share_token_service
from app.services.echo_media import OcrResult

SHARES = "/api/v1/echo/shares"
TOKENS = "/api/v1/echo/share-tokens"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _studio(db, email):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def chroma(monkeypatch):
    """In-memory Chroma: processing embeds what it reads, and no test may
    write to a persistent store."""
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
    a, ha = _studio(db, "tok-a@example.com")
    b, hb = _studio(db, "tok-b@example.com")
    return {"a": a, "ha": ha, "b": b, "hb": hb}


def _make(client, headers, label="Chrome"):
    r = client.post(TOKENS, json={"label": label}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    return body, {"Authorization": f"Bearer {body['token']}"}


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def test_a_token_is_shown_once_and_stored_as_a_hash(unauthenticated_client, db, two):
    body, _ = _make(unauthenticated_client, two["ha"], "Chrome on the laptop")
    assert body["token"].startswith("pec_") and len(body["token"]) > 40
    assert body["prefix"] == body["token"][:10] and body["label"] == "Chrome on the laptop"
    listed = unauthenticated_client.get(TOKENS, headers=two["ha"]).json()
    assert listed["max"] == settings.ECHO_SHARE_TOKENS_MAX
    assert [t["id"] for t in listed["items"]] == [body["id"]] and "token" not in listed["items"][0]
    row = db.get(EchoShareToken, body["id"])
    assert row.tenant_id == two["a"].id and row.token_hash != body["token"] and len(row.token_hash) == 64
    stored = json.dumps({c.name: str(getattr(row, c.name)) for c in row.__table__.columns})
    assert body["token"] not in stored


def test_a_token_adds_shares_and_does_nothing_else(unauthenticated_client, db, two):
    _, tok = _make(unauthenticated_client, two["ha"])
    link = unauthenticated_client.post(SHARES, json={"url": "https://example.org/a", "surface": "browser_ext"}, headers=tok)
    assert link.status_code == 201, link.text
    quote = unauthenticated_client.post(SHARES, json={"text": "importers pay", "surface": "browser_ext"}, headers=tok)
    upload = unauthenticated_client.post(f"{SHARES}/upload", headers=tok, data={"surface": "browser_ext"},
                                         files={"file": ("n.txt", b"a note", "text/plain")})
    assert quote.status_code == 201 and upload.status_code == 201
    rows = db.query(Share).filter(Share.tenant_id == two["a"].id).all()
    assert len(rows) == 3 and {r.surface for r in rows} == {"browser_ext"}
    assert all(not r.author_is_tenant for r in rows), "a quote is context only unless the user says otherwise"

    for method, path in (("GET", SHARES), ("GET", f"{SHARES}/{link.json()['id']}"), ("GET", TOKENS),
                         ("POST", TOKENS), ("GET", "/api/v1/echo/export"), ("GET", "/api/v1/auth/me"),
                         ("DELETE", f"{SHARES}/{link.json()['id']}")):
        r = unauthenticated_client.request(method, path, headers=tok, json={"label": "x"} if method == "POST" else None)
        assert r.status_code == 401, (method, path, r.status_code)


def test_revoked_tokens_stop_working_and_only_their_owner_can_revoke(unauthenticated_client, db, two):
    body, tok = _make(unauthenticated_client, two["ha"])
    assert unauthenticated_client.delete(f"{TOKENS}/{body['id']}", headers=two["hb"]).status_code == 404
    assert unauthenticated_client.post(SHARES, json={"text": "still works"}, headers=tok).status_code == 201
    assert unauthenticated_client.delete(f"{TOKENS}/{body['id']}", headers=two["ha"]).json() == {"revoked": True}
    assert unauthenticated_client.post(SHARES, json={"text": "now refused"}, headers=tok).status_code == 401
    assert unauthenticated_client.get(TOKENS, headers=two["ha"]).json()["items"] == []
    assert unauthenticated_client.delete(f"{TOKENS}/{body['id']}", headers=two["ha"]).status_code == 404


def test_a_downgraded_account_tokens_stop_at_the_studio_check(unauthenticated_client, db, two):
    _, tok = _make(unauthenticated_client, two["ha"])
    two["a"].tier = "free"
    db.commit()
    r = unauthenticated_client.post(SHARES, json={"text": "x"}, headers=tok)
    assert r.status_code == 403 and "Studio" in r.json()["detail"]


def test_the_check_says_who_and_how(unauthenticated_client, db, two):
    _, tok = _make(unauthenticated_client, two["ha"])
    assert unauthenticated_client.get(f"{TOKENS}/check", headers=tok).json() == {
        "ok": True, "email": "tok-a@example.com", "via": "share_token",
    }
    assert unauthenticated_client.get(f"{TOKENS}/check", headers=two["ha"]).json()["via"] == "session"
    bogus = {"Authorization": "Bearer pec_" + "x" * 43}
    assert unauthenticated_client.get(f"{TOKENS}/check", headers=bogus).status_code == 401


def test_tokens_are_capped_and_last_use_is_recorded(unauthenticated_client, db, two, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARE_TOKENS_MAX", 2)
    body, tok = _make(unauthenticated_client, two["ha"])
    _make(unauthenticated_client, two["ha"])
    r = unauthenticated_client.post(TOKENS, json={"label": "third"}, headers=two["ha"])
    assert r.status_code == 409 and "revoke one" in r.json()["detail"]
    assert db.get(EchoShareToken, body["id"]).last_used_at is None
    unauthenticated_client.post(SHARES, json={"text": "x"}, headers=tok)
    db.expire_all()
    assert db.get(EchoShareToken, body["id"]).last_used_at is not None
    assert unauthenticated_client.get(TOKENS, headers=two["ha"]).json()["items"][-1]["last_used_at"]


def test_another_tenants_token_writes_only_to_that_tenant(unauthenticated_client, db, two):
    _, tok_b = _make(unauthenticated_client, two["hb"])
    s = unauthenticated_client.post(SHARES, json={"text": "B's quote"}, headers=tok_b).json()
    assert db.get(Share, s["id"]).tenant_id == two["b"].id
    assert unauthenticated_client.get(SHARES, headers=two["ha"]).json()["total"] == 0


def test_authenticate_ignores_anything_that_is_not_a_share_token(db, two):
    assert echo_share_token_service.authenticate(db, "eyJhbGciOiJIUzI1NiJ9.x.y") is None
    assert echo_share_token_service.authenticate(db, "") is None


# ---------------------------------------------------------------------------
# Where a quote or an image came from
# ---------------------------------------------------------------------------


def test_a_quote_keeps_its_page(unauthenticated_client, db, two):
    r = unauthenticated_client.post(SHARES, headers=two["ha"], json={
        "text": "Tariffs are paid by importers.", "surface": "browser_ext",
        "source_url": "https://example.org/essays/tariffs", "source_title": "  Who   pays  ",
    })
    assert r.status_code == 201
    assert r.json()["source"] == {"url": "https://example.org/essays/tariffs", "title": "Who pays"}
    bad = unauthenticated_client.post(SHARES, headers=two["ha"], json={"text": "x", "source_url": "javascript:alert(1)"})
    assert bad.status_code == 422
    plain = unauthenticated_client.post(SHARES, headers=two["ha"], json={"text": "no source"}).json()
    assert plain["source"] is None


# ---------------------------------------------------------------------------
# Images shared by their address
# ---------------------------------------------------------------------------


@pytest.fixture
def web(monkeypatch):
    """A fake internet: DNS answers per host, HTTP answers per URL."""
    dns: dict[str, str] = {}
    pages: dict[str, httpx.Response] = {}

    def getaddrinfo(host, port):
        if host not in dns:
            raise socket.gaierror("unknown host")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (dns[host], port))]

    def handler(request: httpx.Request) -> httpx.Response:
        return pages.get(str(request.url), httpx.Response(404))

    # Patch echo_media's seams only: a process-wide patch of httpx or the
    # resolver leaks into libraries that cache clients (huggingface_hub does).
    monkeypatch.setattr(echo_media, "_getaddrinfo", getaddrinfo)
    monkeypatch.setattr(echo_media, "_http_client", lambda **kw: httpx.Client(transport=httpx.MockTransport(handler), **kw))
    return dns, pages


def _image_share(client, headers, url):
    r = client.post(SHARES, headers=headers, json={"url": url, "content_type": "image", "surface": "browser_ext",
                                                   "source_url": "https://example.org/post"})
    assert r.status_code == 201, r.text
    return r.json()


def test_an_image_address_is_fetched_read_and_deleted_with_its_share(unauthenticated_client, db, two, web, monkeypatch):
    dns, pages = web
    dns["cdn.example.org"] = "93.184.216.34"
    pages["https://cdn.example.org/chart.png"] = httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
    s = _image_share(unauthenticated_client, two["ha"], "https://cdn.example.org/chart.png")
    seen = {}

    def fake_load(path):
        seen["bytes"] = path.read_bytes()
        return object()

    monkeypatch.setattr(echo_media, "load_image", fake_load)
    monkeypatch.setattr(echo_media, "ocr_local", lambda image: OcrResult("Imports fell by two thirds", 0.98, 1))
    assert echo_processing_service.process_share(db, s["id"]).state == "processed"
    row = db.get(Share, s["id"])
    assert seen["bytes"] == PNG and row.extracted_text == "Imports fell by two thirds"
    assert row.file_path and row.file_path.startswith(f"{two['a'].id}/") and row.file_path.endswith(".png")
    root = Path(settings.ECHO_SHARES_DIR)
    path = root / row.file_path
    assert path.read_bytes() == PNG
    assert unauthenticated_client.delete(f"{SHARES}/{s['id']}", headers=two["ha"]).json()["files"] == 1
    assert not path.exists() and root.exists()


@pytest.mark.parametrize("ip", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.20"])
def test_an_image_on_a_private_address_is_not_fetched(unauthenticated_client, db, two, web, ip):
    dns, pages = web
    dns["internal.example"] = ip
    pages["http://internal.example/secret.png"] = httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
    s = _image_share(unauthenticated_client, two["ha"], "http://internal.example/secret.png")
    result = echo_processing_service.process_share(db, s["id"])
    assert result.state == "failed" and "private network" in result.reason
    assert db.get(Share, s["id"]).file_path is None


def test_a_redirect_into_a_private_network_is_refused(unauthenticated_client, db, two, web):
    dns, pages = web
    dns["cdn.example.org"] = "93.184.216.34"
    dns["metadata.internal"] = "169.254.169.254"
    pages["https://cdn.example.org/a.png"] = httpx.Response(302, headers={"location": "http://metadata.internal/latest"})
    s = _image_share(unauthenticated_client, two["ha"], "https://cdn.example.org/a.png")
    result = echo_processing_service.process_share(db, s["id"])
    assert result.state == "failed" and "private network" in result.reason


def test_only_images_within_the_size_cap_are_kept(unauthenticated_client, db, two, web, monkeypatch):
    dns, pages = web
    dns["cdn.example.org"] = "93.184.216.34"
    pages["https://cdn.example.org/page.png"] = httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>")
    pages["https://cdn.example.org/huge.png"] = httpx.Response(200, headers={"content-type": "image/png"}, content=PNG * 100)
    html = _image_share(unauthenticated_client, two["ha"], "https://cdn.example.org/page.png")
    assert "does not serve an image" in echo_processing_service.process_share(db, html["id"]).reason
    monkeypatch.setattr(settings, "ECHO_SHARE_MAX_BYTES", 1000)
    huge = _image_share(unauthenticated_client, two["ha"], "https://cdn.example.org/huge.png")
    assert "larger than a share" in echo_processing_service.process_share(db, huge["id"]).reason
    assert list((Path(settings.ECHO_SHARES_DIR) / two["a"].id).glob(f"{huge['id']}*")) == []


def test_a_private_lan_image_can_be_allowed_on_a_self_hosted_install(unauthenticated_client, db, two, web, monkeypatch):
    dns, pages = web
    dns["nas.local"] = "192.168.1.20"
    pages["http://nas.local/scan.png"] = httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
    monkeypatch.setattr(settings, "ECHO_FETCH_ALLOW_PRIVATE", True)
    monkeypatch.setattr(echo_media, "load_image", lambda path: object())
    monkeypatch.setattr(echo_media, "ocr_local", lambda image: OcrResult("a scanned page of text", 0.97, 1))
    s = _image_share(unauthenticated_client, two["ha"], "http://nas.local/scan.png")
    assert echo_processing_service.process_share(db, s["id"]).state == "processed"


def test_an_image_link_is_recognised_by_its_extension_too(db, two):
    share = Share(id="x", tenant_id="t", user_id="t", surface="browser_ext", content_type="link",
                  raw_payload_json="{}", author_is_tenant=False, processing_state="pending")
    assert echo_processing_service._is_image_url(share, "https://cdn.example.org/a/photo.JPG?w=800")
    assert not echo_processing_service._is_image_url(share, "https://example.org/article")
