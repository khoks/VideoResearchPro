"""T-8.8.1.5 (D-085 addendum) and T-5.4.23: no route takes a JWT from the URL.

A ``?token=`` lands in browser history, server and proxy logs and Referer
headers. Until 2026-10-25 the legacy HTML report route and the six /exports
downloads accepted one because ``<iframe src>`` and ``<a download>`` cannot
send an Authorization header. The frontend now fetches those files with the
header and hands them to the browser as blob: URLs, and the fallback is gone.

The /ws/jobs WebSocket was the last. A browser cannot set a header on its
handshake, but it can offer subprotocols, so since T-5.4.23 the client offers
``bearer`` and then the token, and the server answers ``bearer`` alone.

The route-table check below walks every route's dependency tree, so a route
that re-adds a query-string credential — through any dependency, at any
depth — fails it. It proves it can see such a parameter on a route made for
the purpose. A handler reading ``websocket.query_params`` itself is not a
parameter, so the socket's own refusal is checked by opening it.

Mutation checks (each failed the named test when this shipped): reading
``websocket.query_params`` as a fallback
(``test_a_valid_token_in_the_url_opens_no_socket``); accepting with no
subprotocol, which a browser fails
(``test_the_socket_authenticates_with_the_bearer_subprotocol``); answering
with the offered list's token (the same test); dropping the split on a comma
(``test_a_header_handed_over_unsplit_still_reads``).
"""

import re

import pytest
from fastapi import APIRouter, Depends, Query, WebSocket
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.middleware.rate_limit import _user_id_from_jwt
from app.routers.ws import BEARER_SUBPROTOCOL, _offered_token
from app.utils.log_redaction import CREDENTIAL_QUERY_NAMES

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


def test_no_route_reads_a_credential_from_the_query_string():
    served = _served_routes()
    assert set(_RETIRED) | {"/ws/jobs"} <= {path for path, _route, _dependant in served}  # never passes having seen nothing
    offenders = {
        f"{sorted(getattr(route, 'methods', None) or ['WS'])} {path}": names
        for path, route, dependant in served
        if (names := sorted(_query_param_names(dependant) & CREDENTIAL_QUERY_NAMES))
    }
    assert offenders == {}, f"routes reading a credential from the URL: {offenders}"


def test_the_walk_sees_a_query_string_credential_at_any_depth():
    # The check above's proof, on a socket and through a dependency.
    def nested(token: str | None = Query(default=None)):
        return token

    def outer(_inner=Depends(nested)):
        return None

    probe = APIRouter()

    @probe.websocket("/probe")
    async def probe_socket(websocket: WebSocket, _outer=Depends(outer)):
        pass

    [route] = probe.routes
    assert isinstance(route, APIWebSocketRoute)
    assert _query_param_names(route.dependant) & CREDENTIAL_QUERY_NAMES == {"token"}


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
# The WebSocket takes its token as a subprotocol
# ---------------------------------------------------------------------------


class _FakeManager:
    """Stands in for the Redis-backed manager: accepts, records, no listener."""

    def __init__(self):
        self.connected = 0
        self.disconnected = 0

    async def connect(self, websocket, *, subprotocol=None, tenant_id=None, jti=None, expires_at=None):
        await websocket.accept(subprotocol=subprotocol)
        self.connected += 1

    async def disconnect(self, websocket):
        self.disconnected += 1

    def subscribe(self, websocket, job_id):
        pass

    def unsubscribe(self, websocket, job_id):
        pass


@pytest.fixture
def fake_manager(monkeypatch):
    from tests.conftest import TestingSessionLocal

    fake = _FakeManager()
    monkeypatch.setattr("app.routers.ws.manager", fake)
    # T-5.4.15: the handshake checks the token's session and user in a
    # session of its own, from app.database.SessionLocal.
    monkeypatch.setattr("app.database.SessionLocal", TestingSessionLocal)
    return fake


def test_the_socket_authenticates_with_the_bearer_subprotocol(unauthenticated_client, auth_token, fake_manager):
    with unauthenticated_client.websocket_connect("/ws/jobs", subprotocols=["bearer", auth_token]) as ws:
        # A browser fails a handshake whose answer names nothing it offered,
        # and the token never comes back.
        assert ws.accepted_subprotocol == "bearer"
        assert auth_token not in str(ws.extra_headers)
        ws.send_text("ping")
        assert ws.receive_text() == "pong"
    assert fake_manager.connected == 1


def test_a_valid_token_in_the_url_opens_no_socket(unauthenticated_client, auth_token, fake_manager):
    with pytest.raises(WebSocketDisconnect) as exc:
        with unauthenticated_client.websocket_connect(f"/ws/jobs?token={auth_token}"):
            pass
    assert exc.value.code == 1008
    assert fake_manager.connected == 0


def test_a_token_in_the_url_does_not_stand_in_for_the_subprotocol(unauthenticated_client, auth_token, fake_manager):
    with pytest.raises(WebSocketDisconnect) as exc:
        with unauthenticated_client.websocket_connect(f"/ws/jobs?token={auth_token}", subprotocols=["bearer"]):
            pass
    assert exc.value.code == 1008
    assert fake_manager.connected == 0


@pytest.mark.parametrize("offered", [[], ["bearer", "not-a-real-jwt"]])
def test_websocket_refuses_a_missing_or_bad_token(unauthenticated_client, fake_manager, offered):
    with pytest.raises(WebSocketDisconnect) as exc:
        with unauthenticated_client.websocket_connect("/ws/jobs", subprotocols=offered):
            pass
    assert exc.value.code == 1008
    assert fake_manager.connected == 0


@pytest.mark.parametrize(
    "offered",
    [
        [],
        ["bearer"],
        ["bearer", ""],
        ["a.b.c"],
        ["a.b.c", "bearer"],
        ["bearer", "a.b.c", "more"],
        ["Bearer", "a.b.c"],
        ["graphql-ws", "a.b.c"],
    ],
)
def test_only_bearer_then_a_token_is_an_offer(offered):
    assert _offered_token(offered) is None


def test_a_header_handed_over_unsplit_still_reads():
    """uvicorn's sans-IO protocol passes the header's value as one entry;
    its other two split it."""
    assert _offered_token(["bearer", "a.b.c"]) == "a.b.c"
    assert _offered_token(["bearer, a.b.c"]) == "a.b.c"
    assert _offered_token(["bearer,a.b.c"]) == "a.b.c"


def test_a_real_token_is_a_legal_subprotocol_name(auth_token):
    """RFC 6455 section 4.1 holds a subprotocol to RFC 2616's token: US-ASCII
    with no separators. A browser throws on anything else. A JWT is three
    unpadded base64url parts, so ``=`` never appears."""
    assert re.fullmatch(r"[!#$%&'*+\-.0-9A-Z^_`a-z|~]+", auth_token)
    assert auth_token != BEARER_SUBPROTOCOL, "the two offered must differ"


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
