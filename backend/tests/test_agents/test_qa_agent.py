"""Tests for the Q&A Agent (backend/app/agents/qa_agent.py).

Verifies retrieve_context's ChromaDB interaction, refine_context compaction,
formulate_answer, and extract_references ranking.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.agents import qa_agent


def _fake_llm_returning(payload: str) -> MagicMock:
    response = MagicMock()
    response.content = payload
    llm = MagicMock()
    llm.invoke.return_value = response
    return llm


def _rag_result(video_id: str, channel: str, title: str, text: str,
                ts_start: float = 0.0, distance: float = 0.1) -> dict:
    return {
        "text": text,
        "metadata": {
            "video_id": video_id,
            "video_title": title,
            "channel_name": channel,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "timestamp_start": ts_start,
        },
        "distance": distance,
    }


# ---------- retrieve_context ----------

def test_retrieve_context_queries_chroma_with_top_k():
    """retrieve_context delegates to chroma_service.query_collection with n_results=15.

    Multi-query expansion is mocked to return no extra sub-queries so only the
    original question is issued.
    """
    with patch.object(qa_agent.chroma_service, "query_collection") as mock_query, \
         patch.object(qa_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("")  # no sub-queries
        mock_query.return_value = [
            _rag_result("v1", "ChA", "Video 1", "chunk 1", ts_start=42.0),
        ]
        state = {
            "job_id": "job-abc",
            "job_type": "topic",
            "question": "what is quantum entanglement?",
            "report_html": None,
        }
        result = qa_agent.retrieve_context(state)

    mock_query.assert_called_once()
    # The third positional is n_results=15 by default for the QA agent
    call_kwargs = mock_query.call_args.kwargs
    call_args = mock_query.call_args.args
    # Signature: query_collection(job_id, query_text, n_results=...)
    assert call_args[0] == "job-abc"
    assert call_args[1] == "what is quantum entanglement?"
    assert call_kwargs.get("n_results") == 15

    # Results were enriched with timestamp_display + youtube_link
    rag = result["rag_results"]
    assert len(rag) == 1
    assert rag[0]["timestamp_display"] == "0:42"
    assert "v1" in rag[0]["youtube_link"]
    assert "t=42" in rag[0]["youtube_link"]


def test_retrieve_context_topic_job_extracts_report_text():
    """HTML tags/styles stripped; clean text is capped at REPORT_CONTEXT_CHAR_CAP."""
    html = """
        <html>
          <head><style>body { color: red; }</style></head>
          <body>
            <script>var x = 1;</script>
            <h1>Research Report</h1>
            <p>Important finding about quantum computing.</p>
          </body>
        </html>
    """
    with patch.object(qa_agent.chroma_service, "query_collection", return_value=[]), \
         patch.object(qa_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("")
        result = qa_agent.retrieve_context({
            "job_id": "j",
            "job_type": "topic",
            "question": "q",
            "report_html": html,
        })

    clean = result["report_context"]
    assert clean is not None
    assert "body { color" not in clean  # style removed
    assert "var x" not in clean  # script removed
    assert "<h1>" not in clean  # tags removed
    assert "Research Report" in clean
    assert "quantum computing" in clean


def test_retrieve_context_channel_job_skips_report_context():
    with patch.object(qa_agent.chroma_service, "query_collection", return_value=[]), \
         patch.object(qa_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("")
        result = qa_agent.retrieve_context({
            "job_id": "j",
            "job_type": "channel",
            "question": "q",
            "report_html": "<p>ignored</p>",
        })
    assert result["report_context"] is None


def test_retrieve_context_truncates_long_reports():
    # REPORT_CONTEXT_CHAR_CAP is 50000 (Unit 6 raised it from 15000).
    big_text = "word " * 20000  # 100000 chars >> 50000 cap
    html = f"<p>{big_text}</p>"
    with patch.object(qa_agent.chroma_service, "query_collection", return_value=[]), \
         patch.object(qa_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("")  # no sub-queries
        result = qa_agent.retrieve_context({
            "job_id": "j",
            "job_type": "topic",
            "question": "q",
            "report_html": html,
        })
    clean = result["report_context"]
    assert clean.endswith("...")
    # 50000 cap + len("...")
    assert len(clean) <= qa_agent.REPORT_CONTEXT_CHAR_CAP + 10


def test_retrieve_context_empty_chroma_results():
    with patch.object(qa_agent.chroma_service, "query_collection", return_value=[]), \
         patch.object(qa_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("")
        result = qa_agent.retrieve_context({
            "job_id": "j",
            "job_type": "topic",
            "question": "q",
            "report_html": None,
        })
    assert result["rag_results"] == []
    assert result["report_context"] is None


# ---------- refine_context ----------

def test_refine_context_formats_sources_and_calls_llm():
    rag = [
        _rag_result("v1", "ChA", "Video A", "text A", ts_start=30.0),
        _rag_result("v2", "ChB", "Video B", "text B", ts_start=60.0),
    ]
    # Mimic retrieve_context enrichment
    rag[0]["timestamp_display"] = "0:30"
    rag[0]["youtube_link"] = "https://www.youtube.com/watch?v=v1&t=30"
    rag[1]["timestamp_display"] = "1:00"
    rag[1]["youtube_link"] = "https://www.youtube.com/watch?v=v2&t=60"

    with patch.object(qa_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("Refined extract: A and B")
        state = {
            "question": "how?",
            "rag_results": rag,
            "report_context": None,
        }
        result = qa_agent.refine_context(state)

    assert result["refined_context"] == "Refined extract: A and B"
    llm_call = mock_get_llm.return_value.invoke.call_args
    # Prompt includes both chunks' titles/channels
    prompt_text = llm_call.args[0][0].content
    assert "Video A" in prompt_text
    assert "Video B" in prompt_text
    assert "ChA" in prompt_text
    assert "ChB" in prompt_text


def test_refine_context_includes_report_section():
    with patch.object(qa_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("compacted")
        state = {
            "question": "q",
            "rag_results": [],
            "report_context": "A research report body.",
        }
        qa_agent.refine_context(state)

    prompt_text = mock_get_llm.return_value.invoke.call_args.args[0][0].content
    assert "RESEARCH REPORT" in prompt_text
    assert "A research report body." in prompt_text


# ---------- formulate_answer ----------

def test_formulate_answer_uses_refined_context():
    with patch.object(qa_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("Here is the answer.")
        state = {
            "question": "how do qubits work?",
            "refined_context": "Qubits use superposition.",
        }
        result = qa_agent.formulate_answer(state)

    assert result["answer"] == "Here is the answer."
    # System + human messages passed
    messages = mock_get_llm.return_value.invoke.call_args.args[0]
    assert len(messages) == 2


def test_formulate_answer_with_no_context():
    with patch.object(qa_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("I don't know.")
        state = {"question": "q", "refined_context": ""}
        result = qa_agent.formulate_answer(state)
    assert result["answer"] == "I don't know."


# ---------- extract_references ----------

def test_extract_references_structures_citations():
    rag = [
        _rag_result("v1", "ChA", "Quantum Video", "chunk", ts_start=42.0),
        _rag_result("v2", "ChB", "Other Video", "chunk", ts_start=60.0),
    ]
    state = {
        "rag_results": rag,
        "answer": "Based on the Quantum Video, qubits are interesting.",
    }
    result = qa_agent.extract_references(state)

    refs = result["references"]
    assert len(refs) >= 1
    first = refs[0]
    assert first["video_url"].endswith("v=v1")
    assert first["timestamp_display"] == "0:42"
    assert "t=42" in first["youtube_link"]
    assert first["timestamp_seconds"] == 42.0


def test_extract_references_dedupes_same_video_timestamp():
    rag = [
        _rag_result("v1", "ChA", "Vid", "x", ts_start=30.0),
        _rag_result("v1", "ChA", "Vid", "y", ts_start=30.0),  # duplicate
        _rag_result("v1", "ChA", "Vid", "z", ts_start=60.0),  # different ts, keep
    ]
    # Answer must contain the video_id so the deterministic citation matcher
    # picks up the chunks (titles under 10 chars are ignored to avoid false
    # positives on generic titles).
    result = qa_agent.extract_references({"rag_results": rag, "answer": "see v1 for context"})

    keys = {(r["video_url"], r["timestamp_seconds"]) for r in result["references"]}
    assert len(keys) == len(result["references"])  # all unique
    # Expect 2 distinct timestamps
    assert len(result["references"]) == 2


def test_extract_references_caps_at_ten_inputs():
    rag = [
        _rag_result(f"v{i}", f"Ch{i}", f"Title {i}", "x", ts_start=float(i))
        for i in range(20)
    ]
    result = qa_agent.extract_references({"rag_results": rag, "answer": ""})
    # Only first 10 rag_results considered (dedup may reduce, but never exceed)
    assert len(result["references"]) <= 10


def test_extract_references_empty_rag():
    result = qa_agent.extract_references({"rag_results": [], "answer": ""})
    assert result["references"] == []


# ---------- run_qa_agent end-to-end ----------

def test_run_qa_agent_full_graph():
    rag = [
        _rag_result("v1", "ChA", "Video A", "some transcript text", ts_start=42.0),
    ]
    # Each get_llm_for() call returns a fresh fake LLM. The graph invokes get_llm_for
    # in this order: sub_query expansion -> refine_context -> formulate_answer.
    # extract_references uses the deterministic citation matcher when the
    # answer contains the video_id (no LLM call needed).
    fake_llms = [
        _fake_llm_returning(""),                    # sub-queries: none
        _fake_llm_returning("compacted context"),   # refine_context
        _fake_llm_returning("Answer referencing v1 / Video A"),  # formulate_answer
    ]
    with patch.object(qa_agent.chroma_service, "query_collection", return_value=rag), \
         patch.object(qa_agent, "get_llm_for", side_effect=fake_llms):
        answer, references = qa_agent.run_qa_agent(
            job_id="job-1",
            job_type="topic",
            question="tell me",
            report_html=None,
        )

    assert answer == "Answer referencing v1 / Video A"
    assert len(references) == 1
    assert references[0]["video_title"] == "Video A"


# ---------- _build_allowed_sources ----------

def test_build_allowed_sources_lists_unique_videos():
    rag = [
        _rag_result("v1", "ChA", "Title One", "x"),
        _rag_result("v1", "ChA", "Title One", "x"),  # duplicate
        _rag_result("v2", "ChB", "Title Two", "y"),
    ]
    out = qa_agent._build_allowed_sources(rag, include_report=False)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 2
    assert '"Title One" by ChA' in out
    assert '"Title Two" by ChB' in out
    assert "Research Report" not in out


def test_build_allowed_sources_includes_report_when_present():
    rag = [_rag_result("v1", "ChA", "Title One", "x")]
    out = qa_agent._build_allowed_sources(rag, include_report=True)
    assert "Research Report" in out


def test_build_allowed_sources_handles_empty():
    out = qa_agent._build_allowed_sources([], include_report=False)
    assert "no sources available" in out.lower()


# ---------- _sanitize_citations ----------

def test_sanitize_strips_fabricated_citation():
    rag = [_rag_result("v1", "Real Channel", "Real Title About Quantum", "x")]
    answer = (
        'Quantum stuff is interesting [Source: "Real Title About Quantum" by Real Channel at 0:42]. '
        'Other research [Source: "Made Up Paper" by Fake Lab at 1:00] disagrees.'
    )
    sanitized, removed = qa_agent._sanitize_citations(answer, rag)
    assert removed == 1
    assert '"Real Title About Quantum" by Real Channel' in sanitized
    assert "Made Up Paper" not in sanitized
    assert "[Source: unverified]" in sanitized


def test_sanitize_keeps_real_citation_with_rephrased_title():
    """LLM commonly drops leading numbers/parens — sanitizer must accept variants."""
    rag = [_rag_result("v1", "Milan J", "8 Pragmatic Tips (From Real Projects)", "x")]
    answer = '[Source: "Pragmatic Tips" by Milan J at 0:53] explains the pattern.'
    sanitized, removed = qa_agent._sanitize_citations(answer, rag)
    assert removed == 0
    assert "Pragmatic Tips" in sanitized


def test_sanitize_keeps_research_report_citations():
    rag = [_rag_result("v1", "ChA", "Real Title", "x")]
    answer = (
        'Per the report [Source: Research Report at 0:00] and the video '
        '[Source: "Real Title" by ChA at 0:42] the answer is yes.'
    )
    sanitized, removed = qa_agent._sanitize_citations(answer, rag)
    assert removed == 0
    assert "Research Report" in sanitized


def test_sanitize_no_op_when_all_citations_grounded():
    rag = [
        _rag_result("v1", "ChA", "Title One About Quantum Computing", "x"),
        _rag_result("v2", "ChB", "Title Two About Networking", "y"),
    ]
    answer = (
        '[Source: "Title One About Quantum Computing" by ChA at 0:00] and '
        '[Source: "Title Two About Networking" by ChB at 1:00].'
    )
    sanitized, removed = qa_agent._sanitize_citations(answer, rag)
    assert removed == 0
    assert sanitized == answer


def test_sanitize_handles_empty_answer():
    sanitized, removed = qa_agent._sanitize_citations("", [])
    assert sanitized == ""
    assert removed == 0


# ---------- extract_references with sanitizer ----------

def test_extract_references_returns_sanitized_answer():
    rag = [_rag_result("v1", "Real", "Real Topic Video", "x", ts_start=0.0)]
    answer = (
        'Real says [Source: "Real Topic Video" by Real at 0:00]. '
        'Fake says [Source: "Fake Video" by Fake Channel at 1:00].'
    )
    result = qa_agent.extract_references({"rag_results": rag, "answer": answer})
    # Sanitizer should have stripped the fabricated citation
    assert "Fake Video" not in result["answer"]
    assert "Real Topic Video" in result["answer"]
    assert len(result["references"]) == 1
    assert result["references"][0]["video_title"] == "Real Topic Video"


# ---------- formulate_answer passes allowed_sources ----------

def test_formulate_answer_injects_allowed_sources():
    rag = [_rag_result("v1", "ChA", "Real Video", "x")]
    with patch.object(qa_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("answer")
        qa_agent.formulate_answer({
            "question": "q",
            "refined_context": "ctx",
            "rag_results": rag,
            "report_context": None,
        })
    # Inspect the human message — it should include the allowed-sources list
    messages = mock_get_llm.return_value.invoke.call_args.args[0]
    human_text = messages[1].content
    assert '"Real Video" by ChA' in human_text
    assert "Allowed sources" in human_text


# ---------------------------------------------------------------------------
# Polymorphic _chunk_to_reference (S-1.5.5 backend reference enrichment)
# ---------------------------------------------------------------------------
# Per S-1.5.5, the frontend <CitationLink> dispatches its rendering on
# Reference.source_type. The backend extractor emits that discriminator
# per chunk so Reddit / HN citations render with their proper labels
# (r/sub · u/author · title) rather than falling through to YouTube.

def test_chunk_to_reference_video_default_path() -> None:
    """Legacy YouTube-only chunks (no source_type in metadata) keep
    rendering as before — back-compat for chunks indexed pre-S-1.5.5."""
    chunk = {
        "metadata": {
            "video_id": "abc123",
            "video_title": "Tariffs explained",
            "channel_name": "Some Channel",
            "video_url": "https://www.youtube.com/watch?v=abc123",
            "timestamp_start": 145.0,
        },
        "text": "snippet",
    }
    key, ref = qa_agent._chunk_to_reference(chunk)
    assert ref["source_type"] == "video"
    assert ref["video_title"] == "Tariffs explained"
    assert "youtube.com" in ref["youtube_link"]
    assert ref["timestamp_display"]  # non-empty
    assert key == "abc123_145"


def test_chunk_to_reference_reddit_renders_polymorphic() -> None:
    """Reddit chunks emit source_type='reddit_post', a permalink, and
    author + subreddit fields the frontend renders as
    'r/sub · u/author · title'."""
    chunk = {
        "metadata": {
            "source_type": "reddit_post",
            "source_id": "reddit:abc",
            "video_id": None,
            "title": "Why tariffs broke our supply chain",
            "permalink": "https://www.reddit.com/r/economics/comments/abc",
            "subreddit": "economics",
            "author": "supply_chain_pro",
            "timestamp_start": 0,
        },
        "text": "snippet",
    }
    key, ref = qa_agent._chunk_to_reference(chunk)
    assert ref["source_type"] == "reddit_post"
    assert ref["thread_title"] == "Why tariffs broke our supply chain"
    assert ref["subreddit"] == "economics"
    assert ref["author"] == "supply_chain_pro"
    assert ref["permalink"].startswith(
        "https://www.reddit.com/r/economics/comments/abc"
    )
    # Legacy YouTube-shaped fields still populated as fallback.
    assert ref["channel_name"] == "r/economics"


def test_chunk_to_reference_reddit_appends_comment_anchor_when_present() -> None:
    """When a chunk is from a specific reply (comment_id set), the
    permalink gains the #comment-<id> anchor so the citation opens
    at the right reply."""
    chunk = {
        "metadata": {
            "source_type": "reddit_post",
            "source_id": "reddit:abc",
            "title": "thread title",
            "permalink": "https://www.reddit.com/r/sub/comments/abc",
            "subreddit": "sub",
            "author": "user",
            "comment_id": "xyz789",
        },
        "text": "comment-level snippet",
    }
    _key, ref = qa_agent._chunk_to_reference(chunk)
    assert ref["permalink"].endswith("#comment-xyz789")


def test_chunk_to_reference_hn_renders_polymorphic() -> None:
    """HN chunks emit source_type='hn_story', a story-item permalink,
    and author so the frontend renders as 'HN · author · title'."""
    chunk = {
        "metadata": {
            "source_type": "hn_story",
            "source_id": "hn:42000",
            "title": "Caching strategies in production",
            "permalink": "https://news.ycombinator.com/item?id=42000",
            "author": "throwaway_dev",
        },
        "text": "snippet",
    }
    _key, ref = qa_agent._chunk_to_reference(chunk)
    assert ref["source_type"] == "hn_story"
    assert ref["thread_title"] == "Caching strategies in production"
    assert ref["author"] == "throwaway_dev"
    assert ref["permalink"] == "https://news.ycombinator.com/item?id=42000"
    # Legacy fallback fields populated.
    assert ref["channel_name"] == "throwaway_dev"


def test_chunk_to_reference_hn_comment_uses_comment_item_url() -> None:
    """For HN, per-comment URLs are separate item endpoints (not anchors).
    When comment_id is set, permalink points at that item directly."""
    chunk = {
        "metadata": {
            "source_type": "hn_story",
            "source_id": "hn:42000",
            "title": "Story title",
            "author": "op",
            "comment_id": 42100,
        },
        "text": "comment snippet",
    }
    _key, ref = qa_agent._chunk_to_reference(chunk)
    assert ref["permalink"] == "https://news.ycombinator.com/item?id=42100"


def test_chunk_to_reference_mastodon_renders_polymorphic() -> None:
    """Mastodon chunks emit source_type='mastodon_post', a permalink,
    and author + instance fields the frontend renders as
    '@author@instance · title'."""
    chunk = {
        "metadata": {
            "source_type": "mastodon_post",
            "source_id": "mastodon:111222",
            "title": "Federated identity reconsidered",
            "permalink": "https://mastodon.social/@privacynerd/111222",
            "author": "privacynerd",
            "instance": "mastodon.social",
        },
        "text": "status snippet",
    }
    _key, ref = qa_agent._chunk_to_reference(chunk)
    assert ref["source_type"] == "mastodon_post"
    assert ref["thread_title"] == "Federated identity reconsidered"
    assert ref["author"] == "privacynerd"
    assert ref["instance"] == "mastodon.social"
    assert ref["permalink"] == "https://mastodon.social/@privacynerd/111222"
    # Legacy fallback fields populated for back-compat with rendering
    # paths that haven't migrated to <CitationLink>.
    assert ref["channel_name"] == "privacynerd"


def test_chunk_to_reference_mastodon_uses_comment_url_when_present() -> None:
    """When a Mastodon chunk is from a specific reply (comment_id +
    comment_url), the citation permalink jumps to the reply's status
    URL rather than the OP's URL. This is the Mastodon analogue of
    Reddit's #comment-<id> anchor and HN's per-item endpoint."""
    chunk = {
        "metadata": {
            "source_type": "mastodon_post",
            "source_id": "mastodon:111222",
            "title": "Original post title",
            "permalink": "https://mastodon.social/@op/111222",
            "author": "op",
            "instance": "mastodon.social",
            "comment_id": "111333",
            "comment_url": "https://mastodon.social/@reply_user/111333",
        },
        "text": "reply snippet",
    }
    key, ref = qa_agent._chunk_to_reference(chunk)
    assert ref["permalink"] == "https://mastodon.social/@reply_user/111333"
    # Dedupe key includes comment_id so two cites from the same thread
    # but different replies stay distinct in the answer's reference set.
    assert key.endswith("_111333")


def test_chunk_to_reference_mastodon_falls_back_to_op_url_when_no_comment_url() -> None:
    """If the indexer wrote a comment_id but no separate comment_url
    (older data, or chunking hasn't been updated yet), the permalink
    stays on the OP — better than producing a broken link."""
    chunk = {
        "metadata": {
            "source_type": "mastodon_post",
            "source_id": "mastodon:111222",
            "title": "OP title",
            "permalink": "https://mastodon.social/@op/111222",
            "author": "op",
            "comment_id": "111333",
            # No comment_url.
        },
        "text": "snippet",
    }
    _key, ref = qa_agent._chunk_to_reference(chunk)
    assert ref["permalink"] == "https://mastodon.social/@op/111222"


def test_chunk_to_reference_bluesky_renders_polymorphic() -> None:
    """Bluesky chunks emit source_type='bluesky_post', a permalink,
    and author so the frontend renders as '@author · title'."""
    chunk = {
        "metadata": {
            "source_type": "bluesky_post",
            "source_id": "bluesky:at://did:plc:abc/app.bsky.feed.post/100",
            "title": "AT-Protocol design notes",
            "permalink": "https://bsky.app/profile/alice.bsky.social/post/100",
            "author": "alice.bsky.social",
        },
        "text": "post snippet",
    }
    _key, ref = qa_agent._chunk_to_reference(chunk)
    assert ref["source_type"] == "bluesky_post"
    assert ref["thread_title"] == "AT-Protocol design notes"
    assert ref["author"] == "alice.bsky.social"
    assert ref["permalink"] == (
        "https://bsky.app/profile/alice.bsky.social/post/100"
    )
    assert ref["channel_name"] == "alice.bsky.social"


def test_chunk_to_reference_bluesky_uses_comment_url_when_present() -> None:
    """When a Bluesky chunk is from a specific reply (comment_id +
    comment_url), the citation jumps to the reply's bsky.app URL
    rather than the OP's. Same shape as Mastodon."""
    chunk = {
        "metadata": {
            "source_type": "bluesky_post",
            "source_id": "bluesky:at://did:plc:abc/app.bsky.feed.post/100",
            "title": "Original post title",
            "permalink": "https://bsky.app/profile/op.bsky.social/post/100",
            "author": "op.bsky.social",
            "comment_id": "at://did:plc:bob/app.bsky.feed.post/r1",
            "comment_url": "https://bsky.app/profile/bob.bsky.social/post/r1",
        },
        "text": "reply snippet",
    }
    key, ref = qa_agent._chunk_to_reference(chunk)
    assert ref["permalink"] == "https://bsky.app/profile/bob.bsky.social/post/r1"
    # Dedupe key includes comment_id.
    assert key.endswith("at://did:plc:bob/app.bsky.feed.post/r1")


def test_chunk_to_reference_bluesky_falls_back_to_op_url_when_no_comment_url() -> None:
    """If the indexer wrote a comment_id but no comment_url (older
    data, or chunking hasn't been updated yet), the permalink stays
    on the OP — better than producing a broken link."""
    chunk = {
        "metadata": {
            "source_type": "bluesky_post",
            "source_id": "bluesky:at://did:plc:abc/app.bsky.feed.post/100",
            "title": "OP title",
            "permalink": "https://bsky.app/profile/op.bsky.social/post/100",
            "author": "op.bsky.social",
            "comment_id": "at://did:plc:bob/app.bsky.feed.post/r1",
            # No comment_url.
        },
        "text": "snippet",
    }
    _key, ref = qa_agent._chunk_to_reference(chunk)
    assert ref["permalink"] == "https://bsky.app/profile/op.bsky.social/post/100"


def test_chunk_to_reference_unknown_source_type_falls_through_to_video() -> None:
    """Defensive fallback — unrecognized source_type renders via the
    YouTube path so we don't hard-fail on a future-source-type chunk
    that happens to land in the index before the renderer is updated."""
    chunk = {
        "metadata": {
            "source_type": "future_unknown_type",
            "video_id": "xyz",
            "video_title": "Some title",
            "channel_name": "Whatever",
            "timestamp_start": 30.0,
        },
        "text": "snippet",
    }
    _key, ref = qa_agent._chunk_to_reference(chunk)
    assert ref["source_type"] == "video"  # falls through
