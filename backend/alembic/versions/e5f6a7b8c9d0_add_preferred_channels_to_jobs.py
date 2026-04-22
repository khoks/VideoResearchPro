"""add preferred_channels to jobs

Revision ID: e5f6a7b8c9d0
Revises: 391da9d50ccd
Create Date: 2026-04-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "391da9d50ccd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("preferred_channels", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "preferred_channels")
