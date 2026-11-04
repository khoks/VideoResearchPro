"""jobs.published_after_days — a relative publish window (S-8.6.3 / D-112)

Revision ID: b84e405ab989
Revises: 6d5b3d5aa6fa
Create Date: 2026-11-04

NULL means no preference, so existing jobs keep exactly today's ranking
prompt. Days, not a date: the search agent turns it into a date when the run
ranks, which is what lets a template mean "the last 30 days" for as long as it
is used. A ranking preference, never a filter (D-059, D-072). Purely additive.
"""
import sqlalchemy as sa
from alembic import op

revision = "b84e405ab989"
down_revision = "6d5b3d5aa6fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("published_after_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "published_after_days")
