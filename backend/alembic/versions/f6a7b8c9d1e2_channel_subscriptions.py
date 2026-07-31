"""channel_subscriptions — per-tenant subscription state (D-065)

Revision ID: f6a7b8c9d1e2
Revises: e5f6a7b8c9d1
Create Date: 2026-07-31

Backfill: existing `channels.subscribed` rows are attributed to the tenants
who can actually see documents from that channel (via document_visibility).
Channels with no visible documents cannot be attributed to anyone and are
left unsubscribed — the safe direction, and reversible by re-subscribing.

The legacy columns on `channels` are LEFT IN PLACE rather than dropped: they
are read by code paths not yet migrated, and dropping them in the same
revision would make a partial rollout unrecoverable. A follow-up removes them
once nothing reads them (S-5.10.3).
"""
import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d1e2"
down_revision = "e5f6a7b8c9d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "channel_id",
            sa.String(50),
            sa.ForeignKey("channels.channel_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("subscribed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("source_weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("channel_id", "tenant_id", name="uq_channel_subscription"),
    )
    op.create_index("ix_channel_subscriptions_channel_id", "channel_subscriptions", ["channel_id"])
    op.create_index("ix_channel_subscriptions_tenant_id", "channel_subscriptions", ["tenant_id"])
    op.create_index(
        "ix_channel_subscriptions_tenant_channel",
        "channel_subscriptions",
        ["tenant_id", "channel_id"],
    )

    # Attribute each channel's state to every tenant with visibility on one of
    # its documents. GROUP BY keeps the unique constraint satisfied.
    op.execute(
        """
        INSERT INTO channel_subscriptions
            (id, channel_id, tenant_id, subscribed, source_weight, last_synced_at, created_at)
        SELECT lower(hex(randomblob(16))), c.channel_id, v.tenant_id,
               c.subscribed, c.source_weight, c.last_synced_at, CURRENT_TIMESTAMP
        FROM channels c
        JOIN documents d ON d.channel_id = c.channel_id
        JOIN document_visibility v ON v.video_id = d.video_id
        GROUP BY c.channel_id, v.tenant_id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_channel_subscriptions_tenant_channel", table_name="channel_subscriptions")
    op.drop_index("ix_channel_subscriptions_tenant_id", table_name="channel_subscriptions")
    op.drop_index("ix_channel_subscriptions_channel_id", table_name="channel_subscriptions")
    op.drop_table("channel_subscriptions")
