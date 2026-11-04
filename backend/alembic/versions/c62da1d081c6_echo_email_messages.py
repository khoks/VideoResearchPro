"""echo_email_messages: the mail the IMAP inbox has already taken (T-3.7.4.1)

Revision ID: c62da1d081c6
Revises: 6d5b3d5aa6fa
Create Date: 2026-11-04

One additive table, so a re-poll of a mailbox adds nothing and a share the
user deleted does not come back. See ``app/models/echo_email_message.py``.

**Reversible:** ``downgrade()`` drops the table. The shares themselves are
untouched; a mailbox polled after a downgrade relies on the read flag alone.
"""
import sqlalchemy as sa
from alembic import op

revision = "c62da1d081c6"
down_revision = "6d5b3d5aa6fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "echo_email_messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("message_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "message_key", name="uq_echo_email_messages"),
    )
    op.create_index("ix_echo_email_messages_tenant_id", "echo_email_messages", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_echo_email_messages_tenant_id", table_name="echo_email_messages")
    op.drop_table("echo_email_messages")
