from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class SearchAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    topic: str
    search_instructions: str
    num_videos: int
    min_duration: int | None
    max_duration: int | None
    channel_type_filters: list[str]
    # Raw user-supplied channel hints (URLs/handles/UC-IDs). Optional; may be empty.
    preferred_channels: list[str]
    # Channel IDs resolved from `preferred_channels` via the YouTube API.
    preferred_channel_ids: list[str]
    # LLM-selected keywords used to score preferred-channel uploads for topic relevance.
    channel_keywords: list[str]
    discovered_videos: list[dict]
    curated_videos: list[dict]
    search_queries_used: list[str]


class ReportAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    job_type: str
    topic: str
    transcript_chunks: list[dict]
    chunk_summaries: list[dict]
    report_sections: dict[str, str]
    statistics: dict
    final_html: str


class QAAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    job_id: str
    job_type: str
    question: str
    report_html: str
    sub_queries: list[str]
    rag_results: list[dict]
    report_context: str | None
    refined_context: str
    answer: str
    references: list[dict]
