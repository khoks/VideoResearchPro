from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.job import JobResponse

# The ten palette tokens, Notion's set, mirrored by `theme.ts` on the
# frontend. The API stores and returns the NAME, never a hex value, so the
# rendering stays theme-aware and never relies on colour alone.
SHELF_COLORS: tuple[str, ...] = (
    "default",
    "gray",
    "brown",
    "orange",
    "yellow",
    "green",
    "blue",
    "purple",
    "pink",
    "red",
)
ShelfColor = Literal[
    "default", "gray", "brown", "orange", "yellow", "green", "blue", "purple", "pink", "red"
]


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Shelf name cannot be blank")
    return cleaned


class ShelfCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    color: ShelfColor = "default"

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return _clean_name(v)


class ShelfUpdate(BaseModel):
    """Partial update. A field left out is untouched; `description: null`
    clears it (callers see which fields were sent via `model_fields_set`)."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    color: ShelfColor | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        return None if v is None else _clean_name(v)


class ShelfResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    color: str = "default"
    job_count: int = 0
    # The shelf's job ids, most recently added first. Lets one cached
    # listing answer "which shelves is this run on" for a whole page.
    job_ids: list[str] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ShelfDetailResponse(ShelfResponse):
    """The shelf plus its jobs, newest membership first."""

    jobs: list[JobResponse] = []
