"""``GET /jobs/{id}/videos`` carries the polymorphic document fields.

``job_service.job_videos_response`` has built ``source_type`` /
``document_id`` / ``source_metadata`` since S-1.5.4, but the response schema
did not declare them, so FastAPI dropped them — and a non-video document
(``video_id`` NULL) failed validation outright. The job page's approval cards
and the reader's citation cards (S-8.8.2) both dispatch on ``source_type``.
"""

from datetime import datetime, timezone

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo


def _job_with_documents(db, tenant_id):
    job = Job(job_type="topic", topic="polymorphic", status="completed", num_videos=2, tenant_id=tenant_id)
    db.add(job)
    video = Document(
        video_id="abcdefghijk",
        source_type="video",
        source_id="abcdefghijk",
        title="A video",
        url="https://www.youtube.com/watch?v=abcdefghijk",
        duration_seconds=600,
        transcript_status="completed",
        created_at=datetime.now(timezone.utc),
    )
    pdf = Document(
        video_id=None,
        source_type="pdf",
        source_id="sha256-of-the-file",
        source_url=None,
        source_metadata_json='{"page_count": 12}',
        title="A paper",
        url="",
        duration_seconds=None,
        transcript_status="completed",
        created_at=datetime.now(timezone.utc),
    )
    db.add_all([video, pdf])
    db.commit()
    db.add_all(
        [
            JobVideo(job_id=job.id, document_id=video.document_id, video_id=video.video_id),
            JobVideo(job_id=job.id, document_id=pdf.document_id, video_id=None),
        ]
    )
    db.commit()
    db.refresh(job)
    return job, video, pdf


def test_job_videos_include_source_type_and_document_id(client, db, test_user):
    job, video, pdf = _job_with_documents(db, test_user.id)
    response = client.get(f"/api/v1/jobs/{job.id}/videos")
    assert response.status_code == 200, response.text
    rows = {r["document_id"]: r for r in response.json()}
    assert set(rows) == {video.document_id, pdf.document_id}

    v = rows[video.document_id]
    assert v["source_type"] == "video"
    assert v["video_id"] == "abcdefghijk"
    assert v["channel_name"] in ("", None)  # no Channel row seeded; property reads it
    assert v["duration_seconds"] == 600


def test_non_video_document_on_a_job_serialises(client, db, test_user):
    """Before the fix this row 500'd: ``video_id`` and ``duration_seconds``
    were declared non-nullable."""
    job, _video, pdf = _job_with_documents(db, test_user.id)
    response = client.get(f"/api/v1/jobs/{job.id}/videos")
    assert response.status_code == 200, response.text
    p = next(r for r in response.json() if r["document_id"] == pdf.document_id)
    assert p["source_type"] == "pdf"
    assert p["video_id"] is None
    assert p["duration_seconds"] is None
    assert p["source_metadata"] == {"page_count": 12}
    assert p["id"] == pdf.document_id
