from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.shelf import ShelfColor


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Tag name cannot be blank")
    return cleaned


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: ShelfColor = "default"

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return _clean_name(v)


class TagUpdate(BaseModel):
    """Rename and / or recolour. A field left out is untouched."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    color: ShelfColor | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        return None if v is None else _clean_name(v)


class TagSummary(BaseModel):
    """What a library row carries for each of the caller's tags on it."""

    id: str
    name: str
    color: str = "default"


class TagResponse(TagSummary):
    # Documents carrying this tag that the caller can still see (D-063).
    document_count: int = 0
    created_at: datetime
