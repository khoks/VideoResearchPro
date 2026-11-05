"""T-1.11.11.4 at the production callers: the ``snippet.defaultAudioLanguage`` that
``get_video_details`` already paid for reaches the document and the transcript
fetch, so the 1-unit lazy lookup is not needed.

Each job runs for real through the YouTube connector, ``get_video_details`` and
``fetch_transcript``; only the network is replaced: a fake Data API client that
counts its requests, and the player response served by ``FakeTranscriptApi``.
The shape is one whose non-dub tracks span two languages, because that is the
only shape the lazy lookup runs on.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents import search_agent
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.services import youtube_service
from app.sources.types import DEFAULT_AUDIO_LANGUAGE, Candidate
from app.sources.video.connector import YouTubeConnector
from app.tasks import job_tasks
from tests.caption_track_fixtures import SHAPES, FakeTranscriptApi

CHANNEL = "UCaudioLanguage1"
DECLARES_HINDI = SHAPES["hindi_audio_english_translation"]
DECLARES_NOTHING = SHAPES["hindi_audio_english_translation_undeclared"]


class _NoWait:
    def wait(self) -> None:
        return None


class _Request:
    def __init__(self, response: dict):
        self._response = response

    def execute(self) -> dict:
        return self._response


class FakeDataApi:
    """The ``videos.list`` a real client would answer, one record per request."""

    def __init__(self, shapes):
        self.shapes = {s.video_id: s for s in shapes}
        self.requests: list[dict] = []

    def videos(self):
        return self

    def list(self, **kwargs):
        self.requests.append(kwargs)
        items = []
        for vid in kwargs["id"].split(","):
            shape = self.shapes.get(vid)
            if shape is None:
                continue
            snippet = {
                "title": "Hindi lecture with an English translation",
                "channelTitle": "Lecture Channel", "channelId": CHANNEL,
                "publishedAt": "2025-02-01T00:00:00Z", "description": "",
                # Only the title's language; D-117 says it is never a speech signal.
                "defaultLanguage": "en",
            }
            if shape.declared:
                snippet["defaultAudioLanguage"] = shape.declared
            items.append({
                "id": vid, "snippet": snippet,
                "contentDetails": {"duration": "PT10M"}, "statistics": {},
            })
        return _Request({"items": items})

    @property
    def lookups(self) -> list[dict]:
        """The lazy lookup's own request: only its `fields` narrows the snippet."""
        return [r for r in self.requests if "fields" in r]

    @property
    def details_calls(self) -> list[dict]:
        return [r for r in self.requests if "fields" not in r]


@pytest.fixture
def network(monkeypatch):
    """Everything but the two networks is real. ``use(shape)`` picks a video."""
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setattr(youtube_service, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setattr(youtube_service, "transcript_limiter", _NoWait())
    monkeypatch.setattr(youtube_service, "transcript_breaker", youtube_service._TranscriptCircuitBreaker())
    monkeypatch.setattr(youtube_service, "_transcribe_with_whisper", lambda vid, job_id="": None)
    monkeypatch.setattr(youtube_service.quota_service, "record", lambda *a, **k: None)
    monkeypatch.setattr(job_tasks, "_ensure_era", lambda *a, **k: None)
    monkeypatch.setattr(youtube_service, "resolve_channel_id", lambda c, **kw: CHANNEL)
    monkeypatch.setattr(youtube_service, "get_channel_metadata", lambda c, **kw: {
        "channel_id": CHANNEL, "name": "Lecture Channel",
        "uploads_playlist_id": "UUaudioLanguage1", "subscriber_count": 10,
    })

    state = {}

    def use(shape):
        api = FakeDataApi([shape])
        transcripts = FakeTranscriptApi(shape.captions())
        monkeypatch.setattr(youtube_service, "get_youtube_client", lambda: api)
        monkeypatch.setattr(youtube_service, "_build_transcript_api", lambda: transcripts)
        monkeypatch.setattr(youtube_service, "get_channel_videos_all", lambda c, **kw: [shape.video_id])
        monkeypatch.setattr(youtube_service, "get_channel_videos", lambda c, **kw: [shape.video_id])
        state["shape"], state["api"], state["transcripts"] = shape, api, transcripts
        return state

    state["use"] = use
    return state


def _document(db, shape) -> Document:
    db.expire_all()
    return db.query(Document).filter(Document.video_id == shape.video_id).one()


def _metadata(doc: Document) -> dict:
    return json.loads(doc.source_metadata_json)


def _subscription_job(db) -> Job:
    job = Job(job_type="subscription", topic=None, num_videos=1,
              channel_list=f'["{CHANNEL}"]', tenant_id="tenant-audio-language")
    db.add(job)
    db.commit()
    return job


def _run_subscription(job_id: str) -> None:
    with patch.object(job_tasks, "chroma_service") as chroma, patch.object(job_tasks, "progress_service"):
        chroma.insert_chunks = MagicMock(return_value=1)
        job_tasks.execute_subscription_job.run(job_id)


def _resume(job_id: str) -> None:
    with (
        patch.object(job_tasks, "chroma_service") as chroma,
        patch.object(job_tasks, "progress_service"),
        patch("app.agents.report_agent.run_report_agent", return_value=({}, "<p>report</p>")),
        patch.object(job_tasks, "build_report_html", return_value="<html></html>"),
        patch.object(job_tasks, "save_report", return_value="report.html"),
    ):
        chroma.insert_chunks = MagicMock(return_value=1)
        job_tasks.resume_job_after_approval.run(job_id)


# --- execute_subscription_job ------------------------------------------------


def test_a_subscription_job_reads_the_language_from_the_details_it_fetched(network, db):
    state = network["use"](DECLARES_HINDI)

    _run_subscription(_subscription_job(db).id)

    doc = _document(db, DECLARES_HINDI)
    meta = _metadata(doc)
    assert meta[DEFAULT_AUDIO_LANGUAGE] == "hi"
    assert doc.transcript_language == "hi"
    assert meta["caption_track"]["spoken_language_source"] == "data_api"
    assert meta["caption_track"]["declared_audio_language"] == "hi"
    assert state["transcripts"].fetched == ["hi"]
    assert state["api"].lookups == [], "the details already said; no second videos.list"
    assert len(state["api"].details_calls) == 1


def test_a_video_that_declares_nothing_spares_the_lookup_too(network, db):
    """The key with None is the whole difference between knowing and not."""
    state = network["use"](DECLARES_NOTHING)

    _run_subscription(_subscription_job(db).id)

    doc = _document(db, DECLARES_NOTHING)
    meta = _metadata(doc)
    assert DEFAULT_AUDIO_LANGUAGE in meta and meta[DEFAULT_AUDIO_LANGUAGE] is None
    assert doc.transcript_language == "hi", "the recogniser's language decides, as D-117 says"
    assert meta["caption_track"]["spoken_language_source"] == "asr_track"
    assert state["api"].lookups == []


# --- resume_job_after_approval: the topic and channel path ---------------------


def test_a_channel_job_carries_the_language_from_listing_to_fetch(network, db):
    state = network["use"](DECLARES_HINDI)
    job = Job(job_type="channel", topic=None, num_videos=1, videos_per_channel=1,
              channel_list=f'["{CHANNEL}"]', tenant_id="tenant-audio-language")
    db.add(job)
    db.commit()

    with patch.object(job_tasks, "progress_service"):
        job_tasks.execute_channel_job.run(job.id)
    assert _metadata(_document(db, DECLARES_HINDI))[DEFAULT_AUDIO_LANGUAGE] == "hi"

    _resume(job.id)

    doc = _document(db, DECLARES_HINDI)
    assert doc.transcript_language == "hi"
    assert state["api"].lookups == []


def test_a_topic_job_carries_it_through_the_search_agent(network, db, monkeypatch):
    """`run_search_agent` for real, its two LLM calls and the search replaced."""
    state = network["use"](DECLARES_HINDI)
    shape = DECLARES_HINDI
    plan = MagicMock()
    plan.invoke.return_value.content = json.dumps({"broad_queries": ["q"], "channel_keywords": []})
    monkeypatch.setattr(search_agent, "get_llm_for", lambda *a, **k: plan)
    monkeypatch.setattr(youtube_service, "search_videos", lambda *a, **k: [{
        "video_id": shape.video_id, "title": "Lecture", "channel_name": "Lecture Channel",
        "channel_id": CHANNEL, "thumbnail_url": None, "published_at": "2025-02-01T00:00:00Z",
    }])
    monkeypatch.setattr(youtube_service, "get_channel_subscribers", lambda ids, **k: {})
    job = Job(job_type="topic", topic="lecture", num_videos=1, tenant_id="tenant-audio-language")
    db.add(job)
    db.commit()

    with patch.object(job_tasks, "progress_service"):
        job_tasks.execute_topic_job.run(job.id)
    db.expire_all()
    assert db.get(Job, job.id).status == "awaiting_approval"
    assert _metadata(_document(db, shape))[DEFAULT_AUDIO_LANGUAGE] == "hi"

    _resume(job.id)

    assert _document(db, shape).transcript_language == "hi"
    assert state["transcripts"].fetched == ["hi"]
    assert state["api"].lookups == []


def _approved_existing_document(db, shape, **kwargs) -> Job:
    doc = Document(video_id=shape.video_id, source_id=shape.video_id, title="Lecture",
                   url=f"https://www.youtube.com/watch?v={shape.video_id}", **kwargs)
    job = Job(job_type="channel", topic=None, num_videos=1, status="awaiting_approval",
              channel_list=f'["{CHANNEL}"]', tenant_id="tenant-audio-language")
    db.add_all([doc, job])
    db.flush()
    db.add(JobVideo(job_id=job.id, video_id=shape.video_id, document_id=doc.document_id, approved=True))
    db.commit()
    return job


def test_a_document_older_than_this_keeps_todays_lookup(network, db):
    """NULL metadata means nobody looked: the fetch asks, once, as it always did."""
    state = network["use"](DECLARES_HINDI)
    job = _approved_existing_document(db, DECLARES_HINDI)

    _resume(job.id)

    doc = _document(db, DECLARES_HINDI)
    assert doc.transcript_language == "hi"
    assert len(state["api"].lookups) == 1
    assert DEFAULT_AUDIO_LANGUAGE not in _metadata(doc), "the lookup does not write the document"


def test_a_stored_none_is_not_looked_up_on_the_approval_path(network, db):
    state = network["use"](DECLARES_NOTHING)
    job = _approved_existing_document(
        db, DECLARES_NOTHING, source_metadata_json=json.dumps({DEFAULT_AUDIO_LANGUAGE: None}),
    )

    _resume(job.id)

    assert _document(db, DECLARES_NOTHING).transcript_language == "hi"
    assert state["api"].lookups == []


def test_a_job_that_reads_details_fills_in_an_existing_document(network, db):
    """A document left pending or unavailable gains the language from the next
    job's details, and what it already holds stays."""
    state = network["use"](DECLARES_HINDI)
    doc = Document(video_id=DECLARES_HINDI.video_id, source_id=DECLARES_HINDI.video_id, title="Lecture",
                   url=f"https://www.youtube.com/watch?v={DECLARES_HINDI.video_id}",
                   transcript_status="unavailable",
                   source_metadata_json=json.dumps({"caption_track": {"language": "en"}}))
    job = Job(job_type="channel", topic=None, num_videos=1, videos_per_channel=1,
              channel_list=f'["{CHANNEL}"]', tenant_id="tenant-audio-language")
    db.add_all([doc, job])
    db.commit()

    with patch.object(job_tasks, "progress_service"):
        job_tasks.execute_channel_job.run(job.id)

    meta = _metadata(_document(db, DECLARES_HINDI))
    assert meta[DEFAULT_AUDIO_LANGUAGE] == "hi"
    assert meta["caption_track"] == {"language": "en"}
    assert state["api"].lookups == []


def test_a_listing_without_details_leaves_the_stored_language_alone(db):
    """No key in the row is not a claim that the video declares nothing."""
    job = Job(job_type="channel", topic=None, num_videos=1, tenant_id="tenant-audio-language")
    doc = Document(video_id="vidKEEP0001", source_id="vidKEEP0001", title="Kept",
                   url="https://www.youtube.com/watch?v=vidKEEP0001",
                   source_metadata_json=json.dumps({DEFAULT_AUDIO_LANGUAGE: "hi"}))
    db.add_all([job, doc])
    db.commit()

    job_tasks._upsert_video_and_link(db, job.id, {"video_id": "vidKEEP0001", "title": "Kept"})
    db.commit()

    db.expire_all()
    assert _metadata(db.get(Document, doc.document_id))[DEFAULT_AUDIO_LANGUAGE] == "hi"


def test_unreadable_metadata_reads_as_unknown_and_never_fails_the_job(network, db):
    """Bad JSON must cost a lookup at worst, never a failed job."""
    state = network["use"](DECLARES_HINDI)
    job = _approved_existing_document(db, DECLARES_HINDI, source_metadata_json="{not json")

    _resume(job.id)

    assert _document(db, DECLARES_HINDI).transcript_language == "hi"
    assert len(state["api"].lookups) == 1


# --- the connector, and the details dict ----------------------------------------


def _details_item(snippet_extra: dict) -> dict:
    return {"id": "abc", "snippet": {"title": "t", **snippet_extra}, "contentDetails": {}, "statistics": {}}


def test_get_video_details_reports_the_declared_language_or_none(monkeypatch):
    client = MagicMock()
    client.videos.return_value.list.return_value.execute.return_value = {
        "items": [_details_item({"defaultAudioLanguage": "hi", "defaultLanguage": "en"})],
    }
    monkeypatch.setattr(youtube_service, "get_youtube_client", lambda: client)
    monkeypatch.setattr(youtube_service.quota_service, "record", lambda *a, **k: None)
    assert youtube_service.get_video_details(["abc"])["abc"]["default_audio_language"] == "hi"

    client.videos.return_value.list.return_value.execute.return_value = {
        "items": [_details_item({"defaultLanguage": "en"})],
    }
    details = youtube_service.get_video_details(["abc"])["abc"]
    assert "default_audio_language" in details and details["default_audio_language"] is None, (
        "defaultLanguage is the title's language, never a speech signal (D-117)"
    )


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({DEFAULT_AUDIO_LANGUAGE: "hi"}, {"audio_language": "hi"}),
        ({DEFAULT_AUDIO_LANGUAGE: None}, {"audio_language": None}),
        ({}, {}),
    ],
)
def test_the_connector_passes_only_what_it_knows(extra, expected):
    with patch.object(youtube_service, "fetch_transcript", return_value=None) as fetch:
        YouTubeConnector().fetch_text(
            Candidate(source_type="video", source_id="abc", title="t", source_url="u", extra=extra)
        )
    kwargs = fetch.call_args.kwargs
    assert {k: v for k, v in kwargs.items() if k == "audio_language"} == expected
