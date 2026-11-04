"""T-1.17.3.3 at the production caller: a job that reuses an embedded document
and extracts its era for the first time stamps the document's stored chunks.

The reuse path re-chunks a document without re-inserting it, so the chunks
built on that run never reach Chroma and the era would wait for the next
backfill. These tests run ``resume_job_after_approval`` for real, against an
in-memory Chroma holding chunks written before R3; only the era model call,
the report and the progress channel are replaced.
"""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.transcript_cache import TranscriptCache
from app.services import chroma_service, metadata_backfill_service, temporal_service
from app.services.metadata_backfill_service import TEMPORAL_FIELDS
from app.tasks import job_tasks
from app.utils.chunking import chunk_transcript

VIDEO_ID = "vidREUSED01"
ERA = {"era_start": 1947, "era_end": 1950, "era_confidence": 0.8, "is_retrospective": True,
       "extracted_at": "2026-11-04T00:00:00+00:00", "model": "m"}
SEGMENTS = [
    {"text": f"The partition reshaped the railways of the subcontinent, part {i}.",
     "start": float(i * 5), "duration": 5.0}
    for i in range(8)
]


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
def reused_job(db, monkeypatch, ephemeral_chroma):
    """A channel job whose user approved a document already in the library:
    fetched, embedded, no era yet, and its chunks predate R3."""
    from tests import conftest as _conftest

    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)

    doc = Document(video_id=VIDEO_ID, source_id=VIDEO_ID, title="Partition railways",
                   url=f"https://www.youtube.com/watch?v={VIDEO_ID}",
                   published_at=datetime(2024, 3, 12), transcript_status="fetched",
                   embedded_in_chroma=True)
    job = Job(job_type="channel", topic=None, num_videos=1, status="awaiting_approval",
              channel_list='["UCchannel"]', tenant_id="tenant-era-stamp")
    db.add_all([doc, job])
    db.flush()
    db.add(JobVideo(job_id=job.id, video_id=VIDEO_ID, document_id=doc.document_id, approved=True))
    db.add(TranscriptCache(document_id=doc.document_id, video_id=VIDEO_ID,
                           segments_json=json.dumps(SEGMENTS), language="en", source="youtube"))
    db.commit()

    chunks = chunk_transcript(SEGMENTS, chunk_size=40, chunk_overlap=8, video_metadata={
        "video_id": VIDEO_ID, "document_id": doc.document_id, "title": doc.title,
    })
    for chunk in chunks:
        for name in TEMPORAL_FIELDS:
            chunk["metadata"].pop(name, None)
    ephemeral_chroma.insert_chunks(chunks)
    return job


def _resume(job_id: str, *, era: dict | None = ERA) -> MagicMock:
    with (
        patch.object(temporal_service, "extract_discussed_era", return_value=era) as extract,
        patch.object(job_tasks, "progress_service"),
        patch("app.agents.report_agent.run_report_agent", return_value=({}, "<p>report</p>")),
        patch.object(job_tasks, "build_report_html", return_value="<html></html>"),
        patch.object(job_tasks, "save_report", return_value="report.html"),
    ):
        job_tasks.resume_job_after_approval.run(job_id)
    return extract


def _stored() -> list[dict]:
    got = chroma_service.get_global_collection().get(
        where={"video_id": VIDEO_ID}, include=["metadatas", "documents", "embeddings"]
    )
    return [
        {"id": cid, "meta": m, "text": d, "embedding": [round(float(x), 6) for x in e]}
        for cid, m, d, e in zip(got["ids"], got["metadatas"], got["documents"], got["embeddings"])
    ]


def _job_status(db, job_id: str) -> str:
    db.expire_all()
    return db.get(Job, job_id).status


def test_a_reused_document_gets_its_era_stamped_on_its_stored_chunks(reused_job, db):
    before = _stored()
    assert before and not any("era_start" in c["meta"] for c in before)

    _resume(reused_job.id)

    after = _stored()
    assert [c["id"] for c in after] == [c["id"] for c in before]
    for old, new in zip(before, after):
        assert new["meta"]["era_start"] == 1947 and new["meta"]["era_end"] == 1950
        assert new["meta"]["is_retrospective"] is True
        assert new["meta"]["published_year"] == 2024 and new["meta"]["published_ts"] > 0
        # Metadata only: the same text, the same vector, every other key kept.
        assert new["text"] == old["text"] and new["embedding"] == old["embedding"]
        kept = {k: v for k, v in old["meta"].items() if k != "published_at"}
        assert {k: new["meta"].get(k) for k in kept} == kept
    assert _job_status(db, reused_job.id) == "completed"


def test_a_second_job_changes_nothing_and_makes_no_call(reused_job, db):
    _resume(reused_job.id)
    settled = _stored()
    db.expire_all()
    job = db.get(Job, reused_job.id)
    job.status = "awaiting_approval"
    db.commit()

    with patch.object(metadata_backfill_service, "stamp_chunk_temporal_fields") as stamp:
        extract = _resume(reused_job.id)

    extract.assert_not_called()  # the era is on the document already
    stamp.assert_not_called()    # nothing was extracted, so nothing to stamp
    assert _stored() == settled


def test_a_chroma_error_never_fails_the_job(reused_job, db):
    """The era is enrichment, and the backfill script reaches the chunks later."""
    with patch.object(
        metadata_backfill_service, "stamp_chunk_temporal_fields",
        side_effect=RuntimeError("chroma went away"),
    ) as stamp:
        _resume(reused_job.id)

    stamp.assert_called_once()
    assert _job_status(db, reused_job.id) == "completed"
    db.expire_all()
    document = db.query(Document).filter(Document.video_id == VIDEO_ID).one()
    assert json.loads(document.discussed_era_json)["era_start"] == 1947  # the era is kept


def test_a_failed_chunk_read_never_fails_the_job(reused_job, db):
    """The same, through the real stamp: the read fails, the job does not."""
    class Broken:
        def get(self, **kw):
            raise RuntimeError("chroma went away")

    document = db.query(Document).filter(Document.video_id == VIDEO_ID).one()
    with patch.object(chroma_service, "get_global_collection", return_value=Broken()):
        job_tasks._stamp_era_on_embedded_chunks(document, "job-1")  # must not raise


def test_a_failed_era_extraction_stamps_nothing(reused_job, db):
    before = _stored()

    _resume(reused_job.id, era=None)

    assert not any("era_start" in c["meta"] for c in _stored())
    assert [c["id"] for c in _stored()] == [c["id"] for c in before]
    assert _job_status(db, reused_job.id) == "completed"


def test_a_document_not_embedded_yet_is_left_to_the_insert(db, ephemeral_chroma):
    """Its chunks are about to be inserted with the era on them; there is
    nothing stored to stamp."""
    document = Document(video_id="vidNEW00001", title="t", url="u", embedded_in_chroma=False)
    db.add(document)
    db.commit()

    with (
        patch.object(temporal_service, "extract_discussed_era", return_value=ERA),
        patch.object(metadata_backfill_service, "stamp_chunk_temporal_fields") as stamp,
    ):
        job_tasks._ensure_era(db, document, SEGMENTS, "job-1")

    stamp.assert_not_called()
    assert document.discussed_era_json


def test_chunks_written_before_the_document_id_stamp_are_found_by_video(db, ephemeral_chroma):
    document = Document(video_id="vidLEGACY02", title="t", url="u",
                        discussed_era_json=json.dumps(ERA))
    db.add(document)
    db.commit()
    chunks = chunk_transcript(SEGMENTS, chunk_size=40, chunk_overlap=8,
                              video_metadata={"video_id": "vidLEGACY02", "document_id": document.document_id})
    for chunk in chunks:
        for name in (*TEMPORAL_FIELDS, "document_id"):
            chunk["metadata"].pop(name, None)
    ephemeral_chroma.insert_chunks(chunks)

    updated = metadata_backfill_service.stamp_chunk_temporal_fields(document)

    assert updated == len(chunks)
    got = ephemeral_chroma.get_global_collection().get(where={"video_id": "vidLEGACY02"}, include=["metadatas"])
    assert all(m["era_start"] == 1947 for m in got["metadatas"])


def test_mutation_without_the_stamp_the_chunks_wait_for_the_backfill(reused_job, db):
    """Mutation check: drop the hook and the stored chunks keep no era, which
    is the gap T-1.17.3.3 closes."""
    with patch.object(job_tasks, "_stamp_era_on_embedded_chunks"):
        _resume(reused_job.id)
    assert not any("era_start" in c["meta"] for c in _stored())
