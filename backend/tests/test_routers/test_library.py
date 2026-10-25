"""Tests for the library-wide Q&A router (Unit 6).

Endpoints:
  GET  /api/v1/library/qa           list persisted exchanges
  POST /api/v1/library/qa           ask a question (library-scoped)
  POST /api/v1/library/qa/clarify   generate clarifying questions
  GET  /api/v1/library/videos       browse the global video library
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

pytest.importorskip("app.routers.library", reason="pending Unit 6 merge — library router")

from app.models.channel import Channel
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.document import Document
from app.models.library_qa_exchange import LibraryQAExchange


def test_get_library_qa_initially_empty(client):
    response = client.get("/api/v1/library/qa")
    assert response.status_code == 200
    assert response.json() == []


def test_post_library_qa_persists_and_returns_result(client):
    """POST runs the library Q&A agent (mocked), persists the exchange,
    returns the answer + references."""
    fake_answer = "DNS resolves domain names to IP addresses."
    fake_refs = [{
        "video_id": "vDNS",
        "video_url": "https://www.youtube.com/watch?v=vDNS",
        "video_title": "How DNS Works",
        "channel_name": "NetTeach",
        "timestamp_seconds": 30.0,
        "timestamp_display": "0:30",
        "youtube_link": "https://www.youtube.com/watch?v=vDNS&t=30",
    }]

    with patch(
        "app.agents.qa_agent.run_library_qa_agent",
        return_value={"answer": fake_answer, "references": fake_refs},
    ):
        response = client.post("/api/v1/library/qa", json={"question": "What is DNS?"})

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == fake_answer
    assert "id" in data
    assert len(data["references"]) == 1
    assert data["references"][0]["video_title"] == "How DNS Works"


def test_get_library_qa_returns_persisted_exchange(client):
    fake_answer = "Answer."
    fake_refs = []
    with patch(
        "app.agents.qa_agent.run_library_qa_agent",
        return_value={"answer": fake_answer, "references": fake_refs},
    ):
        post_resp = client.post("/api/v1/library/qa", json={"question": "What is DNS?"})
    assert post_resp.status_code == 200

    get_resp = client.get("/api/v1/library/qa")
    assert get_resp.status_code == 200
    items = get_resp.json()
    assert len(items) == 1
    item = items[0]
    assert item["question"] == "What is DNS?"
    assert item["answer"] == "Answer."
    assert item["created_at"] is not None


def test_post_library_qa_clarify_returns_interpretation_and_clarifications(client):
    """clarify endpoint mocks get_llm_for to return the JSON envelope the real route parses."""
    json_payload = (
        '{"interpretation": "User wants a DNS primer.", '
        '"clarifications": ["What level?", "Which record types?", "For DevOps?"]}'
    )

    class _Resp:
        content = json_payload

    class _LLM:
        def invoke(self, _prompt):
            return _Resp()

    with patch("app.routers.library.get_llm_for", return_value=_LLM()):
        response = client.post(
            "/api/v1/library/qa/clarify",
            json={"question": "What is DNS?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["interpretation"] == "User wants a DNS primer."
    assert len(data["clarifications"]) == 3
    assert "What level?" in data["clarifications"]


# ---------------------------------------------------------------------------
# S-8.13.1: "Confirm & search" sends the clarify answers as `context`
# ---------------------------------------------------------------------------

# What LibraryQAPage sends after the clarify step: the interpretation the
# reader confirmed, then each clarifying question they answered with the answer.
CLARIFY_CONTEXT = "My interpretation: User wants a DNS primer.\n\nWhich record types?\nMX and CNAME"


def _ask_library(client, body):
    with (
        patch(
            "app.agents.qa_agent.run_library_qa_agent",
            return_value={"answer": "Answer.", "references": []},
        ) as agent,
        patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True),
    ):
        response = client.post("/api/v1/library/qa", json=body)
    return response, agent


def test_library_qa_clarify_answers_reach_the_agent(client, db):
    """The confirmed interpretation and the reader's answers reach the agent
    inside its question, exactly as job Q&A folds them; the stored exchange
    keeps the question as typed. Fails if the fold-in in
    ``answer_library_question`` is removed or the schema drops ``context``
    again (Pydantic ignored the unknown field, so "Confirm & search" answered
    exactly like "Skip clarifications")."""
    response, agent = _ask_library(client, {"question": "What is DNS?", "context": CLARIFY_CONTEXT})

    assert response.status_code == 200, response.text
    assert agent.call_args.kwargs["question"] == (
        "What is DNS?\n\nAdditional context from user:\n" + CLARIFY_CONTEXT
    )
    assert response.json()["question"] == "What is DNS?"
    row = db.get(LibraryQAExchange, response.json()["id"])
    assert row.question == "What is DNS?", "history shows the typed question, not the folded one"


def test_library_qa_skip_asks_the_bare_question(client):
    for body in ({"question": "What is DNS?"}, {"question": "What is DNS?", "context": "  \n "}):
        response, agent = _ask_library(client, body)
        assert response.status_code == 200, response.text
        assert agent.call_args.kwargs["question"] == "What is DNS?"


def test_library_qa_clarify_context_is_bounded(client):
    """Bounded like job Q&A's ``context`` (4,000 characters)."""
    response, agent = _ask_library(client, {"question": "What is DNS?", "context": "x" * 4001})
    assert response.status_code == 422
    agent.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/v1/library/videos
# ---------------------------------------------------------------------------


def _seed_library(db, tenant_id: str) -> dict:
    """Two channels, four videos with varied transcript states/durations,
    and two jobs sharing one video so the aggregation has something to count.

    S-5.7.1: documents are a shared cache with no tenant of their own, so the
    caller only sees what `document_visibility` grants them. All four videos are
    granted to ``tenant_id``; only two are attached to jobs, which is what keeps
    the `job_count == 0` assertion meaningful — that is now precisely the
    "ingested via paste/PDF, never used by a job" case."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    ch_a = Channel(channel_id="UCaaaaaaaaaaaaaaaaaaaaa1", name="Alpha Channel")
    ch_b = Channel(channel_id="UCbbbbbbbbbbbbbbbbbbbbb2", name="Beta Channel")
    db.add_all([ch_a, ch_b])
    db.commit()

    v1 = Document(
        video_id="vid001alpha",
        channel_id=ch_a.channel_id,
        title="Alpha Intro to DNS",
        url="https://www.youtube.com/watch?v=vid001alpha",
        duration_seconds=300,
        thumbnail_url=None,
        transcript_status="fetched",
        transcript_language="en",
        transcript_word_count=900,
        created_at=base + timedelta(days=1),
    )
    v2 = Document(
        video_id="vid002alpha",
        channel_id=ch_a.channel_id,
        title="Alpha Deep Dive on TCP",
        url="https://www.youtube.com/watch?v=vid002alpha",
        duration_seconds=1800,
        thumbnail_url=None,
        transcript_status="pending",
        transcript_language=None,
        transcript_word_count=None,
        created_at=base + timedelta(days=2),
    )
    v3 = Document(
        video_id="vid003beta",
        channel_id=ch_b.channel_id,
        title="Beta Hindi Tutorial",
        url="https://www.youtube.com/watch?v=vid003beta",
        duration_seconds=600,
        thumbnail_url=None,
        transcript_status="fetched",
        transcript_language="hi",
        transcript_word_count=1200,
        created_at=base + timedelta(days=3),
    )
    v4 = Document(
        video_id="vid004beta",
        channel_id=ch_b.channel_id,
        title="Beta Unavailable Video",
        url="https://www.youtube.com/watch?v=vid004beta",
        duration_seconds=120,
        thumbnail_url=None,
        transcript_status="unavailable",
        transcript_language=None,
        transcript_word_count=None,
        created_at=base + timedelta(days=4),
    )
    db.add_all([v1, v2, v3, v4])
    db.commit()

    job_a = Job(job_type="topic", topic="DNS basics", status="completed", tenant_id=tenant_id)
    job_b = Job(job_type="topic", topic="Networking 101", status="completed", tenant_id=tenant_id)
    db.add_all([job_a, job_b])
    db.commit()

    db.add_all([
        JobVideo(job_id=job_a.id, video_id=v1.video_id, approved=True),
        JobVideo(job_id=job_b.id, video_id=v1.video_id, approved=True),
        JobVideo(job_id=job_b.id, video_id=v2.video_id, approved=True),
    ])
    db.commit()

    from app.services import visibility_service

    visibility_service.grant(
        db, [v.document_id for v in (v1, v2, v3, v4)], tenant_id,
        visibility_service.SOURCE_JOB,
    )

    return {
        "channels": {"alpha": ch_a, "beta": ch_b},
        "videos": {"v1": v1, "v2": v2, "v3": v3, "v4": v4},
        "jobs": {"a": job_a, "b": job_b},
    }


def test_get_library_videos_empty(client):
    response = client.get("/api/v1/library/videos")
    assert response.status_code == 200
    assert response.json() == []


def test_get_library_videos_returns_all_with_aggregation(client, db, test_user):
    seed = _seed_library(db, test_user.id)
    response = client.get("/api/v1/library/videos")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 4

    by_id = {it["video_id"]: it for it in items}
    v1 = by_id["vid001alpha"]
    # D-070: `id` is the primary key, not the legacy YouTube id.
    assert v1["id"] != v1["video_id"] and len(v1["id"]) == 36
    assert v1["source_type"] == "video"
    assert v1["title"] == "Alpha Intro to DNS"
    assert v1["channel_name"] == "Alpha Channel"
    assert v1["channel_id"] == seed["channels"]["alpha"].channel_id
    assert v1["job_count"] == 2
    assert set(v1["job_titles"]) == {"DNS basics", "Networking 101"}
    assert v1["transcript_status"] == "fetched"
    assert v1["transcript_language"] == "en"

    v3 = by_id["vid003beta"]
    assert v3["job_count"] == 0
    assert v3["job_titles"] == []
    assert v3["transcript_language"] == "hi"


def test_get_library_videos_search_matches_title_or_channel(client, db, test_user):
    _seed_library(db, test_user.id)

    title_match = client.get("/api/v1/library/videos", params={"search": "DNS"})
    assert title_match.status_code == 200
    assert {it["video_id"] for it in title_match.json()} == {"vid001alpha"}

    channel_match = client.get("/api/v1/library/videos", params={"search": "Beta Channel"})
    assert channel_match.status_code == 200
    assert {it["video_id"] for it in channel_match.json()} == {"vid003beta", "vid004beta"}


def test_get_library_videos_filters_language_channel_status(client, db, test_user):
    seed = _seed_library(db, test_user.id)

    en_only = client.get("/api/v1/library/videos", params={"language": "en"})
    assert {it["video_id"] for it in en_only.json()} == {"vid001alpha"}

    alpha_only = client.get(
        "/api/v1/library/videos",
        params={"channel_id": seed["channels"]["alpha"].channel_id},
    )
    assert {it["video_id"] for it in alpha_only.json()} == {"vid001alpha", "vid002alpha"}

    pending = client.get("/api/v1/library/videos", params={"transcript_status": "pending"})
    assert {it["video_id"] for it in pending.json()} == {"vid002alpha"}


def test_get_library_videos_sort_variants(client, db, test_user):
    _seed_library(db, test_user.id)

    newest = client.get("/api/v1/library/videos", params={"sort": "newest"}).json()
    assert [it["video_id"] for it in newest][0] == "vid004beta"

    oldest = client.get("/api/v1/library/videos", params={"sort": "oldest"}).json()
    assert [it["video_id"] for it in oldest][0] == "vid001alpha"

    longest = client.get("/api/v1/library/videos", params={"sort": "longest"}).json()
    assert [it["video_id"] for it in longest][0] == "vid002alpha"

    shortest = client.get("/api/v1/library/videos", params={"sort": "shortest"}).json()
    assert [it["video_id"] for it in shortest][0] == "vid004beta"


def test_get_library_videos_pagination(client, db, test_user):
    _seed_library(db, test_user.id)
    first = client.get("/api/v1/library/videos", params={"limit": 2, "offset": 0}).json()
    second = client.get("/api/v1/library/videos", params={"limit": 2, "offset": 2}).json()
    assert len(first) == 2
    assert len(second) == 2
    assert {it["video_id"] for it in first}.isdisjoint({it["video_id"] for it in second})


def test_get_library_videos_requires_auth(unauthenticated_client):
    response = unauthenticated_client.get("/api/v1/library/videos")
    assert response.status_code == 401


def test_library_list_filters_to_one_document(client, db, test_user):
    """S-8.2.2: a palette result opens `/library?document=<id>`, which asks
    the listing for that one row. Before this filter existed the page showed
    the whole library and the user had to find the row again."""
    seeded = _seed_library(db, test_user.id)
    v3 = seeded["videos"]["v3"]
    response = client.get("/api/v1/library/videos", params={"document_id": v3.document_id})
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [r["title"] for r in rows] == ["Beta Hindi Tutorial"]


def test_library_document_filter_stays_inside_visibility(client, db, test_user):
    """Another tenant's document id matches nothing rather than leaking it."""
    seeded = _seed_library(db, "someone-else")
    foreign = seeded["videos"]["v1"]
    response = client.get("/api/v1/library/videos", params={"document_id": foreign.document_id})
    assert response.status_code == 200
    assert response.json() == []
