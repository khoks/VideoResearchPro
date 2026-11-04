"""S-8.6.3 — the relative publish window in the search agent's ranking.

The rule from D-059 and D-072 is load-bearing: the window is a ranking
PREFERENCE, never a filter. These tests run the real `rank_and_curate`, so a
pool member can only disappear if the code drops it.

The fixtures in `tests/fixtures/search_rank/` were rendered by this same
`_render` from master at e9a7d67, before any publish-window code existed. They
pin that an unset window leaves the prompt byte-identical: the ranking prompt
is hardened against measured defects and every existing run depends on it.
If one fails, either the unset path gained a byte (a defect), or someone
changed the prompt on purpose and should regenerate them in the same change.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agents import search_agent

_GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "search_rank"

TODAY = date(2026, 11, 4)
THIRTY_DAYS_BACK = "2026-10-05"

POOL = [
    {"video_id": "old", "title": "The 2008 crash explained", "channel_id": "UC_a", "channel_name": "Alpha",
     "duration_seconds": 1500, "view_count": 120000, "like_count": 4100, "channel_subscribers": 910000,
     "published_at": "2015-01-01T00:00:00Z", "source": "search"},
    {"video_id": "new", "title": "Markets today", "channel_id": "UC_b", "channel_name": "Beta",
     "duration_seconds": 620, "view_count": 900, "like_count": None, "channel_subscribers": None,
     "published_at": "2026-10-30T12:00:00Z", "source": "preferred_channel"},
    {"video_id": "hi", "title": "बाज़ार की कहानी", "channel_id": "UC_c", "channel_name": "Gamma",
     "duration_seconds": 840, "published_at": None, "source": "search"},
]
ERA = {"old": {"era_start": 2008, "era_end": 2009, "era_confidence": 0.9, "is_retrospective": True}}
PROFILE = {"recency_weight": "dominant", "target_era": "the 2008 crisis", "rationale": "Moves fast."}


def _fake_llm(picks: list[str]) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=json.dumps(picks))
    return llm


def _rank(state_extra: dict, *, pool=None, target=2, picks=("old", "hi")) -> tuple[dict, MagicMock]:
    llm = _fake_llm(list(picks))
    state = {
        "topic": "2008 financial crisis",
        "discovered_videos": [dict(v) for v in (pool if pool is not None else POOL)],
        "num_videos": target,
        "search_instructions": "Prefer economists.",
        **state_extra,
    }
    with patch.object(search_agent, "get_llm_for", return_value=llm), \
         patch.object(search_agent, "_lookup_known_eras", return_value=ERA), \
         patch.object(search_agent, "_today", return_value=TODAY):
        result = search_agent.rank_and_curate(state)
    return result, llm


def _render(state_extra: dict) -> str:
    _, llm = _rank(state_extra)
    return llm.invoke.call_args.args[0][0].content


# --- an unset window is byte-identical ---------------------------------------

@pytest.mark.parametrize(
    ("fixture", "extra"),
    [
        ("no_window_default.txt", {}),
        ("no_window_default.txt", {"published_after_days": None}),
        ("no_window_profile.txt", {"temporal_profile": PROFILE}),
        ("no_window_profile.txt", {"temporal_profile": PROFILE, "published_after_days": None}),
    ],
)
def test_unset_window_leaves_the_ranking_prompt_byte_identical(fixture, extra):
    assert _render(extra) == (_GOLDEN / fixture).read_text(encoding="utf-8")


def test_the_golden_prompts_are_the_real_ranking_prompt():
    """A guard on the pin itself: an empty or stale fixture would pin nothing."""
    default = (_GOLDEN / "no_window_default.txt").read_text(encoding="utf-8")
    profile = (_GOLDEN / "no_window_profile.txt").read_text(encoding="utf-8")
    assert "RECENCY IS SECONDARY" in default and "RECENCY IS DOMINANT" in profile
    assert "| Era: discusses 2008–2009 (retrospective) |" in default
    assert "| Script: Devanagari |" in default
    assert "PUBLISH WINDOW" not in default + profile


# --- a set window ------------------------------------------------------------

def test_set_window_adds_one_block_and_changes_nothing_else():
    without = _render({"temporal_profile": PROFILE})
    with_window = _render({"temporal_profile": PROFILE, "published_after_days": 30})
    with patch.object(search_agent, "_today", return_value=TODAY):
        block = search_agent._publish_window_guidance(30) + "\n"

    assert block in with_window
    assert with_window.replace(block, "") == without


def test_window_names_the_date_and_keeps_the_never_a_filter_rule_last():
    with patch.object(search_agent, "_today", return_value=TODAY):
        text = search_agent._temporal_guidance(PROFILE, 30)
    lines = text.split("\n")
    assert f"on or after {THIRTY_DAYS_BACK}, the last 30 days" in lines[-2]
    assert lines[-1].startswith("These are ranking preferences, never filters")


def test_one_day_window_reads_as_a_sentence():
    with patch.object(search_agent, "_today", return_value=TODAY):
        assert "on or after 2026-11-03, the last day." in search_agent._publish_window_guidance(1)


@pytest.mark.parametrize(
    "profile",
    [
        {"recency_weight": "minimal", "target_era": None, "rationale": "Evergreen."},
        {"recency_weight": "secondary", "target_era": None, "rationale": ""},
        {"recency_weight": "dominant", "target_era": None, "rationale": ""},
        None,
    ],
)
def test_the_window_leads_whatever_the_planner_decided(profile):
    """The planner's call stays in the prompt, so the model sees both, and the
    block says which one leads. A `minimal` topic is the real disagreement."""
    prompt = _render({"temporal_profile": profile, "published_after_days": 30})
    weight = (profile or {}).get("recency_weight", "secondary").upper()
    assert f"RECENCY IS {weight}" in prompt
    assert "the window leads, because the user chose it" in prompt
    assert prompt.index(f"RECENCY IS {weight}") < prompt.index("PUBLISH WINDOW")


def test_target_era_and_window_are_different_dates_and_both_stand():
    """D-072's two dates: POSTED and DISCUSSED do not compete."""
    prompt = _render({
        "temporal_profile": {"recency_weight": "minimal", "target_era": "the 2008 crisis", "rationale": ""},
        "published_after_days": 30,
    })
    assert "TARGET ERA: the topic concerns the 2008 crisis" in prompt
    assert "when a video was POSTED, not the period it discusses, so any target era still applies" in prompt


# --- a preference, never a filter --------------------------------------------

STALE_POOL = [
    {"video_id": f"s{i}", "title": f"Old {i}", "channel_id": f"UC{i}", "channel_name": f"Ch{i}",
     "duration_seconds": 900, "published_at": f"201{i}-01-01T00:00:00Z", "source": "search"}
    for i in range(5)
]


def test_nothing_inside_the_window_still_fills_the_selection():
    result, llm = _rank({"published_after_days": 7}, pool=STALE_POOL, target=3, picks=["s0", "s1", "s2"])
    assert [v["video_id"] for v in result["curated_videos"]] == ["s0", "s1", "s2"]
    # The model saw every candidate: none was pruned before it.
    prompt = llm.invoke.call_args.args[0][0].content
    assert all(f"ID: {v['video_id']} " in prompt for v in STALE_POOL)


def test_a_model_pick_outside_the_window_is_kept_over_one_inside():
    """The window informs the model; code never overrules its ranking."""
    pool = [
        {"video_id": "classic", "title": "Foundational lecture", "channel_id": "UC1", "channel_name": "A",
         "duration_seconds": 3600, "published_at": "2012-01-01T00:00:00Z", "source": "search"},
        {"video_id": "fresh", "title": "Thin clip", "channel_id": "UC2", "channel_name": "B",
         "duration_seconds": 600, "published_at": "2026-11-01T00:00:00Z", "source": "search"},
    ]
    result, _ = _rank({"published_after_days": 30}, pool=pool, target=1, picks=["classic"])
    assert [v["video_id"] for v in result["curated_videos"]] == ["classic"]


def test_a_failed_ranking_call_falls_back_without_dropping_stale_candidates():
    """The head-of-list fallback must not become a date filter either."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="not json")
    state = {
        "topic": "t", "discovered_videos": [dict(v) for v in STALE_POOL], "num_videos": 2,
        "search_instructions": "", "published_after_days": 7,
    }
    with patch.object(search_agent, "get_llm_for", return_value=llm), \
         patch.object(search_agent, "_lookup_known_eras", return_value={}):
        result = search_agent.rank_and_curate(state)
    assert [v["video_id"] for v in result["curated_videos"]] == ["s0", "s1"]


def test_a_pool_at_or_below_target_is_kept_whole_without_a_model_call():
    result, llm = _rank({"published_after_days": 7}, pool=STALE_POOL, target=5)
    assert len(result["curated_videos"]) == 5
    llm.invoke.assert_not_called()


def test_preferred_channel_guarantee_survives_a_window():
    """D-059's quota draws on the full pool. A preferred channel whose only
    candidate is outside the window keeps its slot."""
    pool = [
        {"video_id": "pref-old", "title": "From the channel you named", "channel_id": "UC_pref",
         "channel_name": "Pref", "duration_seconds": 900, "published_at": "2014-01-01T00:00:00Z",
         "source": "preferred_channel"},
        *[
            {"video_id": f"n{i}", "title": f"New {i}", "channel_id": f"UC{i}", "channel_name": f"Ch{i}",
             "duration_seconds": 900, "published_at": "2026-11-01T00:00:00Z", "source": "search"}
            for i in range(4)
        ],
    ]
    result, _ = _rank(
        {"published_after_days": 30, "preferred_channel_ids": ["UC_pref"]},
        pool=pool, target=2, picks=["n0", "n1"],
    )
    assert "pref-old" in {v["video_id"] for v in result["curated_videos"]}


def test_every_tournament_round_is_told_the_same_date():
    """S-1.12.5: an oversized pool ranks in batches; each must carry the block."""
    pool = [
        {"video_id": f"v{i}", "title": f"T{i}", "channel_id": f"UC{i}", "channel_name": f"Ch{i}",
         "duration_seconds": 900, "published_at": "2020-01-01T00:00:00Z", "source": "search"}
        for i in range(search_agent.RANK_BATCH_MAX_CANDIDATES + 50)
    ]
    _, llm = _rank({"published_after_days": 30}, pool=pool, target=10, picks=[])
    prompts = [call.args[0][0].content for call in llm.invoke.call_args_list]
    assert len(prompts) >= 3, "two batches and a final call"
    assert all(f"on or after {THIRTY_DAYS_BACK}, the last 30 days" in p for p in prompts)


# --- the whole graph: only ranking changes -----------------------------------

def _run_graph(**kwargs) -> tuple[list[str], list[dict]]:
    """`run_search_agent` end to end. Returns every LLM prompt and the pool."""
    plan = MagicMock()
    plan.invoke.return_value = MagicMock(
        content=json.dumps({"broad_queries": ["q1"], "channel_keywords": []})
    )
    rank = _fake_llm(["s0", "s1"])
    connector = MagicMock()
    connector.search.return_value = []
    pool: list[dict] = []

    def _discovered(state):
        return {"discovered_videos": [dict(v) for v in STALE_POOL], "messages": []}

    with patch.object(search_agent, "get_llm_for", side_effect=[plan, rank]), \
         patch.object(search_agent, "execute_searches", _discovered), \
         patch.object(search_agent, "_lookup_known_eras", return_value={}), \
         patch.object(search_agent, "_today", return_value=TODAY):
        search_agent.run_search_agent(topic="t", num_videos=2, candidates_out=pool, **kwargs)
    prompts = [c.args[0][0].content for llm in (plan, rank) for c in llm.invoke.call_args_list]
    return prompts, pool


def test_the_window_reaches_the_ranker_and_nothing_before_it():
    (plan_a, rank_a), pool_a = _run_graph()
    (plan_b, rank_b), pool_b = _run_graph(published_after_days=30)

    assert "PUBLISH WINDOW" not in rank_a
    assert f"on or after {THIRTY_DAYS_BACK}" in rank_b
    assert plan_a == plan_b, "the planner never sees the window"
    assert pool_a == pool_b, "discovery is the same with or without it"
