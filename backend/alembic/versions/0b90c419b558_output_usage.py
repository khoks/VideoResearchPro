"""outputs.usage_json: what generating an output cost (S-6.1.3)

Revision ID: 0b90c419b558
Revises: 3f8a1c2d9b7e
Create Date: 2026-10-19

The book cohesion pass is the first outputter that calls a model. Each call's
use case, model, tokens and cost are kept on the row so the page can show
what a book cost and the measurement can be read back. Nullable; outputs
made without a model call leave it empty.
"""
import sqlalchemy as sa
from alembic import op

revision = "0b90c419b558"
down_revision = "3f8a1c2d9b7e"  # re-parented onto S-8.4.1 (merged first)
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("outputs") as batch:
        batch.add_column(sa.Column("usage_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("outputs") as batch:
        batch.drop_column("usage_json")
