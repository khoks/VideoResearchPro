"""usage_records — per-tenant daily usage by feature (E-5.2, status plan item 10)

Revision ID: 6cf03630d943
Revises: 066d3f4b4d4d
Create Date: 2026-11-03

Additive. One row per (tenant_id, day, feature, metric): LLM tokens in and
out, LLM calls, and YouTube Data API units, recorded for every user-triggered
path. Nothing is enforced from it (D-111). The daily totals in quota_usage
are unchanged; this is the breakdown beside them.

**Reversible:** downgrade() drops the table.
"""
import sqlalchemy as sa
from alembic import op

revision = "6cf03630d943"
down_revision = "066d3f4b4d4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("feature", sa.String(length=40), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "day", "feature", "metric", name="uq_usage_records_bucket"),
    )
    op.create_index("ix_usage_records_tenant_day", "usage_records", ["tenant_id", "day"])


def downgrade() -> None:
    op.drop_index("ix_usage_records_tenant_day", table_name="usage_records")
    op.drop_table("usage_records")
