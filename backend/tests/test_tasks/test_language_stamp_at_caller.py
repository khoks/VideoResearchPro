"""T-1.16.2.16 at the production callers: a job that reuses an embedded document
gives its stored chunks the document-level ``code_mix_*`` fields they lack.

The reuse path re-chunks a document without re-inserting it, so a chunk written
before S-1.16.2 would otherwise wait for ``backfill_chunk_language_fields.py``.
These tests run ``resume_job_after_approval`` (topic and channel jobs) and
``execute_subscription_job`` for real, against an in-memory Chroma; only the
era model call, the report, the progress channel and the YouTube listing are
replaced.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.transcript_cache import TranscriptCache
from app.services import (
    chroma_service,
    language_mix_service,
    metadata_backfill_service,
    temporal_service,
    youtube_service,
)
from app.services.metadata_backfill_service import LANGUAGE_FIELDS, chunk_language_fields
from app.tasks import job_tasks
from app.utils.chunking import chunk_transcript

VIDEO_ID = "vidHINGLISH"
ENGLISH_ID = "vidENGLISH0"
CHANNEL = "UCstampChannel01"
HINGLISH = [
    {"text": f"yaar pehle dekho incentive kya hai aur phir baat karte hain, part {i}",
     "start": float(i * 5), "duration": 5.0}
    for i in range(8)
]
ENGLISH = [
    {"text": f"The railways reshaped the subcontinent and its trade routes, part {i}.",
     "start": float(i * 5), "duration": 5.0}
    for i in range(8)
]


def _strip_language_fields(chunks: list[dict]) -> None:
    for chunk in chunks:
        for name in [k for k in chunk["metadata"] if k.startswith("code_mix_")]:
            chunk["metadata"].pop(name)


def _embed(document: Document, segments: list[dict], *, written_before_s1162: bool = True) -> list[dict]:
    chunks = chunk_transcript(segments, chunk_size=40, chunk_overlap=8, video_metadata={
        "video_id": document.video_id, "document_id": document.document_id, "title": document.title,
    })
    if written_before_s1162:
        _strip_language_fields(chunks)
    chroma_service.insert_chunks(chunks)
    return chunks


def _stored(video_id: str = VIDEO_ID) -> list[dict]:
    got = chroma_service.get_global_collection().get(
        where={"video_id": video_id}, include=["metadatas", "documents", "embeddings"]
    )
    return [
        {"id": cid, "meta": m, "text": d, "embedding": [round(float(x), 6) for x in e]}
        for cid, m, d, e in zip(got["ids"], got["metadatas"], got["documents"], got["embeddings"])
    ]


def _library_document(db, video_id: str, segments: list[dict], title: str) -> Document:
    """A document already in the library: fetched, embedded, transcript cached."""
    doc = Document(video_id=video_id, source_id=video_id, title=title,
                   url=f"https://www.youtube.com/watch?v={video_id}",
                   transcript_status="fetched", embedded_in_chroma=True)
    db.add(doc)
    db.flush()
    db.add(TranscriptCache(document_id=doc.document_id, video_id=video_id,
                           segments_json=json.dumps(segments), language="hi", source="youtube"))
    db.commit()
    return doc


def _approved_job(db, doc: Document) -> Job:
    job = Job(job_type="channel", topic=None, num_videos=1, status="awaiting_approval",
              channel_list='["UCchannel"]', tenant_id="tenant-language-stamp")
    db.add(job)
    db.flush()
    db.add(JobVideo(job_id=job.id, video_id=doc.video_id, document_id=doc.document_id, approved=True))
    db.commit()
    return job


@pytest.fixture
def ephemeral_chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    yield chroma_service
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


@pytest.fixture
def library(db, monkeypatch, ephemeral_chroma):
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    doc = _library_document(db, VIDEO_ID, HINGLISH, "Incentives yaar")
    _embed(doc, HINGLISH)
    return doc


def _resume(job_id: str) -> None:
    with (
        patch.object(temporal_service, "extract_discussed_era", return_value=None),
        patch.object(job_tasks, "progress_service"),
        patch("app.agents.report_agent.run_report_agent", return_value=({}, "<p>report</p>")),
        patch.object(job_tasks, "build_report_html", return_value="<html></html>"),
        patch.object(job_tasks, "save_report", return_value="report.html"),
    ):
        job_tasks.resume_job_after_approval.run(job_id)


def _rerun(db, job: Job) -> None:
    db.expire_all()
    db.get(Job, job.id).status = "awaiting_approval"
    db.commit()
    _resume(job.id)


def _status(db, job_id: str) -> str:
    db.expire_all()
    return db.get(Job, job_id).status


def _expected_fields(db, doc: Document) -> dict:
    db.expire_all()
    profile = json.loads(db.get(Document, doc.document_id).language_mix)
    fields = chunk_language_fields(profile)
    assert fields["code_mix_primary"] == "hi", "the fixture must read as a Hindi source"
    return fields


def test_a_reused_document_gets_its_language_fields_on_its_stored_chunks(library, db):
    before = _stored()
    assert before and not any(k.startswith("code_mix_") for c in before for k in c["meta"])
    job = _approved_job(db, library)

    _resume(job.id)

    fields = _expected_fields(db, library)
    after = _stored()
    assert [c["id"] for c in after] == [c["id"] for c in before]
    for old, new in zip(before, after):
        assert {k: new["meta"].get(k) for k in fields} == fields
        # Metadata only: the same text, the same vector, every other key kept.
        assert new["text"] == old["text"] and new["embedding"] == old["embedding"]
        assert {k: new["meta"].get(k) for k in old["meta"]} == old["meta"]
        # Labelled, not rendered, and the per-chunk fields stay chunking's.
        assert "text_en" not in new["meta"]
        assert "code_mix_chunk_share" not in new["meta"]
    assert _status(db, job.id) == "completed"


def test_a_second_job_writes_nothing(library, db):
    job = _approved_job(db, library)
    _resume(job.id)
    settled = _stored()

    collection = chroma_service.get_global_collection()
    with patch.object(type(collection), "update", autospec=True) as update:
        _rerun(db, job)

    update.assert_not_called()
    assert _stored() == settled


def test_a_chunk_already_stamped_is_left_alone_even_with_another_value(library, db):
    """Only the owner's backfill rewrites a value: a job fills what is missing."""
    collection = chroma_service.get_global_collection()
    ids = sorted(c["id"] for c in _stored())
    stamped, bare = ids[0], ids[1:]
    assert bare, "the fixture needs more than one chunk"
    older = {"code_mix_primary": "hi", "code_mix_share": 0.11, "code_mix_quote": "roman"}
    collection.update(ids=[stamped], metadatas=[older])
    job = _approved_job(db, library)

    _resume(job.id)

    fields = _expected_fields(db, library)
    by_id = {c["id"]: c["meta"] for c in _stored()}
    assert {k: by_id[stamped].get(k) for k in older} == older
    assert "code_mix_matrix_share" not in by_id[stamped], "no field added to a stamped chunk"
    for chunk_id in bare:
        assert {k: by_id[chunk_id].get(k) for k in fields} == fields


def test_a_plain_english_document_costs_no_chroma_read(db, monkeypatch, ephemeral_chroma):
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    doc = _library_document(db, ENGLISH_ID, ENGLISH, "Railways")
    _embed(doc, ENGLISH)
    settled = _stored(ENGLISH_ID)
    job = _approved_job(db, doc)

    with patch.object(
        metadata_backfill_service, "_document_chunks", side_effect=AssertionError("read"),
    ) as read:
        _resume(job.id)

    read.assert_not_called()
    assert _stored(ENGLISH_ID) == settled
    assert _status(db, job.id) == "completed"


def test_a_chroma_read_error_never_fails_the_job(library, db):
    job = _approved_job(db, library)
    with patch.object(
        metadata_backfill_service, "_document_chunks", side_effect=RuntimeError("chroma went away"),
    ) as read:
        _resume(job.id)

    read.assert_called_once()
    assert _status(db, job.id) == "completed"


def test_a_chroma_write_error_never_fails_the_job_and_the_next_job_finishes(library, db):
    job = _approved_job(db, library)
    collection = chroma_service.get_global_collection()
    with patch.object(type(collection), "update", side_effect=RuntimeError("disk full")):
        _resume(job.id)

    assert _status(db, job.id) == "completed"
    assert not any("code_mix_primary" in c["meta"] for c in _stored())

    _rerun(db, job)

    fields = _expected_fields(db, library)
    assert all(c["meta"].get("code_mix_primary") == fields["code_mix_primary"] for c in _stored())


def test_a_chunk_older_than_document_id_is_found_by_its_video_id(library, db):
    collection = chroma_service.get_global_collection()
    ids = [c["id"] for c in _stored()]
    collection.update(ids=ids, metadatas=[{"document_id": None}] * len(ids))  # None drops the key
    assert not any("document_id" in c["meta"] for c in _stored())
    job = _approved_job(db, library)

    _resume(job.id)

    fields = _expected_fields(db, library)
    assert all(c["meta"].get("code_mix_primary") == fields["code_mix_primary"] for c in _stored())


def test_a_document_with_no_profile_has_nothing_to_stamp(library, db):
    job = _approved_job(db, library)
    with patch.object(language_mix_service, "compute", side_effect=RuntimeError("tagger")):
        _resume(job.id)

    assert _status(db, job.id) == "completed"
    assert not any(k.startswith("code_mix_") for c in _stored() for k in c["meta"])


def test_mutation_without_the_stamp_the_chunks_wait_for_the_script(library, db, monkeypatch):
    """Mutation check: take the call out of the reuse branch and the first test fails."""
    monkeypatch.setattr(job_tasks, "_stamp_language_on_reused_chunks", lambda video, job_id: None)
    job = _approved_job(db, library)

    _resume(job.id)

    assert not any(k.startswith("code_mix_") for c in _stored() for k in c["meta"])


def test_a_document_not_yet_embedded_is_inserted_with_its_fields_not_stamped(db, monkeypatch, ephemeral_chroma):
    """The stamp belongs to the reuse branch: a first embed writes the fields itself."""
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    doc = _library_document(db, VIDEO_ID, HINGLISH, "Incentives yaar")
    doc.embedded_in_chroma = False
    db.commit()
    job = _approved_job(db, doc)

    with patch.object(metadata_backfill_service, "stamp_chunk_language_fields") as stamp:
        _resume(job.id)

    stamp.assert_not_called()
    fields = _expected_fields(db, doc)
    stored = _stored()
    assert stored and all(c["meta"].get("code_mix_primary") == fields["code_mix_primary"] for c in stored)


# --- execute_subscription_job: the second reuse branch ----------------------


def test_a_subscription_job_stamps_a_reused_document_too(library, db, monkeypatch):
    job = Job(job_type="subscription", topic=None, num_videos=1,
              channel_list=f'["{CHANNEL}"]', tenant_id="tenant-language-stamp")
    db.add(job)
    db.commit()

    details = {VIDEO_ID: {"video_id": VIDEO_ID, "title": library.title, "channel_id": CHANNEL,
                          "channel_name": "Stamp Channel", "url": library.url,
                          "duration_seconds": 40, "thumbnail_url": None, "published_at": None}}
    monkeypatch.setattr(youtube_service, "resolve_channel_id", lambda c, **kw: CHANNEL)
    monkeypatch.setattr(youtube_service, "get_channel_metadata", lambda c, **kw: {
        "channel_id": CHANNEL, "name": "Stamp Channel",
        "uploads_playlist_id": "UUstampChannel01", "subscriber_count": 10,
    })
    monkeypatch.setattr(youtube_service, "get_channel_videos_all", lambda c, **kw: [VIDEO_ID])
    monkeypatch.setattr(youtube_service, "get_video_details", lambda ids, **kw: details)

    insert = MagicMock(return_value=0)
    with (
        patch.object(temporal_service, "extract_discussed_era", return_value=None),
        patch.object(job_tasks, "progress_service"),
        patch.object(job_tasks.chroma_service, "insert_chunks", insert),
    ):
        job_tasks.execute_subscription_job.run(job.id)

    assert _status(db, job.id) == "completed"
    fields = _expected_fields(db, library)
    stored = _stored()
    assert stored and all({k: c["meta"].get(k) for k in fields} == fields for c in stored)
    insert.assert_not_called()


def test_every_language_field_the_backfill_counts_can_be_stamped():
    """The stamp writes `chunk_language_fields`, which the backfill reports on."""
    profile = {"primary_language": "hi", "native_script": "Latin", "hi_share": 0.7,
               "matrix_hi_share": 0.8, "quote_mode": "roman", "named_share": 1.0}
    assert set(chunk_language_fields(profile)) == set(LANGUAGE_FIELDS)
