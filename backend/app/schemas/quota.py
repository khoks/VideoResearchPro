from pydantic import BaseModel


class QuotaStatus(BaseModel):
    """Today's YouTube Data API v3 quota usage snapshot."""

    date: str
    used: int
    daily_limit: int
    remaining: int
