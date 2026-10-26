"""The document cap inside the subscription task (T-5.2.10).

A sync is the one ingest with no request to refuse — a scheduled sync has no
user at all — so ``execute_subscription_job`` stops at the cap instead:
uploads the tenant already sees always pass, new ones are taken in playlist
order (newest first) until the cap, and the job says how many it left out.
There is no scheduled channel sync today; any future one runs through this
task, so these tests are its behaviour.

Mutation checks (run by hand when this shipped): replacing
``cap_budget.admit(db, ...)`` with the plain list made
``test_sync_stops_at_the_cap_and_says_so`` and
``test_sync_at_the_cap_ingests_nothing_new`` fail. Deleting the grant before
the uploads walk failed ``test_redelivered_sync_counts_the_links_its_earlier_run_made``;
deleting the per-channel grant after linking failed
``test_sync_grants_each_channel_as_soon_as_it_is_linked``; and deleting the
visible-count re-read in ``SyncBudget.admit`` failed
``test_sync_charges_ingests_that_landed_after_its_budget_was_read``.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services.tier_service import TIER_CAPABILITIES, Tier
from app.sources.video import connector as yt_connector
from app.tasks import job_tasks

CHANNEL = "UCcapSync"


@pytest.fixture
def patch_session_local(monkeypatch, db):
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    yield


def _job(db, tenant_id: str) -> Job:
    job = Job(job_type="subscription", num_videos=0, channel_list=f'["{CHANNEL}"]', tenant_id=tenant_id)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _seen(db, tenant_id: str, video_ids: list[str]) -> None:
    for vid in video_ids:
        doc = Document(video_id=vid, title=vid, url=f"https://www.youtube.com/watch?v={vid}")
        db.add(doc)
        db.commit()
        db.add(DocumentVisibility(document_id=doc.document_id, tenant_id=tenant_id, source="job"))
        db.commit()


def _run(job_id: str, uploads: list[str]) -> None:
    details = {
        vid: {
            "video_id": vid,
            "title": f"Upload {vid}",
            "channel_name": "Cap",
            "channel_id": CHANNEL,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "duration_seconds": 60,
            "thumbnail_url": None,
            "published_at": None,
        }
        for vid in uploads
    }
    with patch.object(job_tasks, "youtube_service") as yt, \
         patch.object(yt_connector, "youtube_service", yt), \
         patch.object(job_tasks, "chroma_service") as chroma, \
         patch.object(job_tasks, "progress_service"), \
         patch.object(job_tasks.temporal_service, "ensure_discussed_era", return_value=None):
        yt.resolve_channel_id = MagicMock(return_value=CHANNEL)
        yt.get_channel_metadata = MagicMock(return_value={
            "channel_id": CHANNEL, "name": "Cap", "uploads_playlist_id": "UUcapSync",
            "subscriber_count": 1,
        })
        yt.get_channel_videos_all = MagicMock(return_value=uploads)
        yt.get_video_details = MagicMock(
            side_effect=lambda ids, **_kw: {v: details[v] for v in ids if v in details}
        )
        yt.fetch_transcript = MagicMock(
            return_value=([{"text": "words", "start": 0.0, "duration": 1.0}], "en", "youtube")
        )
        chroma.insert_chunks = MagicMock(return_value=1)
        chroma.delete_video_chunks = MagicMock(return_value=None)
        job_tasks.execute_subscription_job.run(job_id)


def _linked(db, job_id: str) -> list[str]:
    return sorted(r[0] for r in db.query(JobVideo.video_id).filter(JobVideo.job_id == job_id))


def _visible(db, tenant_id: str) -> int:
    return db.query(DocumentVisibility).filter(DocumentVisibility.tenant_id == tenant_id).count()


def test_sync_stops_at_the_cap_and_says_so(patch_session_local, db, test_user, monkeypatch):
    """Cap 4 with 2 seen: one of the five uploads is already seen (passes
    free), the two newest new ones fill the cap, the last two are left out."""
    monkeypatch.setitem(TIER_CAPABILITIES[Tier.FREE], "document_count_cap", 4)
    _seen(db, test_user.id, ["old0", "u2"])
    job = _job(db, test_user.id)

    _run(job.id, ["u1", "u2", "u3", "u4", "u5"])

    assert _linked(db, job.id) == ["u1", "u2", "u3"]
    assert _visible(db, test_user.id) == 4
    db.expire_all()
    job = db.get(Job, job.id)
    assert job.status == "completed"
    assert "2 new uploads were left out" in job.progress_message
    assert "Free plan's cap of 4 documents" in job.progress_message


def test_sync_at_the_cap_ingests_nothing_new(patch_session_local, db, test_user, monkeypatch):
    """The library filled up after the sync was queued (or a scheduled sync
    found it full): nothing new is linked or granted and the job says why."""
    monkeypatch.setitem(TIER_CAPABILITIES[Tier.FREE], "document_count_cap", 1)
    _seen(db, test_user.id, ["old0"])
    job = _job(db, test_user.id)

    _run(job.id, ["n1", "n2"])

    assert _linked(db, job.id) == []
    assert _visible(db, test_user.id) == 1
    assert db.query(Document).filter(Document.video_id.in_(["n1", "n2"])).count() == 0
    db.expire_all()
    job = db.get(Job, job.id)
    assert job.status == "failed"
    assert job.error_message.startswith("2 new uploads were left out")


def test_sync_at_the_cap_still_relinks_uploads_already_seen(patch_session_local, db, test_user, monkeypatch):
    monkeypatch.setitem(TIER_CAPABILITIES[Tier.FREE], "document_count_cap", 2)
    _seen(db, test_user.id, ["s1", "s2"])
    job = _job(db, test_user.id)

    _run(job.id, ["s1", "new1", "s2"])

    assert _linked(db, job.id) == ["s1", "s2"]
    db.expire_all()
    job = db.get(Job, job.id)
    assert job.status == "completed"
    assert "1 new upload was left out" in job.progress_message


def test_studio_sync_is_not_capped(patch_session_local, db, test_user, monkeypatch):
    monkeypatch.setitem(TIER_CAPABILITIES[Tier.FREE], "document_count_cap", 0)
    test_user.tier = "studio"
    db.commit()
    job = _job(db, test_user.id)

    _run(job.id, ["a1", "a2", "a3"])

    assert _linked(db, job.id) == ["a1", "a2", "a3"]
    db.expire_all()
    assert db.get(Job, job.id).progress_message == "Subscription sync completed successfully!"


def test_sync_under_the_cap_is_unchanged(patch_session_local, db, test_user):
    job = _job(db, test_user.id)
    _run(job.id, ["b1", "b2"])
    assert _linked(db, job.id) == ["b1", "b2"]
    db.expire_all()
    assert db.get(Job, job.id).progress_message == "Subscription sync completed successfully!"


def _link(db, job_id: str, video_ids: list[str]) -> None:
    """Links a previous run of the job made before it died (no grants yet)."""
    for vid in video_ids:
        doc = Document(video_id=vid, title=vid, url=f"https://www.youtube.com/watch?v={vid}")
        db.add(doc)
        db.commit()
        db.add(JobVideo(job_id=job_id, document_id=doc.document_id, video_id=vid, approved=True))
        db.commit()


def test_redelivered_sync_counts_the_links_its_earlier_run_made(
    patch_session_local, db, test_user, monkeypatch
):
    """Tasks ack late, so a worker that dies mid-walk gets the job redelivered.
    The first run's links (granted only at extraction start before this fix)
    must count against the cap, not ride on top of a fresh full budget: cap 4,
    three earlier links, so one more upload fits and two are left out."""
    monkeypatch.setitem(TIER_CAPABILITIES[Tier.FREE], "document_count_cap", 4)
    job = _job(db, test_user.id)
    _link(db, job.id, ["p1", "p2", "p3"])

    _run(job.id, ["p1", "p2", "p3", "n1", "n2", "n3"])

    assert _linked(db, job.id) == ["n1", "p1", "p2", "p3"]
    assert _visible(db, test_user.id) == 4
    db.expire_all()
    assert "2 new uploads were left out" in db.get(Job, job.id).progress_message


def test_sync_grants_each_channel_as_soon_as_it_is_linked(
    patch_session_local, db, test_user, monkeypatch
):
    """The admitted uploads are in the library (and on the cap's count) before
    extraction starts, which can take hours behind a solo worker; an approval
    or paste made meanwhile is measured against them."""
    monkeypatch.setitem(TIER_CAPABILITIES[Tier.FREE], "document_count_cap", 10)
    _seen(db, test_user.id, ["old0"])
    job = _job(db, test_user.id)
    at_extraction: list[int] = []

    def _extraction(_self, db_, _job):
        at_extraction.append(_visible(db_, test_user.id))

    with patch.object(job_tasks, "_run_extraction_and_rag", side_effect=_extraction):
        _run(job.id, ["g1", "g2", "g3"])

    assert at_extraction == [4]


def test_sync_charges_ingests_that_landed_after_its_budget_was_read(
    patch_session_local, db, test_user, monkeypatch
):
    """The budget is read before the uploads walk; documents granted after
    that (another ingest landing while the playlist was listed) are charged
    before this channel takes its share. Cap 4, one seen, two granted after
    the budget was read: one new upload fits, not three."""
    from app.services import document_cap_service

    monkeypatch.setitem(TIER_CAPABILITIES[Tier.FREE], "document_count_cap", 4)
    _seen(db, test_user.id, ["old0"])
    job = _job(db, test_user.id)
    real_budget = document_cap_service.sync_budget

    def _budget_then_another_ingest(db_, tenant_id):
        budget = real_budget(db_, tenant_id)
        _seen(db, test_user.id, ["mid1", "mid2"])
        return budget

    with patch.object(document_cap_service, "sync_budget", side_effect=_budget_then_another_ingest):
        _run(job.id, ["c1", "c2", "c3"])

    assert _linked(db, job.id) == ["c1"]
    assert _visible(db, test_user.id) == 4
