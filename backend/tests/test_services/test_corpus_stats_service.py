"""`corpus_stats_service` — the figures Q&A's length policy reads (S-1.15.2)."""
from __future__ import annotations

import json
from datetime import datetime

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services import corpus_stats_service as css
from app.services import output_length, visibility_service


def _doc(vid: str, words: int, year: int | None, era: dict | None = None) -> Document:
    # document_id == video_id so the short ids below address the row under
    # both keys; grants and statistics are keyed on document_id (D-070).
    return Document(
        document_id=vid,
        video_id=vid,
        title=f"Video {vid}",
        url=f"https://www.youtube.com/watch?v={vid}",
        transcript_word_count=words,
        published_at=datetime(year, 6, 1) if year else None,
        discussed_era_json=json.dumps(era) if era else None,
    )


def test_empty_set_is_zero_statistics_and_small_bracket(db):
    stats = css.corpus_statistics_for_document_ids(db, [])
    assert stats["video_count"] == 0 and stats["total_words"] == 0
    assert stats["earliest_published"] is None
    assert output_length.corpus_bracket(stats) == "small"


def test_statistics_over_an_explicit_set(db):
    db.add_all([
        _doc("a", 100, 2024, {"era_start": 2019, "era_end": 2021, "era_confidence": 0.9, "is_retrospective": True}),
        _doc("b", 250, 2026),
        _doc("c", 50, None),
        _doc("ignored", 9999, 2020),
    ])
    db.commit()

    stats = css.corpus_statistics_for_document_ids(db, ["a", "b", "c", "a", "nope"])
    assert stats["video_count"] == 3
    assert stats["total_words"] == 400
    assert stats["earliest_published"] == "2024-06-01"
    assert stats["latest_published"] == "2026-06-01"
    assert stats["median_published"] == "2026-06-01"
    assert stats["videos_by_year"] == {"2026": 1, "2024": 1}
    assert stats["dated_video_count"] == 2
    assert stats["era_known_count"] == 1
    assert stats["discussed_era_start"] == 2019 and stats["discussed_era_end"] == 2021
    assert stats["retrospective_count"] == 1


def test_word_count_falls_back_for_non_video_sources(db):
    doc = Document(document_id="p", title="pdf", url="u", source_type="pdf", source_id="p", word_count=777)
    db.add(doc)
    db.commit()
    assert css.corpus_statistics_for_document_ids(db, ["p"])["total_words"] == 777


def test_job_statistics_use_only_approved_documents(db):
    job = Job(job_type="topic", topic="t", status="completed", num_videos=2)
    db.add(job)
    db.add_all([_doc("y", 300_000, 2025), _doc("n", 300_000, 2025), _doc("z", 300_000, 2026)])
    db.commit()
    db.add_all([
        JobVideo(job_id=job.id, video_id="y", approved=True, selection_reason="s"),
        JobVideo(job_id=job.id, video_id="z", approved=True, selection_reason="s"),
        JobVideo(job_id=job.id, video_id="n", approved=False, selection_reason="s"),
    ])
    db.commit()

    stats = css.corpus_statistics_for_job(db, job.id)
    assert stats["video_count"] == 2
    assert stats["total_words"] == 600_000
    # Words alone can promote the bracket — the policy keys off either axis.
    assert output_length.corpus_bracket(stats) == "xlarge"


def test_tenant_statistics_follow_visibility_grants(db, test_user):
    db.add_all([_doc("s1", 10, 2024), _doc("s2", 20, 2025), _doc("hidden", 30, 2026)])
    db.commit()
    visibility_service.grant(db, ["s1", "s2"], test_user.id, source="job")
    db.commit()

    stats = css.corpus_statistics_for_tenant(db, test_user.id)
    assert stats["video_count"] == 2
    assert stats["total_words"] == 30
    assert stats["latest_published"] == "2025-06-01"
