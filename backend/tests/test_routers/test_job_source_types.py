"""S-1.5.13 — ``source_types`` on job creation, verified at the caller.

``POST /api/v1/jobs`` is the production caller. These tests submit through
it, read the row it wrote, hand that row to the real Celery task body and
check which discovery path ran: the search agent for ``video``,
``connector_dispatch`` for everything else. This is the HTTP-level variant
S-1.5.11 never wrote (T-1.5.13.4). Connectors are fakes: a live Reddit / HN
search needs credentials and network, and is not exercised here.
"""
from __future__ import annotations

import json

import pytest

from app.models.document import Document
from app.models.job import Job
from app.models.job_template import JobTemplateVersion
from app.services import job_source_types, visibility_service
from app.sources import registry
from app.sources.base import BaseConnector
from app.sources.types import Candidate, ExtractedText
from app.tasks import job_tasks
from app.tasks.job_tasks import _resolve_source_types


class _FakeConnector(BaseConnector):
    """Yields one candidate per id from search(); fetch_text succeeds."""

    def __init__(self, source_type: str, ids: list[str]):
        self.source_type = source_type
        self._ids = ids
        self.searched: list[str] = []

    def search(self, query: str, instructions: str = "", limit: int = 10):
        self.searched.append(query)
        return [
            Candidate(
                source_type=self.source_type,
                source_id=f"{self.source_type}:{i}",
                title=f"{self.source_type} {i}",
                source_url=f"https://example.com/{self.source_type}/{i}",
            )
            for i in self._ids[:limit]
        ]

    def list_creator_items(self, *args, **kwargs):  # pragma: no cover
        return []

    def fetch_metadata(self, *args, **kwargs):  # pragma: no cover
        return {}

    def fetch_text(self, candidate, *, job_id: str = "", query: str = ""):
        return ExtractedText(
            segments=[{"text": "body text", "start": 0.0, "duration": 1.0}],
            language="en",
            text_source=self.source_type,
            word_count=2,
        )


_YOUTUBE_VIDEO = {
    "video_id": "ytS1513",
    "title": "A YouTube video",
    "channel_id": "UC_s1513",
    "channel_name": "Channel",
    "url": "https://www.youtube.com/watch?v=ytS1513",
    "duration_seconds": 600,
    "published_at": None,
    "thumbnail_url": None,
    "description": "",
}


@pytest.fixture
def reddit_configured(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "id-for-tests")
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "secret-for-tests")


@pytest.fixture
def unconfigured(monkeypatch):
    """No credential-gated source is set up (the suite's own default, pinned
    so a developer's environment cannot change the answer)."""
    from app.config import settings

    for name in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "BRAVE_SEARCH_API_KEY", "TWITTER_BEARER_TOKEN"):
        monkeypatch.setattr(settings, name, "")


@pytest.fixture
def fake_sources():
    """Swap the registry for fakes; restore the real connectors afterwards."""
    snapshot = registry.all_connectors()
    registry._reset_for_tests()
    fakes = {
        "reddit_post": _FakeConnector("reddit_post", ["r1", "r2"]),
        "hn_story": _FakeConnector("hn_story", ["h1"]),
    }
    for fake in fakes.values():
        registry.register(fake)
    yield fakes
    registry._reset_for_tests()
    for c in snapshot.values():
        registry.register(c)


@pytest.fixture
def run_worker(db, monkeypatch):
    """Run the real `execute_topic_job` body on the test session, recording
    whether the search agent ran and what `dispatch_search` was handed."""
    from app.services import connector_dispatch, progress_service

    calls: dict[str, list] = {"search_agent": [], "dispatch": []}

    def _search_agent(**kwargs):
        calls["search_agent"].append(kwargs["topic"])
        return [dict(_YOUTUBE_VIDEO)], ["q1"], []

    real_dispatch = connector_dispatch.dispatch_search

    def _spy_dispatch(source_types, *args, **kwargs):
        calls["dispatch"].append(list(source_types))
        return real_dispatch(source_types, *args, **kwargs)

    monkeypatch.setattr(job_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr("app.agents.search_agent.run_search_agent", _search_agent)
    monkeypatch.setattr(connector_dispatch, "dispatch_search", _spy_dispatch)
    monkeypatch.setattr(progress_service, "publish_progress", lambda *a, **kw: None)
    monkeypatch.setattr(progress_service, "publish_status_change", lambda *a, **kw: None)

    def _run(job_id: str) -> dict[str, list]:
        job_tasks.execute_topic_job.run(job_id)
        return calls

    return _run


def _topic(**extra) -> dict:
    return {"job_type": "topic", "topic": "rare earth supply", "num_videos": 5, **extra}


# ---------------------------------------------------------------------------
# The acceptance path: persist, read back, dispatch
# ---------------------------------------------------------------------------

def test_post_persists_source_types_and_the_run_dispatches_them(
    client, db, test_user, reddit_configured, fake_sources, run_worker
):
    user_id = test_user.id  # the worker closes the shared session
    r = client.post("/api/v1/jobs", json=_topic(source_types=["video", "reddit_post"]))
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    assert r.json()["source_types"] == ["video", "reddit_post"]

    row = db.query(Job).filter(Job.id == job_id).one()
    assert json.loads(row.source_types_json) == ["video", "reddit_post"]
    assert _resolve_source_types(row) == ["video", "reddit_post"]

    calls = run_worker(job_id)

    # YouTube through the search agent, Reddit (and only Reddit) through
    # connector_dispatch; HN is registered but was not asked for.
    assert calls["search_agent"] == ["rare earth supply"]
    assert calls["dispatch"] == [["reddit_post"]]
    assert fake_sources["reddit_post"].searched == ["rare earth supply"]
    assert fake_sources["hn_story"].searched == []

    job = db.query(Job).filter(Job.id == job_id).one()
    assert job.status == "awaiting_approval"
    by_type = {
        st: db.query(Document).filter(Document.source_type == st).count()
        for st in ("video", "reddit_post", "hn_story")
    }
    assert by_type == {"video": 1, "reddit_post": 2, "hn_story": 0}

    # D-063: the dispatched documents are granted to the submitter at search
    # time, as the search agent's candidates are.
    visible = {row[0] for row in visibility_service.visible_document_ids(db, user_id)}
    reddit_ids = {d.document_id for d in db.query(Document).filter(Document.source_type == "reddit_post")}
    assert reddit_ids and reddit_ids <= visible

    # The approval list carries both kinds.
    videos = client.get(f"/api/v1/jobs/{job_id}/videos").json()
    assert sorted(v["source_type"] for v in videos) == ["reddit_post", "reddit_post", "video"]


def test_non_video_only_run_skips_the_search_agent(client, db, fake_sources, run_worker):
    r = client.post("/api/v1/jobs", json=_topic(source_types=["hn_story"]))
    assert r.status_code == 201, r.text

    calls = run_worker(r.json()["id"])

    assert calls["search_agent"] == []
    assert calls["dispatch"] == [["hn_story"]]
    assert db.query(Document).filter(Document.source_type == "hn_story").count() == 1


def test_omitting_source_types_keeps_youtube_only(client, db, fake_sources, run_worker):
    """The default is unchanged: NULL in the column, the search agent alone
    at run time, and nothing handed to the dispatcher."""
    r = client.post("/api/v1/jobs", json=_topic())
    assert r.status_code == 201, r.text
    assert r.json()["source_types"] == ["video"]
    row = db.query(Job).filter(Job.id == r.json()["id"]).one()
    assert row.source_types_json is None

    calls = run_worker(row.id)

    assert calls["search_agent"] == ["rare earth supply"]
    assert calls["dispatch"] == []
    assert db.query(Document).filter(Document.source_type != "video").count() == 0


def test_youtube_only_is_stored_as_the_default(client, db):
    r = client.post("/api/v1/jobs", json=_topic(source_types=["video"]))
    assert r.status_code == 201
    assert db.query(Job).filter(Job.id == r.json()["id"]).one().source_types_json is None


def test_order_is_canonical_and_repeats_collapse(client, db):
    r = client.post("/api/v1/jobs", json=_topic(source_types=["hn_story", " video ", "hn_story"]))
    assert r.status_code == 201, r.text
    assert r.json()["source_types"] == ["video", "hn_story"]


# ---------------------------------------------------------------------------
# Refusals (422)
# ---------------------------------------------------------------------------

def _detail(r) -> str:
    return json.dumps(r.json()["detail"])


@pytest.mark.parametrize(
    "source_types, expected",
    [
        (["myspace_post"], "Unknown source type: myspace_post"),
        (["video", "pdf"], "cannot be searched"),
        (["li_post"], "Add sources"),
        ([], "at least one source type"),
        ([" "], "at least one source type"),
    ],
)
def test_unknown_library_only_or_empty_types_are_422(client, db, source_types, expected):
    r = client.post("/api/v1/jobs", json=_topic(source_types=source_types))
    assert r.status_code == 422
    assert expected in _detail(r)
    assert db.query(Job).count() == 0


@pytest.mark.parametrize(
    "source_type, setting",
    [
        ("tweet", "TWITTER_BEARER_TOKEN"),
        ("article", "BRAVE_SEARCH_API_KEY"),
        ("reddit_post", "REDDIT_CLIENT_ID"),
    ],
)
def test_a_type_this_install_has_not_set_up_is_422(client, db, unconfigured, monkeypatch, source_type, setting):
    r = client.post("/api/v1/jobs", json=_topic(source_types=["video", source_type]))
    assert r.status_code == 422
    assert "Not set up on this install" in _detail(r) and setting in _detail(r)

    # Set it up and the same request is accepted.
    from app.config import settings

    monkeypatch.setattr(settings, "TWITTER_BEARER_TOKEN", "t")
    monkeypatch.setattr(settings, "BRAVE_SEARCH_API_KEY", "b")
    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "i")
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "s")
    r = client.post("/api/v1/jobs", json=_topic(source_types=["video", source_type]))
    assert r.status_code == 201, r.text
    assert r.json()["source_types"] == ["video", source_type]


def test_channel_runs_refuse_other_source_types_but_accept_youtube(client, db):
    channel = {"job_type": "channel", "channel_list": ["@veritasium"], "videos_per_channel": 5}
    r = client.post("/api/v1/jobs", json={**channel, "source_types": ["hn_story"]})
    assert r.status_code == 422
    assert "topic research only" in _detail(r)

    r = client.post("/api/v1/jobs", json={**channel, "source_types": ["video"]})
    assert r.status_code == 201, r.text
    assert db.query(Job).filter(Job.id == r.json()["id"]).one().source_types_json is None


# ---------------------------------------------------------------------------
# /health tells the form what to offer
# ---------------------------------------------------------------------------

def test_health_reports_a_flag_for_every_credential_gated_type(client, unconfigured, monkeypatch):
    caps = client.get("/api/v1/health").json()["capabilities"]
    for source_type, cap in job_source_types.CAPABILITY_FOR_SOURCE_TYPE.items():
        assert caps[cap] is False, source_type

    from app.config import settings

    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "i")
    assert client.get("/api/v1/health").json()["capabilities"]["reddit_search_enabled"] is False
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "s")
    assert client.get("/api/v1/health").json()["capabilities"]["reddit_search_enabled"] is True


def test_every_searchable_type_has_a_registered_connector():
    """The validation list must not offer a type the worker cannot dispatch."""
    import app.sources  # noqa: F401  (registers every connector)

    registered = set(registry.all_connectors())
    assert set(job_source_types.SEARCHABLE_SOURCE_TYPES) <= registered
    assert set(job_source_types.LIBRARY_ONLY_SOURCE_TYPES) <= registered


# ---------------------------------------------------------------------------
# Duplicate and templates carry the choice
# ---------------------------------------------------------------------------

def test_duplicate_reads_the_choice_back_from_the_run(client):
    job = client.post("/api/v1/jobs", json=_topic(source_types=["video", "hn_story"])).json()
    assert client.get(f"/api/v1/jobs/{job['id']}").json()["source_types"] == ["video", "hn_story"]
    listed = client.get("/api/v1/jobs").json()
    assert [j["source_types"] for j in listed if j["id"] == job["id"]] == [["video", "hn_story"]]


def test_save_as_template_and_run_from_it_keep_source_types(client, db):
    job = client.post("/api/v1/jobs", json=_topic(source_types=["hn_story", "podcast_episode"])).json()
    r = client.post(f"/api/v1/jobs/{job['id']}/save-as-template", json={"name": "Forums and podcasts"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["parameters"]["source_types"] == ["hn_story", "podcast_episode"]

    run = client.post(f"/api/v1/jobs?template_id={t['id']}", json=_topic(**{
        k: v for k, v in t["parameters"].items() if v is not None
    }))
    assert run.status_code == 201, run.text
    assert run.json()["source_types"] == ["hn_story", "podcast_episode"]


def test_default_run_saves_a_template_without_source_types(client):
    job = client.post("/api/v1/jobs", json=_topic()).json()
    t = client.post(f"/api/v1/jobs/{job['id']}/save-as-template", json={"name": "Plain"}).json()
    assert t["parameters"]["source_types"] is None


def test_template_refuses_what_a_submission_would(client, unconfigured):
    params = {"job_type": "topic", "num_videos": 10, "source_types": ["tweet"]}
    r = client.post("/api/v1/job-templates", json={"name": "Tweets", "parameters": params})
    assert r.status_code == 422
    assert "TWITTER_BEARER_TOKEN" in r.json()["detail"]
    params = {"job_type": "channel", "source_types": ["hn_story"]}
    assert client.post("/api/v1/job-templates", json={"name": "Bad", "parameters": params}).status_code == 422


def test_template_reports_a_source_this_install_no_longer_has(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "TWITTER_BEARER_TOKEN", "t")
    params = {"job_type": "topic", "num_videos": 10, "source_types": ["video", "tweet"]}
    t = client.post("/api/v1/job-templates", json={"name": "With tweets", "parameters": params}).json()
    assert t["problems"] == []

    monkeypatch.setattr(settings, "TWITTER_BEARER_TOKEN", "")
    t = client.get(f"/api/v1/job-templates/{t['id']}").json()
    assert len(t["problems"]) == 1 and "tweet" in t["problems"][0]


def test_a_version_saved_before_source_types_existed_is_not_re_versioned(client, db):
    """Stored text from before the field lacks its key; the same recipe sent
    back is the same version, not a new one."""
    params = {"job_type": "topic", "num_videos": 12, "output_length": "brief"}
    t = client.post("/api/v1/job-templates", json={"name": "Old", "parameters": params}).json()
    row = db.query(JobTemplateVersion).filter_by(template_id=t["id"], version=1).one()
    old = json.loads(row.parameters_json)
    old.pop("source_types")
    row.parameters_json = json.dumps(old, sort_keys=True)
    db.commit()

    r = client.put(f"/api/v1/job-templates/{t['id']}", json={"parameters": params})
    assert r.status_code == 200 and r.json()["version"] == 1
    r = client.put(f"/api/v1/job-templates/{t['id']}", json={"parameters": {**params, "source_types": ["video", "hn_story"]}})
    assert r.json()["version"] == 2
