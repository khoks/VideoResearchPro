"""The job API must report what was stored.

`visual_analysis` and `output_length` were persisted by POST /jobs but dropped
by `job_to_response_dict`, so every job read back as visual_analysis=False and
output_length=None (found 2026-10-19 while measuring R1: the DB row said True,
the API said False). A UI toggle built on the response would have shown the
wrong state for every job.
"""
from __future__ import annotations


def _create(client, **overrides):
    payload = {
        "job_type": "topic",
        "topic": "matplotlib tutorials",
        "num_videos": 3,
        "visual_analysis": True,
        "output_length": "deep",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/jobs", json=payload)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def test_create_response_echoes_visual_analysis_and_output_length(client):
    body = _create(client)
    assert body["visual_analysis"] is True
    assert body["output_length"] == "deep"


def test_get_and_list_report_the_stored_values(client):
    created = _create(client)
    got = client.get(f"/api/v1/jobs/{created['id']}").json()
    assert got["visual_analysis"] is True
    assert got["output_length"] == "deep"

    listed = client.get("/api/v1/jobs").json()
    items = listed if isinstance(listed, list) else listed.get("jobs") or listed.get("items")
    row = next(j for j in items if j["id"] == created["id"])
    assert row["visual_analysis"] is True
    assert row["output_length"] == "deep"


def test_defaults_read_back_as_false_and_none(client):
    body = _create(client, visual_analysis=False, output_length=None)
    got = client.get(f"/api/v1/jobs/{body['id']}").json()
    assert got["visual_analysis"] is False
    assert got["output_length"] is None
