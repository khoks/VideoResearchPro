"""jobs.output_length — optional user override of report depth (R4 / D-064)

Revision ID: e5f6a7b8c9d1
Revises: d4e5f6a7b8c0
Create Date: 2026-07-31

NULL means 'auto' — the corpus bracket decides. Existing jobs keep NULL and
therefore keep exactly today's behaviour.
"""
import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d1"
down_revision = "d4e5f6a7b8c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("output_length", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "output_length")
