"""echo_drafts.written_words — how many words the user typed into a draft (S-3.4.2)

Revision ID: e5a9c3d7b2f4
Revises: b7e2c4a9d1f6
Create Date: 2026-10-20

Additive, nullable (no feedback yet). Signal extraction's cheap new-input
counter reads it, so an edit too small to learn from never queues a run.
"""
import sqlalchemy as sa
from alembic import op

revision = "e5a9c3d7b2f4"
down_revision = "b7e2c4a9d1f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("echo_drafts") as batch:
        batch.add_column(sa.Column("written_words", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("echo_drafts") as batch:
        batch.drop_column("written_words")
