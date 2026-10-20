"""Saved-search payloads (S-8.3.2)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SavedSearchCadence(BaseModel):
    """A human cadence: ``weekday`` is 0 = Monday … 6 = Sunday; ``day_of_month`` 1–28."""

    model_config = ConfigDict(extra="forbid")

    cadence: Literal["daily", "weekly", "monthly"]
    hour: int = Field(ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    weekday: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=28)
    timezone: str = Field(default="UTC", max_length=64)


class SavedSearchScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shelf_id: str


class SavedSearchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=2000)
    cadence: SavedSearchCadence
    answer_language: str = Field(default="en", max_length=10)
    #: Null searches the whole library.
    scope: SavedSearchScope | None = None
    notify_email: bool = True


class SavedSearchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, min_length=3, max_length=2000)
    cadence: SavedSearchCadence | None = None
    answer_language: str | None = Field(default=None, max_length=10)
    scope: SavedSearchScope | None = None
    notify_email: bool | None = None
    enabled: bool | None = None


class SavedSearchResponse(BaseModel):
    id: str
    question: str
    answer_language: str
    scope: dict[str, Any] | None
    cadence: dict[str, Any] | None
    #: UTC. Null while paused.
    next_run_at: datetime | None
    notify_email: bool
    enabled: bool
    created_at: datetime
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    last_success_at: datetime | None
    last_exchange_id: str | None
    last_answer: str | None


class SavedSearchList(BaseModel):
    items: list[SavedSearchResponse]
    #: Enabled saved searches and the tier's cap on them (-1 = unlimited).
    active: int
    cap: int


class RunNowResponse(BaseModel):
    status: Literal["queued"]


class SavedSearchRunResponse(BaseModel):
    """One run (S-8.3.3). ``changed`` is null on the first run and on runs
    that did not answer; ``decided_by`` says whether the two signals agreed
    or the judge decided."""

    id: str
    ran_at: datetime
    trigger: str
    status: str
    error: str | None
    exchange_id: str | None
    previous_exchange_id: str | None
    changed: bool | None
    jaccard: float | None
    embedding_distance: float | None
    decided_by: str | None
    added_reference_ids: list[str]
    dropped_reference_ids: list[str]
    diff_summary: str | None
