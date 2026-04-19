"""add search_queries_used to jobs

Revision ID: 7a1c9e3b4f20
Revises: 23670b97ba39
Create Date: 2026-04-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7a1c9e3b4f20"
down_revision: Union[str, None] = "23670b97ba39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("search_queries_used", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "search_queries_used")
