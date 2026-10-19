"""Era extraction at ingest (R3 / S-1.17.2): wired, cached, fail-soft."""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.tasks import job_tasks
from app.tasks.job_tasks import _build_video_metadata, _ensure_era


def _doc(**over) -> SimpleNamespace:
    base = {
        "video_id": "abc123", "title": "Sample", "channel_name": "Ch", "channel_id": "UC",
        "url": "https://youtube.com/watch?v=abc123", "published_at": None, "duration_seconds": 1,
        "transcript_language": "en", "source_type": "video", "source_id": "abc123",
        "source_url": "https://youtube.com/watch?v=abc123", "source_metadata_json": {},
        "description": None, "discussed_era_json": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_build_video_metadata_flattens_a_known_era():
    doc = _doc(discussed_era_json=json.dumps(
        {"era_start": 2019, "era_end": 2021, "era_confidence": 0.8, "is_retrospective": True}
    ))
    md = _build_video_metadata(doc, language=None)
    assert md["discussed_era"] == {
        "era_start": 2019, "era_end": 2021, "era_confidence": 0.8, "is_retrospective": True,
    }


def test_build_video_metadata_without_era_is_empty_dict():
    assert _build_video_metadata(_doc(), language=None)["discussed_era"] == {}


def test_ensure_era_delegates_and_never_raises():
    doc = _doc()
    with patch.object(job_tasks.temporal_service, "ensure_discussed_era", return_value={"era_start": 2020}) as ens:
        _ensure_era(None, doc, [{"text": "x"}], "job1")
    ens.assert_called_once_with(None, doc, [{"text": "x"}])

    with patch.object(job_tasks.temporal_service, "ensure_discussed_era", side_effect=RuntimeError("boom")):
        _ensure_era(None, doc, [{"text": "x"}], "job1")  # must not raise


def test_every_chunking_site_in_the_job_loops_runs_era_extraction_first():
    """Source-level guard: each `chunk_transcript(_with_visuals(...))` call in
    the ingest loops is preceded by `_ensure_era(...)` for the same segments,
    so new chunks carry the era. A new ingest path that forgets it fails here."""
    src = Path(job_tasks.__file__).read_text(encoding="utf-8")
    sites = list(re.finditer(
        r"_ensure_era\(db, video, (\w+), job_id\)\n\s+chunks = chunk_transcript\(\n\s+_with_visuals\(db, job, video, (\w+),",
        src,
    ))
    total = len(re.findall(r"chunks = chunk_transcript\(\n\s+_with_visuals\(", src))
    assert total >= 6
    assert len(sites) == total, "a chunk_transcript site is missing its _ensure_era call"
    assert all(m.group(1) == m.group(2) for m in sites), "era extracted from different segments than chunked"
