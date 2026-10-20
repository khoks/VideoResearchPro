"""Activity events as signal input (T-3.3.2.8).

``activity_events.text_content`` holds only the user's own words (commit
messages, reviews, workout notes, search queries) by its contract. Each
connector's events are ONE input, sampled like an import; examples cite the
event (``event:<id>``). Events are deleted in bulk by paths outside
extraction (a connector revoke, an import undo), so their words must leave
every signal at once, in one pass, and the retrieval vectors must follow.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta

import pytest

from app.models.activity_event import ActivityEvent
from app.models.voice_signal import VoiceSignal
from app.models.voice_signal_input import VoiceSignalInput
from app.services import auth_service, echo_connector_service, echo_signal_service
from app.services import echo_signal_extraction as ex

T0 = datetime(2024, 1, 1)


def _user(db):
    u = auth_service.create_user(db, email=f"ev-{uuid.uuid4().hex[:8]}@example.com", password="pw" * 6)
    u.tier = "studio"
    db.commit()
    return u


def _event(db, user, connector, event_type, text, k=0):
    e = ActivityEvent(
        id=str(uuid.uuid4()), tenant_id=user.id, user_id=user.id, connector=connector,
        external_id=f"{connector}-{uuid.uuid4().hex}", event_type=event_type,
        occurred_at=T0 + timedelta(days=k), payload_json="{}", text_content=text,
    )
    db.add(e)
    db.commit()
    return e


def _llm(quote):
    def call(prompt):
        pids = [pid for pid, body in re.findall(r"\[(P\d+)\] \([^)]*\)\n([^\n]*)", prompt) if quote in body]
        out = [{"signal_type": "methodology", "value": "Checks base rates first",
                "examples": [{"id": pid, "quote": quote} for pid in pids]}] if pids else []
        return json.dumps({"signals": out}), 10, 10
    return call


def test_each_connector_is_one_input_and_queries_are_not_prose(db):
    user = _user(db)
    commits = [_event(db, user, "github", "committed", f"Check the base rate before trusting the benchmark {k}", k) for k in range(5)]
    _event(db, user, "google_takeout", "searched_youtube", "monetary policy india", 1)
    _event(db, user, "google_takeout", "searched_youtube", "ok", 2)
    _event(db, user, "internal", "shared_to_pratidhvani", None)
    _event(db, user, "spotify_export", "played", None)

    inputs = {i.ref: i for i in ex.gather_inputs(db, user.id)}
    assert set(inputs) == {"events:github", "events:google_takeout"}
    gh = inputs["events:github"]
    assert gh.kind == "events" and all(c.text_content in gh.text for c in commits)
    assert {p.ref for p in gh.passages} == {f"event:{c.id}" for c in commits}
    takeout = inputs["events:google_takeout"]
    assert takeout.text == "", "a search query is not prose for stylometry"
    assert [(p.kind, p.text) for p in takeout.passages] == [("query", "monetary policy india")], "one-word queries are noise"
    assert ex.quick_new_count(db, user.id) == 2, "a connector counts once"

    # A new search changes the input although its prose did not change.
    ex.run(db, user.id, use_llm=False)
    _event(db, user, "google_takeout", "searched_youtube", "tariffs and jobs data", 3)
    assert [i.ref for i in ex.pending(db, user.id).changed] == ["events:google_takeout"]


def test_a_signal_cites_the_event_and_the_ledger_holds_the_connector(db):
    user = _user(db)
    e = _event(db, user, "github", "committed", "Check the base rate before trusting the benchmark")
    ex.run(db, user.id, llm=_llm("Check the base rate"), model="m")
    sig = next(r for r in echo_signal_service.list_signals(db, user.id) if r.signal_type == "methodology")
    assert json.loads(sig.derived_from) == [f"event:{e.id}"]
    ledger = db.query(VoiceSignalInput).filter(VoiceSignalInput.tenant_id == user.id).all()
    assert [(r.source_ref, r.llm_done) for r in ledger] == [("events:github", True)]
    assert ex.quick_new_count(db, user.id) == 0


def test_revoking_a_connector_withdraws_its_words_at_once_and_syncs(db, monkeypatch):
    user = _user(db)
    event_id = _event(db, user, "github", "committed", "Check the base rate before trusting the benchmark").id
    ex.run(db, user.id, llm=_llm("Check the base rate"), model="m")
    sig = next(r for r in echo_signal_service.list_signals(db, user.id) if r.signal_type == "methodology")

    from app.services import echo_personal_vectors

    from app.models.echo_connector import EchoConnectorGrant

    db.add(EchoConnectorGrant(tenant_id=user.id, connector="github", consent_version="2026-10-19"))
    db.commit()
    synced = []
    monkeypatch.setattr(echo_personal_vectors, "sync_soft", lambda db_, tenant: synced.append(tenant))
    echo_connector_service.revoke(db, user.id, "github")
    db.expire_all()
    row = db.get(VoiceSignal, sig.id)
    assert row.suppressed_reason == "source_deleted", "no run needed: the revoke itself withdrew it"
    assert json.loads(row.examples_json) == []
    assert db.get(ActivityEvent, event_id) is None
    assert synced == [user.id], "the revoked facts and signals leave retrieval after the commit"


def test_a_bulk_event_delete_elsewhere_is_reconciled_by_the_next_run(db):
    """An import undo deletes its events with a bulk query; the next run (or
    the undo's own call to withdraw_missing_events) takes them out."""
    user = _user(db)
    a = _event(db, user, "letterboxd_export", "reviewed_film", "A slow film that rewards patience with every frame", 1)
    b = _event(db, user, "letterboxd_export", "reviewed_film", "Too long, and a slow film that rewards nobody", 2)
    ex.run(db, user.id, llm=_llm("a slow film that rewards"), model="m")
    sig = next(r for r in echo_signal_service.list_signals(db, user.id) if r.signal_type == "methodology")
    assert set(json.loads(sig.derived_from)) == {f"event:{b.id}"}

    db.query(ActivityEvent).filter(ActivityEvent.id.in_([a.id, b.id])).delete(synchronize_session=False)
    db.commit()
    ex.run(db, user.id, use_llm=False)
    db.expire_all()
    assert db.get(VoiceSignal, sig.id).suppressed_reason == "source_deleted"
    assert db.query(VoiceSignalInput).filter(VoiceSignalInput.tenant_id == user.id).count() == 0


def test_undoing_an_event_import_withdraws_its_words_at_once_and_syncs(db, monkeypatch):
    from app.models.echo_import import EchoImport
    from app.services import echo_import_service, echo_personal_vectors

    user = _user(db)
    record = EchoImport(tenant_id=user.id, user_id=user.id, importer="letterboxd_export", filename="x.zip", status="done")
    db.add(record)
    db.commit()
    e = ActivityEvent(
        id=str(uuid.uuid4()), tenant_id=user.id, user_id=user.id, connector="letterboxd_export",
        external_id="film-1", event_type="reviewed_film", occurred_at=T0,
        payload_json=json.dumps({"import_id": record.id}), text_content="A slow film that rewards patience with every frame",
    )
    db.add(e)
    db.commit()
    ex.run(db, user.id, llm=_llm("A slow film that rewards"), model="m")
    sig = next(r for r in echo_signal_service.list_signals(db, user.id) if r.signal_type == "methodology")

    synced = []
    monkeypatch.setattr(echo_personal_vectors, "sync_soft", lambda db_, tenant: synced.append(tenant))
    echo_import_service.delete_import(db, user.id, record.id)
    db.expire_all()
    assert db.get(VoiceSignal, sig.id).suppressed_reason == "source_deleted", "no run needed"
    assert user.id in synced


def test_withdraw_sources_is_one_pass_over_many_refs(db):
    user = _user(db)
    row = echo_signal_service.create(
        db, tenant_id=user.id, user_id=user.id, signal_type="interest", value="Chess", origin="llm", weight=3.0,
        examples=[{"text": f"chess {k}", "source": f"event:e{k}"} for k in range(3)],
    )
    res = echo_signal_service.withdraw_sources(db, user.id, {"event:e0", "event:e1", "event:unrelated"})
    db.commit()
    assert res == echo_signal_service.SourceWithdrawal(updated=1, suppressed=0)
    db.refresh(row)
    assert json.loads(row.derived_from) == ["event:e2"] and row.weight == 1.0
    assert [e["source"] for e in json.loads(row.examples_json)] == ["event:e2"]
    assert echo_signal_service.withdraw_sources(db, user.id, set()) == echo_signal_service.SourceWithdrawal(0, 0)
