"""`PUT /channels/{id}/weight` and the per-tenant trust re-rank at the
production callers (S-7.1.1 / D-068).

The router tests assert at the caller, not at the function that implements
the re-rank: R4's Q&A half once shipped as agent plumbing no router fed
(CLAUDE.md, "verify a feature at its caller").
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models.channel import Channel
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services import auth_service, subscription_service, visibility_service

CH_TRUSTED = "UCtrusted0000000000000"
CH_PLAIN = "UCplain000000000000000"


@pytest.fixture
def other_user(db):
    user = auth_service.create_user(db, email="b@example.com", password="testpass123")
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def shared_corpus(db, test_user, other_user):
    """Two channels, one document each, visible to BOTH tenants."""
    db.add_all([
        Channel(channel_id=CH_TRUSTED, name="Trusted Channel", creator_external_id=CH_TRUSTED),
        Channel(channel_id=CH_PLAIN, name="Plain Channel", creator_external_id=CH_PLAIN),
    ])
    db.commit()
    docs = [
        Document(document_id="doc-trusted", video_id="vidtrusted1", channel_id=CH_TRUSTED,
                 title="Trusted video", url="https://youtu.be/vidtrusted1", transcript_status="fetched"),
        Document(document_id="doc-plain", video_id="vidplain001", channel_id=CH_PLAIN,
                 title="Plain video", url="https://youtu.be/vidplain001", transcript_status="fetched"),
    ]
    db.add_all(docs)
    db.commit()
    ids = [d.document_id for d in docs]
    visibility_service.grant(db, ids, test_user.id)
    visibility_service.grant(db, ids, other_user[0].id)
    return ids


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


def test_put_weight_sets_only_the_callers_weight(client, other_user, shared_corpus):
    _, b_headers = other_user
    resp = client.put(f"/api/v1/channels/{CH_TRUSTED}/weight", json={"weight": 1.8})
    assert resp.status_code == 200, resp.text
    assert resp.json()["source_weight"] == pytest.approx(1.8)

    assert client.get(f"/api/v1/channels/{CH_TRUSTED}").json()["source_weight"] == pytest.approx(1.8)
    theirs = client.get(f"/api/v1/channels/{CH_TRUSTED}", headers=b_headers).json()
    assert theirs["source_weight"] == pytest.approx(1.0)


@pytest.mark.parametrize("bad", [-0.1, 2.01, "high", None])
def test_put_weight_rejects_out_of_range_values(client, shared_corpus, bad):
    resp = client.put(f"/api/v1/channels/{CH_TRUSTED}/weight", json={"weight": bad})
    assert resp.status_code == 422


def test_put_weight_accepts_the_bounds(client, shared_corpus):
    assert client.put(f"/api/v1/channels/{CH_TRUSTED}/weight", json={"weight": 0.0}).status_code == 200
    assert client.put(f"/api/v1/channels/{CH_TRUSTED}/weight", json={"weight": 2.0}).status_code == 200


def test_put_weight_on_an_unknown_channel_404s(client):
    assert client.put("/api/v1/channels/UCnope/weight", json={"weight": 1.5}).status_code == 404


def test_put_weight_requires_auth(unauthenticated_client):
    assert unauthenticated_client.put(f"/api/v1/channels/{CH_TRUSTED}/weight",
                                      json={"weight": 1.5}).status_code == 401


def test_channel_weights_lists_only_non_neutral_rows(db, test_user, shared_corpus):
    subscription_service.set_weight(db, CH_TRUSTED, test_user.id, 2.0)
    subscription_service.set_weight(db, CH_PLAIN, test_user.id, 1.0)
    assert subscription_service.channel_weights(db, test_user.id) == {CH_TRUSTED: 2.0}
    assert subscription_service.channel_weights(db, "nobody") == {}
    with pytest.raises(ValueError):
        subscription_service.set_weight(db, CH_TRUSTED, test_user.id, 3.0)


# ---------------------------------------------------------------------------
# Two tenants, real routers, real agent, patched store + LLMs
# ---------------------------------------------------------------------------


def _pool(query_text, n_results=None, document_ids=None, distance_threshold=None):
    """Plain is nearer than Trusted on raw distance; both pass the threshold."""
    hits = [
        {"text": "plain passage", "distance": 0.30, "metadata": {
            "document_id": "doc-plain", "video_id": "vidplain001", "chunk_index": 0,
            "channel_id": CH_PLAIN, "video_title": "Plain video", "channel_name": "Plain Channel"}},
        {"text": "trusted passage", "distance": 0.40, "metadata": {
            "document_id": "doc-trusted", "video_id": "vidtrusted1", "chunk_index": 0,
            "channel_id": CH_TRUSTED, "video_title": "Trusted video", "channel_name": "Trusted Channel"}},
    ]
    return [h for h in hits if h["metadata"]["document_id"] in (document_ids or [])]


def _llms(recorded: list):
    def factory(use_case, **_kw):
        llm = MagicMock()

        def invoke(messages):
            recorded.append((use_case, "\n".join(getattr(m, "content", str(m)) for m in messages)))
            r = MagicMock()
            r.content = "" if "sub_query" in use_case else ("[]" if "references" in use_case else "ok")
            r.usage_metadata = None
            r.response_metadata = {}
            return r

        llm.invoke.side_effect = invoke
        return llm
    return factory


def _ask_library(client, headers=None) -> str:
    recorded: list = []
    with patch("app.agents.qa_agent.chroma_service.query_collection", side_effect=_pool), \
         patch("app.agents.qa_agent.get_llm_for", side_effect=_llms(recorded)), \
         patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True):
        resp = client.post("/api/v1/library/qa", json={"question": "what do they say?"}, headers=headers)
    assert resp.status_code == 200, resp.text
    return next(text for uc, text in recorded if "refine_context" in uc)


def _first(prompt: str) -> str:
    return "Trusted video" if prompt.index("Trusted video") < prompt.index("Plain video") else "Plain video"


def test_one_tenants_weights_never_change_another_tenants_ranking(client, other_user, shared_corpus):
    _, b_headers = other_user
    assert _first(_ask_library(client)) == "Plain video"
    assert _first(_ask_library(client, b_headers)) == "Plain video"

    # A trusts the farther channel: 0.40 / 2.0 = 0.20 now beats 0.30.
    assert client.put(f"/api/v1/channels/{CH_TRUSTED}/weight", json={"weight": 2.0}).status_code == 200
    assert _first(_ask_library(client)) == "Trusted video"
    assert _first(_ask_library(client, b_headers)) == "Plain video", "B's ranking must not move"

    # And the other way round: B distrusting a channel leaves A alone.
    assert client.put(f"/api/v1/channels/{CH_PLAIN}/weight", json={"weight": 0.0},
                      headers=b_headers).status_code == 200
    assert _first(_ask_library(client)) == "Trusted video"
    assert _first(_ask_library(client, b_headers)) == "Trusted video"


def test_job_qa_router_passes_the_askers_weights(client, db, test_user, other_user, shared_corpus):
    job = Job(job_type="topic", topic="t", status="completed", tenant_id=test_user.id)
    db.add(job)
    db.commit()
    db.add_all([JobVideo(job_id=job.id, document_id=d, approved=True) for d in shared_corpus])
    db.commit()
    subscription_service.set_weight(db, CH_TRUSTED, test_user.id, 1.7)
    subscription_service.set_weight(db, CH_PLAIN, other_user[0].id, 0.2)

    with patch("app.agents.qa_agent.run_qa_agent", return_value=("answer", [])) as agent, \
         patch("app.routers.qa.chroma_service.upsert_qa_exchange", return_value=True):
        resp = client.post(f"/api/v1/jobs/{job.id}/qa", json={"question": "what is said?"})
    assert resp.status_code == 200, resp.text
    assert agent.call_args.kwargs["channel_weights"] == {CH_TRUSTED: 1.7}
