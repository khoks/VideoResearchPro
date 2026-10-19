from typing import Any

from pydantic import BaseModel


class GraphNode(BaseModel):
    """`id` is stable across requests: `document:<document_id>`,
    `channel:<channel_id>`, `topic:<lowercased label>`,
    `exchange:<job|library>:<exchange_id>`."""

    id: str
    type: str  # document | channel | topic | exchange
    label: str
    degree: int
    meta: dict[str, Any] = {}


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str  # published_by | about | cites | co_occurs
    weight: int = 1


class GraphCounts(BaseModel):
    documents: int
    channels: int
    topics: int
    exchanges: int


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    # True when the cap or the focus left nodes out.
    truncated: bool
    # Every node and edge before the cap, by type, for "showing N of M".
    total: GraphCounts
    shown: GraphCounts
    # One paragraph describing the graph: the textual alternative to the canvas.
    summary: str
    focus: str | None = None
