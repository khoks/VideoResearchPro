"""T-8.8.1.5 (D-085 addendum): no HTTP route takes a JWT from the URL.

A ``?token=`` lands in browser history, server and proxy logs and Referer
headers. Until 2026-10-25 the legacy HTML report route and the six /exports
downloads accepted one because ``<iframe src>`` and ``<a download>`` cannot
send an Authorization header. The frontend now fetches those files with the
header and hands them to the browser as blob: URLs, and the fallback is gone.

The one route that still reads a token from the URL is the /ws/jobs
WebSocket: the browser WebSocket API cannot set headers on the handshake.

The route-table check below walks every route's dependency tree, so a route
that re-adds a query-string credential — through any dependency, at any
depth — fails it. It proves it can see such a parameter by finding the
WebSocket's own.
"""

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.middleware.rate_limit import _user_id_from_jwt

# The names a query-string credential has gone by (`get_user_from_query_or_header`
# read `token`; the others are the usual spellings).
_CREDENTIAL_NAMES = {"token", "access_token", "jwt", "auth", "authorization"}

# Every HTTP route that accepted `?token=` before T-8.8.1.5.
_RETIRED = [
    "/api/v1/jobs/{job_id}/report",
    "/api/v1/exports/qa-dataset/openai.jsonl",
    "/api/v1/exports/qa-dataset/tuple.jsonl",
    "/api/v1/exports/knowledge-dataset/openai.jsonl",
    "/api/v1/exports/knowledge-dataset/tuple.jsonl",
    "/api/v1/exports/notes.jsonl",
    "/api/v1/exports/notes.md",
]


def _query_param_names(dependant) -> set[str]:
    names = {p.alias for p in dependant.query_params}
    for sub in dependant.dependencies:
        names |= _query_param_names(sub)
    return names


def _routes_by_path():
    return {route.path: route for route in app.routes if isinstance(route, (APIRoute, APIWebSocketRoute))}


def test_no_http_route_reads_a_credential_from_the_query_string():
    offenders = {
        route.path: sorted(_query_param_names(route.dependant) & _CREDENTIAL_NAMES)
        for route in app.routes
        if isinstance(route, APIRoute)
    }
    offenders = {path: names for path, names in offenders.items() if names}
    assert offenders == {}, f"HTTP routes reading a credential from the URL: {offenders}"


def test_the_websocket_is_the_one_route_that_still_does():
    # Also the check above's proof that the walk sees a query-string token.
    ws = _routes_by_path()["/ws/jobs"]
    assert isinstance(ws, APIWebSocketRoute)
    assert "token" in _query_param_names(ws.dependant)


def test_every_retired_route_still_exists():
    # Keeps the list honest: a route that moved would otherwise drop out of
    # the per-route checks below without anyone noticing.
    routes = _routes_by_path()
    assert [p for p in _RETIRED if p not in routes] == []


@pytest.mark.parametrize("path", _RETIRED)
def test_a_valid_query_token_no_longer_authenticates(unauthenticated_client, db, auth_token, test_user, path):
    url = path.replace("{job_id}", "any-job")
    response = unauthenticated_client.get(url, params={"token": auth_token})
    assert response.status_code == 401, f"?token= authenticated {path}"


@pytest.mark.parametrize("path", _RETIRED[1:])
def test_the_header_still_authenticates(client, path):
    # The path services/apiFiles.ts takes. (The report route's header case,
    # which needs a stored report, is in test_qa.py.)
    assert client.get(path).status_code == 200


# ---------------------------------------------------------------------------
# The WebSocket keeps its query token
# ---------------------------------------------------------------------------


class _FakeManager:
    """Stands in for the Redis-backed manager: accepts, records, no listener."""

    def __init__(self):
        self.connected = 0
        self.disconnected = 0

    async def connect(self, websocket):
        await websocket.accept()
        self.connected += 1

    async def disconnect(self, websocket):
        self.disconnected += 1

    def subscribe(self, websocket, job_id):
        pass

    def unsubscribe(self, websocket, job_id):
        pass


def test_websocket_still_authenticates_with_a_query_token(unauthenticated_client, auth_token, monkeypatch):
    fake = _FakeManager()
    monkeypatch.setattr("app.routers.ws.manager", fake)
    with unauthenticated_client.websocket_connect(f"/ws/jobs?token={auth_token}") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"
    assert fake.connected == 1


@pytest.mark.parametrize("query", ["", "?token=not-a-real-jwt"])
def test_websocket_refuses_a_missing_or_bad_token(unauthenticated_client, monkeypatch, query):
    fake = _FakeManager()
    monkeypatch.setattr("app.routers.ws.manager", fake)
    with pytest.raises(WebSocketDisconnect) as exc:
        with unauthenticated_client.websocket_connect(f"/ws/jobs{query}"):
            pass
    assert exc.value.code == 1008
    assert fake.connected == 0


# ---------------------------------------------------------------------------
# The rate limiter no longer buckets by a URL token
# ---------------------------------------------------------------------------


def _request(headers: dict[str, str] | None = None, query: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/jobs",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "query_string": query.encode(),
        }
    )


def test_rate_limiter_treats_a_url_token_as_anonymous(auth_token, test_user):
    # The token would 401 at the route, so it must not pick the user's bucket.
    assert _user_id_from_jwt(_request(query=f"token={auth_token}")) is None
    assert _user_id_from_jwt(_request({"Authorization": f"Bearer {auth_token}"})) == test_user.id
