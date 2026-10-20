"""What the user did with a "speak as me" draft (S-3.4.2), and the provenance guard.

What it must hold, with the LLM patched:

- Only the words the user TYPED into a draft are theirs: not the draft words
  they kept (the model wrote those), not what they cut, not the disclosure
  line, and not a stretch they repeated from the incoming message (the
  sender's words, S-3.4.1's 8-word guard). A change of case or punctuation
  is not a word they wrote.
- Feedback stores the text they used and whether the disclosure stayed;
  it may be sent again, is audited with counts only and is not a draft
  against the daily cap.
- The edit is the extraction input ``draft_edit:<id>``: a run learns a
  signal from it that cites it, and a quote of the model's words is
  dropped. An edit below the passage floor is no input at all.
- Deleting the draft withdraws what it taught at once.
- Only the tenant's own notes and own-words shares may set the voice:
  never another tenant's, never a context-only share, never a draft.
"""
from __future__ import annotations

import json

import pytest

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.echo_draft import EchoDraft
from app.models.job import Job
from app.models.voice_signal import VoiceSignal
from app.models.voice_signal_input import VoiceSignalInput
from app.services import echo_draft_edits as edits
from app.services import echo_draft_service, echo_intake_service, echo_signal_service
from app.services import echo_signal_extraction as ex
from tests.test_services.test_echo_draft import _studio
from tests.test_services.test_echo_signal_extraction import FakeLLM, _note

DRAFT = "Mostly the importer pays first. Then the buyer pays more at the till."
FINAL = "Honestly, the importer pays first, then the buyer pays more at the till. I checked the base rates on this twice."


@pytest.fixture
def asha(db):
    u = _studio(db)
    db.add(Job(id=f"job-{u.id[:8]}", tenant_id=u.id, job_type="topic", topic="t", status="completed"))
    db.commit()
    return u


MESSAGE = "My cousin says the new tariff will bring back every factory job we lost. Is he right?"
QUOTING = (DRAFT + " You say the new tariff will bring back every factory job we lost, "
           "but I checked the base rates on this twice.")


def _draft(db, user, text=DRAFT, message="Who pays?"):
    row = EchoDraft(tenant_id=user.id, user_id=user.id, input_message=message, language="en", draft=text,
                    disclosure=echo_draft_service.disclosure_for(user))
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# The diff


def test_the_users_words_are_only_what_they_typed():
    d = edits.edit_diff(DRAFT, FINAL)
    assert d.written == ["Honestly,", "I checked the base rates on this twice."]
    assert d.removed == ["Mostly"]
    assert d.written_words == 9 and d.removed_words == 1
    assert d.kept_words == 12, "first, / pays. are the same word as pays first. / first,"


def test_case_and_punctuation_are_not_a_change():
    d = edits.edit_diff("Mostly the importer pays.", "mostly, the importer pays!")
    assert d.written == [] and d.removed == [] and d.kept_words == 4


def test_a_written_run_is_sliced_as_typed():
    d = edits.edit_diff("We should wait.", "We should  wait\n\nand  see what the data says.")
    assert d.written == ["and  see what the data says."], "the user's own spacing, not re-joined words"


def test_words_repeated_from_the_incoming_message_are_not_the_users():
    d = edits.edit_diff(DRAFT, QUOTING, third_party=[MESSAGE])
    assert d.quoted == ["the new tariff will bring back every factory job we lost,"]
    assert d.written == ["You say", "but I checked the base rates on this twice."]
    assert d.written_words == 11 and d.quoted_words == 11
    assert edits.edit_diff(DRAFT, QUOTING).quoted == [], "without the message nothing is set aside"
    seven = edits.edit_diff(DRAFT, DRAFT + " The new tariff will bring back every.", third_party=[MESSAGE])
    assert seven.quoted == [] and seven.written_words == 7, "under 8 shared words is not a quote (S-3.4.1's rule)"


def test_a_quote_across_kept_draft_words_is_caught():
    draft = "Mostly the importer pays first."
    msg = "Everyone knows the importer pays first and then the buyer pays at the till."
    final = "Mostly the importer pays first and then the buyer pays at the till, I think."
    d = edits.edit_diff(draft, final, third_party=[msg])
    assert d.quoted == ["and then the buyer pays at the till,"] and d.written == ["I think."]


def test_the_disclosure_is_never_the_users_words():
    disclosure = "Drafted with Echo, reviewed by sam"
    assert edits.strip_disclosure(f"{FINAL}\n\n— {disclosure}", disclosure) == FINAL
    assert edits.strip_disclosure(FINAL, disclosure) == FINAL
    assert edits.user_written_text(DRAFT, DRAFT, min_words=1) == "", "an unedited draft teaches nothing"
    assert edits.user_written_text(DRAFT, "Mostly the importer pays first. Then the buyer pays.", min_words=4) == ""


# ---------------------------------------------------------------------------
# Feedback


def test_feedback_is_stored_audited_and_not_a_draft(db):
    user = _studio(db)
    row = _draft(db, user)
    out = echo_draft_service.feedback(db, user, row.id, f"{FINAL}\n\n{row.disclosure}", disclosure_kept=False)
    assert out.final_text == FINAL and out.disclosure_kept is False and out.feedback_at is not None
    assert out.written_words == 9
    d = echo_draft_service.to_dict(out)
    assert d["edit"] == {"written_words": 9, "removed_words": 1, "quoted_words": 0, "kept_words": 12,
                         "written": ["Honestly,", "I checked the base rates on this twice."], "removed": ["Mostly"],
                         "quoted": []}
    assert echo_draft_service.drafts_today(db, user) == 0, "feedback is not a draft against the cap"

    audit = db.query(AuditLog).filter(AuditLog.event == "echo_draft_feedback").one()
    meta = json.loads(audit.metadata_json)
    assert "importer" not in audit.metadata_json, "the audit holds counts, not words"
    assert meta["written_words"] == 9 and meta["disclosure_kept"] is False

    again = echo_draft_service.feedback(db, user, row.id, DRAFT)
    assert again.final_text == DRAFT and again.written_words == 0 and again.disclosure_kept is True


def test_feedback_counts_only_the_users_own_words(db):
    user = _studio(db)
    row = _draft(db, user, message=MESSAGE)
    out = echo_draft_service.feedback(db, user, row.id, QUOTING)
    assert out.written_words == 11, "the repeated stretch of the message is not counted"
    assert echo_draft_service.to_dict(out)["edit"]["quoted"] == ["the new tariff will bring back every factory job we lost,"]


def test_feedback_is_the_owners_only(db):
    user, other = _studio(db), _studio(db)
    row = _draft(db, user)
    try:
        echo_draft_service.feedback(db, other, row.id, FINAL)
    except echo_draft_service.DraftNotFound:
        pass
    else:
        raise AssertionError("another tenant's draft must be a 404")
    db.refresh(row)
    assert row.final_text is None


# ---------------------------------------------------------------------------
# The edit as an input


def test_an_edit_is_an_input_of_the_typed_words_only(db, asha):
    row = _draft(db, asha)
    echo_draft_service.feedback(db, asha, row.id, FINAL)
    small = _draft(db, asha)
    echo_draft_service.feedback(db, asha, small.id, DRAFT.replace("Mostly", "Mainly"))
    untouched = _draft(db, asha)

    refs = {i.ref: i for i in ex.gather_inputs(db, asha.id)}
    assert f"draft_edit:{small.id}" not in refs, "one word is below the passage floor"
    assert f"draft_edit:{untouched.id}" not in refs
    i = refs[f"draft_edit:{row.id}"]
    assert i.kind == "draft_edit" and i.text == "Honestly,\nI checked the base rates on this twice."
    assert "importer" not in i.text and "Mostly" not in i.text and "Drafted with Echo" not in i.text
    assert ex.quick_new_count(db, asha.id) == 1, "the cheap counter sees the edit, not the small one"


def test_the_senders_words_never_reach_the_model(db, asha):
    row = _draft(db, asha, message=MESSAGE)
    echo_draft_service.feedback(db, asha, row.id, QUOTING)
    i = {i.ref: i for i in ex.gather_inputs(db, asha.id)}[f"draft_edit:{row.id}"]
    assert i.text == "You say\nbut I checked the base rates on this twice."
    llm = FakeLLM([(r"every factory job we lost", "trusted_conclusion", "Thinks tariffs bring jobs back")])
    ex.run(db, asha.id, llm=llm, model="m")
    assert "every factory job" not in "\n".join(llm.prompts)
    assert not [r for r in echo_signal_service.list_signals(db, asha.id) if r.signal_type == "trusted_conclusion"]


def test_a_run_learns_from_the_edit_and_never_from_the_models_words(db, asha):
    row = _draft(db, asha)
    echo_draft_service.feedback(db, asha, row.id, FINAL)
    rules = [
        (r"I checked the base rates[^.]*\.", "methodology", "Checks the base rate before believing a claim"),
        (r"the importer pays first", "trusted_conclusion", "Thinks importers pay tariffs"),
    ]
    llm = FakeLLM(rules)
    ex.run(db, asha.id, llm=llm, model="m")
    sent = "\n".join(llm.prompts)
    assert "draft_edit" in sent and "the importer pays first" not in sent, "the model's kept words never reach the model"

    live = {r.signal_type: r for r in echo_signal_service.list_signals(db, asha.id)}
    assert "trusted_conclusion" not in live
    sig = live["methodology"]
    assert json.loads(sig.derived_from) == [f"draft_edit:{row.id}"]
    assert [e["text"] for e in json.loads(sig.examples_json)] == ["I checked the base rates on this twice."]
    assert not any(r.signal_type == "cadence" and f"draft_edit:{row.id}" in r.derived_from
                   for r in db.query(VoiceSignal).filter(VoiceSignal.tenant_id == asha.id)), "an edit is not prose for cadence"

    echo_draft_service.delete_draft(db, asha.id, row.id)
    db.expire_all()
    gone = db.get(VoiceSignal, sig.id)
    assert gone.suppressed_reason == "source_deleted" and json.loads(gone.examples_json) == []
    assert db.query(VoiceSignalInput).filter(VoiceSignalInput.source_ref == f"draft_edit:{row.id}").count() == 0


# ---------------------------------------------------------------------------
# The provenance guard


def test_only_the_tenants_own_words_may_set_the_voice(db, asha, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path))
    other = _studio(db)
    db.add(Job(id=f"job-{other.id[:8]}", tenant_id=other.id, job_type="topic", topic="t", status="completed"))
    db.commit()
    _note(db, asha, "My own note on base rates.")
    _note(db, other, "SOMEONE ELSE'S note.")
    echo_intake_service.create_text_share(db, asha.id, asha.id, text="My own essay on tariffs.", author_is_tenant=True)
    echo_intake_service.create_text_share(db, asha.id, asha.id, text="A THREAD I only saved", annotation="MY NOTE on it")
    row = _draft(db, asha, text="THE MODEL'S whole draft about tariffs.")
    echo_draft_service.feedback(db, asha, row.id, "THE MODEL'S whole draft about tariffs. And my own closing words here.")

    texts = echo_draft_service.own_texts(db, asha.id)
    assert sorted(texts) == ["My own essay on tariffs.", "My own note on base rates."]
    joined = "\n".join(texts)
    for foreign in ("SOMEONE ELSE'S", "A THREAD I only saved", "MY NOTE on it", "THE MODEL'S"):
        assert foreign not in joined, foreign
