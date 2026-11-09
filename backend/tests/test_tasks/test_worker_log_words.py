"""T-4.11.4.2: the worker's log holds no user's words, read where it is written.

``POST /api/v1/jobs`` writes a topic run with a topic, search instructions and
two named channels, one a pasted link with a share token in it and one a name.
The real ``execute_topic_job`` runs its search phase through the real search
agent, the real ``youtube_service`` and the real Hacker News, Mastodon and
Bluesky clients. Only the network is faked: YouTube answers every search with
an ``HttpError`` that quotes its request, as Google's client does, and the
other sources answer 5xx through a real ``httpx.Client``, so httpx writes its
own request lines and ``raise_for_status`` quotes the URL. A handler on the
root logger at INFO, with Celery's own formatter, is what the worker writes,
and none of the user's words may be in it. The words stay on the run's row,
which is the user's to read.

The channel and subscription runs, and ``_handle_failure``'s fallback, are
checked at the task with a patched logger.
"""
from __future__ import annotations

import io
import json
import logging
from unittest.mock import MagicMock

import httpx
import pytest
from celery.utils.log import ColorFormatter

from app.agents import search_agent
from app.models.job import Job
from app.services import connector_dispatch, quota_service, youtube_service
from app.sources import _http_retry
from app.sources.bluesky import client as bluesky_client
from app.sources.hn import client as hn_client
from app.sources.mastodon import client as mastodon_client
from app.tasks import job_tasks
from tests.test_routers.test_quiet_sources import (  # noqa: F401  (fixtures)
    _REAL_SEARCH_AGENT,
    _no_pacing,
    worker,
)
from tests.test_services.test_worker_log_call_sites import FakeYouTube, said

TOPIC = "Zanzibar quokka fermentation"
INSTRUCTIONS = "Prefer xylophonic field recordings"
LINK = "https://www.youtube.com/@stoatlab?si=SHAREtoken123"
NAME = "Wombat Brewing Society"
FORBIDDEN = ("zanzibar", "quokka", "fermentation", "xylophonic", "sharetoken123", "wombat")

# Celery's worker format (``worker_log_format``), on the root logger at INFO.
CELERY_FORMAT = "[%(asctime)s: %(levelname)s/%(processName)s] %(message)s"


@pytest.fixture
def worker_log():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(ColorFormatter(CELERY_FORMAT, use_color=False))
    root = logging.getLogger()
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(level)


@pytest.fixture
def search_phase(worker, monkeypatch):
    """The real search agent with a planner that writes queries from the
    topic, YouTube refusing every search, and three sources answering 5xx."""
    planner = {"broad_queries": [f"{TOPIC} history", f"{TOPIC} today"], "channel_keywords": []}

    def llm(use_case, **kwargs):
        fake = MagicMock()
        fake.invoke.return_value = MagicMock(content=json.dumps(planner))
        return fake

    monkeypatch.setattr(search_agent, "run_search_agent", _REAL_SEARCH_AGENT)
    monkeypatch.setattr(search_agent, "get_llm_for", llm)
    monkeypatch.setattr(search_agent, "_lookup_known_eras", lambda ids: {})
    youtube = FakeYouTube()
    monkeypatch.setattr(youtube_service, "get_youtube_client", lambda: youtube)
    monkeypatch.setattr(quota_service, "record", lambda *a, **kw: None)

    status = {"hn.algolia.com": 503, "mastodon": 500, "bsky": 500}
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        code = next((c for host, c in status.items() if host in request.url.host), 500)
        return httpx.Response(code, json={})

    real_client = httpx.Client

    def http_get(url, **kwargs):
        kwargs.pop("timeout", None)
        with real_client(transport=httpx.MockTransport(answer)) as client:
            return client.get(url, **kwargs)

    monkeypatch.setattr(httpx, "get", http_get)
    monkeypatch.setattr(_http_retry, "_sleep", lambda seconds: None)
    for module, cls in (
        (hn_client, hn_client.HNClient),
        (mastodon_client, mastodon_client.MastodonClient),
        (bluesky_client, bluesky_client.BlueskyClient),
    ):
        monkeypatch.setattr(cls, "__init__", _no_pacing, raising=True)
        module._reset_for_tests()
    yield {"youtube": youtube, "asked": asked}
    for module in (hn_client, mastodon_client, bluesky_client):
        module._reset_for_tests()


def _run_topic_search(client, worker) -> str:
    r = client.post("/api/v1/jobs", json={
        "job_type": "topic",
        "topic": TOPIC,
        "search_instructions": INSTRUCTIONS,
        "preferred_channels": [LINK, NAME],
        "num_videos": 8,
        "source_types": ["video", "hn_story", "mastodon_post", "bluesky_post"],
    })
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    worker.run(job_id)
    return job_id


def test_a_topic_runs_search_phase_writes_none_of_the_users_words(client, db, worker, search_phase, worker_log):
    job_id = _run_topic_search(client, worker)

    # The requests did carry the words, so the log had the chance to.
    youtube = search_phase["youtube"]
    assert LINK in youtube.queries and NAME in youtube.queries
    assert any(TOPIC in q for q in youtube.queries)
    assert any("zanzibar" in url.lower() for url in search_phase["asked"])

    written = worker_log.getvalue()
    lowered = written.lower()
    for word in FORBIDDEN:
        assert word not in lowered, f"{word!r} reached the worker's log:\n{written}"

    # And the lines an operator needs are still there.
    for line in (
        f"[job:{job_id}] Topic job starting: topic of {len(TOPIC)} characters",
        "resolve_channel_id: input is a link on www.youtube.com",
        "resolve_channel_id: handle @stoatlab not found via API",
        "resolve_preferred_channels: a link on www.youtube.com raised, skipping",
        "resolve_preferred_channels: a name of 22 characters raised, skipping",
        "YouTube API search failed: HttpError 400 (badRequest)",
        "broad search 1 of 2 failed; skipping",
        "googleapiclient.errors.HttpError",
        "hn.algolia.com: 503; trying once more",
        "dispatch_search: connector 'hn_story' raised during search() (failed, HTTP 503)",
        "httpx.HTTPStatusError",
        f"[job:{job_id}] YouTube search unavailable: HttpError",
        f"[job:{job_id}] No candidates found across source_types=",
    ):
        assert line in written, f"missing {line!r}:\n{written}"

    # The words are on the row, for the user who wrote them.
    db.expire_all()
    job = db.get(Job, job_id)
    assert job.status == "failed"
    assert TOPIC in job.error_message


def test_the_check_sees_a_leak(client, db, worker, search_phase, worker_log, monkeypatch):
    """The mutation: one call site back to the exception's text, and the same
    run writes the topic. So the check above can fail."""
    monkeypatch.setattr(connector_dispatch, "traceback_without_text", lambda e: str(e))

    _run_topic_search(client, worker)

    assert "zanzibar" in worker_log.getvalue().lower()


# ---------------------------------------------------------------------------
# Channel and subscription runs, at the task
# ---------------------------------------------------------------------------

@pytest.fixture
def job_log(monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(job_tasks, "logger", log)
    return log


def _channel_run(db, job_type: str) -> Job:
    job = Job(job_type=job_type, topic=None, num_videos=2, videos_per_channel=2,
              channel_list=json.dumps([LINK, NAME]), tenant_id="tenant-log-words")
    db.add(job)
    db.commit()
    return job


@pytest.mark.parametrize("job_type, task", [
    ("channel", "execute_channel_job"),
    ("subscription", "execute_subscription_job"),
])
def test_an_unresolved_channel_is_named_by_kind(db, worker, job_log, monkeypatch, job_type, task):
    youtube = FakeYouTube(search_items=[])
    monkeypatch.setattr(youtube_service, "get_youtube_client", lambda: youtube)
    monkeypatch.setattr(quota_service, "record", lambda *a, **kw: None)
    job = _channel_run(db, job_type)

    getattr(job_tasks, task).run(job.id)

    text = said(job_log)
    for word in FORBIDDEN:
        assert word not in text, f"{word!r}:\n{text}"
    assert "could not resolve channel 1 (a link on www.youtube.com), skipping" in text
    assert "could not resolve channel 2 (a name of 22 characters), skipping" in text
    db.expire_all()
    assert db.get(Job, job.id).status == "failed"


@pytest.mark.parametrize("job_type, task", [
    ("channel", "execute_channel_job"),
    ("subscription", "execute_subscription_job"),
])
def test_a_channel_search_that_raises_is_logged_without_its_words(db, worker, job_log, monkeypatch, job_type, task):
    """resolve_channel_id's search fallback raises an HttpError quoting the
    channel name; the run's failure line keeps the type and the frames."""
    youtube = FakeYouTube()  # every search raises
    monkeypatch.setattr(youtube_service, "get_youtube_client", lambda: youtube)
    monkeypatch.setattr(quota_service, "record", lambda *a, **kw: None)
    job = _channel_run(db, job_type)

    getattr(job_tasks, task).run(job.id)

    text = said(job_log)
    for word in (*FORBIDDEN, "googleapis"):
        assert word not in text, f"{word!r}:\n{text}"
    assert "failed" in text and "googleapiclient.errors.httperror" in text
    assert "resolve_channel_id" in text, "the frames say where"
    db.expire_all()
    assert db.get(Job, job.id).status == "failed"


def test_handle_failures_fallback_names_neither_the_error_nor_its_values(db, job_log, monkeypatch):
    """When recording the failure fails, the line says how long the error was
    and where the write broke. A database error quotes its statement's values,
    the error among them."""
    error = f"No candidates found for topic '{TOPIC}' across source_types=['video']."

    def broken_update(db_, job, **fields):
        raise RuntimeError(f"(sqlite3.OperationalError) database is locked [parameters: ({fields['error_message']!r},)]")

    def broken_session():
        raise RuntimeError(f"cannot open a session to record {error!r}")

    job = Job(job_type="topic", topic=TOPIC, num_videos=1, tenant_id="tenant-log-words")
    db.add(job)
    db.commit()
    monkeypatch.setattr(job_tasks, "_update_job", broken_update)
    monkeypatch.setattr(job_tasks, "SessionLocal", broken_session)
    monkeypatch.setattr(job_tasks.progress_service, "publish_error", lambda *a, **kw: None)

    job_tasks._handle_failure(db, job.id, error)

    text = said(job_log)
    for word in FORBIDDEN:
        assert word not in text, f"{word!r}:\n{text}"
    assert f"recording an error of {len(error)} characters" in text
    assert "fresh-session fallback also failed" in text
    assert text.count("runtimeerror") >= 2
