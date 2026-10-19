"""document_visibility keyed on document_id, not the legacy video_id

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-10-19

S-5.10.4 / D-070. ``document_visibility.video_id`` referenced
``documents.video_id`` — the nullable back-compat YouTube-id column that is
NULL for every non-video source — so a grant for an uploaded PDF or a pasted
page was never written and those documents were visible to nobody. The grant
now references the real primary key, ``documents.document_id``.

Upgrade: add ``document_id``, backfill it by joining ``documents`` on
``video_id``, drop grants whose document no longer exists (the FK was never
enforced on SQLite, so such rows can exist), move the unique constraint to
``(document_id, tenant_id)`` and retire ``video_id``. SQLite cannot drop a
column that carries constraints, so the table is rebuilt in batch mode.

Downgrade: restore ``video_id`` from the same join. Grants over non-video
documents cannot be represented by the old schema and are DELETED on
downgrade — the pre-D-070 state is exactly "non-video documents are invisible",
so this loses nothing the old code could read, but it is data loss relative
to head and is logged with a count.
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = "d8e9f0a1b2c3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_TABLE = "document_visibility"
_UQ = "uq_document_visibility"
_FK_DOCUMENT = "fk_document_visibility_document_id"
_FK_VIDEO = "fk_document_visibility_video_id"


def _scalar(sql: str) -> int:
    row = op.get_bind().execute(sa.text(sql)).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("document_id", sa.String(36), nullable=True))

    # Backfill from the documents table. Only video rows can match — for
    # every other source_type the legacy column is NULL, which is the bug
    # this migration exists to fix.
    op.execute(
        f"""
        UPDATE {_TABLE}
        SET document_id = (
            SELECT d.document_id FROM documents d
            WHERE d.video_id = {_TABLE}.video_id AND d.video_id IS NOT NULL
        )
        WHERE document_id IS NULL
        """
    )
    orphans = _scalar(f"SELECT COUNT(*) FROM {_TABLE} WHERE document_id IS NULL")
    if orphans:
        logger.warning(
            "document_visibility: dropping %d grant(s) whose document no longer "
            "exists (video_id had no matching documents row)",
            orphans,
        )
        op.execute(f"DELETE FROM {_TABLE} WHERE document_id IS NULL")
    total = _scalar(f"SELECT COUNT(*) FROM {_TABLE}")
    logger.info("document_visibility: %d grant(s) re-keyed on document_id", total)

    # Indexes on the column being retired must go before the table rebuild;
    # batch mode does not drop them on our behalf.
    op.drop_index("ix_document_visibility_tenant_video", table_name=_TABLE)
    op.drop_index("ix_document_visibility_video_id", table_name=_TABLE)

    # SQLite: rebuild the table. Dropping `video_id` takes its (unnamed) FK
    # and the unique constraint with it; the new constraints are named so
    # the downgrade can address them.
    with op.batch_alter_table(_TABLE, recreate="always") as batch_op:
        batch_op.drop_constraint(_UQ, type_="unique")
        batch_op.drop_column("video_id")
        batch_op.alter_column("document_id", existing_type=sa.String(36), nullable=False)
        batch_op.create_foreign_key(
            _FK_DOCUMENT, "documents", ["document_id"], ["document_id"], ondelete="CASCADE"
        )
        batch_op.create_unique_constraint(_UQ, ["document_id", "tenant_id"])

    op.create_index("ix_document_visibility_document_id", _TABLE, ["document_id"])
    op.create_index(
        "ix_document_visibility_tenant_document", _TABLE, ["tenant_id", "document_id"]
    )


def downgrade() -> None:
    op.add_column(_TABLE, sa.Column("video_id", sa.String(64), nullable=True))
    op.execute(
        f"""
        UPDATE {_TABLE}
        SET video_id = (
            SELECT d.video_id FROM documents d
            WHERE d.document_id = {_TABLE}.document_id
        )
        WHERE video_id IS NULL
        """
    )
    non_video = _scalar(f"SELECT COUNT(*) FROM {_TABLE} WHERE video_id IS NULL")
    if non_video:
        logger.warning(
            "document_visibility: downgrade drops %d grant(s) over non-video "
            "documents — the video_id schema cannot represent them",
            non_video,
        )
        op.execute(f"DELETE FROM {_TABLE} WHERE video_id IS NULL")

    op.drop_index("ix_document_visibility_tenant_document", table_name=_TABLE)
    op.drop_index("ix_document_visibility_document_id", table_name=_TABLE)

    with op.batch_alter_table(_TABLE, recreate="always") as batch_op:
        batch_op.drop_constraint(_UQ, type_="unique")
        batch_op.drop_constraint(_FK_DOCUMENT, type_="foreignkey")
        batch_op.drop_column("document_id")
        batch_op.alter_column("video_id", existing_type=sa.String(64), nullable=False)
        batch_op.create_foreign_key(
            _FK_VIDEO, "documents", ["video_id"], ["video_id"], ondelete="CASCADE"
        )
        batch_op.create_unique_constraint(_UQ, ["video_id", "tenant_id"])

    op.create_index("ix_document_visibility_video_id", _TABLE, ["video_id"])
    op.create_index(
        "ix_document_visibility_tenant_video", _TABLE, ["tenant_id", "video_id"]
    )
