"""Search Agent: plans and executes YouTube video discovery for a topic job.

Pipeline (LangGraph):

    resolve_preferred_channels
        ↓
    plan_searches    (LLM produces {broad_queries, channel_keywords})
        ↓
    execute_searches (broad queries + preferred-channel uploads, deduped)
        ↓
    rank_and_curate  (LLM ranks the merged pool)
        ↓
    END

Key design choices:

* The user's ``search_instructions`` is semantic guidance only — it never
  gets pasted into a YouTube query string. The LLM is explicitly told to
  ignore creator names, handles, and URLs when drafting queries.
* Preferred channels are resolved to channel IDs and their uploads playlists
  are walked directly. We then keyword-filter those uploads down to the
  topic-relevant subset using ``channel_keywords`` from the LLM plan.
* We merge both sources before the final LLM rank, giving the curator full
  awareness of each video's provenance (``source=search`` vs
  ``source=preferred_channel``) so it can weight accordingly.
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents.prompts.search_prompts import (
    PLAN_SEARCHES_PROMPT,
    PREFERRED_CHANNELS_BLOCK,
    RANK_AND_CURATE_PROMPT,
)
from app.agents.state import SearchAgentState
from app.services import youtube_service
from app.services.llm_service import get_llm_for
from app.sources import connector_for
from app.sources.types import Candidate, SourceMetadata
from app.utils.youtube_helpers import format_duration

logger = logging.getLogger(__name__)

# How many recent uploads we pull per preferred channel before keyword-filtering.
# 50 hits the YouTube playlistItems page size for a single quota unit.
PREFERRED_CHANNEL_FETCH_LIMIT = 50


def _candidate_to_legacy_dict(c: Candidate) -> dict:
    """Convert a connector ``Candidate`` (from ``search()``) back to the
    legacy ``youtube_service.search_videos`` dict shape so the existing
    ``execute_searches`` plumbing (`source` tags, dedup-by-id, the
    LLM rank prompt) keeps working untouched.
    """
    return {
        "video_id": c.source_id,
        "title": c.title,
        "channel_name": c.creator_name or "",
        "channel_id": c.creator_external_id or "",
        "published_at": c.published_at,
        "thumbnail_url": c.thumbnail_url,
    }


def _source_metadata_to_legacy_dict(sm: SourceMetadata, source_id: str) -> dict:
    """Convert a connector ``SourceMetadata`` back to the legacy
    ``youtube_service.get_video_details`` dict shape — same role as the
    helper in ``job_tasks.py`` but kept local to avoid coupling the
    agent module to the orchestrator. Both helpers will retire when
    callers migrate to ``SourceMetadata`` directly.

    ``source_id`` is the dict key from ``fetch_metadata``'s return
    mapping — passed in so the legacy ``video_id`` field is populated
    (the connector dataclass keeps it as the mapping key, not on the
    object itself).
    """
    return {
        "video_id": source_id,
        "title": sm.title,
        "channel_id": sm.creator_external_id or "",
        "channel_name": sm.creator_name or "",
        "duration_seconds": sm.duration_seconds,
        "published_at": sm.published_at,
        "thumbnail_url": sm.thumbnail_url,
        "url": sm.extra.get("url"),
        "view_count": sm.extra.get("view_count"),
        "like_count": sm.extra.get("like_count"),
    }


def resolve_preferred_channels(state: SearchAgentState) -> dict:
    """Resolve user-supplied channel hints (URLs / handles / UC-IDs) to channel IDs.

    Unresolvable entries are skipped with a warning so a single typo does
    not sink the whole job.
    """
    hints = state.get("preferred_channels") or []
    if not hints:
        return {"preferred_channel_ids": [], "unresolved_channels": []}

    connector = connector_for("video")
    resolved: list[str] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for hint in hints:
        hint = (hint or "").strip()
        if not hint:
            continue
        try:
            cid = connector.resolve_creator_id(hint)
        except Exception:
            logger.exception("resolve_preferred_channels: %r raised, skipping", hint)
            unresolved.append(hint)
            continue
        if cid and cid not in seen:
            seen.add(cid)
            resolved.append(cid)
        elif not cid:
            logger.warning("resolve_preferred_channels: could not resolve %r", hint)
            unresolved.append(hint)

    logger.info(
        "resolve_preferred_channels: %d/%d hints resolved (%d unresolved)",
        len(resolved), len(hints), len(unresolved),
    )
    return {"preferred_channel_ids": resolved, "unresolved_channels": unresolved}


def plan_searches(state: SearchAgentState) -> dict:
    """LLM produces a structured search plan: broad_queries + channel_keywords.

    Replaces the old ``generate_search_queries`` node. Always returns at
    least one broad query (falling back to the topic itself if the LLM
    response is unparseable), and never stuffs channel names into the
    queries.
    """
    topic = state["topic"]
    preferred_ids = state.get("preferred_channel_ids") or []

    if preferred_ids:
        preferred_block = PREFERRED_CHANNELS_BLOCK.format(
            channels=", ".join(preferred_ids)
        )
    else:
        preferred_block = ""

    llm = get_llm_for("search_plan_queries", temperature=0.3)
    prompt = PLAN_SEARCHES_PROMPT.format(
        topic=topic,
        search_instructions=state.get("search_instructions", "") or "(none)",
        channel_type_filters=", ".join(state.get("channel_type_filters", [])) or "none",
        preferred_channels_section=preferred_block,
    )
    response = llm.invoke([HumanMessage(content=prompt)])

    broad_queries: list[str] = []
    channel_keywords: list[str] = []
    try:
        plan = json.loads(response.content)
        if isinstance(plan, dict):
            raw_q = plan.get("broad_queries") or []
            if isinstance(raw_q, list):
                broad_queries = [str(q).strip() for q in raw_q if str(q).strip()]
            raw_k = plan.get("channel_keywords") or []
            if isinstance(raw_k, list):
                channel_keywords = [str(k).strip().lower() for k in raw_k if str(k).strip()]
    except (json.JSONDecodeError, TypeError):
        logger.exception("plan_searches: failed to parse LLM JSON, falling back to topic")

    # Defensive fallbacks — the pipeline MUST have at least one query, and
    # at least one keyword if preferred channels were supplied (otherwise
    # the keyword filter would keep nothing).
    if not broad_queries:
        broad_queries = [topic]
    if preferred_ids and not channel_keywords:
        channel_keywords = [w.lower() for w in topic.split() if len(w) > 2]

    logger.info(
        "plan_searches: %d broad_queries, %d channel_keywords",
        len(broad_queries), len(channel_keywords),
    )

    return {
        "search_queries_used": broad_queries,
        "channel_keywords": channel_keywords,
        "messages": [
            HumanMessage(
                content=(
                    f"Planned {len(broad_queries)} broad queries and "
                    f"{len(channel_keywords)} channel keywords"
                )
            )
        ],
    }


def _run_broad_searches(queries: list[str], target: int) -> dict[str, dict]:
    """Run each broad query against YouTube, deduping by video_id."""
    per_query_max = max(target * 3, 50)
    connector = connector_for("video")
    all_videos: dict[str, dict] = {}
    for query in queries:
        try:
            candidates = connector.search(query, limit=per_query_max)
        except Exception:
            logger.exception("broad search for %r failed; skipping", query)
            continue
        for c in candidates:
            vid = c.source_id
            if vid not in all_videos:
                v = _candidate_to_legacy_dict(c)
                v["source"] = "search"
                v["source_query"] = query
                all_videos[vid] = v
        if len(all_videos) >= target * 5:
            break
    return all_videos


def _keyword_score(text: str, keywords: list[str]) -> int:
    """Very cheap relevance score: count of keyword substring hits in text.

    Kept simple on purpose — the LLM-based ``rank_and_curate`` does the
    heavy lifting. This scoring just filters out channel uploads that are
    obviously off-topic (e.g. a creator's cooking video when the topic is
    AI safety).
    """
    if not keywords:
        return 0
    text_l = (text or "").lower()
    return sum(1 for kw in keywords if kw and kw in text_l)


def _fetch_preferred_channel_uploads(
    channel_ids: list[str],
    keywords: list[str],
    cap_per_channel: int = 20,
) -> dict[str, dict]:
    """Pull recent uploads from each preferred channel and keyword-filter them.

    We fetch the ``PREFERRED_CHANNEL_FETCH_LIMIT`` most recent uploads per
    channel, fetch their details, and keep only the ones whose title
    matches at least one keyword. This prevents a channel's entire back
    catalogue from drowning out topic relevance while still surfacing
    everything on-topic they have recently published.
    """
    if not channel_ids:
        return {}

    connector = connector_for("video")

    # Fetch recent upload IDs per channel.
    all_ids: list[str] = []
    channel_of: dict[str, str] = {}
    for cid in channel_ids:
        try:
            vids = [
                c.source_id
                for c in connector.list_creator_items(
                    cid, limit=PREFERRED_CHANNEL_FETCH_LIMIT
                )
            ]
        except Exception:
            logger.exception("preferred-channel fetch failed for %s", cid)
            continue
        for vid in vids:
            if vid not in channel_of:
                channel_of[vid] = cid
                all_ids.append(vid)

    if not all_ids:
        return {}

    try:
        details_meta = connector.fetch_metadata(all_ids)
    except Exception:
        logger.exception("fetch_metadata failed for preferred-channel uploads")
        return {}
    details = {
        vid: _source_metadata_to_legacy_dict(sm, vid)
        for vid, sm in details_meta.items()
    }

    # Score by title+description (description is usually not returned by
    # videos.list without a separate fetch, so we rely on title).
    scored_per_channel: dict[str, list[tuple[int, dict]]] = {}
    for vid, d in details.items():
        d["source"] = "preferred_channel"
        d["source_channel_id"] = channel_of.get(vid, "")
        score = _keyword_score(d.get("title", ""), keywords)
        scored_per_channel.setdefault(channel_of.get(vid, ""), []).append((score, d))

    kept: dict[str, dict] = {}
    for cid, scored in scored_per_channel.items():
        # Keep keyword matches first, then fill up to cap_per_channel with
        # the most recent uploads so the user's channel is always represented.
        scored.sort(key=lambda t: (-t[0], t[1].get("published_at") or ""), reverse=False)
        matches = [v for s, v in scored if s > 0]
        if not matches:
            # No keyword hits — keep the top few recent uploads so the LLM
            # ranker at least sees this channel. It will drop them as
            # off-topic if they really are.
            matches = [v for _, v in scored[:3]]
        for v in matches[:cap_per_channel]:
            kept[v["video_id"]] = v

    logger.info(
        "_fetch_preferred_channel_uploads: kept %d videos across %d channels",
        len(kept), len(channel_ids),
    )
    return kept


def execute_searches(state: SearchAgentState) -> dict:
    """Execute the planned searches against YouTube and the uploads playlists.

    Merges broad-query results with preferred-channel uploads, enriches
    each with channel-subscriber counts, and applies the user's duration
    filter.
    """
    queries = state.get("search_queries_used") or [state["topic"]]
    target = state["num_videos"]
    min_dur = state.get("min_duration")
    max_dur = state.get("max_duration")
    preferred_ids = state.get("preferred_channel_ids") or []
    keywords = state.get("channel_keywords") or []

    # NOTE: `channel_type_filters` (e.g. "educational", "academic") is a
    # semantic preference consumed by the LLM ranking step, NOT a YouTube
    # API parameter. YouTube's `channelType` only accepts
    # ['channelTypeUnspecified', 'any', 'show']. Don't forward user-facing
    # semantic filters to the API — let the rank prompt use them.

    all_videos: dict[str, dict] = _run_broad_searches(queries, target)

    # Preferred-channel path: walks uploads directly, sidestepping the
    # "stuff channel names into the search query" pathology.
    if preferred_ids:
        preferred_videos = _fetch_preferred_channel_uploads(preferred_ids, keywords)
        # Preferred-channel videos already carry full details from
        # videos.list; merge them in without clobbering the search-sourced
        # `source` tag on overlaps (prefer the preferred_channel tag so
        # the ranker knows this video comes from a channel the user asked for).
        for vid, v in preferred_videos.items():
            all_videos[vid] = v

    # Fetch detailed metadata for any video we haven't already enriched.
    missing_ids = [
        vid for vid, v in all_videos.items()
        if "duration_seconds" not in v
    ]
    if missing_ids:
        connector = connector_for("video")
        details_meta = connector.fetch_metadata(missing_ids)
        details = {
            vid: _source_metadata_to_legacy_dict(sm, vid)
            for vid, sm in details_meta.items()
        }
        for vid, detail in details.items():
            if vid in all_videos:
                # Preserve the `source` and `source_query` tags we set.
                merged = {**detail, **{k: v for k, v in all_videos[vid].items() if k.startswith("source")}}
                merged.setdefault("source", all_videos[vid].get("source", "search"))
                all_videos[vid] = {**all_videos[vid], **merged}

    # Fetch channel subscriber counts so ranking can use channel authority.
    channel_ids = sorted({v.get("channel_id") for v in all_videos.values() if v.get("channel_id")})
    if channel_ids:
        try:
            subs = youtube_service.get_channel_subscribers(channel_ids)
        except Exception:
            logger.exception("Failed to fetch channel subscribers; continuing without them")
            subs = {}
        for v in all_videos.values():
            v["channel_subscribers"] = subs.get(v.get("channel_id"))

    # Fine-grained duration filtering using minute bounds.
    filtered = []
    for v in all_videos.values():
        dur_min = v.get("duration_seconds", 0) / 60
        if min_dur is not None and dur_min < min_dur:
            continue
        if max_dur is not None and dur_min > max_dur:
            continue
        filtered.append(v)

    logger.info(
        "execute_searches: %d videos after merge+filter (broad+preferred)",
        len(filtered),
    )
    return {
        "discovered_videos": filtered,
        "messages": [HumanMessage(content=f"Found {len(filtered)} videos after filtering")],
    }


def _format_video_line(v: dict) -> str:
    """Render a single video entry for the ranking prompt."""
    subs = v.get("channel_subscribers")
    subs_str = f"{subs:,}" if isinstance(subs, int) else "unknown"
    views = v.get("view_count")
    views_str = f"{views:,}" if isinstance(views, int) else "unknown"
    likes = v.get("like_count")
    likes_str = f"{likes:,}" if isinstance(likes, int) else "unknown"
    source = v.get("source", "search")
    return (
        f"- ID: {v['video_id']} | Source: {source} | "
        f"Title: {v.get('title', 'N/A')} | "
        f"Channel: {v.get('channel_name', 'N/A')} | "
        f"Duration: {format_duration(v.get('duration_seconds', 0))} | "
        f"Views: {views_str} | Likes: {likes_str} | "
        f"Published: {v.get('published_at', 'unknown')} | "
        f"Subscribers: {subs_str}"
    )


def rank_and_curate(state: SearchAgentState) -> dict:
    """Use LLM to rank and select the best videos."""
    videos = state.get("discovered_videos", [])
    target = state["num_videos"]

    if len(videos) <= target:
        return {"curated_videos": videos}

    llm = get_llm_for("search_rank_and_curate", temperature=0.0)
    video_list = "\n".join(_format_video_line(v) for v in videos)

    prompt = RANK_AND_CURATE_PROMPT.format(
        topic=state["topic"],
        search_instructions=state.get("search_instructions", ""),
        num_videos=target,
        video_list=video_list,
    )
    response = llm.invoke([HumanMessage(content=prompt)])

    try:
        selected_ids = json.loads(response.content)
        if isinstance(selected_ids, list):
            id_set = set(selected_ids[:target])
            curated = [v for v in videos if v["video_id"] in id_set]
            # Fill remaining slots if LLM didn't select enough
            if len(curated) < target:
                for v in videos:
                    if v["video_id"] not in id_set:
                        curated.append(v)
                        if len(curated) >= target:
                            break
            return {"curated_videos": curated}
    except (json.JSONDecodeError, TypeError):
        logger.exception("Failed to parse rank_and_curate LLM response; falling back to head-of-list")

    return {"curated_videos": videos[:target]}


def build_search_graph() -> StateGraph:
    """Build the search agent LangGraph."""
    graph = StateGraph(SearchAgentState)
    graph.add_node("resolve_preferred_channels", resolve_preferred_channels)
    graph.add_node("plan_searches", plan_searches)
    graph.add_node("execute_searches", execute_searches)
    graph.add_node("rank_and_curate", rank_and_curate)

    graph.set_entry_point("resolve_preferred_channels")
    graph.add_edge("resolve_preferred_channels", "plan_searches")
    graph.add_edge("plan_searches", "execute_searches")
    graph.add_edge("execute_searches", "rank_and_curate")
    graph.add_edge("rank_and_curate", END)

    return graph.compile()


# --------------------------------------------------------------------------
# Back-compat shim for tests that still import ``generate_search_queries``.
# The new orchestration uses ``plan_searches``, which does everything
# ``generate_search_queries`` did plus produces ``channel_keywords``.
# Kept here so the existing test suite keeps passing.
# --------------------------------------------------------------------------
def generate_search_queries(state: SearchAgentState) -> dict:
    """Deprecated: use ``plan_searches``. Left for test/back-compat only."""
    return plan_searches(state)


def run_search_agent(
    topic: str,
    num_videos: int = 10,
    search_instructions: str = "",
    min_duration: int | None = None,
    max_duration: int | None = None,
    channel_type_filters: list[str] | None = None,
    preferred_channels: list[str] | None = None,
    progress_callback=None,
) -> tuple[list[dict], list[str], list[str]]:
    """Run the search agent.

    Returns ``(curated_videos, search_queries_used, unresolved_channels)``.

    ``progress_callback`` (S-1.11.8), when given, is invoked as
    ``cb(pct: int, message: str)`` after each pipeline node so the caller
    can surface sub-progress instead of a static "Searching..." for the
    whole multi-minute phase. Callback errors are swallowed — progress
    reporting must never sink the search itself.
    """
    graph = build_search_graph()
    initial_state = {
        "messages": [],
        "topic": topic,
        "search_instructions": search_instructions,
        "num_videos": num_videos,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "channel_type_filters": channel_type_filters or [],
        "preferred_channels": preferred_channels or [],
        "preferred_channel_ids": [],
        "unresolved_channels": [],
        "channel_keywords": [],
        "discovered_videos": [],
        "curated_videos": [],
        "search_queries_used": [],
    }

    def _notify(pct: int, message: str) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(pct, message)
        except Exception:
            logger.exception("search progress_callback raised; continuing")

    result: dict = dict(initial_state)
    for update in graph.stream(initial_state, stream_mode="updates"):
        for node_name, delta in update.items():
            if isinstance(delta, dict):
                result.update(delta)
            if node_name == "resolve_preferred_channels":
                n_res = len(result.get("preferred_channel_ids") or [])
                n_unres = len(result.get("unresolved_channels") or [])
                unres_note = f" ({n_unres} unresolved)" if n_unres else ""
                _notify(6, f"Resolved {n_res} preferred channels{unres_note}. Planning queries...")
            elif node_name == "plan_searches":
                n_q = len(result.get("search_queries_used") or [])
                _notify(8, f"Planned {n_q} search queries. Searching YouTube...")
            elif node_name == "execute_searches":
                n_found = len(result.get("discovered_videos") or [])
                _notify(12, f"Found {n_found} candidates. Ranking with AI...")

    return (
        result.get("curated_videos", []),
        result.get("search_queries_used", []),
        result.get("unresolved_channels", []),
    )
