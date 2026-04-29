"""add document_id UUID column to documents

Revision ID: d12345678901
Revises: 01c5b6dae736, b8c9d0e1f2a3
Create Date: 2026-04-28 10:00:00.000000

E-1.10 T-1.10.1 — first migration in the UUID-PK promotion sequence
(D-015 + D-017 hard cutover).

This migration also serves as a **merge node** for the two parallel
heads that have lived in the migration graph since L1 PR-1 (the
``b8c9d0e1f2a3 → a7b8c9d0e1f2 → f6a7b8c9d0e1`` multi-source/knowledge
chain) and L1 PR-4 (the ``01c5b6dae736 → f6a7b8c9d0e1`` videos →
documents rename). Both chains share ``f6a7b8c9d0e1`` as a common
ancestor; in production, both were applied (the schema reflects
multi-source columns AND the documents rename) but Alembic's metadata
still saw two heads. This migration joins them by listing both as
``down_revision``, restoring a single linear head for future PRs in
the E-1.10 series.

The merge does no DDL of its own beyond the additive document_id
column — the body remains the original T-1.10.1 work.

Additive scope: it adds a new ``document_id`` column populated with
fresh UUIDs for every existing row. Subsequent migrations in the
E-1.10 series will:

  * T-1.10.2 — drop the legacy ``video_id`` PK and add the
    ``(source_type, source_id)`` unique constraint as the new
    composite identity, retargeting ``job_videos`` and
    ``transcript_cache`` FKs onto ``document_id``.
  * T-1.10.3 — flip the ORM PK to ``document_id`` and re-point
    relationships.
  * T-1.10.4..T-1.10.7 — rename / retarget remaining tables and
    Chroma chunk metadata.
  * T-1.10.8 — round-trip migration test + e2e smoke (gating).

The column is added as ``nullable=True`` so the migration can run
against the existing 912 production rows without violating NOT NULL.
A Python-side backfill populates every row with a newly generated
UUID4 (rendered as a 36-char hex-with-dashes string for SQLite
portability — Postgres deployments can re-type to UUID natively in
T-1.10.2). After the backfill, ``document_id`` is altered to NOT
NULL.

Why CHAR(36) and not BLOB(16)? The project ships SQLite primarily
and the human-readable hex form is friendlier in ad-hoc DB queries
during the cutover; the ~3x storage overhead is negligible at our
scale (~912 rows today, projected sub-million for the foreseeable
future).

Reversibility: the ``downgrade()`` path drops the column. Reversible
in isolation.
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d12345678901"
down_revision: Union[str, Sequence[str], None] = ("01c5b6dae736", "b8c9d0e1f2a3")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add as nullable so the migration runs cleanly against existing
    #    rows. The NOT NULL constraint follows the backfill.
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(
            sa.Column("document_id", sa.String(length=36), nullable=True)
        )

    # 2. Backfill: one UUID4 per existing row. We iterate Python-side
    #    rather than relying on a DB-native UUID generator because
    #    SQLite has none, and we want the migration to behave
    #    identically across SQLite and Postgres.
    documents_table = sa.Table(
        "documents",
        sa.MetaData(),
        sa.Column("video_id", sa.String(20), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=True),
    )
    rows = bind.execute(sa.select(documents_table.c.video_id)).fetchall()
    for row in rows:
        bind.execute(
            sa.update(documents_table)
            .where(documents_table.c.video_id == row[0])
            .values(document_id=str(uuid.uuid4()))
        )

    # 3. Now that every row has a document_id, enforce NOT NULL. Use
    #    batch_alter_table for SQLite's no-ALTER-COLUMN-NOT-NULL
    #    constraint — Alembic handles the table-rebuild dance.
    with op.batch_alter_table("documents") as batch_op:
        batch_op.alter_column(
            "document_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )

    # 4. Add a unique index so we have an immediate query path on
    #    document_id (not a PK yet — that's T-1.10.2). The unique
    #    constraint also catches accidental duplicates if anyone
    #    inserts a hand-rolled UUID later.
    op.create_index(
        "ix_documents_document_id",
        "documents",
        ["document_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_documents_document_id", table_name="documents")
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_column("document_id")
