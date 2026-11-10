"""S-3.1.1 / T-3.1.1.1: a fact whose key holds ``/`` is deleted by its route.

``POST /echo/context`` takes any key up to 128 characters, ``/`` included,
and a connector or importer may derive one. The server decodes ``%2F`` before
it routes, so under ``DELETE /echo/context/{kind}/{key}`` such a key arrived
as one segment too many and the route answered 404: the fact could not be
deleted. The route now reads the key as the rest of the path
(``{key:path}``), so every key the API accepts is deleted by it, and a key
with no ``/`` answers as before.

Written through the production write route (``POST /echo/context``) and
deleted through the production delete route, as the Echo page's
``echoApi.deleteContext`` writes the path (``encodeURIComponent``).

Starlette's ``TestClient`` decodes a path twice (httpx's ``URL.path`` is
already decoded and the transport unquotes it again), so a key holding
``%2F`` or ``%25`` as typed text would reach the route as something else. Those
keys go through ``httpx.ASGITransport``, which decodes once, as uvicorn does;
``test_access_log_words.test_the_real_server_writes_no_users_words`` asks the
real server for them too.

Mutation checks (each failed the named tests when this shipped):

- the route as ``{key}`` again (``test_a_key_holding_a_slash_is_deleted``
  for every key with a ``/``, ``test_typed_percent_text_is_decoded_once``
  for the one that decodes to a ``/``, ``test_only_the_named_key_goes``,
  ``test_no_other_route_sits_under_the_context_delete``,
  ``test_a_derived_fact_holding_a_slash_stays_deleted_until_allowed_again``
  in ``test_echo_connectors.py``, the real-server test in
  ``test_access_log_words.py``, and in-suite as
  ``test_the_check_sees_the_segment_route``);
- another route under ``/echo/context/``, which ``{key:path}`` would shadow
  or be shadowed by (``test_no_other_route_sits_under_the_context_delete``).
"""
from __future__ import annotations

import asyncio
from urllib.parse import quote, unquote

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_db
from app.main import app
from app.models.personal_context import PersonalContext
from app.routers import echo as echo_router
from app.services import auth_service
from tests.test_routers.test_url_tokens import _served_routes

CONTEXT = "/api/v1/echo/context"
TEMPLATE = "/api/v1/echo/context/{kind}/{key:path}"


def encode_uri_component(value: str) -> str:
    """A path segment as the Echo page writes one (``echoApi.deleteContext``)."""
    return quote(value, safe="-_.!~*'()")


def _path(kind: str, key: str) -> str:
    return f"{CONTEXT}/{encode_uri_component(kind)}/{encode_uri_component(key)}"


def _studio(db, email: str):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


def _record(client, headers, kind: str, key: str) -> None:
    r = client.post(CONTEXT, json={"kind": kind, "key": key, "value": "v"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["key"] == key


def _keys(db, user_id: str) -> set[tuple[str, str]]:
    """The user's facts, as ``(kind, key)``."""
    db.expire_all()
    return {(row.kind, row.key) for row in db.query(PersonalContext).filter_by(user_id=user_id)}


# Keys a user may write on the form or the API, or a connector derive.
SLASH_KEYS = {
    "one": "TCP/IP",
    "several": "work/2026/q4/plans",
    "leading": "/etc notes",
    "trailing": "reading list/",
    "only": "/",
    "two-only": "//",
    "dot-segments": "quokka/../tariffs",
    "query-marks": "what? #2/now",
    "unicode": "अहिंसा/धर्म",
}
PLAIN_KEYS = {
    "plain": "cooking",
    "spaces": "Favourite quokka",
    "query-marks-no-slash": "tariffs? quokka #2",
    "plus": "C++",
}


@pytest.mark.parametrize("key", sorted({**SLASH_KEYS, **PLAIN_KEYS}))
def test_a_key_holding_a_slash_is_deleted(unauthenticated_client, db, key):
    """Recorded by the API, deleted by its route: 200, the row gone, and a
    second delete 404. A key with no ``/`` answers as it did."""
    value = {**SLASH_KEYS, **PLAIN_KEYS}[key]
    user, headers = _studio(db, f"slash-{key}@x.com")
    _record(unauthenticated_client, headers, "interest", value)

    r = unauthenticated_client.delete(_path("interest", value), headers=headers)

    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": True}
    assert _keys(db, user.id) == set()
    assert unauthenticated_client.delete(_path("interest", value), headers=headers).status_code == 404


def test_only_the_named_key_goes(unauthenticated_client, db):
    """``a/b`` is one key: deleting it leaves ``a``, ``b``, ``a/b/c`` and the
    same key under another kind, and each is deleted by its own path."""
    user, headers = _studio(db, "slash-siblings@x.com")
    for key in ("a", "b", "a/b", "a/b/c", "/a", "a/"):
        _record(unauthenticated_client, headers, "interest", key)
    _record(unauthenticated_client, headers, "hobby", "a/b")

    assert unauthenticated_client.delete(_path("interest", "a/b"), headers=headers).status_code == 200
    assert _keys(db, user.id) == {("interest", k) for k in ("a", "b", "a/b/c", "/a", "a/")} | {("hobby", "a/b")}

    for key in ("a/", "/a", "a/b/c", "a", "b"):
        assert unauthenticated_client.delete(_path("interest", key), headers=headers).status_code == 200, key
    assert unauthenticated_client.delete(_path("hobby", "a/b"), headers=headers).status_code == 200
    assert _keys(db, user.id) == set()


def test_another_users_key_is_not_reached(unauthenticated_client, db):
    """The route still deletes only the caller's row."""
    owner, owner_headers = _studio(db, "slash-owner@x.com")
    _, other_headers = _studio(db, "slash-other@x.com")
    _record(unauthenticated_client, owner_headers, "interest", "TCP/IP")

    assert unauthenticated_client.delete(_path("interest", "TCP/IP"), headers=other_headers).status_code == 404
    assert _keys(db, owner.id) == {("interest", "TCP/IP")}


def test_an_empty_key_deletes_nothing(unauthenticated_client, db):
    """``{key:path}`` matches an empty rest of the path; no key is empty
    (``POST`` needs one character), so it is a 404 and nothing goes."""
    user, headers = _studio(db, "slash-empty@x.com")
    _record(unauthenticated_client, headers, "interest", "cooking")

    r = unauthenticated_client.delete(f"{CONTEXT}/interest/", headers=headers)

    assert r.status_code == 404
    assert _keys(db, user.id) == {("interest", "cooking")}


def _delete_decoded_once(path: str, headers: dict[str, str]) -> httpx.Response:
    """A DELETE through ``httpx.ASGITransport``, which decodes the path once,
    as uvicorn does."""

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.delete(path, headers=headers)

    return asyncio.run(send())


TYPED_PERCENT_KEYS = {
    "typed-%2F": "100%2F",
    "typed-%25": "50%25 off",
    "typed-%2F-and-slash": "a%2Fb/c",
    "percent": "100% quokka",
}


@pytest.mark.parametrize("key", sorted(TYPED_PERCENT_KEYS))
def test_typed_percent_text_is_decoded_once(unauthenticated_client, db, key):
    """``%2F`` or ``%25`` typed as text is the key's own: the server decodes
    the path once, so the route reads the key as it was written, and a row
    whose key is what a second decode would make is left alone."""
    value = TYPED_PERCENT_KEYS[key]
    user, headers = _studio(db, f"pct-{key}@x.com")
    _record(unauthenticated_client, headers, "interest", value)
    decoy = unquote(value)  # what a second decode of the path would read
    if decoy != value:
        _record(unauthenticated_client, headers, "interest", decoy)

    r = _delete_decoded_once(_path("interest", value), headers)

    assert r.status_code == 200, r.text
    assert ("interest", value) not in _keys(db, user.id)
    assert _keys(db, user.id) == ({("interest", decoy)} if decoy != value else set())


def test_no_other_route_sits_under_the_context_delete():
    """``{key:path}`` would swallow any other route under ``/echo/context/``,
    so it is the only one, and it is a DELETE alone. The list and the write
    are on ``/echo/context`` itself."""
    under = [
        (path, sorted(getattr(route, "methods", None) or ()))
        for path, route, _dependant in _served_routes()
        if path.lower().startswith(f"{CONTEXT}/")
    ]
    assert under == [(TEMPLATE, ["DELETE"])]
    on_context = sorted(
        method for path, route, _ in _served_routes() if path == CONTEXT for method in route.methods
    )
    assert on_context == ["GET", "POST"]


def test_the_check_sees_the_segment_route(db):
    """The mutation: the same handler on ``{key}``, and a key holding ``/``
    answers 404 again while a plain key is still deleted. So the tests above
    can fail."""
    user, headers = _studio(db, "slash-mutation@x.com")
    for key in ("TCP/IP", "cooking"):
        echo_router.echo_service.record_context(
            db, user_id=user.id, kind="interest", key=key, value="v", source="manual"
        )
    router = APIRouter()
    router.add_api_route(
        f"{CONTEXT}/{{kind}}/{{key}}", echo_router.delete_context_endpoint, methods=["DELETE"],
    )
    fixture = FastAPI()
    fixture.include_router(router)
    fixture.dependency_overrides[get_db] = lambda: db

    with TestClient(fixture) as client:
        assert client.delete(_path("interest", "TCP/IP"), headers=headers).status_code == 404
        assert client.delete(_path("interest", "cooking"), headers=headers).status_code == 200
    assert _keys(db, user.id) == {("interest", "TCP/IP")}
