"""Response shape of ``GET /api/v1/usage`` (E-5.2)."""
from datetime import date

from pydantic import BaseModel


class UsageAmounts(BaseModel):
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    llm_calls: int = 0
    youtube_units: int = 0
    whisper_seconds: int = 0


class UsageFeatureRow(BaseModel):
    feature: str
    label: str
    today: UsageAmounts
    last_30_days: UsageAmounts


class UsageTotals(BaseModel):
    today: UsageAmounts
    last_30_days: UsageAmounts


class UsageSummaryResponse(BaseModel):
    """The signed-in user's own usage. Recorded, never limited (D-111)."""

    today: date
    window_start: date
    window_days: int
    # The first day anything was recorded for this user; None before then.
    metered_since: date | None
    features: list[UsageFeatureRow]
    totals: UsageTotals
