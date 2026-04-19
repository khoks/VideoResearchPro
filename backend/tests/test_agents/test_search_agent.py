"""Tests for the Search Agent (backend/app/agents/search_agent.py).

These tests mock `get_llm` to produce canned responses and mock the YouTube
service so the agent runs offline against real LangGraph code paths.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

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


def test_generate_search_queries_parses_json_list():
    with patch.object(search_agent, "get_llm") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning(
            '["quantum computing intro", "qubit tutorial", "quantum gates"]'
        )
        state = {
            "topic": "quantum computing",
            "search_instructions": "",
            "channel_type_filters": [],
        }
        result = search_agent.generate_search_queries(state)

    assert result["search_queries_used"] == [
        "quantum computing intro",
        "qubit tutorial",
        "quantum gates",
    ]
    assert len(result["messages"]) == 1


def test_generate_search_queries_falls_back_on_bad_json():
    with patch.object(search_agent, "get_llm") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning("not valid json!!")
        state = {
            "topic": "physics",
            "search_instructions": "",
            "channel_type_filters": [],
        }
        result = search_agent.generate_search_queries(state)

    assert result["search_queries_used"] == ["physics"]


def test_generate_search_queries_falls_back_when_not_a_list():
    with patch.object(search_agent, "get_llm") as mock_get_llm:
        mock_get_llm.return_value = _fake_llm_returning('{"query": "physics"}')
        state = {
            "topic": "physics",
            "search_instructions": "",
            "channel_type_filters": [],
        }
        result = search_agent.generate_search_queries(state)

    assert result["search_queries_used"] == ["physics"]


def test_execute_searches_calls_youtube_service_with_expected_queries(fake_videos):
    queries = ["q one", "q two"]
    with patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details:
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
        }
        result = search_agent.execute_searches(state)

    # search_videos was called for each query
    assert mock_search.call_count == 2
    actual_queries = [c.kwargs.get("query") or c.args[0] for c in mock_search.call_args_list]
    assert actual_queries == queries
    # Videos returned and enriched
    assert len(result["discovered_videos"]) == 2


def test_execute_searches_applies_long_duration_filter(fake_videos):
    """min_duration >= 20 picks the 'long' filter keyword."""
    with patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details:
        mock_search.return_value = fake_videos
        mock_details.return_value = {
            v["video_id"]: {"duration_seconds": v["duration_seconds"]} for v in fake_videos
        }

        state = {
            "topic": "quantum",
            "search_queries_used": ["q1"],
            "num_videos": 5,
            "min_duration": 30,
            "max_duration": None,
        }
        search_agent.execute_searches(state)

    # The first (and only) call used video_duration="long"
    assert mock_search.call_args.kwargs["video_duration"] == "long"


def test_execute_searches_applies_short_duration_filter(fake_videos):
    with patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details:
        mock_search.return_value = []
        mock_details.return_value = {}

        state = {
            "topic": "t",
            "search_queries_used": ["q1"],
            "num_videos": 5,
            "min_duration": None,
            "max_duration": 3,
        }
        search_agent.execute_searches(state)

    assert mock_search.call_args.kwargs["video_duration"] == "short"


def test_execute_searches_filters_by_duration_minutes(fake_videos):
    """After enrichment, videos outside the min/max minute range are dropped."""
    with patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details:
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
        }
        result = search_agent.execute_searches(state)

    kept = [v["video_id"] for v in result["discovered_videos"]]
    # v1 is 10min (excluded), v2 is 30min (kept), v3 is 60min (excluded)
    assert kept == ["v2"]


def test_execute_searches_dedupes_across_queries(fake_videos):
    with patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details:
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
        }
        result = search_agent.execute_searches(state)

    assert len(result["discovered_videos"]) == 2


def test_rank_and_curate_returns_all_when_below_target(fake_videos):
    """Short-circuit: no LLM call if candidate count <= target."""
    with patch.object(search_agent, "get_llm") as mock_get_llm:
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
    with patch.object(search_agent, "get_llm") as mock_get_llm:
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
    with patch.object(search_agent, "get_llm") as mock_get_llm:
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
    with patch.object(search_agent, "get_llm") as mock_get_llm:
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
    """Full graph: LLM + YouTube service all mocked; verifies the wiring works."""
    with patch.object(search_agent, "get_llm") as mock_get_llm, \
         patch.object(search_agent.youtube_service, "search_videos") as mock_search, \
         patch.object(search_agent.youtube_service, "get_video_details") as mock_details:

        # generate_search_queries LLM call
        query_llm = _fake_llm_returning('["q1", "q2"]')
        # rank_and_curate LLM call
        rank_llm = _fake_llm_returning(json.dumps(["v1", "v2"]))
        mock_get_llm.side_effect = [query_llm, rank_llm]

        mock_search.return_value = fake_videos
        mock_details.return_value = {
            v["video_id"]: {"duration_seconds": v["duration_seconds"]} for v in fake_videos
        }

        curated = search_agent.run_search_agent(
            topic="quantum computing",
            num_videos=2,
            search_instructions="focus on fundamentals",
        )

    assert isinstance(curated, list)
    assert len(curated) == 2
    # YouTube service was invoked
    assert mock_search.called
    # LLM invoked twice (queries + curation)
    assert mock_get_llm.call_count == 2
