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


def test_a_signal_in_a_language_echo_cannot_name_can_be_edited(unauthenticated_client, db, two):
    """`update` re-checks the row's language, so a learned `other` signal would
    refuse every edit if the vocabulary did not hold it."""
    a, ha, _, _ = two
    row = echo_signal_service.create(
        db, tenant_id=a.id, user_id=a.id, signal_type="framing", value="Empieza por los incentivos",
        language="other",
    )
    db.commit()

    got = unauthenticated_client.get(f"{SIGNALS}?language=other", headers=ha).json()
    assert [s["language"] for s in got["items"]] == ["other"]

    r = unauthenticated_client.patch(f"{SIGNALS}/{row.id}", json={"value": "Primero los incentivos"}, headers=ha)
    assert r.status_code == 200, r.text
    assert r.json()["language"] == "other"


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


def _note(db, a, nid, body=None):
    """A live note whose text holds the example ``_derived`` writes for it."""
    from app.models.note import Note

    note = Note(id=nid, tenant_id=a.id, target_type="job", target_id="job-1",
                body_md=body if body is not None else f"Some context, then example from note:{nid} and more.")
    db.add(note)
    db.commit()
    return note


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


def test_rewording_a_learned_signal_makes_it_the_users(unauthenticated_client, db, two):
    a, ha, _, _ = two
    learned = _derived(db, a, ["note:n-3"], "Leans on base rates", signal_type="methodology")

    r = unauthenticated_client.patch(f"{SIGNALS}/{learned.id}", json={"register": "professional"}, headers=ha)
    assert r.json()["origin"] == "llm", "a language or audience fix leaves the provenance alone"
    r = unauthenticated_client.patch(f"{SIGNALS}/{learned.id}", json={"value": "Starts from base rates"}, headers=ha)
    assert r.json()["origin"] == "user"
    assert r.json()["derived_from"] == ["note:n-3"], "the evidence is kept"


# ------------------------------------------------------------------ T-3.3.1.6: list and restore rejections


def test_rejections_are_listed_and_restore_lifts_the_refusal(unauthenticated_client, db, two):
    """The panel's "Rejected (N)" and its Restore, at the router. Before the
    restore, re-adding and re-learning are refused; after it, neither is."""
    from app.services import echo_signal_extraction as extraction

    a, ha, _, _ = two
    keep = unauthenticated_client.post(SIGNALS, json={"signal_type": "framing", "value": "Starts from incentives"}, headers=ha).json()
    sid = unauthenticated_client.post(SIGNALS, json={"signal_type": "interest", "value": "Cricket"}, headers=ha).json()["id"]
    assert unauthenticated_client.get(f"{SIGNALS}/rejected", headers=ha).json() == {"items": []}
    unauthenticated_client.delete(f"{SIGNALS}/{sid}", headers=ha)

    r = unauthenticated_client.get(f"{SIGNALS}/rejected", headers=ha)
    assert r.status_code == 200, r.text
    [item] = r.json()["items"]
    assert item["id"] == sid and item["value"] == "Cricket" and item["signal_type"] == "interest"
    assert item["rejected_at"].endswith(("Z", "+00:00")), "sent with its offset"
    assert keep["id"] not in [i["id"] for i in r.json()["items"]], "a live signal is not a rejection"

    def learn_cricket():
        counts = extraction.MergeCounts()
        cand = {"signal_type": "interest", "value": "cricket", "language": None, "register": None,
                "examples": [{"text": "I watched the test match", "source": "note:n-1"}]}
        extraction.merge_candidate(db, a.id, cand, "llm", counts)
        db.commit()
        return counts

    # Mutation-style: the refusal is real before the restore...
    assert unauthenticated_client.post(SIGNALS, json={"signal_type": "interest", "value": "cricket"}, headers=ha).status_code == 422
    assert learn_cricket().rejected_by_user == 1

    r = unauthenticated_client.post(f"{SIGNALS}/{sid}/restore", headers=ha)
    assert r.status_code == 200, r.text
    assert r.json()["live"] is True and r.json()["signal"]["id"] == sid
    # ...and gone after it: the signal is back, and learning merges into it.
    assert unauthenticated_client.get(f"{SIGNALS}/rejected", headers=ha).json()["items"] == []
    assert sid in [s["id"] for s in unauthenticated_client.get(SIGNALS, headers=ha).json()["items"]]
    assert not echo_signal_service.is_suppressed(db, a.id, "interest", "cricket", None)
    counts = learn_cricket()
    assert counts.rejected_by_user == 0 and counts.merged == 1
    assert unauthenticated_client.get(f"{SIGNALS}/export", headers=ha).json()["rejected"] == []
    # Restoring twice is a 404: it is no longer a rejection.
    assert unauthenticated_client.post(f"{SIGNALS}/{sid}/restore", headers=ha).status_code == 404


def test_rejections_are_the_callers_own(unauthenticated_client, db, two):
    a, ha, b, hb = two
    sid = unauthenticated_client.post(SIGNALS, json={"signal_type": "apprehension", "value": "lock-in"}, headers=ha).json()["id"]
    unauthenticated_client.delete(f"{SIGNALS}/{sid}", headers=ha)
    assert unauthenticated_client.get(f"{SIGNALS}/rejected", headers=hb).json()["items"] == []
    assert unauthenticated_client.post(f"{SIGNALS}/{sid}/restore", headers=hb).status_code == 404
    db.expire_all()
    assert db.get(VoiceSignal, sid).suppressed_reason == "user", "B's attempt changed nothing"


def test_listing_and_restoring_rejections_need_the_echo_feature(unauthenticated_client, db):
    _, h = _user(db, "signals-free-2@example.com", tier="free")
    assert unauthenticated_client.get(f"{SIGNALS}/rejected", headers=h).status_code == 403
    assert unauthenticated_client.post(f"{SIGNALS}/anything/restore", headers=h).status_code == 403
    assert unauthenticated_client.get(f"{SIGNALS}/rejected").status_code == 401


def test_a_signal_hidden_because_its_sources_went_is_not_a_rejection(unauthenticated_client, db, two):
    a, ha, _, _ = two
    row = _derived(db, a, ["note:n-7"], "Quotes old proverbs", signal_type="recurring_reference")
    echo_signal_service.withdraw_source(db, a.id, "note:n-7")
    db.commit()
    assert db.get(VoiceSignal, row.id).suppressed_reason == "source_deleted"
    assert unauthenticated_client.get(f"{SIGNALS}/rejected", headers=ha).json()["items"] == []
    assert unauthenticated_client.post(f"{SIGNALS}/{row.id}/restore", headers=ha).status_code == 404


def test_a_deleted_share_leaves_a_rejection_too_so_restore_cannot_bring_it_back(
    unauthenticated_client, db, two, chroma, tmp_path, monkeypatch
):
    """Before T-3.3.1.6 a withdrawal skipped rejected rows, so a rejection kept
    a deleted share's verbatim words; a restore would have put them back."""
    from app.config import settings

    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    a, ha, _, _ = two
    share = echo_intake_service.create_text_share(db, a.id, a.id, text="my own essay", author_is_tenant=True)
    _note(db, a, "n-2")
    only = _derived(db, a, [f"share:{share.id}"], "Opens with a story")
    both = _derived(db, a, [f"share:{share.id}", "note:n-2"], "Closes with a question")
    for row in (only, both):
        unauthenticated_client.delete(f"{SIGNALS}/{row.id}", headers=ha)

    assert unauthenticated_client.delete(f"/api/v1/echo/shares/{share.id}", headers=ha).status_code in (200, 204)
    db.expire_all()
    for row_id in (only.id, both.id):
        row = db.get(VoiceSignal, row_id)
        assert row.suppressed_reason == "user", "still a rejection"
        assert f"share:{share.id}" not in row.derived_from + row.examples_json, "the share's words left it"

    # The one with evidence left comes back live, citing only that evidence.
    r = unauthenticated_client.post(f"{SIGNALS}/{both.id}/restore", headers=ha)
    assert r.json()["live"] is True
    assert r.json()["signal"]["derived_from"] == ["note:n-2"]
    assert [e["source"] for e in r.json()["signal"]["examples"]] == ["note:n-2"]
    # The one with nothing left is no longer refused, but has no evidence to show.
    r = unauthenticated_client.post(f"{SIGNALS}/{only.id}/restore", headers=ha)
    assert r.status_code == 200 and r.json()["live"] is False
    db.expire_all()
    assert db.get(VoiceSignal, only.id).suppressed_reason == "source_deleted"
    assert not echo_signal_service.is_suppressed(db, a.id, "framing", "Opens with a story", None)
    assert [s["value"] for s in unauthenticated_client.get(SIGNALS, headers=ha).json()["items"]] == ["Closes with a question"]


def test_missing_events_leave_rejections_too(db, two):
    """The bulk path (a connector revoke, an import undo) cleans rejections."""
    from app.services import echo_signal_extraction as extraction

    a, _, _, _ = two
    row = _derived(db, a, ["event:gone-1", "note:n-4"], "Writes terse commit messages", signal_type="cadence")
    echo_signal_service.suppress(db, a.id, row.id)
    extraction.withdraw_missing_events(db, a.id)
    db.commit()
    row = db.get(VoiceSignal, row.id)
    assert json.loads(row.derived_from) == ["note:n-4"] and row.suppressed_reason == "user"


def test_restore_keeps_an_equal_live_signal_and_drops_the_tombstone(unauthenticated_client, db, two):
    a, ha, _, _ = two
    sid = unauthenticated_client.post(SIGNALS, json={"signal_type": "interest", "value": "Chess"}, headers=ha).json()["id"]
    unauthenticated_client.delete(f"{SIGNALS}/{sid}", headers=ha)
    other = unauthenticated_client.post(SIGNALS, json={"signal_type": "interest", "value": "Go"}, headers=ha).json()["id"]
    # Rewording another signal into the rejected one's words is not refused.
    unauthenticated_client.patch(f"{SIGNALS}/{other}", json={"value": "chess"}, headers=ha)

    r = unauthenticated_client.post(f"{SIGNALS}/{sid}/restore", headers=ha)
    assert r.status_code == 200 and r.json()["signal"]["id"] == other and r.json()["live"] is True
    db.expire_all()
    assert db.get(VoiceSignal, sid) is None
    assert [s["id"] for s in unauthenticated_client.get(SIGNALS, headers=ha).json()["items"]] == [other]


def test_restore_drops_evidence_a_rejection_kept_from_before_the_fix(
    unauthenticated_client, db, two, chroma, tmp_path, monkeypatch
):
    """Before T-3.3.1.6 a delete left rejected signals alone and dropped the
    ledger row at once, so no later run cleans them: a rejection made before
    the deploy can still cite a deleted share (or note, event, question,
    draft edit) and hold its words. Restoring it must not bring them back,
    nor words the user has since edited out of a note."""
    from datetime import datetime

    from app.config import settings
    from app.models.activity_event import ActivityEvent
    from app.models.note import Note

    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    a, ha, _, _ = two
    _note(db, a, "n-live", "I always start from the base rates, then argue.")
    _note(db, a, "n-edited", "These days I mostly play go.")
    _note(db, a, "n-deleted", "words from a note I deleted")
    db.get(Note, "n-deleted").deleted_at = datetime(2026, 10, 1)
    kept_share = echo_intake_service.create_text_share(
        db, a.id, a.id, text="My essay opens with a story about my grandfather.", author_is_tenant=True
    )
    deleted_share = echo_intake_service.create_text_share(
        db, a.id, a.id, text="the essay I deleted, every word of it", author_is_tenant=True
    )
    unmarked = echo_intake_service.create_text_share(
        db, a.id, a.id, text="words I no longer mark as mine", author_is_tenant=True
    )
    event = ActivityEvent(
        tenant_id=a.id, user_id=a.id, connector="github", external_id="c-1", event_type="committed",
        occurred_at=datetime(2026, 10, 2), payload_json="{}", text_content="Refactor the parser so it reads one pass",
    )
    db.add(event)
    db.commit()
    live = {
        "note:n-live": "start from the base rates",
        f"share:{kept_share.id}": "opens with a story about my grandfather",
        f"event:{event.id}": "reads one pass",
    }
    gone = {
        "note:n-edited": "chess is my whole life",
        "note:n-deleted": "words from a note I deleted",
        f"share:{deleted_share.id}": "the essay I deleted",
        f"share:{unmarked.id}": "no longer mark as mine",
        "event:gone-1": "fixed the flaky test again",
        "qa:gone-q": "why do tariffs always rise",
        "draft_edit:gone-d": "thanks, I will look tonight",
    }
    examples = [{"text": t, "source": ref} for ref, t in {**live, **gone}.items()]
    row = echo_signal_service.create(
        db, tenant_id=a.id, user_id=a.id, signal_type="methodology", value="Argues from first principles",
        origin="llm", weight=10.0, examples=examples,
    )
    orphan = echo_signal_service.create(
        db, tenant_id=a.id, user_id=a.id, signal_type="framing", value="Ends on a confession",
        origin="llm", weight=1.0, examples=[{"text": "the essay I deleted", "source": f"share:{deleted_share.id}"}],
    )
    for sid in (row.id, orphan.id):
        assert unauthenticated_client.delete(f"{SIGNALS}/{sid}", headers=ha).status_code == 200
    # The deletes as they ran before the fix: the rows go, the rejections keep
    # citing them and holding their words.
    unmarked.author_is_tenant = False
    deleted_ref = f"share:{deleted_share.id}"
    db.expunge(deleted_share)
    db.query(Share).filter(Share.id == deleted_ref.split(":", 1)[1]).delete(synchronize_session=False)
    db.commit()
    db.expire_all()
    assert deleted_ref in db.get(VoiceSignal, row.id).derived_from
    # The Rejected list names a rejection; it does not quote its stale evidence.
    r = unauthenticated_client.get(f"{SIGNALS}/rejected", headers=ha)
    assert {i["id"] for i in r.json()["items"]} == {row.id, orphan.id}
    assert all(i["examples"] == [] for i in r.json()["items"])
    assert all(words not in r.text for words in gone.values())

    r = unauthenticated_client.post(f"{SIGNALS}/{row.id}/restore", headers=ha)
    assert r.status_code == 200, r.text
    signal = r.json()["signal"]
    assert r.json()["live"] is True
    assert sorted(signal["derived_from"]) == sorted(live)
    assert sorted((e["source"], e["text"]) for e in signal["examples"]) == sorted(live.items())
    assert signal["weight"] == 3.0, "one less per source that left, as a withdrawal counts it"
    db.expire_all()
    stored = db.get(VoiceSignal, row.id)
    for ref, words in gone.items():
        assert ref not in stored.derived_from and words not in stored.examples_json, ref
        assert words not in r.text, ref
    [listed] = unauthenticated_client.get(SIGNALS, headers=ha).json()["items"]
    assert listed["id"] == row.id and len(listed["examples"]) == len(live)

    # Nothing left: no longer refused, out of the profile, and none of the
    # deleted share's words kept on the row.
    r = unauthenticated_client.post(f"{SIGNALS}/{orphan.id}/restore", headers=ha)
    assert r.status_code == 200 and r.json()["live"] is False
    assert r.json()["signal"]["examples"] == [] and r.json()["signal"]["derived_from"] == []
    db.expire_all()
    assert db.get(VoiceSignal, orphan.id).suppressed_reason == "source_deleted"
    assert "the essay I deleted" not in db.get(VoiceSignal, orphan.id).examples_json


def test_restore_lifts_every_rejection_of_the_same_signal(
    unauthenticated_client, db, two, chroma, tmp_path, monkeypatch
):
    """Rewording one signal into a rejected one's words, then rejecting it
    too, makes two rejections of one key. Restoring either must lift both,
    or the twin goes on refusing the restored signal; its evidence is merged
    in, and a share it cited now withdraws from the restored row."""
    from app.config import settings
    from app.services import echo_signal_extraction as extraction

    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    a, ha, _, _ = two
    _note(db, a, "n-c")
    share = echo_intake_service.create_text_share(
        db, a.id, a.id, text="I keep coming back to the Najdorf.", author_is_tenant=True
    )
    first = _derived(db, a, ["note:n-c"], "Chess", signal_type="interest")
    unauthenticated_client.delete(f"{SIGNALS}/{first.id}", headers=ha)
    twin = echo_signal_service.create(
        db, tenant_id=a.id, user_id=a.id, signal_type="interest", value="Go", origin="llm", weight=1.0,
        examples=[{"text": "coming back to the Najdorf", "source": f"share:{share.id}"}],
    )
    extraction.record_on_shares(db, a.id, twin)
    db.commit()
    assert unauthenticated_client.patch(f"{SIGNALS}/{twin.id}", json={"value": "chess"}, headers=ha).status_code == 200
    unauthenticated_client.delete(f"{SIGNALS}/{twin.id}", headers=ha)
    assert len(unauthenticated_client.get(f"{SIGNALS}/rejected", headers=ha).json()["items"]) == 2

    r = unauthenticated_client.post(f"{SIGNALS}/{first.id}/restore", headers=ha)
    assert r.status_code == 200 and r.json()["live"] is True and r.json()["signal"]["id"] == first.id
    assert r.json()["signal"]["derived_from"] == ["note:n-c", f"share:{share.id}"], "the twin's evidence is merged"
    assert unauthenticated_client.get(f"{SIGNALS}/rejected", headers=ha).json()["items"] == []
    db.expire_all()
    assert db.get(VoiceSignal, twin.id) is None
    assert not echo_signal_service.is_suppressed(db, a.id, "interest", "chess", None)
    counts = extraction.MergeCounts()
    cand = {"signal_type": "interest", "value": "chess", "language": None, "register": None,
            "examples": [{"text": "example from note:n-c", "source": "note:n-c"}]}
    assert extraction.merge_candidate(db, a.id, cand, "llm", counts).id == first.id
    assert counts.rejected_by_user == 0 and counts.merged == 1
    db.commit()

    # The merged share evidence is withdrawn when the share is deleted.
    assert unauthenticated_client.delete(f"/api/v1/echo/shares/{share.id}", headers=ha).status_code in (200, 204)
    db.expire_all()
    assert json.loads(db.get(VoiceSignal, first.id).derived_from) == ["note:n-c"]
    # And re-adding it is no longer refused.
    assert unauthenticated_client.post(SIGNALS, json={"signal_type": "interest", "value": "chess"}, headers=ha).status_code == 201


def test_restore_onto_an_equal_live_signal_drops_every_tombstone(unauthenticated_client, db, two):
    a, ha, _, _ = two
    ids = [unauthenticated_client.post(SIGNALS, json={"signal_type": "interest", "value": v}, headers=ha).json()["id"]
           for v in ("Chess", "Go", "Draughts")]
    first, twin, other = ids
    unauthenticated_client.delete(f"{SIGNALS}/{first}", headers=ha)
    unauthenticated_client.patch(f"{SIGNALS}/{twin}", json={"value": "chess"}, headers=ha)
    unauthenticated_client.delete(f"{SIGNALS}/{twin}", headers=ha)
    unauthenticated_client.patch(f"{SIGNALS}/{other}", json={"value": "CHESS"}, headers=ha)

    r = unauthenticated_client.post(f"{SIGNALS}/{first}/restore", headers=ha)
    assert r.status_code == 200 and r.json()["signal"]["id"] == other
    assert unauthenticated_client.get(f"{SIGNALS}/rejected", headers=ha).json()["items"] == []
    db.expire_all()
    assert db.get(VoiceSignal, first) is None and db.get(VoiceSignal, twin) is None
    assert not echo_signal_service.is_suppressed(db, a.id, "interest", "chess", None)
