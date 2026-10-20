"""S-6.4.2 — newsletter subscriptions and scheduled delivery.

What delivery promises: one issue and one email per period however often the
period is dispatched; a period with nothing new sends nothing; unsubscribing
or turning the digest off stops the next run; the scheduler's tick hands the
task the slot that decides the period; the email carries an HTML part and a
stable Message-ID.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.models.newsletter_subscription import NewsletterSend
from app.models.notification import Notification
from app.models.output import Output
from app.services import auth_service, email_service, newsletter_service, scheduler_service
from tests.test_services.test_book_endnotes import _smoke_run

WEEKLY = {"cadence": "weekly", "weekday": 0, "hour": 8, "timezone": "UTC"}


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    import app.services.outputters  # noqa: F401
    import app.tasks.newsletter_tasks  # noqa: F401 — registers the kind

    monkeypatch.setattr(settings, "OUTPUTS_DIR", str(tmp_path / "outputs"))
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://pratidhvani.example")
    with patch("app.services.progress_service.publish_progress"), patch("app.services.progress_service.publish_status_change"):
        yield


@pytest.fixture
def sent():
    calls: list[dict] = []

    def fake(to, subject, body, *, html=None, message_id=None):
        calls.append({"to": to, "subject": subject, "body": body, "html": html, "message_id": message_id})
        return True

    with patch.object(email_service, "send_email", side_effect=fake):
        yield calls


def _subscriber(db, tmp_path, email="sub@x.com", content=True):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "pro"  # Author Studio
    db.commit()
    if content:
        _smoke_run(db, user.id, tmp_path, topic="Smoking and lungs")  # three documents enter the library now
    return user, newsletter_service.save(db, user, cadence=WEEKLY)


def test_saving_schedules_and_validates(db, tmp_path):
    user, sub = _subscriber(db, tmp_path, content=False)
    run = scheduler_service.get_run(db, "newsletter", sub.id)
    assert run is not None and run.enabled and run.tenant_id == user.id
    assert json.loads(sub.sections_json)["featured"] is False, "D-097: featured stays opt-in"
    with pytest.raises(newsletter_service.NewsletterError):
        newsletter_service.save(db, user, cadence={"cadence": "fortnightly"})
    with pytest.raises(newsletter_service.NewsletterError):
        newsletter_service.save(db, user, sections={"gossip": True})
    with pytest.raises(newsletter_service.NewsletterError):
        newsletter_service.save(db, user, sections={k: False for k in newsletter_service.DEFAULT_SECTIONS})


def test_one_issue_and_one_email_per_period(db, tmp_path, sent):
    user, sub = _subscriber(db, tmp_path)
    slot = datetime(2026, 10, 19, 8, 0)
    first = newsletter_service.deliver(db, sub.id, slot=slot)
    again = newsletter_service.deliver(db, sub.id, slot=slot + timedelta(minutes=5))  # a retried tick
    assert first["status"] == "sent" and again == {"status": "duplicate", "period_key": "2026-W43"}
    assert db.query(Output).filter(Output.user_id == user.id, Output.kind == "newsletter").count() == 1
    assert len(sent) == 1
    mail = sent[0]
    assert mail["to"] == "sub@x.com" and mail["subject"].startswith("Pratidhvani — Your library digest — week 43, 2026")
    assert "## New in your library (3)" in mail["body"] and "<table" in mail["html"]
    assert mail["message_id"] == f"<newsletter.{sub.id}.2026-W43@pratidhvani.example>"
    bell = db.query(Notification).filter(Notification.tenant_id == user.id).all()
    assert len(bell) == 1 and bell[0].kind == "newsletter_issue" and bell[0].href == f"/author/outputs/{first['output_id']}"
    rows = db.query(NewsletterSend).filter(NewsletterSend.subscription_id == sub.id).all()
    assert [(r.period_key, r.status) for r in rows] == [("2026-W43", "sent")]


def test_the_next_period_continues_where_the_last_issue_ended(db, tmp_path, sent):
    user, sub = _subscriber(db, tmp_path, email="sub2@x.com")
    newsletter_service.deliver(db, sub.id, slot=datetime(2026, 10, 19, 8, 0))
    db.refresh(sub)
    ended = sub.last_issue_at
    nothing = newsletter_service.deliver(db, sub.id, slot=datetime(2026, 10, 26, 8, 0))
    assert nothing["status"] == "skipped", "nothing entered the library since the last issue"
    assert len(sent) == 1, "a skipped period sends nothing"
    issue = db.get(Output, nothing["output_id"])
    assert issue.status == "skipped" and json.loads(issue.parameters_json)["since"].startswith(ended.isoformat()[:19])


def test_period_keys_follow_the_subscription_timezone():
    late_sunday_utc = datetime(2026, 10, 18, 20, 0)  # Monday 01:30 in Kolkata
    assert newsletter_service.period_key({"cadence": "weekly", "timezone": "UTC"}, late_sunday_utc) == "2026-W42"
    assert newsletter_service.period_key({"cadence": "weekly", "timezone": "Asia/Kolkata"}, late_sunday_utc) == "2026-W43"
    assert newsletter_service.period_key({"cadence": "daily", "timezone": "Asia/Kolkata"}, late_sunday_utc) == "2026-10-19"
    assert newsletter_service.period_key({"cadence": "monthly", "timezone": "UTC"}, late_sunday_utc) == "2026-10"


def test_unsubscribing_or_turning_off_stops_the_next_run(db, tmp_path, sent):
    user, sub = _subscriber(db, tmp_path, email="sub3@x.com")
    newsletter_service.save(db, user, enabled=False)
    assert scheduler_service.get_run(db, "newsletter", sub.id).enabled is False
    assert newsletter_service.deliver(db, sub.id, slot=datetime(2026, 10, 19, 8, 0)) == {"status": "inactive"}
    with patch("app.services.scheduler_service.task_routing_service.dispatch_for_tenant_id") as dispatch:
        scheduler_service.run_tick(db, now=datetime(2030, 1, 1))
    assert not dispatch.called, "a disabled digest is not dispatched"
    newsletter_service.delete(db, newsletter_service.get_for(db, user.id))
    assert scheduler_service.get_run(db, "newsletter", sub.id) is None
    assert newsletter_service.deliver(db, sub.id) == {"status": "inactive"}
    assert sent == []


def test_a_plan_without_author_studio_stops_the_issues(db, tmp_path, sent):
    user, sub = _subscriber(db, tmp_path, email="sub5@x.com")
    user.tier = "free"
    db.commit()
    assert newsletter_service.deliver(db, sub.id, slot=datetime(2026, 10, 19, 8, 0)) == {"status": "not_entitled"}
    assert sent == [] and db.query(NewsletterSend).filter(NewsletterSend.subscription_id == sub.id).count() == 0


def test_the_tick_dispatches_the_task_with_its_slot(db, tmp_path):
    user, sub = _subscriber(db, tmp_path, email="sub4@x.com", content=False)
    run = scheduler_service.get_run(db, "newsletter", sub.id)
    due = run.next_run_at
    with patch("app.services.scheduler_service.task_routing_service.dispatch_for_tenant_id") as dispatch:
        result = scheduler_service.run_tick(db, now=due + timedelta(seconds=1))
    assert result["dispatched"] == 1
    task, _db, tenant, *args = dispatch.call_args.args
    assert task.name == "newsletter.issue" and tenant == user.id and args == [sub.id]
    assert dispatch.call_args.kwargs["slot"] == due.isoformat()


def test_the_kind_is_registered_from_its_own_task_module():
    assert "newsletter" in scheduler_service.registered_kinds()
    celery_source = (Path(__file__).resolve().parents[2] / "app" / "tasks" / "celery_app.py").read_text(encoding="utf-8")
    assert 'related_name="newsletter_tasks"' in celery_source


def test_the_email_has_an_html_part_and_the_message_id():
    msg = email_service.build_message("a@x.com", "S", "plain", html="<p>rich</p>", message_id="<id@host>")
    assert msg["Message-ID"] == "<id@host>" and msg.is_multipart()
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]
    plain = email_service.build_message("a@x.com", "S", "plain")
    assert not plain.is_multipart() and plain["Message-ID"] is None


def test_router_round_trip(unauthenticated_client, db, tmp_path, sent):
    user = auth_service.create_user(db, email="sub5@x.com", password="pw" * 6)
    user.tier = "pro"
    db.commit()
    _smoke_run(db, user.id, tmp_path, topic="Run")
    token, _ = auth_service.create_access_token(user.id)
    h = {"Authorization": f"Bearer {token}"}
    assert unauthenticated_client.get("/api/v1/author/newsletter", headers=h).json() == {"subscription": None}
    assert unauthenticated_client.post("/api/v1/author/newsletter/send-now", headers=h).status_code == 400
    bad = unauthenticated_client.put("/api/v1/author/newsletter", headers=h, json={"cadence": {"cadence": "hourly"}})
    assert bad.status_code == 400
    body = unauthenticated_client.put("/api/v1/author/newsletter", headers=h,
                                      json={"cadence": {"cadence": "daily", "hour": 7, "timezone": "Asia/Kolkata"},
                                            "sections": {"outputs": False}}).json()["subscription"]
    assert body["cadence"]["cadence"] == "daily" and body["sections"]["outputs"] is False and body["next_issue_at"]
    queued = unauthenticated_client.post("/api/v1/author/newsletter/send-now", headers=h).json()
    assert queued["status"] == "queued"
    now = unauthenticated_client.post("/api/v1/author/newsletter/send-now?sync=true", headers=h).json()
    assert now["status"] == "sent" and now["period_key"].startswith("manual:")
    listed = unauthenticated_client.get("/api/v1/author/newsletter", headers=h).json()["subscription"]
    assert listed["sends"][0]["status"] == "sent" and listed["last_issue_at"]
    assert unauthenticated_client.delete("/api/v1/author/newsletter", headers=h).json() == {"deleted": True}
    assert unauthenticated_client.get("/api/v1/author/newsletter", headers=h).json() == {"subscription": None}
