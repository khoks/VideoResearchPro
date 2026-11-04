"""S-8.6.3 — the relative publish window, verified at its production callers.

``POST /api/v1/jobs`` stores it, the template routes carry it, and
``execute_topic_job`` hands it to the search agent. The chain tests below run
the real Celery task body and the real LangGraph search agent; only YouTube
and the model are fake, so a window that is dropped anywhere on the way from
the request to the ranking prompt fails here.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from app.agents import search_agent
from app.models.job import Job
from app.models.job_template import JobTemplateVersion
from app.schemas.job import MAX_PUBLISHED_AFTER_DAYS
from app.sources.types import Candidate, SourceMetadata
from app.tasks import job_tasks

TOPIC = {"job_type": "topic", "topic": "tariffs", "num_videos": 2}
# A template recipe: `{{topic}}` and every other frozen field, no topic.
RECIPE = {"job_type": "topic", "num_videos": 2, "search_instructions": "About {{topic}}"}


def _ranking_candidates() -> dict[str, datetime]:
    return {
        "yt_recent000": datetime(2026, 10, 30),
        "yt_classic00": datetime(2011, 3, 1),
        "yt_classic01": datetime(2012, 3, 1),
    }


@pytest.fixture
def real_search(db, monkeypatch):
    """The real `execute_topic_job` and real search agent over a fake YouTube
    and a fake model. Yields a runner returning the ranking prompt."""
    from app.services import progress_service

    published = _ranking_candidates()

    class _FakeYouTube:
        def search(self, query, instructions="", limit=10):
            return [
                Candidate(
                    source_type="video",
                    source_id=vid,
                    title=f"Video {vid}",
                    source_url=f"https://www.youtube.com/watch?v={vid}",
                    creator_external_id=f"UC_{vid}",
                    creator_name=f"Channel {vid}",
                )
                for vid in published
            ]

        def fetch_metadata(self, ids):
            return {
                vid: SourceMetadata(
                    title=f"Video {vid}",
                    creator_external_id=f"UC_{vid}",
                    creator_name=f"Channel {vid}",
                    duration_seconds=900,
                    published_at=published[vid],
                    extra={"url": f"https://www.youtube.com/watch?v={vid}"},
                )
                for vid in ids
            }

    # The model ranks the two OLD videos first: if the window were a filter,
    # they could not come back from it.
    picks = ["yt_classic00", "yt_classic01"]
    prompts: list[str] = []

    def _llm_for(use_case, **kwargs):
        llm = MagicMock()
        if use_case == "search_plan_queries":
            llm.invoke.return_value = MagicMock(
                content=json.dumps({"broad_queries": ["q1"], "channel_keywords": []})
            )
            return llm

        def _rank(messages):
            prompts.append(messages[0].content)
            return MagicMock(content=json.dumps(picks))

        llm.invoke.side_effect = _rank
        return llm

    monkeypatch.setattr(job_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(search_agent, "get_llm_for", _llm_for)
    monkeypatch.setattr(search_agent, "connector_for", lambda st: _FakeYouTube())
    monkeypatch.setattr(search_agent, "_lookup_known_eras", lambda ids: {})
    monkeypatch.setattr(search_agent.youtube_service, "get_channel_subscribers", lambda ids: {})
    monkeypatch.setattr(progress_service, "publish_progress", lambda *a, **kw: None)
    monkeypatch.setattr(progress_service, "publish_status_change", lambda *a, **kw: None)

    def _run(job_id: str, today: date) -> str:
        monkeypatch.setattr(search_agent, "_today", lambda: today)
        prompts.clear()
        job_tasks.execute_topic_job.run(job_id)
        assert len(prompts) == 1, "one candidate pool, one ranking call"
        return prompts[0]

    return _run


# --- POST /jobs ---------------------------------------------------------------

def test_job_stores_and_returns_the_window(client, db):
    r = client.post("/api/v1/jobs", json={**TOPIC, "published_after_days": 30})
    assert r.status_code == 201, r.text
    assert r.json()["published_after_days"] == 30
    assert db.get(Job, r.json()["id"]).published_after_days == 30
    assert client.get(f"/api/v1/jobs/{r.json()['id']}").json()["published_after_days"] == 30


def test_omitted_window_is_null(client, db):
    r = client.post("/api/v1/jobs", json=TOPIC)
    assert r.status_code == 201, r.text
    assert r.json()["published_after_days"] is None
    assert db.get(Job, r.json()["id"]).published_after_days is None


@pytest.mark.parametrize("value", [0, -7, MAX_PUBLISHED_AFTER_DAYS + 1, 1.5, "soon"])
def test_a_window_out_of_range_is_refused(client, value):
    r = client.post("/api/v1/jobs", json={**TOPIC, "published_after_days": value})
    assert r.status_code == 422


def test_the_widest_window_is_accepted_and_resolves(client, db, real_search):
    r = client.post("/api/v1/jobs", json={**TOPIC, "published_after_days": MAX_PUBLISHED_AFTER_DAYS})
    assert r.status_code == 201, r.text
    assert "on or after 2016-11-06" in real_search(r.json()["id"], date(2026, 11, 4))


@pytest.mark.parametrize(
    "body",
    [
        {"job_type": "channel", "channel_list": ["@a"]},
        {"job_type": "subscription", "channel_list": ["@a"]},
    ],
)
def test_a_window_on_a_channel_run_is_refused_not_ignored(client, body):
    r = client.post("/api/v1/jobs", json={**body, "published_after_days": 30})
    assert r.status_code == 422
    assert "topic research only" in r.text
    assert client.post("/api/v1/jobs", json=body).status_code == 201


def test_a_window_on_a_run_that_never_ranks_is_refused_not_ignored(client):
    """Only YouTube results are ranked, so a podcast-only window does nothing."""
    body = {**TOPIC, "source_types": ["podcast_episode"], "published_after_days": 30}
    r = client.post("/api/v1/jobs", json=body)
    assert r.status_code == 422
    assert "must search YouTube" in r.text


def test_a_mixed_run_that_includes_youtube_may_set_a_window(client):
    body = {**TOPIC, "source_types": ["video", "hn_story"], "published_after_days": 30}
    assert client.post("/api/v1/jobs", json=body).status_code == 201


# --- the worker ---------------------------------------------------------------

def test_worker_hands_the_window_to_the_search_agent(client, db, monkeypatch):
    from app.services import progress_service

    seen: list = []

    def _search_agent(**kwargs):
        seen.append(kwargs["published_after_days"])
        return [], ["q1"], []

    monkeypatch.setattr(job_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr("app.agents.search_agent.run_search_agent", _search_agent)
    monkeypatch.setattr(progress_service, "publish_progress", lambda *a, **kw: None)
    monkeypatch.setattr(progress_service, "publish_status_change", lambda *a, **kw: None)
    monkeypatch.setattr(progress_service, "publish_error", lambda *a, **kw: None)

    for body in ({**TOPIC, "published_after_days": 45}, TOPIC):
        job_tasks.execute_topic_job.run(client.post("/api/v1/jobs", json=body).json()["id"])
    assert seen == [45, None]


def test_request_to_ranking_prompt(client, real_search):
    job_id = client.post("/api/v1/jobs", json={**TOPIC, "published_after_days": 30}).json()["id"]
    prompt = real_search(job_id, date(2026, 11, 4))
    assert "PUBLISH WINDOW (the user set this for this run)" in prompt
    assert "on or after 2026-10-05, the last 30 days" in prompt


def test_unset_window_never_reaches_the_ranking_prompt(client, real_search):
    job_id = client.post("/api/v1/jobs", json=TOPIC).json()["id"]
    assert "PUBLISH WINDOW" not in real_search(job_id, date(2026, 11, 4))


def test_the_date_is_resolved_when_the_run_ranks_not_when_it_was_saved(client, db, real_search):
    """One recipe, used twice, months apart: each run counts back from its own
    day. Stored days stay days, so nothing about the template went stale."""
    t = client.post(
        "/api/v1/job-templates",
        json={"name": "Weekly scan", "parameters": {**RECIPE, "published_after_days": 7}},
    ).json()
    run = {**RECIPE, "topic": "tariffs", "published_after_days": 7}

    first = client.post(f"/api/v1/jobs?template_id={t['id']}", json=run).json()["id"]
    assert "on or after 2026-03-25, the last 7 days" in real_search(first, date(2026, 4, 1))

    second = client.post(f"/api/v1/jobs?template_id={t['id']}", json=run).json()["id"]
    assert "on or after 2026-11-24, the last 7 days" in real_search(second, date(2026, 12, 1))

    assert db.get(Job, first).published_after_days == db.get(Job, second).published_after_days == 7


def test_a_job_queued_before_midnight_counts_from_the_day_it_runs(client, db, real_search):
    job_id = client.post("/api/v1/jobs", json={**TOPIC, "published_after_days": 1}).json()["id"]
    db.get(Job, job_id).created_at = datetime(2020, 1, 1)
    db.commit()
    assert "on or after 2026-11-03, the last day" in real_search(job_id, date(2026, 11, 4))


def test_videos_outside_the_window_reach_the_approval_list(client, db, real_search):
    """The whole point of "never a filter": the model chose two old videos
    over a recent one and a 30-day window did not stop it."""
    job_id = client.post("/api/v1/jobs", json={**TOPIC, "published_after_days": 30}).json()["id"]
    real_search(job_id, date(2026, 11, 4))

    assert db.get(Job, job_id).status == "awaiting_approval"
    videos = client.get(f"/api/v1/jobs/{job_id}/videos").json()
    assert {v["video_id"] for v in videos} == {"yt_classic00", "yt_classic01"}


# --- templates ----------------------------------------------------------------

def test_template_round_trip(client):
    params = {**RECIPE, "published_after_days": 30}
    t = client.post("/api/v1/job-templates", json={"name": "Scan", "parameters": params})
    assert t.status_code == 201, t.text
    assert t.json()["parameters"]["published_after_days"] == 30
    fetched = client.get(f"/api/v1/job-templates/{t.json()['id']}").json()
    assert fetched["parameters"]["published_after_days"] == 30
    listed = {x["id"]: x for x in client.get("/api/v1/job-templates").json()}
    assert listed[t.json()["id"]]["parameters"]["published_after_days"] == 30


def test_save_as_template_keeps_a_runs_window(client):
    job = client.post("/api/v1/jobs", json={**TOPIC, "published_after_days": 14}).json()
    r = client.post(f"/api/v1/jobs/{job['id']}/save-as-template", json={"name": "From run"})
    assert r.status_code == 201, r.text
    assert r.json()["parameters"]["published_after_days"] == 14

    plain = client.post("/api/v1/jobs", json=TOPIC).json()
    r = client.post(f"/api/v1/jobs/{plain['id']}/save-as-template", json={"name": "Plain"})
    assert r.json()["parameters"]["published_after_days"] is None


def test_changing_the_window_adds_a_version_and_resaving_does_not(client):
    t = client.post(
        "/api/v1/job-templates",
        json={"name": "Scan", "parameters": {**RECIPE, "published_after_days": 30}},
    ).json()
    same = client.put(
        f"/api/v1/job-templates/{t['id']}",
        json={"parameters": {**RECIPE, "published_after_days": 30}},
    ).json()
    assert same["version"] == 1
    changed = client.put(
        f"/api/v1/job-templates/{t['id']}",
        json={"parameters": {**RECIPE, "published_after_days": 7}},
    ).json()
    assert changed["version"] == 2
    history = client.get(f"/api/v1/job-templates/{t['id']}/versions").json()
    assert [(v["version"], v["parameters"]["published_after_days"]) for v in history] == [(2, 7), (1, 30)]


def test_a_version_saved_before_the_field_existed_gains_no_version(client, db):
    """S-1.5.13's rule: a new optional field never versions an identical save."""
    t = client.post("/api/v1/job-templates", json={"name": "Old", "parameters": RECIPE}).json()
    row = db.get(JobTemplateVersion, (t["id"], 1))
    stored = json.loads(row.parameters_json)
    del stored["published_after_days"]
    row.parameters_json = json.dumps(stored)
    db.commit()

    r = client.put(f"/api/v1/job-templates/{t['id']}", json={"parameters": RECIPE})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1
    assert r.json()["parameters"]["published_after_days"] is None


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"job_type": "channel", "channel_list": ["@a"], "published_after_days": 7}, "topic research only"),
        ({**RECIPE, "source_types": ["hn_story", "podcast_episode"], "published_after_days": 7}, "must search YouTube"),
    ],
)
def test_a_template_cannot_hold_a_window_a_run_would_refuse(client, params, message):
    r = client.post("/api/v1/job-templates", json={"name": "Bad", "parameters": params})
    assert r.status_code == 422
    assert message in r.text


@pytest.mark.parametrize("value", [0, MAX_PUBLISHED_AFTER_DAYS + 1])
def test_a_template_window_out_of_range_is_refused(client, value):
    r = client.post(
        "/api/v1/job-templates",
        json={"name": "Bad", "parameters": {**RECIPE, "published_after_days": value}},
    )
    assert r.status_code == 422
