"""S-1.18.2: frames surfaced to the user.

Endpoints:
  GET  /api/v1/videos/{video_id}/frames
  GET  /api/v1/videos/{video_id}/frames/{frame_id}/image
  POST /api/v1/videos/{video_id}/extract-frames

A frame is as private as its document (D-063): every route 404s for a
document the caller cannot see, exactly like a missing one.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.models.document import Document
from app.models.transcript_cache import TranscriptCache
from app.models.visual_frame import VisualFrame
from app.services import auth_service, quota_metering_service, visibility_service

JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes\xff\xd9"


def _video(db, vid: str, *, grant_to=None, transcript=True, source_type="video") -> Document:
    now = datetime.now(timezone.utc)
    doc = Document(
        video_id=vid if source_type == "video" else None,
        source_type=source_type,
        source_id=vid,
        title=f"Video {vid}",
        url=f"https://www.youtube.com/watch?v={vid}",
        duration_seconds=600,
        published_at=now,
        transcript_status="fetched",
        created_at=now,
    )
    db.add(doc)
    db.flush()
    if transcript and doc.video_id:
        db.add(TranscriptCache(
            video_id=doc.video_id,
            segments_json=json.dumps([{"text": "a chart appears", "start": 0.0, "duration": 5.0}]),
            language="en", fetched_at=now,
        ))
    db.commit()
    db.refresh(doc)
    if grant_to is not None:
        visibility_service.grant(db, [doc.document_id], grant_to.id)
    return doc


@pytest.fixture
def frames_dir(tmp_path, monkeypatch):
    root = tmp_path / "frames"
    root.mkdir()
    monkeypatch.setattr(settings, "VISUAL_FRAMES_DIR", str(root))
    return root


def _frame(db, doc, ts: float, frames_dir, *, write=True, image_path=None, status="described") -> VisualFrame:
    rel = image_path if image_path is not None else f"{doc.video_id}/{int(ts)}.jpg"
    if write and image_path is None:
        (frames_dir / doc.video_id).mkdir(exist_ok=True)
        (frames_dir / rel).write_bytes(JPEG)
    f = VisualFrame(video_id=doc.video_id, timestamp_seconds=ts, image_path=rel, status=status,
                    description=f"chart at {ts}", informative=True, width=640, height=360)
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


@pytest.fixture
def other_tenant_headers(db):
    other = auth_service.create_user(db, email="other@example.com", password="testpass123")
    token, _ = auth_service.create_access_token(other.id)
    return {"Authorization": f"Bearer {token}"}


# ---------- list ----------------------------------------------------------------

def test_lists_a_visible_documents_frames_in_time_order(client, db, test_user, frames_dir):
    doc = _video(db, "vidAAAAAAAA", grant_to=test_user)
    _frame(db, doc, 194.0, frames_dir)
    _frame(db, doc, 58.0, frames_dir, write=False)
    r = client.get(f"/api/v1/videos/{doc.video_id}/frames")
    assert r.status_code == 200
    body = r.json()
    assert body["document_id"] == doc.document_id
    assert [(f["timestamp_display"], f["has_image"]) for f in body["frames"]] == [("0:58", False), ("3:14", True)]
    assert body["visual_enabled"] is bool(settings.VISUAL_ENABLED)


def test_frames_are_found_by_document_id_too(client, db, test_user, frames_dir):
    doc = _video(db, "vidBBBBBBBB", grant_to=test_user)
    _frame(db, doc, 10.0, frames_dir)
    assert len(client.get(f"/api/v1/videos/{doc.document_id}/frames").json()["frames"]) == 1


def test_another_tenants_document_404s_like_a_missing_one(client, db, test_user, frames_dir, other_tenant_headers):
    doc = _video(db, "vidCCCCCCCC", grant_to=test_user)
    f = _frame(db, doc, 10.0, frames_dir)
    for url in (f"/api/v1/videos/{doc.video_id}/frames", f"/api/v1/videos/{doc.video_id}/frames/{f.frame_id}/image"):
        theirs = client.get(url, headers=other_tenant_headers)
        missing = client.get(url.replace(doc.video_id, "vidZZZZZZZZ"), headers=other_tenant_headers)
        assert theirs.status_code == missing.status_code == 404
        assert theirs.json() == {"detail": "Video not found"} == missing.json()


# ---------- image ---------------------------------------------------------------

def test_serves_the_still(client, db, test_user, frames_dir):
    doc = _video(db, "vidDDDDDDDD", grant_to=test_user)
    f = _frame(db, doc, 77.0, frames_dir)
    r = client.get(f"/api/v1/videos/{doc.video_id}/frames/{f.frame_id}/image")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == JPEG
    assert "private" in r.headers["cache-control"]


def test_a_visible_document_cannot_read_another_documents_frame(client, db, test_user, frames_dir):
    mine = _video(db, "vidEEEEEEEE", grant_to=test_user)
    foreign = _video(db, "vidFFFFFFFF")          # nobody granted it to this user
    f = _frame(db, foreign, 5.0, frames_dir)
    r = client.get(f"/api/v1/videos/{mine.video_id}/frames/{f.frame_id}/image")
    assert r.status_code == 404


def test_a_stored_path_outside_the_frames_root_is_never_served(client, db, test_user, frames_dir, tmp_path):
    doc = _video(db, "vidGGGGGGGG", grant_to=test_user)
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(JPEG)
    f1 = _frame(db, doc, 1.0, frames_dir, image_path=str(secret))           # absolute, outside
    f2 = _frame(db, doc, 2.0, frames_dir, image_path="../secret.jpg")        # relative escape
    for f in (f1, f2):
        assert client.get(f"/api/v1/videos/{doc.video_id}/frames/{f.frame_id}/image").status_code == 404
    listed = client.get(f"/api/v1/videos/{doc.video_id}/frames").json()["frames"]
    assert [x["has_image"] for x in listed] == [False, False]


def test_a_missing_file_404s(client, db, test_user, frames_dir):
    doc = _video(db, "vidHHHHHHHH", grant_to=test_user)
    f = _frame(db, doc, 9.0, frames_dir, write=False)
    assert client.get(f"/api/v1/videos/{doc.video_id}/frames/{f.frame_id}/image").status_code == 404


# ---------- extract ---------------------------------------------------------------

@pytest.fixture
def visual_on(monkeypatch):
    monkeypatch.setattr(settings, "VISUAL_ENABLED", True)
    with patch("app.services.visual_extraction_service.mark_started", return_value=True) as started, \
         patch("app.services.visual_extraction_service.mark_finished") as finished, \
         patch("app.services.visual_extraction_service.is_in_progress", return_value=False):
        yield started, finished


def test_extract_queues_the_worker_task(client, db, test_user, visual_on):
    doc = _video(db, "vidIIIIIIII", grant_to=test_user)
    with patch("app.routers.frames.task_routing_service.dispatch_for_user") as dispatch:
        r = client.post(f"/api/v1/videos/{doc.video_id}/extract-frames")
    assert r.status_code == 202
    assert r.json() == {"status": "queued", "document_id": doc.document_id}
    task, user, *args = dispatch.call_args.args
    assert user.id == test_user.id and args == [doc.document_id, test_user.id, False]


def test_extract_is_refused_when_the_install_switch_is_off(client, db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "VISUAL_ENABLED", False)
    doc = _video(db, "vidJJJJJJJJ", grant_to=test_user)
    r = client.post(f"/api/v1/videos/{doc.video_id}/extract-frames")
    assert r.status_code == 503 and "VISUAL_ENABLED" in r.json()["detail"]


def test_extract_is_refused_when_the_vision_models_failed_their_probe(client, db, test_user, visual_on):
    doc = _video(db, "vidKKKKKKKK", grant_to=test_user)
    with patch("app.services.llm_smoke._STATUS.unavailable_features", return_value=["visual_analysis"]):
        assert client.post(f"/api/v1/videos/{doc.video_id}/extract-frames").status_code == 503


def test_extract_needs_a_youtube_video_with_a_transcript(client, db, test_user, visual_on):
    pdf = _video(db, "pdf:abc", grant_to=test_user, source_type="pdf")
    bare = _video(db, "vidLLLLLLLL", grant_to=test_user, transcript=False)
    assert client.post(f"/api/v1/videos/{pdf.document_id}/extract-frames").status_code == 422
    assert client.post(f"/api/v1/videos/{bare.video_id}/extract-frames").status_code == 422


def test_existing_frames_need_force(client, db, test_user, frames_dir, visual_on):
    doc = _video(db, "vidMMMMMMMM", grant_to=test_user)
    _frame(db, doc, 3.0, frames_dir)
    with patch("app.routers.frames.task_routing_service.dispatch_for_user") as dispatch:
        assert client.post(f"/api/v1/videos/{doc.video_id}/extract-frames").status_code == 409
        assert client.post(f"/api/v1/videos/{doc.video_id}/extract-frames?force=true").status_code == 202
    assert dispatch.call_count == 1 and dispatch.call_args.args[-1] is True


def test_a_capture_already_running_is_a_409(client, db, test_user, visual_on):
    started, _finished = visual_on
    started.return_value = False
    doc = _video(db, "vidNNNNNNNN", grant_to=test_user)
    with patch("app.routers.frames.task_routing_service.dispatch_for_user") as dispatch:
        assert client.post(f"/api/v1/videos/{doc.video_id}/extract-frames").status_code == 409
    dispatch.assert_not_called()


def test_extract_enforces_the_monthly_quota(client, db, test_user, visual_on):
    doc = _video(db, "vidOOOOOOOO", grant_to=test_user)
    quota_metering_service.record_usage(db, test_user.id, "visual_extractions", 2)   # free tier: 2
    with patch("app.routers.frames.task_routing_service.dispatch_for_user") as dispatch:
        assert client.post(f"/api/v1/videos/{doc.video_id}/extract-frames").status_code == 429
    dispatch.assert_not_called()


def test_a_failed_dispatch_releases_the_document(client, db, test_user, visual_on):
    _started, finished = visual_on
    doc = _video(db, "vidPPPPPPPP", grant_to=test_user)
    with patch("app.routers.frames.task_routing_service.dispatch_for_user", side_effect=RuntimeError("broker down")):
        assert client.post(f"/api/v1/videos/{doc.video_id}/extract-frames").status_code == 503
    finished.assert_called_once_with(doc.document_id)


def test_another_tenant_cannot_spend_a_capture_on_my_document(client, db, test_user, visual_on, other_tenant_headers):
    doc = _video(db, "vidQQQQQQQQ", grant_to=test_user)
    with patch("app.routers.frames.task_routing_service.dispatch_for_user") as dispatch:
        r = client.post(f"/api/v1/videos/{doc.video_id}/extract-frames", headers=other_tenant_headers)
    assert r.status_code == 404
    dispatch.assert_not_called()


# ---------- health ---------------------------------------------------------------

def test_health_reports_the_install_switch(client, monkeypatch):
    monkeypatch.setattr(settings, "VISUAL_ENABLED", True)
    assert client.get("/api/v1/health").json()["capabilities"]["visual_analysis_enabled"] is True
    monkeypatch.setattr(settings, "VISUAL_ENABLED", False)
    assert client.get("/api/v1/health").json()["capabilities"]["visual_analysis_enabled"] is False


# ---------- worker task ------------------------------------------------------------

def _run_task(db, doc_id, user_id, newly):
    from app.tasks import visual_tasks

    session = MagicMock(wraps=db)
    session.close = MagicMock()
    with patch.object(visual_tasks, "SessionLocal", return_value=session), \
         patch("app.agents.visual_agent.run_visual_agent", return_value=([], newly)) as agent, \
         patch("app.services.visual_extraction_service.mark_finished") as finished:
        out = visual_tasks.extract_frames.run(doc_id, user_id, False)
    return out, agent, finished


def test_the_task_charges_quota_only_for_frames_it_captured(db, test_user):
    doc = _video(db, "vidRRRRRRRR", grant_to=test_user)
    out, agent, finished = _run_task(db, doc.document_id, test_user.id, newly=7)
    assert out == 7
    assert agent.call_args.kwargs["video_id"] == doc.video_id
    assert agent.call_args.kwargs["segments"][0]["text"] == "a chart appears"
    assert quota_metering_service.get_usage(db, test_user.id, "visual_extractions") == 1
    finished.assert_called_once_with(doc.document_id)

    out, _agent, finished = _run_task(db, doc.document_id, test_user.id, newly=0)   # frames already existed
    assert out == 0
    assert quota_metering_service.get_usage(db, test_user.id, "visual_extractions") == 1
    finished.assert_called_once_with(doc.document_id)


def test_the_task_always_releases_the_document_even_when_it_fails(db, test_user):
    from app.tasks import visual_tasks

    doc = _video(db, "vidSSSSSSSS", grant_to=test_user)
    session = MagicMock(wraps=db)
    session.close = MagicMock()
    with patch.object(visual_tasks, "SessionLocal", return_value=session), \
         patch("app.agents.visual_agent.run_visual_agent", side_effect=RuntimeError("yt-dlp blocked")), \
         patch("app.services.visual_extraction_service.mark_finished") as finished:
        assert visual_tasks.extract_frames.run(doc.document_id, test_user.id, False) == 0
    finished.assert_called_once_with(doc.document_id)
