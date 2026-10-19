"""documents.discussed_era_json — the era a source DISCUSSES (R3 / S-1.17.2)

Revision ID: b1a2c3d4e5f8
Revises: a7b8c9d1e2f3
Create Date: 2026-10-18

`published_at` says when a source was posted. This column says which period
it talks about — a 2026 video about a 2019 paper is a 2026 source about a
2019 event, and nothing in the pipeline could tell those apart. Written once
per document by the `temporal_scope_extract` use case the first time a job
touches the document; NULL means "not extracted yet", which every reader
treats as unknown rather than as "discusses now".

Purely additive. No backfill: existing rows gain the value lazily the next
time any job re-chunks them.
"""
from alembic import op
import sqlalchemy as sa

revision = "b1a2c3d4e5f8"
down_revision = "a7b8c9d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("discussed_era_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("discussed_era_json")
