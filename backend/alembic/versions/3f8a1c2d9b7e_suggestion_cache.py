"""suggestion_cache — per-tenant question-suggestion cache (S-8.4.1 / M4)

Revision ID: 3f8a1c2d9b7e
Revises: e8667092c208
Create Date: 2026-10-19

Additive. One row per (tenant, context): the suggestions computed for it and
the fingerprint of the inputs. A cache, not a record: downgrade drops it and
the next request recomputes.
"""
import sqlalchemy as sa
from alembic import op

revision = "3f8a1c2d9b7e"
down_revision = "e8667092c208"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suggestion_cache",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("context_key", sa.String(120), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "context_key", name="uq_suggestion_cache_context"),
    )
    op.create_index("ix_suggestion_cache_tenant_id", "suggestion_cache", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_suggestion_cache_tenant_id", table_name="suggestion_cache")
    op.drop_table("suggestion_cache")
