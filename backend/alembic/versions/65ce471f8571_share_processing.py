"""shares_inbox.processing_json — what processing found (S-3.7.2)

Revision ID: 65ce471f8571
Revises: 1a6e09517250
Create Date: 2026-10-19

`raw_payload_json` records what arrived and never changes. This column
records what processing made of it: the resolved title and author, which
path extracted the text, the failure reason, whether the share can be
offered to the library, and when processing ran. NULL means "not processed
yet". Purely additive.
"""
from alembic import op
import sqlalchemy as sa

revision = "65ce471f8571"
down_revision = "1a6e09517250"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shares_inbox") as batch:
        batch.add_column(sa.Column("processing_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("shares_inbox") as batch:
        batch.drop_column("processing_json")
