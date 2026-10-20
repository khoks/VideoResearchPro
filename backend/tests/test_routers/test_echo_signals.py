"""The signals panel's API (S-3.3.1): ``/echo/signals``.

What it must hold:

- Signals are the caller's own: another tenant can neither see nor change
  them, and every route needs the Echo feature.
- "That's not me" is a tombstone. The row leaves every list and the live
  profile, and the same signal cannot be written again, by the user or (in
  S-3.3.2) by extraction, because ``is_suppressed`` says so.
- Deleting a share withdraws it as evidence: its examples leave the signals
  it fed, and a signal with nothing left is suppressed as ``source_deleted``
  (which, unlike the user's rejection, new evidence may re-derive).
"""
from __future__ import annotations

import json

import pytest

from app.models.share import Share
from app.models.voice_signal import VoiceSignal
from app.services import auth_service, echo_intake_service, echo_signal_service

SIGNALS = "/api/v1/echo/signals"


def _user(db, email: str, tier: str = "studio"):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = tier
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two(db):
    a, ha = _user(db, "signals-a@example.com")
    b, hb = _user(db, "signals-b@example.com")
    return a, ha, b, hb


@pytest.fixture
def chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    yield
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


def test_signals_need_the_echo_feature(unauthenticated_client, db):
    _, h = _user(db, "signals-free@example.com", tier="free")
    assert unauthenticated_client.get(SIGNALS, headers=h).status_code == 403
    assert unauthenticated_client.post(SIGNALS, json={"signal_type": "framing", "value": "x"}, headers=h).status_code == 403
    assert unauthenticated_client.get(SIGNALS).status_code == 401


def test_create_list_patch_and_export(unauthenticated_client, two):
    a, ha, _, _ = two
    r = unauthenticated_client.post(
        SIGNALS,
        json={"signal_type": "interest", "value": "  monetary   history ", "language": "en"},
        headers=ha,
    )
    assert r.status_code == 201, r.text
    interest = r.json()
    assert interest["value"] == "monetary history"
    assert interest["layer"] == "personality"
    assert interest["origin"] == "user" and interest["derived_from"] == ["user"]
    assert interest["consent_version"] == echo_signal_service.CONSENT_VERSION
    assert interest["register"] is None

    r = unauthenticated_client.post(
        SIGNALS, json={"signal_type": "framing", "value": "Start from the incentives", "register": "casual"}, headers=ha
    )
    framing = r.json()
    assert framing["layer"] == "style" and framing["register"] == "casual"

    # Style types list before personality types (the panel's two layers).
    listed = unauthenticated_client.get(SIGNALS, headers=ha).json()
    assert [s["id"] for s in listed["items"]] == [framing["id"], interest["id"]]
    only = unauthenticated_client.get(SIGNALS, params={"signal_type": "interest"}, headers=ha).json()
    assert [s["id"] for s in only["items"]] == [interest["id"]]

    # An absent field keeps its value; an explicit null clears it.
    r = unauthenticated_client.patch(f"{SIGNALS}/{framing['id']}", json={"weight": 3}, headers=ha)
    assert r.json()["register"] == "casual" and r.json()["weight"] == 3
    r = unauthenticated_client.patch(f"{SIGNALS}/{framing['id']}", json={"register": None}, headers=ha)
    assert r.status_code == 200 and r.json()["register"] is None

    r = unauthenticated_client.get(f"{SIGNALS}/export", headers=ha)
    assert r.status_code == 200
    assert "echo-voice-profile.json" in r.headers["content-disposition"]
    profile = r.json()
    assert profile["format"] == "pratidhvani-voice-profile"
    assert [s["value"] for s in profile["style"]] == ["Start from the incentives"]
    assert [s["value"] for s in profile["personality"]] == ["monetary history"]


def test_closed_vocabularies_are_enforced(unauthenticated_client, two):
    _, ha, _, _ = two
    for body in (
        {"signal_type": "mood", "value": "x"},
        {"signal_type": "framing", "value": "x", "language": "fr"},
        {"signal_type": "framing", "value": "x", "register": "shouty"},
        {"signal_type": "framing", "value": ""},
        {"signal_type": "framing", "value": "x", "origin": "llm"},
    ):
        assert unauthenticated_client.post(SIGNALS, json=body, headers=ha).status_code == 422, body


def test_another_tenant_cannot_see_or_touch_a_signal(unauthenticated_client, two):
    a, ha, b, hb = two
    sid = unauthenticated_client.post(SIGNALS, json={"signal_type": "apprehension", "value": "lock-in"}, headers=ha).json()["id"]
    assert unauthenticated_client.get(SIGNALS, headers=hb).json()["items"] == []
    assert unauthenticated_client.patch(f"{SIGNALS}/{sid}", json={"value": "mine now"}, headers=hb).status_code == 404
    assert unauthenticated_client.delete(f"{SIGNALS}/{sid}", headers=hb).status_code == 404
    assert unauthenticated_client.get(f"{SIGNALS}/export", headers=hb).json()["personality"] == []
    assert [s["value"] for s in unauthenticated_client.get(SIGNALS, headers=ha).json()["items"]] == ["lock-in"]


def test_a_rejected_signal_never_comes_back(unauthenticated_client, db, two):
    a, ha, _, _ = two
    sid = unauthenticated_client.post(SIGNALS, json={"signal_type": "interest", "value": "Cricket"}, headers=ha).json()["id"]
    r = unauthenticated_client.delete(f"{SIGNALS}/{sid}", headers=ha)
    assert r.status_code == 200

    assert unauthenticated_client.get(SIGNALS, headers=ha).json()["items"] == []
    row = db.get(VoiceSignal, sid)
    assert row is not None and row.suppressed_reason == "user", "a tombstone, not a delete"

    # The same signal, however it is cased or spaced, is refused...
    r = unauthenticated_client.post(SIGNALS, json={"signal_type": "interest", "value": "  cricket. "}, headers=ha)
    assert r.status_code == 422
    # ...and extraction's check says so too.
    assert echo_signal_service.is_suppressed(db, a.id, "interest", "CRICKET", None)
    assert not echo_signal_service.is_suppressed(db, a.id, "topic_emphasis", "cricket", None)
    # A tombstone cannot be edited or rejected twice.
    assert unauthenticated_client.patch(f"{SIGNALS}/{sid}", json={"value": "x"}, headers=ha).status_code == 404
    assert unauthenticated_client.delete(f"{SIGNALS}/{sid}", headers=ha).status_code == 404

    profile = unauthenticated_client.get(f"{SIGNALS}/export", headers=ha).json()
    assert profile["personality"] == []
    assert profile["rejected"] == [{"signal_type": "interest", "value": "Cricket", "language": None}]


def _derived(db, a, share_ids, value, signal_type="framing"):
    """A signal as extraction will write it: provenance and examples from
    the given sources, its id recorded on each share."""
    row = echo_signal_service.create(
        db,
        tenant_id=a.id,
        user_id=a.id,
        signal_type=signal_type,
        value=value,
        origin="llm",
        weight=2.0,
        examples=[{"text": f"example from {ref}", "source": ref} for ref in share_ids],
    )
    for ref in share_ids:
        if ref.startswith("share:"):
            share = db.get(Share, ref.split(":", 1)[1])
            share.derived_signal_ids_json = json.dumps(json.loads(share.derived_signal_ids_json or "[]") + [row.id])
    db.commit()
    return row


def test_deleting_a_share_withdraws_it_as_evidence(unauthenticated_client, db, two, chroma, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    a, ha, _, _ = two
    share = echo_intake_service.create_text_share(db, a.id, a.id, text="my own essay", author_is_tenant=True)
    note_ref = "note:n-1"
    only = _derived(db, a, [f"share:{share.id}"], "Opens with a story")
    both = _derived(db, a, [f"share:{share.id}", note_ref], "Closes with a question")

    r = unauthenticated_client.delete(f"/api/v1/echo/shares/{share.id}", headers=ha)
    assert r.status_code in (200, 204), r.text
    db.expire_all()

    gone = db.get(VoiceSignal, only.id)
    assert gone.suppressed_reason == "source_deleted"
    assert json.loads(gone.derived_from) == [] and json.loads(gone.examples_json) == []

    kept = db.get(VoiceSignal, both.id)
    assert kept.suppressed_at is None
    assert json.loads(kept.derived_from) == [note_ref]
    assert [e["source"] for e in json.loads(kept.examples_json)] == [note_ref]

    listed = [s["value"] for s in unauthenticated_client.get(SIGNALS, headers=ha).json()["items"]]
    assert listed == ["Closes with a question"]
    # Not the user's rejection: new evidence may derive it again.
    assert not echo_signal_service.is_suppressed(db, a.id, "framing", "Opens with a story", None)


def test_withdraw_source_without_ids_scans_every_live_signal(db, two):
    a, _, b, _ = two
    mine = _derived(db, a, ["note:n-9", "qa:q-1"], "Uses cricket metaphors", signal_type="recurring_reference")
    theirs = _derived(db, b, ["note:n-9"], "Uses cricket metaphors", signal_type="recurring_reference")

    result = echo_signal_service.withdraw_source(db, a.id, "note:n-9")
    db.commit()
    assert result == echo_signal_service.SourceWithdrawal(updated=1, suppressed=0)
    assert json.loads(db.get(VoiceSignal, mine.id).derived_from) == ["qa:q-1"]
    assert json.loads(db.get(VoiceSignal, theirs.id).derived_from) == ["note:n-9"], "only the caller's tenant"

    assert echo_signal_service.withdraw_source(db, a.id, "note:n-9", signal_ids=[]) == echo_signal_service.SourceWithdrawal(0, 0)


def test_the_api_vocabularies_are_the_service_vocabularies():
    from typing import get_args

    from app.schemas import voice_signal as schema

    assert get_args(schema.SignalType) == echo_signal_service.SIGNAL_TYPES
    assert get_args(schema.Language) == echo_signal_service.LANGUAGES
    assert get_args(schema.Register) == echo_signal_service.REGISTERS
