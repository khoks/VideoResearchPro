from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# The variable fields of a run: what a reader changes each time they use a
# template. Everything else on `JobCreate` is frozen into the template.
# `test_job_templates.py` pins that FROZEN ∪ VARIABLE == JobCreate's fields,
# so a new JobCreate field forces a decision here instead of being silently
# dropped by every template (the Duplicate-flow defect, T-8.6.1.0).
VARIABLE_FIELDS: frozenset[str] = frozenset({"topic"})


class TemplateParameters(BaseModel):
    """The frozen half of a `JobCreate`."""

    job_type: Literal["topic", "channel", "subscription"]
    # May contain `{{topic}}`, replaced by the run's topic at creation.
    search_instructions: str | None = None
    num_videos: int = Field(default=10, ge=1, le=500)
    min_duration_minutes: int | None = Field(default=None, ge=1)
    max_duration_minutes: int | None = Field(default=None, ge=1)
    channel_type_filters: list[str] | None = None
    preferred_channels: list[str] | None = None
    output_length: Literal["auto", "brief", "standard", "deep"] | None = None
    visual_analysis: bool = False
    channel_list: list[str] | None = None
    videos_per_channel: int | None = Field(default=10, ge=1, le=50)

    model_config = {"extra": "forbid"}


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Template name cannot be blank")
    return cleaned


class JobTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    parameters: TemplateParameters

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return _clean_name(v)


class JobTemplateUpdate(BaseModel):
    """Partial update. New `parameters` that differ from the latest version
    create a new version; name and description change in place."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    parameters: TemplateParameters | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        return None if v is None else _clean_name(v)


class SaveAsTemplate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return _clean_name(v)


class JobTemplateResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    job_type: str
    builtin: bool = False
    builtin_key: str | None = None
    version: int
    parameters: TemplateParameters
    # Why using this template right now would fail for the caller (a tier
    # cap below its `num_videos`, ...). Empty when it is good to go.
    problems: list[str] = []
    created_at: datetime
    updated_at: datetime


class JobTemplateVersionResponse(BaseModel):
    version: int
    parameters: TemplateParameters
    created_at: datetime
