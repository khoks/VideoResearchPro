"""S-1.14.6: the report pipeline's map/reduce intermediates are persisted,
losslessly, and nothing is written when the setting is off.

The pipeline used to keep these only in LangGraph state, so a map regression
was invisible unless it spoiled the finished report. These tests run the
real graph with fake LLMs (no providers), persist through the job task's
own function, and read the rows back.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agents import report_agent
from app.models.job import Job
from app.models.job_report_intermediate import (
    MAP_FAILED,
    MAP_PARSED,
    MAP_UNPARSED,
    STAGE_MAP,
    STAGE_REDUCE,
    JobReportIntermediate,
)
from app.tasks import job_tasks
from app.tasks.job_tasks import _persist_report_intermediates, _report_intermediates_sink

KEYS = ("facts", "comments", "conclusions", "references", "speakers")


def _chunk(i: int, vid: str) -> dict:
    return {
        "text": f"chunk number {i} of video {vid} " * 3,
        "metadata": {
            "video_id": vid,
            "video_title": f"Video {vid}",
            "channel_name": "Ch",
            "video_url": f"https://www.youtube.com/watch?v={vid}",
            "timestamp_start": float(i * 60),
            "timestamp_end": float(i * 60 + 60),
            "word_count": 18,
        },
    }


class _MapLLM:
    """Fake map model: per call, one fact + one comment per chunk header in
    the prompt, plus a repeat of the first fact so reduce has an exact
    duplicate to collapse (the only thing the lossless union may remove)."""

    def __init__(self, fail_on_calls: set[int] | None = None, garbage_on_calls: set[int] | None = None):
        self.calls = 0
        self.fail_on_calls = fail_on_calls or set()
        self.garbage_on_calls = garbage_on_calls or set()

    def invoke(self, messages):
        self.calls += 1
        if self.calls in self.fail_on_calls:
            raise RuntimeError("provider 500")
        if self.calls in self.garbage_on_calls:
            return MagicMock(content="not json at all")
        prompt = messages[0].content
        heads = re.findall(r"\[Video (v\d+) \| Ch \| (\d+:\d+)", prompt)
        facts, comments = [], []
        for vid, ts in heads:
            base = {
                "video_title": f"Video {vid}", "channel_name": "Ch",
                "video_url": f"https://www.youtube.com/watch?v={vid}",
                "timestamp_display": ts, "timestamp_seconds": 0,
            }
            facts.append({**base, "content": f"fact {vid} {ts} call{self.calls}"})
            comments.append({**base, "content": f"comment {vid} {ts} call{self.calls}"})
        if facts:
            facts.append(dict(facts[0]))  # exact duplicate
        return MagicMock(content=json.dumps({
            "facts": facts, "comments": comments,
            "conclusions": [], "references": [], "speakers": [],
        }))


def _small_batches(use_case, fraction=report_agent._WINDOW_SAFETY_FRACTION):
    """Map batches of ~2 chunks; compose budget generous."""
    return 120 if use_case == "report_map_chunks" else 100_000


def _run(chunks, map_llm, intermediates):
    with patch.object(report_agent, "_batch_budget", side_effect=_small_batches), \
         patch.object(report_agent, "get_llm_for", return_value=map_llm), \
         patch.object(report_agent, "_invoke_with_retry", return_value="<h2>S</h2><p>x</p>"):
        return report_agent.run_report_agent(
            "topic", "t", chunks, intermediates_out=intermediates
        )


@pytest.fixture
def job(db):
    j = Job(job_type="topic", topic="t", status="completed", num_videos=3)
    db.add(j)
    db.commit()
    return j


def test_pipeline_rows_are_written_and_lossless(db, job):
    chunks = [_chunk(i, f"v{i % 3}") for i in range(7)]
    intermediates: dict = {}
    _run(chunks, _MapLLM(), intermediates)

    written = _persist_report_intermediates(db, job.id, intermediates)
    rows = db.query(JobReportIntermediate).filter_by(job_id=job.id).all()
    maps = [r for r in rows if r.stage == STAGE_MAP]
    reduce_rows = [r for r in rows if r.stage == STAGE_REDUCE]

    assert written == len(rows) == len(maps) + 1
    assert len(maps) >= 3, "small budget must produce several batches"
    assert len(reduce_rows) == 1 and len({r.run_id for r in rows}) == 1
    assert all(r.status == MAP_PARSED for r in maps)
    assert sum(r.chunk_count for r in maps) == len(chunks), "every chunk accounted for"

    # Each map row's payload round-trips to exactly what it says it holds.
    for r in maps:
        payload = json.loads(r.payload_json)
        assert sum(len(payload[k]) for k in KEYS) == r.item_count
        assert json.loads(r.notes_json)["videos"]

    # Lossless: map items in == reduce items out + exact duplicates collapsed.
    red = reduce_rows[0]
    notes = json.loads(red.notes_json)
    map_total = sum(r.item_count for r in maps)
    assert notes["reduce_items_in"] == map_total
    assert red.item_count == map_total - notes["reduce_exact_duplicates_collapsed"]
    assert notes["reduce_exact_duplicates_collapsed"] == len(maps)  # one planted per call
    assert red.status == "lossless" and notes["reduce_items_trimmed"] == 0

    # Content-level: every distinct map item is in the reduced payload.
    def ident(item):
        return (item["video_url"], item["content"])
    map_items = {ident(i) for r in maps for k in KEYS for i in json.loads(r.payload_json)[k]}
    reduced = json.loads(red.payload_json)
    red_items = {ident(i) for k in KEYS for i in reduced[k]}
    assert map_items == red_items


def test_failed_and_unparsed_batches_are_recorded_not_absent(db, job):
    """A dropped batch must show up as a row — absence is what hid regressions."""
    chunks = [_chunk(i, f"v{i}") for i in range(6)]
    # Call 1 fails (bisect: calls 2, 3 are its halves); call 3 fails too, so
    # half 1 of batch 0 is lost. Call 4 returns non-JSON.
    llm = _MapLLM(fail_on_calls={1, 3}, garbage_on_calls={4})
    intermediates: dict = {}
    _run(chunks, llm, intermediates)
    _persist_report_intermediates(db, job.id, intermediates)

    maps = (
        db.query(JobReportIntermediate)
        .filter_by(job_id=job.id, stage=STAGE_MAP)
        .order_by(JobReportIntermediate.batch_index, JobReportIntermediate.sub_index)
        .all()
    )
    b0 = [r for r in maps if r.batch_index == 0]
    assert [(r.sub_index, r.status) for r in b0] == [(0, MAP_PARSED), (1, MAP_FAILED)]
    failed = b0[1]
    assert failed.payload_json is None and failed.item_count == 0
    assert "provider 500" in json.loads(failed.notes_json)["error"]
    assert failed.chunk_count >= 1
    assert any(r.status == MAP_UNPARSED for r in maps)
    assert sum(r.chunk_count for r in maps) == len(chunks)


def test_records_are_frozen_before_compose_mutates_items(db, job):
    """Compose adds keys to the same item dicts map produced (quote forms,
    modality tags). The audit record must hold what map EMITTED."""
    intermediates: dict = {}
    original = report_agent._attach_quote_forms

    def tamper(consolidated, forms):
        for items in consolidated.values():
            for it in items:
                it["tampered"] = True
        return original(consolidated, forms)

    with patch.object(report_agent, "_attach_quote_forms", side_effect=tamper):
        _run([_chunk(i, "v1") for i in range(3)], _MapLLM(), intermediates)
    _persist_report_intermediates(db, job.id, intermediates)
    for r in db.query(JobReportIntermediate).filter_by(job_id=job.id).all():
        assert "tampered" not in (r.payload_json or "")


def test_each_run_gets_its_own_run_id(db, job):
    for _ in range(2):
        intermediates: dict = {}
        _run([_chunk(i, "v1") for i in range(3)], _MapLLM(), intermediates)
        _persist_report_intermediates(db, job.id, intermediates)
    runs = {r.run_id for r in db.query(JobReportIntermediate).filter_by(job_id=job.id)}
    assert len(runs) == 2


# ---------- setting off ------------------------------------------------------

def test_setting_off_captures_and_writes_nothing(db, job):
    with patch.object(job_tasks.settings, "REPORT_INTERMEDIATES_ENABLED", False):
        sink = _report_intermediates_sink()
        assert sink is None
        _run([_chunk(i, "v1") for i in range(3)], _MapLLM(), sink)
        # Even a caller that captured anyway writes nothing while it is off.
        captured: dict = {}
        _run([_chunk(i, "v1") for i in range(3)], _MapLLM(), captured)
        assert captured["map"], "capture itself works"
        assert _persist_report_intermediates(db, job.id, captured) == 0
    assert db.query(JobReportIntermediate).count() == 0


def test_setting_on_sink_is_a_dict():
    with patch.object(job_tasks.settings, "REPORT_INTERMEDIATES_ENABLED", True):
        assert _report_intermediates_sink() == {}


def test_persist_is_best_effort(job):
    broken = MagicMock()
    broken.bulk_save_objects.side_effect = RuntimeError("disk full")
    intermediates = {"map": [{"batch_index": 0, "sub_index": None, "status": "parsed",
                              "chunk_count": 1, "item_count": 0, "payload_json": "{}",
                              "notes_json": "{}", "model": "m"}], "reduce": None}
    assert _persist_report_intermediates(broken, job.id, intermediates) == 0
    broken.rollback.assert_called_once()


def test_channel_jobs_produce_no_intermediates():
    intermediates: dict = {}
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content='{"channel_name": "Ch", "themes": [], "highlights": []}')
    with patch.object(report_agent, "get_llm_for", return_value=llm):
        report_agent.run_report_agent("channel", "c", [_chunk(0, "v1")], intermediates_out=intermediates)
    assert intermediates == {"map": [], "reduce": None}


def test_the_job_task_wires_capture_and_persistence():
    """Source-level guard, like test_ensure_era: the production caller passes
    the sink and persists it. A refactor that drops either fails here."""
    src = Path(job_tasks.__file__).read_text(encoding="utf-8")
    calls = re.findall(r"run_report_agent\((.*?)\n\s+\)", src, re.S)
    assert calls, "run_report_agent call not found"
    assert all("intermediates_out=report_intermediates" in c for c in calls)
    assert "report_intermediates = _report_intermediates_sink()" in src
    assert "_persist_report_intermediates(db, job_id, report_intermediates)" in src


def test_audit_script_reads_the_rows_back(db, job, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "audit_report_intermediates",
        Path(__file__).resolve().parents[2] / "scripts" / "audit_report_intermediates.py",
    )
    audit_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit_mod)

    intermediates: dict = {}
    _run([_chunk(i, f"v{i % 2}") for i in range(5)], _MapLLM(), intermediates)
    _persist_report_intermediates(db, job.id, intermediates)

    assert audit_mod.audit(db, job.id[:8], None, show_batches=True) == 0
    out = capsys.readouterr().out
    assert "1 run(s)" in out and "reduce: lossless" in out
    assert "matches" in out and "DOES NOT match" not in out
    assert "per-batch:" in out
