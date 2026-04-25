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
# GET /api/v1/library/videos
# ---------------------------------------------------------------------------


def _seed_library(db) -> dict:
    """Two channels, four videos with varied transcript states/durations,
    and two jobs sharing one video so the aggregation has something to count."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    ch_a = Channel(channel_id="UCaaaaaaaaaaaaaaaaaaaaa1", name="Alpha Channel", subscribed=True)
    ch_b = Channel(channel_id="UCbbbbbbbbbbbbbbbbbbbbb2", name="Beta Channel", subscribed=False)
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

    job_a = Job(job_type="topic", topic="DNS basics", status="completed")
    job_b = Job(job_type="topic", topic="Networking 101", status="completed")
    db.add_all([job_a, job_b])
    db.commit()

    db.add_all([
        JobVideo(job_id=job_a.id, video_id=v1.video_id, approved=True),
        JobVideo(job_id=job_b.id, video_id=v1.video_id, approved=True),
        JobVideo(job_id=job_b.id, video_id=v2.video_id, approved=True),
    ])
    db.commit()

    return {
        "channels": {"alpha": ch_a, "beta": ch_b},
        "videos": {"v1": v1, "v2": v2, "v3": v3, "v4": v4},
        "jobs": {"a": job_a, "b": job_b},
    }


def test_get_library_videos_empty(client):
    response = client.get("/api/v1/library/videos")
    assert response.status_code == 200
    assert response.json() == []


def test_get_library_videos_returns_all_with_aggregation(client, db):
    seed = _seed_library(db)
    response = client.get("/api/v1/library/videos")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 4

    by_id = {it["video_id"]: it for it in items}
    v1 = by_id["vid001alpha"]
    assert v1["id"] == v1["video_id"]
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


def test_get_library_videos_search_matches_title_or_channel(client, db):
    _seed_library(db)

    title_match = client.get("/api/v1/library/videos", params={"search": "DNS"})
    assert title_match.status_code == 200
    assert {it["video_id"] for it in title_match.json()} == {"vid001alpha"}

    channel_match = client.get("/api/v1/library/videos", params={"search": "Beta Channel"})
    assert channel_match.status_code == 200
    assert {it["video_id"] for it in channel_match.json()} == {"vid003beta", "vid004beta"}


def test_get_library_videos_filters_language_channel_status(client, db):
    seed = _seed_library(db)

    en_only = client.get("/api/v1/library/videos", params={"language": "en"})
    assert {it["video_id"] for it in en_only.json()} == {"vid001alpha"}

    alpha_only = client.get(
        "/api/v1/library/videos",
        params={"channel_id": seed["channels"]["alpha"].channel_id},
    )
    assert {it["video_id"] for it in alpha_only.json()} == {"vid001alpha", "vid002alpha"}

    pending = client.get("/api/v1/library/videos", params={"transcript_status": "pending"})
    assert {it["video_id"] for it in pending.json()} == {"vid002alpha"}


def test_get_library_videos_sort_variants(client, db):
    _seed_library(db)

    newest = client.get("/api/v1/library/videos", params={"sort": "newest"}).json()
    assert [it["video_id"] for it in newest][0] == "vid004beta"

    oldest = client.get("/api/v1/library/videos", params={"sort": "oldest"}).json()
    assert [it["video_id"] for it in oldest][0] == "vid001alpha"

    longest = client.get("/api/v1/library/videos", params={"sort": "longest"}).json()
    assert [it["video_id"] for it in longest][0] == "vid002alpha"

    shortest = client.get("/api/v1/library/videos", params={"sort": "shortest"}).json()
    assert [it["video_id"] for it in shortest][0] == "vid004beta"


def test_get_library_videos_pagination(client, db):
    _seed_library(db)
    first = client.get("/api/v1/library/videos", params={"limit": 2, "offset": 0}).json()
    second = client.get("/api/v1/library/videos", params={"limit": 2, "offset": 2}).json()
    assert len(first) == 2
    assert len(second) == 2
    assert {it["video_id"] for it in first}.isdisjoint({it["video_id"] for it in second})


def test_get_library_videos_requires_auth(unauthenticated_client):
    response = unauthenticated_client.get("/api/v1/library/videos")
    assert response.status_code == 401
