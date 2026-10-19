"""S-8.4.1: question suggestions — service and ``/suggestions``.

The generator is patched at ``get_llm_for`` (the factory the service
imports) and the embedder at the service's ``_encode`` seam, so no test
calls a provider or loads the sentence-transformer. One test runs the
history pool against a real in-memory Chroma to pin tenant isolation.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.qa_exchange import QAExchange
from app.models.quota_usage import QuotaUsage
from app.models.suggestion_cache import SuggestionCache
from app.services import auth_service, llm_routing, llm_smoke, suggestion_service, visibility_service

URL = "/api/v1/suggestions"

GENERATED = [
    {"question": "How do tariffs change consumer prices over time?", "rationale": "Ties policy to prices."},
    {"question": "Which industries gained jobs after the steel tariffs?", "rationale": "Winners."},
    {"question": "What did economists predict about retaliation from China?", "rationale": "Forecasts."},
    {"question": "How do tariffs change consumer prices over the years?", "rationale": "Near duplicate."},
    {"question": "Why did the dollar strengthen during the trade war?", "rationale": "Currency."},
    {"question": "What did farmers receive in bailout payments?", "rationale": "Costs."},
]


class FakeLLM:
    def __init__(self, items=None, fail: bool = False):
        self.items = GENERATED if items is None else items
        self.fail = fail
        self.prompts: list[str] = []

    def invoke(self, messages):
        self.prompts.append(messages[0].content)
        if self.fail:
            raise RuntimeError("provider down")
        return AIMessage(
            content=json.dumps({"suggestions": self.items}),
            usage_metadata={"input_tokens": 1200, "output_tokens": 160, "total_tokens": 1360},
        )


def fake_encode(texts):
    """Bag of words hashed into 64 dims: shared words → similar vectors."""
    out = []
    for t in texts:
        v = [0.0] * 64
        for w in t.lower().replace("?", "").replace(",", "").split():
            if len(w) > 3:
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
        out.append(v)
    return out


@pytest.fixture(autouse=True)
def _cheap_embedder(monkeypatch):
    monkeypatch.setattr(suggestion_service, "_encode", fake_encode)
    monkeypatch.setattr(suggestion_service.chroma_service, "query_qa_collection", lambda *a, **k: [])


def _job(db, user_id, *, status="completed", topic="US tariffs and trade") -> Job:
    job = Job(job_type="topic", topic=topic, status=status, num_videos=2, tenant_id=user_id,
              completed_at=datetime.now(timezone.utc) if status == "completed" else None)
    db.add(job)
    db.commit()
    for i, (title, topics) in enumerate([
        ("Steel tariffs explained", ["Steel tariffs", "Consumer prices"]),
        ("Trade war with China", ["Retaliation", "Farm bailouts"]),
    ]):
        doc = Document(
            video_id=f"tar{i}{uuid.uuid4().hex[:7]}",
            title=title,
            url="https://example.com",
            transcript_status="completed",
            extracted_knowledge_json=json.dumps({"topics": [{"name": t} for t in topics]}),
        )
        db.add(doc)
        db.commit()
        db.add(JobVideo(job_id=job.id, document_id=doc.document_id, video_id=doc.video_id, approved=True))
        visibility_service.grant(db, [doc.document_id], user_id, "job")
    db.commit()
    return job


def _ask(db, job, user_id, question):
    row = QAExchange(job_id=job.id, tenant_id=user_id, question=question, answer="…", references="[]")
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------- context


def test_parse_context():
    assert suggestion_service.parse_context("library") == ("library", None)
    assert suggestion_service.parse_context(" job:abc ") == ("job", "abc")
    assert suggestion_service.parse_context("document:d1") == ("document", "d1")
    for bad in ("", "job:", "jobs:1", "shelf:1", "library:x"):
        with pytest.raises(suggestion_service.ContextError):
            suggestion_service.parse_context(bad)


def test_prompt_carries_the_summary_the_asked_questions_and_the_english_contract(db, test_user):
    job = _job(db, test_user.id)
    _ask(db, job, test_user.id, "What is a tariff?")
    ctx = suggestion_service.resolve_context(db, test_user, f"job:{job.id}")
    prompt = suggestion_service.build_prompt(ctx)
    assert "US tariffs and trade" in prompt
    assert "Steel tariffs" in prompt and "Trade war with China" in prompt
    assert "- What is a tariff?" in prompt
    assert "LANGUAGE OF OUTPUT" in prompt


def test_a_channel_run_is_described_by_its_channels(db, test_user):
    job = Job(job_type="channel", channel_list=json.dumps(["@3blue1brown", "@veritasium"]), status="completed",
              num_videos=5, tenant_id=test_user.id)
    db.add(job)
    db.commit()
    ctx = suggestion_service.resolve_context(db, test_user, f"job:{job.id}")
    assert "Channels: @3blue1brown, @veritasium" in suggestion_service.build_prompt(ctx)


# ------------------------------------------------------------- pools/MMR


def test_no_history_returns_generated_only_deduped_and_capped(db, test_user):
    job = _job(db, test_user.id)
    fake = FakeLLM()
    with patch.object(suggestion_service, "get_llm_for", return_value=fake) as factory:
        out = suggestion_service.suggestions_for(db, test_user, f"job:{job.id}")
    assert factory.call_args.args[0] == "qa_suggest_questions"
    qs = [s["question"] for s in out["suggestions"]]
    assert len(qs) == 5 and {s["source"] for s in out["suggestions"]} == {"generated"}
    # the near-duplicate of the first question is dropped, not shown twice
    assert not ({GENERATED[0]["question"], GENERATED[3]["question"]} <= set(qs))
    assert out["generated"] is True and out["cached"] is False


def test_history_merges_skips_this_run_and_repeats_of_what_was_asked(db, test_user, monkeypatch):
    job = _job(db, test_user.id)
    _ask(db, job, test_user.id, "Why did the dollar strengthen during the trade war?")
    hits = [
        {"text": "Q: How did soybean exports to China collapse?\n\nA: …", "metadata": {"source": "job", "job_id": "other", "exchange_id": "x1"}},
        {"text": "Q: Asked on this very run?\n\nA: …", "metadata": {"source": "job", "job_id": job.id, "exchange_id": "x2"}},
    ]
    seen = {}

    def query(text, top_k=None, where=None, tenant_id=None):
        seen["tenant_id"] = tenant_id
        return hits

    monkeypatch.setattr(suggestion_service.chroma_service, "query_qa_collection", query)
    with patch.object(suggestion_service, "get_llm_for", return_value=FakeLLM()):
        out = suggestion_service.suggestions_for(db, test_user, f"job:{job.id}")
    assert seen["tenant_id"] == test_user.id  # never an unscoped query
    qs = [s["question"] for s in out["suggestions"]]
    assert "Asked on this very run?" not in qs
    assert "Why did the dollar strengthen during the trade war?" not in qs  # already asked here
    history = [s for s in out["suggestions"] if s["source"] == "history"]
    assert [h["question"] for h in history] == ["How did soybean exports to China collapse?"]
    assert history[0]["origin"] == {"source": "job", "exchange_id": "x1", "job_id": "other"}


def test_mmr_spreads_subjects_before_repeating_one():
    def enc(texts):
        # query first, then candidates: three subjects, the first one thrice
        basis = {"a": [1, 0, 0], "b": [0, 1, 0], "c": [0, 0, 1]}
        out = [[1, 1, 1]]
        for t in texts[1:]:
            v = basis[t[0]]
            out.append([x + 0.05 * int(t[1]) for x in v])
        return out

    cands = [suggestion_service.Candidate(q, "", "generated") for q in ("a1", "a2", "a3", "b1", "c1")]
    # a2/a3 are near-duplicates of a1 under this encoder, so dedupe keeps one "a"
    picked = suggestion_service.select(cands, query_text="q", asked=[], k=3, encode=enc)
    assert sorted(c.question[0] for c in picked) == ["a", "b", "c"]


# ------------------------------------------------------------------ cache


def test_cache_hit_makes_no_model_call_and_a_new_exchange_invalidates(db, test_user):
    job = _job(db, test_user.id)
    fake = FakeLLM()
    with patch.object(suggestion_service, "get_llm_for", return_value=fake):
        first = suggestion_service.suggestions_for(db, test_user, f"job:{job.id}")
        second = suggestion_service.suggestions_for(db, test_user, f"job:{job.id}")
        assert len(fake.prompts) == 1
        assert second["cached"] is True and second["suggestions"] == first["suggestions"]
        _ask(db, job, test_user.id, "A new question")
        third = suggestion_service.suggestions_for(db, test_user, f"job:{job.id}")
    assert len(fake.prompts) == 2 and third["cached"] is False
    assert db.query(SuggestionCache).filter_by(tenant_id=test_user.id).count() == 1


def test_cache_expires_after_the_window(db, test_user):
    job = _job(db, test_user.id)
    fake = FakeLLM()
    now = datetime.now(timezone.utc)
    with patch.object(suggestion_service, "get_llm_for", return_value=fake):
        suggestion_service.suggestions_for(db, test_user, f"job:{job.id}", now=now)
        later = now + timedelta(minutes=suggestion_service.settings.SUGGESTIONS_CACHE_TTL_MIN + 1)
        out = suggestion_service.suggestions_for(db, test_user, f"job:{job.id}", now=later)
    assert out["cached"] is False and len(fake.prompts) == 2


def test_a_failed_generator_degrades_to_history_and_is_not_cached(db, test_user, monkeypatch):
    job = _job(db, test_user.id)
    monkeypatch.setattr(
        suggestion_service.chroma_service,
        "query_qa_collection",
        lambda *a, **k: [{"text": "Q: How did soybean exports collapse?\n\nA: …", "metadata": {"source": "library"}}],
    )
    fake = FakeLLM(fail=True)
    with patch.object(suggestion_service, "get_llm_for", return_value=fake):
        out = suggestion_service.suggestions_for(db, test_user, f"job:{job.id}")
        again = suggestion_service.suggestions_for(db, test_user, f"job:{job.id}")
    assert out["generated"] is False and [s["source"] for s in out["suggestions"]] == ["history"]
    assert again["cached"] is False and len(fake.prompts) == 2
    assert db.query(SuggestionCache).count() == 0


def test_generator_unavailable_skips_the_model(db, test_user):
    job = _job(db, test_user.id)
    with patch.object(suggestion_service, "get_llm_for") as factory:
        out = suggestion_service.suggestions_for(db, test_user, f"job:{job.id}", generator_available=False)
    factory.assert_not_called()
    assert out["generated"] is False


def test_generation_is_metered_under_the_daily_token_keys(db, test_user):
    job = _job(db, test_user.id)
    with patch.object(suggestion_service, "get_llm_for", return_value=FakeLLM()):
        suggestion_service.suggestions_for(db, test_user, f"job:{job.id}")
    rows = {r.resource: r.consumed for r in db.query(QuotaUsage).filter_by(user_id=test_user.id)}
    assert rows.get("llm_tokens_in") == 1200 and rows.get("llm_tokens_out") == 160


# ---------------------------------------------------------------- isolation


def test_history_pool_never_returns_another_tenants_questions(db, test_user, monkeypatch):
    """Real in-memory Chroma: two tenants ask near-identical questions."""
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    monkeypatch.undo()  # restore the real query_qa_collection
    monkeypatch.setattr(suggestion_service, "_encode", fake_encode)
    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    try:
        other = auth_service.create_user(db, email="neighbour@example.com", password="otherpass123")
        mine = _job(db, test_user.id)
        theirs = _job(db, other.id)
        _ask(db, theirs, other.id, "What did tariffs on steel do to car prices?")
        for row in db.query(QAExchange).all():
            chroma_service.upsert_qa_exchange(row, source="job")
        ctx = suggestion_service.resolve_context(db, test_user, f"job:{mine.id}")
        assert suggestion_service.history_pool(ctx, test_user.id) == []
        ctx_other = suggestion_service.resolve_context(db, other, f"job:{theirs.id}")
        # their own question on their own run is excluded as "this context", so
        # look from a second run of theirs: it is found for them
        second = _job(db, other.id, topic="Steel and cars")
        ctx_other = suggestion_service.resolve_context(db, other, f"job:{second.id}")
        found = [c.question for c in suggestion_service.history_pool(ctx_other, other.id)]
        assert "What did tariffs on steel do to car prices?" in found
    finally:
        monkeypatch.setattr(chroma_service, "_client", None)
        SharedSystemClient._identifier_to_system = {}


# ------------------------------------------------------------------ router


def test_router_contexts_and_errors(client, db, test_user):
    job = _job(db, test_user.id)
    pending = _job(db, test_user.id, status="extracting")
    foreign = _job(db, "someone-else")
    with patch.object(suggestion_service, "get_llm_for", return_value=FakeLLM()):
        ok = client.get(URL, params={"context": f"job:{job.id}"})
        assert ok.status_code == 200, ok.text
        assert len(ok.json()["suggestions"]) == 5
        assert client.get(URL, params={"context": "job:"}).status_code == 422
        assert client.get(URL, params={"context": f"job:{foreign.id}"}).status_code == 404
        assert client.get(URL, params={"context": f"job:{pending.id}"}).status_code == 400
        assert client.get(URL, params={"context": "document:nope"}).status_code == 404
        doc = db.query(JobVideo).filter_by(job_id=job.id).first()
        assert client.get(URL, params={"context": f"document:{doc.document_id}"}).status_code == 200
        lib = client.get(URL, params={"context": "library"})
        assert lib.status_code == 200 and lib.json()["context"] == "library"
    shown = db.query(AuditLog).filter_by(user_id=test_user.id, event="suggestion_shown").all()
    assert len(shown) == 3
    assert json.loads(shown[0].metadata_json)["count"] == 5


def test_router_turns_the_generator_off_when_its_probe_failed(client, db, test_user, monkeypatch):
    job = _job(db, test_user.id)
    monkeypatch.setattr(llm_smoke._STATUS, "is_use_case_available", lambda uc: uc != "qa_suggest_questions")
    with patch.object(suggestion_service, "get_llm_for") as factory:
        r = client.get(URL, params={"context": f"job:{job.id}"})
    assert r.status_code == 200 and r.json()["generated"] is False
    factory.assert_not_called()


def test_feedback_records_clicks_for_your_own_contexts_only(client, db, test_user):
    job = _job(db, test_user.id)
    foreign = _job(db, "someone-else")
    body = {"context": f"job:{job.id}", "question": "Why?", "action": "ask", "source": "generated"}
    assert client.post(f"{URL}/feedback", json=body).status_code == 204
    row = db.query(AuditLog).filter_by(user_id=test_user.id, event="suggestion_clicked").one()
    assert json.loads(row.metadata_json) == {"context": f"job:{job.id}", "action": "ask", "source": "generated", "question": "Why?"}
    assert client.post(f"{URL}/feedback", json={**body, "context": f"job:{foreign.id}"}).status_code == 404
    assert client.post(f"{URL}/feedback", json={**body, "extra": 1}).status_code == 422
    assert client.post(f"{URL}/feedback", json={**body, "action": "hover"}).status_code == 422


def test_requires_auth(unauthenticated_client):
    assert unauthenticated_client.get(URL, params={"context": "library"}).status_code == 401
    assert unauthenticated_client.post(f"{URL}/feedback", json={}).status_code == 401


# ---------------------------------------------------------------- registry


def test_use_case_is_registered_on_the_volume_tier_with_reasoning_off():
    info = llm_routing.USE_CASE_REGISTRY["qa_suggest_questions"]
    volume = llm_routing.USE_CASE_REGISTRY["report_map_chunks"].default_config
    assert info.default_config.reasoning == "off"
    assert (info.default_config.provider, info.default_config.model) == (volume.provider, volume.model)
    assert llm_routing.resolve_config("qa_suggest_questions").reasoning == "off"
    assert info.guidance.status == "unmeasured" and info.guidance.note
    assert info.typical_output_tokens < suggestion_service.MAX_COMPLETION_TOKENS
    # fail-soft: probed, but not a feature gate (like temporal_scope_extract)
    gated = {uc for ucs in llm_smoke.FEATURE_TO_USE_CASES.values() for uc in ucs}
    assert "qa_suggest_questions" not in gated
