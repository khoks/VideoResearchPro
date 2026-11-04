"""echo_fact_tombstones — derived facts the user deleted stay deleted (T-3.2.4.4)

Revision ID: a68953e57c63
Revises: 066d3f4b4d4d
Create Date: 2026-11-03

One row per (tenant, connector, kind, key) the user deleted, so a connector
sync or a re-import skips that key instead of re-creating it (D-110).
Purely additive.
"""
from alembic import op
import sqlalchemy as sa

revision = "a68953e57c63"
down_revision = "066d3f4b4d4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "echo_fact_tombstones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("connector", sa.String(48), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "connector", "kind", "key", name="uq_echo_fact_tombstones"),
    )
    op.create_index("ix_echo_fact_tombstones_tenant_id", "echo_fact_tombstones", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_echo_fact_tombstones_tenant_id", table_name="echo_fact_tombstones")
    op.drop_table("echo_fact_tombstones")
