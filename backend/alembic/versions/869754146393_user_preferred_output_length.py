"""users.preferred_output_length: one person's default depth (T-1.15.3.9)

Revision ID: 869754146393
Revises: 8e4b1f6c2a37
Create Date: 2026-11-04

One additive, nullable column. NULL is Auto, which is every account until its
holder picks something, so nothing is backfilled and no request changes.

**Reversible:** ``downgrade()`` drops the column, and with it what people chose.
"""
import sqlalchemy as sa
from alembic import op

revision = "869754146393"
down_revision = "8e4b1f6c2a37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("preferred_output_length", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("preferred_output_length")
