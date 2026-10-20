"""``/echo/draft`` and ``/echo/drafts`` (S-3.4.1): the contract the Echo bubble hosts.

Tier first (403), then every gate as a 409 with its code, a status object and
words for the user; the private-person confirmation round trip; the daily
cap as a 429; drafts listed, read and deleted per tenant only.
"""
from __future__ import annotations

import uuid

import pytest

from app.config import settings
from app.services import auth_service, echo_draft_service, echo_service
from app.services import quota_metering_service as quota
from tests.test_services.test_echo_draft import deps

DRAFT = "/api/v1/echo/draft"


def _user(db, tier="studio"):
    u = auth_service.create_user(db, email=f"d-{uuid.uuid4().hex[:8]}@example.com", password="pw" * 6)
    u.tier = tier
    db.commit()
    token, _ = auth_service.create_access_token(u.id)
    return u, {"Authorization": f"Bearer {token}"}


def _enable(db, user, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SPEAK_AS_ME_ENABLED", True)
    for k in range(100):
        echo_service.record_context(db, user_id=user.id, kind="interest", key=f"k{k}", value="v", source=f"s{k % 3}")
    echo_service.record_context(db, user_id=user.id, kind="personality_trait", key="t", value="v", source="manual")
    echo_draft_service.record_voice_test(db, user.id, pairs=20, picked_own=12)


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def make(db, user):
        d, calls = deps(**holder.get("kw", {}))
        holder["calls"] = calls
        return d

    monkeypatch.setattr(echo_draft_service, "_real_deps", make)
    return holder


def test_a_tier_without_the_feature_is_refused(unauthenticated_client, db):
    _, h = _user(db, tier="pro")
    assert unauthenticated_client.get(f"{DRAFT}/status", headers=h).status_code == 403
    assert unauthenticated_client.post(DRAFT, json={"message": "hi"}, headers=h).status_code == 403


def test_status_and_a_blocked_draft_say_why_in_words(unauthenticated_client, db, fake):
    _, h = _user(db)
    st = unauthenticated_client.get(f"{DRAFT}/status", headers=h).json()
    assert st["enabled"] is False
    assert [b["code"] for b in st["blockers"]] == ["install_off", "not_ready", "voice_test_required"]
    assert st["voice_gate"] == {"status": "not_run", "run_at": None, "pairs": 0, "picked_own_share": None,
                                "notes_total": 0, "notes_needed": 40}

    r = unauthenticated_client.post(DRAFT, json={"message": "Who pays?"}, headers=h)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "install_off" and detail["message"] and detail["status"]["enabled"] is False
    assert "calls" not in fake, "no model was built, let alone called"


def test_an_enabled_user_gets_a_cited_draft(unauthenticated_client, db, fake, monkeypatch):
    user, h = _user(db)
    _enable(db, user, monkeypatch)
    assert unauthenticated_client.get(f"{DRAFT}/status", headers=h).json()["enabled"] is True

    r = unauthenticated_client.post(DRAFT, json={"message": "Who really pays for tariffs?", "register": "casual", "audience": "my brother"}, headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["draft"] == "Mostly the importer pays first. Then the buyer."
    assert body["register"] == "casual" and body["audience"] == "my brother" and body["language"] == "en"
    assert body["citations"][0]["kind"] == "source" and body["voice_match_score"] == 100.0
    assert body["disclosure"].startswith("Drafted with Echo, reviewed by ")
    assert unauthenticated_client.get(f"{DRAFT}/status", headers=h).json()["drafts_today"] == 1


def test_a_private_person_round_trip(unauthenticated_client, db, fake, monkeypatch):
    user, h = _user(db)
    _enable(db, user, monkeypatch)
    fake["kw"] = {"classify": {"intent": "request", "topic": "dinner", "language": "en", "people": [{"name": "Priya", "public": False}]}}
    r = unauthenticated_client.post(DRAFT, json={"message": "Priya asked about dinner"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "names_need_confirmation"
    assert r.json()["detail"]["names"] == ["Priya"]
    assert unauthenticated_client.get(f"{DRAFT}/status", headers=h).json()["drafts_today"] == 0, "a stopped draft is not counted"

    r = unauthenticated_client.post(DRAFT, json={"message": "Priya asked about dinner", "acknowledge_names": ["Priya"]}, headers=h)
    assert r.status_code == 201


def test_the_daily_cap_is_a_429(unauthenticated_client, db, fake, monkeypatch):
    user, h = _user(db)
    _enable(db, user, monkeypatch)
    for _ in range(20):
        quota.record_usage(db, user.id, "echo_drafts")
    r = unauthenticated_client.post(DRAFT, json={"message": "Who pays?"}, headers=h)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "daily_cap"
    assert [b["code"] for b in unauthenticated_client.get(f"{DRAFT}/status", headers=h).json()["blockers"]] == ["daily_cap"]


def test_drafts_are_listed_read_and_deleted_per_tenant(unauthenticated_client, db, fake, monkeypatch):
    user, h = _user(db)
    _enable(db, user, monkeypatch)
    other, ho = _user(db)
    did = unauthenticated_client.post(DRAFT, json={"message": "Who pays?"}, headers=h).json()["id"]

    assert [d["id"] for d in unauthenticated_client.get("/api/v1/echo/drafts", headers=h).json()["items"]] == [did]
    assert unauthenticated_client.get("/api/v1/echo/drafts", headers=ho).json()["items"] == []
    assert unauthenticated_client.get(f"/api/v1/echo/drafts/{did}", headers=ho).status_code == 404
    assert unauthenticated_client.delete(f"/api/v1/echo/drafts/{did}", headers=ho).status_code == 404
    assert unauthenticated_client.get(f"/api/v1/echo/drafts/{did}", headers=h).json()["message"] == "Who pays?"
    assert unauthenticated_client.delete(f"/api/v1/echo/drafts/{did}", headers=h).status_code == 204
    assert unauthenticated_client.get(f"/api/v1/echo/drafts/{did}", headers=h).status_code == 404


def test_the_request_is_validated(unauthenticated_client, db, fake, monkeypatch):
    user, h = _user(db)
    _enable(db, user, monkeypatch)
    for body in ({"message": ""}, {"message": "x", "register": "shouty"}, {"message": "x", "language": "fr"}, {"message": "x", "send": True}):
        assert unauthenticated_client.post(DRAFT, json=body, headers=h).status_code == 422, body
