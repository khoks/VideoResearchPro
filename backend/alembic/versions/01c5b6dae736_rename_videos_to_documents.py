"""rename videos table to documents

Revision ID: 01c5b6dae736
Revises: f6a7b8c9d0e1
Create Date: 2026-04-25 10:00:00.000000

L1 PR 4 — pure rename. The schema stays byte-identical; only the parent
table name changes from ``videos`` to ``documents`` so the L1
multi-source vocabulary lines up with the rest of the codebase
(``Document`` model, ``source_type`` discriminator, etc.).

Deliberate non-changes in this PR:
  - The primary key column name stays ``video_id``. Renaming the column
    would cascade through ``job_videos.video_id`` (FK) and
    ``transcript_cache.video_id`` (string column, not a FK), tripling the
    blast radius for no functional gain. A later PR can promote the
    column to ``document_id`` once non-video sources actually need it.
  - ``job_videos`` and its ``video_id`` column keep their names — same
    reasoning.
  - ``transcript_cache.video_id`` is unchanged — it is a non-FK string
    column today, so no rename is required.

The two ``videos``-prefixed indexes are renamed to mirror the new table
name; index names are merely identifiers, so renaming them is cheap and
keeps ``\\d documents`` readable in the future.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "01c5b6dae736"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _drop_index_if_exists(bind: sa.engine.Connection, index_name: str, table_name: str) -> None:
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return
    existing = {ix["name"] for ix in inspector.get_indexes(table_name)}
    if index_name in existing:
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    bind = op.get_bind()

    # SQLite preserves indexes across `ALTER TABLE ... RENAME TO`, so we
    # drop the legacy `videos`-named indexes before the rename and recreate
    # them under the `documents` prefix afterwards. On PostgreSQL we'd just
    # `ALTER INDEX ... RENAME TO`, but the drop+recreate path is portable
    # and equivalent.
    _drop_index_if_exists(bind, "ix_videos_channel_id", "videos")
    _drop_index_if_exists(bind, "ix_videos_source_type_source_id", "videos")

    op.rename_table("videos", "documents")

    op.create_index(
        "ix_documents_channel_id",
        "documents",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        "ix_documents_source_type_source_id",
        "documents",
        ["source_type", "source_id"],
        unique=True,
    )

    # `job_videos.video_id` had a FK to `videos.video_id` on non-SQLite
    # backends (see migration `c3d4e5f6a7b8`). The rename does not move
    # the FK target on PostgreSQL, so re-point it at `documents.video_id`.
    if bind.dialect.name != "sqlite":
        with op.batch_alter_table("job_videos") as batch_op:
            batch_op.drop_constraint("fk_job_videos_video_id", type_="foreignkey")
            batch_op.create_foreign_key(
                "fk_job_videos_video_id",
                "documents",
                ["video_id"],
                ["video_id"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "sqlite":
        with op.batch_alter_table("job_videos") as batch_op:
            batch_op.drop_constraint("fk_job_videos_video_id", type_="foreignkey")

    _drop_index_if_exists(bind, "ix_documents_channel_id", "documents")
    _drop_index_if_exists(bind, "ix_documents_source_type_source_id", "documents")

    op.rename_table("documents", "videos")

    op.create_index(
        "ix_videos_channel_id",
        "videos",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        "ix_videos_source_type_source_id",
        "videos",
        ["source_type", "source_id"],
        unique=True,
    )

    if bind.dialect.name != "sqlite":
        with op.batch_alter_table("job_videos") as batch_op:
            batch_op.create_foreign_key(
                "fk_job_videos_video_id",
                "videos",
                ["video_id"],
                ["video_id"],
                ondelete="CASCADE",
            )
