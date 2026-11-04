"""scripts/backfill_language_mix.py (T-1.16.1.7), run through its ``main``.

An in-memory database and an ephemeral Chroma collection hold the library
as it stands before T-1.16.1.7: documents chunked with no ``language_mix``.
The dry run computes and writes nothing; ``--write`` stores the profile from
the transcript cache, or from the chunks for a document whose text lives
nowhere else; a second run changes nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.models.document import Document
from app.models.transcript_cache import TranscriptCache
from app.services import code_mixing_service
from app.utils.chunking import chunk_transcript

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import backfill_language_mix as blm  # noqa: E402

HINDI = "यह वक्ता के अपने शब्द हैं और व्याख्यान हिंदी में है"
HINGLISH = [
    "yaar ye video bahut accha hai, maine socha ki main bhi try karunga.",
    "taaki baadme koi kasar koi zarra na reh jaye, sab kuch dhyan se dekhna.",
    "mujhe lagta hai ki ye tareeka sabke liye kaam karega agar aap mehnat karo.",
    "phir bhi kuch log kehte hain ki isme time bahut lagta hai aur paisa bhi.",
] * 3


@pytest.fixture
def ephemeral_chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    yield chroma_service
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


@pytest.fixture
def library(db, monkeypatch, ephemeral_chroma):
    from tests import conftest as _conftest

    monkeypatch.setattr(blm, "SessionLocal", _conftest.TestingSessionLocal)

    video = Document(video_id="vidHINDI001", title="Hindi lecture", url="u",
                     transcript_status="fetched", embedded_in_chroma=True)
    pdf = Document(source_type="pdf", source_id="pdf:hinglish", title="Hinglish notes", url="u",
                   transcript_status="fetched", embedded_in_chroma=True)
    empty = Document(video_id="vidNOTEXT01", title="No text anywhere", url="u",
                     transcript_status="fetched")
    candidate = Document(video_id="vidPENDING1", title="Search candidate", url="u",
                         transcript_status="pending")
    stale = Document(video_id="vidSTALE001", title="Re-fetched since", url="u",
                     transcript_status="fetched", embedded_in_chroma=True,
                     language_mix=json.dumps({"primary_language": "en", "quote_mode": "plain_english",
                                              "hi_share": 0.0}))
    db.add_all([video, pdf, empty, candidate, stale])
    db.flush()
    video_segments = [{"text": HINDI, "start": float(i), "duration": 1.0} for i in range(4)]
    stale_segments = [{"text": HINDI, "start": 0.0, "duration": 1.0}]
    db.add_all([
        TranscriptCache(document_id=video.document_id, video_id=video.video_id,
                        segments_json=json.dumps(video_segments), language="hi"),
        TranscriptCache(document_id=stale.document_id, video_id=stale.video_id,
                        segments_json=json.dumps(stale_segments), language="hi"),
    ])
    db.commit()

    # The PDF's text lives only in its chunks (chunked before the column).
    pdf_segments = [{"text": s, "start": float(i), "duration": 0.0} for i, s in enumerate(HINGLISH)]
    pdf_chunks = chunk_transcript(pdf_segments, chunk_size=48, chunk_overlap=16,
                                  video_metadata={"document_id": pdf.document_id, "source_type": "pdf"})
    assert len(pdf_chunks) > 2
    ephemeral_chroma.insert_chunks(pdf_chunks)
    return {
        "video": video.document_id, "pdf": pdf.document_id, "empty": empty.document_id,
        "candidate": candidate.document_id, "stale": stale.document_id,
        "video_segments": video_segments, "stale_segments": stale_segments,
        "pdf_segments": pdf_segments, "pdf_chunks": pdf_chunks,
    }


def _run(tmp_path, *args: str) -> tuple[int, dict]:
    out = tmp_path / f"report-{len(list(tmp_path.iterdir()))}.json"
    code = blm.main([*args, "--json", str(out), "--quiet"])
    return code, json.loads(out.read_text(encoding="utf-8"))


def _mix(db, document_id: str):
    db.expire_all()
    raw = db.get(Document, document_id).language_mix
    return json.loads(raw) if raw else None


def test_dry_run_reports_and_writes_nothing(db, library, tmp_path):
    code, report = _run(tmp_path)

    assert code == 0
    assert report["write"] is False
    # The pending candidate holds no text; the already-profiled row is skipped.
    assert report["considered"] == 3
    assert report["profiled"] == 2 and report["no_text"] == 1
    assert report["changed"] == 2
    assert report["by_origin"] == {"transcript_cache": 1, "chunks": 1}
    assert report["by_primary"] == {"hi": 2}
    assert report["code_mixed"] == 2
    for key in ("video", "pdf", "empty", "candidate"):
        assert _mix(db, library[key]) is None


def test_write_stores_the_profile_and_a_second_run_changes_nothing(db, library, tmp_path):
    code, report = _run(tmp_path, "--write")
    assert code == 0 and report["changed"] == 2

    # From the transcript cache: exactly the profile chunking computes.
    assert _mix(db, library["video"]) == code_mixing_service.profile_transcript(library["video_segments"])
    # From the chunks: the same reading of the source as at chunk time.
    pdf_mix = _mix(db, library["pdf"])
    at_chunk_time = code_mixing_service.profile_transcript(library["pdf_segments"])
    for key in ("primary_language", "native_script", "quote_mode"):
        assert pdf_mix[key] == at_chunk_time[key]
    assert abs(pdf_mix["hi_share"] - at_chunk_time["hi_share"]) < 0.05
    # ...so the stored profile tells a page what the chunks already tell the models.
    on_chunks = library["pdf_chunks"][0]["metadata"]
    from_profile = code_mixing_service.chunk_metadata_from_profile(pdf_mix)
    for key in ("code_mix_primary", "code_mix_script", "code_mix_quote"):
        assert from_profile[key] == on_chunks[key]
    assert _mix(db, library["empty"]) is None
    assert _mix(db, library["candidate"]) is None

    # Idempotent and resumable: only the document with no text is left.
    code, again = _run(tmp_path, "--write")
    assert code == 0
    assert again["considered"] == 1 and again["no_text"] == 1 and again["changed"] == 0


def test_all_re_profiles_and_corrects_a_stale_profile(db, library, tmp_path):
    _run(tmp_path, "--write")
    code, report = _run(tmp_path, "--write", "--all")

    assert code == 0
    assert report["considered"] == 4
    assert report["changed"] == 1 and report["unchanged"] == 2
    assert _mix(db, library["stale"]) == code_mixing_service.profile_transcript(library["stale_segments"])

    code, again = _run(tmp_path, "--write", "--all")
    assert again["changed"] == 0 and again["unchanged"] == 3


def test_document_ids_limit_the_pass(db, library, tmp_path):
    code, report = _run(tmp_path, "--write", "--document-ids", library["pdf"])
    assert report["considered"] == 1 and report["changed"] == 1
    assert _mix(db, library["pdf"]) is not None
    assert _mix(db, library["video"]) is None


def test_a_failing_document_is_counted_and_the_rest_are_written(db, library, tmp_path, monkeypatch):
    from app.services import language_mix_service

    real = language_mix_service.stored_segments

    def flaky(session, document):
        if document.document_id == library["video"]:
            raise RuntimeError("corrupt row")
        return real(session, document)

    monkeypatch.setattr(language_mix_service, "stored_segments", flaky)
    code, report = _run(tmp_path, "--write")

    assert code == 1
    assert report["failed"] == 1 and report["changed"] == 1
    assert _mix(db, library["video"]) is None
    assert _mix(db, library["pdf"]) is not None
