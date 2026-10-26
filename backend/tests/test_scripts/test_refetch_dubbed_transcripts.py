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


def _statuses(report):
    return {r["video_id"]: r["status"] for r in report["rows"]}


def test_dry_run_lists_only_the_dubbed_transcripts_and_writes_nothing(db, library):
    sleeps = []
    api = _MultiApi(library["by_video"])
    report = rd.run(db, ytt_api=api, sleep=sleeps.append)

    assert report["mode"] == "dry_run"
    assert report["skipped"] == {"whisper": 1, "already_checked": 1}
    assert _statuses(report) == {
        "1v3_AQ26jZ0": "refetch",          # Bengali dub of a Hindi lecture
        "v6CuYULP3tM": "refetch",          # English dub, nothing declared
        "J-HV7gNVdd0": "ok_declared",      # cached in the declared language
        "IcVYyF3EEbk": "ok_declared",
        "IbcYNtZ8HZY": "ok",               # listed: declared en, cached hi, hi is right
        "onlyDubs01": "no_spoken_track",
    }
    row = next(r for r in report["rows"] if r["video_id"] == "1v3_AQ26jZ0")
    assert (row["chosen_language"], row["chosen_kind"]) == ("hi", "asr")
    assert row["skipped_dubbed"] == ["bn", "en-US"]

    # Tracks listed only where a dub was possible, paced per D-051.
    assert sorted(api._fetcher.listed) == ["1v3_AQ26jZ0", "IbcYNtZ8HZY", "onlyDubs01", "v6CuYULP3tM"]
    assert len(sleeps) == 3 and all(s >= 3.0 for s in sleeps)
    # Dry run: no quota-log row, no transcript downloaded, nothing changed.
    assert library["declared_calls"][0][1] is False
    assert api._fetcher._http_client.fetched == []
    cached = db.query(TranscriptCache).filter(TranscriptCache.video_id == "1v3_AQ26jZ0").one()
    assert cached.language == "bn"
    db.expire_all()
    doc = db.query(Document).filter(Document.video_id == "1v3_AQ26jZ0").one()
    assert doc.transcript_language == "bn" and doc.source_metadata_json is None


def test_dry_run_stops_at_the_first_ip_block(db, library):
    api = _MultiApi(library["by_video"], block_on="IbcYNtZ8HZY")
    report = rd.run(db, ytt_api=api, sleep=lambda s: None)
    assert report["stopped"] and "IP-block" in report["stopped"]
    assert api._fetcher.listed[-1] == "IbcYNtZ8HZY"
    assert "v6CuYULP3tM" not in api._fetcher.listed  # after the block, in id order


def test_write_mode_replaces_the_transcript_and_the_chunks(db, library, monkeypatch):
    from app.services import chroma_service
    from tests import conftest as _conftest

    monkeypatch.setattr(youtube_service, "SessionLocal", _conftest.TestingSessionLocal)
    deleted, inserted = [], []
    monkeypatch.setattr(chroma_service, "delete_video_chunks", lambda vid: deleted.append(vid) or True)
    monkeypatch.setattr(chroma_service, "insert_chunks", lambda chunks: inserted.extend(chunks) or len(chunks))

    api = _MultiApi(library["by_video"])
    report = rd.run(db, video_ids=["1v3_AQ26jZ0"], write=True, ytt_api=api, sleep=lambda s: None)

    assert _statuses(report) == {"1v3_AQ26jZ0": "refetched"}
    assert library["declared_calls"][0][1] is True  # write mode logs its quota
    db.expire_all()
    cached = db.query(TranscriptCache).filter(TranscriptCache.video_id == "1v3_AQ26jZ0").one()
    assert cached.language == "hi"
    assert json.loads(cached.segments_json)[0]["text"] == TRACK_TEXT["hi"]
    doc = db.query(Document).filter(Document.video_id == "1v3_AQ26jZ0").one()
    assert doc.transcript_language == "hi"
    assert json.loads(doc.source_metadata_json)["caption_track"]["language"] == "hi"
    assert deleted == ["1v3_AQ26jZ0"]
    assert inserted and all(TRACK_TEXT["hi"] in c["text"] for c in inserted)


def test_language_names_are_treated_as_whisper():
    assert rd._is_whisper("english", None)
    assert rd._is_whisper("hi", "whisper")
    assert not rd._is_whisper("en-US", "youtube")
    assert not rd._is_whisper("zh-Hans", None)
