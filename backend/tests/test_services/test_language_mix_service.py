"""``language_mix_service`` (T-1.16.1.7): the stored profile is the chunker's.

The callers (job loops, the library routes, the backfill) are tested at
their own entry points; these pin the pieces they share: the stored profile
equals ``profile_transcript``, handing it to ``chunk_transcript`` changes
nothing about the chunks, re-recording an equal profile writes nothing, and
the backfill reads text from the stores in the documented order.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.document import Document
from app.models.transcript_cache import TranscriptCache
from app.services import code_mixing_service, language_mix_service
from app.services.visual_service import format_annotation
from app.utils.chunking import chunk_transcript

HINDI = "यह वक्ता के अपने शब्द हैं और व्याख्यान हिंदी में है"
HINGLISH = "yaar ye video bahut accha hai, maine socha ki main bhi try karunga taaki baadme koi kasar na reh jaye"
ENGLISH = "This is a plain English talk about tidal energy storage and how pumped storage works."


def _segments(text: str, n: int = 6) -> list[dict]:
    return [{"text": f"{text}.", "start": float(i * 3), "duration": 3.0} for i in range(n)]


@pytest.mark.parametrize("text", [HINDI, HINGLISH, ENGLISH])
def test_chunks_built_from_the_stored_profile_equal_chunks_that_profile_themselves(text):
    segments = _segments(text, n=30)
    meta = {"video_id": "vidLANG0001", "document_id": "doc-lang"}
    profile = language_mix_service.compute(segments)

    own = chunk_transcript(segments, chunk_size=64, chunk_overlap=8, video_metadata=meta)
    handed = chunk_transcript(
        segments, chunk_size=64, chunk_overlap=8, video_metadata=meta, language_profile=profile
    )
    assert len(own) > 1
    assert own == handed
    assert code_mixing_service.chunk_metadata_from_profile(profile) == (
        code_mixing_service.chunk_metadata_for_transcript(segments)
    )


def test_the_handed_profile_is_what_the_chunks_carry():
    """The chunker uses the profile it is handed rather than re-profiling the
    segments it chunks, which on a visual run include our English
    annotations; the job loops hand it the profile of the speech alone."""
    speech = _segments(HINDI, n=4)
    annotated = [*speech, {"text": format_annotation(9.0, "A slide reads Quarterly Revenue Growth " * 6),
                           "start": 9.0, "duration": 0.01, "extra": {"atomic": True, "kind": "visual"}}]
    profile = language_mix_service.compute(speech)

    chunks = chunk_transcript(annotated, video_metadata={"document_id": "d"}, language_profile=profile)

    expected = code_mixing_service.chunk_metadata_from_profile(profile)
    assert all({k: c["metadata"][k] for k in expected} == expected for c in chunks)
    assert expected["code_mix_share"] == 1.0
    # Re-profiled with the annotation, the share would have moved.
    assert code_mixing_service.chunk_metadata_for_transcript(annotated)["code_mix_share"] < 1.0


def test_record_writes_once_and_compares_parsed_profiles():
    doc = SimpleNamespace(language_mix=None, document_id="d1")
    profile = language_mix_service.compute(_segments(HINGLISH))

    assert language_mix_service.record(doc, profile) is True
    assert json.loads(doc.language_mix) == profile
    first = doc.language_mix
    assert language_mix_service.record(doc, dict(profile)) is False
    assert doc.language_mix == first

    # The same profile serialised another way (key order, ASCII escapes) is equal.
    doc.language_mix = json.dumps(profile, ensure_ascii=True)
    assert language_mix_service.record(doc, profile) is False

    assert language_mix_service.record(doc, None) is False


@pytest.mark.parametrize("raw", [None, "", "{not json", "[1, 2]", json.dumps({"hi_share": 0.4})])
def test_load_reads_a_missing_or_malformed_profile_as_none(raw):
    assert language_mix_service.load(SimpleNamespace(language_mix=raw)) is None


def test_ensure_is_fail_soft():
    doc = SimpleNamespace(language_mix=None, document_id="d1")
    with patch.object(language_mix_service, "compute", side_effect=RuntimeError("tagger broke")):
        assert language_mix_service.ensure(doc, _segments(HINDI)) is None
    assert doc.language_mix is None

    # A document that refuses the write still hands the profile to the chunker.
    class _ReadOnly(SimpleNamespace):
        def __setattr__(self, name, value):
            if name == "language_mix":
                raise RuntimeError("detached")
            super().__setattr__(name, value)

    stuck = _ReadOnly(language_mix=None, document_id="d2")
    assert language_mix_service.ensure(stuck, _segments(HINDI))["primary_language"] == "hi"


def test_public_view_carries_the_chunkers_decision():
    mixed = SimpleNamespace(language_mix=json.dumps(language_mix_service.compute(_segments(HINGLISH))))
    english = SimpleNamespace(language_mix=json.dumps(language_mix_service.compute(_segments(ENGLISH))))

    view = language_mix_service.public_view(mixed)
    assert set(view) == {*language_mix_service.PUBLIC_KEYS, "code_mixed"}
    assert view["primary_language"] == "hi" and view["code_mixed"] is True
    assert language_mix_service.public_view(english)["code_mixed"] is False
    assert language_mix_service.public_view(SimpleNamespace(language_mix=None)) is None


# --- stored_segments: where the backfill reads a document's text ------------


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


def test_stored_segments_prefers_the_transcript_cache(db):
    doc = Document(video_id="vidCACHE001", title="t", url="u")
    db.add(doc)
    db.flush()
    segments = _segments(HINDI, n=2)
    db.add(TranscriptCache(document_id=doc.document_id, video_id="vidCACHE001",
                           segments_json=json.dumps(segments), language="hi"))
    db.commit()

    assert language_mix_service.stored_segments(db, doc) == (segments, "transcript_cache")


def test_stored_segments_falls_back_to_the_legacy_video_id_key(db):
    owner = Document(video_id="vidLEGACY01", title="t", url="u")
    db.add(owner)
    db.flush()
    segments = _segments(HINGLISH, n=2)
    db.add(TranscriptCache(document_id=owner.document_id, video_id="vidLEGACY01",
                           segments_json=json.dumps(segments), language="en"))
    db.commit()
    # A row keyed on another document_id but the same YouTube id.
    reader = SimpleNamespace(document_id="some-other-id", video_id="vidLEGACY01")

    assert language_mix_service.stored_segments(db, reader) == (segments, "transcript_cache")


def test_stored_segments_reassembles_chunks_without_overlap_or_annotations(db, ephemeral_chroma):
    """A PDF keeps its text only in its chunks: reassembled in order, each
    overlap read once, and our `[VISUAL @ ...]` words dropped, so the profile
    measures the source and not the annotation's English."""
    doc = Document(source_type="pdf", source_id="pdf:abc", title="t", url="u")
    db.add(doc)
    db.commit()
    sentences = [f"{HINGLISH} number {i}." for i in range(12)]
    segments = [{"text": s, "start": float(i), "duration": 0.0} for i, s in enumerate(sentences)]
    segments.insert(3, {"text": format_annotation(3.0, "A slide reads Quarterly Revenue Growth"),
                        "start": 3.0, "duration": 0.01, "extra": {"atomic": True, "kind": "visual"}})
    chunks = chunk_transcript(segments, chunk_size=60, chunk_overlap=20,
                              video_metadata={"document_id": doc.document_id, "source_type": "pdf"})
    assert len(chunks) > 3
    assert any("Quarterly" in c["text"] for c in chunks), "the annotation must be in a chunk"
    ephemeral_chroma.insert_chunks(chunks)

    got, origin = language_mix_service.stored_segments(db, doc)

    assert origin == "chunks"
    text = " ".join(s["text"] for s in got)
    assert "VISUAL" not in text and "Quarterly" not in text
    for sentence in sentences:
        assert text.count(sentence) == 1


def test_stored_segments_without_any_text(db, ephemeral_chroma):
    doc = Document(source_type="pdf", source_id="pdf:none", title="t", url="u")
    db.add(doc)
    db.commit()
    assert language_mix_service.stored_segments(db, doc) == (None, "")
