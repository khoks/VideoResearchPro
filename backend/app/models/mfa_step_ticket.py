"""Second-factor ticket attempts — T-5.4.13.

``POST /auth/login`` (and an OAuth sign-in) hands an account with two-step
verification on a five-minute ticket, a signed JWT
(``mfa_service.issue_mfa_step_token``) that ``POST /auth/login/mfa``
exchanges, with a code, for a session. Until T-5.4.13 the only bound on the
codes one ticket could try was the per-IP sign-in rate limit, so a ticket
could be tried from many addresses.

One row per ticket that has been tried, keyed on the ticket's ``jti``, not
on the caller's IP. ``attempts`` counts the codes checked against it; at
``mfa_service.MFA_TICKET_MAX_ATTEMPTS`` the ticket is dead and sign-in
starts over at the password (or provider) step. ``used_at`` is set when a
code is accepted, so a ticket buys one session. The row is written at the
first attempt, not when the ticket is issued, and rows past ``expires_at``
(the ticket's own ``exp``) are deleted as later attempts come in.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MfaStepTicket(Base):
    __tablename__ = "mfa_step_tickets"

    # The ticket's `jti` claim.
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # The ticket's `exp`, so a sweep can drop rows no ticket can reach.
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # Set when a code was accepted: the ticket has bought its session.
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
