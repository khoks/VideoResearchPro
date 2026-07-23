"""Tests for the Search Agent (backend/app/agents/search_agent.py).

These tests mock `get_llm_for` to produce canned responses and mock the YouTube
service so the agent runs offline against real LangGraph code paths.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents import search_agent


def _fake_llm_returning(payload: str) -> MagicMock:
    """Build a ChatOpenAI-like mock whose .invoke returns an AIMessage-shaped object."""
    response = MagicMock()
    response.content = payload
    llm = MagicMock()
    llm.invoke.return_value = response
    return llm


@pytest.fixture
def fake_videos():
    return [
        {"video_id": "v1", "title": "Quantum 101", "channel_name": "ChA",
         "channel_id": "UC1", "thumbnail_url": None, "duration_seconds": 600},
        {"video_id": "v2", "title": "Quantum Deep Dive", "channel_name": "ChB",
         "channel_id": "UC2", "thumbnail_url": None, "duration_seconds": 1800},
        {"video_id": "v3", "title": "Advanced Qubits", "channel_name": "ChC",
         "channel_id": "UC3", "thumbnail_url": None, "duration_seconds": 3600},
    ]


def _plan_payload(queries: list[str], keywords: list[str] | None = None) -> str:
    """Return a JSON plan payload matching the new PLAN_SEARCHES_PROMPT schema."""
    return json.dumps({"broad_queries": queries, "channel_keywords": keywords or []})


def test_plan_searches_parses_json_object():
    with patch.object(search_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning(
            _plan_payload(
                ["quantum computing intro", "qubit tutorial", "quantum gates"],
                ["quantum", "qubit"],
            )
        )
        state = {
            "topic": "quantum computing",
            "search_instructions": "",
            "channel_type_filters": [],
            "preferred_channel_ids": [],
        }
        result = search_agent.plan_searches(state)

    assert result["search_queries_used"] == [
        "quantum computing intro",
        "qubit tutorial",
        "quantum gates",
    ]
    assert result["channel_keywords"] == ["quantum", "qubit"]
    assert len(result["messages"]) == 1


def test_plan_searches_falls_back_on_bad_json():
    with patch.object(search_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("not valid json!!")
        state = {
            "topic": "physics",
            "search_instructions": "",
            "channel_type_filters": [],
            "preferred_channel_ids": [],
        }
        result = search_agent.plan_searches(state)

    # Falls back to the topic as a single broad query.
    assert result["search_queries_used"] == ["physics"]
    assert result["channel_keywords"] == []


def test_plan_searches_falls_back_when_not_an_object():
    """LLM returned a list (old format) or anything that isn't a dict — we
    cannot trust it, so we fall back to the topic."""
    with patch.object(search_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning('["physics"]')
        state = {
            "topic": "physics",
            "search_instructions": "",
            "channel_type_filters": [],
            "preferred_channel_ids": [],
        }
        result = search_agent.plan_searches(state)

    assert result["search_queries_used"] == ["physics"]


def test_plan_searches_generates_fallback_keywords_when_channels_present():
    """If preferred channels are supplied but the LLM forgot to include
    channel_keywords, we synthesize them from the topic so the keyword
    filter is never empty."""
    with patch.object(search_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning(
            json.dumps({"broad_queries": ["quantum intro"], "channel_keywords": []})
        )
        state = {
            "topic": "quantum computing fundamentals",
            "search_instructions": "",
            "channel_type_filters": [],
            "preferred_channel_ids": ["UC123"],
        }
        result = search_agent.plan_searches(state)

    assert result["search_queries_used"] == ["quantum intro"]
    # Synthesized from topic tokens (>2 chars).
    assert set(result["channel_keywords"]) == {"quantum", "computing", "fundamentals"}


def test_resolve_preferred_channels_dedupes_and_skips_failures():
    with patch.object(search_agent.youtube_service, "resolve_channel_id") as mock_resolve:
        mock_resolve.side_effect = ["UC1", "UC1", None, "UC2"]
        result = search_agent.resolve_preferred_channels(
            {"preferred_channels": ["@a", "@aDup", "@bogus", "@b"]}
        )
    assert result["preferred_channel_ids"] == ["UC1", "UC2"]


def test_resolve_preferred_channels_empty_input_skips_api():
    with patch.object(search_agent.youtube_service, "resolve_channel_id") as mock_resolve:
        result = search_agent.resolve_preferred_channels(
            {"preferred_channels": []}
        )
    assert result["preferred_channel_ids"] == []
    mock_resolve.assert_not_called()


def test_execute_searches_calls_youtube_service_with_expected_queries(fake_videos):
    queries = ["q one", "q two"]
    with patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details, \
         patch.object(search_agent.youtube_service, "get_channel_subscribers", return_value={}):
        mock_search.return_value = fake_videos[:2]
        mock_details.return_value = {
            v["video_id"]: {"duration_seconds": v["duration_seconds"]}
            for v in fake_videos[:2]
        }

        state = {
            "topic": "quantum",
            "search_queries_used": queries,
            "num_videos": 5,
            "min_duration": None,
            "max_duration": None,
            "preferred_channel_ids": [],
            "channel_keywords": [],
        }
        result = search_agent.execute_searches(state)

    # search_videos was called for each query
    assert mock_search.call_count == 2
    actual_queries = [c.kwargs.get("query") or c.args[0] for c in mock_search.call_args_list]
    assert actual_queries == queries
    # Videos returned and enriched
    assert len(result["discovered_videos"]) == 2
    # All are tagged as search-sourced.
    assert all(v["source"] == "search" for v in result["discovered_videos"])


def test_execute_searches_filters_videos_above_min_duration(fake_videos):
    """min_duration in minutes excludes videos under that length (post-fetch filter)."""
    with patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details, \
         patch.object(search_agent.youtube_service, "get_channel_subscribers", return_value={}):
        mock_search.return_value = fake_videos
        mock_details.return_value = {
            v["video_id"]: {"duration_seconds": v["duration_seconds"]} for v in fake_videos
        }

        state = {
            "topic": "quantum",
            "search_queries_used": ["q1"],
            "num_videos": 5,
            "min_duration": 30,  # 30 minutes
            "max_duration": None,
            "preferred_channel_ids": [],
            "channel_keywords": [],
        }
        result = search_agent.execute_searches(state)

    # v1=10min, v2=30min, v3=60min — only v2 and v3 are >= 30 min
    kept_ids = {v["video_id"] for v in result["discovered_videos"]}
    assert kept_ids == {"v2", "v3"}


def test_execute_searches_filters_videos_under_max_duration(fake_videos):
    """max_duration in minutes excludes videos longer than that bound."""
    with patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details, \
         patch.object(search_agent.youtube_service, "get_channel_subscribers", return_value={}):
        mock_search.return_value = fake_videos
        mock_details.return_value = {
            v["video_id"]: {"duration_seconds": v["duration_seconds"]} for v in fake_videos
        }

        state = {
            "topic": "t",
            "search_queries_used": ["q1"],
            "num_videos": 5,
            "min_duration": None,
            "max_duration": 15,  # 15 minutes — only v1 (10min) qualifies
            "preferred_channel_ids": [],
            "channel_keywords": [],
        }
        result = search_agent.execute_searches(state)

    kept_ids = {v["video_id"] for v in result["discovered_videos"]}
    assert kept_ids == {"v1"}


def test_execute_searches_filters_by_duration_minutes(fake_videos):
    """After enrichment, videos outside the min/max minute range are dropped."""
    with patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details, \
         patch.object(search_agent.youtube_service, "get_channel_subscribers", return_value={}):
        mock_search.return_value = fake_videos
        mock_details.return_value = {
            v["video_id"]: {"duration_seconds": v["duration_seconds"]} for v in fake_videos
        }

        state = {
            "topic": "t",
            "search_queries_used": ["q"],
            "num_videos": 5,
            "min_duration": 15,  # >= 15 minutes only
            "max_duration": 45,  # <= 45 minutes
            "preferred_channel_ids": [],
            "channel_keywords": [],
        }
        result = search_agent.execute_searches(state)

    kept = [v["video_id"] for v in result["discovered_videos"]]
    # v1 is 10min (excluded), v2 is 30min (kept), v3 is 60min (excluded)
    assert kept == ["v2"]


def test_execute_searches_dedupes_across_queries(fake_videos):
    with patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details, \
         patch.object(search_agent.youtube_service, "get_channel_subscribers", return_value={}):
        # Same videos returned twice — should be deduped
        mock_search.return_value = fake_videos[:2]
        mock_details.return_value = {
            v["video_id"]: {"duration_seconds": v["duration_seconds"]}
            for v in fake_videos[:2]
        }

        state = {
            "topic": "t",
            "search_queries_used": ["q1", "q2"],
            "num_videos": 5,
            "min_duration": None,
            "max_duration": None,
            "preferred_channel_ids": [],
            "channel_keywords": [],
        }
        result = search_agent.execute_searches(state)

    assert len(result["discovered_videos"]) == 2


def test_execute_searches_merges_preferred_channel_uploads(fake_videos):
    """Preferred channels contribute uploads via playlist walk, tagged source=preferred_channel."""
    broad = [fake_videos[0]]  # v1 from broad search

    # Preferred channel UCX returns v2 and v3 as recent uploads.
    preferred_uploads = [fake_videos[1]["video_id"], fake_videos[2]["video_id"]]

    with patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_channel_videos", return_value=preferred_uploads), \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details, \
         patch.object(search_agent.youtube_service, "get_channel_subscribers", return_value={}):
        mock_search.return_value = broad

        # get_video_details is called twice: once for preferred uploads, once for broad enrichment.
        # Accepts **_ so the connector's `job_id=""` kwarg passes through.
        def _details_side_effect(ids, **_):
            return {
                v["video_id"]: {
                    "video_id": v["video_id"],
                    "title": v["title"],
                    "channel_name": v["channel_name"],
                    "channel_id": v["channel_id"],
                    "duration_seconds": v["duration_seconds"],
                    "published_at": "2024-01-01T00:00:00Z",
                }
                for v in fake_videos
                if v["video_id"] in ids
            }

        mock_details.side_effect = _details_side_effect

        state = {
            "topic": "quantum",
            "search_queries_used": ["quantum intro"],
            "num_videos": 5,
            "min_duration": None,
            "max_duration": None,
            "preferred_channel_ids": ["UCX"],
            # Both "quantum" and "qubits" match fake_videos titles.
            "channel_keywords": ["quantum", "qubits"],
        }
        result = search_agent.execute_searches(state)

    by_id = {v["video_id"]: v for v in result["discovered_videos"]}
    assert set(by_id) == {"v1", "v2", "v3"}
    assert by_id["v1"]["source"] == "search"
    assert by_id["v2"]["source"] == "preferred_channel"
    assert by_id["v3"]["source"] == "preferred_channel"


def test_rank_and_curate_returns_all_when_below_target(fake_videos):
    """Short-circuit: no LLM call if candidate count <= target."""
    with patch.object(search_agent, "get_llm_for") as mock_get_llm:
        state = {
            "topic": "t",
            "discovered_videos": fake_videos,
            "num_videos": 5,
            "search_instructions": "",
        }
        result = search_agent.rank_and_curate(state)

    assert result["curated_videos"] == fake_videos
    mock_get_llm.assert_not_called()


def test_rank_and_curate_llm_selects_ids(fake_videos):
    with patch.object(search_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning('["v3", "v1"]')
        state = {
            "topic": "t",
            "discovered_videos": fake_videos,
            "num_videos": 2,
            "search_instructions": "",
        }
        result = search_agent.rank_and_curate(state)

    curated_ids = [v["video_id"] for v in result["curated_videos"]]
    assert set(curated_ids) == {"v1", "v3"}
    assert len(curated_ids) == 2


def test_rank_and_curate_falls_back_on_bad_json(fake_videos):
    with patch.object(search_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("nonsense")
        state = {
            "topic": "t",
            "discovered_videos": fake_videos,
            "num_videos": 2,
            "search_instructions": "",
        }
        result = search_agent.rank_and_curate(state)

    # Falls back to first N
    assert len(result["curated_videos"]) == 2
    assert result["curated_videos"] == fake_videos[:2]


def test_rank_and_curate_fills_short_llm_selection(fake_videos):
    """If LLM selects fewer than num_videos, pad with remaining videos."""
    with patch.object(search_agent, "get_llm_for") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning('["v2"]')
        state = {
            "topic": "t",
            "discovered_videos": fake_videos,
            "num_videos": 2,
            "search_instructions": "",
        }
        result = search_agent.rank_and_curate(state)

    assert len(result["curated_videos"]) == 2
    assert "v2" in [v["video_id"] for v in result["curated_videos"]]


def test_run_search_agent_end_to_end(fake_videos):
    """Full graph: LLM + YouTube service all mocked; verifies the wiring works.

    run_search_agent returns (curated_videos, queries_used).
    """
    with patch.object(search_agent, "get_llm_for") as mock_get_llm, \
         patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details, \
         patch.object(search_agent.youtube_service, "get_channel_subscribers", return_value={}):

        # plan_searches LLM call (structured plan)
        plan_llm = _fake_llm_returning(_plan_payload(["q1", "q2"]))
        # rank_and_curate LLM call
        rank_llm = _fake_llm_returning(json.dumps(["v1", "v2"]))
        mock_get_llm.side_effect = [plan_llm, rank_llm]

        mock_search.return_value = fake_videos
        mock_details.return_value = {
            v["video_id"]: {"duration_seconds": v["duration_seconds"]} for v in fake_videos
        }

        curated, queries_used, _unresolved = search_agent.run_search_agent(
            topic="quantum computing",
            num_videos=2,
            search_instructions="focus on fundamentals",
        )

    assert isinstance(curated, list)
    assert len(curated) == 2
    assert queries_used == ["q1", "q2"]
    # YouTube service was invoked
    assert mock_search.called
    # LLM invoked twice (plan + curation)
    assert mock_get_llm.call_count == 2


def test_run_search_agent_resolves_preferred_channels(fake_videos):
    """End-to-end with preferred_channels supplied: resolve_channel_id is
    called for each hint, and their uploads show up as preferred-sourced."""
    preferred_uploads_v2 = ["v2"]

    with patch.object(search_agent, "get_llm_for") as mock_get_llm, \
         patch.object(search_agent.youtube_service, "resolve_channel_id") as mock_resolve, \
         patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_channel_videos") as mock_channel_videos, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details, \
         patch.object(search_agent.youtube_service, "get_channel_subscribers", return_value={}):

        mock_resolve.side_effect = ["UCABC"]
        plan_llm = _fake_llm_returning(
            _plan_payload(["quantum intro", "quantum risks"], ["quantum"])
        )
        rank_llm = _fake_llm_returning(json.dumps(["v2", "v1"]))
        mock_get_llm.side_effect = [plan_llm, rank_llm]

        mock_search.return_value = [fake_videos[0]]  # v1 from broad
        mock_channel_videos.return_value = preferred_uploads_v2  # v2 from preferred channel

        def _details_side_effect(ids, **_):
            return {
                v["video_id"]: {
                    "video_id": v["video_id"],
                    "title": v["title"],
                    "channel_name": v["channel_name"],
                    "channel_id": v["channel_id"],
                    "duration_seconds": v["duration_seconds"],
                    "published_at": "2024-01-01T00:00:00Z",
                }
                for v in fake_videos
                if v["video_id"] in ids
            }

        mock_details.side_effect = _details_side_effect

        curated, queries_used, _unresolved = search_agent.run_search_agent(
            topic="quantum",
            num_videos=2,
            preferred_channels=["@preferred"],
        )

    assert mock_resolve.call_count == 1
    mock_channel_videos.assert_called_once()
    # Broad queries must NOT contain the channel hint text.
    assert all("@preferred" not in q for q in queries_used)
    # Both broad and preferred-source videos make it into the curated set.
    assert {v["video_id"] for v in curated} == {"v1", "v2"}
