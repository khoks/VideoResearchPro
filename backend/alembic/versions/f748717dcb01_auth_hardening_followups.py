"""auth hardening follow-ups: users.has_password (T-5.4.14), mfa_step_tickets (T-5.4.13)

Revision ID: f748717dcb01
Revises: a68953e57c63
Create Date: 2026-11-04

Two additive changes:

* ``users.has_password`` (NOT NULL, default true): whether the account
  holder knows a password. ``POST /auth/password/change`` asks for the
  current one, which an account Google or GitHub sign-in created has never
  had (it was given a random hash nobody knows), so such an account is told
  to use the reset flow instead.

  Backfill: an account is marked as having no password when an OAuth
  identity was linked to it within ``OAUTH_CREATED_WINDOW`` of the account
  being created (``oauth_service._link_or_create_user`` creates the user and
  links the identity in one request, milliseconds apart; linking to an
  account that already existed happens at a later sign-in), unless
  ``audit_log`` says otherwise: ``user_registered`` is written only by
  POST /auth/register, so that account chose a password even if Google
  followed within the window, and a completed password reset gave one to
  an account that had none. The flag only decides what the change-password
  route answers: sign-in never reads it, so a wrong guess here costs a user
  nothing but a pointer to the reset flow.

* ``mfa_step_tickets``: one row per second-factor ticket that has been
  tried, keyed on the ticket's ``jti``, counting the codes checked against
  it so ``POST /auth/login/mfa`` can stop a ticket after
  ``mfa_service.MFA_TICKET_MAX_ATTEMPTS``.

**Reversible:** ``downgrade()`` drops the table and the column.
"""
from datetime import datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision = "f748717dcb01"
down_revision = "a68953e57c63"
branch_labels = None
depends_on = None

OAUTH_CREATED_WINDOW = timedelta(seconds=60)


def _parse(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except ValueError:
        return None


def _oauth_created_accounts(bind) -> list[str]:
    """Ids of accounts an OAuth sign-in created whose holder never set a
    password since: linked within the window, and no audit event that
    says the account has a password. Compared in Python, not SQL, so it
    does not depend on the database's date functions."""
    created = {row[0]: _parse(row[1]) for row in bind.execute(sa.text("SELECT id, created_at FROM users"))}
    first_link: dict[str, datetime] = {}
    for user_id, linked_at in bind.execute(sa.text("SELECT user_id, created_at FROM oauth_identities")):
        when = _parse(linked_at)
        if when is not None and (user_id not in first_link or when < first_link[user_id]):
            first_link[user_id] = when
    set_a_password = {
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT DISTINCT user_id FROM audit_log "
                "WHERE event IN ('user_registered', 'password_reset_completed') "
                "AND user_id IS NOT NULL"
            )
        )
    }
    out = []
    for user_id, linked_at in first_link.items():
        made = created.get(user_id)
        if made is None or user_id in set_a_password:
            continue
        if abs(linked_at - made) <= OAUTH_CREATED_WINDOW:
            out.append(user_id)
    return sorted(out)


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("has_password", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    bind = op.get_bind()
    users = sa.table("users", sa.column("id", sa.String), sa.column("has_password", sa.Boolean))
    for user_id in _oauth_created_accounts(bind):
        bind.execute(users.update().where(users.c.id == user_id).values(has_password=False))

    op.create_table(
        "mfa_step_tickets",
        sa.Column("jti", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_mfa_step_tickets_user_id", "mfa_step_tickets", ["user_id"])
    op.create_index("ix_mfa_step_tickets_expires_at", "mfa_step_tickets", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_mfa_step_tickets_expires_at", table_name="mfa_step_tickets")
    op.drop_index("ix_mfa_step_tickets_user_id", table_name="mfa_step_tickets")
    op.drop_table("mfa_step_tickets")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("has_password")
