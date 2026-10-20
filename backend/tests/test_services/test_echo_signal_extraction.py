"""Signal extraction (S-3.3.2).

What it must hold, with the LLM patched:

- Only the user's own words reach the model: live notes, the questions they
  asked (never a saved search's re-asks, never an answer), shares marked as
  theirs. A context-only share never does, annotation included (D-089).
- An example survives only if it is found, exactly, in the passage it cites;
  a signal with no surviving example is dropped.
- Candidates merge by (type, value, language), weights accumulate across
  runs, and the user's rejection is never written again.
- A deleted note is withdrawn at once (D-074); an edited one is re-read with
  its old evidence withdrawn first; a deleted share leaves the ledger.
- A failed call leaves its inputs pending for the next run; stylometry
  still runs.
- Every run reports its tokens and cost.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from app.config import settings
from app.models.job import Job
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.qa_exchange import QAExchange
from app.models.qa_history_exchange import QAHistoryExchange
from app.models.saved_search_run import SavedSearchRun
from app.models.voice_signal import VoiceSignal
from app.models.voice_signal_input import VoiceSignalInput
from app.services import auth_service, echo_intake_service, echo_signal_service, note_service
from app.services import echo_signal_extraction as ex
from app.services import echo_stylometry as stylo

PERSONAS = json.loads(
    (pathlib.Path(__file__).parent.parent / "fixtures" / "echo_voice" / "personas.json").read_text(encoding="utf-8")
)["personas"]


def _user(db, email, tier="studio"):
    u = auth_service.create_user(db, email=email, password="pw" * 6)
    u.tier = tier
    db.commit()
    return u


@pytest.fixture
def asha(db):
    u = _user(db, "asha@example.com")
    db.add(Job(id=f"job-{u.id[:8]}", tenant_id=u.id, job_type="topic", topic="t", status="completed"))
    db.commit()
    return u


def _note(db, user, body):
    return note_service.create_note(db, user.id, target_type="job", target_id=f"job-{user.id[:8]}", body_md=body)


class FakeLLM:
    """Records prompts; replies with signals quoting whatever passages match
    ``rules``: (regex over a passage, signal_type, value)."""

    def __init__(self, rules=(), fail=False, invent=False):
        self.rules = list(rules)
        self.fail = fail
        self.invent = invent
        self.prompts: list[str] = []

    def __call__(self, prompt: str):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("provider down")
        passages = dict(re.findall(r"\[(P\d+)\] \([^)]*\)\n(.*?)(?=\n\n\[P\d+\] |\n\nReply with JSON)", prompt, re.S))
        out = []
        for pattern, signal_type, value in self.rules:
            examples = []
            for pid, text in passages.items():
                m = re.search(pattern, text)
                if m:
                    examples.append({"id": pid, "quote": m.group(0)})
            if examples:
                out.append({"signal_type": signal_type, "value": value, "language": "en", "register": None, "examples": examples})
        if self.invent:
            out.append({"signal_type": "interest", "value": "Loves opera", "language": "en", "examples": [{"id": "P1", "quote": "I adore the opera season every year"}]})
        return json.dumps({"signals": out}), 1000, 200


RULES = [
    (r"[Bb]ase rates?[^.?!]*[.?!]", "methodology", "Checks the base rate before believing a claim"),
    (r"[Oo]ne source is not evidence[^.]*\.|[Ss]ingle-source claim[^.]*\.", "apprehension", "Distrusts claims that rest on a single source"),
]


# ---------------------------------------------------------------------------
# Pure pieces


def test_language_of_sees_romanised_hindi():
    assert ex.language_of("I think the incentives matter more than intentions here.") == "en"
    assert ex.language_of("pehle dekho incentive kya hai, phir intention samajh aayega") == "hi-Latn"
    assert ex.language_of("मुझे लगता है कि यह सही है") == "hi-Deva"
    assert ex.language_of("yaar this policy is bilkul bakwas, but the data says otherwise") == "mixed"


def test_find_verbatim_returns_the_users_own_span():
    text = "Base rates again.  Most startups fail. So a founder “story” proves very little."
    assert ex.find_verbatim("most startups FAIL.", text) == "Most startups fail."
    assert ex.find_verbatim('So a founder "story" proves', text) == "So a founder “story” proves"
    assert ex.find_verbatim("Most startups succeed.", text) is None
    assert ex.find_verbatim("fail", text) is None, "too short to count as a quote"


def test_parse_reply_drops_invented_quotes_and_unknown_types():
    inp = ex.Input("note:1", "note", "One source is not evidence. Check the base rate.", "2026-10-01", "en")
    reply = json.dumps({"signals": [
        {"signal_type": "apprehension", "value": "Wary of single sources", "language": "en",
         "examples": [{"id": "P1", "quote": "One source is not evidence."}, {"id": "P1", "quote": "Never trust a blog."}]},
        {"signal_type": "interest", "value": "Opera", "examples": [{"id": "P1", "quote": "I adore the opera"}]},
        {"signal_type": "cadence", "value": "Short", "examples": [{"id": "P1", "quote": "Check the base rate."}]},
        {"signal_type": "mood", "value": "x", "examples": [{"id": "P1", "quote": "Check the base rate."}]},
    ]})
    out, dropped = ex.parse_reply(reply, {"P1": inp})
    assert [c["value"] for c in out] == ["Wary of single sources"]
    assert out[0]["examples"] == [{"text": "One source is not evidence.", "source": "note:1", "at": "2026-10-01"}]
    assert dropped == 2
    with pytest.raises(ValueError):
        ex.parse_reply("sorry, I cannot help", {"P1": inp})


def test_batches_respect_the_token_budget():
    inputs = [ex.Input(f"note:{i}", "note", "x" * 4000, None, "en") for i in range(7)]
    assert [len(b) for b in ex.batches(inputs, budget=3000)] == [3, 3, 1]
    assert [len(b) for b in ex.batches(inputs[:3], budget=100_000, max_inputs=2)] == [2, 1]


def test_stylometry_tells_the_three_writers_apart():
    prof = {name: stylo.combine(stylo.profile(t) for t in p["notes"]) for name, p in PERSONAS.items()}
    held = {name: stylo.combine(stylo.profile(t) for t in p["held_out"]) for name, p in PERSONAS.items()}
    for name in PERSONAS:
        own = stylo.similarity(held[name], prof[name])
        others = [stylo.similarity(held[name], prof[o]) for o in PERSONAS if o != name]
        assert own > max(others), (name, own, others)

    asha = {s.value for s in stylo.cadence_signals(prof["asha"])}
    bharat = {s.value for s in stylo.cadence_signals(prof["bharat"])}
    chetan = {s.value for s in stylo.cadence_signals(prof["chetan"])}
    assert "Writes in short sentences (under 12 words on average)" in asha
    assert "Asks questions often (more than one sentence in seven)" in asha
    assert "Writes in long sentences (over 20 words on average)" in bharat
    assert "Adds asides in parentheses" in bharat
    assert {"Uses emoji", "Often starts sentences in lowercase"} <= chetan
    assert stylo.cadence_signals(stylo.profile("Too little. Text.")) == []


def test_profiles_survive_the_ledger_round_trip():
    p = stylo.profile(" ".join(PERSONAS["bharat"]["notes"][:5]))
    back = stylo.StyleProfile.from_json(json.loads(json.dumps(p.to_json())))
    assert back.n_words == p.n_words and back.function_words == p.function_words
    # The ledger keeps the 300 most frequent trigrams, so a stored profile is
    # close to, not identical with, the full one.
    assert stylo.similarity(back, p) == pytest.approx(stylo.similarity(p, p), abs=0.05)


# ---------------------------------------------------------------------------
# Inputs: only the user's own words


def test_gather_reads_own_words_only(db, asha, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path))
    kept = _note(db, asha, "A live note about base rates.")
    gone = _note(db, asha, "A note I deleted.")
    note_service.delete_note(db, asha.id, gone.id)
    db.add_all([
        QAExchange(id="q1", job_id=f"job-{asha.id[:8]}", tenant_id=asha.id, question="Job question?", answer="model words"),
        LibraryQAExchange(id="lq1", tenant_id=asha.id, question="Library question?", answer="model words"),
        LibraryQAExchange(id="lq-rerun", tenant_id=asha.id, question="Pinned re-ask?", answer="model words"),
        QAHistoryExchange(id="hq1", tenant_id=asha.id, question="History question?", answer="model words"),
        SavedSearchRun(saved_search_id="ss1", tenant_id=asha.id, status="ok", exchange_id="lq-rerun"),
    ])
    db.commit()
    own = echo_intake_service.create_text_share(db, asha.id, asha.id, text="My own essay on tariffs.", author_is_tenant=True)
    ctx = echo_intake_service.create_text_share(
        db, asha.id, asha.id, text="SOMEONE ELSE'S thread", annotation="MY ANNOTATION on their thread"
    )

    refs = {i.ref: i for i in ex.gather_inputs(db, asha.id)}
    assert set(refs) == {f"note:{kept.id}", "qa:q1", "library_qa:lq1", "history_qa:hq1", f"share:{own.id}"}
    assert all("model words" not in i.text for i in refs.values()), "answers are the model's words"
    assert f"share:{ctx.id}" not in refs

    llm = FakeLLM()
    ex.run(db, asha.id, llm=llm, model="gpt-5.6-luna")
    sent = "\n".join(llm.prompts)
    assert "SOMEONE ELSE'S thread" not in sent and "MY ANNOTATION" not in sent, "D-089: context-only never feeds signals"
    assert "A note I deleted." not in sent and "Pinned re-ask?" not in sent
    assert "My own essay on tariffs." in sent and "A live note about base rates." in sent


# ---------------------------------------------------------------------------
# Runs


def _seed_asha(db, user, n=None):
    notes = [_note(db, user, t) for t in PERSONAS["asha"]["notes"][:n]]
    return notes


def test_a_run_creates_signals_with_verbatim_examples_and_reports_cost(db, asha):
    notes = _seed_asha(db, asha)
    llm = FakeLLM(RULES, invent=True)
    report = ex.run(db, asha.id, llm=llm, model="gpt-5.6-luna")

    assert report.inputs_read == len(notes) and report.batches == len(llm.prompts) >= 1
    assert report.tokens_in == 1000 * report.batches and report.tokens_out == 200 * report.batches
    assert report.cost_usd == pytest.approx(report.batches * (1000 * 0.20 + 200 * 1.20) / 1e6)
    assert report.examples_dropped >= 1, "the invented opera quote is not in any passage"

    rows = {r.value: r for r in echo_signal_service.list_signals(db, asha.id)}
    assert "Loves opera" not in rows
    method = rows["Checks the base rate before believing a claim"]
    assert method.origin == "llm" and method.language == "en"
    sources = json.loads(method.derived_from)
    assert method.weight == len(sources) == 2, "two notes mention base rates"
    texts = {n.id: n.body_md for n in notes}
    for e in json.loads(method.examples_json):
        assert e["text"] in texts[e["source"].split(":", 1)[1]], "every example is the user's exact words"
    assert len(json.loads(method.examples_json)) <= echo_signal_service.MAX_EXAMPLES

    ledger = db.query(VoiceSignalInput).filter(VoiceSignalInput.tenant_id == asha.id).all()
    assert len(ledger) == len(notes) and all(r.llm_done for r in ledger)
    # Stylometry ran too.
    cadence = {r.value for r in rows.values() if r.signal_type == "cadence"}
    assert "Writes in short sentences (under 12 words on average)" in cadence
    assert all(r.origin == "stylometry" for r in rows.values() if r.signal_type == "cadence")

    # Nothing new: a second run reads nothing and calls nothing.
    again = FakeLLM(RULES)
    assert ex.run(db, asha.id, llm=again, model="gpt-5.6-luna").inputs_read == 0
    assert again.prompts == []


def test_known_signals_are_offered_and_weights_accumulate(db, asha):
    _seed_asha(db, asha, n=10)
    ex.run(db, asha.id, llm=FakeLLM(RULES), model="m")
    first = {r.value: r.weight for r in echo_signal_service.list_signals(db, asha.id)}

    for t in PERSONAS["asha"]["notes"][10:]:
        _note(db, asha, t)
    llm = FakeLLM(RULES)
    ex.run(db, asha.id, llm=llm, model="m")
    assert "Checks the base rate before believing a claim" in llm.prompts[0], "the model is told the known wording"
    rows = {r.value: r for r in echo_signal_service.list_signals(db, asha.id)}
    # One single-source note in each half of the fixture.
    key = "Distrusts claims that rest on a single source"
    assert first[key] == 1 and rows[key].weight == 2
    assert db.query(VoiceSignal).filter(VoiceSignal.tenant_id == asha.id, VoiceSignal.value == key).count() == 1


def test_the_users_rejection_is_never_written_again(db, asha):
    _seed_asha(db, asha, n=12)
    ex.run(db, asha.id, llm=FakeLLM(RULES), model="m")
    row = next(r for r in echo_signal_service.list_signals(db, asha.id) if r.signal_type == "apprehension")
    echo_signal_service.suppress(db, asha.id, row.id)

    for t in PERSONAS["asha"]["notes"][12:]:
        _note(db, asha, t)
    report = ex.run(db, asha.id, llm=FakeLLM(RULES), model="m")
    assert report.counts.rejected_by_user >= 1
    live = [r for r in echo_signal_service.list_signals(db, asha.id) if r.signal_type == "apprehension"]
    assert live == []
    assert db.get(VoiceSignal, row.id).suppressed_reason == "user"


def test_a_rejected_cadence_is_not_recomputed(db, asha):
    _seed_asha(db, asha)
    ex.run(db, asha.id, use_llm=False)
    short = next(r for r in echo_signal_service.list_signals(db, asha.id) if r.value.startswith("Writes in short"))
    echo_signal_service.suppress(db, asha.id, short.id)
    _note(db, asha, "Another short note. Why not?")
    ex.run(db, asha.id, use_llm=False)
    assert not any(r.value.startswith("Writes in short") for r in echo_signal_service.list_signals(db, asha.id))


def test_deleting_a_note_withdraws_it_at_once(db, asha):
    lone = _note(db, asha, "Single-source claim again. Flagging it and moving on.")
    other = _note(db, asha, "Base rates again. Most startups fail.")
    ex.run(db, asha.id, llm=FakeLLM(RULES), model="m")
    appr = next(r for r in echo_signal_service.list_signals(db, asha.id) if r.signal_type == "apprehension")
    assert json.loads(appr.derived_from) == [f"note:{lone.id}"]

    note_service.delete_note(db, asha.id, lone.id)
    db.expire_all()
    row = db.get(VoiceSignal, appr.id)
    assert row.suppressed_reason == "source_deleted" and json.loads(row.examples_json) == []
    assert db.query(VoiceSignalInput).filter(VoiceSignalInput.source_ref == f"note:{lone.id}").count() == 0
    assert db.query(VoiceSignalInput).filter(VoiceSignalInput.source_ref == f"note:{other.id}").count() == 1


def test_an_edited_note_is_read_again(db, asha):
    note = _note(db, asha, "Single-source claim again. Flagging it and moving on.")
    ex.run(db, asha.id, llm=FakeLLM(RULES), model="m")
    note_service.update_note(db, asha.id, note.id, body_md="Base rates first. Then the story.")
    assert ex.pending(db, asha.id).changed[0].ref == f"note:{note.id}"

    llm = FakeLLM(RULES)
    ex.run(db, asha.id, llm=llm, model="m")
    assert "Base rates first. Then the story." in llm.prompts[0]
    by_type = {r.signal_type: r for r in echo_signal_service.list_signals(db, asha.id)}
    assert "apprehension" not in by_type, "the old wording no longer supports it"
    assert json.loads(by_type["methodology"].examples_json)[0]["text"] == "Base rates first."


def test_a_share_records_its_signals_and_leaves_the_ledger_on_delete(db, asha, tmp_path, monkeypatch, unauthenticated_client):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path))
    share = echo_intake_service.create_text_share(
        db, asha.id, asha.id, text="One source is not evidence. I wrote this.", author_is_tenant=True
    )
    ex.run(db, asha.id, llm=FakeLLM(RULES), model="m")
    db.refresh(share)
    sig_ids = json.loads(share.derived_signal_ids_json)
    assert sig_ids and db.get(VoiceSignal, sig_ids[0]).signal_type == "apprehension"

    token, _ = auth_service.create_access_token(asha.id)
    r = unauthenticated_client.delete(f"/api/v1/echo/shares/{share.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(VoiceSignal, sig_ids[0]).suppressed_reason == "source_deleted"
    assert db.query(VoiceSignalInput).filter(VoiceSignalInput.source_ref == f"share:{share.id}").count() == 0
    SharedSystemClient._identifier_to_system = {}


def test_a_failed_call_leaves_its_inputs_pending(db, asha):
    _seed_asha(db, asha, n=5)
    report = ex.run(db, asha.id, llm=FakeLLM(RULES, fail=True), model="m")
    assert report.calls_failed == 1
    assert db.query(VoiceSignalInput).filter(VoiceSignalInput.llm_done.is_(True)).count() == 0
    assert len(ex.pending(db, asha.id).retry) == 5

    llm = FakeLLM(RULES)
    ex.run(db, asha.id, llm=llm, model="m")
    assert len(llm.prompts) == 1 and ex.pending(db, asha.id).count == 0


def test_tenants_never_mix(db, asha):
    other = _user(db, "other@example.com")
    db.add(Job(id=f"job-{other.id[:8]}", tenant_id=other.id, job_type="topic", topic="t", status="completed"))
    db.commit()
    _note(db, other, "Single-source claim again. OTHER TENANT.")
    _note(db, asha, "Base rates again. Most startups fail.")
    llm = FakeLLM(RULES)
    ex.run(db, asha.id, llm=llm, model="m")
    assert "OTHER TENANT" not in "\n".join(llm.prompts)
    assert echo_signal_service.list_signals(db, other.id) == []


# ---------------------------------------------------------------------------
# Queueing and the hooks


def test_maybe_queue_waits_for_enough_new_text(db, asha, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SIGNAL_EXTRACTION", "off")
    assert ex.maybe_queue(db, asha.id) == "off"

    monkeypatch.setattr(settings, "ECHO_SIGNAL_EXTRACTION", "celery")
    monkeypatch.setattr(settings, "ECHO_SIGNALS_MIN_NEW_INPUTS", 3)
    dispatched = []
    from app.services import task_routing_service

    monkeypatch.setattr(task_routing_service, "dispatch_for_user", lambda task, user, *a: dispatched.append(a))
    _note(db, asha, "one")  # the create hook itself calls maybe_queue
    assert dispatched == []
    assert ex.maybe_queue(db, asha.id) == "waiting"
    assert ex.maybe_queue(db, asha.id, force=True) == "queued"
    dispatched.clear()
    _note(db, asha, "two")
    _note(db, asha, "three")
    assert dispatched == [(asha.id,)], "the note hook queued once the threshold was met"

    free = _user(db, "free@example.com", tier="free")
    assert ex.maybe_queue(db, free.id, force=True) == "not_entitled"


def test_the_qa_routes_and_share_processing_queue_learning(db, monkeypatch):
    """Wiring: each surface where the user writes calls maybe_queue."""
    import inspect

    from app.routers import library, qa, qa_history
    from app.services import echo_processing_service

    for mod in (qa, library, qa_history):
        assert "echo_signal_extraction.maybe_queue(db, current_user.id)" in inspect.getsource(mod), mod.__name__
    src = inspect.getsource(echo_processing_service._finish)
    assert "voice_eligible(share)" in src and "maybe_queue(db, share.tenant_id)" in src


def test_library_question_queues_learning(client, db, test_user, monkeypatch):
    calls = []
    monkeypatch.setattr(ex, "maybe_queue", lambda db_, tenant, **k: calls.append(tenant) or "waiting")
    from app.agents import qa_agent

    monkeypatch.setattr(qa_agent, "run_library_qa_agent", lambda **k: {"answer": "a", "references": []})
    r = client.post("/api/v1/library/qa", json={"question": "What is the base rate?"})
    assert r.status_code in (200, 201), r.text
    assert calls == [test_user.id]


def test_signals_endpoint_reports_learning_state(unauthenticated_client, db, asha, monkeypatch):
    token, _ = auth_service.create_access_token(asha.id)
    h = {"Authorization": f"Bearer {token}"}
    _note(db, asha, "Base rates again.")
    _note(db, asha, "पहले आधार दर देखो, फिर कहानी।")
    body = unauthenticated_client.get("/api/v1/echo/signals", headers=h).json()
    assert body["learning"]["inputs"] == 2 and body["learning"]["pending"] == 2
    assert body["learning"]["by_language"] == {"en": 1, "hi-Deva": 1}
    assert body["learning"]["last_learned_at"] is None

    monkeypatch.setattr(settings, "ECHO_SIGNAL_EXTRACTION", "inline")
    monkeypatch.setattr(ex, "_default_llm", lambda tenant, db_: (FakeLLM(RULES), "gpt-5.6-luna"))
    r = unauthenticated_client.post("/api/v1/echo/signals/learn", headers=h)
    assert r.status_code == 202 and r.json() == {"status": "ran", "pending": 0}
    body = unauthenticated_client.get("/api/v1/echo/signals", headers=h).json()
    assert body["learning"]["pending"] == 0 and body["learning"]["last_learned_at"] is not None
    assert any(s["value"] == "Checks the base rate before believing a claim" for s in body["items"])
