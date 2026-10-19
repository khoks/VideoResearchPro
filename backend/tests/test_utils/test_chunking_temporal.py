"""Numeric publish fields + discussed era in chunk metadata (T-1.17.1.6 / S-1.17.2).

Chroma cannot range-filter an ISO string; it can an int. Unknown values are
OMITTED, not sentinel-valued, so `{"published_ts": {"$gte": ...}}` excludes
undated chunks instead of matching them against 1970.
"""
from datetime import datetime, timezone

from app.utils.chunking import chunk_transcript

SEGS = [{"text": "Hello world. This is a test.", "start": 0.0, "duration": 5.0}]


def _meta(chunks):
    return chunks[0]["metadata"]


def test_numeric_publish_fields_from_datetime():
    md = _meta(chunk_transcript(SEGS, video_metadata={
        "video_id": "v", "published_at": datetime(2025, 3, 12, 10, tzinfo=timezone.utc),
    }))
    assert md["published_ts"] == int(datetime(2025, 3, 12, 10, tzinfo=timezone.utc).timestamp())
    assert md["published_year"] == 2025
    assert isinstance(md["published_ts"], int) and isinstance(md["published_year"], int)


def test_numeric_publish_fields_from_iso_string_with_z():
    md = _meta(chunk_transcript(SEGS, video_metadata={"video_id": "v", "published_at": "2024-06-01T00:00:00Z"}))
    assert md["published_year"] == 2024
    assert md["published_ts"] == int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp())
    assert md["published_at"] == "2024-06-01T00:00:00Z", "the ISO string is untouched"


def test_naive_datetime_is_read_as_utc():
    md = _meta(chunk_transcript(SEGS, video_metadata={"video_id": "v", "published_at": datetime(2024, 6, 1)}))
    assert md["published_ts"] == int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp())


def test_unknown_or_unparseable_date_omits_numeric_keys():
    for value in (None, "", "not a date"):
        md = _meta(chunk_transcript(SEGS, video_metadata={"video_id": "v", "published_at": value}))
        assert "published_ts" not in md and "published_year" not in md


def test_era_fields_pass_through_flat():
    md = _meta(chunk_transcript(SEGS, video_metadata={
        "video_id": "v",
        "discussed_era": {"era_start": 2019, "era_end": 2021, "era_confidence": 0.8, "is_retrospective": True},
    }))
    assert (md["era_start"], md["era_end"]) == (2019, 2021)
    assert md["era_confidence"] == 0.8 and md["is_retrospective"] is True


def test_missing_or_malformed_era_omits_keys():
    for value in (None, {}, "2019", ["x"]):
        md = _meta(chunk_transcript(SEGS, video_metadata={"video_id": "v", "discussed_era": value}))
        assert "era_start" not in md


def test_all_metadata_values_remain_chroma_scalars():
    md = _meta(chunk_transcript(SEGS, video_metadata={
        "video_id": "v", "published_at": "2024-06-01T00:00:00Z",
        "discussed_era": {"era_start": 2019, "era_end": 2021, "era_confidence": 0.8, "is_retrospective": True},
    }))
    assert all(isinstance(v, (str, int, float, bool)) for v in md.values())
