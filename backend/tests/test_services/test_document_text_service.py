"""`document_text_service`: a document's full text from the right store.

The chunk-reassembly half is checked against the production chunker: chunk a
text with `chunk_transcript`, reassemble the chunks, and the result must be
the original sentences, once each, in order — for several chunk sizes and
overlaps, including chunks handed back out of order.
"""
from __future__ import annotations

import json
import random
from unittest.mock import patch

import pytest

from app.models.document import Document
from app.models.transcript_cache import TranscriptCache
from app.services import document_text_service as dts
from app.utils.chunking import chunk_transcript

SENTENCES = [
    f"Point {i} says the harbour wall {['rose', 'fell', 'held'][i % 3]} in year {1900 + i}."
    for i in range(1, 41)
]
ORIGINAL = " ".join(SENTENCES)


def _chunks(chunk_size: int, overlap: int, *, doc_id: str = "doc-1") -> list[dict]:
    segments = [{"text": s, "start": float(i), "duration": 1.0} for i, s in enumerate(SENTENCES)]
    out = chunk_transcript(
        segments,
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        video_metadata={"document_id": doc_id, "source_type": "pdf"},
        transcription_source="pdf",
    )
    return [
        {"id": f"{doc_id}:{c['metadata']['chunk_index']}", "text": c["text"], "metadata": c["metadata"]}
        for c in out
    ]


def _normalised(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Overlap de-duplication against the real chunker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("chunk_size,overlap", [(32, 8), (48, 16), (64, 32), (256, 32), (40, 0)])
def test_reassembled_chunks_are_the_original_text(chunk_size, overlap):
    chunks = _chunks(chunk_size, overlap)
    assert len(chunks) > 1 or chunk_size >= 256
    assert _normalised(dts.reassemble_chunks(chunks)) == ORIGINAL


def test_the_overlap_is_real_and_is_what_gets_removed():
    """Guard against a vacuous pass: the raw chunks DO repeat sentences."""
    chunks = _chunks(48, 16)
    joined_raw = " ".join(c["text"] for c in chunks)
    assert any(joined_raw.count(s) > 1 for s in SENTENCES)
    rebuilt = dts.reassemble_chunks(chunks)
    assert all(rebuilt.count(s) == 1 for s in SENTENCES)


def test_order_comes_from_chunk_index_not_from_chroma():
    """Chroma ids sort `:10` before `:2`; the result order must not care."""
    chunks = _chunks(32, 8)
    assert len(chunks) > 10
    shuffled = chunks[:]
    random.Random(7).shuffle(shuffled)
    by_id = sorted(chunks, key=lambda c: c["id"])  # lexicographic, like a store might
    assert _normalised(dts.reassemble_chunks(shuffled)) == ORIGINAL
    assert _normalised(dts.reassemble_chunks(by_id)) == ORIGINAL


def test_index_falls_back_to_the_chunk_id_suffix_and_repeats_are_read_once():
    chunks = _chunks(48, 16)
    no_meta = [{"id": c["id"], "text": c["text"], "metadata": {}} for c in chunks]
    doubled = no_meta + no_meta[:3]
    assert _normalised(dts.reassemble_chunks(doubled)) == ORIGINAL


def test_chunks_that_cannot_be_placed_are_skipped():
    chunks = _chunks(48, 16)
    stray = {"id": "no-index-here", "text": "STRAY TEXT", "metadata": {}}
    assert "STRAY TEXT" not in dts.reassemble_chunks([stray, *chunks])


def test_each_chunk_becomes_a_paragraph_for_the_splitter():
    chunks = _chunks(48, 16)
    assert dts.reassemble_chunks(chunks).count("\n\n") == len(chunks) - 1


def test_strip_overlap_keeps_the_rest_verbatim():
    prev = "Alpha beta. Gamma delta."
    cur = "Gamma delta. Epsilon\nzeta  eta."
    assert dts.strip_overlap(prev, cur) == "Epsilon\nzeta  eta."


def test_strip_overlap_without_a_shared_run_changes_nothing():
    assert dts.strip_overlap("One two three.", "Four five six.") == "Four five six."


def test_strip_overlap_takes_the_longest_shared_run():
    prev = "x y. a b. a b."
    cur = "a b. a b. c d."
    assert dts.strip_overlap(prev, cur) == "c d."


def test_strip_overlap_respects_its_bound():
    words = [f"w{i}" for i in range(200)]
    prev = " ".join(words)
    cur = " ".join(words[50:]) + " tail"
    # 150 shared words: past a 64-word bound nothing is stripped.
    assert dts.strip_overlap(prev, cur, max_words=64) == cur
    assert dts.strip_overlap(prev, cur, max_words=200) == "tail"


def test_a_chunk_entirely_inside_the_previous_one_adds_nothing():
    chunks = [
        {"id": "d:0", "text": "One. Two. Three.", "metadata": {"chunk_index": 0}},
        {"id": "d:1", "text": "Two. Three.", "metadata": {"chunk_index": 1}},
        {"id": "d:2", "text": "Three. Four.", "metadata": {"chunk_index": 2}},
    ]
    assert _normalised(dts.reassemble_chunks(chunks)) == "One. Two. Three. Four."


# ---------------------------------------------------------------------------
# Which store
# ---------------------------------------------------------------------------


def _pdf(db) -> Document:
    doc = Document(source_type="pdf", source_id="pdf:abc", title="Paper", url="/api/v1/library/pdf/abc.pdf")
    db.add(doc)
    db.commit()
    return doc


def test_transcript_cache_wins_and_is_keyed_on_document_id(db):
    """A cache row keyed on document_id with no video_id (what a non-video
    cache writer would store) is found — D-070, not the legacy column."""
    doc = _pdf(db)
    db.add(TranscriptCache(
        document_id=doc.document_id,
        video_id=None,
        segments_json=json.dumps([{"text": "Cached sentence one."}, {"text": "Cached two."}]),
        language="en",
    ))
    db.commit()
    with patch("app.services.chroma_service.get_document_chunks") as chunks:
        got = dts.full_text(db, doc)
    assert got.origin == dts.ORIGIN_TRANSCRIPT_CACHE
    assert got.text == "Cached sentence one. Cached two."
    assert not chunks.called, "the chunks are only read when the cache is empty"


def test_video_cache_row_still_found_by_its_youtube_id(db):
    video = Document(video_id="vidCache001", title="V", url="https://youtu.be/vidCache001")
    db.add(video)
    db.commit()
    db.add(TranscriptCache(
        video_id="vidCache001",
        segments_json=json.dumps([{"text": f"s{i}"} for i in range(25)]),
        language="en",
    ))
    db.commit()
    got = dts.full_text(db, video)
    assert got.origin == dts.ORIGIN_TRANSCRIPT_CACHE
    # Paragraphs of twenty segments, as the knowledge router always built them.
    assert got.text.split("\n\n") == [" ".join(f"s{i}" for i in range(20)), "s20 s21 s22 s23 s24"]


def test_without_a_cache_row_the_chunks_are_read_by_document_id(db):
    doc = _pdf(db)
    chunks = _chunks(48, 16, doc_id=doc.document_id)
    with patch("app.services.chroma_service.get_document_chunks", return_value=chunks) as get:
        got = dts.full_text(db, doc)
    get.assert_called_once_with(doc.document_id, None)
    assert got.origin == dts.ORIGIN_CHUNKS
    assert got.chunk_count == len(chunks)
    assert _normalised(got.text) == ORIGINAL


def test_nothing_anywhere_is_empty(db):
    doc = _pdf(db)
    with patch("app.services.chroma_service.get_document_chunks", return_value=[]):
        got = dts.full_text(db, doc)
    assert got.text == "" and got.origin == ""
