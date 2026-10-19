"""channel_intelligence_cache — per-tenant channel aggregate cache (S-8.7.2 / E-8.7)

Revision ID: b4c5d6e7f8a0
Revises: a3b4c5d6e7f9
Create Date: 2026-10-19

Additive. One row per (channel, tenant): the document-derived aggregate and
the fingerprint of the inputs it was computed from. A cache, not a record:
downgrade drops it and the next request recomputes.
"""
import sqlalchemy as sa
from alembic import op

revision = "b4c5d6e7f8a0"
down_revision = "a3b4c5d6e7f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_intelligence_cache",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "channel_id",
            sa.String(50),
            sa.ForeignKey("channels.channel_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("channel_id", "tenant_id", name="uq_channel_intelligence_tenant"),
    )
    op.create_index(
        "ix_channel_intelligence_cache_tenant_id", "channel_intelligence_cache", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_channel_intelligence_cache_tenant_id", table_name="channel_intelligence_cache")
    op.drop_table("channel_intelligence_cache")
