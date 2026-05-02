"""Integration tests for the multi-source orchestrator path.

S-1.5.11 wiring: ``execute_topic_job`` now reads ``Job.source_types_json``,
runs the YouTube search agent for ``video`` and the connector_dispatch
path for everything else (Reddit, HN, future Mastodon / Bluesky).

Strategy:
  - Patch ``connector_for(...)`` to return fakes that yield Candidates
    on ``search()`` and synthesised ``ExtractedText`` on ``fetch_text()``.
  - Patch ``run_search_agent`` for the YouTube branch.
  - Drive ``execute_topic_job`` and assert on the persisted Documents +
    JobVideo links + classification metadata.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.types import Candidate, ExtractedText
from app.tasks.job_tasks import (
    _dispatch_and_store_non_video_sources,
    _resolve_source_types,
    execute_topic_job,
)


# ---------------------------------------------------------------------------
# Fake connectors used by both the unit-level helper tests and the
# integration test for ``execute_topic_job``.
# ---------------------------------------------------------------------------
class _FakeRedditConnector(BaseConnector):
    source_type = "reddit_post"

    def __init__(self, candidates: list[Candidate]):
        self._candidates = candidates

    def search(self, query: str, instructions: str = "", limit: int = 10):
        return self._candidates[:limit]

    def list_creator_items(self, *args, **kwargs):  # pragma: no cover
        return []

    def fetch_metadata(self, *args, **kwargs):  # pragma: no cover
        return {}

    def fetch_text(self, candidate, *, job_id: str = "", query: str = ""):
        # Simulate inline classification per D-023.
        return ExtractedText(
            segments=[{"text": "OP body", "start": 0.0, "duration": 1.0}],
            language="en",
            text_source="reddit",
            word_count=2,
            extra={
                "classification": {
                    "stance": "for",
                    "sentiment": "positive",
                    "framing": "experiential",
                    "topic_relevance": 0.8,
                }
            },
        )


class _FakeHNConnector(BaseConnector):
    source_type = "hn_story"

    def __init__(self, candidates: list[Candidate]):
        self._candidates = candidates

    def search(self, query: str, instructions: str = "", limit: int = 10):
        return self._candidates[:limit]

    def list_creator_items(self, *args, **kwargs):  # pragma: no cover
        return []

    def fetch_metadata(self, *args, **kwargs):  # pragma: no cover
        return {}

    def fetch_text(self, candidate, *, job_id: str = "", query: str = ""):
        return ExtractedText(
            segments=[{"text": "Story body", "start": 0.0, "duration": 1.0}],
            language="en",
            text_source="hn",
            word_count=2,
            extra={
                "classification": {
                    "stance": "neutral",
                    "sentiment": "neutral",
                    "framing": "technical",
                    "topic_relevance": 0.6,
                }
            },
        )


@pytest.fixture
def clean_registry():
    """Snapshot + reset the connector registry; restore afterwards."""
    snapshot = registry.all_connectors()
    registry._reset_for_tests()
    yield
    registry._reset_for_tests()
    for c in snapshot.values():
        registry.register(c)


def _make_topic_job(db, source_types: list[str] | None = None, topic="tariffs") -> Job:
    job = Job(
        job_type="topic",
        topic=topic,
        status="pending",
        num_videos=5,
        source_types_json=(
            json.dumps(source_types) if source_types is not None else None
        ),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _reddit_cand(post_id: str, title: str = "Reddit OP") -> Candidate:
    return Candidate(
        source_type="reddit_post",
        source_id=f"reddit:{post_id}",
        title=title,
        source_url=f"https://www.reddit.com/r/test/comments/{post_id}",
    )


def _hn_cand(story_id: str, title: str = "HN story") -> Candidate:
    return Candidate(
        source_type="hn_story",
        source_id=f"hn:{story_id}",
        title=title,
        source_url=f"https://news.ycombinator.com/item?id={story_id}",
    )


# ---------------------------------------------------------------------------
# _resolve_source_types — defaulting + parsing
# ---------------------------------------------------------------------------
def test_resolve_source_types_defaults_to_video_when_null(db):
    job = _make_topic_job(db, source_types=None)
    assert _resolve_source_types(job) == ["video"]


def test_resolve_source_types_passes_through_video_only_explicit(db):
    job = _make_topic_job(db, source_types=["video"])
    assert _resolve_source_types(job) == ["video"]


def test_resolve_source_types_passes_through_mixed(db):
    job = _make_topic_job(
        db, source_types=["video", "reddit_post", "hn_story"]
    )
    assert _resolve_source_types(job) == [
        "video",
        "reddit_post",
        "hn_story",
    ]


def test_resolve_source_types_falls_back_on_malformed_json(db):
    job = Job(
        job_type="topic",
        topic="x",
        status="pending",
        num_videos=5,
        source_types_json="this is not json",
    )
    db.add(job)
    db.commit()
    assert _resolve_source_types(job) == ["video"]


def test_resolve_source_types_falls_back_on_empty_array(db):
    job = _make_topic_job(db, source_types=[])
    assert _resolve_source_types(job) == ["video"]


# ---------------------------------------------------------------------------
# _dispatch_and_store_non_video_sources — direct unit test
# ---------------------------------------------------------------------------
def test_dispatch_and_store_persists_reddit_candidates(db, clean_registry):
    fake = _FakeRedditConnector(
        [_reddit_cand("r1"), _reddit_cand("r2"), _reddit_cand("r3")]
    )
    registry.register(fake)

    job = _make_topic_job(db, source_types=["reddit_post"])

    stored = _dispatch_and_store_non_video_sources(
        db, job, source_types=["reddit_post"], limit_per_type=5
    )

    assert stored == 3
    docs = (
        db.query(Document)
        .filter(Document.source_type == "reddit_post")
        .all()
    )
    assert len(docs) == 3

    for doc in docs:
        # Classification persisted per D-023 + T-1.5.3.4.
        metadata = json.loads(doc.source_metadata_json)
        assert metadata["classification"]["stance"] == "for"
        # Transcript state recorded.
        assert doc.transcript_status == "fetched"
        assert doc.transcript_source == "reddit"

    links = db.query(JobVideo).filter(JobVideo.job_id == job.id).all()
    assert len(links) == 3


def test_dispatch_and_store_handles_mixed_source_types(db, clean_registry):
    registry.register(_FakeRedditConnector([_reddit_cand("r1"), _reddit_cand("r2")]))
    registry.register(_FakeHNConnector([_hn_cand("h1")]))

    job = _make_topic_job(db, source_types=["reddit_post", "hn_story"])

    stored = _dispatch_and_store_non_video_sources(
        db, job, source_types=["reddit_post", "hn_story"], limit_per_type=5
    )

    assert stored == 3
    by_type = {
        st: db.query(Document).filter(Document.source_type == st).count()
        for st in ("reddit_post", "hn_story")
    }
    assert by_type == {"reddit_post": 2, "hn_story": 1}


def test_dispatch_and_store_skips_video_in_source_types(db, clean_registry):
    """The non-video helper must ignore 'video' even if it appears in
    the source_types list — that path is owned by run_search_agent."""
    registry.register(_FakeRedditConnector([_reddit_cand("r1")]))

    job = _make_topic_job(db, source_types=["video", "reddit_post"])

    stored = _dispatch_and_store_non_video_sources(
        db, job, source_types=["video", "reddit_post"], limit_per_type=5
    )

    assert stored == 1
    docs = db.query(Document).all()
    assert len(docs) == 1
    assert docs[0].source_type == "reddit_post"


def test_dispatch_and_store_returns_zero_when_only_video(db, clean_registry):
    job = _make_topic_job(db, source_types=["video"])

    stored = _dispatch_and_store_non_video_sources(
        db, job, source_types=["video"], limit_per_type=5
    )

    assert stored == 0
    assert db.query(Document).count() == 0


# ---------------------------------------------------------------------------
# execute_topic_job — integration test (Reddit-only path)
# ---------------------------------------------------------------------------
def test_execute_topic_job_reddit_only_goes_through_dispatch_path(
    db, clean_registry, monkeypatch
):
    """A topic job with source_types=['reddit_post'] must NOT call the
    YouTube search agent at all and must persist Reddit candidates."""
    registry.register(_FakeRedditConnector([_reddit_cand("r1"), _reddit_cand("r2")]))

    job = _make_topic_job(db, source_types=["reddit_post"], topic="ai safety")

    # Patch SessionLocal so the Celery task uses our test DB.
    from app.tasks import job_tasks

    monkeypatch.setattr(job_tasks, "SessionLocal", lambda: db)

    # Patch run_search_agent so a stray video-path call would crash loudly.
    def _no_video_path(*args, **kwargs):  # pragma: no cover
        raise AssertionError("run_search_agent should not be called for Reddit-only jobs")

    monkeypatch.setattr(
        "app.agents.search_agent.run_search_agent",
        _no_video_path,
    )

    # Patch progress_service to no-op the WebSocket pubsub.
    from app.services import progress_service

    monkeypatch.setattr(progress_service, "publish_progress", lambda *a, **kw: None)
    monkeypatch.setattr(progress_service, "publish_status_change", lambda *a, **kw: None)

    # Drive the task synchronously by calling .run() with a stub `self`.
    class _StubSelf:
        class request:
            id = "stub-celery-id"

    execute_topic_job.run(job.id)

    # The Celery task closes its own session in `finally`. Re-query
    # the job in our test session rather than refreshing the stale
    # instance.
    persisted_job = db.query(Job).filter(Job.id == job.id).first()
    assert persisted_job is not None
    assert persisted_job.status == "awaiting_approval"

    docs = db.query(Document).filter(Document.source_type == "reddit_post").all()
    assert len(docs) == 2
    links = db.query(JobVideo).filter(JobVideo.job_id == job.id).all()
    assert len(links) == 2


def test_execute_topic_job_fails_clearly_when_all_sources_empty(
    db, clean_registry, monkeypatch
):
    """If every requested source returns zero candidates, the job goes
    to 'failed' with a helpful message rather than dropping the user
    onto an empty approval list."""
    registry.register(_FakeRedditConnector([]))  # No candidates.

    job = _make_topic_job(db, source_types=["reddit_post"], topic="obscure")

    from app.tasks import job_tasks

    monkeypatch.setattr(job_tasks, "SessionLocal", lambda: db)

    from app.services import progress_service

    monkeypatch.setattr(progress_service, "publish_progress", lambda *a, **kw: None)
    monkeypatch.setattr(progress_service, "publish_status_change", lambda *a, **kw: None)

    execute_topic_job.run(job.id)

    persisted_job = db.query(Job).filter(Job.id == job.id).first()
    assert persisted_job is not None
    assert persisted_job.status == "failed"
    assert "No candidates found" in (persisted_job.error_message or "")
