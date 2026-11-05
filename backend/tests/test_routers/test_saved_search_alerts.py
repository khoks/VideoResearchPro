"""S-8.3.3: change detection, notifications and email for saved searches.

The library Q&A agent is a fake, the embedder a bag-of-words stand-in and
the judge is patched at ``get_llm_for``, so no provider is called. The
thresholds are the pre-registered priors (J < 0.50, D > 0.15).

T-1.15.4.9 mutation checks, run by hand on 2026-11-05:
- comparing a cut answer as usual fails
  ``test_a_cut_answer_is_not_a_change_in_the_sources``;
- a cut answer moving the embedding, the cited ids or the exchange pointer fails
  ``test_the_answer_after_a_cut_is_compared_with_the_last_full_one``;
- a cut answer not taking the empty pointer fails
  ``test_a_first_answer_that_was_cut_shows_on_the_card_and_sets_no_baseline``;
- a cut answer leaving ``last_scope_hash`` alone fails
  ``test_the_gate_holds_after_a_cut_and_run_now_still_asks``;
- ``decided_by`` staying ``none`` fails the first test and the runs endpoint test.

T-8.3.3.10 mutation checks, run by hand on 2026-11-04:
- keying ``cited_key`` on ``video_id`` again fails
  ``test_a_pdf_only_citation_counts``;
- skipping ``with_document_ids`` on the baseline fails
  ``test_a_baseline_from_before_document_ids_does_not_read_as_changed``;
- removing the ``comparable`` check fails the ``unresolvable`` tests;
- resolving outside the visible set fails
  ``test_an_old_key_resolves_only_inside_the_tenants_visible_set``.
"""
from __future__ import annotations

import hashlib
import json
import os
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from app.agents import qa_agent
from app.models.document import Document
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.notification import Notification
from app.models.quota_usage import QuotaUsage
from app.models.saved_search_run import SavedSearchRun
from app.services import (
    auth_service,
    llm_routing,
    llm_smoke,
    saved_search_change_service,
    saved_search_service,
    visibility_service,
)

WEEKLY = {"cadence": "weekly", "hour": 9, "weekday": 0, "timezone": "UTC"}


def cheap_encode(texts):
    out = []
    for t in texts:
        v = [0.0] * 64
        for w in t.lower().replace(".", "").split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
        out.append(v)
    return out


@pytest.fixture(autouse=True)
def _seams(monkeypatch):
    monkeypatch.setattr(saved_search_service, "_encode", cheap_encode)
    with patch("app.services.chroma_service.upsert_qa_exchange"), patch(
        "app.services.email_service.send_email", return_value=True
    ) as mail:
        yield mail


@pytest.fixture
def pro(db, test_user):
    test_user.tier = "pro"
    db.commit()
    return test_user


class Agent:
    """Answers with whatever the test sets; refs are (video_id, title) pairs."""

    def __init__(self, answer="Rates fell twice this year.", refs=(("v1", "Fed minutes"), ("v2", "Bank note"))):
        self.answer, self.refs, self.calls = answer, list(refs), 0
        self.cut = False

    def __call__(self, **_kwargs):
        self.calls += 1
        return {
            "answer": self.answer,
            "references": [{"video_id": k, "video_title": t} for k, t in self.refs],
            "answer_cut_off": self.cut,
        }


def _doc(db, tenant_id, title="Source"):
    doc = Document(video_id=os.urandom(5).hex()[:11], title=title, url="https://example.com", transcript_status="completed")
    db.add(doc)
    db.commit()
    visibility_service.grant(db, [doc.document_id], tenant_id, "job")
    return doc


def _search(db, user, **over):
    _doc(db, user.id)
    return saved_search_service.create(db, user, question="What do my sources say about rate cuts?", cadence=WEEKLY, **over)


def _runs(db, ss):
    return db.query(SavedSearchRun).filter_by(saved_search_id=ss.id).order_by(SavedSearchRun.ran_at).all()


def _notes(db, user):
    return db.query(Notification).filter_by(tenant_id=user.id).all()


def _judge_returning(payload=None, fail=False):
    class Fake:
        calls = 0

        def invoke(self, messages):
            Fake.calls += 1
            self.prompt = messages[0].content
            if fail:
                raise RuntimeError("judge down")
            return AIMessage(content=json.dumps(payload))

    return Fake()


def _cut(agent: Agent) -> None:
    """The same question stopped at its budget: the end, and its citations, are gone."""
    agent.answer, agent.refs, agent.cut = "Rates fell", agent.refs[:1], True


FULL_REFS = (("v1", "Fed minutes"), ("v2", "Bank note"), ("v3", "Press conference"))


# ---------------------------------------------------------------- the gate


def test_a_scheduled_run_with_nothing_new_is_skipped_before_quota_or_model(db, pro):
    ss = _search(db, pro)
    agent = Agent()
    assert saved_search_service.execute(db, ss.id, agent=agent)["status"] == "ok"  # first run: no baseline yet
    out = saved_search_service.execute(db, ss.id, agent=agent)
    assert out["status"] == "no_new_sources"
    assert agent.calls == 1
    assert db.query(QuotaUsage).filter_by(user_id=pro.id).one().consumed == 1
    assert [r.status for r in _runs(db, ss)] == ["ok", "no_new_sources"]


def test_a_new_source_in_scope_opens_the_gate_and_run_now_always_asks(db, pro):
    ss = _search(db, pro)
    agent = Agent()
    saved_search_service.execute(db, ss.id, agent=agent)
    assert saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)["status"] == "ok"
    _doc(db, pro.id, "Fresh source")
    assert saved_search_service.execute(db, ss.id, agent=agent)["status"] == "ok"
    assert agent.calls == 3


def test_another_tenants_new_source_does_not_open_the_gate(db, pro):
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=Agent())
    other = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    _doc(db, other.id, "Theirs")
    assert saved_search_service.execute(db, ss.id, agent=Agent())["status"] == "no_new_sources"


def test_a_shelf_that_gains_a_run_of_already_visible_sources_opens_the_gate(db, pro):
    """A visibility-timestamp gate would miss this: nothing new was granted,
    the shelf's document set changed."""
    from app.models.job import Job
    from app.models.job_video import JobVideo
    from app.services import shelf_service

    seen, later = _doc(db, pro.id, "Seen"), _doc(db, pro.id, "Already visible")
    jobs = []
    for doc in (seen, later):
        job = Job(job_type="topic", topic="t", status="completed", num_videos=1, tenant_id=pro.id)
        db.add(job)
        db.commit()
        db.add(JobVideo(job_id=job.id, document_id=doc.document_id, video_id=doc.video_id, approved=True))
        db.commit()
        jobs.append(job)
    shelf = shelf_service.create_shelf(db, pro.id, name="Macro")
    shelf_service.add_job(db, shelf, jobs[0])
    ss = saved_search_service.create(db, pro, question="What changed on rates?", cadence=WEEKLY, scope={"shelf_id": shelf.id})
    saved_search_service.execute(db, ss.id, agent=Agent())
    assert saved_search_service.execute(db, ss.id, agent=Agent())["status"] == "no_new_sources"
    shelf_service.add_job(db, shelf, jobs[1])
    assert saved_search_service.execute(db, ss.id, agent=Agent())["status"] == "ok"


# ---------------------------------------------------------------- signals


def test_the_first_run_is_the_baseline_and_notifies_nobody(db, pro):
    ss = _search(db, pro)
    out = saved_search_service.execute(db, ss.id, agent=Agent())
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.changed is None and run.decided_by == "none"
    db.refresh(ss)
    assert len(json.loads(ss.last_answer_embedding_json)) == 64
    assert _notes(db, pro) == []


def test_the_same_answer_and_sources_do_not_notify(db, pro, _seams):
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=Agent())
    with patch.object(saved_search_change_service, "get_llm_for") as judge:
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=Agent())
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.changed is False and run.decided_by == "agreed" and run.jaccard == 1.0 and run.embedding_distance == 0.0
    judge.assert_not_called()
    assert _notes(db, pro) == [] and not _seams.called


def test_new_sources_and_a_new_answer_notify_in_app_and_by_email(db, pro, _seams):
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=Agent())
    changed = Agent(answer="A third cut arrived in October after weak hiring data.", refs=(("v9", "October statement"),))
    with patch.object(saved_search_change_service, "get_llm_for") as judge:
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=changed)
    judge.assert_not_called()  # both signals agreed
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.changed is True and run.decided_by == "agreed"
    assert json.loads(run.added_reference_ids_json) == ["v9"] and json.loads(run.dropped_reference_ids_json) == ["v1", "v2"]
    assert "October statement" in run.diff_summary and "No longer cites" in run.diff_summary
    (note,) = _notes(db, pro)
    assert note.kind == "saved_search_changed" and note.href == f"/saved-searches?search={ss.id}&run={run.id}"
    assert note.title.startswith("New answer: What do my sources say")
    to, subject, body = _seams.call_args.args
    assert to == pro.email and "new answer" in subject
    assert f"/saved-searches?search={ss.id}&run={run.id}" in body and saved_search_service_settings_base() in body


def test_a_changed_answer_rings_the_live_bell(db, pro, monkeypatch):
    """T-8.3.3.8 at the production producer: the notification a changed
    answer stores is published for its owner's open sockets, id and kind
    only; the baseline run publishes nothing."""
    from app.config import settings
    from app.services import progress_service

    monkeypatch.setattr(settings, "NOTIFICATIONS_PUSH_ENABLED", True)
    ss = _search(db, pro)
    with patch.object(progress_service, "publish_notification", return_value=True) as publish:
        saved_search_service.execute(db, ss.id, agent=Agent())
        publish.assert_not_called()
        changed = Agent(answer="A third cut arrived in October after weak hiring data.", refs=(("v9", "October statement"),))
        with patch.object(saved_search_change_service, "get_llm_for"):
            saved_search_service.execute(db, ss.id, trigger="manual", agent=changed)
    (note,) = _notes(db, pro)
    publish.assert_called_once_with(pro.id, {"type": "notification", "id": note.id, "kind": "saved_search_changed"})


def saved_search_service_settings_base():
    from app.config import settings

    return settings.APP_BASE_URL.rstrip("/")


def test_no_email_when_the_search_asks_for_none(db, pro, _seams):
    ss = _search(db, pro, notify_email=False)
    saved_search_service.execute(db, ss.id, agent=Agent())
    saved_search_service.execute(db, ss.id, trigger="manual", agent=Agent(answer="Something else entirely now.", refs=(("v9", "New"),)))
    assert len(_notes(db, pro)) == 1 and not _seams.called


def test_the_judge_decides_only_when_the_signals_disagree(db, pro):
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=Agent())
    # Same words, different sources: J says changed, D says not.
    fake = _judge_returning({"changed": True, "what_changed": "The October statement now backs a third cut."})
    with patch.object(saved_search_change_service, "get_llm_for", return_value=fake) as factory:
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=Agent(refs=(("v7", "Other"),)))
    assert factory.call_args.args[0] == "saved_search_judge"
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.decided_by == "judged" and run.changed is True
    assert run.diff_summary == "The October statement now backs a third cut."
    assert "PREVIOUS ANSWER" in fake.prompt and "LANGUAGE OF OUTPUT" in fake.prompt
    assert _notes(db, pro)[0].body == "The October statement now backs a third cut."


def test_a_judge_that_sees_no_substance_change_stays_quiet(db, pro):
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=Agent())
    fake = _judge_returning({"changed": False, "what_changed": ""})
    with patch.object(saved_search_change_service, "get_llm_for", return_value=fake):
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=Agent(refs=(("v7", "Other"),)))
    assert db.get(SavedSearchRun, out["run_id"]).changed is False
    assert _notes(db, pro) == []


def test_a_failed_judge_lets_the_citation_signal_decide(db, pro):
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=Agent())
    with patch.object(saved_search_change_service, "get_llm_for", return_value=_judge_returning(fail=True)):
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=Agent(refs=(("v7", "Other"),)))
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.decided_by == "judge_failed" and run.changed is True  # the cited set did change


# ---------------------------------------------------------------- document_id keys
#
# T-8.3.3.10: the cited set is keyed on document_id (D-070). `video_id` is empty
# on every non-YouTube citation, so before this a PDF was not counted at all.


class RefAgent:
    """Answers with whole reference dicts, shaped as the agent shapes them."""

    def __init__(self, refs, answer="Rates fell twice this year."):
        self.refs, self.answer = refs, answer

    def __call__(self, **_kwargs):
        return {"answer": self.answer, "references": self.refs}


def _source(db, tenant_id, title, source_type="pdf"):
    doc = Document(
        source_type=source_type, source_id=f"{source_type}-{title}", title=title,
        url="https://example.com/paper", transcript_status="completed",
    )
    db.add(doc)
    db.commit()
    visibility_service.grant(db, [doc.document_id], tenant_id, "pdf_upload")
    return doc


def _library_ref(doc):
    """The reference the library agent stores: `_chunk_to_reference`, then
    `video_id` from the url, which is "" for everything but YouTube."""
    meta = {
        "source_type": doc.source_type, "source_id": doc.source_id, "document_id": doc.document_id,
        "video_title": doc.title, "video_url": doc.url, "video_id": doc.video_id or "",
    }
    _, ref = qa_agent._chunk_to_reference({"text": "Text.", "metadata": meta})
    return {**ref, "video_id": doc.video_id or ""}


def _before_397(ref):
    """That reference as an exchange stored before #397 holds it."""
    return {k: v for k, v in ref.items() if k != "document_id"}


def _old_baseline(db, ss, refs):
    """Rewrites the last exchange to what a row from before #397 holds."""
    db.refresh(ss)
    db.get(LibraryQAExchange, ss.last_exchange_id).references_json = json.dumps(refs)
    db.commit()


def test_a_pdf_only_citation_counts(db, pro):
    first, second = _source(db, pro.id, "Q3 report"), _source(db, pro.id, "Q4 report")
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=RefAgent([_library_ref(first)]))
    db.refresh(ss)
    assert json.loads(ss.last_reference_ids_json) == [first.document_id]

    changed = RefAgent([_library_ref(second)], answer="A third cut arrived in October after weak hiring data.")
    with patch.object(saved_search_change_service, "get_llm_for") as judge:
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=changed)
    judge.assert_not_called()  # both signals agreed: the citation one saw the PDFs
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.changed is True and run.decided_by == "agreed" and run.jaccard == 0.0
    assert json.loads(run.added_reference_ids_json) == [second.document_id]
    assert json.loads(run.dropped_reference_ids_json) == [first.document_id]
    assert "Q4 report" in run.diff_summary and "Q3 report" in run.diff_summary


def test_a_pdf_citation_that_stays_is_not_a_change(db, pro):
    paper = _source(db, pro.id, "Q3 report")
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=RefAgent([_library_ref(paper)]))
    with patch.object(saved_search_change_service, "get_llm_for") as judge:
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=RefAgent([_library_ref(paper)]))
    judge.assert_not_called()
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.changed is False and run.jaccard == 1.0 and run.decided_by == "agreed"


def test_a_baseline_from_before_document_ids_does_not_read_as_changed(db, pro):
    """The stored exchange names its videos by YouTube id alone. The same
    videos cited today carry both ids, and that must not look like a change."""
    videos = [_doc(db, pro.id, title) for title in ("Fed minutes", "Bank note")]
    ss = saved_search_service.create(db, pro, question="What do my sources say about rate cuts?", cadence=WEEKLY)
    stored = [{"video_id": v.video_id, "video_title": v.title} for v in videos]
    saved_search_service.execute(db, ss.id, agent=RefAgent(stored))
    _old_baseline(db, ss, stored)

    cited = [{"video_id": v.video_id, "document_id": v.document_id, "video_title": v.title} for v in videos]
    with patch.object(saved_search_change_service, "get_llm_for") as judge:
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=RefAgent(cited))
    judge.assert_not_called()
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.changed is False and run.jaccard == 1.0 and run.decided_by == "agreed"
    assert json.loads(run.added_reference_ids_json) == [] and json.loads(run.dropped_reference_ids_json) == []
    assert _notes(db, pro) == []
    db.refresh(ss)
    assert json.loads(ss.last_reference_ids_json) == sorted(v.document_id for v in videos)


def test_an_unresolvable_old_citation_skips_the_citation_vote_once(db, pro):
    """A non-YouTube citation from before #397 has no id to map, so the sets
    cannot be compared. Comparing them anyway reports the PDF as a new source."""
    paper = _source(db, pro.id, "Q3 report")
    ref = _library_ref(paper)
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=RefAgent([ref]))
    _old_baseline(db, ss, [_before_397(ref)])

    with patch.object(saved_search_change_service, "get_llm_for") as judge:
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=RefAgent([ref]))
    judge.assert_not_called()
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.changed is False and run.decided_by == "embedding_only" and run.jaccard is None
    assert run.embedding_distance == 0.0
    assert json.loads(run.added_reference_ids_json) == [] and json.loads(run.dropped_reference_ids_json) == []
    assert _notes(db, pro) == []

    # Once: this run's answer is the baseline now, and it carries the id.
    other = _source(db, pro.id, "Q4 report")
    moved = RefAgent([_library_ref(other)], answer="A third cut arrived in October after weak hiring data.")
    out = saved_search_service.execute(db, ss.id, trigger="manual", agent=moved)
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.changed is True and run.decided_by == "agreed" and run.jaccard == 0.0


def test_an_unresolvable_old_citation_leaves_the_judge_to_decide_a_moved_answer(db, pro):
    paper = _source(db, pro.id, "Q3 report")
    ref = _library_ref(paper)
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=RefAgent([ref]))
    _old_baseline(db, ss, [_before_397(ref)])

    fake = _judge_returning({"changed": True, "what_changed": "The October statement now backs a third cut."})
    moved = RefAgent([ref], answer="A third cut arrived in October after weak hiring data.")
    with patch.object(saved_search_change_service, "get_llm_for", return_value=fake):
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=moved)
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.changed is True and run.decided_by == "judged" and run.jaccard is None
    assert run.diff_summary == "The October statement now backs a third cut."


def test_an_unresolvable_old_citation_with_a_failed_judge_stays_quiet(db, pro):
    paper = _source(db, pro.id, "Q3 report")
    ref = _library_ref(paper)
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=RefAgent([ref]))
    _old_baseline(db, ss, [_before_397(ref)])

    moved = RefAgent([ref], answer="A third cut arrived in October after weak hiring data.")
    with patch.object(saved_search_change_service, "get_llm_for", return_value=_judge_returning(fail=True)):
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=moved)
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.changed is False and run.decided_by == "judge_failed"
    assert _notes(db, pro) == []


def test_an_old_key_resolves_only_inside_the_tenants_visible_set(db, pro):
    other = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    mine, theirs = _doc(db, pro.id, "Mine"), _doc(db, other.id, "Theirs")
    refs = [{"video_id": mine.video_id}, {"video_id": theirs.video_id}]
    out = saved_search_change_service.with_document_ids(db, pro.id, refs)
    assert out[0]["document_id"] == mine.document_id
    assert "document_id" not in out[1]
    assert saved_search_change_service.cited_keys(out) == {mine.document_id, theirs.video_id}


def test_a_note_citation_stays_out_of_the_cited_set_and_keeps_the_vote(db, pro):
    """A note is not a document: it has no id to key on, and that must not
    read as a citation that could not be resolved."""
    paper = _source(db, pro.id, "Q3 report")
    note = {"source_type": "note", "note_id": "n1", "video_id": "", "video_title": "Your note"}
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=RefAgent([_library_ref(paper), note]))
    with patch.object(saved_search_change_service, "get_llm_for") as judge:
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=RefAgent([_library_ref(paper), note]))
    judge.assert_not_called()
    run = db.get(SavedSearchRun, out["run_id"])
    assert run.jaccard == 1.0 and run.decided_by == "agreed" and run.changed is False


def test_thresholds_come_from_settings(monkeypatch):
    v = dict(question="q", previous_answer="a", previous_refs=[{"video_id": "x"}], previous_embedding=[1.0, 0.0],
             current_answer="b", current_refs=[{"video_id": "x"}], current_embedding=[0.9, 0.1])
    assert saved_search_change_service.compare(**v).changed is False
    monkeypatch.setattr(saved_search_change_service.settings, "SAVED_SEARCH_EMBEDDING_THRESHOLD", 0.001)
    monkeypatch.setattr(saved_search_change_service.settings, "SAVED_SEARCH_JACCARD_THRESHOLD", 1.01)
    assert saved_search_change_service.compare(**v).changed is True


def test_a_failed_run_keeps_the_baseline_and_notifies_nobody(db, pro):
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=Agent())
    db.refresh(ss)
    baseline = (ss.last_exchange_id, ss.last_answer_embedding_json)

    def boom(**_):
        raise RuntimeError("provider down")

    assert saved_search_service.execute(db, ss.id, trigger="manual", agent=boom)["status"] == "failed"
    db.refresh(ss)
    assert (ss.last_exchange_id, ss.last_answer_embedding_json) == baseline
    assert _runs(db, ss)[-1].status == "failed" and _notes(db, pro) == []


# ---------------------------------------------------------------- REST


# ---------------------------------------------------------------- a cut answer


def test_a_cut_answer_is_not_a_change_in_the_sources(db, pro, _seams):
    """T-1.15.4.9. It cites one of the three sources, so both signals would vote."""
    ss = _search(db, pro)
    agent = Agent(refs=FULL_REFS)
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    _cut(agent)
    fake = _judge_returning({"changed": True, "what_changed": "Should never be asked."})

    with patch.object(saved_search_change_service, "get_llm_for", return_value=fake):
        out = saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)

    assert out["status"] == "ok"
    assert out["changed"] is None
    assert type(fake).calls == 0
    assert _notes(db, pro) == []
    _seams.assert_not_called()
    run = _runs(db, ss)[-1]
    assert (run.changed, run.decided_by, run.jaccard, run.embedding_distance) == (None, "cut_off", None, None)
    assert run.previous_exchange_id is None
    assert (run.diff_summary, json.loads(run.dropped_reference_ids_json)) == (None, [])
    assert db.get(LibraryQAExchange, run.exchange_id).answer_cut_off is True


def test_a_cut_run_still_spends_its_question(db, pro):
    """The model answered, so the quota is charged, as for any answer."""
    ss = _search(db, pro)
    agent = Agent()
    _cut(agent)
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    assert db.query(QuotaUsage).filter_by(user_id=pro.id).one().consumed == 1


def test_the_answer_after_a_cut_is_compared_with_the_last_full_one(db, pro, _seams):
    """The same three sources come back. Against the cut answer they would read
    as two new sources; against the last full answer nothing moved."""
    ss = _search(db, pro)
    agent = Agent(refs=FULL_REFS)
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    full_exchange = _runs(db, ss)[-1].exchange_id
    full_baseline = (ss.last_answer_hash, ss.last_reference_ids_json, ss.last_answer_embedding_json)

    full_answer = agent.answer
    _cut(agent)
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    db.refresh(ss)
    assert ss.last_exchange_id == full_exchange
    assert (ss.last_answer_hash, ss.last_reference_ids_json, ss.last_answer_embedding_json) == full_baseline

    agent.answer, agent.refs, agent.cut = full_answer, list(FULL_REFS), False
    out = saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)

    assert out["changed"] is False
    run = _runs(db, ss)[-1]
    assert run.previous_exchange_id == full_exchange
    assert run.decided_by == "agreed"
    assert _notes(db, pro) == []
    _seams.assert_not_called()


def test_a_real_change_after_a_cut_is_still_found(db, pro):
    """A cut holds the comparison over; it does not lose what moved."""
    ss = _search(db, pro)
    agent = Agent(refs=FULL_REFS)
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    full_exchange = _runs(db, ss)[-1].exchange_id
    _cut(agent)
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)

    agent.answer, agent.cut = "Rates rose sharply after the October statement.", False
    agent.refs = [("v8", "October statement"), ("v9", "Treasury note")]
    out = saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)

    assert out["changed"] is True
    assert _runs(db, ss)[-1].previous_exchange_id == full_exchange
    (note,) = _notes(db, pro)
    assert "October statement" in note.body


def test_a_first_answer_that_was_cut_shows_on_the_card_and_sets_no_baseline(db, pro, _seams):
    ss = _search(db, pro)
    agent = Agent(refs=FULL_REFS)
    full_answer = agent.answer
    _cut(agent)
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    assert saved_search_service.to_dict(db, ss)["last_answer"] == "Rates fell"
    assert ss.last_answer_embedding_json is None

    # A second cut in a row: the card takes the newest, and still no baseline.
    agent.answer = "Rates fell twice"
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    assert saved_search_service.to_dict(db, ss)["last_answer"] == "Rates fell twice"
    assert ss.last_answer_embedding_json is None

    # The first full answer is the baseline, not a change from the cut ones.
    agent.answer, agent.refs, agent.cut = full_answer, list(FULL_REFS), False
    out = saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    assert out["changed"] is None
    assert _runs(db, ss)[-1].decided_by == "none"
    assert saved_search_service.to_dict(db, ss)["last_answer"] == full_answer
    assert _notes(db, pro) == []
    _seams.assert_not_called()

    out = saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    assert out["changed"] is False


def test_the_gate_holds_after_a_cut_and_run_now_still_asks(db, pro):
    """The cut run read a scope that had moved. Re-asking on every tick would spend
    a question to stop at the same budget, so cost keeps following ingest
    (S-8.3.3 stage 1)."""
    ss = _search(db, pro)
    agent = Agent()
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    _doc(db, pro.id, "A new source")
    _cut(agent)
    assert saved_search_service.execute(db, ss.id, trigger="schedule", agent=agent)["status"] == "ok"
    assert agent.calls == 2

    assert saved_search_service.execute(db, ss.id, trigger="schedule", agent=agent)["status"] == "no_new_sources"
    assert agent.calls == 2

    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    assert agent.calls == 3


def test_the_next_new_source_reopens_the_gate_after_a_cut(db, pro):
    """What the cut run could not compare waits for the next full answer."""
    ss = _search(db, pro)
    agent = Agent(refs=FULL_REFS)
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    full_answer = agent.answer
    _cut(agent)
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)

    _doc(db, pro.id, "A new source")
    agent.answer, agent.refs, agent.cut = full_answer, list(FULL_REFS), False
    out = saved_search_service.execute(db, ss.id, trigger="schedule", agent=agent)
    assert out["status"] == "ok"
    assert out["changed"] is False


def test_a_finished_run_is_stored_as_checked(db, pro):
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, trigger="manual", agent=Agent())
    assert db.get(LibraryQAExchange, _runs(db, ss)[-1].exchange_id).answer_cut_off is False


def test_the_runs_endpoint_says_a_run_was_cut(client, db, pro):
    ss = _search(db, pro)
    agent = Agent()
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)
    _cut(agent)
    saved_search_service.execute(db, ss.id, trigger="manual", agent=agent)

    newest, first = client.get(f"/api/v1/saved-searches/{ss.id}/runs").json()
    assert (newest["decided_by"], newest["changed"], newest["status"]) == ("cut_off", None, "ok")
    assert newest["exchange_id"]
    assert first["decided_by"] == "none"


def test_runs_endpoint_lists_newest_first_and_is_private(client, db, pro):
    ss = _search(db, pro)
    saved_search_service.execute(db, ss.id, agent=Agent())
    saved_search_service.execute(db, ss.id, agent=Agent())
    runs = client.get(f"/api/v1/saved-searches/{ss.id}/runs").json()
    assert [r["status"] for r in runs] == ["no_new_sources", "ok"]
    assert runs[1]["changed"] is None and runs[1]["added_reference_ids"] == []
    other = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    other.tier = "pro"
    db.commit()
    theirs = _search(db, other)
    assert client.get(f"/api/v1/saved-searches/{theirs.id}/runs").status_code == 404


def test_notifications_list_read_and_read_all_are_per_tenant(client, db, pro, unauthenticated_client):
    from app.services import notification_service

    a = notification_service.create(db, pro.id, kind="saved_search_changed", title="One", href="/saved-searches")
    notification_service.create(db, pro.id, kind="saved_search_changed", title="Two")
    other = auth_service.create_user(db, email="other@example.com", password="otherpass123")
    theirs = notification_service.create(db, other.id, kind="saved_search_changed", title="Theirs")
    data = client.get("/api/v1/notifications").json()
    assert data["unread"] == 2 and [n["title"] for n in data["items"]] == ["Two", "One"]
    assert client.patch(f"/api/v1/notifications/{a.id}", json={"read": True}).json()["read_at"]
    assert client.get("/api/v1/notifications").json()["unread"] == 1
    assert client.get("/api/v1/notifications", params={"unread_only": True}).json()["items"][0]["title"] == "Two"
    assert client.patch(f"/api/v1/notifications/{theirs.id}", json={"read": True}).status_code == 404
    assert client.post("/api/v1/notifications/read-all").json() == {"marked": 1}
    assert client.get("/api/v1/notifications").json()["unread"] == 0
    db.refresh(theirs)
    assert theirs.read_at is None
    assert unauthenticated_client.get("/api/v1/notifications").status_code == 401


# ---------------------------------------------------------------- registry


def test_the_judge_use_case_is_volume_tier_reasoning_off_and_not_a_gate():
    info = llm_routing.USE_CASE_REGISTRY["saved_search_judge"]
    volume = llm_routing.USE_CASE_REGISTRY["report_map_chunks"].default_config
    assert (info.default_config.provider, info.default_config.model) == (volume.provider, volume.model)
    assert info.default_config.reasoning == "off" and llm_routing.resolve_config("saved_search_judge").reasoning == "off"
    assert info.guidance.status == "unmeasured"
    assert info.typical_output_tokens < saved_search_change_service.JUDGE_MAX_TOKENS
    gated = {uc for ucs in llm_smoke.FEATURE_TO_USE_CASES.values() for uc in ucs}
    assert "saved_search_judge" not in gated
