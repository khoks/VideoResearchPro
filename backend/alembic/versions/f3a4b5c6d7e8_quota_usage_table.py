"""T-5.5.5 / T-5.2.5 quota metering — quota_usage table

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-05-05 14:00:00.000000

Per [E-5.2 / E-5.5 in initiatives.md](docs/initiatives.md#i-5--saas-readiness-long-horizon),
this migration adds the `quota_usage` table — per-user, per-resource,
per-period consumption ledger. The composite
``(user_id, resource, period_kind, period_start)`` is unique;
``consumed`` is incremented atomically per resource event.

**Reversible:** ``downgrade()`` drops the table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quota_usage",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("resource", sa.String(length=64), nullable=False),
        sa.Column("period_kind", sa.String(length=16), nullable=False),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column(
            "consumed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "resource",
            "period_kind",
            "period_start",
            name="uq_quota_usage_user_resource_period",
        ),
    )
    op.create_index(
        "ix_quota_usage_user_id", "quota_usage", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_quota_usage_user_id", table_name="quota_usage")
    op.drop_table("quota_usage")
