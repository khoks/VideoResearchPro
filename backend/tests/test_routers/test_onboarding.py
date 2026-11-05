"""S-8.10.1: ``/auth/me/onboarding`` and the activation events.

The wizard's state is per account, survives a reload (resumable), and its
milestones come from ``jobs`` and ``audit_log``. The events must be wired
at their real producers — job creation and the reader's body route — so
two tests drive those routes rather than the service.
"""
from unittest.mock import patch

import pytest

from app.models.audit_log import AuditLog
from app.models.job import Job
from app.services import auth_service
from app.utils.html_builder import build_report_html

URL = "/api/v1/auth/me/onboarding"


def _events(db, user_id, name):
    return db.query(AuditLog).filter(AuditLog.user_id == user_id, AuditLog.event == name).count()


def _other_user_headers(db):
    other = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    token, _ = auth_service.create_access_token(other.id)
    return other, {"Authorization": f"Bearer {token}"}


def test_fresh_account_is_sent_to_the_wizard(client):
    r = client.get(URL)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["should_onboard"] is True
    assert data["started"] is False
    assert data["onboarded_at"] is None
    assert data["state"]["step"] == 1
    assert data["milestones"] == {"jobs": 0, "first_job": None, "report_opened": False, "questions": 0}
    assert data["state"]["checklist_dismissed"] is False


def test_progress_is_kept_on_the_server_and_resumes(client, db, test_user):
    r = client.patch(URL, json={"step": 2, "channels": [" @3blue1brown ", "@Veritasium", "@3blue1brown", ""]})
    assert r.status_code == 200, r.text
    again = client.get(URL).json()
    assert again["state"]["step"] == 2
    assert again["state"]["choices"]["channels"] == ["@3blue1brown", "@Veritasium"]
    assert again["started"] is True
    assert again["should_onboard"] is True
    client.patch(URL, json={"step": 3})
    assert _events(db, test_user.id, "onboarding_started") == 1  # once, not per patch


def test_a_mid_wizard_account_with_its_first_run_still_resumes(client, db, test_user):
    client.patch(URL, json={"step": 2, "channels": ["@3blue1brown"]})
    job = client.post("/api/v1/jobs", json={"job_type": "channel", "channel_list": ["@3blue1brown"], "videos_per_channel": 5}).json()
    r = client.patch(URL, json={"step": 3, "first_job_id": job["id"]})
    data = r.json()
    assert data["should_onboard"] is True
    assert data["state"]["choices"]["first_job_id"] == job["id"]
    assert data["milestones"]["jobs"] == 1
    assert data["milestones"]["first_job"]["id"] == job["id"]
    assert data["milestones"]["first_job"]["job_type"] == "channel"


def test_existing_accounts_with_runs_are_left_alone(client, db, test_user):
    db.add(Job(job_type="topic", topic="older run", status="completed", num_videos=1, tenant_id=test_user.id))
    db.commit()
    assert client.get(URL).json()["should_onboard"] is False


def test_finishing_sets_onboarded_at_everywhere(client, db, test_user):
    r = client.patch(URL, json={"completed": True})
    data = r.json()
    assert data["onboarded_at"]
    assert data["state"]["completed_at"]
    assert data["should_onboard"] is False
    assert client.get("/api/v1/auth/me").json()["onboarded_at"]
    client.patch(URL, json={"completed": True})
    assert _events(db, test_user.id, "onboarding_completed") == 1


def test_skipping_stops_the_redirect(client, db, test_user):
    data = client.patch(URL, json={"dismissed": True}).json()
    assert data["state"]["dismissed"] is True
    assert data["should_onboard"] is False
    assert data["onboarded_at"] is None
    assert _events(db, test_user.id, "onboarding_skipped") == 1


def test_first_job_id_must_be_your_own_run(client, db):
    foreign = Job(job_type="topic", topic="theirs", status="completed", num_videos=1, tenant_id="someone-else")
    db.add(foreign)
    db.commit()
    r = client.patch(URL, json={"first_job_id": foreign.id})
    assert r.status_code == 404


def test_patch_rejects_unknown_fields_and_out_of_range_values(client):
    assert client.patch(URL, json={"onboarded_at": "2026-01-01"}).status_code == 422
    assert client.patch(URL, json={"step": 4}).status_code == 422
    assert client.patch(URL, json={"channels": ["a", "b", "c", "d", "e", "f"]}).status_code == 422


def test_state_is_per_account(client, db, test_user):
    other, headers = _other_user_headers(db)
    client.patch(URL, json={"step": 3, "channels": ["@mine"]})
    theirs = client.get(URL, headers=headers).json()
    assert theirs["state"]["step"] == 1
    assert theirs["state"]["choices"]["channels"] == []
    assert theirs["started"] is False


def test_requires_auth(unauthenticated_client):
    assert unauthenticated_client.get(URL).status_code == 401
    assert unauthenticated_client.patch(URL, json={"step": 2}).status_code == 401


def test_first_job_created_is_recorded_once_by_job_creation(client, db, test_user):
    body = {"job_type": "channel", "channel_list": ["@3blue1brown"], "videos_per_channel": 5}
    first = client.post("/api/v1/jobs", json=body)
    assert first.status_code == 201
    client.post("/api/v1/jobs", json=body)
    rows = db.query(AuditLog).filter(AuditLog.user_id == test_user.id, AuditLog.event == "first_job_created").all()
    assert len(rows) == 1
    assert first.json()["id"] in rows[0].metadata_json


def test_first_report_opened_is_recorded_once_by_the_reader(client, db, test_user, tmp_path):
    job = Job(job_type="topic", topic="read me", status="completed", num_videos=1, report_path=str(tmp_path / "r.html"), tenant_id=test_user.id)
    db.add(job)
    db.commit()
    html = build_report_html(title="Research Report: read me", job_type="topic", statistics={
        "video_count": 1, "transcript_count": 1, "total_words": 10, "total_minutes": 1, "channel_breakdown": [],
    }, report_body="<h2>One</h2><p>x</p>")
    with patch("app.routers.reports.report_service.get_report_html", return_value=html):
        assert client.get(f"/api/v1/jobs/{job.id}/report/body").status_code == 200
        assert client.get(f"/api/v1/jobs/{job.id}/report/body").status_code == 200
    assert _events(db, test_user.id, "first_report_opened") == 1
    assert client.get(URL).json()["milestones"]["report_opened"] is True


def test_questions_milestone_counts_every_surface(client, db, test_user):
    """S-8.10.2: the checklist's third item. A run, the library and the
    history chat each count; another account's questions do not."""
    from app.models.library_qa_exchange import LibraryQAExchange
    from app.models.qa_exchange import QAExchange
    from app.models.qa_history_exchange import QAHistoryExchange

    job = Job(job_type="topic", topic="t", status="completed", num_videos=1, tenant_id=test_user.id)
    db.add(job)
    db.commit()
    db.add_all([
        QAExchange(job_id=job.id, tenant_id=test_user.id, question="q1", answer="a", references="[]"),
        LibraryQAExchange(tenant_id=test_user.id, question="q2", answer="a"),
        QAHistoryExchange(tenant_id=test_user.id, question="q3", answer="a"),
        LibraryQAExchange(tenant_id="someone-else", question="theirs", answer="a"),
    ])
    db.commit()
    assert client.get(URL).json()["milestones"]["questions"] == 3


def test_hiding_the_checklist_does_not_start_the_wizard(client, db, test_user):
    data = client.patch(URL, json={"checklist_dismissed": True}).json()
    assert data["state"]["checklist_dismissed"] is True
    assert data["state"]["checklist_dismissed_at"]
    assert data["started"] is False
    assert data["should_onboard"] is True  # a fresh account is still sent to /welcome
    assert _events(db, test_user.id, "onboarding_started") == 0
    # and it survives a later wizard patch
    client.patch(URL, json={"step": 2})
    assert client.get(URL).json()["state"]["checklist_dismissed"] is True


def test_channels_not_yet_run_are_the_wizards_other_channels(client, db, test_user):
    """T-8.10.1.7: the submit page pre-fills its channel list with the
    wizard's channels that no run has named. The first run reads one; the
    rest stay offered until a run names them, however the link is written."""
    chosen = ["@first", "@Second", "https://www.youtube.com/@third/videos", "@fourth"]
    assert client.patch(URL, json={"step": 2, "channels": chosen}).status_code == 200
    assert client.get(URL).json()["channels_not_yet_run"] == chosen

    first = client.post("/api/v1/jobs", json={"job_type": "channel", "channel_list": ["@first"], "videos_per_channel": 5})
    assert first.status_code == 201, first.text
    assert client.get(URL).json()["channels_not_yet_run"] == chosen[1:]

    # A later run that names two of them as URLs, in another case.
    later = client.post("/api/v1/jobs", json={
        "job_type": "channel",
        "channel_list": ["https://youtube.com/@second/", "@THIRD"],
        "videos_per_channel": 5,
    })
    assert later.status_code == 201, later.text
    assert client.get(URL).json()["channels_not_yet_run"] == ["@fourth"]


@pytest.mark.parametrize(
    "chosen, named",
    [
        ("UCabcdefghijklmnopqrstuv", "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv"),
        ("https://youtube.com/channel/UCabcdefghijklmnopqrstuv/", "UCabcdefghijklmnopqrstuv"),
        ("youtube.com/channel/UCabcdefghijklmnopqrstuv", "https://www.youtube.com/channel/ucabcdefghijklmnopqrstuv/videos"),
    ],
)
def test_a_channel_id_and_its_url_are_one_channel(client, db, test_user, chosen, named):
    """The wizard and the submit page both accept a bare UC id and its URL.
    Offering one after a run named the other would say, falsely, that no run
    has read it."""
    assert client.patch(URL, json={"channels": [chosen, "@other"]}).status_code == 200
    run = client.post("/api/v1/jobs", json={"job_type": "channel", "channel_list": [named], "videos_per_channel": 5})
    assert run.status_code == 201, run.text
    assert client.get(URL).json()["channels_not_yet_run"] == ["@other"]


def test_channels_not_yet_run_ignores_other_accounts_runs(client, db, test_user):
    other, _ = _other_user_headers(db)
    db.add(Job(job_type="channel", status="completed", num_videos=1, tenant_id=other.id, channel_list='["@mine"]'))
    db.add(Job(job_type="channel", status="completed", num_videos=1, tenant_id=test_user.id, channel_list="not json"))
    db.commit()
    client.patch(URL, json={"channels": ["@mine"]})
    assert client.get(URL).json()["channels_not_yet_run"] == ["@mine"]


def test_no_wizard_channels_means_nothing_to_prefill(client):
    assert client.get(URL).json()["channels_not_yet_run"] == []
