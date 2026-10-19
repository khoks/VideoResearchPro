"""S-8.6.1 — job templates: save, version, provenance, built-ins, isolation."""
import json

import pytest

from app.models.job import Job
from app.models.job_template import JobTemplate, JobTemplateVersion
from app.schemas.job import JobCreate
from app.schemas.job_template import VARIABLE_FIELDS, TemplateParameters
from app.services import auth_service, job_template_service

TOPIC_PARAMS = {
    "job_type": "topic",
    "search_instructions": "Long-form interviews about {{topic}}; skip clips.",
    "num_videos": 25,
    "min_duration_minutes": 10,
    "channel_type_filters": ["educational"],
    "preferred_channels": ["@lexfridman"],
    "output_length": "deep",
    "visual_analysis": True,
}


@pytest.fixture
def other(db):
    return auth_service.create_user(db, email="other@example.com", password="otherpass123")


@pytest.fixture
def builtin(db):
    t = JobTemplate(tenant_id=None, builtin_key="topic-scan", name="Topic scan", job_type="topic")
    db.add(t)
    db.flush()
    db.add(JobTemplateVersion(template_id=t.id, version=1, parameters_json=json.dumps({"job_type": "topic", "num_videos": 20})))
    db.commit()
    return t


def test_frozen_and_variable_fields_cover_jobcreate_exactly():
    """A new JobCreate field must be decided frozen or variable here; the
    Duplicate flow lost output_length and visual_analysis for want of this."""
    frozen = set(TemplateParameters.model_fields)
    assert frozen | VARIABLE_FIELDS == set(JobCreate.model_fields)
    assert not frozen & VARIABLE_FIELDS


# ---------------------------------------------------------------------------
# Save, version, list
# ---------------------------------------------------------------------------

def test_create_get_and_version_on_parameter_change(client):
    r = client.post("/api/v1/job-templates", json={"name": "Weekly AI policy scan", "parameters": TOPIC_PARAMS})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["version"] == 1 and t["builtin"] is False and t["problems"] == []
    assert t["parameters"]["output_length"] == "deep" and t["parameters"]["visual_analysis"] is True

    # Rename only: same version.
    r = client.put(f"/api/v1/job-templates/{t['id']}", json={"name": "AI policy scan"})
    assert r.json()["version"] == 1 and r.json()["name"] == "AI policy scan"
    # Same parameters again: still no new version.
    r = client.put(f"/api/v1/job-templates/{t['id']}", json={"parameters": TOPIC_PARAMS})
    assert r.json()["version"] == 1
    # Changed parameters: version 2, history kept.
    r = client.put(f"/api/v1/job-templates/{t['id']}", json={"parameters": {**TOPIC_PARAMS, "num_videos": 40}})
    assert r.status_code == 200 and r.json()["version"] == 2
    versions = client.get(f"/api/v1/job-templates/{t['id']}/versions").json()
    assert [(v["version"], v["parameters"]["num_videos"]) for v in versions] == [(2, 40), (1, 25)]


def test_name_collision_case_insensitive_and_reusable_after_delete(client):
    first = client.post("/api/v1/job-templates", json={"name": "Scan", "parameters": TOPIC_PARAMS}).json()
    assert client.post("/api/v1/job-templates", json={"name": "SCAN", "parameters": TOPIC_PARAMS}).status_code == 409
    assert client.delete(f"/api/v1/job-templates/{first['id']}").status_code == 204
    assert client.get(f"/api/v1/job-templates/{first['id']}").status_code == 404
    assert client.post("/api/v1/job-templates", json={"name": "scan", "parameters": TOPIC_PARAMS}).status_code == 201


def test_invalid_parameters_are_rejected_like_a_submission(client):
    # A channel recipe with no channels would fail at submission; refuse it now.
    r = client.post("/api/v1/job-templates", json={"name": "Broken", "parameters": {"job_type": "channel"}})
    assert r.status_code == 422
    assert "channel_list" in r.json()["detail"]
    # Unknown fields are refused rather than silently dropped.
    r = client.post("/api/v1/job-templates", json={"name": "X", "parameters": {**TOPIC_PARAMS, "topic": "frozen?"}})
    assert r.status_code == 422


def test_versions_are_pruned_to_the_newest_twenty(client, db):
    t = client.post("/api/v1/job-templates", json={"name": "Busy", "parameters": TOPIC_PARAMS}).json()
    for n in range(2, 25):
        client.put(f"/api/v1/job-templates/{t['id']}", json={"parameters": {**TOPIC_PARAMS, "num_videos": n}})
    versions = client.get(f"/api/v1/job-templates/{t['id']}/versions").json()
    assert len(versions) == job_template_service.MAX_VERSIONS
    assert versions[0]["version"] == 24 and versions[-1]["version"] == 5


def test_problems_report_a_tier_cap_below_the_recipe(client, test_user):
    t = client.post("/api/v1/job-templates", json={"name": "Huge", "parameters": {**TOPIC_PARAMS, "num_videos": 300}}).json()
    assert test_user.tier == "free"
    assert len(t["problems"]) == 1 and "100" in t["problems"][0]


# ---------------------------------------------------------------------------
# Save a run as a template; start a run from one (provenance)
# ---------------------------------------------------------------------------

def test_save_as_template_freezes_everything_but_the_topic(client):
    job = client.post("/api/v1/jobs", json={**TOPIC_PARAMS, "topic": "tariffs", "search_instructions": "Prefer economists."}).json()
    r = client.post(f"/api/v1/jobs/{job['id']}/save-as-template", json={"name": "Econ deep dive"})
    assert r.status_code == 201, r.text
    p = r.json()["parameters"]
    assert p["output_length"] == "deep" and p["visual_analysis"] is True
    assert p["num_videos"] == 25 and p["preferred_channels"] == ["@lexfridman"]
    assert p["search_instructions"] == "Prefer economists."
    assert "topic" not in p
    assert client.post(f"/api/v1/jobs/{job['id']}/save-as-template", json={"name": "econ DEEP dive"}).status_code == 409


def test_run_from_template_records_provenance_and_fills_topic(client, db):
    t = client.post("/api/v1/job-templates", json={"name": "Interviews", "parameters": TOPIC_PARAMS}).json()
    body = {**TOPIC_PARAMS, "topic": "rare earths"}
    r = client.post(f"/api/v1/jobs?template_id={t['id']}", json=body)
    assert r.status_code == 201, r.text
    job = r.json()
    assert (job["template_id"], job["template_version"]) == (t["id"], 1)
    assert job["search_instructions"] == "Long-form interviews about rare earths; skip clips."
    assert job["output_length"] == "deep" and job["visual_analysis"] is True

    # An explicit older version is recorded as asked.
    client.put(f"/api/v1/job-templates/{t['id']}", json={"parameters": {**TOPIC_PARAMS, "num_videos": 30}})
    r = client.post(f"/api/v1/jobs?template_id={t['id']}&template_version=1", json=body)
    assert r.json()["template_version"] == 1
    assert client.post(f"/api/v1/jobs?template_id={t['id']}&template_version=9", json=body).status_code == 404
    # Type mismatch is refused.
    r = client.post(f"/api/v1/jobs?template_id={t['id']}", json={"job_type": "channel", "channel_list": ["@x"]})
    assert r.status_code == 422


def test_deleted_template_keeps_provenance(client, db):
    t = client.post("/api/v1/job-templates", json={"name": "Gone soon", "parameters": TOPIC_PARAMS}).json()
    job = client.post(f"/api/v1/jobs?template_id={t['id']}", json={**TOPIC_PARAMS, "topic": "x"}).json()
    client.delete(f"/api/v1/job-templates/{t['id']}")
    assert client.get(f"/api/v1/jobs/{job['id']}").json()["template_id"] == t["id"]
    assert db.query(JobTemplateVersion).filter_by(template_id=t["id"]).count() == 1
    # A deleted template cannot start new runs.
    assert client.post(f"/api/v1/jobs?template_id={t['id']}", json={**TOPIC_PARAMS, "topic": "y"}).status_code == 404


def test_topic_placeholder_without_a_template_is_filled_too(client):
    job = client.post("/api/v1/jobs", json={"job_type": "topic", "topic": "lithium", "search_instructions": "Focus on {{topic}} mining."}).json()
    assert job["search_instructions"] == "Focus on lithium mining."


# ---------------------------------------------------------------------------
# Built-ins and isolation
# ---------------------------------------------------------------------------

def test_builtins_are_listed_for_everyone_and_read_only(client, builtin):
    listed = client.get("/api/v1/job-templates").json()
    assert [(t["name"], t["builtin"]) for t in listed] == [("Topic scan", True)]
    assert client.put(f"/api/v1/job-templates/{builtin.id}", json={"name": "Mine now"}).status_code == 403
    assert client.delete(f"/api/v1/job-templates/{builtin.id}").status_code == 403
    r = client.post(f"/api/v1/jobs?template_id={builtin.id}", json={"job_type": "topic", "topic": "x", "num_videos": 20})
    assert r.status_code == 201 and r.json()["template_id"] == builtin.id


def test_own_templates_list_before_builtins(client, builtin):
    client.post("/api/v1/job-templates", json={"name": "Zeta mine", "parameters": TOPIC_PARAMS})
    names = [t["name"] for t in client.get("/api/v1/job-templates").json()]
    assert names == ["Zeta mine", "Topic scan"]


def test_templates_never_cross_tenants(client, db, other):
    theirs = job_template_service.create_template(db, other.id, "Their recipe", TemplateParameters(**TOPIC_PARAMS))
    their_job = Job(tenant_id=other.id, job_type="topic", topic="t", status="completed", num_videos=3)
    db.add(their_job)
    db.commit()

    mine = client.post("/api/v1/job-templates", json={"name": "Their recipe", "parameters": TOPIC_PARAMS})
    assert mine.status_code == 201, "names are unique per reader, not globally"

    assert {t["id"] for t in client.get("/api/v1/job-templates").json()} == {mine.json()["id"]}
    assert client.get(f"/api/v1/job-templates/{theirs.id}").status_code == 404
    assert client.get(f"/api/v1/job-templates/{theirs.id}/versions").status_code == 404
    assert client.put(f"/api/v1/job-templates/{theirs.id}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/job-templates/{theirs.id}").status_code == 404
    assert client.post(f"/api/v1/jobs?template_id={theirs.id}", json={**TOPIC_PARAMS, "topic": "x"}).status_code == 404
    assert client.post(f"/api/v1/jobs/{their_job.id}/save-as-template", json={"name": "steal"}).status_code == 404

    db.expire_all()
    assert job_template_service.get_template(db, theirs.id, other.id).name == "Their recipe"


def test_template_endpoints_require_auth(unauthenticated_client):
    assert unauthenticated_client.get("/api/v1/job-templates").status_code == 401
