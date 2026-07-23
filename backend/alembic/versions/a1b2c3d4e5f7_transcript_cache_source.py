"""transcript_cache.source provenance column (S-1.11.4 / D-051)

Adds a nullable ``source`` column recording which path produced each
cached transcript ("youtube" caption fetch vs "whisper" transcription).
Pre-existing rows stay NULL and are read as "youtube" — the dominant
writer before this migration (the Whisper path existed but its rows are
indistinguishable retroactively).

Revision ID: a1b2c3d4e5f7
Revises: b5c6d7e8f9a0
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f7"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transcript_cache",
        sa.Column("source", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transcript_cache", "source")
