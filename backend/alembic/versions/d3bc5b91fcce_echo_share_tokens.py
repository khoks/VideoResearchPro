"""echo_share_tokens — scoped, revocable tokens for adding to Echo (S-3.7.3)

Revision ID: d3bc5b91fcce
Revises: 509a4efd9319
Create Date: 2026-10-19

The browser extension adds shares with a token that lasts until revoked and
is accepted only by the share intake endpoints. Only a SHA-256 hash and a
short display prefix are stored. Purely additive.
"""
from alembic import op
import sqlalchemy as sa

revision = "d3bc5b91fcce"
down_revision = "509a4efd9319"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "echo_share_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_echo_share_tokens_tenant", "echo_share_tokens", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_echo_share_tokens_tenant", table_name="echo_share_tokens")
    op.drop_table("echo_share_tokens")
