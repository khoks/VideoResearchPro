"""drop the legacy global subscription columns on channels (S-5.10.3)

Revision ID: 1a6e09517250
Revises: 0b90c419b558
Create Date: 2026-10-19

D-065 moved per-user channel state — `subscribed`, `source_weight`,
`last_synced_at` — into `channel_subscriptions` and left the global columns in
place so a partial rollout stayed recoverable (migration f6a7b8c9d1e2). The
audit for S-5.10.3 found nothing reads them any more; the subscription job was
the last writer and now writes per-tenant state through
`subscription_service`. The columns go.

Downgrade restores them from `channel_subscriptions`, which is the only place
the values now live:

* ``subscribed``     — true if ANY tenant subscribes (the old column was
  global, so "someone follows this channel" is the closest meaning).
* ``last_synced_at`` — the most recent sync by any tenant.
* ``source_weight``  — 1.0. A global weight cannot be rebuilt from several
  tenants' weights without picking a winner, and at every revision that has
  these columns the code reads weights from `channel_subscriptions` (D-068),
  so neutral loses nothing a downgraded app would read.
"""
import sqlalchemy as sa
from alembic import op

revision = "1a6e09517250"
down_revision = "0b90c419b558"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("channels", recreate="always") as batch_op:
        batch_op.drop_column("subscribed")
        batch_op.drop_column("last_synced_at")
        batch_op.drop_column("source_weight")


def downgrade() -> None:
    with op.batch_alter_table("channels", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column("subscribed", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("last_synced_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("source_weight", sa.Float(), nullable=False, server_default="1.0")
        )
    op.execute(
        """
        UPDATE channels SET
            subscribed = COALESCE((
                SELECT MAX(CASE WHEN cs.subscribed THEN 1 ELSE 0 END)
                FROM channel_subscriptions cs WHERE cs.channel_id = channels.channel_id
            ), 0),
            last_synced_at = (
                SELECT MAX(cs.last_synced_at)
                FROM channel_subscriptions cs WHERE cs.channel_id = channels.channel_id
            )
        """
    )
