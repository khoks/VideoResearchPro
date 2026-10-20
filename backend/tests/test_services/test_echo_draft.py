""""Speak as me" (S-3.4.1): the agent and the service, every model patched.

What must hold:

- Citations are what the draft cited, mapped to the items it was given;
  unknown markers are dropped and the delivered text has none.
- A private person named in the message stops the draft until acknowledged.
- The critic loop revises below its target, stops at its round limit and
  keeps the best candidate; a failed critic is said, not hidden.
- Third-party words are never delivered verbatim: paraphrased once, then
  the sentence goes. The user's own words may be reused.
- Only the user's own texts set the voice (the provenance guard): a
  context-only share never becomes an exemplar.
- The gates: install switch, readiness, the per-user voice test (D-100,
  pre-registered rule), the daily cap; nothing is spent when one blocks.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.agents import echo_agent as agent
from app.agents.echo_agent import ContextItem, DraftDeps
from app.config import settings
from app.models.echo_draft import EchoDraft
from app.services import auth_service, echo_draft_service, echo_intake_service, echo_service
from app.services import quota_metering_service as quota

SOURCE = "Tariffs raise prices for the importer first and then for the buyer, the study found across forty markets."


class Calls:
    def __init__(self):
        self.prompts: dict[str, list[str]] = {"classify": [], "draft": [], "critique": []}


def deps(*, classify=None, drafts=None, critiques=None, knowledge=None, facts=None, exemplars=None, signals=None):
    calls = Calls()
    drafts = list(drafts or ["Mostly the importer pays first [S1]. Then the buyer [S1]."])
    critiques = list(critiques or [{"tone": 5, "vocabulary": 5, "structure": 5, "topicality": 5, "grounded": 5, "notes": []}])

    def classify_fn(prompt):
        calls.prompts["classify"].append(prompt)
        return json.dumps(classify or {"intent": "opinion", "topic": "who pays tariffs", "language": "en", "people": []}), 50, 20

    def draft_fn(prompt):
        calls.prompts["draft"].append(prompt)
        return (drafts.pop(0) if len(drafts) > 1 else drafts[0]), 300, 80

    def critique_fn(prompt):
        calls.prompts["critique"].append(prompt)
        c = critiques.pop(0) if len(critiques) > 1 else critiques[0]
        if isinstance(c, Exception):
            raise c
        return json.dumps(c), 200, 40

    d = DraftDeps(
        classify=classify_fn, draft=draft_fn, critique=critique_fn,
        knowledge=lambda topic: knowledge if knowledge is not None else [ContextItem("S1", "source", SOURCE, "Tariff study — Econ Channel", "https://youtube.com/watch?v=x&t=42s")],
        signals=lambda topic, lang: signals or ["personality · methodology: Checks the base rate first"],
        facts=lambda topic: facts or [ContextItem("F1", "fact", "interest: tariffs — since 2019", "what Echo knows about you", third_party=False)],
        exemplars=lambda lang: exemplars or ["What is the base rate here? Nobody says."],
        language_of=lambda text: "en",
        models={"echo_draft": "gpt-5.5"},
    )
    return d, calls


# ---------------------------------------------------------------------------
# The agent


def test_citations_are_what_the_draft_cited_and_markers_are_stripped():
    d, calls = deps(drafts=["Mostly the importer pays first [S1]. I care about this [F1]. Also [S9]."])
    state = agent.run_echo_draft(d, message="Who really pays for tariffs?")
    r = state["result"]
    assert r["draft"] == "Mostly the importer pays first. I care about this. Also."
    assert r["citations"] == [
        {"kind": "source", "label": "Tariff study — Econ Channel", "url": "https://youtube.com/watch?v=x&t=42s"},
        {"kind": "fact", "label": "what Echo knows about you"},
    ], "S9 matched nothing and is dropped"
    assert r["voice_match_score"] == 100.0 and r["confidence"] == 1.0
    prompt = calls.prompts["draft"][0]
    assert "Checks the base rate first" in prompt and "What is the base rate here?" in prompt
    assert "[S1] (source: Tariff study" in prompt and "Who really pays for tariffs?" in prompt


def test_a_private_person_stops_the_draft_until_acknowledged():
    cls = {"intent": "request", "topic": "dinner", "language": "en",
           "people": [{"name": "Priya", "public": False}, {"name": "Narendra Modi", "public": True}]}
    d, calls = deps(classify=cls)
    state = agent.run_echo_draft(d, message="Priya asked if you can come to dinner")
    assert state["needs_confirmation"] == ["Priya"] and "result" not in state
    assert calls.prompts["draft"] == [], "nothing is drafted before the confirmation"

    state = agent.run_echo_draft(d, message="Priya asked if you can come to dinner", acknowledge_names=["priya"])
    assert state["result"]["draft"]


def test_the_critic_revises_keeps_the_best_and_stops_at_its_limit(monkeypatch):
    monkeypatch.setattr(settings, "ECHO_DRAFT_CRITIQUE_ROUNDS", 2)
    low = {"tone": 2, "vocabulary": 2, "structure": 2, "topicality": 2, "grounded": 2, "notes": ["Too formal for them."]}
    mid = {"tone": 3, "vocabulary": 3, "structure": 4, "topicality": 4, "grounded": 4, "notes": []}
    d, calls = deps(drafts=["Formal draft [S1].", "Better draft [S1]."], critiques=[low, mid])
    r = agent.run_echo_draft(d, message="Who pays?")["result"]
    assert len(calls.prompts["critique"]) == 2 and len(calls.prompts["draft"]) == 2
    assert "Too formal for them." in calls.prompts["draft"][1], "the revision sees the critique"
    assert r["draft"] == "Better draft." and r["critique_rounds"] == 2
    assert r["voice_match_score"] == pytest.approx(3.5 / 5 * 100)


def test_a_failed_critic_is_said_not_hidden():
    d, _ = deps(critiques=[RuntimeError("judge down")])
    r = agent.run_echo_draft(d, message="Who pays?")["result"]
    assert r["voice_match_score"] == 0.0 and "The voice check could not run for this draft." in r["deviation_notes"]


def test_third_party_words_are_paraphrased_and_then_removed():
    quoting = "My view: " + SOURCE + " [S1] That is the base rate."
    d, calls = deps(drafts=[quoting, quoting])  # the paraphrase still quotes
    r = agent.run_echo_draft(d, message="Who pays?")["result"]
    assert len(calls.prompts["draft"]) == 2, "one paraphrase attempt"
    assert "importer first and then for the buyer" not in r["draft"]
    assert "That is the base rate." in r["draft"]
    assert "verbatim_removed" in r["flags"]
    assert agent.verbatim_spans(r["draft"], [SOURCE]) == []


def test_a_good_paraphrase_is_kept_and_own_words_may_repeat():
    d, calls = deps(drafts=["The study says " + SOURCE + " [S1]", "Mostly the importer pays, then us [S1]."])
    r = agent.run_echo_draft(d, message="Who pays?")["result"]
    assert r["draft"] == "Mostly the importer pays, then us." and "verbatim_removed" not in r["flags"]

    note = ContextItem("N1", "note", "What is the base rate here? Nobody in this video says. That is the first thing I check.", "your note", third_party=False)
    d, calls = deps(knowledge=[note], drafts=["What is the base rate here? Nobody in this video says. That is the first thing I check [N1]."])
    r = agent.run_echo_draft(d, message="Thoughts?")["result"]
    assert len(calls.prompts["draft"]) == 1, "the user's own words are not a quote to avoid"
    assert r["citations"] == [{"kind": "note", "label": "your note"}]


def test_an_ungrounded_opinion_is_flagged():
    d, _ = deps(knowledge=[], drafts=["I think it is the buyer."])
    r = agent.run_echo_draft(d, message="Who pays?")["result"]
    assert "ungrounded" in r["flags"]


def test_the_language_comes_from_the_request_then_the_message():
    d, calls = deps(classify={"intent": "social", "topic": "hi", "language": "hi-Latn", "people": []})
    assert agent.run_echo_draft(d, message="kya haal hai")["language"] == "hi-Latn"
    assert "Hindi written in Roman letters" in calls.prompts["draft"][0]
    assert agent.run_echo_draft(d, message="kya haal hai", language="en")["language"] == "en"


# ---------------------------------------------------------------------------
# The service: gates, provenance, persistence


def _studio(db):
    u = auth_service.create_user(db, email=f"sam-{uuid.uuid4().hex[:8]}@example.com", password="pw" * 6)
    u.tier = "studio"
    db.commit()
    return u


def _make_ready(db, user):
    for k in range(100):
        echo_service.record_context(db, user_id=user.id, kind="interest", key=f"k{k}", value="v", source=f"src{k % 3}")
    echo_service.record_context(db, user_id=user.id, kind="personality_trait", key="sceptic", value="yes", source="manual")


def test_status_names_every_gate_in_words(db, monkeypatch):
    user = _studio(db)
    st = echo_draft_service.status(db, user)
    codes = [b["code"] for b in st.blockers]
    assert codes == ["install_off", "not_ready", "voice_test_required"] and not st.enabled
    msg = next(b["message"] for b in st.blockers if b["code"] == "voice_test_required")
    assert "40 of your notes; you have 0" in msg
    assert st.drafts_per_day == 20

    monkeypatch.setattr(settings, "ECHO_SPEAK_AS_ME_ENABLED", True)
    _make_ready(db, user)
    echo_draft_service.record_voice_test(db, user.id, pairs=20, picked_own=17)
    st = echo_draft_service.status(db, user)
    assert [b["code"] for b in st.blockers] == ["voice_test_failed"]
    assert "85% of 20 pairs" in st.blockers[0]["message"]

    echo_draft_service.record_voice_test(db, user.id, pairs=20, picked_own=16)
    assert echo_draft_service.status(db, user).enabled


@pytest.mark.parametrize("pairs,own,passed", [(20, 16, True), (24, 10, True), (19, 5, False), (20, 17, False)])
def test_the_voice_test_rule_is_the_pre_registered_one(db, pairs, own, passed):
    user = _studio(db)
    row = echo_draft_service.record_voice_test(db, user.id, pairs=pairs, picked_own=own)
    assert (row.status == "passed") is passed
    with pytest.raises(ValueError):
        echo_draft_service.record_voice_test(db, user.id, pairs=0, picked_own=0)


def test_a_blocked_draft_spends_nothing(db):
    user = _studio(db)
    d, calls = deps()
    with pytest.raises(echo_draft_service.DraftBlocked) as e:
        echo_draft_service.draft(db, user, "Who pays?", deps=d)
    assert e.value.code == "install_off"
    assert all(not v for v in calls.prompts.values())
    assert db.query(EchoDraft).count() == 0


def test_a_draft_is_stored_with_its_disclosure_counted_and_audited(db, monkeypatch):
    from app.models.audit_log import AuditLog

    monkeypatch.setattr(settings, "ECHO_SPEAK_AS_ME_ENABLED", True)
    user = _studio(db)
    _make_ready(db, user)
    echo_draft_service.record_voice_test(db, user.id, pairs=20, picked_own=12)
    d, _ = deps()
    row = echo_draft_service.draft(db, user, "Who really pays for tariffs?", audience="my brother", deps=d)
    assert row.draft == "Mostly the importer pays first. Then the buyer."
    assert row.disclosure.startswith("Drafted with Echo, reviewed by ")
    assert json.loads(row.citations_json)[0]["kind"] == "source"
    assert row.tokens_in > 0 and row.cost_usd > 0
    assert quota.get_usage(db, user.id, "echo_drafts") == 1
    audit = db.query(AuditLog).filter(AuditLog.event == "echo_drafted").one()
    assert "tariffs" not in (audit.metadata_json or ""), "the audit holds counts, not words"


def test_the_daily_cap_holds(db, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SPEAK_AS_ME_ENABLED", True)
    user = _studio(db)
    _make_ready(db, user)
    echo_draft_service.record_voice_test(db, user.id, pairs=20, picked_own=12)
    for _ in range(20):
        quota.record_usage(db, user.id, "echo_drafts")
    d, calls = deps()
    with pytest.raises(echo_draft_service.DraftCapReached):
        echo_draft_service.draft(db, user, "Who pays?", deps=d)
    assert not calls.prompts["draft"]


def test_only_the_users_own_words_set_the_voice(db, tmp_path, monkeypatch):
    from app.models.job import Job
    from app.services import note_service

    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path))
    user = _studio(db)
    db.add(Job(id=f"j-{user.id[:8]}", tenant_id=user.id, job_type="topic", topic="t", status="completed"))
    db.commit()
    note_service.create_note(db, user.id, target_type="job", target_id=f"j-{user.id[:8]}", body_md="MY NOTE: base rates first.")
    echo_intake_service.create_text_share(db, user.id, user.id, text="MY ESSAY on tariffs.", author_is_tenant=True)
    echo_intake_service.create_text_share(db, user.id, user.id, text="THEIR THREAD that I forwarded.", annotation="mine?")
    texts = echo_draft_service.own_texts(db, user.id)
    assert sorted(texts) == ["MY ESSAY on tariffs.", "MY NOTE: base rates first."]
    assert all("THEIR THREAD" not in t for t in texts), "a context-only share never sets the voice"


def test_exemplars_are_style_diverse_within_the_language():
    texts = [f"Short {k}." for k in range(3)] + ["A " + "very " * 30 + "long one."] + ["yaar ye kya hai bhai"] * 3
    lang = lambda t: "hi-Latn" if "yaar" in t else "en"  # noqa: E731
    picked = echo_draft_service.exemplars(texts, "en", lang, k=3)
    assert len(picked) == 3 and all("yaar" not in t for t in picked)
    assert picked[-1].startswith("A very"), "the longest-sentence text is part of the spread"
    assert len(echo_draft_service.exemplars(texts, "hi-Deva", lang, k=3)) == 3, "falls back to every language"
