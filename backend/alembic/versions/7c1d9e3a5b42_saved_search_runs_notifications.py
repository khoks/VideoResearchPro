"""saved_search_runs + notifications (S-8.3.3 / M3)

Revision ID: 7c1d9e3a5b42
Revises: 5d2e8b1f4a60
Create Date: 2026-10-19

Additive. A row per saved-search run (status, change signals, diff), the
first in-app notifications table, and ``saved_searches.last_scope_hash`` (the
gate's fingerprint of the document set the last good run could cite).
Downgrade drops all three.
"""
import sqlalchemy as sa
from alembic import op

revision = "7c1d9e3a5b42"
down_revision = "5d2e8b1f4a60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_search_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("saved_search_id", sa.String(36), sa.ForeignKey("saved_searches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("ran_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("trigger", sa.String(16), nullable=False, server_default="schedule"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("exchange_id", sa.String(36), nullable=True),
        sa.Column("previous_exchange_id", sa.String(36), nullable=True),
        sa.Column("changed", sa.Boolean(), nullable=True),
        sa.Column("jaccard", sa.Float(), nullable=True),
        sa.Column("embedding_distance", sa.Float(), nullable=True),
        sa.Column("decided_by", sa.String(16), nullable=True),
        sa.Column("added_reference_ids_json", sa.Text(), nullable=True),
        sa.Column("dropped_reference_ids_json", sa.Text(), nullable=True),
        sa.Column("diff_summary", sa.Text(), nullable=True),
    )
    op.create_index("ix_saved_search_runs_saved_search_id", "saved_search_runs", ["saved_search_id"])
    op.create_index("ix_saved_search_runs_tenant_id", "saved_search_runs", ["tenant_id"])
    op.create_index("ix_saved_search_runs_ran_at", "saved_search_runs", ["ran_at"])
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("href", sa.String(500), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_tenant_created", "notifications", ["tenant_id", "created_at"])
    with op.batch_alter_table("saved_searches") as batch:
        batch.add_column(sa.Column("last_scope_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("saved_searches") as batch:
        batch.drop_column("last_scope_hash")
    op.drop_index("ix_notifications_tenant_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_saved_search_runs_ran_at", table_name="saved_search_runs")
    op.drop_index("ix_saved_search_runs_tenant_id", table_name="saved_search_runs")
    op.drop_index("ix_saved_search_runs_saved_search_id", table_name="saved_search_runs")
    op.drop_table("saved_search_runs")
