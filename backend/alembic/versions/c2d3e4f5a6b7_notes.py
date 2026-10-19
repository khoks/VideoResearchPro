"""notes — the user's own voice in the library (M5 / S-8.5.1)

Revision ID: c2d3e4f5a6b7
Revises: b1a2c3d4e5f8
Create Date: 2026-10-19

One row per note the user writes on a document, job, Q&A exchange, channel
or knowledge artifact. Per tenant from the first row (D-063 applies to the
target at write time). ``deleted_at`` is a soft delete so exports can carry
deletions. Purely additive; no backfill — there is nothing to backfill.
"""
from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5a6b7"
down_revision = "b1a2c3d4e5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("selector_json", sa.Text(), nullable=True),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column(
            "motivation",
            sa.String(16),
            nullable=False,
            server_default="commenting",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_notes_tenant_target",
        "notes",
        ["tenant_id", "target_type", "target_id"],
    )
    op.create_index(
        "ix_notes_tenant_created",
        "notes",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notes_tenant_created", table_name="notes")
    op.drop_index("ix_notes_tenant_target", table_name="notes")
    op.drop_table("notes")
