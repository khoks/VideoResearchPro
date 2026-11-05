"""T-1.15.3.9: one person's default depth, at the routes.

`PATCH /auth/me/preferences` stores it and `GET /auth/me` returns it. Nothing else
reads it: the pages preset their controls from it, and a request carries a depth
only when the control shows one (frontend `usePreferredDepth`). So the tests that
matter here are the negative ones. A request with no depth behaves the same with
a preference set, and the value reaches no one else.

Mutation checks, run by hand on 2026-11-04:
- filtering the update on nothing (setting every row) fails
  `test_a_preference_is_one_persons`;
- storing `auto` as the string fails `test_auto_is_stored_as_no_preference`;
- the job and library routes falling back to the column fail
  `test_a_job_request_with_no_depth_stays_on_auto` and
  `test_a_library_question_with_no_depth_gets_the_unset_budget`;
- adding the field to `UserResponse` fails `test_only_me_returns_it`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agents import qa_agent
from app.models.document import Document
from app.models.user import User
from app.services import auth_service, output_length, visibility_service
from app.services.llm_routing import UseCaseConfig
from app.tasks import job_tasks
from app.utils.chunking import chunk_transcript

_PATH = "/api/v1/auth/me/preferences"


def _me(client) -> dict:
    return client.get("/api/v1/auth/me").json()


def test_no_one_has_a_preference_until_they_set_one(client):
    assert _me(client)["preferred_output_length"] is None


@pytest.mark.parametrize("depth", ["brief", "standard", "deep"])
def test_a_depth_is_stored_and_returned(client, db, test_user, depth):
    resp = client.patch(_PATH, json={"output_length": depth})
    assert resp.status_code == 200
    assert resp.json() == {"output_length": depth}
    assert _me(client)["preferred_output_length"] == depth
    db.expire_all()
    assert db.get(User, test_user.id).preferred_output_length == depth


@pytest.mark.parametrize("clear", ["auto", None])
def test_auto_is_stored_as_no_preference(client, db, test_user, clear):
    """So Auto and never having chosen cannot differ."""
    client.patch(_PATH, json={"output_length": "deep"})
    resp = client.patch(_PATH, json={"output_length": clear})
    assert resp.json() == {"output_length": None}
    db.expire_all()
    assert db.get(User, test_user.id).preferred_output_length is None


def test_an_unknown_depth_is_refused(client, db, test_user):
    resp = client.patch(_PATH, json={"output_length": "enormous"})
    assert resp.status_code == 422
    db.expire_all()
    assert db.get(User, test_user.id).preferred_output_length is None


def test_it_needs_a_session(unauthenticated_client):
    assert unauthenticated_client.patch(_PATH, json={"output_length": "deep"}).status_code == 401


def test_a_preference_is_one_persons(client, db, test_user):
    other = auth_service.create_user(db, "other-depth@example.com", "correct-horse-battery")
    client.patch(_PATH, json={"output_length": "deep"})
    db.expire_all()
    assert db.get(User, other.id).preferred_output_length is None


def test_only_me_returns_it(unauthenticated_client):
    """`/auth/register` answers with `UserResponse`, which stays without it."""
    resp = unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "new-depth@example.com", "password": "correct-horse-battery"},
    )
    assert resp.status_code == 201
    assert "preferred_output_length" not in resp.json()


def test_a_job_request_with_no_depth_stays_on_auto(client):
    """The server never applies the preference, so a client that sends no depth
    (an old tab, a script, the extension) gets exactly what it got before."""
    client.patch(_PATH, json={"output_length": "deep"})
    resp = client.post(
        "/api/v1/jobs",
        json={"job_type": "topic", "topic": "tidal storage", "num_videos": 3},
    )
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["output_length"] is None


def _library_ask(client, doc) -> dict:
    meta = job_tasks._build_video_metadata(doc, "en")
    chunks = chunk_transcript(
        [{"text": "Tidal lagoons store energy behind a wall.", "start": 0.0, "duration": 5.0}],
        video_metadata=meta,
    )
    hits = [
        {"text": c["text"], "metadata": {k: v for k, v in c["metadata"].items() if v is not None}, "distance": 0.1}
        for c in chunks
    ]
    seen: dict = {}

    def build(use_case: str, **kwargs):
        if use_case == "library_qa_formulate_answer":
            seen.update(kwargs)
        llm = MagicMock()

        def invoke(messages):
            if use_case == "library_qa_formulate_answer":
                seen["prompt"] = messages[-1].content
            return MagicMock(content="Lagoons store energy.", response_metadata={})

        llm.invoke.side_effect = invoke
        return llm

    with (
        patch.object(qa_agent.chroma_service, "query_collection", return_value=hits),
        patch.object(qa_agent, "get_llm_for", side_effect=build),
        patch.object(qa_agent, "resolve_config", return_value=UseCaseConfig("anthropic", "claude-sonnet-5", "off")),
        patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        resp = client.post("/api/v1/library/qa", json={"question": "How do lagoons store energy?"})
    assert resp.status_code == 200, resp.text
    return seen


def test_a_library_question_with_no_depth_gets_the_unset_budget(client, db, test_user):
    doc = Document(
        video_id="prefVid0001",
        title="Tidal energy storage",
        url="https://www.youtube.com/watch?v=prefVid0001",
        duration_seconds=60,
        transcript_status="fetched",
        transcript_word_count=500,
        created_at=datetime.now(timezone.utc),
    )
    db.add(doc)
    db.commit()
    visibility_service.grant(db, [doc.document_id], test_user.id)

    before = _library_ask(client, doc)
    client.patch(_PATH, json={"output_length": "brief"})
    after = _library_ask(client, doc)

    assert after["max_tokens"] == before["max_tokens"]
    assert output_length.guidance({}, "brief") not in after["prompt"]
