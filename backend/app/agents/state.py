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
    # Hints that could not be resolved to a channel ID (S-1.11.6) — surfaced
    # to the user at approval time instead of being silently dropped.
    unresolved_channels: list[str]
    # LLM-selected keywords used to score preferred-channel uploads for topic relevance.
    channel_keywords: list[str]
    discovered_videos: list[dict]
    curated_videos: list[dict]
    search_queries_used: list[str]
    # R3 / T-1.17.2.3: the planner's deliberate per-topic recency decision —
    # {recency_weight: dominant|secondary|minimal, target_era, rationale}.
    # A ranking input, never a filter.
    temporal_profile: dict


class ReportAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    job_type: str
    topic: str
    transcript_chunks: list[dict]
    chunk_summaries: list[dict]
    report_sections: dict[str, str]
    statistics: dict
    final_html: str
    # R4 / D-064: user's optional depth override ('brief'|'standard'|'deep');
    # None means 'auto' — the corpus size bracket decides.
    output_length: str | None
    # S-1.12.4 loud accounting: map batch/drop counters surfaced as a
    # processing-note footer in the composed report.
    processing_notes: dict
    # S-1.14.6: audit records of what map emitted per batch and what reduce
    # handed to compose, serialised when each stage produced them.
    map_batch_records: list[dict]
    reduce_record: dict


class KnowledgeAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    # The YouTube id for a video, else the document_id (logging only).
    video_id: str
    # `documents.source_type`: picks how the prompts name the source
    # (`knowledge_prompts.source_profile`). Absent reads as "video".
    source_type: str
    video_title: str
    channel_name: str
    # R3: `YYYY-MM-DD` publish date ("" when unknown) that relative time is
    # anchored to, and the prompt-ready discussed-era clause ("" when unknown).
    published_at: str
    discussed_era: str
    # The document's full text: its transcript_cache row, or its Chroma chunks
    # reassembled (`document_text_service.full_text`).
    full_transcript_text: str
    # Token-budgeted slices of `full_transcript_text` fed to the map pass.
    transcript_batches: list[str]
    # One structured extraction per batch: {topics, concepts, events, facts}.
    per_batch_extractions: list[dict]
    # Union-deduped merged extraction.
    merged_extraction: dict
    # Final Markdown knowledge document.
    knowledge_report_md: str


class QAAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    job_id: str
    job_type: str
    question: str
    report_html: str
    # S-1.12.1: the job's approved document ids scoping its retrieval —
    # `documents.document_id` values since D-070, never the legacy video_id.
    document_ids: list[str]
    # D-068: the asking tenant's non-neutral trust weights, {channel_id:
    # weight}, resolved by the router at request time. Empty = unweighted.
    channel_weights: dict[str, float]
    # S-8.5.2: whose notes join retrieval, and on which targets (job
    # scope). None tenant = no notes; None keys = every note of the tenant.
    notes_tenant_id: str | None
    note_target_keys: list[str] | None
    sub_queries: list[str]
    rag_results: list[dict]
    report_context: str | None
    refined_context: str
    answer: str
    references: list[dict]
    corpus_statistics: dict | None
    output_length: str | None
