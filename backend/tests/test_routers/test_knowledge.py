"""Tests for the per-video knowledge router (Unit 4).

Endpoints:
  POST /api/v1/videos/{video_id}/extract-knowledge
  GET  /api/v1/videos/{video_id}/knowledge
"""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.transcript_cache import TranscriptCache
from app.models.document import Document


@pytest.fixture
def seeded_video_with_transcript(db):
    """Create one Video row plus a matching TranscriptCache row."""
    now = datetime.now(timezone.utc)
    video = Document(
        video_id="vid123abcXYZ",
        title="Intro to PostgreSQL",
        channel_id=None,
        url="https://www.youtube.com/watch?v=vid123abcXYZ",
        duration_seconds=600,
        published_at=now,
        transcript_status="fetched",
        created_at=now,
    )
    db.add(video)

    segments = [
        {"text": "PostgreSQL is an open source database.", "start": 0.0, "duration": 5.0},
        {"text": "It supports ACID transactions.", "start": 5.0, "duration": 3.0},
    ]
    cache = TranscriptCache(
        video_id=video.video_id,
        segments_json=json.dumps(segments),
        language="en",
        fetched_at=now,
    )
    db.add(cache)
    db.commit()
    db.refresh(video)
    return video


def _fake_agent_result() -> dict:
    return {
        "topics": ["databases"],
        "concepts": ["ACID"],
        "events": [],
        "facts": ["PostgreSQL is open source"],
        "knowledge_report_md": "# Databases\n\nParagraph.",
    }


def test_extract_knowledge_404_if_video_missing(client):
    response = client.post("/api/v1/videos/nope/extract-knowledge")
    assert response.status_code == 404


def test_extract_knowledge_422_if_no_transcript(client, db):
    """Video exists but TranscriptCache row is missing → 422."""
    video = Document(
        video_id="vidNoTrans",
        title="No transcript",
        channel_id=None,
        url="https://www.youtube.com/watch?v=vidNoTrans",
        duration_seconds=100,
        transcript_status="pending",
    )
    db.add(video)
    db.commit()

    response = client.post("/api/v1/videos/vidNoTrans/extract-knowledge")
    assert response.status_code == 422


def test_extract_knowledge_runs_agent_and_persists(client, seeded_video_with_transcript, db):
    with patch(
        "app.agents.knowledge_agent.run_knowledge_extract_agent",
        return_value=_fake_agent_result(),
    ):
        response = client.post(
            f"/api/v1/videos/{seeded_video_with_transcript.video_id}/extract-knowledge"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["video_id"] == seeded_video_with_transcript.video_id
    assert data["topics"] == ["databases"]
    assert data["facts"] == ["PostgreSQL is open source"]
    assert data["knowledge_report_md"].startswith("# Databases")
    assert data["knowledge_extracted_at"] is not None

    # Persisted on the row
    db.expire_all()
    refreshed = db.get(Document, seeded_video_with_transcript.video_id)
    assert refreshed.knowledge_report_md.startswith("# Databases")
    stored = json.loads(refreshed.extracted_knowledge_json)
    assert stored["topics"] == ["databases"]
    assert refreshed.knowledge_extracted_at is not None


def test_extract_knowledge_409_if_already_extracted(client, seeded_video_with_transcript):
    """Second extraction without ?force=true returns 409."""
    with patch(
        "app.agents.knowledge_agent.run_knowledge_extract_agent",
        return_value=_fake_agent_result(),
    ):
        first = client.post(
            f"/api/v1/videos/{seeded_video_with_transcript.video_id}/extract-knowledge"
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/v1/videos/{seeded_video_with_transcript.video_id}/extract-knowledge"
        )
    assert second.status_code == 409


def test_extract_knowledge_force_overrides_409(client, seeded_video_with_transcript):
    with patch(
        "app.agents.knowledge_agent.run_knowledge_extract_agent",
        return_value=_fake_agent_result(),
    ) as mock_agent:
        client.post(
            f"/api/v1/videos/{seeded_video_with_transcript.video_id}/extract-knowledge"
        )
        second = client.post(
            f"/api/v1/videos/{seeded_video_with_transcript.video_id}/extract-knowledge?force=true"
        )
    assert second.status_code == 200
    assert mock_agent.call_count == 2


def test_get_knowledge_returns_persisted_artifact(client, seeded_video_with_transcript):
    with patch(
        "app.agents.knowledge_agent.run_knowledge_extract_agent",
        return_value=_fake_agent_result(),
    ):
        client.post(
            f"/api/v1/videos/{seeded_video_with_transcript.video_id}/extract-knowledge"
        )

    response = client.get(
        f"/api/v1/videos/{seeded_video_with_transcript.video_id}/knowledge"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["topics"] == ["databases"]
    assert data["knowledge_report_md"].startswith("# Databases")


def test_get_knowledge_404_if_not_extracted(client, seeded_video_with_transcript):
    response = client.get(
        f"/api/v1/videos/{seeded_video_with_transcript.video_id}/knowledge"
    )
    assert response.status_code == 404


def test_extract_knowledge_requires_auth(unauthenticated_client, seeded_video_with_transcript):
    response = unauthenticated_client.post(
        f"/api/v1/videos/{seeded_video_with_transcript.video_id}/extract-knowledge"
    )
    assert response.status_code == 401


def test_get_knowledge_requires_auth(unauthenticated_client, seeded_video_with_transcript):
    response = unauthenticated_client.get(
        f"/api/v1/videos/{seeded_video_with_transcript.video_id}/knowledge"
    )
    assert response.status_code == 401
