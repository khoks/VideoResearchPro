"""Per-user LLM use-case overrides — E-1.13.

One row per (user, use_case): the user's chosen (provider, model,
reasoning) triple, overriding the registry default for THEIR runs only.
Loaded into a ContextVar alongside BYOK credentials at request/task
entry (see ``llm_service.byok_context``) and consulted first by
``llm_routing.resolve_config``.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserLLMOverride(Base):
    __tablename__ = "user_llm_overrides"
    __table_args__ = (
        UniqueConstraint("user_id", "use_case", name="uq_user_llm_override"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    use_case: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(128))
    reasoning: Mapped[str] = mapped_column(String(16), default="off")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
