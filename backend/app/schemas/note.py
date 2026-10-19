"""Pydantic shapes for the notes API (M5 / S-8.5.1).

Validation of the closed sets (target types, motivations) happens here at
the API layer, as T-8.5.1.1 asks, so a typo is a 422 with a readable message
rather than a row nobody can query.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TargetType = Literal[
    "document",
    "job",
    "qa_exchange",
    "library_qa_exchange",
    "qa_history_exchange",
    "channel",
    "knowledge_artifact",
]

Motivation = Literal["commenting", "highlighting", "tagging"]

# A note is an annotation, not a document. The cap keeps a pasted transcript
# from becoming a "note" and bounds what every list call returns.
NOTE_BODY_MAX_CHARS = 20_000
SELECTOR_TEXT_MAX_CHARS = 2_000


class Selector(BaseModel):
    """W3C Web Annotation ``TextQuoteSelector`` plus a media-time anchor.

    ``exact`` is the quoted span; ``prefix`` / ``suffix`` disambiguate it;
    ``start_seconds`` lets a note on a video anchor to a moment and carry a
    ``&t=`` link exactly like a Q&A citation. All optional except ``exact``
    when a selector is given at all.
    """

    type: Literal["TextQuoteSelector"] = "TextQuoteSelector"
    exact: str = Field(min_length=1, max_length=SELECTOR_TEXT_MAX_CHARS)
    prefix: str | None = Field(default=None, max_length=SELECTOR_TEXT_MAX_CHARS)
    suffix: str | None = Field(default=None, max_length=SELECTOR_TEXT_MAX_CHARS)
    start_seconds: float | None = Field(default=None, ge=0)


class NoteCreate(BaseModel):
    target_type: TargetType
    target_id: str = Field(min_length=1, max_length=64)
    body_md: str = Field(min_length=1, max_length=NOTE_BODY_MAX_CHARS)
    motivation: Motivation = "commenting"
    selector: Selector | None = None

    @field_validator("body_md")
    @classmethod
    def _body_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("body_md must not be blank")
        return v

    @field_validator("target_id")
    @classmethod
    def _target_id_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("target_id must not be blank")
        return v


class NoteUpdate(BaseModel):
    """Partial update. Omitted fields are untouched; ``selector: null`` clears it."""

    body_md: str | None = Field(default=None, min_length=1, max_length=NOTE_BODY_MAX_CHARS)
    motivation: Motivation | None = None
    selector: Selector | None = None

    @field_validator("body_md")
    @classmethod
    def _body_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("body_md must not be blank")
        return v


class NoteResponse(BaseModel):
    id: str
    target_type: TargetType
    target_id: str
    body_md: str
    motivation: Motivation
    selector: Selector | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    # Resolved summary of the target so a list of notes can be rendered
    # without a follow-up request per note. ``target_label`` is None when the
    # target no longer exists (a deleted job); the note is still the user's.
    target_label: str | None = None
    # For document and knowledge-artifact targets only: the legacy YouTube id
    # of the document, so surfaces still keyed on ``video_id`` (the library
    # shelf, the knowledge drawer) can match a note stored under the
    # canonical ``document_id``. Goes away with D-070.
    target_video_id: str | None = None
    # ``qa_exchange`` targets only: the job that holds the exchange, so the
    # notes page can link to the page the answer lives on.
    target_parent_id: str | None = None


class NoteListResponse(BaseModel):
    items: list[NoteResponse]
    total: int
    limit: int
    offset: int


class NoteDeleteResponse(BaseModel):
    deleted: bool
    deleted_at: datetime
