"""S-1.14.6 — the search candidate pool is persisted, not discarded.

D-055 could not re-rank a real 200-video job because the ~217 candidates
that ranking rejected had never been stored anywhere; selection quality had
to be audited against stated criteria instead of measured head-to-head.
"""
from unittest.mock import patch

from app.agents import search_agent
from app.models.job_search_candidate import JobSearchCandidate
from app.tasks.job_tasks import _persist_search_candidates


def _cand(vid: str, title: str = "t", chan: str = "c") -> dict:
    return {
        "video_id": vid,
        "title": title,
        "channel_name": chan,
        "channel_id": f"UC{vid}",
        "published_at": "2026-01-01T00:00:00Z",
        "duration_seconds": 600,
    }


def test_persists_pool_with_selected_flag(db) -> None:
    from app.models.job import Job

    job = Job(id="job-cand-1", job_type="topic", topic="t", status="searching")
    db.add(job)
    db.commit()

    pool = [_cand("v1"), _cand("v2"), _cand("v3")]
    curated = [_cand("v2")]
    _persist_search_candidates(db, "job-cand-1", pool, curated)

    rows = (
        db.query(JobSearchCandidate)
        .filter(JobSearchCandidate.job_id == "job-cand-1")
        .all()
    )
    assert len(rows) == 3
    by_id = {r.video_id: r for r in rows}
    assert by_id["v2"].selected is True
    # The rejects are the point — they must survive.
    assert by_id["v1"].selected is False
    assert by_id["v3"].selected is False
    assert by_id["v1"].payload_json and "UCv1" in by_id["v1"].payload_json


def test_persistence_failure_never_breaks_the_job(db) -> None:
    """A diagnostic write must not sink a job that otherwise succeeded."""
    with patch("app.models.job_search_candidate.JobSearchCandidate", side_effect=RuntimeError("boom")):
        # Should swallow and return rather than propagate.
        _persist_search_candidates(db, "job-missing", [_cand("v1")], [])


def test_empty_pool_is_a_noop(db) -> None:
    _persist_search_candidates(db, "job-empty", [], [])
    assert (
        db.query(JobSearchCandidate)
        .filter(JobSearchCandidate.job_id == "job-empty")
        .count()
        == 0
    )


def test_run_search_agent_exposes_the_pool_without_changing_its_return() -> None:
    """``candidates_out`` is additive: the 3-tuple contract is unchanged, so
    existing callers and their tests keep working."""
    discovered = [_cand("a"), _cand("b"), _cand("c")]
    curated = [_cand("b")]

    class _FakeGraph:
        def stream(self, state, stream_mode=None):
            yield {"execute_searches": {"discovered_videos": discovered}}
            yield {"rank_and_curate": {"curated_videos": curated, "search_queries_used": ["q"]}}

    pool: list[dict] = []
    with patch.object(search_agent, "build_search_graph", return_value=_FakeGraph()):
        result = search_agent.run_search_agent(
            topic="t", num_videos=1, candidates_out=pool
        )

    assert isinstance(result, tuple) and len(result) == 3
    curated_out, queries, _unresolved = result
    assert [v["video_id"] for v in curated_out] == ["b"]
    assert queries == ["q"]
    # The full pool, including the two rejects, came back out of band.
    assert [v["video_id"] for v in pool] == ["a", "b", "c"]


def test_candidates_out_omitted_is_still_fine() -> None:
    class _FakeGraph:
        def stream(self, state, stream_mode=None):
            yield {"rank_and_curate": {"curated_videos": [_cand("z")]}}

    with patch.object(search_agent, "build_search_graph", return_value=_FakeGraph()):
        curated, _q, _u = search_agent.run_search_agent(topic="t", num_videos=1)
    assert [v["video_id"] for v in curated] == ["z"]
