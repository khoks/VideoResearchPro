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


def _served_routes() -> list[tuple[str, object, object]]:
    """Every route the app serves, as (full path, route, effective dependant).

    A list, not a dict by path: a GET and a POST on one path are two routes
    with two dependency trees, and both are checked.

    FastAPI up to at least 0.135 copies an included router's routes into
    ``app.routes`` with the prefix and the router-level dependencies applied.
    Later releases (0.162, what CI's fresh install gets) keep each inclusion
    as one ``_IncludedRouter`` entry and resolve the prefixed path and the
    dependant per inclusion, through ``fastapi.routing.iter_route_contexts``.
    Walking ``app.routes`` alone there finds no APIRoute at all, and a check
    over it passes having looked at nothing.
    """
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # the flat route table
        return [
            (route.path, route, route.dependant)
            for route in app.routes
            if isinstance(route, (APIRoute, APIWebSocketRoute))
        ]
    served = []
    for ctx in iter_route_contexts(app.routes):
        route = ctx.original_route
        if isinstance(route, (APIRoute, APIWebSocketRoute)):
            served.append((ctx.path, route, ctx.dependant))
    return served


def _served_paths() -> set[str]:
    return {path for path, _route, _dependant in _served_routes()}


def test_the_route_walk_sees_the_whole_app():
    # The checks below are only as good as this walk: it must reach the
    # routes behind include_router (all of them) on whichever FastAPI is
    # installed.
    served = _served_routes()
    paths = {path for path, _route, _dependant in served}
    assert set(_RETIRED) <= paths
    assert "/ws/jobs" in paths
    assert len(served) > 100


def test_no_http_route_reads_a_credential_from_the_query_string():
    http = [(path, route, dependant) for path, route, dependant in _served_routes() if isinstance(route, APIRoute)]
    assert set(_RETIRED) <= {path for path, _route, _dependant in http}  # never passes having seen nothing
    offenders = {
        f"{sorted(route.methods)} {path}": names
        for path, route, dependant in http
        if (names := sorted(_query_param_names(dependant) & _CREDENTIAL_NAMES))
    }
    assert offenders == {}, f"HTTP routes reading a credential from the URL: {offenders}"


def test_the_websocket_is_the_one_route_that_still_does():
    # Also the check above's proof that the walk sees a query-string token.
    [(ws, dependant)] = [(route, dep) for path, route, dep in _served_routes() if path == "/ws/jobs"]
    assert isinstance(ws, APIWebSocketRoute)
    assert "token" in _query_param_names(dependant)


def test_every_retired_route_still_exists():
    # Keeps the list honest: a route that moved would otherwise drop out of
    # the per-route checks below without anyone noticing.
    routes = _served_paths()
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
