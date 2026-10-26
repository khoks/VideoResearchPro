"""The document cap at every ingest entry point (T-5.2.10 / D-111).

``document_count_cap`` (Free 500, Pro 5,000, Studio unlimited) counts the
documents a tenant can SEE (``document_visibility``, D-063). Each test drives
the production caller — the router — and asserts both the refusal and that
nothing changed behind it. Most tests shrink the Free cap to a handful so the
arithmetic is visible; one uses the real 500 so the tier table is wired.

Mutation checks (run when this shipped; each made the named test fail):
deleting the ``enforce`` call in ``approve_job``
(``test_approval_over_the_cap_is_refused_whole``) or in ``upload_pdf``
(``test_pdf_upload_at_the_cap_is_refused_before_any_write``); deleting the
``_enforce_paste_cap`` call (``test_paste_batch_over_the_cap_is_refused_before_any_fetch``)
or counting a repeated URL twice
(``test_paste_counts_duplicates_once_and_skips_blank_and_visible``); deleting
any ``refuse_if_full`` call in the channels router or ``create_job``
(``test_subscribe_and_sync_at_the_cap_are_refused``,
``test_subscription_job_creation_at_the_cap_is_refused``); counting dedup
hits (``test_approval_of_documents_already_visible_is_not_counted``); ``<``
for ``<=`` (``test_approval_at_exactly_the_cap_boundary``); granting every
candidate again (``test_job_grants_only_approved_documents``); and reading
``documents`` usage from the counter table
(``test_quota_endpoint_reports_visible_documents``).
"""
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.models.channel import Channel
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services import subscription_service, visibility_service
from app.services.tier_service import TIER_CAPABILITIES, Tier
from app.sources.types import ExtractedText

OTHER_TENANT = "other-tenant-uuid"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def free_cap(monkeypatch):
    """Shrink the Free plan's cap for one test; returns the setter."""

    def _set(cap: int) -> None:
        monkeypatch.setitem(TIER_CAPABILITIES[Tier.FREE], "document_count_cap", cap)

    return _set


def _doc(db, key: str, **kw) -> Document:
    doc = Document(
        video_id=kw.pop("video_id", key[:20]),
        title=f"Doc {key}",
        url=f"https://www.youtube.com/watch?v={key}",
        **kw,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _seed_visible(db, tenant_id: str, n: int, prefix: str = "seen") -> list[Document]:
    """``n`` documents ``tenant_id`` already sees."""
    docs = [
        Document(
            video_id=f"{prefix}{i:05d}",
            title=f"Seen {i}",
            url=f"https://www.youtube.com/watch?v={prefix}{i:05d}",
        )
        for i in range(n)
    ]
    db.add_all(docs)
    db.commit()
    db.bulk_save_objects(
        [DocumentVisibility(document_id=d.document_id, tenant_id=tenant_id, source="job") for d in docs]
    )
    db.commit()
    return docs


def _visible(db, tenant_id: str) -> int:
    return db.query(DocumentVisibility).filter(DocumentVisibility.tenant_id == tenant_id).count()


def _awaiting_job(db, tenant_id: str, docs: list[Document]) -> Job:
    job = Job(job_type="topic", topic="t", status="awaiting_approval", tenant_id=tenant_id)
    db.add(job)
    db.commit()
    db.add_all(
        [
            JobVideo(job_id=job.id, document_id=d.document_id, video_id=d.video_id, approved=True)
            for d in docs
        ]
    )
    db.commit()
    db.refresh(job)
    return job


def _approve(client, job, docs):
    return client.put(
        f"/api/v1/jobs/{job.id}/approve",
        json={"approved_video_ids": [d.video_id for d in docs]},
    )


def _assert_cap_refusal(resp, *, consumed: int, limit: int, requested):
    assert resp.status_code == 429, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "quota_exceeded"
    assert detail["resource"] == "documents"
    assert detail["consumed"] == consumed
    assert detail["limit"] == limit
    assert detail["requested"] == requested
    assert detail["available"] == max(0, limit - consumed)
    assert detail["retry_at"] is None  # the cap is not periodic
    assert "Retry-After" not in resp.headers
    assert f"{limit:,}" in detail["message"]
    return detail


# ---------------------------------------------------------------------------
# Job approval
# ---------------------------------------------------------------------------


def test_approval_over_the_cap_is_refused_whole(client, db, test_user, free_cap):
    """Room for 2, approving 3 new documents: refused whole, and nothing
    about the job moves — no approval flags, no resume task, same status."""
    free_cap(5)
    _seed_visible(db, test_user.id, 3)
    candidates = [_doc(db, f"new{i}") for i in range(4)]
    job = _awaiting_job(db, test_user.id, candidates)
    with patch("app.routers.jobs.resume_job_after_approval") as resume:
        resp = _approve(client, job, candidates[:3])
    detail = _assert_cap_refusal(resp, consumed=3, limit=5, requested=3)
    assert "room for 2 more" in detail["message"]
    assert "Deselect at least 1" in detail["message"]
    resume.apply_async.assert_not_called()

    db.expire_all()
    job = db.get(Job, job.id)
    assert job.status == "awaiting_approval"
    # The deselected fourth candidate would read False had the approval applied.
    assert all(jv.approved for jv in job.job_videos)


def test_approval_that_fits_goes_through_and_deselected_candidates_do_not_count(
    client, db, test_user, free_cap
):
    """Room for 2 with 4 candidates: approving 2 fits. The 2 deselected ones
    are not counted (a check over every candidate would refuse this)."""
    free_cap(5)
    _seed_visible(db, test_user.id, 3)
    candidates = [_doc(db, f"fit{i}") for i in range(4)]
    job = _awaiting_job(db, test_user.id, candidates)
    resp = _approve(client, job, candidates[:2])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "extracting"


def test_approval_at_exactly_the_cap_boundary(client, db, test_user, free_cap):
    """visible + new == cap is allowed; one more is refused (off-by-one guard)."""
    free_cap(4)
    _seed_visible(db, test_user.id, 2)
    candidates = [_doc(db, f"edge{i}") for i in range(3)]

    over = _awaiting_job(db, test_user.id, candidates)
    _assert_cap_refusal(_approve(client, over, candidates), consumed=2, limit=4, requested=3)

    exact = _awaiting_job(db, test_user.id, candidates[:2])
    assert _approve(client, exact, candidates[:2]).status_code == 200


def test_approval_of_documents_already_visible_is_not_counted(client, db, test_user, free_cap):
    """At the cap, a run over documents the tenant already sees is a set of
    dedup hits: nothing new, so it is approved."""
    free_cap(3)
    seen = _seed_visible(db, test_user.id, 3)
    job = _awaiting_job(db, test_user.id, seen)
    resp = _approve(client, job, seen)
    assert resp.status_code == 200, resp.text


def test_approval_counts_documents_only_another_tenant_sees(client, db, test_user, free_cap):
    """A document in the shared cache that only someone else has ingested is
    new to this tenant, so it counts (D-063: shared cache, private catalogue)."""
    free_cap(1)
    _seed_visible(db, test_user.id, 1)
    theirs = _doc(db, "theirs1")
    visibility_service.grant(db, [theirs.document_id], OTHER_TENANT)
    job = _awaiting_job(db, test_user.id, [theirs])
    _assert_cap_refusal(_approve(client, job, [theirs]), consumed=1, limit=1, requested=1)


def test_free_cap_of_500_from_the_tier_table(client, db, test_user):
    """No patching: the real Free cap (500) applies."""
    _seed_visible(db, test_user.id, 500)
    new = _doc(db, "fiveHundred1")
    job = _awaiting_job(db, test_user.id, [new])
    detail = _assert_cap_refusal(_approve(client, job, [new]), consumed=500, limit=500, requested=1)
    assert "at the Free plan's cap of 500 documents" in detail["message"]
    assert "Documents already in your library stay." in detail["message"]


def test_over_the_cap_keeps_everything_but_cannot_add(client, db, test_user, free_cap):
    """A tenant already past the cap (a downgrade) is not trimmed: their
    library and its dedup hits still work; only new documents are refused."""
    free_cap(2)
    seen = _seed_visible(db, test_user.id, 4)
    listed = client.get("/api/v1/library/videos", params={"limit": 50}).json()
    assert len(listed) == 4

    ok = _awaiting_job(db, test_user.id, seen[:2])
    assert _approve(client, ok, seen[:2]).status_code == 200

    new = _doc(db, "overCap1")
    refused = _awaiting_job(db, test_user.id, [new])
    detail = _assert_cap_refusal(_approve(client, refused, [new]), consumed=4, limit=2, requested=1)
    assert "over the Free plan's cap of 2" in detail["message"]
    assert _visible(db, test_user.id) == 4


def test_studio_has_no_cap(client, db, test_user, free_cap):
    free_cap(0)
    test_user.tier = "studio"
    db.commit()
    _seed_visible(db, test_user.id, 6)
    candidates = [_doc(db, f"studio{i}") for i in range(3)]
    job = _awaiting_job(db, test_user.id, candidates)
    assert _approve(client, job, candidates).status_code == 200


def test_pro_cap_is_5000(db, test_user):
    from app.services import document_cap_service

    test_user.tier = "pro"
    db.commit()
    assert document_cap_service.cap_for(test_user) == 5000
    assert document_cap_service.headroom(db, test_user) == 5000


# ---------------------------------------------------------------------------
# Resume grants only what was approved
# ---------------------------------------------------------------------------


def test_job_grants_only_approved_documents(db, test_user):
    """The resume path grants the approved set, not every candidate. Before
    T-5.2.10 deselected candidates were granted too, which would charge the
    cap for documents the user rejected."""
    from app.tasks.job_tasks import _grant_job_document_visibility

    kept, dropped = _doc(db, "keptOne"), _doc(db, "droppedOne")
    job = Job(job_type="topic", topic="t", status="extracting", tenant_id=test_user.id)
    db.add(job)
    db.commit()
    db.add_all(
        [
            JobVideo(job_id=job.id, document_id=kept.document_id, video_id=kept.video_id, approved=True),
            JobVideo(job_id=job.id, document_id=dropped.document_id, video_id=dropped.video_id, approved=False),
        ]
    )
    db.commit()
    _grant_job_document_visibility(db, job)
    granted = {
        r[0]
        for r in db.query(DocumentVisibility.document_id).filter(
            DocumentVisibility.tenant_id == test_user.id
        )
    }
    assert granted == {kept.document_id}


# ---------------------------------------------------------------------------
# PDF upload
# ---------------------------------------------------------------------------


class _FakeConnector:
    def __init__(self, extracted):
        self._extracted = extracted
        self.calls = []

    def fetch_text(self, candidate, **_kw):
        self.calls.append(candidate)
        return self._extracted


def _pdf_text():
    return ExtractedText(
        segments=[{"text": "Page one.", "start": 0.0, "duration": 0.0,
                   "extra": {"kind": "page", "comment_url": "#page=1"}}],
        language="en",
        text_source="pdf",
        word_count=2,
        extra={"page_count": 1},
    )


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PDF_UPLOAD_DIR", str(tmp_path / "pdf"))
    return tmp_path / "pdf"


def _upload(client, payload=b"%PDF-1.4\n% cap test bytes\n"):
    connector = _FakeConnector(_pdf_text())
    with (
        patch("app.routers.library._connector_for", return_value=connector),
        patch("app.routers.library.chroma_service.insert_chunks"),
    ):
        resp = client.post(
            "/api/v1/library/upload-pdf",
            files={"file": ("paper.pdf", payload, "application/pdf")},
        )
    return resp, connector


def test_pdf_upload_at_the_cap_is_refused_before_any_write(client, db, test_user, free_cap, upload_dir):
    free_cap(2)
    _seed_visible(db, test_user.id, 2)
    resp, connector = _upload(client)
    detail = _assert_cap_refusal(resp, consumed=2, limit=2, requested=1)
    assert "This PDF is not in your library yet." in detail["message"]
    assert not connector.calls
    assert db.query(Document).filter(Document.source_type == "pdf").count() == 0
    assert not upload_dir.exists() or not any(upload_dir.iterdir())


def test_pdf_upload_under_the_cap_goes_through(client, db, test_user, free_cap, upload_dir):
    free_cap(2)
    _seed_visible(db, test_user.id, 1)
    resp, _ = _upload(client)
    assert resp.status_code == 201, resp.text
    assert _visible(db, test_user.id) == 2


def test_reuploading_a_visible_pdf_at_the_cap_is_a_dedup_hit(client, db, test_user, free_cap, upload_dir):
    free_cap(1)
    first, _ = _upload(client)
    assert first.status_code == 201
    again, _ = _upload(client)
    assert again.status_code == 201, again.text
    assert again.json()["deduped"] is True


def test_pdf_only_another_tenant_has_counts_as_new(client, db, test_user, free_cap, upload_dir):
    """Same bytes, already in the shared cache, but granted only to someone
    else: new to this tenant, so refused at the cap."""
    free_cap(1)
    first, _ = _upload(client)
    doc_id = first.json()["document_id"]
    db.query(DocumentVisibility).filter(DocumentVisibility.tenant_id == test_user.id).delete()
    db.commit()
    visibility_service.grant(db, [doc_id], OTHER_TENANT, visibility_service.SOURCE_PDF)
    _seed_visible(db, test_user.id, 1)

    resp, _ = _upload(client)
    _assert_cap_refusal(resp, consumed=1, limit=1, requested=1)


# ---------------------------------------------------------------------------
# Paste URLs
# ---------------------------------------------------------------------------


def _paste(client, urls):
    connector = _FakeConnector(
        ExtractedText(
            segments=[{"text": "A paragraph.", "start": 0.0, "duration": 0.0}],
            language="en",
            text_source="trafilatura",
            word_count=2,
            extra={"extracted_title": "T"},
        )
    )
    with (
        patch("app.routers.library._connector_for", return_value=connector),
        patch("app.routers.library.chroma_service.insert_chunks"),
    ):
        resp = client.post("/api/v1/library/paste-urls", json={"urls": urls})
    return resp, connector


def test_paste_batch_over_the_cap_is_refused_before_any_fetch(client, db, test_user, free_cap):
    free_cap(3)
    _seed_visible(db, test_user.id, 1)
    urls = [f"https://example.com/essay-{i}" for i in range(3)]
    resp, connector = _paste(client, urls)
    detail = _assert_cap_refusal(resp, consumed=1, limit=3, requested=3)
    assert "Paste at most 2 new links" in detail["message"]
    assert not connector.calls
    assert _visible(db, test_user.id) == 1


def test_paste_counts_duplicates_once_and_skips_blank_and_visible(client, db, test_user, free_cap):
    """Room for 1: a batch of one new URL (twice, once with a tracking
    parameter the dedup hash drops), a blank line and a page the tenant
    already sees adds one document, so it fits."""
    free_cap(2)
    first, _ = _paste(client, ["https://example.com/already-mine"])
    assert first.status_code == 201
    resp, _ = _paste(
        client,
        [
            "https://example.com/new-one",
            "https://example.com/new-one?utm_source=x",
            "   ",
            "https://example.com/already-mine",
        ],
    )
    assert resp.status_code == 201, resp.text
    statuses = sorted(r["status"] for r in resp.json()["results"])
    assert statuses == ["created", "deduped", "deduped", "invalid_url"]
    assert _visible(db, test_user.id) == 2


def test_paste_at_the_cap_still_accepts_visible_dedup_hits(client, db, test_user, free_cap):
    free_cap(1)
    assert _paste(client, ["https://example.com/mine"])[0].status_code == 201
    again, _ = _paste(client, ["https://example.com/mine"])
    assert again.status_code == 201
    assert again.json()["results"][0]["status"] == "deduped"


# ---------------------------------------------------------------------------
# Channel subscribe / sync, subscription jobs
# ---------------------------------------------------------------------------


def _channel(db, channel_id="UCcap1"):
    db.add(Channel(channel_id=channel_id, name="Cap Channel", uploads_playlist_id="UUcap1"))
    db.commit()


def test_subscribe_and_sync_at_the_cap_are_refused(client, db, test_user, free_cap):
    """A full library refuses both before anything changes: no subscription
    flip, no sync job."""
    free_cap(2)
    _seed_visible(db, test_user.id, 2)
    _channel(db)
    jobs_before = db.query(Job).count()
    with patch("app.tasks.job_tasks.execute_subscription_job") as task:
        sub = client.post("/api/v1/channels/UCcap1/subscribe")
        sync = client.post("/api/v1/channels/UCcap1/sync")
    for resp in (sub, sync):
        detail = _assert_cap_refusal(resp, consumed=2, limit=2, requested=None)
        assert "A sync cannot add anything new" in detail["message"]
    task.apply_async.assert_not_called()
    assert db.query(Job).count() == jobs_before
    assert subscription_service.get_or_create(db, "UCcap1", test_user.id).subscribed is False


def test_subscribe_and_sync_with_room_dispatch(client, db, test_user, free_cap):
    """One slot left is enough to start; the task stops at the cap."""
    free_cap(3)
    _seed_visible(db, test_user.id, 2)
    _channel(db)
    with patch("app.tasks.job_tasks.execute_subscription_job") as task:
        task.apply_async.return_value = MagicMock(id="t")
        assert client.post("/api/v1/channels/UCcap1/subscribe").status_code == 200
        assert client.post("/api/v1/channels/UCcap1/sync").status_code == 200
    assert task.apply_async.call_count == 2


def test_subscription_job_creation_at_the_cap_is_refused(client, db, test_user, free_cap):
    free_cap(1)
    _seed_visible(db, test_user.id, 1)
    resp = client.post("/api/v1/jobs", json={"job_type": "subscription", "channel_list": ["@foo"]})
    _assert_cap_refusal(resp, consumed=1, limit=1, requested=None)
    assert db.query(Job).count() == 0


def test_topic_job_creation_is_not_capped(client, db, test_user, free_cap):
    """A topic run may land on documents the tenant already has; its new ones
    are checked at approval, so creating it is never refused by the cap."""
    free_cap(1)
    _seed_visible(db, test_user.id, 1)
    resp = client.post("/api/v1/jobs", json={"job_type": "topic", "topic": "q", "num_videos": 5})
    assert resp.status_code == 201, resp.text


def test_studio_subscribe_with_a_large_library(client, db, test_user, free_cap):
    free_cap(0)
    test_user.tier = "studio"
    db.commit()
    _seed_visible(db, test_user.id, 3)
    _channel(db)
    with patch("app.tasks.job_tasks.execute_subscription_job") as task:
        task.apply_async.return_value = MagicMock(id="t")
        assert client.post("/api/v1/channels/UCcap1/subscribe").status_code == 200


# ---------------------------------------------------------------------------
# Usage, for the Subscription page
# ---------------------------------------------------------------------------


def test_quota_endpoint_reports_visible_documents(client, db, test_user):
    _seed_visible(db, test_user.id, 7)
    visibility_service.grant(db, [_doc(db, "notMine1").document_id], OTHER_TENANT)
    body = client.get("/api/v1/auth/quota").json()
    documents = {r["resource"]: r for r in body["resources"]}["documents"]
    assert documents["consumed"] == 7
    assert documents["limit"] == 500
    assert documents["over_limit"] is False
