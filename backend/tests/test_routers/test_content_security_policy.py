"""T-4.11.2.1: the Content-Security-Policy on what the API serves.

The route-level checks for the file routes sit with each route's own tests
(the PDF, a share's file, Author downloads, a frame, ``report.md``, the
exports). The policies themselves are worth stating as literals here: a change
to one should be a change someone chose to make.

The header alone cannot show a script stays still, so this was also run by hand
in Chromium through Playwright when it shipped: a stored report with an inline
script, a handler and a ``javascript:`` link ran none of them and kept its
styles, its ``target="_blank"`` links opened, and ``/docs`` and ``/redoc``
rendered from the live CDNs with no violation in the console.

Mutation checks (each failed the named test when this shipped): taking the
middleware out of ``app/main.py`` (all of them); adding it before CORS
(``test_a_preflight_carries_it``); adding it before the limiter
(``test_a_rate_limited_response_carries_it``); ``'unsafe-inline'`` in Swagger's
``script-src`` (``test_swagger_allows_its_one_inline_script_by_hash``); a stale
hash (the same test); ``allow-scripts`` on the report
(``test_the_stored_report_can_run_nothing``); holding every response to hash it
(``test_a_stream_is_not_held_back``).
"""
from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from unittest.mock import patch

import anyio
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.middleware.content_security_policy import (
    API_POLICY,
    FILE_POLICY,
    REPORT_POLICY,
    ContentSecurityPolicyMiddleware,
)
from app.models.job import Job
from app.services import rate_limit_service

HEADER = "content-security-policy"


def _directives(policy: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for directive in policy.split(";"):
        name, *values = directive.split()
        parsed[name] = values
    return parsed


def test_the_policies_are_exactly_these():
    assert API_POLICY == "default-src 'none'; frame-ancestors 'none'"
    assert FILE_POLICY == "default-src 'none'; frame-ancestors 'none'; sandbox"
    assert REPORT_POLICY == (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'; sandbox allow-popups allow-popups-to-escape-sandbox"
    )


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def test_json_gets_the_bare_policy(unauthenticated_client):
    r = unauthenticated_client.get("/api/v1/auth/oauth/providers")
    assert r.status_code == 200
    assert r.headers[HEADER] == API_POLICY


@pytest.mark.parametrize(
    "method, path, expected",
    [
        ("get", "/api/v1/auth/me", 401),
        ("get", "/api/v1/nothing-here", 404),
        ("post", "/api/v1/auth/login", 422),
        ("delete", "/api/v1/auth/oauth/providers", 405),
    ],
)
def test_an_error_gets_it_too(unauthenticated_client, method, path, expected):
    r = getattr(unauthenticated_client, method)(path)
    assert r.status_code == expected
    assert r.headers[HEADER] == API_POLICY


def test_a_rate_limited_response_carries_it(unauthenticated_client, monkeypatch):
    """The limiter answers from inside this middleware, not from a route."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_MIN", 1)
    monkeypatch.setattr(rate_limit_service, "_now", lambda: 1_000_020)
    rate_limit_service.reset()
    body = {"email": "csp@x.com", "password": "wrong-password"}
    unauthenticated_client.post("/api/v1/auth/login", json=body)
    r = unauthenticated_client.post("/api/v1/auth/login", json=body)
    rate_limit_service.reset()
    assert r.status_code == 429
    assert r.headers[HEADER] == API_POLICY


def test_a_preflight_carries_it(unauthenticated_client):
    r = unauthenticated_client.options(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 200
    assert HEADER in r.headers


def test_the_openapi_document_is_json(unauthenticated_client):
    assert unauthenticated_client.get("/openapi.json").headers[HEADER] == API_POLICY


# ---------------------------------------------------------------------------
# The stored report
# ---------------------------------------------------------------------------


REPORT = (
    "<!DOCTYPE html><html><head><title>t</title><style>body { color: red; }</style></head>"
    "<body onload=\"window.ran = 'handler'\"><script>window.ran = 'inline';</script>"
    '<a href="https://www.youtube.com/watch?v=x" target="_blank">00:10</a></body></html>'
)


def _job_with_report(db, tenant_id: str, path) -> Job:
    job = Job(
        job_type="topic",
        topic="csp",
        status="completed",
        num_videos=1,
        report_path=str(path),
        tenant_id=tenant_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_the_stored_report_can_run_nothing(client, db, test_user, tmp_path):
    path = tmp_path / "report.html"
    path.write_text(REPORT, encoding="utf-8")
    job = _job_with_report(db, test_user.id, path)

    r = client.get(f"/api/v1/jobs/{job.id}/report")

    assert r.status_code == 200
    assert r.text == REPORT, "the route serves the file as stored; the header is what stops it"
    assert r.headers["content-type"].startswith("text/html")
    policy = r.headers[HEADER]
    assert policy == REPORT_POLICY
    directives = _directives(policy)
    assert directives["default-src"] == ["'none'"]
    assert "script-src" not in directives, "scripts must fall back to default-src 'none'"
    assert "allow-scripts" not in directives["sandbox"]
    assert "allow-same-origin" not in directives["sandbox"]


def test_the_frames_flags_and_the_reports_match():
    """``REPORT_FRAME_SANDBOX`` in utils/reportDocument.ts shows these bytes
    too, so its links work the same both ways."""
    frontend = (Path(__file__).resolve().parents[3] / "frontend/src/utils/reportDocument.ts").read_text(
        encoding="utf-8"
    )
    flags = re.search(r"REPORT_FRAME_SANDBOX = '([^']+)'", frontend).group(1).split()
    assert flags == _directives(REPORT_POLICY)["sandbox"]


def test_a_report_that_is_not_there_is_a_json_404(client, db, test_user, tmp_path):
    job = _job_with_report(db, test_user.id, tmp_path / "gone.html")
    r = client.get(f"/api/v1/jobs/{job.id}/report")
    assert r.status_code == 404
    assert r.headers[HEADER] == API_POLICY


def test_the_report_body_route_is_plain_json(client, db, test_user):
    job = _job_with_report(db, test_user.id, "/fake/report.html")
    with patch("app.routers.reports.report_service.get_report_html", return_value=REPORT):
        r = client.get(f"/api/v1/jobs/{job.id}/report/body")
    assert r.status_code == 200
    assert r.headers[HEADER] == API_POLICY


# ---------------------------------------------------------------------------
# The API docs
# ---------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return f"'sha256-{base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()}'"


def _loaded_by(page: str) -> list[str]:
    return re.findall(r'(?:src|href)="(https?://[^"]+)"', page)


def test_swagger_allows_its_one_inline_script_by_hash(unauthenticated_client):
    r = unauthenticated_client.get("/docs")
    assert r.status_code == 200
    directives = _directives(r.headers[HEADER])

    inline = re.findall(r"<script>(.*?)</script>", r.text, re.S)
    assert len(inline) == 1
    assert _sha256(inline[0]) in directives["script-src"]
    assert "'unsafe-inline'" not in directives["script-src"]
    assert "'unsafe-eval'" not in directives["script-src"]


def test_swagger_may_load_what_its_page_links(unauthenticated_client):
    r = unauthenticated_client.get("/docs")
    directives = _directives(r.headers[HEADER])
    sources = directives["script-src"] + directives["style-src"] + directives["img-src"]
    for url in _loaded_by(r.text):
        assert any(url.startswith(s) for s in sources if s.startswith("https://")), url


def test_redoc_may_load_what_its_page_links_and_runs_no_inline_script(unauthenticated_client):
    r = unauthenticated_client.get("/redoc")
    assert r.status_code == 200
    directives = _directives(r.headers[HEADER])
    assert directives["worker-src"] == ["blob:"]
    assert not any(s.startswith("'sha256-") for s in directives["script-src"])
    sources = directives["script-src"] + directives["style-src"] + directives["img-src"]
    for url in _loaded_by(r.text):
        assert any(url.startswith(s) for s in sources if s.startswith("https://")), url


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_a_docs_page_keeps_its_length_and_body(unauthenticated_client, path):
    r = unauthenticated_client.get(path)
    assert r.headers["content-length"] == str(len(r.content))
    assert "<html>" in r.text


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_a_docs_page_cannot_be_framed_or_post_elsewhere(unauthenticated_client, path):
    directives = _directives(unauthenticated_client.get(path).headers[HEADER])
    assert directives["frame-ancestors"] == ["'none'"]
    assert directives["base-uri"] == ["'none'"]
    assert directives["form-action"] == ["'none'"]
    assert directives["default-src"] == ["'none'"]


def test_the_swagger_oauth_page_stays_locked(unauthenticated_client):
    """Only an OAuth2 redirect flow lands on this page, and the one flow the
    API declares is the password flow, which Swagger runs with a fetch."""
    schemes = app.openapi()["components"]["securitySchemes"].values()
    flows = {flow for scheme in schemes for flow in scheme.get("flows", {})}
    assert flows == {"password"}

    r = unauthenticated_client.get("/docs/oauth2-redirect")
    assert r.status_code == 200
    assert r.headers[HEADER] == FILE_POLICY


# ---------------------------------------------------------------------------
# The middleware itself
# ---------------------------------------------------------------------------


def _html_app(scope, receive, send):
    async def _run():
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/html")]})
        await send({"type": "http.response.body", "body": b"<svg onload=alert(1)>"})

    return _run()


def test_a_route_nobody_named_starts_locked():
    client = TestClient(ContentSecurityPolicyMiddleware(_html_app))
    assert client.get("/api/v1/some/new/page").headers[HEADER] == FILE_POLICY


def test_a_look_alike_path_is_not_the_report():
    client = TestClient(ContentSecurityPolicyMiddleware(_html_app))
    for path in ("/api/v1/jobs/a/report/x", "/x/api/v1/jobs/a/report", "/api/v1/jobs/a/b/report"):
        assert client.get(path).headers[HEADER] == FILE_POLICY


def test_a_stream_is_not_held_back():
    """The Q&A stream's first event must leave before the next is ready."""
    sent: list[str] = []

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
        await send({"type": "http.response.body", "body": b"data: one\n\n", "more_body": True})
        assert sent == ["http.response.start", "http.response.body"], "still buffered"
        await send({"type": "http.response.body", "body": b"data: two\n\n"})

    async def outer(message):
        sent.append(message["type"])

    async def receive():
        return {"type": "http.request"}

    scope = {"type": "http", "path": "/api/v1/jobs/j/qa/stream"}
    anyio.run(ContentSecurityPolicyMiddleware(inner), scope, receive, outer)
    assert len(sent) == 3


def test_a_websocket_passes_straight_through():
    seen: list[dict] = []

    async def inner(scope, receive, send):
        await send({"type": "websocket.accept"})

    async def outer(message):
        seen.append(message)

    async def receive():
        return {}

    anyio.run(ContentSecurityPolicyMiddleware(inner), {"type": "websocket", "path": "/ws/jobs"}, receive, outer)
    assert seen == [{"type": "websocket.accept"}]
