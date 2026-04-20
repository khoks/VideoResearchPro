"""add jobs.channel_list_resolved for subscription jobs

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-20 01:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add `jobs.channel_list_resolved` column.

    Subscription jobs write a JSON-encoded `[{channel_id, name}, ...]` summary
    here after Phase 1 of `execute_subscription_job`. Nullable so existing
    rows (topic/channel jobs) need no backfill.
    """
    op.add_column(
        "jobs",
        sa.Column("channel_list_resolved", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "channel_list_resolved")
