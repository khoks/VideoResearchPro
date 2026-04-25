"""add multi-source ingest columns to videos and channels

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-04-24 12:00:00.000000

L1 PR 1 — additive schema only. Introduces the source-type discriminator
and supporting columns described in `docs/source-types.md` so the existing
`videos` table can host non-video sources (podcasts, articles, threads,
PDFs, etc.) in subsequent PRs without another migration.

This migration is intentionally conservative:
  - new columns are added, never renamed or dropped
  - `source_type` defaults to `'video'` for every existing row
  - `source_id` and `creator_external_id` are backfilled from the existing
    primary keys (`videos.video_id`, `channels.channel_id`)
  - `duration_seconds` becomes nullable so non-video sources can omit it
  - a unique `(source_type, source_id)` index supersedes the implicit
    YouTube-only uniqueness for cross-source dedup
  - the `videos`/`channels` table names are preserved; the documents/creators
    rename is deferred to a later PR
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- videos: add nullable columns + relax duration_seconds ---
    with op.batch_alter_table("videos") as batch_op:
        batch_op.add_column(
            sa.Column(
                "source_type",
                sa.String(length=20),
                nullable=False,
                server_default="video",
            )
        )
        batch_op.add_column(sa.Column("source_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("source_url", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("source_metadata_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("language", sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column("word_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("user_provenance_json", sa.Text(), nullable=True))
        batch_op.alter_column(
            "duration_seconds",
            existing_type=sa.Integer(),
            nullable=True,
        )

    # Backfill: existing rows are all YouTube videos.
    bind.execute(
        sa.text(
            """
            UPDATE videos
            SET source_id = video_id,
                source_url = COALESCE(source_url, url),
                language = COALESCE(language, transcript_language),
                word_count = COALESCE(word_count, transcript_word_count)
            WHERE source_id IS NULL
            """
        )
    )

    with op.batch_alter_table("videos") as batch_op:
        batch_op.alter_column(
            "source_id",
            existing_type=sa.String(length=255),
            nullable=False,
        )

    op.create_index(
        "ix_videos_source_type_source_id",
        "videos",
        ["source_type", "source_id"],
        unique=True,
    )

    # --- channels: add creator-shaped columns; preserve table name ---
    with op.batch_alter_table("channels") as batch_op:
        batch_op.add_column(
            sa.Column(
                "source_type",
                sa.String(length=20),
                nullable=False,
                server_default="video",
            )
        )
        batch_op.add_column(
            sa.Column("creator_external_id", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "source_weight",
                sa.Float(),
                nullable=False,
                server_default="1.0",
            )
        )
        batch_op.add_column(sa.Column("creator_metadata_json", sa.Text(), nullable=True))

    bind.execute(
        sa.text(
            """
            UPDATE channels
            SET creator_external_id = channel_id
            WHERE creator_external_id IS NULL
            """
        )
    )

    with op.batch_alter_table("channels") as batch_op:
        batch_op.alter_column(
            "creator_external_id",
            existing_type=sa.String(length=100),
            nullable=False,
        )


def downgrade() -> None:
    op.drop_index("ix_videos_source_type_source_id", table_name="videos")

    with op.batch_alter_table("videos") as batch_op:
        batch_op.alter_column(
            "duration_seconds",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.drop_column("user_provenance_json")
        batch_op.drop_column("word_count")
        batch_op.drop_column("language")
        batch_op.drop_column("source_metadata_json")
        batch_op.drop_column("source_url")
        batch_op.drop_column("source_id")
        batch_op.drop_column("source_type")

    with op.batch_alter_table("channels") as batch_op:
        batch_op.drop_column("creator_metadata_json")
        batch_op.drop_column("source_weight")
        batch_op.drop_column("creator_external_id")
        batch_op.drop_column("source_type")
