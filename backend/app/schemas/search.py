"""Response shape of ``GET /api/v1/search`` (S-8.2.1 / M2)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SearchType = Literal["jobs", "documents", "channels", "qa", "knowledge"]


class SearchItem(BaseModel):
    id: str
    title: str
    subtitle: str = ""
    # A frontend route the palette navigates to. Documents point at the
    # library with `?document=<document_id>` — the canonical id, since most
    # non-video documents have no video_id (D-070) — which the library page
    # honours as a one-row filter (S-8.2.2). Knowledge reports open in their
    # reader at `/knowledge/<document_id>` (S-8.8.3).
    href: str
    # Higher is better. The LIKE fallback has no ranking and reports 0.0.
    score: float = 0.0


class SearchGroup(BaseModel):
    type: SearchType
    items: list[SearchItem]


class SearchResponse(BaseModel):
    q: str
    # Engine used for THIS query: "fts5", or "like" (FTS5 absent, or every
    # token shorter than three characters).
    backend: Literal["fts5", "like"]
    groups: list[SearchGroup]
