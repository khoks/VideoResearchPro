"""S-1.5.14: sources that quietly return nothing, verified at the caller.

``POST /api/v1/jobs`` writes the run, the real ``execute_topic_job`` body runs
it, and ``GET /api/v1/jobs/{id}`` and ``/health`` are what the reader sees. Only
the network and the search agent's LLM are faked. Where it matters the real
connectors run over a faked HTTP answer, because the bug was in what a real
connector did with a 403.
"""
from __future__ import annotations

import json
import socket
import ssl
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import httpx
import httplib2
import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from app.agents import search_agent
from app.config import settings
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.source_refusal import SourceRefusal
from app.services import (
    connector_dispatch,
    job_source_types,
    progress_service,
    quota_service,
    source_failure,
    source_refusal_service,
)
from app.services.quota_service import QuotaExceededError
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.bluesky import client as bluesky_client
from app.sources.hn import client as hn_client
from app.sources.mastodon import client as mastodon_client
from app.sources.podcast import client as podcast_client
from app.sources.reddit import client as reddit_client
from app.sources.types import Candidate, ExtractedText, SourceMetadata
from app.tasks import job_tasks

_403 = httpx.Response(403, text="<html>403 Forbidden</html>", request=httpx.Request("GET", "https://cdn.example"))
_REAL_SEARCH_AGENT = search_agent.run_search_agent


class _Unclosable:
    """The test session, which the task's ``db.close()`` must not end."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


class _Source(BaseConnector):
    """A source with ``count`` candidates, or one whose search raises."""

    def __init__(self, source_type: str, count: int = 0, raises: Exception | None = None):
        self.source_type = source_type
        self.count = count
        self.raises = raises
        self.asked: list[int] = []
        self.fetched: list[str] = []

    def search(self, query: str, instructions: str = "", limit: int = 10):
        self.asked.append(limit)
        if self.raises:
            raise self.raises
        return [
            Candidate(
                source_type=self.source_type,
                source_id=f"{self.source_type}:{i}",
                title=f"{self.source_type} {i}",
                source_url=f"https://example.com/{self.source_type}/{i}",
            )
            for i in range(min(self.count, limit))
        ]

    def list_creator_items(self, *args, **kwargs):  # pragma: no cover
        return []

    def fetch_metadata(self, *args, **kwargs):  # pragma: no cover
        return {}

    def fetch_text(self, candidate, *, job_id: str = "", query: str = "", **kwargs):
        self.fetched.append(candidate.source_id)
        return ExtractedText(
            segments=[{"text": "body", "start": 0.0, "duration": 1.0}],
            language="en",
            text_source=self.source_type,
            word_count=1,
        )


@pytest.fixture
def sources():
    """Swap in fakes for the types a test registers; restore afterwards."""
    snapshot = registry.all_connectors()
    registry._reset_for_tests()

    def install(*fakes: _Source) -> dict[str, _Source]:
        for fake in fakes:
            registry.register(fake)
        return {fake.source_type: fake for fake in fakes}

    yield install
    registry._reset_for_tests()
    for connector in snapshot.values():
        registry.register(connector)


@pytest.fixture
def worker(db, monkeypatch):
    """Runs ``execute_topic_job`` on the test session. ``worker.videos`` is how
    many videos the search agent has, and ``worker.targets`` what it was asked."""
    state = type("Worker", (), {})()
    state.videos = 100
    state.targets = []
    state.raises = None

    def _search_agent(**kwargs):
        state.targets.append(kwargs["num_videos"])
        if state.raises:
            raise state.raises
        count = min(state.videos, kwargs["num_videos"])
        videos = [
            {
                "video_id": f"yt{i:09d}",
                "title": f"Video {i}",
                "channel_id": "UC_quiet",
                "channel_name": "Channel",
                "url": f"https://www.youtube.com/watch?v=yt{i:09d}",
                "duration_seconds": 600,
                "published_at": None,
                "thumbnail_url": None,
                "description": "",
            }
            for i in range(count)
        ]
        return videos, ["q1"], []

    session = _Unclosable(db)
    monkeypatch.setattr(job_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr("app.agents.search_agent.run_search_agent", _search_agent)
    for name in ("publish_progress", "publish_status_change", "publish_error"):
        monkeypatch.setattr(progress_service, name, lambda *a, **kw: None)
    monkeypatch.setattr(quota_service, "get_today_usage", lambda: 0)
    state.run = lambda job_id: job_tasks.execute_topic_job.run(job_id)
    return state


class _YouTube(_Source):
    """YouTube for the real search agent: a broad query raises ``raises``, and
    ``uploads`` is what a named channel has on its playlist."""

    def __init__(self, raises: Exception | None = None, uploads: tuple[str, ...] = ()):
        super().__init__("video", raises=raises)
        self.uploads = uploads

    def resolve_creator_id(self, hint: str, *, job_id: str = ""):
        return "UC_named"

    def list_creator_items(self, creator_external_id, since=None, *, limit=None, job_id=""):
        return [
            Candidate(source_type="video", source_id=vid, title=vid, source_url=f"https://y/{vid}")
            for vid in self.uploads
        ]

    def fetch_metadata(self, source_ids, *, job_id=""):
        return {
            vid: SourceMetadata(
                title=vid,
                creator_external_id="UC_named",
                creator_name="Named",
                duration_seconds=600,
                extra={"url": f"https://www.youtube.com/watch?v={vid}"},
            )
            for vid in source_ids
        }


@pytest.fixture
def real_agent(worker, monkeypatch):
    """The real graph between the job and its connectors, since what a failure
    turns into on the way out of it is the point. Only its model is faked."""

    def llm(use_case, **kwargs):
        ranking = use_case == "search_rank_and_curate"
        payload = ["uploaded0001"] if ranking else {"broad_queries": ["q1", "q2"], "channel_keywords": []}
        fake = MagicMock()
        fake.invoke.return_value = MagicMock(content=json.dumps(payload))
        return fake

    monkeypatch.setattr(search_agent, "run_search_agent", _REAL_SEARCH_AGENT)
    monkeypatch.setattr(search_agent, "get_llm_for", llm)
    monkeypatch.setattr(search_agent, "_lookup_known_eras", lambda ids: {})
    monkeypatch.setattr(search_agent.youtube_service, "get_channel_subscribers", lambda ids: {})


def _submit(
    client,
    *source_types: str,
    num_videos: int = 12,
    topic: str = "nuclear power",
    **fields,
) -> str:
    r = client.post(
        "/api/v1/jobs",
        json={
            "job_type": "topic",
            "topic": topic,
            "num_videos": num_videos,
            "source_types": list(source_types),
            **fields,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _notes(client, job_id: str) -> list[dict]:
    return client.get(f"/api/v1/jobs/{job_id}").json()["run_notes"]


def _kept(db, job_id: str) -> dict[str, int]:
    rows = (
        db.query(Document.source_type)
        .join(JobVideo, JobVideo.document_id == Document.document_id)
        .filter(JobVideo.job_id == job_id)
        .all()
    )
    counts: dict[str, int] = {}
    for (source_type,) in rows:
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


def _caps(client) -> dict[str, bool]:
    return client.get("/api/v1/health").json()["capabilities"]


# ---------------------------------------------------------------------------
# T-1.5.14.1: "the service refused" is not "nothing found"
# ---------------------------------------------------------------------------

def test_a_real_403_reads_as_unavailable_and_not_as_no_results(client, db, worker, monkeypatch):
    """The reported bug, through the real connector and client: Bluesky's CDN
    answers 403, and the run has to say so. Hacker News has nothing to say,
    which is a different sentence."""

    def http_get(url, params=None, headers=None, timeout=None):
        if "bsky" in url:
            return _403
        return httpx.Response(200, json={"hits": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(bluesky_client.httpx, "get", http_get)
    monkeypatch.setattr(hn_client.httpx, "get", http_get)
    monkeypatch.setattr(bluesky_client.BlueskyClient, "__init__", _no_pacing, raising=True)
    monkeypatch.setattr(hn_client.HNClient, "__init__", _no_pacing, raising=True)
    bluesky_client._reset_for_tests()
    hn_client._reset_for_tests()
    job_id = _submit(client, "video", "hn_story", "bluesky_post", num_videos=3)

    worker.run(job_id)

    bluesky_client._reset_for_tests()
    hn_client._reset_for_tests()
    assert db.get(Job, job_id).status == "awaiting_approval"
    by_source = {n.get("source_type"): n for n in _notes(client, job_id) if "source_type" in n}
    assert by_source["bluesky_post"]["kind"] == "source_unavailable"
    assert "refused" in by_source["bluesky_post"]["text"] and "403" in by_source["bluesky_post"]["text"]
    assert by_source["hn_story"]["kind"] == "source_empty"
    assert "found nothing" in by_source["hn_story"]["text"]


def _no_pacing(self) -> None:
    from app.utils.rate_limiter import RateLimiter

    self._limiter = RateLimiter(rate=0.0)
    self._timeout = httpx.Timeout(1.0)


def test_a_refused_mastodon_instance_is_reported_like_bluesky(client, db, worker, monkeypatch):
    monkeypatch.setattr(mastodon_client.httpx, "get", lambda *a, **kw: _403)
    monkeypatch.setattr(mastodon_client.MastodonClient, "__init__", _no_pacing, raising=True)
    mastodon_client._reset_for_tests()
    job_id = _submit(client, "video", "mastodon_post", num_videos=4)

    worker.run(job_id)

    mastodon_client._reset_for_tests()
    kinds = {n.get("source_type"): n["kind"] for n in _notes(client, job_id)}
    assert kinds["mastodon_post"] == "source_unavailable"


def test_a_failure_that_is_not_a_refusal_says_unavailable_and_keeps_the_source_on_offer(
    client, db, sources, worker
):
    """A timeout or a 500 says nothing about this install."""
    sources(_Source("hn_story", raises=httpx.ConnectError("no route")))
    job_id = _submit(client, "video", "hn_story", num_videos=4)

    worker.run(job_id)

    text = next(n["text"] for n in _notes(client, job_id) if n.get("source_type") == "hn_story")
    assert text == "Hacker News was unavailable: the search failed."
    assert _caps(client)["hn_search_enabled"] is True
    assert db.query(SourceRefusal).count() == 0


def test_a_rate_limit_is_said_as_one_and_does_not_hold_the_source(client, db, sources, worker):
    limited = httpx.HTTPStatusError(
        "429", request=httpx.Request("GET", "https://x"), response=httpx.Response(429)
    )
    sources(_Source("hn_story", raises=limited))
    job_id = _submit(client, "video", "hn_story", num_videos=4)

    worker.run(job_id)

    text = next(n["text"] for n in _notes(client, job_id) if n.get("source_type") == "hn_story")
    assert "slow down" in text and "429" in text
    assert db.query(SourceRefusal).count() == 0


def test_when_every_source_refused_the_failure_does_not_blame_the_topic(client, db, sources, worker):
    refused = httpx.HTTPStatusError("403", request=httpx.Request("GET", "https://x"), response=_403)
    sources(_Source("hn_story", raises=refused), _Source("mastodon_post", raises=refused))
    job_id = _submit(client, "hn_story", "mastodon_post", num_videos=4)

    worker.run(job_id)

    job = db.get(Job, job_id)
    assert job.status == "failed"
    assert "Hacker News was unavailable" in job.error_message
    assert "Mastodon was unavailable" in job.error_message
    assert "broader topic" not in job.error_message
    assert len(_notes(client, job_id)) == 2, "the notes survive the failure's rollback"


def test_when_one_refused_and_one_found_nothing_the_failure_says_both(client, db, sources, worker):
    refused = httpx.HTTPStatusError("403", request=httpx.Request("GET", "https://x"), response=_403)
    sources(_Source("hn_story", raises=refused), _Source("mastodon_post"))
    job_id = _submit(client, "hn_story", "mastodon_post", num_videos=4)

    worker.run(job_id)

    message = db.get(Job, job_id).error_message
    assert "Hacker News was unavailable" in message and "others found nothing" in message


def test_a_run_where_nothing_answered_for_lack_of_results_keeps_its_advice(client, db, sources, worker):
    sources(_Source("hn_story"))
    job_id = _submit(client, "hn_story", num_videos=4)

    worker.run(job_id)

    assert "Try a broader topic" in db.get(Job, job_id).error_message


def test_the_approval_message_names_the_unavailable_source(client, db, sources, worker):
    refused = httpx.HTTPStatusError("403", request=httpx.Request("GET", "https://x"), response=_403)
    sources(_Source("hn_story", raises=refused))
    job_id = _submit(client, "video", "hn_story", num_videos=4)

    worker.run(job_id)

    message = db.get(Job, job_id).progress_message
    assert message.startswith("Found 4 candidates.")
    assert "Hacker News was unavailable" in message


# ---------------------------------------------------------------------------
# YouTube itself: the search agent swallowed its refusals too
# ---------------------------------------------------------------------------

def test_youtube_refusing_leaves_the_other_sources_standing(client, db, sources, worker):
    """A spent quota used to read as "no candidates", or fail the whole run."""
    sources(_Source("hn_story", count=20))
    worker.raises = QuotaExceededError()
    job_id = _submit(client, "video", "hn_story", num_videos=6)

    worker.run(job_id)

    assert db.get(Job, job_id).status == "awaiting_approval"
    assert _kept(db, job_id) == {"hn_story": 6}, "and its share goes to the source that has more"
    note = next(n for n in _notes(client, job_id) if n.get("source_type") == "video")
    assert note["kind"] == "source_unavailable" and "quota is spent" in note["text"]


def test_youtube_alone_refusing_fails_the_run_and_says_why(client, db, worker):
    worker.raises = QuotaExceededError()
    job_id = _submit(client, "video", num_videos=6)

    worker.run(job_id)

    job = db.get(Job, job_id)
    assert job.status == "failed"
    assert "quota is spent" in job.error_message and "broader topic" not in job.error_message


def test_a_youtube_error_never_puts_the_api_key_on_the_run(client, db, sources, worker):
    """An HttpError's message holds the request URL, and the key is in its
    query string. The run's note and error are written from the status."""
    leaky = HttpError(
        Response({"status": 403}),
        b'{"error": {"message": "API key not valid"}}',
        uri="https://www.googleapis.com/youtube/v3/search?q=x&key=SECRET-KEY-VALUE",
    )
    assert "SECRET-KEY-VALUE" in str(leaky), "the test is only worth having while this holds"
    worker.raises = leaky
    job_id = _submit(client, "video", num_videos=6)

    worker.run(job_id)

    job = db.get(Job, job_id)
    assert job.status == "failed"
    assert "SECRET-KEY-VALUE" not in job.error_message
    assert "SECRET-KEY-VALUE" not in (job.run_notes_json or "")
    assert "refused the search (HTTP 403)" in job.error_message


@pytest.mark.parametrize(
    "raised",
    [
        TimeoutError("timed out"),
        socket.gaierror("no such host"),
        httplib2.ServerNotFoundError("Unable to find the server"),
        ssl.SSLError("handshake failed"),
        ValueError("a page that would not parse"),
        RuntimeError("the model is down"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_youtube_failing_any_way_leaves_the_other_sources_standing(client, db, sources, worker, raised):
    """Hacker News has already answered by now. This caught quota and HTTP
    errors alone, so a timeout threw its results away with the run."""
    sources(_Source("hn_story", count=20))
    worker.raises = raised
    job_id = _submit(client, "video", "hn_story", num_videos=6)

    worker.run(job_id)

    assert db.get(Job, job_id).status == "awaiting_approval"
    assert _kept(db, job_id) == {"hn_story": 6}
    note = next(n for n in _notes(client, job_id) if n.get("source_type") == "video")
    assert note["kind"] == "source_unavailable"
    assert note["text"] == "YouTube was unavailable: the search failed."


def test_a_model_refusing_is_not_youtube_refusing(client, db, sources, worker):
    """An LLM SDK's errors carry a ``.response`` too, and a 401 from the
    search agent's model must not be told as YouTube refusing the run."""

    class ModelRefused(Exception):
        response = httpx.Response(401)

    sources(_Source("hn_story", count=20))
    worker.raises = ModelRefused()
    job_id = _submit(client, "video", "hn_story", num_videos=6)

    worker.run(job_id)

    assert db.get(Job, job_id).status == "awaiting_approval"
    note = next(n for n in _notes(client, job_id) if n.get("source_type") == "video")
    assert note["text"] == "YouTube was unavailable: the search failed."


@pytest.mark.parametrize("others", [(), ("hn_story",)], ids=["alone", "beside_an_empty_source"])
def test_a_model_failure_with_nothing_else_to_keep_keeps_its_own_reason(client, db, sources, worker, others):
    """Not YouTube's doing, and "YouTube was unavailable" would hide what the
    reader needs. The run fails as it always did."""
    sources(_Source("hn_story", count=0))
    worker.raises = RuntimeError("the model is down")
    job_id = _submit(client, "video", *others, num_videos=6)

    worker.run(job_id)

    job = db.get(Job, job_id)
    assert job.status == "failed"
    assert job.error_message == "RuntimeError: the model is down"


def test_youtube_timing_out_through_the_real_agent_leaves_the_others_standing(
    client, db, sources, worker, real_agent
):
    sources(_YouTube(raises=TimeoutError("timed out")), _Source("hn_story", count=20))
    job_id = _submit(client, "video", "hn_story", num_videos=6)

    worker.run(job_id)

    assert db.get(Job, job_id).status == "awaiting_approval"
    assert _kept(db, job_id) == {"hn_story": 6}
    note = next(n for n in _notes(client, job_id) if n.get("source_type") == "video")
    assert note["text"] == "YouTube was unavailable: the search failed."


def test_youtube_alone_timing_out_says_it_was_unavailable(client, db, sources, worker, real_agent):
    """Not "try a broader topic", which is what a run said when the agent
    swallowed this, and not a bare "timed out"."""
    sources(_YouTube(raises=TimeoutError("timed out")))
    job_id = _submit(client, "video", num_videos=6)

    worker.run(job_id)

    job = db.get(Job, job_id)
    assert job.status == "failed"
    assert "YouTube was unavailable: the search failed." in job.error_message
    assert "broader topic" not in job.error_message and "timed out" not in job.error_message


@pytest.mark.parametrize(
    "raised",
    [
        TimeoutError("timed out"),
        HttpError(Response({"status": 500}), b"{}", uri="https://www.googleapis.com/youtube/v3/search"),
        QuotaExceededError(),
    ],
    ids=lambda e: type(e).__name__,
)
def test_a_failed_broad_search_keeps_the_channels_the_user_named(client, db, sources, worker, real_agent, raised):
    """search.list failing says nothing about playlistItems, which a run on
    named channels walks at 1 unit a page."""
    sources(_YouTube(raises=raised, uploads=("uploaded0001",)))
    job_id = _submit(client, "video", num_videos=6, preferred_channels=["@named"])

    worker.run(job_id)

    assert db.get(Job, job_id).status == "awaiting_approval"
    assert _kept(db, job_id) == {"video": 1}
    assert [n for n in _notes(client, job_id) if n["kind"] == "source_unavailable"] == []


def test_a_run_on_named_channels_can_be_read_back(client, db, sources, worker, real_agent):
    """A run that names channels stores a summary object, and the response
    only allowed a list, so reading the run or the job list was a 500."""
    sources(_YouTube(uploads=("uploaded0001",)))
    job_id = _submit(client, "video", num_videos=6, preferred_channels=["@named"])

    worker.run(job_id)

    one = client.get(f"/api/v1/jobs/{job_id}").json()
    assert one["channel_list_resolved"] == {"resolved_count": 1, "unresolved": []}
    assert [job["id"] for job in client.get("/api/v1/jobs").json()] == [job_id]


def test_a_failed_broad_search_with_nothing_from_the_named_channels_is_reported(
    client, db, sources, worker, real_agent
):
    sources(_YouTube(raises=TimeoutError("timed out")))
    job_id = _submit(client, "video", num_videos=6, preferred_channels=["@named"])

    worker.run(job_id)

    job = db.get(Job, job_id)
    assert job.status == "failed"
    assert "YouTube was unavailable: the search failed." in job.error_message


def test_broad_search_hands_back_a_refusal_that_found_nothing(monkeypatch):
    """The agent's own step: it caught everything and returned no videos."""

    class Refused:
        def search(self, query, limit):
            raise QuotaExceededError()

    monkeypatch.setattr(search_agent, "connector_for", lambda st: Refused())
    videos, failure = search_agent._run_broad_searches(["a", "b"], 5)
    assert videos == {}
    assert isinstance(failure, QuotaExceededError)


def test_broad_search_stops_at_a_spent_quota_and_keeps_what_it_has(monkeypatch):
    calls: list[str] = []

    class Partly:
        def search(self, query, limit):
            calls.append(query)
            if query == "b":
                raise QuotaExceededError()
            return [Candidate(source_type="video", source_id="v1", title="V", source_url="https://y/v1")]

    monkeypatch.setattr(search_agent, "connector_for", lambda st: Partly())
    videos, _failure = search_agent._run_broad_searches(["a", "b", "c"], 5)
    assert list(videos) == ["v1"]
    assert calls == ["a", "b"], "every later query would get the same answer"


def test_broad_search_still_skips_one_bad_query(monkeypatch):
    class Flaky:
        def search(self, query, limit):
            if query == "a":
                raise RuntimeError("hiccup")
            return [Candidate(source_type="video", source_id="v1", title="V", source_url="https://y/v1")]

    monkeypatch.setattr(search_agent, "connector_for", lambda st: Flaky())
    videos, _failure = search_agent._run_broad_searches(["a", "b"], 5)
    assert list(videos) == ["v1"]


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "exc, kind, status",
    [
        (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://x"), response=httpx.Response(401)), "refused", 401),
        (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://x"), response=httpx.Response(403)), "refused", 403),
        (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://x"), response=httpx.Response(429)), "rate_limited", 429),
        (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://x"), response=httpx.Response(503)), "failed", 503),
        (httpx.ConnectError("down"), "failed", None),
        (RuntimeError("anything"), "failed", None),
        (QuotaExceededError(), "quota_spent", 403),
        (HttpError(Response({"status": 403}), b"{}", uri="https://x"), "refused", 403),
        (source_failure.SearchFailed("x"), "failed", None),
    ],
)
def test_classify(exc, kind, status):
    assert source_failure.classify(exc) == source_failure.SourceFailure(kind, status)


def test_classify_keeps_the_status_of_a_target_that_refused_without_calling_it_a_refusal():
    """A 403 from one feed host: the reader can have the status, but only a
    refusal starts a hold."""
    cause = httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://x"), response=httpx.Response(403))
    try:
        try:
            raise cause
        except httpx.HTTPError as inner:
            raise source_failure.SearchFailed("one feed") from inner
    except source_failure.SearchFailed as wrapped:
        assert source_failure.classify(wrapped) == source_failure.SourceFailure("failed", 403)


def test_classify_looks_through_a_wrapper():
    """Reddit wraps a failed token fetch in RedditAuthError."""
    from app.sources.reddit.client import RedditAuthError

    cause = httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://x"), response=httpx.Response(401))
    try:
        try:
            raise cause
        except httpx.HTTPError as inner:
            raise RedditAuthError("Reddit OAuth token fetch failed") from inner
    except RedditAuthError as wrapped:
        assert source_failure.classify(wrapped).kind == "refused"


# ---------------------------------------------------------------------------
# The form stops offering a source that refused
# ---------------------------------------------------------------------------

def test_a_refusal_takes_the_source_off_the_form(client, db, sources, worker):
    refused = httpx.HTTPStatusError("403", request=httpx.Request("GET", "https://x"), response=_403)
    sources(_Source("bluesky_post", raises=refused))
    assert _caps(client)["bluesky_search_enabled"] is True
    job_id = _submit(client, "video", "bluesky_post", num_videos=4)

    worker.run(job_id)

    health = client.get("/api/v1/health").json()
    assert health["capabilities"]["bluesky_search_enabled"] is False
    assert health["source_holds"]["bluesky_post"]["status"] == 403


def _podcast_search(feed_answer: httpx.Response):
    """iTunes names one show, and its RSS host answers ``feed_answer``."""

    def http_get(url, params=None, headers=None, timeout=None, follow_redirects=False):
        if "itunes.apple.com" in url:
            show = {"collectionName": "A show", "feedUrl": "https://feeds.example/show.rss"}
            return httpx.Response(200, json={"results": [show]}, request=httpx.Request("GET", url))
        return feed_answer

    return http_get


@pytest.fixture
def podcasts(monkeypatch):
    monkeypatch.setattr(podcast_client.PodcastClient, "__init__", _no_pacing, raising=True)
    podcast_client._reset_for_tests()
    yield
    podcast_client._reset_for_tests()


@pytest.fixture
def reddit(monkeypatch):
    token = httpx.Response(200, json={"access_token": "t"}, request=httpx.Request("POST", "https://reddit"))
    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "REDDIT_RATE_LIMIT_RPM", 6_000_000)
    monkeypatch.setattr(reddit_client.httpx, "post", lambda *a, **kw: token)
    reddit_client._reset_for_tests()
    yield
    reddit_client._reset_for_tests()


def test_one_feed_host_refusing_is_not_the_service_refusing(client, db, worker, monkeypatch, podcasts):
    """iTunes answered. A 403 from the host of the one show it named says
    nothing about podcasts, and a hold reaches every tenant, so any one user's
    topic could take the source off everyone's form."""
    monkeypatch.setattr(podcast_client.httpx, "get", _podcast_search(_403))
    job_id = _submit(client, "podcast_episode", num_videos=4)

    worker.run(job_id)

    job = db.get(Job, job_id)
    assert job.status == "failed"
    assert "Podcasts was unavailable: the search failed (HTTP 403)." in job.error_message
    assert "refused" not in job.error_message
    assert _caps(client)["podcast_search_enabled"] is True
    assert client.get("/api/v1/health").json()["source_holds"] == {}
    assert db.query(SourceRefusal).count() == 0


def test_itunes_itself_refusing_still_takes_podcasts_off_the_form(client, db, worker, monkeypatch, podcasts):
    monkeypatch.setattr(podcast_client.httpx, "get", lambda *a, **kw: _403)
    job_id = _submit(client, "podcast_episode", num_videos=4)

    worker.run(job_id)

    assert "it refused the search (HTTP 403)" in db.get(Job, job_id).error_message
    assert _caps(client)["podcast_search_enabled"] is False
    assert client.get("/api/v1/health").json()["source_holds"]["podcast_episode"]["status"] == 403


def test_a_private_subreddit_is_not_reddit_refusing(client, db, worker, monkeypatch, reddit):
    """A user can scope a topic to a subreddit, and a private or quarantined
    one answers 403. That is about the subreddit, not this install."""
    monkeypatch.setattr(reddit_client.httpx, "get", lambda *a, **kw: _403)
    job_id = _submit(client, "reddit_post", num_videos=4, topic="subreddit:someprivatesub climate")

    worker.run(job_id)

    job = db.get(Job, job_id)
    assert job.status == "failed"
    assert "Reddit was unavailable: the search failed (HTTP 403)." in job.error_message
    assert _caps(client)["reddit_search_enabled"] is True
    assert db.query(SourceRefusal).count() == 0


def test_a_site_wide_reddit_refusal_still_holds(client, db, worker, monkeypatch, reddit):
    monkeypatch.setattr(reddit_client.httpx, "get", lambda *a, **kw: _403)
    job_id = _submit(client, "reddit_post", num_videos=4)

    worker.run(job_id)

    assert _caps(client)["reddit_search_enabled"] is False
    assert client.get("/api/v1/health").json()["source_holds"]["reddit_post"]["status"] == 403
    assert "it refused the search (HTTP 403)" in db.get(Job, job_id).error_message


def test_a_hold_leaves_the_api_open_so_a_saved_recipe_still_runs(client, db, sources, worker):
    """A hold is one run's evidence, and the source may have recovered."""
    source_refusal_service.record(db, "bluesky_post", 403)
    db.commit()
    hn = sources(_Source("bluesky_post", count=5))["bluesky_post"]
    assert _caps(client)["bluesky_search_enabled"] is False

    job_id = _submit(client, "video", "bluesky_post", num_videos=4)
    worker.run(job_id)

    assert hn.asked, "the run tried it"
    assert _kept(db, job_id)["bluesky_post"] == 2


def test_a_source_that_answers_comes_off_hold(client, db, sources, worker):
    source_refusal_service.record(db, "bluesky_post", 403)
    db.commit()
    sources(_Source("bluesky_post", count=5))

    worker.run(_submit(client, "video", "bluesky_post", num_videos=4))

    assert _caps(client)["bluesky_search_enabled"] is True
    assert db.query(SourceRefusal).count() == 0


def test_try_it_anyway_goes_through_job_creation_as_it_stands(client, db, sources):
    """T-1.5.14.6 needs no new route: the form sends the held source, and the
    API keeps it on the run. A check here that read the hold would refuse the
    very thing the form now offers."""
    source_refusal_service.record(db, "podcast_episode", 403)
    db.commit()
    sources(_Source("podcast_episode", count=5))
    assert _caps(client)["podcast_search_enabled"] is False

    r = client.post(
        "/api/v1/jobs",
        json={"job_type": "topic", "topic": "tariffs", "num_videos": 4, "source_types": ["podcast_episode"]},
    )

    assert r.status_code == 201, r.text
    assert r.json()["source_types"] == ["podcast_episode"]


def test_trying_a_held_source_that_answers_ends_the_hold(client, db, sources, worker):
    source_refusal_service.record(db, "podcast_episode", 403)
    db.commit()
    sources(_Source("podcast_episode", count=5))

    job_id = _submit(client, "podcast_episode", num_videos=4)
    worker.run(job_id)

    health = client.get("/api/v1/health").json()
    assert health["capabilities"]["podcast_search_enabled"] is True
    assert health["source_holds"] == {}
    assert db.get(Job, job_id).status == "awaiting_approval"


def test_trying_a_held_source_that_answers_with_nothing_still_ends_the_hold(client, db, sources, worker):
    """An empty answer is an answer: the source is taking searches again."""
    source_refusal_service.record(db, "bluesky_post", 403)
    db.commit()
    sources(_Source("bluesky_post", count=0))

    worker.run(_submit(client, "video", "bluesky_post", num_videos=4))

    assert _caps(client)["bluesky_search_enabled"] is True


def test_trying_a_held_source_that_refuses_again_renews_the_hold(client, db, sources, worker):
    """The source's own answer decides, and the run says what happened."""
    source_refusal_service.record(db, "bluesky_post", 403)
    db.commit()
    row = db.get(SourceRefusal, "bluesky_post")
    row.refused_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=source_refusal_service.HOLD_HOURS - 1
    )
    db.commit()
    before = row.refused_at
    refused = httpx.HTTPStatusError(
        "401", request=httpx.Request("GET", "https://x"), response=httpx.Response(401)
    )
    bluesky = sources(_Source("bluesky_post", raises=refused))["bluesky_post"]

    job_id = _submit(client, "video", "bluesky_post", num_videos=4)
    worker.run(job_id)

    assert bluesky.asked, "the run tried it"
    db.expire_all()
    assert db.get(SourceRefusal, "bluesky_post").refused_at > before
    holds = client.get("/api/v1/health").json()["source_holds"]
    assert holds["bluesky_post"]["status"] == 401
    assert _caps(client)["bluesky_search_enabled"] is False
    notes = client.get(f"/api/v1/jobs/{job_id}").json()["run_notes"]
    assert any(n["text"] == "Bluesky was unavailable: it refused the search (HTTP 401)." for n in notes)


def test_a_hold_ends_when_the_settings_that_reach_the_source_change(client, db, monkeypatch):
    """How credentials arrive, and how an operator points at another endpoint."""
    from app.config import settings

    source_refusal_service.record(db, "bluesky_post", 403)
    db.commit()
    assert _caps(client)["bluesky_search_enabled"] is False

    monkeypatch.setattr(settings, "BLUESKY_XRPC_BASE", "https://pds.example.com")
    assert _caps(client)["bluesky_search_enabled"] is True


def test_a_hold_ends_on_its_own_because_a_block_can_lift(client, db):
    source_refusal_service.record(db, "bluesky_post", 403)
    db.commit()
    row = db.get(SourceRefusal, "bluesky_post")
    row.refused_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=source_refusal_service.HOLD_HOURS + 1
    )
    db.commit()
    assert _caps(client)["bluesky_search_enabled"] is True
    assert client.get("/api/v1/health").json()["source_holds"] == {}


def test_a_second_refusal_restarts_the_hold(client, db):
    source_refusal_service.record(db, "bluesky_post", 403)
    db.commit()
    row = db.get(SourceRefusal, "bluesky_post")
    row.refused_at = datetime(2020, 1, 1)
    db.commit()

    source_refusal_service.record(db, "bluesky_post", 401)
    db.commit()

    assert client.get("/api/v1/health").json()["source_holds"]["bluesky_post"]["status"] == 401


def test_a_hold_stores_no_secret(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "TWITTER_BEARER_TOKEN", "bearer-secret-value")
    source_refusal_service.record(db, "tweet", 401)
    db.commit()
    row = db.get(SourceRefusal, "tweet")
    assert "bearer-secret-value" not in row.config_fingerprint


def test_health_stays_up_when_the_hold_table_cannot_be_read(client, monkeypatch):
    def broken(*a, **kw):
        raise RuntimeError("no such table")

    class Broken:
        query = broken

    assert source_refusal_service.active(Broken()) == {}
    assert client.get("/api/v1/health").status_code == 200


# ---------------------------------------------------------------------------
# T-1.5.13.6: a blank base URL is "not set up"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source_type, setting, capability",
    [
        ("mastodon_post", "MASTODON_INSTANCE_BASE", "mastodon_search_enabled"),
        ("bluesky_post", "BLUESKY_XRPC_BASE", "bluesky_search_enabled"),
    ],
)
@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_base_url_is_not_set_up(client, db, monkeypatch, source_type, setting, capability, blank):
    from app.config import settings

    assert _caps(client)[capability] is True
    monkeypatch.setattr(settings, setting, blank)

    assert _caps(client)[capability] is False
    r = client.post(
        "/api/v1/jobs",
        json={"job_type": "topic", "topic": "x", "num_videos": 4, "source_types": ["video", source_type]},
    )
    assert r.status_code == 422
    assert setting in r.text
    assert db.query(Job).count() == 0


# ---------------------------------------------------------------------------
# T-1.5.14.3: a share a source cannot fill goes to the others
# ---------------------------------------------------------------------------

def test_redistribute_gives_a_short_share_to_who_has_more():
    shares = {"video": 3, "hn_story": 3, "mastodon_post": 3, "bluesky_post": 3}
    limits = job_source_types.redistribute(
        shares, {"video": None, "hn_story": 12, "mastodon_post": 1, "bluesky_post": 0}
    )
    assert limits == {"video": 6, "hn_story": 5, "mastodon_post": 1, "bluesky_post": 0}
    assert sum(limits.values()) == 12


def test_redistribute_never_grows_the_run_and_never_invents_candidates():
    shares = {"hn_story": 4, "bluesky_post": 4}
    assert job_source_types.redistribute(shares, {"hn_story": 5, "bluesky_post": 0}) == {
        "hn_story": 5,
        "bluesky_post": 0,
    }


def test_redistribute_changes_nothing_when_every_source_fills_its_share():
    shares = {"video": 4, "hn_story": 4}
    assert job_source_types.redistribute(shares, {"video": None, "hn_story": 12}) == shares


def test_redistribute_ignores_a_source_that_was_not_searched():
    assert job_source_types.redistribute({"video": 4, "tweet": 0}, {"video": None}) == {"video": 4, "tweet": 0}


def test_an_empty_source_tops_youtube_up_on_the_one_search(client, db, sources, worker):
    """Its share goes to YouTube as a bigger target, not a second search."""
    sources(_Source("hn_story"), _Source("mastodon_post", count=20))
    job_id = _submit(client, "video", "hn_story", "mastodon_post", num_videos=12)

    worker.run(job_id)

    assert worker.targets == [6], "4 + 2 of Hacker News's 4, the other 2 to Mastodon"
    assert _kept(db, job_id) == {"video": 6, "mastodon_post": 6}
    moved = next(n for n in _notes(client, job_id) if n["kind"] == "budget_moved")
    assert moved["text"] == "4 results that Hacker News could not fill went to YouTube (2) and Mastodon (2)."


def test_the_run_total_stays_what_it_was(client, db, sources, worker):
    sources(_Source("hn_story", count=2), _Source("mastodon_post", count=50), _Source("bluesky_post"))
    job_id = _submit(client, "video", "hn_story", "mastodon_post", "bluesky_post", num_videos=20)

    worker.run(job_id)

    kept = _kept(db, job_id)
    assert sum(kept.values()) == 20
    assert kept["hn_story"] == 2


def test_only_what_the_run_keeps_is_fetched(client, db, sources, worker):
    """Each fetch is a classifier call on a social source, so the bigger ask
    costs nothing unless the share really moved."""
    hn = sources(_Source("hn_story", count=50))["hn_story"]
    worker.run(_submit(client, "video", "hn_story", num_videos=4))
    assert hn.asked == [4], "asked for the whole budget, since the search costs the same"
    assert len(hn.fetched) == 2, "and keeps its share, because nobody came back short"


def test_a_youtube_shortfall_goes_to_a_source_that_has_more(client, db, sources, worker):
    """YouTube answers last, and a thin topic can leave it short too. What the
    other source already found covers it, with no further search."""
    hn = sources(_Source("hn_story", count=50))["hn_story"]
    worker.videos = 1
    job_id = _submit(client, "video", "hn_story", num_videos=10)

    worker.run(job_id)

    assert _kept(db, job_id) == {"video": 1, "hn_story": 9}
    assert len(hn.asked) == 1


def test_a_run_where_every_source_fills_its_share_is_unchanged(client, db, sources, worker):
    """No top-up, so not one extra quota unit, and nothing to say."""
    sources(_Source("hn_story", count=50))
    job_id = _submit(client, "video", "hn_story", num_videos=10)

    worker.run(job_id)

    assert worker.targets == [5]
    assert _kept(db, job_id) == {"video": 5, "hn_story": 5}
    assert db.get(Job, job_id).run_notes_json is None
    assert _notes(client, job_id) == []


def test_a_metered_source_is_asked_for_its_share_alone(client, db, sources, worker, monkeypatch):
    """X bills by what a search reads, so spare budget must not read more."""
    from app.config import settings

    monkeypatch.setattr(settings, "TWITTER_BEARER_TOKEN", "t")
    tweets = sources(_Source("tweet", count=50), _Source("hn_story"))["tweet"]

    worker.run(_submit(client, "video", "hn_story", "tweet", num_videos=9))

    assert tweets.asked == [3]


def test_a_top_up_waits_for_room_in_the_days_quota(client, db, sources, worker, monkeypatch):
    """YOUTUBE_DAILY_QUOTA is a limit the top-up respects: YouTube keeps its
    share, the spare goes where it can, and the run says so."""
    from app.config import settings

    sources(_Source("hn_story"), _Source("mastodon_post", count=30))
    monkeypatch.setattr(settings, "YOUTUBE_DAILY_QUOTA", 10000)
    monkeypatch.setattr(quota_service, "get_today_usage", lambda: 9900)
    job_id = _submit(client, "video", "hn_story", "mastodon_post", num_videos=12)

    worker.run(job_id)

    assert worker.targets == [4], "its share, not a bigger one"
    assert _kept(db, job_id) == {"video": 4, "mastodon_post": 8}
    note = next(n for n in _notes(client, job_id) if n["kind"] == "top_up_skipped")
    assert "100 are left today" in note["text"]


def test_a_top_up_within_the_days_quota_goes_ahead(client, db, sources, worker, monkeypatch):
    from app.config import settings

    sources(_Source("hn_story"))
    needed = job_source_types.youtube_search_units(12)
    monkeypatch.setattr(settings, "YOUTUBE_DAILY_QUOTA", 10000)
    monkeypatch.setattr(quota_service, "get_today_usage", lambda: 10000 - needed)

    worker.run(_submit(client, "video", "hn_story", num_videos=12))

    assert worker.targets == [12]


def test_a_spent_day_does_not_stop_the_search_youtube_was_going_to_run(client, db, sources, worker, monkeypatch):
    """The guard is on the top-up. A run's own share behaves as it always did,
    and a spent quota answers for itself."""
    sources(_Source("hn_story", count=50))
    monkeypatch.setattr(quota_service, "get_today_usage", lambda: 999_999)

    worker.run(_submit(client, "video", "hn_story", num_videos=4))

    assert worker.targets == [2]


@pytest.mark.parametrize(
    "target, pages_setting, units",
    [(6, 2, 600), (16, 2, 600), (17, 2, 1200), (17, 1, 600), (200, 2, 1200), (200, 5, 3000)],
)
def test_the_most_a_youtube_search_can_cost(monkeypatch, target, pages_setting, units):
    from app.config import settings

    monkeypatch.setattr(settings, "YOUTUBE_SEARCH_MAX_PAGES", pages_setting)
    assert job_source_types.youtube_search_units(target) == units


def test_the_cost_ceiling_tracks_what_the_agent_really_does():
    """``youtube_search_units`` restates three facts from elsewhere. If the
    agent asks for more, the ceiling must move with it."""
    import inspect

    from app.agents.prompts.search_prompts import PLAN_SEARCHES_PROMPT
    from app.services import youtube_service

    assert "per_query_max = max(target * 3, 50)" in inspect.getsource(search_agent._run_broad_searches)
    assert '"maxResults": min(max_results, 50)' in inspect.getsource(youtube_service.search_videos)
    assert f"exactly 4-{job_source_types._MOST_BROAD_QUERIES} items" in PLAN_SEARCHES_PROMPT


def test_a_note_reaches_the_api_for_a_run_with_none_too(client, db, sources, worker):
    job_id = _submit(client, "video", num_videos=4)
    worker.run(job_id)
    assert _notes(client, job_id) == []


def test_dispatch_reports_a_failure_by_kind_and_a_clean_empty_as_neither(sources):
    refused = httpx.HTTPStatusError("403", request=httpx.Request("GET", "https://x"), response=_403)
    sources(_Source("bluesky_post", raises=refused), _Source("hn_story"))

    result = connector_dispatch.dispatch_search(["bluesky_post", "hn_story"], query="x")

    assert result.failures_by_source_type == {
        "bluesky_post": source_failure.SourceFailure("refused", 403)
    }
    assert result.candidates_by_source_type == {"bluesky_post": [], "hn_story": []}
