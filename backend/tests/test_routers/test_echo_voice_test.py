"""``/echo/voice-test`` (T-3.4.1.8): the "which of these did you write?" test, in the app.

At the production caller, with the draft model patched:

- Tier first (403). Then the install switch, readiness and the 40-note
  floor, each said in words instead of offering the test, with nothing spent.
- Start writes 20 blinded pairs (inline here, a Celery task in production).
  The page gets the texts, never which side is the user's.
- Picks are stored one pair at a time; scoring needs all of them.
- The score is ``user-score``'s and the gate is written as ``--record``
  writes it: a pass opens speak as me, a fail does not (and a failed retake
  closes it again).
- Every test is its owner's: another tenant's id is a 404.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.config import settings
from app.models.echo_draft import EchoVoiceGate
from app.models.echo_voice_test import EchoVoiceTest
from app.models.job import Job
from app.services import auth_service, echo_draft_service, note_service, task_routing_service
from app.services import echo_voice_test_service as vt
from app.services.llm_routing import resolve_config
from tests.test_services.test_echo_draft import _make_ready
from tests.test_services.test_echo_voice_test import NOTES, FakeModel

VT = "/api/v1/echo/voice-test"


def _user(db, tier="studio", notes=NOTES):
    u = auth_service.create_user(db, email=f"vt-{uuid.uuid4().hex[:8]}@example.com", password="pw" * 6)
    u.tier = tier
    job_id = f"job-{u.id[:8]}"
    db.add(Job(id=job_id, tenant_id=u.id, job_type="topic", topic="t", status="completed"))
    db.commit()
    for text in notes:
        note_service.create_note(db, u.id, target_type="job", target_id=job_id, body_md=text)
    token, _ = auth_service.create_access_token(u.id)
    return u, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    built = []

    def drafter(db, tenant_id):
        built.append(tenant_id)
        return fake

    monkeypatch.setattr(vt, "_drafter", drafter)
    monkeypatch.setattr(settings, "ECHO_VOICE_TEST_GENERATION", "inline")
    fake.built = built
    return fake


def _open(monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SPEAK_AS_ME_ENABLED", True)
    _make_ready(monkeypatch)


def _key(db, test_id):
    db.expire_all()
    return {k["pair"]: k["own_is"] for k in json.loads(db.get(EchoVoiceTest, test_id).key_json)}


def _pick_own(client, h, db, test_id, own: int):
    """Pick the user's own text in the first ``own`` pairs, the draft in the rest."""
    key = _key(db, test_id)
    for i, (pair, own_is) in enumerate(sorted(key.items())):
        choice = own_is if i < own else ("B" if own_is == "A" else "A")
        r = client.put(f"{VT}/{test_id}/picks", json={"pair": pair, "pick": choice}, headers=h)
        assert r.status_code == 200, r.text


def _started(client, h):
    r = client.post(VT, headers=h)
    assert r.status_code == 202, r.text
    return r.json()


def test_a_tier_without_the_feature_is_refused(unauthenticated_client, db, model):
    _, h = _user(db, tier="pro", notes=[])
    assert unauthenticated_client.get(VT, headers=h).status_code == 403
    assert unauthenticated_client.post(VT, headers=h).status_code == 403
    assert unauthenticated_client.get(f"{VT}/x", headers=h).status_code == 403
    assert unauthenticated_client.put(f"{VT}/x/picks", json={"pair": "p01", "pick": "A"}, headers=h).status_code == 403
    assert unauthenticated_client.post(f"{VT}/x/score", headers=h).status_code == 403
    assert model.prompts == [] and model.built == []


def test_install_off_or_not_ready_says_why_instead_of_offering_the_test(unauthenticated_client, db, model, monkeypatch):
    user, h = _user(db)
    body = unauthenticated_client.get(VT, headers=h).json()
    off = body["offer"]
    assert off["available"] is False
    assert [b["code"] for b in off["blockers"]] == ["install_off", "not_ready"]
    draft_gate = {b["code"]: b["message"] for b in echo_draft_service.status(db, user).blockers}
    assert all(b["message"] == draft_gate[b["code"]] for b in off["blockers"]), "the same words as the draft gate"
    model_name = resolve_config("echo_draft").model
    assert (off["pairs"], off["model_calls"], off["model"], off["notes"], off["notes_needed"]) == (20, 40, model_name, 48, 40)
    assert body["test"] is None and body["gate"]["status"] == "not_run"

    r = unauthenticated_client.post(VT, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "install_off"

    monkeypatch.setattr(settings, "ECHO_SPEAK_AS_ME_ENABLED", True)
    r = unauthenticated_client.post(VT, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_ready"
    assert r.json()["detail"]["message"].startswith("Echo needs more to go on first")

    _make_ready(monkeypatch)
    few, hf = _user(db, notes=NOTES[:39])
    off = unauthenticated_client.get(VT, headers=hf).json()["offer"]
    assert [b["code"] for b in off["blockers"]] == ["notes_needed"]
    assert "needs 40 of your notes" in off["blockers"][0]["message"] and "You have 39." in off["blockers"][0]["message"]
    assert unauthenticated_client.post(VT, headers=hf).status_code == 409

    assert model.prompts == [] and model.built == [], "nothing spent while a gate is shut"
    assert db.query(EchoVoiceTest).count() == 0


def test_start_writes_blinded_pairs_without_the_key(unauthenticated_client, db, model, monkeypatch):
    user, h = _user(db)
    _open(monkeypatch)
    assert unauthenticated_client.get(VT, headers=h).json()["offer"]["available"] is True

    test = _started(unauthenticated_client, h)
    assert test["status"] == "ready" and test["pairs_built"] == 20 and len(test["pairs"]) == 20
    assert len(model.prompts) == 40 and model.built == [user.id]
    notes = {n.body_md for n in note_service.iter_notes(db, user.id, include_deleted=False)}
    for p in test["pairs"]:
        assert set(p) == {"pair", "A", "B"}
        assert (p["A"] in notes) != (p["B"] in notes), "one side is the user's note, the other the draft"
    shown = json.dumps(unauthenticated_client.get(f"{VT}/{test['id']}", headers=h).json())
    assert "own_is" not in shown and "note_id" not in shown
    assert unauthenticated_client.get(VT, headers=h).json()["test"]["id"] == test["id"]
    row = db.get(EchoVoiceTest, test["id"])
    assert row.cost_usd > 0 and row.tokens_in == 20 * 940


def test_the_gate_opens_on_a_pass_and_not_on_a_fail(unauthenticated_client, db, model, monkeypatch):
    _open(monkeypatch)
    passer, hp = _user(db)
    test = _started(unauthenticated_client, hp)
    _pick_own(unauthenticated_client, hp, db, test["id"], own=16)
    r = unauthenticated_client.post(f"{VT}/{test['id']}/score", headers=hp)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["test"]["status"] == "scored" and body["test"]["pairs"] == []
    assert body["test"]["result"] == {"pairs": 20, "picked_own": 16, "picked_own_share": 0.8, "passed": True}
    assert body["gate"]["status"] == "passed" and body["gate"]["pairs"] == 20 and body["gate"]["picked_own_share"] == 0.8
    st = echo_draft_service.status(db, passer)
    assert st.enabled is True, "the pass is what turns speak as me on"

    failer, hf = _user(db)
    test = _started(unauthenticated_client, hf)
    _pick_own(unauthenticated_client, hf, db, test["id"], own=17)
    body = unauthenticated_client.post(f"{VT}/{test['id']}/score", headers=hf).json()
    assert body["test"]["result"]["passed"] is False and body["gate"]["status"] == "failed"
    st = echo_draft_service.status(db, failer)
    assert st.enabled is False and [b["code"] for b in st.blockers] == ["voice_test_failed"]
    assert "85% of 20 pairs" in st.blockers[0]["message"]
    gate = db.query(EchoVoiceGate).filter(EchoVoiceGate.tenant_id == failer.id).one()
    assert (gate.status, gate.pairs, gate.picked_own_share) == ("failed", 20, 0.85)


def test_a_failed_retake_closes_the_gate_as_record_does(unauthenticated_client, db, model, monkeypatch):
    _open(monkeypatch)
    user, h = _user(db)
    first = _started(unauthenticated_client, h)
    _pick_own(unauthenticated_client, h, db, first["id"], own=10)
    unauthenticated_client.post(f"{VT}/{first['id']}/score", headers=h)
    assert echo_draft_service.voice_gate(db, user.id)["status"] == "passed"

    again = _started(unauthenticated_client, h)
    assert again["id"] != first["id"]
    _pick_own(unauthenticated_client, h, db, again["id"], own=20)
    unauthenticated_client.post(f"{VT}/{again['id']}/score", headers=h)
    assert echo_draft_service.voice_gate(db, user.id)["status"] == "failed"
    assert db.query(EchoVoiceGate).filter(EchoVoiceGate.tenant_id == user.id).count() == 1


def test_picks_are_checked_and_scoring_needs_every_pair(unauthenticated_client, db, model, monkeypatch):
    _open(monkeypatch)
    user, h = _user(db)
    test = _started(unauthenticated_client, h)
    url = f"{VT}/{test['id']}"
    assert unauthenticated_client.put(f"{url}/picks", json={"pair": "p01", "pick": "C"}, headers=h).status_code == 422
    assert unauthenticated_client.put(f"{url}/picks", json={"pair": "p99", "pick": "A"}, headers=h).status_code == 422
    for i in range(1, 20):
        unauthenticated_client.put(f"{url}/picks", json={"pair": f"p{i:02d}", "pick": "A"}, headers=h)
    # A pick can be changed before scoring.
    r = unauthenticated_client.put(f"{url}/picks", json={"pair": "p01", "pick": "B"}, headers=h)
    assert r.json()["picks"]["p01"] == "B" and len(r.json()["picks"]) == 19

    r = unauthenticated_client.post(f"{url}/score", headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "incomplete" and "1 left" in r.json()["detail"]["message"]
    assert echo_draft_service.voice_gate(db, user.id)["status"] == "not_run", "nothing recorded"

    unauthenticated_client.put(f"{url}/picks", json={"pair": "p20", "pick": "A"}, headers=h)
    assert unauthenticated_client.post(f"{url}/score", headers=h).status_code == 200
    assert unauthenticated_client.post(f"{url}/score", headers=h).json()["detail"]["code"] == "not_open"
    r = unauthenticated_client.put(f"{url}/picks", json={"pair": "p01", "pick": "A"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_open"


def test_a_test_belongs_to_its_tenant(unauthenticated_client, db, model, monkeypatch):
    _open(monkeypatch)
    _, ha = _user(db)
    _, hb = _user(db)
    test = _started(unauthenticated_client, ha)
    url = f"{VT}/{test['id']}"
    assert unauthenticated_client.get(url, headers=hb).status_code == 404
    assert unauthenticated_client.put(f"{url}/picks", json={"pair": "p01", "pick": "A"}, headers=hb).status_code == 404
    assert unauthenticated_client.post(f"{url}/score", headers=hb).status_code == 404
    assert unauthenticated_client.get(VT, headers=hb).json()["test"] is None


def test_one_open_test_at_a_time_and_a_daily_limit(unauthenticated_client, db, model, monkeypatch):
    _open(monkeypatch)
    monkeypatch.setattr(settings, "ECHO_VOICE_TESTS_PER_DAY", 2)
    _, h = _user(db)
    test = _started(unauthenticated_client, h)
    r = unauthenticated_client.post(VT, headers=h)
    assert r.status_code == 409 and r.json()["detail"] == {"code": "test_open", "message": "Finish the test you started first."}

    _pick_own(unauthenticated_client, h, db, test["id"], own=10)
    unauthenticated_client.post(f"{VT}/{test['id']}/score", headers=h)
    second = _started(unauthenticated_client, h)
    _pick_own(unauthenticated_client, h, db, second["id"], own=10)
    unauthenticated_client.post(f"{VT}/{second['id']}/score", headers=h)
    off = unauthenticated_client.get(VT, headers=h).json()["offer"]
    assert [b["code"] for b in off["blockers"]] == ["daily_limit"] and off["tests_today"] == 2
    assert unauthenticated_client.post(VT, headers=h).status_code == 409
    assert len(model.prompts) == 80, "two tests, forty calls each, and no third"


def test_in_production_the_request_only_queues(unauthenticated_client, db, model, monkeypatch):
    _open(monkeypatch)
    monkeypatch.setattr(settings, "ECHO_VOICE_TEST_GENERATION", "celery")
    queued = []
    monkeypatch.setattr(task_routing_service, "dispatch_for_user", lambda task, user, *args: queued.append((task.name, user.id, args)))
    user, h = _user(db)
    test = _started(unauthenticated_client, h)
    assert test["status"] == "generating" and test["pairs"] == [] and test["pairs_built"] == 0
    assert queued == [("echo.generate_voice_test", user.id, (test["id"],))]
    assert model.prompts == [], "the model is called by the worker, not the request"
    body = unauthenticated_client.get(VT, headers=h).json()
    assert body["offer"]["blockers"] == [{"code": "test_open", "message": "Your test is being written."}]

    # The task itself, on the worker.
    from app.tasks import echo_tasks

    monkeypatch.setattr(echo_tasks, "SessionLocal", lambda: _NoClose(db))
    assert echo_tasks.generate_voice_test_task(test["id"]) == "ready"
    assert unauthenticated_client.get(f"{VT}/{test['id']}", headers=h).json()["pairs_built"] == 20


def test_a_queue_failure_says_so(unauthenticated_client, db, model, monkeypatch):
    _open(monkeypatch)
    monkeypatch.setattr(settings, "ECHO_VOICE_TEST_GENERATION", "celery")

    def down(*a, **k):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(task_routing_service, "dispatch_for_user", down)
    _, h = _user(db)
    test = _started(unauthenticated_client, h)
    assert test["status"] == "failed" and "could not be started" in test["error"]
    assert unauthenticated_client.get(VT, headers=h).json()["offer"]["available"] is True


class _NoClose:
    """The test's session, handed to the task, which closes what it opens."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass
