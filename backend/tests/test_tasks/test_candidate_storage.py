"""Unit tests for ``_upsert_candidate_and_link`` — T-1.5.1.4 + T-1.5.2.5 + T-1.5.3.4.

Covers Document + JobVideo persistence from a connector ``Candidate``
with optional classification + extracted-text payload. The function
generalizes the YouTube-shaped ``_upsert_video_and_link`` to handle
any ``source_type`` (e.g. ``reddit_post``, ``hn_story``).

Strategy: drive the function against an in-memory SQLite session
with the new schema (E-1.10 applied), inspect resulting rows.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.sources.types import Candidate
from app.tasks.job_tasks import _upsert_candidate_and_link


def _make_job(db, *, job_type: str = "topic", topic: str = "Test topic") -> Job:
    job = Job(job_type=job_type, topic=topic, status="searching")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _reddit_candidate(post_id: str = "abc123", title: str = "Reddit OP title") -> Candidate:
    return Candidate(
        source_type="reddit_post",
        source_id=f"reddit:{post_id}",
        title=title,
        source_url=f"https://www.reddit.com/r/test/comments/{post_id}",
        creator_external_id="r/test",
        creator_name="r/test",
        published_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        description="OP body excerpt",
    )


def _hn_candidate(story_id: str = "42000000", title: str = "HN story title") -> Candidate:
    return Candidate(
        source_type="hn_story",
        source_id=f"hn:{story_id}",
        title=title,
        source_url=f"https://news.ycombinator.com/item?id={story_id}",
        creator_external_id="hnuser",
        creator_name="hnuser",
        published_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )


def _classification(stance: str = "for", topic_relevance: float = 0.85) -> dict:
    return {
        "stance": stance,
        "sentiment": "positive",
        "framing": "experiential",
        "topic_relevance": topic_relevance,
    }


# ---------------------------------------------------------------------------
# Reddit happy path (T-1.5.1.4)
# ---------------------------------------------------------------------------
def test_upsert_inserts_reddit_document(db):
    job = _make_job(db)
    cand = _reddit_candidate()

    doc = _upsert_candidate_and_link(db, job.id, cand)
    db.commit()

    assert doc is not None
    assert doc.source_type == "reddit_post"
    assert doc.source_id == "reddit:abc123"
    assert doc.video_id is None  # not a video → NULL back-compat column
    assert doc.title == "Reddit OP title"
    assert doc.source_url == cand.source_url
    assert doc.url == cand.source_url
    assert doc.transcript_status == "pending"
    assert doc.source_metadata_json is None  # no classification provided

    # JobVideo link populated correctly.
    link = db.query(JobVideo).filter(JobVideo.job_id == job.id).first()
    assert link is not None
    assert link.document_id == doc.document_id
    assert link.video_id is None  # back-compat column NULL for non-video
    assert link.approved is True


def test_upsert_inserts_hn_document(db):
    """T-1.5.2.5 — same shape as Reddit, different source_type."""
    job = _make_job(db)
    cand = _hn_candidate()

    doc = _upsert_candidate_and_link(db, job.id, cand)
    db.commit()

    assert doc is not None
    assert doc.source_type == "hn_story"
    assert doc.source_id == "hn:42000000"
    assert doc.video_id is None
    assert doc.title == "HN story title"


# ---------------------------------------------------------------------------
# Idempotency on (source_type, source_id)
# ---------------------------------------------------------------------------
def test_upsert_dedupes_on_source_type_source_id(db):
    job = _make_job(db)
    cand = _reddit_candidate()

    _upsert_candidate_and_link(db, job.id, cand)
    db.commit()

    # Re-running with the same Candidate should NOT create a duplicate
    # Document or duplicate JobVideo link.
    cand2 = _reddit_candidate()
    cand2.title = "Updated Reddit title"
    _upsert_candidate_and_link(db, job.id, cand2)
    db.commit()

    documents = (
        db.query(Document)
        .filter(
            Document.source_type == "reddit_post",
            Document.source_id == "reddit:abc123",
        )
        .all()
    )
    assert len(documents) == 1
    assert documents[0].title == "Updated Reddit title"  # surface refreshed

    links = db.query(JobVideo).filter(JobVideo.job_id == job.id).all()
    assert len(links) == 1


def test_upsert_separate_jobs_share_document(db):
    """Two jobs that find the same Reddit post share one Document row
    and produce two JobVideo links."""
    job_a = _make_job(db)
    job_b = _make_job(db)
    cand = _reddit_candidate()

    _upsert_candidate_and_link(db, job_a.id, cand)
    _upsert_candidate_and_link(db, job_b.id, cand)
    db.commit()

    docs = db.query(Document).all()
    assert len(docs) == 1

    links = db.query(JobVideo).all()
    assert len(links) == 2
    assert {link.job_id for link in links} == {job_a.id, job_b.id}


# ---------------------------------------------------------------------------
# Classification persistence (T-1.5.3.4)
# ---------------------------------------------------------------------------
def test_upsert_persists_classification_into_source_metadata(db):
    job = _make_job(db)
    cand = _reddit_candidate()
    classification = _classification()

    doc = _upsert_candidate_and_link(
        db, job.id, cand, classification=classification
    )
    db.commit()

    assert doc.source_metadata_json is not None
    metadata = json.loads(doc.source_metadata_json)
    assert metadata["classification"] == classification


def test_upsert_overrides_classification_on_re_upsert(db):
    """Re-running classification on the same candidate updates source_metadata."""
    job = _make_job(db)
    cand = _reddit_candidate()

    _upsert_candidate_and_link(
        db, job.id, cand, classification=_classification(stance="against", topic_relevance=0.4)
    )
    db.commit()

    _upsert_candidate_and_link(
        db, job.id, cand, classification=_classification(stance="for", topic_relevance=0.9)
    )
    db.commit()

    docs = db.query(Document).all()
    assert len(docs) == 1
    metadata = json.loads(docs[0].source_metadata_json)
    assert metadata["classification"]["stance"] == "for"
    assert metadata["classification"]["topic_relevance"] == 0.9


def test_upsert_preserves_other_metadata_keys(db):
    """When classification updates, other source_metadata keys (set by
    future per-source enrichment) survive untouched."""
    job = _make_job(db)
    cand = _reddit_candidate()

    # Seed with an existing document carrying unrelated metadata.
    seeded = Document(
        source_type="reddit_post",
        source_id="reddit:abc123",
        title="seed",
        url="https://example",
        source_url="https://example",
        source_metadata_json=json.dumps({"reddit_specific": {"score": 100}}),
    )
    db.add(seeded)
    db.commit()

    # Now upsert with classification — should merge, not replace.
    _upsert_candidate_and_link(
        db, job.id, cand, classification=_classification()
    )
    db.commit()

    docs = (
        db.query(Document)
        .filter(Document.source_id == "reddit:abc123")
        .all()
    )
    assert len(docs) == 1
    metadata = json.loads(docs[0].source_metadata_json)
    assert metadata["reddit_specific"]["score"] == 100  # preserved
    assert metadata["classification"]["stance"] == "for"  # added


# ---------------------------------------------------------------------------
# ExtractedText persistence
# ---------------------------------------------------------------------------
def test_upsert_records_extracted_text_state(db):
    """When extracted_text is provided, document goes to fetched + records
    word count, language, source."""
    job = _make_job(db)
    cand = _reddit_candidate()

    class _FakeExtractedText:
        word_count = 1234
        language = "en"
        text_source = "reddit"

    doc = _upsert_candidate_and_link(
        db, job.id, cand, extracted_text=_FakeExtractedText()
    )
    db.commit()

    assert doc.transcript_status == "fetched"
    assert doc.transcript_word_count == 1234
    assert doc.transcript_language == "en"
    assert doc.transcript_source == "reddit"


# ---------------------------------------------------------------------------
# Defensive guards
# ---------------------------------------------------------------------------
def test_upsert_returns_none_when_source_id_is_empty(db):
    job = _make_job(db)
    cand = Candidate(
        source_type="reddit_post",
        source_id="",
        title="No source_id",
        source_url="https://example",
    )

    result = _upsert_candidate_and_link(db, job.id, cand)
    assert result is None
    assert db.query(Document).count() == 0
    assert db.query(JobVideo).count() == 0
