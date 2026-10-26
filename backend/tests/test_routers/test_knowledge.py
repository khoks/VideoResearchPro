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
from app.services import auth_service, visibility_service


@pytest.fixture
def seeded_video_with_transcript(db, test_user):
    """Create one Video row plus a matching TranscriptCache row, visible to
    the client's user (D-063: an ungranted document 404s like a missing one)."""
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
    visibility_service.grant(db, [video.document_id], test_user.id)
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


def test_extract_knowledge_422_if_no_transcript(client, db, test_user):
    """Video exists but has neither a TranscriptCache row nor chunks → 422.

    The chunks are the second store consulted (by document_id, with the
    YouTube id as the fallback key); patched here so the test never opens a
    persistent Chroma collection."""
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
    visibility_service.grant(db, [video.document_id], test_user.id)

    with (
        patch("app.services.chroma_service.get_document_chunks", return_value=[]) as chunks,
        patch("app.agents.knowledge_agent.run_knowledge_extract_agent") as agent,
    ):
        response = client.post("/api/v1/videos/vidNoTrans/extract-knowledge")
    assert response.status_code == 422
    chunks.assert_called_once_with(video.document_id, "vidNoTrans")
    assert not agent.called


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
    refreshed = db.get(Document, seeded_video_with_transcript.document_id)
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
    # S-8.8.3: the reader names the source from this response alone.
    assert data["title"] == "Intro to PostgreSQL"
    assert data["document_id"] == seeded_video_with_transcript.document_id
    assert data["source_type"] == "video"
    assert data["url"] == "https://www.youtube.com/watch?v=vid123abcXYZ"
    assert data["published_at"]


def test_get_knowledge_for_a_non_video_document(client, db, test_user):
    """A PDF's artifact (no legacy video_id) serialises; before S-8.8.3 the
    schema declared ``video_id: str`` and this 500'd."""
    now = datetime.now(timezone.utc)
    pdf = Document(
        video_id=None,
        source_type="pdf",
        source_id="sha256-knowledge",
        title="A paper",
        url="",
        transcript_status="completed",
        knowledge_report_md="# A paper\n\n## Findings\n\nText.",
        extracted_knowledge_json=json.dumps({"topics": ["t"], "concepts": [], "events": [], "facts": []}),
        knowledge_extracted_at=now,
        created_at=now,
    )
    db.add(pdf)
    db.commit()
    visibility_service.grant(db, [pdf.document_id], test_user.id)
    response = client.get(f"/api/v1/videos/{pdf.document_id}/knowledge")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["video_id"] is None
    assert data["source_type"] == "pdf"
    assert data["title"] == "A paper"
    assert data["url"] is None


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


# ---------------------------------------------------------------------------
# D-063: the artifact is shared cache, the right to read it is not
# ---------------------------------------------------------------------------


@pytest.fixture
def other_tenant_headers(db):
    other = auth_service.create_user(db, email="other@example.com", password="testpass123")
    token, _ = auth_service.create_access_token(other.id)
    return {"Authorization": f"Bearer {token}"}


def test_other_tenant_cannot_read_or_extract_knowledge(
    client, db, seeded_video_with_transcript, other_tenant_headers
):
    """The document is visible to the client's user only. Another signed-in
    user gets 404 on both endpoints — indistinguishable from a missing id —
    and the extraction agent never runs on their behalf. Before 2026-10-19
    neither endpoint checked the tenant."""
    vid = seeded_video_with_transcript.video_id
    with patch(
        "app.agents.knowledge_agent.run_knowledge_extract_agent",
        return_value=_fake_agent_result(),
    ):
        assert client.post(f"/api/v1/videos/{vid}/extract-knowledge").status_code == 200

    with patch("app.agents.knowledge_agent.run_knowledge_extract_agent") as agent:
        foreign_post = client.post(
            f"/api/v1/videos/{vid}/extract-knowledge?force=true", headers=other_tenant_headers
        )
    assert foreign_post.status_code == 404
    assert not agent.called

    foreign_get = client.get(f"/api/v1/videos/{vid}/knowledge", headers=other_tenant_headers)
    assert foreign_get.status_code == 404
    missing = client.get("/api/v1/videos/doesNotExist1/knowledge", headers=other_tenant_headers)
    assert foreign_get.json() == missing.json() == {"detail": "Video not found"}

    # The owner still reads it.
    assert client.get(f"/api/v1/videos/{vid}/knowledge").status_code == 200


def test_knowledge_resolves_by_document_id_too(client, seeded_video_with_transcript):
    """The path accepts the primary key as well as the legacy YouTube id."""
    doc_id = seeded_video_with_transcript.document_id
    with patch(
        "app.agents.knowledge_agent.run_knowledge_extract_agent",
        return_value=_fake_agent_result(),
    ):
        assert client.post(f"/api/v1/videos/{doc_id}/extract-knowledge").status_code == 200
    assert client.get(f"/api/v1/videos/{doc_id}/knowledge").status_code == 200
