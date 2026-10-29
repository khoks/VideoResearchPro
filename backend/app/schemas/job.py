from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services import job_source_types


class JobCreate(BaseModel):
    job_type: Literal["topic", "channel", "subscription"]

    # Topic fields
    topic: str | None = None
    search_instructions: str | None = None
    num_videos: int = Field(default=10, ge=1, le=500)
    min_duration_minutes: int | None = Field(default=None, ge=1)
    max_duration_minutes: int | None = Field(default=None, ge=1)
    channel_type_filters: list[str] | None = None
    # Optional list of YouTube channel URLs, handles, or UC-IDs that the user
    # wants the Search Agent to emphasize. Unlike free-text in
    # `search_instructions`, these are resolved to channel_ids and their
    # uploads playlists are walked directly — avoiding the pathological
    # pattern where the LLM stuffs channel names into YouTube query strings.
    preferred_channels: list[str] | None = None

    # R4: optional depth override for the generated report. Omitted or
    # 'auto' lets the corpus size bracket decide, which is the default
    # experience — the control is additive and never required.
    output_length: Literal["auto", "brief", "standard", "deep"] | None = None

    # R1: opt-in visual understanding — capture frames at moments the
    # transcript suggests something is being SHOWN, describe them, and merge
    # the descriptions into the transcript as clearly-marked annotations.
    # Opt-in rather than default because it adds video-stream downloads on
    # top of the audio traffic that already triggered a YouTube IP block
    # once (D-051), and because it is the app's only multimodal spend.
    # AND-ed with the install-wide VISUAL_ENABLED setting.
    visual_analysis: bool = False

    # S-1.5.13: which source types a topic run searches. Omitted means
    # YouTube only, exactly as before. Validated against what this install
    # can search (an unknown, library-only or unconfigured type is a 422)
    # and put in canonical order; `video` runs the search agent, the rest
    # go through `connector_dispatch`. `num_videos` is shared across them
    # (`job_source_types.share_limits`), so the tier cap bounds the run.
    source_types: list[str] | None = Field(default=None, max_length=32)

    # Channel fields
    channel_list: list[str] | None = None
    videos_per_channel: int | None = Field(default=10, ge=1, le=50)

    @field_validator("source_types")
    @classmethod
    def validate_source_types(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return job_source_types.normalise(value)

    @model_validator(mode="after")
    def validate_job_type_fields(self) -> Self:
        if self.job_type == "topic" and not self.topic:
            raise ValueError("topic is required for topic-based jobs")
        if self.job_type == "channel" and not self.channel_list:
            raise ValueError("channel_list is required for channel-based jobs")
        if self.job_type == "subscription" and not self.channel_list:
            raise ValueError("channel_list is required for subscription jobs")
        if self.min_duration_minutes and self.max_duration_minutes:
            if self.min_duration_minutes > self.max_duration_minutes:
                raise ValueError("min_duration_minutes must be <= max_duration_minutes")
        if self.job_type != "topic" and self.source_types is not None:
            # Channel and subscription runs read YouTube channels; YouTube
            # alone is accepted and dropped, anything else is a mistake.
            if not job_source_types.is_default(self.source_types):
                raise ValueError(
                    "source_types applies to topic research only; channel and "
                    "subscription runs read YouTube channels"
                )
            self.source_types = None
        if (
            self.job_type == "topic"
            and self.source_types is not None
            and self.num_videos < len(self.source_types)
        ):
            # The run shares num_videos across its sources (the tier cap
            # bounds the whole run, not each source), so each needs one.
            raise ValueError(
                f"num_videos must be at least {len(self.source_types)}, one per "
                "source type: a run shares num_videos across the sources it searches"
            )
        return self


class JobResponse(BaseModel):
    id: str
    job_type: str
    status: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    topic: str | None = None
    search_instructions: str | None = None
    num_videos: int
    min_duration_minutes: int | None = None
    max_duration_minutes: int | None = None
    channel_type_filters: list[str] | None = None
    preferred_channels: list[str] | None = None
    channel_list: list[str] | None = None
    videos_per_channel: int | None = None
    output_length: str | None = None
    visual_analysis: bool = False
    # S-1.5.13: what the run searches, resolved (["video"] by default).
    source_types: list[str] = Field(default_factory=lambda: ["video"])
    # E-8.6: the template version this run started from, if any.
    template_id: str | None = None
    template_version: int | None = None
    search_queries_used: list[str] | None = None
    channel_list_resolved: list[dict] | None = None
    progress_pct: int
    progress_message: str | None = None
    error_message: str | None = None
    video_count: int = 0
    transcript_count: int = 0
    has_report: bool = False

    model_config = {"from_attributes": True}


class VideoApproval(BaseModel):
    approved_video_ids: list[str]
