"""output_citations — the sources every Author Studio output cites (S-6.7.3)

Revision ID: c5ee7a568ef8
Revises: 007c708bb890
Create Date: 2026-10-19

One row per citation in output order, written by every outputter through
`output_citation_service.record_citations`. Additive; existing outputs have
no rows until they are regenerated.
"""
import sqlalchemy as sa
from alembic import op

revision = "c5ee7a568ef8"
down_revision = "007c708bb890"  # re-parented onto S-3.7.1 (merged first)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "output_citations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "output_id",
            sa.String(36),
            sa.ForeignKey("outputs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(255), nullable=False, server_default=""),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("seconds", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.String(36), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=True),
        sa.Column("source_id", sa.String(255), nullable=True),
        sa.Column("resolved_by", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_output_citations_output_position", "output_citations", ["output_id", "position"]
    )


def downgrade() -> None:
    op.drop_index("ix_output_citations_output_position", table_name="output_citations")
    op.drop_table("output_citations")
