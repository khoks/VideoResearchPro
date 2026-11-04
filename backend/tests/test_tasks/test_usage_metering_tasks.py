"""Usage metering at the Celery callers (E-5.2, status plan item 10).

Celery work is charged to the job's owner (or the document request's, the
saved search's, the output's). Each test runs the task body with only the
network replaced: the provider client below ``get_llm_for``
(``metered_llms``) and the YouTube Data API client below
``youtube_service`` (``youtube_network``), so ``_execute_youtube_request``,
``quota_service.record`` and the install-wide ``api_quota_log`` all run.

Mutation check: with the task-level scope removed from ``job_tasks``, a
channel job's YouTube requests are charged to no one
(``test_mutation_a_channel_job_without_its_scope_charges_no_one``), so
``test_a_channel_job_charges_its_youtube_requests_to_the_owner`` fails.
"""
from __future__ import annotations

import json
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.api_quota_log import ApiQuotaLog
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.transcript_cache import TranscriptCache
from app.services import auth_service, youtube_service
from app.tasks import job_tasks
from tests.usage_helpers import call_llm, metered_llms, tenants_with_usage, usage_rows, youtube_network  # noqa: F401

CHANNEL = "UCusageMetering000000001"  # 24 characters: resolved without a request
assert len(CHANNEL) == 24


@pytest.fixture
def worker(monkeypatch, db):
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setattr(job_tasks, "progress_service", MagicMock())
    return db


def _owner(db, email=None):
    return auth_service.create_user(db, email=email or f"o-{uuid.uuid4().hex[:8]}@example.com", password="pw" * 6)


def _video_item(vid, minutes=10):
    return {
        "id": vid,
        "snippet": {"title": f"Video {vid}", "channelTitle": "Econ", "channelId": CHANNEL},
        "contentDetails": {"duration": f"PT{minutes}M"},
    }


def _channel_responses(video_ids):
    return {
        "channels": {"items": [{"id": CHANNEL, "contentDetails": {"relatedPlaylists": {"uploads": "UUusage"}},
                                "snippet": {"title": "Econ"}, "statistics": {"subscriberCount": "10"}}]},
        "playlistItems": {"items": [{"contentDetails": {"videoId": v}} for v in video_ids]},
        "videos": {"items": [_video_item(v) for v in video_ids]},
    }


# ---------------------------------------------------------------- topic search


def test_topic_search_charges_its_model_calls_and_youtube_search_to_the_owner(worker, db, metered_llms, youtube_network):
    owner = _owner(db)
    job = Job(job_type="topic", topic="tariffs", num_videos=1, tenant_id=owner.id)
    db.add(job)
    db.commit()
    youtube_network.responses = {"search": {"items": [{"id": {"videoId": "vS1"}, "snippet": {"title": "t", "channelTitle": "Econ", "channelId": CHANNEL}}]},
                                 "videos": {"items": [_video_item("vS1")]}}

    def search_agent(**kwargs):
        # What run_search_agent does: plan, search YouTube, read details, rank.
        call_llm("search_plan_queries")
        youtube_service.search_videos("tariffs who pays", max_results=5)
        details = youtube_service.get_video_details(["vS1"])
        call_llm("search_rank_and_curate")
        return [{**details["vS1"], "selection_reason": "relevant"}], ["tariffs who pays"], []

    with patch("app.agents.search_agent.run_search_agent", side_effect=search_agent):
        job_tasks.execute_topic_job.run(job.id)

    db.expire_all()
    assert db.get(Job, job.id).status == "awaiting_approval"
    assert usage_rows(db, owner.id) == {
        ("search", "llm_calls"): 2, ("search", "llm_tokens_in"): 200, ("search", "llm_tokens_out"): 40,
        ("search", "youtube_units"): 100, ("video_metadata", "youtube_units"): 1,
    }
    # The install-wide log keeps every request, as before.
    assert sorted(r.operation for r in db.query(ApiQuotaLog)) == ["search", "videos"]


# ---------------------------------------------------------------- channel job


def _channel_job(db, owner):
    job = Job(job_type="channel", num_videos=2, videos_per_channel=2, channel_list=json.dumps([CHANNEL]),
              tenant_id=owner.id)
    db.add(job)
    db.commit()
    return job


def test_a_channel_job_charges_its_youtube_requests_to_the_owner(worker, db, youtube_network):
    owner = _owner(db)
    job = _channel_job(db, owner)
    youtube_network.responses = _channel_responses(["vC1", "vC2"])

    job_tasks.execute_channel_job.run(job.id)

    db.expire_all()
    assert db.get(Job, job.id).status == "awaiting_approval"
    # channels.list + playlistItems.list for the uploads, videos.list for details.
    assert usage_rows(db, owner.id) == {("channel_sync", "youtube_units"): 2, ("video_metadata", "youtube_units"): 1}
    assert db.query(ApiQuotaLog).count() == 3
    assert tenants_with_usage(db) == {owner.id}


def test_mutation_a_channel_job_without_its_scope_charges_no_one(worker, db, youtube_network, monkeypatch):
    monkeypatch.setattr(job_tasks.usage_service, "metered", lambda *a, **k: nullcontext())
    owner = _owner(db)
    job = _channel_job(db, owner)
    youtube_network.responses = _channel_responses(["vC1", "vC2"])

    job_tasks.execute_channel_job.run(job.id)

    assert usage_rows(db, owner.id) == {}
    assert db.query(ApiQuotaLog).count() == 3, "the install-wide log does not depend on the scope"


# ---------------------------------------------------------------- subscription (channel sync)


def test_a_channel_sync_charges_its_youtube_requests_to_the_subscriber(worker, db, youtube_network, monkeypatch):
    owner = _owner(db)
    job = Job(job_type="subscription", num_videos=1, channel_list=json.dumps([CHANNEL]), tenant_id=owner.id)
    db.add(job)
    db.commit()
    youtube_network.responses = _channel_responses(["vSub1"])
    # Transcripts and Chroma are not this test's subject.
    monkeypatch.setattr(youtube_service, "fetch_transcript",
                        lambda vid, **kw: ([{"text": "hello", "start": 0.0, "duration": 1.0}], "en", "youtube"))
    monkeypatch.setattr(youtube_service, "get_default_audio_languages", lambda ids, job_id="": {})
    monkeypatch.setattr(job_tasks, "_ensure_era", lambda *a, **k: None)
    with patch.object(job_tasks, "chroma_service") as chroma:
        chroma.insert_chunks = MagicMock(return_value=1)
        job_tasks.execute_subscription_job.run(job.id)

    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    rows = usage_rows(db, owner.id)
    assert rows[("channel_sync", "youtube_units")] >= 2
    assert rows[("video_metadata", "youtube_units")] >= 1
    assert tenants_with_usage(db) == {owner.id}


# ---------------------------------------------------------------- report generation


def test_report_generation_charges_map_reduce_and_compose_to_the_owner(worker, db, metered_llms, monkeypatch):
    owner = _owner(db)
    doc = Document(video_id="vRep0000001", source_id="vRep0000001", title="Tariffs",
                   url="https://www.youtube.com/watch?v=vRep0000001", transcript_status="fetched")
    job = Job(job_type="topic", topic="tariffs", num_videos=1, status="awaiting_approval", tenant_id=owner.id)
    db.add_all([doc, job])
    db.flush()
    db.add(JobVideo(job_id=job.id, video_id=doc.video_id, document_id=doc.document_id, approved=True))
    db.add(TranscriptCache(video_id=doc.video_id, language="en", fetched_at=datetime.now(timezone.utc),
                           segments_json=json.dumps([{"text": "Tariffs are taxes on imports.", "start": 0.0, "duration": 3.0}])))
    db.commit()
    monkeypatch.setattr(job_tasks, "_ensure_era", lambda *a, **k: None)
    monkeypatch.setattr(youtube_service, "fetch_transcript",
                        lambda vid, **kw: ([{"text": "Tariffs are taxes on imports.", "start": 0.0, "duration": 3.0}], "en", "youtube"))
    monkeypatch.setattr(youtube_service, "get_default_audio_languages", lambda ids, job_id="": {})

    def report_agent(**kwargs):
        from concurrent.futures import ThreadPoolExecutor

        from app.agents.report_agent import _map_in_context

        # Map batches on a pool, as report_agent runs them, then reduce and compose.
        with ThreadPoolExecutor(max_workers=2) as pool:
            _map_in_context(pool, lambda i: call_llm("report_map_chunks", str(i)), range(3))
        call_llm("report_reduce_summaries")
        call_llm("report_compose")
        return {}, "<p>report</p>"

    with (
        patch.object(job_tasks, "chroma_service") as chroma,
        patch("app.agents.report_agent.run_report_agent", side_effect=report_agent),
        patch.object(job_tasks, "build_report_html", return_value="<html></html>"),
        patch.object(job_tasks, "save_report", return_value="report.html"),
    ):
        chroma.insert_chunks = MagicMock(return_value=1)
        job_tasks.resume_job_after_approval.run(job.id)

    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    assert usage_rows(db, owner.id) == {
        ("report", "llm_calls"): 5, ("report", "llm_tokens_in"): 500, ("report", "llm_tokens_out"): 100,
    }


# ---------------------------------------------------------------- visual (frame capture)


def test_frame_capture_is_charged_to_the_requester(db, metered_llms, monkeypatch):
    from app.tasks import visual_tasks
    from tests import conftest as _conftest

    monkeypatch.setattr(visual_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    requester = _owner(db)
    doc = Document(video_id="vVis0000001", source_id="vVis0000001", title="Charts", url="https://youtu.be/vVis0000001")
    db.add(doc)
    db.add(TranscriptCache(video_id=doc.video_id, language="en", fetched_at=datetime.now(timezone.utc),
                           segments_json=json.dumps([{"text": "Look at this chart.", "start": 0.0, "duration": 3.0}])))
    db.commit()

    def visual_agent(db_, **kwargs):
        call_llm("visual_select_moments")
        call_llm("visual_describe_frame")
        return [], 0

    with patch("app.agents.visual_agent.run_visual_agent", side_effect=visual_agent):
        visual_tasks.extract_frames.run(doc.document_id, requester.id)

    assert usage_rows(db, requester.id) == {
        ("visual", "llm_calls"): 2, ("visual", "llm_tokens_in"): 200, ("visual", "llm_tokens_out"): 40,
    }


# ---------------------------------------------------------------- saved search


def test_a_saved_search_run_is_charged_to_its_owner_as_a_saved_search(db, metered_llms, monkeypatch):
    from app.services import saved_search_service
    from app.tasks import saved_search_tasks
    from tests import conftest as _conftest

    monkeypatch.setattr(saved_search_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setattr(saved_search_service, "_encode", lambda texts: [[1.0, 0.0, 0.0] for _ in texts])
    monkeypatch.setattr("app.services.chroma_service.upsert_qa_exchange", lambda *a, **k: True)
    owner = _owner(db)
    owner.tier = "pro"
    db.commit()
    ss = saved_search_service.create(db, owner, question="Who pays for tariffs?", cadence={"cadence": "weekly", "hour": 9, "weekday": 0, "timezone": "Europe/London"})

    def agent(**kwargs):
        call_llm("qa_sub_query_expansion")
        call_llm("library_qa_formulate_answer")
        return {"answer": "Importers pay first.", "references": []}

    with patch("app.agents.qa_agent.run_library_qa_agent", side_effect=agent):
        out = saved_search_tasks.run_saved_search.run(ss.id, trigger="manual")

    assert out["status"] == "ok", out
    assert usage_rows(db, owner.id) == {
        ("saved_search", "llm_calls"): 2, ("saved_search", "llm_tokens_in"): 200, ("saved_search", "llm_tokens_out"): 40,
    }


# ---------------------------------------------------------------- Author Studio


def test_an_author_output_is_charged_to_its_owner(db, metered_llms, monkeypatch):
    from app.models.output import Output
    from app.services import output_service
    from app.services.outputters import book_cohesion
    from app.tasks import output_tasks
    from tests import conftest as _conftest

    class _DeckStandIn:
        kind = "deck"

        def generate(self, db_, user, output):
            # The outputters' production call path.
            book_cohesion._default_invoke("author_deck_outline", "system", "user", 500)
            output.content_text = "# Deck"

    monkeypatch.setattr(output_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setitem(output_service._OUTPUTTERS, "deck", _DeckStandIn())
    monkeypatch.setattr("app.services.progress_service.publish_progress", lambda *a, **k: None)
    monkeypatch.setattr("app.services.progress_service.publish_status_change", lambda *a, **k: None)
    owner = _owner(db)
    row = output_service.create_output(db, user_id=owner.id, kind="deck", title="Deck", source_ids=["j"])

    assert output_tasks.generate_output.run(row.id) == "completed"
    db.expire_all()
    assert db.get(Output, row.id).status == "completed"
    assert usage_rows(db, owner.id) == {
        ("author", "llm_calls"): 1, ("author", "llm_tokens_in"): 100, ("author", "llm_tokens_out"): 20,
    }


# ---------------------------------------------------------------- Echo learning


def test_an_echo_learning_run_is_charged_to_its_tenant(db, metered_llms, monkeypatch):
    from app.services import note_service
    from app.tasks import echo_tasks
    from tests import conftest as _conftest

    monkeypatch.setattr(echo_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    owner = _owner(db)
    owner.tier = "studio"
    db.add(Job(id=f"job-{owner.id[:8]}", tenant_id=owner.id, job_type="topic", topic="t", status="completed"))
    db.commit()
    for body in ("Base rates first, always. One source is not evidence.",
                 "I check who benefits before I believe a claim about trade."):
        note_service.create_note(db, owner.id, target_type="job", target_id=f"job-{owner.id[:8]}", body_md=body)
    metered_llms.reply = json.dumps({"signals": []})

    echo_tasks.extract_signals_task.run(owner.id)

    rows = usage_rows(db, owner.id)
    assert rows[("echo_signals", "llm_calls")] >= 1
    assert rows[("echo_signals", "llm_tokens_in")] == 100 * rows[("echo_signals", "llm_calls")]
    assert {f for f, _ in rows} == {"echo_signals"}
