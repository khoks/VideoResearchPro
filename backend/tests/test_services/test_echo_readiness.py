"""S-3.5.1 — five-domain readiness, measured from the stores.

Each domain against its `personal-brain.md` minimum; inferred facts and the
internal share event do not count; blocked connectors read "not connected";
the voice floor is per script, own-words shares count and context-only ones
do not; stability is measured from note vectors when the index is on; the
gate is every domain; thresholds of 0 switch a check off; nothing crosses
readers.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.connectors.base import ActivityEvent as EventIn
from app.models.echo_connector import EchoConnectorGrant
from app.models.note import Note
from app.models.share import Share
from app.models.voice_signal import VoiceSignal
from app.services import activity_event_service, auth_service, echo_readiness_service, echo_service

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def user(db):
    return auth_service.create_user(db, email="ready-a@example.com", password="pw" * 6)


@pytest.fixture
def other(db):
    return auth_service.create_user(db, email="ready-b@example.com", password="pw" * 6)


def _domains(db, uid):
    r = echo_readiness_service.evaluate(db, uid)
    return r, {d.key: d for d in r.domains}


def _facts(db, uid, n, kinds, source="manual", expired=False):
    kinds_cycle = ["interest", "hobby", "work", "skill", "place"][:kinds]
    for i in range(n):
        echo_service.record_context(
            db, user_id=uid, kind=kinds_cycle[i % len(kinds_cycle)], key=f"{source}-{i}", value="v", source=source,
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc) if expired else None,
        )


def _events(db, uid, n, days, connector="github"):
    total = days * 86400  # whole seconds, so the last event lands exactly `days` after the first
    activity_event_service.store_events(db, uid, connector, [
        EventIn(f"{connector}-{i}", "did", T0 + timedelta(seconds=total * i // max(1, n - 1))) for i in range(n)
    ])


def _signals(db, uid, n, types, suppressed=False):
    kinds = ["vocabulary", "cadence", "framing", "methodology", "interest"][:types]
    for i in range(n):
        db.add(VoiceSignal(tenant_id=uid, user_id=uid, signal_type=kinds[i % len(kinds)], value=f"v{i}",
                           value_key=f"v{i}", consent_version="1",
                           suppressed_at=datetime(2026, 1, 1) if suppressed else None))
    db.commit()


def _shares(db, uid, n, types, own_text=None):
    kinds = ["link", "text_snippet", "image", "chat", "pdf"][:types]
    for i in range(n):
        db.add(Share(tenant_id=uid, user_id=uid, surface="test", content_type=kinds[i % len(kinds)],
                     raw_payload_json="{}", processing_state="processed",
                     author_is_tenant=own_text is not None, extracted_text=own_text))
    db.commit()


def _notes(db, uid, n, text="I think the real cost of tariffs falls on the importing country's own buyers."):
    for i in range(n):
        db.add(Note(tenant_id=uid, target_type="job", target_id=f"job-{i}", body_md=f"{text} ({i})"))
    db.commit()


# ------------------------------------------------------------------ an empty account

def test_an_empty_account_says_what_is_missing_and_is_not_ready(db, user):
    r, d = _domains(db, user.id)
    assert r.ready is False and r.progress == 0
    assert [x.key for x in r.domains] == ["facts", "activity", "signals", "voice", "shares"]
    assert d["facts"].status == "not_started" and "write 30 more facts" in d["facts"].missing
    assert d["activity"].status == "not_connected", "nothing connected is not a failure"
    assert d["activity"].missing.startswith("Not connected yet")
    assert "Write 30 more notes or 2000 more words" in d["voice"].missing
    sources = {s["name"]: s for s in d["activity"].details["sources"]}
    assert sources["github"]["status"] == "not_connected" and sources["github"]["reason"]  # no OAuth app in tests
    for planned in ("youtube_likes", "google_calendar"):
        assert sources[planned]["status"] == "not_connected" and "Google sign-in setup" in sources[planned]["reason"]


# ------------------------------------------------------------------ per domain

def test_facts_count_only_what_the_user_wrote(db, user):
    _facts(db, user.id, 40, 3, source="connector:github")
    _facts(db, user.id, 10, 3, source="manual", expired=True)
    _, d = _domains(db, user.id)
    assert d["facts"].met is False and d["facts"].details == {"self_authored": 0, "inferred": 40}
    assert "40 more facts Echo inferred are kept but not counted" in d["facts"].summary
    _facts(db, user.id, 30, 2)
    _, d = _domains(db, user.id)
    assert d["facts"].criteria[0].met and not d["facts"].criteria[1].met
    assert "cover 1 more kind" in d["facts"].missing
    _facts(db, user.id, 3, 3, source="manual")
    assert _domains(db, user.id)[1]["facts"].met


def test_activity_needs_volume_and_a_span_and_ignores_the_share_event(db, user):
    _events(db, user.id, 500, 30, connector="internal")
    _, d = _domains(db, user.id)
    assert d["activity"].criteria[0].current == 0, "the internal share event mirrors Domain 5"
    _events(db, user.id, 250, 60)
    _, d = _domains(db, user.id)
    assert d["activity"].status == "in_progress" and "history spanning 30 more days" in d["activity"].missing
    _events(db, user.id, 50, 120, connector="spotify_export")
    _, d = _domains(db, user.id)
    assert d["activity"].met
    sources = {s["name"]: s for s in d["activity"].details["sources"]}
    assert sources["spotify_export"]["kind"] == "import" and sources["spotify_export"]["events"] == 50
    assert sources["github"]["events"] == 250


def test_a_connected_service_reads_connected(db, user):
    db.add(EchoConnectorGrant(tenant_id=user.id, connector="github", consent_version="1"))
    db.commit()
    _, d = _domains(db, user.id)
    sources = {s["name"]: s for s in d["activity"].details["sources"]}
    assert sources["github"]["status"] == "connected"
    assert d["activity"].status == "not_started", "connected, first sync not in yet"
    assert not d["activity"].missing.startswith("Not connected")


def test_signals_count_live_ones_by_type(db, user):
    _signals(db, user.id, 80, 4, suppressed=True)
    _signals(db, user.id, 50, 3)
    _, d = _domains(db, user.id)
    assert d["signals"].criteria[0].met and not d["signals"].met and "1 more kind" in d["signals"].missing
    _signals(db, user.id, 4, 4)  # adds the fourth kind
    assert _domains(db, user.id)[1]["signals"].met


def test_shares_need_count_and_variety(db, user):
    _shares(db, user.id, 120, 3)
    _, d = _domains(db, user.id)
    assert not d["shares"].met and "1 more kind" in d["shares"].missing
    _shares(db, user.id, 4, 4)  # adds the fourth kind
    assert _domains(db, user.id)[1]["shares"].met


def test_the_voice_floor_is_per_script(db, user, monkeypatch):
    monkeypatch.setattr(settings, "NOTES_INDEX_ENABLED", False)
    _notes(db, user.id, 20)
    _notes(db, user.id, 20, text="मुझे लगता है कि शुल्क का असली बोझ आयात करने वाले देश के खरीदारों पर पड़ता है")
    _, d = _domains(db, user.id)
    assert not d["voice"].met, "40 notes, but 20 per script"
    per = d["voice"].details["per_script"]
    assert per["Latin"]["pieces"] == 20 and per["Devanagari"]["pieces"] == 20
    _notes(db, user.id, 10)
    _, d = _domains(db, user.id)
    assert d["voice"].met and d["voice"].details["best_script"] == "Latin"
    stability = d["voice"].details["stability"]
    assert stability["measured"] is False and "notes index is off" in stability["reason"], "unmeasurable does not block"


def test_the_floor_can_be_met_by_words_and_own_words_shares_count(db, user, monkeypatch):
    monkeypatch.setattr(settings, "NOTES_INDEX_ENABLED", False)
    _shares(db, user.id, 5, 1)  # context-only: not the user's writing
    _, d = _domains(db, user.id)
    assert d["voice"].details["per_script"] == {}
    _shares(db, user.id, 4, 1, own_text=" ".join(["word"] * 500))
    _, d = _domains(db, user.id)
    assert d["voice"].met and d["voice"].details["per_script"]["Latin"] == {"pieces": 4, "words": 2000}


def test_stability_uses_the_note_vectors(db, user, monkeypatch):
    _notes(db, user.id, 30)
    rng = random.Random(1)
    tight = [[1.0 + rng.uniform(-0.01, 0.01), 0.5, 0.25] for _ in range(30)]
    scattered = [[rng.uniform(-1, 1) for _ in range(8)] for _ in range(12)]
    monkeypatch.setattr(echo_readiness_service, "_note_vectors", lambda tid: tight)
    _, d = _domains(db, user.id)
    assert d["voice"].met and d["voice"].details["stability"]["measured"] is True
    assert d["voice"].details["stability"]["spread"] < settings.ECHO_READY_VOICE_SPREAD_MAX
    monkeypatch.setattr(echo_readiness_service, "_note_vectors", lambda tid: scattered)
    _, d = _domains(db, user.id)
    assert not d["voice"].met and "still shifting" in d["voice"].missing
    monkeypatch.setattr(echo_readiness_service, "_note_vectors", lambda tid: tight[:5])
    _, d = _domains(db, user.id)
    assert not d["voice"].met and "at least 10 indexed notes" in d["voice"].details["stability"]["reason"]


def test_the_voice_test_is_reported_not_gated(db, user, monkeypatch):
    monkeypatch.setattr(settings, "NOTES_INDEX_ENABLED", False)
    _notes(db, user.id, 35)
    vt = _domains(db, user.id)[1]["voice"].details["voice_test"]
    assert vt == {"eligible": False, "notes": 35, "notes_needed": 5}
    _notes(db, user.id, 5)
    assert _domains(db, user.id)[1]["voice"].details["voice_test"]["eligible"] is True


def test_bootstrap_spread_is_deterministic_and_zero_for_one_voice():
    same = [[0.2, 0.4, 0.8]] * 12
    assert echo_readiness_service.bootstrap_spread(same) == pytest.approx(0.0, abs=1e-9)
    vs = [[random.Random(i).uniform(-1, 1) for _ in range(6)] for i in range(20)]
    assert echo_readiness_service.bootstrap_spread(vs) == echo_readiness_service.bootstrap_spread(vs)


# ------------------------------------------------------------------ the gate

def test_ready_means_every_domain_and_status_carries_it(unauthenticated_client, db, user, monkeypatch):
    monkeypatch.setattr(settings, "NOTES_INDEX_ENABLED", False)
    _facts(db, user.id, 30, 3)
    _events(db, user.id, 200, 100)
    _signals(db, user.id, 50, 4)
    _shares(db, user.id, 100, 4)
    r, _ = _domains(db, user.id)
    assert not r.ready, "four of five"
    _notes(db, user.id, 30)
    r, _ = _domains(db, user.id)
    assert r.ready and r.progress == 1.0

    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    body = unauthenticated_client.get("/api/v1/echo/status", headers={"Authorization": f"Bearer {token}"}).json()
    assert body["ready"] is True and body["progress"] == 1.0
    assert [d["key"] for d in body["domains"]] == ["facts", "activity", "signals", "voice", "shares"]
    assert all(d["status"] == "met" and d["missing"] is None for d in body["domains"])
    assert body["total_rows"] == 30, "the v1 figures are still reported"


def test_a_zero_threshold_switches_a_check_off(db, user, monkeypatch):
    for name in ("FACTS_MIN", "FACT_KINDS_MIN", "EVENTS_MIN", "EVENT_DAYS_MIN", "SIGNALS_MIN", "SIGNAL_TYPES_MIN",
                 "SHARES_MIN", "SHARE_TYPES_MIN", "VOICE_PIECES_MIN", "VOICE_WORDS_MIN", "VOICE_SPREAD_MAX"):
        monkeypatch.setattr(settings, f"ECHO_READY_{name}", 0)
    r, _ = _domains(db, user.id)
    assert r.ready is True


def test_another_readers_data_never_counts(db, user, other, monkeypatch):
    monkeypatch.setattr(settings, "NOTES_INDEX_ENABLED", False)
    _facts(db, other.id, 30, 3)
    _events(db, other.id, 200, 100)
    _signals(db, other.id, 50, 4)
    _shares(db, other.id, 100, 4)
    _notes(db, other.id, 30)
    r, d = _domains(db, user.id)
    assert r.progress == 0 and not any(x.met for x in r.domains)
    assert _domains(db, other.id)[0].ready
