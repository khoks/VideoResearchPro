"""scripts/backfill_chunk_temporal_fields.py (S-1.17.3), run through its ``main``.

The ephemeral collection holds chunks as they were written before R3: the
production chunker's output (so ``code_mix_*``, ``document_id`` and the
timestamps are real) with the era and numeric publish fields removed, plus a
``text_en`` rendering of the kind D-084 adds. The pass must add exactly the
fields the chunker writes today, omit unknown ones, keep every other key, the
stored text and the embedding, and find nothing to do the second time.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.document import Document
from app.services import metadata_backfill_service
from app.services.metadata_backfill_service import TEMPORAL_FIELDS
from app.utils.chunking import chunk_transcript

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import backfill_chunk_temporal_fields as bct  # noqa: E402

HINDI = "यह वक्ता के अपने शब्द हैं और व्याख्यान हिंदी में है।"
ENGLISH = "Tidal energy storage holds water behind a barrage and releases it later."
PUBLISHED = datetime(2024, 3, 12, 10, 30)
ERA = {"era_start": 2019, "era_end": 2021, "era_confidence": 0.8, "is_retrospective": True,
       "extracted_at": "2026-10-19T00:00:00+00:00", "model": "m"}


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


def _pre_r3_chunks(text: str, n: int, metadata: dict, *, stamp_document_id: bool = True,
                   text_en: str | None = None) -> list[dict]:
    segments = [{"text": f"{text} ({i})", "start": float(i * 4), "duration": 4.0} for i in range(n)]
    chunks = chunk_transcript(segments, chunk_size=40, chunk_overlap=8, video_metadata=metadata)
    for chunk in chunks:
        meta = chunk["metadata"]
        for name in TEMPORAL_FIELDS:
            meta.pop(name, None)
        if not stamp_document_id:
            meta.pop("document_id", None)
        if text_en:
            meta["text_en"] = text_en
    return chunks


@pytest.fixture
def library(db, monkeypatch, ephemeral_chroma):
    from tests import conftest as _conftest

    monkeypatch.setattr(bct, "SessionLocal", _conftest.TestingSessionLocal)

    hindi = Document(video_id="vidHINDI001", title="Hindi lecture", url="u",
                     published_at=PUBLISHED, discussed_era_json=json.dumps(ERA))
    pdf = Document(source_type="pdf", source_id="pdf:dated", title="Dated PDF", url="u",
                   published_at=datetime(2025, 1, 2))
    undated = Document(video_id="vidUNDATED1", title="Era unknown", url="u",
                       discussed_era_json=json.dumps({**ERA, "era_confidence": 0.0}))
    legacy = Document(video_id="vidLEGACY01", title="Unstamped chunks", url="u",
                      published_at=datetime(2023, 6, 1))
    db.add_all([hindi, pdf, undated, legacy])
    db.commit()

    chunks = (
        _pre_r3_chunks(HINDI, 8, {"video_id": hindi.video_id, "document_id": hindi.document_id,
                                  "published_at": PUBLISHED},
                       text_en="These are the speaker's own words and the lecture is in Hindi.")
        + _pre_r3_chunks(ENGLISH, 6, {"document_id": pdf.document_id, "source_type": "pdf",
                                      "source_id": "pdf:dated"})
        + _pre_r3_chunks(ENGLISH, 3, {"video_id": undated.video_id, "document_id": undated.document_id})
        + _pre_r3_chunks(ENGLISH, 3, {"video_id": legacy.video_id, "document_id": legacy.document_id},
                         stamp_document_id=False)
        + _pre_r3_chunks(ENGLISH, 2, {"video_id": "vidGONE0001"}, stamp_document_id=False)
    )
    ephemeral_chroma.insert_chunks(chunks)
    return {"hindi": hindi.document_id, "pdf": pdf.document_id, "undated": undated.document_id,
            "legacy": legacy.document_id}


def _snapshot(chroma) -> dict[str, dict]:
    got = chroma.get_global_collection().get(include=["metadatas", "documents", "embeddings"])
    return {
        cid: {"meta": dict(m or {}), "text": d, "embedding": [round(float(x), 6) for x in e]}
        for cid, m, d, e in zip(got["ids"], got["metadatas"], got["documents"], got["embeddings"])
    }


def _run(tmp_path, *args: str) -> tuple[int, dict]:
    out = tmp_path / f"report-{len(list(tmp_path.iterdir()))}.json"
    code = bct.main([*args, "--page-size", "5", "--json", str(out)])
    return code, json.loads(out.read_text(encoding="utf-8"))


def _by_prefix(snapshot: dict, prefix: str) -> list[dict]:
    rows = [row for cid, row in snapshot.items() if cid.startswith(prefix)]
    assert rows
    return rows


def test_dry_run_counts_per_field_and_writes_nothing(library, ephemeral_chroma, tmp_path):
    before = _snapshot(ephemeral_chroma)
    code, report = _run(tmp_path)

    assert code == 0 and report["write"] is False
    assert _snapshot(ephemeral_chroma) == before
    hindi_n = len(_by_prefix(before, "vidHINDI001:"))
    pdf_n = len(_by_prefix(before, library["pdf"] + ":"))
    legacy_n = len(_by_prefix(before, "vidLEGACY01:"))
    assert report["documents_with_dates"] == 3
    assert report["chunks_matched"] == hindi_n + pdf_n + legacy_n
    assert report["chunks_undated"] == len(_by_prefix(before, "vidUNDATED1:"))
    assert report["chunks_unresolved"] == len(_by_prefix(before, "vidGONE0001:"))
    assert report["chunks_to_update"] == report["chunks_matched"] and report["chunks_updated"] == 0
    assert report["gained"] == {
        "era_start": hindi_n, "era_end": hindi_n, "era_confidence": hindi_n,
        "is_retrospective": hindi_n,
        "published_ts": hindi_n + pdf_n + legacy_n, "published_year": hindi_n + pdf_n + legacy_n,
    }
    assert set(report["changed"].values()) == {0}


def test_write_adds_known_fields_keeps_every_other_key_and_never_reembeds(
    library, ephemeral_chroma, tmp_path
):
    before = _snapshot(ephemeral_chroma)
    code, report = _run(tmp_path, "--write")
    after = _snapshot(ephemeral_chroma)

    assert code == 0 and report["chunks_updated"] == report["chunks_to_update"] > 0
    assert set(after) == set(before)
    for cid, row in after.items():
        # Stored text and vector untouched; no key lost or altered.
        assert row["text"] == before[cid]["text"]
        assert row["embedding"] == before[cid]["embedding"]
        old = before[cid]["meta"]
        assert {k: row["meta"].get(k) for k in old} == old, cid

    published_ts = int(PUBLISHED.replace(tzinfo=timezone.utc).timestamp())
    for row in _by_prefix(after, "vidHINDI001:"):
        meta = row["meta"]
        assert meta["code_mix_primary"] == "hi" and meta["code_mix_script"] == "Devanagari"
        assert meta["text_en"].startswith("These are the speaker's own words")
        assert meta["document_id"] == library["hindi"]
        assert (meta["era_start"], meta["era_end"], meta["is_retrospective"]) == (2019, 2021, True)
        assert meta["era_confidence"] == pytest.approx(0.8)
        assert (meta["published_ts"], meta["published_year"]) == (published_ts, 2024)
    for row in _by_prefix(after, library["pdf"] + ":"):
        # A publish date but no era: the era fields stay absent, never sentinels.
        assert row["meta"]["published_year"] == 2025
        assert not any(k.startswith("era_") or k == "is_retrospective" for k in row["meta"])
    for row in _by_prefix(after, "vidLEGACY01:"):
        # Resolved through video_id although the chunk has no document_id yet.
        assert row["meta"]["published_year"] == 2023
        assert "document_id" not in row["meta"]
    for prefix in ("vidUNDATED1:", "vidGONE0001:"):
        for row in _by_prefix(after, prefix):
            assert not any(k in row["meta"] for k in TEMPORAL_FIELDS)

    # Idempotent: the second run finds every dated chunk current.
    code, again = _run(tmp_path, "--write")
    assert code == 0
    assert again["chunks_to_update"] == 0 and again["chunks_updated"] == 0
    assert again["chunks_already_current"] == report["chunks_matched"]
    assert _snapshot(ephemeral_chroma) == after


def test_a_changed_publish_date_is_reported_as_changed(db, library, ephemeral_chroma, tmp_path):
    _run(tmp_path, "--write")
    doc = db.get(Document, library["pdf"])
    doc.published_at = datetime(2025, 7, 1)
    db.commit()

    code, report = _run(tmp_path, "--write")
    n = len(_by_prefix(_snapshot(ephemeral_chroma), library["pdf"] + ":"))
    assert report["changed"]["published_ts"] == n and report["changed"]["published_year"] == 0
    assert report["gained"]["published_ts"] == 0


def test_document_ids_limit_the_pass(library, ephemeral_chroma, tmp_path):
    code, report = _run(tmp_path, "--write", "--document-ids", library["pdf"])
    after = _snapshot(ephemeral_chroma)

    assert report["documents_with_dates"] == 1
    assert all("published_year" in r["meta"] for r in _by_prefix(after, library["pdf"] + ":"))
    assert not any("published_year" in r["meta"] for r in _by_prefix(after, "vidHINDI001:"))


# --- the merge, against a store that REPLACES metadata on update -------------


class _ReplacingCollection:
    """A collection whose ``update`` replaces a chunk's metadata (Chroma 1.5
    merges; older or other backends may not). Pages like Chroma's ``get``."""

    def __init__(self, metas: dict[str, dict], fail_on_update: int | None = None):
        self.metas = {cid: dict(m) for cid, m in metas.items()}
        self.updates = 0
        self.fail_on_update = fail_on_update

    def get(self, ids=None, limit=None, offset=0, include=None):
        keys = list(ids) if ids is not None else list(self.metas)[offset:offset + limit]
        keys = [k for k in keys if k in self.metas]
        return {"ids": keys, "metadatas": [dict(self.metas[k]) for k in keys]}

    def update(self, ids, metadatas):
        self.updates += 1
        if self.fail_on_update is not None and self.updates == self.fail_on_update:
            raise RuntimeError("database is locked")
        for cid, meta in zip(ids, metadatas):
            self.metas[cid] = dict(meta)


def _replacing(library, ephemeral_chroma, **kw) -> _ReplacingCollection:
    got = ephemeral_chroma.get_global_collection().get(include=["metadatas"])
    return _ReplacingCollection(dict(zip(got["ids"], got["metadatas"])), **kw)


def test_keys_survive_an_update_that_replaces_metadata(db, library, ephemeral_chroma):
    store = _replacing(library, ephemeral_chroma)
    before = {cid: dict(m) for cid, m in store.metas.items()}

    report = metadata_backfill_service.backfill_chunk_temporal_fields(
        db, write=True, page_size=4, collection=store
    )

    assert report.chunks_updated > 0
    for cid, old in before.items():
        assert {k: store.metas[cid].get(k) for k in old} == old
    assert all(store.metas[c]["code_mix_primary"] == "hi" for c in store.metas if c.startswith("vidHINDI"))


def test_mutation_sending_only_the_new_fields_would_lose_keys(db, library, ephemeral_chroma, monkeypatch):
    """Mutation check: send only the new fields (no merge) and a replacing
    store loses ``code_mix_*``, ``document_id`` and ``text_en`` — what the
    test above would catch."""
    monkeypatch.setattr(metadata_backfill_service, "_merge_metadata", lambda stored, new: dict(new))
    store = _replacing(library, ephemeral_chroma)

    metadata_backfill_service.backfill_chunk_temporal_fields(db, write=True, page_size=4, collection=store)

    hindi = [m for c, m in store.metas.items() if c.startswith("vidHINDI")]
    assert hindi and all("code_mix_primary" not in m and "text_en" not in m for m in hindi)


def test_a_failed_batch_stops_the_pass_and_a_rerun_resumes(db, library, ephemeral_chroma):
    store = _replacing(library, ephemeral_chroma, fail_on_update=2)

    first = metadata_backfill_service.backfill_chunk_temporal_fields(
        db, write=True, page_size=4, collection=store
    )
    assert first.stopped and "run again" in first.stopped
    assert first.chunks_updated == 4 < first.chunks_to_update

    store.fail_on_update = None
    second = metadata_backfill_service.backfill_chunk_temporal_fields(
        db, write=True, page_size=4, collection=store
    )
    assert not second.stopped
    assert second.chunks_to_update == first.chunks_to_update - 4
    third = metadata_backfill_service.backfill_chunk_temporal_fields(
        db, write=True, page_size=4, collection=store
    )
    assert third.chunks_to_update == 0


def test_the_script_exits_non_zero_when_the_pass_stops(db, library, ephemeral_chroma, tmp_path, monkeypatch):
    store = _replacing(library, ephemeral_chroma, fail_on_update=1)
    monkeypatch.setattr(ephemeral_chroma, "get_global_collection", lambda: store)

    code, report = _run(tmp_path, "--write")
    assert code == 1 and report["stopped"]
