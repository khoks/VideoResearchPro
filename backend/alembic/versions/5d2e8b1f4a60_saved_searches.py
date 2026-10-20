"""saved_searches — pinned library questions (S-8.3.2 / M3)

Revision ID: 5d2e8b1f4a60
Revises: cd4c5467506d
Create Date: 2026-10-19

Additive. One row per pinned question; its schedule is a ``scheduled_runs``
row of kind ``saved_search`` (S-8.3.1). Downgrade drops the table; the
scheduled rows of that kind are removed too, so the tick does not dispatch
work whose target no longer exists.
"""
import sqlalchemy as sa
from alembic import op

revision = "5d2e8b1f4a60"
down_revision = "cd4c5467506d"  # re-parented onto S-8.1.4 (merged first)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_searches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("scope_json", sa.Text(), nullable=True),
        sa.Column("notify_email", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_exchange_id", sa.String(36), nullable=True),
        sa.Column("last_answer_hash", sa.String(64), nullable=True),
        sa.Column("last_reference_ids_json", sa.Text(), nullable=True),
        sa.Column("last_answer_embedding_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_saved_searches_tenant_id", "saved_searches", ["tenant_id"])


def downgrade() -> None:
    op.execute("DELETE FROM scheduled_runs WHERE kind = 'saved_search'")
    op.drop_index("ix_saved_searches_tenant_id", table_name="saved_searches")
    op.drop_table("saved_searches")
