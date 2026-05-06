"""PersonalContext model — I-3 Echo foundation (E-3.1).

Append-only-ish ledger of facts about a user that aren't sourced
content. Distinct from the global library (which holds public-ish
sources like videos / podcasts / articles): this table stores
**identity-and-life data** — interests, hobbies, work, talents,
skills, personality traits, life events, locations, daily routines.

Scope (v1):
- One row per `(user_id, kind, key)` is unique. Re-recording the same
  fact updates the row's value + ``captured_at`` + ``confidence``.
  ``expires_at`` lets stale facts age out (e.g. "current employer"
  expires after 6 months without re-confirmation).
- Each row carries a ``source`` indicating where it came from:
  ``manual`` (user typed it in), ``youtube_watch_history``,
  ``spotify_history``, ``email`` (read-only OAuth), ``calendar``,
  ``browser_history``, etc. The set is open — connectors register
  their own source name.
- ``confidence`` is a 0-1 float. Manual entries default to 1.0;
  inferred ones get whatever confidence the connector reports.
- Privacy posture: every connector is opt-in + revocable; revocation
  deletes the user's rows from this table where ``source = <connector>``.

Out of scope for v1:
- Embedding the value for semantic search (would need its own
  index; deferred to E-3.3 voice & style capture).
- Cross-user analytics (Echo is strictly per-user; no aggregation).
- Inference / derivation rules (no auto-promotion of "watched
  cooking videos 50 times" → "interest:cooking" yet — connectors
  produce raw rows; promotion is a future ETL).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PersonalContext(Base):
    __tablename__ = "personal_context"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "kind",
            "key",
            name="uq_personal_context_user_kind_key",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    # One of: location, interest, hobby, work, talent, skill,
    # personality_trait, life_event, daily_routine, place. The service
    # registry validates known kinds; unknown kinds are accepted but
    # rejected at the API surface.
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # The specific key under that kind. E.g. kind="interest" key="cooking",
    # kind="work" key="current_employer", kind="personality_trait" key="introversion_score".
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Free-form value (TEXT so structured payloads can JSON-encode in here
    # without an extra column).
    value: Mapped[str] = mapped_column(Text, nullable=False)
    # Where this row came from. Connectors register their own source.
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # When the fact stops being trustworthy without re-confirmation.
    # NULL = no expiry. Used for "current employer" / "current location"
    # types.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
