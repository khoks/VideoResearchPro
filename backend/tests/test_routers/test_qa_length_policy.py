"""Router-level wiring for the Q&A length policy and temporal note (S-1.15.2).

These exist because of a specific failure: the agent accepted
`corpus_statistics` / `output_length` from 2026-07-31, and nothing passed
them until 2026-10-18. `corpus_bracket({})` is `small`, so every job answer
on the 200-video corpus got the small-corpus brief and never saw the
publication span — and no test noticed, because every test exercised the
agent, not its caller. These assert at the PRODUCTION CALLER.
"""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services import output_length, visibility_service


def _completed_job(db, tenant_id: str, length: str | None = None) -> Job:
    job = Job(
        job_type="topic", topic="t", status="completed", num_videos=3,
        tenant_id=tenant_id, output_length=length,
    )
    db.add(job)
    db.commit()
    return job


def _doc(vid: str, words: int, year: int) -> Document:
    return Document(
        document_id=vid,
        video_id=vid, title=f"Video {vid}", url=f"https://www.youtube.com/watch?v={vid}",
        transcript_word_count=words, published_at=datetime(year, 3, 1),
        discussed_era_json=json.dumps(
            {"era_start": year - 2, "era_end": year, "era_confidence": 0.7, "is_retrospective": False}
        ),
    )


def _seed_job_corpus(db, job: Job) -> None:
    # 3 approved documents of 200K words each: xlarge by words (>= 500K).
    db.add_all([_doc("a", 200_000, 2024), _doc("b", 200_000, 2025), _doc("c", 200_000, 2026),
                _doc("rejected", 200_000, 2020)])
    db.commit()
    db.add_all([
        JobVideo(job_id=job.id, video_id="a", approved=True, selection_reason="s"),
        JobVideo(job_id=job.id, video_id="b", approved=True, selection_reason="s"),
        JobVideo(job_id=job.id, video_id="c", approved=True, selection_reason="s"),
        JobVideo(job_id=job.id, video_id="rejected", approved=False, selection_reason="s"),
    ])
    db.commit()


# ---------- job Q&A ----------------------------------------------------------

def test_job_qa_passes_corpus_statistics_and_job_length(client, db, test_user):
    job = _completed_job(db, test_user.id, length="deep")
    _seed_job_corpus(db, job)

    with patch("app.agents.qa_agent.run_qa_agent", return_value=("answer", [])) as agent, \
         patch("app.routers.qa.chroma_service.upsert_qa_exchange", return_value=True):
        response = client.post(f"/api/v1/jobs/{job.id}/qa", json={"question": "tell me"})

    assert response.status_code == 200
    kwargs = agent.call_args.kwargs
    stats = kwargs["corpus_statistics"]
    assert stats["video_count"] == 3, "rejected documents must not count"
    assert stats["total_words"] == 600_000
    assert stats["earliest_published"] == "2024-03-01"
    assert stats["latest_published"] == "2026-03-01"
    assert stats["era_known_count"] == 3
    assert output_length.corpus_bracket(stats) == "xlarge"
    assert kwargs["output_length"] == "deep"


def test_job_qa_request_override_beats_job_setting(client, db, test_user):
    job = _completed_job(db, test_user.id, length="deep")
    _seed_job_corpus(db, job)
    with patch("app.agents.qa_agent.run_qa_agent", return_value=("answer", [])) as agent, \
         patch("app.routers.qa.chroma_service.upsert_qa_exchange", return_value=True):
        client.post(f"/api/v1/jobs/{job.id}/qa", json={"question": "tell me", "output_length": "brief"})
    assert agent.call_args.kwargs["output_length"] == "brief"


def test_job_qa_without_any_preference_passes_none(client, db, test_user):
    """NULL everywhere means the bracket decides — the policy must see None, not 'auto'."""
    job = _completed_job(db, test_user.id)
    _seed_job_corpus(db, job)
    with patch("app.agents.qa_agent.run_qa_agent", return_value=("answer", [])) as agent, \
         patch("app.routers.qa.chroma_service.upsert_qa_exchange", return_value=True):
        client.post(f"/api/v1/jobs/{job.id}/qa", json={"question": "tell me"})
    assert agent.call_args.kwargs["output_length"] is None


def test_job_qa_rejects_unknown_length_value(client, db, test_user):
    job = _completed_job(db, test_user.id)
    response = client.post(f"/api/v1/jobs/{job.id}/qa", json={"question": "tell me", "output_length": "huge"})
    assert response.status_code == 422


def test_job_qa_stream_passes_the_same_statistics(client, db, test_user):
    job = _completed_job(db, test_user.id, length="standard")
    _seed_job_corpus(db, job)
    with patch("app.agents.qa_agent.run_qa_agent", return_value=("answer", [])) as agent, \
         patch("app.routers.qa.chroma_service.upsert_qa_exchange", return_value=True):
        response = client.post(f"/api/v1/jobs/{job.id}/qa/stream", json={"question": "tell me"})
    assert response.status_code == 200
    kwargs = agent.call_args.kwargs
    assert kwargs["corpus_statistics"]["video_count"] == 3
    assert kwargs["output_length"] == "standard"


# ---------- library Q&A ------------------------------------------------------

def test_library_qa_passes_visible_corpus_statistics(client, db, test_user):
    db.add_all([_doc("v1", 100, 2024), _doc("v2", 300, 2026), _doc("hidden", 900, 2020)])
    db.commit()
    visibility_service.grant(db, ["v1", "v2"], test_user.id, source="job")
    db.commit()

    with patch("app.agents.qa_agent.run_library_qa_agent",
               return_value={"answer": "a", "references": []}) as agent, \
         patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True):
        response = client.post("/api/v1/library/qa", json={"question": "What is DNS?"})

    assert response.status_code == 200
    kwargs = agent.call_args.kwargs
    stats = kwargs["corpus_statistics"]
    assert stats["video_count"] == 2, "documents the tenant cannot see must not count"
    assert stats["total_words"] == 400
    assert stats["latest_published"] == "2026-03-01"
    assert kwargs["output_length"] is None


def test_library_qa_request_length_override(client, db, test_user):
    with patch("app.agents.qa_agent.run_library_qa_agent",
               return_value={"answer": "a", "references": []}) as agent, \
         patch("app.routers.library.chroma_service.upsert_qa_exchange", return_value=True):
        client.post("/api/v1/library/qa", json={"question": "What is DNS?", "output_length": "deep"})
    assert agent.call_args.kwargs["output_length"] == "deep"
    # A tenant with nothing ingested gets zero statistics — never a crash,
    # never a silent fallback to someone else's corpus.
    assert agent.call_args.kwargs["corpus_statistics"]["video_count"] == 0
