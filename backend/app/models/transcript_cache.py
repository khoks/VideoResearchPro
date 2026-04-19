from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TranscriptCache(Base):
    """Cache of fetched transcripts keyed by YouTube video_id.

    Transcripts rarely change for a given video, so caching avoids repeated
    YouTube Transcript API calls and Whisper transcriptions across jobs.
    """

    __tablename__ = "transcript_cache"

    video_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    segments_json: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
