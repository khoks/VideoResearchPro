from datetime import datetime

from pydantic import BaseModel


class DocumentRef(BaseModel):
    id: str
    title: str


class Coverage(BaseModel):
    """How much of the channel the knowledge-derived panels can see."""

    documents: int
    with_knowledge: int
    without_knowledge: int
    ratio: float  # 0..1; 0 when there are no documents
    with_transcript: int


class MonthCount(BaseModel):
    month: str  # "YYYY-MM"
    count: int


class Cadence(BaseModel):
    months: list[MonthCount]  # contiguous, zeros included
    undated: int


class DurationBucket(BaseModel):
    label: str
    min_minutes: float
    max_minutes: float | None
    count: int


class Durations(BaseModel):
    buckets: list[DurationBucket]
    unknown: int
    median_minutes: float | None


class LabelCount(BaseModel):
    label: str
    documents: int  # distinct documents carrying it
    examples: list[DocumentRef]


class Keyword(BaseModel):
    term: str
    weight: float  # 0..1, relative to the top term
    documents: int


class StanceMonth(BaseModel):
    month: str
    counts: dict[str, int]  # stance value -> documents


class Stance(BaseModel):
    """Only where documents carry social classification (D-014); YouTube
    documents carry none, so for most channels this is absent."""

    stance: list[StanceMonth]
    sentiment: list[StanceMonth]
    classified_documents: int


class QAExchangeRef(BaseModel):
    id: str
    kind: str  # "job" | "library"
    question: str
    created_at: datetime | None
    job_id: str | None = None


class QAActivity(BaseModel):
    exchanges: int
    most_cited: list[LabelCount]  # documents of this channel by citing exchanges
    recent: list[QAExchangeRef]


class ChannelIntelligenceResponse(BaseModel):
    channel_id: str
    computed_at: datetime
    cached: bool
    coverage: Coverage
    cadence: Cadence
    durations: Durations
    topics: list[LabelCount]
    concepts: list[LabelCount]
    keywords: list[Keyword]
    stance: Stance | None
    # Why a panel is empty, in the reader's terms. Keyed by panel name.
    notes: dict[str, str]
    qa: QAActivity
