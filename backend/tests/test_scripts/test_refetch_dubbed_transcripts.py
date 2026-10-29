"""refetch_dubbed_transcripts.py (T-1.11.11.3): which cached transcripts
came from a dub, decided without writing anything; the write mode is the
owner's step and is tested here against fakes only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from youtube_transcript_api import IpBlocked

from app.models.document import Document
from app.models.transcript_cache import TranscriptCache
from app.services import youtube_service
from tests.caption_track_fixtures import SHAPES, TRACK_TEXT, FakeHttp

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import refetch_dubbed_transcripts as rd  # noqa: E402


class _MultiFetcher:
    def __init__(self, by_video: dict, block_on: str | None = None):
        self._http_client = FakeHttp()
        self._by_video = by_video
        self._block_on = block_on
        self.listed: list[str] = []

    def _fetch_captions_json(self, video_id):
        self.listed.append(video_id)
        if video_id == self._block_on:
            raise IpBlocked(video_id)
        return self._by_video[video_id]


class _MultiApi:
    def __init__(self, by_video: dict, block_on: str | None = None):
        self._fetcher = _MultiFetcher(by_video, block_on)


# (shape or None, cached language, cache source, already checked?)
ROWS = {
    "1v3_AQ26jZ0": ("hindi_audio_bengali_and_english_dubs", "bn", "youtube", False),
    "v6CuYULP3tM": ("hindi_audio_english_dub", "en-US", "youtube", False),
    "J-HV7gNVdd0": ("asr_only", "hi", "youtube", False),
    "whisperEra1": (None, "english", None, False),
    "checked0001": (None, "en", "youtube", True),
    "IcVYyF3EEbk": ("original_asr_beside_regional_dub", "en", "youtube", False),
    "IbcYNtZ8HZY": ("dubs_beside_mislabelled_original", "hi", "youtube", False),
    "onlyDubs01": ("only_dubs", "en-US", None, False),
    # Declared `en-IN` (wrong), cached the `en-US` dub: same primary subtag
    # as the declaration, still a dub.
    "enINdub0001": ("mislabelled_declaration_hides_dub", "en-US", "youtube", False),
}


@pytest.fixture
def library(db, monkeypatch):
    by_video, declared = {}, {}
    for vid, (shape_name, lang, source, checked) in ROWS.items():
        doc = Document(
            video_id=vid, source_id=vid, title=f"video {vid}", url=f"https://youtu.be/{vid}",
            transcript_status="fetched", transcript_language=lang, embedded_in_chroma=True,
            source_metadata_json=json.dumps({"caption_track": {"language": lang}}) if checked else None,
        )
        db.add(doc)
        db.flush()
        db.add(TranscriptCache(
            document_id=doc.document_id, video_id=vid, language=lang, source=source,
            segments_json=json.dumps([{"text": "old text", "start": 0.0, "duration": 1.0}]),
        ))
        if shape_name:
            shape = SHAPES[shape_name]
            by_video[vid] = shape.captions()
            declared[vid] = shape.declared
    db.commit()

    calls = []

    def fake_declared(ids, record_quota):
        calls.append((list(ids), record_quota))
        return {vid: declared.get(vid) for vid in ids}

    monkeypatch.setattr(rd, "declared_audio_languages", fake_declared)
    return {"by_video": by_video, "declared_calls": calls}


@pytest.fixture
def chroma(monkeypatch):
    """The write mode's Chroma calls, recorded; ``delete_ok`` and
    ``insert_error`` steer a failure."""
    from app.services import chroma_service
    from tests import conftest as _conftest

    monkeypatch.setattr(youtube_service, "SessionLocal", _conftest.TestingSessionLocal)
    state = {"deleted": [], "inserted": [], "delete_ok": True, "insert_error": None}

    def delete(vid):
        state["deleted"].append(vid)
        return state["delete_ok"]

    def insert(chunks):
        if state["insert_error"]:
            raise state["insert_error"]
        state["inserted"].extend(chunks)
        return len(chunks)

    monkeypatch.setattr(chroma_service, "delete_video_chunks", delete)
    monkeypatch.setattr(chroma_service, "insert_chunks", insert)
    return state


def _statuses(report):
    return {r["video_id"]: r["status"] for r in report["rows"]}


def _cached(db, vid):
    db.expire_all()
    return db.query(TranscriptCache).filter(TranscriptCache.video_id == vid).one()


def _doc(db, vid):
    db.expire_all()
    return db.query(Document).filter(Document.video_id == vid).one()


def test_dry_run_lists_every_candidate_and_writes_nothing(db, library):
    sleeps = []
    api = _MultiApi(library["by_video"])
    report = rd.run(db, ytt_api=api, sleep=sleeps.append)

    assert report["mode"] == "dry_run"
    assert report["skipped"] == {"whisper": 1, "already_checked": 1}
    assert _statuses(report) == {
        "1v3_AQ26jZ0": "refetch",          # Bengali dub of a Hindi lecture
        "v6CuYULP3tM": "refetch",          # English dub, nothing declared
        "enINdub0001": "refetch",          # English dub hidden by an en-IN declaration
        "J-HV7gNVdd0": "ok",
        "IcVYyF3EEbk": "ok",               # en is the original's ASR track, not the en-US dub
        "IbcYNtZ8HZY": "ok",               # declared en, cached hi, hi is right
        "onlyDubs01": "no_spoken_track",
    }
    row = next(r for r in report["rows"] if r["video_id"] == "1v3_AQ26jZ0")
    assert (row["chosen_language"], row["chosen_kind"]) == ("hi", "asr")
    assert row["skipped_dubbed"] == ["bn", "en-US"]
    # No caption track can replace an all-dub transcript: an owner decision.
    assert [d["video_id"] for d in report["owner_decisions"]] == ["onlyDubs01"]

    # Every candidate's tracks are listed (a declaration is no proof), paced per D-051.
    assert sorted(api._fetcher.listed) == sorted(
        ["1v3_AQ26jZ0", "IbcYNtZ8HZY", "IcVYyF3EEbk", "J-HV7gNVdd0", "enINdub0001",
         "onlyDubs01", "v6CuYULP3tM"]
    )
    assert len(sleeps) == 6 and all(s >= 3.0 for s in sleeps)
    # Dry run: no quota-log row, no transcript downloaded, nothing changed.
    assert library["declared_calls"][0][1] is False
    assert api._fetcher._http_client.fetched == []
    assert _cached(db, "1v3_AQ26jZ0").language == "bn"
    doc = _doc(db, "1v3_AQ26jZ0")
    assert doc.transcript_language == "bn" and doc.source_metadata_json is None


def test_a_cached_dub_sharing_the_declared_primary_subtag_is_still_listed(db, library):
    """Mutation-style: the first cut skipped a row whose cached language had
    the declared language's primary subtag (`en-US` under `en-IN`), so this
    dub was marked fine without its tracks ever being listed."""
    api = _MultiApi(library["by_video"])
    report = rd.run(db, video_ids=["enINdub0001"], ytt_api=api, sleep=lambda s: None)
    assert api._fetcher.listed == ["enINdub0001"]
    row = report["rows"][0]
    assert row["status"] == "refetch"
    assert (row["chosen_language"], row["spoken_language_source"]) == ("hi", "player")
    assert row["skipped_dubbed"] == ["en-US"]


def test_dry_run_stops_at_the_first_ip_block(db, library):
    api = _MultiApi(library["by_video"], block_on="IbcYNtZ8HZY")
    report = rd.run(db, ytt_api=api, sleep=lambda s: None)
    assert report["stopped"] and "IP-block" in report["stopped"]
    assert api._fetcher.listed[-1] == "IbcYNtZ8HZY"
    assert "v6CuYULP3tM" not in api._fetcher.listed  # after the block, in id order


def test_write_mode_replaces_the_transcript_and_the_chunks(db, library, chroma):
    api = _MultiApi(library["by_video"])
    report = rd.run(db, video_ids=["1v3_AQ26jZ0"], write=True, ytt_api=api, sleep=lambda s: None)

    assert _statuses(report) == {"1v3_AQ26jZ0": "refetched"}
    assert library["declared_calls"][0][1] is True  # write mode logs its quota
    cached = _cached(db, "1v3_AQ26jZ0")
    assert cached.language == "hi"
    assert json.loads(cached.segments_json)[0]["text"] == TRACK_TEXT["hi"]
    doc = _doc(db, "1v3_AQ26jZ0")
    assert doc.transcript_language == "hi"
    assert doc.embedded_in_chroma is True
    assert json.loads(doc.source_metadata_json)["caption_track"]["language"] == "hi"
    assert chroma["deleted"] == ["1v3_AQ26jZ0"]
    assert chroma["inserted"] and all(TRACK_TEXT["hi"] in c["text"] for c in chroma["inserted"])


def test_write_mode_writes_nothing_when_the_old_chunks_cannot_be_deleted(db, library, chroma):
    """`delete_video_chunks` reports a failure (Chroma locked by the worker)
    by returning False. Upserting anyway would overwrite chunk ids 0..N-1 and
    leave every higher-index dub chunk behind a document reported fixed."""
    chroma["delete_ok"] = False
    api = _MultiApi(library["by_video"])
    report = rd.run(db, video_ids=["1v3_AQ26jZ0"], write=True, ytt_api=api, sleep=lambda s: None)

    assert _statuses(report) == {"1v3_AQ26jZ0": "refetch_failed"}
    assert chroma["inserted"] == []
    assert _cached(db, "1v3_AQ26jZ0").language == "bn"
    doc = _doc(db, "1v3_AQ26jZ0")
    assert doc.transcript_language == "bn" and doc.source_metadata_json is None
    assert doc.embedded_in_chroma is True  # its chunks are still there
    # The next run finds it again.
    again = rd.run(db, video_ids=["1v3_AQ26jZ0"], ytt_api=_MultiApi(library["by_video"]),
                   sleep=lambda s: None)
    assert _statuses(again) == {"1v3_AQ26jZ0": "refetch"}


def test_write_mode_writes_nothing_when_chunking_fails(db, library, chroma, monkeypatch):
    """The first cut committed the new cache through its own session before
    chunking; a chunking error then left a Hindi cache beside a document and
    chunks still in Bengali, and the next run read the row as fine."""
    import app.utils.chunking as chunking

    def boom(*a, **k):
        raise ValueError("chunker broke")

    monkeypatch.setattr(chunking, "chunk_transcript", boom)
    api = _MultiApi(library["by_video"])
    report = rd.run(db, video_ids=["1v3_AQ26jZ0"], write=True, ytt_api=api, sleep=lambda s: None)

    assert _statuses(report) == {"1v3_AQ26jZ0": "refetch_failed"}
    assert chroma["deleted"] == [] and chroma["inserted"] == []
    assert _cached(db, "1v3_AQ26jZ0").language == "bn"
    assert _doc(db, "1v3_AQ26jZ0").transcript_language == "bn"


def test_write_mode_failure_while_writing_keeps_the_row_detectable(db, library, chroma, monkeypatch):
    """The old chunks are gone when the database write fails: the document is
    marked un-embedded, the cache keeps the dub, and the next run lists it."""

    def boom(*a, **k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(rd, "_write_cache_row", boom)
    api = _MultiApi(library["by_video"])
    report = rd.run(db, video_ids=["1v3_AQ26jZ0"], write=True, ytt_api=api, sleep=lambda s: None)

    assert _statuses(report) == {"1v3_AQ26jZ0": "refetch_failed"}
    assert chroma["deleted"] == ["1v3_AQ26jZ0"] and chroma["inserted"] == []
    assert _cached(db, "1v3_AQ26jZ0").language == "bn"
    doc = _doc(db, "1v3_AQ26jZ0")
    assert doc.transcript_language == "bn" and doc.source_metadata_json is None
    assert doc.embedded_in_chroma is False
    again = rd.run(db, video_ids=["1v3_AQ26jZ0"], ytt_api=_MultiApi(library["by_video"]),
                   sleep=lambda s: None)
    assert _statuses(again) == {"1v3_AQ26jZ0": "refetch"}


def test_write_mode_reports_a_failed_embed_as_unembedded(db, library, chroma):
    chroma["insert_error"] = RuntimeError("chroma down")
    api = _MultiApi(library["by_video"])
    report = rd.run(db, video_ids=["1v3_AQ26jZ0"], write=True, ytt_api=api, sleep=lambda s: None)

    assert _statuses(report) == {"1v3_AQ26jZ0": "refetched_unembedded"}
    assert _cached(db, "1v3_AQ26jZ0").language == "hi"
    doc = _doc(db, "1v3_AQ26jZ0")
    assert doc.transcript_language == "hi"
    assert doc.embedded_in_chroma is False  # the next job embeds it from the cache


def test_write_mode_stops_at_an_ip_block_while_refetching(db, library, chroma):
    """An IP block raised by the track download ends the pass, as in the dry run."""
    api = _MultiApi(library["by_video"])

    def blocked(url):
        raise IpBlocked("1v3_AQ26jZ0")

    api._fetcher._http_client.get = blocked
    report = rd.run(db, video_ids=["1v3_AQ26jZ0", "v6CuYULP3tM"], write=True, ytt_api=api,
                    sleep=lambda s: None)

    assert report["stopped"] and "IP-block" in report["stopped"]
    assert api._fetcher.listed == ["1v3_AQ26jZ0"]
    assert _statuses(report) == {"1v3_AQ26jZ0": "refetch_failed", "v6CuYULP3tM": ""}
    assert chroma["deleted"] == []
    assert _cached(db, "1v3_AQ26jZ0").language == "bn"


def test_language_names_are_treated_as_whisper():
    assert rd._is_whisper("english", None)
    assert rd._is_whisper("hi", "whisper")
    assert not rd._is_whisper("en-US", "youtube")
    assert not rd._is_whisper("zh-Hans", None)
