"""scripts/backfill_chunk_language_fields.py (T-1.16.2.14), run through its ``main``.

The ephemeral collection holds chunks as they were written before S-1.16.2:
the production chunker's output with every ``code_mix_*`` field removed. The
pass must add exactly the document-level fields the chunker writes today, from
the stored ``documents.language_mix``, keep every other key, the stored text
and the embedding, compute nothing, call no LLM, and find nothing to do the
second time.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.document import Document
from app.services import code_mixing_service, language_mix_service, metadata_backfill_service
from app.services.metadata_backfill_service import LANGUAGE_FIELDS
from app.utils.chunking import chunk_transcript

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import backfill_chunk_language_fields as bcl  # noqa: E402

HINDI = "यह वक्ता के अपने शब्द हैं और व्याख्यान हिंदी में है"
SPANISH = "el perro de mi hermana come en la cocina todos los dias porque tiene mucha hambre siempre"
ENGLISH = "Tidal energy storage holds water behind a barrage and releases it later."


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


def _segments(text: str, n: int) -> list[dict]:
    return [{"text": f"{text} {i}", "start": float(i * 4), "duration": 4.0} for i in range(n)]


def _old_chunks(text: str, n: int, metadata: dict, *, text_en: str | None = None,
                stamp_document_id: bool = True) -> list[dict]:
    chunks = chunk_transcript(_segments(text, n), chunk_size=40, chunk_overlap=8, video_metadata=metadata)
    for chunk in chunks:
        meta = chunk["metadata"]
        for name in [k for k in meta if k.startswith("code_mix_")]:
            del meta[name]
        if not stamp_document_id:
            meta.pop("document_id", None)
        if text_en:
            meta["text_en"] = text_en
    return chunks


@pytest.fixture
def library(db, monkeypatch, ephemeral_chroma):
    from tests import conftest as _conftest

    monkeypatch.setattr(bcl, "SessionLocal", _conftest.TestingSessionLocal)

    hindi = Document(video_id="vidHINDI001", title="Hindi lecture", url="u")
    spanish = Document(source_type="pdf", source_id="pdf:spanish", title="Spanish PDF", url="u")
    english = Document(video_id="vidENGLISH1", title="English talk", url="u")
    unprofiled = Document(video_id="vidNOPROFIL", title="Not profiled", url="u")
    legacy = Document(video_id="vidLEGACY01", title="Unstamped chunks", url="u")
    for document, text in ((hindi, HINDI), (spanish, SPANISH), (english, ENGLISH), (legacy, HINDI)):
        language_mix_service.record(document, code_mixing_service.profile_transcript(_segments(text, 6)))
    db.add_all([hindi, spanish, english, unprofiled, legacy])
    db.commit()

    chunks = (
        _old_chunks(HINDI, 8, {"video_id": hindi.video_id, "document_id": hindi.document_id})
        + _old_chunks(SPANISH, 6, {"document_id": spanish.document_id, "source_type": "pdf",
                                   "source_id": "pdf:spanish"},
                      text_en="My sister's dog eats in the kitchen.")
        + _old_chunks(ENGLISH, 3, {"video_id": english.video_id, "document_id": english.document_id})
        + _old_chunks(HINDI, 3, {"video_id": unprofiled.video_id, "document_id": unprofiled.document_id})
        + _old_chunks(HINDI, 3, {"video_id": legacy.video_id, "document_id": legacy.document_id},
                      stamp_document_id=False)
        + _old_chunks(HINDI, 2, {"video_id": "vidGONE0001"}, stamp_document_id=False)
    )
    ephemeral_chroma.insert_chunks(chunks)
    return {"hindi": hindi, "spanish": spanish, "english": english, "unprofiled": unprofiled, "legacy": legacy}


def _snapshot(chroma) -> dict[str, dict]:
    got = chroma.get_global_collection().get(include=["metadatas", "documents", "embeddings"])
    return {
        cid: {"meta": dict(m or {}), "text": d, "embedding": [round(float(x), 6) for x in e]}
        for cid, m, d, e in zip(got["ids"], got["metadatas"], got["documents"], got["embeddings"])
    }


def _run(tmp_path, *args: str) -> tuple[int, dict]:
    out = tmp_path / f"report-{len(list(tmp_path.iterdir()))}.json"
    code = bcl.main([*args, "--page-size", "5", "--json", str(out)])
    return code, json.loads(out.read_text(encoding="utf-8"))


def _rows(snapshot: dict, video_or_source: str) -> list[dict]:
    rows = [r for r in snapshot.values()
            if video_or_source in (r["meta"].get("video_id"), r["meta"].get("source_id"))]
    assert rows
    return rows


def test_dry_run_counts_and_writes_nothing(library, ephemeral_chroma, tmp_path):
    before = _snapshot(ephemeral_chroma)

    code, report = _run(tmp_path)

    assert code == 0
    assert _snapshot(ephemeral_chroma) == before
    assert report["documents_profiled"] == 4
    assert report["documents_code_mixed"] == 3  # the English talk has nothing to stamp
    assert report["chunks_scanned"] == len(before)
    hindi = len(_rows(before, "vidHINDI001")) + len(_rows(before, "vidLEGACY01"))
    spanish = len(_rows(before, "pdf:spanish"))
    assert report["chunks_matched"] == report["chunks_to_update"] == hindi + spanish
    assert report["chunks_plain_english"] == len(_rows(before, "vidENGLISH1"))
    assert report["chunks_unprofiled"] == len(_rows(before, "vidNOPROFIL"))
    assert report["chunks_unresolved"] == len(_rows(before, "vidGONE0001"))
    assert report["chunks_updated"] == 0
    for name in LANGUAGE_FIELDS:
        assert report["gained"][name] == hindi + spanish and report["changed"][name] == 0


def test_the_report_says_those_chunks_stay_embedded_as_their_original_text(library, ephemeral_chroma, tmp_path, capsys):
    before = _snapshot(ephemeral_chroma)

    _, report = _run(tmp_path)

    # The Spanish chunks carry a rendering; the Hindi ones were never rendered.
    expected = len(_rows(before, "vidHINDI001")) + len(_rows(before, "vidLEGACY01"))
    assert report["chunks_embedded_as_original"] == expected
    assert f"{expected} of these chunks have no English rendering and stay embedded as their original text" in capsys.readouterr().out


def test_write_adds_what_the_chunker_writes_and_touches_nothing_else(library, ephemeral_chroma, tmp_path):
    before = _snapshot(ephemeral_chroma)

    code, report = _run(tmp_path, "--write")

    assert code == 0 and report["chunks_updated"] == report["chunks_to_update"]
    after = _snapshot(ephemeral_chroma)
    for cid, was in before.items():
        assert after[cid]["text"] == was["text"]
        assert after[cid]["embedding"] == was["embedding"]
        assert {k: after[cid]["meta"].get(k) for k in was["meta"]} == was["meta"]

    expected = code_mixing_service.chunk_metadata_from_profile(
        language_mix_service.load(library["hindi"])
    )
    assert expected["code_mix_primary"] == "hi" and expected["code_mix_script"] == "Devanagari"
    for row in _rows(after, "vidHINDI001") + _rows(after, "vidLEGACY01"):
        assert {k: row["meta"].get(k) for k in LANGUAGE_FIELDS} == expected
        assert "code_mix_chunk_share" not in row["meta"]  # per-chunk fields are not this pass's

    # The fixes reach the old chunks: a Spanish PDF is not Hindi.
    for row in _rows(after, "pdf:spanish"):
        assert row["meta"]["code_mix_primary"] == "other"
        assert row["meta"]["text_en"]
        assert "Hindi (romanised)" not in code_mixing_service.source_note(row["meta"])

    for video in ("vidENGLISH1", "vidNOPROFIL", "vidGONE0001"):
        assert not any(k.startswith("code_mix") for r in _rows(after, video) for k in r["meta"])


def test_a_second_run_finds_nothing_to_change(library, ephemeral_chroma, tmp_path):
    _run(tmp_path, "--write")
    settled = _snapshot(ephemeral_chroma)

    code, report = _run(tmp_path, "--write")

    assert code == 0
    assert report["chunks_to_update"] == report["chunks_updated"] == 0
    assert report["chunks_already_current"] == report["chunks_matched"] > 0
    assert _snapshot(ephemeral_chroma) == settled


def test_a_refreshed_profile_reaches_chunks_that_hold_the_old_one(db, library, ephemeral_chroma, tmp_path):
    """How a tagger change gets to a chunk written with the old reading."""
    _run(tmp_path, "--write")
    document = library["hindi"]
    stale = dict(language_mix_service.load(document), hi_share=0.5, quote_mode="roman")
    language_mix_service.record(document, stale)
    db.commit()

    _, report = _run(tmp_path, "--write", "--document-ids", document.document_id)

    assert report["changed"]["code_mix_share"] == report["chunks_updated"] > 0
    assert report["gained"]["code_mix_share"] == 0
    rows = _rows(_snapshot(ephemeral_chroma), "vidHINDI001")
    assert all(r["meta"]["code_mix_share"] == 0.5 and r["meta"]["code_mix_quote"] == "roman" for r in rows)


def test_a_document_now_plain_english_keeps_its_fields_and_is_reported(db, library, ephemeral_chroma, tmp_path):
    _run(tmp_path, "--write")
    document = library["hindi"]
    language_mix_service.record(document, code_mixing_service.profile_transcript(_segments(ENGLISH, 6)))
    db.commit()

    _, report = _run(tmp_path, "--write", "--document-ids", document.document_id)

    rows = _rows(_snapshot(ephemeral_chroma), "vidHINDI001")
    assert report["chunks_stale"] == len(rows)
    assert report["chunks_cleared"] == 0
    assert report["chunks_updated"] == 0
    assert all(r["meta"]["code_mix_primary"] == "hi" for r in rows)


def _now_plain_english(db, library, tmp_path):
    """Chunks written with today's fields, per-chunk ones too, of a document
    whose refreshed profile reads plain English."""
    _run(tmp_path, "--write")
    document = library["hindi"]
    language_mix_service.record(document, code_mixing_service.profile_transcript(_segments(ENGLISH, 6)))
    db.commit()
    return document


def test_clear_stale_removes_the_fields_a_plain_english_document_carries(db, library, ephemeral_chroma, tmp_path):
    """The review of PR #403: no normal path re-chunks an embedded document, so
    without this the false claim stays on stored chunks for good."""
    document = _now_plain_english(db, library, tmp_path)
    ids = [cid for cid, row in _snapshot(ephemeral_chroma).items()
           if row["meta"].get("video_id") == "vidHINDI001"]
    ephemeral_chroma.get_global_collection().update(ids=ids, metadatas=[
        {"code_mix_chunk_share": 0.9, "code_mix_chunk_matrix": "hi", "text_en": "rendered"} for _ in ids
    ])
    before = _snapshot(ephemeral_chroma)

    _, report = _run(tmp_path, "--write", "--clear-stale", "--document-ids", document.document_id)

    after = _snapshot(ephemeral_chroma)
    assert report["chunks_stale"] == report["chunks_cleared"] == len(ids) > 0
    for cid in ids:
        old, new = before[cid], after[cid]
        assert new["meta"] == {k: v for k, v in old["meta"].items() if not k.startswith("code_mix_")}
        assert new["meta"]["text_en"] == "rendered"  # the vector's own source stays
        assert new["text"] == old["text"]
        assert new["embedding"] == old["embedding"]

    _, again = _run(tmp_path, "--write", "--clear-stale", "--document-ids", document.document_id)
    assert again["chunks_stale"] == again["chunks_cleared"] == 0


def test_clear_stale_is_a_no_op_without_write(db, library, ephemeral_chroma, tmp_path):
    document = _now_plain_english(db, library, tmp_path)
    before = _snapshot(ephemeral_chroma)

    _, report = _run(tmp_path, "--clear-stale", "--document-ids", document.document_id)

    assert report["chunks_stale"] > 0 and report["chunks_cleared"] == 0
    assert _snapshot(ephemeral_chroma) == before


def test_clear_stale_leaves_every_other_document_alone(db, library, ephemeral_chroma, tmp_path):
    _now_plain_english(db, library, tmp_path)
    before = _rows(_snapshot(ephemeral_chroma), "vidLEGACY01")

    _run(tmp_path, "--write", "--clear-stale")

    assert _rows(_snapshot(ephemeral_chroma), "vidLEGACY01") == before


def test_the_chunks_gain_the_named_share_the_note_depends_on(library, ephemeral_chroma, tmp_path):
    _run(tmp_path, "--write")
    rows = _rows(_snapshot(ephemeral_chroma), "vidHINDI001")
    assert rows and all(r["meta"]["code_mix_named_share"] == 1.0 for r in rows)


def test_document_ids_limit_the_pass(library, ephemeral_chroma, tmp_path):
    _, report = _run(tmp_path, "--write", "--document-ids", library["spanish"].document_id)

    after = _snapshot(ephemeral_chroma)
    assert report["documents_profiled"] == 1
    assert all("code_mix_primary" in r["meta"] for r in _rows(after, "pdf:spanish"))
    assert not any("code_mix_primary" in r["meta"] for r in _rows(after, "vidHINDI001"))


def test_no_llm_no_embedder_and_no_tagger(db, library, ephemeral_chroma):
    """It reads the stored profile: nothing is computed, so nothing can differ
    from the column, and nothing could reach a provider."""
    with (
        patch("app.services.llm_service.get_llm_for", side_effect=AssertionError("no LLM")),
        patch.object(code_mixing_service, "profile_transcript", side_effect=AssertionError("no tagger")),
        patch.object(code_mixing_service, "render_english", side_effect=AssertionError("no rendering")),
    ):
        report = metadata_backfill_service.backfill_chunk_language_fields(db, write=True, page_size=5)
    assert report.chunks_updated > 0


def test_a_failed_batch_stops_the_pass_and_a_rerun_resumes(db, library, ephemeral_chroma):
    real = ephemeral_chroma.get_global_collection()

    class FailsOnce:
        def __init__(self):
            self.calls = 0

        def get(self, **kw):
            return real.get(**kw)

        def update(self, **kw):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("chroma went away")
            return real.update(**kw)

    store = FailsOnce()
    first = metadata_backfill_service.backfill_chunk_language_fields(
        db, write=True, page_size=4, collection=store
    )
    assert first.stopped and "run again" in first.stopped
    assert first.chunks_updated == 4 < first.chunks_to_update

    second = metadata_backfill_service.backfill_chunk_language_fields(
        db, write=True, page_size=4, collection=store
    )
    assert not second.stopped
    assert second.chunks_updated == first.chunks_to_update - 4


def test_a_failed_scan_writes_nothing_and_exits_non_zero(db, library, tmp_path, monkeypatch):
    class Broken:
        def get(self, **kw):
            raise RuntimeError("chroma went away")

    from app.services import chroma_service

    monkeypatch.setattr(chroma_service, "get_global_collection", lambda: Broken())
    code, report = _run(tmp_path, "--write")

    assert code == 1 and "nothing written" in report["stopped"]
    assert report["chunks_updated"] == 0
