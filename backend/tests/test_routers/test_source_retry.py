"""T-1.5.11.2 at the caller: one retry before a source counts as failed.

``POST /api/v1/jobs`` writes the run, the real ``execute_topic_job`` runs it
through the real connectors and clients, and ``GET /api/v1/jobs/{id}`` is
what the reader sees. Only ``httpx.get``, the search agent and the backoff's
sleep are faked. The fixtures are the quiet-sources suite's (S-1.5.14).
"""
from __future__ import annotations

import httpx
import pytest

from app.models.source_refusal import SourceRefusal
from app.services import source_refusal_service
from app.sources import _http_retry
from app.sources.bluesky import client as bluesky_client
from app.sources.hn import client as hn_client
from tests.test_routers.test_quiet_sources import (  # noqa: F401  (fixtures)
    _no_pacing,
    _notes,
    _submit,
    worker,
)


def _answer(status: int, url: str, json: object | None = None) -> httpx.Response:
    return httpx.Response(status, json=json if json is not None else {}, request=httpx.Request("GET", url))


@pytest.fixture
def no_backoff(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(_http_retry, "_sleep", slept.append)
    return slept


@pytest.fixture
def hn(monkeypatch):
    """Hacker News answers ``hn.answers`` in turn, then the last one forever."""
    state = type("HN", (), {})()
    state.answers = []
    state.calls = 0

    def http_get(url, params=None, headers=None, timeout=None):
        state.calls += 1
        status = state.answers.pop(0) if len(state.answers) > 1 else state.answers[0]
        return _answer(status, url, {"hits": []})

    monkeypatch.setattr(hn_client.httpx, "get", http_get)
    monkeypatch.setattr(hn_client.HNClient, "__init__", _no_pacing, raising=True)
    hn_client._reset_for_tests()
    yield state
    hn_client._reset_for_tests()


@pytest.fixture
def holds(monkeypatch):
    """Every hold the run starts, as ``(source_type, status)``."""
    started: list[tuple[str, int]] = []
    real = source_refusal_service.record

    def record(db, source_type, status_code):
        started.append((source_type, status_code))
        real(db, source_type, status_code)

    monkeypatch.setattr(source_refusal_service, "record", record)
    return started


def _source_notes(client, job_id: str, source_type: str) -> list[dict]:
    return [n for n in _notes(client, job_id) if n.get("source_type") == source_type]


def test_a_503_then_an_answer_is_an_answer(client, db, worker, hn, no_backoff):
    """Without the retry this run would say Hacker News was unavailable."""
    hn.answers = [503, 200]
    job_id = _submit(client, "video", "hn_story", num_videos=4)

    worker.run(job_id)

    notes = _source_notes(client, job_id, "hn_story")
    assert [n["kind"] for n in notes] == ["source_empty"], notes
    assert no_backoff == [_http_retry.BACKOFF_SECONDS]


def test_two_503s_are_one_failure_on_the_run_and_no_hold(client, db, worker, hn, no_backoff, holds):
    hn.answers = [503]
    job_id = _submit(client, "video", "hn_story", num_videos=4)

    worker.run(job_id)

    notes = _source_notes(client, job_id, "hn_story")
    assert len(notes) == 1, notes
    assert notes[0]["kind"] == "source_unavailable"
    assert "HTTP 503" in notes[0]["text"]
    assert hn.calls == 2, "one try and one retry, then the search failed"
    assert holds == [], "a 503 says nothing about this install"


def test_a_refusal_is_asked_once_and_held_once(client, db, worker, monkeypatch, no_backoff, holds):
    """D-141: a 403 starts the hold. It is not retried, so the run hears it
    once and records it once."""
    calls: list[str] = []

    def http_get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        return _answer(403, url)

    monkeypatch.setattr(bluesky_client.httpx, "get", http_get)
    monkeypatch.setattr(bluesky_client.BlueskyClient, "__init__", _no_pacing, raising=True)
    bluesky_client._reset_for_tests()
    job_id = _submit(client, "video", "bluesky_post", num_videos=4)

    worker.run(job_id)

    bluesky_client._reset_for_tests()
    assert len(calls) == 1
    assert no_backoff == []
    assert holds == [("bluesky_post", 403)]
    assert db.query(SourceRefusal).filter_by(source_type="bluesky_post").count() == 1
    assert len(_source_notes(client, job_id, "bluesky_post")) == 1


def test_a_429_with_no_short_retry_after_is_reported_as_rate_limited_once(
    client, db, worker, hn, no_backoff, holds
):
    hn.answers = [429]
    job_id = _submit(client, "video", "hn_story", num_videos=4)

    worker.run(job_id)

    notes = _source_notes(client, job_id, "hn_story")
    assert len(notes) == 1 and "slow down (HTTP 429)" in notes[0]["text"], notes
    assert hn.calls == 1
    assert holds == []
