"""D-068 / S-7.1.1 — trust-weighted re-rank in the Q&A agent.

The formula is pre-registered in D-068: retrieve 3 x top_k, drop anything
failing RAG_DISTANCE_THRESHOLD on the RAW distance, sort by distance / weight,
keep top_k; a weight of 0 is clamped to 0.05; a chunk with no channel weighs
1.0. These tests pin each clause, plus the one guarantee the design exists
for: a trusted but off-topic passage can never enter the answer.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.agents import qa_agent
from app.config import settings

TOP_K = settings.RAG_TOP_K


def _chunk(cid: str, channel: str | None, distance: float, title: str | None = None) -> dict:
    meta = {
        "document_id": f"doc-{cid}",
        "video_id": cid,
        "chunk_index": 0,
        "video_title": title or f"Video {cid}",
        "channel_name": channel or "",
        "timestamp_start": 0.0,
    }
    if channel:
        meta["channel_id"] = channel
    return {"text": f"text of {cid}", "metadata": meta, "distance": distance}


class _Pool:
    """Stands in for `chroma_service.query_collection`: returns the pool in
    distance order, honouring `n_results` and the threshold like the real one."""

    def __init__(self, pool: list[dict]):
        self.pool = sorted(pool, key=lambda r: r["distance"])
        self.calls: list[dict] = []

    def __call__(self, query_text, n_results=None, document_ids=None, distance_threshold=None):
        self.calls.append({"n_results": n_results, "document_ids": document_ids,
                           "distance_threshold": distance_threshold})
        if document_ids is not None and len(document_ids) == 0:
            return []
        hits = self.pool[: n_results or TOP_K]
        limit = distance_threshold if distance_threshold is not None else settings.RAG_DISTANCE_THRESHOLD
        return [h for h in hits if h["distance"] <= limit]


# ---------------------------------------------------------------------------
# _trust_weight
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("weights,channel,expected", [
    ({}, "UCa", 1.0),                       # no weights at all
    ({"UCa": 2.0}, None, 1.0),              # chunk without a channel (PDF, Reddit...)
    ({"UCa": 2.0}, "UCb", 1.0),             # channel the tenant never weighted
    ({"UCa": 1.5}, "UCa", 1.5),
    ({"UCa": 0.0}, "UCa", qa_agent.MIN_TRUST_WEIGHT),   # 0 sinks, never excludes
    ({"UCa": 9.0}, "UCa", qa_agent.MAX_TRUST_WEIGHT),   # out-of-range stored value
    ({"UCa": float("nan")}, "UCa", 1.0),
])
def test_trust_weight_resolution(weights, channel, expected):
    meta = {"channel_id": channel} if channel else {}
    assert qa_agent._trust_weight(meta, weights) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# _scoped_query — pool size, threshold, ordering, cap
# ---------------------------------------------------------------------------


def test_unweighted_query_is_unchanged_from_before_d068():
    """No weights (every tenant by default): one query for top_k, results
    returned exactly as Chroma ordered them."""
    pool = _Pool([_chunk(f"v{i}", "UCa", 0.1 + i * 0.01) for i in range(40)])
    with patch.object(qa_agent.chroma_service, "query_collection", side_effect=pool):
        out = qa_agent._scoped_query("q", ["d"], {})
        neutral = qa_agent._scoped_query("q", ["d"], {"UCa": 1.0})
    assert [c["n_results"] for c in pool.calls] == [TOP_K, TOP_K]
    assert [r["metadata"]["video_id"] for r in out] == [f"v{i}" for i in range(TOP_K)]
    assert [r["metadata"]["video_id"] for r in neutral] == [f"v{i}" for i in range(TOP_K)]


def test_weighted_query_draws_a_3x_pool_and_keeps_top_k_by_distance_over_weight():
    # 30 chunks from UCa at 0.10..0.39, then 15 from UCtrusted at 0.40..0.54.
    pool = _Pool(
        [_chunk(f"a{i}", "UCa", 0.10 + i * 0.01) for i in range(30)]
        + [_chunk(f"t{i}", "UCtrusted", 0.40 + i * 0.01) for i in range(15)]
    )
    with patch.object(qa_agent.chroma_service, "query_collection", side_effect=pool):
        out = qa_agent._scoped_query("q", ["d"], {"UCtrusted": 2.0})

    assert pool.calls[0]["n_results"] == TOP_K * qa_agent.TRUST_POOL_MULTIPLIER
    assert len(out) == TOP_K
    scores = [qa_agent._weighted_distance(r, {"UCtrusted": 2.0}) for r in out]
    assert scores == sorted(scores)
    # Weighted 0.40/2 = 0.20 beats UCa's raw 0.21+, so trusted chunks enter the
    # top_k that an unweighted query would have filled entirely with UCa.
    assert {r["metadata"]["channel_id"] for r in out} == {"UCa", "UCtrusted"}
    assert out[0]["metadata"]["video_id"] == "a0"  # 0.10 still beats 0.20


def test_zero_weight_sinks_a_channel_but_does_not_exclude_it():
    pool = _Pool([_chunk("distrusted", "UCbad", 0.05), _chunk("other", "UCa", 0.50)])
    with patch.object(qa_agent.chroma_service, "query_collection", side_effect=pool):
        out = qa_agent._scoped_query("q", ["d"], {"UCbad": 0.0})
    # 0.05 / 0.05 = 1.0 > 0.50: last, but still there when little else matches.
    assert [r["metadata"]["video_id"] for r in out] == ["other", "distrusted"]


def test_unchannelled_sources_weigh_one():
    pool = _Pool([_chunk("pdf", None, 0.30), _chunk("weighted", "UCa", 0.50)])
    with patch.object(qa_agent.chroma_service, "query_collection", side_effect=pool):
        out = qa_agent._scoped_query("q", ["d"], {"UCa": 2.0})
    # 0.50 / 2 = 0.25 < 0.30: the weighted channel passes the unweighted PDF.
    assert [r["metadata"]["video_id"] for r in out] == ["weighted", "pdf"]


def test_threshold_applies_to_raw_distance_even_if_the_store_returned_more():
    """The re-rank re-checks the raw threshold itself, so a pool that slipped
    an over-threshold chunk through (any caller, any store) still cannot
    promote it. 0.9 / 2.0 = 0.45 would beat 0.5 if weighting came first."""
    over = _chunk("offtopic", "UCtrusted", 0.90)
    within = _chunk("ontopic", "UCa", 0.50)
    loose = MagicMock(return_value=[within, over])
    with patch.object(qa_agent.chroma_service, "query_collection", loose):
        out = qa_agent._scoped_query("q", ["d"], {"UCtrusted": 2.0})
    assert [r["metadata"]["video_id"] for r in out] == ["ontopic"]


def test_empty_scope_still_retrieves_nothing_when_weighted():
    pool = _Pool([_chunk("x", "UCa", 0.1)])
    with patch.object(qa_agent.chroma_service, "query_collection", side_effect=pool):
        assert qa_agent._scoped_query("q", [], {"UCa": 2.0}) == []


# ---------------------------------------------------------------------------
# Both entry points use it
# ---------------------------------------------------------------------------


def _fake_llms(recorded: list[tuple[str, str]]):
    def factory(use_case, **_kw):
        llm = MagicMock()

        def invoke(messages):
            text = "\n".join(getattr(m, "content", str(m)) for m in messages) if isinstance(messages, list) else str(messages)
            recorded.append((use_case, text))
            resp = MagicMock()
            resp.content = {"qa_extract_references": "[]"}.get(use_case, "" if "sub_query" in use_case else "ok")
            resp.usage_metadata = None
            resp.response_metadata = {}
            return resp

        llm.invoke.side_effect = invoke
        return llm
    return factory


def _refine_prompt(recorded) -> str:
    return next(text for use_case, text in recorded if "refine_context" in use_case)


def test_job_qa_orders_context_by_the_weighted_score():
    pool = _Pool([_chunk("plain", "UCa", 0.30, "Plain video"), _chunk("trusted", "UCt", 0.40, "Trusted video")])
    for weights, first in (({}, "Plain video"), ({"UCt": 2.0}, "Trusted video")):
        recorded: list = []
        with patch.object(qa_agent.chroma_service, "query_collection", side_effect=pool), \
             patch.object(qa_agent, "get_llm_for", side_effect=_fake_llms(recorded)):
            qa_agent.run_qa_agent(job_id="j", job_type="channel", question="q",
                                  document_ids=["d"], channel_weights=weights)
        prompt = _refine_prompt(recorded)
        other = "Trusted video" if first == "Plain video" else "Plain video"
        assert prompt.index(first) < prompt.index(other), weights


def test_library_qa_orders_context_by_the_weighted_score():
    pool = _Pool([_chunk("plain", "UCa", 0.30, "Plain video"), _chunk("trusted", "UCt", 0.40, "Trusted video")])
    for weights, first in (({}, "Plain video"), ({"UCt": 2.0}, "Trusted video")):
        recorded: list = []
        with patch.object(qa_agent.chroma_service, "query_collection", side_effect=pool), \
             patch.object(qa_agent, "get_llm_for", side_effect=_fake_llms(recorded)):
            qa_agent.run_library_qa_agent(question="q", visible_document_ids=["d"],
                                          channel_weights=weights)
        prompt = _refine_prompt(recorded)
        other = "Trusted video" if first == "Plain video" else "Plain video"
        assert prompt.index(first) < prompt.index(other), weights


# ---------------------------------------------------------------------------
# The guarantee, against a real collection with real embeddings
# ---------------------------------------------------------------------------


@pytest.fixture
def ephemeral_chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    monkeypatch.setattr(chroma_service, "_client", chromadb.EphemeralClient())
    yield chroma_service
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


def _stored(doc: str, channel: str, title: str, text: str, idx: int = 0) -> dict:
    return {"text": text, "metadata": {
        "document_id": doc, "video_id": doc, "chunk_index": idx, "channel_id": channel,
        "video_title": title, "channel_name": channel, "timestamp_start": 0.0,
    }}


def test_a_trusted_off_topic_chunk_cannot_enter_the_answer(ephemeral_chroma):
    """A weight-2.0 channel's chunk that fails the raw relevance threshold
    must reach neither the context the answer is built from nor the list of
    sources the answer may cite."""
    chroma = ephemeral_chroma
    question = "How does DNS resolve a domain name to an IP address?"
    chroma.insert_chunks([
        _stored("doc-dns", "UCnet", "DNS explained",
                "DNS resolves a domain name to an IP address by querying recursive resolvers, "
                "root servers and authoritative name servers."),
        _stored("doc-bread", "UCtrusted", "Sourdough at home",
                "Feed the sourdough starter with rye flour, fold the dough every thirty minutes "
                "and bake it in a covered cast-iron pot."),
    ])

    # Preconditions, measured rather than assumed: the test means something
    # only if the off-topic chunk really fails the raw threshold.
    raw = {h["metadata"]["document_id"]: h["distance"] for h in chroma.query_collection(
        question, n_results=10, document_ids=["doc-dns", "doc-bread"], distance_threshold=float("inf"))}
    threshold = settings.RAG_DISTANCE_THRESHOLD
    assert raw["doc-dns"] <= threshold < raw["doc-bread"], raw

    recorded: list = []
    with patch.object(qa_agent, "get_llm_for", side_effect=_fake_llms(recorded)):
        qa_agent.run_library_qa_agent(
            question=question,
            visible_document_ids=["doc-dns", "doc-bread"],
            channel_weights={"UCtrusted": 2.0},
        )
    everything_sent = "\n".join(text for _uc, text in recorded)
    assert "DNS explained" in everything_sent
    assert "Sourdough" not in everything_sent and "rye flour" not in everything_sent
